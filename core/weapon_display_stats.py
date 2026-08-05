"""Verified BL4 weapon item-card evaluator used by the save editor."""

from __future__ import annotations

from math import ceil, floor
import re
from struct import pack, unpack
from typing import Any, Iterable


RARITY_STAT_SCALE = {
    "common": 1.0,
    "uncommon": 1.2,
    "rare": 1.4,
    "epic": 1.6,
    "legendary": 1.65,
    "pearl": 1.65,
    "pearlescent": 1.65,
}

WEAPON_TYPE_BY_ROOT_SUFFIX = {"ps": "Pistol", "sg": "Shotgun", "ar": "AssaultRifle", "sm": "SMG", "sr": "Sniper"}
PRIMARY_ELEMENT_COMPONENTS = frozenset(range(10, 15))
ELEMENT_NAMES = ("corrosive", "cryo", "fire", "radiation", "shock")
STATUS_APPLICATION_DEFAULTS = {
    "corrosive": {"dps_scalar": 0.155, "chance": 0.05},
    "cryo": {"dps_scalar": 0.0},
    "fire": {"dps_scalar": 0.2, "chance": 0.05},
    "radiation": {"dps_scalar": 0.13, "chance": 0.05},
    "shock": {"dps_scalar": 0.38, "chance": 0.05},
}
STATUS_CHANCE_BASE_BY_TYPE = {
    "Pistol": 0.105,
    "Shotgun": 0.065,
    "AssaultRifle": 0.095,
    "SMG": 0.08,
    "Sniper": 0.2,
}
CRYO_IMPACT_BASE_BY_TYPE = {
    "Pistol": 1.05,
    "Shotgun": 1.0,
    "AssaultRifle": 1.075,
    "SMG": 0.9,
    "Sniper": 1.25,
}
STATUS_STAT_FALLBACKS = {
    "damage": {"scalar": 0.1, "manufacturer_multipliers": {"borg": 1.15, "maliwan": 1.35}},
    "chance": {"scalar": 0.2, "manufacturer_multipliers": {"borg": 1.4, "maliwan": 1.2}},
    "cryo": {"scalar": 0.125, "manufacturer_multipliers": {}},
}
ACCURACY_IMPULSE_SCALAR = 0.015
ACCURACY_IMPULSE_MANUFACTURER_MULTIPLIERS = {"order": 1.1}
ACCURACY_UI = {
    "Pistol": (0.75, 10.0, 0.25, 1.5, 0.1, 0.5),
    "SMG": (0.75, 10.0, 0.25, 1.5, 0.1, 0.5),
    "AssaultRifle": (0.75, 10.0, 0.25, 1.5, 0.1, 0.5),
    "Shotgun": (0.95, 17.0, 0.05, 1.5, 0.1, 0.5),
    "Sniper": (0.9, 15.0, 0.1, 2.5, 0.1, 0.5),
}
BARREL_ACCIMPULSE_DEFAULT = 0.2
BARREL_DAMAGE_SCALE_DEFAULT = 1.0
ADS_BASE_TIME = {"Pistol": 0.2, "SMG": 0.2, "Shotgun": 0.2, "AssaultRifle": 0.3, "Sniper": 0.3}
EQUIP_TIME_BASE = {"Pistol": 1.15, "SMG": 1.15, "Shotgun": 1.25, "AssaultRifle": 1.4, "Sniper": 1.4}


def f32(value: float) -> float:
    """Round exactly as a single-precision game-side intermediate."""
    return unpack("<f", pack("<f", value))[0]


def _serial_part_keys(decoded: str, root_id: str) -> list[str]:
    keys: list[str] = []
    for token in re.findall(r"\{([^{}]+)\}", decoded):
        group, separator, payload = token.partition(":")
        if not separator:
            if group.strip().isdigit():
                keys.append(f"{root_id}:{group.strip()}")
            continue
        if group.strip().isdigit():
            keys.extend(f"{group.strip()}:{part_id}" for part_id in re.findall(r"\d+", payload))
    return keys


def _serial_parts(decoded: str, index: dict[str, Any], root_id: str) -> list[dict[str, Any]]:
    refs = index["part_refs"]
    return [refs[key] for key in _serial_part_keys(decoded, root_id) if key in refs]


def _serial_behavior_parts(decoded: str, index: dict[str, Any], root_id: str) -> list[dict[str, Any]]:
    parts = _serial_parts(decoded, index, root_id)
    refs = index["part_refs"]
    forced = [refs[key] for part in parts for key in part.get("forced_behavior_part_refs", []) if key in refs]
    return parts + [part for part in forced if part not in parts]


def _is_elemental_serial(decoded: str) -> bool:
    components = [
        int(part_id)
        for token in re.findall(r"\{1:([^{}]+)\}", decoded)
        for part_id in re.findall(r"\d+", token)
    ]
    return any(component in PRIMARY_ELEMENT_COMPONENTS for component in components)


def _scaled_stat_group(
    base: float,
    points: Iterable[float],
    per_point: float,
    rarity: str | float,
    multiplier: float = 1.0,
) -> float:
    rarity_scale = RARITY_STAT_SCALE[rarity.lower()] if isinstance(rarity, str) else rarity
    scale_add = 0.0
    for point_value in points:
        contribution = f32(f32(f32(point_value) * f32(per_point)) * f32(multiplier))
        contribution = f32(contribution * f32(rarity_scale))
        scale_add = f32(scale_add + contribution)
    return f32(f32(base) * f32(1.0 + scale_add))


