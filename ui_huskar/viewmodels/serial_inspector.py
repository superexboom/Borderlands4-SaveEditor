"""序列号检视页视图模型：移植 QtSerialInspectorTab 的全部非渲染逻辑。

只读页：解析 Base85 / 解码字符串，展示摘要、双形态序列号、分部件卡片、
生成规则与违规列表、物品卡片（点击放大 / 导出 PNG）。解析复用
core.serial_inspect，卡片数据来自 core.item_card_model，由 QML ItemCard 绘制；
本页绝不写存档。

内置英文回退表对齐主线 _FALLBACK_LOC：i18n 缺键时不会出现空白。
"""

from __future__ import annotations

import json
from html import escape
from typing import Any

from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QGuiApplication

from core import item_card_model, item_display_resolver, resource_loader, serial_inspect

from .base import PageViewModel, register


_FALLBACK_LOC: dict[str, Any] = {
    "labels": {
        "input": "Serial (Base85 or decoded)",
        "summary": "Summary",
        "card": "Item card",
        "parts": "Parts",
        "rules": "Generation rules",
        "empty": "Paste a serial above to inspect it.",
        "no_card": "No card available for this item type.",
        "no_parts": "No parts to show.",
        "zoom_hint": "Click the card to enlarge",
        "item_id": "Item ID",
        "manufacturer": "Manufacturer",
        "type": "Type",
        "level": "Level",
        "seed": "Seed",
        "name": "Name",
        "rarity": "Rarity",
        "name_source": "Name source",
        "base85": "Base85",
        "decoded": "Decoded",
        "components": "Components",
        "roundtrip": "Round-trip",
        "bit_total": "Total bits",
        "bit_padding": "Padding bits",
        "part_total": "Parts",
        "implicit_level_one": "Implicit level 1",
        "provenance": "Source",
        "catalog_empty": "The embedded serial catalog is unavailable or empty.",
    },
    "buttons": {
        "inspect": "Inspect",
        "paste": "Paste",
        "clear": "Clear",
        "copy_json": "Copy JSON",
        "export_json": "Export JSON",
        "save_card": "Save card image",
        "copy": "Copy",
        "use": "Edit this form",
        "catalog": "Internal / NPC / Mission presets",
    },
    "provenance_tags": {
        "official_loadout": "Official loadout",
        "mission": "Mission",
        "npc": "NPC / Cinematic",
        "skill": "Skill actor",
        "ui": "UI preview",
        "historical": "Historical",
        "orphan": "Orphan / Legacy",
    },
    "catalog": {
        "title": "Internal / NPC / Mission presets",
        "warning": "Internal and scene-only data may be rejected, corrected or removed by the game. Inspect before using it.",
        "search": "Filter by name, type, source or context...",
        "name": "Name",
        "type": "Type",
        "context": "Scene / Context",
        "level": "Level",
        "details": "Details",
        "load": "Inspect",
        "copy": "Copy Base85",
        "add": "Add to backpack",
        "close": "Close",
        "no_selection": "Select an entry to see its source and rule data.",
        "no_serial": "Rule-only entry; no serial is embedded.",
        "copy_title": "Copy internal serial?",
        "copy_warning": "This is internal or scene-derived content. It may not be safe as a player item. Copy Base85 anyway?",
        "add_title": "Add internal serial?",
        "add_warning": "This is internal or scene-derived content. The game may remove, correct or reject it. Add it to the backpack anyway?",
        "add_blocked": "This entry is inspect-only and cannot be added to a player backpack.",
        "groups": {
            "official_loadout": "Official starter / loadout",
            "npc_mission": "NPC / mission / cinematic",
            "skill_ui": "Skill actor / UI preview",
            "history": "Historical / orphan",
            "rules_only": "Rule-only compositions",
            "other": "Other embedded data",
        },
    },
    "effect_state": {
        "described": "described",
        "cosmetic": "cosmetic",
        "unmapped": "unmapped payload",
        "unknown": "unknown ref",
    },
    "status": {
        "legal": "Legal",
        "incomplete": "Incomplete",
        "modified": "Modified",
        "conditional": "Conditional",
        "unknown": "Unknown",
        "gold": "Gold foundation",
    },
    "roundtrip": {
        "match": "re-encodes identically",
        "differs": "re-encodes to a different code",
        "failed": "re-encode failed",
    },
    "rules_labels": {
        "not_weapon": "Generation rules apply to firearms only; this item type has no rule tree.",
        "no_rules": "No generation rule data is available for this item type.",
        "no_data": "No generation rule data is available for this weapon.",
        "composition": "Composition",
        "parent": "Parent",
        "availability": "Availability",
        "coverage": "Rule coverage complete",
        "base_tags": "Base tags",
        "tag_limits": "Tag limits",
        "groups": "Part groups",
        "violations": "Issues",
        "catalog_rule": "Embedded read-only rule",
        "preferred_parts": "Preferred parts",
        "yes": "yes",
        "no": "no",
    },
    "rules_columns": ["Group", "Selected", "Legal", "Pool", "State"],
    "rules_state": {
        "ok": "ok",
        "incomplete": "not filled",
        "unreachable": "unreachable",
    },
    # Part categories outside the firearm taxonomy the weapon editor localizes.
    "categories": {
        "passive_points": "Passive Skill",
        "inv_comp": "Item Component",
        "class_mod_body": "Class Mod Body",
        "action_skill_mod": "Action Skill Mod",
        "stat_group1": "Stat Roll 1",
        "stat_group2": "Stat Roll 2",
        "stat_group3": "Stat Roll 3",
        "stat_augment": "Stat Augment",
        "primary_augment": "Primary Augment",
        "secondary_augment": "Secondary Augment",
        "core_augment": "Core Augment",
        "payload": "Payload",
        "payload_augment": "Payload Augment",
        "manufacturer_perk": "Manufacturer Perk",
        "firmware": "Firmware",
        "element": "Element",
        "augment_element_resist": "Elemental Resistance",
        "augment_element_immunity": "Elemental Immunity",
        "augment_element_splat": "Elemental Splat",
        "augment_element_nova": "Elemental Nova",
        "unique": "Unique Part",
        "barrel_licensed": "Licensed Barrel",
    },
}

