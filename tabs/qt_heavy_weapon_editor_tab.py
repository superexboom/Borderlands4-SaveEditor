import pandas as pd
from functools import lru_cache
import random
import re

from PyQt6.QtCore import Qt

from core import item_display_resolver, resource_loader
from tabs.qt_equipment_base_tab import BaseEquipmentEditorTab

# Heavy barrels and barrel accessories carry their subtype in the index's internal
# part string: part_barrel_01_* is T1, part_barrel_02_* is T2. This is exported by
# the pipeline and is authoritative; the CSV String column is hand-written and wrong
# for several parts (289:24 says Barrel_01 but is really part_barrel_02_gammavoid), so
# the tab must never derive the subtype from CSV. Special/unique barrels (javelin,
# dahlfather, loiter) carry no 01/02 and get no marker.
_BARREL_SUBTYPE_RE = re.compile(r"barrel_(01|02)")


def _barrel_type_marker(ref_key):
    """Return 'T1'/'T2' from a part's index internal string, or '' when it has no subtype."""
    match = _BARREL_SUBTYPE_RE.search(item_display_resolver.equipment_part_internal(ref_key).lower())
    return f"T{int(match.group(1))}" if match else ""


@lru_cache(maxsize=None)
def load_heavy_weapon_data(lang='zh-CN'):
    try:
        df_main = resource_loader.load_localized_csv_resource('heavy/heavy_main_perk.csv', lang)
        df_parts = resource_loader.load_localized_csv_resource('heavy/heavy_manufacturer_perk.csv', lang)
        # Rarity rows live in their own file, as they already do for the other three
        # equipment families (grenade/manufacturer_rarity_perk.csv, shield/manufacturer_perk.csv,
        # repkit/repkit_manufacturer_perk.csv). Keeping them out of the part file lets the
        # part file carry ids and names only, with descriptions coming from the index. The
        # rarity file keeps its Description column because that is where the legendary skin
        # names live, and those have no other source.
        df_rarity = resource_loader.load_localized_csv_resource('heavy/heavy_rarity.csv', lang)
        df_mfg = pd.concat([df_parts, df_rarity], ignore_index=True)
        df_mfg['Manufacturer ID'] = pd.to_numeric(df_mfg['Manufacturer ID'], errors='coerce')
        df_mfg.dropna(subset=['Manufacturer ID'], inplace=True)
        df_mfg['Manufacturer ID'] = df_mfg['Manufacturer ID'].astype(int)
        localization = {}
        if lang == 'zh-CN':
            localization = resource_loader.load_json_resource('heavy/Heavy_localization_zh-CN.json') or {}
        return df_main, df_mfg, localization
    except Exception as e:
        print(f"Error loading heavy weapon data: {e}")
        return None, None, None


