"""Game Progress page view model.

Offline progress editing backed by the NCS-derived catalog
(:mod:`core.progress_catalog`) and pure save helpers (:mod:`core.progress_logic`).
Every write goes through ``SaveGameController.mutate`` so autosave, recovery
and the dirty flag behave like the other editors.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from PyQt6.QtCore import pyqtProperty, pyqtSignal, pyqtSlot

from core import progress_catalog as cat
from core import progress_logic as logic

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
        app.liveChanged.connect(self._on_live_changed)

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _lang(self) -> str:
        return str(self.app.language)

    def _labels(self) -> dict[str, Any]:
        return self.strings.get("labels") or {}

    def _on_live_changed(self) -> None:
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
        if self._kind == "character":
            self._overview = logic.read_overview(data)
            self._summary = logic.completion_summary(data) if cat.available() else {}
            self._regions = logic.region_kills(data, self._lang())
        else:
            self._overview, self._summary, self._regions = {}, {}, []
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
