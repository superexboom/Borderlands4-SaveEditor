"""武器生成器 VM：移植 QtWeaponGeneratorTab 的全部非渲染逻辑。

包含：厂商/类型/等级/种子选择、稀有度与传奇/珠光皮肤、元素芯片单选、
珠光属性/元素、部件多槽下拉（含条件部件）、实时属性预览、自然生成规则
指引（状态徽标 + 组配额 + 候选着色）、幸运 Roll 与批量写背包。
"""

from __future__ import annotations

import random
from typing import Any

import pandas as pd
from PyQt6.QtCore import pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QApplication

from core import b_encoder, item_display_resolver, resource_loader
from core.weapon_generation_logic import sample_composition_parts
from tabs import qt_items_tab

from .base import PageViewModel, register

_FLAG_CODE_ORDER = ("1", "3", "5", "17", "33", "65", "129")
_RARITY_ORDER = ("Common", "Uncommon", "Rare", "Epic", "Legendary", "Pearl")


def _rarity_rank(value: str) -> int:
    value = str(value or "").casefold()
    for index, name in enumerate(_RARITY_ORDER):
        if name.casefold() == value:
            return index
    return 99
_PURE_ELEMENTS = {"Corrosive", "Cryo", "Fire", "Radiation", "Shock"}
_ELEM_KEYWORDS = ["Shock", "Radiation", "Incendiary", "Cryo", "Corrosive"]
_NONE_VALUE = "None"

ATTR_LAYOUT = {
    "Rarity": (0, 0), "Legendary Type": (0, 1), "Pearl Type": (0, 1),
    "Element 1": (1, 0), "Element 2": (2, 0),
}
PART_LAYOUT = {
    "Body": (0, 0), "Body Mechanism": (0, 1),
    "Body Accessory": (1, 0), "Special Element Set": (1, 1),
    "Barrel": (2, 0), "Barrel Accessory": (2, 1),
    "Magazine": (3, 0), "Magazine Accessory": (3, 1),
    "Grip": (4, 0), "Foregrip": (4, 1),
    "Scope": (5, 0), "Scope Accessory": (5, 1),
    "Underbarrel": (6, 0), "Underbarrel Accessory": (6, 1),
    "Manufacturer Part": (7, 0), "Tediore Payload": (7, 1),
    "Tediore Throw Reload": (8, 0), "Borg Magazine Adapter": (8, 1),
    "Stat Modifier": (9, 1),
}
CONDITIONAL_PART_TYPES = {"Tediore Throw Reload", "Borg Magazine Adapter", "Special Element Set"}
_ELEMENT_GROUP_PART_TYPES = {"body_ele": "Special Element Set", "secondary_ele": "", "pearl_elem": ""}
MULTI_SELECT_SLOTS = {
    "Body Accessory": 4, "Barrel Accessory": 4,
    "Manufacturer Part": 4, "Scope Accessory": 4,
    "Underbarrel Accessory": 3,
}
_SPECIAL_PARTS = {"Rarity", "Legendary Type", "Pearl Type",
                  "Element 1", "Element 2", "Pearl Stat", "Pearl Elements"}

# 配件下拉项 legit 上色（对齐主线 _apply_part_rule_colors：官方推荐=紫底白字加粗、
# 合法候选=青底白字加粗、可允许=琥珀底深字）。vendor HusSelect 补丁按
# itemBg/itemColor/itemBold 角色渲染，label 保持纯文本（不再拼 ★/✓/! 标记）。
_KIND_POPUP_STYLE = {
    "preferred": ("#7C3AED", "#F5F3FF", True),
    "eligible": ("#0E7490", "#F0FDFA", True),
    "allowed": ("#F59E0B", "#1C1917", False),
}
# 元素类选项（{1:pid}）在自然生成规则里的分组
_ELEMENT_RULE_GROUPS = (
    ("element1", "body_ele"),
    ("element2", "secondary_ele"),
    ("pearl_stat", "pearl_stat"),
    ("pearl_elem", "pearl_elem"),
)

_SECTION_FALLBACKS = {
    "config": "Weapon Config", "attributes": "Rarity / Elements", "parts": "Weapon Parts",
    "multi": "Multi", "pearl_stat": "Pearl Stat", "pearl_elements": "Pearl Elements",
    "available_only": "Only current options are shown",
    "attribute_hint": "Secondary and Pearl fields appear only when the current build supports them.",
    "stats": "Stats",
    "missing_parts": "Missing: {parts}",
    "missing_parts_format": "{label} {actual}/{limit}",
}


