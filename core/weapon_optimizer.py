from __future__ import annotations

import copy
import heapq
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

from core import b_encoder, item_display_resolver


AUTO = "*"
NONE = ""
ELEMENT_GROUPS = ("body_ele", "secondary_ele", "pearl_elem")
WEAPON_TYPE_ALIASES = {
    "weapon_sm": "SMG",
    "weapon_ar": "Assault Rifle",
    "AssaultRifle": "Assault Rifle",
}
TORGUE_TAGS = {
    # ``torgue_mag_*`` also appears on ordinary stat parts which merely inherit
    # the licensed mode's damage.  The exact tags below identify the actual
    # Torgue normal/sticky authorization part requested by the user.
    "sticky": frozenset({"torgue_sticky", "torgue_mag_sticky"}),
    "impact": frozenset({"torgue_normal", "torgue_mag_normal"}),
}


@dataclass(frozen=True)
class GodRollRequest:
    root_id: str
    composition_ref: str
    level: int = 60
    mode: str = "legal"
    fixed_barrel_ref: str | None = None
    torgue_mode: str = "any"
    base_element_ref: str | None = AUTO
    secondary_element_ref: str | None = AUTO
    pearl_element_ref: str | None = AUTO
    allow_illegal_elements: bool = False
    group_limits: Mapping[str, tuple[int, int]] = field(default_factory=dict)
    top_n: int = 10
    max_samples: int = 20_000
    time_limit: float = 8.0
    seed: int | None = None


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))


def _target_count(rule: Mapping[str, Any], rng: random.Random, required: int) -> int:
    minimum = max(0, int(rule.get("min", 1)))
    maximum = max(minimum, int(rule.get("max", 1)))
    try:
        chance = float(rule.get("additional_chance", 0.5))
    except (TypeError, ValueError):
        chance = 0.5
    if chance <= 0:
        target = minimum
    elif chance >= 1:
        target = maximum
    else:
        # Native drop chance changes frequency, not reachability.  An optimizer
        # must explore every legal count instead of over-sampling the minimum.
        target = rng.randint(minimum, maximum)
    return min(maximum, max(target, required))


def _target_counts(rule: Mapping[str, Any]) -> tuple[int, ...]:
    minimum = max(0, int(rule.get("min", 1)))
    maximum = max(minimum, int(rule.get("max", 1)))
    try:
        chance = float(rule.get("additional_chance", 0.5))
    except (TypeError, ValueError):
        return tuple(range(minimum, maximum + 1))
    if chance <= 0:
        return (minimum,)
    if chance >= 1:
        return (maximum,)
    return tuple(range(minimum, maximum + 1))


