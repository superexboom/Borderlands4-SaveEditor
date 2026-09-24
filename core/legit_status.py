"""UI-facing legality status for Class Mod and Enhancement builders.

The generation resolver remains the source of truth. This module only maps its
machine result to stable UI states and human-readable explanations; it never
widens a pool or invents a missing rule.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from .item_display_resolver import validate_weapon_generation


STATUS_LABELS = {
    "zh-CN": {
        "legal": "Legit · 合法",
        "incomplete": "未完成",
        "modified": "非法组合",
        "unknown": "未知",
        "conditional": "条件合法",
    },
    "en-US": {
        "legal": "Legit · Legal",
        "incomplete": "Incomplete",
        "modified": "Invalid combination",
        "unknown": "Unknown",
        "conditional": "Conditional",
    },
}

STATUS_COLORS = {
    "legal": "legal",
    "incomplete": "incomplete",
    "modified": "invalid",
    "unknown": "unknown",
    "conditional": "conditional",
}

REASON_LABELS = {
    "zh-CN": {
        "count_below": "必需槽位尚未填满",
        "count_above": "超过该槽位的最大数量",
        "part_not_allowed": "包含当前模板不允许的部件",
        "foreign_root_part": "包含其他物品类型或厂商的部件",
        "unknown_part": "存在索引未识别的部件",
        "unknown_composition": "稀有度模板无法识别",
        "rules_unavailable": "没有可用的生成规则",
        "weapon_rules_missing": "当前根类型没有生成规则",
        "unresolved_rule_parts": "规则中仍有未解析的部件",
        "conditional_availability": "规则带有版本或场景条件",
        "duplicate_part": "同一部件重复占用槽位",
        "tag_count_below": "标签数量未达到规则要求",
        "tag_limit": "标签数量超过规则上限",
        "missing_required_tag": "缺少前置依赖标签",
        "excluded_tag_conflict": "与排除标签冲突",
        "inheritance_cycle": "规则继承出现循环",
        "invalid_serial": "序列格式无效",
    },
    "en-US": {
        "count_below": "Required slots are not filled",
        "count_above": "Slot count exceeds the rule maximum",
        "part_not_allowed": "A part is not allowed by this template",
        "foreign_root_part": "A part belongs to another type or manufacturer",
        "unknown_part": "A part is missing from the index",
        "unknown_composition": "The rarity template is unknown",
        "rules_unavailable": "No generation rules are available",
        "weapon_rules_missing": "No rules exist for this root type",
        "unresolved_rule_parts": "The rule contains unresolved parts",
        "conditional_availability": "The rule has a version or context condition",
        "duplicate_part": "The same part occupies a slot more than once",
        "tag_count_below": "Required tag count is not met",
        "tag_limit": "Tag count exceeds the rule limit",
        "missing_required_tag": "A dependency tag is missing",
        "excluded_tag_conflict": "An exclusion tag conflicts",
        "inheritance_cycle": "Rule inheritance contains a cycle",
        "invalid_serial": "The serial format is invalid",
    },
}

GROUP_LABELS_ZH = {
    "class_mod_body": "传奇名称", "passive_points": "技能点", "action_skill_mod": "主动技能加成",
    "special_passive": "特殊技能", "stat_group1": "属性槽 1", "stat_group2": "属性槽 2",
    "stat_group3": "属性槽 3", "firmware": "固件", "core_augment": "核心强化",
    "body": "稀有度核心",
}


def _language(language: str) -> str:
    return "zh-CN" if str(language).startswith("zh") else "en-US"


def _detail(violations: list[dict[str, Any]], language: str) -> str:
    lang = _language(language)
    labels = REASON_LABELS[lang]
    counts = Counter(str(row.get("code", "unknown")) for row in violations)
    lines = []
    for code, count in counts.items():
        label = labels.get(code, code)
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
    status = raw_status if raw_status in STATUS_LABELS["zh-CN"] else "unknown"
    violations = list(result.get("violations") or [])
    detail = _detail(violations, language)
    if not detail:
        detail = (
            "规则完整，已选部件都能在当前 NCS 生成池中完成。"
            if _language(language) == "zh-CN" else
            "The selected parts form a complete build in the current NCS pool."
        ) if status == "legal" else (
            "尚未发现足够的规则或部件数据，暂不判定。"
            if _language(language) == "zh-CN" else
            "There is not enough rule or part data to decide."
        )
    return {
        "status": STATUS_COLORS.get(status, "unknown"),
        "rawStatus": status,
        "label": STATUS_LABELS[_language(language)].get(status, STATUS_LABELS[_language(language)]["unknown"]),
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
    lang = _language(language)
    return {
        "status": status,
        "label": STATUS_LABELS[lang].get(status, STATUS_LABELS[lang]["unknown"]),
        "detail": str(option.get("hint") or option.get("tooltip") or ""),
    }


def candidate_state(
    context: dict[str, Any], refs: list[str] | tuple[str, ...] | str,
    language: str = "zh-CN", *, label: str = "",
) -> dict[str, Any]:
    """Describe whether one picker option can be added to the current build.

    ``refs`` normally contains the next rank/part that clicking ``+`` adds. The
    context is calculated once per rebuild, so decorating a large catalog does
    not repeatedly run the generation evaluator.
    """
    refs = [str(ref) for ref in ([refs] if isinstance(refs, str) else refs) if ref]
    zh = _language(language) == "zh-CN"
    if not refs or not context.get("rules_available") or not context.get("composition_ref"):
        return {
            "kind": "unknown", "marker": "?", "badge": "规则未知" if zh else "Rules unknown",
            "hint": "没有足够的规则数据判断这个部件。" if zh else "There is not enough rule data to classify this part.",
        }
    groups = context.get("groups") or {}
    matched: list[tuple[str, dict[str, Any], str]] = []
    for ref in refs:
        for group, spec in groups.items():
            if ref in set(spec.get("allowed") or []):
                matched.append((str(group), spec, ref))
    if not matched:
        return {
            "kind": "modified", "marker": "◇", "badge": "非自然配件" if zh else "Modified part",
            "hint": (
                f"{label or '该部件'}不在当前传奇/稀有度模板的自然生成池内；仍可作为魔改选择。"
                if zh else
                f"{label or 'This part'} is outside the natural pool for the current template; it remains selectable as a modified part."
            ),
        }

    active = [(group, spec, ref) for group, spec, ref in matched
              if int(spec.get("effective_max", spec.get("max", 0))) > 0
              or ref in set(spec.get("selected") or [])]
    if not active:
        return {
            "kind": "modified", "marker": "◇", "badge": "当前模板不启用" if zh else "Inactive in template",
            "hint": "部件存在于基础池，但当前模板没有启用对应槽位。" if zh else
                    "The part exists in the base pool, but this template does not activate its slot.",
        }

    names = " / ".join(dict.fromkeys(
        GROUP_LABELS_ZH.get(group, group) if zh else group.replace("_", " ").title()
        for group, _spec, _ref in active))
    selected = any(ref in set(spec.get("selected") or []) for _group, spec, ref in active)
    remaining = any(ref in set(spec.get("remaining_eligible_refs") or []) for _group, spec, ref in active)
    eligible = any(ref in set(spec.get("eligible_refs") or []) for _group, spec, ref in active)
    duplicate = any(list(context.get("selected_part_refs") or []).count(ref) > 1 for ref in refs)
    if duplicate:
        return {
            "kind": "modified", "marker": "◇", "badge": "重复部件" if zh else "Duplicate part",
            "hint": "该部件重复占用了自然生成槽位。" if zh else "This part occupies a natural slot more than once.",
        }
    overfull = any(ref in set(spec.get("selected") or [])
                   and len(spec.get("selected") or []) > int(spec.get("effective_max", spec.get("max", 0)))
                   for _group, spec, ref in active)
    if overfull:
        return {
            "kind": "modified", "marker": "◇", "badge": "超过槽位上限" if zh else "Slot limit exceeded",
            "hint": f"当前 {names} 的已选数量超过自然生成上限。" if zh else
                    f"The selected count exceeds the natural limit for {names}.",
        }
    blocked_selected = any(ref in set(spec.get("selected") or []) and not spec.get("selected_reachable", False)
                           for _group, spec, ref in active)
    if blocked_selected:
        return {
            "kind": "warning", "marker": "!", "badge": "当前组合冲突" if zh else "Current combination conflicts",
            "hint": f"该部件属于 {names}，但当前依赖或排除关系无法到达这个组合。" if zh else
                    f"The part belongs to {names}, but current dependencies or exclusions make the combination unreachable.",
        }
    if remaining:
        return {
            "kind": "legal", "marker": "✓", "badge": "合法候选" if zh else "Natural candidate",
            "hint": f"当前构筑可继续选择该部件（{names}）。" if zh else
                    f"This part can be added to the current build ({names}).",
        }
    if selected:
        return {
            "kind": "legal", "marker": "✓", "badge": "已选合法部件" if zh else "Selected natural part",
            "hint": f"该部件已在当前自然构筑中（{names}）。" if zh else
                    f"This part is already present in the natural build ({names}).",
        }
    if eligible:
        return {
            "kind": "warning", "marker": "!", "badge": "槽位已满" if zh else "Slot is full",
            "hint": f"它属于合法池（{names}），但当前槽位已满；替换现有部件后可保持合法。" if zh else
                    f"It belongs to the natural pool ({names}), but the slot is full; replace an existing part to stay legal.",
        }
    limited = any(ref in set(spec.get("tag_limited_refs") or []) for _group, spec, ref in active)
    return {
        "kind": "warning", "marker": "!",
        "badge": ("标签上限" if limited else "条件未满足") if zh else
                 ("Tag limit" if limited else "Condition unmet"),
        "hint": (
            f"它属于合法池（{names}），但当前依赖、排除关系或数量上限不允许直接添加。"
            if zh else
            f"It belongs to the natural pool ({names}), but current dependencies, exclusions, or limits block it."
        ),
    }
