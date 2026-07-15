from __future__ import annotations

import csv
import re
from functools import lru_cache
from typing import Any

from . import resource_loader, weapon_display_stats


WEAPON_TYPES = {"Pistol", "Shotgun", "SMG", "Assault Rifle", "Sniper"}
WEAPON_PISTOL_IDS = {2, 3, 4, 5, 6}
WEAPON_AR_IDS = {13, 14, 15, 17, 18, 27}
WEAPON_SNIPER_IDS = {16, 23, 24, 25, 26}
WEAPON_SMG_IDS = {19, 20, 21, 22}
WEAPON_SHOTGUN_IDS = {7, 8, 9, 10, 11, 12}
HEAVY_TYPE = "Heavy Weapon"
GENERIC_PART_TYPES = {"Rarity", "Model"}
RARITY_ZH = {
    "Common": "普通",
    "common": "普通",
    "Uncommon": "罕见",
    "uncommon": "罕见",
    "Rare": "稀有",
    "rare": "稀有",
    "Epic": "史诗",
    "epic": "史诗",
    "Legendary": "传奇",
    "legendary": "传奇",
    "Pearl": "珠光",
    "pearl": "珠光",
}
CLASSMOD_RARITY_CODES = {
    254: {"217": "Common", "218": "Uncommon", "219": "Rare", "220": "Epic"},
    255: {"70": "Common", "69": "Uncommon", "68": "Rare", "67": "Epic"},
    256: {"66": "Common", "67": "Uncommon", "68": "Rare", "69": "Epic"},
    259: {"224": "Common", "223": "Uncommon", "222": "Rare", "221": "Epic"},
    404: {"52": "Common", "53": "Uncommon", "54": "Rare", "55": "Epic"},
}


def _read_csv(path) -> list[dict[str, str]]:
    if not path or not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _lang_is_zh(lang: str) -> bool:
    return lang == "zh-CN"


def _text(row: dict[str, str], lang: str) -> str:
    if _lang_is_zh(lang):
        return (row.get("Stat_ZH") or row.get("perk_name_ZH") or row.get("Stat") or "").strip()
    return (row.get("Stat_EN") or row.get("perk_name_EN") or row.get("Stat") or "").strip()


def _desc(row: dict[str, str], lang: str) -> str:
    if _lang_is_zh(lang):
        return (row.get("Description_ZH") or "").strip()
    return (row.get("Description_EN") or row.get("Description") or "").strip()


def _rarity_text(value: str, lang: str) -> str:
    value = (value or "").strip()
    if _lang_is_zh(lang):
        return RARITY_ZH.get(value, value)
    return value[:1].upper() + value[1:] if value.islower() else value


def _clean_markup(text: str) -> str:
    text = re.sub(r"\[[^\]]+\]", "", text or "")
    return " ".join(text.split())


def _title_from_text(text: str) -> str:
    text = _clean_markup(text)
    if not text:
        return ""
    return re.split(r"\s*-\s*", text, maxsplit=1)[0].strip().replace("Ⅳ", "IV")


def _valid_name(text: str) -> bool:
    return bool(text and text not in {"/", "Unknown", "未知", "N/A"})


def _parse_components(component_str: str) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    pattern = r'\{(\d+)(?::(\d+|\[[\d\s]+\]))?\}|\"c\",\s*(?:(\d+)|\"([^\"]+)\")'
    for match in re.finditer(pattern, component_str or ""):
        if match.group(3):
            components.append({"type": "skin", "id": str(match.group(3)), "raw": match.group(0)})
        elif match.group(4):
            components.append({"type": "skin", "id": match.group(4), "raw": match.group(0)})
        else:
            outer_id, inner = match.group(1), match.group(2)
            if not inner:
                components.append({"type": "simple", "id": outer_id, "raw": match.group(0)})
            elif "[" in inner:
                components.append(
                    {
                        "type": "group",
                        "id": outer_id,
                        "sub_ids": inner.strip("[]").split(),
                        "raw": match.group(0),
                    }
                )
            else:
                components.append({"type": "elemental", "id": outer_id, "sub_id": inner, "raw": match.group(0)})
    return components


