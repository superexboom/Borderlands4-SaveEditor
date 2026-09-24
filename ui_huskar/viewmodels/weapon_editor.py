"""武器编辑器 VM：移植 WeaponEditorTab 的全部非渲染逻辑。

背包武器浏览、序列号双向编辑、稀有度/等级/种子联动、部件列表
（简单/元素/组/皮肤，排序、删除、上移下移、组折叠）、添加配件目录
（facet + 生成候选提示）、皮肤选择、写回存档 / 加入背包、内部名显示开关。
"""

from __future__ import annotations

import random
import re
from collections import Counter, defaultdict
from typing import Any

import pandas as pd
from PyQt6.QtCore import pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QApplication

from core import b_encoder, bl4_functions as bl4f, decoder_logic, item_display_resolver, resource_loader

from .base import PageViewModel, register

_FLAG_CODE_ORDER = ("1", "3", "5", "17", "33", "65", "129")

PART_TYPE_COLORS = {
    "Barrel": "#B0BEC5", "Barrel Accessory": "#90A4AE",
    "Body": "#BCAAA4", "Body Accessory": "#A1887F", "Body Mechanism": "#8D6E63",
    "Foregrip": "#9CCC65", "Grip": "#AED581",
    "Magazine": "#FFB300", "Magazine Accessory": "#FFCA28",
    "Manufacturer Part": "#9FA8DA",
    "Scope": "#4DD0E1", "Scope Accessory": "#26C6DA",
    "Stat Modifier": "#F06292",
    "Underbarrel": "#BCAAA4", "Underbarrel Accessory": "#A1887F",
    "Elemental": "#EF9A9A", "Element": "#EF9A9A", "Element Switch": "#EF9A9A",
    "Underbarrel Element Switch": "#EF9A9A",
    "Pearl Elements": "#80CBC4", "Pearl Stat": "#CE93D8",
    "Skin": "#FFEA00", "Rarity": "#B39DDB", "Legendary": "#FF8A65",
}

TAXONOMY_KEYS = {
    "Body": "body", "Body Accessory": "body_accessory", "Body Mechanism": "body_mechanism",
    "Barrel": "barrel", "Barrel Accessory": "barrel_accessory",
    "Manufacturer Part": "manufacturer_part", "Tediore Payload": "tediore_payload",
    "Tediore Throw Reload": "tediore_throw_reload", "Magazine": "magazine",
    "Magazine Accessory": "magazine_accessory", "Scope": "scope",
    "Scope Accessory": "scope_accessory", "Grip": "grip",
    "Underbarrel": "underbarrel", "Underbarrel Accessory": "underbarrel_accessory",
    "Foregrip": "foregrip", "Borg Magazine Adapter": "borg_magazine_adapter",
    "Special Element Set": "special_element_set", "Stat Modifier": "stat_modifier",
    "Elemental": "elemental", "Element": "element", "Element Switch": "element_switch",
    "Underbarrel Element Switch": "underbarrel_element_switch",
    "Pearl Elements": "pearl_elements", "Pearl Stat": "pearl_stat",
    "Skin": "skin", "Rarity": "rarity", "Common": "common",
    "Uncommon": "uncommon", "Rare": "rare", "Epic": "epic",
    "Legendary": "legendary", "Pearl": "pearl",
    "Assault Rifle": "assault_rifle", "Pistol": "pistol", "Shotgun": "shotgun",
    "SMG": "smg", "Sniper": "sniper",
}

GENERATION_GROUP_TYPES = {
    "barrel": "Barrel", "barrel_acc": "Barrel Accessory",
    "body": "Body", "body_acc": "Body Accessory", "body_bolt": "Body Mechanism",
    "body_ele": "Special Element Set", "body_mag": "Manufacturer Part",
    "endgame": "Stat Modifier", "firmware": "Stat Modifier",
    "foregrip": "Foregrip", "grip": "Grip",
    "hyperion_secondary_acc": "Manufacturer Part",
    "magazine": "Magazine", "magazine_acc": "Magazine Accessory",
    "magazine_borg": "Borg Magazine Adapter",
    "magazine_ted_thrown": "Tediore Throw Reload",
    "pearl_elem": "Pearl Elements", "pearl_stat": "Pearl Stat",
    "scope": "Scope", "scope_acc": "Scope Accessory",
    "secondary_ammo": "Manufacturer Part",
    "secondary_ele": "Underbarrel Element Switch",
    "tediore_acc": "Tediore Payload",
    "tediore_secondary_acc": "Manufacturer Part",
    "underbarrel": "Underbarrel", "underbarrel_acc": "Underbarrel Accessory",
    "underbarrel_acc_vis": "Underbarrel Accessory",
}

INTERNAL_NAME_SKIP_TYPES = {
    "Elemental", "Element", "Element Switch", "Underbarrel Element Switch",
    "Pearl Elements", "Pearl Stat", "Special Element Set",
}

_WEAPON_TYPES = {"Pistol", "Shotgun", "SMG", "Assault Rifle", "Sniper"}
_RARITY_UI = ("Common", "Uncommon", "Rare", "Epic")