# Violation codes carry no text of their own; the weapon_rules section
# localizes each one, so those keys are reused like the mainline tab does.
_VIOLATION_FALLBACK = {
    "invalid_serial": "Serial could not be parsed",
    "tag_count_below": "Tagged parts are missing",
    "foreign_root_part_manufacturer": "Cross-manufacturer part",
    "foreign_root_part_type": "Cross-type part",
}

# Categories outside the firearm taxonomy get their own hues; firearm part
# types keep the weapon editor's colours.
_EXTRA_CATEGORY_COLORS = {
    "passive_points": "#7E9BE0",
    "inv_comp": "#B39DDB",
    "class_mod_body": "#9575CD",
    "action_skill_mod": "#7986CB",
    "stat_group1": "#F06292",
    "stat_group2": "#F06292",
    "stat_group3": "#F06292",
    "stat_augment": "#EC7CA8",
    "primary_augment": "#4FC3F7",
    "secondary_augment": "#4DD0E1",
    "core_augment": "#29B6F6",
    "payload": "#FFA726",
    "payload_augment": "#FFB74D",
    "manufacturer_perk": "#FF8A65",
    "firmware": "#29B6F6",
    "element": "#EF9A9A",
    "body_ele": "#EF9A9A",
    "augment_element_resist": "#E57373",
    "augment_element_immunity": "#E57373",
    "augment_element_splat": "#FF8A65",
    "augment_element_nova": "#FF8A65",
    "tediore_acc": "#AED581",
    "magazine_ted_thrown": "#DCE775",
    "barrel_licensed": "#B0BEC5",
    "unique": "#FFD54F",
}
_DEFAULT_CATEGORY_COLOR = "#B0BEC5"

_EFFECT_STATE_COLORS = {
    "unmapped": "#FFB74D",
    "unknown": "#E57373",
}

_RARITY_COLORS = {
    "common": "#c8c8c8",
    "unusual": "#4ade80",
    "uncommon": "#4ade80",
    "rare": "#38bdf8",
    "veryrare": "#a855f7",
    "epic": "#a855f7",
    "legendary": "#fb923c",
    "unique": "#fbbf24",
}

_PROVENANCE_COLORS = {
    "official_loadout": "#4FC3F7",
    "mission": "#66BB6A",
    "npc": "#FFB74D",
    "skill": "#AB47BC",
    "ui": "#26C6DA",
    "historical": "#90A4AE",
    "orphan": "#EF5350",
}

_STATUS_COLORS = {
    "legal": "#4ade80",
    "incomplete": "#FFB74D",
    "modified": "#E57373",
    "conditional": "#38bdf8",
    "unknown": "#B0BEC5",
    "gold": "#fbbf24",
}

_CATALOG_GROUP_ORDER = (
    "official_loadout", "npc_mission", "skill_ui", "history", "rules_only", "other"
)


