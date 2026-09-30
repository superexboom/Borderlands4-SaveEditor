"""UI-facing legality status for Class Mod and Enhancement builders.

The generation resolver remains the source of truth. This module only maps its
machine result to stable UI states and human-readable explanations; it never
widens a pool or invents a missing rule.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from functools import lru_cache

from . import ui_text
from .item_display_resolver import (
    generation_blocked_groups,
    generation_conflict_possible,
    validate_weapon_generation,
)


#: status -> catalog key under ``legit.status``
STATUS_KEYS = ("legal", "incomplete", "modified", "unknown", "conditional")

STATUS_COLORS = {
    "legal": "legal",
    "incomplete": "incomplete",
    "modified": "invalid",
    "unknown": "unknown",
    "conditional": "conditional",
}

def _language(language: str) -> str:
    return str(language or "zh-CN")


def _t(key: str, language: str, **fmt: Any) -> str:
    return ui_text.tr(f"legit.{key}", _language(language), **fmt)


def _status_label(status: str, language: str) -> str:
    return _t(f"status.{status if status in STATUS_KEYS else 'unknown'}", language)


def _group_label(group: str, language: str) -> str:
    return ui_text.tr(f"legit.groups.{group}", _language(language),
                      default=str(group).replace("_", " ").title())


def _detail(violations: list[dict[str, Any]], language: str) -> str:
    counts = Counter(str(row.get("code", "unknown")) for row in violations)
    lines = []
    for code, count in counts.items():
        label = ui_text.tr(f"legit.reasons.{code}", _language(language), default=code)
        lines.append(f"{label} ×{count}" if count > 1 else label)
    return "\n".join(lines)


def evaluate(decoded: str, language: str = "zh-CN", *, index: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a stable badge model for a generated Class Mod/Enhancement serial."""
    try:
        result = validate_weapon_generation(decoded, allow_incomplete=True, index=index)
    except Exception as exc:
        status = "unknown"
        result = {"status": status, "violations": [{"code": "invalid_serial", "error": str(exc)}]}
    raw_status = str(result.get("status") or "unknown")
    status = raw_status if raw_status in STATUS_KEYS else "unknown"
    violations = list(result.get("violations") or [])
    detail = _detail(violations, language)
    if not detail:
        detail = _t("detail_legal" if status == "legal" else "detail_unknown", language)
    return {
        "status": STATUS_COLORS.get(status, "unknown"),
        "rawStatus": status,
        "label": _status_label(status, language),
        "detail": detail,
        "violations": violations,
        "coverageComplete": bool(result.get("coverage_complete")),
        "rootRef": str(result.get("root_ref", "")),
        "compositionRef": str(result.get("composition_ref", "")),
    }


def option_status(option: dict[str, Any], language: str = "zh-CN") -> dict[str, Any]:
    """Normalize an individual picker option's existing candidate marker."""
    kind = str(option.get("kind") or option.get("candidate", {}).get("kind") or "unknown")
    mapping = {"legal": "legal", "warning": "conditional", "unknown": "unknown"}
    status = mapping.get(kind, "unknown")
    return {
        "status": status,
        "label": _status_label(status, language),
        "detail": str(option.get("hint") or option.get("tooltip") or ""),
    }


@lru_cache(maxsize=4096)
def _status_with_part(decoded: str, root: str, ref: str) -> tuple[str, str]:
    """(status, first hard violation code) of ``decoded`` with part ``ref`` appended."""
    owner, _, part = ref.partition(":")
    token = f"{{{part}}}" if owner == root else f"{{{owner}:{part}}}"
    head, sep, tail = decoded.rpartition("|")
    trial = f"{head} {token} {sep}{tail}" if sep else f"{decoded} {token}"
    result = validate_weapon_generation(trial, allow_incomplete=True)
    hard = next((str(item.get("code") or "") for item in result.get("violations") or []
                 if item.get("code") not in {"count_below", "tag_count_below"}), "")
    return str(result.get("status") or ""), hard


def cross_group_conflict(context: dict[str, Any], ref: str, decoded: str) -> str:
    """Violation code if adding ``ref`` breaks the build through another group, else "".

    Group states only see the tags of the groups evaluated before them, so a part
    that clashes with a part of another group (excluded tag, one-licensed-part
    limit) still looks addable; this confirms such a clash on the full build.
    """
    if not decoded or not generation_conflict_possible(context, ref):
        return ""
    status, code = _status_with_part(decoded, str(context.get("root_ref") or ""), ref)
    return (code or "modified") if status == "modified" else ""