class WeaponGodRollOptimizer:
    """Budgeted Top-K weapon optimizer using the editor's verified rules/evaluator.

    The search is deliberately anytime: every returned candidate is fully encoded,
    scored, and classified, while ``complete`` remains false until a future exact
    branch-and-bound pass proves the full frontier.  This avoids pretending a raw
    10^12+ Cartesian product was exhausted.
    """

    def __init__(self, item_index: Mapping[str, Any]):
        self.index = dict(item_index or {})
        self.rules = self.index.get("weapon_generation_rules") or {}
        self.weapons = self.rules.get("weapons") or {}
        self.part_refs = self.index.get("part_refs") or {}
        self.selection_tags = self.rules.get("part_selection_tags") or {}
        self.excluded_refs = set((self.rules.get("part_availability") or {}).keys())
        self._pool_cache: dict[tuple[str, str], dict[str, list[str]]] = {}
        self._capability_cache: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
        self._unrestricted_torgue_cache: dict[tuple[str, str, str, str], dict[str, bool]] = {}
        self._search_cache: dict[tuple[Any, ...], dict[str, Any]] = {}

    def catalog(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for root_id, weapon in self.weapons.items():
            weapon_type = self._normalized_type(weapon)
            if weapon_type not in {"Pistol", "Shotgun", "Assault Rifle", "Sniper", "SMG"}:
                continue
            for composition_ref, composition in (weapon.get("compositions") or {}).items():
                if composition.get("availability") != "coregame" or composition.get("internal_only"):
                    continue
                base_tags = {str(tag).casefold() for tag in composition.get("base_tags", ())}
                if "npc_weapon" in base_tags:
                    continue
                names = composition.get("name") or {}
                if (
                    str(composition.get("part") or "").casefold() == "comp_05_legendary"
                    and not str(names.get("en") or "").strip()
                    and not str(names.get("zh") or "").strip()
                    and not composition.get("forced_part_refs")
                ):
                    continue
                rows.append({
                    "root_id": str(root_id),
                    "composition_ref": str(composition_ref),
                    "manufacturer": str(weapon.get("manufacturer") or ""),
                    "weapon_type": weapon_type,
                    "rarity": str(composition.get("rarity") or ""),
                    "name_en": str(names.get("en") or "").strip(),
                    "name_zh": str(names.get("zh") or "").strip(),
                    "part": str(composition.get("part") or ""),
                })
        return rows

    def _part_selection_tags(self, ref: str) -> dict[str, set[str]]:
        row = self.selection_tags.get(str(ref)) or (self.part_refs.get(str(ref)) or {}).get("selection_tags") or {}
        return {
            key: {str(value).casefold() for value in row.get(key, ())}
            for key in ("adds", "requires", "excludes")
        }

    def _part_semantic_tags(self, ref: str) -> set[str]:
        row = self.part_refs.get(str(ref)) or {}
        tags = {str(tag).casefold() for tag in row.get("weapon_tags", ())}
        tags.update(self._part_selection_tags(ref)["adds"])
        return tags

    def _part_order_sensitive(self, ref: str) -> bool:
        row = self.part_refs.get(str(ref)) or {}
        if row.get("values") or row.get("forced_behavior_part_refs"):
            return True
        return any(
            str(effect.get("modifier_type") or "").casefold() == "overridebasevalue"
            for effect in row.get("weapon_attribute_effects", ())
        )

    def part_label(self, ref: str) -> str:
        row = self.part_refs.get(str(ref)) or {}
        return str(row.get("part") or row.get("name") or ref)

    @staticmethod
    def _normalized_type(weapon: Mapping[str, Any]) -> str:
        value = str(weapon.get("weapon_type") or "")
        return WEAPON_TYPE_ALIASES.get(value, value)

    def _composition_for_mode(
        self,
        root_id: str,
        composition_ref: str,
        mode: str,
    ) -> dict[str, Any]:
        weapon = self.weapons[str(root_id)]
        original = weapon["compositions"][str(composition_ref)]
        composition = copy.deepcopy(original)
        if mode != "unrestricted":
            return composition
        merged_rules: dict[frozenset[str], int] = {
            frozenset(str(tag).casefold() for tag in row.get("tags", ())): int(row.get("max", 1))
            for row in original.get("tag_rules", ())
            if row.get("tags")
        }
        target_type = self._normalized_type(weapon)
        for other in self.weapons.values():
            if self._normalized_type(other) != target_type:
                continue
            for other_comp in (other.get("compositions") or {}).values():
                if other_comp.get("availability") != "coregame" or other_comp.get("internal_only"):
                    continue
                for row in other_comp.get("tag_rules", ()):
                    tags = frozenset(str(tag).casefold() for tag in row.get("tags", ()))
                    if tags:
                        merged_rules.setdefault(tags, int(row.get("max", 1)))
        composition["tag_rules"] = [
            {"tags": sorted(tags), "max": maximum}
            for tags, maximum in sorted(merged_rules.items(), key=lambda item: tuple(sorted(item[0])))
        ]
        return composition

    def _legal_capabilities(
        self,
        root_id: str,
        composition_ref: str,
        *,
        mode: str = "legal",
        fixed_barrel_ref: str | None = None,
        base_element_ref: str | None = AUTO,
    ) -> dict[str, Any]:
        """Exact lightweight DP over legal part/tag states.

        This reuses the optimizer's group/tag-rule transition engine but drops
        complete part lists after every group. It is fast enough for UI gating
        and cannot invent Torgue/secondary-element combinations which no legal
        final build can reach.
        """
        key = (
            str(root_id),
            str(composition_ref),
            str(mode),
            str(fixed_barrel_ref or ""),
            str(base_element_ref if base_element_ref is not None else AUTO),
        )
        cached = self._capability_cache.get(key)
        if cached is not None:
            return copy.deepcopy(cached)

        weapon = self.weapons[str(root_id)]
        composition = self._composition_for_mode(str(root_id), str(composition_ref), str(mode))
        pools = self._group_pool(str(root_id), str(composition_ref), str(mode))
        groups = {
            str(group).casefold(): rule
            for group, rule in (composition.get("groups") or {}).items()
        }
        for group, rule in groups.items():
            rule["allowed_part_refs"] = list(pools.get(group, ()))
        ordered = _unique(str(group).casefold() for group in weapon.get("part_types", ()))
        ordered.extend(group for group in sorted(groups) if group not in ordered)
        ordered = [group for group in ordered if group in groups]
        tag_rules = [
            (frozenset(str(tag).casefold() for tag in rule.get("tags", ())), int(rule.get("max", 1)))
            for rule in composition.get("tag_rules", ())
        ]
        required: dict[str, frozenset[str]] = {}
        if fixed_barrel_ref:
            required["barrel"] = frozenset({str(fixed_barrel_ref)})
        if base_element_ref not in (None, AUTO, NONE):
            required["body_ele"] = frozenset({str(base_element_ref)})

        if base_element_ref == NONE and "body_ele" in groups:
            groups["body_ele"]["min"] = groups["body_ele"]["max"] = 0

        # Keep only tags which can still affect a later requires/excludes check.
        # Carrying every cosmetic/identity tag made common rarity templates fan
        # out into hundreds of thousands of otherwise equivalent UI states.
        needed_from: list[frozenset[str]] = [frozenset() for _ in range(len(ordered) + 1)]
        needed: set[str] = set()
        for index in range(len(ordered) - 1, -1, -1):
            for ref in groups[ordered[index]].get("allowed_part_refs", ()):
                tags = self._part_selection_tags(ref)
                needed.update(tags["requires"])
                needed.update(tags["excludes"])
            needed_from[index] = frozenset(needed)

        base_tags = {str(tag).casefold() for tag in composition.get("base_tags", ())}
        inherited_refs = [str(composition_ref), *map(str, composition.get("forced_part_refs", ()))]
        inherited_semantic = set().union(
            *(self._part_semantic_tags(ref) for ref in inherited_refs)
        ) if inherited_refs else set()
        semantic_seed = base_tags | inherited_semantic

        # active tags, tag-rule counters, selected element refs, and Torgue
        # semantic flags.  Element refs remain until the terminal state because
        # the UI needs the exact reachable choices; all other part identities
        # are deliberately discarded.
        states: set[tuple[
            frozenset[str], tuple[int, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...], bool, bool,
        ]] = {
            (
                frozenset(base_tags & set(needed_from[0])),
                tuple(0 for _ in tag_rules),
                (), (), (),
                bool(semantic_seed & TORGUE_TAGS["sticky"]),
                bool(semantic_seed & TORGUE_TAGS["impact"]),
            )
        }
        marker_index = {"body_ele": 2, "secondary_ele": 3, "pearl_elem": 4}
        transition_cache: dict[
            tuple[str, frozenset[str], tuple[int, ...]],
            tuple[tuple[tuple[str, ...], frozenset[str], tuple[int, ...]], ...],
        ] = {}
        for group_index, group in enumerate(ordered):
            next_states = set()
            for state in states:
                active, counts = state[0], state[1]
                transition_key = (group, active, counts)
                transitions = transition_cache.get(transition_key)
                if transitions is None:
                    transitions = tuple(self._enumerate_group_choices(
                        groups[group], active, tag_rules, counts,
                        required.get(group, frozenset()), lambda: False,
                    ))
                    transition_cache[transition_key] = transitions
                for picked, next_active, next_counts in transitions:
                    markers = [state[2], state[3], state[4]]
                    if group in marker_index:
                        markers[marker_index[group] - 2] = tuple(picked)
                    semantic = set().union(
                        *(self._part_semantic_tags(ref) for ref in picked)
                    ) if picked else set()
                    next_states.add((
                        frozenset(set(next_active) & set(needed_from[group_index + 1])),
                        next_counts,
                        *markers,
                        state[5] or bool(semantic & TORGUE_TAGS["sticky"]),
                        state[6] or bool(semantic & TORGUE_TAGS["impact"]),
                    ))
            states = next_states
            if not states:
                break

        body_refs = {ref for state in states for ref in state[2]}
        secondary_refs = {ref for state in states for ref in state[3]}
        pearl_refs = {ref for state in states for ref in state[4]}
        native_torgue = str(weapon.get("manufacturer") or "").casefold() == "torgue"
        sticky = any(state[5] for state in states)
        impact = any(
            not state[5]
            if native_torgue
            else state[6]
            for state in states
        )
        result = {
            "body_ele": body_refs,
            "secondary_ele": secondary_refs if base_element_ref not in (None, AUTO, NONE) else set(),
            "pearl_elem": pearl_refs,
            "element_none_legal": {
                "body_ele": any(not state[2] for state in states),
                "secondary_ele": any(not state[3] for state in states),
                "pearl_elem": any(not state[4] for state in states),
            },
            "torgue_modes": {"sticky": sticky, "impact": impact},
            "state_count": len(states),
        }
        self._capability_cache[key] = copy.deepcopy(result)
        return result

    def _unrestricted_torgue_modes(
        self,
        root_id: str,
        composition_ref: str,
        *,
        fixed_barrel_ref: str | None = None,
        base_element_ref: str | None = AUTO,
    ) -> dict[str, bool]:
        """Find unrestricted Torgue witnesses without enumerating every UI state."""
        key = (
            str(root_id), str(composition_ref), str(fixed_barrel_ref or ""),
            str(base_element_ref if base_element_ref is not None else AUTO),
        )
        cached = self._unrestricted_torgue_cache.get(key)
        if cached is not None:
            return dict(cached)

        weapon = self.weapons[str(root_id)]
        composition = self._composition_for_mode(str(root_id), str(composition_ref), "unrestricted")
        pools = self._group_pool(str(root_id), str(composition_ref), "unrestricted")
        groups = {
            str(group).casefold(): rule
            for group, rule in (composition.get("groups") or {}).items()
        }
        for group, rule in groups.items():
            rule["allowed_part_refs"] = list(pools.get(group, ()))
        required: dict[str, set[str]] = {}
        if fixed_barrel_ref and "barrel" in groups:
            groups["barrel"]["allowed_part_refs"] = [str(fixed_barrel_ref)]
            groups["barrel"]["min"] = groups["barrel"]["max"] = 1
            required["barrel"] = {str(fixed_barrel_ref)}
        if base_element_ref not in (None, AUTO, NONE) and "body_ele" in groups:
            groups["body_ele"]["allowed_part_refs"] = [str(base_element_ref)]
            groups["body_ele"]["min"] = groups["body_ele"]["max"] = 1
            required["body_ele"] = {str(base_element_ref)}
        elif base_element_ref == NONE and "body_ele" in groups:
            groups["body_ele"]["min"] = groups["body_ele"]["max"] = 0

        ordered = _unique(str(group).casefold() for group in weapon.get("part_types", ()))
        ordered.extend(group for group in sorted(groups) if group not in ordered)
        ordered = [group for group in ordered if group in groups]
        tag_rules = [
            (frozenset(str(tag).casefold() for tag in rule.get("tags", ())), int(rule.get("max", 1)))
            for rule in composition.get("tag_rules", ())
        ]
        base_tags = {str(tag).casefold() for tag in composition.get("base_tags", ())}
        inherited_refs = [str(composition_ref), *map(str, composition.get("forced_part_refs", ()))]
        inherited = set().union(
            *(self._part_semantic_tags(ref) for ref in inherited_refs)
        ) if inherited_refs else set()
        inherited.update(set().union(*(
            self._part_semantic_tags(ref)
            for refs in required.values()
            for ref in refs
        )) if required else set())
        native_torgue = str(weapon.get("manufacturer") or "").casefold() == "torgue"

        def blocked_by_zero_rule(ref: str) -> bool:
            adds = self._part_selection_tags(ref)["adds"]
            return any(adds & bucket and limit <= 0 for bucket, limit in tag_rules)

        possible_before: dict[str, set[str]] = {}
        possible = set(base_tags)
        for group in ordered:
            possible_before[group] = set(possible)
            rule = groups[group]
            if int(rule.get("max", 0)) <= 0:
                continue
            refs = list(rule.get("allowed_part_refs", ()))
            changed = True
            while changed:
                changed = False
                for ref in refs:
                    tags = self._part_selection_tags(ref)
                    if blocked_by_zero_rule(ref) or not tags["requires"] <= possible:
                        continue
                    before = len(possible)
                    possible.update(tags["adds"])
                    changed = changed or len(possible) != before

        def feasible(group: str, ref: str) -> bool:
            tags = self._part_selection_tags(ref)
            return bool(
                not blocked_by_zero_rule(ref)
                and tags["requires"] <= possible_before.get(group, base_tags)
                and not tags["excludes"] & base_tags
            )

        reachable = {
            mode: bool(inherited & tags) or any(
                self._part_semantic_tags(ref) & tags and feasible(group, ref)
                for group in ordered
                for ref in groups[group].get("allowed_part_refs", ())
            )
            for mode, tags in TORGUE_TAGS.items()
        }
        if native_torgue:
            # Cross-manufacturer mode can replace ordinary group choices; only
            # a forced/fixed sticky semantic makes impact structurally impossible.
            reachable["impact"] = not bool(inherited & TORGUE_TAGS["sticky"])
        result = {mode: bool(reachable.get(mode)) for mode in ("sticky", "impact")}
        self._unrestricted_torgue_cache[key] = dict(result)
        return result

    def _group_pool(self, root_id: str, composition_ref: str, mode: str) -> dict[str, list[str]]:
        key = (f"{root_id}:{composition_ref}", mode)
        if key in self._pool_cache:
            return copy.deepcopy(self._pool_cache[key])
        weapon = self.weapons[str(root_id)]
        composition = weapon["compositions"][str(composition_ref)]
        pools = {
            str(group).casefold(): _unique(rule.get("allowed_part_refs", ()))
            for group, rule in (composition.get("groups") or {}).items()
        }
        if mode == "unrestricted":
            target_type = self._normalized_type(weapon)
            union: dict[str, list[str]] = {group: list(values) for group, values in pools.items()}
            for other in self.weapons.values():
                if self._normalized_type(other) != target_type:
                    continue
                for other_comp in (other.get("compositions") or {}).values():
                    if other_comp.get("availability") != "coregame" or other_comp.get("internal_only"):
                        continue
                    for group, rule in (other_comp.get("groups") or {}).items():
                        group = str(group).casefold()
                        if group not in union or group == "barrel":
                            continue
                        union[group].extend(map(str, rule.get("allowed_part_refs", ())))
            pools = {group: _unique(values) for group, values in union.items()}
            pools = {
                group: [
                    ref for ref in values
                    if not str((self.part_refs.get(ref) or {}).get("selection_group") or "")
                    or str((self.part_refs.get(ref) or {}).get("selection_group") or "").casefold() == group
                ]
                for group, values in pools.items()
            }
        pools = {
            group: [ref for ref in values if ref not in self.excluded_refs]
            for group, values in pools.items()
        }
        self._pool_cache[key] = copy.deepcopy(pools)
        return pools

    def composition_options(
        self,
        root_id: str,
        composition_ref: str,
        mode: str = "legal",
        *,
        fixed_barrel_ref: str | None = None,
        base_element_ref: str | None = AUTO,
    ) -> dict[str, Any]:
        weapon = self.weapons[str(root_id)]
        composition = weapon["compositions"][str(composition_ref)]
        pools = self._group_pool(str(root_id), str(composition_ref), mode)
        if mode == "unrestricted":
            capabilities = {
                **{group: set() for group in ELEMENT_GROUPS},
                "element_none_legal": {group: True for group in ELEMENT_GROUPS},
                "torgue_modes": self._unrestricted_torgue_modes(
                    str(root_id), str(composition_ref),
                    fixed_barrel_ref=fixed_barrel_ref,
                    base_element_ref=base_element_ref,
                ),
            }
        else:
            capabilities = self._legal_capabilities(
                str(root_id),
                str(composition_ref),
                mode=mode,
                fixed_barrel_ref=fixed_barrel_ref,
                base_element_ref=base_element_ref,
            )
        validation_groups = (self._composition_validation(str(root_id), str(composition_ref)).get("groups") or {})
        groups: dict[str, Any] = {}
        target_type = self._normalized_type(weapon)
        observed_max: dict[str, int] = {}
        for other in self.weapons.values():
            if self._normalized_type(other) != target_type:
                continue
            for other_comp in (other.get("compositions") or {}).values():
                if other_comp.get("availability") != "coregame" or other_comp.get("internal_only"):
                    continue
                for group, rule in (other_comp.get("groups") or {}).items():
                    group = str(group).casefold()
                    observed_max[group] = max(observed_max.get(group, 0), int(rule.get("max", 1)))
        for group, rule in (composition.get("groups") or {}).items():
            group = str(group).casefold()
            validation_group = validation_groups.get(group) or {}
            conditional = bool(validation_group.get("activation_tags")) or not bool(
                validation_group.get("initial_eligible_refs")
            )
            groups[group] = {
                "min": 0 if conditional else int(rule.get("min", 1)),
                "max": int(rule.get("max", 1)),
                "hard_max": max(int(rule.get("max", 1)), observed_max.get(group, 0)),
                "pool_size": len(pools.get(group, ())),
            }
        base_tags = {str(tag).casefold() for tag in composition.get("base_tags", ())}

        def element_options(group: str) -> list[dict[str, Any]]:
            native_rule = (composition.get("groups") or {}).get(group)
            native_refs = set(capabilities.get(group, ())) if native_rule is not None else set()
            if native_rule is None or int(native_rule.get("max", 0)) <= 0:
                native_refs.clear()
            if group == "pearl_elem" and "pearlescent" not in base_tags:
                native_refs.clear()
            global_refs = _unique(
                ref for ref, row in self.part_refs.items()
                if str(row.get("selection_group") or "").casefold() == group
                and str(ref).startswith("1:")
                and ref not in self.excluded_refs
            )
            refs = _unique([*pools.get(group, ()), *global_refs])
            return self._part_options(
                refs,
                legal_refs=refs if mode == "unrestricted" else native_refs,
            )

        none_legal = (
            {group: True for group in ELEMENT_GROUPS}
            if mode == "unrestricted"
            else dict(capabilities.get("element_none_legal") or {})
        )
        legal_barrels = self._legal_barrels(str(root_id), str(composition_ref))
        return {
            "barrels": self._part_options(legal_barrels),
            "body_elements": element_options("body_ele"),
            "secondary_elements": element_options("secondary_ele"),
            "pearl_elements": element_options("pearl_elem"),
            "element_none_legal": none_legal,
            "torgue_modes": dict(capabilities["torgue_modes"]),
            "groups": groups,
        }

    def _legal_barrels(self, root_id: str, composition_ref: str) -> list[str]:
        validation = self._composition_validation(root_id, composition_ref)
        barrel = (validation.get("groups") or {}).get("barrel") or {}
        refs = barrel.get("initial_eligible_refs") or barrel.get("eligible_refs") or ()
        return _unique(refs)

    def barrel_options(self, root_id: str, composition_ref: str) -> list[dict[str, Any]]:
        return self._part_options(self._legal_barrels(str(root_id), str(composition_ref)))

    def _composition_validation(self, root_id: str, composition_ref: str) -> dict[str, Any]:
        token = self._serial_token(composition_ref, root_id)
        decoded = f"{root_id}, 0, 1, 60| 2, 1|| {token} |"
        return item_display_resolver.validate_weapon_generation(decoded)

    def _part_options(
        self,
        refs: Iterable[str],
        *,
        legal_refs: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        legal = set(map(str, legal_refs)) if legal_refs is not None else None
        return [
            {"ref": ref, "label": self.part_label(ref), "legal": legal is None or ref in legal}
            for ref in _unique(refs)
        ]

    @staticmethod
    def _serial_token(ref: str, root_id: str) -> str:
        ref_root, separator, part_id = str(ref).partition(":")
        if not separator:
            part_id = ref_root
            ref_root = str(root_id)
        return f"{{{part_id}}}" if ref_root == str(root_id) else f"{{{ref_root}:{part_id}}}"

    def _decoded(self, request: GodRollRequest, selected: Iterable[str], seed: int) -> str:
        refs = [request.composition_ref, *selected]
        components = " ".join(self._serial_token(ref, request.root_id) for ref in refs)
        return f"{request.root_id}, 0, 1, {int(request.level)}| 2, {int(seed)}|| {components} |"

    def _synthetic_composition(self, request: GodRollRequest) -> tuple[dict[str, Any], dict[str, set[str]], list[str]]:
        weapon = self.weapons[str(request.root_id)]
        composition = self._composition_for_mode(
            request.root_id, request.composition_ref, request.mode
        )
        pools = self._group_pool(request.root_id, request.composition_ref, request.mode)
        option_data = self.composition_options(
            request.root_id,
            request.composition_ref,
            request.mode,
            fixed_barrel_ref=request.fixed_barrel_ref,
            base_element_ref=request.base_element_ref,
        )
        option_groups = option_data["groups"]
        legal_element_refs = {
            "body_ele": {row["ref"] for row in option_data["body_elements"] if row.get("legal")},
            "secondary_ele": {row["ref"] for row in option_data["secondary_elements"] if row.get("legal")},
            "pearl_elem": {row["ref"] for row in option_data["pearl_elements"] if row.get("legal")},
        }
        required: dict[str, set[str]] = {}
        forced_elements: list[str] = []
        groups = composition.get("groups") or {}
        if (
            request.mode == "legal"
            and request.torgue_mode in TORGUE_TAGS
            and not option_data["torgue_modes"].get(request.torgue_mode)
        ):
            raise ValueError("selected Torgue mode is not legal for this weapon")
        for group, rule in groups.items():
            group_key = str(group).casefold()
            rule["allowed_part_refs"] = list(pools.get(group_key, ()))
            if request.mode == "unrestricted" and group_key in request.group_limits:
                minimum, maximum = request.group_limits[group_key]
                hard_max = int((option_groups.get(group_key) or {}).get("hard_max", rule.get("max", 1)))
                rule["min"] = max(0, min(int(minimum), hard_max))
                rule["max"] = max(int(rule["min"]), min(int(maximum), hard_max))

        if request.fixed_barrel_ref:
            barrel = groups.get("barrel")
            if barrel is None:
                raise ValueError("selected composition has no barrel group")
            if request.fixed_barrel_ref not in self._legal_barrels(request.root_id, request.composition_ref):
                raise ValueError("selected barrel does not belong to the target composition")
            barrel["allowed_part_refs"] = [request.fixed_barrel_ref]
            barrel["min"] = barrel["max"] = 1

        selections = {
            "body_ele": request.base_element_ref,
            "secondary_ele": request.secondary_element_ref,
            "pearl_elem": request.pearl_element_ref,
        }
        for group, selection in selections.items():
            if selection in (None, AUTO):
                continue
            rule = groups.get(group)
            allowed = pools.get(group, ())
            if selection == NONE:
                if rule is not None:
                    rule["min"] = rule["max"] = 0
                continue
            if (
                rule is not None
                and selection in allowed
                and selection in legal_element_refs[group]
                and int(rule.get("max", 0)) > 0
            ):
                rule["allowed_part_refs"] = [str(selection)]
                rule["min"] = rule["max"] = 1
                required[group] = {str(selection)}
                continue
            if not request.allow_illegal_elements:
                raise ValueError(f"{group} selection is not legal for this composition")
            if rule is not None:
                rule["min"] = rule["max"] = 0
            forced_elements.append(str(selection))
        return composition, required, forced_elements

    def _sample_group(
        self,
        rule: Mapping[str, Any],
        active: set[str],
        tag_rules: list[tuple[set[str], int]],
        counts: list[int],
        required: set[str],
        rng: random.Random,
    ) -> list[str] | None:
        allowed = [ref for ref in _unique(rule.get("allowed_part_refs", ())) if ref not in self.excluded_refs]
        tags = {ref: self._part_selection_tags(ref) for ref in allowed}

        def can_pick(ref: str) -> bool:
            row = tags[ref]
            if not row["requires"] <= active or row["excludes"] & active:
                return False
            return not any(row["adds"] & bucket and counts[index] >= limit for index, (bucket, limit) in enumerate(tag_rules))

        pool = [ref for ref in allowed if can_pick(ref)]
        target = _target_count(rule, rng, len(required))
        selected: list[str] = []

        def accept(ref: str) -> None:
            selected.append(ref)
            adds = tags[ref]["adds"]
            active.update(adds)
            for index, (bucket, _limit) in enumerate(tag_rules):
                counts[index] += bool(adds & bucket)

        for ref in sorted(required):
            if ref not in pool or not can_pick(ref):
                return None
            pool.remove(ref)
            accept(ref)
            pool[:] = [candidate for candidate in pool if can_pick(candidate)]
        while len(selected) < target and pool:
            ref = rng.choice(pool)
            pool.remove(ref)
            accept(ref)
            pool[:] = [candidate for candidate in pool if can_pick(candidate)]
        return selected

    def _torgue_matches_parts(
        self,
        root_id: str,
        composition_ref: str,
        composition: Mapping[str, Any],
        selected: Iterable[str],
        mode: str,
    ) -> bool:
        if mode not in TORGUE_TAGS:
            return True
        refs = [str(composition_ref), *map(str, composition.get("forced_part_refs", ())), *map(str, selected)]
        tags = set().union(*(self._part_semantic_tags(ref) for ref in refs)) if refs else set()
        native_torgue = str(self.weapons[str(root_id)].get("manufacturer") or "").casefold() == "torgue"
        has_sticky = bool(tags & TORGUE_TAGS["sticky"])
        if native_torgue:
            return has_sticky if mode == "sticky" else not has_sticky
        return bool(tags & TORGUE_TAGS[mode])

    def _sample_parts(
        self,
        request: GodRollRequest,
        composition: Mapping[str, Any],
        fixed_required: Mapping[str, set[str]],
        rng: random.Random,
    ) -> list[str] | None:
        weapon = self.weapons[str(request.root_id)]
        groups = {str(group).casefold(): rule for group, rule in (composition.get("groups") or {}).items()}
        ordered = _unique(str(group).casefold() for group in weapon.get("part_types", ()))
        ordered.extend(group for group in sorted(groups) if group not in ordered)
        tag_rules = [
            ({str(tag).casefold() for tag in rule.get("tags", ())}, int(rule.get("max", 1)))
            for rule in composition.get("tag_rules", ())
        ]
        active = {str(tag).casefold() for tag in composition.get("base_tags", ())}
        counts = [0] * len(tag_rules)
        required = {group: set(refs) for group, refs in fixed_required.items()}

        native_torgue_impact = (
            request.torgue_mode == "impact"
            and str(weapon.get("manufacturer") or "").casefold() == "torgue"
        )
        if request.torgue_mode in TORGUE_TAGS and not native_torgue_impact:
            tags_needed = TORGUE_TAGS[request.torgue_mode]
            inherited = [request.composition_ref, *composition.get("forced_part_refs", ())]
            if not any(self._part_semantic_tags(ref) & tags_needed for ref in inherited):
                choices = [
                    (group, ref)
                    for group, rule in groups.items()
                    for ref in rule.get("allowed_part_refs", ())
                    if self._part_semantic_tags(ref) & tags_needed
                ]
                if not choices:
                    return None
                group, ref = rng.choice(choices)
                required.setdefault(group, set()).add(ref)

        selected: list[str] = []
        for group in ordered:
            rule = groups.get(group)
            if not rule:
                continue
            picked = self._sample_group(rule, active, tag_rules, counts, required.get(group, set()), rng)
            if picked is None:
                return None
            selected.extend(picked)
        if not self._torgue_matches_parts(
            request.root_id,
            request.composition_ref,
            composition,
            selected,
            request.torgue_mode,
        ):
            return None
        return selected

    def _enumerate_group_choices(
        self,
        rule: Mapping[str, Any],
        active_before: frozenset[str],
        tag_rules: list[tuple[frozenset[str], int]],
        counts_before: tuple[int, ...],
        required: frozenset[str],
        should_stop: Callable[[], bool],
    ):
        allowed = tuple(ref for ref in _unique(rule.get("allowed_part_refs", ())) if ref not in self.excluded_refs)
        tags = {ref: self._part_selection_tags(ref) for ref in allowed}

        def can_pick(ref: str, active: frozenset[str], counts: tuple[int, ...]) -> bool:
            row = tags[ref]
            if not row["requires"] <= active or row["excludes"] & active:
                return False
            return not any(
                row["adds"] & bucket and counts[index] >= limit
                for index, (bucket, limit) in enumerate(tag_rules)
            )

        initial_pool = tuple(ref for ref in allowed if can_pick(ref, active_before, counts_before))
        emitted: set[tuple[tuple[str, ...], frozenset[str], tuple[int, ...]]] = set()
        order_sensitive = int(rule.get("max", 1)) > 1 and any(
            self._part_order_sensitive(ref) for ref in allowed
        )
        group_adds = set().union(*(row["adds"] for row in tags.values())) if tags else set()
        group_conditions = set().union(*(
            row["requires"] | row["excludes"] for row in tags.values()
        )) if tags else set()
        combination_safe = not order_sensitive and not bool(group_adds & group_conditions)
        allowed_order = {ref: index for index, ref in enumerate(allowed)}

        def walk(
            selected: tuple[str, ...],
            pool: tuple[str, ...],
            active: frozenset[str],
            counts: tuple[int, ...],
            target: int,
        ):
            if should_stop():
                return
            if len(selected) >= target or not pool:
                if required <= set(selected):
                    output_selected = selected if order_sensitive else tuple(
                        sorted(selected, key=allowed_order.__getitem__)
                    )
                    row = (output_selected, active, counts)
                    if row not in emitted:
                        emitted.add(row)
                        yield row
                return
            missing = len(required - set(selected))
            if missing > target - len(selected):
                return
            for position, ref in enumerate(pool):
                if should_stop():
                    return
                row = tags[ref]
                next_active_set = set(active)
                next_active_set.update(row["adds"])
                next_active = frozenset(next_active_set)
                next_counts = list(counts)
                for index, (bucket, _limit) in enumerate(tag_rules):
                    next_counts[index] += bool(row["adds"] & bucket)
                next_counts_tuple = tuple(next_counts)
                candidates = pool[position + 1:] if combination_safe else tuple(
                    candidate for candidate in pool if candidate != ref
                )
                remaining = tuple(
                    candidate for candidate in candidates
                    if can_pick(candidate, next_active, next_counts_tuple)
                )
                yield from walk(
                    (*selected, ref), remaining, next_active, next_counts_tuple, target
                )

        for target in _target_counts(rule):
            if len(required) <= target:
                yield from walk((), initial_pool, active_before, counts_before, target)

    def _enumerate_legal_parts(
        self,
        request: GodRollRequest,
        composition: Mapping[str, Any],
        fixed_required: Mapping[str, set[str]],
        should_stop: Callable[[], bool],
    ):
        weapon = self.weapons[str(request.root_id)]
        groups = {str(group).casefold(): rule for group, rule in (composition.get("groups") or {}).items()}
        ordered = _unique(str(group).casefold() for group in weapon.get("part_types", ()))
        ordered.extend(group for group in sorted(groups) if group not in ordered)
        ordered = [group for group in ordered if group in groups]
        tag_rules = [
            (frozenset(str(tag).casefold() for tag in rule.get("tags", ())), int(rule.get("max", 1)))
            for rule in composition.get("tag_rules", ())
        ]
        active = frozenset(str(tag).casefold() for tag in composition.get("base_tags", ()))
        counts = tuple(0 for _ in tag_rules)

        def walk(index: int, active_now: frozenset[str], counts_now: tuple[int, ...], selected: tuple[str, ...]):
            if should_stop():
                return
            if index >= len(ordered):
                yield list(selected)
                return
            group = ordered[index]
            required = frozenset(fixed_required.get(group, set()))
            for picked, next_active, next_counts in self._enumerate_group_choices(
                groups[group], active_now, tag_rules, counts_now, required, should_stop
            ):
                if should_stop():
                    return
                yield from walk(index + 1, next_active, next_counts, (*selected, *picked))

        yield from walk(0, active, counts, ())

    @staticmethod
    def _element_only(validation: Mapping[str, Any]) -> bool:
        violations = list(validation.get("violations") or ())
        if not violations:
            return False
        for row in violations:
            group = str(row.get("group") or "").casefold()
            part = str(row.get("part") or "")
            parts = [ref for ref in [part, *map(str, row.get("parts") or ())] if ref]
            if group in ELEMENT_GROUPS:
                continue
            if parts and all(ref.startswith("1:") for ref in parts):
                continue
            return False
        return True

    def _element_text(self, refs: Iterable[str]) -> str:
        labels: list[str] = []
        for ref in refs:
            row = self.part_refs.get(str(ref)) or {}
            if str(row.get("selection_group") or "").casefold() not in ELEMENT_GROUPS:
                continue
            label = self.part_label(ref).replace("part_", "").replace("pearl_", "Pearl ").replace("_", " ")
            if label and label not in labels:
                labels.append(label.title())
        return " / ".join(labels)

    def _candidate(
        self,
        request: GodRollRequest,
        selected: list[str],
        forced_elements: list[str],
        seed: int,
        language: str,
        *,
        final_refs: list[str] | None = None,
        decoded: str | None = None,
        stats: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        final_refs = list(final_refs) if final_refs is not None else self._final_refs(
            request, selected, forced_elements
        )
        if final_refs is None:
            return None
        decoded = decoded or self._decoded(request, final_refs, seed)
        validation = item_display_resolver.validate_weapon_generation(decoded)
        status = str(validation.get("status") or "unknown")
        forced_element_request = bool(forced_elements) or (
            request.allow_illegal_elements
            and any(selection == NONE for selection in (
                request.base_element_ref,
                request.secondary_element_ref,
                request.pearl_element_ref,
            ))
        )
        element_only = forced_element_request and self._element_only(validation)
        if request.mode == "legal" and status != "legal" and not (request.allow_illegal_elements and element_only):
            return None
        if request.mode == "unrestricted" and status not in {"legal", "modified"}:
            return None
        stats = dict(stats or item_display_resolver.resolve_weapon_stats(decoded))
        dps = stats.get("dps")
        if dps is None:
            return None
        serial, error = b_encoder.encode_to_base85(decoded)
        if error or not serial:
            return None
        weapon = self.weapons[str(request.root_id)]
        composition = weapon["compositions"][str(request.composition_ref)]
        names = composition.get("name") or {}
        preferred_name = names.get("zh") if language == "zh-CN" else names.get("en")
        name = str(preferred_name or names.get("en") or names.get("zh") or composition.get("part") or "—")
        rarity = str(composition.get("rarity") or "")
        formatted = {
            key: item_display_resolver.format_weapon_stat(key, stats.get(key), language) or "—"
            for key in item_display_resolver.WEAPON_STAT_KEYS
        }
        status_label = "Legal" if status == "legal" else ("Element-only Modified" if element_only else "Modified")
        semantic_refs = [
            str(request.composition_ref),
            *map(str, composition.get("forced_part_refs", ())),
            *map(str, final_refs),
        ]
        semantic_tags = set().union(
            *(self._part_semantic_tags(ref) for ref in semantic_refs)
        ) if semantic_refs else set()
        has_sticky = bool(semantic_tags & TORGUE_TAGS["sticky"])
        native_torgue = str(weapon.get("manufacturer") or "").casefold() == "torgue"
        torgue_label = "Sticky" if has_sticky else (
            "Impact" if native_torgue or semantic_tags & TORGUE_TAGS["impact"] else ""
        )
        important_groups = {
            "body_acc", "barrel_acc", "magazine", "magazine_acc", "grip",
            "foregrip", "underbarrel", "underbarrel_acc", "secondary_ele", "pearl_elem",
        }
        important = [
            self.part_label(ref).replace("part_", "").replace("_", " ")
            for ref in final_refs
            if str((self.part_refs.get(ref) or {}).get("selection_group") or "").casefold() in important_groups
        ]
        variant_bits = [value for value in (torgue_label, *important[:4]) if value]
        variant_summary = " · ".join(variant_bits)
        tooltip_lines = [name, f"DPS: {formatted.get('dps')}", status_label]
        for violation in validation.get("violations", ()):
            detail = violation.get("group") or violation.get("part") or ", ".join(map(str, violation.get("parts") or ()))
            tooltip_lines.append(f"{violation.get('code')}: {detail}" if detail else str(violation.get("code")))
        tooltip_lines.extend(f"{ref} · {self.part_label(ref)}" for ref in final_refs)
        tooltip_lines.append(f"Base85: {serial}")
        return {
            "serial": serial,
            "decoded": decoded,
            "selected_refs": list(final_refs),
            "root_id": str(request.root_id),
            "composition_ref": str(request.composition_ref),
            "level": int(request.level),
            "name": name,
            "manufacturer": str(weapon.get("manufacturer") or ""),
            "manufacturer_key": str(weapon.get("manufacturer") or ""),
            "weapon_type": self._normalized_type(weapon),
            "weapon_type_key": self._normalized_type(weapon),
            "rarity": rarity,
            "rarity_key": rarity,
            "element": self._element_text(final_refs),
            "status": status,
            "status_label": status_label,
            "variant_summary": variant_summary,
            "torgue_mode": torgue_label.casefold() if torgue_label else "none",
            "element_only_modified": element_only,
            "violations": list(validation.get("violations") or ()),
            "stats": stats,
            "formatted_stats": formatted,
            "tooltip": "\n".join(tooltip_lines),
        }

    def _final_refs(
        self,
        request: GodRollRequest,
        selected: Iterable[str],
        forced_elements: Iterable[str],
    ) -> list[str] | None:
        final_refs = [ref for ref in selected if str((self.part_refs.get(ref) or {}).get("selection_group") or "").casefold() not in {
            group for group, selection in {
                "body_ele": request.base_element_ref,
                "secondary_ele": request.secondary_element_ref,
                "pearl_elem": request.pearl_element_ref,
            }.items() if selection == NONE
        }]
        final_refs.extend(forced_elements)
        if request.mode == "unrestricted" and request.group_limits:
            counts: dict[str, int] = {}
            for ref in final_refs:
                group = str((self.part_refs.get(str(ref)) or {}).get("selection_group") or "").casefold()
                counts[group] = counts.get(group, 0) + 1
            if any(
                not int(minimum) <= counts.get(str(group).casefold(), 0) <= int(maximum)
                for group, (minimum, maximum) in request.group_limits.items()
            ):
                return None
        return final_refs

    def search(
        self,
        request: GodRollRequest,
        *,
        language: str = "zh-CN",
        cancelled: Callable[[], bool] | None = None,
        progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        if request.mode not in {"legal", "unrestricted"}:
            raise ValueError("mode must be legal or unrestricted")
        if str(request.root_id) not in self.weapons:
            raise ValueError("unknown weapon root")
        weapon = self.weapons[str(request.root_id)]
        if str(request.composition_ref) not in (weapon.get("compositions") or {}):
            raise ValueError("unknown weapon composition")
        cache_key = (
            request.root_id, request.composition_ref, int(request.level), request.mode,
            request.fixed_barrel_ref, request.torgue_mode, request.base_element_ref,
            request.secondary_element_ref, request.pearl_element_ref,
            bool(request.allow_illegal_elements),
            tuple(sorted((str(group), int(bounds[0]), int(bounds[1])) for group, bounds in request.group_limits.items())),
            int(request.top_n), str(language),
        )
        cached = self._search_cache.get(cache_key)
        if cached is not None:
            result = copy.deepcopy(cached)
            result["elapsed"] = 0.0
            result["cached"] = True
            return result
        composition, required, forced_elements = self._synthetic_composition(request)
        rng = random.Random(request.seed)
        start = time.perf_counter()
        deadline = start + max(0.1, float(request.time_limit))
        max_samples = max(1, int(request.max_samples))
        top_n = max(1, min(50, int(request.top_n)))
        heap: list[tuple[float, int, dict[str, Any]]] = []
        seen: set[tuple[str, ...]] = set()
        attempted = accepted = rejected = 0
        exact_examined = 0

        def stopped() -> bool:
            return (
                attempted >= max_samples
                or time.perf_counter() >= deadline
                or bool(cancelled is not None and cancelled())
            )

        def torgue_matches(selected: Iterable[str]) -> bool:
            return self._torgue_matches_parts(
                request.root_id,
                request.composition_ref,
                composition,
                selected,
                request.torgue_mode,
            )

        def consider(selected: list[str]) -> None:
            nonlocal attempted, accepted, rejected
            attempted += 1
            if not torgue_matches(selected):
                rejected += 1
                return
            final_refs = self._final_refs(request, selected, forced_elements)
            build_key = tuple(final_refs or ())
            if final_refs is None or build_key in seen:
                rejected += 1
                return
            seen.add(build_key)
            seed = rng.randint(100, 9999)
            decoded = self._decoded(request, final_refs, seed)
            stats = item_display_resolver.resolve_weapon_stats(decoded)
            if stats.get("dps") is None:
                rejected += 1
                return
            accepted += 1
            score = float(stats["dps"])
            if len(heap) >= top_n and score <= heap[0][0]:
                return
            candidate = self._candidate(
                request, selected, forced_elements, seed, language,
                final_refs=final_refs, decoded=decoded, stats=stats,
            )
            if candidate is None:
                rejected += 1
                return
            row = (score, attempted, candidate)
            if len(heap) < top_n:
                heapq.heappush(heap, row)
            elif score > heap[0][0]:
                heapq.heapreplace(heap, row)
            if progress is not None and (attempted == 1 or attempted % 250 == 0):
                progress({
                    "attempted": attempted,
                    "accepted": accepted,
                    "rejected": rejected,
                    "best_dps": max((item[0] for item in heap), default=0.0),
                    "elapsed": time.perf_counter() - start,
                })

        # Warm the Top-K heap so a large legal frontier still yields useful
        # results before the exact traversal reaches its deadline.
        warm_limit = min(1_000, max(0, max_samples // 10))
        warm_deadline = min(deadline, start + min(0.75, max(0.1, request.time_limit * 0.15)))
        while attempted < warm_limit and time.perf_counter() < warm_deadline:
            if cancelled is not None and cancelled():
                break
            selected = self._sample_parts(request, composition, required, rng)
            if selected is None:
                attempted += 1
                rejected += 1
                continue
            consider(selected)

        complete = False
        if request.mode == "legal" and not stopped():
            complete = True
            for selected in self._enumerate_legal_parts(request, composition, required, stopped):
                if stopped():
                    complete = False
                    break
                exact_examined += 1
                consider(selected)
            if stopped():
                complete = False
        else:
            while not stopped():
                selected = self._sample_parts(request, composition, required, rng)
                if selected is None:
                    attempted += 1
                    rejected += 1
                    continue
                consider(selected)

        results = [row[2] for row in sorted(heap, key=lambda item: (-item[0], item[1]))]
        for index, candidate in enumerate(results, 1):
            candidate["rank"] = index
        elapsed = time.perf_counter() - start
        result = {
            "results": results,
            "attempted": attempted,
            "exact_examined": exact_examined,
            "accepted": accepted,
            "rejected": rejected,
            "elapsed": elapsed,
            "cancelled": bool(cancelled is not None and cancelled()),
            "complete": complete,
            "search_kind": "exact_legal" if complete else "budgeted_anytime",
            "mode": request.mode,
        }
        if complete:
            self._search_cache[cache_key] = copy.deepcopy(result)
        return result
