"""配置管理器 VM：移植 QtLoadoutManagerTab 的全部非渲染逻辑。"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from PyQt6.QtCore import pyqtProperty, pyqtSignal, pyqtSlot

from core import bl4_functions as bl4f
from core import decoder_logic, item_display_resolver, lookup, resource_loader
from core.unlock_data import CHARACTER_CLASSES

from .base import PageViewModel, register

WEAPON_SLOT_KEYS = {"slot_0", "slot_1", "slot_2", "slot_3"}
SDU_GRAPH_NAME = "sdu_upgrades"

_SLOT_FALLBACK = {
    "slot_0": "武器1", "slot_1": "武器2", "slot_2": "武器3", "slot_3": "武器4",
    "slot_4": "护盾", "slot_5": "重武器/手雷", "slot_6": "修复套件",
    "slot_7": "强化模组", "slot_8": "职业模组",
}

CLASS_IDS = {"Amon": 255, "Harlowe": 259, "Rafa": 256, "Vex": 254, "C4sh": 404, "C4SH": 404}
CLASS_NAME_ALIASES = {"C4SH": "C4sh"}


def _get_editor_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]


def _get_skill_graphs(graphs: list) -> list:
    result = []
    for g in graphs:
        if g.get("name", "") == SDU_GRAPH_NAME:
            break
        result.append(g)
    return result


def _replace_skill_graphs(graphs: list, new_skill_graphs: list) -> list:
    sdu_index = None
    for i, g in enumerate(graphs):
        if g.get("name", "") == SDU_GRAPH_NAME:
            sdu_index = i
            break
    if sdu_index is not None:
        return new_skill_graphs + graphs[sdu_index:]
    return list(new_skill_graphs)


@register("loadout_manager", "LoadoutManagerPage.qml")
class LoadoutManagerViewModel(PageViewModel):
    STRINGS_SECTION = "loadout_tab"

    dataChanged = pyqtSignal()

    def __init__(self, app, parent=None):
        super().__init__(app, parent)
        self.yaml_data = None
        self.current_loadout_index = 1
        self.save_file_path = None
        self.save_name = None
        self.current_lang = str(app.language)
        self._manual_read_active = False
        self._live_busy = False
        self._inventory_mutation_blocked = False
        self._saved_loadouts: dict[int, dict | None] = {i: None for i in range(1, 7)}
        self._equipped_rows: list[dict[str, str]] = []
        self._skill_rows: list[dict[str, str]] = []
        self._load_weapon_csv_data()
        self._load_skills_csv_data()
        self._load_weapon_localization()

    # ------------------------------------------------------------------ #
    # i18n
    # ------------------------------------------------------------------ #
    def _t(self, section: str, key: str, **kwargs) -> str:
        val = self.strings.get(section, {}).get(key, key)
        if kwargs:
            try:
                return val.format(**kwargs)
            except (KeyError, IndexError):
                return val
        return val

    def _t_slot(self, slot_key: str) -> str:
        return self.strings.get("slots", {}).get(slot_key, _SLOT_FALLBACK.get(slot_key, slot_key))

    def on_language_changed(self) -> None:
        super().on_language_changed()
        self.current_lang = str(self.app.language)
        self._load_weapon_localization()
        if self._manual_read_active:
            self._refresh_equipped_display_from_yaml()
            self._refresh_skills_display_from_yaml()
        else:
            self._display_slot_content(self.current_loadout_index)

    # ------------------------------------------------------------------ #
    # 数据加载
    # ------------------------------------------------------------------ #
    def _load_weapon_csv_data(self):
        try:
            self.all_weapon_parts_df = pd.read_csv(
                resource_loader.get_weapon_data_path("all_weapon_part.csv"))
            self.weapon_rarity_df = pd.read_csv(
                resource_loader.get_weapon_data_path("weapon_rarity.csv"))
        except Exception:
            self.all_weapon_parts_df = pd.DataFrame()
            self.weapon_rarity_df = pd.DataFrame()

    def _load_weapon_localization(self):
        if self.current_lang == "zh-CN":
            try:
                self.weapon_localization = (
                    resource_loader.load_weapon_json("weapon_localization_zh-CN.json") or {})
            except Exception:
                self.weapon_localization = {}
        else:
            self.weapon_localization = {}

    def _load_skills_csv_data(self):
        self.skills_data = resource_loader.load_class_mods_csv("Skills.csv")
        self.class_ids = dict(CLASS_IDS)
        self.class_names_by_identifier = {}
        self.skills_by_class = {}
        for skill in self.skills_data:
            class_id = skill.get("class_ID", "")
            class_name = skill.get("class_name", "").strip()
            class_identifier = skill.get("class_identifier", "").strip().casefold()
            if class_id.isdigit() and class_name:
                self.class_ids[class_name] = int(class_id)
                if class_identifier:
                    self.class_names_by_identifier[class_identifier] = class_name
            if class_id not in self.skills_by_class:
                self.skills_by_class[class_id] = []
            self.skills_by_class[class_id].append(skill)

        self.skill_lookup = {}
        self.skills_by_graph = {}
        for skill in self.skills_data:
            key = (skill.get("class_ID", ""), skill.get("skill_name_EN", ""))
            self.skill_lookup[key] = skill
            graph_key = self._skill_mapping_key(
                skill.get("class_ID", ""), skill.get("graph_name", ""), skill.get("node_name", ""))
            self.skills_by_graph[graph_key] = skill
        self._load_skill_name_mapping()

    @staticmethod
    def _normalize_mapping_text(value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip()).casefold()

    def _skill_mapping_key(self, class_id: str, graph_name: str, node_name: str) -> tuple:
        return (
            str(class_id or "").strip(),
            self._normalize_mapping_text(graph_name),
            self._normalize_mapping_text(node_name),
        )

    def _skill_mapping_class_key(self, class_id: str, node_name: str) -> tuple:
        return (str(class_id or "").strip(), self._normalize_mapping_text(node_name))

    def _load_skill_name_mapping(self):
        self.skill_name_mapping = {}
        self.skill_name_mapping_by_graph = {}
        self.skill_name_mapping_by_class = {}
        try:
            mapping_path = resource_loader.get_loadout_data_path("skill_name_mapping.csv")
            if mapping_path and mapping_path.exists():
                with open(mapping_path, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    fieldnames = set(reader.fieldnames or [])
                    for row in reader:
                        if {"class_id", "graph_name", "node_name", "middle_name", "skill_name_EN"}.issubset(fieldnames):
                            class_id = row.get("class_id", "").strip()
                            graph_name = row.get("graph_name", "").strip()
                            node_name = row.get("node_name", "").strip()
                            middle_name = row.get("middle_name", "").strip()
                            mapped_name = row.get("skill_name_EN", "").strip()
                            if not (class_id and mapped_name):
                                continue
                            for lookup_name in {node_name, middle_name}:
                                if graph_name and lookup_name:
                                    self.skill_name_mapping_by_graph[
                                        self._skill_mapping_key(class_id, graph_name, lookup_name)
                                    ] = row
                                if lookup_name:
                                    self.skill_name_mapping_by_class[
                                        self._skill_mapping_class_key(class_id, lookup_name)
                                    ] = row
                                    self.skill_name_mapping.setdefault(lookup_name, mapped_name)
                        else:
                            raw_name = row.get("raw_display_name", "").strip()
                            mapped_name = row.get("skill_name_EN", "").strip()
                            if raw_name and mapped_name:
                                self.skill_name_mapping[raw_name] = mapped_name
        except Exception:
            self.skill_name_mapping = {}
            self.skill_name_mapping_by_graph = {}
            self.skill_name_mapping_by_class = {}

    # ------------------------------------------------------------------ #
    # 角色/技能辅助
    # ------------------------------------------------------------------ #
    def _get_character_class_name(self) -> str:
        if not self.yaml_data:
            return ""
        try:
            state = self.yaml_data.get("state", self.yaml_data)
            class_raw = state.get("class", "")
            discovered_name = self.class_names_by_identifier.get(str(class_raw).casefold())
            if discovered_name:
                return CLASS_NAME_ALIASES.get(discovered_name, discovered_name)
            class_key = class_raw.replace("Char_", "") if class_raw.startswith("Char_") else class_raw
            char_info = CHARACTER_CLASSES.get(class_key, {})
            class_name = char_info.get("name", class_key)
            return CLASS_NAME_ALIASES.get(class_name, class_name)
        except (AttributeError, TypeError):
            return ""

    def _skill_icon_url(self, icon_file: str, class_name: str) -> str:
        if not icon_file:
            return ""
        class_name = CLASS_NAME_ALIASES.get(class_name, class_name)
        try:
            path = resource_loader.get_class_mods_image_path(class_name, icon_file)
            if path and Path(path).exists():
                return Path(path).as_uri()
        except Exception:
            pass
        return ""

    def _find_skill_csv_row(self, class_id: str, graph_name: str = "", node_name: str = "",
                            skill_name: str = "") -> dict:
        if graph_name and node_name:
            row = self.skills_by_graph.get(self._skill_mapping_key(class_id, graph_name, node_name))
            if row:
                return row
        normalized_name = re.sub(r" [BGR]$", "", skill_name).casefold()
        for row in self.skills_by_class.get(class_id, []):
            if graph_name and self._normalize_mapping_text(row.get("graph_name", "")) != self._normalize_mapping_text(graph_name):
                continue
            row_name = re.sub(r" [BGR]$", "", row.get("skill_name_EN", "")).casefold()
            if row_name == normalized_name:
                return row
        return {}

    def _find_loadout_skill_mapping(self, class_id: str, graph_name: str, skill_name: str) -> dict:
        if graph_name and skill_name:
            row = self.skill_name_mapping_by_graph.get(
                self._skill_mapping_key(class_id, graph_name, skill_name))
            if row:
                return row
        if skill_name:
            row = self.skill_name_mapping_by_class.get(
                self._skill_mapping_class_key(class_id, skill_name))
            if row:
                return row
        return {}

    def _get_skill_display_info(self, skill_name_en: str, class_name: str,
                                class_id: str, graph_name: str = "") -> tuple:
        class_name = CLASS_NAME_ALIASES.get(class_name, class_name)
        mapping_row = self._find_loadout_skill_mapping(class_id, graph_name, skill_name_en)
        if mapping_row:
            mapped_name = mapping_row.get("skill_name_EN", "").strip() or skill_name_en
            skill_row = self._find_skill_csv_row(
                class_id,
                mapping_row.get("graph_name", ""),
                mapping_row.get("graph_coord", "") or mapping_row.get("node_name", ""),
                mapped_name,
            )
            display_name = skill_row.get("skill_name_EN", "").strip() or mapped_name
            zh_name = (skill_row.get("skill_name_ZH", "") or mapping_row.get("skill_name_ZH", "")).strip()
            if self.current_lang == "zh-CN" and zh_name:
                display_name = zh_name
            return display_name, self._skill_icon_url(skill_row.get("icon_file", ""), class_name)

        mapped_name = self.skill_name_mapping.get(skill_name_en, skill_name_en)
        lookup_name = mapped_name
        display_name = lookup_name
        icon_url = ""
        skill_row = self.skill_lookup.get((class_id, lookup_name))
        if not skill_row:
            candidates = self.skills_by_class.get(class_id, [])
            for row in candidates:
                en_name = row.get("skill_name_EN", "")
                if en_name.lower() == lookup_name.lower():
                    skill_row = row
                    break
            if not skill_row:
                for row in candidates:
                    en_name = row.get("skill_name_EN", "")
                    if (lookup_name.lower() in en_name.lower()
                            or en_name.lower() in lookup_name.lower()):
                        skill_row = row
                        break
        if skill_row:
            skill_name_en_canonical = skill_row.get("skill_name_EN", lookup_name)
            zh_name = skill_row.get("skill_name_ZH", "")
            if self.current_lang == "zh-CN" and zh_name:
                display_name = zh_name
            else:
                display_name = skill_name_en_canonical
            icon_url = self._skill_icon_url(skill_row.get("icon_file", ""), class_name)
        return display_name, icon_url

    # ------------------------------------------------------------------ #
    # 武器名称解析
    # ------------------------------------------------------------------ #
    def _get_weapon_real_name(self, serial: str) -> str:
        try:
            formatted_str, _, err = decoder_logic.decode_serial_to_string(serial)
            if err or "||" not in formatted_str:
                return ""
            header_part, component_part = formatted_str.split("||", 1)
            sections = header_part.strip().split("|")
            m_id = int(sections[0].strip().split(",")[0])
            manufacturer, item_type, found = lookup.get_kind_enums(m_id)
            if not found:
                return ""
            display = item_display_resolver.resolve_item_display(
                m_id, manufacturer, item_type, formatted_str, self.current_lang)
            weapon_name = "" if display.get("display_source") == "fallback" else display.get("display_name", "")
            loc_rarity = display.get("rarity", "")
            display_parts = []
            if loc_rarity:
                display_parts.append(f"[{loc_rarity}]")
            if weapon_name:
                display_parts.append(weapon_name)
            return " ".join(display_parts) if display_parts else ""
        except Exception:
            return ""

    def _decode_item_name(self, serial: str) -> str:
        try:
            formatted_str, _, err = decoder_logic.decode_serial_to_string(serial)
            if err:
                return f"[{self._t('decode', 'decode_failed')}: {err}]"
            if "||" not in formatted_str:
                return f"[{self._t('decode', 'unknown_item')}]"
            header_part, _ = formatted_str.split("||", 1)
            id_section = header_part.strip().split("|")[0]
            id_part = id_section.strip().split(",")
            if len(id_part) < 4:
                return f"[{self._t('decode', 'unknown_item')}]"
            item_id = int(id_part[0].strip())
            manufacturer, item_type, found = lookup.get_kind_enums(item_id)
            if not found:
                return f"[ID: {item_id}]"
            loc_mfr = bl4f.get_localized_string(manufacturer)
            loc_type = bl4f.get_localized_string(item_type)
            return f"{loc_mfr} {loc_type}"
        except Exception:
            return f"[{self._t('decode', 'decode_error')}]"

    # ------------------------------------------------------------------ #
    # 生命周期（set_data 等价）
    # ------------------------------------------------------------------ #
    def set_data(self, yaml_data, save_file_path=None) -> None:
        """live 退出/离线切换时重置（与主线 set_data 对齐）。"""
        self.yaml_data = yaml_data
        self._manual_read_active = False
        self.save_file_path = save_file_path
        self._select_save_name()
        self._scan_saved_loadouts()
        self._display_slot_content(self.current_loadout_index)

    def refresh(self) -> None:
        self.current_lang = str(self.app.language)
        self.set_data(self.controller.yaml_obj, self.controller.save_path)

    def on_save_opened(self) -> None:
        self.refresh()

    def _live_profile_name(self) -> str:
        root = self.yaml_data.get("state", self.yaml_data) if isinstance(self.yaml_data, dict) else {}
        raw_name = str(root.get("char_name") or "current").strip()
        safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", raw_name).strip(" ._")
        return f"live_{safe_name[:48] or 'current'}"

    def _select_save_name(self) -> None:
        if self.app.liveActive:
            self.save_name = self._live_profile_name()
        elif self.save_file_path:
            self.save_name = Path(self.save_file_path).stem
        else:
            self.save_name = None

    def _get_loadout_dir(self) -> Path:
        return _get_editor_root() / "loadouts"

    def _get_loadout_filepath(self, slot: int) -> Path:
        return self._get_loadout_dir() / f"loadout_{self.save_name}_{slot}.json"

    def _scan_saved_loadouts(self) -> None:
        self._saved_loadouts = {i: None for i in range(1, 7)}
        if not self.save_name:
            return
        loadout_dir = self._get_loadout_dir()
        if not loadout_dir.exists():
            return
        for slot in range(1, 7):
            fp = loadout_dir / f"loadout_{self.save_name}_{slot}.json"
            if fp.exists():
                try:
                    with open(fp, "r", encoding="utf-8") as f:
                        self._saved_loadouts[slot] = json.load(f)
                except Exception:
                    pass

    # ------------------------------------------------------------------ #
    # QML 属性
    # ------------------------------------------------------------------ #
    @pyqtProperty(bool, notify=dataChanged)
    def liveMode(self) -> bool:
        return self.app.liveActive

    @pyqtProperty(bool, notify=dataChanged)
    def saveLoaded(self) -> bool:
        return self.controller.yaml_obj is not None

    @pyqtProperty(list, notify=dataChanged)
    def slotButtons(self) -> list[dict[str, Any]]:
        buttons = []
        for slot in range(1, 7):
            saved = self._saved_loadouts.get(slot)
            buttons.append({
                "slot": slot,
                "active": slot == self.current_loadout_index,
                "hasSaved": saved is not None,
                "tooltip": (saved or {}).get("config_name", "") if saved else "",
            })
        return buttons

    @pyqtProperty(str, notify=dataChanged)
    def configNameText(self) -> str:
        saved = self._saved_loadouts.get(self.current_loadout_index)
        if saved and saved.get("config_name"):
            return f"[ {saved['config_name']} ]"
        default_name = self._t("labels", "default_config_name", slot=self.current_loadout_index)
        return f"[ {default_name} ]"

    @pyqtProperty(str, notify=dataChanged)
    def noticeText(self) -> str:
        return self.strings.get("notice", "")

    @pyqtProperty(list, notify=dataChanged)
    def equippedRows(self) -> list[dict[str, str]]:
        return self._equipped_rows

    @pyqtProperty(list, notify=dataChanged)
    def skillRows(self) -> list[dict[str, str]]:
        return self._skill_rows

    @pyqtProperty(str, notify=dataChanged)
    def saveButtonText(self) -> str:
        return self._t("buttons", "save_live_loadout" if self.liveMode else "save_loadout")

    @pyqtProperty(str, notify=dataChanged)
    def loadButtonText(self) -> str:
        return self._t("buttons", "apply_live_loadout" if self.liveMode else "load_loadout")

    @pyqtProperty(bool, notify=dataChanged)
    def canLoad(self) -> bool:
        if self._live_busy:
            return False
        if self.liveMode:
            return (not self._inventory_mutation_blocked
                    and self._saved_loadouts.get(self.current_loadout_index) is not None)
        return not self._live_busy

    @pyqtProperty(bool, notify=dataChanged)
    def canSaveLoadout(self) -> bool:
        return not self._live_busy

    @pyqtProperty(bool, notify=dataChanged)
    def skillsVisible(self) -> bool:
        return not self.liveMode

    # ------------------------------------------------------------------ #
    # QML 槽
    # ------------------------------------------------------------------ #
    @pyqtSlot(int)
    def selectSlot(self, index: int) -> None:
        if not 1 <= index <= 6:
            return
        self.current_loadout_index = index
        self._manual_read_active = False
        self._display_slot_content(index)

    @pyqtSlot()
    def readSave(self) -> None:
        if not self.yaml_data:
            self.app.toast(self._t("dialogs", "open_save_first"), "warning")
            return
        self._manual_read_active = True
        self._refresh_equipped_display_from_yaml()
        self._refresh_skills_display_from_yaml()

    @pyqtSlot(str)
    def saveLoadout(self, config_name: str) -> None:
        if self.liveMode:
            if self._live_busy:
                return
            if not self.save_name:
                self.app.toast(self._t("dialogs", "live_unavailable"), "warning")
                return
            self.app.live.start_loadout_worker(
                "save", self.current_loadout_index, {"config_name": config_name or ""})
            return
        if not self.yaml_data:
            self.app.toast(self._t("dialogs", "open_save_first"), "warning")
            return
        if not self.save_name:
            self.app.toast(self._t("dialogs", "no_save_name"), "warning")
            return
        idx = self.current_loadout_index
        loadout_dir = self._get_loadout_dir()
        loadout_dir.mkdir(parents=True, exist_ok=True)
        filepath = self._get_loadout_filepath(idx)

        equipped_data = self._get_equipped_data() or {}
        equipped_items = []
        for slot_key in ["slot_0", "slot_1", "slot_2", "slot_3", "slot_4",
                         "slot_5", "slot_6", "slot_7", "slot_8"]:
            if slot_key not in equipped_data:
                continue
            item_list = equipped_data[slot_key]
            if isinstance(item_list, list) and len(item_list) > 0:
                item = item_list[0]
            elif isinstance(item_list, dict):
                item = item_list
            else:
                continue
            equipped_items.append({
                "slot": slot_key,
                "serial": item.get("serial", ""),
                "flags": item.get("flags", None),
                "state_flags": item.get("state_flags", 1),
            })

        progression = self.yaml_data.get("progression", {})
        graphs = progression.get("graphs", [])
        skill_graphs = _get_skill_graphs(graphs)

        loadout = {
            "save_name": self.save_name,
            "slot": idx,
            "config_name": config_name.strip(),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "equipped_items": equipped_items,
            "skill_graphs": skill_graphs,
        }
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(loadout, f, ensure_ascii=False, indent=2)
            self._saved_loadouts[idx] = loadout
            self._manual_read_active = False
            self._display_slot_content(idx)
            self.app.toast(self._t("dialogs", "save_success", slot=idx, path=str(filepath)), "success")
        except Exception as exc:
            self.app.toast(self._t("dialogs", "save_fail", error=str(exc)), "error")

    @pyqtSlot()
    def loadLoadout(self) -> None:
        idx = self.current_loadout_index
        if self.liveMode:
            if self._live_busy:
                return
            saved = self._saved_loadouts.get(idx)
            if not saved:
                self.app.toast(self._t("dialogs", "no_saved_config", slot=idx), "warning")
                return
            payload = self._live_apply_payload(saved)
            if not payload.get("entries"):
                self.app.toast(self._t("dialogs", "live_no_entries"), "warning")
                return

            def _apply(accepted: bool) -> None:
                if accepted:
                    self.app.live.start_loadout_worker("apply", idx, payload)

            self.app._request_confirm(
                self._t("dialogs", "confirm_live_apply_title"),
                self._t("dialogs", "confirm_live_apply_msg", slot=idx),
                _apply, warning=True)
            return
        if not self.yaml_data:
            self.app.toast(self._t("dialogs", "open_save_first"), "warning")
            return
        saved = self._saved_loadouts.get(idx)
        if not saved:
            self.app.toast(self._t("dialogs", "no_saved_config", slot=idx), "warning")
            return

        def _overwrite(accepted: bool) -> None:
            if accepted:
                self._apply_offline_loadout(idx, saved)

        self.app._request_confirm(
            self._t("dialogs", "confirm_overwrite_title"),
            self._t("dialogs", "confirm_overwrite_msg", slot=idx),
            _overwrite, warning=True)

    def _apply_offline_loadout(self, idx: int, saved: dict) -> None:
        errors = []
        try:
            state = self.yaml_data.get("state", self.yaml_data)
            inventory = state.get("inventory", {})
            equipped_inv = inventory.setdefault("equipped_inventory", {})
            new_equipped = {}
            for item_data in saved.get("equipped_items", []):
                slot = item_data["slot"]
                entry = {"serial": item_data["serial"]}
                if item_data.get("flags") is not None:
                    entry["flags"] = item_data["flags"]
                entry["state_flags"] = item_data.get("state_flags", 1)
                new_equipped[slot] = [entry]
            equipped_inv["equipped"] = new_equipped
        except Exception as exc:
            errors.append(self._t("dialogs", "equip_fail", error=str(exc)))

        skill_graphs = saved.get("skill_graphs", [])
        if skill_graphs:
            try:
                progression = self.yaml_data.setdefault("progression", {})
                current_graphs = progression.get("graphs", [])
                progression["graphs"] = _replace_skill_graphs(current_graphs, skill_graphs)
            except Exception as exc:
                errors.append(self._t("dialogs", "skill_fail", error=str(exc)))

        if errors:
            self.app.toast("\n".join(errors), "warning")
        else:
            self.app.toast(self._t("dialogs", "load_success", slot=idx), "success")

        # 与主线一致：直接改写 yaml_data 后通知 controller 置脏
        try:
            self.controller.mark_dirty()
        except Exception:
            pass
        self.app._mark_items_stale()
        self._display_slot_content(idx)

    @pyqtSlot()
    def reviewRecovery(self) -> None:
        self.app.live.start_loadout_worker("recovery", 0, {})

    @pyqtSlot()
    def clearRecovery(self) -> None:
        self.app.live.start_loadout_worker("clear_recovery", 0, {})

    # -- live 回调（LiveManager 调用） --------------------------------------- #
    def set_live_mode(self, enabled: bool) -> None:
        self._manual_read_active = False
        self._select_save_name()
        self._scan_saved_loadouts()
        self._display_slot_content(self.current_loadout_index)
        self.dataChanged.emit()

    def set_live_busy(self, busy: bool) -> None:
        self._live_busy = bool(busy)
        self.dataChanged.emit()

    def set_inventory_mutation_blocked(self, blocked: bool) -> None:
        self._inventory_mutation_blocked = bool(blocked)
        self.dataChanged.emit()

    def finish_live_snapshot(self, slot: int, config_name: str, snapshot: dict | None,
                             error: str | None = None) -> None:
        if error:
            self.app.toast(self._t("dialogs", "live_save_fail", error=error), "error")
            return
        try:
            loadout = self._live_loadout_from_snapshot(slot, config_name, snapshot or {})
            loadout_dir = self._get_loadout_dir()
            loadout_dir.mkdir(parents=True, exist_ok=True)
            filepath = self._get_loadout_filepath(slot)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(loadout, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            self.app.toast(self._t("dialogs", "live_save_fail", error=str(exc)), "error")
            return
        self._saved_loadouts[slot] = loadout
        self._manual_read_active = False
        if self.current_loadout_index == slot:
            self._display_slot_content(slot)
        self.app.toast(self._t("dialogs", "live_save_success", slot=slot, path=str(filepath)),
                       "success")

    def finish_live_apply(self, slot: int, result: dict | None, error: str | None = None) -> None:
        result = result if isinstance(result, dict) else {}
        if not error and result.get("ok") and result.get("verified"):
            message = self._t(
                "dialogs", "live_apply_success", slot=slot,
                applied=len(result.get("applied") or []),
                skipped=len(result.get("skipped") or []),
            )
            if result.get("cache_pending"):
                message += "\n" + self._t("dialogs", "live_apply_cache_pending")
            self.app.toast(message, "success")
            return
        detail = error or str(result.get("error") or "invalid response")
        if result.get("rollback_complete") is False:
            detail += "\n" + self._t("dialogs", "live_apply_rollback_incomplete")
        if result.get("uncertain") or result.get("recovery"):
            detail += "\n" + self._t("dialogs", "live_recovery_available")
        self.app.toast(self._t("dialogs", "live_apply_fail", error=detail), "error")

    def finish_live_recovery(self, operation: str, result: dict | None,
                             error: str | None = None) -> None:
        result = result if isinstance(result, dict) else {}
        if error or not result.get("ok"):
            self.app.toast(self._t(
                "dialogs", "live_recovery_fail",
                error=error or str(result.get("error") or "invalid response")), "error")
            return
        if operation == "recovery":
            recovery = result.get("recovery") if isinstance(result.get("recovery"), dict) else {}
            if not result.get("pending"):
                self.app.toast(self._t("dialogs", "live_recovery_none"), "info")
                return
            reason = str(recovery.get("reason") or recovery.get("error") or "unknown")

            def _clear(accepted: bool) -> None:
                if accepted:
                    self.app.live.start_loadout_worker("clear_recovery", 0, {})

            self.app._request_confirm(
                self._t("dialogs", "live_recovery_title"),
                self._t("dialogs", "live_recovery_confirm", reason=reason),
                _clear, warning=True)
            return
        self.app.toast(self._t("dialogs", "live_recovery_cleared"), "success")

    # ------------------------------------------------------------------ #
    # live 数据结构
    # ------------------------------------------------------------------ #
    @staticmethod
    def _live_item_fingerprint(serial: str, fingerprint: str = "") -> str:
        value = str(fingerprint or "").strip().lower()
        serial = str(serial or "")
        return value or (
            hashlib.sha256(serial.encode("utf-8")).hexdigest()
            if serial.startswith("@U") else "")

    def _live_loadout_from_snapshot(self, slot: int, config_name: str, snapshot: dict) -> dict:
        if not isinstance(snapshot, dict) or not snapshot.get("ok"):
            raise ValueError(str((snapshot or {}).get("error") or "invalid live loadout snapshot"))
        rows = snapshot.get("slots")
        if not isinstance(rows, list):
            raise ValueError("live loadout snapshot has no slots")
        equipped_items = []
        for row in rows:
            if not isinstance(row, dict) or row.get("locked"):
                continue
            slot_index = row.get("slot_index")
            serial = str(row.get("serial") or "")
            fingerprint = self._live_item_fingerprint(serial, str(row.get("serial_sha256") or ""))
            occurrence = row.get("occurrence")
            if (isinstance(slot_index, bool) or not isinstance(slot_index, int)
                    or not re.fullmatch(r"[0-9a-f]{64}", fingerprint)
                    or isinstance(occurrence, bool) or not isinstance(occurrence, int)):
                continue
            equipped_items.append({
                "slot_index": slot_index,
                "serial_sha256": fingerprint,
                "occurrence": occurrence,
            })
        if not equipped_items:
            raise ValueError(self._t("dialogs", "live_no_entries"))
        return {
            "save_name": self.save_name,
            "slot": slot,
            "config_name": config_name,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "source": "live",
            "equipped_items": equipped_items,
            "skill_graphs": [],
        }

    def _live_apply_payload(self, saved: dict) -> dict:
        entries = []
        seen_slots = set()
        for item in saved.get("equipped_items", []):
            if not isinstance(item, dict):
                continue
            slot_index = item.get("slot_index")
            if slot_index is None:
                match = re.fullmatch(r"slot_(\d+)", str(item.get("slot") or ""))
                slot_index = int(match.group(1)) if match else None
            serial = str(item.get("serial") or "")
            fingerprint = self._live_item_fingerprint(serial, str(item.get("serial_sha256") or ""))
            if (isinstance(slot_index, bool) or not isinstance(slot_index, int)
                    or slot_index < 0 or slot_index in seen_slots
                    or not re.fullmatch(r"[0-9a-f]{64}", fingerprint)):
                continue
            seen_slots.add(slot_index)
            entry = {"slot_index": slot_index, "serial_sha256": fingerprint}
            occurrence = item.get("occurrence")
            if isinstance(occurrence, int) and not isinstance(occurrence, bool):
                entry["occurrence"] = occurrence
            entries.append(entry)
        return {"entries": entries}

    # ------------------------------------------------------------------ #
    # 显示构建
    # ------------------------------------------------------------------ #
    def _display_slot_content(self, slot: int) -> None:
        saved = self._saved_loadouts.get(slot)
        if saved:
            self._display_loadout_data(saved)
        else:
            placeholder_key = "empty_slot_live" if self.liveMode else "empty_slot"
            self._equipped_rows = [{"kind": "placeholder", "text": self._t("placeholders", placeholder_key)}]
            self._skill_rows = [{"kind": "placeholder", "text": self._t("placeholders", "empty_slot_skills")}]
        self.dataChanged.emit()

    def _display_loadout_data(self, loadout: dict) -> None:
        rows = []
        equipped_items = loadout.get("equipped_items", [])
        if equipped_items:
            for item_data in equipped_items:
                slot_index = item_data.get("slot_index")
                slot_key = item_data.get("slot", "")
                if not slot_key and isinstance(slot_index, int) and not isinstance(slot_index, bool):
                    slot_key = f"slot_{slot_index}"
                slot_name = self._t_slot(slot_key)
                serial = str(item_data.get("serial") or "")
                fingerprint = str(item_data.get("serial_sha256") or "").strip().lower()
                if loadout.get("source") == "live":
                    if not fingerprint and serial.startswith("@U"):
                        fingerprint = self._live_item_fingerprint(serial)
                    if not fingerprint:
                        continue
                    if serial.startswith("@U"):
                        item_name = (
                            self._get_weapon_real_name(serial)
                            if slot_key in WEAPON_SLOT_KEYS else ""
                        ) or self._decode_item_name(serial)
                    else:
                        item_name = f"SHA-256 {fingerprint[:16]}…"
                    rows.append({"kind": "item", "slot": slot_name, "name": item_name,
                                 "serial": fingerprint})
                else:
                    if not serial:
                        continue
                    if slot_key in WEAPON_SLOT_KEYS:
                        item_name = self._get_weapon_real_name(serial)
                        if not item_name:
                            item_name = self._decode_item_name(serial)
                    else:
                        item_name = self._decode_item_name(serial)
                    rows.append({"kind": "item", "slot": slot_name, "name": item_name,
                                 "serial": serial})
        else:
            rows.append({"kind": "placeholder", "text": self._t("placeholders", "no_equipped")})
        self._equipped_rows = rows

        skill_graphs = loadout.get("skill_graphs", [])
        if skill_graphs:
            self._skill_rows = self._build_skill_rows(skill_graphs)
        else:
            self._skill_rows = [{"kind": "placeholder", "text": self._t("placeholders", "no_skills")}]

    def _get_equipped_data(self):
        try:
            state = self.yaml_data.get("state", self.yaml_data)
            inventory = state.get("inventory", {})
            equipped_inv = inventory.get("equipped_inventory", {})
            return equipped_inv.get("equipped", {})
        except (AttributeError, TypeError):
            return None

    def _refresh_equipped_display_from_yaml(self) -> None:
        if not self.yaml_data:
            self._equipped_rows = [{"kind": "placeholder", "text": self._t("placeholders", "open_first")}]
            self.dataChanged.emit()
            return
        equipped_data = self._get_equipped_data()
        if not equipped_data:
            self._equipped_rows = [{"kind": "placeholder", "text": self._t("placeholders", "no_equipped_data")}]
            self.dataChanged.emit()
            return
        rows = []
        for slot_key in ["slot_0", "slot_1", "slot_2", "slot_3", "slot_4",
                         "slot_5", "slot_6", "slot_7", "slot_8"]:
            if slot_key not in equipped_data:
                continue
            slot_name = self._t_slot(slot_key)
            item_list = equipped_data[slot_key]
            if isinstance(item_list, list) and len(item_list) > 0:
                item = item_list[0]
            elif isinstance(item_list, dict):
                item = item_list
            else:
                continue
            serial = item.get("serial", "")
            if not serial:
                continue
            if slot_key in WEAPON_SLOT_KEYS:
                item_name = self._get_weapon_real_name(serial)
                if not item_name:
                    item_name = self._decode_item_name(serial)
            else:
                item_name = self._decode_item_name(serial)
            rows.append({"kind": "item", "slot": slot_name, "name": item_name, "serial": serial})
        if not rows:
            rows.append({"kind": "placeholder", "text": self._t("placeholders", "no_items")})
        self._equipped_rows = rows
        self.dataChanged.emit()

    def _refresh_skills_display_from_yaml(self) -> None:
        if not self.yaml_data:
            self._skill_rows = [{"kind": "placeholder", "text": self._t("placeholders", "no_data")}]
            self.dataChanged.emit()
            return
        progression = self.yaml_data.get("progression", {})
        graphs = progression.get("graphs", [])
        skill_graphs = _get_skill_graphs(graphs)
        if not skill_graphs:
            self._skill_rows = [{"kind": "placeholder", "text": self._t("placeholders", "no_data")}]
            self.dataChanged.emit()
            return
        self._skill_rows = self._build_skill_rows(skill_graphs)
        self.dataChanged.emit()

    def _build_skill_rows(self, skill_graphs: list) -> list[dict[str, str]]:
        class_name = self._get_character_class_name()
        class_id = str(self.class_ids.get(class_name, 0))
        rows = [{"kind": "header", "text": self._t("labels", "activated_skills")}]
        pts_suffix = self._t("labels", "points_suffix")
        activated_text = self._t("labels", "activated")
        found_any = False
        for graph in skill_graphs:
            graph_name = graph.get("name", "")
            for node in graph.get("nodes", []):
                name = node.get("name") or self._t("decode", "unknown")
                pts = node.get("points_spent", 0)
                is_activated = node.get("is_activated", False)
                if pts and pts > 0:
                    found_any = True
                    display_name, icon_url = self._get_skill_display_info(name, class_name, class_id, graph_name)
                    rows.append({"kind": "skill", "name": display_name,
                                 "status": f"{pts}{pts_suffix}", "color": "#64b5f6",
                                 "iconUrl": icon_url})
                elif is_activated:
                    found_any = True
                    display_name, icon_url = self._get_skill_display_info(name, class_name, class_id, graph_name)
                    rows.append({"kind": "skill", "name": display_name,
                                 "status": activated_text, "color": "#4caf50",
                                 "iconUrl": icon_url})
        if not found_any:
            rows.append({"kind": "placeholder", "text": self._t("placeholders", "no_activated")})
        return rows