@register("weapon_generator", "WeaponGeneratorPage.qml")
class WeaponGeneratorViewModel(PageViewModel):
    STRINGS_SECTION = "weapon_gen_tab"

    dataChanged = pyqtSignal()
    rollFinished = pyqtSignal(bool)

    def __init__(self, app, parent=None):
        super().__init__(app, parent)
        self.current_lang = str(app.language)
        self._character_level = "50"
        self._mfg_index = 0
        self._wt_index = 0
        self._level = self._character_level
        self._seed = str(random.randint(100, 9999))
        self._flag_index = 0
        self._decoded = ""
        self._b85 = ""
        self._encode_error = False
        self._stats: list[dict[str, str]] = []
        self._rule_badge = {"text": "—", "status": "unknown", "tooltip": ""}
        self._missing_parts: list[dict[str, Any]] = []
        self._part_groups: list[dict[str, Any]] = []
        self._rarity_options: list[dict[str, Any]] = []
        self._rarity_index = 0
        self._special_options: dict[str, list[dict[str, Any]]] = {}
        self._special_index: dict[str, int] = {}
        self._element1_values: list[str] = []
        self._element1_index = 0
        self._element2_values: list[str] = []
        self._element2_index = 0
        self._pearl_stat_values: list[str] = []
        self._pearl_stat_index = 0
        self._pearl_element_values: list[str] = []
        self._pearl_element_index = 0
        self._element_states: dict[str, list[dict[str, str]]] = {}
        self._pearl_visible = False
        self._legendary_visible = False
        self._pearl_type_visible = False
        self._element2_visible = False
        self._roll_results: list[dict[str, Any]] = []
        self._roll_summary = ""
        self._flags = resource_loader.get_flag_labels(self.current_lang)
        self._flag_labels = [self._flags[k] for k in _FLAG_CODE_ORDER if k in self._flags]
        self._flag_index = self._default_flag_index()
        self._load_data(self.current_lang)
        if self.all_weapon_parts_df is not None:
            self._rebuild_part_groups()

    # ------------------------------------------------------------------ #
    # 数据加载（对齐主线 load_data）
    # ------------------------------------------------------------------ #
    def _load_data(self, lang: str) -> None:
        self.current_lang = lang
        self.ui_loc = self.app.localizer.section("weapon_gen_tab")
        self.weapon_rule_loc = self.app.localizer.section("weapon_rules")
        self.legit_loc = self.app.localizer.section("equipment_legit")
        self.stats_loc = (self.app.localizer.section("weapon_editor_tab") or {}).get("stats", {})
        self.weapon_taxonomy = (self.app.localizer.section("weapon_editor_tab") or {}).get("taxonomy", {})
        try:
            suffix = "_EN" if lang in ("en-US", "ru", "ua") else ""

            def get_path(base_name):
                name_with_suffix = base_name.replace(".csv", f"{suffix}.csv")
                path = resource_loader.get_weapon_data_path(name_with_suffix)
                if path and path.exists():
                    return path
                return resource_loader.get_weapon_data_path(base_name)

            self.all_weapon_parts_df = pd.read_csv(get_path("all_weapon_part.csv"))
            self.all_weapon_parts_df["Part ID"] = (
                self.all_weapon_parts_df["Part ID"].astype("Int64").astype(str).replace("<NA>", ""))
            self.elemental_df = pd.read_csv(resource_loader.get_weapon_data_path("elemental.csv"))
            self.elemental_stat_col = "Stat_ZH" if lang == "zh-CN" else "Stat"
            self.weapon_rarity_df = pd.read_csv(get_path("weapon_rarity.csv"))
            self.rarity_desc_col = "Description_ZH" if lang == "zh-CN" else "Description"
            self.item_index = resource_loader.load_item_json("item_name_index.json") or {}
            self.weapon_rules = self.item_index.get("weapon_generation_rules") or {}
            catalog = resource_loader.load_json_resource("core/data/embedded_serial_catalog.json") or {}
            preferred_parts = catalog.get("preferred_parts") if isinstance(catalog, dict) else None
            self.preferred_parts = preferred_parts if isinstance(preferred_parts, dict) else {}
            self.weapon_localization = (
                resource_loader.load_weapon_json("weapon_localization_zh-CN.json") or {}
                if lang == "zh-CN" else {})
            self._flags = resource_loader.get_flag_labels(lang)
            self._flag_labels = [self._flags[k] for k in _FLAG_CODE_ORDER if k in self._flags]
        except Exception as exc:
            self.all_weapon_parts_df = None
            self._load_error = str(exc)

    def on_language_changed(self) -> None:
        super().on_language_changed()
        mfg_idx, wt_idx = self._mfg_index, self._wt_index
        self._load_data(str(self.app.language))
        if self.all_weapon_parts_df is not None:
            self._mfg_index = min(mfg_idx, len(self.mfgOptions) - 1)
            self._wt_index = wt_idx
            self._rebuild_part_groups()

    def refresh(self) -> None:
        try:
            data = self.controller.get_character_data() or {}
            level = str(data.get("角色等级") or "")
        except Exception:
            level = ""
        if level and level != self._character_level:
            self._character_level = level
            self._level = level
        if str(self.app.language) != self.current_lang:
            self.on_language_changed()
            return
        self._generate()

    # ------------------------------------------------------------------ #
    # 本地化工具
    # ------------------------------------------------------------------ #
    def get_localized_string(self, key, default=""):
        if self.ui_loc:
            for section in ("labels", "buttons", "dialogs"):
                if key in self.ui_loc.get(section, {}):
                    return self.ui_loc[section][key]
        return self.weapon_localization.get(str(key), default or str(key))

    def _get_english_key(self, localized_value):
        if not localized_value or not self.weapon_localization:
            return localized_value
        reverse_map = {v: k for k, v in self.weapon_localization.items()}
        return reverse_map.get(localized_value, localized_value)

    def _section_text(self, key):
        return self.ui_loc.get("sections", {}).get(key) or _SECTION_FALLBACKS.get(key, key)

    def _rule_message(self, key, zh, en, **fmt):
        fallback = zh if self.current_lang == "zh-CN" else en
        text = self.weapon_rule_loc.get(key, fallback)
        return text.format(**fmt) if fmt else text

    # ------------------------------------------------------------------ #
    # QML 属性：选择器
    # ------------------------------------------------------------------ #
    @pyqtProperty(bool, notify=dataChanged)
    def dataLoaded(self) -> bool:
        return self.all_weapon_parts_df is not None

    @pyqtProperty(str, notify=dataChanged)
    def loadErrorText(self) -> str:
        return getattr(self, "_load_error", "")

    @pyqtProperty(list, notify=dataChanged)
    def mfgOptions(self) -> list[dict[str, Any]]:
        if self.all_weapon_parts_df is None:
            return []
        return [{"label": self.get_localized_string(m), "value": m}
                for m in sorted(self.all_weapon_parts_df["Manufacturer"].unique())]

    @pyqtProperty(int, notify=dataChanged)
    def mfgIndex(self) -> int:
        return self._mfg_index

    @pyqtProperty(list, notify=dataChanged)
    def weaponTypeOptions(self) -> list[dict[str, Any]]:
        if self.all_weapon_parts_df is None:
            return []
        mfg_en = self._current_mfg_en()
        available = sorted(self.all_weapon_parts_df[
            self.all_weapon_parts_df["Manufacturer"] == mfg_en]["Weapon Type"].unique())
        return [{"label": self.get_localized_string(v), "value": v} for v in available]

    @pyqtProperty(int, notify=dataChanged)
    def weaponTypeIndex(self) -> int:
        return self._wt_index

    @pyqtProperty(str, notify=dataChanged)
    def level(self) -> str:
        return self._level

    @pyqtProperty(str, notify=dataChanged)
    def seed(self) -> str:
        return self._seed

    @pyqtProperty(list, notify=dataChanged)
    def flagOptions(self) -> list[dict[str, Any]]:
        return [{"label": label, "value": label.split(" ", 1)[0]} for label in self._flag_labels]

    @pyqtProperty(int, notify=dataChanged)
    def flagIndex(self) -> int:
        return self._flag_index

    # -- 属性卡片 ---------------------------------------------------------- #
    @pyqtProperty(list, notify=dataChanged)
    def rarityOptions(self) -> list[dict[str, Any]]:
        return self._rarity_options

    @pyqtProperty(int, notify=dataChanged)
    def rarityIndex(self) -> int:
        return self._rarity_index

    @pyqtProperty(list, notify=dataChanged)
    def legendaryTypeOptions(self) -> list[dict[str, Any]]:
        return self._special_options.get("Legendary Type", [])

    @pyqtProperty(int, notify=dataChanged)
    def legendaryTypeIndex(self) -> int:
        return self._special_index.get("Legendary Type", 0)

    @pyqtProperty(list, notify=dataChanged)
    def pearlTypeOptions(self) -> list[dict[str, Any]]:
        return self._special_options.get("Pearl Type", [])

    @pyqtProperty(int, notify=dataChanged)
    def pearlTypeIndex(self) -> int:
        return self._special_index.get("Pearl Type", 0)

    @pyqtProperty(bool, notify=dataChanged)
    def legendaryVisible(self) -> bool:
        return self._legendary_visible

    @pyqtProperty(bool, notify=dataChanged)
    def pearlTypeVisible(self) -> bool:
        return self._pearl_type_visible

    @pyqtProperty(bool, notify=dataChanged)
    def pearlVisible(self) -> bool:
        return self._pearl_visible

    @pyqtProperty(bool, notify=dataChanged)
    def element2Visible(self) -> bool:
        return self._element2_visible

    @pyqtProperty(list, notify=dataChanged)
    def element1Options(self) -> list[dict[str, Any]]:
        return self._element_options_view(self._element1_values, "element1")

    @pyqtProperty(int, notify=dataChanged)
    def element1Index(self) -> int:
        return self._element1_index

    @pyqtProperty(list, notify=dataChanged)
    def element2Options(self) -> list[dict[str, Any]]:
        return self._element_options_view(self._element2_values, "element2")

    @pyqtProperty(int, notify=dataChanged)
    def element2Index(self) -> int:
        return self._element2_index

    @pyqtProperty(list, notify=dataChanged)
    def pearlStatOptions(self) -> list[dict[str, Any]]:
        return self._element_options_view(self._pearl_stat_values, "pearl_stat")

    @pyqtProperty(int, notify=dataChanged)
    def pearlStatIndex(self) -> int:
        return self._pearl_stat_index

    @pyqtProperty(list, notify=dataChanged)
    def pearlElementOptions(self) -> list[dict[str, Any]]:
        return self._element_options_view(self._pearl_element_values, "pearl_elem")

    @pyqtProperty(int, notify=dataChanged)
    def pearlElementIndex(self) -> int:
        return self._pearl_element_index

    # -- 部件 --------------------------------------------------------------- #
    @pyqtProperty(list, notify=dataChanged)
    def partGroups(self) -> list[dict[str, Any]]:
        return self._part_groups

    # -- 输出 --------------------------------------------------------------- #
    @pyqtProperty(str, notify=dataChanged)
    def decodedOutput(self) -> str:
        return self._decoded

    @pyqtProperty(str, notify=dataChanged)
    def base85Output(self) -> str:
        return self._b85

    @pyqtProperty(bool, notify=dataChanged)
    def encodeError(self) -> bool:
        return self._encode_error

    @pyqtProperty(list, notify=dataChanged)
    def statsPreview(self) -> list[dict[str, str]]:
        return self._stats

    @pyqtProperty("QVariantMap", notify=dataChanged)
    def ruleBadge(self) -> dict[str, Any]:
        return self._rule_badge

    @pyqtProperty(list, notify=dataChanged)
    def missingParts(self) -> list[dict[str, Any]]:
        return self._missing_parts

    @pyqtProperty(str, notify=dataChanged)
    def missingPartsText(self) -> str:
        if not self._missing_parts:
            return ""
        fmt = self._section_text("missing_parts_format")
        parts = [fmt.format(label=m["label"], actual=m["actual"], limit=m["limit"])
                 for m in self._missing_parts]
        return self._section_text("missing_parts").format(parts=" · ".join(parts))

    @pyqtProperty("QVariantMap", notify=dataChanged)
    def sectionTexts(self) -> dict[str, str]:
        return {key: self._section_text(key) for key in _SECTION_FALLBACKS}

    # ------------------------------------------------------------------ #
    # QML 槽：选择器
    # ------------------------------------------------------------------ #
    @pyqtSlot(int)
    def setMfgIndex(self, index: int) -> None:
        if not 0 <= index < len(self.mfgOptions):
            return
        self._mfg_index = index
        self._wt_index = 0
        self._rebuild_part_groups()

    @pyqtSlot(int)
    def setWeaponTypeIndex(self, index: int) -> None:
        if not 0 <= index < len(self.weaponTypeOptions):
            return
        self._wt_index = index
        self._rebuild_part_groups()

    @pyqtSlot(str)
    def setLevel(self, text: str) -> None:
        self._level = text
        self._generate()

    @pyqtSlot(str)
    def setSeed(self, text: str) -> None:
        self._seed = text
        self._generate()

    @pyqtSlot()
    def randomizeSeed(self) -> None:
        self._seed = str(random.randint(100, 9999))
        self._generate()

    @pyqtSlot(int)
    def setFlagIndex(self, index: int) -> None:
        if 0 <= index < len(self._flag_labels):
            self._flag_index = index
            self.dataChanged.emit()

    @pyqtSlot(int)
    def setRarityIndex(self, index: int) -> None:
        if not 0 <= index < len(self._rarity_options):
            return
        self._rarity_index = index
        selected = self._rarity_options[index]["value"]
        self._legendary_visible = selected == "Legendary"
        self._pearl_type_visible = selected == "Pearl"
        self._pearl_visible = selected == "Pearl"
        if selected != "Legendary":
            self._special_index["Legendary Type"] = 0
        if selected != "Pearl":
            self._special_index["Pearl Type"] = 0
        self._generate()

    @pyqtSlot(int)
    def setLegendaryTypeIndex(self, index: int) -> None:
        if 0 <= index < len(self.legendaryTypeOptions):
            self._special_index["Legendary Type"] = index
            self._generate()

    @pyqtSlot(int)
    def setPearlTypeIndex(self, index: int) -> None:
        if 0 <= index < len(self.pearlTypeOptions):
            self._special_index["Pearl Type"] = index
            self._generate()

    @pyqtSlot(int)
    def setElement1Index(self, index: int) -> None:
        if not 0 <= index < len(self.element1Options):
            return
        self._element1_index = index
        self._refresh_element2()
        self._generate()

    @pyqtSlot(int)
    def setElement2Index(self, index: int) -> None:
        if not 0 <= index < len(self.element2Options):
            return
        self._element2_index = index
        self._generate()

    @pyqtSlot(int)
    def setPearlStatIndex(self, index: int) -> None:
        if not 0 <= index < len(self.pearlStatOptions):
            return
        self._pearl_stat_index = index
        self._generate()

    @pyqtSlot(int)
    def setPearlElementIndex(self, index: int) -> None:
        if not 0 <= index < len(self.pearlElementOptions):
            return
        self._pearl_element_index = index
        self._generate()

    @pyqtSlot(str, int)
    def setPartSelection(self, combo_key: str, index: int) -> None:
        group = next((g for g in self._part_groups for s in g["slots"] if s["key"] == combo_key), None)
        if group is None:
            return
        slot = next(s for s in group["slots"] if s["key"] == combo_key)
        if not 0 <= index < len(slot["options"]):
            return
        slot["selectedIndex"] = index
        if group["partType"] == "Underbarrel":
            self._refresh_element2()
        self._generate()

    # ------------------------------------------------------------------ #
    # 内部：当前选择
    # ------------------------------------------------------------------ #
    def _current_mfg_en(self) -> str:
        options = self.mfgOptions
        return options[self._mfg_index]["value"] if 0 <= self._mfg_index < len(options) else ""

    def _current_wt_en(self) -> str:
        options = self.weaponTypeOptions
        return options[self._wt_index]["value"] if 0 <= self._wt_index < len(options) else ""

    def _current_m_id(self):
        mfg_en, wt_en = self._current_mfg_en(), self._current_wt_en()
        if not mfg_en or not wt_en:
            return None
        try:
            return self.all_weapon_parts_df.loc[
                (self.all_weapon_parts_df["Manufacturer"] == mfg_en)
                & (self.all_weapon_parts_df["Weapon Type"] == wt_en),
                "Manufacturer & Weapon Type ID",
            ].iloc[0]
        except IndexError:
            return None

    def _default_flag_index(self) -> int:
        target = self._flags.get("3")
        for index, label in enumerate(self._flag_labels):
            if label == target:
                return index
        return 0

    def _flag_value(self) -> str:
        if 0 <= self._flag_index < len(self._flag_labels):
            return self._flag_labels[self._flag_index].split(" ", 1)[0]
        return "3"

    # ------------------------------------------------------------------ #
    # 部件组构建（对齐 _create_part_dropdowns）
    # ------------------------------------------------------------------ #
    def _part_option_label(self, item_id, part_id, row):
        name = item_display_resolver.weapon_part_name(int(item_id), str(part_id), self.current_lang, row)
        return f"{part_id} - {name}" if name else str(part_id)

    def _part_option_text(self, item_id, part_id, row, decoded_str=""):
        return item_display_resolver.format_weapon_part_option(
            int(item_id), str(part_id), decoded_str, self.current_lang, row)

    def _rebuild_part_groups(self) -> None:
        m_id = self._current_m_id()
        self._part_groups = []
        if m_id is None:
            self.dataChanged.emit()
            return

        # 稀有度
        df = self.weapon_rarity_df[self.weapon_rarity_df["Manufacturer & Weapon Type ID"] == m_id]
        available = list(df["Stat"].dropna().unique())
        ordered = [r for r in _RARITY_ORDER if r in available]
        ordered.extend(sorted(set(available) - set(ordered)))
        self._rarity_options = [{"label": self.get_localized_string(_NONE_VALUE), "value": ""}]
        self._rarity_options += [{"label": self.get_localized_string(r), "value": r} for r in ordered]
        self._rarity_index = 0
        self._legendary_visible = False
        self._pearl_type_visible = False
        self._pearl_visible = False

        # 传奇 / 珠光皮肤
        self._special_options = {}
        self._special_index = {"Legendary Type": 0, "Pearl Type": 0}
        for name in ("Legendary Type", "Pearl Type"):
            rarity = name.split()[0]
            special_df = self.weapon_rarity_df[
                (self.weapon_rarity_df["Manufacturer & Weapon Type ID"] == m_id)
                & (self.weapon_rarity_df["Stat"] == rarity)]
            options = [{"label": self.get_localized_string(_NONE_VALUE), "value": None}]
            for _, r in special_df.iterrows():
                description = r[self.rarity_desc_col]
                if pd.notna(description) and description:
                    options.append({"label": f"{r['Part ID']} - {description}", "value": str(r["Part ID"])})
            self._special_options[name] = options

        # 元素 / 珠光
        self._element1_values = self._element1_value_list()
        self._element1_index = 0
        self._element2_values = []
        self._element2_index = 0
        self._element2_visible = False
        self._pearl_stat_values = self._pearl_stat_value_list()
        self._pearl_stat_index = 0
        self._pearl_element_values = self._pearl_element_value_list()
        self._pearl_element_index = 0

        # 部件组
        filtered_df = self.all_weapon_parts_df[self.all_weapon_parts_df["Manufacturer & Weapon Type ID"] == m_id]
        groups = []
        for part_type_en, group_df in filtered_df.groupby("Part Type"):
            if part_type_en not in PART_LAYOUT:
                continue
            num_slots = MULTI_SELECT_SLOTS.get(part_type_en, 1)
            none_label = self.get_localized_string(_NONE_VALUE)
            options = [{"label": none_label, "text": none_label, "value": None,
                        "tooltip": "", "kind": ""}]
            for _, part_row in group_df.iterrows():
                part_id = str(part_row["Part ID"])
                if part_id:
                    label = self._part_option_label(m_id, part_id, part_row)
                    options.append({
                        "label": label,
                        "text": label,
                        "value": part_id,
                        "tooltip": "",
                        "kind": "",
                    })
            slots = [{"key": f"{part_type_en}_{i}", "options": options, "selectedIndex": 0,
                      "detail": ""} for i in range(num_slots)]
            row, col = PART_LAYOUT[part_type_en]
            groups.append({
                "partType": part_type_en,
                "title": self.get_localized_string(part_type_en),
                "badge": "—",
                "badgeTip": "",
                "slots": slots,
                "row": row, "col": col,
                "visible": not (part_type_en in CONDITIONAL_PART_TYPES and group_df.empty),
            })
        groups.sort(key=lambda g: (g["row"], g["col"]))
        self._part_groups = groups
        self._refresh_element2()
        self._generate()

    # ------------------------------------------------------------------ #
    # 元素（对齐元素工具方法）
    # ------------------------------------------------------------------ #
    def _element_options_view(self, values, state_key):
        """元素芯片选项：label 为原始 "pid - 描述" 值，marker/kind 为合法候选状态。"""
        states = self._element_states.get(state_key) or []
        options = [{"label": self.get_localized_string(_NONE_VALUE), "marker": "", "kind": ""}]
        for i, value in enumerate(values):
            state = states[i] if i < len(states) else {}
            options.append({
                "label": value,
                "marker": str(state.get("marker", "")),
                "kind": str(state.get("kind", "")),
            })
        return options

    def _element_value_at(self, values, index):
        """index 为含 None 首项的下标；返回原始 "pid - 描述" 值或 None。"""
        if 0 < index <= len(values):
            return values[index - 1]
        return None

    @staticmethod
    def _element_candidate_state(value, spec):
        """对齐 equipment_base._candidate_state 的 ✓/! 语义（ref 恒为 {1:pid}）。"""
        pid = str(value).split(" - ", 1)[0]
        ref = f"1:{pid}" if pid.isdigit() else ""
        if not ref or not isinstance(spec, dict):
            return {"marker": "", "kind": ""}
        if ref not in set(spec.get("allowed") or []):
            return {"marker": "", "kind": ""}
        selected = set(spec.get("selected") or [])
        if not (int(spec.get("effective_max", spec.get("max", 0))) > 0 or ref in selected):
            return {"marker": "", "kind": ""}
        if ref in selected or ref in set(spec.get("remaining_eligible_refs") or []):
            return {"marker": "✓", "kind": "legal"}
        return {"marker": "!", "kind": "warning"}

    def _refresh_element_states(self, groups, rules_ready) -> None:
        groups = groups if rules_ready else {}
        value_lists = {
            "element1": self._element1_values,
            "element2": self._element2_values,
            "pearl_stat": self._pearl_stat_values,
            "pearl_elem": self._pearl_element_values,
        }
        self._element_states = {
            state_key: [
                self._element_candidate_state(value, groups.get(group_key))
                for value in value_lists[state_key]
            ]
            for state_key, group_key in _ELEMENT_RULE_GROUPS
        }

    def _fmt_elem_value(self, row):
        return f"{row['Part_ID']} - {row[self.elemental_stat_col]}"

    def _fmt_pearl_value(self, row):
        display = str(row[self.elemental_stat_col])
        for sep in (":", "："):
            if sep in display:
                display = display.split(sep, 1)[1].strip()
                break
        display = display.replace(", ", "\n")
        return f"{row['Part_ID']} - {display}"

    def _element1_value_list(self):
        return [self._fmt_elem_value(r) for _, r in self.elemental_df.iterrows()
                if str(r["Stat"]).split(" (", 1)[0] in _PURE_ELEMENTS]

    def _pearl_stat_value_list(self):
        return [self._fmt_pearl_value(r) for _, r in self.elemental_df.iterrows()
                if str(r["Stat"]).startswith("Pearl Stat")]

    def _pearl_element_value_list(self):
        return [self._fmt_pearl_value(r) for _, r in self.elemental_df.iterrows()
                if str(r["Stat"]).startswith("Pearl Elements")]

    def _normal_switch_rows(self):
        return [r for _, r in self.elemental_df.iterrows()
                if str(r["Stat"]).startswith("switch between")]

    def _underbarrel_switch_rows(self):
        return [r for _, r in self.elemental_df.iterrows()
                if str(r["Stat"]).startswith("Maliwan Underbarrel-switch")]

    def _element_name_of_selection(self, value):
        none_val = self.get_localized_string(_NONE_VALUE)
        if not value or value == none_val:
            return None
        pid = value.split(" - ")[0]
        if not pid.isdigit():
            return None
        rows = self.elemental_df[self.elemental_df["Part_ID"] == int(pid)]
        if rows.empty:
            return None
        stat = str(rows.iloc[0]["Stat"]).split(" (", 1)[0]
        return "Incendiary" if stat == "Fire" else stat

    def _switch_first_element(self, stat_en):
        best = None
        best_idx = None
        for kw in _ELEM_KEYWORDS:
            idx = stat_en.find(kw)
            if idx != -1 and (best_idx is None or idx < best_idx):
                best_idx = idx
                best = kw
        return best

    def _underbarrel_has_malswitch(self):
        m_id = self._current_m_id()
        if m_id is None:
            return False
        for group in self._part_groups:
            if group["partType"] != "Underbarrel":
                continue
            for slot in group["slots"]:
                selected = slot["options"][slot["selectedIndex"]]
                pid = selected.get("value")
                if pid is None or not str(pid).isdigit():
                    continue
                rows = self.all_weapon_parts_df[
                    (self.all_weapon_parts_df["Manufacturer & Weapon Type ID"] == m_id)
                    & (self.all_weapon_parts_df["Part Type"] == "Underbarrel")
                    & (self.all_weapon_parts_df["Part ID"] == str(pid))
                ]
                for _, r in rows.iterrows():
                    if "malswitch" in str(r["String"]).lower():
                        return True
        return False

    def _refresh_element2(self) -> None:
        elem1_val = self._element_value_at(self._element1_values, self._element1_index)
        elem_name = self._element_name_of_selection(elem1_val)
        if elem_name is None:
            self._element2_values = []
            self._element2_index = 0
            self._element2_visible = False
            return
        values = []
        for r in self._normal_switch_rows():
            if self._switch_first_element(str(r["Stat"])) == elem_name:
                values.append(self._fmt_elem_value(r))
        if self._underbarrel_has_malswitch():
            for r in self._underbarrel_switch_rows():
                if self._switch_first_element(str(r["Stat"])) == elem_name:
                    values.append(self._fmt_elem_value(r))
        # 保留原选择（若仍合法）
        prev = self._element_value_at(self._element2_values, self._element2_index)
        self._element2_values = values
        self._element2_visible = bool(values)
        self._element2_index = (self._element2_values.index(prev) + 1) if prev in values else 0

    # ------------------------------------------------------------------ #
    # 生成（对齐 generate_weapon）
    # ------------------------------------------------------------------ #
    def _selected_part_refs(self, item_id):
        refs = set()
        for group in self._part_groups:
            for slot in group["slots"]:
                value = slot["options"][slot["selectedIndex"]].get("value")
                if value is not None:
                    refs.add(f"{item_id}:{value}")
        return refs

    def _generate(self) -> None:
        try:
            m_id = self._current_m_id()
            if m_id is None:
                self._decoded = ""
                self._b85 = ""
                self._stats = []
                self.dataChanged.emit()
                return
            level = self._level if str(self._level).isdigit() else self._character_level
            seed = self._seed if str(self._seed).isdigit() else str(random.randint(100, 9999))
            header = f"{m_id}, 0, 1, {level}| 2, {seed}||"
            parts_list = []

            selected_rarity = self._rarity_options[self._rarity_index]["value"] if self._rarity_options else ""
            if selected_rarity in {"Legendary", "Pearl"}:
                special = self._special_options.get(f"{selected_rarity} Type", [])
                idx = self._special_index.get(f"{selected_rarity} Type", 0)
                if 0 <= idx < len(special) and special[idx]["value"] is not None:
                    part_id = str(special[idx]["value"])
                    if part_id.isdigit():
                        parts_list.append(f"{{{part_id}}}")
            elif selected_rarity:
                rarity_id_row = self.weapon_rarity_df[
                    (self.weapon_rarity_df["Manufacturer & Weapon Type ID"] == m_id)
                    & (self.weapon_rarity_df["Stat"] == selected_rarity)
                    & (self.weapon_rarity_df["Description"].isna())]
                if not rarity_id_row.empty:
                    parts_list.append(f"{{{rarity_id_row.iloc[0]['Part ID']}}}")

            for values, index in (
                (self._element1_values, self._element1_index),
                (self._element2_values, self._element2_index),
                (self._pearl_stat_values, self._pearl_stat_index),
                (self._pearl_element_values, self._pearl_element_index),
            ):
                value = self._element_value_at(values, index)
                if value is None:
                    continue
                part_id = value.split(" - ")[0]
                if part_id.isdigit():
                    parts_list.append(f"{{1:{part_id}}}")

            for group in self._part_groups:
                for slot in group["slots"]:
                    value = slot["options"][slot["selectedIndex"]].get("value")
                    if value is not None and str(value).isdigit():
                        parts_list.append(f"{{{value}}}")

            component_str = " ".join(parts_list)
            self._decoded = f"{header} {component_str} |"
            encoded_serial, err = b_encoder.encode_to_base85(self._decoded)
            self._encode_error = bool(err)
            if err:
                self._b85 = ""
                raise ValueError(err)
            self._b85 = encoded_serial
            self._update_stats()
            self._refresh_part_details()
            self._update_rule_guidance()
        except Exception:
            self._encode_error = True
            self._b85 = ""
            self._stats = []
        self.dataChanged.emit()

    def _update_stats(self) -> None:
        stats = item_display_resolver.resolve_weapon_stats(self._decoded) if self._decoded else {}
        self._stats = []
        for key in item_display_resolver.WEAPON_STAT_KEYS:
            value = item_display_resolver.format_weapon_stat(key, stats.get(key), self.current_lang) or "—"
            self._stats.append({
                "key": key,
                "label": self.stats_loc.get(key, key.replace("_", " ").title()),
                "value": str(value),
            })

    def _refresh_part_details(self) -> None:
        m_id = self._current_m_id()
        if m_id is None:
            return
        for group in self._part_groups:
            rows = self.all_weapon_parts_df[
                (self.all_weapon_parts_df["Manufacturer & Weapon Type ID"] == m_id)
                & (self.all_weapon_parts_df["Part Type"] == group["partType"])]
            row_by_pid = {str(r["Part ID"]): r for _, r in rows.iterrows()}
            for slot in group["slots"]:
                # HusSelect 弹层只渲染 label，旧版 popupAboutToShow 的全量属性文本
                # 在这里预计算到 text，由 _apply_part_kinds 拼上 marker 后写入 label。
                for option in slot["options"]:
                    part_id = option.get("value")
                    if part_id is None:
                        continue
                    row = row_by_pid.get(str(part_id))
                    if row is not None:
                        option["text"] = self._part_option_text(
                            m_id, str(part_id), row, self._decoded)
                selected = slot["options"][slot["selectedIndex"]].get("value")
                if selected is None:
                    slot["detail"] = ""
                    continue
                row = row_by_pid.get(str(selected))
                description = item_display_resolver.format_weapon_part_description(
                    int(m_id), str(selected), self._decoded, self.current_lang,
                    str(row["Part Type"]) if row is not None else "")
                slot["detail"] = description or ""

    # ------------------------------------------------------------------ #
    # 规则指引（对齐 _update_generation_rule_guidance）
    # ------------------------------------------------------------------ #
    def _rule_violation_text(self, violation):
        labels = {
            "rules_unavailable": ("violation_rules_unavailable", "规则数据不可用", "Rule data unavailable"),
            "weapon_rules_missing": ("violation_weapon_rules_missing", "缺少该武器规则", "Weapon rules missing"),
            "unknown_composition": ("violation_unknown_composition", "未选择或无法识别武器模板", "Weapon composition is missing or unknown"),
            "multiple_compositions": ("violation_multiple_compositions", "存在多个武器模板", "Multiple weapon compositions"),
            "foreign_root_part": ("violation_foreign_root_part", "存在跨来源配件", "Foreign part"),
            "foreign_root_part_manufacturer": ("violation_foreign_root_part_manufacturer", "存在跨厂商配件", "Cross-manufacturer part"),
            "foreign_root_part_type": ("violation_foreign_root_part_type", "存在跨类型配件", "Cross-type part"),
            "unknown_part": ("violation_unknown_part", "存在未知配件", "Unknown weapon part"),
            "part_not_allowed": ("violation_part_not_allowed", "存在非自然生成配件", "Part is outside the natural pool"),
            "count_below": ("violation_count_below", "配件尚未补齐", "Required parts are missing"),
            "count_above": ("violation_count_above", "配件数量超过自然上限", "Part count exceeds the natural maximum"),
            "duplicate_part": ("violation_duplicate_part", "存在重复配件", "Duplicate part"),
            "missing_required_tag": ("violation_missing_required_tag", "配件依赖未满足", "Part dependency is not satisfied"),
            "excluded_tag_conflict": ("violation_excluded_tag_conflict", "配件条件冲突", "Part conditions conflict"),
            "tag_limit": ("violation_tag_limit", "授权类配件超过上限", "Tagged part count exceeds the limit"),
            "forced_part_missing": ("violation_forced_part_missing", "缺少模板固有配件", "Forced composition part is missing"),
            "conditional_availability": ("violation_conditional_availability", "仅在特定条件下生成", "Available only in a special context"),
            "unresolved_rule_parts": ("violation_unresolved_rule_parts", "规则仍有未解析配件", "Rule contains unresolved parts"),
            "inheritance_cycle": ("violation_inheritance_cycle", "模板规则继承异常", "Composition rule inheritance cycle"),
        }
        code = violation.get("code")
        foreign_kind = str(violation.get("foreign_kind") or "")
        if code == "foreign_root_part" and foreign_kind:
            code = f"{code}_{foreign_kind}"
        key, zh, en = labels.get(code, ("", str(code or ""), str(code or "")))
        text = self._rule_message(key, zh, en) if key else en
        actual = violation.get("actual")
        limit = violation.get("min", violation.get("max"))
        if actual is not None and limit is not None:
            text += f" ({actual}/{limit})"
        return text

    def _rule_candidate_text(self, ref, rows):
        root_id, _, part_id = str(ref).partition(":")
        matches = rows[rows["Part ID"] == part_id] if rows is not None else None
        row = matches.iloc[0] if matches is not None and not matches.empty else None
        name = item_display_resolver.weapon_part_name(
            int(root_id), part_id, self.current_lang, row) if root_id.isdigit() else ""
        return f"{ref} — {name}" if name else str(ref)

    def _preferred_refs_for_composition(self, composition_ref):
        entry = self.preferred_parts.get(str(composition_ref))
        if not isinstance(entry, dict):
            return set()
        return {str(ref) for ref in entry.get("refs", ()) if str(ref)}

    def _update_rule_guidance(self) -> None:
        try:
            result = item_display_resolver.validate_weapon_generation(
                self._decoded, allow_incomplete=True)
        except Exception as exc:
            result = {"status": "unknown", "groups": {},
                      "violations": [{"code": f"rule_error: {exc}"}],
                      "rules_available": False, "composition_ref": ""}

        status_labels = {
            "legal": ("status_legal", "自然生成", "Legal"),
            "incomplete": ("status_incomplete", "待补齐", "Incomplete"),
            "modified": ("status_modified", "魔改", "Modified"),
            "conditional": ("status_conditional", "条件限定", "Conditional"),
            "unknown": ("status_unknown", "规则未知", "Rules unknown"),
        }
        status = str(result.get("status") or "unknown")
        status_key, status_zh, status_en = status_labels.get(status, status_labels["unknown"])
        status_text = self._rule_message(status_key, status_zh, status_en)
        violations = [self._rule_violation_text(item) for item in result.get("violations", [])]
        item_id = self._current_m_id()
        preferred_refs = self._preferred_refs_for_composition(result.get("composition_ref"))
        status_lines = violations or [self._rule_message(
            "matches_rules", "符合当前自然生成规则", "Matches the current generation rules")]
        if preferred_refs and item_id is not None:
            selected = len(preferred_refs & self._selected_part_refs(item_id))
            status_lines.append(self._rule_message(
                "preferred_selected_count", "已选 {selected}/{total} 个官方推荐件",
                "Selected {selected}/{total} recommended parts",
                selected=selected, total=len(preferred_refs)))
        self._rule_badge = {"text": status_text, "status": status,
                            "tooltip": "\n".join(status_lines)}
        # 缺失配件列表（构建状态旁展示）：count_below 违规按规则组给出 "组 当前/下限"
        rule_groups = result.get("groups") or {}
        missing = []
        for violation in result.get("violations", []):
            if str(violation.get("code") or "") != "count_below":
                continue
            group_key = str(violation.get("group") or "")
            spec = rule_groups.get(group_key) or {}
            first_ref = next((ref for ref in (spec.get("allowed") or [])), "")
            missing.append({
                "label": self._rule_group_label(group_key, first_ref, item_id),
                "actual": int(violation.get("actual", 0) or 0),
                "limit": int(violation.get("min", 0) or 0),
            })
        self._missing_parts = missing

        rules_ready = bool(result.get("rules_available") and result.get("composition_ref"))
        groups = result.get("groups") or {}
        self._refresh_element_states(groups, rules_ready)
        display_matches = {}
        group_categories = {}
        if rules_ready and item_id is not None:
            for group in self._part_groups:
                part_type = group["partType"]
                rows = self.all_weapon_parts_df[
                    (self.all_weapon_parts_df["Manufacturer & Weapon Type ID"] == item_id)
                    & (self.all_weapon_parts_df["Part Type"] == part_type)]
                candidate_refs = {
                    f"{item_id}:{part_id}"
                    for part_id in (rows["Part ID"].tolist() if rows is not None else [])
                    if str(part_id)
                }
                matched_groups = [
                    g for g, group_rule in groups.items()
                    if (set(group_rule.get("allowed") or []) | set(group_rule.get("selected") or [])) & candidate_refs
                ]
                display_matches[part_type] = (rows, candidate_refs, matched_groups)
                for g in matched_groups:
                    group_categories.setdefault(g, set()).add(part_type)

        for group in self._part_groups:
            part_type = group["partType"]
            current = sum(
                slot["options"][slot["selectedIndex"]].get("value") is not None
                for slot in group["slots"])
            if not rules_ready or item_id is None:
                group["badge"] = f"{current} / —"
                group["badgeTip"] = self._rule_message(
                    "select_composition", "选择武器模板后显示合法范围", "Select a composition to show its legal range")
                self._apply_part_kinds(group, item_id, preferred_refs=preferred_refs)
                continue
            rows, candidate_refs, matched_groups = display_matches.get(part_type, (None, set(), []))
            if not matched_groups:
                group["badge"] = f"{current} / —"
                group["badgeTip"] = self._rule_message(
                    "no_group_rule", "该显示分组没有独立生成规则", "No separate generation rule for this display group")
                self._apply_part_kinds(group, item_id, preferred_refs=preferred_refs)
                continue
            matched = [groups[g] for g in matched_groups]
            current = sum(len(group_rule.get("selected") or []) for group_rule in matched)
            shared = any(len(group_categories.get(g, ())) > 1 for g in matched_groups)
            legal_min = sum(int(group_rule.get("effective_min", 0)) for group_rule in matched)
            legal_max = sum(int(group_rule.get("effective_max", 0)) for group_rule in matched)
            legal_range = str(legal_min) if legal_min == legal_max else f"{legal_min}–{legal_max}"
            group["badge"] = self._rule_message(
                "shared_current_legal" if shared else "current_legal",
                "共享配额 当前{current}/合法{range}" if shared else "当前{current}/合法{range}",
                "shared {current}/{range}" if shared else "{current}/{range}",
                current=current, range=legal_range)
            eligible = sorted({
                ref
                for group_rule in matched
                for ref in group_rule.get("eligible_refs") or []
                if ref in candidate_refs
                and (len(group_rule.get("selected") or []) < int(group_rule.get("effective_max", 1))
                     or ref in set(group_rule.get("selected") or []))
            }, key=lambda ref: tuple(map(int, ref.split(":"))))
            allowed = {
                ref
                for group_rule in matched
                for ref in group_rule.get("allowed") or []
                if ref in candidate_refs
            }
            self._apply_part_kinds(group, item_id, eligible, allowed, preferred_refs)
            lines = [
                self._rule_message("current", "当前：{current}", "Current: {current}", current=current),
                self._rule_message("legal_count", "合法数量：{range}", "Legal count: {range}", range=legal_range),
            ]
            if eligible:
                lines.append(self._rule_message("legal_candidates", "合法候选：", "Legal candidates:"))
                lines.extend(self._rule_candidate_text(ref, rows) for ref in eligible)
            else:
                lines.append(self._rule_message(
                    "no_legal_candidates", "当前配件条件下没有合法候选",
                    "No legal candidates under the current part conditions"))
            group["badgeTip"] = "\n".join(lines)

    def _rule_group_label(self, group_key: str, ref: str, item_id) -> str:
        """规则组显示名：legit 组表 → 组内首个 allowed 配件的配件类型标题 → 标题化回退。"""
        legit_groups = (self.legit_loc or {}).get("groups") or {}
        if group_key in legit_groups:
            return str(legit_groups[group_key])
        _owner, _sep, part_id = str(ref or "").partition(":")
        if part_id and item_id is not None and self.all_weapon_parts_df is not None:
            rows = self.all_weapon_parts_df[
                (self.all_weapon_parts_df["Manufacturer & Weapon Type ID"] == item_id)
                & (self.all_weapon_parts_df["Part ID"] == part_id)]
            if not rows.empty:
                return self.get_localized_string(str(rows.iloc[0]["Part Type"]))
        special = {
            "pearl_stat": (self.ui_loc.get("sections") or {}).get("pearl_stat"),
            "pearl_elem": (self.ui_loc.get("sections") or {}).get("pearl_elements"),
            "secondary_ele": (self.ui_loc.get("labels") or {}).get("secondary_element"),
        }.get(group_key)
        if special:
            return str(special)
        pretty = group_key.replace("_", " ").title()
        return str(self.weapon_localization.get(pretty) or pretty)

    def _apply_part_kinds(self, group, item_id, eligible_refs=(), allowed_refs=(), preferred_refs=()):
        eligible_refs, allowed_refs, preferred_refs = (
            set(eligible_refs), set(allowed_refs), set(preferred_refs))
        for slot in group["slots"]:
            for option in slot["options"]:
                part_id = option.get("value")
                if item_id is None or part_id is None:
                    kind = ""
                else:
                    ref = f"{item_id}:{part_id}"
                    if ref in preferred_refs:
                        kind = "preferred"
                    elif ref in eligible_refs:
                        kind = "eligible"
                    elif ref in allowed_refs:
                        kind = "allowed"
                    else:
                        kind = ""
                option["kind"] = kind
                bg, fg, bold = _KIND_POPUP_STYLE.get(kind, ("", "", False))
                option["itemBg"] = bg
                option["itemColor"] = fg
                option["itemBold"] = bold
                # label 恢复纯文本（text 为预计算的完整属性描述，见 _refresh_part_details）
                option["label"] = str(option.get("text") or option.get("label") or "")

    # ------------------------------------------------------------------ #
    # 写背包 / 复制
    # ------------------------------------------------------------------ #
    @pyqtSlot()
    def addToBackpack(self) -> None:
        if not self._b85 or self._encode_error:
            self.app.toast(self.ui_loc.get("dialogs", {}).get("gen_first", "Please generate a weapon first."),
                           "warning")
            return
        self.app.addSerialToBackpack(self._b85, self._flag_value())

    @pyqtSlot()
    def copyRawToClipboard(self) -> None:
        QApplication.clipboard().setText(self._decoded)
        self.app.toast(self.ui_loc.get("dialogs", {}).get("base85_copied", "Copied"), "success")

    @pyqtSlot()
    def copyBase85ToClipboard(self) -> None:
        QApplication.clipboard().setText(self._b85)
        self.app.toast(self.ui_loc.get("dialogs", {}).get("base85_copied", "Copied"), "success")

    # ------------------------------------------------------------------ #
    # 幸运 Roll（对齐 _roll_weapons）
    # ------------------------------------------------------------------ #
    def _roll_texts(self):
        labels = self.ui_loc.get("labels", {})
        buttons = self.ui_loc.get("buttons", {})
        sections = self.ui_loc.get("sections", {})
        return {
            "constraints_title": sections.get("roll_options", "Roll Options"),
            "results_title": sections.get("roll_results", "Roll Results"),
            "manufacturer": labels.get("manufacturer", "Manufacturer"),
            "weapon_type": labels.get("weapon_type", "Weapon Type"),
            "rarity": labels.get("rarity", "Rarity"),
            "count": labels.get("quantity", "Quantity"),
            "random": labels.get("random", "Random"),
            "element": labels.get("element", "Element"),
            "generated": labels.get("generated", "Generated {count} legal weapons"),
            "no_results": labels.get("no_results", "No generated weapons yet"),
            "level_value": labels.get("level_value", "Lv{level}"),
            "legal": labels.get("legal", "Legal"),
            "scope_template": labels.get("scope_template", "Manufacturer: {manufacturer} · Type: {weapon_type} · Rarity: {rarity}"),
            "roll": buttons.get("roll", "Roll"),
            "add_one": buttons.get("add_one", "Add This"),
            "copy_base85": buttons.get("copy_base85", "Copy Base85"),
            "add_all": buttons.get("add_all", "Add All"),
            "copied": self.ui_loc.get("dialogs", {}).get("base85_copied", "Base85 copied"),
            "roll_failed": self.ui_loc.get("dialogs", {}).get("roll_failed", "Roll failed: {error}"),
            "no_legal_result": self.ui_loc.get("dialogs", {}).get("no_legal_result", "No legal build matches the filters."),
            "roll_add_done": self.ui_loc.get("dialogs", {}).get("roll_add_done", "Added {success}; failed {fail}"),
        }

    def _weapon_roll_catalog(self):
        catalog = []
        weapons = self.weapon_rules.get("weapons") or {}
        root_column = pd.to_numeric(self.all_weapon_parts_df["Manufacturer & Weapon Type ID"], errors="coerce")
        for root_id, weapon in weapons.items():
            rows = self.all_weapon_parts_df[root_column == int(root_id)]
            if rows.empty:
                continue
            manufacturer = str(rows.iloc[0]["Manufacturer"])
            weapon_type = str(rows.iloc[0]["Weapon Type"])
            manufacturer_label = self.get_localized_string(manufacturer, manufacturer)
            weapon_type_label = self.weapon_taxonomy.get(
                weapon_type.casefold().replace(" ", "_"),
                self.get_localized_string(weapon_type, weapon_type))
            for composition_ref, composition in (weapon.get("compositions") or {}).items():
                if composition.get("availability") != "coregame":
                    continue
                if "npc_weapon" in {str(tag).casefold() for tag in composition.get("base_tags", ())}:
                    continue
                names = composition.get("name") or {}
                if (str(composition.get("part") or "").casefold() == "comp_05_legendary"
                        and not str(names.get("en") or "").strip()
                        and not str(names.get("zh") or "").strip()
                        and not composition.get("forced_part_refs")):
                    continue
                rarity = str(composition.get("rarity") or "")
                named = bool(str(names.get("en") or "").strip() or str(names.get("zh") or "").strip())
                preferred_name = names.get("zh") if self.current_lang == "zh-CN" else names.get("en")
                name = str(preferred_name or names.get("en") or names.get("zh") or "").strip()
                rarity_label = self.weapon_taxonomy.get(
                    rarity.casefold(), self.get_localized_string(rarity, rarity))
                catalog.append({
                    "root_id": str(root_id),
                    "composition_ref": str(composition_ref),
                    "manufacturer": manufacturer,
                    "manufacturer_label": manufacturer_label,
                    "weapon_type": weapon_type,
                    "weapon_type_label": weapon_type_label,
                    "rarity": rarity,
                    "rarity_label": rarity_label,
                    "name": name if named else "",
                    "is_named": named and rarity in {"Legendary", "Pearl"},
                })
        return catalog

    @staticmethod
    def _roll_serial_token(ref, root_id):
        ref_root, _, part_id = str(ref).partition(":")
        return f"{{{part_id}}}" if ref_root == str(root_id) else f"{{{ref_root}:{part_id}}}"

    def _roll_part_tags(self, ref):
        return (
            (self.weapon_rules.get("part_selection_tags") or {}).get(str(ref))
            or (self.item_index.get("part_refs") or {}).get(str(ref), {}).get("selection_tags")
            or {}
        )

    def _roll_element_text(self, selected_refs):
        values = []
        part_refs = self.item_index.get("part_refs") or {}
        for ref in selected_refs:
            group = str((part_refs.get(str(ref)) or {}).get("selection_group") or "").casefold()
            if group not in {"body_ele", "secondary_ele", "pearl_elem"}:
                continue
            root, _sep, part_id = str(ref).partition(":")
            if not part_id.isdigit() or not root.isdigit():
                continue
            rows = self.elemental_df[
                (self.elemental_df["Elemental_ID"] == int(root))
                & (self.elemental_df["Part_ID"] == int(part_id))
            ]
            if rows.empty:
                value = item_display_resolver.format_weapon_part_description(
                    int(root), part_id, "", self.current_lang,
                    _ELEMENT_GROUP_PART_TYPES.get(group, ""))
                if value == item_display_resolver.no_stat_changes_text(self.current_lang):
                    value = ""
            else:
                value = str(rows.iloc[0].get(self.elemental_stat_col) or "").strip()
                if group == "pearl_elem" and ":" in value:
                    value = value.split(":", 1)[1].strip()
            value = str(value or "").strip()
            if value and value not in values:
                values.append(value)
        return " / ".join(values)

    @staticmethod
    def _filter_roll_catalog(catalog, constraints):
        return [
            row for row in catalog
            if (constraints.get("manufacturer") is None or row["manufacturer"] == constraints["manufacturer"])
            and (constraints.get("weapon_type") is None or row["weapon_type"] == constraints["weapon_type"])
            and (constraints.get("rarity") is None or row["rarity"] == constraints["rarity"])
            and (constraints.get("composition_ref") is None or row["composition_ref"] == constraints["composition_ref"])
        ]

    def _roll_one_weapon(self, candidate, rng):
        root_id = candidate["root_id"]
        weapon = (self.weapon_rules.get("weapons") or {})[root_id]
        composition = weapon["compositions"][candidate["composition_ref"]]
        selected = sample_composition_parts(
            composition=composition,
            part_types=weapon.get("part_types") or (),
            tags_for_ref=self._roll_part_tags,
            excluded_refs=set((self.weapon_rules.get("part_availability") or {}).keys()),
            rng=rng,
        )
        level = self._level if str(self._level).isdigit() else self._character_level
        seed = rng.randint(100, 9999)
        refs = [candidate["composition_ref"], *selected]
        components = " ".join(self._roll_serial_token(ref, root_id) for ref in refs)
        decoded = f"{root_id}, 0, 1, {level}| 2, {seed}|| {components} |"
        serial, error = b_encoder.encode_to_base85(decoded)
        if error:
            raise ValueError(error)
        validation = item_display_resolver.validate_weapon_generation(decoded)
        if validation.get("status") != "legal":
            raise ValueError(", ".join(
                str(item.get("code")) for item in validation.get("violations", ())
            ) or str(validation.get("status")))
        display = item_display_resolver.resolve_item_display(
            int(root_id), candidate["manufacturer"], candidate["weapon_type"], decoded, self.current_lang)
        stats = item_display_resolver.resolve_weapon_stats(decoded)
        formatted_stats = {
            key: item_display_resolver.format_weapon_stat(key, stats.get(key), self.current_lang) or "—"
            for key in item_display_resolver.WEAPON_STAT_KEYS
        }
        name = display.get("display_name") or candidate.get("name") or "—"
        rarity = display.get("rarity") or candidate["rarity_label"]
        element = self._roll_element_text(selected)
        rarity_color = qt_items_tab.WEAPON_CARD_RARITY_COLORS.get(
            str(candidate.get("rarity") or "").casefold()) or qt_items_tab.WEAPON_CARD_RARITY_COLORS.get(
            str(rarity).casefold()) or "#78909C"
        return {
            "serial": serial,
            "decoded": decoded,
            "level": str(level),
            "name": name,
            "manufacturer": candidate["manufacturer_label"],
            "weapon_type": candidate["weapon_type_label"],
            "rarity": rarity,
            "rarity_color": rarity_color,
            "element": element,
            "stats": [{"key": k, "label": self.stats_loc.get(k, k), "value": str(v)}
                      for k, v in formatted_stats.items()],
            "effect_entries": self._roll_effect_entries(decoded, stats),
            "tooltip": "\n".join([
                name,
                f"{candidate['manufacturer_label']} · {candidate['weapon_type_label']}",
                f"{self.get_localized_string('rarity', 'Rarity')}: {rarity}",
                *(f"{self.stats_loc.get(k, k)}: {formatted_stats[k]}" for k in item_display_resolver.WEAPON_STAT_KEYS),
                f"Base85: {serial}",
            ]),
        }

    def _roll_effect_entries(self, decoded: str, stats) -> list[dict[str, Any]]:
        """Roll 结果详情的图标化词条列表：与物品页武器卡同一数据源/图标资源。"""
        if not decoded:
            return []
        try:
            details = qt_items_tab._weapon_card_details(decoded, stats or {}, self.current_lang)
        except Exception:
            return []
        entries = (details or {}).get("display_entries") or (details or {}).get("entries") or []
        out: list[dict[str, Any]] = []
        for entry in entries:
            text = str(entry.get("text") or "").strip()
            if not text:
                continue
            title, description = text, ""
            for separator in (" - ", " – "):
                if separator in title:
                    title, description = title.split(separator, maxsplit=1)
                    break
            out.append({
                "title": title.strip(),
                "description": description.strip(),
                "icon": qt_items_tab._effect_icon_uri(str(entry.get("icon_asset") or "")),
                "legendary": str(entry.get("display_kind") or "") == "legendary",
            })
        return out

    def _roll_scope_text(self, constraints, catalog):
        texts = self._roll_texts()

        def label(field, label_field):
            value = constraints.get(field)
            if value is None:
                return texts["random"]
            row = next((item for item in catalog if item.get(field) == value), None)
            return str((row or {}).get(label_field) or value)

        return texts["scope_template"].format(
            manufacturer=label("manufacturer", "manufacturer_label"),
            weapon_type=label("weapon_type", "weapon_type_label"),
            rarity=label("rarity", "rarity_label"))

    @pyqtProperty("QVariantMap", notify=dataChanged)
    def rollTexts(self) -> dict[str, str]:
        return self._roll_texts()

    @pyqtSlot(result="QVariantMap")
    def rollConstraintOptions(self) -> dict[str, list]:
        texts = self._roll_texts()
        catalog = self._weapon_roll_catalog()
        random_opt = {"label": texts["random"], "value": None}
        mfgs, types, rarities = {}, {}, {}
        for row in catalog:
            mfgs[row["manufacturer"]] = row["manufacturer_label"]
            types[row["weapon_type"]] = row["weapon_type_label"]
            if row["rarity"]:
                rarities[row["rarity"]] = row["rarity_label"]
        return {
            "manufacturers": [random_opt, *[{"label": v, "value": k} for k, v in sorted(mfgs.items())]],
            "weapon_types": [random_opt, *[{"label": v, "value": k} for k, v in sorted(types.items())]],
            # 稀有度按 普通→珠光 固定顺序（对齐主线 _RARITY_ORDER）
            "rarities": [random_opt, *[{"label": v, "value": k} for k, v in sorted(
                rarities.items(), key=lambda item: _rarity_rank(item[0]))]],
        }

    @pyqtProperty(list, notify=rollFinished)
    def rollResults(self) -> list[dict[str, Any]]:
        return self._roll_results

    @pyqtProperty(str, notify=rollFinished)
    def rollSummaryText(self) -> str:
        return self._roll_summary

    @pyqtSlot("QVariantMap", int, result=bool)
    def roll(self, constraints, count) -> bool:
        constraints = {k: v for k, v in dict(constraints or {}).items() if v is not None and v != ""}
        count = max(1, min(50, int(count)))
        catalog = self._filter_roll_catalog(self._weapon_roll_catalog(), constraints)
        texts = self._roll_texts()
        if not catalog:
            self.app.toast(texts["no_legal_result"], "warning")
            self._roll_results = []
            self._roll_summary = ""
            self.rollFinished.emit(False)
            return False
        rng = random.SystemRandom()
        roots = sorted({row["root_id"] for row in catalog}, key=int)
        results = []
        try:
            for _ in range(count):
                last_error = None
                for _attempt in range(24):
                    root_id = rng.choice(roots)
                    candidate = rng.choice([row for row in catalog if row["root_id"] == root_id])
                    try:
                        results.append(self._roll_one_weapon(candidate, rng))
                        break
                    except Exception as exc:
                        last_error = exc
                else:
                    raise RuntimeError(last_error or "no legal result")
        except Exception as exc:
            self.app.toast(texts["roll_failed"].format(error=exc), "error")
            self._roll_results = []
            self._roll_summary = ""
            self.rollFinished.emit(False)
            return False
        self._roll_results = results
        self._roll_summary = texts["generated"].format(count=len(results)) \
            + " · " + self._roll_scope_text(constraints, catalog)
        self.rollFinished.emit(True)
        return True

    @pyqtSlot(int)
    def copyRollResult(self, index: int) -> None:
        if 0 <= index < len(self._roll_results):
            QApplication.clipboard().setText(self._roll_results[index]["serial"])
            self.app.toast(self._roll_texts()["copied"], "success")

    @pyqtSlot("QVariantList")
    def addRollToBackpack(self, indices) -> None:
        from core.batch import add_serial_lines

        serials = [self._roll_results[i]["serial"] for i in indices
                   if isinstance(i, int) and 0 <= i < len(self._roll_results)]
        if not serials:
            return
        texts = self._roll_texts()
        if not self.controller.yaml_obj:
            self.app.toast(self.tr("main_window.dialogs.load_save_first"), "warning")
            return
        self.app.suspend_autosave(True)
        success = fail = 0
        try:
            for _current, _total, s, f in add_serial_lines(self.controller, serials, self._flag_value()):
                success, fail = s, f
        finally:
            self.app.suspend_autosave(False)
        self.app.toast(texts["roll_add_done"].format(success=success, fail=fail),
                       "success" if success else "warning")
        if success:
            self.app._mark_items_stale()
