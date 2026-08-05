import pandas as pd
from functools import lru_cache

from PyQt6.QtCore import Qt

from core import resource_loader
from tabs.qt_equipment_base_tab import BaseEquipmentEditorTab


@lru_cache(maxsize=None)
def load_shield_data(lang='zh-CN'):
    try:
        df_main = resource_loader.load_localized_csv_resource('shield/shield_main_perk.csv', lang)
        df_mfg = resource_loader.load_localized_csv_resource('shield/manufacturer_perk.csv', lang)
        localization = {}
        if lang == 'zh-CN':
            localization = resource_loader.load_json_resource('shield/Shield_localization_zh-CN.json') or {}
        return df_main, df_mfg, localization
    except Exception as e:
        print(f"Error loading shield data: {e}")
        return None, None, None


class QtShieldEditorTab(BaseEquipmentEditorTab):
    EQUIP_TYPE = "shield"
    UI_LOC_KEY = "shield_tab"
    DEFAULT_SEED = 306
    MFG_IDS = [279, 283, 287, 293, 300, 306, 312, 321]
    BACKPACK_TYPE_EN = "Shield"
    ITEM_LABEL = "Shield"

    MFG_TYPE_BASE = {279: "Energy", 283: "Armor", 287: "Armor", 293: "Energy",
                     300: "Energy", 306: "Armor", 312: "Energy", 321: "Armor"}
    # perk group -> (parent token id, shield type it belongs to or None)
    GROUP_PARENT = {"universal": 246, "energy": 248, "armor": 237}
    ELEMENT_PARENT = 246

    def load_data(self, lang):
        return load_shield_data(lang)

    def __init__(self, main_app=None, parent=None):
        self._source_model_present = False
        super().__init__(main_app, parent)

    def _build_perk_groups(self, perks_layout):
        super()._build_perk_groups(perks_layout)
        perks_layout.setColumnStretch(0, 1)
        perks_layout.setColumnStretch(1, 1)

    def _declare_perk_groups(self):
        return [
            {"key": "element", "mode": "chip", "title_key": "element", "columns": 3, "grid": (0, 0, 1, 1)},
            {"key": "firmware", "mode": "chip", "title_key": "firmware", "columns": 3, "grid": (0, 1, 1, 1)},
            {"key": "legendary", "mode": "picker", "title_key": "legendary", "stackable": False, "grid": (1, 0, 1, 2)},
            {"key": "energy", "mode": "picker", "title_key": "energy", "stackable": True, "grid": (2, 0, 1, 2)},
            {"key": "armor", "mode": "picker", "title_key": "armor", "stackable": True, "grid": (3, 0, 1, 2)},
            {"key": "universal", "mode": "picker", "title_key": "universal", "stackable": True, "grid": (4, 0, 1, 2)},
        ]

    def _initial_preserved_children(self):
        return {246: [], 248: [], 237: []}

    def _extra_reset_state(self):
        self._source_model_present = False

    # ------------------------------------------------------------------ #
    # Population
    # ------------------------------------------------------------------ #
    def _populate_initial_extra(self):
        df = self.df_main[self.df_main['Shield_perk_main_ID'] == 246]
        self._populate_chip_group(self._group_cfgs["element"], df[df['Part_type'] == 'Elemental Resistance'], self._fmt_row)
        self._populate_chip_group(self._group_cfgs["firmware"], df[df['Part_type'] == 'Firmware'], self._fmt_row)
        self._group_pickles["universal"].set_source(self._perk_items(246))

    def _perk_items(self, main_id):
        items = []
        df = self.df_main[(self.df_main['Shield_perk_main_ID'] == main_id) & (self.df_main['Part_type'] == 'Perk')]
        for _, r in df.iterrows():
            text, part_id = self._fmt_row(r)
            items.append({"key": f"p{main_id}:{part_id}", "label": text, "category": None, "data": int(part_id)})
        return items

    def _legendary_items(self, current_mfg):
        items = []
        df_leg = self.df_mfg[self.df_mfg['Part_type'] == 'Legendary Perk'].copy()
        df_leg['sort_key'] = df_leg['Manufacturer ID'].apply(lambda x: 0 if x == current_mfg else 1)
        df_leg = df_leg.sort_values(by=['sort_key', 'Manufacturer ID', 'Part_ID'])
        for _, r in df_leg.iterrows():
            mfg_name = self._get_mfg_name(r['Manufacturer ID'])
            text, _ = self._fmt_row(r)
            label = f"{mfg_name} - {text}".strip(" -")
            pid, mid = int(r['Part_ID']), int(r['Manufacturer ID'])
            items.append({"key": f"l{mid}:{pid}", "label": label,
                          "category": "current" if mid == current_mfg else "other", "data": (pid, mid)})
        return items

    def _group_items(self, key, mfg_id):
        if key == "legendary":
            return self._legendary_items(mfg_id)
        if key == "energy":
            return self._perk_items(248)
        if key == "armor":
            return self._perk_items(237)
        if key == "universal":
            return self._perk_items(246)
        return []

    def _group_rows(self, key, mfg_id):
        return None  # element/firmware populated once in _populate_initial_extra

    def _on_mfg_changed_extra(self, mfg_id):
        # enable/disable energy vs armor pickers based on shield type
        mfg_type = self.MFG_TYPE_BASE.get(mfg_id)
        energy_on = mfg_type == "Energy"
        armor_on = mfg_type == "Armor"
        for key, on in (("energy", energy_on), ("armor", armor_on)):
            picker = self._group_pickles.get(key)
            if picker is not None:
                picker.setEnabled(on)
                picker.parentWidget().setEnabled(on)

    # ------------------------------------------------------------------ #
    # Output
    # ------------------------------------------------------------------ #
    def _build_skill_parts(self, mfg_id):
        skill_parts, secondary = [], {}
        leg_entries = self._picker_entries("legendary")
        # Model part
        if self._imported_copy and self._source_model_present:
            skill_parts.append(f"{{{self.mfg_model_map[mfg_id]}}}")
        elif not leg_entries and mfg_id in self.mfg_model_map:
            skill_parts.append(f"{{{self.mfg_model_map[mfg_id]}}}")
        # legendary (cross-mfg -> {mfg:[ids]})
        other_mfg = {}
        for e in leg_entries:
            pid, item_mfg = e["data"]
            for _ in range(self._count_of(e)):
                if item_mfg == mfg_id:
                    skill_parts.append(f"{{{pid}}}")
                else:
                    other_mfg.setdefault(item_mfg, []).append(pid)
        for item_mfg, ids in other_mfg.items():
            skill_parts.append(f"{{{item_mfg}:{ids[0]}}}" if len(ids) == 1
                               else f"{{{item_mfg}:[{' '.join(map(str, sorted(ids)))}]}}")
        # element + firmware -> 246
        for pid in self._checked_part_ids("element", "firmware"):
            secondary.setdefault(self.ELEMENT_PARENT, []).append(pid)
        # perk lists -> their parent ids (respect enable state)
        mfg_type = self.MFG_TYPE_BASE.get(mfg_id)
        for key, parent in self.GROUP_PARENT.items():
            picker = self._group_pickles.get(key)
            if picker is None or not picker.isEnabled():
                continue
            for e in self._picker_entries(key):
                for _ in range(self._count_of(e)):
                    secondary.setdefault(parent, []).append(e["data"])
        return skill_parts, secondary

    @property
    def mfg_model_map(self):
        if getattr(self, "_mfg_model_map", None) is None:
            self._mfg_model_map = {
                row['Manufacturer ID']: row['Part_ID']
                for _, row in self.df_mfg[self.df_mfg['Part_type'] == 'Model'].iterrows()
            }
        return self._mfg_model_map

    # ------------------------------------------------------------------ #
    # Import
    # ------------------------------------------------------------------ #
    def _apply_components(self, component):
        from tabs.qt_serial_import import parse_components
        mfg_id = self._current_mfg_id()
        rarity_ids = self._rarity_index_map()
        universal = self._picker_item_map("universal")
        energy = self._picker_item_map("energy")
        armor = self._picker_item_map("armor")
        legendary = self._picker_item_map("legendary")
        shield_type = self.MFG_TYPE_BASE.get(mfg_id)
        model_id = self.mfg_model_map.get(mfg_id)

        for token in parse_components(component):
            ttype = token['type']
            if ttype == 'quoted':
                self._preserved_tokens.append(f'"{token["value"]}"')
                continue
            if ttype == 'simple':
                part_id = token['id']
                if part_id in rarity_ids:
                    self.rarity_combo.setCurrentIndex(rarity_ids[part_id])
                elif model_id is not None and part_id == int(model_id):
                    self._source_model_present = True
                elif (part_id, mfg_id) in legendary:
                    self._picker_add("legendary", legendary[(part_id, mfg_id)])
                else:
                    self._preserved_tokens.append(f"{{{part_id}}}")
                continue
            parent_id = token['id']
            children = token['children'] if ttype == 'group' else [token['value']]
            unknown = []
            for part_id in children:
                if parent_id == 246:
                    if self._select_group_pid("element", part_id):
                        pass
                    elif self._select_group_pid("firmware", part_id):
                        pass
                    elif part_id in universal:
                        self._picker_add("universal", universal[part_id])
                    else:
                        self._preserved_children[246].append(part_id)
                elif parent_id == 248:
                    if shield_type == 'Energy' and part_id in energy:
                        self._picker_add("energy", energy[part_id])
                    else:
                        self._preserved_children[248].append(part_id)
                elif parent_id == 237:
                    if shield_type == 'Armor' and part_id in armor:
                        self._picker_add("armor", armor[part_id])
                    else:
                        self._preserved_children[237].append(part_id)
                elif (part_id, parent_id) in legendary:
                    self._picker_add("legendary", legendary[(part_id, parent_id)])
                else:
                    unknown.append(part_id)
            if unknown:
                values = ' '.join(map(str, unknown))
                self._preserved_tokens.append(
                    f"{{{parent_id}:{unknown[0]}}}" if len(unknown) == 1 else f"{{{parent_id}:[{values}]}}"
                )
