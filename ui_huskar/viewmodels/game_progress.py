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

from PyQt6.QtCore import QUrl, pyqtProperty, pyqtSignal, pyqtSlot

from core import progress_catalog as cat
from core import progress_logic as logic
from core.unlock_data import CHARACTER_CLASSES
from core.unlock_logic import update_sdu_points

from .base import PageViewModel, register


@register("game_progress", "GameProgressPage.qml")
class GameProgressViewModel(PageViewModel):
    STRINGS_SECTION = "game_progress_tab"

    dataChanged = pyqtSignal()

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
        app.liveChanged.connect(self._on_live_changed)
        app.runtimeActionFinished.connect(self._on_runtime_finished)

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _lang(self) -> str:
        return str(self.app.language)

    def _labels(self) -> dict[str, Any]:
        return self.strings.get("labels") or {}

    def _on_live_changed(self) -> None:
        # 玩家换了地图（含首次读到位置）时，地图页签跟到玩家所在地图；之后仍可自由浏览别的图
        player = logic.live_player_marker(self._live_position(), self._current_map)
        if self.app.liveActive and player["available"] and player["map"] != self._last_player_map:
            self._last_player_map = player["map"]
            world = self._artwork_map(player["map"])
            if world and world != self._current_map:
                self._current_map = world
                self._markers_cache = None
        elif not self.app.liveActive:
            self._last_player_map = ""
        self.dataChanged.emit()

    def _editable(self) -> bool:
        return isinstance(self.controller.yaml_obj, dict) and not self.app.liveActive

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
            # live 快照只有背包/仓库，读不到进度：只提供地图（定位与传送）
            self._kind = "live"
        if self._kind == "character":
            self._overview = logic.read_overview(data)
            self._summary = logic.completion_summary(data) if cat.available() else {}
            self._regions = logic.region_kills(data, self._lang())
            self._challenge_categories = self._build_challenge_categories(data)
            self._collectible_categories = logic.collectible_categories(
                data, self._lang(), self.strings.get("collectible_names") or {})
            self._maps = logic.map_list(data, self._lang(), self.strings.get("map_names") or {})
            self._mission_categories = self._build_mission_categories(data)
        else:
            self._overview, self._summary, self._regions = {}, {}, []
            self._challenge_categories, self._collectible_categories = [], []
            self._mission_categories = []
            self._maps = (logic.map_list({}, self._lang(), self.strings.get("map_names") or {}, track=False)
                          if self._kind == "live" else [])
        self._markers_cache = None
        self.dataChanged.emit()

    @pyqtProperty(bool, notify=dataChanged)
    def saveLoaded(self) -> bool:
        return self.app.saveLoaded

    @pyqtProperty(bool, notify=dataChanged)
    def liveMode(self) -> bool:
        return self.app.liveActive

    @pyqtProperty(bool, notify=dataChanged)
    def editable(self) -> bool:
        return self._editable()

    @pyqtProperty(str, notify=dataChanged)
    def saveKind(self) -> str:
        return self._kind

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
             "value": s["missions_completed"], "total": 0},
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

    @pyqtProperty(list, notify=dataChanged)
    def challengeCategories(self) -> list[dict[str, Any]]:
        return self._challenge_categories

    @pyqtProperty(str, notify=dataChanged)
    def challengeCategory(self) -> str:
        return self._challenge_category

    @pyqtSlot(str)
    def setChallengeCategory(self, key: str) -> None:
        self._challenge_category = str(key)
        self.dataChanged.emit()

    def _category_members(self) -> list[str]:
        return next((members for key, _title, members in logic.challenge_category_keys()
                     if key == self._challenge_category), [])

    @pyqtProperty(list, notify=dataChanged)
    def challengeRows(self) -> list[dict[str, Any]]:
        data = self.controller.yaml_obj
        if self._kind != "character" or not isinstance(data, dict):
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
        data = self.controller.yaml_obj
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
    @pyqtProperty(list, notify=dataChanged)
    def collectibleCategories(self) -> list[dict[str, Any]]:
        return self._collectible_categories

    @pyqtProperty(str, notify=dataChanged)
    def collectibleCategory(self) -> str:
        return self._collectible_category

    @pyqtSlot(str)
    def setCollectibleCategory(self, key: str) -> None:
        self._collectible_category = str(key)
        self.dataChanged.emit()

    @pyqtProperty(list, notify=dataChanged)
    def collectibleRows(self) -> list[dict[str, Any]]:
        data = self.controller.yaml_obj
        if self._kind != "character" or not isinstance(data, dict) or not self._collectible_category:
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
        title = next((row["title"] for row in self._collectible_categories
                      if row["key"] == self._collectible_category), stat)
        self._write(lambda data: logic.set_collected(data, stat, collected), title)

    @pyqtSlot(bool)
    def setCategoryCollected(self, collected: bool) -> None:
        data = self.controller.yaml_obj
        if not isinstance(data, dict) or not self._collectible_category:
            return
        stats = [row["stat"] for row in logic.collectible_items(data, self._collectible_category, self._lang())]
        title = next((row["title"] for row in self._collectible_categories
                      if row["key"] == self._collectible_category), "")

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
        data = self.controller.yaml_obj
        if self._kind not in ("character", "live") or not isinstance(data, dict):
            return []
        if self._markers_cache is None or self._markers_cache[0] != self._current_map:
            markers = logic.map_markers(data, self._current_map, self._lang(),
                                        self.strings.get("collectible_names") or {},
                                        track=self._kind == "character")
            for marker in markers:
                for field in ("icon", "icon_done"):
                    path = cat.icon_path(marker[field]) if marker[field] else None
                    marker[field + "_url"] = QUrl.fromLocalFile(str(path)).toString() if path else ""
            self._markers_cache = (self._current_map, markers)
        return self._markers_cache[1]

    @pyqtProperty(list, notify=dataChanged)
    def mapList(self) -> list[dict[str, Any]]:
        return self._maps

    @pyqtProperty(str, notify=dataChanged)
    def currentMap(self) -> str:
        return self._current_map

    @pyqtProperty(str, notify=dataChanged)
    def mapImage(self) -> str:
        path = cat.map_image_path(self._current_map)
        return QUrl.fromLocalFile(str(path)).toString() if path else ""

    @pyqtSlot(str)
    def setCurrentMap(self, world: str) -> None:
        if world and world != self._current_map:
            self._current_map = str(world)
            self._focus_id = ""
            self.dataChanged.emit()

    @pyqtProperty(list, notify=dataChanged)
    def mapLayers(self) -> list[dict[str, Any]]:
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

    @pyqtProperty(list, notify=dataChanged)
    def mapMarkers(self) -> list[dict[str, Any]]:
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
        self.dataChanged.emit()

    @pyqtSlot(str, bool)
    def setLayerGroupVisible(self, group: str, visible: bool) -> None:
        for layer in self.mapLayers:
            if layer["group"] == group:
                self._layer_overrides[layer["key"]] = bool(visible)
        self._store_layer_overrides()
        self.dataChanged.emit()

    @pyqtProperty(bool, notify=dataChanged)
    def mapOnlyMissing(self) -> bool:
        return self._only_missing

    @pyqtSlot(bool)
    def setMapOnlyMissing(self, value: bool) -> None:
        self._only_missing = bool(value)
        self.dataChanged.emit()

    @pyqtProperty(str, notify=dataChanged)
    def focusMarkerId(self) -> str:
        return self._focus_id

    @pyqtProperty(int, notify=dataChanged)
    def focusSerial(self) -> int:
        return self._focus_serial

    @pyqtSlot(str, result=bool)
    def focusCollectible(self, stat: str) -> bool:
        """Select the map point of one collectible and ask the view to center on it."""
        challenge = next((key for key, row in cat.section("challenges").items() if row.get("stat") == stat), "")
        location = next(((key, row) for key, row in cat.section("locations").items()
                         if challenge and row.get("challenge") == challenge
                         and cat.project(row.get("map", ""), row["x"], row["y"])), None)
        if not location:
            return False
        self._current_map = location[1]["map"]
        self._focus_id = location[0]
        self._focus_serial += 1
        self._markers_cache = None
        self.dataChanged.emit()
        return True

    @pyqtSlot(str)
    def selectMarker(self, marker_id: str) -> None:
        self._focus_id = str(marker_id)
        self.dataChanged.emit()

    @pyqtSlot(str, bool)
    def setMarkerCollected(self, stat: str, collected: bool) -> None:
        if stat:
            title = next((row["title"] for row in self._maps if row["key"] == self._current_map), self._current_map)
            self._write(lambda data: logic.set_collected(data, stat, collected), title)

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

    @pyqtProperty("QVariantMap", notify=dataChanged)
    def livePlayer(self) -> dict[str, Any]:
        """Player position projected onto the current map (``on_map`` when drawable)."""
        if not self.app.liveActive:
            return {"available": False, "on_map": False}
        return logic.live_player_marker(self._live_position(), self._current_map)

    @pyqtProperty(int, notify=dataChanged)
    def playerFocusSerial(self) -> int:
        return self._player_serial

    @pyqtProperty(bool, notify=dataChanged)
    def teleportReady(self) -> bool:
        """Live, player position known and standing on the map being viewed."""
        return not self._teleport_block_reason()

    @pyqtProperty(str, notify=dataChanged)
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
        self._player_serial += 1
        self.dataChanged.emit()
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

    @pyqtProperty(list, notify=dataChanged)
    def missionCategories(self) -> list[dict[str, Any]]:
        return self._mission_categories

    @pyqtProperty(str, notify=dataChanged)
    def missionCategory(self) -> str:
        return self._mission_category

    @pyqtSlot(str)
    def setMissionCategory(self, key: str) -> None:
        self._mission_category = str(key)
        self.dataChanged.emit()

    def _mission_title(self, key: str) -> str:
        row = cat.section("missions").get(key) or {}
        return logic.game_text(cat.text(row.get("title"), self._lang(), key))

    def _pending_prerequisites(self, data: dict[str, Any], key: str) -> list[str]:
        return [item for item in logic.main_prerequisites(key) if logic.mission_state(data, item) != "done"]

    @pyqtProperty(list, notify=dataChanged)
    def missionRows(self) -> list[dict[str, Any]]:
        data = self.controller.yaml_obj
        if self._kind != "character" or not isinstance(data, dict) or not self._mission_category:
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
        data = self.controller.yaml_obj
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
        data = self.controller.yaml_obj
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
        data = self.controller.yaml_obj
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
