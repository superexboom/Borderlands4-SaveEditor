"""修复套件编辑器 VM：对齐主线 QtRepkitEditorTab 的差异配置。"""

from __future__ import annotations

import re

from core import item_display_resolver
from core.equipment_data import load_repkit_data
from core.serial_import import parse_components

from .base import register
from .equipment_base import EquipmentBaseViewModel


@register("repkit", "RepkitPage.qml")
class RepkitViewModel(EquipmentBaseViewModel):
    EQUIP_TYPE = "repkit"
    UI_LOC_KEY = "repkit_tab"
    STRINGS_SECTION = "repkit_tab"
    DEFAULT_SEED = 307
    MFG_IDS = [277, 265, 266, 285, 274, 290, 261, 269]
    BACKPACK_TYPE_EN = "Repkit"
    ITEM_LABEL = "Repkit"

    SECONDARY_PARENT = 243

    RULE_GROUPS_BY_PICKER = {
        "prefix": ("payload",),
        "resistance": ("augment_element_resist", "element"),
        "immunity": ("augment_element_immunity", "element"),
        "firmware": ("firmware",),
        "legendary": ("primary_augment", "secondary_augment", "vile"),
        "universal": ("primary_augment", "secondary_augment",
                      "augment_element_splat", "augment_element_nova"),
    }

    _DERIVED_MAP = {}
    for _ids, _derived in (({24, 50, 29, 44}, 98), ({23, 47, 28, 43}, 99),
                           ({26, 51, 31, 46}, 100), ({22, 49, 27, 42}, 101),
                           ({25, 48, 30, 45}, 102)):
        for _i in _ids:
            _DERIVED_MAP[_i] = _derived
    DERIVED_IDS = {98, 99, 100, 101, 102}

    _CARRIER_FIXED = {}
    for _eff, _carrier in ((range(22, 27), 76), (range(27, 32), 78),
                           (range(42, 47), 55), (range(47, 52), 53)):
        for _e in _eff:
            _CARRIER_FIXED[_e] = _carrier
    _CARRIER_EITHER = {}
    for _eff, _pri, _sec in ((range(32, 37), 72, 95), (range(37, 42), 66, 89)):
        for _e in _eff:
            _CARRIER_EITHER[_e] = (_pri, _sec)
    CARRIER_IDS = {53, 76, 55, 78, 72, 95, 66, 89}
    _PRIMARY_CARRIERS = {53, 55, 72, 66}

    _AUGMENT_FACETS = ("primary_augment", "secondary_augment",
                       "augment_element_splat", "augment_element_nova")

    def load_data(self, lang):
        return load_repkit_data(lang)

    def _backpack_predicate(self, value):
        return value.get("container") == "Backpack" and (
            value.get("type_en") == "Repkit" or value.get("id") in self.mfg_ids)

    def _declare_perk_groups(self):
        return [
            {"key": "prefix", "mode": "chip", "title_key": "prefix"},
            {"key": "resistance", "mode": "chip", "title_key": "resistance"},
            {"key": "immunity", "mode": "chip", "title_key": "immunity"},
            {"key": "firmware", "mode": "chip", "title_key": "firmware"},
            {"key": "legendary", "mode": "picker", "title_key": "legendary", "stackable": False},
            {"key": "universal", "mode": "picker", "title_key": "universal", "stackable": True},
        ]

    def _initial_preserved_children(self):
        self._primary_carriers = set()
        return {}

    # ------------------------------------------------------------------ #
    # 规则指引
    # ------------------------------------------------------------------ #
    def _generation_ref_for_option(self, key, data):
        if data is None:
            return ""
        if key == "legendary":
            part_id, owner = data
            return f"{int(owner)}:{int(part_id)}"
        return f"{self.SECONDARY_PARENT}:{int(data)}"

    def _element_macro_bundle(self, part_id):
        part_id = int(part_id)
        carrier = self._CARRIER_FIXED.get(part_id)
        derived = self._DERIVED_MAP.get(part_id)
        if carrier is None or derived is None:
            return []
        refs = item_display_resolver._item_index().get("part_refs") or {}
        bundle = []
        for ref in (f"{self.SECONDARY_PARENT}:{part_id}",
                    f"{self.SECONDARY_PARENT}:{carrier}",
                    f"{self.SECONDARY_PARENT}:{derived}"):
            category = str((refs.get(ref) or {}).get("category") or "")
            if category:
                bundle.append((category, ref))
        return bundle

    def _candidate_state_for_option(self, key, data, ref, rule_keys, groups):
        if key not in {"resistance", "immunity"} or data is None:
            return super()._candidate_state_for_option(key, data, ref, rule_keys, groups)
        bundle = self._element_macro_bundle(data)
        if not bundle:
            return super()._candidate_state_for_option(key, data, ref, rule_keys, groups)

        replaced = set()
        current = self._selected_button_pid(key)
        if current is not None:
            replaced = {bundle_ref for _group, bundle_ref in self._element_macro_bundle(current)}

        group_names = []
        for group, bundle_ref in bundle:
            spec = groups.get(group) or {}
            allowed = set(spec.get("allowed") or [])
            maximum = int(spec.get("max", 0))
            if bundle_ref not in allowed or maximum <= 0:
                return {
                    "kind": "warning",
                    "marker": "!",
                    "hint": self._legit_text(
                        "candidate_dependency",
                        "This macro is not active for the current rarity or slot layout.",
                    ).format(group=self._generation_group_text(group)),
                }
            selected = set(spec.get("selected") or []) - replaced
            if bundle_ref not in selected and len(selected) >= maximum:
                return {
                    "kind": "warning",
                    "marker": "!",
                    "hint": self._legit_text(
                        "candidate_slot_full",
                        "Natural candidate for {group}; replace an existing part to stay legal.",
                    ).format(group=self._generation_group_text(group)),
                }
            group_names.append(self._generation_group_text(group))

        return {
            "kind": "legal",
            "marker": "✓",
            "hint": self._legit_text("candidate_legal", "Natural candidate: {group}").format(
                group=" / ".join(dict.fromkeys(group_names))
            ),
        }

    # ------------------------------------------------------------------ #
    # 组内容
    # ------------------------------------------------------------------ #
    def _df243(self):
        return self.df_main[self.df_main["Repkit_perk_main_ID"] == 243]

    def _chip_options(self, key, mfg_id):
        df = self._df243()
        if key == "prefix":
            return self._chip_option_list(key, df[df["Part_type"] == "Perfix"], self._fmt_row)
        if key == "firmware":
            return self._chip_option_list(
                key, self._firmware_group_df("Repkit_perk_main_ID", self.SECONDARY_PARENT),
                self._fmt_row)
        if key == "resistance":
            return self._chip_option_list(key, df[df["Part_type"] == "Resistance"], self._fmt_row)
        if key == "immunity":
            return self._chip_option_list(key, df[df["Part_type"] == "Immunity"], self._fmt_row)
        return None

    def _universal_items(self):
        items = []
        for _, r in self._df243()[self._df243()["Part_type"] == "Perk"].iterrows():
            text, _ = self._fmt_row(r)
            pid = int(r["Part_ID"])
            if pid in self.CARRIER_IDS or pid in self.DERIVED_IDS:
                continue
            label = f"{text} [{pid}]"
            items.append({"key": f"u{pid}", "label": label,
                          "category": self._augment_facet(pid), "data": pid})
        return items

    def _augment_facet(self, part_id):
        ref = (item_display_resolver._item_index().get("part_refs") or {}).get(
            f"{self.SECONDARY_PARENT}:{part_id}") or {}
        category = str(ref.get("category") or "")
        return category if category in self._AUGMENT_FACETS else "other"

    def _picker_categories(self, key):
        if key != "universal":
            return super()._picker_categories(key)
        groups = (self.ui_loc or {}).get("augment_facets") or {}
        cats = [("all", groups.get("all", "All"))]
        for k in self._AUGMENT_FACETS:
            cats.append((k, groups.get(k, k)))
        cats.append(("other", groups.get("other", "Other")))
        return cats

    def _legendary_items(self, current_mfg):
        items = []
        df_leg = self.df_mfg[self.df_mfg["Part_type"] == "Legendary Perk"].copy()
        df_leg["sort_key"] = df_leg["Manufacturer ID"].apply(lambda x: 0 if x == current_mfg else 1)
        df_leg = df_leg.sort_values(by=["sort_key", "Manufacturer ID", "Part_ID"])
        for _, r in df_leg.iterrows():
            mfg_name = self._get_mfg_name(r["Manufacturer ID"])
            text, _ = self._fmt_row(r)
            label = f"{mfg_name} - {text}".strip(" -")
            pid, mid = int(r["Part_ID"]), int(r["Manufacturer ID"])
            items.append({"key": f"l{mid}:{pid}", "label": label,
                          "category": "current" if mid == current_mfg else "other", "data": (pid, mid)})
        return items

    def _group_items(self, key, mfg_id):
        if key == "legendary":
            return self._legendary_items(mfg_id)
        if key == "universal":
            return self._universal_items()
        return []

    def _model_id(self, mfg_id):
        rows = self.df_mfg[(self.df_mfg["Manufacturer ID"] == mfg_id) & (self.df_mfg["Part_type"] == "Model")]
        return int(rows.iloc[0]["Part_ID"]) if not rows.empty else None

    # ------------------------------------------------------------------ #
    # 输出组装
    # ------------------------------------------------------------------ #
    def _build_skill_parts(self, mfg_id):
        skill_parts, secondary = [], {}
        model_id = self._model_id(mfg_id)
        if model_id is not None:
            skill_parts.append(f"{{{model_id}}}")
        other_mfg = {}
        for e in self._entries("legendary"):
            pid, item_mfg = e["data"]
            for _ in range(int(e.get("count", 1))):
                if item_mfg == mfg_id:
                    skill_parts.append(f"{{{pid}}}")
                else:
                    other_mfg.setdefault(item_mfg, []).append(pid)
        for item_mfg, ids in other_mfg.items():
            skill_parts.append(f"{{{item_mfg}:{ids[0]}}}" if len(ids) == 1
                               else f"{{{item_mfg}:[{' '.join(map(str, sorted(ids)))}]}}")
        derived_ids = set()
        for pid in self._checked_part_ids("prefix", "firmware", "resistance", "immunity"):
            secondary.setdefault(self.SECONDARY_PARENT, []).append(pid)
            derived = self._DERIVED_MAP.get(pid)
            if derived is not None:
                derived_ids.add(derived)
        secondary.setdefault(self.SECONDARY_PARENT, []).extend(sorted(derived_ids))
        for e in self._entries("universal"):
            for _ in range(int(e.get("count", 1))):
                secondary.setdefault(self.SECONDARY_PARENT, []).append(e["data"])
        self._add_elemental_carriers(secondary.setdefault(self.SECONDARY_PARENT, []))
        return skill_parts, secondary

    def _add_elemental_carriers(self, children):
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
    # 导入
    # ------------------------------------------------------------------ #
    def _apply_components(self, component):
        current_mfg = self._current_mfg_id()
        rarity_ids = self._rarity_index_map()
        model_id = self._model_id(current_mfg)
        universal = self._picker_item_map("universal")
        legendary = self._picker_item_map("legendary")
        pending_derived, extra_secondary = [], []
        selected_radio = {}
        primary_carriers = set()

        def radio_category(pid):
            for key in ("prefix", "firmware", "resistance", "immunity"):
                if pid in self._button_pid_map(key):
                    return key
            return None

        for token in parse_components(component):
            kind = token["type"]
            if kind == "simple":
                part_id = token["id"]
                if part_id in rarity_ids:
                    self._rarity_index = rarity_ids[part_id]
                elif model_id is not None and part_id == model_id:
                    continue
                elif (part_id, current_mfg) in legendary:
                    self._picker_add("legendary", legendary[(part_id, current_mfg)])
                else:
                    self._preserved_tokens.append(f"{{{part_id}}}")
                continue
            if kind in ("single", "group"):
                parent = token["id"]
                children = [token["value"]] if kind == "single" else token["children"]
                unknown = []
                for child in children:
                    if parent == self.SECONDARY_PARENT and child in self.DERIVED_IDS:
                        pending_derived.append(child)
                        continue
                    if parent == self.SECONDARY_PARENT and child in self.CARRIER_IDS:
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

        self._primary_carriers = primary_carriers

        generated = []
        for key in ("resistance", "immunity"):
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