def scaled_stat(base: float, points: float, per_point: float, rarity: str | float, multiplier: float = 1.0) -> float:
    """Apply one InventoryStat ScaleAdd contribution to an overridden base."""
    return _scaled_stat_group(base, (points,), per_point, rarity, multiplier)


def display_decimal(value: float, precision: int = 1) -> float:
    """Round a positive finalized stat the way NumericDisplayValue presents it."""
    scale = 10**precision
    return f32(floor(f32(value) * scale + 0.5) / scale)


def fire_rate(base: float, points: float, rarity: str | float, manufacturer_multiplier: float = 1.0) -> float:
    return display_decimal(scaled_stat(base, points, 0.05, rarity, manufacturer_multiplier))


def reload_time(base: float, points: float, rarity: str | float, manufacturer_multiplier: float = 1.0) -> float:
    """ReloadSpeed stat points reduce the overridden reload/repair duration."""
    return display_decimal(scaled_stat(base, -points, 0.06, rarity, manufacturer_multiplier))


def accuracy_rating(
    spread: float,
    accuracy_impulse: float,
    sway: float,
    *,
    spread_weight: float,
    spread_max: float,
    impulse_weight: float,
    impulse_max: float,
    sway_weight: float,
    sway_max: float,
) -> int:
    """Evaluate weapon_accuracy_ui_compare and return its integer percent row."""

    def contribution(weight: float, value: float, maximum: float) -> float:
        normalized = f32(min(abs(f32(value)), f32(maximum)) / f32(maximum))
        return f32(f32(weight) * f32(1.0 - normalized))

    numerator = f32(contribution(spread_weight, spread, spread_max) + contribution(impulse_weight, accuracy_impulse, impulse_max))
    numerator = f32(numerator + contribution(sway_weight, sway, sway_max))
    denominator = f32(f32(spread_weight) + f32(impulse_weight))
    denominator = f32(denominator + f32(sway_weight))
    return floor(f32(f32(numerator / denominator) * 100.0) + 0.5)


def magazine_capacity(base: float, points: float, rarity: str | float, manufacturer_multiplier: float = 1.0) -> int:
    """Max-loaded-ammo UI uses the upward integer row (not the compare row)."""
    return ceil(scaled_stat(base, points, 0.15, rarity, manufacturer_multiplier))


def weapon_damage(
    level: int,
    rarity: str | float,
    *,
    barrel_scale: float,
    damage_stat_points: float = 0.0,
    damage_stat_groups: Iterable[Iterable[float]] | None = None,
    scale_multipliers: Iterable[float] = (),
    weapon_type_scale: float = 1.0,
    elemental: bool = False,
    projectiles: float = 1.0,
    base_damage: float = 6.0,
    level_growth: float = 1.09,
    damage_per_stat_point: float = 0.075,
    damage_stat_multiplier: float = 1.0,
) -> float:
    """Evaluate finalized weapon_damage_per_shot using game-like float order."""
    if level < 1:
        raise ValueError("level must be at least 1")

    value = f32(base_damage)
    value = f32(value * f32(f32(level_growth) ** level))
    value = f32(value * f32(weapon_type_scale))
    value = f32(value * f32(barrel_scale))

    point_groups = damage_stat_groups if damage_stat_groups is not None else ((damage_stat_points,),)
    for points in point_groups:
        value = _scaled_stat_group(value, points, damage_per_stat_point, rarity, damage_stat_multiplier)
    for multiplier in scale_multipliers:
        value = f32(value * f32(multiplier))
    if elemental:
        value = f32(value * f32(0.8))
    return f32(value * f32(projectiles))


def weapon_damage_from_serial(
    decoded: str,
    index: dict[str, Any],
    *,
    elemental: bool | None = None,
    projectiles: float | None = None,
    mode_bit: int = 1,
) -> float:
    """Resolve the confirmed damage inputs from a decoded serial and name index."""
    header = re.match(r"\s*(\d+)\s*,\s*\d+\s*,\s*\d+\s*,\s*(\d+)", decoded)
    if not header:
        raise ValueError("invalid decoded weapon serial")
    root_id, level_text = header.groups()
    parts = _serial_parts(decoded, index, root_id)
    if elemental is None:
        elemental = _is_elemental_serial(decoded)

    rarity = next((part.get("rarity") for part in parts if part.get("rarity")), None)
    if not rarity:
        raise ValueError("serial has no indexed rarity component")

    barrel = next((part for part in parts if part.get("category") == "barrel"), None)
    if not barrel:
        raise ValueError("serial has no indexed barrel")
    barrel_scale = next(
        (
            float(ref["values"]["damage_scale"])
            for ref in barrel.get("weapon_base_value_refs", [])
            if ref.get("values", {}).get("damage_scale") is not None
        ),
        float(index.get("weapon_native_model", {}).get("attribute_defaults", {}).get("barrel_damage_scale", BARREL_DAMAGE_SCALE_DEFAULT)),
    )
    if projectiles is None:
        projectiles = next(
            (
                float(ref["values"]["projectilespershot_value"])
                for ref in barrel.get("weapon_base_value_refs", [])
                if ref.get("values", {}).get("projectilespershot_value") is not None
            ),
            1.0,
        )

    damage_stat_groups = _stat_modifier_groups(parts, "Damage", mode_bit)

    native_model = index["weapon_native_model"]
    item_model = native_model["items"][root_id]
    provider = item_model["stats"].removesuffix("_weapon")
    stat_multiplier = native_model["stats"]["Damage"].get("manufacturer_multipliers", {}).get(provider, 1.0)
    root_suffix = item_model["root"].rsplit("_", 1)[-1]
    type_scale = native_model["type_initializers"].get(WEAPON_TYPE_BY_ROOT_SUFFIX[root_suffix], {}).get("Damage", 1.0)

    scale_multipliers = []
    for part in parts:
        for effect in part.get("weapon_attribute_effects", []):
            if effect.get("attribute") != "weapon_damage" or effect.get("modifier_type") != "ScaleMultiply":
                continue
            mode = effect.get("use_mode_bitmask")
            if mode is not None and not int(mode) & mode_bit:
                continue
            value = effect.get("constant")
            if value is None:
                value = next((ref.get("value") for ref in effect.get("datatable_refs", []) if ref.get("value") is not None), None)
            if value is not None:
                scale_multipliers.append(float(value))

    return weapon_damage(
        int(level_text),
        rarity,
        barrel_scale=barrel_scale,
        damage_stat_groups=damage_stat_groups,
        damage_stat_multiplier=stat_multiplier,
        scale_multipliers=scale_multipliers,
        weapon_type_scale=type_scale,
        elemental=elemental,
        projectiles=projectiles,
    )