def candidate_state(
    context: dict[str, Any], refs: list[str] | tuple[str, ...] | str,
    language: str = "zh-CN", *, label: str = "", decoded: str = "",
) -> dict[str, Any]:
    """Describe whether one picker option can be added to the current build.

    ``refs`` normally contains the next rank/part that clicking ``+`` adds. The
    context is calculated once per rebuild, so decorating a large catalog does
    not repeatedly run the generation evaluator.
    """
    refs = [str(ref) for ref in ([refs] if isinstance(refs, str) else refs) if ref]
    c = lambda key, **fmt: _t(f"candidate.{key}", language, **fmt)
    if not refs or not context.get("rules_available") or not context.get("composition_ref"):
        return {
            "kind": "unknown", "marker": "?", "badge": c("unknown_badge"), "hint": c("unknown_hint"),
        }
    groups = context.get("groups") or {}
    matched: list[tuple[str, dict[str, Any], str]] = []
    for ref in refs:
        for group, spec in groups.items():
            if ref in set(spec.get("allowed") or []):
                matched.append((str(group), spec, ref))
    if not matched:
        return {
            "kind": "modified", "marker": "◇", "badge": c("outside_badge"),
            "hint": c("outside_hint", label=label or _t("this_part", language)),
        }

    active = [(group, spec, ref) for group, spec, ref in matched
              if int(spec.get("effective_max", spec.get("max", 0))) > 0
              or ref in set(spec.get("selected") or [])]
    if not active:
        return {
            "kind": "modified", "marker": "◇", "badge": c("inactive_badge"), "hint": c("inactive_hint"),
        }

    names = " / ".join(dict.fromkeys(
        _group_label(group, language) for group, _spec, _ref in active))
    selected = any(ref in set(spec.get("selected") or []) for _group, spec, ref in active)
    remaining = any(ref in set(spec.get("remaining_eligible_refs") or []) for _group, spec, ref in active)
    eligible = any(ref in set(spec.get("eligible_refs") or []) for _group, spec, ref in active)
    duplicate = any(list(context.get("selected_part_refs") or []).count(ref) > 1 for ref in refs)
    if duplicate:
        return {
            "kind": "modified", "marker": "◇", "badge": c("duplicate_badge"), "hint": c("duplicate_hint"),
        }
    overfull = any(ref in set(spec.get("selected") or [])
                   and len(spec.get("selected") or []) > int(spec.get("effective_max", spec.get("max", 0)))
                   for _group, spec, ref in active)
    if overfull:
        return {
            "kind": "modified", "marker": "◇", "badge": c("overfull_badge"), "hint": c("overfull_hint", names=names),
        }
    blocked_selected = any(ref in set(spec.get("selected") or []) and not spec.get("selected_reachable", False)
                           for _group, spec, ref in active)
    if blocked_selected:
        return {
            "kind": "warning", "marker": "!", "badge": c("unreachable_badge"), "hint": c("unreachable_hint", names=names),
        }
    if remaining and decoded and not any(ref in set(spec.get("selected") or []) for _g, spec, ref in active):
        # A group only sees the tags of the groups evaluated before it: a part that
        # clashes with a part of another group (excluded tag, one-licensed-part
        # limit) still looks addable. Confirm by validating the build with it.
        for _group, _spec, ref in active:
            code = cross_group_conflict(context, ref, decoded)
            if code:
                return {
                    "kind": "warning", "marker": "!", "badge": c("conflict_badge"),
                    "hint": c("conflict_hint", names=names, code=code),
                }
    if remaining and not selected:
        blocked = [group for _group, _spec, ref in active for group in generation_blocked_groups(context, ref)]
        if blocked:
            blocked_names = " / ".join(dict.fromkeys(_group_label(group, language) for group in blocked))
            return {
                "kind": "warning", "marker": "!", "badge": c("blocks_badge"), "hint": c("blocks_hint", names=blocked_names),
            }
    if remaining:
        return {
            "kind": "legal", "marker": "✓", "badge": c("legal_badge"), "hint": c("legal_hint", names=names),
        }
    if selected:
        return {
            "kind": "legal", "marker": "✓", "badge": c("selected_badge"), "hint": c("selected_hint", names=names),
        }
    if eligible:
        return {
            "kind": "warning", "marker": "!", "badge": c("full_badge"), "hint": c("full_hint", names=names),
        }
    limited = any(ref in set(spec.get("tag_limited_refs") or []) for _group, spec, ref in active)
    return {
        "kind": "warning", "marker": "!",
        "badge": c("tag_limit_badge" if limited else "condition_badge"),
        "hint": c("condition_hint", names=names),
    }