@register("serial_inspector", "SerialInspectorPage.qml")
class SerialInspectorViewModel(PageViewModel):
    STRINGS_SECTION = "serial_inspector_tab"

    dataChanged = pyqtSignal()
    #: QML 输入框回填请求（粘贴 / 目录载入 / useForm），QML 监听后设置文本
    inputRequested = pyqtSignal(str)

    def __init__(self, app, parent: QObject | None = None):
        super().__init__(app, parent)
        self._report: dict[str, Any] = {}
        self._input = ""
        self._card_model: dict[str, Any] = {}
        # 摘要 / 部件 / 规则 / 来源 / 状态 的 QML 视图数据
        self._summary_error = ""
        self._summary_first: list[dict[str, str]] = []
        self._summary_second: list[dict[str, str]] = []
        self._provenance_tags: list[dict[str, str]] = []
        self._provenance_contexts: list[str] = []
        self._status_text = ""
        self._status_color = ""
        self._parts: list[dict[str, Any]] = []
        self._rules_html = ""
        # 目录浏览器状态
        self._catalog_entries: list[dict[str, Any]] = []
        self._catalog_visible: list[dict[str, Any]] = []
        self._catalog_rows: list[dict[str, Any]] = []
        self._catalog_sel = -1
        self._catalog_detail_html = ""
        self._catalog_can_load = False
        self._catalog_can_copy = False
        self._catalog_can_add = False

    # -- 本地化 ------------------------------------------------------------
    def _merged_loc(self) -> dict[str, Any]:
        """主线行为：i18n 节按 key 与英文回退表合并，缺键永不崩溃。"""
        merged = dict(_FALLBACK_LOC)
        section = self.app.localizer.section(self.STRINGS_SECTION or "")
        merged.update(section)
        for key, value in _FALLBACK_LOC.items():
            if isinstance(value, dict):
                combined = dict(value)
                if isinstance(section.get(key), dict):
                    combined.update(section[key])
                merged[key] = combined
        return merged

    def _tr(self, loc: dict[str, Any], section: str, key: str) -> str:
        value = (loc.get(section) or {}).get(key)
        if isinstance(value, str) and value:
            return value
        return str((_FALLBACK_LOC.get(section) or {}).get(key) or key)

    def _columns(self, loc: dict[str, Any], key: str) -> list[str]:
        value = loc.get(key)
        if isinstance(value, list) and value:
            return [str(entry) for entry in value]
        return list(_FALLBACK_LOC[key])

    def _rule_loc(self) -> dict[str, Any]:
        return self.app.localizer.section("weapon_rules")

    def _taxonomy_loc(self) -> dict[str, Any]:
        section = self.app.localizer.section("weapon_editor_tab")
        taxonomy = (section or {}).get("taxonomy")
        return taxonomy if isinstance(taxonomy, dict) else {}

    def _equipment_legit_loc(self) -> dict[str, Any]:
        return self.app.localizer.section("equipment_legit")

    def _equipment_group_loc(self) -> dict[str, Any]:
        groups = self._equipment_legit_loc().get("groups")
        return groups if isinstance(groups, dict) else {}

    def _grenade_group_loc(self) -> dict[str, Any]:
        groups = (self.app.localizer.section("grenade_tab") or {}).get("groups")
        return groups if isinstance(groups, dict) else {}

    def _shield_misc_loc(self) -> dict[str, Any]:
        misc = (self.app.localizer.section("shield_tab") or {}).get("misc")
        return misc if isinstance(misc, dict) else {}

    @property
    def _lang(self) -> str:
        return self.app.language

    # -- 输入与解析 ---------------------------------------------------------
    @pyqtSlot(str)
    def setInput(self, text: str) -> None:
        """QML 输入框变化时同步文本（不自动解析，对齐主线仅按钮触发）。"""
        self._input = text

    @pyqtSlot()
    def inspect(self) -> None:
        self._run_inspect(self._input)

    @pyqtSlot()
    def paste(self) -> None:
        clipboard = QGuiApplication.clipboard()
        text = clipboard.text().strip() if clipboard else ""
        if not text:
            return
        self.inputRequested.emit(text)
        self._run_inspect(text)

    @pyqtSlot()
    def clear(self) -> None:
        self._report = {}
        self._input = ""
        self._card_model: dict[str, Any] = {}
        self._rebuild()
        self.inputRequested.emit("")

    def _run_inspect(self, text: str) -> None:
        text = (text or "").strip()
        self._input = text
        if not text:
            self.clear()
            return
        # core.serial_inspect 永不抛异常、绝不写存档；首次调用会加载目录与
        # CSV 缓存，耗时几百毫秒，与主线一样在 GUI 线程内联执行。
        self._report = serial_inspect.inspect_serial(text, self._lang)
        self._rebuild()

    @pyqtSlot()
    def refresh(self) -> None:
        self.dataChanged.emit()

    def on_language_changed(self) -> None:
        super().on_language_changed()
        # 主线行为：切换语言后用当前输入重跑，使名称/描述/卡片随语言更新
        if self._input.strip():
            self._report = serial_inspect.inspect_serial(self._input, self._lang)
            self._rebuild()

    # -- 视图数据 -----------------------------------------------------------
    @pyqtProperty(bool, notify=dataChanged)
    def hasReport(self) -> bool:
        return bool(self._report)

    @pyqtProperty(bool, notify=dataChanged)
    def reportOk(self) -> bool:
        return bool(self._report.get("ok"))

    @pyqtProperty(str, notify=dataChanged)
    def base85(self) -> str:
        return str(self._report.get("base85") or "")

    @pyqtProperty(str, notify=dataChanged)
    def decoded(self) -> str:
        return str(self._report.get("decoded_full") or "")

    @pyqtProperty(str, notify=dataChanged)
    def summaryPlaceholder(self) -> str:
        if self._report and not self._report.get("ok"):
            return self._summary_error
        return self._tr(self._merged_loc(), "labels", "empty")

    @pyqtProperty("QVariantList", notify=dataChanged)
    def summaryFirst(self) -> list[dict[str, str]]:
        return self._summary_first

    @pyqtProperty("QVariantList", notify=dataChanged)
    def summarySecond(self) -> list[dict[str, str]]:
        return self._summary_second

    @pyqtProperty("QVariantList", notify=dataChanged)
    def provenanceTags(self) -> list[dict[str, str]]:
        return self._provenance_tags

    @pyqtProperty("QVariantList", notify=dataChanged)
    def provenanceContexts(self) -> list[str]:
        return self._provenance_contexts

    @pyqtProperty(bool, notify=dataChanged)
    def hasProvenance(self) -> bool:
        return bool(self._provenance_tags or self._provenance_contexts)

    @pyqtProperty(str, notify=dataChanged)
    def statusText(self) -> str:
        return self._status_text

    @pyqtProperty(str, notify=dataChanged)
    def statusColor(self) -> str:
        return self._status_color

    @pyqtProperty("QVariantList", notify=dataChanged)
    def parts(self) -> list[dict[str, Any]]:
        return self._parts

    @pyqtProperty(str, notify=dataChanged)
    def rulesHtml(self) -> str:
        return self._rules_html

    @pyqtProperty(bool, notify=dataChanged)
    def hasCard(self) -> bool:
        return bool(self._card_model)

    @pyqtProperty("QVariantMap", notify=dataChanged)
    def cardModel(self) -> dict[str, Any]:
        return self._card_model

    @pyqtProperty(str, notify=dataChanged)
    def cardMessage(self) -> str:
        """没有卡片时展示 no_card 文案；尚未解析时保持空白（对齐主线）。"""
        if self._report.get("ok") and not self._card_model:
            return self._tr(self._merged_loc(), "labels", "no_card")
        return ""

    def _rebuild(self) -> None:
        report = self._report
        self._rebuild_summary()
        self._rebuild_provenance()
        self._rebuild_status()
        self._rebuild_parts()
        self._rebuild_rules()
        self._render_card()
        self.dataChanged.emit()

    # -- 摘要 ---------------------------------------------------------------
    def _shield_type_label(self, subtype: str) -> str:
        return str(
            self._shield_misc_loc().get("shield_type_" + str(subtype).casefold())
            or str(subtype).title()
        )

    def _rebuild_summary(self) -> None:
        report = self._report
        loc = self._merged_loc()
        self._summary_error = ""
        self._summary_first = []
        self._summary_second = []
        if not report:
            return
        if not report.get("ok"):
            self._summary_error = str(report.get("error") or "")
            return

        rt = report.get("roundtrip") or {}
        if not rt.get("ok"):
            rt_text = self._tr(loc, "roundtrip", "failed")
        elif rt.get("matches_input"):
            rt_text = self._tr(loc, "roundtrip", "match")
        else:
            rt_text = self._tr(loc, "roundtrip", "differs")

        counts = report.get("part_counts") or {}
        type_text = "%s / %s" % (report.get("type") or "", report.get("type_en") or "")
        if subtype := str(report.get("equipment_subtype") or ""):
            localized = self._shield_type_label(subtype)
            english = subtype.title()
            type_text += " · %s" % (localized if localized == english else f"{localized} / {english}")
        first = [
            ("name", report.get("display_name")),
            ("rarity", report.get("rarity")),
            ("type", type_text),
            ("manufacturer", "%s / %s" % (report.get("manufacturer") or "", report.get("manufacturer_en") or "")),
            ("level", report.get("level")),
        ]
        second = [
            ("item_id", report.get("item_id")),
            ("seed", report.get("seed")),
            ("part_total", counts.get("total")),
            ("roundtrip", rt_text),
            ("name_source", report.get("display_source")),
        ]
        if report.get("implicit_level_one"):
            second.append(("implicit_level_one", self._tr(loc, "rules_labels", "yes")))
        self._summary_first = [
            {"label": self._tr(loc, "labels", key), "value": "" if value is None else str(value)}
            for key, value in first
        ]
        self._summary_second = [
            {"label": self._tr(loc, "labels", key), "value": "" if value is None else str(value)}
            for key, value in second
        ]

    # -- 来源标签 -----------------------------------------------------------
    def _provenance_tag_text(self, tag: str, loc: dict[str, Any]) -> str:
        value = (loc.get("provenance_tags") or {}).get(tag)
        if isinstance(value, str) and value:
            return value
        return str((_FALLBACK_LOC.get("provenance_tags") or {}).get(tag) or tag)

    def _catalog_localized(self, value: Any) -> str:
        if not isinstance(value, dict):
            return str(value or "")
        zh = self._lang == "zh-CN"
        keys = ("zh", "zh-CN", "en", "en-US") if zh else ("en", "en-US", "zh", "zh-CN")
        return next((str(value.get(key) or "") for key in keys if value.get(key)), "")

    def _rebuild_provenance(self) -> None:
        report = self._report
        loc = self._merged_loc()
        self._provenance_tags = []
        self._provenance_contexts = []
        provenance = (report or {}).get("source_provenance") or {}
        entries = provenance.get("entries") or []
        if not entries:
            return
        tags = provenance.get("tags") or []
        self._provenance_tags = [
            {
                "tag": str(tag),
                "text": self._provenance_tag_text(str(tag), loc),
                "color": _PROVENANCE_COLORS.get(str(tag), "#B0BEC5"),
            }
            for tag in tags
        ]
        contexts: list[str] = []
        for entry in entries:
            text = " · ".join(
                self._catalog_localized(entry.get(key)).strip()
                for key in ("source_kind", "object_name", "context")
                if self._catalog_localized(entry.get(key)).strip()
            )
            if text and text not in contexts:
                contexts.append(text)
        self._provenance_contexts = contexts[:4]

    # -- 状态徽标 -----------------------------------------------------------
    def _rebuild_status(self) -> None:
        report = self._report
        self._status_text = ""
        self._status_color = ""
        status = str((report or {}).get("status") or "")
        if not report.get("ok") or not status:
            return
        loc = self._merged_loc()
        if status == "gold":
            text = str(self._equipment_legit_loc().get("status_gold")
                       or self._tr(loc, "status", "gold"))
        else:
            text = self._tr(loc, "status", status)
        self._status_text = text or status
        self._status_color = _STATUS_COLORS.get(status, "#B0BEC5")

    # -- 部件卡片 -----------------------------------------------------------
    @staticmethod
    def _group_types() -> dict[str, str]:
        # Imported lazily: the weapon editor pulls in pandas and the part catalogs.
        from ui_huskar.viewmodels.weapon_editor import GENERATION_GROUP_TYPES

        return GENERATION_GROUP_TYPES

    @staticmethod
    def _taxonomy_keys() -> dict[str, str]:
        from ui_huskar.viewmodels.weapon_editor import TAXONOMY_KEYS

        return TAXONOMY_KEYS

    @staticmethod
    def _part_type_colors() -> dict[str, str]:
        from ui_huskar.viewmodels.weapon_editor import PART_TYPE_COLORS

        return PART_TYPE_COLORS

    def _taxonomy_text(self, term: str) -> str:
        key = self._taxonomy_keys().get(str(term))
        text = self._taxonomy_loc().get(key or "")
        return str(text) if text else str(term)

    def _group_label(self, group: str) -> str:
        if (
            str(group).casefold() == "body"
            and str(self._report.get("type_en") or "").casefold() == "shield"
        ):
            return str(self._shield_misc_loc().get("base") or "Base")
        part_type = self._group_types().get(str(group).casefold())
        taxonomy_key = self._taxonomy_keys().get(part_type or "")
        text = self._taxonomy_loc().get(taxonomy_key or "")
        if text:
            return str(text)
        return part_type or str(group).replace("_", " ").title()

    def _category_label(self, category: str, loc: dict[str, Any]) -> str:
        if not category:
            return "-"
        key = category.casefold()
        if key == "body" and str(self._report.get("type_en") or "").casefold() == "shield":
            return self._group_label(category)
        if key == "manufacturer_perk":
            return str(self._grenade_group_loc().get("mfg_perks") or "Manufacturer Perk")
        if key == "firmware":
            return str(self._equipment_group_loc().get("firmware") or "Firmware")
        if key in self._equipment_group_loc():
            return str(self._equipment_group_loc()[key])
        own = self._tr(loc, "categories", key)
        if own != key:
            return own
        return self._group_label(category)

    def _category_color(self, category: str) -> str:
        key = category.casefold()
        part_type = self._group_types().get(key)
        colour = self._part_type_colors().get(part_type or "")
        if colour:
            return str(colour)
        return _EXTRA_CATEGORY_COLORS.get(key, _DEFAULT_CATEGORY_COLOR)

    def _rebuild_parts(self) -> None:
        report = self._report
        loc = self._merged_loc()
        self._parts = []
        if not report.get("ok"):
            return
        for index, part in enumerate(report.get("parts") or []):
            category = str(part.get("category") or "")
            display_category = str(part.get("display_category") or category)
            state = str(part.get("effect_state") or "")
            if not part.get("known"):
                state = "unknown"
            rarity = str(part.get("rarity") or "")
            self._parts.append({
                "key": str(part.get("key") or ""),
                "ordinal": index + 1,
                "category": self._category_label(display_category, loc),
                "categoryColor": self._category_color(display_category),
                "name": str(part.get("name") or ""),
                "rarity": self._taxonomy_text(rarity) if rarity else "",
                "rarityColor": _RARITY_COLORS.get(rarity.replace(" ", "").casefold(), ""),
                # "described" 是常态不做角标；只有缺失类状态需要醒目
                "state": self._tr(loc, "effect_state", state) if state in _EFFECT_STATE_COLORS else "",
                "stateColor": _EFFECT_STATE_COLORS.get(state, ""),
                "description": str(part.get("description") or ""),
                "internal": str(part.get("part") or ""),
            })

    # -- 生成规则 -----------------------------------------------------------
    @staticmethod
    def _ordered_groups(generation: dict[str, Any]) -> list[str]:
        groups = generation.get("groups") or {}
        ordered: list[str] = []
        for name in generation.get("part_types") or []:
            name = str(name).casefold()
            if name in groups and name not in ordered:
                ordered.append(name)
        ordered.extend(sorted(set(groups) - set(ordered)))
        return ordered

    def _violation_text(self, violation: dict[str, Any]) -> str:
        code = str(violation.get("code") or "")
        shield_type = str(violation.get("shield_type") or "")
        incompatible = str(violation.get("incompatible_shield_type") or "")
        if shield_type and incompatible:
            template = str(
                self._shield_misc_loc().get("perk_type_mismatch")
                or "Current shield type is {shield_type}; cannot add {incompatible_type} shield augments."
            ).replace("\n", " ")
            text = template.format(
                shield_type=self._shield_type_label(shield_type),
                incompatible_type=self._shield_type_label(incompatible),
            )
            refs = violation.get("parts") or [violation.get("part")]
            refs = [str(ref) for ref in refs if ref]
            return text + (" · " + ", ".join(refs) if refs else "")
        foreign_kind = str(violation.get("foreign_kind") or "")
        lookup_code = code + ("_" + foreign_kind if code == "foreign_root_part" and foreign_kind else "")
        rule_loc = self._rule_loc()
        text = (
            rule_loc.get("violation_" + lookup_code)
            or rule_loc.get("violation_" + code)
            or _VIOLATION_FALLBACK.get(lookup_code)
            or _VIOLATION_FALLBACK.get(code)
            or code
        )
        group = violation.get("group")
        if group:
            text += " · %s (%s)" % (self._group_label(str(group)), group)
        actual = violation.get("actual")
        limit = violation.get("min", violation.get("max"))
        if actual is not None and limit is not None:
            text += " (%s/%s)" % (actual, limit)
        for key in ("parts", "tags"):
            values = violation.get(key)
            if values:
                text += " · %s" % ", ".join(str(entry) for entry in values)
        part = violation.get("part")
        if part:
            text += " · %s" % part
            if foreign_kind:
                own_root = str((self._report.get("generation") or {}).get("root_ref") or "")
                other = item_display_resolver.root_kind_label(
                    str(part).partition(":")[0], self._lang
                )
                own = item_display_resolver.root_kind_label(own_root, self._lang) if own_root else ""
                if other:
                    text += " (%s → %s)" % (own, other) if own else " (%s)" % other
        return str(text)

    def _catalog_rules_html(self, report: dict[str, Any], loc: dict[str, Any]) -> str:
        rules = report.get("catalog_rules") or []
        if not rules:
            return ""
        blocks = [
            "<p style='margin:2px 0 4px 0;color:#FFB74D;font-weight:600;'>%s</p>"
            % escape(self._tr(loc, "rules_labels", "catalog_rule"))
        ]
        for entry in rules:
            composition = entry.get("composition_ref") or entry.get("name") or "-"
            if isinstance(composition, dict):
                composition = self._catalog_localized(composition)
            preferred = entry.get("preferred_parts") or entry.get("parts") or []
            shown = json.dumps(preferred, ensure_ascii=False) if isinstance(preferred, (dict, list)) else str(preferred)
            blocks.append(
                "<p style='margin:2px 0;'><b>%s</b><br><span style='opacity:.75;'>%s:</span> %s</p>"
                % (
                    escape(str(composition)),
                    escape(self._tr(loc, "rules_labels", "preferred_parts")),
                    escape(shown or "-"),
                )
            )
        return "".join(blocks)

    def _rebuild_rules(self) -> None:
        report = self._report
        loc = self._merged_loc()

        def label(key: str) -> str:
            return self._tr(loc, "rules_labels", key)

        self._rules_html = ""
        if not report.get("ok"):
            return

        catalog_html = self._catalog_rules_html(report, loc)

        if report.get("guidance_suppressed") == "gold_skin":
            reason = str(
                self._equipment_legit_loc().get("gold_reason")
                or "Gold Skin is only a legendary-skin foundation; generation guidance is disabled."
            )
            self._rules_html = catalog_html + "<p style='opacity:0.8;'>%s</p>" % escape(reason)
            return

        generation = report.get("generation") or {}
        if not generation:
            self._rules_html = catalog_html or "<p style='opacity:0.75;'>%s</p>" % escape(label("no_rules"))
            return

        yes, no = label("yes"), label("no")
        rows = [
            (label("composition"), generation.get("composition_ref") or "-"),
            (label("parent"), generation.get("parent") or "-"),
            (label("availability"), generation.get("availability") or "-"),
            (label("coverage"), yes if generation.get("coverage_complete") else no),
            (label("base_tags"), ", ".join(str(tag) for tag in generation.get("base_tags") or []) or "-"),
        ]
        tag_rules = generation.get("tag_rules") or []
        if tag_rules:
            rows.append((
                label("tag_limits"),
                "; ".join(
                    "%s ≤ %s" % (", ".join(str(tag) for tag in rule.get("tags") or []), rule.get("max", 1))
                    for rule in tag_rules
                ),
            ))

        html = [
            catalog_html,
            "<table cellspacing='0' cellpadding='2'>",
            "".join(
                "<tr><td style='padding-right:12px;opacity:0.75;'>%s</td><td>%s</td></tr>"
                % (escape(str(name)), escape(str(value)))
                for name, value in rows
            ),
            "</table>",
        ]

        groups = generation.get("groups") or {}
        if groups:
            columns = self._columns(loc, "rules_columns")
            html.append("<p style='margin:8px 0 2px 0;font-weight:bold;'>%s</p>" % escape(label("groups")))
            html.append("<table cellspacing='0' cellpadding='3'><tr>")
            html.extend(
                "<th align='left' style='opacity:0.75;padding-right:14px;'>%s</th>" % escape(name)
                for name in columns
            )
            html.append("</tr>")
            for name in self._ordered_groups(generation):
                data = groups.get(name) or {}
                selected = len(data.get("selected") or [])
                low = data.get("effective_min", data.get("min"))
                high = data.get("effective_max", data.get("max"))
                legal = str(low) if low == high else "%s-%s" % (low, high)
                if not data.get("selected_reachable", True):
                    state, colour = self._tr(loc, "rules_state", "unreachable"), "#E57373"
                elif not data.get("selected_terminal", True):
                    state, colour = self._tr(loc, "rules_state", "incomplete"), "#FFB74D"
                else:
                    state, colour = self._tr(loc, "rules_state", "ok"), ""
                style = " style='color:%s;'" % colour if colour else ""
                html.append(
                    "<tr><td style='padding-right:14px;'>%s"
                    "<span style='opacity:0.45;'> %s</span></td>"
                    "<td align='right' style='padding-right:14px;'>%d</td>"
                    "<td align='right' style='padding-right:14px;'>%s</td>"
                    "<td align='right' style='padding-right:14px;opacity:0.6;'>%d</td><td%s>%s</td></tr>"
                    % (
                        escape(self._group_label(name)),
                        escape(str(name)),
                        selected,
                        escape(legal),
                        len(data.get("allowed") or []),
                        style,
                        escape(state),
                    )
                )
            html.append("</table>")

        violations = report.get("violations") or []
        html.append("<p style='margin:8px 0 2px 0;font-weight:bold;'>%s</p>" % escape(label("violations")))
        if violations:
            violation_texts = list(dict.fromkeys(self._violation_text(item) for item in violations))
            html.append("<ul style='margin:0;'>")
            html.extend("<li>%s</li>" % escape(text) for text in violation_texts)
            html.append("</ul>")
        else:
            html.append(
                "<p style='margin:0;opacity:0.75;'>%s</p>"
                % escape(str(self._rule_loc().get("matches_rules") or "-"))
            )

        for warning in report.get("warnings") or []:
            html.append("<p style='margin:2px 0;color:#E57373;'>%s</p>" % escape(str(warning)))
        self._rules_html = "".join(html)

    # -- 卡片 ---------------------------------------------------------------
    def _card_labels(self) -> dict[str, str]:
        """Card builders expect the items_tab 'columns' block for stat labels."""
        try:
            data = resource_loader.load_json_resource(
                resource_loader.get_ui_localization_file(self._lang)
            )
            columns = ((data or {}).get("items_tab") or {}).get("columns") or {}
            if columns:
                return dict(columns)
        except (KeyError, TypeError, ValueError, OSError):
            pass
        return {"level": "Lv"}

    def _render_card(self) -> None:
        report = self._report
        self._card_model = {}
        if not report.get("ok"):
            return
        item = item_card_model.item_from_report(report)
        level_label = self._card_labels().get("level", "Lv")
        self._card_model = item_card_model.build_card(item, self._lang, level_label) or {}

    # -- 剪贴板 / 导出 ------------------------------------------------------
    @pyqtSlot(str)
    def copyText(self, text: str) -> None:
        if not text:
            return
        clipboard = QGuiApplication.clipboard()
        if clipboard:
            clipboard.setText(text)

    @pyqtSlot(str)
    def copyForm(self, key: str) -> None:
        self.copyText(self.base85 if key == "base85" else self.decoded)

    @pyqtSlot(int)
    def copyPart(self, index: int) -> None:
        """Ctrl+C 复制部件列表选中卡片的标识（内部名，退化 key/名称）。"""
        if not (0 <= index < len(self._parts)):
            return
        part = self._parts[index]
        self.copyText(part["internal"] or part["key"] or part["name"])

    @pyqtSlot(str)
    def useForm(self, key: str) -> None:
        """把某一种形态回填进输入框并重新解析（对齐主线 use 按钮）。"""
        text = self.base85 if key == "base85" else self.decoded
        if not text:
            return
        self.inputRequested.emit(text)
        self._run_inspect(text)

    @pyqtSlot()
    def copyJson(self) -> None:
        if not self._report:
            return
        clipboard = QGuiApplication.clipboard()
        if clipboard:
            clipboard.setText(json.dumps(self._report, ensure_ascii=False, indent=2, default=str))

    @pyqtSlot()
    def exportJson(self) -> None:
        if not self._report:
            return
        from PyQt6.QtWidgets import QFileDialog

        loc = self._merged_loc()
        path, _filter = QFileDialog.getSaveFileName(
            None, self._tr(loc, "buttons", "export_json"), "serial.json", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(self._report, handle, ensure_ascii=False, indent=2, default=str)
        except OSError:
            pass

    @pyqtSlot(result=str)
    def askCardPath(self) -> str:
        """Target file for the QML card export (the page grabs the ItemCard itself)."""
        from PyQt6.QtWidgets import QFileDialog

        path, _filter = QFileDialog.getSaveFileName(
            None, self._tr(self._merged_loc(), "buttons", "save_card"), "card.png", "PNG (*.png)")
        return path or ""

    # -- 内置目录浏览器 -------------------------------------------------------
    @pyqtSlot(result=bool)
    def openCatalog(self) -> bool:
        """加载内嵌目录。返回 False 表示目录为空（QML 不弹窗）。"""
        entries = [dict(entry) for entry in serial_inspect.embedded_serial_preset_entries()]
        if not entries:
            self.app.toast(self._tr(self._merged_loc(), "labels", "catalog_empty"), "info")
            return False
        self._catalog_entries = entries
        self._catalog_sel = -1
        self._apply_catalog_filter("")
        return True

    @pyqtSlot(str)
    def catalogFilter(self, text: str) -> None:
        self._apply_catalog_filter(text)

    def _apply_catalog_filter(self, text: str) -> None:
        needle = str(text or "").strip().casefold()
        groups: dict[str, list[int]] = {key: [] for key in _CATALOG_GROUP_ORDER}
        visible: list[dict[str, Any]] = []
        for index, entry in enumerate(self._catalog_entries):
            haystack = " ".join(str(value) for value in entry.values()).casefold()
            if needle and needle not in haystack:
                continue
            visible.append(entry)
            groups.setdefault(self._catalog_entry_group(entry), []).append(len(visible) - 1)
        rows: list[dict[str, Any]] = []
        loc = self._merged_loc()
        for key in _CATALOG_GROUP_ORDER:
            indexes = groups.get(key) or []
            if not indexes:
                continue
            rows.append({"rowType": "group", "title": self._catalog_group_text(key, loc)})
            for visible_index in indexes:
                entry = visible[visible_index]
                context = entry.get("context") or entry.get("object_name") or entry.get("source_kind") or ""
                name = (entry.get("display_name") or entry.get("name")
                        or entry.get("composition_ref") or entry.get("object_name") or "-")
                rows.append({
                    "rowType": "entry",
                    "entryIndex": visible_index,
                    "name": self._catalog_localized(name),
                    "typeText": self._catalog_localized(entry.get("type")),
                    "context": self._catalog_localized(context),
                    "level": str(entry.get("level") or ""),
                })
        self._catalog_visible = visible
        self._catalog_rows = rows
        self._catalog_sel = -1
        self._catalog_detail_html = ""
        self._catalog_can_load = False
        self._catalog_can_copy = False
        self._catalog_can_add = False
        self.dataChanged.emit()

    def _catalog_group_text(self, key: str, loc: dict[str, Any]) -> str:
        groups = (loc.get("catalog") or {}).get("groups") or {}
        fallback = (_FALLBACK_LOC["catalog"].get("groups") or {})
        return str(groups.get(key) or fallback.get(key) or key)

    def _catalog_entry_group(self, entry: dict[str, Any]) -> str:
        tags = set(serial_inspect.catalog_provenance_tags([entry]))
        group = str(entry.get("_catalog_group") or "")
        warnings = entry.get("warnings") or []
        if isinstance(warnings, str):
            warnings = [warnings]
        if (
            group == "rules_only"
            or any("rules_only" in str(value).casefold() for value in warnings)
            or not self._catalog_serial(entry) and entry.get("preferred_parts")
        ):
            return "rules_only"
        if "official_loadout" in tags:
            return "official_loadout"
        if tags.intersection({"historical", "orphan"}):
            return "history"
        if tags.intersection({"skill", "ui"}):
            return "skill_ui"
        if tags.intersection({"npc", "mission"}):
            return "npc_mission"
        return "other"

    @staticmethod
    def _catalog_serial(entry: dict[str, Any]) -> str:
        return str(entry.get("serial") or entry.get("base85") or "").strip()

    @staticmethod
    def _catalog_hard_blocked(entry: dict[str, Any]) -> bool:
        blob = " ".join(
            str(entry.get(key) or "")
            for key in ("root_ref", "composition_ref", "name", "type", "source_kind", "context")
        ).casefold()
        return "exosoldier_turret" in blob or "turret_weapon_" in blob

    @pyqtProperty("QVariantList", notify=dataChanged)
    def catalogRows(self) -> list[dict[str, Any]]:
        return self._catalog_rows

    @pyqtProperty(str, notify=dataChanged)
    def catalogDetailHtml(self) -> str:
        return self._catalog_detail_html

    @pyqtProperty(bool, notify=dataChanged)
    def catalogCanLoad(self) -> bool:
        return self._catalog_can_load

    @pyqtProperty(bool, notify=dataChanged)
    def catalogCanCopy(self) -> bool:
        return self._catalog_can_copy

    @pyqtProperty(bool, notify=dataChanged)
    def catalogCanAdd(self) -> bool:
        return self._catalog_can_add

    @pyqtSlot(int)
    def catalogSelect(self, visible_index: int) -> None:
        if not 0 <= visible_index < len(self._catalog_visible):
            return
        self._catalog_sel = visible_index
        self._rebuild_catalog_detail()

    def _rebuild_catalog_detail(self) -> None:
        loc = self._merged_loc()

        def text(key: str) -> str:
            return self._tr(loc, "catalog", key)

        entry = self._catalog_visible[self._catalog_sel] if self._catalog_sel >= 0 else None
        has_serial = bool(entry and (self._catalog_serial(entry) or entry.get("decoded")))
        allowed = bool(entry and entry.get("add_allowed") is True and not self._catalog_hard_blocked(entry))
        self._catalog_can_load = has_serial
        self._catalog_can_copy = bool(entry and self._catalog_serial(entry))
        self._catalog_can_add = bool(has_serial and allowed)
        if not entry:
            self._catalog_detail_html = ""
            self.dataChanged.emit()
            return
        tags = serial_inspect.catalog_provenance_tags([entry])
        rows = []
        for key in (
            "display_name", "name", "type", "level", "root_ref", "composition_ref", "source_kind",
            "source_file", "object_name", "field", "context", "provenance",
            "latest_present", "add_allowed", "canonical_refs", "internal_refs", "refs", "parts",
        ):
            value = entry.get(key)
            if value not in (None, "", [], {}):
                rows.append((key, value))
        if entry.get("preferred_parts"):
            rows.append(("preferred_parts", entry.get("preferred_parts")))
        if entry.get("warnings"):
            rows.append(("warnings", entry.get("warnings")))
        tag_html = " ".join(
            "<span style='color:%s;font-weight:600;'>%s</span>"
            % (_PROVENANCE_COLORS.get(tag, "#B0BEC5"), escape(self._provenance_tag_text(tag, loc)))
            for tag in tags
        )
        body = ["<p>%s</p>" % tag_html] if tag_html else []
        body.append("<table cellspacing='0' cellpadding='3'>")
        for key, value in rows:
            shown = (
                self._catalog_localized(value)
                if isinstance(value, dict) and key in {"display_name", "name", "type", "context", "provenance"}
                else json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
            )
            body.append(
                "<tr><td style='opacity:.65;padding-right:12px;'>%s</td><td>%s</td></tr>"
                % (escape(key), escape(shown))
            )
        body.append("</table>")
        if not has_serial:
            body.append("<p style='color:#90A4AE;'>%s</p>" % escape(text("no_serial")))
        elif not allowed:
            body.append("<p style='color:#EF5350;'>%s</p>" % escape(text("add_blocked")))
        self._catalog_detail_html = "".join(body)
        self.dataChanged.emit()

    def _catalog_selected_entry(self) -> dict[str, Any] | None:
        if 0 <= self._catalog_sel < len(self._catalog_visible):
            return self._catalog_visible[self._catalog_sel]
        return None

    @pyqtSlot(int, result=str)
    def catalogLoad(self, visible_index: int) -> str:
        """把目录条目的序列号载入检视器。返回序列号（供 QML 关闭弹窗）。"""
        if not 0 <= visible_index < len(self._catalog_visible):
            return ""
        entry = self._catalog_visible[visible_index]
        value = self._catalog_serial(entry) or str(entry.get("decoded") or "").strip()
        if not value:
            return ""
        self.inputRequested.emit(value)
        self._run_inspect(value)
        return value

    @pyqtSlot(int)
    def catalogCopy(self, visible_index: int) -> None:
        if not 0 <= visible_index < len(self._catalog_visible):
            return
        serial = self._catalog_serial(self._catalog_visible[visible_index])
        if not serial:
            return
        loc = self._merged_loc()

        def _copy(accepted: bool) -> None:
            if accepted:
                clipboard = QGuiApplication.clipboard()
                if clipboard:
                    clipboard.setText(serial)

        self.app._request_confirm(
            self._tr(loc, "catalog", "copy_title"),
            self._tr(loc, "catalog", "copy_warning"),
            _copy,
            warning=True,
        )

    @pyqtSlot(int)
    def catalogAdd(self, visible_index: int) -> None:
        if not 0 <= visible_index < len(self._catalog_visible):
            return
        entry = self._catalog_visible[visible_index]
        loc = self._merged_loc()
        if not entry or entry.get("add_allowed") is not True or self._catalog_hard_blocked(entry):
            self.app.toast(self._tr(loc, "catalog", "add_blocked"), "warning")
            return
        serial = self._catalog_serial(entry) or str(entry.get("decoded") or "").strip()
        if not serial:
            return

        def _add(accepted: bool) -> None:
            if accepted:
                self.app.addSerialToBackpack(serial, "1")

        self.app._request_confirm(
            self._tr(loc, "catalog", "add_title"),
            self._tr(loc, "catalog", "add_warning"),
            _add,
            warning=True,
        )