def critical_damage_from_serial(decoded: str, index: dict[str, Any]) -> int:
    """Resolve the signed critical-damage percentage shown on the item card."""
    header = re.match(r"\s*(\d+)\s*,\s*\d+\s*,\s*\d+\s*,\s*\d+", decoded)
    if not header:
        raise ValueError("invalid decoded weapon serial")
    root_id = header.group(1)
    parts = _serial_parts(decoded, index, root_id)
    rarity = next((part.get("rarity") for part in parts if part.get("rarity")), None)
    if not rarity:
        raise ValueError("serial has no indexed rarity component")

    model = index["weapon_native_model"]
    item = model["items"][root_id]
    root_suffix = item["root"].rsplit("_", 1)[-1]
    weapon_type = WEAPON_TYPE_BY_ROOT_SUFFIX[root_suffix]
    total = f32(model["type_initializers"].get(weapon_type, {}).get("CritDamage", 0.0))
    total = f32(total + f32(model["manufacturer_initializers"].get(item["manufacturer"].title(), {}).get("CritDamage", 0.0)))

    for part in parts:
        for effect in part.get("weapon_attribute_effects", []):
            if effect.get("attribute") != "weapon_damage_modifier_add_critical_hit" or effect.get("modifier_type") != "PreAdd":
                continue
            if not int(effect.get("use_mode_bitmask", 1)) & 1:
                continue
            value = effect.get("constant")
            if value is None:
                value = next((ref.get("value") for ref in effect.get("datatable_refs", []) if ref.get("value") is not None), None)
            if value is not None:
                total = f32(total + f32(float(value)))

    provider = item["stats"].removesuffix("_weapon")
    stat = model["stats"]["CritDamage"]
    point_multiplier = stat.get("manufacturer_multipliers", {}).get(provider, 1.0)
    points = 0.0
    for part in parts:
        for modifier in part.get("weapon_stat_modifiers", []):
            if modifier.get("attr") != "CritDamage" or not int(modifier.get("use_mode_bitmask", 1)) & 1:
                continue
            value = modifier.get("constant")
            if value is None:
                value = next((ref.get("value") for ref in modifier.get("datatable_refs", []) if ref.get("value") is not None), None)
            if value is not None:
                points = f32(points + f32(float(value)))
    bonus = f32(f32(f32(points * f32(stat["scalar"])) * f32(point_multiplier)) * f32(RARITY_STAT_SCALE[rarity.lower()]))
    total = f32(total + bonus)
    percent = f32(total * 100.0)
    return floor(percent + 0.5) if percent >= 0 else ceil(percent - 0.5)


def ammo_cost_from_serial(decoded: str, index: dict[str, Any]) -> int:
    """Return weapon_shot_cost, whose native default is one."""
    header = re.match(r"\s*(\d+)", decoded)
    if not header:
        raise ValueError("invalid decoded weapon serial")
    root_id = header.group(1)
    value = 1.0
    for part in _serial_behavior_parts(decoded, index, root_id):
        for effect in part.get("weapon_attribute_effects", []):
            if effect.get("attribute") != "weapon_shot_cost" or effect.get("modifier_type") != "OverrideBaseValue":
                continue
            if not int(effect.get("use_mode_bitmask", 1)) & 1:
                continue
            resolved = effect.get("constant")
            if resolved is None:
                resolved = next((ref.get("value") for ref in effect.get("datatable_refs", []) if ref.get("value") is not None), None)
            if resolved is not None:
                value = float(resolved)
    return ceil(value)


