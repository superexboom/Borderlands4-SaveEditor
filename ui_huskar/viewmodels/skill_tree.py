"""技能树页：在线读取 / 编辑 / 应用角色技能（加点、超限、动作技能、增强与终极、专精）。

布局来自 core/data/skill_layout.json（pipeline ``export-skill-layout``，与游戏技能界面
同构：三棵树，每棵树 = 动作技能 + 主干 3×5 + 下方三个分支 3×3，增强 / 终极嵌在格子里），
数值来自在线 ``skill_snapshot``，编辑逻辑在 core/skill_editor.py。

QML 侧的结构（trees / specs）只在读取或切换语言时重建；格子里的数值通过
``value(graph, index, field)`` 读取，并依赖 ``revision``，所以点一下加点不会重建
整棵树（也不会丢滚动位置）。
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Any

from PyQt6.QtCore import pyqtProperty, pyqtSignal, pyqtSlot

from core import game_text, resource_loader, skill_editor, skill_graphs
from core.item_display_resolver import render_skill_markup

from .base import PageViewModel, register

TREE_COLORS = {"green": "#5cb85c", "blue": "#4a9fe8", "red": "#e05a4f"}
LANG_KEYS = {"en": "EN", "zh": "ZH", "ru": "RU", "de": "DE"}


def _layout() -> dict[str, Any]:
    return skill_editor.layout()


@lru_cache(maxsize=1)
def _skills_csv() -> list[dict[str, str]]:
    try:
        with open(resource_loader.get_class_mods_data_path("Skills.csv"), encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


@lru_cache(maxsize=1)
def _passive_icons() -> dict[tuple[str, str], tuple[str, str]]:
    """(graph, node coordinate) lower case -> (class folder, icon file) from Skills.csv."""
    return {(row.get("graph_name", "").casefold(), row.get("node_name", "").casefold()):
            (row.get("class_name", ""), row["icon_file"]) for row in _skills_csv() if row.get("icon_file")}


def skill_icon_url(icon_file: str) -> str:
    """data/skill_icons/<file> (pipeline build-skill-tree-icons) as a file URL, or ""."""
    if not icon_file:
        return ""
    path = resource_loader.get_resource_path(Path("data") / "skill_icons" / icon_file)
    return path.as_uri() if path and path.exists() else ""


def _class_name(graphs: set[str]) -> str:
    """The character's name (Skills.csv class_name) from any of its skill graphs."""
    for row in _skills_csv():
        if row.get("graph_name", "").casefold() in graphs:
            return row.get("class_name", "")
    return ""


