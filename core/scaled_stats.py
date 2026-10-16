"""Level-scaled stat rolls of Enhancements and Class Mods.

Both families roll stat parts whose value is a balance formula of the item
level (``table modifier x (1 + k x level)``, ``base x 1.09^level x c``). The
CSV labels carry the number of one fixed level; the pipeline exports the
formulas as ``scaled_stat_model`` so the editor shows the value of the item's
own level, like the game card does.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from . import game_text, resource_loader

_NUMBER_RE = re.compile(r"[+\-−]?\d[\d,]*(?:\.\d+)?(?:\s?%)?")


def _index() -> dict[str, Any]:
    return resource_loader.load_item_json("item_name_index.json") or {}


def _resolvers() -> dict[str, Any]:
    return ((_index().get("scaled_stat_model") or {}).get("attribute_resolvers") or {})


def _ref_name(value: Any) -> str:
    text = str(value or "").strip().rstrip("'")
    if "'" in text:
        text = text.rsplit("'", 1)[-1]
    return text.casefold()


def _number(value: Any) -> float | None:
    try:
        return None if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return None


def attribute_value(name: str, level: int) -> float | None:
    """Evaluate one exported attribute at an item level (``None`` when unknown)."""
    return _attribute_value(_ref_name(name), int(level), frozenset())


@lru_cache(maxsize=4096)
def _attribute_value(name: str, level: int, stack: frozenset[str]) -> float | None:
    if name in {"inventory_experience_level", "weapon_level"}:
        return float(level)
    if name in stack:
        return None
    value = ((_resolvers().get(name) or {}).get("definition") or {}).get("value") or {}
    kind = str(value.get("structtype") or "").casefold()
    inner = stack | {name}

    def atom(node: Any, default: float | None) -> float | None:
        if not isinstance(node, dict):
            return default
        if node.get("attribute"):
            resolved = _attribute_value(_ref_name(node["attribute"]), level, inner)
            if resolved is not None:
                return resolved
        resolved = _number((node.get("datatablevalue") or {}).get("resolved_value"))
        if resolved is not None:
            return resolved
        constant = _number(node.get("constant"))
        return default if constant is None else constant

    if "balanceformulavalueresolver" in kind:
        multiplier = atom(value.get("multiplier"), 1.0)
        base = atom(value.get("level"), 1.0)
        power = atom(value.get("power"), 1.0)
        scalar = atom(value.get("scalar"), 1.0)
        offset = atom(value.get("offset"), 0.0)
        if None in (multiplier, base, power, scalar, offset):
            return None
        return multiplier * base ** power * scalar + offset
    if "balancestatevalueresolver" in kind and _ref_name(value.get("valuetoresolve")) == "experiencelevel":
        return float(level)
    if "constantattributevalueresolver" in kind:
        initial = value.get("attributeinit") or {}
        result = atom(initial, None)
        if result is None:
            return None
        return result * (_number(initial.get("basescale")) or 1.0) * (_number(initial.get("postscale")) or 1.0)
    return None


def apply_sign_style(value: float, arg: dict[str, Any]) -> float:
    """Apply a NumericDisplayValue's SignStyle, as the game's UI does.

    Positive/Negative force the shown sign (Deadeye's -0.3 accuracy reads +30%),
    OppositeSign flips it. Every uistat formatter must go through this.
    """
    style = str(arg.get("signstyle") or "").casefold()
    if style == "oppositesign":
        return -value
    if style == "positive":
        return abs(value)
    if style == "negative":
        return -abs(value)
    return value


def _display_value(value: float, arg: dict[str, Any]) -> float:
    if arg.get("bcalculatewithreductionmath") and value < 0:
        value = -(1.0 - 1.0 / (1.0 - value))
    return apply_sign_style(value, arg)


def _format(value: float, arg: dict[str, Any]) -> str:
    value = _display_value(value, arg)
    if arg.get("bdisplayaspercentage"):
        number = int(abs(value) * 100.0 + 0.5 + 1e-9)
        text = f"{number}%"
    else:
        number = int(abs(value) + 0.5 + 1e-9)
        text = f"{number:,}"
    if value < 0 and number:
        return "-" + text
    return ("+" + text) if arg.get("bdisplayplussign") and number else text


def _part_uistats(ref_key: str) -> list[dict[str, Any]]:
    index = _index()
    part = (index.get("part_refs") or {}).get(ref_key) or {}
    if part.get("parent") not in {"enhancement", "classmod"} or not str(part.get("category") or "").startswith("stat_group"):
        return []
    uistats = index.get("uistats") or {}
    ids = list(dict.fromkeys(part.get("uistats_include") or part.get("uistats") or []))
    return [uistats[key] for key in (str(ui_id).casefold() for ui_id in ids) if key in uistats]


def part_values(ref_key: str, level: Any) -> list[str]:
    """Formatted numbers of a scaled stat part, in placeholder order (empty if not scaled)."""
    try:
        level = int(level)
    except (TypeError, ValueError):
        return []
    out = []
    for ui in _part_uistats(ref_key):
        template = str(ui.get("en") or "")
        args = ((ui.get("statvalue") or {}).get("args") or {})
        folded = {str(key).casefold(): arg for key, arg in args.items()}
        for placeholder in re.findall(r"\{(\w+)\}", template):
            arg = folded.get(placeholder.casefold()) or {}
            value = attribute_value(arg.get("attribute") or "", level) if arg.get("attribute") else None
            if value is None:
                return []
            out.append(_format(value, arg))
    return out


def part_text(ref_key: str, level: Any, lang: str, *, markup: bool = False) -> str:
    """The game's own UIStat sentence for a scaled stat part at ``level``."""
    values = part_values(ref_key, level)
    if not values:
        return ""
    lines = []
    remaining = iter(values)
    for ui in _part_uistats(ref_key):
        text = game_text.pick(ui, lang)
        text = re.sub(r"\{\w+\}", lambda _match: next(remaining, "?"), text)
        if not markup:
            text = re.sub(r"\[[^\]]+\]", "", text)
        lines.append(" ".join(text.split()))
    return "; ".join(line for line in lines if line)


def scale_label(label: str, ref_key: str, level: Any) -> str:
    """Replace the number of a CSV perk label with the value at ``level``.

    The labels are short forms ("+10% 近战暴击率", "Gun DMG +25%") written for
    one level; only their number changes, so all languages keep their wording.
    """
    values = part_values(ref_key, level)
    if len(values) != 1 or not label:
        return label
    match = _NUMBER_RE.search(label)
    if not match:
        return label
    old = match.group(0)
    new = values[0]
    if "%" in old and "%" not in new or "%" in new and "%" not in old:
        return label
    if not old.lstrip().startswith(("+", "-", "−")):
        new = new.lstrip("+")
    if old.endswith(" %"):
        new = new.replace("%", " %")
    return label[: match.start()] + new + label[match.end():]
