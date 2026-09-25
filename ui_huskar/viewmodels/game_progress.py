"""Game Progress page view model.

Offline progress editing backed by the NCS-derived catalog
(:mod:`core.progress_catalog`) and pure save helpers (:mod:`core.progress_logic`).
Every write goes through ``SaveGameController.mutate`` so autosave, recovery
and the dirty flag behave like the other editors.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable

from PyQt6.QtCore import Qt, QUrl, pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QGuiApplication

from core import account_progress as account
from core import progress_catalog as cat
from core import progress_logic as logic
from core.unlock_data import CHARACTER_CLASSES
from core.unlock_logic import update_sdu_points

from .base import PageViewModel, register


# Live progress is re-read when the page opens or the editor window regains focus
# (e.g. alt-tab back from the game) and the last read is older than this.
LIVE_STALE_SECONDS = 5.0


@register("game_progress", "GameProgressPage.qml")
class GameProgressViewModel(PageViewModel):
    STRINGS_SECTION = "game_progress_tab"

    dataChanged = pyqtSignal()
    # Per-section signals: picking a category or toggling a map layer only
    # re-evaluates that tab's bindings. refresh() emits all of them.
    liveInfoChanged = pyqtSignal()
    challengesChanged = pyqtSignal()
    collectiblesChanged = pyqtSignal()
    missionsChanged = pyqtSignal()
    mapChanged = pyqtSignal()
    mapFocusChanged = pyqtSignal()
    playerChanged = pyqtSignal()
    accountChanged = pyqtSignal()

    def __init__(self, app, parent=None):
        super().__init__(app, parent)
        self._kind = ""
        self._overview: dict[str, Any] = {}
        self._summary: dict[str, Any] = {}
        self._regions: list[dict[str, Any]] = []
        self._challenge_categories: list[dict[str, Any]] = []
        self._challenge_category = ""
        self._collectible_categories: list[dict[str, Any]] = []
        self._collectible_category = ""
        self._mission_categories: list[dict[str, Any]] = []
        self._mission_category = ""
        self._account_categories: list[dict[str, Any]] = []
        self._account_category = "sdu"
        self._maps: list[dict[str, Any]] = []
        self._current_map = "World_P"
        self._markers_cache: tuple[str, list[dict[str, Any]]] | None = None
        self._layer_overrides: dict[str, bool] = self._load_layer_overrides()
        self._only_missing = False
        self._focus_id = ""
        self._focus_serial = 0
        self._player_serial = 0
        self._last_player_map = ""
        self._teleport_what = ""
        # Built rows by property name; cleared by refresh() and by the section that owns them.
        self._memo: dict[str, Any] = {}
        self._live_seen = False
        self._snapshot_token: Any = None
        self._tab_index = -1
        self._collect_what = ""
        app.liveChanged.connect(self._on_live_changed)
        app.liveChallengesSent.connect(self._on_challenges_sent)
        app.runtimeActionFinished.connect(self._on_runtime_finished)
        app.liveProgressChanged.connect(self._on_live_progress)
        qapp = QGuiApplication.instance()
        if qapp is not None:
            qapp.applicationStateChanged.connect(self._on_application_state)

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _lang(self) -> str:
        return str(self.app.language)

    def _labels(self) -> dict[str, Any]:
        return self.strings.get("labels") or {}

    def _cached(self, key: str, build: Callable[[], Any]) -> Any:
        """QML re-reads a list property on every element access; build each one once."""
        if key not in self._memo:
            self._memo[key] = build()
        return self._memo[key]

    def _drop(self, *keys: str) -> None:
        for key in keys:
            self._memo.pop(key, None)

    def _emit_all(self) -> None:
        for signal in (self.dataChanged, self.liveInfoChanged, self.challengesChanged, self.collectiblesChanged,
                       self.missionsChanged, self.mapChanged, self.mapFocusChanged, self.playerChanged,
                       self.accountChanged):
            signal.emit()

    def _page_shown(self) -> bool:
        return self.app.pageKey == self.PAGE_KEY

    def on_language_changed(self) -> None:
        super().on_language_changed()
        if self._page_shown():  # rows carry localized titles
            self._stale = False
            self.refresh()

    def _on_live_changed(self) -> None:
        # Fires on every live state/busy change: only the player marker and map follow it.
        # 玩家换了地图（含首次读到位置）时，地图页签跟到玩家所在地图；之后仍可自由浏览别的图
        player = logic.live_player_marker(self._live_position(), self._current_map)
        map_changed = False
        if self.app.liveActive and player["available"] and player["map"] != self._last_player_map:
            self._last_player_map = player["map"]
            world = self._artwork_map(player["map"])
            if world and world != self._current_map:
                self._current_map = world
                self._markers_cache = None
                self._drop("mapLayers", "mapMarkers")
                map_changed = True
        elif not self.app.liveActive:
            self._last_player_map = ""
        if self.app.liveActive != self._live_seen:
            self._live_seen = self.app.liveActive
            self.dataChanged.emit()
        if map_changed:
            self.mapChanged.emit()
        self.playerChanged.emit()

    def _editable(self) -> bool:
        return isinstance(self.controller.yaml_obj, dict) and not self.app.liveActive

    def _data(self) -> dict[str, Any] | None:
        """Progress source: the save, or in live mode the snapshot read from the game."""
        if self.app.liveActive:
            snapshot = self.app.live_progress()[0]
            return snapshot if isinstance(snapshot, dict) else None
        data = self.controller.yaml_obj
        return data if isinstance(data, dict) else None

    def _progress_ready(self) -> bool:
        return self._kind == "character" or (self._kind == "live" and self._data() is not None)

    def _on_live_progress(self) -> None:
        snapshot, meta, _loading, _error = self.app.live_progress()
        token = (id(snapshot), meta.get("read_at")) if snapshot is not None else None
        changed = token != self._snapshot_token
        self._snapshot_token = token
        if changed and (self.app.liveActive or self._kind == "live"):
            self.refresh()  # a hidden page has no QML bound, so this is only the Python rebuild
            return
        self.liveInfoChanged.emit()

    def on_activated(self) -> None:
        super().on_activated()
        # Live: read the game's progress when the page opens (never on a timer).
        self._refresh_live_if_stale()

    def _on_application_state(self, state) -> None:
        # Coming back from the game (alt-tab) re-reads once while this page is shown.
        if state == Qt.ApplicationState.ApplicationActive and self.app.pageKey == "game_progress":
            self._refresh_live_if_stale()

    def _refresh_live_if_stale(self) -> None:
        if not self.app.liveActive:
            return
        snapshot, meta, loading, _error = self.app.live_progress()
        if not loading and (snapshot is None or time.time() - float(meta.get("read_at") or 0) > LIVE_STALE_SECONDS):
            self.app.fetch_live_progress()

    def _write(self, change: Callable[[dict[str, Any]], Any], what: str) -> bool:
        if not self._editable():
            return False
        self.controller.mutate(change)
        # Other pages cache values from the save (YAML tree, character fields).
        for key, vm in self.app._vms.items():
            if vm is not self:
                vm.mark_stale()
        toast = (self.strings.get("toasts") or {}).get("saved", "Updated: {what}")
        self.app.set_status(toast.format(what=what))
        self.refresh()
        return True

    # ------------------------------------------------------------------ #
    # state
    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        data = self.controller.yaml_obj
        self._kind = logic.save_kind(data) if isinstance(data, dict) else ""
        if self.app.liveActive and isinstance(data, dict):
            # live：背包快照里没有进度；进度来自游戏读回的快照（只读），读到之前只提供地图
            self._kind = "live"
        source = self._data()
        if self._progress_ready() and source is not None:
            self._overview = logic.read_overview(source) if self._kind == "character" else {}
            self._summary = logic.completion_summary(source) if cat.available() else {}
            self._regions = logic.region_kills(source, self._lang())
            self._challenge_categories = self._build_challenge_categories(source)
            self._collectible_categories = logic.collectible_categories(
                source, self._lang(), self.strings.get("collectible_names") or {})
            self._maps = logic.map_list(source, self._lang(), self.strings.get("map_names") or {})
            self._mission_categories = self._build_mission_categories(source)
        else:
            self._overview, self._summary, self._regions = {}, {}, []
            self._challenge_categories, self._collectible_categories = [], []
            self._mission_categories = []
            self._maps = (logic.map_list({}, self._lang(), self.strings.get("map_names") or {}, track=False)
                          if self._kind == "live" else [])
        self._account_categories = (self._build_account_categories(data)
                                    if self._kind == "profile" and isinstance(data, dict) else [])
        self._markers_cache = None
        self._memo.clear()
        self._emit_all()

    @pyqtProperty(int, constant=True)
    def tabIndex(self) -> int:
        """Last tab shown, restored when the page is opened again (-1: none yet)."""
        return self._tab_index

    @pyqtSlot(int)
    def setTabIndex(self, index: int) -> None:
        self._tab_index = int(index)

    @pyqtProperty(bool, notify=dataChanged)
    def saveLoaded(self) -> bool:
        return self.app.saveLoaded

    @pyqtProperty(bool, notify=dataChanged)
    def liveMode(self) -> bool:
        return self.app.liveActive

    @pyqtProperty(bool, notify=dataChanged)
    def editable(self) -> bool:
        return self._editable()

    @pyqtProperty(bool, notify=dataChanged)
    def liveCollect(self) -> bool:
        """Live: collectibles can be credited in the game (the mod exposes the challenge increment)."""
        if not self.app.liveActive or self._data() is None:
            return False
        return "progress_increment_challenges" in (self.app.live_progress()[1].get("actions") or [])

    @pyqtProperty(str, notify=dataChanged)
    def saveKind(self) -> str:
        return self._kind

    @pyqtProperty(bool, notify=dataChanged)
    def progressAvailable(self) -> bool:
        """Progress views have data: a character save, or a live read of the game."""
        return self._progress_ready()

    @pyqtProperty(bool, notify=liveInfoChanged)
    def liveProgressLoading(self) -> bool:
        return self.app.live_progress()[2]

    @pyqtProperty(str, notify=liveInfoChanged)
    def liveProgressInfo(self) -> str:
        snapshot, meta, loading, error = self.app.live_progress()
        labels = self._labels()
        if loading:
            return str(labels.get("live_progress_loading", "Reading progress from the game..."))
        if error:
            return str(labels.get("live_progress_error", "Reading failed: {error}")).format(error=error)
        if snapshot is None:
            return ""
        return str(labels.get("live_progress_info", "Read at {time} · {count} values · {ms} ms game thread")).format(
            time=time.strftime("%H:%M:%S", time.localtime(float(meta.get("read_at") or 0))),
            count=int(meta.get("set") or 0), ms=meta.get("game_ms", 0))

    @pyqtSlot()
    def refreshLiveProgress(self) -> None:
        if self.app.fetch_live_progress():
            self.liveInfoChanged.emit()

    @pyqtProperty(bool, notify=dataChanged)
    def catalogAvailable(self) -> bool:
        return cat.available()

    @pyqtProperty(str, notify=dataChanged)
    def catalogVersion(self) -> str:
        return str(cat.catalog().get("source_folder") or "")

    # -- overview -------------------------------------------------------- #
    @pyqtProperty(int, notify=dataChanged)
    def playtimeHours(self) -> int:
        return int(self._overview.get("playtime_seconds", 0.0) // 3600)

    @pyqtProperty(int, notify=dataChanged)
    def playtimeMinutes(self) -> int:
        return int(self._overview.get("playtime_seconds", 0.0) % 3600 // 60)

    @pyqtProperty(str, notify=dataChanged)
    def lastPlayedText(self) -> str:
        stamp = int(self._overview.get("last_played") or 0)
        if stamp <= 0:
            return str(self._labels().get("never", "—"))
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(stamp))

    @pyqtProperty(str, notify=dataChanged)
    def cash(self) -> str:
        return str(self._overview.get("cash", ""))

    @pyqtProperty(str, notify=dataChanged)
    def eridium(self) -> str:
        return str(self._overview.get("eridium", ""))

    @pyqtProperty(list, notify=dataChanged)
    def ammoRows(self) -> list[dict[str, Any]]:
        names = self.strings.get("ammo") or {}
        return [{"key": key, "label": str(names.get(key, key)), "value": str(value)}
                for key, value in (self._overview.get("ammo") or {}).items()]

    @pyqtProperty(int, notify=dataChanged)
    def uvhLevel(self) -> int:
        return int(self._overview.get("uvh_level", 0))

    @pyqtProperty(int, notify=dataChanged)
    def uvhHighest(self) -> int:
        return int(self._overview.get("uvh_highest", 0))

    @pyqtProperty(int, notify=dataChanged)
    def uvhMax(self) -> int:
        return int(self._overview.get("uvh_max", logic.max_vault_hunter_level()))

    @pyqtProperty(bool, notify=dataChanged)
    def trueMode(self) -> bool:
        return bool(self._overview.get("true_mode"))

    @pyqtProperty(list, notify=dataChanged)
    def summaryTiles(self) -> list[dict[str, Any]]:
        if not self._summary:
            return []
        labels = self._labels()
        s = self._summary
        return [
            {"key": "main", "label": labels.get("main_story", "Main story"),
             "value": s["main_completed"], "total": s["main_total"]},
            {"key": "collectibles", "label": labels.get("collectibles", "Collectibles"),
             "value": s["collectibles_collected"], "total": s["collectibles_total"]},
            {"key": "challenges", "label": labels.get("challenges", "Challenges"),
             "value": s["challenges_completed"], "total": s["challenges_total"]},
            {"key": "missions", "label": labels.get("missions_completed", "Missions completed"),
             "value": s["missions_completed"], "total": s.get("missions_total", 0)},
        ]

    @pyqtProperty(list, notify=dataChanged)
    def regionKills(self) -> list[dict[str, Any]]:
        return self._regions

    # ------------------------------------------------------------------ #
    # overview writes
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_int(text: Any) -> int | None:
        try:
            return int(str(text).strip().replace(",", ""))
        except (TypeError, ValueError):
            return None

    def _invalid(self) -> None:
        self.app.toast((self.strings.get("toasts") or {}).get("invalid", "Invalid value"), "warning")

    @pyqtSlot("QVariantMap", result=bool)
    def applyOverview(self, values) -> bool:
        """Commit the overview panel in one write; unchanged fields are skipped.

        Keys: hours, minutes, cash, eridium, uvh_level, uvh_highest, ammo.<key>.
        """
        values = dict(values or {})
        parsed: dict[str, int] = {}
        for key, raw in values.items():
            number = self._parse_int(raw)
            if number is None or number < 0:
                self._invalid()
                return False
            parsed[str(key)] = number
        current = self._overview
        seconds = parsed.get("hours", self.playtimeHours) * 3600 + min(parsed.get("minutes", self.playtimeMinutes), 59) * 60
        old_seconds = self.playtimeHours * 3600 + self.playtimeMinutes * 60
        changes: list[Callable[[dict[str, Any]], Any]] = []
        if seconds != old_seconds:
            changes.append(lambda data: logic.set_playtime(data, seconds))
        for key in ("cash", "eridium"):
            if key in parsed and parsed[key] != current.get(key):
                changes.append(lambda data, key=key: logic.set_currency(data, key, parsed[key]))
        for key, value in (current.get("ammo") or {}).items():
            new = parsed.get(f"ammo.{key}")
            if new is not None and new != value:
                changes.append(lambda data, key=key, new=new: logic.set_ammo(data, key, new))
        level = parsed.get("uvh_level", current.get("uvh_level", 0))
        highest = parsed.get("uvh_highest", current.get("uvh_highest", 0))
        if (level, highest) != (current.get("uvh_level", 0), current.get("uvh_highest", 0)):
            changes.append(lambda data: logic.set_vault_hunter_levels(data, level, highest))
        if not changes:
            return False

        def apply_all(data):
            for change in changes:
                change(data)
        return self._write(apply_all, (self.strings.get("tabs") or {}).get("overview", "Overview"))

    @pyqtSlot()
    def fillAmmo(self) -> None:
        from core import unlock_logic
        self._write(unlock_logic.max_ammo, self._labels().get("ammo", "Ammo"))

    @pyqtSlot()
    def maxCurrency(self) -> None:
        def change(data):
            logic.set_currency(data, "cash", logic.INT32_MAX)
            logic.set_currency(data, "eridium", logic.INT32_MAX)
        self._write(change, self._labels().get("currencies", "Currencies"))

    # ------------------------------------------------------------------ #
    # challenges & achievements
    # ------------------------------------------------------------------ #
    def _build_challenge_categories(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        for key, title, members in logic.challenge_category_keys():
            if not members:
                continue
            if key == logic.ACHIEVEMENTS_CATEGORY:
                label = str(self._labels().get("achievements", "Achievements"))
            else:
                label = cat.text(title, self._lang(), key)
                if key.startswith("char_"):
                    # 六个角色分类在游戏里都叫「角色」，补上角色名以便区分
                    who = next((info["name"] for name, info in CHARACTER_CLASSES.items()
                                if name.lower() == key[len("char_"):]), "")
                    label = f"{label} · {who}" if who else label
            done = sum(1 for member in members if logic.challenge_state(data, member)["done"])
            rows.append({"key": key, "title": label, "done": done, "total": len(members)})
        return rows

    @pyqtProperty(list, notify=challengesChanged)
    def challengeCategories(self) -> list[dict[str, Any]]:
        return self._challenge_categories

    @pyqtProperty(str, notify=challengesChanged)
    def challengeCategory(self) -> str:
        return self._challenge_category

    @pyqtSlot(str)
    def setChallengeCategory(self, key: str) -> None:
        self._challenge_category = str(key)
        self._drop("challengeRows")
        self.challengesChanged.emit()

    def _category_members(self) -> list[str]:
        return next((members for key, _title, members in logic.challenge_category_keys()
                     if key == self._challenge_category), [])

    @pyqtProperty(list, notify=challengesChanged)
    def challengeRows(self) -> list[dict[str, Any]]:
        return self._cached("challengeRows", self._build_challenge_rows)

    def _build_challenge_rows(self) -> list[dict[str, Any]]:
        data = self._data()
        if not self._progress_ready() or not isinstance(data, dict):
            return []
        rows = []
        challenges = cat.section("challenges")
        for key in self._category_members():
            row = challenges.get(key) or {}
            state = logic.challenge_state(data, key)
            rows.append({
                "key": key,
                "title": cat.text(row.get("title"), self._lang(), row.get("name", key)),
                "desc": cat.text(row.get("desc"), self._lang()),
                "value": state["value"],
                "goal": state["goal"],
                "tiers": " / ".join(str(goal) for goal in state["goals"]) if len(state["goals"]) > 1 else "",
                "done": state["done"],
                "aggregate": state["aggregate"],
            })
        return rows

    def _challenge_title(self, key: str) -> str:
        row = cat.section("challenges").get(key) or {}
        return cat.text(row.get("title"), self._lang(), key)

    @pyqtSlot(str, str)
    def setChallengeValue(self, key: str, text: str) -> None:
        value = self._parse_int(text)
        if value is None or value < 0:
            self._invalid()
            return
        data = self._data()
        if not isinstance(data, dict) or logic.challenge_state(data, key)["value"] == value:
            return
        self._write(lambda d: logic.set_challenge_value(d, key, value), self._challenge_title(key))

    @pyqtSlot(str, bool)
    def completeChallenge(self, key: str, done: bool) -> None:
        self._write(lambda d: logic.complete_challenge(d, key, done), self._challenge_title(key))

    @pyqtSlot(bool)
    def completeChallengeCategory(self, done: bool) -> None:
        members = self._category_members()
        if not members:
            return
        title = next((row["title"] for row in self._challenge_categories
                      if row["key"] == self._challenge_category), self._challenge_category)

        def change(data):
            seen: set = set()
            for key in members:
                logic.complete_challenge(data, key, done, seen)
        self._write(change, title)

    # ------------------------------------------------------------------ #
    # collectibles
    # ------------------------------------------------------------------ #
    @pyqtProperty(list, notify=collectiblesChanged)
    def collectibleCategories(self) -> list[dict[str, Any]]:
        return self._collectible_categories

    @pyqtProperty(str, notify=collectiblesChanged)
    def collectibleCategory(self) -> str:
        return self._collectible_category

    @pyqtSlot(str)
    def setCollectibleCategory(self, key: str) -> None:
        self._collectible_category = str(key)
        self._drop("collectibleRows")
        self.collectiblesChanged.emit()

    @pyqtProperty(list, notify=collectiblesChanged)
    def collectibleRows(self) -> list[dict[str, Any]]:
        return self._cached("collectibleRows", self._build_collectible_rows)

    def _build_collectible_rows(self) -> list[dict[str, Any]]:
        data = self._data()
        if not self._progress_ready() or not isinstance(data, dict) or not self._collectible_category:
            return []
        lang = self._lang()
        template = str(self._labels().get("location", "{map} ({x}, {y})"))
        rows = logic.collectible_items(data, self._collectible_category, lang,
                                       self.strings.get("collectible_names") or {})
        for row in rows:
            row["location_text"] = (template.format(map=logic.map_title(row["map"], lang),
                                                    x=round(row["x"] / 100), y=round(row["y"] / 100))
                                    if row["has_location"] else str(self._labels().get("no_location", "")))
            row["on_map"] = bool(row["has_location"] and cat.project(row["map"], row["x"], row["y"]))
        return rows

    @pyqtSlot(str, bool)
    def setCollected(self, stat: str, collected: bool) -> None:
        if self.app.liveActive:
            item = next((row for row in self.collectibleRows if row["stat"] == stat), None)
            if collected:
                self._live_collect([stat], item["title"] if item else stat)
            return
        title = next((row["title"] for row in self._collectible_categories
                      if row["key"] == self._collectible_category), stat)
        self._write(lambda data: logic.set_collected(data, stat, collected), title)

    @pyqtSlot(bool)
    def setCategoryCollected(self, collected: bool) -> None:
        data = self._data()
        if not isinstance(data, dict) or not self._collectible_category:
            return
        stats = [row["stat"] for row in logic.collectible_items(data, self._collectible_category, self._lang())]
        title = next((row["title"] for row in self._collectible_categories
                      if row["key"] == self._collectible_category), "")
        if self.app.liveActive:
            pending = logic.live_collect_rows(data, stats)
            if collected and pending and self.liveCollect:
                self._confirm("live_collect_all", lambda: self._live_collect(stats, title),
                              what=title, count=len(pending))
            return

        def change(d):
            for stat in stats:
                logic.set_collected(d, stat, collected)
        self._write(change, title)

    # ------------------------------------------------------------------ #
    # map
    # ------------------------------------------------------------------ #
    _LAYER_SETTINGS_KEY = "progress/map_layers"

    def _load_layer_overrides(self) -> dict[str, bool]:
        try:
            raw = json.loads(str(self.app._settings.value(self._LAYER_SETTINGS_KEY, "{}") or "{}"))
        except (TypeError, ValueError):
            return {}
        return {str(key): bool(value) for key, value in raw.items()} if isinstance(raw, dict) else {}

    def _store_layer_overrides(self) -> None:
        self.app._settings.setValue(self._LAYER_SETTINGS_KEY, json.dumps(self._layer_overrides))

    def _layer_visible(self, type_key: str) -> bool:
        return self._layer_overrides.get(type_key, logic.default_layer_visible(type_key))

    def _all_markers(self) -> list[dict[str, Any]]:
        if self._kind not in ("character", "live"):
            return []
        data = self._data() or {}
        if self._markers_cache is None or self._markers_cache[0] != self._current_map:
            markers = logic.map_markers(data, self._current_map, self._lang(),
                                        self.strings.get("collectible_names") or {},
                                        track=self._progress_ready())
            for marker in markers:
                for field in ("icon", "icon_done"):
                    path = cat.icon_path(marker[field]) if marker[field] else None
                    marker[field + "_url"] = QUrl.fromLocalFile(str(path)).toString() if path else ""
            self._markers_cache = (self._current_map, markers)
        return self._markers_cache[1]

    @pyqtProperty(list, notify=mapChanged)
    def mapList(self) -> list[dict[str, Any]]:
        return self._maps

    @pyqtProperty(str, notify=mapChanged)
    def currentMap(self) -> str:
        return self._current_map

    @pyqtProperty(str, notify=mapChanged)
    def mapImage(self) -> str:
        path = cat.map_image_path(self._current_map)
        return QUrl.fromLocalFile(str(path)).toString() if path else ""

    def _map_moved(self) -> None:
        """Current map, layers or filter changed: rebuild markers and layer rows."""
        self._drop("mapLayers", "mapMarkers")
        self.mapChanged.emit()
        self.mapFocusChanged.emit()
        self.playerChanged.emit()  # teleport availability depends on the map shown

    @pyqtSlot(str)
    def setCurrentMap(self, world: str) -> None:
        if world and world != self._current_map:
            self._current_map = str(world)
            self._focus_id = ""
            self._map_moved()

    @pyqtProperty(list, notify=mapChanged)
    def mapLayers(self) -> list[dict[str, Any]]:
        return self._cached("mapLayers", self._build_map_layers)

    def _build_map_layers(self) -> list[dict[str, Any]]:
        group_names = self.strings.get("map_groups") or {}
        layers: dict[str, dict[str, Any]] = {}
        for marker in self._all_markers():
            layer = layers.setdefault(marker["type"], {
                "key": marker["type"], "title": marker["type_title"], "group": marker["group"],
                "group_title": str(group_names.get(marker["group"], marker["group"])),
                "icon": marker["icon_url"], "count": 0, "done": 0, "tracked": 0,
                "visible": self._layer_visible(marker["type"]),
            })
            layer["count"] += 1
            if marker["done"] is not None:
                layer["tracked"] += 1
                layer["done"] += int(bool(marker["done"]))
        order = {group: index for index, group in enumerate(logic.LAYER_GROUPS)}
        return sorted(layers.values(), key=lambda row: (order.get(row["group"], 99), -row["count"], row["title"]))

    @pyqtProperty(list, notify=mapChanged)
    def mapMarkers(self) -> list[dict[str, Any]]:
        return self._cached("mapMarkers", self._build_map_markers)

    def _build_map_markers(self) -> list[dict[str, Any]]:
        out = []
        for marker in self._all_markers():
            if not self._layer_visible(marker["type"]) and marker["id"] != self._focus_id:
                continue
            if self._only_missing and marker["done"] is not False and marker["id"] != self._focus_id:
                continue
            out.append(marker)
        return out

    @pyqtSlot(str, bool)
    def setLayerVisible(self, type_key: str, visible: bool) -> None:
        self._layer_overrides[str(type_key)] = bool(visible)
        self._store_layer_overrides()
        self._map_moved()

    @pyqtSlot(str, bool)
    def setLayerGroupVisible(self, group: str, visible: bool) -> None:
        for layer in self.mapLayers:
            if layer["group"] == group:
                self._layer_overrides[layer["key"]] = bool(visible)
        self._store_layer_overrides()
        self._map_moved()

    @pyqtProperty(bool, notify=mapChanged)
    def mapOnlyMissing(self) -> bool:
        return self._only_missing

    @pyqtSlot(bool)
    def setMapOnlyMissing(self, value: bool) -> None:
        self._only_missing = bool(value)
        self._map_moved()

    @pyqtProperty(str, notify=mapFocusChanged)
    def focusMarkerId(self) -> str:
        return self._focus_id

    @pyqtProperty(int, notify=mapFocusChanged)
    def focusSerial(self) -> int:
        return self._focus_serial

    def _set_focus(self, marker_id: str) -> None:
        """Select a marker; the marker list only changes when the focus un-hides one."""
        before = [marker["id"] for marker in self.mapMarkers]
        self._focus_id = str(marker_id)
        self._drop("mapMarkers")
        if [marker["id"] for marker in self.mapMarkers] != before:
            self.mapChanged.emit()
        self.mapFocusChanged.emit()

    @pyqtSlot(str, result=bool)
    def focusCollectible(self, stat: str) -> bool:
        """Select the map point of one collectible and ask the view to center on it."""
        challenge = next((key for key, row in cat.section("challenges").items() if row.get("stat") == stat), "")
        location = next(((key, row) for key, row in cat.section("locations").items()
                         if challenge and row.get("challenge") == challenge
                         and cat.project(row.get("map", ""), row["x"], row["y"])), None)
        if not location:
            return False
        if location[1]["map"] != self._current_map:
            self._current_map = location[1]["map"]
            self._markers_cache = None
            self._map_moved()
        self._focus_serial += 1
        self._set_focus(location[0])
        return True

    @pyqtSlot(str)
    def selectMarker(self, marker_id: str) -> None:
        self._set_focus(marker_id)

    @pyqtSlot(str, bool)
    def setMarkerCollected(self, stat: str, collected: bool) -> None:
        if not stat:
            return
        if self.app.liveActive:
            marker = next((row for row in self._all_markers() if row.get("stat") == stat), None)
            if collected:
                self._live_collect([stat], marker["title"] if marker else stat)
            return
        title = next((row["title"] for row in self._maps if row["key"] == self._current_map), self._current_map)
        self._write(lambda data: logic.set_collected(data, stat, collected), title)

    # ------------------------------------------------------------------ #
    # live: collect through the game's own challenge increment
    # ------------------------------------------------------------------ #
    def _live_collect(self, stats: list[str], what: str) -> bool:
        data = self._data()
        rows = logic.live_collect_rows(data, stats) if self.liveCollect and isinstance(data, dict) else []
        if not rows:
            self._drop("collectibleRows")  # the checkbox the user ticked snaps back
            self.collectiblesChanged.emit()
            return False
        if not self.app.live_increment_challenges(rows):
            self.app.toast(str((self.strings.get("toasts") or {}).get(
                "live_busy", "Another live action is still running.")), "warning")
            self._drop("collectibleRows")
            self.collectiblesChanged.emit()
            return False
        self._collect_what = what
        return True

    def _on_challenges_sent(self, results: Any, error: str) -> None:
        if not self._collect_what:
            return
        what, self._collect_what = self._collect_what, ""
        toasts = self.strings.get("toasts") or {}
        if error or not isinstance(results, list):
            self.app.toast(str(toasts.get("live_collect_failed", "Collecting in the game failed: {error}"))
                           .format(error=error or "invalid response"), "error")
            self._drop("collectibleRows")
            self.collectiblesChanged.emit()
            return
        sent = sum(1 for row in results if isinstance(row, dict) and row.get("status") == "sent")
        self.app.toast(str(toasts.get("live_collected", "Collected in the game ({count}): {what}"))
                       .format(count=sent, what=what), "success")

    # ------------------------------------------------------------------ #
    # live: 玩家位置与传送（bl4_live 的 teleport_position 运行时动作）
    # ------------------------------------------------------------------ #
    def _live_position(self) -> dict[str, Any]:
        state = self.app.live_runtime_state()
        position = state.get("position") or state.get("position_state") or {}
        return position if isinstance(position, dict) else {}

    def _artwork_map(self, world: str) -> str:
        """Catalog map key with artwork matching a runtime world name ("" if none)."""
        return next((key for key in (cat.maps().get("maps") or {}) if logic.same_map(key, world)), "")

    @pyqtProperty("QVariantMap", notify=playerChanged)
    def livePlayer(self) -> dict[str, Any]:
        """Player position projected onto the current map (``on_map`` when drawable)."""
        if not self.app.liveActive:
            return {"available": False, "on_map": False}
        return logic.live_player_marker(self._live_position(), self._current_map)

    @pyqtProperty(int, notify=playerChanged)
    def playerFocusSerial(self) -> int:
        return self._player_serial

    @pyqtProperty(bool, notify=playerChanged)
    def teleportReady(self) -> bool:
        """Live, player position known and standing on the map being viewed."""
        return not self._teleport_block_reason()

    @pyqtProperty(str, notify=playerChanged)
    def teleportHint(self) -> str:
        return self._teleport_block_reason()

    def _teleport_block_reason(self) -> str:
        labels = self._labels()
        if not self.app.liveActive:
            return str(labels.get("teleport_need_live", "Live mode required."))
        player = logic.live_player_marker(self._live_position(), self._current_map)
        if not player["available"]:
            return str(labels.get("teleport_no_position", "Player position not read yet."))
        if not logic.same_map(player["map"], self._current_map):
            world = self._artwork_map(player["map"])
            where = logic.map_title(world, self._lang(), self.strings.get("map_names") or {}) if world else player["map"]
            return str(labels.get("teleport_other_map", "The player is on another map ({map}).")).format(map=where)
        return ""

    @pyqtSlot(str, result=bool)
    def teleportToMarker(self, marker_id: str) -> bool:
        """Ask the live mod to move the player to one discovery point of the current map."""
        target = logic.teleport_target(marker_id)
        if not target or self._teleport_block_reason() or not logic.same_map(target["map"], self._current_map):
            return False
        marker = next((row for row in self._all_markers() if row["id"] == marker_id), None)
        self._teleport_what = marker["title"] if marker else marker_id
        self.app.runtime_action("teleport_position", target)
        return True

    @pyqtSlot()
    def refreshLivePosition(self) -> None:
        if self.app.liveActive:
            self.app.runtime_action("state", {"_quiet": True})

    @pyqtSlot(result=bool)
    def focusPlayer(self) -> bool:
        """Switch to the player's map (when it has artwork) and ask the view to center on them."""
        self.refreshLivePosition()
        player = logic.live_player_marker(self._live_position(), self._current_map)
        world = self._artwork_map(player["map"]) if player["available"] else ""
        if not world:
            return False
        if world != self._current_map:
            self._current_map = world
            self._markers_cache = None
            self._map_moved()
        self._player_serial += 1
        self.playerChanged.emit()
        return True

    def _on_runtime_finished(self, action: str, ok: bool, error: str) -> None:
        if action != "teleport_position" or not self._teleport_what:
            return
        toasts = self.strings.get("toasts") or {}
        if ok:
            self.app.toast(str(toasts.get("teleport_ok", "Teleported: {what}")).format(what=self._teleport_what), "success")
        else:
            self.app.toast(str(toasts.get("teleport_failed", "Teleport failed: {error}")).format(error=error), "error")
        self._teleport_what = ""

    # ------------------------------------------------------------------ #
    # missions
    # ------------------------------------------------------------------ #
    def _mission_area_title(self, area: str) -> str:
        names = self.strings.get("mission_areas") or {}
        if area in ("", "extra"):
            return str(names.get(area or "base", area or "Base game"))
        return logic.area_title(area, self._lang())

    def _build_mission_categories(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        kinds = self.strings.get("mission_kinds") or {}
        return [dict(row, title=str(kinds.get(row["kind"], row["kind"])), area=self._mission_area_title(row["area_key"]))
                for row in logic.mission_categories(data, self._lang())]

    @pyqtProperty(list, notify=missionsChanged)
    def missionCategories(self) -> list[dict[str, Any]]:
        return self._mission_categories

    @pyqtProperty(str, notify=missionsChanged)
    def missionCategory(self) -> str:
        return self._mission_category

    @pyqtSlot(str)
    def setMissionCategory(self, key: str) -> None:
        self._mission_category = str(key)
        self._drop("missionRows")
        self.missionsChanged.emit()

    def _mission_title(self, key: str) -> str:
        row = cat.section("missions").get(key) or {}
        return logic.game_text(cat.text(row.get("title"), self._lang(), key))

    def _pending_prerequisites(self, data: dict[str, Any], key: str) -> list[str]:
        return [item for item in logic.main_prerequisites(key) if logic.mission_state(data, item) != "done"]

    @pyqtProperty(list, notify=missionsChanged)
    def missionRows(self) -> list[dict[str, Any]]:
        return self._cached("missionRows", self._build_mission_rows)

    def _build_mission_rows(self) -> list[dict[str, Any]]:
        data = self._data()
        if not self._progress_ready() or not isinstance(data, dict) or not self._mission_category:
            return []
        lang = self._lang()
        other = str(self._labels().get("region_other", "Other"))
        index = logic._mission_index()
        rows = []
        for key in logic.missions_in_category(self._mission_category):
            row = cat.section("missions").get(key) or {}
            main = index[key]["kind"] == "main"
            state = logic.mission_state(data, key)
            objectives = logic.mission_objectives(data, key, lang) if state == "active" else []
            region = str(row.get("region") or "")
            rows.append({
                "key": key,
                "title": self._mission_title(key),
                "desc": logic.game_text(cat.text(row.get("desc"), lang)),
                "state": state,
                "objectives": objectives,
                "objectives_done": sum(1 for item in objectives if item["state"] in ("done", "skipped")),
                # Main missions keep story order; the rest are grouped by region.
                "group": "" if main else (cat.region_title(region, lang) if region else other),
                "template": logic.mission_template(key) is not None,
                "main": main,
                "prerequisites": len(self._pending_prerequisites(data, key)) if main and state != "done" else 0,
                "can_reset": not main and state != "none",
            })
        if rows and not rows[0]["main"]:
            rows.sort(key=lambda item: (item["group"] == other, item["group"]))
        return rows

    def _confirm(self, key: str, callback: Callable[[], None], warning: bool = False, **values: Any) -> None:
        texts = (self.strings.get("confirm") or {})
        title = str(texts.get(key + "_title", ""))
        text = str(texts.get(key + "_text", "")).format(**values)
        self.app._request_confirm(title, text, lambda accepted: accepted and callback(), warning)

    def _complete_missions(self, data: dict[str, Any], keys: list[str]) -> int:
        changed = sum(logic.complete_mission(data, key) for key in keys)
        if changed and any(logic._mission_index()[key]["kind"] == "activity" for key in keys):
            update_sdu_points(data)  # activities feed the SDU token pool, like "complete all activities"
        return changed

    @pyqtSlot(str)
    def completeMission(self, key: str) -> None:
        data = self._data()
        if not self._editable() or key not in logic._mission_index():
            return
        title = self._mission_title(key)
        pending = self._pending_prerequisites(data, key)
        if pending:
            self._confirm("complete_through",
                          lambda: self._write(lambda d: self._complete_missions(d, pending + [key]), title),
                          what=title, count=len(pending))
            return
        self._write(lambda d: self._complete_missions(d, [key]), title)

    @pyqtSlot(str)
    def resetMission(self, key: str) -> None:
        if not self._editable() or key not in logic._mission_index():
            return
        title = self._mission_title(key)
        self._confirm("reset_mission", lambda: self._write(lambda d: logic.reset_mission(d, key), title),
                      warning=True, what=title)

    def _category_title(self) -> str:
        row = next((item for item in self._mission_categories if item["key"] == self._mission_category), None)
        return f"{row['area']} · {row['title']}" if row else self._mission_category

    @pyqtSlot()
    def completeMissionCategory(self) -> None:
        data = self._data()
        if not self._editable() or not self._mission_category:
            return
        keys = [key for key in logic.missions_in_category(self._mission_category)
                if logic.mission_state(data, key) != "done"]
        if not keys:
            return
        what = self._category_title()
        self._confirm("complete_all_missions", lambda: self._write(lambda d: self._complete_missions(d, keys), what),
                      what=what, count=len(keys))

    @pyqtSlot()
    def resetMissionCategory(self) -> None:
        data = self._data()
        if not self._editable() or not self._mission_category:
            return
        keys = [key for key in logic.missions_in_category(self._mission_category)
                if logic._mission_index()[key]["kind"] != "main" and logic.mission_state(data, key) != "none"]
        if not keys:
            return
        what = self._category_title()
        self._confirm("reset_all_missions",
                      lambda: self._write(lambda d: sum(logic.reset_mission(d, key) for key in keys), what),
                      warning=True, what=what, count=len(keys))

    # ------------------------------------------------------------------ #
    # account progress (profile save)
    # ------------------------------------------------------------------ #
    def _account_ledger_title(self, ledger: str) -> str:
        names = self.strings.get("account_ledgers") or {}
        if names.get(ledger):
            return str(names[ledger])
        if ledger.startswith("sharedprogress_"):
            token = ledger[len("sharedprogress_"):]
            place = (logic.area_title(token, self._lang()) if token in (cat.catalog().get("areas") or {})
                     else cat.region_title(token, self._lang()))
            return str(names.get("shared_progress_format", "{place}")).format(place=place)
        who = account.character_name(ledger)
        return str(names.get("character_format", "{name}")).format(name=who) if who else ledger

    def _build_account_categories(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        groups = self.strings.get("account_groups") or {}
        names = self.strings.get("account_ledgers") or {}
        sdu = account.sdu_rows(data, self._lang())
        powers = account.vault_power_rows(data)
        rows = [
            {"key": "sdu", "title": str(names.get("sdu", "SDU")), "area": str(groups.get("upgrades", "")),
             "done": sum(row["level"] for row in sdu), "total": sum(row["max"] for row in sdu)},
            {"key": "vaultpower", "title": str(names.get("vaultpower", "Vault powers")),
             "area": str(groups.get("upgrades", "")),
             "done": sum(1 for row in powers if row["activated"]), "total": len(powers)},
        ]
        for ledger in account.ledger_keys():
            done, total = account.ledger_counts(data, ledger)
            group = "cosmetics" if ledger in account.COSMETIC_LEDGERS else "shared"
            rows.append({"key": "ledger:" + ledger, "title": self._account_ledger_title(ledger),
                         "area": str(groups.get(group, group)), "done": done, "total": total})
        return rows

    @pyqtProperty(list, notify=accountChanged)
    def accountCategories(self) -> list[dict[str, Any]]:
        return self._account_categories

    @pyqtProperty(str, notify=accountChanged)
    def accountCategory(self) -> str:
        return self._account_category

    @pyqtSlot(str)
    def setAccountCategory(self, key: str) -> None:
        self._account_category = str(key)
        self._drop("accountRows")
        self.accountChanged.emit()

    @pyqtProperty(str, notify=accountChanged)
    def accountView(self) -> str:
        return "ledger" if self._account_category.startswith("ledger:") else self._account_category

    @pyqtProperty("QVariantMap", notify=accountChanged)
    def sduPoints(self) -> dict[str, Any]:
        data = self.controller.yaml_obj
        return account.sdu_points(data) if self._kind == "profile" and isinstance(data, dict) else {}

    @pyqtProperty(list, notify=accountChanged)
    def accountRows(self) -> list[dict[str, Any]]:
        return self._cached("accountRows", self._build_account_rows)

    def _build_account_rows(self) -> list[dict[str, Any]]:
        data = self.controller.yaml_obj
        if self._kind != "profile" or not isinstance(data, dict):
            return []
        if self._account_category == "sdu":
            return account.sdu_rows(data, self._lang())
        if self._account_category == "vaultpower":
            titles = self.strings.get("vault_powers") or {}
            return [dict(row, title=str(titles.get(row["key"], row["alias"]))) for row in account.vault_power_rows(data)]
        ledger = self._account_category.partition(":")[2]
        kinds = self.strings.get("cosmetic_kinds") or {}
        rows = account.ledger_rows(data, ledger, self._lang())
        if ledger in account.COSMETIC_LEDGERS:
            for row in rows:
                row["group"] = str(kinds.get(row["group"], row["group"]))
        return rows

    def _account_write(self, change: Callable[[dict[str, Any]], Any], what: str) -> None:
        def apply(data: dict[str, Any]) -> Any:
            result = change(data)
            # Account-wide activity/collectible unlocks feed the SDU token pool (never lowers it).
            update_sdu_points(data)
            return result
        self._write(apply, what)

    def _account_title(self) -> str:
        row = next((item for item in self._account_categories if item["key"] == self._account_category), None)
        return row["title"] if row else self._account_category

    @pyqtSlot(str, int)
    def setSduLevel(self, key: str, level: int) -> None:
        self._account_write(lambda d: account.set_sdu_level(d, key, level), self._account_title())

    @pyqtSlot(bool)
    def setAllSdu(self, maxed: bool) -> None:
        self._account_write(lambda d: account.set_all_sdu(d, maxed), self._account_title())

    @pyqtSlot(str, bool)
    def setVaultPower(self, alias: str, activated: bool) -> None:
        self._account_write(lambda d: account.set_vault_power(d, alias, activated), self._account_title())

    @pyqtSlot(str, bool)
    def setLedgerEntry(self, entry: str, unlocked: bool) -> None:
        ledger = self._account_category.partition(":")[2]
        if ledger:
            self._account_write(lambda d: account.set_entries(d, ledger, [entry], unlocked), self._account_title())

    @pyqtSlot(bool)
    def setLedgerAll(self, unlocked: bool) -> None:
        ledger = self._account_category.partition(":")[2]
        if ledger:
            self._account_write(lambda d: account.set_ledger(d, ledger, unlocked), self._account_title())