@register("skill_tree", "SkillTreePage.qml")
class SkillTreeViewModel(PageViewModel):
    STRINGS_SECTION = "skill_tree_tab"

    structureChanged = pyqtSignal()
    valuesChanged = pyqtSignal()
    selectionChanged = pyqtSignal()
    busyChanged = pyqtSignal()

    def __init__(self, app, parent=None):
        super().__init__(app, parent)
        self._base: dict | None = None
        self._state: dict | None = None
        self._class: dict | None = None
        self._trees: list[dict[str, Any]] = []
        self._specs: list[dict[str, Any]] = []
        self._revision = 0
        self._busy = False
        self._selected: tuple[str, int] | None = None
        self._cells: dict[tuple[str, int], dict[str, Any]] = {}

    # ------------------------------------------------------------------ #
    # i18n
    # ------------------------------------------------------------------ #
    def _t(self, key: str, **kwargs) -> str:
        value = str(self.strings.get(key, key))
        if kwargs:
            try:
                return value.format(**kwargs)
            except (KeyError, IndexError):
                return value
        return value

    def _text(self, mapping: dict | None) -> str:
        mapping = mapping or {}
        code = LANG_KEYS.get(game_text.text_lang(self.app.language), "EN")
        return str(mapping.get(code) or mapping.get("EN") or "")

    def on_language_changed(self) -> None:
        super().on_language_changed()
        if self._state is not None:
            self._build_structure()
            self.structureChanged.emit()
            self.selectionChanged.emit()
            self.valuesChanged.emit()

    # ------------------------------------------------------------------ #
    # QML 属性
    # ------------------------------------------------------------------ #
    @pyqtProperty(bool, notify=structureChanged)
    def liveMode(self) -> bool:
        return bool(self.app.liveActive)

    @pyqtProperty(bool, notify=structureChanged)
    def loaded(self) -> bool:
        return self._state is not None

    @pyqtProperty(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @pyqtProperty(list, notify=structureChanged)
    def trees(self) -> list[dict[str, Any]]:
        return self._trees

    @pyqtProperty(list, notify=structureChanged)
    def specs(self) -> list[dict[str, Any]]:
        return self._specs

    @pyqtProperty(str, notify=structureChanged)
    def className(self) -> str:
        return str((self._class or {}).get("name") or "")

    @pyqtProperty(str, notify=structureChanged)
    def specSlotsText(self) -> str:
        slots = (_layout().get("specializations") or {}).get("slot_requirements") or []
        return self._t("spec_slots", levels=" / ".join(str(v) for v in slots)) if slots else ""

    @pyqtProperty(int, notify=valuesChanged)
    def revision(self) -> int:
        return self._revision

    @pyqtProperty(bool, notify=valuesChanged)
    def dirty(self) -> bool:
        return self._state is not None and skill_editor.differs(self._state, self._base)

    @pyqtProperty(str, notify=valuesChanged)
    def summary(self) -> str:
        if self._state is None:
            return ""
        usage = skill_editor.pool_usage(self._state)
        spent, total = usage.get(skill_graphs.SKILL_POOLS[0], (0, 0))
        spec_spent, spec_total = usage.get(skill_graphs.SKILL_POOLS[1], (0, 0))
        bonus = sum(node["bonus"] for entry in self._state["graphs"] for node in entry["nodes"])
        return self._t("summary", spent=spent, total=total, left=total - spent,
                       spec_spent=spec_spent, spec_total=spec_total, bonus=bonus)

    @pyqtProperty(str, notify=valuesChanged)
    def poolNote(self) -> str:
        """Pools the apply will raise (the build spends more than the character has)."""
        if self._state is None:
            return ""
        points = skill_editor.apply_payload(self._state).get("points") or {}
        parts = [self._t("pool_" + pool.lower(), total=total) for pool, total in points.items()]
        return self._t("pool_raise", pools="、".join(parts) if game_text.is_chinese(self.app.language)
                       else ", ".join(parts)) if parts else ""

    @pyqtProperty(bool, notify=valuesChanged)
    def overBudget(self) -> bool:
        if self._state is None:
            return False
        return any(spent > total for spent, total in skill_editor.pool_usage(self._state).values())

    @pyqtProperty("QVariantMap", notify=selectionChanged)
    def selected(self) -> dict[str, Any]:
        if self._selected is None:
            return {}
        return dict(self._cells.get(self._selected) or {})

    # ------------------------------------------------------------------ #
    # QML 槽：数值与编辑
    # ------------------------------------------------------------------ #
    @pyqtSlot(str, int, str, result=int)
    def value(self, graph: str, index: int, field: str) -> int:
        node = self._node(graph, index)
        return int(node.get(field) or 0) if node else 0

    @pyqtSlot(str, int)
    def select(self, graph: str, index: int) -> None:
        self._selected = (graph, int(index))
        self.selectionChanged.emit()

    @pyqtSlot(str, int, str, int)
    def setValue(self, graph: str, index: int, field: str, value: int) -> None:
        if self._state is None:
            return
        setter = {"spent": skill_editor.set_spent, "bonus": skill_editor.set_bonus}.get(field)
        if setter is not None and setter(self._state, graph, index, value):
            self._touched()

    @pyqtSlot(str, int, str, int)
    def step(self, graph: str, index: int, field: str, delta: int) -> None:
        self.setValue(graph, index, field, self.value(graph, index, field) + int(delta))

    @pyqtSlot(str, int)
    def toggle(self, graph: str, index: int) -> None:
        node = self._node(graph, index)
        if node and skill_editor.set_active(self._state, graph, index, not node["active"]):
            self._touched()

    @pyqtSlot(int)
    def bonusInvested(self, value: int) -> None:
        if self._state is None:
            return
        if not skill_editor.bonus_invested(self._state, value):
            self.app.toast(self._t("no_invested"), "warning")
        self._touched()

    @pyqtSlot(str)
    def bulk(self, operation: str) -> None:
        if self._state is None:
            return
        if operation == "clear_bonus":
            skill_editor.clear_bonus(self._state)
        elif operation == "max_trees":
            skill_editor.max_trees(self._state)
        elif operation == "clear_points":
            skill_editor.clear_points(self._state)
        elif operation == "revert":
            self._state = skill_editor.clone(self._base)
        else:
            return
        self._touched()

    # ------------------------------------------------------------------ #
    # QML 槽：读取 / 应用（在线）
    # ------------------------------------------------------------------ #
    @pyqtSlot()
    def load(self) -> None:
        if not self.app.liveActive:
            self.app.toast(self._t("live_required"), "warning")
            return
        if self._busy:
            return
        self._set_busy(True)
        self.app.live.start_skill_worker("skill_read", {})

    @pyqtSlot()
    def apply(self) -> None:
        if self._state is None or self._busy or not self.app.liveActive:
            return
        payload = skill_editor.apply_payload(self._state)

        def _apply(accepted: bool) -> None:
            if accepted:
                self._set_busy(True)
                self.app.live.start_skill_worker("skill_write", payload)

        self.app._request_confirm(self._t("confirm_title"), self._t("confirm_msg"), _apply, warning=True)

    def finish_skill(self, operation: str, result: dict | None, error: str | None = None) -> None:
        self._set_busy(False)
        result = result if isinstance(result, dict) else {}
        if operation == "skill_read":
            if error or not result.get("ok"):
                self.app.toast(self._t("read_failed", error=error or str(result.get("error") or "?")), "error")
                return
            self.set_snapshot(result)
            return
        snapshot = result.get("snapshot") if isinstance(result.get("snapshot"), dict) else None
        if snapshot and snapshot.get("ok"):
            self.set_snapshot(snapshot)  # what the game really has now
        if error or not result.get("ok"):
            detail = error or str(result.get("error") or "")
            if result.get("mismatches"):
                detail = detail or self._t("mismatch", count=len(result["mismatches"]))
            self.app.toast(self._t("apply_failed", error=detail or "?"), "error")
        else:
            self.app.toast(self._t("applied"), "success")

    def set_snapshot(self, snapshot: dict) -> None:
        self._base = skill_editor.build_state(snapshot)
        self._state = skill_editor.clone(self._base)
        self._build_structure()
        self._revision += 1
        self.structureChanged.emit()
        self.selectionChanged.emit()
        self.valuesChanged.emit()

    def on_live_changed(self) -> None:
        """Live mode switched: a build read from another session is no longer valid."""
        if not self.app.liveActive:
            self._base = self._state = None
            self._trees, self._specs, self._cells = [], [], {}
            self._selected = None
        self.structureChanged.emit()
        self.valuesChanged.emit()
        self.selectionChanged.emit()

    # ------------------------------------------------------------------ #
    # 结构构建
    # ------------------------------------------------------------------ #
    def _node(self, graph: str, index: int) -> dict | None:
        for entry in (self._state or {}).get("graphs") or []:
            if entry["graph"].casefold() == graph.casefold():
                for node in entry["nodes"]:
                    if node["i"] == index:
                        return node
        return None

    def _touched(self) -> None:
        self._revision += 1
        self.valuesChanged.emit()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.busyChanged.emit()

    def _icon(self, graph: str, coord: str) -> str:
        found = _passive_icons().get((graph.casefold(), coord.casefold()))
        if not found:
            return ""
        try:
            path = resource_loader.get_class_mods_image_path(found[0], found[1])
            return Path(path).as_uri() if path and Path(path).exists() else ""
        except Exception:
            return ""

    def _cell(self, cell: dict, color: str) -> dict[str, Any]:
        if cell.get("kind") == "empty" or self._node(cell.get("graph", ""), int(cell.get("index", -1))) is None:
            return {"kind": "empty"}
        node = self._node(cell["graph"], int(cell["index"]))
        name = self._text(cell.get("name")) or node["name"]
        row = {
            "kind": cell["kind"], "graph": cell["graph"], "i": int(cell["index"]),
            "name": name, "initials": "".join(w[:1] for w in name.split()[:2]).upper(),
            "descHtml": render_skill_markup(self._text(cell.get("desc"))),
            "icon": skill_icon_url(cell.get("icon_file", "")) or (
                self._icon(cell["graph"], cell.get("coord", "")) if cell["kind"] == "passive" else ""),
            "max": node["max"], "color": color, "group": node["group"],
        }
        # the live graph name (case as the game reports it) is what edits address
        for entry in self._state["graphs"]:
            if entry["graph"].casefold() == cell["graph"].casefold():
                row["graph"] = entry["graph"]
        self._cells[(row["graph"], row["i"])] = row
        return row

    def _build_structure(self) -> None:
        self._cells = {}
        self._trees, self._specs, self._class = [], [], None
        if self._state is None:
            return
        live_graphs = {entry["graph"].casefold() for entry in self._state["graphs"]}
        classes = _layout().get("classes") or {}
        layout = next((value for key, value in classes.items() if key in live_graphs), None)
        if layout:
            self._class = {"name": _class_name(live_graphs),
                           "trait": self._text((layout.get("trait") or {}).get("name"))}
            for tree in layout.get("trees") or []:
                color = TREE_COLORS.get(tree.get("color", ""), "#9e9e9e")
                segments = []
                for segment in tree.get("segments") or []:
                    # tier 0 on top, as in the game (trunk above the branches, capstones last)
                    rows = [[self._cell(cell, color) for cell in row] for row in segment.get("rows") or []]
                    segments.append({"graph": segment.get("graph", ""), "rows": rows})
                action = tree.get("action") or {}
                action_row = self._cell({**action, "kind": "action"}, color) if action else {"kind": "empty"}
                self._trees.append({
                    "name": self._text(tree.get("name")), "color": color,
                    "action": action_row,
                    "trunk": segments[0] if segments else {"rows": []},
                    "branches": segments[1:],
                })
        spec = _layout().get("specializations") or {}
        for tree in spec.get("trees") or []:
            row = self._cell({**tree, "kind": "spec"}, "#c9a227")
            if row["kind"] == "empty":
                continue
            row["skills"] = [self._cell({**skill, "kind": "perk"}, "#c9a227") for skill in tree.get("skills") or []]
            self._specs.append(row)
