import re

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

    # The universal picker serves the CSV's 51 "Perk" rows, which resolve to four rule
    # groups: secondary_augment (21), primary_augment (20), augment_element_splat (5) and
    # augment_element_nova (5). Its budget is therefore the sum of those groups as declared
    # for the current composition, read from the generation rules so a retuned or new
    # composition needs no code change.
    RULE_GROUPS_BY_PICKER = {
        "universal": ("primary_augment", "secondary_augment",
                      "augment_element_splat", "augment_element_nova"),
    }
    # resistance/immunity part_id -> derived "Model Plus" id
    _DERIVED_MAP = {}
    for _ids, _derived in (({24, 50, 29, 44}, 98), ({23, 47, 28, 43}, 99),
                           ({26, 51, 31, 46}, 100), ({22, 49, 27, 42}, 101),
                           ({25, 48, 30, 45}, 102)):
        for _i in _ids:
            _DERIVED_MAP[_i] = _derived
    DERIVED_IDS = {98, 99, 100, 101, 102}

    # Elemental augments only work alongside the mechanics carrier of their
    # family, the way a weapon needs its body. The effect part supplies the card
    # text; the carrier supplies the mechanism, so emitting one without the other
    # produces a serial the game cannot resolve.
    #
    # Confirmed over 592 repkit samples (245 epic / 151 legendary / 196 CT
    # deserialized): every elemental effect co-occurs with exactly one carrier of
    # its family, every carrier co-occurs with an effect, and no sample carries
    # both variants of a family at once.
    #
    # Two shapes, and they are not interchangeable:
    #  * resist / immunity have distinct effect ids per slot, so the id alone
    #    fixes the carrier (22-26 -> 76, 47-51 -> 53, ...). Here the "_sec"
    #    suffix does agree with the slot.
    #  * splat / nova reuse one set of effect ids across both slots, so the id
    #    cannot pick a carrier. Their part names carry no "_sec" suffix even
    #    though they appear in the secondary slot too, which is why the suffix is
    #    never used as the discriminator.
    _CARRIER_FIXED = {}
    for _eff, _carrier in ((range(22, 27), 76), (range(27, 32), 78),
                           (range(42, 47), 55), (range(47, 52), 53)):
        for _e in _eff:
            _CARRIER_FIXED[_e] = _carrier
    # effect id -> (primary carrier, secondary carrier); secondary is the default
    # because it is the majority in every sample family, and an import that
    # already names the primary carrier keeps it via _primary_carriers.
    _CARRIER_EITHER = {}
    for _eff, _pri, _sec in ((range(32, 37), 72, 95), (range(37, 42), 66, 89)):
        for _e in _eff:
            _CARRIER_EITHER[_e] = (_pri, _sec)
    # Every carrier id, so imports can tell a carrier from a real augment pick.
    CARRIER_IDS = {53, 76, 55, 78, 72, 95, 66, 89}
    _PRIMARY_CARRIERS = {53, 55, 72, 66}

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
        # Cleared alongside _preserved_tokens on both import and reset, so a
        # previous item's slot choice cannot leak into the next build.
        self._primary_carriers = set()
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
        self._group_pickles["universal"].set_categories(self._universal_categories(), columns=3)
        self._group_pickles["universal"].set_source(self._universal_items())

    def _universal_items(self):
        items = []
        for _, r in self._df243()[self._df243()['Part_type'] == 'Perk'].iterrows():
            text, _ = self._fmt_row(r)
            pid = int(r['Part_ID'])
            label = f"{text} [{pid}]"
            items.append({"key": f"u{pid}", "label": label,
                          "category": self._augment_facet(pid), "data": pid})
        return items

    # The picker used to collapse all 51 Perk rows into one uncategorised list,
    # which hid that primary and secondary augments occupy different slots. The
    # facet keys below are the part_refs categories, mapped through the tab's own
    # localization so they read as slot names rather than internal identifiers.
    _AUGMENT_FACETS = ("primary_augment", "secondary_augment",
                       "augment_element_splat", "augment_element_nova")

    def _augment_facet(self, part_id):
        from core import item_display_resolver as resolver

        ref = (resolver._item_index().get("part_refs") or {}).get(
            f"{self.SECONDARY_PARENT}:{part_id}") or {}
        category = str(ref.get("category") or "")
        return category if category in self._AUGMENT_FACETS else "other"

    def _universal_categories(self):
        groups = (self.ui_loc or {}).get('augment_facets') or {}
        cats = [("all", groups.get('all', 'All'))]
        for key in self._AUGMENT_FACETS:
            cats.append((key, groups.get(key, key)))
        cats.append(("other", groups.get('other', 'Other')))
        return cats

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
        self._add_elemental_carriers(secondary.setdefault(self.SECONDARY_PARENT, []))
        return skill_parts, secondary

    def _add_elemental_carriers(self, children):
        """Inject the mechanics carrier for every elemental effect present.

        Runs after all groups have contributed, because a carrier may be implied
        by a resistance chip and by a universal pick at the same time and must
        still only be emitted once. Carriers the user picked by hand (they are
        selectable in the universal list) are left where they are, so nothing is
        duplicated and an explicitly chosen primary is not swapped for the
        secondary default.

        Effects can also arrive through _preserved_tokens: resist and immunity
        share one single-select chip group, so importing an item that carries one
        of each displaces the loser into a preserved ``{243:...}`` token. Those
        still need their carrier, hence the token scan.
        """
        present = set(children)
        effects = set(present)
        for token in self._preserved_tokens:
            match = re.fullmatch(
                r"\{" + str(self.SECONDARY_PARENT) + r":\[?([\d ]+)\]?\}", token.strip()
            )
            if match:
                effects.update(int(x) for x in match.group(1).split())
        for pid in sorted(effects):
            if pid in self._CARRIER_FIXED:
                needed = self._CARRIER_FIXED[pid]
            elif pid in self._CARRIER_EITHER:
                primary, secondary_carrier = self._CARRIER_EITHER[pid]
                # Honour whichever slot the serial already establishes; the
                # secondary carrier is the fallback for a fresh build.
                if primary in effects or primary in getattr(self, "_primary_carriers", ()):
                    needed = primary
                else:
                    needed = secondary_carrier
            else:
                continue
            if needed not in present:
                children.append(needed)
                present.add(needed)

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
        primary_carriers = set()

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
                    if parent == self.SECONDARY_PARENT and child in self.CARRIER_IDS:
                        # Carriers are re-derived from the effect picks on every
                        # rebuild. Preserving the token as well would emit the id
                        # twice, so only the slot choice is kept. 243:66 is also a
                        # selectable Perk row, so it still needs to reach the
                        # picker to stay visible in the UI.
                        if child in self._PRIMARY_CARRIERS:
                            primary_carriers.add(child)
                        if child in universal:
                            self._picker_add("universal", universal[child])
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

        # splat/nova reuse one effect id across both slots, so the imported
        # carrier is the only record of which slot the item used.
        self._primary_carriers = primary_carriers

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
