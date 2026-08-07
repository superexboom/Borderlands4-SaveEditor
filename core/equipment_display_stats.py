"""Offline item-card evaluator for BL4 non-weapon equipment."""

from __future__ import annotations

import ast
from math import ceil, floor
import re
from typing import Any, Iterable

from . import weapon_display_stats as weapon


FAMILY_BY_ITEM_TYPE = {
    "Grenade": "grenade",
    "Shield": "shield",
    "Repkit": "repkit",
    "Heavy Weapon": "heavy",
}

MANUFACTURER_ALIASES = {
    "borg": ("borg", "bor"),
    "ripper": ("borg", "bor"),
    "daedalus": ("daedalus", "dad"),
    "jakobs": ("jakobs", "jak"),
    "maliwan": ("maliwan", "mal"),
    "order": ("order", "ord"),
    "tediore": ("tediore", "ted"),
    "torgue": ("torgue", "tor"),
    "vladof": ("vladof", "vla"),
}

BASE_BODY_PARTS = {
    "part_body",
    "part_body_armor",
    "part_body_energy",
    "part_bor",
    "part_dad",
    "part_jak",
    "part_mal",
    "part_ord",
    "part_ted",
    "part_tor",
    "part_vla",
}
BASE_BODY_PART_KEYS = frozenset(re.sub(r"[^a-z0-9]+", "", name.casefold()) for name in BASE_BODY_PARTS)

