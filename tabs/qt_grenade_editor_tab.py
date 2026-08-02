import pandas as pd
from functools import lru_cache
import re

from PyQt6.QtCore import Qt

from core import resource_loader
from tabs.qt_equipment_base_tab import BaseEquipmentEditorTab


@lru_cache(maxsize=None)
def load_grenade_data(lang='zh-CN'):
    try:
        df_main = resource_loader.load_localized_csv_resource('grenade/grenade_main_perk.csv', lang)
        df_mfg = resource_loader.load_localized_csv_resource('grenade/manufacturer_rarity_perk.csv', lang)
        localization = {}
        if lang == 'zh-CN':
            localization = resource_loader.load_json_resource('grenade/Grenade_localization_zh-CN.json') or {}
        return df_main, df_mfg, localization
    except Exception as e:
        print(f"Error loading grenade data ({lang}): {e}")
        return None, None, None


class QtGrenadeEditorTab(BaseEquipmentEditorTab):
    EQUIP_TYPE = "grenade"
    UI_LOC_KEY = "grenade_tab"
    DEFAULT_SEED = 305
    MFG_IDS = [263, 267, 270, 272, 278, 291, 298, 311]
    BACKPACK_TYPE_EN = "Grenade"
    ITEM_LABEL = "Grenade"

    # secondary token parent id for element/firmware/universal
    SECONDARY_PARENT = 245

    def load_data(self, lang):
        return load_grenade_data(lang)

    def _build_perk_groups(self, perks_layout):
        super()._build_perk_groups(perks_layout)
        perks_layout.setColumnStretch(0, 1)
        perks_layout.setColumnStretch(1, 1)

    def _declare_perk_groups(self):
        return [
            {"key": "element", "mode": "chip", "title_key": "element", "columns": 3, "grid": (0, 0, 1, 1)},
            {"key": "firmware", "mode": "chip", "title_key": "firmware", "columns": 3, "grid": (0, 1, 1, 1)},
            {"key": "mfg_perk", "mode": "picker", "title_key": "mfg_perks", "stackable": False, "grid": (1, 0, 1, 2)},
            {"key": "legendary", "mode": "picker", "title_key": "legendary", "stackable": False, "grid": (2, 0, 1, 2)},
            {"key": "universal", "mode": "picker", "title_key": "universal", "stackable": True, "grid": (3, 0, 1, 2)},
        ]

    def _initial_preserved_children(self):
        return {self.SECONDARY_PARENT: []}

    # ------------------------------------------------------------------ #
    # Data -> group contents
    # ------------------------------------------------------------------ #
    def _populate_initial_extra(self):
        # element / firmware / universal are mfg-independent (from df_main)
        for key, ptype in (("element", "Element"), ("firmware", "Firmware")):
            cfg = self._group_cfgs[key]
            df = self.df_main[self.df_main['Part_type'] == ptype]
            self._populate_chip_group(cfg, df, self._fmt_row)
        self._group_pickles["universal"].set_source(self._universal_items())

    def _universal_items(self):
        items = []
        for _, r in self.df_main[self.df_main['Part_type'] == 'Perk'].iterrows():
            text, part_id = self._fmt_row(r)
            items.append({
                "key": f"u{part_id}", "label": text, "category": None,
                "data": int(part_id),
            })
        return items

    def _group_rows(self, key, mfg_id):
        # element/firmware populated once in _populate_initial_extra; skip refresh
        return None

    def _group_items(self, key, mfg_id):
        if key == "mfg_perk":
            items = []
            df = self.df_mfg[(self.df_mfg['Manufacturer ID'] == mfg_id) & (self.df_mfg['Part_type'] == 'Perk')]
            for _, r in df.iterrows():
                text, part_id = self._fmt_row(r)
                items.append({"key": f"m{part_id}", "label": text, "category": None, "data": int(part_id)})
            return items
        if key == "legendary":
            return self._legendary_items(mfg_id)
        if key == "universal":
            return self._universal_items()
        return []

    def _legendary_items(self, current_mfg):
        items = []
        df_leg = self.df_mfg[self.df_mfg['Part_type'] == 'Legendary Perk'].copy()
        df_leg['sort_key'] = df_leg['Manufacturer ID'].apply(lambda x: 0 if x == current_mfg else 1)
        df_leg = df_leg.sort_values(by=['sort_key', 'Manufacturer ID', 'Part_ID'])
        for _, r in df_leg.iterrows():
            mfg_name = self._get_mfg_name(r['Manufacturer ID'])
            desc = r['Description'] if pd.notna(r['Description']) else ''
            label = f"{mfg_name} - {self._(r['Stat'])} - {desc}".strip(" -")
            pid, mid = int(r['Part_ID']), int(r['Manufacturer ID'])
            items.append({
                "key": f"l{mid}:{pid}", "label": label,
                "category": "current" if mid == current_mfg else "other",
                "data": (pid, mid),
            })
        return items

    # ------------------------------------------------------------------ #
    # Output assembly
    # ------------------------------------------------------------------ #
    def _build_skill_parts(self, mfg_id):
        skill_parts, secondary = [], {}
        # legendary perks (mfg may differ -> {mfg:[ids]})
        other_mfg = {}
        for e in self._picker_entries("legendary"):
            pid, item_mfg = e["data"]
            for _ in range(self._count_of(e)):
                if item_mfg == mfg_id:
                    skill_parts.append(f"{{{pid}}}")
                else:
                    other_mfg.setdefault(item_mfg, []).append(pid)
        for item_mfg, ids in other_mfg.items():
            skill_parts.append(f"{{{item_mfg}:{ids[0]}}}" if len(ids) == 1
                               else f"{{{item_mfg}:[{' '.join(map(str, sorted(ids)))}]}}")
        # element + firmware -> secondary group 245
        for pid in self._checked_part_ids("element", "firmware"):
            secondary.setdefault(self.SECONDARY_PARENT, []).append(pid)
        # mfg perks -> plain {id}
        for e in self._picker_entries("mfg_perk"):
            for _ in range(self._count_of(e)):
                skill_parts.append(f"{{{e['data']}}}")
        # universal -> secondary group 245 (stacked)
        for e in self._picker_entries("universal"):
            for _ in range(self._count_of(e)):
                secondary.setdefault(self.SECONDARY_PARENT, []).append(e["data"])
        return skill_parts, secondary

    # ------------------------------------------------------------------ #
    # Import
    # ------------------------------------------------------------------ #
    def _apply_components(self, component):
        from tabs.qt_serial_import import parse_components
        mfg_id = self._current_mfg_id()
        rarity_ids = self._rarity_index_map()
        mfg_perks = self._picker_item_map("mfg_perk")
        universal = self._picker_item_map("universal")
        legendary = self._picker_item_map("legendary")

        for token in parse_components(component):
            ttype = token['type']
            if ttype == 'quoted':
                self._preserved_tokens.append(f'"{token["value"]}"')
                continue
            if ttype == 'simple':
                part_id = token['id']
                if part_id in rarity_ids:
                    self.rarity_combo.setCurrentIndex(rarity_ids[part_id])
                elif part_id in mfg_perks:
                    self._picker_add("mfg_perk", mfg_perks[part_id])
                elif (part_id, mfg_id) in legendary:
                    self._picker_add("legendary", legendary[(part_id, mfg_id)])
                else:
                    self._preserved_tokens.append(f"{{{part_id}}}")
                continue
            parent_id = token['id']
            children = token['children'] if ttype == 'group' else [token['value']]
            unknown = []
            for part_id in children:
                if parent_id == self.SECONDARY_PARENT:
                    if self._select_group_pid("element", part_id):
                        pass
                    elif self._select_group_pid("firmware", part_id):
                        pass
                    elif part_id in universal:
                        self._picker_add("universal", universal[part_id])
                    else:
                        self._preserved_children[self.SECONDARY_PARENT].append(part_id)
                elif (part_id, parent_id) in legendary:
                    self._picker_add("legendary", legendary[(part_id, parent_id)])
                else:
                    unknown.append(part_id)
            if unknown:
                values = ' '.join(map(str, unknown))
                self._preserved_tokens.append(
                    f"{{{parent_id}:{unknown[0]}}}" if len(unknown) == 1 else f"{{{parent_id}:[{values}]}}"
                )