def _ordered_ids(components: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for part in components:
        if part.get("type") == "simple":
            ids.append(str(part.get("id", "")))
        elif part.get("type") == "group":
            ids.extend(str(item) for item in part.get("sub_ids", []))
    return [item for item in ids if item]


def _simple_ids(components: list[dict[str, Any]]) -> list[str]:
    return [str(part.get("id", "")) for part in components if part.get("type") == "simple" and part.get("id")]


def _group_sub_ids(components: list[dict[str, Any]], group_id: str) -> list[str]:
    ids: list[str] = []
    for part in components:
        if part.get("type") == "group" and str(part.get("id", "")) == group_id:
            ids.extend(str(item) for item in part.get("sub_ids", []))
    return [item for item in ids if item]


@lru_cache(maxsize=1)
def _item_index() -> dict[str, Any]:
    return resource_loader.load_item_json("item_name_index.json") or {}


@lru_cache(maxsize=8)
def _weapon_parts(lang: str) -> list[dict[str, str]]:
    filename = "all_weapon_part.csv" if _lang_is_zh(lang) else "all_weapon_part_EN.csv"
    return _read_csv(resource_loader.get_weapon_data_path(filename))


@lru_cache(maxsize=1)
def _weapon_rarity() -> list[dict[str, str]]:
    return _read_csv(resource_loader.get_weapon_data_path("weapon_rarity.csv"))


@lru_cache(maxsize=8)
def _rows_by_file(filename: str) -> list[dict[str, str]]:
    folder, name = filename.split("/", maxsplit=1)
    getter = {
        "heavy": resource_loader.get_heavy_data_path,
        "grenade": resource_loader.get_grenade_data_path,
        "shield": resource_loader.get_shield_data_path,
        "repkit": resource_loader.get_repkit_data_path,
        "enhancement": resource_loader.get_enhancement_data_path,
        "class_mods": resource_loader.get_class_mods_data_path,
    }.get(folder)
    return _read_csv(getter(name)) if getter else []


def _csv_rows_for_type(item_type: str) -> list[dict[str, str]]:
    if item_type == "Heavy Weapon":
        return _rows_by_file("heavy/heavy_manufacturer_perk.csv")
    if item_type == "Grenade":
        return _rows_by_file("grenade/manufacturer_rarity_perk.csv")
    if item_type == "Shield":
        return _rows_by_file("shield/manufacturer_perk.csv")
    if item_type == "Repkit":
        return _rows_by_file("repkit/repkit_manufacturer_perk.csv")
    return []


def _find_csv_part(item_id: int, part_id: str, item_type: str) -> dict[str, str] | None:
    for row in _csv_rows_for_type(item_type):
        if row.get("Manufacturer ID", "").strip() == str(item_id) and row.get("Part_ID", "").strip() == str(part_id):
            return row
    return None


def _index_part_name(item_id: int, part_id: str, lang: str) -> tuple[str, str]:
    index = _item_index()
    part_ref = (index.get("part_refs") or {}).get(f"{item_id}:{part_id}", {})
    name = part_ref.get("name") or {}
    key = "zh" if _lang_is_zh(lang) else "en"
    if _valid_name(name.get(key, "")):
        return name.get(key, ""), "ncs_name"
    if _valid_name(name.get("en", "")):
        return name.get("en", ""), "ncs_name"
    for uistat in [*part_ref.get("uistats", []), *part_ref.get("uistats_include", [])]:
        ui = (index.get("uistats") or {}).get(str(uistat).lower(), {})
        title = _title_from_text(ui.get(key, "") or ui.get("en", ""))
        if _valid_name(title):
            return title, "ncs_uistat"
    return "", ""


def _component_part_refs(item_id: int, components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for component in components:
        component_type = component.get("type")
        if component_type == "simple":
            ref = _part_ref(item_id, str(component.get("id", "")))
            if ref:
                refs.append(ref)
        elif component_type == "group":
            owner = int(component.get("id", 0))
            refs.extend(ref for part_id in component.get("sub_ids", []) if (ref := _part_ref(owner, str(part_id))))
        elif component_type == "elemental" and component.get("sub_id"):
            ref = _part_ref(int(component.get("id", 0)), str(component["sub_id"]))
            if ref:
                refs.append(ref)
    return refs


def _name_part_text(name_part: str, lang: str) -> tuple[str, float]:
    entry = (_item_index().get("inv_name_parts") or {}).get(str(name_part).lower(), {})
    key = "zh" if _lang_is_zh(lang) else "en"
    text = entry.get(key) or entry.get("en") or ""
    try:
        priority = float(entry.get("priority", 0))
    except (TypeError, ValueError):
        priority = 0.0
    return text.strip(), priority


def _nonweapon_name(item_id: int, components: list[dict[str, Any]], lang: str) -> tuple[str, str]:
    sections: dict[str, list[tuple[float, int, str]]] = {"prefix": [], "title": [], "suffix": []}
    seen: set[tuple[str, str]] = set()
    part_refs = _component_part_refs(item_id, components)
    disable_prefixes = any(str(ref.get("disable_prefixes", "")).casefold() == "true" for ref in part_refs)
    has_named_composition = any(
        ref.get("category") == "inv_comp"
        and _valid_name(((ref.get("name") or {}).get("zh" if _lang_is_zh(lang) else "en") or (ref.get("name") or {}).get("en", "")))
        for ref in part_refs
    )
    for order, ref in enumerate(part_refs):
        for section in sections:
            if section == "prefix" and has_named_composition and ref.get("category") == "payload":
                continue
            for name_part in ref.get(f"{section}_part_list", []):
                dedupe = (section, str(name_part).lower())
                if dedupe in seen:
                    continue
                seen.add(dedupe)
                text, priority = _name_part_text(name_part, lang)
                if _valid_name(text):
                    sections[section].append((priority, order, text))

    for values in sections.values():
        values.sort(key=lambda item: (-item[0], item[1]))
    prefixes = [] if disable_prefixes else [item[2] for item in sections["prefix"][:2]]
    title = sections["title"][0][2] if sections["title"] else ""
    suffix = sections["suffix"][0][2] if sections["suffix"] else ""
    name = " ".join([*prefixes, title, suffix]).strip()
    return name, "native_name_parts" if name else ""


def _shield_prefix(item_id: int, components: list[dict[str, Any]], lang: str) -> str:
    table = _item_index().get("shield_names") or {}
    if any(str(ref.get("disable_prefixes", "")).casefold() == "true" for ref in _component_part_refs(item_id, components)):
        return ""
    selected: dict[str, set[str]] = {}
    for ref in _component_part_refs(item_id, components):
        if ref.get("category") not in {"primary_augment", "secondary_augment"}:
            continue
        row = str(ref.get("naming_row", ""))
        if row:
            selected.setdefault(row, set()).add(str(ref.get("category")))
    words: list[str] = []
    key = "zh" if _lang_is_zh(lang) else "en"
    for row, categories in selected.items():
        values = table.get(re.sub(r"[^a-z0-9]+", "", row.lower()), {})
        column = "both" if len(categories) > 1 else ("primary" if "primary_augment" in categories else "secondary")
        entry = values.get(column) or {}
        text = entry.get(key) or entry.get("en") or ""
        if _valid_name(text):
            words.append(text.strip())
    return " ".join(words)


def _strategy_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _strategy_text(entry: dict[str, Any] | None, lang: str) -> str:
    if not entry:
        return ""
    key = "zh" if _lang_is_zh(lang) else "en"
    return (entry.get(key) or entry.get("en") or "").strip()


def _strategy_combo(table: dict[str, Any], first: str, second: str, lang: str) -> str:
    combos = table.get("combos", {}) if isinstance(table, dict) else {}
    first_key = _strategy_key(first)
    second_key = _strategy_key(second)
    return _strategy_text(combos.get(f"{first_key}|{second_key}") or combos.get(f"{second_key}|{first_key}"), lang)


def _strategy_single(table: dict[str, Any], attr: str, lang: str) -> str:
    singles = table.get("singles", {}) if isinstance(table, dict) else {}
    return _strategy_text(singles.get(_strategy_key(attr)), lang)


def _strategy_words(attrs: list[str], table: dict[str, Any], lang: str) -> list[str]:
    remaining = [attr for attr in attrs if attr]
    words: list[str] = []
    while len(remaining) >= 2:
        pair: tuple[int, int, str] | None = None
        for prefer_duplicate in (True, False):
            for i, first in enumerate(remaining):
                for j in range(i + 1, len(remaining)):
                    second = remaining[j]
                    if prefer_duplicate and _strategy_key(first) != _strategy_key(second):
                        continue
                    word = _strategy_combo(table, first, second, lang)
                    if word:
                        pair = (i, j, word)
                        break
                if pair:
                    break
            if pair:
                break
        if not pair:
            break
        i, j, word = pair
        words.append(word)
        del remaining[j]
        del remaining[i]
    for attr in remaining:
        word = _strategy_single(table, attr, lang)
        if word:
            words.append(word)
    return words


def _unique_words(words: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for word in words:
        key = word.casefold()
        if key and key not in seen:
            seen.add(key)
            out.append(word)
    return out


def _enhancement_name(item_id: int, core_ids: list[str], stat_ids: list[str], lang: str) -> tuple[str, str]:
    strategy = _item_index().get("enhancement_strategies") or {}
    stat_attrs: list[str] = []
    core_attrs: list[str] = []
    for part_id in stat_ids:
        ref = _part_ref(247, part_id)
        if str(ref.get("category", "")).startswith("stat_group"):
            stat_attrs.append(ref.get("naming_row", ""))
    for part_id in core_ids:
        ref = _part_ref(item_id, part_id)
        if ref.get("category") == "core_augment":
            core_attrs.append(ref.get("naming_row", ""))

    words = _strategy_words(stat_attrs, strategy.get("stats", {}), lang)
    words.extend(_strategy_words(core_attrs, strategy.get("cores", {}), lang))
    words = _unique_words(words)
    name = " ".join(word for word in words if word).strip()
    return name, "enhancement_strategy" if name else ""


def _part_ref(item_id: int, part_id: str) -> dict[str, Any]:
    return (_item_index().get("part_refs") or {}).get(f"{item_id}:{part_id}", {})


WEAPON_PART_STAT_LABELS = {
    "Damage": ("伤害", "Damage"),
    "CritDamage": ("暴击伤害", "Critical Damage"),
    "FireRate": ("射速", "Fire Rate"),
    "ChargeTime": ("蓄力时间", "Charge Time"),
    "ReloadSpeed": ("装填时间", "Reload Time"),
    "MagSize": ("弹匣容量", "Magazine Capacity"),
    "Accuracy": ("散布", "Spread"),
    "ElementalPower": ("元素伤害", "Elemental Damage"),
    "ADSProficiency": ("瞄准时间", "ADS Time"),
    "DamageRadius": ("爆炸范围", "Splash Radius"),
}
WEAPON_PART_ATTRIBUTE_LABELS = {
    "weapon_damage": ("伤害", "Damage"),
    "weapon_damage_modifier_add_critical_hit": ("暴击伤害", "Critical Damage"),
    "weapon_fire_rate": ("射速", "Fire Rate"),
    "weapon_reload_time": ("装填时间", "Reload Time"),
    "weapon_max_loaded_ammo": ("弹匣容量", "Magazine Capacity"),
    "weapon_spread": ("散布", "Spread"),
    "weapon_accuracy_impulse": ("精准度冲量", "Accuracy Impulse"),
    "accuracy_resource_max_value": ("精准度资源", "Accuracy Resource"),
    "weapon_recoil_scale": ("后坐力", "Recoil"),
    "weapon_recoil_scale_x": ("水平后坐力", "Horizontal Recoil"),
    "weapon_recoil_scale_y": ("垂直后坐力", "Vertical Recoil"),
    "weapon_sway_scale": ("晃动", "Sway"),
    "weapon_sway_zoom_scale": ("晃动", "Sway"),
    "weapon_sway_accuracy_scale": ("晃动", "Sway"),
    "weapon_sway_zoom_accuracy_scale": ("晃动", "Sway"),
    "weapon_zoom_duration": ("瞄准时间", "ADS Time"),
    "weapon_zoom_fov_scale": ("瞄准视野", "ADS FOV"),
    "weapon_equip_time": ("装备时间", "Equip Time"),
    "weapon_damage_radius": ("爆炸范围", "Splash Radius"),
    "weapon_damage_modifier_base_status_effect_damage": ("元素伤害", "Elemental Damage"),
    "weapon_damage_modifier_base_status_effect_chance": ("元素触发率", "Elemental Chance"),
    "weapon_projectile_speed_scale": ("弹丸速度", "Projectile Speed"),
    "weapon_projectile_per_shot": ("弹丸数", "Projectiles"),
    "weapon_shot_cost": ("弹药消耗", "Ammo Cost"),
    "weapon_charge_time": ("蓄力时间", "Charge Time"),
    "weapon_auto_burst_count": ("连发数", "Burst Count"),
    "weapon_burst_fire_delay": ("连发间隔", "Burst Delay"),
    "weapon_switch_mode_time_scale": ("模式切换时间", "Mode Switch Time"),
    "weapon_ted_throw_damage_scale": ("投掷伤害", "Thrown Damage"),
    "weapon_ted_throw_radius": ("投掷爆炸范围", "Thrown Splash Radius"),
    "weapon_ted_thrusterscalar": ("投掷推进力", "Thrown Thrust"),
    "weapon_ted_thrustercount": ("投掷推进器", "Thrown Thrusters"),
    "weapon_tor_sticky_attach_damage_scale": ("粘弹伤害", "Sticky Damage"),
}
WEAPON_PART_INTERNAL_ATTRIBUTES = {
    "weapon_part_reload_value",
    "weapon_part_grip_value",
    "weapon_part_barrel_value",
    "weapon_part_underbarrel_value",
    "weapon_part_foregrip_value",
    "weapon_part_melee_value",
    "weapon_part_scope_value",
    "weapon_part_thrown_reload_value",
    "weapon_underbarrel_acc_value",
}


def _part_label(labels: tuple[str, str], lang: str) -> str:
    return labels[0] if _lang_is_zh(lang) else labels[1]


def _part_number(value: float, decimals: int = 3) -> str:
    return f"{value:.{decimals}f}".rstrip("0").rstrip(".")


def _part_row_value(row: Any, *keys: str) -> str:
    if row is None:
        return ""
    for key in keys:
        try:
            value = row.get(key, "")
        except AttributeError:
            continue
        text = str(value).strip()
        if text and text.casefold() not in {"nan", "<na>", "none"}:
            return text
    return ""


def weapon_part_name(item_id: int, part_id: str, lang: str = "zh-CN", row: Any = None) -> str:
    """Return the maintained part name without reusing the old hand-written effect text."""
    if _lang_is_zh(lang):
        name = _part_row_value(row, "Name_ZH", "Name")
    else:
        name = _part_row_value(row, "Name_EN", "Name")
    if _valid_name(name):
        return name

    ref = _part_ref(item_id, part_id)
    fallback = ref.get("fallback_name") or {}
    key = "zh" if _lang_is_zh(lang) else "en"
    name = fallback.get(key) or fallback.get("en", "")
    if _valid_name(name):
        return name

    name, _source = _index_part_name(item_id, part_id, lang)
    if _valid_name(name):
        return name

    # Transition support for the old CSV: only its first barrel/behavior title is a name.
    legacy = _part_row_value(row, "Stat_ZH" if _lang_is_zh(lang) else "Stat_EN", "Stat")
    if ref.get("category") == "barrel":
        return legacy.split(",", maxsplit=1)[0].strip()
    if (ref.get("uistats") or ref.get("uistats_include")) and legacy and not re.match(
        r"^[+\-×x\d]|^(?:无|No\s+stat|Damage|Accuracy|Reload|Fire\s+Rate)\b", legacy, re.I
    ):
        return legacy.split(",", maxsplit=1)[0].strip()
    return ""


def _part_effect_value(effect: dict[str, Any], index: dict[str, Any]) -> float | None:
    defaults = (index.get("weapon_native_model") or {}).get("attribute_defaults") or {}
    value: Any = defaults.get(effect.get("value_attribute")) if effect.get("value_attribute") else None
    if value is None:
        value = effect.get("constant")
    if value is None:
        value = next((ref.get("value") for ref in effect.get("datatable_refs", []) if ref.get("value") is not None), None)
    if value is None:
        value = defaults.get(effect.get("attribute"))
    try:
        return float(value) * float(effect.get("postscale", 1))
    except (TypeError, ValueError):
        return None


def _part_mode_suffix(value: Any, lang: str) -> str:
    try:
        secondary_only = not (int(value) & 1) and bool(int(value) & 2)
    except (TypeError, ValueError):
        secondary_only = False
    if not secondary_only:
        return ""
    return "（副模式）" if _lang_is_zh(lang) else " (secondary mode)"


def _part_stat_context(decoded_full: str, item_id: int, index: dict[str, Any]) -> tuple[str, str]:
    model = index.get("weapon_native_model") or {}
    root_id = str(item_id)
    match = re.match(r"\s*(\d+)", decoded_full or "")
    if match:
        root_id = match.group(1)
    rarity = "Common"
    for key in weapon_display_stats._serial_part_keys(decoded_full or "", root_id):
        ref = (index.get("part_refs") or {}).get(key, {})
        if ref.get("rarity"):
            rarity = str(ref["rarity"])
    root = (model.get("items") or {}).get(root_id, {})
    provider = str(root.get("stats", "")).removesuffix("_weapon") or str(root.get("manufacturer", "")).lower()
    return rarity, provider


def _part_stat_operations(
    ref: dict[str, Any], decoded_full: str, item_id: int, index: dict[str, Any], lang: str
) -> tuple[list[str], dict[tuple[str, str], list[tuple[int, float]]]]:
    model = index.get("weapon_native_model") or {}
    stats = model.get("stats") or {}
    rarity, provider = _part_stat_context(decoded_full, item_id, index)
    rarity_scale = float((model.get("rarity_scales") or {}).get(rarity, 1.0))
    direct: list[str] = []
    operations: dict[tuple[str, str], list[tuple[int, float]]] = {}
    points: dict[tuple[str, str], float] = {}

    for modifier in ref.get("weapon_stat_modifiers", []):
        attr = str(modifier.get("attr") or "")
        if attr not in stats:
            continue
        value = _part_effect_value(modifier, index)
        if value is not None:
            mode = _part_mode_suffix(modifier.get("use_mode_bitmask"), lang)
            points[(attr, mode)] = points.get((attr, mode), 0.0) + value

    for (attr, mode), point in points.items():
        spec = stats[attr]
        delta = point * rarity_scale * float(spec.get("scalar", 0.0))
        delta *= float((spec.get("manufacturer_multipliers") or {}).get(provider, 1.0))
        if spec.get("invert"):
            delta = -delta
        label = _part_label(WEAPON_PART_STAT_LABELS.get(attr, (attr, attr)), lang)
        if attr == "CritDamage":
            if abs(delta) > 0.000001:
                direct.append(f"{label} {delta:+.0%}{mode}")
        else:
            operations.setdefault((label, mode), []).append((int(spec.get("modifier_type", 3)), 1.0 + delta))
    return direct, operations


def _part_direct_effects(
    ref: dict[str, Any], index: dict[str, Any], lang: str, skip: set[str]
) -> tuple[list[str], dict[tuple[str, str], list[tuple[int, float]]]]:
    direct: list[str] = []
    operations: dict[tuple[str, str], list[tuple[int, float]]] = {}
    seen: set[tuple[str, str, str, float, str]] = set()
    for effect in ref.get("weapon_attribute_effects", []):
        attr = str(effect.get("attribute") or "").lower()
        if attr in skip or attr in WEAPON_PART_INTERNAL_ATTRIBUTES or attr not in WEAPON_PART_ATTRIBUTE_LABELS:
            continue
        value = _part_effect_value(effect, index)
        if value is None:
            continue
        kind_name = str(effect.get("modifier_type") or "ScaleSimple")
        mode = _part_mode_suffix(effect.get("use_mode_bitmask"), lang)
        label = _part_label(WEAPON_PART_ATTRIBUTE_LABELS[attr], lang)
        source = str(effect.get("source_aspect") or "")
        signature = (label, mode, kind_name, round(value, 7), source)
        if signature in seen:
            continue
        seen.add(signature)

        if attr == "weapon_damage_modifier_add_critical_hit" and kind_name in {"PreAdd", "PostAdd", "ScaleSimple"}:
            if abs(value) > 0.000001:
                direct.append(f"{label} {value:+.0%}{mode}")
            continue
        if attr == "weapon_damage_radius" and kind_name in {"PreAdd", "PostAdd"}:
            if abs(value) > 0.000001:
                direct.append(f"{label} {value:+g}cm{mode}")
            continue
        if attr == "weapon_accuracy_impulse" and kind_name == "ScaleMultiply" and value < 0:
            continue
        if kind_name == "OverrideBaseValue":
            if attr in {"weapon_ted_throw_damage_scale", "weapon_ted_throw_radius", "weapon_ted_thrusterscalar"}:
                if abs(value - 1.0) > 0.000001:
                    operations.setdefault((label, mode), []).append((3, value))
            elif attr == "weapon_projectile_per_shot" and value > 1:
                direct.append(f"{label} {_part_number(value)}/发{mode}" if _lang_is_zh(lang) else f"{label} {_part_number(value)}/shot{mode}")
            elif attr == "weapon_shot_cost" and value > 1:
                direct.append(f"{label} {_part_number(value)}/发{mode}" if _lang_is_zh(lang) else f"{label} {_part_number(value)}/shot{mode}")
            elif attr == "weapon_damage_radius" and value > 0:
                direct.append(f"{label} {_part_number(value)}cm{mode}")
            elif attr in {"weapon_reload_time", "weapon_zoom_duration", "weapon_equip_time", "weapon_charge_time", "weapon_burst_fire_delay"} and value > 0:
                direct.append(f"{label} {_part_number(value)}s{mode}")
            elif attr in {"weapon_auto_burst_count", "weapon_ted_thrustercount"} and value > 1:
                direct.append(f"{label} {_part_number(value)}{mode}")
            elif attr == "weapon_max_loaded_ammo" and value > 0:
                direct.append(f"{label} {_part_number(value)}{mode}")
            elif attr == "weapon_zoom_fov_scale" and value > 0:
                direct.append(f"{label} ×{_part_number(value)}{mode}")
            continue
        kind = WEAPON_NATIVE_MODIFIER_TYPES.get(kind_name)
        if kind is not None:
            operations.setdefault((label, mode), []).append((kind, value))
    return direct, operations


def _format_part_operations(operations: dict[tuple[str, str], list[tuple[int, float]]]) -> list[str]:
    lines: list[str] = []
    for (label, mode), values in operations.items():
        positive = sum(value for kind, value in values if kind == 0 and value >= 0)
        negative = sum(value for kind, value in values if kind == 0 and value < 0)
        pre_add = sum(value for kind, value in values if kind == 1)
        post_add = sum(value for kind, value in values if kind == 2)
        product = 1.0
        for kind, value in values:
            if kind == 3:
                product *= value
        ratio = product * ((1.0 + positive) / (1.0 - negative)) * (1.0 + pre_add) + post_add
        if abs(ratio - 1.0) > 0.0005:
            lines.append(f"{label} ×{_part_number(ratio)}{mode}")
    return lines


def _magazine_description(ref: dict[str, Any], index: dict[str, Any], lang: str) -> tuple[list[str], set[str]]:
    if ref.get("category") != "magazine":
        return [], set()
    stats = ref.get("magazine_stats") or {}
    heat = stats.get("heat") or {}
    tags = {str(tag).lower() for tag in ref.get("weapon_tags", [])}
    lines: list[str] = []
    license_name = next((name for tag, name in (("borg_mag", "Borg"), ("tor_mag", "Torgue")) if tag in tags), "")
    if "cov_mag" in tags:
        lines.append("COV 机制" if _lang_is_zh(lang) else "COV Mechanism")
    elif license_name:
        lines.append(f"{license_name} 授权" if _lang_is_zh(lang) else f"{license_name}-licensed")

    capacity = stats.get("capacity")
    reload_time = stats.get("reload_time")
    heat_impulse = heat.get("heat_impulse")
    if capacity is None:
        capacity = next(
            (
                _part_effect_value(effect, index)
                for effect in ref.get("weapon_attribute_effects", [])
                if effect.get("attribute") == "weapon_max_loaded_ammo" and _weapon_native_primary_mode(effect.get("use_mode_bitmask"))
            ),
            None,
        )
    if reload_time is None:
        reload_time = next(
            (
                _part_effect_value(effect, index)
                for effect in ref.get("weapon_attribute_effects", [])
                if effect.get("attribute") == "weapon_reload_time" and _weapon_native_primary_mode(effect.get("use_mode_bitmask"))
            ),
            None,
        )
    if heat_impulse is None:
        heat_impulse = next(
            (
                _part_effect_value(effect, index)
                for effect in ref.get("weapon_attribute_effects", [])
                if effect.get("attribute") == "weapon_heat_impulse" and _weapon_native_primary_mode(effect.get("use_mode_bitmask"))
            ),
            None,
        )

    mechanism = str(heat.get("mechanism") or ("cov" if "cov_mag" in tags else ""))
    shots = heat.get("shots_to_overheat")
    if shots is None and mechanism == "cov" and heat_impulse:
        shots = 1.0 / float(heat_impulse)
    if mechanism == "cov":
        if shots:
            lines.append(f"约 {_part_number(float(shots), 1)} 发过热" if _lang_is_zh(lang) else f"~{_part_number(float(shots), 1)} shots to overheat")
        cooldown_rate = heat.get("cooldown_rate")
        if cooldown_rate:
            lines.append(f"散热速度 {_part_number(float(cooldown_rate))}/s" if _lang_is_zh(lang) else f"Cooling {_part_number(float(cooldown_rate))}/s")
        cooldown_delay = heat.get("cooldown_delay") or heat.get("overheat_cooldown_delay")
        if cooldown_delay:
            lines.append(f"散热延迟 {_part_number(float(cooldown_delay))}s" if _lang_is_zh(lang) else f"Cooling Delay {_part_number(float(cooldown_delay))}s")
        repair_time = heat.get("repair_time") or heat.get("overheat_time") or reload_time
        if repair_time:
            lines.append(f"完全过热维修 {_part_number(float(repair_time))}s" if _lang_is_zh(lang) else f"Overheat Repair {_part_number(float(repair_time))}s")
    else:
        if capacity is not None and float(capacity) > 0:
            lines.append(f"原始弹容 {_part_number(float(capacity))}" if _lang_is_zh(lang) else f"Base Capacity {_part_number(float(capacity))}")
        if reload_time is not None and float(reload_time) > 0:
            lines.append(f"装填时间 {_part_number(float(reload_time))}s" if _lang_is_zh(lang) else f"Reload Time {_part_number(float(reload_time))}s")
    return lines, {"weapon_max_loaded_ammo", "weapon_reload_time", "weapon_heat_impulse"}


def _thrown_reload_description(ref: dict[str, Any], lang: str) -> tuple[list[str], set[str]]:
    stats = ref.get("thrown_reload_stats") or {}
    if not stats:
        return [], set()
    reload_time = float(stats.get("reload_time", 2.0))
    complete = float(stats.get("reload_complete_percent", 0.75))
    if _lang_is_zh(lang):
        lines = [f"投掷换弹时间 {_part_number(reload_time)}s", f"换弹完成点 {complete:.0%}"]
    else:
        lines = [f"Thrown Reload {_part_number(reload_time)}s", f"Reload Complete {complete:.0%}"]
    return lines, {"weapon_reload_time", "weapon_reload_complete_percent"}


def _adapter_description(ref: dict[str, Any], lang: str) -> tuple[list[str], set[str]]:
    if ref.get("display_group") != "Borg Magazine Adapter":
        return [], set()
    for base_ref in ref.get("weapon_base_value_refs", []):
        value = (base_ref.get("values") or {}).get("maxloadedammo_value")
        try:
            capacity = float(value)
        except (TypeError, ValueError):
            continue
        text = f"弹匣容量 {_part_number(capacity)}" if _lang_is_zh(lang) else f"Magazine Capacity {_part_number(capacity)}"
        return [text], {"weapon_max_loaded_ammo"}
    return [], set()


def _part_behavior_text(ref: dict[str, Any], index: dict[str, Any], lang: str) -> str:
    key = "zh" if _lang_is_zh(lang) else "en"
    for uistat_id in [*ref.get("uistats_include", []), *ref.get("uistats", [])]:
        entry = (index.get("uistats") or {}).get(str(uistat_id).lower(), {})
        text = _clean_markup(entry.get(key, "") or entry.get("en", ""))
        if not text:
            continue
        for separator in (" - ", " – "):
            if separator in text:
                return text.split(separator, maxsplit=1)[1].strip()
        return text
    return ""


def _serial_with_weapon_part(decoded_full: str, item_id: int, part_id: str, category: str) -> str:
    if not decoded_full or "||" not in decoded_full:
        return decoded_full
    match = re.match(r"\s*(\d+)", decoded_full)
    if not match:
        return decoded_full
    root_id = match.group(1)
    header, components = decoded_full.split("||", maxsplit=1)
    refs = (_item_index().get("part_refs") or {})
    for current_id in re.findall(r"\{(\d+)\}", components):
        if refs.get(f"{root_id}:{current_id}", {}).get("category") == category:
            components = re.sub(rf"\{{{re.escape(current_id)}\}}", f"{{{part_id}}}", components, count=1)
            return f"{header}||{components}"
    end = components.rfind("|")
    if end >= 0:
        components = f"{components[:end].rstrip()} {{{part_id}}}{components[end:]}"
    else:
        components = f"{components.rstrip()} {{{part_id}}} |"
    return f"{header}||{components}"


def _ensure_weapon_rarity(decoded_full: str, item_id: int) -> str:
    refs = _item_index().get("part_refs") or {}
    root_id = str(item_id)
    if any(refs.get(key, {}).get("rarity") for key in weapon_display_stats._serial_part_keys(decoded_full, root_id)):
        return decoded_full
    common_id = next(
        (key.split(":", maxsplit=1)[1] for key, ref in refs.items() if key.startswith(f"{root_id}:") and ref.get("rarity") == "Common"),
        "",
    )
    return _serial_with_weapon_part(decoded_full, item_id, common_id, "inv_comp") if common_id else decoded_full


def _barrel_description(item_id: int, part_id: str, decoded_full: str, lang: str) -> list[str]:
    candidate = _ensure_weapon_rarity(_serial_with_weapon_part(decoded_full, item_id, part_id, "barrel"), item_id)
    if not candidate:
        return []
    stats = resolve_weapon_stats(candidate)
    if all(key in stats for key in ("damage", "accuracy", "fire_rate")):
        if _lang_is_zh(lang):
            lines = [f"{stats['damage']}伤害", f"{stats['accuracy']}%精准度", f"{float(stats['fire_rate']):.1f}/s射速"]
            optional = (("critical_damage", "%爆伤"), ("ammo_cost", "/发"), ("splash_radius", "cm爆炸范围"))
        else:
            lines = [f"{stats['damage']} Damage", f"{stats['accuracy']}% Accuracy", f"{float(stats['fire_rate']):.1f}/s Fire Rate"]
            optional = (("critical_damage", "% Crit"), ("ammo_cost", "/shot"), ("splash_radius", "cm Splash"))
        for key, suffix in optional:
            value = int(stats.get(key) or 0)
            if (key == "critical_damage" and value) or (key == "ammo_cost" and value > 1) or (key == "splash_radius" and value > 0):
                lines.append(f"{value:+d}{suffix}" if key == "critical_damage" else f"{value}{suffix}")
        return lines

    values = next((entry.get("values", {}) for entry in _part_ref(item_id, part_id).get("weapon_base_value_refs", []) if entry.get("values")), {})
    labels = {
        "accuracy_value": ("基础精准值", "Base Accuracy"),
        "firerate_value": ("基础射速", "Base Fire Rate"),
        "projectilespershot_value": ("弹丸数", "Projectiles"),
    }
    lines: list[str] = []
    for key, label in labels.items():
        value = values.get(key)
        if value is None or (key == "projectilespershot_value" and float(value) <= 1):
            continue
        suffix = "/发" if _lang_is_zh(lang) and key == "projectilespershot_value" else "/shot" if key == "projectilespershot_value" else "/s" if key == "firerate_value" else ""
        lines.append(f"{_part_label(label, lang)} {_part_number(float(value))}{suffix}")
    return lines


def _scope_description(item_id: int, part_id: str, decoded_full: str, lang: str) -> list[str]:
    candidate = _ensure_weapon_rarity(_serial_with_weapon_part(decoded_full, item_id, part_id, "scope"), item_id)
    if not candidate:
        return []
    ref = _part_ref(item_id, part_id)
    fov = next((_part_effect_value(effect, _item_index()) for effect in ref.get("weapon_attribute_effects", []) if effect.get("attribute") == "weapon_zoom_fov_scale"), None)
    try:
        ads_time = weapon_display_stats.ads_time_from_serial(candidate, _item_index())
    except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError):
        ads_time = None
    lines: list[str] = []
    if fov is not None:
        lines.append(f"瞄准视野 ×{_part_number(fov)}" if _lang_is_zh(lang) else f"ADS FOV ×{_part_number(fov)}")
    if ads_time is not None:
        lines.append(f"开镜时间 {_part_number(ads_time)}s" if _lang_is_zh(lang) else f"ADS Time {_part_number(ads_time)}s")
    return lines


def _ammo_switch_description(ref: dict[str, Any], lang: str) -> list[str]:
    stats = ref.get("ammo_switch_stats") or {}
    mode = stats.get("mode") or {}
    ammo = mode.get("ammo") or {}
    ammo_name = ammo.get("zh" if _lang_is_zh(lang) else "en", "")
    lines = []
    if ammo_name:
        lines.append(f"次要开火消耗{ammo_name}" if _lang_is_zh(lang) else f"Secondary fire consumes {ammo_name}")
    labels = {
        "damage_scale": ("伤害", "Damage"), "firerate_scale": ("射速", "Fire Rate"),
        "reloadtime_scale": ("装填时间", "Reload Time"), "spread_scale": ("扩散", "Spread"),
        "maxaccuracy_scale": ("最大精准度", "Max Accuracy"), "recoil_scale": ("后坐力", "Recoil"),
        "projpershot_scale": ("弹丸数", "Projectiles"), "ammocost_add": ("弹药消耗", "Ammo Cost"),
        "zoomduration_scale": ("开镜时间", "ADS Time"), "equiptime_scale": ("切枪时间", "Equip Time"),
        "putdowntime_scale": ("收枪时间", "Putdown Time"), "accimpulse_scale": ("精准度冲量", "Accuracy Impulse"),
        "critdamage_add": ("暴击伤害", "Crit Damage"),
    }
    for key, value in (stats.get("effects") or {}).items():
        key = str(key).lower()
        match = next(((suffix, label) for suffix, label in labels.items() if key.endswith(suffix)), None)
        if not match:
            continue
        suffix, label = match
        number = float(value)
        if suffix == "ammocost_add" and number:
            lines.append(f"{_part_label(label, lang)} +{_part_number(number)}/发" if _lang_is_zh(lang) else f"{_part_label(label, lang)} +{_part_number(number)}/shot")
        elif suffix.endswith("_add") and number:
            lines.append(f"{_part_label(label, lang)} {number:+.0%}")
        elif suffix.endswith("_value") and number:
            lines.append(f"{_part_label(label, lang)} +{_part_number(number)}")
        elif not suffix.endswith(("_add", "_value")) and abs(number - 1.0) > 0.0005:
            lines.append(f"{_part_label(label, lang)} ×{_part_number(number)}")
    return lines


def format_weapon_part_description(
    item_id: int, part_id: str, decoded_full: str = "", lang: str = "zh-CN", part_type: str = ""
) -> str:
    """Format only effects actually resolved for one weapon part."""
    index = _item_index()
    ref = (index.get("part_refs") or {}).get(f"{item_id}:{part_id}", {})
    fallback = "无属性变化" if _lang_is_zh(lang) else "No stat changes"
    if not ref:
        return fallback
    if part_type == "Body":
        return "固有配件" if _lang_is_zh(lang) else "Intrinsic Part"
    if ref.get("category") == "barrel":
        return ", ".join(_barrel_description(item_id, part_id, decoded_full, lang)) or fallback
    if ref.get("category") == "scope":
        scope_lines = _scope_description(item_id, part_id, decoded_full, lang)
        if scope_lines:
            return ", ".join(scope_lines)

    lines, skip = _magazine_description(ref, index, lang)
    thrown_lines, thrown_skip = _thrown_reload_description(ref, lang)
    adapter_lines, adapter_skip = _adapter_description(ref, lang)
    lines.extend(thrown_lines)
    lines.extend(adapter_lines)
    skip.update(thrown_skip)
    skip.update(adapter_skip)
    stat_lines, operations = _part_stat_operations(ref, decoded_full, item_id, index, lang)
    effect_lines, effect_operations = _part_direct_effects(ref, index, lang, skip)
    for key, values in effect_operations.items():
        operations.setdefault(key, []).extend(values)
    lines.extend(stat_lines)
    lines.extend(effect_lines)
    lines.extend(_format_part_operations(operations))

    tags = {str(tag).lower() for tag in ref.get("weapon_tags", [])}
    part_name = str(ref.get("part") or "").lower()
    if "part_underbarrel_05_ammoswitcher" in part_name:
        lines = [
            "启用弹药模式切换；具体模式由厂商授权部件选择"
            if _lang_is_zh(lang)
            else "Enables ammo mode switching; the manufacturer part selects the mode"
        ]
    elif ref.get("ammo_switch_stats"):
        lines = _ammo_switch_description(ref, lang)
    elif "part_barrel_licensed_hyp" in part_name:
        lines.insert(0, "启用亥伯龙前置武器护盾及其护盾配件" if _lang_is_zh(lang) else "Enables the Hyperion front weapon shield and its shield parts")
    elif "part_underbarrel_06_malswitch" in part_name:
        lines.insert(0, "在已配置的两种元素伤害间切换" if _lang_is_zh(lang) else "Switches between the two configured elemental damage types")

    behavior = _part_behavior_text(ref, index, lang)
    suppress_behavior = ref.get("category") == "barrel" or (ref.get("category") == "magazine" and bool(tags & {"cov_mag", "borg_mag"}))
    if behavior and not suppress_behavior and (not lines or "licensed" in tags or any("ted_" in tag for tag in tags)):
        lines.append(behavior)
    return ", ".join(dict.fromkeys(line for line in lines if line)) or fallback


def format_weapon_part_option(
    item_id: int, part_id: str, decoded_full: str = "", lang: str = "zh-CN", row: Any = None
) -> str:
    name = weapon_part_name(item_id, part_id, lang, row)
    description = format_weapon_part_description(item_id, part_id, decoded_full, lang, _part_row_value(row, "Part Type"))
    detail = ", ".join(part for part in (name, description) if part)
    return f"{part_id} - {detail}" if detail else str(part_id)


def weapon_part_selection_tags(item_id: int, part_id: str) -> dict[str, list[str]]:
    tags = _part_ref(item_id, part_id).get("selection_tags") or {}
    return {
        key: [str(value).lower() for value in tags.get(key, [])]
        for key in ("adds", "requires", "excludes")
        if tags.get(key)
    }


def _weapon_csv_barrel_name(item_id: int, part_id: str, lang: str) -> str:
    rows = _weapon_parts(lang)
    for row in rows:
        if row.get("Manufacturer & Weapon Type ID") != str(item_id) or row.get("Part ID") != str(part_id):
            continue
        if row.get("Part Type") != "Barrel":
            continue
        name = ((row.get("Name") or _text(row, lang)).split(",", maxsplit=1)[0] or "").strip()
        name = re.sub(r"\s+Barrel$", "", name).strip().replace("Ⅳ", "IV")
        if _valid_name(name):
            return name
    return ""


def _weapon_has_named_barrel_variant(item_id: int, ref: dict[str, Any], lang: str) -> bool:
    key = "zh" if _lang_is_zh(lang) else "en"
    tags = {str(tag).lower() for tag in ref.get("weapon_tags", [])}
    unique_tags = {tag for tag in tags if tag.startswith("uni_")}
    if not unique_tags:
        return False
    for part_key, other_ref in (_item_index().get("part_refs") or {}).items():
        if not str(part_key).startswith(f"{item_id}:"):
            continue
        if other_ref.get("category") != "barrel_acc":
            continue
        other_tags = {str(tag).lower() for tag in other_ref.get("weapon_tags", [])}
        if not unique_tags.intersection(other_tags):
            continue
        name = (other_ref.get("name") or {}).get(key) or (other_ref.get("name") or {}).get("en", "")
        if _valid_name(name):
            return True
    return False


def _weapon_root_name(item_id: int, ids: list[str], lang: str) -> tuple[str, str]:
    key = "zh" if _lang_is_zh(lang) else "en"
    if item_id == 11 and ("7" in ids or "8" in ids) and any(part_id in ids for part_id in ("79", "80")):
        names: list[str] = []
        barrel_id = "8" if "8" in ids else "7"
        for part_id in (barrel_id, "79"):
            ref = _part_ref(item_id, part_id)
            name = ((ref.get("name") or {}).get(key) or (ref.get("name") or {}).get("en", "")).strip()
            if _valid_name(name) and name not in names:
                names.append(name)
        if names:
            return " ".join(names), "ncs_name"
    for part_id in ids:
        ref = _part_ref(item_id, part_id)
        tags = {str(tag).lower() for tag in ref.get("weapon_tags", [])}
        if ref.get("category") == "barrel_acc" and any(tag.startswith("uni_") for tag in tags):
            name = ((ref.get("name") or {}).get(key) or (ref.get("name") or {}).get("en", "")).strip()
            if _valid_name(name):
                return name, "ncs_name"
    for part_id in ids:
        ref = _part_ref(item_id, part_id)
        if ref.get("category") != "barrel":
            continue
        ncs_name = ((ref.get("name") or {}).get(key) or (ref.get("name") or {}).get("en", "")).strip()
        if item_id == 16 and part_id == "1" and "71" in ids and _valid_name(ncs_name):
            return ("升级版" + ncs_name) if _lang_is_zh(lang) else ("Upgraded " + ncs_name), "ncs_name"
        csv_name = _weapon_csv_barrel_name(item_id, part_id, lang)
        if item_id == 3 and part_id == "75" and _valid_name(ncs_name):
            return ncs_name, "ncs_name"
        if _valid_name(ncs_name) and "·" in ncs_name:
            return ncs_name, "ncs_name"
        if _weapon_has_named_barrel_variant(item_id, ref, lang) and _valid_name(ncs_name):
            return ncs_name, "ncs_name"
        if _valid_name(csv_name):
            return csv_name, "weapon_csv"
        if _valid_name(ncs_name):
            return ncs_name, "ncs_name"
    return "", ""


def _weapon_tag_match(tags: set[str], needle: str) -> bool:
    return any(needle in tag for tag in tags)


def _weapon_strategy_value(row: dict[str, Any], key: str) -> Any:
    if key in row:
        return row.get(key)
    prefix = key + "_"
    for row_key, value in row.items():
        row_key = str(row_key).lower()
        if row_key == key or row_key.startswith(prefix):
            return value
    return None


WEAPON_SPECIAL_ROW_CATEGORIES = {"barrel_acc", "hyperion_secondary_acc", "magazine_ted_thrown"}
WEAPON_SPECIAL_MAG_CATEGORIES = {"magazine", "magazine_acc", "magazine_ted_thrown"}
WEAPON_PAYLOAD_TAGS = {
    "ted_default_payload",
    "ted_javelin",
    "ted_homing",
    "ted_legs",
    "ted_shooting",
    "ted_mirv",
    "ted_combo",
    "ted_replicator",
}


def _weapon_special_tag_sets(item_id: int, ids: list[str]) -> tuple[set[str], set[str], set[str]]:
    row_tags: set[str] = set()
    mag_tags: set[str] = set()
    payload_tags: set[str] = set()
    for part_id in ids:
        ref = _part_ref(item_id, part_id)
        category = str(ref.get("category") or "")
        tags = {str(tag).lower() for tag in ref.get("weapon_tags", [])}
        if category in WEAPON_SPECIAL_MAG_CATEGORIES:
            mag_tags.update(tag for tag in tags if any(marker in tag for marker in ("borg_mag", "cov_mag", "tor_mag")))
        if category in WEAPON_SPECIAL_ROW_CATEGORIES:
            row_tags.update(tag for tag in tags if any(marker in tag for marker in ("hyp_shield", "jak_barrel_acc")))
        if category != "inv_comp":
            payload_tags.update(tag for tag in tags if any(marker in tag for marker in WEAPON_PAYLOAD_TAGS))
            if (
                "licensed_ted" in tags
                and (category == "magazine_ted_thrown" or any(_weapon_tag_match(tags, marker) for marker in WEAPON_PAYLOAD_TAGS))
            ):
                row_tags.add("licensed_ted")
    return row_tags, mag_tags, payload_tags


def _weapon_special_prefix(
    strategy: dict[str, Any],
    row_tags: set[str],
    mag_tags: set[str],
    payload_tags: set[str],
    lang: str,
    use_payload: bool = True,
    include_default: bool = False,
) -> str:
    mag_table = strategy.get("mag_prefix") or {}
    if not mag_table:
        return ""
    row_key = "default"
    for candidate in ("hyp_shield", "jak_barrel_acc", "licensed_ted"):
        if _weapon_tag_match(row_tags, candidate):
            row_key = candidate
            break
    if row_key not in mag_table:
        row_key = "default"
    row = mag_table.get(row_key) or {}
    if use_payload and (row.get("_use_payload_prefix") or any(str(key).lower().startswith("use_payload_prefix") for key in row)):
        return _weapon_payload_prefix(strategy, payload_tags, lang)
    col_key = ""
    for candidate in ("borg_mag", "cov_mag", "tor_mag"):
        if _weapon_tag_match(mag_tags, candidate) and _weapon_strategy_value(row, candidate):
            col_key = candidate
            break
    if not col_key:
        text = _strategy_text(_weapon_strategy_value(row, "default"), lang) if row_key != "default" or include_default else ""
    else:
        text = _strategy_text(_weapon_strategy_value(row, col_key) or _weapon_strategy_value(row, "default"), lang)
    return text.lstrip("-").strip()


def _weapon_payload_prefix(strategy: dict[str, Any], tags: set[str], lang: str) -> str:
    table = strategy.get("payload_prefix") or {}
    if not table:
        return ""
    payload_rows = [row for row in table if row != "default"]
    payload_rows.sort(key=lambda row: row.count("+"), reverse=True)
    row_key = "default"
    for row in payload_rows:
        if all(_weapon_tag_match(tags, piece) for piece in row.split("+")):
            row_key = row
            break
    col_key = "default"
    for candidate in ("ted_javelin", "ted_homing", "ted_legs"):
        if _weapon_tag_match(tags, candidate):
            col_key = candidate
            break
    row = table.get(row_key) or {}
    return _strategy_text(_weapon_strategy_value(row, col_key) or _weapon_strategy_value(row, "default"), lang)


WEAPON_NATIVE_TYPES = {
    **{item_id: "Pistol" for item_id in WEAPON_PISTOL_IDS},
    **{item_id: "Shotgun" for item_id in WEAPON_SHOTGUN_IDS},
    **{item_id: "AssaultRifle" for item_id in WEAPON_AR_IDS},
    **{item_id: "SMG" for item_id in WEAPON_SMG_IDS},
    **{item_id: "Sniper" for item_id in WEAPON_SNIPER_IDS},
}
WEAPON_STAT_KEYS = (
    "damage",
    "dps",
    "accuracy",
    "fire_rate",
    "reload_time",
    "magazine",
    "critical_damage",
    "ammo_cost",
    "splash_radius",
    "ads_time",
    "equip_time",
)
WEAPON_NATIVE_ATTRIBUTES = {
    "weapon_damage": "Damage",
    "weapon_damage_modifier_add_critical_hit": "CritDamage",
    "weapon_fire_rate": "FireRate",
    "weapon_reload_time": "ReloadSpeed",
    "weapon_max_loaded_ammo": "MagSize",
    "weapon_spread": "Accuracy",
    "weapon_damage_modifier_base_status_effect_damage": "ElementalPower",
    "weapon_zoom_duration": "ADSProficiency",
}
WEAPON_NATIVE_MODIFIER_TYPES = {
    "ScaleSimple": 0,
    "PreAdd": 1,
    "PostAdd": 2,
    "ScaleMultiply": 3,
    "OverrideBaseValue": 4,
}
WEAPON_FOCUS_POINTS = {
    "51": ("Damage", ("FireRate", "ReloadSpeed", "Accuracy")),
    "52": ("ReloadSpeed", ("Damage", "FireRate", "MagSize")),
    "53": ("FireRate", ("Damage", "ReloadSpeed", "Accuracy")),
    "54": ("Accuracy", ("Damage", "FireRate", "ReloadSpeed")),
}


def _weapon_native_primary_mode(value: Any) -> bool:
    if value in (None, ""):
        return True
    try:
        return bool(int(value) & 1)
    except (TypeError, ValueError):
        return True


def _weapon_native_effect_value(effect: dict[str, Any]) -> float | None:
    value: Any = effect.get("constant")
    for ref in effect.get("datatable_refs", []):
        if "value" in ref:
            value = ref["value"]
            break
    try:
        return float(value) * float(effect.get("postscale", 1))
    except (TypeError, ValueError):
        return None


def _weapon_native_ratios(
    item_id: int,
    components: list[dict[str, Any]],
    ids: list[str],
    index: dict[str, Any] | None = None,
) -> dict[str, float]:
    index = index or _item_index()
    model = index.get("weapon_native_model") or {}
    stats = model.get("stats") or {}
    modifiers: dict[str, list[tuple[int, float]]] = {attr: [] for attr in stats}

    if any(part.get("type") == "elemental" and str(part.get("id")) == "1" for part in components):
        modifiers.setdefault("Damage", []).append((3, 0.8))

    type_row = WEAPON_NATIVE_TYPES.get(item_id, "")
    for attr, value in (model.get("type_initializers") or {}).get(type_row, {}).items():
        modifiers.setdefault(attr, []).append((1 if attr == "CritDamage" else 3, float(value)))

    refs = index.get("part_refs") or {}
    root = (model.get("items") or {}).get(str(item_id), {})
    effects = list(root.get("attribute_effects", []))
    rarity = "Common"
    points: dict[str, float] = {}
    dual_damage = False
    native_ids = [str(part["id"]) for part in components if part.get("type") == "simple"]
    for part_id in native_ids:
        ref = refs.get(f"{item_id}:{part_id}", {})
        if ref.get("rarity"):
            rarity = str(ref["rarity"])
        part_effects = list(ref.get("weapon_attribute_effects", []))
        if ref.get("category") == "magazine":
            present = {str(effect.get("attribute", "")) for effect in part_effects}
            for base_ref in ref.get("weapon_base_value_refs", []):
                values = base_ref.get("values") or {}
                for column, attribute in (
                    ("damage_scale", "weapon_damage"),
                    ("firerate_scale", "weapon_fire_rate"),
                    ("spread_scale", "weapon_spread"),
                ):
                    if attribute not in present and column in values:
                        part_effects.append(
                            {"attribute": attribute, "modifier_type": "ScaleMultiply", "constant": values[column]}
                        )
                        present.add(attribute)
        effects.extend(part_effects)
        dual_damage = dual_damage or "leg_dualdamage" in ref.get("weapon_tags", [])
        for modifier in ref.get("weapon_stat_modifiers", []):
            attr = str(modifier.get("attr", ""))
            if not attr or (attr != "MagSize" and not _weapon_native_primary_mode(modifier.get("use_mode_bitmask"))):
                continue
            raw_point: Any = modifier.get("constant")
            if raw_point is None:
                raw_point = next((item.get("value") for item in modifier.get("datatable_refs", []) if "value" in item), None)
            try:
                point = float(raw_point)
            except (TypeError, ValueError):
                continue
            points[attr] = points.get(attr, 0.0) + point

    if dual_damage:
        modifiers.setdefault("Damage", []).append((3, 0.8))

    focus_parts = _group_sub_ids(components, "1")
    stat_focus = WEAPON_FOCUS_POINTS.get(focus_parts[-1]) if len(focus_parts) == 2 else None
    if stat_focus:
        focus, donors = stat_focus
        for attr in donors:
            points[attr] = points.get(attr, 0.0) - 1.0
        points[focus] = points.get(focus, 0.0) + 3.0

    rarity_scale = float((model.get("rarity_scales") or {}).get(rarity, 1.0))
    manufacturer = str(root.get("stats", "")).removesuffix("_weapon") or str(root.get("manufacturer", ""))
    for attr, point in points.items():
        spec = stats.get(attr) or {}
        if not spec:
            continue
        multiplier = float((spec.get("manufacturer_multipliers") or {}).get(manufacturer, 1.0))
        delta = point * rarity_scale * float(spec.get("scalar", 0.0)) * multiplier
        if spec.get("invert"):
            delta = -delta
        modifier_type = int(spec.get("modifier_type", 3))
        modifiers.setdefault(attr, []).append((modifier_type, delta if modifier_type == 1 else 1.0 + delta))

    for effect in effects:
        if not _weapon_native_primary_mode(effect.get("use_mode_bitmask")):
            continue
        attr = WEAPON_NATIVE_ATTRIBUTES.get(str(effect.get("attribute", "")).lower())
        modifier_type = WEAPON_NATIVE_MODIFIER_TYPES.get(str(effect.get("modifier_type") or "ScaleSimple"))
        value = _weapon_native_effect_value(effect)
        if attr and modifier_type is not None and value is not None:
            modifiers.setdefault(attr, []).append((modifier_type, value))

    ratios: dict[str, float] = {}
    for attr, values in modifiers.items():
        positive = sum(value for kind, value in values if kind == 0 and value >= 0)
        negative = sum(value for kind, value in values if kind == 0 and value < 0)
        pre_add = sum(value for kind, value in values if kind == 1)
        post_add = sum(value for kind, value in values if kind == 2)
        product = 1.0
        for kind, value in values:
            if kind == 3:
                product *= value
        ratios[attr] = product * ((1.0 + positive) / (1.0 - negative)) * (1.0 + pre_add) + post_add
    return ratios


def _weapon_native_prefix(strategy: dict[str, Any], ratios: dict[str, float], lang: str) -> str:
    passed: dict[str, tuple[bool, bool]] = {}
    for attr, thresholds in (strategy.get("thresholds") or {}).items():
        first = thresholds.get("first")
        second = thresholds.get("second")
        if first is None or second is None or (abs(float(first)) < 0.0001 and abs(float(second)) < 0.0001):
            continue
        ratio = ratios.get(attr, 1.0)
        passed[attr] = (
            ratio > float(first) if float(first) >= 1.0 else ratio < float(first),
            ratio > float(second) if float(second) >= 1.0 else ratio < float(second),
        )
    for item in strategy.get("native_names", []):
        attrs = [str(attr) for attr in item.get("attrs", []) if attr]
        threshold_index = 1 if item.get("kind") == "double" else 0
        if attrs and all(passed.get(attr, (False, False))[threshold_index] for attr in attrs):
            return _strategy_text(item, lang)
    return ""


def _weapon_native_item_prefix(
    item_id: int,
    components: list[dict[str, Any]],
    index: dict[str, Any],
    lang: str,
) -> str:
    native_ids = [str(part["id"]) for part in components if part.get("type") == "simple"]
    refs = index.get("part_refs") or {}
    if any(str(refs.get(f"{item_id}:{part_id}", {}).get("disable_prefixes", "")).casefold() == "true" for part_id in native_ids):
        return ""
    strategy = (index.get("weapon_strategies") or {}).get(str(item_id), {})
    return _weapon_native_prefix(strategy, _weapon_native_ratios(item_id, components, native_ids, index), lang)


def _weapon_name(item_id: int, components: list[dict[str, Any]], ids: list[str], lang: str) -> tuple[str, str]:
    root, root_source = _weapon_root_name(item_id, ids, lang)
    index = _item_index()
    strategy = (index.get("weapon_strategies") or {}).get(str(item_id), {})
    if not strategy:
        return root, root_source
    row_tags, mag_tags, payload_tags = _weapon_special_tag_sets(item_id, ids)
    attr_prefix = _weapon_native_item_prefix(item_id, components, index, lang)
    if item_id in WEAPON_PISTOL_IDS:
        special_prefix = _weapon_special_prefix(
            strategy,
            row_tags,
            mag_tags,
            payload_tags,
            lang,
            use_payload=False,
            include_default=item_id == 5 and "59" in ids,
        )
    elif item_id in WEAPON_AR_IDS:
        special_prefix = _weapon_special_prefix(
            strategy,
            row_tags,
            mag_tags,
            payload_tags,
            lang,
            use_payload=False,
            include_default=item_id == 14 and "39" in ids,
        )
    elif item_id in WEAPON_SNIPER_IDS:
        special_prefix = _weapon_special_prefix(strategy, row_tags, mag_tags, payload_tags, lang, use_payload=False)
    elif item_id in WEAPON_SMG_IDS:
        special_prefix = _weapon_special_prefix(strategy, row_tags, mag_tags, payload_tags, lang, use_payload=False)
    elif item_id in WEAPON_SHOTGUN_IDS:
        special_prefix = _weapon_special_prefix(
            strategy,
            row_tags,
            mag_tags,
            payload_tags,
            lang,
            use_payload=False,
            include_default=item_id == 11,
        )
    else:
        special_prefix = _weapon_special_prefix(strategy, row_tags, mag_tags, payload_tags, lang)
    if item_id == 26 and "83" in ids and "84" in ids:
        # ponytail: observed Solar Temper suppresses sniper special prefixes; promote to data if more roots need it.
        special_prefix = ""
    if item_id in WEAPON_SNIPER_IDS and not attr_prefix:
        special_prefix = ""
    words = [
        special_prefix,
        attr_prefix,
        root,
    ]
    name = " ".join(word for word in words if word).strip()
    return name, "weapon_strategy" if name != root else root_source


def _rarity_from_csv(item_id: int, ids: list[str], item_type: str, lang: str) -> str:
    if item_type == "Class Mod":
        for part_id in ids:
            rarity = CLASSMOD_RARITY_CODES.get(item_id, {}).get(part_id)
            if rarity:
                return _rarity_text(rarity, lang)
    if item_type in WEAPON_TYPES:
        for part_id in ids:
            for row in _weapon_rarity():
                if row.get("Manufacturer & Weapon Type ID") == str(item_id) and row.get("Part ID") == str(part_id):
                    return _rarity_text(row.get("Stat", ""), lang)
    if item_type == "Enhancement":
        for part_id in ids:
            for row in _rows_by_file("enhancement/Enhancement_rarity.csv"):
                if row.get("manufacturers_ID") == str(item_id) and row.get("rarity_ID") == str(part_id):
                    return _rarity_text(row.get("rarity", ""), lang)
    for part_id in ids:
        row = _find_csv_part(item_id, part_id, item_type)
        if row and (row.get("Part_type") or "").strip() == "Rarity":
            return _rarity_text(_text(row, lang), lang)
    return ""


def _first_combo(ids: list[str], rules: list[dict[str, Any]]) -> tuple[int, dict[str, Any]] | None:
    seen: set[str] = set()
    for pos, part_id in enumerate(ids):
        seen.add(part_id)
        for rule in rules:
            combo = [str(item) for item in rule.get("ids", [])]
            if part_id in combo and all(item in seen for item in combo):
                return pos, rule
    return None


def _first_single(ids: list[str], singles: list[dict[str, Any]]) -> dict[str, Any] | None:
    by_id = {str(item.get("id")): item for item in singles}
    for part_id in ids:
        if part_id in by_id:
            return by_id[part_id]
    return None


def _heavy_strategy_word(item_id: int, ids: list[str], section: str, lang: str) -> str:
    strategy = (_item_index().get("heavy_strategies") or {}).get(str(item_id))
    if not strategy:
        return ""
    key = "zh" if _lang_is_zh(lang) else "en"
    item = _first_combo(ids, strategy.get(section, {}).get("rules", []))
    rule = item[1] if item else _first_single(ids, strategy.get(section, {}).get("singles", []))
    return (rule.get(key) or rule.get("en", "")).strip() if rule else ""


def _heavy_canonical_ids(item_id: int, ids: list[str]) -> list[str]:
    canonical: list[str] = []
    suffix_map = {
        "body": {"a": "7", "b": "8", "c": "9", "d": "10"},
        "barrel_01": {"a": "13", "b": "14", "c": "15", "d": "16"},
        "barrel_02": {"a": "17", "b": "18", "c": "19", "d": "20"},
    }
    for part_id in ids:
        row = _find_csv_part(item_id, part_id, HEAVY_TYPE)
        part_string = (row or {}).get("String", "").strip().lower()
        match = re.fullmatch(r"(body|barrel_01|barrel_02)_([a-d])", part_string)
        if match:
            canonical.append(suffix_map[match.group(1)][match.group(2)])
    return canonical


def _heavy_barrel_row(item_id: int, ids: list[str]) -> dict[str, str] | None:
    for part_id in ids:
        row = _find_csv_part(item_id, part_id, HEAVY_TYPE)
        if row and (row.get("Part_type") or "").strip() == "Barrel":
            return row
    return None


def _heavy_has_legendary_rarity(item_id: int, ids: list[str]) -> bool:
    for part_id in ids:
        row = _find_csv_part(item_id, part_id, HEAVY_TYPE)
        if row and (row.get("Part_type") or "").strip() == "Rarity":
            if (row.get("Stat_EN") or row.get("Stat") or "").strip().lower() == "legendary":
                return True
    return False


def _heavy_barrel_section(part_string: str) -> str:
    text = part_string.strip().lower()
    if text.startswith("barrel_01") or text.startswith("part_barrel_01"):
        return "barrel1"
    if text.startswith("barrel_02") or text.startswith("part_barrel_02"):
        return "barrel2"
    if text.startswith("barrel_"):
        return "barrel1"
    return ""


def _heavy_regular_barrel_name(item_id: int, section: str, lang: str) -> str:
    target = {"barrel1": "barrel_01", "barrel2": "barrel_02"}.get(section)
    if not target:
        return ""
    for row in _csv_rows_for_type(HEAVY_TYPE):
        if row.get("Manufacturer ID", "").strip() != str(item_id):
            continue
        if (row.get("Part_type") or "").strip() != "Barrel":
            continue
        if row.get("String", "").strip().lower() == target:
            return _title_from_text(_text(row, lang))
    return ""


def _strip_skin_suffix(text: str) -> str:
    text = _title_from_text(text)
    text = re.sub(r"\s*skin\s*$", "", text, flags=re.IGNORECASE).strip()
    return re.sub(r"\s*皮肤\s*$", "", text).strip()


def _heavy_legendary_skin_name(item_id: int, ids: list[str], lang: str) -> str:
    for part_id in ids:
        row = _find_csv_part(item_id, part_id, HEAVY_TYPE)
        if not row or (row.get("Part_type") or "").strip() != "Rarity":
            continue
        if (row.get("Stat_EN") or row.get("Stat") or "").strip().lower() != "legendary":
            continue
        name = _strip_skin_suffix(_desc(row, lang))
        if _valid_name(name):
            return name
    return ""


def _heavy_name(item_id: int, ids: list[str], lang: str) -> tuple[str, str]:
    canonical_ids = _heavy_canonical_ids(item_id, ids)
    prefix = _heavy_strategy_word(item_id, canonical_ids, "body", lang)
    if any(str(_part_ref(item_id, part_id).get("disable_prefixes", "")).casefold() == "true" for part_id in ids):
        prefix = ""
    barrel_row = _heavy_barrel_row(item_id, ids)
    barrel_name = ""
    source = "heavy_strategy"

    if barrel_row:
        barrel_string = barrel_row.get("String", "").strip().lower()
        section = _heavy_barrel_section(barrel_string)
        is_special = barrel_string not in {"barrel_01", "barrel_02"}
        if is_special and _heavy_has_legendary_rarity(item_id, ids):
            barrel_name = _heavy_legendary_skin_name(item_id, ids, lang) or _title_from_text(_text(barrel_row, lang))
            source = "heavy_skin"
        elif section:
            barrel_name = _heavy_strategy_word(item_id, canonical_ids, section, lang)
        if not barrel_name:
            barrel_name = _heavy_regular_barrel_name(item_id, section, lang) if is_special else _title_from_text(_text(barrel_row, lang))
            source = "heavy_csv"

    if not barrel_name:
        barrel_name, _unused_rarity, source = _csv_fallback_name(item_id, ids, HEAVY_TYPE, lang)

    name = _with_prefix(prefix, barrel_name)
    return name, source if name else ""


def _classmod_name(item_id: int, ids: list[str], lang: str) -> tuple[str, str, str]:
    normal_rarity = _rarity_from_csv(item_id, ids, "Class Mod", lang)
    prefix = _classmod_prefix(item_id, ids, lang)
    names = _rows_by_file("class_mods/Class_rarity_name.csv")
    by_code = {
        (row.get("class_ID", "").strip(), row.get("name_code", "").strip()): row
        for row in names
    }
    pairs = [
        (row.get("L_name_ID", "").strip(), row.get("item_card_ID", "").strip())
        for row in _rows_by_file("class_mods/Class_legendary_map.csv")
        if row.get("class_ID", "").strip() == str(item_id)
    ]
    seen: set[str] = set()
    for part_id in ids:
        seen.add(part_id)
        for name_id, card_id in pairs:
            if name_id in seen and card_id in seen:
                row = by_code.get((str(item_id), name_id))
                if row:
                    key = "name_ZH" if _lang_is_zh(lang) else "name_EN"
                    rarity = _rarity_text(row.get("rarity", ""), lang)
                    name = _with_prefix(prefix, row.get(key, "") or row.get("name_EN", ""))
                    return name, rarity, "classmod_pair"
    for part_id in ids:
        row = by_code.get((str(item_id), part_id))
        if row:
            key = "name_ZH" if _lang_is_zh(lang) else "name_EN"
            row_rarity = row.get("rarity", "")
            rarity = normal_rarity if row_rarity == "normal" else _rarity_text(row_rarity, lang)
            name = _with_prefix(prefix, row.get(key, "") or row.get("name_EN", ""))
            return name, rarity, "classmod_csv"
        ref = _part_ref(item_id, part_id)
        if ref.get("category") == "class_mod_body":
            key = "zh" if _lang_is_zh(lang) else "en"
            body_name = (ref.get("name") or {}).get(key) or (ref.get("name") or {}).get("en", "")
            if _valid_name(body_name):
                return _with_prefix(prefix, body_name), normal_rarity, "classmod_index"
    return "", "", ""


def _with_prefix(prefix: str, name: str) -> str:
    if not prefix or not name or name.startswith(prefix + " "):
        return name
    return f"{prefix} {name}"


def _classmod_prefix(item_id: int, ids: list[str], lang: str) -> str:
    prefixes = (_item_index().get("classmod_prefixes") or {}).get(str(item_id), {})
    key = "zh" if _lang_is_zh(lang) else "en"
    seen_bodies: list[str] = []
    seen_passives: list[str] = []
    for part_id in ids:
        ref = _part_ref(item_id, part_id)
        if ref.get("category") == "class_mod_body":
            body = ref.get("part", "")
            if body and body not in seen_bodies:
                seen_bodies.append(body)
        elif ref.get("category") == "passive_points":
            seen_passives.append(part_id)
    for body in seen_bodies:
        body_rules = prefixes.get(body, {})
        native_rows = body_rules.get("_native", [])
        if native_rows:
            candidates: dict[tuple[str, str], dict[str, Any]] = {}
            for order, passive_id in enumerate(seen_passives):
                for passive in _part_ref(item_id, passive_id).get("passives", []):
                    actual = (str(passive.get("graph", "")).casefold(), str(passive.get("node", "")).casefold())
                    candidate = candidates.setdefault(actual, {"points": 0, "order": order})
                    candidate["points"] += 1
            selected: tuple[float, int, int, dict[str, Any]] | None = None
            for actual, candidate in candidates.items():
                configured = next(
                    (row for row in native_rows if str(row.get("node", "")).casefold() == actual[1]),
                    None,
                )
                if not configured:
                    continue
                max_points = int(configured.get("max_points", 5)) or 5
                ranked = (-candidate["points"] / max_points, max_points, candidate["order"], configured)
                if selected is None or ranked[:3] < selected[:3]:
                    selected = ranked
            if selected:
                return selected[3].get(key) or selected[3].get("en", "")
        for passive_id in seen_passives:
            item = body_rules.get(passive_id)
            if item:
                return item.get(key) or item.get("en", "")
    return ""


def _csv_fallback_name(item_id: int, ids: list[str], item_type: str, lang: str) -> tuple[str, str, str]:
    for part_id in ids:
        row = _find_csv_part(item_id, part_id, item_type)
        if not row:
            continue
        part_type = (row.get("Part_type") or "").strip()
        text = _text(row, lang)
        if part_type == "Rarity":
            continue
        if part_type in GENERIC_PART_TYPES and item_type == "Shield":
            continue
        title = _title_from_text(text)
        if _valid_name(title):
            return title, "", "csv"
    return "", "", ""


def resolve_weapon_stats(decoded_full: str) -> dict[str, Any]:
    try:
        return weapon_display_stats.weapon_card_stats_from_serial(decoded_full, _item_index())
    except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError):
        return {}


def format_weapon_stat(key: str, value: Any, lang: str = "zh-CN") -> str:
    if value is None or value == "":
        return ""
    if key == "accuracy":
        return f"{int(value)}%"
    if key == "dps":
        return f"{int(value):,}"
    if key == "fire_rate":
        return f"{float(value):.1f}/s"
    if key == "reload_time":
        return f"{float(value):.1f}s"
    if key in {"ads_time", "equip_time"}:
        return f"{float(value):.2f}s"
    if key == "critical_damage":
        return f"{int(value):+d}%" if value else "0%"
    if key == "ammo_cost":
        suffix = {"zh-CN": "发", "ru": "выстрел", "ua": "постріл"}.get(lang, "shot")
        return f"{int(value)}/{suffix}"
    if key == "splash_radius":
        return f"{int(value)}cm"
    return str(value)


def resolve_item_display(
    item_id: int,
    manufacturer: str,
    item_type: str,
    decoded_full: str,
    lang: str = "zh-CN",
) -> dict[str, str]:
    try:
        component_part = decoded_full.split("||", maxsplit=1)[1]
    except IndexError:
        component_part = ""
    components = _parse_components(component_part)
    ids = _ordered_ids(components)
    simple_ids = _simple_ids(components)
    enhancement_stat_ids = _group_sub_ids(components, "247")
    rarity_ids = simple_ids if item_type == "Enhancement" else ids

    name = ""
    rarity = _rarity_from_csv(item_id, rarity_ids, item_type, lang)
    pearl_ids = {str(value) for value in range(51, 61)}
    if item_type in WEAPON_TYPES and any(
        str(part.get("id", "")) == "1"
        and (
            str(part.get("sub_id", "")) in pearl_ids
            or bool(pearl_ids.intersection(map(str, part.get("sub_ids", []))))
        )
        for part in components
        if part.get("type") in {"elemental", "group"}
    ):
        rarity = _rarity_text("Pearl", lang)
    source = ""

    if item_type in WEAPON_TYPES:
        name, source = _weapon_name(item_id, components, ids, lang)
    elif item_type == HEAVY_TYPE:
        name, source = _heavy_name(item_id, ids, lang)
    elif item_type == "Class Mod":
        name, rarity, source = _classmod_name(item_id, ids, lang)
    elif item_type == "Enhancement":
        name, source = _enhancement_name(item_id, simple_ids, enhancement_stat_ids, lang)
    elif item_type in {"Grenade", "Shield", "Repkit"}:
        name, source = _nonweapon_name(item_id, components, lang)
        if item_type == "Shield":
            shield_prefix = _shield_prefix(item_id, components, lang)
            if shield_prefix:
                name = f"{shield_prefix} {name}".strip()
                source = "shield_name_table"
        if not name or not any(_part_ref(item_id, part_id).get("title_part_list") for part_id in simple_ids):
            found_fallback = False
            for part_id in simple_ids:
                ref = _part_ref(item_id, part_id)
                if ref.get("category") not in {"body", "payload", "unique", "primary_augment", "secondary_augment"}:
                    continue
                fallback_name, fallback_source = _index_part_name(item_id, part_id, lang)
                if fallback_name:
                    name = f"{name} {fallback_name}".strip() if name else fallback_name
                    source = source or fallback_source
                    found_fallback = True
                    break
            if not found_fallback:
                fallback_name, _unused_rarity, fallback_source = _csv_fallback_name(item_id, ids, item_type, lang)
                if fallback_name:
                    name = f"{name} {fallback_name}".strip() if name else fallback_name
                    source = source or fallback_source
    else:
        for part_id in ids:
            name, source = _index_part_name(item_id, part_id, lang)
            if name:
                break
        if not name:
            name, _unused_rarity, source = _csv_fallback_name(item_id, ids, item_type, lang)

    manufacturer_display = manufacturer
    item_type_display = item_type
    fallback = f"{manufacturer_display} {item_type_display}".strip()
    display_name = name if _valid_name(name) else fallback
    return {
        "display_name": display_name,
        "rarity": rarity,
        "display_source": source or "fallback",
        "parts_summary": " ".join(f"{{{item}}}" for item in ids[:12]),
    }