# Current-build values from Status_Application_Defaults.  The pipeline may
# override them in the native model when the table is exported directly.
GRENADE_STATUS_DEFAULTS = {
    "corrosive": {"dps_scalar": 0.155, "chance": 0.05},
    "fire": {"dps_scalar": 0.2, "chance": 0.05},
    "radiation": {"dps_scalar": 0.13, "chance": 0.05},
    "shock": {"dps_scalar": 0.38, "chance": 0.05},
}


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _number(value: Any, default: float | None = None) -> float | None:
    if isinstance(value, dict):
        if "value" in value:
            return _number(value["value"], default)
        if "values" in value:
            return _number(value["values"], default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _row(rows: dict[str, Any], *names: Any) -> dict[str, Any]:
    wanted = {_norm(name) for name in names if name not in (None, "")}
    for key, value in (rows or {}).items():
        if _norm(key) in wanted:
            return value.get("values", value) if isinstance(value, dict) else {}
    return {}


def _column(row: dict[str, Any], *names: str, default: float | None = None) -> float | None:
    wanted = {_norm(name) for name in names}
    columns: list[tuple[str, Any]] = []
    for key, value in (row or {}).items():
        normalized = re.sub(r"(?:\d+)?[0-9a-f]{32}$", "", _norm(key))
        columns.append((normalized, value))
    for exact in (True, False):
        for normalized, value in columns:
            matched = normalized in wanted if exact else any(normalized.startswith(name) for name in wanted)
            if matched:
                number = _number(value)
                if number is not None:
                    return number
    return default


def _header(decoded: str) -> tuple[str, int]:
    header_text = decoded.split("||", 1)[0]
    segments = [segment.strip() for segment in header_text.split("|") if segment.strip()]
    fields = [[int(value.strip()) for value in segment.split(",")] for segment in segments]
    if not fields or len(fields[0]) < 4:
        raise ValueError("invalid decoded equipment serial")
    first = fields[0]
    return str(first[0]), 1 if len(fields) == 1 and first[2] == 2 else first[3]


def _family_model(index: dict[str, Any], root_id: str, item_type: str | None) -> tuple[str, dict[str, Any], dict[str, Any]]:
    native = index.get("equipment_native_models") or {}
    models = native.get("models") or {}
    preferred = FAMILY_BY_ITEM_TYPE.get(item_type or "")
    families = [preferred] if preferred else []
    families.extend(family for family in models if family not in families)
    for family in families:
        model = models.get(family) or {}
        root = (model.get("roots") or {}).get(root_id)
        if root is not None:
            return family, model, root
    raise KeyError(f"no equipment model for root {root_id}")


def _parts(decoded: str, index: dict[str, Any], root_id: str) -> list[dict[str, Any]]:
    refs = index.get("part_refs") or {}
    return [
        {**refs[key], "_ref_key": key}
        for key in weapon._serial_part_keys(decoded, root_id)
        if key in refs
    ]


def _rarity(parts: list[dict[str, Any]]) -> str:
    rarity = next((str(part.get("rarity")) for part in parts if part.get("rarity")), "")
    if not rarity:
        raise ValueError("equipment serial has no indexed rarity")
    return rarity


def _manufacturer_row(model: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    manufacturer = _norm(root.get("manufacturer"))
    names = MANUFACTURER_ALIASES.get(manufacturer, (manufacturer,))
    return _row(model.get("manufacturers") or {}, *names)


def _rarity_row(model: dict[str, Any], rarity: str) -> dict[str, Any]:
    return _row(model.get("rarities") or {}, rarity)


def _rarity_stat_scale(index: dict[str, Any], rarity: str) -> float:
    balance = (index.get("equipment_native_models") or {}).get("rarity_balance") or {}
    return _column(_row(balance, rarity), "stat_scale", default=1.0) or 1.0


def _effect_value(effect: dict[str, Any], defaults: dict[str, Any]) -> float | None:
    value_attribute = effect.get("value_attribute")
    if value_attribute:
        value = _number(defaults.get(value_attribute))
        if value is not None:
            return weapon.f32(value * (_number(effect.get("basescale"), 1.0) or 1.0) * (_number(effect.get("postscale"), 1.0) or 1.0))
    value = next(
        (_number(ref.get("value")) for ref in effect.get("datatable_refs", []) if _number(ref.get("value")) is not None),
        None,
    )
    if value is None:
        value = _number(effect.get("constant"))
    if value is None:
        return None
    return weapon.f32(value * (_number(effect.get("basescale"), 1.0) or 1.0) * (_number(effect.get("postscale"), 1.0) or 1.0))


def _effects(parts: Iterable[dict[str, Any]], *, include_base_body: bool = False) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for part in parts:
        if part.get("category") == "inv_comp":
            continue
        if not include_base_body and part.get("category") == "body" and _norm(part.get("part")) in BASE_BODY_PART_KEYS:
            continue
        out.extend(
            {
                **effect,
                "_part_category": part.get("category", ""),
                "_part_name": part.get("part", ""),
            }
            for effect in part.get("weapon_attribute_effects", [])
        )
    return out


def _modify(
    base: float,
    effects: Iterable[dict[str, Any]],
    attribute: str,
    defaults: dict[str, Any],
) -> float:
    override: float | None = None
    pre_add = post_add = 0.0
    product = 1.0
    simple: list[float] = []
    for effect in effects:
        if effect.get("attribute") != attribute or not int(effect.get("use_mode_bitmask", 1)) & 1:
            continue
        value = _effect_value(effect, defaults)
        if value is None:
            continue
        kind = str(effect.get("modifier_type") or "ScaleSimple")
        if kind == "OverrideBaseValue":
            override = value
        elif kind == "PreAdd":
            pre_add = weapon.f32(pre_add + value)
        elif kind == "PostAdd":
            post_add = weapon.f32(post_add + value)
        elif kind == "ScaleMultiply":
            product = weapon.f32(product * value)
        else:
            simple.append(value)
    positive = sum(value for value in simple if value >= 0)
    negative = sum(value for value in simple if value < 0)
    scale = weapon.f32(product * ((1.0 + positive) / (1.0 - negative)))
    value = override if override is not None else base
    return weapon.f32(weapon.f32(weapon.f32(value + pre_add) * scale) + post_add)


def _override_value(effects: Iterable[dict[str, Any]], attribute: str, defaults: dict[str, Any]) -> float | None:
    value = None
    for effect in effects:
        if (
            effect.get("attribute") == attribute
            and effect.get("modifier_type") == "OverrideBaseValue"
            and int(effect.get("use_mode_bitmask", 1)) & 1
        ):
            resolved = _effect_value(effect, defaults)
            if resolved is not None:
                value = resolved
    return value


def _scale_simple(base: float, modifiers: Iterable[float]) -> float:
    values = list(modifiers)
    positive = sum(value for value in values if value >= 0)
    negative = sum(value for value in values if value < 0)
    return weapon.f32(weapon.f32(base) * weapon.f32((1.0 + positive) / (1.0 - negative)))


def _stat_groups(parts: Iterable[dict[str, Any]], *aliases: str) -> tuple[tuple[float, ...], tuple[float, ...]]:
    wanted = {_norm(alias) for alias in aliases}
    groups: list[list[float]] = [[], []]
    for part in parts:
        for modifier in part.get("weapon_stat_modifiers", []):
            tag = _norm(modifier.get("attr") or modifier.get("stat_tag"))
            if tag not in wanted:
                continue
            mode = modifier.get("use_mode_bitmask")
            if mode is not None and not int(mode) & 1:
                continue
            value = _effect_value(modifier, {})
            if value is not None:
                groups[int(mode is not None)].append(value)
    return tuple(groups[0]), tuple(groups[1])


def _element_damage_scale(parts: Iterable[dict[str, Any]]) -> float:
    scale = 1.0
    for part in parts:
        for modifier in part.get("weapon_stat_modifiers", []):
            if modifier.get("source_aspect") not in {
                "grenade_element_damage_scalar",
                "weapon_element_damage_scalar",
            }:
                continue
            value = _effect_value(modifier, {})
            if value is not None:
                scale = weapon.f32(scale * value)
    return scale


def _stat_scalar(model: dict[str, Any], *names: str, default: float = 0.0) -> float:
    row = _row(model.get("stat_scalars") or {}, *names)
    return _column(row, "default", default=default) or 0.0


def _apply_stat(
    value: float,
    parts: list[dict[str, Any]],
    model: dict[str, Any],
    rarity_scale: float,
    row_names: tuple[str, ...],
    aliases: tuple[str, ...],
    *,
    invert: bool = False,
) -> float:
    scalar = _stat_scalar(model, *row_names)
    if not scalar:
        return value
    for group in _stat_groups(parts, *aliases):
        if group:
            points = (-point for point in group) if invert else group
            value = weapon._scaled_stat_group(value, points, scalar, rarity_scale)
    return value


def _level_value(base: float, growth: float, level: int) -> float:
    if level < 1:
        raise ValueError("level must be positive")
    return weapon.f32(weapon.f32(base) * weapon.f32(weapon.f32(growth) ** level))


def _round_int(value: float) -> int:
    return floor(weapon.f32(value) + 0.50001) if value >= 0 else ceil(weapon.f32(value) - 0.50001)


def _display_decimal(value: float, precision: int = 1) -> float:
    scale = 10**precision
    return weapon.f32(floor(weapon.f32(value) * scale + 0.50001) / scale)


def _grenade_stats(
    level: int,
    rarity: str,
    parts: list[dict[str, Any]],
    index: dict[str, Any],
    model: dict[str, Any],
    root: dict[str, Any],
) -> dict[str, Any]:
    base = model.get("base") or {}
    growth = _number(model.get("level_growth"), _number((index.get("equipment_native_models") or {}).get("level_growth"), 1.09)) or 1.09
    manufacturer = _manufacturer_row(model, root)
    rarity_row = _rarity_row(model, rarity)
    rarity_stat = _rarity_stat_scale(index, rarity)
    effects = [
        effect
        for effect in _effects(parts)
        if not (
            effect.get("_part_category") == "body"
            and effect.get("source_aspect") == "grenade_attr_base_values"
        )
        if not (
            effect.get("_part_category") != "body"
            and effect.get("source_aspect") == "grenade_attr_base_values"
            and effect.get("attribute") in {"gadget_cooldown", "grenade_gadget_max_number_of_charges"}
        )
    ]
    orphan_effects = [
        {**modifier, "attribute": effect.get("attribute")}
        for part in parts
        for modifier in part.get("weapon_stat_modifiers", [])
        if not modifier.get("attr") and not modifier.get("stat_tag") and modifier.get("value_attribute")
        for effect in effects
        if effect.get("value_attribute") == modifier.get("value_attribute")
    ]
    defaults = model.get("attribute_defaults") or {}

    damage = _level_value(_number(base.get("damage"), 80.0) or 80.0, growth, level)
    damage = weapon.f32(damage * (_column(manufacturer, "damage_scale", default=1.0) or 1.0))
    damage = weapon.f32(damage * (_column(rarity_row, "damage_scale", default=1.0) or 1.0))
    damage = _apply_stat(damage, parts, model, rarity_stat, ("Damage",), ("Damage",))
    damage = _modify(damage, effects, "grenade_gadget_damage", defaults)
    damage = weapon.f32(damage * _element_damage_scale(parts))

    radius = _column(manufacturer, "radius", default=_number(base.get("radius"), 300.0)) or 0.0
    radius = weapon.f32(radius * (_column(rarity_row, "radius_scale", default=1.0) or 1.0))
    radius = _apply_stat(radius, parts, model, rarity_stat, ("Radius",), ("DamageRadius", "splash_radius", "radius"))
    radius = _modify(radius, effects, "grenade_gadget_radius", defaults)

    cooldown = _column(manufacturer, "cooldown", default=_number(base.get("cooldown"), 20.0)) or 0.0
    cooldown = weapon.f32(cooldown * (_column(rarity_row, "cooldown_scale", default=1.0) or 1.0))
    cooldown = _apply_stat(cooldown, parts, model, rarity_stat, ("Cooldown",), ("cooldown",), invert=True)
    cooldown = _modify(cooldown, [*effects, *orphan_effects], "gadget_cooldown", defaults)

    charges = _column(manufacturer, "charges_value", "charges", default=_number(base.get("charges"), 2.0)) or 2.0
    charges = _modify(charges, effects, "grenade_gadget_max_number_of_charges", defaults)

    crit = weapon.f32(
        _apply_stat(1.0, parts, model, rarity_stat, ("CritDamage",), ("CritDamage", "critical_damage")) - 1.0
    )
    crit = _modify(crit, effects, "grenade_gadget_critical_damage", defaults)
    crit_chance = weapon.f32(
        _apply_stat(1.0, parts, model, rarity_stat, ("CritChance",), ("CritChance", "CriticalChance", "critical_chance")) - 1.0
    )
    crit_chance = _modify(crit_chance, effects, "grenade_gadget_crit_chance", defaults)
    stats: dict[str, Any] = {
        "damage": str(_round_int(damage)),
        "radius": _round_int(radius),
        "cooldown": _round_int(cooldown),
        "charges": max(1, floor(charges)),
    }
    if crit:
        stats["critical_damage"] = _round_int(crit * 100.0)
    if crit_chance:
        stats["critical_chance"] = _round_int(crit_chance * 100.0)

    element = next(
        (
            _norm(part.get("part")).removeprefix("part")
            for part in parts
            if part.get("category") == "element"
        ),
        "",
    )
    status_effects = _effects(parts, include_base_body=True)
    if element == "cryo":
        charge = _modify(
            1.0,
            status_effects,
            "grenade_damage_modifier_base_status_effect_charge",
            defaults,
        )
        stats["cryo_efficiency"] = _round_int(charge * 100.0)
    elif element in GRENADE_STATUS_DEFAULTS:
        status_defaults = {
            **GRENADE_STATUS_DEFAULTS,
            **{
                key.casefold(): value
                for key, value in (
                    (index.get("equipment_native_models") or {}).get("status_application_defaults") or {}
                ).items()
            },
        }[element]
        status_damage = _modify(
            1.0,
            status_effects,
            "grenade_damage_modifier_base_status_effect_damage",
            defaults,
        )
        status_chance = _modify(
            1.0,
            status_effects,
            "grenade_damage_modifier_base_status_effect_chance",
            defaults,
        )
        dot_interval = _number(model.get("status_dot_interval"), 0.33) or 0.33
        stats["elemental_dps"] = _round_int(
            weapon.f32(
                weapon.f32(
                    weapon.f32(damage * status_damage)
                    * (_number(status_defaults.get("dps_scalar"), 0.0) or 0.0)
                )
                / dot_interval
            )
        )
        stats["elemental_chance"] = _round_int(
            status_chance * (_number(status_defaults.get("chance"), 0.0) or 0.0) * 100.0
        )
    return stats


def _shield_stats(
    level: int,
    rarity: str,
    parts: list[dict[str, Any]],
    index: dict[str, Any],
    model: dict[str, Any],
    root: dict[str, Any],
) -> dict[str, Any]:
    base = model.get("base") or {}
    growth = _number(model.get("level_growth"), _number((index.get("equipment_native_models") or {}).get("level_growth"), 1.09)) or 1.09
    manufacturer = _manufacturer_row(model, root)
    rarity_row = _rarity_row(model, rarity)
    dynamic_attributes = {
        "shield_ra_armor_segment_value",
        "shield_eng_recharge_rate_value",
        "shield_eng_recharge_delay_value",
        "shield_unv_capacity_value",
        "shield_unv_turtle_value",
    }
    all_effects = _effects(parts)
    augment_effects = [effect for effect in all_effects if effect.get("source_aspect") == "shield_attr_augment_init"]
    effects = [
        effect
        for effect in all_effects
        if effect not in augment_effects
        if effect.get("value_attribute") not in dynamic_attributes
        if not (
            effect.get("source_aspect") == "shd_aug_unv_turtle"
            and effect.get("attribute") == "shield_capacity"
        )
    ]
    defaults = model.get("attribute_defaults") or {}
    augment_rows: list[dict[str, Any]] = []
    initializers = model.get("part_initializers") or {}
    payloads = model.get("payloads") or {}
    for part in parts:
        initializer = initializers.get(str(part.get("_ref_key") or "")) or {}
        values = next(
            (
                reference.get("values")
                for reference in initializer.get("references", [])
                if reference.get("table") == "Shield_Augment_Init"
                and isinstance(reference.get("values"), dict)
            ),
            None,
        )
        if values is None and initializer.get("table") == "Shield_Augment_Init":
            values = _row(payloads.get("Shield_Augment_Init") or {}, initializer.get("row"))
        if values:
            augment_rows.append(values)
    level_base = _level_value(_number(base.get("capacity"), 100.0) or 100.0, growth, level)
    dynamic: dict[str, list[float]] = {
        "capacity_scale": [],
        "recharge_rate": [],
        "recharge_delay": [],
        "segments": [],
    }
    grouped: dict[str, list[dict[str, Any]]] = {}
    for initializer, _values in _part_initializer_values(model, parts):
        grouped.setdefault(_norm(initializer.get("row")), []).append(initializer)
    dynamic_rows = {
        "turtle": ("Shield_Augment_Universal", "Turtle", "capacity_scale"),
        "capacity": ("Shield_Augment_Universal", "Capacity", "capacity_scale"),
        "rechargerate": ("Shield_Augment_Energy", "RechargeRate", "recharge_rate"),
        "rechargedelay": ("Shield_Augment_Energy", "RechargeDelay", "recharge_delay"),
        "armorsegment": ("Shield_Augment_Armor", "ArmorExtraSegment", "segments"),
        "armorextrasegment": ("Shield_Augment_Armor", "ArmorExtraSegment", "segments"),
    }
    for row_key, initializers in grouped.items():
        spec = dynamic_rows.get(row_key)
        if not spec:
            continue
        table_name, table_row, target = spec
        values = _row(payloads.get(table_name) or {}, table_row)
        roles = {_norm(item.get("role")) for item in initializers}
        if "primaryaugment" in roles and "secondaryaugment" in roles:
            value = _column(values, "augment_both")
            if value is not None:
                dynamic[target].append(value)
        else:
            for initializer in initializers:
                role = "augment_primary" if _norm(initializer.get("role")) == "primaryaugment" else "augment_secondary"
                value = _column(values, role)
                if value is not None:
                    dynamic[target].append(value)

    def augment_values(*columns: str) -> list[float]:
        return [
            value
            for row in augment_rows
            if (value := _column(row, *columns)) is not None
        ]

    capacity = weapon.f32(level_base * (_column(manufacturer, "capacity", default=1.0) or 1.0))
    capacity = _scale_simple(
        capacity,
        [(_column(rarity_row, "capacity", default=0.0) or 0.0), *augment_values("capacity")],
    )
    for scale in dynamic["capacity_scale"]:
        capacity = weapon.f32(capacity * scale)
    capacity = _modify(capacity, effects, "shield_capacity", defaults)
    stats: dict[str, Any] = {"capacity": _round_int(capacity)}

    shield_kind = str(root.get("shield_kind") or root.get("base_type") or _column(manufacturer, "comment", default=None) or "").casefold()
    armor_segments = _column(manufacturer, "armorsegments", "armor_segments")
    is_armor = armor_segments is not None or "armor" in shield_kind
    if is_armor:
        segments = armor_segments or 0.0
        segments += _column(rarity_row, "armorsegments", "armor_segments", default=0.0) or 0.0
        segments = _modify(segments, effects, "shield_segments", defaults)
        segments += sum(dynamic["segments"])
        reduction = _column(manufacturer, "armordamagereduction", "armor_damage_reduction", default=0.0) or 0.0
        reduction = _scale_simple(
            reduction,
            [(_column(rarity_row, "armordamagereduction", "armor_damage_reduction", default=0.0) or 0.0)],
        )
        reduction = _modify(reduction, effects, "shield_armor_damage_reduction", defaults)
        stats["armor_segments"] = max(0, _round_int(segments))
        stats["damage_reduction"] = _round_int((1.0 - (1.0 / (1.0 - reduction))) * 100.0) if reduction < 0 else _round_int(reduction * 100.0)
        return stats

    delay = (_number(base.get("regen_delay"), 4.5) or 4.5) * (_column(manufacturer, "delay", default=1.0) or 1.0)
    delay = _scale_simple(
        delay,
        [
            (_column(rarity_row, "delay", default=0.0) or 0.0),
            *augment_values("delay"),
            *dynamic["recharge_delay"],
        ],
    )
    delay = _modify(delay, effects, "shield_regen_delay", defaults)
    regen = weapon.f32(level_base * (_number(base.get("regen_scale"), 0.18) or 0.18))
    regen = weapon.f32(regen * (_column(manufacturer, "rechargerate", "recharge_rate", default=1.0) or 1.0))
    regen = _scale_simple(
        regen,
        [
            (_column(rarity_row, "rechargerate", "recharge_rate", default=0.0) or 0.0),
            *augment_values("rechargerate", "recharge_rate"),
            *dynamic["recharge_rate"],
        ],
    )
    regen = _modify(regen, effects, "shield_regen_rate", defaults)
    stats["recharge_delay"] = _display_decimal(delay)
    stats["recharge_rate"] = _round_int(regen)
    return stats


def _payload_row(model: dict[str, Any], parts: list[dict[str, Any]]) -> dict[str, Any]:
    payloads = model.get("payloads") or {}
    rows = payloads.get("repkit_base_data") or payloads.get("RepKit_BaseData") or payloads
    for part in parts:
        if part.get("category") != "payload":
            continue
        name = _norm(part.get("part"))
        for row_name, row in (rows or {}).items():
            if _norm(row_name).removeprefix("payload") in name:
                return row.get("values", row) if isinstance(row, dict) else {}
    return {}


def _part_initializer_values(model: dict[str, Any], parts: Iterable[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    initializers = model.get("part_initializers") or {}
    payloads = model.get("payloads") or {}
    out: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for part in parts:
        initializer = initializers.get(str(part.get("_ref_key") or ""))
        if not isinstance(initializer, dict):
            continue
        table = str(initializer.get("table") or "")
        row_name = str(initializer.get("row") or "")
        values = _row(payloads.get(table) or {}, row_name)
        if not values:
            values = next(
                (
                    ref.get("values")
                    for ref in initializer.get("references", [])
                    if isinstance(ref.get("values"), dict)
                ),
                {},
            )
        if values:
            out.append((initializer, values))
    return out


def _repkit_stats(
    level: int,
    rarity: str,
    parts: list[dict[str, Any]],
    index: dict[str, Any],
    model: dict[str, Any],
    root: dict[str, Any],
) -> dict[str, Any]:
    base = model.get("base") or {}
    growth = _number(model.get("level_growth"), _number((index.get("equipment_native_models") or {}).get("level_growth"), 1.09)) or 1.09
    manufacturer = _manufacturer_row(model, root) or _row(model.get("manufacturers") or {}, "Default")
    rarity_row = _rarity_row(model, rarity)
    payload = _payload_row(model, parts)
    all_effects = _effects(parts, include_base_body=True)
    effects = [
        effect
        for effect in all_effects
        if not (
            effect.get("_part_category") == "body"
            and _norm(effect.get("_part_name")) in BASE_BODY_PART_KEYS
        )
        if effect.get("source_aspect") != "repair_kit_base_attr_init"
    ]
    defaults = model.get("attribute_defaults") or {}

    healing = _level_value(_number(base.get("healing"), 80.0) or 80.0, growth, level)
    healing = weapon.f32(healing * (_column(manufacturer, "healing_scale", default=0.5) or 0.5))
    healing = weapon.f32(healing * (_column(rarity_row, "healing_scale", default=1.0) or 1.0))
    healing = weapon.f32(healing * (_column(payload, "healing_scale", default=1.0) or 1.0))
    healing = _modify(healing, effects, "repair_kit_health", defaults)

    cooldown = _column(manufacturer, "cooldown", default=24.0) or 24.0
    cooldown = weapon.f32(cooldown * (_column(rarity_row, "cooldown_scale", default=1.0) or 1.0))
    cooldown = weapon.f32(cooldown * (_column(payload, "cooldown_scale", default=1.0) or 1.0))
    cooldown = _modify(cooldown, effects, "repair_kit_cooldown", defaults)
    duration = _column(manufacturer, "duration", default=6.0) or 6.0
    duration = _modify(duration, effects, "repair_kit_duration", defaults)
    instant_base = _column(manufacturer, "health_instant", "health_instant_pct")
    overtime_base = _column(manufacturer, "health_overtime", "health_over_time")
    instant_pct = _modify(1.0 if instant_base is None else instant_base, effects, "repair_kit_health_instant_pct", defaults)
    overtime_pct = _modify(1.0 if overtime_base is None else overtime_base, effects, "repair_kit_health_over_time_pct", defaults)
    instant = weapon.f32(healing * instant_pct)
    overtime = weapon.f32(healing * overtime_pct)
    charges = _modify(_number(base.get("charges"), 1.0) or 1.0, all_effects, "repair_kit_max_charges", defaults)
    return {
        "healing": _round_int(instant + overtime),
        "instant_healing": _round_int(instant),
        "health_over_time": _round_int(overtime),
        "cooldown": _round_int(cooldown),
        "duration": _round_int(duration),
        "charges": max(1, ceil(charges)),
    }


def _barrel_values(model: dict[str, Any], parts: list[dict[str, Any]]) -> dict[str, Any]:
    barrels = model.get("barrels") or {}
    payloads = model.get("payloads") or {}
    initializers = model.get("part_initializers") or {}
    for part in parts:
        if part.get("category") != "barrel":
            continue
        ref_key = str(part.get("_ref_key") or "")
        row = barrels.get(ref_key) or {}
        values = dict(row.get("base_values") or row.get("values") or {})
        initializer = initializers.get(ref_key) or {}
        for reference in initializer.get("references", []):
            for key, value in (reference.get("values") or {}).items():
                values.setdefault(key, value)
        values.update(
            _row(
                payloads.get(str(initializer.get("table") or "")) or {},
                initializer.get("row"),
            )
        )
        cooldown_resolved = False
        cooldown_effect_present = False
        for effect in part.get("weapon_attribute_effects", []):
            if effect.get("attribute") == "weapon_damage" and effect.get("modifier_type") == "OverrideBaseValue":
                target = _norm(effect.get("value_attribute")).removesuffix("damage").replace("hw", "")
                base_row = next(
                    (
                        row
                        for row_name, row in (payloads.get("Gadget_HW_Barrels") or {}).items()
                        if _norm(row_name) == target
                    ),
                    None,
                )
                scale = _column(base_row or {}, "damage_scale")
                if scale is not None:
                    values["damage_scale"] = scale
            if effect.get("attribute") == "gadget_cooldown" and effect.get("modifier_type") == "OverrideBaseValue":
                cooldown_effect_present = True
                cooldown = _effect_value(effect, {})
                if cooldown is not None:
                    values["cooldown"] = cooldown
                    cooldown_resolved = True
        if cooldown_effect_present and not cooldown_resolved:
            # A missing table cell leaves HeavyWeaponGadget.CooldownTime at its 60-second class default.
            values["cooldown"] = _number((model.get("base") or {}).get("cooldown"), 60.0) or 60.0
            cooldown_resolved = True
        if not cooldown_resolved:
            cooldown = next(
                (
                    _effect_value(modifier, {})
                    for modifier in part.get("weapon_stat_modifiers", [])
                    if modifier.get("source_aspect") == "hw_cooldown_attr"
                    and modifier.get("modifier_type") == "OverrideBaseValue"
                    and _effect_value(modifier, {}) is not None
                ),
                None,
            )
            if cooldown is not None:
                values["cooldown"] = cooldown
                cooldown_resolved = True
        if not cooldown_resolved:
            cooldown = next(
                (
                    _column(reference.get("values") or {}, "cooldown")
                    for reference in initializer.get("references", [])
                    if reference.get("table") == "Gadget_HW_Barrels"
                    and "cooldown" in _norm(reference.get("column"))
                    and _column(reference.get("values") or {}, "cooldown") is not None
                ),
                None,
            )
            if cooldown is not None:
                values["cooldown"] = cooldown
        if values:
            return values
        for ref in part.get("weapon_base_value_refs", []):
            values = ref.get("values") or {}
            if values:
                return values
    raise ValueError("heavy weapon has no resolved barrel")


def _heavy_stats(
    level: int,
    rarity: str,
    parts: list[dict[str, Any]],
    index: dict[str, Any],
    model: dict[str, Any],
    root: dict[str, Any],
) -> dict[str, Any]:
    base = model.get("base") or {}
    growth = _number(model.get("level_growth"), _number((index.get("equipment_native_models") or {}).get("level_growth"), 1.09)) or 1.09
    barrel = _barrel_values(model, parts)
    rarity_row = _rarity_row(model, rarity)
    rarity_stat = _rarity_stat_scale(index, rarity)
    effects = _effects(parts, include_base_body=True)
    defaults = model.get("attribute_defaults") or {}
    seed_attributes = {
        "weapon_damage",
        "weapon_fire_rate",
        "weapon_spread",
        "weapon_accuracy_impulse",
        "weapon_max_loaded_ammo",
        "weapon_damage_radius",
        "gadget_cooldown",
    }
    seed_sources = {
        "barrel_inst_attr_base_values",
        "barrel_attr_base_values",
        "hw_barrel_attr_base_values",
        "hw_cooldown_attr",
        "tor_hw_fire_projectile",
        "tor_hw_fire_projectile_charge",
        "bor_hw_fire_projectile",
        "bor_hw_fire_beam",
        "vla_hw_fire_projectile",
        "mal_hw_fire_projectile",
    }
    post_seed_effects = [
        effect
        for effect in effects
        if not (
            effect.get("modifier_type") == "OverrideBaseValue"
            and effect.get("attribute") in seed_attributes
            and effect.get("source_aspect") in seed_sources
        )
    ]

    damage = _level_value(_number(base.get("damage"), 60.0) or 60.0, growth, level)
    damage = weapon.f32(damage * (_column(barrel, "damage_scale", default=1.0) or 1.0))
    damage = weapon.f32(damage * (_column(rarity_row, "damage_scale", default=1.0) or 1.0))
    damage = _apply_stat(damage, parts, model, rarity_stat, ("Damage",), ("Damage",))
    damage = _modify(damage, post_seed_effects, "weapon_damage", defaults)
    damage = weapon.f32(damage * _element_damage_scale(parts))

    fire_rate = _column(barrel, "firerate_value", "fire_rate")
    fire_rate = fire_rate if fire_rate is not None else (_override_value(effects, "weapon_fire_rate", defaults) or 1.0)
    fire_rate = _apply_stat(fire_rate, parts, model, rarity_stat, ("Fire_Rate",), ("FireRate", "fire_rate"))
    fire_rate = _modify(fire_rate, post_seed_effects, "weapon_fire_rate", defaults)
    magazine = _column(barrel, "magazinesize_value", "magazine_size")
    magazine = magazine if magazine is not None else (_override_value(effects, "weapon_max_loaded_ammo", defaults) or 1.0)
    magazine = _apply_stat(magazine, parts, model, rarity_stat, ("Max_Loaded_Ammo",), ("MagSize", "magazine_size"))
    magazine = _modify(magazine, post_seed_effects, "weapon_max_loaded_ammo", defaults)
    radius = _column(barrel, "damageradius_value", "damage_radius")
    radius = radius if radius is not None else (_override_value(effects, "weapon_damage_radius", defaults) or 0.0)
    radius = weapon.f32(radius * (_column(rarity_row, "radius_scale", default=1.0) or 1.0))
    radius = _apply_stat(radius, parts, model, rarity_stat, ("Damage_Radius",), ("DamageRadius", "damage_radius"))
    radius = _modify(radius, post_seed_effects, "weapon_damage_radius", defaults)
    cooldown = _column(barrel, "cooldown")
    cooldown = cooldown if cooldown is not None else (_override_value(effects, "gadget_cooldown", defaults) or 0.0)
    cooldown = weapon.f32(cooldown * (_column(rarity_row, "cooldown_scale", default=1.0) or 1.0))
    cooldown = _apply_stat(cooldown, parts, model, rarity_stat, ("Cooldown_Reduction",), ("cooldown", "cooldown_reduction"), invert=True)
    cooldown = _modify(cooldown, post_seed_effects, "gadget_cooldown", defaults)

    spread = _column(barrel, "spread_value", "spread", default=0.0) or 0.0
    impulse = _column(barrel, "accimpulse_value", "accuracy_impulse", default=0.2) or 0.2
    spread = _apply_stat(spread, parts, model, rarity_stat, ("Spread",), ("Accuracy", "Spread"), invert=True)
    impulse = _apply_stat(impulse, parts, model, rarity_stat, ("Accuracy_Impulse",), ("Accuracy", "AccuracyImpulse"), invert=True)
    spread = _modify(spread, post_seed_effects, "weapon_spread", defaults)
    impulse = _modify(impulse, post_seed_effects, "weapon_accuracy_impulse", defaults)
    accuracy_ui = model.get("accuracy_ui") or {}
    accuracy = weapon.accuracy_rating(
        spread,
        impulse,
        0.0,
        spread_weight=_number(accuracy_ui.get("spread_weight"), 0.75) or 0.75,
        spread_max=_number(accuracy_ui.get("spread_max"), 10.0) or 10.0,
        impulse_weight=_number(accuracy_ui.get("impulse_weight"), 0.25) or 0.25,
        impulse_max=_number(accuracy_ui.get("impulse_max"), 1.5) or 1.5,
        sway_weight=_number(accuracy_ui.get("sway_weight"), 0.1) or 0.1,
        sway_max=_number(accuracy_ui.get("sway_max"), 0.5) or 0.5,
    )

    crit = weapon.f32(
        _apply_stat(1.0, parts, model, rarity_stat, ("Critical_Damage",), ("CritDamage", "critical_damage")) - 1.0
    )
    crit = _modify(crit, post_seed_effects, "weapon_damage_modifier_add_critical_hit", defaults)
    projectiles = max(1, _round_int(_modify(1.0, post_seed_effects, "weapon_projectile_per_shot", defaults)))
    total_damage = weapon.f32(damage * projectiles)
    stats: dict[str, Any] = {
        "damage": weapon.format_damage(total_damage, projectiles),
        "dps": _round_int(total_damage * fire_rate),
        "accuracy": accuracy,
        "fire_rate": weapon.display_decimal(fire_rate),
        "magazine": max(1, ceil(magazine)),
    }
    if cooldown > 0:
        stats["cooldown"] = _round_int(cooldown)
    if crit:
        stats["critical_damage"] = _round_int(crit * 100.0)
    if radius > 0:
        stats["splash_radius"] = _round_int(radius)
    return stats


def equipment_card_stats_from_serial(
    decoded: str,
    index: dict[str, Any],
    item_type: str | None = None,
) -> dict[str, Any]:
    """Return the stat rows that the non-weapon item card can resolve offline."""
    root_id, level = _header(decoded)
    family, model, root = _family_model(index, root_id, item_type)
    parts = _parts(decoded, index, root_id)
    rarity = _rarity(parts)
    resolver = {
        "grenade": _grenade_stats,
        "shield": _shield_stats,
        "repkit": _repkit_stats,
        "heavy": _heavy_stats,
    }[family]
    return resolver(level, rarity, parts, index, model, root)


_PROPERTY_STATS = {
    "cooldowntime": "cooldown",
    "cooldown": "cooldown",
    "damage": "damage",
    "criticalhitchance": "critical_chance",
    "radius": "radius",
    "maxnumberofcharges": "charges",
    "capacity": "capacity",
    "regendelay": "recharge_delay",
    "regenrate": "recharge_rate",
    "segments": "armor_segments",
    "duration": "duration",
    "health": "healing",
    "maxcharges": "charges",
    "firerate": "fire_rate",
    "maxloadedammo": "magazine",
    "damageradius": "splash_radius",
}

_SINGLE_SLOT_CATEGORIES = {
    "inv_comp",
    "body",
    "barrel",
    "payload",
    "element",
    "firmware",
    "unique",
    "body_ele",
    "secondary_ele",
    "pearl_elem",
    "pearl_stat",
}


def _ref_name(value: Any) -> str:
    text = str(value or "").strip().rstrip("'")
    if "'" in text:
        text = text.rsplit("'", 1)[-1]
    return text.rsplit("/", 1)[-1].casefold()


def _stat_number(stats: dict[str, Any], key: str) -> float | None:
    value = stats.get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value or "").replace(",", ""))
    return float(match.group()) if match else None


def _candidate_serial(decoded: str, index: dict[str, Any], root_id: str, ref_key: str) -> str:
    refs = index.get("part_refs") or {}
    target = refs.get(ref_key) or {}
    if not target or ref_key in weapon._serial_part_keys(decoded, root_id):
        return decoded
    target_owner, target_id = ref_key.split(":", 1)
    target_category = target.get("category")
    inserted = False

    if target_category not in _SINGLE_SLOT_CATEGORIES:
        token = f"{{{target_id}}}" if target_owner == root_id else f"{{{target_owner}:{target_id}}}"
        split = decoded.rfind("|")
        return f"{decoded[:split].rstrip()} {token}{decoded[split:]}" if split >= 0 else f"{decoded.rstrip()} {token}"

    def replace(match: re.Match[str]) -> str:
        nonlocal inserted
        token = match.group(1)
        owner, separator, payload = token.partition(":")
        owner = owner.strip()
        if not separator:
            keys = [f"{root_id}:{owner}"] if owner.isdigit() else []
        else:
            keys = [f"{owner}:{part_id}" for part_id in re.findall(r"\d+", payload)] if owner.isdigit() else []
        replace_ids = [key for key in keys if (refs.get(key) or {}).get("category") == target_category]
        if not replace_ids:
            return match.group(0)
        if owner == target_owner:
            ids = [key.split(":", 1)[1] for key in keys if key not in replace_ids]
            ids.append(target_id)
            inserted = True
            if owner == root_id:
                return f"{{{target_id}}}"
            return f"{{{owner}:{ids[0]}}}" if len(ids) == 1 else f"{{{owner}:[{' '.join(ids)}]}}"
        remaining = [key.split(":", 1)[1] for key in keys if key not in replace_ids]
        if not remaining:
            return ""
        return f"{{{owner}:{remaining[0]}}}" if len(remaining) == 1 else f"{{{owner}:[{' '.join(remaining)}]}}"

    candidate = re.sub(r"\{([^{}]+)\}", replace, decoded)
    if inserted:
        return candidate
    token = f"{{{target_id}}}" if target_owner == root_id else f"{{{target_owner}:{target_id}}}"
    split = candidate.rfind("|")
    return f"{candidate[:split].rstrip()} {token}{candidate[split:]}" if split >= 0 else f"{candidate.rstrip()} {token}"


def _augment_value(model: dict[str, Any], parts: list[dict[str, Any]], tag: str, index: int) -> float | None:
    suffix = _norm(tag).removeprefix("unv").removeprefix("eng").removeprefix("ra")
    matches: list[dict[str, Any]] = []
    for part in parts:
        initializer = (model.get("part_initializers") or {}).get(str(part.get("_ref_key") or "")) or {}
        row_norm = _norm(initializer.get("row"))
        if row_norm and (row_norm == suffix or row_norm in suffix or suffix in row_norm):
            matches.append(initializer)
    if not matches:
        return None
    roles = {_norm(item.get("role")) for item in matches}
    role = "both" if any("primary" in item for item in roles) and any("secondary" in item for item in roles) else (
        "primary" if any("primary" in item for item in roles) else "secondary"
    )
    table_hint = "universal" if _norm(tag).startswith("unv") else "energy" if _norm(tag).startswith("eng") else "armor"
    row_name = str(matches[0].get("row") or "")
    column = f"augment_{role}" + (f"_{index + 1}" if index else "")
    for table, rows in (model.get("payloads") or {}).items():
        if table_hint not in _norm(table) or "init" in _norm(table):
            continue
        value = _column(_row(rows, row_name), column)
        if value is not None:
            return value
    return None


def _safe_arithmetic(expression: str, values: dict[str, float]) -> float | None:
    binary = {
        ast.Add: lambda a, b: a + b,
        ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b,
        ast.Pow: lambda a, b: a**b,
    }
    unary = {ast.UAdd: lambda a: a, ast.USub: lambda a: -a}

    def walk(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name) and node.id in values:
            return values[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in binary:
            return binary[type(node.op)](walk(node.left), walk(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in unary:
            return unary[type(node.op)](walk(node.operand))
        raise ValueError("unsupported expression")

    try:
        return float(walk(ast.parse(expression, mode="eval")))
    except (ArithmeticError, SyntaxError, ValueError):
        return None


def _datatable_part_scale(value: float, datatable: dict[str, Any], parts: list[dict[str, Any]]) -> float:
    wanted = (
        _norm(_ref_name(datatable.get("datatable"))),
        _norm(datatable.get("rowname")),
        _norm(datatable.get("columnname")),
    )
    for part in parts:
        for modifier in [*part.get("weapon_attribute_effects", []), *part.get("weapon_stat_modifiers", [])]:
            constant = _number(modifier.get("constant"))
            if constant is None:
                continue
            for ref in modifier.get("datatable_refs", []):
                current = (_norm(_ref_name(ref.get("table"))), _norm(ref.get("row")), _norm(ref.get("column")))
                if current == wanted:
                    return value * constant * (_number(modifier.get("basescale"), 1.0) or 1.0) * (
                        _number(modifier.get("postscale"), 1.0) or 1.0
                    )
    return value


def _display_uistat_number(value: float, attribute: str, template: str, arg: dict[str, Any], lang: str) -> str:
    attr = _norm(attribute)
    lower = template.casefold()
    augment_percent = bool(arg.get("_inventory_augment")) and abs(value) <= 1.0 and not any(
        marker in attr for marker in ("count", "segment", "radius", "duration", "time", "target", "missile", "charge")
    )
    percent_context = any(
        marker in lower
        for marker in ("chance", "resistance", "increase", "reduced", "decrease", "几率", "抗性", "增加", "提升", "降低", "减少")
    ) or augment_percent
    if abs(value) <= 1.0 and (percent_context or any(marker in attr for marker in ("chance", "scale", "percent", "resist", "movespeed"))):
        reduced = any(marker in lower for marker in ("reduced", "decrease", "降低", "减少"))
        increased = any(marker in lower for marker in ("increase", "增加", "提升"))
        resistance = any(marker in lower for marker in ("resistance", "抗性"))
        value = abs(value) if reduced or resistance else value
        sign = "+" if not reduced and (increased or resistance) and value >= 0 else ""
        rendered = f"{sign}{abs(_round_int(value * 100.0)) if reduced or resistance else _round_int(value * 100.0)}%"
    elif any(marker in attr for marker in ("damage", "dmg", "dps")) and abs(value) >= 1.0:
        rendered = f"{round(value):,}"
    elif abs(value - round(value)) < 0.0001:
        rendered = f"{round(value):,}"
    else:
        rendered = f"{value:.2f}".rstrip("0").rstrip(".")
    formattext = arg.get("formattext") or {}
    fmt = formattext.get("zh" if lang == "zh-CN" else "en") or formattext.get("en") or "$VALUE$"
    if fmt in {"$VALUE$", "$VALUE$s", "$VALUE$秒"}:
        return rendered
    return str(fmt).replace("$VALUE$", rendered)


def _placeholder_context(text: str, placeholder: str) -> str:
    marker = f"{{{placeholder}}}"
    position = text.find(marker)
    if position < 0:
        return text
    start = max(text.rfind(separator, 0, position) for separator in (",", "，", ";", "；", ".", "。")) + 1
    ends = [text.find(separator, position + len(marker)) for separator in (",", "，", ";", "；", ".", "。")]
    end = min((value for value in ends if value >= 0), default=len(text))
    return text[start:end]


def equipment_part_uistat_descriptions(
    decoded: str,
    index: dict[str, Any],
    item_type: str,
    ref_key: str,
    lang: str = "zh-CN",
    *,
    with_ids: bool = False,
) -> list[Any]:
    """Render official non-weapon part UIStats against the candidate serial; empty means CSV fallback."""
    root_id, level = _header(decoded)
    candidate = _candidate_serial(decoded, index, root_id, ref_key)
    family, model, _root = _family_model(index, root_id, item_type)
    parts = _parts(candidate, index, root_id)
    stats = equipment_card_stats_from_serial(candidate, index, item_type)
    resolvers = model.get("attribute_resolvers") or {}
    target = {**((index.get("part_refs") or {}).get(ref_key) or {}), "_ref_key": ref_key}
    rarity_stat = _rarity_stat_scale(index, _rarity(parts))
    defaults = model.get("attribute_defaults") or {}
    resolving: set[str] = set()
    cache: dict[str, float | None] = {}

    def display_modifier(attribute: str) -> float | None:
        stat = {
            "grenade_gadget_crit_chance": (("CritChance",), ("CritChance", "CriticalChance", "critical_chance")),
            "grenade_damage_modifier_base_status_effect_chance": (("StatusChance",), ("ElementalPower", "StatusChance", "status_chance")),
            "grenade_damage_modifier_base_status_effect_damage": (("StatusDamage",), ("ElementalPower", "StatusDamage", "status_damage")),
            "grenade_gadget_force": (("Force",), ("Force",)),
            "grenade_gadget_transfusion_percent": (("Transfusion",), ("Transfusion",)),
            "grenade_gadget_radius": (("Radius",), ("DamageRadius", "splash_radius", "radius")),
        }.get(attribute)
        if stat:
            value = _apply_stat(1.0, [target], model, rarity_stat, *stat) - 1.0
            if value:
                return value
        if attribute == "grenade_gadget_homing_turn_speed_scale":
            value = _modify(1.0, _effects([target], include_base_body=True), attribute, defaults) - 1.0
            return value if value else None
        if attribute == "grenade_damage_amp_duration":
            value = _modify(0.0, _effects(parts, include_base_body=True), attribute, defaults)
            return value if value else None
        return None

    def property_value(path: str, attribute: str) -> float | None:
        normalized = _norm(path)
        if normalized == "healthinstantpct":
            total = _stat_number(stats, "healing")
            instant = _stat_number(stats, "instant_healing")
            return instant / total if total and instant is not None else None
        if normalized == "healthovertimepct":
            total = _stat_number(stats, "healing")
            overtime = _stat_number(stats, "health_over_time")
            return overtime / total if total and overtime is not None else None
        if normalized == "projectilespershot":
            match = re.search(r"[x×](\d+)", str(stats.get("damage", "")), re.I)
            return float(match.group(1)) if match else 1.0
        if normalized == "criticalhitmultiplier":
            crit = _stat_number(stats, "critical_damage")
            return 1.0 + crit / 100.0 if crit is not None else None
        if normalized == "criticalhitchance":
            chance = _stat_number(stats, "critical_chance")
            return chance / 100.0 if chance is not None else None
        return _stat_number(stats, _PROPERTY_STATS.get(normalized, attribute))

    def atom(node: Any) -> float | None:
        if isinstance(node, (int, float)) and not isinstance(node, bool):
            return float(node)
        if not isinstance(node, dict):
            return None
        if node.get("attribute"):
            value = resolve_attribute(_ref_name(node["attribute"]))
            if value is not None:
                return value
        datatable = node.get("datatablevalue") or {}
        if (value := _number(datatable.get("resolved_value"))) is not None:
            return value
        return _number(node.get("constant"))

    def expression_value(expression: dict[str, Any]) -> float | None:
        formula = str(expression.get("formula") or "")
        values: dict[str, float] = {}

        def attr_replacement(match: re.Match[str]) -> str:
            key = f"a{len(values)}"
            value = resolve_attribute(_ref_name(match.group(1)))
            if value is None:
                raise ValueError("unresolved attribute")
            values[key] = value
            return key

        try:
            formula = re.sub(r"\battr\(\s*([^()]+?)\s*\)", attr_replacement, formula, flags=re.I)
        except ValueError:
            return None
        pairs = (((expression.get("variables") or {}).get("variablevalues") or {}).get("pairs") or {})
        for pair in pairs.values() if isinstance(pairs, dict) else ():
            name = str(pair.get("key") or "")
            raw = ((pair.get("value") or {}).get("value") or {})
            value = resolve_attribute(_ref_name(raw.get("value"))) if _norm(raw.get("type")) == "attribute" else _number(raw.get("value"))
            if name and value is not None:
                values[name] = value
        return _safe_arithmetic(formula, values)

    def resolve_attribute(name: str) -> float | None:
        name = _ref_name(name)
        if name in {"inventory_experience_level", "weapon_level"}:
            return float(level)
        if name == "att_uistat_repkit_bor_hugger_dps":
            damage = resolve_attribute("att_damage_repkit_bor_hugger")
            tick = resolve_attribute("att_repkit_bor_hugger_damage_scale")
            return damage / tick if damage is not None and tick else None
        if name in cache:
            return cache[name]
        if name in resolving:
            return None
        resolving.add(name)
        definition = (resolvers.get(name) or {}).get("definition") or {}
        value = definition.get("value") or {}
        kind = _norm(value.get("structtype"))
        result: float | None = None
        if "propertyvalueresolver" in kind:
            result = property_value(str((value.get("property") or {}).get("propertypath") or ""), name)
        elif "datatablevalueresolver" in kind:
            result = atom(value)
            if result is not None:
                result = _datatable_part_scale(result, value.get("datatablevalue") or {}, parts)
        elif "constantattributevalueresolver" in kind:
            initial = value.get("attributeinit") or {}
            result = atom(initial)
            if result is not None:
                result *= _number(initial.get("basescale"), 1.0) or 1.0
                result *= _number(initial.get("postscale"), 1.0) or 1.0
        elif "balanceformulavalueresolver" in kind:
            multiplier, balance_level, power = atom(value.get("multiplier")), atom(value.get("level")), atom(value.get("power"))
            if multiplier is not None and balance_level is not None and power is not None:
                scalar = atom(value.get("scalar"))
                result = multiplier * (balance_level**power) * (1.0 if scalar is None else scalar)
        elif "inventoryaugmentattributevalueresolver" in kind:
            result = _augment_value(model, parts, str(value.get("augmenttag") or ""), int(value.get("augmentindex") or 0))
            if result is not None and any(
                _ref_name(effect.get("value_attribute")) == name
                and str(effect.get("modifier_type") or "ScaleSimple") == "ScaleMultiply"
                for part in parts
                for effect in part.get("weapon_attribute_effects", [])
            ):
                result -= 1.0
        elif "inventorystatscontainervalueresolver" in kind:
            inventory_effects = _effects(parts, include_base_body=True)
            if name == "grenade_mirv_count" and any(
                part.get("_ref_key") == "245:29" or _norm(part.get("part")) == "part01mirv" for part in parts
            ):
                result = _modify(4.0, inventory_effects, name, defaults)
            elif any(
                effect.get("attribute") == name and _effect_value(effect, defaults) is not None
                for effect in inventory_effects
            ):
                result = _modify(0.0, inventory_effects, name, defaults)
        elif "expressionvalueresolver" in kind:
            result = expression_value(value.get("expression") or {})
        resolving.remove(name)
        cache[name] = result
        return result

    part = (index.get("part_refs") or {}).get(ref_key) or {}
    ui_ids = list(dict.fromkeys(part.get("uistats_include") or part.get("uistats", [])))
    output: list[Any] = []
    for ui_id in ui_ids:
        ui_key = str(ui_id).casefold()
        if any(marker in ui_key for marker in ("redtext", "red_text", "typeline")):
            continue
        ui = (model.get("ui_stats") or {}).get(ui_key) or (index.get("uistats") or {}).get(ui_key) or {}
        text = str(ui.get("zh" if lang == "zh-CN" else "en") or ui.get("en") or "")
        placeholders = set(re.findall(r"\{(\w+)\}", text))
        args = ((ui.get("statvalue") or {}).get("args") or {})
        folded = {str(key).casefold(): value for key, value in args.items()}
        for placeholder in placeholders:
            arg = args.get(placeholder)
            if not isinstance(arg, dict):
                arg = folded.get(placeholder.casefold())
            arg = arg if isinstance(arg, dict) else {}
            attribute = _ref_name(arg.get("attribute"))
            value = display_modifier(attribute) if attribute else None
            if value is None:
                value = resolve_attribute(attribute) if attribute else None
            if value is None:
                # Augment rolls, level formulas and runtime expressions have no
                # static value. Dropping the sentence made the row fall back to
                # "No stat changes", which falsely denies the augment does
                # anything, so mark the one unknown quantity and keep the effect.
                text = text.replace(f"{{{placeholder}}}", "?")
                continue
            resolver_kind = _norm((((resolvers.get(attribute) or {}).get("definition") or {}).get("value") or {}).get("structtype"))
            display_arg = {**arg, "_inventory_augment": "inventoryaugmentattributevalueresolver" in resolver_kind}
            text = text.replace(
                f"{{{placeholder}}}",
                _display_uistat_number(value, attribute, _placeholder_context(text, placeholder), display_arg, lang),
            )
        text = " ".join(re.sub(r"\[[^\]]+\]", "", text).split())
        if text and not any((entry.get("text") if isinstance(entry, dict) else entry) == text for entry in output):
            output.append({"uistat": ui_key, "text": text} if with_ids else text)
    return output
