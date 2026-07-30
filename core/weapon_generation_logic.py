from __future__ import annotations

import random
from collections.abc import Callable, Iterable, Mapping, Sequence
from functools import lru_cache
from typing import Any


def _target_counts(minimum: int, maximum: int, chance: Any) -> tuple[int, ...]:
    minimum, maximum = max(0, int(minimum)), max(0, int(maximum))
    if maximum < minimum:
        maximum = minimum
    if maximum == minimum:
        return (minimum,)
    try:
        chance = float(chance)
    except (TypeError, ValueError):
        return tuple(range(minimum, maximum + 1))
    if chance <= 0:
        return (minimum,)
    if chance >= 1:
        return (maximum,)
    return tuple(range(minimum, maximum + 1))


def sample_group_selection(
    *,
    allowed_refs: Sequence[str],
    tags_for_ref: Callable[[str], Mapping[str, Iterable[str]]],
    base_tags: Iterable[str],
    tag_rules: Sequence[Mapping[str, Any]],
    base_tag_counts: Sequence[int],
    minimum: int,
    maximum: int,
    additional_chance: Any = None,
    excluded_refs: Iterable[str] = (),
    candidate_predicate: Callable[[str], bool] | None = None,
    rng: Any = None,
) -> list[str]:
    """Sample one native part-type slot and return the selected part refs."""
    rng = random if rng is None else rng
    minimum, maximum = max(0, int(minimum)), max(0, int(maximum))
    if maximum < minimum:
        maximum = minimum

    target = minimum
    chance = 0.5 if additional_chance is None else float(additional_chance)
    while target < maximum:
        if chance < float(rng.random()):
            break
        target += 1

    allowed = list(dict.fromkeys(map(str, allowed_refs)))
    excluded = set(map(str, excluded_refs))
    candidate_tags = {
        ref: {
            key: {str(value).casefold() for value in tags_for_ref(ref).get(key, ())}
            for key in ("adds", "requires", "excludes")
        }
        for ref in allowed
    }
    normalized_rules = [
        ({str(tag).casefold() for tag in rule.get("tags", ())}, int(rule.get("max", 1)))
        for rule in tag_rules
    ]
    active = {str(tag).casefold() for tag in base_tags}
    counts = [
        int(base_tag_counts[index]) if index < len(base_tag_counts) else 0
        for index in range(len(normalized_rules))
    ]

    def tag_allowed(ref: str) -> bool:
        tags = candidate_tags[ref]
        if not tags["requires"] <= active or tags["excludes"] & active:
            return False
        return not any(
            tags["adds"] & bucket and counts[index] >= limit
            for index, (bucket, limit) in enumerate(normalized_rules)
        )

    pool = [
        ref
        for ref in allowed
        if ref not in excluded
        and (candidate_predicate is None or candidate_predicate(ref))
        and tag_allowed(ref)
    ]
    selected: list[str] = []
    while len(selected) < target and pool:
        ref = str(rng.choice(pool))
        pool.remove(ref)
        selected.append(ref)
        adds = candidate_tags[ref]["adds"]
        active.update(adds)
        for index, (bucket, _limit) in enumerate(normalized_rules):
            counts[index] += bool(adds & bucket)
        pool = [candidate for candidate in pool if tag_allowed(candidate)]
    return selected


def sample_composition_parts(
    *,
    composition: Mapping[str, Any],
    part_types: Sequence[str],
    tags_for_ref: Callable[[str], Mapping[str, Iterable[str]]],
    excluded_refs: Iterable[str] = (),
    candidate_predicate: Callable[[str], bool] | None = None,
    rng: Any = None,
) -> list[str]:
    """Sample every group in native order and return a legal composition part set."""
    rng = random if rng is None else rng
    groups = {str(group).casefold(): rule for group, rule in (composition.get("groups") or {}).items()}
    ordered_groups = list(dict.fromkeys(str(group).casefold() for group in part_types))
    ordered_groups.extend(sorted(set(groups) - set(ordered_groups)))
    tag_rules = list(composition.get("tag_rules") or [])
    normalized_rules = [
        ({str(tag).casefold() for tag in rule.get("tags", ())}, int(rule.get("max", 1)))
        for rule in tag_rules
    ]
    active_tags = {str(tag).casefold() for tag in composition.get("base_tags", ())}
    tag_counts = [0] * len(normalized_rules)
    selected: list[str] = []
    unavailable = set(map(str, excluded_refs))

    for group in ordered_groups:
        rule = groups.get(group)
        if not rule:
            continue
        picked = sample_group_selection(
            allowed_refs=rule.get("allowed_part_refs", ()),
            tags_for_ref=tags_for_ref,
            base_tags=active_tags,
            tag_rules=tag_rules,
            base_tag_counts=tag_counts,
            minimum=rule.get("min", 1),
            maximum=rule.get("max", 1),
            additional_chance=rule.get("additional_chance"),
            excluded_refs=unavailable | set(selected),
            candidate_predicate=candidate_predicate,
            rng=rng,
        )
        selected.extend(picked)
        for ref in picked:
            adds = {str(tag).casefold() for tag in tags_for_ref(ref).get("adds", ())}
            active_tags.update(adds)
            for index, (bucket, _limit) in enumerate(normalized_rules):
                tag_counts[index] += bool(adds & bucket)
    return selected


