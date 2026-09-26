"""装备编辑器共享视图模型：移植 BaseEquipmentEditorTab 的全部非渲染逻辑。

四族装备（手雷/护盾/修复套件/重武器）共用本基类：子类声明数据源、MFG_IDS、perk 组布局与规则分组映射，
差异钩子（序列号组装、导入回填、厂商切换附加行为）在子类覆写。

与主线保持一致的行为：厂商切换联动稀有度与 perk 组、chip 单选组、picker 多选组
（可堆叠计数）、实时属性预览、自然生成规则合法性指引（状态徽章 + 组预算 +
候选项 ✓/! 标记）、从背包物品/Base85 导入回填（保留未知 token）、输出 serial 生成。
"""

from __future__ import annotations

import random
import re
from typing import Any

import pandas as pd
from PyQt6.QtCore import pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QApplication

from core import (
    b_encoder,
    bl4_functions as bl4f,
    item_display_resolver,
    lookup,
    resource_loader,
)
from core.serial_import import (
    build_header,
    decode_base85,
    parse_components,
    source_texts,
    split_decoded,
)
from core import item_card_data

from .base import PageViewModel

RARITY_ORDER = {"common": 0, "uncommon": 1, "rare": 2, "epic": 3, "legendary": 4, "pearl": 5}

_FLAG_CODE_ORDER = ("1", "3", "5", "17", "33", "65", "129")

# legit 候选下拉项上色（对齐主线 set_candidate_states 的蓝/橙半透明背景）
_KIND_POPUP_BG = {
    "legal": "#304a90e2",
    "warning": "#26e6a439",
    "modified": "#30ce5b5b",
}