class QtHeavyWeaponEditorTab(BaseEquipmentEditorTab):
    EQUIP_TYPE = "heavy"
    UI_LOC_KEY = "heavy_weapon_tab"
    DEFAULT_SEED = None  # heavy uses a random seed per new build
    MFG_IDS = [282, 273, 275, 289]
    BACKPACK_TYPE_EN = "Heavy Weapon"
    ITEM_LABEL = "Heavy Weapon"

    ELEMENT_PARENT = 1
    FIRMWARE_PARENT = 244

    # Each picker serves exactly one rule group here (56 Barrel Accessory rows all resolve
    # to barrel_acc, 16 Body Accessory rows all to body_acc), so the badge shows that
    # group's declared budget for the current composition. Both vary: barrel_acc is max
    # 0/1/2 and body_acc is max 0/1/2/3 depending on the composition, which a constant
    # could not express.
    RULE_GROUPS_BY_PICKER = {
        "barrel_acc": ("barrel_acc",),
        "body_acc": ("body_acc",),
    }

    def load_data(self, lang):
        return load_heavy_weapon_data(lang)

    def _backpack_predicate(self, value):
        return value.get('container') == 'Backpack' and (
            value.get('type_en') == 'Heavy Weapon' or value.get('id') in self.mfg_ids)

    def _default_new_header(self, mfg_id, level):
        return f"{mfg_id}, 0, 1, {level}| 2, {random.randint(100, 9999)}"

    def _declare_perk_groups(self):
        return [
            {"key": "barrel", "mode": "chip", "title_key": "barrel", "columns": 2, "grid": (0, 0, 1, 1)},
            {"key": "element", "mode": "chip", "title_key": "element", "columns": 2, "grid": (0, 1, 1, 1)},
            {"key": "firmware", "mode": "chip", "title_key": "firmware", "columns": 2, "grid": (0, 2, 1, 1)},
            {"key": "barrel_acc", "mode": "picker", "title_key": "barrel_acc", "stackable": True, "grid": (1, 0, 1, 3)},
            {"key": "body_acc", "mode": "picker", "title_key": "body_acc", "stackable": True, "grid": (2, 0, 1, 3)},
        ]

    def _initial_preserved_children(self):
        return {}

    # ------------------------------------------------------------------ #
    # Population
    # ------------------------------------------------------------------ #
    def _populate_initial_extra(self):
        self._populate_chip_group(
            self._group_cfgs["element"],
            self.df_main[self.df_main['Heavy_perk_main_ID'] == self.ELEMENT_PARENT],
            self._fmt_prefixed_row)
        self._populate_chip_group(
            self._group_cfgs["firmware"],
            self.df_main[self.df_main['Heavy_perk_main_ID'] == self.FIRMWARE_PARENT],
            self._fmt_prefixed_row)

    def _fmt_prefixed_row(self, r):
        """Format a heavy row; part_id becomes 'main_id:part_id' when applicable."""
        text = item_display_resolver.equipment_part_name(
            self._row_ref_key(r), self.current_lang, self._(r['Stat'])
        )
        description = self._row_description(r)
        if description:
            text += f" - {description}"
        part_id = r['Part_ID']
        if 'Heavy_perk_main_ID' in r and pd.notna(r['Heavy_perk_main_ID']):
            part_id = f"{int(r['Heavy_perk_main_ID'])}:{part_id}"
        return text, part_id

    def _group_rows(self, key, mfg_id):
        if key == "barrel":
            df = self.df_mfg[(self.df_mfg['Part_type'] == 'Barrel') & (self.df_mfg['Manufacturer ID'] == mfg_id)]
            return df, self._fmt_barrel_row
        return None  # element/firmware populated once

    def _fmt_barrel_row(self, r):
        """Barrel chip label: T1/T2 marker + exported name (like the weapon tab)."""
        ref_key = self._row_ref_key(r)
        marker = _barrel_type_marker(ref_key)
        name = item_display_resolver.equipment_part_name(ref_key, self.current_lang, self._(r['Stat']))
        desc = self._row_description(r)
        text = " - ".join(part for part in (marker, name, desc) if part)
        return text, r['Part_ID']

    def _group_items(self, key, mfg_id):
        if key == "barrel_acc":
            return self._barrel_acc_items(mfg_id)
        if key == "body_acc":
            return self._body_acc_items(mfg_id)
        return []

    def _barrel_acc_items(self, mfg_id):
        items = []
        df = self.df_mfg[self.df_mfg['Part_type'] == 'Barrel Accessory'].copy()
        df = df.drop_duplicates(subset=['Part_ID', 'Manufacturer ID'])
        df = df[df['Manufacturer ID'] == mfg_id].sort_values(by=['Part_ID'])
        for _, r in df.iterrows():
            ref_key = self._row_ref_key(r)
            marker = _barrel_type_marker(ref_key)
            name = item_display_resolver.equipment_part_name(ref_key, self.current_lang, r['Stat'])
            desc = self._row_description(r)
            label = " - ".join(part for part in (marker, name, desc, f"ID:{r['Part_ID']}") if part)
            items.append({"key": f"ba{r['Part_ID']}", "label": label, "category": marker or None,
                          "data": int(r['Part_ID'])})
        return items

    def _body_acc_items(self, mfg_id):
        items = []
        df = self.df_mfg[self.df_mfg['Part_type'] == 'Body Accessory'].copy()
        df = df.drop_duplicates(subset=['Part_ID', 'Manufacturer ID'])
        df = df[df['Manufacturer ID'] == mfg_id].sort_values(by=['Part_ID'])
        for _, r in df.iterrows():
            mfg_name = self._get_mfg_name(r['Manufacturer ID'])
            name = item_display_resolver.equipment_part_name(
                self._row_ref_key(r), self.current_lang, r['Stat']
            )
            desc = self._row_description(r)
            label = " - ".join(part for part in (mfg_name, name, desc, f"ID:{r['Part_ID']}") if part)
            items.append({"key": f"ba2{r['Part_ID']}", "label": label, "category": None, "data": int(r['Part_ID'])})
        return items

    def _body_id(self, mfg_id):
        rows = self.df_mfg[(self.df_mfg['Manufacturer ID'] == mfg_id) & (self.df_mfg['Part_type'] == 'Body')]
        return int(rows.iloc[0]['Part_ID']) if not rows.empty else None

    # ------------------------------------------------------------------ #
    # Output
    # ------------------------------------------------------------------ #
    def _build_skill_parts(self, mfg_id):
        skill_parts, secondary = [], {}
        body_id = self._body_id(mfg_id)
        if body_id is not None:
            skill_parts.append(f"{{{body_id}}}")
        # barrel + element + firmware are emitted as plain {part_id}
        # (element/firmware part_id already carries "parent:child" prefix)
        for pid in self._checked_part_ids("barrel", "element", "firmware"):
            skill_parts.append(f"{{{pid}}}")
        # accessories stacked
        for key in ("barrel_acc", "body_acc"):
            for e in self._picker_entries(key):
                for _ in range(self._count_of(e)):
                    skill_parts.append(f"{{{e['data']}}}")
        return skill_parts, secondary

    # ------------------------------------------------------------------ #
    # Import
    # ------------------------------------------------------------------ #
    def _apply_components(self, component):
        from tabs.qt_serial_import import parse_components
        mfg_id = self._current_mfg_id()
        rarity_ids = self._rarity_index_map()
        body_id = self._body_id(mfg_id)
        barrel_pids = {int(p) for p in self._group_cfgs["barrel"]["_chip"].option_pids()}
        barrel_acc = self._picker_item_map("barrel_acc")
        body_acc = self._picker_item_map("body_acc")

        for token in parse_components(component):
            kind = token['type']
            if kind == 'simple':
                part_id = token['id']
                if part_id in rarity_ids:
                    self.rarity_combo.setCurrentIndex(rarity_ids[part_id])
                elif body_id is not None and part_id == body_id:
                    continue
                elif part_id in barrel_pids:
                    self._select_group_pid("barrel", part_id)
                elif part_id in barrel_acc:
                    self._picker_add("barrel_acc", barrel_acc[part_id])
                elif part_id in body_acc:
                    self._picker_add("body_acc", body_acc[part_id])
                else:
                    self._preserved_tokens.append(f"{{{part_id}}}")
                continue
            if kind in ('single', 'group'):
                parent = token['id']
                children = [token['value']] if kind == 'single' else token['children']
                unknown = []
                key = "element" if parent == self.ELEMENT_PARENT else "firmware" if parent == self.FIRMWARE_PARENT else None
                for child in children:
                    if key and self._select_group_pid(key, f"{parent}:{child}"):
                        pass
                    else:
                        unknown.append(child)
                if unknown:
                    self._preserved_tokens.append(self._format_group(parent, unknown))
                continue
            self._preserved_tokens.append(f'"{token["value"]}"')

    @staticmethod
    def _format_group(parent, children):
        return f"{{{parent}:{children[0]}}}" if len(children) == 1 else f"{{{parent}:[{' '.join(map(str, children))}]}}"