def evaluate_group_selection(
    *,
    allowed_refs: Sequence[str],
    selected_refs: Sequence[str],
    tags_for_ref: Callable[[str], Mapping[str, Iterable[str]]],
    base_tags: Iterable[str],
    tag_rules: Sequence[Mapping[str, Any]],
    base_tag_counts: Sequence[int],
    minimum: int,
    maximum: int,
    additional_chance: Any = None,
) -> dict[str, Any]:
    """Evaluate one native part-type slot using the game's shrink-only pool loop."""
    allowed = list(dict.fromkeys(map(str, allowed_refs)))
    selected = list(map(str, selected_refs))
    selected_unique = list(dict.fromkeys(selected))
    ref_indexes = {ref: index for index, ref in enumerate(allowed)}
    candidate_tags = {
        ref: {
            key: {str(value).casefold() for value in tags_for_ref(ref).get(key, ())}
            for key in ("adds", "requires", "excludes")
        }
        for ref in allowed
    }
    normalized_rules = [
        ({str(tag).casefold() for tag in rule.get("tags", ())}, int(rule.get("max", 1)))
        for rule in tag_rules
    ]
    base_active = frozenset(str(tag).casefold() for tag in base_tags)
    base_counts = tuple(
        int(base_tag_counts[index]) if index < len(base_tag_counts) else 0
        for index in range(len(normalized_rules))
    )

    @lru_cache(maxsize=None)
    def state(mask: int) -> tuple[frozenset[str], tuple[int, ...]]:
        active = set(base_active)
        counts = list(base_counts)
        for index, ref in enumerate(allowed):
            if not mask & (1 << index):
                continue
            adds = candidate_tags[ref]["adds"]
            active.update(adds)
            for rule_index, (bucket, _maximum) in enumerate(normalized_rules):
                counts[rule_index] += bool(adds & bucket)
        return frozenset(active), tuple(counts)

    def candidate_allowed(index: int, active: frozenset[str], counts: tuple[int, ...]) -> bool:
        tags = candidate_tags[allowed[index]]
        if not tags["requires"] <= active or tags["excludes"] & active:
            return False
        return not any(
            tags["adds"] & bucket and counts[rule_index] >= limit
            for rule_index, (bucket, limit) in enumerate(normalized_rules)
        )

    initial_pool = 0
    for index in range(len(allowed)):
        if candidate_allowed(index, base_active, base_counts):
            initial_pool |= 1 << index

    reachable_masks: set[int] = set()
    terminal_masks: set[int] = set()
    targets = _target_counts(minimum, maximum, additional_chance)
    for target in targets:
        stack = [(0, initial_pool)]
        visited: set[tuple[int, int]] = set()
        while stack:
            mask, pool = stack.pop()
            if (mask, pool) in visited:
                continue
            visited.add((mask, pool))
            reachable_masks.add(mask)
            if mask.bit_count() >= target or pool == 0:
                terminal_masks.add(mask)
                continue
            remaining = pool
            while remaining:
                bit = remaining & -remaining
                remaining ^= bit
                index = bit.bit_length() - 1
                next_mask = mask | bit
                active, counts = state(next_mask)
                next_pool = pool & ~bit
                filtered_pool = 0
                pending = next_pool
                while pending:
                    candidate_bit = pending & -pending
                    pending ^= candidate_bit
                    candidate_index = candidate_bit.bit_length() - 1
                    if candidate_allowed(candidate_index, active, counts):
                        filtered_pool |= candidate_bit
                stack.append((next_mask, filtered_pool))

    selected_valid = len(selected) == len(selected_unique) and all(ref in ref_indexes for ref in selected_unique)
    selected_set = set(selected_unique)
    selected_mask = sum(1 << ref_indexes[ref] for ref in selected_unique if ref in ref_indexes)
    selected_reachable = selected_valid and selected_mask in reachable_masks
    selected_terminal = selected_valid and selected_mask in terminal_masks
    terminal_supersets = [
        mask for mask in terminal_masks
        if selected_reachable and mask & selected_mask == selected_mask
    ]
    terminal_counts = sorted({mask.bit_count() for mask in terminal_supersets})
    effective_min = terminal_counts[0] if terminal_counts else int(minimum)
    effective_max = terminal_counts[-1] if terminal_counts else int(maximum)

    eligible_refs: list[str] = []
    if selected_reachable:
        for index, ref in enumerate(allowed):
            if ref in selected_set or selected_mask | (1 << index) in reachable_masks:
                eligible_refs.append(ref)
    remaining_eligible = [ref for ref in eligible_refs if ref not in selected_set]

    _, selected_counts = state(selected_mask)
    selected_tag_limit_exceeded = any(
        selected_counts[rule_index] > limit
        and any(
            ref in candidate_tags and candidate_tags[ref]["adds"] & bucket
            for ref in selected_unique
        )
        for rule_index, (bucket, limit) in enumerate(normalized_rules)
    )
    tag_limited = [
        ref
        for ref in allowed
        if ref not in selected_set
        and any(
            candidate_tags[ref]["adds"] & bucket and selected_counts[rule_index] >= limit
            for rule_index, (bucket, limit) in enumerate(normalized_rules)
        )
    ]
    return {
        "target_counts": list(targets),
        "initial_eligible_refs": [ref for index, ref in enumerate(allowed) if initial_pool & (1 << index)],
        "eligible_refs": eligible_refs,
        "remaining_eligible_refs": remaining_eligible,
        "tag_limited_refs": tag_limited,
        "selected_tag_limit_exceeded": selected_tag_limit_exceeded,
        "selected_reachable": selected_reachable,
        "selected_terminal": selected_terminal,
        "terminal_counts": terminal_counts,
        "effective_min": effective_min,
        "effective_max": effective_max,
        "active": bool(selected or (initial_pool and any(target > 0 for target in targets))),
        "tags_before": sorted(base_active),
    }
