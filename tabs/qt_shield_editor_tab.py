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

    def _manufacturer_option_label(self, mfg_id):
        type_key = "shield_type_energy" if self.MFG_TYPE_BASE.get(mfg_id) == "Energy" else "shield_type_armor"
        shield_type = str((self.ui_loc.get("misc") or {}).get(type_key) or self.MFG_TYPE_BASE.get(mfg_id) or "")
        return f"{self._get_mfg_name(mfg_id)} ({shield_type}) - {mfg_id}"

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
            {"key": "primary", "mode": "picker", "title_key": "primary", "stackable": True, "grid": (2, 0, 1, 2)},
            {"key": "secondary", "mode": "picker", "title_key": "secondary", "stackable": True, "grid": (3, 0, 1, 2)},
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
        self._populate_chip_group(self._group_cfgs["firmware"], self._firmware_group_df('Shield_perk_main_ID', 246), self._fmt_row)
        for key in ("primary", "secondary"):
            picker = self._group_pickles.get(key)
            if picker is not None:
                picker.set_categories(self._augment_source_categories(), columns=4)

    # Each augment picker mixes both slots, so its budget is the sum of the two sides as
    # declared for the current composition. The generation rules say max=1 per side, which
    # matches what 80 dumped shields show, but the rules are the source: a retuned or new
    # composition changes the badge without a code edit.
    RULE_GROUPS_BY_PICKER = {
        "element": ("element",),
        "firmware": ("firmware",),
        "primary": ("primary_augment",),
        "secondary": ("secondary_augment",),
        "legendary": ("body", "unique"),
    }

    def _generation_ref_for_option(self, key, data):
        if data is None:
            return ""
        if key in {"element", "firmware"}:
            return f"{self.ELEMENT_PARENT}:{int(data)}"
        if key in {"primary", "secondary"}:
            parent, part_id = data
            return f"{int(parent)}:{int(part_id)}"
        if key == "legendary":
            part_id, owner = data
            return f"{int(owner)}:{int(part_id)}"
        return ""

    @staticmethod
    def _legendary_facet(data):
        from core import item_display_resolver as resolver

        part_id, owner = data
        ref = (resolver._item_index().get("part_refs") or {}).get(f"{int(owner)}:{int(part_id)}") or {}
        category = str(ref.get("category") or "")
        return category if category in {"body", "unique"} else "other"

    def _candidate_state_for_option(self, key, data, ref, rule_keys, groups):
        if key == "legendary":
            facet = self._legendary_facet(data)
            if facet in {"body", "unique"}:
                return self._candidate_state(ref, (facet,), groups)
        return super()._candidate_state_for_option(key, data, ref, rule_keys, groups)

    # Augments occupy two independent slots, confirmed twice over: the rules declare
    # primary_augment and secondary_augment separately with max=1 each, and across 80
    # dumped shields the observed (primary, secondary) counts were (0,0) 23x, (1,0) 25x,
    # (0,1) 12x, (1,1) 20x -- never 2 on a side -- with the two sides never holding the
    # same augment. The pickers are flat and stackable, so stacking two primaries makes a
    # shield the game cannot roll and whose mechanism yields no numbers; faceting by slot
    # makes the split visible and the count badge reports the declared budget.
    _AUGMENT_FACETS = ("primary_augment", "secondary_augment")

    def _augment_facet(self, parent, part_id):
        from core import item_display_resolver as resolver

        ref = (resolver._item_index().get("part_refs") or {}).get(f"{parent}:{part_id}") or {}
        category = str(ref.get("category") or "")
        return category if category in self._AUGMENT_FACETS else "other"

    def _augment_source_categories(self):
        groups = (self.ui_loc or {}).get('augment_sources') or {}
        return [
            ("all", groups.get("all", "All")),
            ("universal", groups.get("universal", "Universal")),
            ("energy", groups.get("energy", "Energy")),
            ("armor", groups.get("armor", "Armor")),
        ]

    def _perk_items(self, main_id):
        items = []
        df = self.df_main[(self.df_main['Shield_perk_main_ID'] == main_id) & (self.df_main['Part_type'] == 'Perk')]
        for _, r in df.iterrows():
            text, part_id = self._fmt_row(r)
            items.append({"key": f"p{main_id}:{part_id}", "label": text,
                          "category": self._augment_facet(main_id, part_id), "data": int(part_id)})
        return items

    def _augment_items(self, mfg_id, slot):
        labels = (self.ui_loc or {}).get('augment_sources') or {}
        source_names = {
            246: labels.get("universal", "Universal"),
            248: labels.get("energy", "Energy"),
            237: labels.get("armor", "Armor"),
        }
        source_keys = {246: "universal", 248: "energy", 237: "armor"}
        current_type = self.MFG_TYPE_BASE.get(mfg_id)
        rows = []
        for parent in (246, 248, 237):
            df = self.df_main[
                (self.df_main['Shield_perk_main_ID'] == parent)
                & (self.df_main['Part_type'] == 'Perk')
            ]
            for _, row in df.iterrows():
                part_id = int(row['Part_ID'])
                if self._augment_facet(parent, part_id) != slot:
                    continue
                text, _ = self._fmt_row(row)
                source_key = source_keys[parent]
                preferred = parent == 246 or source_key.casefold() == str(current_type or "").casefold()
                incompatible_type = "Armor" if current_type == "Energy" else "Energy"
                mismatch = str((self.ui_loc.get("misc") or {}).get("perk_type_mismatch") or "Incompatible shield type")
                disabled_reason = mismatch.format(
                    shield_type=self._shield_type_text(current_type),
                    incompatible_type=self._shield_type_text(incompatible_type),
                ) if not preferred else ""
                rows.append((0 if preferred else 1, parent, part_id, {
                    "key": f"{slot}:{parent}:{part_id}",
                    "label": f"[{source_names[parent]}] {text}",
                    "category": source_key,
                    "data": (parent, part_id),
                    "disabled": not preferred,
                    "disabled_reason": disabled_reason,
                }))
        rows.sort(key=lambda item: (item[0], item[1], item[2]))
        return [item[-1] for item in rows]

    def _shield_type_text(self, shield_type):
        key = "shield_type_energy" if shield_type == "Energy" else "shield_type_armor"
        return str((self.ui_loc.get("misc") or {}).get(key) or shield_type or "")

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
        if key in {"primary", "secondary"}:
            return self._augment_items(mfg_id, f"{key}_augment")
        return []

    def _group_rows(self, key, mfg_id):
        return None  # element/firmware populated once in _populate_initial_extra

    def _on_mfg_changed_extra(self, mfg_id):
        allowed_parents = {246, 248 if self.MFG_TYPE_BASE.get(mfg_id) == "Energy" else 237}
        if not self._imported_copy:
            # Imported copies preserve their original (possibly modified) tokens.
            # New builds must not carry an Armor augment across a manufacturer
            # switch into an Energy shield, or vice versa.
            for key in ("primary", "secondary"):
                picker = self._group_pickles[key]
                for entry in list(picker.entries()):
                    parent, _part_id = entry["data"]
                    if int(parent) not in allowed_parents:
                        picker.remove_key(entry["key"])
        for key in ("primary", "secondary"):
            self._group_pickles[key].set_source(self._group_items(key, mfg_id))

    # ------------------------------------------------------------------ #
    # Output
    # ------------------------------------------------------------------ #
    def _build_skill_parts(self, mfg_id):
        skill_parts, secondary = [], {}
        leg_entries = self._picker_entries("legendary")
        has_legendary_body = any(
            int(entry["data"][1]) == int(mfg_id) and self._legendary_facet(entry["data"]) == "body"
            for entry in leg_entries
        )
        # Model part
        if self._imported_copy and self._source_model_present:
            skill_parts.append(f"{{{self.mfg_model_map[mfg_id]}}}")
        elif not self._imported_copy and not has_legendary_body and mfg_id in self.mfg_model_map:
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
        # Primary and secondary are independent natural slots.  Each candidate keeps
        # its real parent id so universal/energy/armor augments serialize correctly.
        for key in ("primary", "secondary"):
            picker = self._group_pickles.get(key)
            for e in self._picker_entries(key):
                parent, part_id = e["data"]
                for _ in range(self._count_of(e)):
                    secondary.setdefault(parent, []).append(part_id)
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
        primary = self._picker_item_map("primary")
        secondary_picker = self._picker_item_map("secondary")
        legendary = self._picker_item_map("legendary")
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
                    elif (parent_id, part_id) in primary:
                        self._picker_add("primary", primary[(parent_id, part_id)])
                    elif (parent_id, part_id) in secondary_picker:
                        self._picker_add("secondary", secondary_picker[(parent_id, part_id)])
                    else:
                        self._preserved_children[246].append(part_id)
                elif parent_id in (248, 237):
                    if (parent_id, part_id) in primary:
                        self._picker_add("primary", primary[(parent_id, part_id)])
                    elif (parent_id, part_id) in secondary_picker:
                        self._picker_add("secondary", secondary_picker[(parent_id, part_id)])
                    else:
                        self._preserved_children[parent_id].append(part_id)
                elif (part_id, parent_id) in legendary:
                    self._picker_add("legendary", legendary[(part_id, parent_id)])
                else:
                    unknown.append(part_id)
            if unknown:
                values = ' '.join(map(str, unknown))
                self._preserved_tokens.append(
                    f"{{{parent_id}:{unknown[0]}}}" if len(unknown) == 1 else f"{{{parent_id}:[{values}]}}"
                )