@register("weapon_editor", "WeaponEditorPage.qml")
class WeaponEditorViewModel(PageViewModel):
    STRINGS_SECTION = "weapon_editor_tab"

    dataChanged = pyqtSignal()

    def __init__(self, app, parent=None):
        super().__init__(app, parent)
        self.current_lang = str(app.language)
        self.selected_weapon_path = None
        self.parts_data: list = []
        self.rarity_part = None
        self.is_handling_change = False
        self._decoded = ""
        self._b85 = ""
        self._b85_readonly = False
        self._manufacturer = ""
        self._weapon_type = ""
        self._rarity_index = -1
        self._rarity_text = ""
        self._rarity_editable = True
        self._level = ""
        self._seed = ""
        self._weapon_name = ""
        self._stats: list[dict[str, str]] = []
        self._legality = {"text": "—", "status": "unknown", "tooltip": ""}
        self._part_rows: list[dict[str, Any]] = []
        self._group_collapsed: set[int] = set()
        self._browser_items: list[dict[str, Any]] = []
        self._browser_search = ""
        self._summary = ""
        self._flag_index = 0
        self._skin_options: list[dict[str, str]] = []
        self._flags = resource_loader.get_flag_labels(self.current_lang)
        self._flag_labels = [self._flags[k] for k in _FLAG_CODE_ORDER if k in self._flags]
        self._flag_index = self._default_flag_index()
        self._show_internal = bool(self.app._settings.value(
            "weapon_editor/show_internal_part_names", False, type=bool))
        self._load_data(self.current_lang)

    # ------------------------------------------------------------------ #
    # 数据加载
    # ------------------------------------------------------------------ #
    def _load_data(self, lang: str) -> None:
        self.current_lang = lang
        self.ui_localization = self.app.localizer.section("weapon_editor_tab")
        self.weapon_rule_loc = self.app.localizer.section("weapon_rules")
        try:
            suffix = "_EN" if lang in ("en-US", "ru", "ua") else ""

            def get_path(base_name):
                name_with_suffix = base_name.replace(".csv", f"{suffix}.csv")
                path = resource_loader.get_weapon_data_path(name_with_suffix)
                if path and path.exists():
                    return path
                return resource_loader.get_weapon_data_path(base_name)

            self.all_weapon_parts_df = pd.read_csv(get_path("all_weapon_part.csv"))
            self.elemental_df = pd.read_csv(resource_loader.get_weapon_data_path("elemental.csv"))
            self.elemental_stat_col = "Stat_ZH" if lang == "zh-CN" else "Stat"
            self.skin_df = pd.read_csv(resource_loader.get_weapon_data_path("skin.csv"))
            self.skin_df["Skin_ID"] = self.skin_df["Skin_ID"].astype(str)
            self.skin_stat_col = "Stat_EN" if lang in ("en-US", "ru", "ua") else "Stat"
            self.weapon_rarity_df = pd.read_csv(get_path("weapon_rarity.csv"))
            self.rarity_desc_col = "Description_ZH" if lang == "zh-CN" else "Description"
            self.weapon_localization = (
                resource_loader.load_weapon_json("weapon_localization_zh-CN.json") or {}
                if lang == "zh-CN" else {})
            self._flags = resource_loader.get_flag_labels(lang)
            self._flag_labels = [self._flags[k] for k in _FLAG_CODE_ORDER if k in self._flags]
            self._data_error = ""
        except Exception as exc:
            self.all_weapon_parts_df = None
            self._data_error = str(exc)

    def on_language_changed(self) -> None:
        super().on_language_changed()
        decoded = self._decoded
        self._load_data(str(self.app.language))
        self.refresh()
        if decoded:
            self.parse_and_display(decoded)

    def refresh(self) -> None:
        if self.all_weapon_parts_df is None:
            self.dataChanged.emit()
            return
        self._refresh_browser()
        self.dataChanged.emit()

    # ------------------------------------------------------------------ #
    # 本地化
    # ------------------------------------------------------------------ #
    def _loc(self, section, key, en, **fmt):
        text = self.ui_localization.get(section, {}).get(key) or en
        return text.format(**fmt) if fmt else text

    def get_localized_string(self, key, default=""):
        taxonomy_key = TAXONOMY_KEYS.get(str(key))
        if taxonomy_key:
            value = self.ui_localization.get("taxonomy", {}).get(taxonomy_key)
            if value:
                return value
        for section in ("labels", "buttons", "dialogs", "misc"):
            value = self.ui_localization.get(section, {}).get(key)
            if value:
                return value
        return self.weapon_localization.get(key, default or key)

    def _rule_message(self, key, zh, en, **fmt):
        fallback = zh if self.current_lang == "zh-CN" else en
        text = self.weapon_rule_loc.get(key, fallback)
        return text.format(**fmt) if fmt else text

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
    # QML 属性
    # ------------------------------------------------------------------ #
    @pyqtProperty(bool, notify=dataChanged)
    def dataLoaded(self) -> bool:
        return self.all_weapon_parts_df is not None

    @pyqtProperty(str, notify=dataChanged)
    def loadErrorText(self) -> str:
        return getattr(self, "_data_error", "")

    @pyqtProperty(list, notify=dataChanged)
    def browserItems(self) -> list[dict[str, Any]]:
        return self._browser_items

    @pyqtProperty(str, notify=dataChanged)
    def browserSearch(self) -> str:
        return self._browser_search

    @pyqtProperty(str, notify=dataChanged)
    def selectedSummary(self) -> str:
        return self._summary

    @pyqtProperty(str, notify=dataChanged)
    def b85Text(self) -> str:
        return self._b85

    @pyqtProperty(bool, notify=dataChanged)
    def b85Readonly(self) -> bool:
        return self._b85_readonly

    @pyqtProperty(str, notify=dataChanged)
    def decodedText(self) -> str:
        return self._decoded

    @pyqtProperty(str, notify=dataChanged)
    def manufacturerText(self) -> str:
        return self._manufacturer

    @pyqtProperty(str, notify=dataChanged)
    def weaponTypeText(self) -> str:
        return self._weapon_type

    @pyqtProperty(list, notify=dataChanged)
    def rarityOptions(self) -> list[str]:
        return [self.get_localized_string(r) for r in _RARITY_UI]

    @pyqtProperty(int, notify=dataChanged)
    def rarityIndex(self) -> int:
        return self._rarity_index

    @pyqtProperty(str, notify=dataChanged)
    def rarityText(self) -> str:
        return self._rarity_text

    @pyqtProperty(bool, notify=dataChanged)
    def rarityEditable(self) -> bool:
        return self._rarity_editable

    @pyqtProperty(str, notify=dataChanged)
    def levelText(self) -> str:
        return self._level

    @pyqtProperty(str, notify=dataChanged)
    def seedText(self) -> str:
        return self._seed

    @pyqtProperty(str, notify=dataChanged)
    def weaponNameText(self) -> str:
        return self._weapon_name

    @pyqtProperty(list, notify=dataChanged)
    def statsPreview(self) -> list[dict[str, str]]:
        return self._stats

    @pyqtProperty("QVariantMap", notify=dataChanged)
    def legalityBadge(self) -> dict[str, Any]:
        return self._legality

    @pyqtProperty(list, notify=dataChanged)
    def partRows(self) -> list[dict[str, Any]]:
        return self._part_rows

    @pyqtProperty(bool, notify=dataChanged)
    def hasSelection(self) -> bool:
        return self.selected_weapon_path is not None

    @pyqtProperty(bool, notify=dataChanged)
    def hasDecoded(self) -> bool:
        return bool(self._decoded.strip())

    @pyqtProperty(list, notify=dataChanged)
    def flagOptions(self) -> list[dict[str, Any]]:
        return [{"label": label, "value": label.split(" ", 1)[0]} for label in self._flag_labels]

    @pyqtProperty(int, notify=dataChanged)
    def flagIndex(self) -> int:
        return self._flag_index

    @pyqtProperty(bool, notify=dataChanged)
    def showInternalNames(self) -> bool:
        return self._show_internal

    @pyqtProperty(list, notify=dataChanged)
    def skinOptions(self) -> list[dict[str, str]]:
        if self._skin_options:
            return self._skin_options
        options = []
        for _, row in self.skin_df.iterrows():
            skin_name = row[self.skin_stat_col] if pd.notna(row.get(self.skin_stat_col)) else row["Stat"]
            options.append({
                "id": str(row["Skin_ID"]),
                "label": f"{row['Skin_ID']}: {self.get_localized_string(skin_name, skin_name)}",
            })
        self._skin_options = options
        return options

    # ------------------------------------------------------------------ #
    # 背包浏览
    # ------------------------------------------------------------------ #
    def _refresh_browser(self) -> None:
        try:
            items = self.controller.get_all_items() or []
        except Exception:
            items = []
        weapons = [i for i in items if i.get("type_en") in _WEAPON_TYPES and "Backpack" in i.get("container", "")]
        rows = []
        unknown = self._loc("parts", "unknown", "Unknown")
        for weapon in weapons:
            try:
                header, component = weapon.get("decoded_full", "").split("||", 1)
                m_id = int(header.strip().split("|")[0].strip().split(",")[0])
                parsed = self._parse_component_string(component)
                _, name, _, _ = self._get_rarity_and_weapon_name(parsed, m_id, weapon.get("decoded_full", ""))
                w_name = self.get_localized_string(name, name)
                manufacturer = weapon.get("manufacturer") or unknown
                weapon_type = weapon.get("type") or self._loc("parts", "unknown_item", "Unknown Item")
                unknown_names = {"N/A", "Unknown", "未知", "Неизвестно", "Невідомо", unknown}
                disp_name = (f"{manufacturer} {weapon_type} ({w_name})"
                             if w_name not in unknown_names else f"{manufacturer} {weapon_type}")
                detail = (f"{self.get_localized_string('level_label')} {weapon.get('level', 'N/A')}  ·  "
                          f"{self.get_localized_string('slot_label')} {weapon.get('slot', 'N/A').replace('slot_', '')}")
                stats = item_display_resolver.resolve_weapon_stats(weapon.get("decoded_full", "") or "")
                stat_titles = self.ui_localization.get("stats", {})
                rows.append({
                    "title": disp_name,
                    "detail": detail,
                    "level": str(weapon.get("level", "")),
                    "searchText": f"{weapon.get('name', '')} {disp_name} {detail}".casefold(),
                    "stats": [{
                        "label": stat_titles.get(key, key.replace("_", " ").title()),
                        "value": str(item_display_resolver.format_weapon_stat(
                            key, stats.get(key), self.current_lang) or "—"),
                    } for key in ("damage", "accuracy", "fire_rate", "reload_time", "magazine")],
                    "original_path": [str(p) for p in (weapon.get("original_path") or [])],
                    "selected": weapon.get("original_path") == self.selected_weapon_path,
                    "_item": weapon,
                })
            except Exception:
                continue
        self._browser_items = rows
        self._update_summary()

    @pyqtSlot(str)
    def setBrowserSearch(self, text: str) -> None:
        self._browser_search = text
        self.dataChanged.emit()

    @pyqtProperty(list, notify=dataChanged)
    def browserRows(self) -> list[dict[str, Any]]:
        query = self._browser_search.strip().casefold()
        if not query:
            return self._browser_items
        return [row for row in self._browser_items if query in row["searchText"]]

    @pyqtSlot(int)
    def loadBrowserItem(self, row: int) -> None:
        rows = self.browserRows
        if not 0 <= row < len(rows):
            return
        weapon = rows[row]["_item"]
        self.load_weapon_data(weapon)

    @pyqtSlot(int)
    def copyBrowserSerial(self, row: int) -> None:
        """Ctrl+C 复制背包浏览列表选中武器的 Base85 序列。"""
        rows = self.browserRows
        if not 0 <= row < len(rows):
            return
        serial = str(rows[row]["_item"].get("serial", "") or "")
        if serial:
            QApplication.clipboard().setText(serial)

    @pyqtSlot(int)
    def copyPartText(self, index: int) -> None:
        """Ctrl+C 复制部件列表选中行的显示文本（名称 + 内部名，组行取标题）。"""
        row = next((r for r in self._part_rows if r["index"] == index), None)
        if row is None:
            return
        if row["kind"] == "group":
            text = row["title"]
        else:
            text = "  ".join(v for v in (row["name"], row["internal"]) if v)
        if text:
            QApplication.clipboard().setText(text)

    # ------------------------------------------------------------------ #
    # 载入 / 解析
    # ------------------------------------------------------------------ #
    def load_weapon_data(self, weapon_data: dict) -> None:
        if not weapon_data:
            return
        self.selected_weapon_path = weapon_data.get("original_path")
        self.is_handling_change = True
        self._b85 = str(weapon_data.get("serial", "") or "")
        decoded_str = str(weapon_data.get("decoded_full", "") or "")
        self.is_handling_change = False
        if not decoded_str:
            self.app.toast(self.get_localized_string("no_valid_decoded_data"), "error")
            return
        self.parse_and_display(decoded_str)
        self._b85_readonly = True
        self._refresh_browser()
        self.dataChanged.emit()

    def open_roll_result(self, result: dict) -> None:
        """God Roll「在武器编辑器打开」：按生成结果载入（对齐 handle_open_generated_weapon）。"""
        decoded = str(result.get("decoded") or "")
        serial = str(result.get("serial") or "")
        if not decoded:
            raise ValueError("empty roll result")
        self.selected_weapon_path = None
        self.is_handling_change = True
        self._b85 = serial
        self.is_handling_change = False
        self.parse_and_display(decoded)
        self._b85_readonly = True
        self._refresh_browser()
        self.dataChanged.emit()

    def parse_and_display(self, decoded_str: str) -> None:
        try:
            header = bl4f.parse_decoded_item_header(decoded_str)
            if not header:
                raise ValueError("Invalid decoded item header")
            m_id, level = header["mfg_id"], header["level"]
            component_part = header["component"]
            m_info = self.all_weapon_parts_df[
                self.all_weapon_parts_df["Manufacturer & Weapon Type ID"] == m_id].iloc[0]
            self.is_handling_change = True
            self._decoded = decoded_str
            self._manufacturer = self.get_localized_string(m_info["Manufacturer"])
            self._weapon_type = self.get_localized_string(m_info["Weapon Type"])
            self._level = str(level)
            self._seed = str(header["seed"]) if header["seed"] is not None else ""

            temp_parts = self._parse_component_string(component_part)
            display_rarity, weapon_name, self.rarity_part, remaining_parts = (
                self._get_rarity_and_weapon_name(temp_parts, m_id, decoded_str))

            rarity_parts = display_rarity.split(" - ")
            base_rarity, localized_base = rarity_parts[0], self.get_localized_string(rarity_parts[0])
            final_display = (f"{localized_base} - {self.get_localized_string(rarity_parts[1], rarity_parts[1])}"
                             if len(rarity_parts) > 1 else localized_base)

            if base_rarity in {"Legendary", "Pearl"}:
                self._rarity_editable = False
                self._rarity_text = final_display
                self._rarity_index = -1
            else:
                self._rarity_editable = True
                self._rarity_text = ""
                options = self.rarityOptions
                self._rarity_index = options.index(localized_base) if localized_base in options else -1

            name_label = self.get_localized_string("weapon_name_label")
            self._weapon_name = f"{name_label} {weapon_name}"
            self.parts_data = remaining_parts
            self._group_collapsed = set()
            self.is_handling_change = False
            self._update_stats_and_legality()
            self._rebuild_part_rows(m_id)
        except Exception as exc:
            self.app.toast(f"{self.get_localized_string('parse_weapon_error')}: {exc}", "error")
            self.clear_all_fields()
        self.dataChanged.emit()

    def clear_all_fields(self) -> None:
        self.is_handling_change = True
        self._decoded = ""
        self._b85 = ""
        self._b85_readonly = False
        self._manufacturer = ""
        self._weapon_type = ""
        self._rarity_index = -1
        self._rarity_text = ""
        self._rarity_editable = True
        self._level = ""
        self._seed = ""
        self._weapon_name = self.get_localized_string("weapon_name_label")
        self._stats = []
        self._legality = {"text": "—", "status": "unknown", "tooltip": ""}
        self._part_rows = []
        self.selected_weapon_path = None
        self.parts_data = []
        self.rarity_part = None
        self.is_handling_change = False
        self._update_summary()
        self.dataChanged.emit()

    def _get_rarity_and_weapon_name(self, parts, m_id, decoded_str=""):
        rarity, weapon_name, rarity_part, display_rarity, remaining_parts = (
            "Unknown", "Unknown", None, "Unknown", list(parts))
        for p in parts:
            if not isinstance(p, dict) or p.get("type") != "simple":
                continue
            part_id = p.get("id")
            if not part_id:
                continue
            part_details = self.all_weapon_parts_df[
                (self.all_weapon_parts_df["Manufacturer & Weapon Type ID"] == m_id)
                & (self.all_weapon_parts_df["Part ID"] == part_id)]
            if not part_details.empty and part_details.iloc[0]["Part Type"] == "Barrel":
                part_name = item_display_resolver.weapon_part_name(
                    m_id, part_id, self.current_lang, part_details.iloc[0])
                if part_name:
                    weapon_name = part_name
                    if weapon_name.endswith(" Barrel"):
                        weapon_name = weapon_name[:-len(" Barrel")]
                    break
        simple_parts = [p for p in parts if isinstance(p, dict) and p.get("type") == "simple"]
        if simple_parts and "id" in simple_parts[0]:
            rarity_info = self.weapon_rarity_df[
                (self.weapon_rarity_df["Manufacturer & Weapon Type ID"] == m_id)
                & (self.weapon_rarity_df["Part ID"] == simple_parts[0]["id"])]
            if not rarity_info.empty:
                details = rarity_info.iloc[0]
                rarity, desc = details["Stat"], details[self.rarity_desc_col]
                display_rarity = (f"{rarity} - {desc}" if rarity in {"Legendary", "Pearl"}
                                  and pd.notna(desc) and desc else rarity)
                rarity_part = simple_parts[0]
        if not rarity_part:
            display_rarity = rarity = "Legendary"
        pearl_ids = set(range(51, 61))
        if any(
            p.get("id") == 1
            and (p.get("sub_id") in pearl_ids or bool(pearl_ids.intersection(p.get("sub_ids", []))))
            for p in parts if isinstance(p, dict) and p.get("type") in {"elemental", "group"}
        ):
            suffix = display_rarity.split(" - ", 1)[1] if " - " in display_rarity else ""
            rarity = "Pearl"
            display_rarity = f"Pearl - {suffix}" if suffix else "Pearl"
        if rarity_part:
            remaining_parts = [p for p in remaining_parts if p is not rarity_part]
        if decoded_str:
            m_rows = self.all_weapon_parts_df[
                self.all_weapon_parts_df["Manufacturer & Weapon Type ID"] == m_id]
            if not m_rows.empty:
                m_info = m_rows.iloc[0]
                display = item_display_resolver.resolve_item_display(
                    m_id, str(m_info["Manufacturer"]), str(m_info["Weapon Type"]),
                    decoded_str, self.current_lang)
                if display.get("display_source") != "fallback" and display.get("display_name"):
                    weapon_name = display["display_name"]
        return display_rarity, weapon_name, rarity_part, remaining_parts

    def _parse_component_string(self, component_str):
        components, last_index = [], 0
        for match in re.finditer(r'\{(\d+)(?::(\d+|\[[\d\s]+\]))?\}|\"c\",\s*(?:(\d+)|\"([^\"]+)\")', component_str):
            components.append(component_str[last_index:match.start()])
            part_data = {"raw": match.group(0)}
            if match.group(3):
                part_data.update({"type": "skin", "id": int(match.group(3))})
            elif match.group(4):
                part_data.update({"type": "skin", "id": match.group(4)})
            else:
                outer_id, inner = int(match.group(1)), match.group(2)
                if inner:
                    part_data.update(
                        {"type": "group", "id": outer_id,
                         "sub_ids": [int(sid) for sid in inner.strip("[]").split()]}
                        if "[" in inner else
                        {"type": "elemental", "id": outer_id, "sub_id": int(inner)})
                else:
                    part_data.update({"type": "simple", "id": outer_id})
            components.append(part_data)
            last_index = match.end()
        components.append(component_str[last_index:])
        return [c for c in components if c]

    # ------------------------------------------------------------------ #
    # 序列号编辑
    # ------------------------------------------------------------------ #
    @pyqtSlot(str)
    def setB85Text(self, text: str) -> None:
        if self.is_handling_change:
            return
        self._b85 = text
        self.is_handling_change = True
        if not text.strip():
            self.clear_all_fields()
            self.is_handling_change = False
            self.dataChanged.emit()
            return
        decoded_str, _, err = decoder_logic.decode_serial_to_string(text.strip())
        if not err:
            self._b85_readonly = True
            self.is_handling_change = False
            self.parse_and_display(decoded_str)
        else:
            self._decoded = ""
            self.is_handling_change = False
            self.dataChanged.emit()

    @pyqtSlot(str)
    def setDecodedText(self, text: str) -> None:
        if self.is_handling_change:
            return
        if not text.strip():
            self.clear_all_fields()
            return
        new_b85, err = b_encoder.encode_to_base85(text.strip())
        self.is_handling_change = True
        if not err:
            self._b85 = new_b85
        self.is_handling_change = False
        self.parse_and_display(text.strip())

    @pyqtSlot(int)
    def setRarityIndex(self, index: int) -> None:
        if not self._rarity_editable or not 0 <= index < len(_RARITY_UI):
            return
        self._rarity_index = index
        self._update_decoded_from_ui()

    @pyqtSlot(str)
    def setLevelText(self, text: str) -> None:
        self._level = text
        self._update_decoded_from_ui()

    @pyqtSlot(str)
    def setSeedText(self, text: str) -> None:
        self._seed = text
        self._update_decoded_from_ui()

    @pyqtSlot()
    def randomizeSeed(self) -> None:
        self._seed = str(random.randint(100, 9999))
        self._update_decoded_from_ui()
        self.dataChanged.emit()

    def _update_decoded_from_ui(self) -> None:
        if self.is_handling_change or not self._decoded:
            return
        try:
            updated_str = bl4f.update_level_in_decoded_str(self._decoded, self._level)
            parts = updated_str.split("|")
            if len(parts) > 1 and len(parts[1].split(",")) > 1:
                seed_parts = parts[1].split(",")
                seed_parts[1] = f" {self._seed}"
                parts[1] = ",".join(seed_parts)
                updated_str = "|".join(parts)

            if self.rarity_part and self._rarity_editable and self._rarity_index >= 0:
                rarity_en = _RARITY_UI[self._rarity_index]
                m_id = int(updated_str.split("||")[0].strip().split("|")[0].strip().split(",")[0])
                info = self.weapon_rarity_df[
                    (self.weapon_rarity_df["Manufacturer & Weapon Type ID"] == m_id)
                    & (self.weapon_rarity_df["Stat"] == rarity_en)
                    & (self.weapon_rarity_df["Part Type"] == "Rarity")]
                if not info.empty:
                    new_id = info.iloc[0]["Part ID"]
                    updated_str = updated_str.replace(self.rarity_part["raw"], f"{{{new_id}}}")
                    self.rarity_part["id"], self.rarity_part["raw"] = new_id, f"{{{new_id}}}"

            if updated_str != self._decoded:
                self.is_handling_change = True
                self._decoded = updated_str
                new_b85, err = b_encoder.encode_to_base85(updated_str)
                if not err:
                    self._b85 = new_b85
                self.is_handling_change = False
                self._update_stats_and_legality()
                self.dataChanged.emit()
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # 属性 / 合法性
    # ------------------------------------------------------------------ #
    def _update_stats_and_legality(self) -> None:
        stats = item_display_resolver.resolve_weapon_stats(self._decoded) if self._decoded else {}
        stats_loc = self.ui_localization.get("stats", {})
        self._stats = [{
            "key": key,
            "label": stats_loc.get(key, key.replace("_", " ").title()),
            "value": str(item_display_resolver.format_weapon_stat(key, stats.get(key), self.current_lang) or "—"),
        } for key in item_display_resolver.WEAPON_STAT_KEYS]
        self._update_legality()

    def _update_legality(self, force: bool = False) -> None:
        decoded = self._decoded.strip()
        if not decoded:
            result = {"status": "unknown", "violations": []}
        else:
            try:
                result = item_display_resolver.validate_weapon_generation(decoded, allow_incomplete=True)
            except Exception as exc:
                result = {"status": "unknown", "violations": [{"code": "validation_failed", "part": str(exc)}]}
        status = str(result.get("status") or "unknown").casefold()
        labels = {
            "legal": ("status_legal", "自然生成", "Natural"),
            "conditional": ("status_conditional", "条件限定", "Conditional"),
            "incomplete": ("status_incomplete", "待补全", "Incomplete"),
            "modified": ("status_modified", "魔改", "Modified"),
            "unknown": ("status_unknown", "无法验证", "Unknown"),
        }
        label = self._rule_message(*labels.get(status, labels["unknown"]))
        reasons = self._legality_reason_lines(result)
        short = reasons[0] if reasons else ""
        if len(short) > 36:
            short = short[:35] + "…"
        tooltip = [label]
        tooltip.extend(f"• {line}" for line in reasons)
        if not reasons:
            tooltip.append(self._rule_message(
                "matches_rules" if status == "legal" else "no_weapon",
                "符合当前自然生成规则" if status == "legal" else "尚未载入可验证武器",
                "Matches the current generation rules" if status == "legal" else "No verifiable weapon loaded"))
        self._legality = {
            "text": f"{label} · {short}" if short else label,
            "status": status,
            "tooltip": "\n".join(tooltip),
        }

    def _generation_group_text(self, group):
        raw = GENERATION_GROUP_TYPES.get(str(group).casefold())
        return self.get_localized_string(raw, raw) if raw else str(group).replace("_", " ").title()

    def _generation_ref_text(self, ref, group=""):
        root, sep, part_id = str(ref).partition(":")
        name = item_display_resolver.weapon_part_name(
            int(root), part_id, self.current_lang) if sep and root.isdigit() else ""
        return name or f"{self._generation_group_text(group)} [{ref}]"

    def _generation_ref_list(self, refs, group="", limit=2):
        values = list(dict.fromkeys(map(str, refs or [])))
        text = self._rule_message("list_separator", "、", ", ").join(
            self._generation_ref_text(ref, group) for ref in values[:limit])
        if len(values) > limit:
            text += self._rule_message("more_items", "，另{count}个", " +{count}",
                                       count=len(values) - limit)
        return text

    @staticmethod
    def _generation_group_for_ref(result, ref):
        for group, rule in (result.get("groups") or {}).items():
            if ref in set(rule.get("allowed") or []) | set(rule.get("selected") or []):
                return group
        return ""

    def _legality_violation_text(self, violation, result):
        code = str(violation.get("code") or "unknown")
        group = str(violation.get("group") or "")
        group_text = self._generation_group_text(group) if group else ""
        actual = violation.get("actual", violation.get("count"))

        if code == "count_above":
            return self._rule_message(
                "too_many_group", "{group}过多（{actual}/{max}）", "Too many {group} ({actual}/{max})",
                group=group_text, actual=actual, max=violation.get("max"), suffix="")
        if code == "count_below":
            eligible = (result.get("groups", {}).get(group) or {}).get("remaining_eligible_refs", [])
            choices = self._generation_ref_list(eligible, group)
            suffix = self._rule_message(
                "eligible_suffix", "，可选：{parts}", "; eligible: {parts}", parts=choices) if choices else ""
            return self._rule_message(
                "missing_group", "缺少{group}（{actual}/{min}）{suffix}",
                "Missing {group} ({actual}/{min}){suffix}",
                group=group_text, actual=actual, min=violation.get("min"), suffix=suffix)
        if code == "tag_count_below":
            return self._rule_message(
                "missing_combination", "缺少要求的配件组合（{actual}/{min}）",
                "Missing required part combination ({actual}/{min})",
                actual=actual, min=violation.get("min"))
        if code == "duplicate_part":
            counts = Counter(result.get("selected_part_refs") or [])
            refs = violation.get("parts") or []
            names = self._rule_message("list_separator", "、", ", ").join(
                f"{self._generation_ref_text(ref, self._generation_group_for_ref(result, ref))} ×{counts.get(ref, 2)}"
                for ref in refs[:2])
            return self._rule_message("duplicate_part", "重复配件：{parts}", "Duplicate part: {parts}", parts=names)
        if code == "part_not_allowed":
            names = self._generation_ref_list(violation.get("parts") or [], group)
            return self._rule_message(
                "not_allowed", "当前组合不允许：{parts}", "Not allowed by this composition: {parts}", parts=names)
        if code == "foreign_root_part":
            name = self._generation_ref_text(violation.get("part", ""))
            foreign_kind = str(violation.get("foreign_kind") or "")
            other = item_display_resolver.root_kind_label(
                str(violation.get("part", "")).partition(":")[0], self.current_lang)
            own_root = str(result.get("root_ref") or "")
            own = item_display_resolver.root_kind_label(own_root, self.current_lang) if own_root else ""
            if foreign_kind == "manufacturer":
                return self._rule_message(
                    "foreign_part_manufacturer",
                    "跨厂商配件（本物品为{own}，配件来自{other}）：{part}",
                    "Cross-manufacturer part (this item is {own}, part is from {other}): {part}",
                    own=own, other=other, part=name)
            if foreign_kind == "type":
                return self._rule_message(
                    "foreign_part_type",
                    "跨类型配件（本物品为{own}，配件来自{other}）：{part}",
                    "Cross-type part (this item is {own}, part is from {other}): {part}",
                    own=own, other=other, part=name)
            return self._rule_message("foreign_part", "跨来源配件：{part}", "Part from another item: {part}", part=name)
        if code == "forced_part_missing":
            names = self._generation_ref_list(violation.get("parts") or [])
            return self._rule_message(
                "missing_intrinsic", "缺少固有配件：{parts}", "Missing intrinsic part: {parts}", parts=names)
        if code == "missing_required_tag":
            part = self._generation_ref_text(violation.get("part", ""), group)
            required = set(map(str, violation.get("tags") or []))
            providers = []
            for rule in result.get("groups", {}).values():
                for ref in rule.get("allowed", []):
                    root, sep, part_id = str(ref).partition(":")
                    if sep and root.isdigit() and required.intersection(
                        item_display_resolver.weapon_part_selection_tags(int(root), part_id).get("adds", [])
                    ):
                        providers.append(ref)
            choices = self._generation_ref_list(providers)
            if choices:
                return self._rule_message("requires", "{part}缺少前置：{parts}", "{part} requires {parts}",
                                          part=part, parts=choices)
            return self._rule_message(
                "unmet_dependency", "{part}的前置条件未满足", "{part} has an unmet dependency", part=part)
        if code == "excluded_tag_conflict":
            refs = violation.get("parts") or ([violation.get("part")] if violation.get("part") else [])
            names = self._generation_ref_list(refs)
            return self._rule_message(
                "conflicting_parts", "配件搭配互斥：{parts}", "Conflicting parts: {parts}", parts=names)
        if code == "tag_limit":
            bucket = set(map(str, violation.get("tags") or []))
            contributors = []
            for ref in result.get("selected_part_refs") or []:
                root, sep, part_id = str(ref).partition(":")
                if sep and root.isdigit() and bucket.intersection(
                    item_display_resolver.weapon_part_selection_tags(int(root), part_id).get("adds", [])
                ):
                    contributors.append(ref)
            names = self._generation_ref_list(contributors)
            suffix = (f"：{names}" if self.current_lang == "zh-CN" else f": {names}") if names else ""
            return self._rule_message(
                "too_many_tagged", "同类授权配件过多（{actual}/{max}）{suffix}",
                "Too many tagged parts ({actual}/{max}){suffix}",
                actual=actual, max=violation.get("max"), suffix=suffix)
        if code == "multiple_compositions":
            names = self._generation_ref_list(violation.get("parts") or [])
            return self._rule_message(
                "multiple_compositions", "同时存在多个武器模板：{parts}", "Multiple compositions: {parts}", parts=names)
        if code in {"conditional_availability"}:
            return self._rule_message(
                "conditional_availability", "仅限特定投放条件", "Available only under special conditions")
        if code in {"selection_order_unchecked"}:
            return self._rule_message(
                "selection_order_unchecked", "配件过多，依赖顺序未完全验证",
                "Too many parts to verify dependency order")
        if code in {
            "invalid_serial", "rules_unavailable", "weapon_rules_missing", "unknown_composition",
            "unknown_part", "unresolved_rule_parts", "inheritance_cycle", "validation_failed",
        }:
            return self._rule_message(
                "cannot_validate", "无法验证：生成规则未覆盖", "Cannot validate: generation rules are incomplete")
        return code.replace("_", " ").title()

    def _legality_reason_lines(self, result):
        priority = {
            "foreign_root_part": 0, "part_not_allowed": 1, "multiple_compositions": 1,
            "duplicate_part": 2, "count_above": 3, "tag_limit": 3,
            "missing_required_tag": 4, "excluded_tag_conflict": 4,
            "count_below": 5, "forced_part_missing": 5, "tag_count_below": 5,
            "conditional_availability": 6,
        }
        ordered = sorted(result.get("violations") or [], key=lambda item: priority.get(item.get("code"), 9))
        return list(dict.fromkeys(self._legality_violation_text(item, result) for item in ordered))

    # ------------------------------------------------------------------ #
    # 部件行模型
    # ------------------------------------------------------------------ #
    def _internal_part_name(self, owner_id, part_id, raw_type):
        if not self._show_internal or raw_type in INTERNAL_NAME_SKIP_TYPES:
            return ""
        return item_display_resolver.weapon_part_internal(owner_id, part_id)

    def _elemental_part_type(self, row) -> str:
        stat = str(row["Stat"])
        if stat.startswith("Pearl Stat"):
            return "Pearl Stat"
        if stat.startswith("Pearl Elements"):
            return "Pearl Elements"
        if stat.startswith("Maliwan Underbarrel-switch"):
            return "Underbarrel Element Switch"
        if stat.startswith("switch between"):
            return "Element Switch"
        return "Element"

    def _part_color(self, raw_type: str) -> str:
        return PART_TYPE_COLORS.get(raw_type, "#e0e0e0")

    def _simple_part_info(self, part_info, m_id, index):
        part_id = part_info.get("id")
        info = {
            "type": self._loc("parts", "unknown", "Unknown"),
            "raw_type": "Unknown",
            "str": "",
            "stat": self._loc("parts", "no_stat_changes", "No stat changes"),
        }
        is_skin = part_info.get("type") == "skin"
        is_elemental = part_info.get("type") == "elemental"
        if is_skin:
            d = self.skin_df[self.skin_df["Skin_ID"].str.lower() == str(part_id).lower()]
            if not d.empty:
                info.update({
                    "type": self.get_localized_string("Skin"), "raw_type": "Skin",
                    "str": d.iloc[0][self.skin_stat_col],
                    "stat": self._loc("parts", "cosmetic_part", "Cosmetic part"),
                })
        elif is_elemental:
            d = self.elemental_df[self.elemental_df["Part_ID"] == part_info["sub_id"]]
            if not d.empty:
                row = d.iloc[0]
                raw_type = self._elemental_part_type(row)
                description = item_display_resolver.format_weapon_part_description(
                    1, str(part_info["sub_id"]), self._decoded, self.current_lang, "Elemental")
                no_change = description in {"无属性变化", "No stat changes"}
                info.update({
                    "type": self.get_localized_string(raw_type),
                    "raw_type": raw_type,
                    "str": row[self.elemental_stat_col],
                    "stat": self._loc("parts", "element_config", "Element configuration") if no_change else description,
                })
        else:
            d = self.all_weapon_parts_df[
                (self.all_weapon_parts_df["Manufacturer & Weapon Type ID"] == m_id)
                & (self.all_weapon_parts_df["Part ID"] == part_id)]
            if not d.empty:
                row = d.iloc[0]
                name = item_display_resolver.weapon_part_name(m_id, part_id, self.current_lang, row)
                description = item_display_resolver.format_weapon_part_description(
                    m_id, part_id, self._decoded, self.current_lang, str(row["Part Type"]))
                info.update({
                    "type": self.get_localized_string(row["Part Type"]),
                    "raw_type": str(row["Part Type"]),
                    "str": name or (self._loc("parts", "unnamed_barrel", "Unnamed Barrel")
                                    if str(row["Part Type"]) == "Barrel" else ""),
                    "stat": description,
                })
        internal = "" if is_skin or is_elemental else self._internal_part_name(m_id, part_id, info["raw_type"])
        id_text = f"  {part_id}  " if not is_elemental else f"  {part_info['id']}:{part_info['sub_id']}  "
        return {**info, "internal": internal, "idText": id_text, "isSkin": is_skin}

    def _rebuild_part_rows(self, m_id) -> None:
        rows = []
        for index, part_info in enumerate(self.parts_data):
            if isinstance(part_info, str):
                continue
            if part_info.get("type") == "group":
                group_id = part_info.get("id", 0)
                mfg_name = self._loc("parts", "unknown_manufacturer", "Unknown Manufacturer")
                if group_id != 1:
                    try:
                        mfg_name = self.get_localized_string(
                            self.all_weapon_parts_df[
                                self.all_weapon_parts_df["Manufacturer & Weapon Type ID"] == group_id
                            ].iloc[0]["Manufacturer"])
                    except (IndexError, KeyError):
                        pass
                if group_id == 1:
                    title = self._loc("parts", "element_group", "Element Configuration Group · {n} parts",
                                      n=len(part_info.get("sub_ids", [])))
                else:
                    title = self._loc("parts", "licensed_group", "Licensed Part Group · {mfg} · {n} parts",
                                      mfg=mfg_name, n=len(part_info.get("sub_ids", [])))
                subs = []
                for sub_id in part_info.get("sub_ids", []):
                    p_type = self._loc("parts", "unknown", "Unknown")
                    p_str = ""
                    p_stat = self._loc("parts", "no_stat_changes", "No stat changes")
                    if group_id == 1:
                        d = self.elemental_df[
                            (self.elemental_df["Elemental_ID"] == group_id)
                            & (self.elemental_df["Part_ID"] == sub_id)]
                        if not d.empty:
                            row = d.iloc[0]
                            description = item_display_resolver.format_weapon_part_description(
                                group_id, str(sub_id), self._decoded, self.current_lang, "Elemental")
                            p_type = self.get_localized_string(self._elemental_part_type(row))
                            p_str = str(row[self.elemental_stat_col])
                            p_stat = (self._loc("parts", "element_config", "Element configuration")
                                      if description in {"无属性变化", "No stat changes"} else description)
                    else:
                        d = self.all_weapon_parts_df[
                            (self.all_weapon_parts_df["Manufacturer & Weapon Type ID"] == group_id)
                            & (self.all_weapon_parts_df["Part ID"] == sub_id)]
                        if not d.empty:
                            row = d.iloc[0]
                            name = item_display_resolver.weapon_part_name(group_id, sub_id, self.current_lang, row)
                            description = item_display_resolver.format_weapon_part_description(
                                group_id, sub_id, self._decoded, self.current_lang, str(row["Part Type"]))
                            p_type = self.get_localized_string(row["Part Type"])
                            p_str = name or (self._loc("parts", "unnamed_barrel", "Unnamed Barrel")
                                             if str(row["Part Type"]) == "Barrel" else "")
                            p_stat = description
                    raw_type = "Elemental" if group_id == 1 or d.empty else str(row["Part Type"])
                    internal = "" if group_id == 1 else self._internal_part_name(group_id, sub_id, raw_type)
                    subs.append({
                        "idText": f"  {sub_id}  ",
                        "name": " · ".join(v for v in (p_type, p_str) if v),
                        "internal": internal,
                        "stat": str(p_stat),
                        "color": self._part_color(raw_type),
                    })
                rows.append({
                    "index": index, "kind": "group", "title": title,
                    "expanded": index not in self._group_collapsed,
                    "subs": subs, "isSkin": False,
                })
            else:
                info = self._simple_part_info(part_info, m_id, index)
                rows.append({
                    "index": index, "kind": "simple",
                    "idText": info["idText"],
                    "typeText": info["type"],
                    "color": self._part_color(info["raw_type"]),
                    "name": info["str"],
                    "internal": info["internal"],
                    "stat": str(info["stat"]) if pd.notna(info["stat"]) else "",
                    "isSkin": info["isSkin"],
                    "expanded": True, "subs": [],
                })
        self._part_rows = rows

    # ------------------------------------------------------------------ #
    # 部件操作
    # ------------------------------------------------------------------ #
    def _regenerate_serial(self) -> None:
        if "||" not in self._decoded:
            return
        header_part, _ = self._decoded.split("||", 1)
        try:
            m_id = int(header_part.strip().split("|")[0].strip().split(",")[0])
        except (ValueError, IndexError):
            return
        new_component_list = ([self.rarity_part["raw"]] if self.rarity_part else []) + [
            p["raw"] if isinstance(p, dict) else p for p in self.parts_data]
        new_component_str = re.sub(r"\s{2,}", " ", " ".join(new_component_list).strip())
        self.is_handling_change = True
        self._decoded = f"{header_part.strip()}|| {new_component_str}"
        new_b85, err = b_encoder.encode_to_base85(self._decoded)
        if not err:
            self._b85 = new_b85
        self.is_handling_change = False
        self._update_stats_and_legality()
        self._rebuild_part_rows(m_id)
        self.dataChanged.emit()

    @pyqtSlot(int, int)
    def movePart(self, index: int, direction: int) -> None:
        if not (0 <= index < len(self.parts_data)) or not isinstance(self.parts_data[index], dict):
            return
        target = index + direction
        while 0 <= target < len(self.parts_data) and not isinstance(self.parts_data[target], dict):
            target += direction
        if not 0 <= target < len(self.parts_data):
            return
        self.parts_data[index], self.parts_data[target] = self.parts_data[target], self.parts_data[index]
        self._regenerate_serial()

    @pyqtSlot(int)
    def deletePart(self, index: int) -> None:
        if 0 <= index < len(self.parts_data):
            self.parts_data.pop(index)
            self._regenerate_serial()

    @pyqtSlot(int)
    def toggleGroup(self, index: int) -> None:
        if index in self._group_collapsed:
            self._group_collapsed.discard(index)
        else:
            self._group_collapsed.add(index)
        self.dataChanged.emit()

    @pyqtSlot(bool)
    def setShowInternalNames(self, checked: bool) -> None:
        self._show_internal = bool(checked)
        self.app._settings.setValue("weapon_editor/show_internal_part_names", self._show_internal)
        if self._decoded:
            m_id = int(self._decoded.split("||", 1)[0].strip().split("|")[0].split(",")[0])
            self._rebuild_part_rows(m_id)
        self.dataChanged.emit()

    @pyqtSlot()
    def forceRefreshParts(self) -> None:
        if not self._decoded.strip():
            self.app.toast(self.get_localized_string("serial_empty"), "warning")
            return
        self.parse_and_display(self._decoded)
        self.app.toast(self.get_localized_string("parts_refresh_success"), "success")

    # ------------------------------------------------------------------ #
    # 写回 / 加入背包
    # ------------------------------------------------------------------ #
    @pyqtSlot()
    def updateWeapon(self) -> None:
        if not self.selected_weapon_path:
            self.app.toast(self.get_localized_string("select_weapon_first"), "warning")
            return
        new_serial, err = b_encoder.encode_to_base85(self._decoded.strip())
        if err:
            self.app.toast(f"{self.get_localized_string('cannot_reencode_serial')}: {err}", "error")
            return
        payload = {
            "item_path": list(self.selected_weapon_path),
            "original_item_data": {},
            "new_item_data": {"serial": new_serial},
            "success_msg": self.get_localized_string("update_success"),
        }
        self.app.updateItem(payload)

    @pyqtSlot()
    def addNewWeaponToBackpack(self) -> None:
        new_decoded = self._decoded.strip()
        if not new_decoded:
            self.app.toast(self.get_localized_string("serial_empty"), "warning")
            return
        new_serial, err = b_encoder.encode_to_base85(new_decoded)
        if err:
            self.app.toast(f"{self.get_localized_string('cannot_encode_serial')}: {err}", "error")
            return
        self.app.addSerialToBackpack(new_serial, self._flag_value())

    @pyqtSlot(int)
    def setFlagIndex(self, index: int) -> None:
        if 0 <= index < len(self._flag_labels):
            self._flag_index = index
            self.dataChanged.emit()

    # ------------------------------------------------------------------ #
    # 皮肤
    # ------------------------------------------------------------------ #
    @pyqtSlot(result=int)
    def prepareSkinOptions(self) -> int:
        if not self._decoded.strip():
            self.app.toast(self.get_localized_string("load_weapon_first"), "warning")
            return 0
        return len(self.skinOptions)

    @pyqtSlot(int, str)
    def applySkin(self, part_index: int, skin_id: str) -> None:
        options = {o["id"] for o in self.skinOptions}
        if skin_id not in options:
            return
        is_text_id = not str(skin_id).isdigit()
        skin = {
            "type": "skin",
            "id": skin_id if is_text_id else int(skin_id),
            "raw": f'"c", "{skin_id}"' if is_text_id else f'"c", {int(skin_id)}',
        }
        target_index = part_index if part_index >= 0 else next(
            (i for i, part in enumerate(self.parts_data)
             if isinstance(part, dict) and part.get("type") == "skin"),
            None,
        )
        if target_index is not None and 0 <= target_index < len(self.parts_data):
            current = self.parts_data[target_index]
            if not isinstance(current, dict) or current.get("type") != "skin":
                self.app.toast(self._loc("dialogs", "invalid_skin_part",
                                         "The selected part is not a skin part."), "error")
                return
            self.parts_data[target_index] = skin
        else:
            self.parts_data.append(skin)
            self.parts_data.append("|")
        self._regenerate_serial()

    # ------------------------------------------------------------------ #
    # 添加配件目录（对齐 _add_part_catalog_items + 候选提示）
    # ------------------------------------------------------------------ #
    @staticmethod
    def _part_model_label(internal):
        match = re.search(r"part_barrel_(01|02)(?:_([^_]+))?(?:_([^_]+))?", str(internal or ""), re.I)
        if not match:
            return ""
        first, second = (match.group(2) or "").casefold(), (match.group(3) or "").casefold()
        variant = re.fullmatch(r"([a-d])x([a-d])", first)
        if variant:
            suffix = f"{variant.group(1).upper()}×{variant.group(2).upper()}"
        elif re.fullmatch(r"[a-d]", first):
            suffix = first.upper() + (f"×{second.upper()}" if re.fullmatch(r"[a-d]", second) else "")
        else:
            suffix = ""
        return f"B{match.group(1)}" + (f"-{suffix}" if suffix else "")

    def _part_model_for_ref(self, owner_id, part_id):
        label = self._part_model_label(item_display_resolver.weapon_part_internal(owner_id, part_id))
        if label:
            return label
        tags = item_display_resolver.weapon_part_selection_tags(owner_id, part_id)
        for tag in (*tags.get("adds", []), *tags.get("requires", [])):
            match = re.fullmatch(r"barrel_(01|02)", str(tag), re.I)
            if match:
                return f"B{match.group(1)}"
        return ""

    def _current_barrel_family(self):
        root = int(self._decoded.split("||", 1)[0].strip().split("|")[0].split(",")[0]) if self._decoded else 0
        try:
            selected = (
                item_display_resolver.weapon_generation_context(self._decoded)
                .get("groups", {}).get("barrel", {}).get("selected", [])
            )
        except Exception:
            selected = []
        if not selected:
            try:
                selected = item_display_resolver.weapon_generation_context(
                    self._decoded).get("selected_part_refs", [])
            except Exception:
                selected = []
        for ref in selected:
            owner, sep, part_id = str(ref).partition(":")
            if sep and owner.isdigit() and item_display_resolver.weapon_part_category(
                    int(owner), part_id) == "barrel":
                label = self._part_model_for_ref(int(owner), part_id)
                if label:
                    return label.split("-", 1)[0]
        for part in self.parts_data:
            if not isinstance(part, dict) or part.get("type") != "simple":
                continue
            rows = self.all_weapon_parts_df[
                (self.all_weapon_parts_df["Manufacturer & Weapon Type ID"] == root)
                & (self.all_weapon_parts_df["Part ID"] == part.get("id"))]
            if rows.empty or str(rows.iloc[0]["Part Type"]) != "Barrel":
                continue
            label = self._part_model_for_ref(root, part.get("id"))
            if label:
                return label.split("-", 1)[0]
        return ""

    def _model_context(self, model, current=""):
        family = str(model or "").split("-", 1)[0]
        current = current or self._current_barrel_family()
        if not family or not current:
            return "", ""
        if family == current:
            return "same", self._loc("catalog", "same_model", "Same model as current barrel ({model})",
                                     model=current)
        return "cross", self._loc(
            "catalog", "cross_model", "Cross-model part: current {current}, candidate {candidate}",
            current=current, candidate=family)

    def _decorate_model_context(self, source):
        current = self._current_barrel_family()
        for item in source:
            model = str(item.get("_model") or "")
            kind, hint = self._model_context(model, current)
            item["model_kind"], item["model_hint"] = kind, hint
            if hint:
                badge = self._loc(
                    "catalog", "same_model_badge" if kind == "same" else "cross_model_badge",
                    "Same {model}" if kind == "same" else "Cross {model}", model=model.split("-", 1)[0])
                item["badges"] = [badge, *(item.get("badges") or [])]
        source.sort(key=lambda item: {"same": 0, "": 1, "cross": 2}.get(item.get("model_kind", ""), 1))

    @staticmethod
    def _generation_count_range(minimum, maximum):
        minimum, maximum = int(minimum), int(maximum)
        return str(minimum) if minimum == maximum else f"{minimum}–{maximum}"

    def _generation_candidate_condition_text(self, ref, group, context):
        if ref in set((context.get("groups", {}).get(group) or {}).get("tag_limited_refs") or []):
            return self._rule_message(
                "violation_tag_limit", "授权类配件超过上限", "Tagged part count exceeds the limit")
        root, sep, part_id = str(ref).partition(":")
        if not sep or not root.isdigit():
            return ""
        candidate_tags = item_display_resolver.weapon_part_selection_tags(int(root), part_id)
        required = set(candidate_tags.get("requires", []))
        excluded = set(candidate_tags.get("excludes", []))
        ordered_groups = list(dict.fromkeys(map(str, context.get("part_types") or [])))
        ordered_groups.extend(g for g in context.get("groups", {}) if g not in ordered_groups)
        active = set(map(str, context.get("base_tags") or []))
        prior_groups = []
        for current_group in ordered_groups:
            if current_group == group:
                break
            prior_groups.append(current_group)
            for selected_ref in (context.get("groups", {}).get(current_group) or {}).get("selected", []):
                selected_root, selected_sep, selected_id = str(selected_ref).partition(":")
                if selected_sep and selected_root.isdigit():
                    active.update(item_display_resolver.weapon_part_selection_tags(
                        int(selected_root), selected_id).get("adds", []))

        missing = required - active
        conflicts = excluded & active
        providers = []
        conflicting_parts = []
        for current_group in prior_groups:
            rule = context.get("groups", {}).get(current_group) or {}
            for candidate_ref in rule.get("eligible_refs", []):
                candidate_root, candidate_sep, candidate_id = str(candidate_ref).partition(":")
                if candidate_sep and candidate_root.isdigit() and missing.intersection(
                    item_display_resolver.weapon_part_selection_tags(int(candidate_root), candidate_id).get("adds", [])
                ):
                    providers.append((candidate_ref, current_group))
            for selected_ref in rule.get("selected", []):
                selected_root, selected_sep, selected_id = str(selected_ref).partition(":")
                if selected_sep and selected_root.isdigit() and conflicts.intersection(
                    item_display_resolver.weapon_part_selection_tags(int(selected_root), selected_id).get("adds", [])
                ):
                    conflicting_parts.append((selected_ref, current_group))

        if not missing and not conflicts:
            conflicting_parts.extend(
                (selected_ref, group)
                for selected_ref in (context.get("groups", {}).get(group) or {}).get("selected", [])
                if selected_ref != ref
            )

        details = []
        if missing:
            choices = self._rule_message("list_separator", "、", ", ").join(
                self._generation_ref_text(candidate_ref, candidate_group)
                for candidate_ref, candidate_group in list(dict.fromkeys(providers))[:2])
            details.append(self._rule_message(
                "requires_first" if choices else "no_prerequisite",
                "需要先选择：{parts}" if choices else "缺少可用的前置配件",
                "Requires first: {parts}" if choices else "No eligible prerequisite part is currently available",
                **({"parts": choices} if choices else {})))
        if conflicts or conflicting_parts:
            names = self._rule_message("list_separator", "、", ", ").join(
                self._generation_ref_text(selected_ref, selected_group)
                for selected_ref, selected_group in list(dict.fromkeys(conflicting_parts))[:2])
            details.append(self._rule_message(
                "conflicts_selected" if names else "conflicts_composition",
                "与当前已选配件互斥：{parts}" if names else "与当前武器模板互斥",
                "Conflicts with selected part: {parts}" if names else "Conflicts with the current composition",
                **({"parts": names} if names else {})))
        return self._rule_message("semicolon", "；", "; ").join(details)

    def _apply_generation_candidate_hints(self, source, context):
        rules_ready = bool(context.get("rules_available") and context.get("composition_ref"))
        selected_counts = Counter(context.get("selected_part_refs") or [])
        ref_rules = {}
        for group, rule in (context.get("groups") or {}).items():
            for ref in rule.get("allowed", []):
                ref_rules[ref] = (group, rule)

        category_groups = defaultdict(set)
        group_categories = defaultdict(set)
        for item in source:
            ref = item.get("_rule_ref")
            matched = ref_rules.get(ref)
            if not rules_ready:
                item["candidate"] = {
                    "kind": "unknown", "marker": "",
                    "badge": self._rule_message("rules_unknown", "规则未知", "Rules unknown"),
                    "hint": self._rule_message(
                        "rules_unknown_hint",
                        "当前武器没有可识别的稀有度或传奇模板，仍可作为魔改配件添加。",
                        "The current rarity or legendary composition is unknown; the part can still be added."),
                }
                continue
            if not matched:
                item["candidate"] = {
                    "kind": "modified", "marker": "◇",
                    "badge": self._rule_message("modified_pairing", "非自然搭配", "Modified pairing"),
                    "hint": self._rule_message(
                        "modified_pairing_hint",
                        "不在当前稀有度或传奇模板的自然生成配件池内；仍可选择作为魔改。",
                        "Outside the natural pool for this composition; it remains selectable as a modified part."),
                }
                continue

            group, rule = matched
            item["_rule_group"] = group
            category_groups[item["category"]].add(group)
            group_categories[group].add(item["category"])
            current = len(rule.get("selected") or [])
            minimum = int(rule.get("effective_min", rule.get("min", 1)))
            maximum = int(rule.get("effective_max", rule.get("max", 1)))
            legal_range = self._generation_count_range(minimum, maximum)
            group_text = self._generation_group_text(group)
            progress = f"{current}/{legal_range}"

            if selected_counts.get(ref, 0):
                item["candidate"] = {
                    "kind": "legal", "marker": "✓",
                    "badge": self._rule_message(
                        "legal_existing_badge", "合法配件池 · 已存在 · {progress}",
                        "Natural pool · Already present · {progress}", progress=progress),
                    "hint": self._rule_message(
                        "legal_existing_hint",
                        "该配件与当前模板合法，但 {group} 中已经存在它；请先替换/删除，直接再加会成为重复魔改。",
                        "This part is valid for the composition but already exists in {group}; replace/remove it first or adding again creates a duplicate.",
                        group=group_text),
                }
            elif current >= maximum:
                item["candidate"] = {
                    "kind": "legal", "marker": "✓",
                    "badge": self._rule_message(
                        "legal_limit_badge", "合法配件池 · 已达上限 · {progress}",
                        "Natural pool · Limit reached · {progress}", progress=progress),
                    "hint": self._rule_message(
                        "legal_limit_hint",
                        "该配件与当前模板合法；但 {group} 已有 {current} 个、上限为 {max}。先替换/删除可保持合法，直接添加会成为魔改。",
                        "This part is valid for the composition, but {group} is at {current}/{max}. Replace/remove first to stay natural; direct addition is modified.",
                        group=group_text, current=current, max=maximum),
                }
            elif ref not in set(rule.get("eligible_refs") or []):
                condition = self._generation_candidate_condition_text(ref, group, context)
                condition_zh = f"{condition}；" if condition else ""
                condition_en = f" {condition};" if condition else ""
                item["candidate"] = {
                    "kind": "warning", "marker": "!",
                    "badge": self._rule_message(
                        "condition_unmet_badge", "条件未满足 · {progress}", "Condition unmet · {progress}",
                        progress=progress),
                    "hint": self._rule_message(
                        "condition_unmet_hint",
                        "该配件属于 {group} 的生成池，但当前条件不满足。{suffix}仍可选择。",
                        "This part belongs to the {group} pool, but its condition is not satisfied.{suffix} It remains selectable.",
                        group=group_text,
                        suffix=condition_zh if self.current_lang == "zh-CN" else condition_en),
                }
            else:
                item["candidate"] = {
                    "kind": "legal", "marker": "✓",
                    "badge": self._rule_message(
                        "legal_pairing_badge", "合法搭配 · {progress}", "Natural pairing · {progress}",
                        progress=progress),
                    "hint": self._rule_message(
                        "legal_pairing_hint",
                        "当前模板允许该 {group}；现有 {current} 个，自然生成范围为 {range}。",
                        "Allowed by the current composition. Existing: {current}; natural range: {range}.",
                        group=group_text, current=current, range=legal_range),
                }

        hints = {
            str(item.get("category")): self._rule_message(
                "current_legal_zero", "当前{current}/合法—", "{current}/—", current=0)
            for item in source if rules_ready and item.get("category")
        }
        groups = context.get("groups") or {}
        for category, native_groups in category_groups.items():
            current = minimum = maximum = 0
            for group in native_groups:
                rule = groups[group]
                current += len(rule.get("selected") or [])
                minimum += int(rule.get("effective_min", rule.get("min", 1)))
                maximum += int(rule.get("effective_max", rule.get("max", 1)))
            legal_range = self._generation_count_range(minimum, maximum)
            shared = any(len(group_categories[group]) > 1 for group in native_groups)
            hints[category] = self._rule_message(
                "shared_current_legal" if shared else "current_legal",
                "共享配额 当前{current}/合法{range}" if shared else "当前{current}/合法{range}",
                "shared {current}/{range}" if shared else "{current}/{range}",
                current=current, range=legal_range)
        return hints

    def _append_missing_generation_candidates(self, source, context, part_types, manufacturers, weapon_types, level):
        represented = {item.get("_rule_ref") for item in source}
        for group, rule in (context.get("groups") or {}).items():
            for ref in rule.get("allowed", []):
                if ref in represented:
                    continue
                root, sep, part_id = str(ref).partition(":")
                if not sep or not root.isdigit() or not part_id.isdigit():
                    continue
                item_id = int(root)
                part_type = GENERATION_GROUP_TYPES.get(group, group.replace("_", " ").title())
                if item_id == 1:
                    manufacturer = weapon_type = "Elemental"
                    data_type = "elemental"
                else:
                    rows = self.all_weapon_parts_df[
                        self.all_weapon_parts_df["Manufacturer & Weapon Type ID"] == item_id]
                    if rows.empty:
                        continue
                    manufacturer = str(rows.iloc[0]["Manufacturer"])
                    weapon_type = str(rows.iloc[0]["Weapon Type"])
                    data_type = "normal"
                name = item_display_resolver.weapon_part_name(item_id, part_id, self.current_lang)
                preview_serial = f"{item_id}, 0, 1, {level}| 2, 0|| |"
                description = item_display_resolver.format_weapon_part_description(
                    item_id, part_id, preview_serial, self.current_lang, part_type)
                detail = " · ".join(filter(None, (name, description)))
                metadata = " / ".join(
                    self.get_localized_string(value) for value in (manufacturer, weapon_type, part_type))
                internal = item_display_resolver.weapon_part_internal(item_id, part_id)
                model = self._part_model_for_ref(item_id, part_id)
                id_label = f"ID {part_id}"
                display_name = name or part_type
                source.append({
                    "key": f"{data_type}:{item_id}:{part_id}",
                    "label": "  ".join(filter(None, (detail or display_name, f"[{model}]" if model else "", f"[{id_label}]"))),
                    "category": part_type,
                    "subcategory": manufacturer,
                    "tertiary": weapon_type,
                    "title": " ".join(filter(None, (f"[{id_label}]", f"[{model}]" if model else "", display_name))),
                    "detail": "\n".join(filter(None, (description, internal))),
                    "badges": [self.get_localized_string(manufacturer),
                               self.get_localized_string(weapon_type),
                               self.get_localized_string(part_type)],
                    "searchText": " ".join(filter(None, (metadata, internal, model))),
                    "_model": model,
                    "_rule_ref": ref,
                    "data": {"id": part_id, "mfg_id": item_id, "type": data_type},
                })
                represented.add(ref)
                if part_type not in part_types:
                    part_types.append(part_type)
                if manufacturer not in manufacturers:
                    manufacturers.append(manufacturer)
                if weapon_type not in weapon_types:
                    weapon_types.append(weapon_type)

    def _add_part_catalog(self):
        source = []
        part_types = list(dict.fromkeys(str(value) for value in self.all_weapon_parts_df["Part Type"].dropna()))
        elemental_type = "Elemental"
        elemental_types = ("Element", "Element Switch", "Underbarrel Element Switch", "Pearl Elements", "Pearl Stat")
        part_types.extend(value for value in elemental_types if value not in part_types)
        manufacturers = list(dict.fromkeys(str(value) for value in self.all_weapon_parts_df["Manufacturer"].dropna()))
        manufacturers.append(elemental_type)
        weapon_types = list(dict.fromkeys(str(value) for value in self.all_weapon_parts_df["Weapon Type"].dropna()))
        weapon_types.append(elemental_type)

        try:
            level = int(self._level)
        except ValueError:
            level = 60
        for _, row in self.all_weapon_parts_df.iterrows():
            item_id, part_id = int(row["Manufacturer & Weapon Type ID"]), str(row["Part ID"])
            part_type, manufacturer = str(row["Part Type"]), str(row["Manufacturer"])
            weapon_type = str(row["Weapon Type"])
            name = item_display_resolver.weapon_part_name(item_id, part_id, self.current_lang, row)
            preview_serial = f"{item_id}, 0, 1, {level}| 2, 0|| |"
            description = item_display_resolver.format_weapon_part_description(
                item_id, part_id, preview_serial, self.current_lang, part_type)
            name = name or (self._loc("parts", "unnamed_barrel", "Unnamed Barrel") if part_type == "Barrel" else "")
            detail = " · ".join(value for value in (name, description) if value)
            metadata = " / ".join(self.get_localized_string(value) for value in (manufacturer, weapon_type, part_type))
            internal = item_display_resolver.weapon_part_internal(item_id, part_id)
            model = self._part_model_for_ref(item_id, part_id)
            id_label = f"ID {part_id}"
            display_name = name or part_type
            label = "  ".join(filter(None, (detail or display_name, f"[{model}]" if model else "", f"[{id_label}]")))
            source.append({
                "key": f"normal:{item_id}:{part_id}", "label": label, "category": part_type,
                "subcategory": manufacturer, "tertiary": weapon_type,
                "title": " ".join(filter(None, (f"[{id_label}]", f"[{model}]" if model else "", display_name))),
                "detail": "\n".join(filter(None, (description, internal))),
                "badges": [self.get_localized_string(manufacturer),
                           self.get_localized_string(weapon_type),
                           self.get_localized_string(part_type)],
                "searchText": " ".join(filter(None, (metadata, internal, model))),
                "_model": model,
                "_rule_ref": f"{item_id}:{part_id}",
                "data": {"id": part_id, "mfg_id": item_id, "type": "normal"},
            })

        for _, row in self.elemental_df.iterrows():
            element_id, part_id = int(row["Elemental_ID"]), int(row["Part_ID"])
            name = str(row[self.elemental_stat_col])
            part_type = self._elemental_part_type(row)
            stat_text = str(row["Stat"])
            metadata = " / ".join((self.get_localized_string(elemental_type),
                                   self.get_localized_string(part_type)))
            id_label = f"ID {part_id}"
            source.append({
                "key": f"elemental:{element_id}:{part_id}",
                "label": f"{name}  [{metadata}] [{id_label}]", "category": part_type,
                "subcategory": elemental_type, "tertiary": elemental_type,
                "title": f"[{id_label}] {name}", "detail": stat_text,
                "badges": [self.get_localized_string(elemental_type),
                           self.get_localized_string(part_type)],
                "searchText": stat_text,
                "_rule_ref": f"{element_id}:{part_id}",
                "data": {"id": part_id, "mfg_id": element_id, "type": "elemental"},
            })
        try:
            context = item_display_resolver.weapon_generation_context(self._decoded)
        except Exception:
            context = {}
        self._append_missing_generation_candidates(
            source, context, part_types, manufacturers, weapon_types, level)
        self._decorate_model_context(source)
        return source, part_types, manufacturers, weapon_types, self._apply_generation_candidate_hints(source, context)

    @pyqtSlot(result="QVariantMap")
    def prepareAddPartCatalog(self) -> dict[str, Any]:
        """添加配件对话框数据：目录 + facet 选项 + 类别提示。

        items 每项在原始字段之外补三个扁平字段供 QML 行直接绑定：
        - tooltip：完整富文本/多行说明（候选 hint + detail 描述 + 内部名）
        - candidateKind / candidateMarker：legit 上色与标记（对齐主线
          FacetedCatalogPicker._refilter 的蓝底加粗/橙底）
        - modelKind：same/cross 模型提示着色
        """
        if not self._decoded.strip():
            self.app.toast(self.get_localized_string("load_weapon_first"), "warning")
            return {}
        source, part_types, manufacturers, weapon_types, hints = self._add_part_catalog()
        for item in source:
            candidate = item.get("candidate") or {}
            item["candidateKind"] = str(candidate.get("kind", ""))
            item["candidateMarker"] = str(candidate.get("marker", ""))
            item["candidateBadge"] = str(candidate.get("badge", ""))
            item["modelKind"] = str(item.get("model_kind", ""))
            item["tooltip"] = "\n\n".join(filter(None, (
                str(candidate.get("hint") or ""),
                str(item.get("model_hint") or ""),
                str(item.get("detail") or ""),
            )))
        all_text = self._loc("catalog", "all", "All")
        return {
            "items": source,
            "partTypes": [{"key": "all", "label": all_text}] + [
                {"key": v, "label": (f"[{hints[v]}] {self.get_localized_string(v)}"
                                     if v in hints else self.get_localized_string(v))}
                for v in part_types],
            "manufacturers": [{"key": "all", "label": self._loc("catalog", "all_manufacturers", "All Manufacturers")}] + [
                {"key": v, "label": self.get_localized_string(v)} for v in manufacturers],
            "weaponTypes": [{"key": "all", "label": self._loc("catalog", "all_weapon_types", "All Weapon Types")}] + [
                {"key": v, "label": self.get_localized_string(v)} for v in weapon_types],
        }

    @pyqtSlot("QVariantList")
    def addParts(self, entries) -> None:
        """entries: [{key, count}]，key 为目录项 key（normal:mfg:pid / elemental:eid:pid）。"""
        if not entries:
            return
        try:
            current_weapon_mfg_id = int(self._decoded.split(",")[0])
        except (ValueError, IndexError):
            self.app.toast(self.get_localized_string("cannot_determine_mfg"), "error")
            return

        catalog = self.prepareAddPartCatalog()
        by_key = {item["key"]: item for item in catalog.get("items", [])}
        parts_by_mfg: dict[int, list] = {}
        for entry in entries:
            item = by_key.get(str(entry.get("key")))
            if item is None:
                continue
            data = item["data"]
            mfg_id = int(data["mfg_id"])
            parts_by_mfg.setdefault(mfg_id, [])
            count = 1 if data["type"] == "elemental" else max(1, int(entry.get("count", 1)))
            parts_by_mfg[mfg_id].extend([{"id": data["id"], "type": data["type"]}] * count)
        if not parts_by_mfg:
            return

        new_parts_list = []
        for mfg_id, parts in parts_by_mfg.items():
            elemental_parts = [f"{{1:{p['id']}}}" for p in parts if p["type"] == "elemental"]
            normal_parts = [p["id"] for p in parts if p["type"] == "normal"]
            if mfg_id == 1:
                new_parts_list.extend(elemental_parts)
            elif mfg_id == current_weapon_mfg_id:
                new_parts_list.extend(f"{{{pid}}}" for pid in normal_parts)
            elif normal_parts:
                new_parts_list.append(f"{{{mfg_id}:[{' '.join(map(str, sorted(normal_parts)))}]}}")
        if not new_parts_list:
            return

        new_part_data = self._parse_component_string(" ".join(new_parts_list))
        insertion_index = len(self.parts_data)
        for i in range(len(self.parts_data) - 1, -1, -1):
            part = self.parts_data[i]
            if isinstance(part, dict) and part.get("type") != "skin":
                insertion_index = i + 1
                break
        if insertion_index > 0:
            prev_item = self.parts_data[insertion_index - 1]
            if isinstance(prev_item, dict) or (isinstance(prev_item, str) and prev_item.strip()):
                self.parts_data.insert(insertion_index, " ")
                insertion_index += 1
        self.parts_data[insertion_index:insertion_index] = new_part_data
        self._regenerate_serial()

    # ------------------------------------------------------------------ #
    # 汇总
    # ------------------------------------------------------------------ #
    def _update_summary(self) -> None:
        weapon = None
        for row in self._browser_items:
            if row["original_path"] and self.selected_weapon_path is not None and \
                    list(row["original_path"]) == list(self.selected_weapon_path):
                weapon = row["_item"]
                break
        if not weapon:
            self._summary = self._loc("summary", "none_selected", "No backpack weapon selected")
            return
        name = weapon.get("name") or weapon.get("manufacturer") or self._loc("summary", "fallback_name", "Weapon")
        self._summary = self._loc("summary", "selected", "Selected · {name} · Lv.{level}",
                                  name=name, level=weapon.get("level", "N/A"))
