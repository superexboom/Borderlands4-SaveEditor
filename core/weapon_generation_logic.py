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
    dependency_tags: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Evaluate one native part-type slot using the game's shrink-only pool loop.

    ``dependency_tags`` optionally widens the tag set used to satisfy ``requires``
    so that a dependency chain contained within a single slot (class mod skill
    tiers) is accepted. It never widens ``excludes``: the native loop shrinks the
    pool after every pick, so mutually exclusive siblings must still be rejected.
    """
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
    # Tags granted only by the dependency widening. They may satisfy `requires`
    # but must not trigger `excludes`, otherwise a chain like tier_1 -> tier_2
    # would be rejected by the very sibling that enables it.
    widened_only = frozenset(str(tag).casefold() for tag in (dependency_tags or ())) - base_active
    requires_active = base_active | widened_only
    base_counts = tuple(
        int(base_tag_counts[index]) if index < len(base_tag_counts) else 0
        for index in range(len(normalized_rules))
    )

    @lru_cache(maxsize=None)
    def state(mask: int) -> tuple[frozenset[str], tuple[int, ...]]:
        active = set(requires_active)
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
        if not tags["requires"] <= active or tags["excludes"] & (active - widened_only):
            return False
        return not any(
            tags["adds"] & bucket and counts[rule_index] >= limit
            for rule_index, (bucket, limit) in enumerate(normalized_rules)
        )

    initial_pool = 0
    for index in range(len(allowed)):
        if candidate_allowed(index, requires_active, base_counts):
            initial_pool |= 1 << index

    # The pool only ever shrinks, and for a candidate still in it `requires` is
    # already met (active tags only grow) while `excludes` and the tag limits only
    # tighten. So the pool after a set of picks does not depend on their order: it
    # is the initial pool minus the picks minus every candidate an active tag
    # excludes or a full tag rule blocks. That lets the search below track masks
    # (not (mask, pool) pairs) and filter the pool with precomputed bit masks.
    excluded_by: dict[str, int] = {}
    rule_members = [0] * len(normalized_rules)
    for index, ref in enumerate(allowed):
        tags = candidate_tags[ref]
        for tag in tags["excludes"]:
            excluded_by[tag] = excluded_by.get(tag, 0) | (1 << index)
        for rule_index, (bucket, _limit) in enumerate(normalized_rules):
            if tags["adds"] & bucket:
                rule_members[rule_index] |= 1 << index
    pick_block: list[int] = []
    pick_rules: list[tuple[int, ...]] = []
    for ref in allowed:
        adds = candidate_tags[ref]["adds"]
        blocked = 0
        for tag in adds - widened_only:
            blocked |= excluded_by.get(tag, 0)
        pick_block.append(blocked)
        pick_rules.append(tuple(index for index, (bucket, _limit) in enumerate(normalized_rules) if adds & bucket))
    rule_limits = [limit - base for (_bucket, limit), base in zip(normalized_rules, base_counts)]

    targets = _target_counts(minimum, maximum, additional_chance)
    largest = max(targets)

    # Whether a set of picks can come out of the loop needs no search: the picks
    # must all be in the initial pool, no more than the largest target, within
    # every tag rule's remaining room, and orderable so that no pick removes a
    # later one from the pool (a pick only removes what its tags exclude, so the
    # picks it would remove must come first). Enumerating every reachable set
    # instead grows combinatorially: a class mod's skill pool widens with every
    # point spent, and 30 points took seconds per check.
    def reachable(mask: int) -> bool:
        if mask & ~initial_pool or mask.bit_count() > largest:
            return False
        for members, room in zip(rule_members, rule_limits):
            picked = (mask & members).bit_count()
            if picked and picked > room:
                return False
        remaining = mask
        while remaining:
            rest = remaining
            while rest:
                bit = rest & -rest
                rest ^= bit
                if not pick_block[bit.bit_length() - 1] & remaining & ~bit:
                    remaining ^= bit
                    break
            else:
                return False  # every pick left would remove another: no order works
        return True

    def pool_after(mask: int) -> int:
        blocked = 0
        bits = mask
        while bits:
            bit = bits & -bits
            bits ^= bit
            blocked |= pick_block[bit.bit_length() - 1]
        for members, room in zip(rule_members, rule_limits):
            if (mask & members).bit_count() >= room:
                blocked |= members
        return initial_pool & ~mask & ~blocked

    target_set = set(targets)

    def terminal(mask: int) -> bool:
        size = mask.bit_count()
        return size in target_set or (size < largest and not pool_after(mask))

    selected_valid = len(selected) == len(selected_unique) and all(ref in ref_indexes for ref in selected_unique)
    selected_set = set(selected_unique)
    selected_mask = sum(1 << ref_indexes[ref] for ref in selected_unique if ref in ref_indexes)
    selected_reachable = selected_valid and reachable(selected_mask)
    selected_terminal = selected_reachable and terminal(selected_mask)

    eligible_refs: list[str] = []
    terminal_sizes: set[int] = set()
    if selected_reachable:
        extensions = [1 << index for index in range(len(allowed))
                      if not selected_mask & (1 << index) and reachable(selected_mask | (1 << index))]
        extension_bits = sum(extensions)
        for index, ref in enumerate(allowed):
            if ref in selected_set or extension_bits & (1 << index):
                eligible_refs.append(ref)
        # Sizes of the complete selections that keep the current picks. Reachable
        # sets are closed under removal, so an unreachable set ends its branch.
        possible = {size for size in range(selected_mask.bit_count(), largest + 1)}
        stack = [(selected_mask, 0)]
        while stack and terminal_sizes != possible:
            mask, start = stack.pop()
            if terminal(mask):
                terminal_sizes.add(mask.bit_count())
            if mask.bit_count() >= largest:
                continue
            for position in range(start, len(extensions)):
                next_mask = mask | extensions[position]
                if reachable(next_mask):
                    stack.append((next_mask, position + 1))
    terminal_counts = sorted(terminal_sizes)
    effective_min = terminal_counts[0] if terminal_counts else int(minimum)
    effective_max = terminal_counts[-1] if terminal_counts else int(maximum)
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
        "dependency_tags": sorted(requires_active),
    }
