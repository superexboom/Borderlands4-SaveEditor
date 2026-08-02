import pandas as pd
from functools import lru_cache

from PyQt6.QtCore import Qt

from core import resource_loader
from tabs.qt_equipment_base_tab import BaseEquipmentEditorTab


@lru_cache(maxsize=None)
def load_repkit_data(lang='zh-CN'):
    try:
        df_main = resource_loader.load_localized_csv_resource('repkit/repkit_main_perk.csv', lang)
        df_mfg = resource_loader.load_localized_csv_resource('repkit/repkit_manufacturer_perk.csv', lang)
        localization = {}
        if lang == 'zh-CN':
            localization = resource_loader.load_json_resource('repkit/Repkit_localization_zh-CN.json') or {}
        return df_main, df_mfg, localization
    except Exception as e:
        print(f"Error loading repkit data: {e}")
        return None, None, None


class QtRepkitEditorTab(BaseEquipmentEditorTab):
    EQUIP_TYPE = "repkit"
    UI_LOC_KEY = "repkit_tab"
    DEFAULT_SEED = 307
    MFG_IDS = [277, 265, 266, 285, 274, 290, 261, 269]
    BACKPACK_TYPE_EN = "Repkit"
    ITEM_LABEL = "Repkit"

    SECONDARY_PARENT = 243
    # resistance/immunity part_id -> derived "Model Plus" id
    _DERIVED_MAP = {}
    for _ids, _derived in (({24, 50, 29, 44}, 98), ({23, 47, 28, 43}, 99),
                           ({26, 51, 31, 46}, 100), ({22, 49, 27, 42}, 101),
                           ({25, 48, 30, 45}, 102)):
        for _i in _ids:
            _DERIVED_MAP[_i] = _derived
    DERIVED_IDS = {98, 99, 100, 101, 102}

    def load_data(self, lang):
        return load_repkit_data(lang)

    def _backpack_predicate(self, value):
        return value.get('container') == 'Backpack' and (
            value.get('type_en') == 'Repkit' or value.get('id') in self.mfg_ids)

    def _declare_perk_groups(self):
        return [
            {"key": "prefix", "mode": "chip", "title_key": "prefix", "columns": 2, "grid": (0, 0, 1, 1)},
            {"key": "resistance", "mode": "chip", "title_key": "resistance", "columns": 2, "grid": (0, 1, 1, 1)},
            {"key": "firmware", "mode": "chip", "title_key": "firmware", "columns": 2, "grid": (0, 2, 1, 1)},
            {"key": "legendary", "mode": "picker", "title_key": "legendary", "stackable": False, "grid": (1, 0, 1, 3)},
            {"key": "universal", "mode": "picker", "title_key": "universal", "stackable": True, "grid": (2, 0, 1, 3)},
        ]

    def _initial_preserved_children(self):
        return {}

    # ------------------------------------------------------------------ #
    # Population
    # ------------------------------------------------------------------ #
    def _df243(self):
        return self.df_main[self.df_main['Repkit_perk_main_ID'] == 243]

    def _populate_initial_extra(self):
        df = self._df243()
        self._populate_chip_group(self._group_cfgs["prefix"], df[df['Part_type'] == 'Perfix'], self._fmt_row)
        self._populate_chip_group(self._group_cfgs["firmware"], df[df['Part_type'] == 'Firmware'], self._fmt_row)
        self._populate_chip_group(self._group_cfgs["resistance"], df[df['Part_type'].isin(['Resistance', 'Immunity'])], self._fmt_row)
        self._group_pickles["universal"].set_source(self._universal_items())

    def _universal_items(self):
        items = []
        for _, r in self._df243()[self._df243()['Part_type'] == 'Perk'].iterrows():
            name = self._(r['Stat'])
            desc = r['Description'] if pd.notna(r['Description']) else ''
            label = f"{name} - {desc} [{r['Part_ID']}]" if desc else f"{name} [{r['Part_ID']}]"
            items.append({"key": f"u{r['Part_ID']}", "label": label, "category": None, "data": int(r['Part_ID'])})
        return items

    def _legendary_items(self, current_mfg):
        items = []
        df_leg = self.df_mfg[self.df_mfg['Part_type'] == 'Legendary Perk'].copy()
        df_leg['sort_key'] = df_leg['Manufacturer ID'].apply(lambda x: 0 if x == current_mfg else 1)
        df_leg = df_leg.sort_values(by=['sort_key', 'Manufacturer ID', 'Part_ID'])
        for _, r in df_leg.iterrows():
            mfg_name = self._get_mfg_name(r['Manufacturer ID'])
            label = f"{mfg_name} - {r['Stat']} - {r['Description']}"
            pid, mid = int(r['Part_ID']), int(r['Manufacturer ID'])
            items.append({"key": f"l{mid}:{pid}", "label": label,
                          "category": "current" if mid == current_mfg else "other", "data": (pid, mid)})
        return items

    def _group_items(self, key, mfg_id):
        if key == "legendary":
            return self._legendary_items(mfg_id)
        if key == "universal":
            return self._universal_items()
        return []

    def _group_rows(self, key, mfg_id):
        return None  # chip groups populated once in _populate_initial_extra

    def _model_id(self, mfg_id):
        rows = self.df_mfg[(self.df_mfg['Manufacturer ID'] == mfg_id) & (self.df_mfg['Part_type'] == 'Model')]
        return int(rows.iloc[0]['Part_ID']) if not rows.empty else None

    # ------------------------------------------------------------------ #
    # Output
    # ------------------------------------------------------------------ #
    def _build_skill_parts(self, mfg_id):
        skill_parts, secondary = [], {}
        model_id = self._model_id(mfg_id)
        if model_id is not None:
            skill_parts.append(f"{{{model_id}}}")
        # legendary cross-mfg
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
        # prefix + firmware + resistance -> 243, with derived Model Plus
        for pid in self._checked_part_ids("prefix", "firmware", "resistance"):
            secondary.setdefault(self.SECONDARY_PARENT, []).append(pid)
            derived = self._DERIVED_MAP.get(pid)
            if derived is not None:
                secondary.setdefault(self.SECONDARY_PARENT, []).append(derived)
        # universal -> 243 (stacked)
        for e in self._picker_entries("universal"):
            for _ in range(self._count_of(e)):
                secondary.setdefault(self.SECONDARY_PARENT, []).append(e["data"])
        return skill_parts, secondary

    # ------------------------------------------------------------------ #
    # Import
    # ------------------------------------------------------------------ #
    def _apply_components(self, component):
        from tabs.qt_serial_import import parse_components
        current_mfg = self._current_mfg_id()
        rarity_ids = self._rarity_index_map()
        model_id = self._model_id(current_mfg)
        universal = self._picker_item_map("universal")
        legendary = self._picker_item_map("legendary")
        pending_derived, extra_secondary = [], []
        selected_radio = {}

        def radio_category(pid):
            for key in ("prefix", "firmware", "resistance"):
                if pid in self._button_pid_map(key):
                    return key
            return None

        for token in parse_components(component):
            kind = token['type']
            if kind == 'simple':
                part_id = token['id']
                if part_id in rarity_ids:
                    self.rarity_combo.setCurrentIndex(rarity_ids[part_id])
                elif model_id is not None and part_id == model_id:
                    continue
                elif (part_id, current_mfg) in legendary:
                    self._picker_add("legendary", legendary[(part_id, current_mfg)])
                else:
                    self._preserved_tokens.append(f"{{{part_id}}}")
                continue
            if kind in ('single', 'group'):
                parent = token['id']
                children = [token['value']] if kind == 'single' else token['children']
                unknown = []
                for child in children:
                    if parent == self.SECONDARY_PARENT and child in self.DERIVED_IDS:
                        pending_derived.append(child)
                        continue
                    cat = radio_category(child) if parent == self.SECONDARY_PARENT else None
                    if cat:
                        if cat in selected_radio:
                            extra_secondary.append(selected_radio[cat])
                        selected_radio[cat] = child
                        self._select_group_pid(cat, child)
                    elif parent == self.SECONDARY_PARENT and child in universal:
                        self._picker_add("universal", universal[child])
                    elif (child, parent) in legendary:
                        self._picker_add("legendary", legendary[(child, parent)])
                    else:
                        unknown.append(child)
                if unknown:
                    self._preserved_tokens.append(self._format_group(parent, unknown))
                continue
            self._preserved_tokens.append(f'"{token["value"]}"')

        # reconcile derived Model Plus ids against selected resistances
        generated = []
        for key in ("resistance",):
            pid = self._selected_button_pid(key)
            if pid and pid in self._DERIVED_MAP:
                generated.append(self._DERIVED_MAP[pid])
        for child in pending_derived:
            if child in generated:
                generated.remove(child)
            else:
                extra_secondary.append(child)
        if extra_secondary:
            self._preserved_tokens.append(self._format_group(self.SECONDARY_PARENT, extra_secondary))

    @staticmethod
    def _format_group(parent, children):
        return f"{{{parent}:{children[0]}}}" if len(children) == 1 else f"{{{parent}:[{' '.join(map(str, children))}]}}"