def accuracy_from_serial(decoded: str, index: dict[str, Any]) -> int:
    """Evaluate the confirmed item-card Accuracy inputs from a decoded serial."""
    parts, rarity, provider, model, item = _serial_stat_context(decoded, index)
    root_suffix = item["root"].rsplit("_", 1)[-1]
    weapon_type = WEAPON_TYPE_BY_ROOT_SUFFIX[root_suffix]
    barrel = next((part for part in parts if part.get("category") == "barrel"), None)
    if not barrel:
        raise ValueError("serial has no indexed barrel")
    base_values = next(
        (ref.get("values", {}) for ref in barrel.get("weapon_base_value_refs", []) if ref.get("values")),
        {},
    )
    spread = float(base_values.get("spread_value", 0.0))
    impulse = float(base_values.get("accimpulse_value", BARREL_ACCIMPULSE_DEFAULT))
    stat = model["stats"]["Accuracy"]
    spread = _scaled_stat_from_parts(
        spread,
        parts,
        "Accuracy",
        stat["scalar"],
        rarity,
        stat.get("manufacturer_multipliers", {}).get(provider, 1.0),
        invert=True,
    )
    impulse = _scaled_stat_from_parts(
        impulse,
        parts,
        "Accuracy",
        ACCURACY_IMPULSE_SCALAR,
        rarity,
        ACCURACY_IMPULSE_MANUFACTURER_MULTIPLIERS.get(provider, 1.0),
        invert=True,
    )
    for part in parts:
        for effect in part.get("weapon_attribute_effects", []):
            if effect.get("modifier_type") != "ScaleMultiply" or not int(effect.get("use_mode_bitmask", 1)) & 1:
                continue
            value = _effect_value(effect)
            if value is None:
                continue
            if effect.get("attribute") == "weapon_spread":
                spread = f32(spread * f32(value))
            elif effect.get("attribute") == "weapon_accuracy_impulse":
                impulse = f32(impulse * f32(value))
    spread_weight, spread_max, impulse_weight, impulse_max, sway_weight, sway_max = ACCURACY_UI[weapon_type]
    # WidthScale/HeightScale live only in FWeaponBehaviorDef_Sway and are not retained by the runtime behavior.
    return accuracy_rating(
        spread,
        impulse,
        0.0,
        spread_weight=spread_weight,
        spread_max=spread_max,
        impulse_weight=impulse_weight,
        impulse_max=impulse_max,
        sway_weight=sway_weight,
        sway_max=sway_max,
    )


def format_damage(total_damage: float, projectiles: int = 1) -> str:
    """Format the item-card damage row from finalized damage-per-shot."""
    if projectiles < 1:
        raise ValueError("projectiles must be at least 1")
    per_projectile = f32(f32(total_damage) / f32(projectiles))
    rounded = floor(per_projectile + 0.5)
    return f"{rounded}x{projectiles}" if projectiles > 1 else str(rounded)


def _serial_stat_context(
    decoded: str, index: dict[str, Any]
) -> tuple[list[dict[str, Any]], str, str, dict[str, Any], dict[str, Any]]:
    header = re.match(r"\s*(\d+)", decoded)
    if not header:
        raise ValueError("invalid decoded weapon serial")
    root_id = header.group(1)
    parts = _serial_parts(decoded, index, root_id)
    rarity = next((part.get("rarity") for part in parts if part.get("rarity")), None)
    if not rarity:
        raise ValueError("serial has no indexed rarity component")
    item = index["weapon_native_model"]["items"][root_id]
    return parts, rarity, item["stats"].removesuffix("_weapon"), index["weapon_native_model"], item


def _effect_value(effect: dict[str, Any], attribute_defaults: dict[str, float] | None = None) -> float | None:
    value_attribute = effect.get("value_attribute")
    if value_attribute and attribute_defaults and value_attribute in attribute_defaults:
        return float(attribute_defaults[value_attribute])
    value = effect.get("constant")
    if value is None:
        value = next((ref.get("value") for ref in effect.get("datatable_refs", []) if ref.get("value") is not None), None)
    if value is None and attribute_defaults:
        value = attribute_defaults.get(effect.get("attribute"))
    return float(value) if value is not None else None


def _stat_points(parts: list[dict[str, Any]], attr: str, mode_bit: int = 1) -> float:
    base_points, mode_points = _stat_point_groups(parts, attr, mode_bit)
    return f32(base_points + mode_points)


def _stat_point_groups(parts: list[dict[str, Any]], attr: str, mode_bit: int = 1) -> tuple[float, float]:
    return tuple(
        _sum_f32(group)
        for group in _stat_modifier_groups(parts, attr, mode_bit)
    )


def _sum_f32(values: Iterable[float]) -> float:
    total = 0.0
    for value in values:
        total = f32(total + f32(value))
    return total