class EquipmentBaseViewModel(PageViewModel):
    """装备编辑器 VM 基类（不注册；由四族子类 @register）。"""

    STRINGS_SECTION: str | None = None

    # --- 子类提供的类属性（契约同主线 BaseEquipmentEditorTab） ------------
    EQUIP_TYPE = ""
    UI_LOC_KEY = ""
    DEFAULT_SEED: int | None = 305
    MFG_IDS: list[int] = []
    BACKPACK_TYPE_EN = ""
    ITEM_LABEL = "Item"
    PREVIEW_FIELDS = {
        "Grenade": ("damage", "cooldown", "radius", "charges", "critical_damage", "critical_chance"),
        "Shield": ("capacity", "recharge_rate", "recharge_delay", "armor_segments", "damage_reduction"),
        "Repkit": ("healing", "instant_healing", "health_over_time", "duration", "cooldown", "charges"),
        "Heavy Weapon": ("damage", "dps", "accuracy", "fire_rate", "magazine", "cooldown",
                         "critical_damage", "splash_radius"),
    }
    #: perk 组 key -> 规则组名；空映射 = 该族不显示合法性指引
    RULE_GROUPS_BY_PICKER: dict[str, tuple[str, ...]] = {}

    dataChanged = pyqtSignal()

    def __init__(self, app, parent=None):
        super().__init__(app, parent)
        self.current_lang = str(app.language)
        self._character_level = "50"
        self._loading_import = False
        self._imported_copy = False
        self._source_seed = self.DEFAULT_SEED
        self._source_header: dict[str, Any] | None = None
        self._source_name = ""
        self._preserved_tokens: list[str] = []
        self._preserved_children: dict[int, list[int]] = {}
        self._encode_error = False
        self._raw_output = ""
        self._b85_output = ""
        self._stats_preview: list[dict[str, str]] = []
        self._guidance: dict[str, Any] = {"status": "", "statusKey": "unknown",
                                          "reason": "", "groups": ""}
        self._guidance_groups: dict[str, dict[str, Any]] = {}
        self._guidance_ready = False
        self._mfg_options: list[int] = []
        self._mfg_index = 0
        self._rarity_options: list[dict[str, Any]] = []
        self._rarity_index = -1
        self._level = self._character_level
        self._flag_labels: list[str] = []
        self._flag_index = 0
        self._group_cfgs: list[dict[str, Any]] = []
        self._group_titles: dict[str, str] = {}
        self._chip_options_state: dict[str, list[dict[str, Any]]] = {}
        self._chip_sel: dict[str, Any] = {}
        self._picker_src: dict[str, list[dict[str, Any]]] = {}
        self._picker_sel: dict[str, list[dict[str, Any]]] = {}
        self._backpack_items: list[dict[str, str]] = []
        self._roll_constraints: dict[str, Any] = {}
        self._roll_count = 5
        self.df_main = None
        self.df_mfg = None
        self.localization: dict[str, str] = {}
        self.mfg_ids = list(self.MFG_IDS)

        self._load_family_data(self.current_lang)
        if self.df_main is not None:
            self._on_mfg_change()

    # ------------------------------------------------------------------ #
    # 子类钩子（契约同主线）
    # ------------------------------------------------------------------ #
    def load_data(self, lang: str):  # pragma: no cover - abstract
        raise NotImplementedError

    def _declare_perk_groups(self) -> list[dict[str, Any]]:  # pragma: no cover - abstract
        raise NotImplementedError

    def _chip_options(self, key: str, mfg_id: int | None) -> list[dict[str, Any]] | None:
        """chip 组选项（含 None 项）；返回 None 表示该 key 不是 chip 组。"""
        return None

    def _group_items(self, key: str, mfg_id: int) -> list[dict[str, Any]]:
        """picker 组可用条目（主线 CatalogPicker item 格式）。"""
        return []

    def _picker_categories(self, key: str) -> list[tuple[str, str]]:
        """picker 组分类过滤 (key, label)，首项为 all。"""
        return [("all", self.ui_loc.get("misc", {}).get("all", "All"))]

    def _build_skill_parts(self, mfg_id: int):  # pragma: no cover - abstract
        raise NotImplementedError

    def _apply_components(self, component: str):  # pragma: no cover - abstract
        raise NotImplementedError

    def _on_mfg_changed_extra(self, mfg_id: int) -> None:
        """Hook：厂商切换的附加行为（如护盾清除不兼容 augment）。"""

    def _extra_family_load(self) -> None:
        """Hook：数据加载后的附加初始化（如重武器加载 pearl 目录）。"""

    def _extra_reset_state(self) -> None:
        """Hook：导入状态重置。"""

    def _initial_preserved_children(self) -> dict[int, list[int]]:
        return {}

    def _default_new_header(self, mfg_id: int, level: str) -> str:
        return f"{mfg_id}, 0, 1, {level}| 2, {self._source_seed}"

    def _backpack_predicate(self, item: dict[str, Any]) -> bool:
        return (item.get("type_en") == self.BACKPACK_TYPE_EN
                and item.get("container") == "Backpack")

    # -- 规则指引钩子 ------------------------------------------------------ #
    def _generation_ref_for_option(self, key: str, data: Any) -> str:
        return ""

    def _generation_group_text(self, group: Any) -> str:
        if self.EQUIP_TYPE == "shield" and str(group) == "body":
            return str((self.ui_loc or {}).get("misc", {}).get("base") or "Base")
        groups = (self.legit_loc or {}).get("groups") or {}
        return str(groups.get(str(group), group))

    def _candidate_state_for_option(self, key: str, data: Any, ref: str,
                                    rule_keys, groups) -> dict[str, Any]:
        return self._candidate_state(ref, rule_keys, groups)

    # ------------------------------------------------------------------ #
    # 数据 / 本地化
    # ------------------------------------------------------------------ #
    def _load_family_data(self, lang: str) -> None:
        self.current_lang = lang
        self.df_main, self.df_mfg, self.localization = self.load_data(lang)
        self.ui_loc = self.app.localizer.section(self.UI_LOC_KEY)
        self.legit_loc = self.app.localizer.section("equipment_legit")
        self._flags = resource_loader.get_flag_labels(lang)
        self._flag_labels = [self._flags[k] for k in _FLAG_CODE_ORDER if k in self._flags]
        self._flag_index = self._default_flag_index()
        self._extra_family_load()
        if self.df_main is None:
            return
        self._group_cfgs = self._declare_perk_groups()
        self._group_titles = {}
        self._chip_options_state = {}
        self._chip_sel = {}
        self._picker_src = {}
        self._picker_sel = {}
        for cfg in self._group_cfgs:
            key = cfg["key"]
            self._group_titles[key] = self._group_base_title(cfg)
            self._chip_options_state[key] = []
            self._chip_sel[key] = None
            self._picker_src[key] = []
            self._picker_sel[key] = []
        self._mfg_options = sorted(self.mfg_ids)
        if not self._mfg_options:
            return
        self._mfg_index = min(self._mfg_index, len(self._mfg_options) - 1)
        self._level = self._character_level

    def _(self, text: Any) -> str:
        return self.localization.get(str(text), str(text))

    def _group_base_title(self, cfg: dict[str, Any]) -> str:
        return str(self.ui_loc.get("groups", {}).get(cfg.get("title_key", ""), cfg.get("title_key", "")))

    def _stat_labels(self) -> dict[str, str]:
        return dict((self.app.localizer.section("items_tab") or {}).get("columns") or {})

    def _no_element_text(self) -> str:
        return str((self.app.localizer.section("weapon_gen_tab").get("labels") or {}).get("no_element")
                   or "No Element")

    def _get_mfg_name(self, mfg_id: int) -> str:
        if mfg_id in lookup.REVERSE_ID_MAP:
            mfg_en = lookup.REVERSE_ID_MAP[mfg_id][0]
            return bl4f.get_localized_string(mfg_en)
        return "Unknown"

    def _manufacturer_option_label(self, mfg_id: int) -> str:
        return f"{self._get_mfg_name(mfg_id)} - {mfg_id}"

    def _legit_text(self, key: str, fallback: str) -> str:
        return str((self.legit_loc or {}).get(key) or fallback)

    @staticmethod
    def _generation_range(spec: dict[str, Any]) -> str:
        low = int(spec.get("effective_min", spec.get("min", 0)))
        high = int(spec.get("effective_max", spec.get("max", 0)))
        return str(low) if low == high else f"{low}–{high}"

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        lang = str(self.app.language)
        if self.df_main is None or lang != self.current_lang:
            imported_serial = self._b85_output if self._imported_copy else ""
            imported_name = self._source_name
            imported_flag = self._flag_value() if self._imported_copy else None
            self._load_family_data(lang)
            if self.df_main is None:
                self.dataChanged.emit()
                return
            if imported_serial:
                try:
                    self._load_serial_copy(imported_serial, name=imported_name,
                                           state_flags=imported_flag)
                except ValueError:
                    self._reset_import_source()
            else:
                self._mfg_index = 0
                self._on_mfg_change()
        try:
            data = self.controller.get_character_data() or {}
            level = str(data.get("角色等级") or "")
        except Exception:
            level = ""
        if level and level != self._character_level:
            self._character_level = level
            if not self._imported_copy and self._level != level:
                self._level = level
                self._rebuild()
                return
        self.dataChanged.emit()

    # ------------------------------------------------------------------ #
    # QML 属性
    # ------------------------------------------------------------------ #
    @pyqtProperty(bool, notify=dataChanged)
    def dataLoaded(self) -> bool:
        return self.df_main is not None

    @pyqtProperty(str, notify=dataChanged)
    def loadErrorText(self) -> str:
        return str(self.ui_loc.get("dialogs", {}).get(
            "load_error", f"Error: {self.ITEM_LABEL} data failed to load."))

    @pyqtProperty(list, notify=dataChanged)
    def mfgOptions(self) -> list[dict[str, Any]]:
        return [{"label": self._manufacturer_option_label(m), "value": m} for m in self._mfg_options]

    @pyqtProperty(int, notify=dataChanged)
    def mfgIndex(self) -> int:
        return self._mfg_index

    @pyqtProperty(list, notify=dataChanged)
    def rarityOptions(self) -> list[dict[str, Any]]:
        return [{"label": o["label"], "value": o["id"]} for o in self._rarity_options]

    @pyqtProperty(int, notify=dataChanged)
    def rarityIndex(self) -> int:
        return self._rarity_index

    @pyqtProperty(str, notify=dataChanged)
    def level(self) -> str:
        return self._level

    @pyqtProperty(list, notify=dataChanged)
    def flagOptions(self) -> list[dict[str, Any]]:
        return [{"label": label, "value": label.split(" ", 1)[0]} for label in self._flag_labels]

    @pyqtProperty(int, notify=dataChanged)
    def flagIndex(self) -> int:
        return self._flag_index

    @pyqtProperty(str, notify=dataChanged)
    def rawOutput(self) -> str:
        return self._raw_output

    @pyqtProperty(str, notify=dataChanged)
    def base85Output(self) -> str:
        return self._b85_output

    @pyqtProperty(bool, notify=dataChanged)
    def encodeError(self) -> bool:
        return self._encode_error

    @pyqtProperty(bool, notify=dataChanged)
    def importedCopy(self) -> bool:
        return self._imported_copy

    @pyqtProperty(str, notify=dataChanged)
    def sourceText(self) -> str:
        texts = source_texts(self.current_lang)
        if self._imported_copy:
            name = self._source_name or "Base85"
            return texts["imported"].format(name=name)
        return texts["new_source"]

    @pyqtProperty("QVariantMap", notify=dataChanged)
    def sourceTexts(self) -> dict[str, str]:
        return source_texts(self.current_lang)

    @pyqtProperty(list, notify=dataChanged)
    def statsPreview(self) -> list[dict[str, str]]:
        return self._stats_preview

    @pyqtProperty("QVariantMap", notify=dataChanged)
    def guidance(self) -> dict[str, Any]:
        return self._guidance

    @pyqtProperty(list, notify=dataChanged)
    def groups(self) -> list[dict[str, Any]]:
        return self._build_groups_view()

    @pyqtProperty(list, notify=dataChanged)
    def backpackItems(self) -> list[dict[str, str]]:
        return self._backpack_items

    # ------------------------------------------------------------------ #
    # QML 槽
    # ------------------------------------------------------------------ #
    @pyqtSlot(int)
    def setMfgIndex(self, index: int) -> None:
        if self._imported_copy or not 0 <= index < len(self._mfg_options):
            return
        if index == self._mfg_index:
            return
        self._mfg_index = index
        self._on_mfg_change()

    @pyqtSlot(int)
    def setRarityIndex(self, index: int) -> None:
        if not -1 <= index < len(self._rarity_options):
            return
        self._rarity_index = index
        self._rebuild()

    @pyqtSlot(str)
    def setLevel(self, text: str) -> None:
        self._level = text
        self._rebuild()

    @pyqtSlot(int)
    def setFlagIndex(self, index: int) -> None:
        if not 0 <= index < len(self._flag_labels):
            return
        self._flag_index = index
        self.dataChanged.emit()

    @pyqtSlot(str, str)
    def selectChip(self, key: str, pid: str) -> None:
        if key not in self._chip_sel:
            return
        self._chip_sel[key] = self._norm_qml_pid(pid)
        self._rebuild()

    @pyqtSlot(str, str)
    def addPickerItem(self, key: str, item_key: str) -> None:
        option = next((o for o in self._picker_src.get(key, []) if o.get("key") == item_key), None)
        if option is None or option.get("disabled"):
            return
        self._picker_add(key, option)
        self._rebuild()

    @pyqtSlot(str, int)
    def removePickerItem(self, key: str, index: int) -> None:
        entries = self._picker_sel.get(key)
        if entries and 0 <= index < len(entries):
            entries.pop(index)
            self._rebuild()

    @pyqtSlot(str, int, int)
    def setPickerItemCount(self, key: str, index: int, count: int) -> None:
        entries = self._picker_sel.get(key)
        if entries and 0 <= index < len(entries):
            entries[index]["count"] = max(1, int(count))
            self._rebuild()

    @pyqtSlot(str, "QVariantList")
    def addPickerItems(self, key: str, keys) -> None:
        """批量添加（内嵌双栏面板的多选添加），一次 _rebuild。"""
        options = {str(o.get("key")): o for o in self._picker_src.get(key, [])}
        changed = False
        for item_key in keys or []:
            option = options.get(str(item_key))
            if option is None or option.get("disabled"):
                continue
            self._picker_add(key, option)
            changed = True
        if changed:
            self._rebuild()

    @pyqtSlot(str, "QVariantList", int)
    def setPickerItemsCount(self, key: str, indices, count: int) -> None:
        """批量改数（面板多选行统一步进），一次 _rebuild。"""
        entries = self._picker_sel.get(key)
        if not entries:
            return
        changed = False
        for index in indices or []:
            try:
                i = int(index)
            except (TypeError, ValueError):
                continue
            if 0 <= i < len(entries):
                entries[i]["count"] = max(1, int(count))
                changed = True
        if changed:
            self._rebuild()

    @pyqtSlot(str)
    def clearPickerGroup(self, key: str) -> None:
        if key in self._picker_sel:
            self._picker_sel[key] = []
            self._rebuild()

    @pyqtSlot(str, "QVariantList", int)
    def stepPickerItemsCount(self, key: str, indices, delta: int) -> None:
        """已选条目相对步进（每个目标各自 ±delta，下限 1）；一次 _rebuild。"""
        entries = self._picker_sel.get(key)
        if not entries:
            return
        changed = False
        for index in indices or []:
            try:
                i = int(index)
            except (TypeError, ValueError):
                continue
            if 0 <= i < len(entries):
                new_count = max(1, int(entries[i].get("count", 1)) + int(delta))
                if new_count != entries[i].get("count", 1):
                    entries[i]["count"] = new_count
                    changed = True
        if changed:
            self._rebuild()

    @pyqtSlot()
    def copyRawToClipboard(self) -> None:
        QApplication.clipboard().setText(self._raw_output)
        self.app.toast(str(self.ui_loc.get("dialogs", {}).get("copied", "Copied to clipboard.")),
                       "success")

    @pyqtSlot()
    def copyBase85ToClipboard(self) -> None:
        QApplication.clipboard().setText(self._b85_output)
        self.app.toast(str(self.ui_loc.get("dialogs", {}).get("copied", "Copied to clipboard.")),
                       "success")

    @pyqtSlot()
    def addToBackpack(self) -> None:
        dialogs = self.ui_loc.get("dialogs", {})
        if not self._b85_output or self._encode_error:
            self.app.toast(str(dialogs.get("gen_first", "Generate a valid serial code first.")),
                           "warning")
            return
        self.app.addSerialToBackpack(self._b85_output, self._flag_value())

    @pyqtSlot(result=int)
    def prepareBackpackImport(self) -> int:
        texts = source_texts(self.current_lang)
        if not self.controller.yaml_obj:
            self.app.toast(texts["no_save"], "warning")
            return 0
        try:
            items = [it for it in self.controller.get_all_items() if self._backpack_predicate(it)]
        except Exception:
            items = []
        self._backpack_items = []
        for item in items:
            name = str(item.get("name") or item.get("manufacturer") or item.get("type") or "Item")
            detail = " · ".join(
                str(v) for v in (item.get("manufacturer"), item.get("type"),
                                 f"Lv.{item.get('level', '?')}") if v)
            self._backpack_items.append({
                "name": name,
                "detail": detail,
                "serial": str(item.get("serial", "")),
                "flag": str(item.get("state_flags", "") or ""),
            })
        self.dataChanged.emit()
        return len(self._backpack_items)

    @pyqtSlot(int)
    def importBackpackItem(self, index: int) -> None:
        if not 0 <= index < len(self._backpack_items):
            return
        item = self._backpack_items[index]
        texts = source_texts(self.current_lang)
        try:
            self._load_serial_copy(item["serial"], name=item["name"] or self.ITEM_LABEL,
                                   state_flags=item["flag"])
        except ValueError as exc:
            self._reset_import_source()
            self.app.toast(f"{texts['import_error']}: {exc}", "error")

    @pyqtSlot(str)
    def importBase85(self, serial: str) -> None:
        serial = (serial or "").strip()
        if not serial:
            return
        texts = source_texts(self.current_lang)
        try:
            self._load_serial_copy(serial, name="Base85")
        except ValueError as exc:
            self._reset_import_source()
            self.app.toast(f"{texts['import_error']}: {exc}", "error")

    @pyqtSlot()
    def resetSource(self) -> None:
        self._reset_import_source()

    def open_item_serial(self, item: dict) -> None:
        """公开入口：从 YAML 编辑器/物品快照跳转加载（对齐主线同名方法）。"""
        flags = item.get("state_flags")
        try:
            flags = int(str(flags).strip()) if str(flags).strip() else None
        except ValueError:
            flags = None
        self._load_serial_copy(str(item.get("serial", "") or ""),
                               name=str(item.get("name", "") or ""),
                               state_flags=flags)

    # ------------------------------------------------------------------ #
    # 厂商 / 稀有度联动
    # ------------------------------------------------------------------ #
    def _current_mfg_id(self) -> int | None:
        if 0 <= self._mfg_index < len(self._mfg_options):
            return int(self._mfg_options[self._mfg_index])
        return None

    def _current_rarity_id(self) -> int | None:
        if 0 <= self._rarity_index < len(self._rarity_options):
            return int(self._rarity_options[self._rarity_index]["id"])
        return None

    def _default_flag_index(self) -> int:
        target = self._flags.get("3") if hasattr(self, "_flags") else None
        for index, label in enumerate(self._flag_labels):
            if label == target:
                return index
        return 0

    def _flag_value(self) -> str:
        if 0 <= self._flag_index < len(self._flag_labels):
            return self._flag_labels[self._flag_index].split(" ", 1)[0]
        return "3"

    def _set_flag_value(self, value) -> None:
        target = str("3" if value in (None, "") else value).strip().split(" ", 1)[0]
        for index, label in enumerate(self._flag_labels):
            if label.split(" ", 1)[0] == target:
                self._flag_index = index
                return
        if target and target not in [l.split(" ", 1)[0] for l in self._flag_labels]:
            self._flag_labels.append(target)
        self._flag_index = len(self._flag_labels) - 1

    def _ncs_rarity_child_name(self, mfg_id: int, part_id: int) -> str:
        """Return a named child carried by a blank rarity composition row."""
        refs = item_display_resolver._item_index().get("part_refs") or {}
        composition = refs.get(f"{int(mfg_id)}:{int(part_id)}") or {}
        for rule in (composition.get("selection_rules") or {}).get("part_types", []):
            for ref_key in rule.get("part_refs") or []:
                child = refs.get(str(ref_key)) or {}
                if child.get("category") not in {"primary_augment", "secondary_augment", "unique"}:
                    continue
                name = item_display_resolver.equipment_part_name(str(ref_key), self.current_lang)
                if name:
                    return name
        return ""

    def _rebuild_rarity_options(self, mfg_id: int) -> None:
        rarity_rows = self.df_mfg[
            (self.df_mfg["Manufacturer ID"] == mfg_id) & (self.df_mfg["Part_type"] == "Rarity")
        ].copy()
        rarity_rows["_sort_rarity"] = rarity_rows["Stat"].map(
            lambda value: RARITY_ORDER.get(str(value).strip().casefold(), 99))
        rarity_rows = rarity_rows.sort_values(["_sort_rarity", "Part_ID"], kind="stable")
        options = []
        for _, r in rarity_rows.iterrows():
            desc = r["Description"]
            if pd.isna(desc) or not str(desc).strip():
                # NCS keeps some named legendary composition labels on the
                # linked primary augment rather than the rarity CSV row (for
                # example Torgue Repkit 261:9 -> 261:8 Outburst).
                desc = self._ncs_rarity_child_name(mfg_id, int(r["Part_ID"]))
            label = f"{self._(r['Stat'])} - {desc if pd.notna(desc) else ''}".strip(" -")
            options.append({"id": int(r["Part_ID"]), "label": label,
                            "stat": str(r["Stat"]).strip(), "desc": str(desc or "")})
        self._rarity_options = options
        self._rarity_index = 0 if options else -1

    def _on_mfg_change(self) -> None:
        mfg_id = self._current_mfg_id()
        if mfg_id is None or self.df_main is None:
            return
        self._rebuild_rarity_options(mfg_id)
        self._on_mfg_changed_extra(mfg_id)
        self._rebuild()

    def _is_gold_skin_selected(self) -> bool:
        mfg_id = self._current_mfg_id()
        part_id = self._current_rarity_id()
        if mfg_id is None or part_id is None or self.df_mfg is None:
            return False
        try:
            rows = self.df_mfg[
                (self.df_mfg["Manufacturer ID"] == int(mfg_id))
                & (self.df_mfg["Part_ID"] == int(part_id))
                & (self.df_mfg["Part_type"] == "Rarity")
            ]
        except (KeyError, TypeError, ValueError):
            return False
        if rows.empty:
            return False
        row = rows.iloc[0]
        values = [row.get("Description", ""), row.get("Description_ZH", ""), row.get("Description_EN", "")]
        normalized = {str(value).strip().casefold() for value in values if pd.notna(value)}
        return bool(normalized.intersection({"gold skin", "goldskin", "金皮肤"}))

    # ------------------------------------------------------------------ #
    # 行格式化（对齐主线 _fmt_row / _row_description）
    # ------------------------------------------------------------------ #
    @staticmethod
    def _norm_pid(pid: Any) -> Any:
        try:
            return int(pid)
        except (TypeError, ValueError):
            return pid

    @staticmethod
    def _norm_qml_pid(pid: str) -> Any:
        if pid == "":
            return None
        try:
            return int(pid)
        except (TypeError, ValueError):
            return pid

    @staticmethod
    def _row_ref_key(r) -> str:
        owner = next(
            (
                r[column]
                for column in (
                    "Grenade_perk_main_ID",
                    "Shield_perk_main_ID",
                    "Repkit_perk_main_ID",
                    "Heavy_perk_main_ID",
                    "Manufacturer ID",
                )
                if column in r and pd.notna(r[column])
            ),
            None,
        )
        try:
            return f"{int(owner)}:{int(r['Part_ID'])}"
        except (TypeError, ValueError, KeyError):
            return ""

    def _row_description(self, r) -> str:
        fallback = ""
        if "Description" in r and pd.notna(r["Description"]) and r["Description"]:
            fallback = str(r["Description"])
        decoded = self._raw_output
        ref_key = self._row_ref_key(r)
        if not decoded or not ref_key:
            return fallback
        try:
            return item_display_resolver.format_equipment_part_description(
                decoded, self.BACKPACK_TYPE_EN, ref_key, self.current_lang) or fallback
        except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError):
            return fallback

    def _fmt_row(self, r, extra: str | None = None):
        text = item_display_resolver.equipment_part_name(
            self._row_ref_key(r), self.current_lang, self._(r["Stat"]))
        description = self._row_description(r)
        if description:
            text += f" - {description}"
        if extra:
            text = f"{extra}{text}"
        return text, self._norm_pid(r["Part_ID"])

    def _firmware_group_df(self, owner_col: str, owner_id: int) -> "pd.DataFrame":
        rows = [
            {owner_col: owner_id, "Part_ID": int(part_id), "Part_type": "Firmware",
             "Stat": "", "Description": ""}
            for part_id, _internal in item_display_resolver.equipment_firmware_parts(owner_id)
        ]
        return pd.DataFrame(rows, columns=[owner_col, "Part_ID", "Part_type", "Stat", "Description"])

    def _chip_option_list(self, key: str, df, fmt) -> list[dict[str, Any]]:
        """主线 _populate_chip_group 的 VM 版：行 -> 选项 dict（含 None 项）。"""
        options = [{
            "pid": None,
            "label": str(self.ui_loc.get("misc", {}).get("none", "None")),
            "tooltip": "",
        }]
        for _, r in df.iterrows():
            text, pid = fmt(r)
            if key == "firmware":
                name = item_display_resolver.equipment_part_name(
                    self._row_ref_key(r), self.current_lang, self._(r.get("Stat", "")))
                match = re.search(r"(?:^|,\s*)L1:\s*(.*?)(?=,\s*L2:|$)", text)
                compact = " - ".join(filter(None, (name, match.group(1).strip() if match else ""))) \
                    or name or text
                options.append({"pid": pid, "label": compact, "tooltip": text})
            else:
                options.append({"pid": pid, "label": text, "tooltip": text})
        return options

    # ------------------------------------------------------------------ #
    # 组视图（QML 绑定）
    # ------------------------------------------------------------------ #
    def _build_groups_view(self) -> list[dict[str, Any]]:
        out = []
        for cfg in self._group_cfgs:
            key = cfg["key"]
            title = self._group_titles.get(key) or self._group_base_title(cfg)
            if cfg.get("mode") == "chip":
                selected = self._chip_sel.get(key)
                options = []
                for opt in self._chip_options_state.get(key, []):
                    candidate = opt.get("candidate") or {}
                    marker = str(candidate.get("marker") or "").strip()
                    label = str(opt.get("label", ""))
                    kind = str(candidate.get("kind", ""))
                    options.append({
                        "pid": "" if opt.get("pid") is None else str(opt.get("pid")),
                        # 主线 set_candidate_states：标记符拼进文本 + 蓝/橙背景 + 合法加粗
                        "label": f"{marker}  {label}" if marker else label,
                        "marker": marker,
                        "kind": kind,
                        "hint": str(candidate.get("hint", opt.get("tooltip", ""))),
                        "tooltip": str(opt.get("tooltip") or opt.get("detail") or label),
                        "selected": (opt.get("pid") is not None and selected == opt.get("pid")),
                        "isNone": opt.get("pid") is None,
                        # HusSelect 弹层项上色（vendor 补丁识别的扩展角色）
                        "itemBg": _KIND_POPUP_BG.get(kind, ""),
                        "itemColor": "",
                        "itemBold": kind == "legal",
                    })
                out.append({"key": key, "mode": "chip", "title": title, "options": options})
            else:
                options = []
                for opt in self._picker_src.get(key, []):
                    candidate = opt.get("candidate") or {}
                    options.append({
                        "key": str(opt.get("key", "")),
                        "label": str(opt.get("label", "")),
                        "detail": str(opt.get("detail", "")),
                        "category": str(opt.get("category") or ""),
                        "subcategory": str(opt.get("subcategory") or ""),
                        "searchText": str(opt.get("search_text") or opt.get("searchText") or ""),
                        "disabled": bool(opt.get("disabled")),
                        "disabledReason": str(opt.get("disabled_reason", "")),
                        "marker": str(candidate.get("marker", "")),
                        "kind": str(candidate.get("kind", "")),
                        "hint": str(candidate.get("hint", "")),
                        "tooltip": str(opt.get("tooltip") or opt.get("detail") or opt.get("label") or ""),
                        "inPicker": True,
                    })
                entries = [{
                    "key": str(e.get("key", "")),
                    "label": str(e.get("label", "")),
                    "count": int(e.get("count", 1)),
                } for e in self._picker_sel.get(key, [])]
                out.append({
                    "key": key,
                    "mode": "picker",
                    "title": title,
                    "stackable": bool(cfg.get("stackable")),
                    "categories": [{"key": k, "label": l} for k, l in self._picker_categories(key)],
                    "options": options,
                    "entries": entries,
                })
        return out

    # ------------------------------------------------------------------ #
    # picker/chip 状态操作（导入与组装共用）
    # ------------------------------------------------------------------ #
    def _group_cfg(self, key: str) -> dict[str, Any]:
        return next((c for c in self._group_cfgs if c["key"] == key), {})

    def _entries(self, key: str) -> list[dict[str, Any]]:
        return self._picker_sel.get(key, [])

    def _picker_add(self, key: str, it: dict[str, Any], count: int = 1) -> None:
        entries = self._picker_sel[key]
        for entry in entries:
            if entry["key"] == it["key"]:
                if self._group_cfg(key).get("stackable"):
                    entry["count"] = int(entry.get("count", 1)) + count
                return
        entries.append({"key": it["key"], "label": it["label"],
                        "data": it.get("data"), "count": count})

    def _picker_item_map(self, key: str) -> dict[Any, dict[str, Any]]:
        result = {}
        for it in self._picker_src.get(key, []):
            result[self._picker_data_key(it.get("data"))] = it
        return result

    @staticmethod
    def _picker_data_key(data: Any) -> Any:
        if isinstance(data, (tuple, list)):
            return tuple(int(x) for x in data)
        try:
            return int(data)
        except (TypeError, ValueError):
            return data

    def _chip_option_pids(self, key: str) -> list[Any]:
        return [o["pid"] for o in self._chip_options_state.get(key, []) if o.get("pid") is not None]

    def _selected_button_pid(self, key: str) -> Any:
        return self._chip_sel.get(key)

    def _select_group_pid(self, key: str, pid: Any) -> bool:
        pid = self._norm_pid(pid)
        for opt in self._chip_options_state.get(key, []):
            if opt.get("pid") == pid:
                self._chip_sel[key] = pid
                return True
        return False

    def _checked_part_ids(self, *keys: str) -> list[Any]:
        ids = []
        for key in keys:
            pid = self._chip_sel.get(key)
            if pid is not None:
                ids.append(pid)
        return ids

    def _clear_import_widgets(self) -> None:
        for key in self._chip_sel:
            self._chip_sel[key] = None
        for key in self._picker_sel:
            self._picker_sel[key] = []

    # ------------------------------------------------------------------ #
    # 输出组装（对齐主线 rebuild_output）
    # ------------------------------------------------------------------ #
    def _rebuild(self) -> None:
        if self._loading_import or self.df_main is None:
            return
        try:
            mfg_id = self._current_mfg_id()
            if mfg_id is None:
                self.dataChanged.emit()
                return
            self._raw_output = self._compose_raw_output(mfg_id)
            encoded, err = b_encoder.encode_to_base85(self._raw_output)
            self._encode_error = bool(err)
            if err:
                dialogs = self.ui_loc.get("dialogs", {})
                self._b85_output = f"{dialogs.get('error', 'Error')}: {err}"
            else:
                self._b85_output = encoded
            self._update_stats(self._raw_output if not err else "")
            # 顺序对齐主线（先 _refresh_dynamic_descriptions 后 _update_generation_guidance）：
            # 候选标记写在重建后的选项上，反过来会被刷新抹掉、marker 永远为空。
            self._refresh_group_options()
            self._update_generation_guidance(self._raw_output if not err else "")
        except Exception as exc:  # 与主线一致：重建失败保留旧输出
            self._update_stats("")
            print(f"Rebuild error ({self.EQUIP_TYPE}): {exc}")
        # QML 全部属性都挂在 dataChanged 上；漏发会导致选择看似“无效”、
        # 穿梭框添加后界面不刷新（手雷/护盾/修复套件/重武器四页整体失灵）。
        self.dataChanged.emit()

    def _compose_raw_output(self, mfg_id: int) -> str:
        """按当前状态拼出反序列化文本（无副作用，规则指引的变体校验也用它）。"""
        level = self._level
        if self._imported_copy and self._source_header:
            header = build_header(self._source_header, mfg_id=mfg_id, level=level,
                                  seed=self._source_seed)
        else:
            header = self._default_new_header(mfg_id, level)
        skill_parts, secondary = self._build_skill_parts(mfg_id)
        rarity_id = self._current_rarity_id()
        if rarity_id:
            skill_parts.insert(0, f"{{{rarity_id}}}")
        if self._imported_copy:
            skill_parts.extend(self._preserved_tokens)
            for parent_id, children in self._preserved_children.items():
                secondary.setdefault(parent_id, []).extend(children)
        for k, v in secondary.items():
            if v:
                skill_parts.append(
                    f"{{{k}:[{' '.join(map(str, sorted(v)))}]}}" if len(v) > 1
                    else f"{{{k}:{v[0]}}}")
        return f"{header}|| " + " ".join(skill_parts) + " |"

    def _update_stats(self, decoded: str) -> None:
        try:
            stats = (item_display_resolver.resolve_equipment_stats(decoded, self.BACKPACK_TYPE_EN)
                     if decoded else {})
        except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError):
            stats = {}
        labels = self._stat_labels()
        preview = []
        for key in self.PREVIEW_FIELDS.get(self.BACKPACK_TYPE_EN, ()):
            raw = stats.get(key)
            if raw in (None, ""):
                continue
            value = item_display_resolver.format_equipment_stat(key, raw, self.current_lang)
            preview.append({
                "key": key,
                "label": str(labels.get(key, key.replace("_", " ").title())),
                "value": str(value if value != "" else raw),
            })
        self._stats_preview = preview

    # ------------------------------------------------------------------ #
    # 自然生成规则指引（对齐主线 _update_generation_guidance，仅 advisory）
    # ------------------------------------------------------------------ #
    def _update_generation_guidance(self, decoded: str) -> None:
        mapping = self.RULE_GROUPS_BY_PICKER
        self._guidance_groups = {}
        self._guidance_ready = False
        if not mapping or not decoded:
            self._guidance = {"status": "", "statusKey": "unknown", "reason": "", "groups": ""}
            return
        if self._is_gold_skin_selected():
            self._guidance = {
                "status": self._legit_text("status_gold", "Gold skin"),
                "statusKey": "suppressed",
                "reason": self._legit_text(
                    "gold_reason",
                    "Gold Skin is only a legendary-skin foundation, so natural-build guidance is disabled."),
                "groups": "",
            }
            for key in mapping:
                self._set_group_guidance(key, mapping[key], {}, False)
            return
        try:
            result = item_display_resolver.validate_weapon_generation(decoded, allow_incomplete=True)
        except Exception as exc:
            self._guidance = {
                "status": self._legit_text("status_unknown", "Unknown"),
                "statusKey": "unknown",
                "reason": str(exc),
                "groups": "",
            }
            return
        groups = result.get("groups") or {}
        ready = bool(result.get("rules_available") and result.get("composition_ref"))
        status = str(result.get("status") or "unknown")
        status_labels = {
            "legal": self._legit_text("status_legal", "Natural"),
            "incomplete": self._legit_text("status_incomplete", "Incomplete"),
            "modified": self._legit_text("status_modified", "Modified"),
            "conditional": self._legit_text("status_conditional", "Conditional"),
            "unknown": self._legit_text("status_unknown", "Unknown"),
        }
        reasons = list(dict.fromkeys(
            self._generation_violation_text(item) for item in result.get("violations") or []))
        if not reasons:
            reasons = [self._legit_text("reason_legal", "Matches the current natural-generation rules.")]
        ordered = []
        for rule_keys in mapping.values():
            for rule_key in rule_keys:
                if rule_key not in ordered:
                    ordered.append(rule_key)
        group_bits = []
        for rule_key in ordered:
            spec = groups.get(rule_key)
            if not isinstance(spec, dict):
                continue
            maximum = int(spec.get("effective_max", spec.get("max", 0)))
            actual = len(spec.get("selected") or [])
            if maximum <= 0 and actual <= 0:
                continue
            group_bits.append(
                f"{self._generation_group_text(rule_key)} {actual}/{self._generation_range(spec)}")
        self._guidance = {
            "status": status_labels.get(status, status_labels["unknown"]),
            "statusKey": status if status in status_labels else "unknown",
            "reason": " · ".join(reasons[:2]),
            "groups": " · ".join(group_bits),
        }
        self._guidance_groups = groups
        self._guidance_ready = ready
        for key, rule_keys in mapping.items():
            self._set_group_guidance(key, rule_keys, groups, ready)

    def _generation_violation_text(self, violation: dict[str, Any]) -> str:
        code = str(violation.get("code") or "")
        group = self._generation_group_text(violation.get("group") or "")
        if code == "count_below":
            template = self._legit_text("reason_count_below", "Missing {group} ({actual}/{limit})")
            return template.format(group=group, actual=violation.get("actual", 0),
                                   limit=violation.get("min", 0))
        if code == "count_above":
            template = self._legit_text("reason_count_above", "Too many {group} ({actual}/{limit})")
            return template.format(group=group, actual=violation.get("actual", 0),
                                   limit=violation.get("max", 0))
        mapping = {
            "part_not_allowed": "reason_part_not_allowed",
            "duplicate_part": "reason_duplicate_part",
            "missing_required_tag": "reason_missing_dependency",
            "excluded_tag_conflict": "reason_conflict",
            "foreign_root_part": "reason_foreign_part",
            "unknown_part": "reason_unknown_part",
            "unknown_composition": "reason_unknown_composition",
            "multiple_compositions": "reason_multiple_compositions",
            "unresolved_rule_parts": "reason_rule_gap",
            "conditional_availability": "reason_conditional",
        }
        fallbacks = {
            "reason_part_not_allowed": "A selected part is outside this natural template",
            "reason_duplicate_part": "The same part is selected more than once",
            "reason_missing_dependency": "A selected part is missing its dependency",
            "reason_conflict": "Selected parts conflict",
            "reason_foreign_part": "A cross-family part is selected",
            "reason_unknown_part": "An unknown part is present",
            "reason_unknown_composition": "Select a recognized item template",
            "reason_multiple_compositions": "More than one item template is selected",
            "reason_rule_gap": "Generation rules are incomplete",
            "reason_conditional": "This build requires conditional content",
        }
        key = mapping.get(code, "reason_modified")
        return self._legit_text(key, fallbacks.get(key, "Does not match the natural-generation rules"))

    def _candidate_state(self, ref: str, rule_keys, groups) -> dict[str, Any]:
        ref = str(ref or "")
        if not ref:
            return {}
        # 分级与 core.legit_status.candidate_state（职业模组/强化/武器编辑器）一致：
        # 选了就会变成魔改的候选一律标 ◇ modified，不再落到无色的 neutral。
        # 唯一差异：组的原始配额 > 0、只是依赖未满足（如非珠光模板里的珠光组），
        # 按"条件未满足"标 "!"。
        matched = [groups[key] for key in rule_keys
                   if key in groups and ref in set(groups[key].get("allowed") or [])]
        if not matched:
            return {
                "kind": "modified",
                "marker": "◇",
                "hint": self._legit_text(
                    "candidate_not_allowed",
                    "Not part of this natural template; still selectable as a modified part."),
            }
        names = " / ".join(
            self._generation_group_text(key) for key in rule_keys
            if key in groups and ref in set(groups[key].get("allowed") or []))
        if not any(int(spec.get("effective_max", spec.get("max", 0))) > 0
                   or ref in set(spec.get("selected") or []) for spec in matched):
            if any(int(spec.get("max", 0)) > 0 for spec in matched):
                template = self._legit_text(
                    "candidate_dependency",
                    "Belongs to {group}, but the current pairing or dependency is not satisfied.")
                return {"kind": "warning", "marker": "!", "hint": template.format(group=names)}
            return {
                "kind": "modified",
                "marker": "◇",
                "hint": self._legit_text(
                    "candidate_inactive",
                    "This template does not activate the slot; still selectable as a modified part."),
            }
        selected_counts = [list(spec.get("selected") or []).count(ref) for spec in matched]
        if any(count > 1 for count in selected_counts):
            return {
                "kind": "modified",
                "marker": "◇",
                "hint": self._legit_text("reason_duplicate_part", "The same part is selected more than once"),
            }
        if any(count and len(spec.get("selected") or []) > int(spec.get("effective_max", spec.get("max", 0)))
               for count, spec in zip(selected_counts, matched)):
            return {
                "kind": "modified",
                "marker": "◇",
                "hint": self._legit_text(
                    "candidate_overfull", "The selected count exceeds the natural limit for {group}.",
                ).format(group=names),
            }
        # "已选中"只有在该组当前选择本身可自然生成时才算合法：非珠光模板里选了
        # 珠光元素、普通稀有度配传奇枪管等，选择集不可达（selected_reachable=False），
        # 应与其它不合规候选一样标 "!"，而不是因为"已选"就显示 ✓。
        selected = any(
            ref in set(spec.get("selected") or []) and spec.get("selected_reachable", True)
            for spec in matched)
        remaining = any(ref in set(spec.get("remaining_eligible_refs") or []) for spec in matched)
        eligible = any(ref in set(spec.get("eligible_refs") or []) for spec in matched)
        if selected or remaining:
            template = self._legit_text("candidate_legal", "Natural candidate: {group}")
            return {"kind": "legal", "marker": "✓", "hint": template.format(group=names)}
        if eligible:
            template = self._legit_text(
                "candidate_slot_full",
                "Natural candidate for {group}; replace an existing part to stay legal.")
            return {"kind": "warning", "marker": "!", "hint": template.format(group=names)}
        template = self._legit_text(
            "candidate_dependency", "Belongs to {group}, but the current pairing or dependency is not satisfied.")
        return {"kind": "warning", "marker": "!", "hint": template.format(group=names)}

    def _set_group_guidance(self, key: str, rule_keys, groups, ready: bool) -> None:
        cfg = self._group_cfg(key)
        if not cfg:
            return
        base_title = self._group_base_title(cfg)
        if not ready:
            self._group_titles[key] = base_title
            self._clear_group_candidates(key)
            return
        specs = [(rule_key, groups.get(rule_key)) for rule_key in rule_keys]
        specs = [(rule_key, spec) for rule_key, spec in specs if isinstance(spec, dict)]
        visible = [
            (rule_key, spec)
            for rule_key, spec in specs
            if int(spec.get("effective_max", spec.get("max", 0))) > 0 or spec.get("selected")
        ]
        bits = []
        for rule_key, spec in visible:
            actual = len(spec.get("selected") or [])
            value = f"{actual}/{self._generation_range(spec)}"
            if len(visible) > 1:
                value = f"{self._generation_group_text(rule_key)} {value}"
            bits.append(value)
        self._group_titles[key] = (
            f"{base_title} · {' · '.join(bits)}" if bits else f"{base_title} · —")
        if cfg.get("mode") == "chip":
            option_groups = self._chip_replacement_groups(key, groups)
            for opt in self._chip_options_state.get(key, []):
                ref = self._generation_ref_for_option(key, opt.get("pid"))
                opt["candidate"] = self._candidate_state_for_option(
                    key, opt.get("pid"), ref, rule_keys, option_groups)
        else:
            for opt in self._picker_src.get(key, []):
                ref = self._generation_ref_for_option(key, opt.get("data"))
                opt["candidate"] = self._candidate_state_for_option(
                    key, opt.get("data"), ref, rule_keys, groups)

    def _chip_replacement_groups(self, key: str, groups):
        """单选下拉点选即"替换"当前选择：候选按去掉本组当前选择后的规则状态评估。

        否则选中一项后组配额已满，同组其它合法项全部显示"槽位已满"，
        而在单选下拉里换选并不会超出上限（与武器生成器的槽位语义一致）。
        """
        mfg_id = self._current_mfg_id()
        if self._chip_sel.get(key) is None or mfg_id is None:
            return groups
        saved = self._chip_sel[key]
        self._chip_sel[key] = None
        try:
            variant = item_display_resolver.validate_weapon_generation(
                self._compose_raw_output(mfg_id), allow_incomplete=True).get("groups") or {}
        except Exception:
            variant = {}
        finally:
            self._chip_sel[key] = saved
        return variant or groups

    def _clear_group_candidates(self, key: str) -> None:
        for opt in self._chip_options_state.get(key, []):
            opt.pop("candidate", None)
        for opt in self._picker_src.get(key, []):
            opt.pop("candidate", None)

    def _refresh_group_options(self) -> None:
        """每次重建后刷新 chip 选项与 picker 源（含动态描述与候选标记）。"""
        mfg_id = self._current_mfg_id()
        if mfg_id is None:
            return
        for cfg in self._group_cfgs:
            key = cfg["key"]
            if cfg.get("mode") == "chip":
                options = self._chip_options(key, mfg_id)
                if options is not None:
                    self._chip_options_state[key] = options
            else:
                self._picker_src[key] = self._group_items(key, mfg_id)

    # ------------------------------------------------------------------ #
    # 导入 / 重置
    # ------------------------------------------------------------------ #
    def _reset_import_state(self) -> None:
        self._imported_copy = False
        self._source_seed = self.DEFAULT_SEED
        self._source_header = None
        self._source_name = ""
        self._preserved_tokens = []
        self._preserved_children = self._initial_preserved_children()
        self._extra_reset_state()

    def _reset_import_source(self) -> None:
        self._loading_import = True
        try:
            self._reset_import_state()
            self._level = self._character_level
            self._on_mfg_change()
            self._clear_import_widgets()
            self._flag_index = self._default_flag_index()
        finally:
            self._loading_import = False
        self._rebuild()

    def _load_serial_copy(self, serial: str, *, name: str = "", state_flags=None) -> bool:
        parsed = split_decoded(decode_base85(serial))
        if parsed["mfg_id"] not in self.mfg_ids:
            raise ValueError(source_texts(self.current_lang)["wrong_type"])
        self._loading_import = True
        try:
            self._imported_copy = True
            self._source_seed = parsed["seed"]
            self._source_header = parsed
            self._source_name = name
            self._preserved_tokens = []
            self._preserved_children = self._initial_preserved_children()
            self._extra_reset_state()
            try:
                self._mfg_index = self._mfg_options.index(int(parsed["mfg_id"]))
            except ValueError:
                raise ValueError(source_texts(self.current_lang)["wrong_type"])
            self._on_mfg_change()
            self._level = str(parsed["level"])
            self._rarity_index = -1
            self._clear_import_widgets()
            self._apply_components(parsed["component"])
            self._set_flag_value(state_flags)
        finally:
            self._loading_import = False
        self._rebuild()
        if self._encode_error:
            raise ValueError(f"The imported {self.ITEM_LABEL} could not be rebuilt.")
        return True

    def _rarity_index_map(self) -> dict[int, int]:
        return {o["id"]: i for i, o in enumerate(self._rarity_options)}

    def _button_pid_map(self, key: str) -> dict[int, Any]:
        return {int(pid): pid for pid in self._chip_option_pids(key)}

    @staticmethod
    def _format_group(parent: int, children: list[int]) -> str:
        return (f"{{{parent}:{children[0]}}}" if len(children) == 1
                else f"{{{parent}:[{' '.join(map(str, children))}]}}")

    @staticmethod
    def _parse_component_tokens(component: str):
        return parse_components(component)

    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    # 幸运 Roll（移植自主线 _quick_roll / _roll_equipment 与约束菜单）
    # ------------------------------------------------------------------ #
    rollFinished = pyqtSignal(bool)  # True=有结果，False=无合法结果

    #: “类型”字段标签的 equipment_roll 键名（按族）；本地化仅 shield_type，
    #: 其余族走 _ROLL_TYPE_FALLBACK 四语言硬编码回退。
    _ROLL_TYPE_LOC_KEY = {"Grenade": "grenade", "Shield": "shield",
                          "Repkit": "repkit", "Heavy Weapon": "heavy_weapon"}
    _ROLL_TYPE_FALLBACK = {
        "Grenade": {"zh-CN": "手雷类型", "en-US": "Grenade Type",
                    "ru": "Тип гранаты", "ua": "Тип гранати"},
        "Shield": {"zh-CN": "护盾类型", "en-US": "Shield Type",
                   "ru": "Тип щита", "ua": "Тип щита"},
        "Repkit": {"zh-CN": "修复套件类型", "en-US": "Repkit Type",
                   "ru": "Тип ремкомплекта", "ua": "Тип ремкомплекту"},
        "Heavy Weapon": {"zh-CN": "重武器类型", "en-US": "Heavy Weapon Type",
                         "ru": "Тип тяжёлого оружия", "ua": "Тип важкої зброї"},
    }

    def _roll_type_field_label(self, generic: dict, labels: dict) -> str:
        family = self._ROLL_TYPE_LOC_KEY.get(self.BACKPACK_TYPE_EN, "")
        localized = str(generic.get(f"{family}_type") or "") if family else ""
        if localized:
            return localized
        fallback = self._ROLL_TYPE_FALLBACK.get(self.BACKPACK_TYPE_EN) or {}
        return str(fallback.get(self.current_lang) or fallback.get("en-US")
                   or labels.get("weapon_type", "Type"))

    def _roll_texts(self) -> dict[str, str]:
        weapon = self.app.localizer.section("weapon_gen_tab") or {}
        generic = self.app.localizer.section("equipment_roll") or {}
        labels = weapon.get("labels") or {}
        buttons = weapon.get("buttons") or {}
        sections = weapon.get("sections") or {}
        dialogs = weapon.get("dialogs") or {}
        texts = {
            "constraints_title": sections.get("roll_options", "Roll Options"),
            "results_title": sections.get("roll_results", "Roll Results"),
            "manufacturer": labels.get("manufacturer", "Manufacturer"),
            "weapon_type": self._roll_type_field_label(generic, labels),
            "rarity": labels.get("rarity", "Rarity"),
            "named_item": generic.get("named_item", labels.get("named_weapon", "Named Item")),
            "count": labels.get("quantity", "Quantity"),
            "random": labels.get("random", "Random"),
            "matches": labels.get("matches", "Matches: {count}"),
            "no_matches": labels.get("no_matches", "No matches"),
            "generated": generic.get("generated", "Generated {count} legal items"),
            "no_results": generic.get("no_results", "No generated items yet"),
            "select_result": generic.get("select_result", "Select an item from the list"),
            "level_value": labels.get("level_value", "Lv{level}"),
            "legal": labels.get("legal", "Legal"),
            "scope_template": labels.get(
                "scope_template",
                "Manufacturer: {manufacturer} · Type: {weapon_type} · Rarity: {rarity}",
            ),
            "lucky": buttons.get("lucky", "I'm Feeling Lucky"),
            "roll": buttons.get("roll", "Roll"),
            "add_all": buttons.get("add_all", "Add All"),
            "add_one": generic.get("add_one", buttons.get("add_one", "Add This")),
            "copy_base85": buttons.get("copy_base85", "Copy Base85"),
            "copied": dialogs.get("base85_copied", "Base85 copied"),
            "roll_failed": dialogs.get("roll_failed", "Roll failed: {error}"),
            "no_legal_result": dialogs.get("no_legal_result", "No legal build matches the filters."),
            "roll_add_done": dialogs.get("roll_add_done", "Added {success}; failed {fail}"),
        }
        texts.update(self._stat_labels())
        return texts

    def _localized_item_type(self) -> str:
        key = {
            "Grenade": "grenade", "Shield": "shield", "Repkit": "repkit",
            "Heavy Weapon": "heavy_weapon",
        }.get(self.BACKPACK_TYPE_EN, "")
        return str((self.app.localizer.section("tabs") or {}).get(key) or self.ITEM_LABEL)

    def _roll_type_value(self, root_id) -> str:
        return str((getattr(self, "MFG_TYPE_BASE", {}) or {}).get(int(root_id)) or self.BACKPACK_TYPE_EN)

    def _roll_type_label(self, value) -> str:
        if self.BACKPACK_TYPE_EN == "Shield" and hasattr(self, "_shield_type_text"):
            return self._shield_type_text(value)
        return self._localized_item_type()

    def _gold_composition_refs(self) -> set:
        try:
            rows = self.df_mfg[self.df_mfg["Part_type"] == "Rarity"]
        except (KeyError, TypeError):
            return set()
        refs = set()
        for _, row in rows.iterrows():
            zh = str(row.get("Description_ZH") or "").strip()
            en = str(row.get("Description_EN") or "").strip().casefold()
            if zh == "金皮肤" or en == "gold skin":
                refs.add(f"{int(row['Manufacturer ID'])}:{int(row['Part_ID'])}")
        return refs

    @staticmethod
    def _strip_skin_suffix(value) -> str:
        value = str(value or "").strip()
        value = re.sub(r"\s+skin$", "", value, flags=re.IGNORECASE)
        return value[:-2].strip() if value.endswith("皮肤") else value

    def _roll_catalog_name(self, root_id, composition_ref, composition) -> str:
        names = composition.get("name") or {}
        preferred = names.get("zh") if self.current_lang == "zh-CN" else names.get("en")
        name = str(preferred or names.get("en") or names.get("zh") or "").strip()
        if name.casefold() not in {"nan", "none"} and name:
            return name
        part_id = int(str(composition_ref).partition(":")[2])
        rows = self.df_mfg[
            (self.df_mfg["Manufacturer ID"] == int(root_id))
            & (self.df_mfg["Part_ID"] == part_id)
            & (self.df_mfg["Part_type"] == "Rarity")
        ]
        if rows.empty:
            return ""
        row = rows.iloc[0]
        value = row.get("Description")
        if pd.isna(value) or str(value).strip().casefold() in {"", "nan", "none"}:
            value = row.get("Description_EN")
        if pd.isna(value) or str(value).strip().casefold() in {"", "nan", "none"}:
            value = self._ncs_rarity_child_name(root_id, part_id)
        return self._strip_skin_suffix(value)

    def _equipment_roll_catalog(self) -> list[dict[str, Any]]:
        rules = item_display_resolver._item_index().get("weapon_generation_rules") or {}
        weapons = rules.get("weapons") or {}
        gold = self._gold_composition_refs()
        taxonomy = ((self.app.localizer.section("weapon_editor_tab") or {}).get("taxonomy") or {})
        catalog = []
        for root_id in self.mfg_ids:
            weapon = weapons.get(str(root_id)) or {}
            if not weapon:
                continue
            manufacturer_en = str((lookup.REVERSE_ID_MAP.get(int(root_id)) or ("Unknown",))[0])
            manufacturer_label = self._get_mfg_name(root_id)
            type_value = self._roll_type_value(root_id)
            type_label = self._roll_type_label(type_value)
            for composition_ref, composition in (weapon.get("compositions") or {}).items():
                if composition.get("availability") != "coregame" or composition_ref in gold:
                    continue
                tags = {str(tag).casefold() for tag in composition.get("base_tags") or []}
                if "npc_weapon" in tags:
                    continue
                rarity = str(composition.get("rarity") or "")
                name = self._roll_catalog_name(root_id, composition_ref, composition)
                catalog.append({
                    "root_id": str(root_id),
                    "composition_ref": str(composition_ref),
                    "manufacturer": manufacturer_en,
                    "manufacturer_label": manufacturer_label,
                    "weapon_type": type_value,
                    "weapon_type_label": type_label,
                    "rarity": rarity,
                    "rarity_label": str(taxonomy.get(rarity.casefold()) or self._(rarity)),
                    "name": name,
                    "is_named": bool(name and rarity in {"Legendary", "Pearl"}),
                })
        return catalog

    @staticmethod
    def _filter_roll_catalog(catalog, constraints):
        return [
            row for row in catalog
            if (constraints.get("manufacturer") is None or row["manufacturer"] == constraints["manufacturer"])
            and (constraints.get("weapon_type") is None or row["weapon_type"] == constraints["weapon_type"])
            and (constraints.get("rarity") is None or row["rarity"] == constraints["rarity"])
            and (constraints.get("composition_ref") is None or row["composition_ref"] == constraints["composition_ref"])
        ]

    @staticmethod
    def _roll_part_tags(ref):
        index = item_display_resolver._item_index()
        rules = index.get("weapon_generation_rules") or {}
        return (
            (rules.get("part_selection_tags") or {}).get(str(ref))
            or (index.get("part_refs") or {}).get(str(ref), {}).get("selection_tags")
            or {}
        )

    def _roll_element_text(self, decoded, root_id):
        from core import serial_inspect

        values = []
        for row in serial_inspect.part_rows(decoded, int(root_id), self.BACKPACK_TYPE_EN, self.current_lang):
            if row.get("category") not in {"element", "body_ele", "secondary_ele", "pearl_elem"}:
                continue
            if str(row.get("part") or "").casefold().endswith("part_normal"):
                continue
            name = str(row.get("name") or "").strip()
            if name and name not in values:
                values.append(name)
        return " / ".join(values)

    def _roll_serial_token(self, ref, root_id):
        owner, _sep, part_id = str(ref).partition(":")
        return f"{{{part_id}}}" if owner == str(root_id) else f"{{{owner}:{part_id}}}"

    def _roll_one_equipment(self, candidate, rng):
        from core.weapon_generation_logic import sample_composition_parts

        index = item_display_resolver._item_index()
        rules = index.get("weapon_generation_rules") or {}
        root_id = candidate["root_id"]
        weapon = (rules.get("weapons") or {})[root_id]
        composition = weapon["compositions"][candidate["composition_ref"]]
        selected = sample_composition_parts(
            composition=composition,
            part_types=weapon.get("part_types") or (),
            tags_for_ref=self._roll_part_tags,
            excluded_refs=set((rules.get("part_availability") or {}).keys()),
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
                str(item.get("code")) for item in validation.get("violations") or ()
            ) or str(validation.get("status")))
        display = item_display_resolver.resolve_item_display(
            int(root_id), candidate["manufacturer"], self.BACKPACK_TYPE_EN,
            decoded, self.current_lang,
        )
        stats = item_display_resolver.resolve_equipment_stats(decoded, self.BACKPACK_TYPE_EN)
        formatted = {
            key: item_display_resolver.format_equipment_stat(key, stats.get(key), self.current_lang)
            for key in self.PREVIEW_FIELDS.get(self.BACKPACK_TYPE_EN, ())
            if stats.get(key) not in (None, "")
        }
        name = str(display.get("display_name") or candidate.get("name") or "—")
        rarity = str(display.get("rarity") or candidate["rarity_label"])
        element = self._roll_element_text(decoded, root_id)
        rarity_color = item_card_data.WEAPON_CARD_RARITY_COLORS.get(
            str(candidate.get("rarity") or "").casefold()) or item_card_data.WEAPON_CARD_RARITY_COLORS.get(
            rarity.casefold()) or "#78909C"
        return {
            "serial": serial,
            "decoded": decoded,
            "name": name,
            "manufacturer": candidate["manufacturer_label"],
            "weapon_type": candidate["weapon_type_label"],
            "rarity": rarity,
            "rarity_color": rarity_color,
            "element": element,
            "level": str(level),
            "stats": [{"key": k, "label": self._stat_labels().get(k, k), "value": str(v)}
                      for k, v in formatted.items()],
            "effect_entries": self._roll_effect_entries(decoded, stats),
            "tooltip": "\n".join([
                name,
                f"{candidate['manufacturer_label']} · {candidate['weapon_type_label']} · {rarity}",
                *(f"{self._stat_labels().get(k, k)}: {v}" for k, v in formatted.items()),
                f"Base85: {serial}",
            ]),
        }

    def _roll_effect_entries(self, decoded: str, stats) -> list[dict[str, Any]]:
        """Roll 结果详情的图标化词条列表：与物品页装备卡同一数据源/图标资源。"""
        if not decoded:
            return []
        try:
            details = item_display_resolver.resolve_equipment_card_details(
                decoded, self.BACKPACK_TYPE_EN, self.current_lang)
        except Exception:
            return []
        entries = (details or {}).get("entries") or []
        entries = item_display_resolver.limit_item_card_entries(entries)
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
                "icon": item_card_data._effect_icon_uri(str(entry.get("icon_asset") or "")),
                "legendary": str(entry.get("display_kind") or "") == "legendary",
            })
        return out

    def _roll_scope_text(self, constraints, catalog) -> str:
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
            rarity=label("rarity", "rarity_label"),
        )

    # -- QML 接口 ---------------------------------------------------------- #
    @pyqtProperty("QVariantMap", notify=dataChanged)
    def rollTexts(self) -> dict[str, str]:
        return self._roll_texts()

    @pyqtSlot(result="QVariantMap")
    def rollConstraintOptions(self) -> dict[str, Any]:
        """约束选项（制造商/类型/稀有度/指定装备），首项 random。

        对齐主线 WeaponRollOptionsWidget：类型行仅当目录存在多个类型时展示
        （``show_type``）；指定装备（named）选项附带其厂商/类型/稀有度取值，
        便于 QML 侧选中后联动锁定其余约束。
        """
        texts = self._roll_texts()
        catalog = self._equipment_roll_catalog()
        random_opt = {"label": texts["random"], "value": None}
        mfgs, types, rarities, named = {}, {}, {}, {}
        for row in catalog:
            mfgs[row["manufacturer"]] = row["manufacturer_label"]
            types[row["weapon_type"]] = row["weapon_type_label"]
            if row["rarity"]:
                rarities[row["rarity"]] = row["rarity_label"]
            if row.get("is_named"):
                detail = " · ".join(filter(None, (
                    row["manufacturer_label"], row["weapon_type_label"], row["rarity_label"])))
                named[row["composition_ref"]] = (f"{row['name']} — {detail}", row)
        return {
            "manufacturers": [random_opt, *[{"label": v, "value": k} for k, v in sorted(mfgs.items())]],
            "weapon_types": [random_opt, *[{"label": v, "value": k} for k, v in sorted(types.items())]],
            # 稀有度按 普通→珠光 固定顺序（对齐主线 RARITY_ORDER，不再按字母随机分布）
            "rarities": [random_opt, *[{"label": v, "value": k} for k, v in sorted(
                rarities.items(), key=lambda item: RARITY_ORDER.get(item[0].casefold(), 99))]],
            "named_items": [random_opt, *[
                {"label": label, "value": ref,
                 "manufacturer": row["manufacturer"], "weapon_type": row["weapon_type"],
                 "rarity": row["rarity"]}
                for ref, (label, row) in sorted(named.items(), key=lambda item: item[1][0].casefold())
            ]],
            "show_type": len(types) > 1,
        }

    @pyqtProperty(list, notify=rollFinished)
    def rollResults(self) -> list[dict[str, Any]]:
        return getattr(self, "_roll_results", [])

    @pyqtProperty(str, notify=rollFinished)
    def rollSummaryText(self) -> str:
        return getattr(self, "_roll_summary", "")

    @pyqtProperty("QVariantMap", notify=dataChanged)
    def rollConstraints(self) -> dict[str, Any]:
        """上次 Roll 使用的约束（对齐主线 _roll_constraints，VM 侧持久）。"""
        return dict(self._roll_constraints)

    @pyqtProperty(int, notify=dataChanged)
    def rollCount(self) -> int:
        """上次 Roll 数量（对齐主线 _roll_count）。"""
        return self._roll_count

    @pyqtSlot("QVariantMap", result=int)
    def rollMatchCount(self, constraints) -> int:
        """当前约束下的目录匹配数（约束面板的 Matches 显示）。"""
        constraints = {k: v for k, v in dict(constraints or {}).items() if v is not None and v != ""}
        return len(self._filter_roll_catalog(self._equipment_roll_catalog(), constraints))

    @pyqtSlot(result=bool)
    def quickRoll(self) -> bool:
        """主按钮快速 Roll：直接使用上次保存的约束与数量（对齐主线 _quick_roll）。"""
        return self.roll(self._roll_constraints, self._roll_count)

    @pyqtSlot("QVariantMap", int, result=bool)
    def roll(self, constraints, count) -> bool:
        """执行幸运 Roll（同步，与主线一致）。结果存 rollResults；约束/数量持久。"""
        constraints = {k: v for k, v in dict(constraints or {}).items() if v is not None and v != ""}
        count = max(1, min(50, int(count)))
        self._roll_constraints = constraints
        self._roll_count = count
        catalog = self._filter_roll_catalog(self._equipment_roll_catalog(), constraints)
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
                        results.append(self._roll_one_equipment(candidate, rng))
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
        results = getattr(self, "_roll_results", [])
        if 0 <= index < len(results):
            QApplication.clipboard().setText(results[index]["serial"])
            self.app.toast(self._roll_texts()["copied"], "success")

    @pyqtSlot("QVariantList")
    def addRollToBackpack(self, indices) -> None:
        """选中结果批量加入背包：离线写存档，live 模式分批刷进游戏。"""
        results = getattr(self, "_roll_results", [])
        serials = [results[i]["serial"] for i in indices
                   if isinstance(i, int) and 0 <= i < len(results)]
        self.app.add_serials_to_backpack(serials, self._flag_value(), self._roll_texts()["roll_add_done"])