def _stat_modifier_groups(
    parts: list[dict[str, Any]],
    attr: str,
    mode_bit: int = 1,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    points: list[list[float]] = [[], []]
    for part in parts:
        for modifier in part.get("weapon_stat_modifiers", []):
            if modifier.get("attr") != attr:
                continue
            mode = modifier.get("use_mode_bitmask")
            if mode is not None and not int(mode) & mode_bit:
                continue
            value = _effect_value(modifier)
            if value is not None:
                group = int(mode is not None)
                points[group].append(value)
    return tuple(points[0]), tuple(points[1])


def _scaled_stat_from_parts(
    base: float,
    parts: list[dict[str, Any]],
    attr: str,
    per_point: float,
    rarity: str | float,
    multiplier: float = 1.0,
    *,
    invert: bool = False,
    mode_bit: int = 1,
) -> float:
    value = f32(base)
    for points in _stat_modifier_groups(parts, attr, mode_bit):
        if points:
            values = (-point for point in points) if invert else points
            value = _scaled_stat_group(value, values, per_point, rarity, multiplier)
    return value


def _last_override(
    parts: list[dict[str, Any]],
    attribute: str,
    attribute_defaults: dict[str, float] | None = None,
) -> float | None:
    value = None
    for part in parts:
        for effect in part.get("weapon_attribute_effects", []):
            if effect.get("attribute") != attribute or effect.get("modifier_type") != "OverrideBaseValue":
                continue
            if not int(effect.get("use_mode_bitmask", 1)) & 1:
                continue
            resolved = _effect_value(effect, attribute_defaults)
            if resolved is not None:
                value = resolved
    return value


def _fire_rate_value_from_serial(decoded: str, index: dict[str, Any]) -> float:
    parts, rarity, provider, model, _item = _serial_stat_context(decoded, index)
    barrel = next((part for part in parts if part.get("category") == "barrel"), None)
    if not barrel:
        raise ValueError("serial has no indexed barrel")
    base = next(
        (
            float(ref["values"]["firerate_value"])
            for ref in barrel.get("weapon_base_value_refs", [])
            if ref.get("values", {}).get("firerate_value") is not None
        ),
        None,
    )
    if base is None:
        raise ValueError("barrel has no resolved fire-rate base")
    stat = model["stats"]["FireRate"]
    value = _scaled_stat_from_parts(
        base,
        parts,
        "FireRate",
        stat["scalar"],
        rarity,
        stat.get("manufacturer_multipliers", {}).get(provider, 1.0),
    )
    for part in parts:
        for effect in part.get("weapon_attribute_effects", []):
            if effect.get("attribute") != "weapon_fire_rate" or effect.get("modifier_type") != "ScaleMultiply":
                continue
            if not int(effect.get("use_mode_bitmask", 1)) & 1:
                continue
            multiplier = _effect_value(effect)
            if multiplier is not None:
                value = f32(value * f32(multiplier))
    return value


def fire_rate_from_serial(decoded: str, index: dict[str, Any]) -> float:
    return display_decimal(_compare_fire_rate_value_from_serial(decoded, index))


def _reload_time_value_from_serial(decoded: str, index: dict[str, Any]) -> float:
    parts, rarity, provider, model, _item = _serial_stat_context(decoded, index)
    base = _last_override(parts, "weapon_reload_time")
    if base is None:
        raise ValueError("serial has no resolved reload-time base")
    stat = model["stats"]["ReloadSpeed"]
    return _scaled_stat_from_parts(
        base,
        parts,
        "ReloadSpeed",
        stat["scalar"],
        rarity,
        stat.get("manufacturer_multipliers", {}).get(provider, 1.0),
        invert=True,
    )


def _compare_reload_time_value_from_serial(decoded: str, index: dict[str, Any]) -> float:
    parts, _rarity, _provider, model, _item = _serial_stat_context(decoded, index)
    value = _reload_time_value_from_serial(decoded, index)
    if not _last_override(parts, "weapon_is_single_load", model.get("attribute_defaults", {})):
        return value
    loop = _last_override(parts, "weapon_single_load_reload_loop_percent", model.get("attribute_defaults", {}))
    if loop is None:
        raise ValueError("single-load weapon has no reload-loop percent")
    header = re.match(r"\s*(\d+)", decoded)
    behavior_parts = _serial_behavior_parts(decoded, index, header.group(1))
    feed = _last_override(behavior_parts, "weapon_single_feed_increment", model.get("attribute_defaults", {})) or 1.0
    max_ammo = _magazine_capacity_value_from_serial(decoded, index)
    loops = f32(f32(loop) * f32(max_ammo - 2))
    return f32(f32(value * f32(1.0 + loops)) / f32(feed))


def reload_time_from_serial(decoded: str, index: dict[str, Any]) -> float:
    return display_decimal(_compare_reload_time_value_from_serial(decoded, index))


def _magazine_capacity_raw_from_serial(decoded: str, index: dict[str, Any]) -> float:
    parts, rarity, provider, model, _item = _serial_stat_context(decoded, index)
    base = _last_override(parts, "weapon_max_loaded_ammo")
    if base is None:
        heat_impulse = _last_override(parts, "weapon_heat_impulse")
        if not heat_impulse:
            raise ValueError("serial has no resolved magazine or heat base")
        base = f32(1.0 / f32(heat_impulse))

    pre_add = 0.0
    post_add = 0.0
    simple: list[float] = []
    product = 1.0
    defaults = model.get("attribute_defaults", {})
    for part in parts:
        for effect in part.get("weapon_attribute_effects", []):
            if effect.get("attribute") != "weapon_max_loaded_ammo" or not int(effect.get("use_mode_bitmask", 1)) & 1:
                continue
            value = _effect_value(effect, defaults)
            if value is None:
                continue
            kind = effect.get("modifier_type") or "ScaleSimple"
            if kind == "PreAdd":
                pre_add = f32(pre_add + value)
            elif kind == "PostAdd":
                post_add = f32(post_add + value)
            elif kind == "ScaleMultiply":
                product = f32(product * value)
            elif kind == "ScaleSimple":
                simple.append(value)

    stat = model["stats"]["MagSize"]
    value = _scaled_stat_from_parts(
        f32(base + pre_add),
        parts,
        "MagSize",
        stat["scalar"],
        rarity,
        stat.get("manufacturer_multipliers", {}).get(provider, 1.0),
    )
    positive = sum(item for item in simple if item >= 0)
    negative = sum(item for item in simple if item < 0)
    scale = f32(product * ((1.0 + positive) / (1.0 - negative)))
    return f32(f32(value * scale) + post_add)


def _magazine_capacity_value_from_serial(decoded: str, index: dict[str, Any]) -> int:
    return ceil(_magazine_capacity_raw_from_serial(decoded, index))


def magazine_capacity_from_serial(decoded: str, index: dict[str, Any]) -> int:
    return _magazine_capacity_value_from_serial(decoded, index)


def _attribute_effect_ratio(
    effects: Iterable[dict[str, Any]],
    attribute: str,
    attribute_defaults: dict[str, float],
    mode_bit: int = 1,
) -> float:
    simple: list[float] = []
    pre_add = 0.0
    post_add = 0.0
    product = 1.0
    for effect in effects:
        if effect.get("attribute") != attribute:
            continue
        mode = effect.get("use_mode_bitmask")
        if mode is not None and not int(mode) & mode_bit:
            continue
        value = _effect_value(effect, attribute_defaults)
        if value is None:
            continue
        kind = effect.get("modifier_type") or "ScaleSimple"
        if kind == "ScaleSimple":
            simple.append(value)
        elif kind == "PreAdd":
            pre_add += value
        elif kind == "PostAdd":
            post_add += value
        elif kind == "ScaleMultiply":
            product *= value
    positive = sum(value for value in simple if value >= 0)
    negative = sum(value for value in simple if value < 0)
    return f32(product * ((1.0 + positive) / (1.0 - negative)) * (1.0 + pre_add) + post_add)


def ads_time_from_serial(decoded: str, index: dict[str, Any]) -> float:
    """Return the verified primary-mode ZoomDuration BaseValue in seconds."""
    parts, rarity, provider, model, item = _serial_stat_context(decoded, index)
    weapon_type = WEAPON_TYPE_BY_ROOT_SUFFIX[item["root"].rsplit("_", 1)[-1]]
    base = _last_override(parts, "weapon_zoom_duration", model.get("attribute_defaults", {}))
    if base is None:
        base = ADS_BASE_TIME[weapon_type]
    stat = model["stats"]["ADSProficiency"]
    stat_ratio = _scaled_stat_from_parts(
        1.0,
        parts,
        "ADSProficiency",
        stat["scalar"],
        rarity,
        stat.get("manufacturer_multipliers", {}).get(provider, 1.0),
        invert=True,
    )
    effects = [*item.get("attribute_effects", []), *(effect for part in parts for effect in part.get("weapon_attribute_effects", []))]
    type_ratio = model["type_initializers"].get(weapon_type, {}).get("ADSProficiency", 1.0)
    ratio = f32(f32(type_ratio) * f32(stat_ratio))
    ratio = f32(ratio * _attribute_effect_ratio(effects, "weapon_zoom_duration", model.get("attribute_defaults", {})))
    return f32(f32(base) * ratio)


def equip_time_from_serial(decoded: str, index: dict[str, Any]) -> float:
    """Return held AWeapon.EquipTime BaseValue, excluding character buffs."""
    parts, _rarity, _provider, model, item = _serial_stat_context(decoded, index)
    weapon_type = WEAPON_TYPE_BY_ROOT_SUFFIX[item["root"].rsplit("_", 1)[-1]]
    effects = [effect for part in parts for effect in part.get("weapon_attribute_effects", [])]
    ratio = _attribute_effect_ratio(effects, "weapon_equip_time", model.get("attribute_defaults", {}))
    return f32(f32(EQUIP_TIME_BASE[weapon_type]) * ratio)


def weapon_dps(
    damage_per_shot: float,
    shots_per_mag: float,
    fire_rate_value: float,
    compare_reload_time: float,
    compare_charge_time: float = 0.0,
) -> float:
    """Evaluate weapon_dps_estimate with game-like float intermediates."""
    shots = f32(shots_per_mag)
    rate = f32(fire_rate_value)
    if shots <= 0 or rate <= 0:
        raise ValueError("shots per magazine and fire rate must be positive")
    firing_time = f32(shots / rate)
    denominator = f32(f32(firing_time + f32(compare_reload_time)) + f32(compare_charge_time))
    if denominator <= 0:
        raise ValueError("DPS cycle time must be positive")
    numerator = f32(f32(damage_per_shot) * shots)
    return f32(numerator / denominator)


def _compare_fire_rate_value_from_serial(decoded: str, index: dict[str, Any]) -> float:
    header = re.match(r"\s*(\d+)", decoded)
    model = index["weapon_native_model"]
    parts = _serial_behavior_parts(decoded, index, header.group(1))
    defaults = model.get("attribute_defaults", {})
    fire_rate_value = _fire_rate_value_from_serial(decoded, index)
    burst_count = _last_override(parts, "weapon_auto_burst_count", defaults) or 1.0
    if burst_count <= 1:
        return fire_rate_value
    burst_delay = _last_override(parts, "weapon_burst_fire_delay", defaults) or 0.0
    count = f32(burst_count)
    return f32(count / f32(f32(count / f32(fire_rate_value)) + f32(burst_delay)))


def _compare_charge_time_from_serial(decoded: str, index: dict[str, Any]) -> float:
    header = re.match(r"\s*(\d+)", decoded)
    parts, rarity, provider, model, _item = _serial_stat_context(decoded, index)
    behavior_parts = _serial_behavior_parts(decoded, index, header.group(1))
    defaults = model.get("attribute_defaults", {})
    charge_time = _last_override(behavior_parts, "weapon_charge_time", defaults)
    if charge_time is None:
        if any(
            effect.get("attribute") == "weapon_charge_time"
            and effect.get("modifier_type") == "OverrideBaseValue"
            and int(effect.get("use_mode_bitmask", 1)) & 1
            for part in behavior_parts
            for effect in part.get("weapon_attribute_effects", [])
        ):
            raise ValueError("charge behavior has an unresolved charge time")
        return 0.0
    max_stack = _last_override(behavior_parts, "weapon_max_charge_stack", defaults)
    if max_stack is None:
        raise ValueError("charge behavior has no resolved max stack")
    if f32(max_stack) != 1.0:
        return 0.0
    stat = model["stats"]["ChargeTime"]
    return _scaled_stat_from_parts(
        charge_time,
        parts,
        "FireRate",
        stat["scalar"],
        rarity,
        stat.get("manufacturer_multipliers", {}).get(provider, 1.0),
        invert=True,
    )


def _compare_shots_per_mag_from_serial(decoded: str, index: dict[str, Any]) -> float:
    return f32(f32(_magazine_capacity_raw_from_serial(decoded, index)) / f32(ammo_cost_from_serial(decoded, index)))


def weapon_dps_from_serial(decoded: str, index: dict[str, Any]) -> float:
    return weapon_dps(
        weapon_damage_from_serial(decoded, index),
        _compare_shots_per_mag_from_serial(decoded, index),
        _compare_fire_rate_value_from_serial(decoded, index),
        _compare_reload_time_value_from_serial(decoded, index),
        _compare_charge_time_from_serial(decoded, index),
    )


def splash_radius_from_serial(decoded: str, index: dict[str, Any]) -> int | None:
    """Return the primary-mode splash radius in centimeters, or None when absent."""
    parts, rarity, provider, model, _item = _serial_stat_context(decoded, index)
    attribute_defaults = model.get("attribute_defaults", {})
    base = _last_override(parts, "weapon_damage_radius", attribute_defaults)
    if base is None or base <= 0:
        return None

    pre_add = 0.0
    scale_multipliers = []
    for part in parts:
        for effect in part.get("weapon_attribute_effects", []):
            if effect.get("attribute") != "weapon_damage_radius" or not int(effect.get("use_mode_bitmask", 1)) & 1:
                continue
            value = _effect_value(effect, attribute_defaults)
            if value is None:
                continue
            if effect.get("modifier_type") == "PreAdd":
                pre_add = f32(pre_add + f32(value))
            elif effect.get("modifier_type") == "ScaleMultiply":
                scale_multipliers.append(value)

    value = f32(f32(base) + pre_add)
    stat = model["stats"]["DamageRadius"]
    value = _scaled_stat_from_parts(
        value,
        parts,
        "DamageRadius",
        stat["scalar"],
        rarity,
        stat.get("manufacturer_multipliers", {}).get(provider, 1.0),
    )
    for multiplier in scale_multipliers:
        value = f32(value * f32(multiplier))
    return floor(value + 0.5)


def _part_element_names(part: dict[str, Any]) -> list[str]:
    name = str(part.get("part") or "").casefold()
    if "normal" in name or "kinetic" in name:
        return ["kinetic"]
    return [element for _, element in sorted((name.find(element), element) for element in ELEMENT_NAMES if element in name)]


def weapon_elements_from_serial(decoded: str, index: dict[str, Any]) -> tuple[str, str]:
    """Return the primary and mode-02 elements, honoring pearl overrides."""
    header = re.match(r"\s*(\d+)", decoded)
    if not header:
        raise ValueError("invalid decoded weapon serial")
    parts = _serial_parts(decoded, index, header.group(1))
    primary = ""
    secondary = ""
    pearl: str | None = None
    for part in parts:
        category = part.get("category")
        elements = _part_element_names(part)
        if category == "body_ele" and elements and not primary:
            primary = elements[0]
        elif category == "secondary_ele" and elements:
            if not primary:
                primary = elements[0]
            secondary = elements[1] if len(elements) > 1 else elements[0]
        elif category == "pearl_elem":
            pearl = elements[0] if elements else ""
    if pearl is not None:
        primary = pearl
    if secondary == primary:
        secondary = ""
    return primary, secondary


def _status_default(model: dict[str, Any], element: str) -> dict[str, Any]:
    value = dict(STATUS_APPLICATION_DEFAULTS.get(element, {}))
    exported = next(
        (
            row
            for row_name, row in (model.get("status_application_defaults") or {}).items()
            if str(row_name).casefold() == element
        ),
        {},
    )
    value.update(exported)
    return value


def _resolved_number(value: Any, field: str) -> float | None:
    if isinstance(value, dict):
        if value.get(field) is not None:
            try:
                return float(value[field])
            except (TypeError, ValueError):
                pass
        for child in value.values():
            found = _resolved_number(child, field)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _resolved_number(child, field)
            if found is not None:
                return found
    return None


def _status_stat_spec(model: dict[str, Any], kind: str) -> dict[str, Any]:
    spec = dict(STATUS_STAT_FALLBACKS[kind])
    aliases = {
        "damage": ("damage", "StatusDamage", "status_damage", "ElementalPower"),
        "chance": ("chance", "StatusChance", "status_chance"),
        "cryo": ("cryo", "CryoImpact", "cryo_impact"),
    }[kind]
    sources = (model.get("status_stats") or {}, model.get("stats") or {})
    for source in sources:
        candidate = next((source.get(alias) for alias in aliases if isinstance(source.get(alias), dict)), None)
        if candidate:
            spec.update(candidate)
            break
    return spec


def _status_type_base(model: dict[str, Any], weapon_type: str, kind: str) -> float:
    aliases = {
        "damage": ("StatusDamage", "status_damage", "ElementalPower"),
        "chance": ("StatusChance", "status_chance", "ElementalChance"),
        "cryo": ("CryoImpact", "cryo_impact", "CryoImpactContribution"),
    }[kind]
    for source in (model.get("status_type_initializers") or {}, model.get("type_initializers") or {}):
        row = source.get(weapon_type) or {}
        for alias in aliases:
            if row.get(alias) is not None:
                return float(row[alias])
    if kind == "chance":
        return STATUS_CHANCE_BASE_BY_TYPE[weapon_type]
    if kind == "cryo":
        return CRYO_IMPACT_BASE_BY_TYPE[weapon_type]
    return 1.0


def _status_attribute_value(
    parts: list[dict[str, Any]],
    rarity: str,
    provider: str,
    model: dict[str, Any],
    item: dict[str, Any],
    weapon_type: str,
    kind: str,
    mode_bit: int,
) -> float:
    spec = _status_stat_spec(model, kind)
    value = _scaled_stat_from_parts(
        _status_type_base(model, weapon_type, kind),
        parts,
        "ElementalPower",
        float(spec.get("scalar", 0.0)),
        rarity,
        (spec.get("manufacturer_multipliers") or {}).get(provider, 1.0),
        mode_bit=mode_bit,
    )
    attribute = {
        "damage": "weapon_damage_modifier_base_status_effect_damage",
        "chance": "weapon_damage_modifier_base_status_effect_chance",
        "cryo": "impact_contribution_scalar",
    }[kind]
    effects = [
        *item.get("attribute_effects", []),
        *(effect for part in parts for effect in part.get("weapon_attribute_effects", [])),
    ]
    return f32(value * _attribute_effect_ratio(effects, attribute, model.get("attribute_defaults", {}), mode_bit))


def weapon_element_card_stats_from_serial(decoded: str, index: dict[str, Any]) -> dict[str, Any]:
    """Resolve the primary and mode-02 elemental rows shown on a weapon card."""
    parts, rarity, provider, model, item = _serial_stat_context(decoded, index)
    weapon_type = WEAPON_TYPE_BY_ROOT_SUFFIX[item["root"].rsplit("_", 1)[-1]]
    primary, secondary = weapon_elements_from_serial(decoded, index)
    dot_interval = _resolved_number((model.get("attribute_resolvers") or {}).get("att_playershared_dotinterval", {}), "resolved_value") or 0.33
    stats: dict[str, Any] = {}

    for element, mode_bit, suffix in ((primary, 1, ""), (secondary, 2, "_mode02")):
        if not element or element == "kinetic":
            continue
        stats[f"element{suffix}"] = element
        if element == "cryo":
            efficiency = _status_attribute_value(parts, rarity, provider, model, item, weapon_type, "cryo", mode_bit)
            stats[f"cryo_efficiency{suffix}"] = floor(f32(efficiency * 100.0) + 0.5)
            continue

        status_damage = _status_attribute_value(parts, rarity, provider, model, item, weapon_type, "damage", mode_bit)
        damage = weapon_damage_from_serial(decoded, index, projectiles=1.0, mode_bit=mode_bit)
        dps_scalar = float(_status_default(model, element).get("dps_scalar", 0.0))
        elemental_dps = f32(f32(f32(damage * status_damage) * f32(dps_scalar)) / f32(dot_interval))
        chance = _status_attribute_value(parts, rarity, provider, model, item, weapon_type, "chance", mode_bit)
        stats[f"elemental_dps{suffix}"] = floor(elemental_dps + 0.5)
        stats[f"elemental_chance{suffix}"] = floor(f32(chance * 100.0) + 0.5)
    return stats


def weapon_card_stats_from_serial(decoded: str, index: dict[str, Any]) -> dict[str, Any]:
    """Return every verified primary-mode item-card stat that can be resolved."""
    parts, _rarity, _provider, _model, _item = _serial_stat_context(decoded, index)
    barrel = next((part for part in parts if part.get("category") == "barrel"), {})
    projectiles = floor(
        next(
            (
                float(ref["values"]["projectilespershot_value"])
                for ref in barrel.get("weapon_base_value_refs", [])
                if ref.get("values", {}).get("projectilespershot_value") is not None
            ),
            1.0,
        )
        + 0.5
    )
    resolvers = {
        "dps": lambda serial, data: floor(weapon_dps_from_serial(serial, data) + 0.5),
        "accuracy": accuracy_from_serial,
        "fire_rate": fire_rate_from_serial,
        "reload_time": reload_time_from_serial,
        "magazine": magazine_capacity_from_serial,
        "critical_damage": critical_damage_from_serial,
        "ammo_cost": ammo_cost_from_serial,
        "splash_radius": splash_radius_from_serial,
        "ads_time": ads_time_from_serial,
        "equip_time": equip_time_from_serial,
    }
    stats: dict[str, Any] = {}
    try:
        stats["damage"] = format_damage(
            weapon_damage_from_serial(decoded, index, projectiles=projectiles),
            projectiles,
        )
    except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError):
        pass
    for key, resolver in resolvers.items():
        try:
            stats[key] = resolver(decoded, index)
        except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError):
            pass
    try:
        stats.update(weapon_element_card_stats_from_serial(decoded, index))
    except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError):
        pass
    return stats
