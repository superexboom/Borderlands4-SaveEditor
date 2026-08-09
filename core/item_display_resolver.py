from __future__ import annotations

import csv
import re
from collections import Counter
from functools import lru_cache
from html import escape
from typing import Any

from . import equipment_display_stats, resource_loader, weapon_display_stats
from .weapon_generation_logic import evaluate_group_selection


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
# Rarities whose inv_comp skin names a weapon, highest priority last.
# Epic and below keep barrel-derived names, so their named inv_comp entries
# (grenade/shield prefix words like "Gate", "Scab") stay prefixes.
_WEAPON_TITLE_RARITIES = {"Legendary": 0, "Pearl": 1}
CLASSMOD_RARITY_FALLBACK = {
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


_PLACEHOLDER_RE = re.compile(r"\{[^}]*\}")
_MARKUP_SPAN_RE = re.compile(r"\[(?!/)([^\]]+)\]([^\[]*)\[/\1\]")


def _label_from_markup(text: str) -> str:
    """Pull a stat label out of a uistat sentence.

    Stat uistats are templates, e.g. "[secondary]Gun Damage[/secondary] is
    increased by [secondary]{damage}[/secondary]", and the value placeholder is
    only substituted on the card. Using such a sentence as a part name leaked
    the raw "{damage}"/"{mod}" text into the UI. The markup already tags the
    label, so take the first tagged span that holds no placeholder; that works
    whether the placeholder trails the label or leads it ("{damage} [secondary]
    Melee Critical Hit Chance[/secondary]").
    """
    for _tag, inner in _MARKUP_SPAN_RE.findall(text or ""):
        if inner.strip() and not _PLACEHOLDER_RE.search(inner):
            return " ".join(inner.split())
    return ""


def _title_from_text(text: str) -> str:
    label = _label_from_markup(text)
    text = _clean_markup(label or text)
    if not text:
        return ""
    title = re.split(r"\s*-\s*", text, maxsplit=1)[0].strip().replace("Ⅳ", "IV")
    # Never surface a template placeholder as a name; callers treat "" as
    # "no name available" and fall back to the part's other identifiers.
    return "" if _PLACEHOLDER_RE.search(title) else title


def _valid_name(text: str) -> bool:
    return bool(
        text
        and text not in {"/", "Unknown", "未知", "N/A"}
        and str(text).strip().casefold() not in {"nan", "<na>", "none"}
    )


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
        elif part.get("type") == "elemental" and str(part.get("id", "")) == group_id and part.get("sub_id"):
            ids.append(str(part["sub_id"]))
    return [item for item in ids if item]


@lru_cache(maxsize=1)
def _item_index() -> dict[str, Any]:
    index = resource_loader.load_item_json("item_name_index.json") or {}
    # Point-scaled stats multiply by the rarity's declared stat_scale. Seed that table
    # from the export here, at the single place the index is loaded, so the evaluator
    # never relies on a literal that a balance patch could invalidate.
    try:
        weapon_display_stats.load_rarity_stat_scale(index)
    except Exception:
        pass
    return index


@lru_cache(maxsize=1)
def classmod_rarity_codes() -> dict[int, dict[str, str]]:
    codes = {item_id: dict(values) for item_id, values in CLASSMOD_RARITY_FALLBACK.items()}
    for key, ref in (_item_index().get("part_refs") or {}).items():
        if ref.get("category") != "inv_comp":
            continue
        item_id, separator, part_id = str(key).partition(":")
        match = re.search(r"comp_\d+_(common|uncommon|rare|epic)$", str(ref.get("part", "")), re.IGNORECASE)
        if separator and item_id.isdigit() and part_id and match:
            codes.setdefault(int(item_id), {})[part_id] = match.group(1).title()
    return codes


def classmod_rarity_code(item_id: int | str, rarity: str) -> str:
    try:
        values = classmod_rarity_codes().get(int(item_id), {})
    except (TypeError, ValueError):
        return ""
    rarity = str(rarity or "").casefold()
    return next((part_id for part_id, name in values.items() if name.casefold() == rarity), "")


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
        "Firmware": resource_loader.get_firmware_data_path,
    }.get(folder)
    return _read_csv(getter(name)) if getter else []


@lru_cache(maxsize=256)
def root_kind(root_ref: str) -> tuple[str, str]:
    """Return the (manufacturer, item_type) enums for a root id.

    `weapon_generation_rules` leaves `manufacturer`/`weapon_type` empty for the
    non-firearm roots (enhancements, shields, class mods), so the static ID map
    is the authority; `dynamic_item_kind` covers class-mod roots it omits.
    Returns ("", "") when neither knows the root, so callers can degrade to a
    generic message instead of asserting a wrong manufacturer or type.
    """
    from . import lookup

    try:
        item_id = int(str(root_ref).strip())
    except (TypeError, ValueError):
        return "", ""
    manufacturer, item_type, found = lookup.get_kind_enums(item_id)
    if found:
        return manufacturer, item_type
    dynamic = dynamic_item_kind(item_id)
    if dynamic:
        return str(dynamic[0] or ""), str(dynamic[1] or "")
    return "", ""


def classify_foreign_root(own_root: str, other_root: str) -> str:
    """Say *how* a part is foreign: from another brand, or another item class.

    A Maliwan enhancement holding a Ripper enhancement augment is a
    cross-manufacturer swap; the same enhancement holding a Torgue shotgun
    barrel is a cross-type swap. Both were previously reported as "another
    weapon", which is wrong twice over for non-weapon gear. Returns
    "manufacturer", "type", or "" when either root's identity is unknown.
    """
    own_mfr, own_type = root_kind(own_root)
    other_mfr, other_type = root_kind(other_root)
    if not own_type or not other_type:
        return ""
    if own_type != other_type:
        return "type"
    if own_mfr and other_mfr and own_mfr != other_mfr:
        return "manufacturer"
    return ""


# Item-type enums map onto strings the UI already ships: the firearm types live
# in weapon_editor_tab.taxonomy, the gear types in main_window.tabs. Reusing them
# keeps all four languages correct without inventing new translations.
_ROOT_TYPE_LOC_KEYS = {
    "Assault Rifle": ("weapon_editor_tab", "taxonomy", "assault_rifle"),
    "Pistol": ("weapon_editor_tab", "taxonomy", "pistol"),
    "Shotgun": ("weapon_editor_tab", "taxonomy", "shotgun"),
    "SMG": ("weapon_editor_tab", "taxonomy", "smg"),
    "Sniper": ("weapon_editor_tab", "taxonomy", "sniper"),
    "Heavy Weapon": ("main_window", "tabs", "heavy_weapon"),
    "Class Mod": ("main_window", "tabs", "class_mod"),
    "Enhancement": ("main_window", "tabs", "enhancement"),
    "Grenade": ("main_window", "tabs", "grenade"),
    "Shield": ("main_window", "tabs", "shield"),
    "Repkit": ("main_window", "tabs", "repkit"),
}


@lru_cache(maxsize=8)
def _root_type_names(lang: str) -> dict[str, str]:
    """Localized item-type names keyed by enum. Cached: load_json_resource has no
    cache of its own and a serial can raise one violation per foreign part."""
    try:
        data = resource_loader.load_json_resource(
            resource_loader.get_ui_localization_file(lang)
        )
    except (OSError, ValueError):
        return {}
    names: dict[str, str] = {}
    for enum, (section, subsection, key) in _ROOT_TYPE_LOC_KEYS.items():
        value = ((data or {}).get(section) or {}).get(subsection) or {}
        text = value.get(key) if isinstance(value, dict) else None
        if isinstance(text, str) and text:
            names[enum] = text
    return names


def root_kind_label(root_ref: str, lang: str = "zh-CN") -> str:
    """Human-readable "Manufacturer Type" for a root, e.g. "Maliwan 强化模组".

    Manufacturer names are proper nouns and stay untranslated; the item type uses
    the UI's existing translations. Falls back to the bare root id when the root
    is unknown, so callers never print an invented name.
    """
    manufacturer, item_type = root_kind(root_ref)
    if not item_type:
        return str(root_ref)
    type_text = _root_type_names(lang).get(item_type) or item_type
    return f"{manufacturer} {type_text}" if manufacturer else type_text


@lru_cache(maxsize=64)
def dynamic_item_kind(item_id: int) -> tuple[str, str] | None:
    prefix = f"{item_id}:"
    refs = (_item_index().get("part_refs") or {})
    if not any(key.startswith(prefix) and str(ref.get("parent", "")).startswith("classmod_") for key, ref in refs.items()):
        return None
    for row in _rows_by_file("class_mods/Class_rarity_name.csv"):
        if row.get("class_ID", "").strip() == str(item_id) and row.get("class_name", "").strip():
            return row["class_name"].strip(), "Class Mod"
    return "Unknown", "Class Mod"


def _csv_rows_for_type(item_type: str) -> list[dict[str, str]]:
    if item_type == "Heavy Weapon":
        # Heavy rarity/skin rows live in their own file (heavy_rarity.csv) since the part
        # file was split to carry ids+names only. The naming resolver needs both: the
        # rarity row tells it whether a special barrel gets its legendary skin name.
        return [*_rows_by_file("heavy/heavy_manufacturer_perk.csv"),
                *_rows_by_file("heavy/heavy_rarity.csv")]
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
    name_part = str(name_part or "").strip().rstrip("'").rsplit("'", 1)[-1]
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
    family = ""
    root: dict[str, Any] = {}
    for family_name, model in ((_item_index().get("equipment_native_models") or {}).get("models") or {}).items():
        if not isinstance(model, dict):
            continue
        candidate = (model.get("roots") or {}).get(str(item_id))
        if candidate is not None:
            family, root = str(family_name), candidate
            break
    class_data = root.get("class_data") or {}
    disable_prefixes = any(str(ref.get("disable_prefixes", "")).casefold() == "true" for ref in part_refs)
    has_named_composition = any(
        ref.get("category") == "inv_comp"
        and _valid_name(((ref.get("name") or {}).get("zh" if _lang_is_zh(lang) else "en") or (ref.get("name") or {}).get("en", "")))
        for ref in part_refs
    )
    root_name_parts: dict[str, list[str]] = {"prefix": [], "title": [], "suffix": []}
    for aspect in class_data.get("aspects") or []:
        if not isinstance(aspect, dict):
            continue
        for section in root_name_parts:
            root_name_parts[section].extend(aspect.get(f"{section}partlist") or [])
    for section in root_name_parts:
        root_name_parts[section].extend(class_data.get(f"{section}partlist") or [])
        for name_part in root_name_parts[section]:
            if family == "grenade" and has_named_composition and section == "suffix":
                continue
            text, priority = _name_part_text(name_part, lang)
            if _valid_name(text):
                sections[section].append((priority, -1, text))
                seen.add((section, str(name_part).lower()))
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

    for section, values in sections.items():
        # Equal-priority naming aspects are applied last-in-first-out by the
        # inventory namer on Repkits/Shields; Grenade stat prefixes preserve
        # their serialized order instead (e.g. Ancient Booming UAV).
        values.sort(key=lambda item: (-item[0], item[1] if family == "grenade" and section == "prefix" else -item[1]))
    max_prefixes = int(
        class_data.get("maxnumprefixes", class_data.get("maxnumsuffixes", 2)) or 0
    )
    max_suffixes = int(class_data.get("maxnumsuffixes", 1) or 0)
    prefixes = [] if disable_prefixes else [item[2] for item in sections["prefix"][:max_prefixes]]
    title = sections["title"][0][2] if sections["title"] else ""
    suffixes = [item[2] for item in sections["suffix"][:max_suffixes]]
    name = " ".join([*prefixes, title, *suffixes]).strip()
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
    if len(remaining) >= 2:
        word = _strategy_combo(table, remaining[0], remaining[1], lang)
        if word:
            words.append(word)
            remaining = remaining[2:]
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
    stat_attrs_by_group: dict[str, str] = {}
    core_attrs: list[str] = []
    for part_id in stat_ids:
        ref = _part_ref(247, part_id)
        category = str(ref.get("category", ""))
        if category in {"stat_group1", "stat_group2", "stat_group3"}:
            # Modded serials may repeat a slot; native naming uses its final part.
            stat_attrs_by_group[category] = ref.get("naming_row", "")
    for part_id in core_ids:
        ref = _part_ref(item_id, part_id)
        if ref.get("category") == "core_augment":
            core_attrs.append(ref.get("naming_row", ""))

    stat_strategy = strategy.get("stats", {})
    priority = {_strategy_key(attr): order for order, attr in enumerate(stat_strategy.get("priority") or [])}
    stat_attrs = sorted(
        (stat_attrs_by_group.get(f"stat_group{group}", "") for group in range(1, 4)),
        key=lambda attr: priority.get(_strategy_key(attr), len(priority)),
    )
    words = _strategy_words(stat_attrs, stat_strategy, lang)
    if len(core_attrs) <= 2:
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
    "SplashDamage": ("溅射伤害", "Splash Damage"),
    "MeleeDamage": ("近战伤害", "Melee Damage"),
    "ProjectileSpeed": ("弹丸速度", "Projectile Speed"),
    "ThrowDamage": ("投掷伤害", "Thrown Damage"),
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
    # Aim-charge animation blendspace scale. Every weapon body part carries this
    # and nothing else, so leaving it unregistered made all 26 bodies look like
    # they had renderable stats that the formatter had silently dropped.
    "weapon_zoomed_charge_blendspace_scale",
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


def _uistat_arg_number(value: float, arg: dict[str, Any]) -> str:
    """Render a uistat arg the way the game does.

    NumericDisplayValue carries its own formatting flags: bDisplayAsPercentage means
    the stored fraction is shown scaled by 100 with a percent sign, and
    bDisplayPlusSign prefixes gains with '+'. Without the flags the number is a plain
    count (seconds, stacks, ammo) and must stay as-is.
    """
    if arg.get("bdisplayaspercentage"):
        text = _part_number(value * 100.0, 2) + "%"
    else:
        text = _part_number(value)
    if arg.get("bdisplayplussign") and value > 0:
        text = "+" + text
    return text


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
    key = "zh" if _lang_is_zh(lang) else "en"

    # Checked before the CSV because the CSV carries the same wrong name: the
    # game reuses the generic barrel's name for some legendary gimmick parts
    # (18:70 Aegon's Dream shows as "Buzzymuzz") or leaves them unnamed, in which
    # case the namer used to print the red-text sentence as the part name. The
    # pipeline derives this from the rarity component, the authoritative holder.
    unique = _part_ref(item_id, part_id).get("unique_name") or {}
    name = unique.get(key) or unique.get("en", "")
    if _valid_name(name):
        return name

    if _lang_is_zh(lang):
        name = _part_row_value(row, "Name_ZH", "Name")
    else:
        name = _part_row_value(row, "Name_EN", "Name")
    if _valid_name(name):
        return name

    ref = _part_ref(item_id, part_id)
    fallback = ref.get("fallback_name") or {}
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


def _base_value_description(ref: dict[str, Any], lang: str) -> list[str]:
    labels = {
        "damage_value": ("基础伤害", "Base Damage", ""),
        "firerate_value": ("基础射速", "Base Fire Rate", "/s"),
        "accuracy_value": ("基础精准值", "Base Accuracy", ""),
        "spread_value": ("基础扩散值", "Base Spread", ""),
        "damageradius_value": ("爆炸范围", "Splash Radius", "cm"),
        "projectilespershot_value": ("弹丸数", "Projectiles", "/发" if _lang_is_zh(lang) else "/shot"),
    }
    lines: list[str] = []
    for base_ref in ref.get("weapon_base_value_refs", []):
        for key, raw in (base_ref.get("values") or {}).items():
            label = labels.get(str(key).lower())
            if not label:
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if value <= 0 or (str(key).lower() == "projectilespershot_value" and value <= 1):
                continue
            lines.append(f"{_part_label(label[:2], lang)} {_part_number(value)}{label[2]}")
    return list(dict.fromkeys(lines))


# Value slots in a uistat template are filled from statvalue.args, each of which
# names an attribute to evaluate. Some resolve to a runtime expression, a level
# balance formula, or a value rolled into the save's own serial, so no static
# number exists for them.
#
# Editing the sentence around the slot was tried and rejected: removing the value
# and its unit leaves mutilated claims such as "发射一架无人机，每枪，之后会爆炸"
# and "Fires a Gravity Harpoon that and pulls in nearby enemies", because the slot
# sits mid-clause and the surrounding grammar depends on it.
#
# Dropping the whole sentence was also wrong: it made 113 parts fall through to
# "No stat changes", which is a false claim about a shield augment that plainly
# states it grants damage reduction. Substituting a visible placeholder keeps the
# effect readable and only admits the one number we cannot compute.
_UNFILLED_VALUE_SLOT = re.compile(r"\{\w+\}")

# Marker for a value that genuinely has no static number. Kept as "?" so it reads
# as a missing quantity in every language rather than looking like leaked markup.
_UNKNOWN_VALUE_MARK = "?"


@lru_cache(maxsize=1)
def _all_attribute_defaults() -> dict[str, float]:
    """Attribute defaults from every model, keyed case-insensitively.

    Equipment models contribute their own attributes so grenade and repair-kit stats
    resolve too, except for the ``*_modifier_base_*`` entries: those are the
    multiplicative identity the game starts from before an augment's table row
    supplies the real delta, so showing them as a stat would invent a number.
    Weapon entries win over equipment ones so weapon rendering is unchanged.
    """
    index = _item_index()
    merged: dict[str, float] = {}
    for model in ((index.get("equipment_native_models") or {}).get("models") or {}).values():
        for key, value in ((model or {}).get("attribute_defaults") or {}).items():
            name = str(key).casefold()
            if "_modifier_base_" in name:
                continue
            merged.setdefault(name, value)
    for key, value in ((index.get("weapon_native_model") or {}).get("attribute_defaults") or {}).items():
        merged[str(key).casefold()] = value
    return merged


def _fill_uistat_args(text: str, entry: dict[str, Any], index: dict[str, Any]) -> str:
    """Substitute {token} slots from the uistat's own args when a value is known.

    statvalue.args maps each token to an attribute name; when that attribute has a
    literal default we can show the real number instead of dropping the whole
    sentence. Grenade and repair-kit stats name attributes that live in the equipment
    models rather than the weapon model, so both tables are consulted. Tokens whose
    attribute is computed at runtime stay unfilled and the caller discards the text.
    """
    args = ((entry.get("statvalue") or {}).get("args") or {})
    if not args:
        return text
    # uistat_goremaster_desc writes {LowHPThreshold} but names the arg LowHpThreshold,
    # so token lookup has to tolerate the source's own casing slip.
    folded = {str(key).casefold(): value for key, value in args.items()}
    defaults = _all_attribute_defaults()
    for token in set(_UNFILLED_VALUE_SLOT.findall(text)):
        name = token[1:-1]
        arg = args.get(name)
        if not isinstance(arg, dict):
            arg = folded.get(name.casefold())
        arg = arg if isinstance(arg, dict) else {}
        attribute = str(arg.get("attribute") or "")
        if not attribute:
            continue
        value = defaults.get(attribute.casefold())
        if value is None:
            continue
        try:
            text = text.replace(token, _uistat_arg_number(float(value), arg))
        except (TypeError, ValueError):
            continue
    return text


def _part_behavior_text(ref: dict[str, Any], index: dict[str, Any], lang: str) -> str:
    key = "zh" if _lang_is_zh(lang) else "en"
    for uistat_id in [*ref.get("uistats_include", []), *ref.get("uistats", [])]:
        entry = (index.get("uistats") or {}).get(str(uistat_id).lower(), {})
        text = _clean_markup(entry.get(key, "") or entry.get("en", ""))
        if not text:
            continue
        for separator in (" - ", " – "):
            if separator in text:
                text = text.split(separator, maxsplit=1)[1].strip()
                break
        text = _fill_uistat_args(text, entry, index)
        text = _UNFILLED_VALUE_SLOT.sub(_UNKNOWN_VALUE_MARK, text)
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


def no_stat_changes_text(lang: str = "zh-CN") -> str:
    """The placeholder shown when a part resolves to no stat effect at all."""
    return "无属性变化" if _lang_is_zh(lang) else "No stat changes"


def format_weapon_part_description(
    item_id: int, part_id: str, decoded_full: str = "", lang: str = "zh-CN", part_type: str = ""
) -> str:
    """Format only effects actually resolved for one weapon part."""
    index = _item_index()
    ref = (index.get("part_refs") or {}).get(f"{item_id}:{part_id}", {})
    fallback = no_stat_changes_text(lang)
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
    if not lines:
        lines.extend(_base_value_description(ref, lang))

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


def _weapon_generation_refs(decoded: str, root_ref: str) -> list[str]:
    component_text = decoded.split("||", 1)[1] if "||" in decoded else ""
    refs: list[str] = []
    for component in _parse_components(component_text):
        if component.get("type") == "simple":
            refs.append(f"{root_ref}:{component.get('id')}")
        elif component.get("type") == "group":
            refs.extend(f"{component.get('id')}:{part_id}" for part_id in component.get("sub_ids", []))
        elif component.get("type") == "elemental":
            refs.append(f"{component.get('id')}:{component.get('sub_id')}")
    return sorted(ref for ref in refs if not ref.endswith(":None"))


def _weapon_generation_tags(index: dict[str, Any], rules: dict[str, Any], ref: str) -> dict[str, set[str]]:
    raw = (rules.get("part_selection_tags") or {}).get(ref) or (index.get("part_refs") or {}).get(ref, {}).get(
        "selection_tags", {}
    )
    return {
        key: {str(value).casefold() for value in raw.get(key, [])}
        for key in ("adds", "requires", "excludes")
    }


def _weapon_generation_root(ref: str) -> str:
    return ref.partition(":")[0]


def weapon_generation_context(decoded: str) -> dict[str, Any]:
    index = _item_index()
    rules = index.get("weapon_generation_rules") or {}
    match = re.match(r"\s*(\d+)", decoded or "")
    root_ref = match.group(1) if match else ""
    weapon = (rules.get("weapons") or {}).get(root_ref, {})
    refs = _weapon_generation_refs(decoded, root_ref) if root_ref else []
    part_refs = index.get("part_refs") or {}
    compositions = weapon.get("compositions") or {}
    composition_tokens = [ref for ref in refs if ref in compositions]
    unknown_compositions = [
        ref for ref in refs if (part_refs.get(ref) or {}).get("category") == "inv_comp" and ref not in compositions
    ]
    composition_ref = composition_tokens[0] if len(composition_tokens) == 1 else ""
    composition = compositions.get(composition_ref, {})
    selected = [ref for ref in refs if (part_refs.get(ref) or {}).get("category") != "inv_comp"]
    selected_by_group: dict[str, list[str]] = {}
    for ref in selected:
        entry = part_refs.get(ref) or {}
        group = str(entry.get("selection_group") or entry.get("category") or "").casefold()
        if group:
            selected_by_group.setdefault(group, []).append(ref)

    groups: dict[str, Any] = {}
    for group, rule in (composition.get("groups") or {}).items():
        group = str(group).casefold()
        groups[group] = {
            "allowed": list(rule.get("allowed_part_refs") or []),
            "source": str(rule.get("source") or ""),
            "min": int(rule.get("min", 1)),
            "max": int(rule.get("max", 1)),
            "selected": selected_by_group.get(group, []),
            "eligible_refs": [],
            "tag_limited_refs": [],
            "activation_tags": [],
            "active": False,
            "additional_part_chance": rule.get("additional_chance"),
            "unresolved_parts": list(rule.get("unresolved_parts") or []),
        }

    ordered_groups: list[str] = []
    for group in weapon.get("part_types") or []:
        group = str(group).casefold()
        if group not in ordered_groups:
            ordered_groups.append(group)
    ordered_groups.extend(sorted((set(groups) | set(selected_by_group)) - set(ordered_groups)))
    active_tags = {str(tag).casefold() for tag in composition.get("base_tags") or []}
    tag_rules = [
        ({str(tag).casefold() for tag in rule.get("tags", [])}, int(rule.get("max", 1)))
        for rule in composition.get("tag_rules") or []
    ]
    tag_counts = [0] * len(tag_rules)
    for group in ordered_groups:
        if group in groups:
            selected_refs = selected_by_group.get(group, [])
            # Dependency chains can live INSIDE one group: a class mod spends its
            # skill points on `passive_points` where tier_2 requires the tier_1 of
            # the same branch, so the tags a sibling adds must be visible to the
            # parts picked after it. `native_generation_routes.md:267` allows the
            # preferred-parts path to enqueue dependency providers, and :278
            # defines legality as "there exists at least one completion", which is
            # exactly this ordered reading. Exclusions stay on the group-entry
            # snapshot (:269 shrinks the pool but never revives a candidate), so
            # mutually exclusive siblings are still reported.
            dependency_tags = set(active_tags)
            for ref in selected_refs:
                dependency_tags |= _weapon_generation_tags(index, rules, ref)["adds"]
            group_state = evaluate_group_selection(
                allowed_refs=groups[group]["allowed"],
                selected_refs=selected_refs,
                tags_for_ref=lambda ref: _weapon_generation_tags(index, rules, ref),
                base_tags=active_tags,
                dependency_tags=dependency_tags,
                tag_rules=composition.get("tag_rules") or [],
                base_tag_counts=tag_counts,
                minimum=groups[group]["min"],
                maximum=groups[group]["max"],
                additional_chance=groups[group]["additional_part_chance"],
            )
            groups[group].update(group_state)
            requires = [
                _weapon_generation_tags(index, rules, ref)["requires"]
                for ref in groups[group]["allowed"]
            ]
            activation_tags = set.intersection(*requires) if requires else set()
            groups[group]["activation_tags"] = sorted(activation_tags)
        if group in groups and groups[group].get("selected_reachable"):
            for ref in selected_by_group.get(group, []):
                adds = _weapon_generation_tags(index, rules, ref)["adds"]
                active_tags.update(adds)
                for index_, (bucket, _maximum) in enumerate(tag_rules):
                    tag_counts[index_] += bool(adds & bucket)

    unknown_parts = [ref for ref in selected if ref not in part_refs]
    # A part is only "foreign" if it comes from a root this item does not
    # inherit from. Weapons share root 1, but shields share 246, class mods 234,
    # grenades 245 and so on, and a heavy weapon legitimately shares both 244
    # and 1. `shared_roots` is published per root by the rules builder; the
    # literal "1" stays as the fallback for weapon roots exported before it.
    shared_roots = {str(value) for value in (weapon.get("shared_roots") or [])}
    allowed_roots = {root_ref} | (shared_roots or {"1"})
    foreign_parts = [ref for ref in refs if _weapon_generation_root(ref) not in allowed_roots]
    coverage_complete = bool(root_ref and weapon and composition_ref)
    coverage_complete &= not bool(composition.get("inheritance_cycle"))
    coverage_complete &= not any(
        group["unresolved_parts"]
        and (group.get("allowed") or group.get("effective_max", group["max"]) > 0)
        for group in groups.values()
    )
    coverage_complete &= not bool(unknown_parts or unknown_compositions)
    return {
        "root_ref": root_ref,
        "parent": weapon.get("parent", ""),
        "manufacturer": weapon.get("manufacturer", ""),
        "weapon_type": weapon.get("weapon_type", ""),
        "rules_available": bool(rules),
        "weapon_known": bool(weapon),
        "composition_ref": composition_ref,
        "composition_tokens": composition_tokens,
        "unknown_compositions": unknown_compositions,
        "coverage_complete": coverage_complete,
        "availability": composition.get("availability", ""),
        "base_tags": list(composition.get("base_tags") or []),
        "tag_rules": list(composition.get("tag_rules") or []),
        "forced_part_refs": list(composition.get("forced_part_refs") or []),
        "part_types": list(weapon.get("part_types") or []),
        "groups": groups,
        "selected_part_refs": selected,
        "unknown_part_refs": unknown_parts,
        "foreign_part_refs": foreign_parts,
        "inheritance_cycle": list(composition.get("inheritance_cycle") or []),
    }


def validate_weapon_generation(decoded: str, allow_incomplete: bool = False) -> dict[str, Any]:
    context = weapon_generation_context(decoded)
    index = _item_index()
    rules = index.get("weapon_generation_rules") or {}
    part_refs = index.get("part_refs") or {}
    selected = context["selected_part_refs"]
    violations: list[dict[str, Any]] = []
    hard = False
    unknown = False
    incomplete = False
    conditional = False

    def add(code: str, **details: Any) -> None:
        violations.append({"code": code, **details})

    if not context["root_ref"]:
        add("invalid_serial")
        unknown = True
    elif not context["rules_available"]:
        add("rules_unavailable")
        unknown = True
    elif not context["weapon_known"]:
        add("weapon_rules_missing", root_ref=context["root_ref"])
        unknown = True

    if len(context["composition_tokens"]) > 1:
        add("multiple_compositions", parts=context["composition_tokens"])
        hard = True
    elif context["unknown_compositions"]:
        add("unknown_composition", parts=context["unknown_compositions"])
        unknown = True
    elif context["weapon_known"] and not context["composition_ref"]:
        add("unknown_composition")
        unknown = True

    for ref in context["foreign_part_refs"]:
        # Report *why* the part is foreign so the UI can say cross-manufacturer
        # or cross-type instead of always claiming "another weapon".
        add(
            "foreign_root_part",
            part=ref,
            foreign_kind=classify_foreign_root(context["root_ref"], str(ref).partition(":")[0]),
        )
        hard = True
    if context["unknown_part_refs"]:
        add("unknown_part", parts=context["unknown_part_refs"])
        unknown = True
    if context["inheritance_cycle"]:
        add("inheritance_cycle", parts=context["inheritance_cycle"])
        unknown = True
    unresolved = {
        group: data["unresolved_parts"]
        for group, data in context["groups"].items()
        if data["unresolved_parts"]
        and (data.get("allowed") or data.get("effective_max", data["max"]) > 0)
    }
    if unresolved:
        add("unresolved_rule_parts", groups=unresolved)
        unknown = True

    selected_by_group: dict[str, list[str]] = {}
    for ref in selected:
        entry = part_refs.get(ref) or {}
        group = str(entry.get("selection_group") or entry.get("category") or "").casefold()
        if group:
            selected_by_group.setdefault(group, []).append(ref)
    resolved = bool(context["rules_available"] and context["weapon_known"] and context["composition_ref"])
    if resolved:
        duplicate_parts = sorted(ref for ref, count in Counter(selected).items() if count > 1)
        duplicate_set = set(duplicate_parts)
        if duplicate_parts:
            add("duplicate_part", parts=duplicate_parts)
            hard = True
        for group, refs in selected_by_group.items():
            group_rule = context["groups"].get(group)
            if not group_rule:
                add("part_not_allowed", group=group, parts=refs)
                hard = True
                continue
            illegal = sorted(ref for ref in refs if ref not in set(group_rule["allowed"]))
            if illegal:
                add("part_not_allowed", group=group, parts=illegal)
                hard = True
        for group, group_rule in context["groups"].items():
            refs = selected_by_group.get(group, [])
            actual = len(refs)
            if actual > group_rule["max"]:
                add("count_above", group=group, actual=actual, max=group_rule["max"])
                hard = True
                continue
            if any(ref not in set(group_rule["allowed"]) for ref in refs) or duplicate_set.intersection(refs):
                continue
            if not group_rule["selected_reachable"]:
                direct_reason = False
                tags_before = set(group_rule.get("tags_before") or [])
                # `requires` is judged against the widened set so an intra-group
                # dependency chain is not reported as missing; `excludes` keeps
                # using the group-entry snapshot.
                requires_before = set(group_rule.get("dependency_tags") or []) | tags_before
                for ref in refs:
                    tags = _weapon_generation_tags(index, rules, ref)
                    missing = sorted(tags["requires"] - requires_before)
                    if missing:
                        add("missing_required_tag", part=ref, tags=missing)
                        direct_reason = True
                    conflict = sorted(tags["excludes"] & tags_before)
                    if conflict:
                        add("excluded_tag_conflict", part=ref, tags=conflict)
                        direct_reason = True
                if not direct_reason and not group_rule.get("selected_tag_limit_exceeded"):
                    add("excluded_tag_conflict", parts=refs)
                hard = True
            elif not group_rule["selected_terminal"]:
                required = next(
                    (count for count in group_rule.get("terminal_counts", []) if count > actual),
                    group_rule["effective_min"],
                )
                add("count_below", group=group, actual=actual, min=required)
                incomplete = True

    part_tags = [_weapon_generation_tags(index, rules, ref) for ref in selected]

    for rule in context["tag_rules"] if resolved else []:
        tags = {str(tag).casefold() for tag in rule.get("tags", [])}
        actual = sum(bool(part["adds"] & tags) for part in part_tags)
        if "min" in rule and actual < int(rule["min"]):
            add("tag_count_below", tags=sorted(tags), actual=actual, min=int(rule["min"]))
            incomplete = True
        if actual > int(rule.get("max", 1)):
            add("tag_limit", tags=sorted(tags), actual=actual, max=int(rule.get("max", 1)))
            hard = True

    unavailable_parts = sorted(set(selected) & set((rules.get("part_availability") or {})))
    if resolved and (context["availability"] not in {"", "coregame"} or unavailable_parts):
        add("conditional_availability", composition=context["availability"], parts=unavailable_parts)
        conditional = True

    if hard:
        status = "modified"
    elif unknown:
        status = "unknown"
    elif incomplete:
        status = "incomplete" if allow_incomplete else "modified"
    elif conditional:
        status = "conditional"
    else:
        status = "legal"
    return {"status": status, **context, "violations": violations}


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


def _weapon_rarity_component_name(item_id: int, ids: list[str], key: str) -> str:
    """Title for named Legendary/Pearl weapons.

    The rarity skin (``inv_comp``) is the only authoritative name holder. Its
    companion gimmick part carries the legendary effect and usually - but not
    always - repeats the name: barrel ``18:70`` owns the Aegon's Dream effect
    (``uistat_DualDamage_red_text``) yet is named the generic "Buzzymuzz",
    while underbarrel ``18:69`` merely adds fire rate. Reading ``inv_comp``
    sidesteps that split. Pearl outranks Legendary when both are present.
    """
    best_rank = -1
    best_name = ""
    for part_id in ids:
        ref = _part_ref(item_id, part_id)
        if ref.get("category") != "inv_comp":
            continue
        rank = _WEAPON_TITLE_RARITIES.get(str(ref.get("rarity") or ""), -1)
        if rank <= best_rank:
            continue
        name = ((ref.get("name") or {}).get(key) or (ref.get("name") or {}).get("en", "")).strip()
        if _valid_name(name):
            best_rank, best_name = rank, name
    return best_name


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
    # A unique barrel_acc above may upgrade the title ("Superconducting Plasma
    # Coil" over "Plasma Coil"), so the rarity skin only applies after it.
    rarity_name = _weapon_rarity_component_name(item_id, ids, key)
    if rarity_name:
        return rarity_name, "ncs_name"
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
            rarity = classmod_rarity_codes().get(item_id, {}).get(part_id)
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


# Canonical naming ids for heavy parts, defined by the pipeline's HEAVY_IDS and keyed off
# the index's internal part string (authoritative), never the hand-written CSV String.
#   part_body_a..d        -> body id    7/8/9/10      (drives the name prefix)
#   part_barrel_01_a..d   -> barrel1 id 13/14/15/16   (drives a T1 barrel base name)
#   part_barrel_02_a..d   -> barrel2 id 17/18/19/20   (drives a T2 barrel base name)
# x-variants (part_barrel_01_axb etc.) stay on their base letter's id.
_HEAVY_CANON_MAP = {
    "body": {"a": "7", "b": "8", "c": "9", "d": "10"},
    "barrel_01": {"a": "13", "b": "14", "c": "15", "d": "16"},
    "barrel_02": {"a": "17", "b": "18", "c": "19", "d": "20"},
}
_HEAVY_CANON_RE = re.compile(r"part_(body|barrel_01|barrel_02)_([a-d])(?:x([a-d]))?$")


def _heavy_canonical_parts(item_id: int, ids: list[str]) -> dict[str, list[str]]:
    """Group present parts into the three naming sections using the index internal string.

    Returns {"body": [ids...], "barrel_01": [...], "barrel_02": [...]} with canonical ids.
    Base barrels (part_barrel_01 / part_barrel_02, no a-d suffix) and special/legendary
    barrels carry no canonical id and so do not participate here.
    """
    sections: dict[str, list[str]] = {"body": [], "barrel_01": [], "barrel_02": []}
    variants: dict[str, list[tuple[str, str]]] = {"body": [], "barrel_01": [], "barrel_02": []}
    for part_id in ids:
        internal = str(_part_ref(item_id, part_id).get("part") or "").lower()
        match = _HEAVY_CANON_RE.fullmatch(internal)
        if not match:
            continue
        group = match.group(1)
        if match.group(3):
            variants[group].append((match.group(2), match.group(3)))
            continue
        canon = _HEAVY_CANON_MAP[group].get(match.group(2))
        if canon and canon not in sections[group]:
            sections[group].append(canon)
    for group, pairs in variants.items():
        present = {
            letter
            for letter, canon in _HEAVY_CANON_MAP[group].items()
            if canon in sections[group]
        }
        for base, suffix in pairs:
            # The x-part supplies the counterpart of the ordinary accessory
            # serialized beside it.  Without that companion, the x suffix is
            # the active single component.
            letter = base if suffix in present and base not in present else suffix
            canon = _HEAVY_CANON_MAP[group].get(letter)
            if canon and canon not in sections[group]:
                sections[group].append(canon)
                present.add(letter)
    return sections


def _combo_word(ids: list[str], rules: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the naming rule whose id set exactly matches the stacked parts of one section.

    ``rules[].ids`` is the exact set of canonical ids that stack to produce that name
    (a row like ``body_mod_a.body_mod_b`` plus a column gives the pair {7,8}). The correct
    match is therefore the largest rule whose id set is a subset of the section's present
    ids — never "first rule containing any present id", which lets ids from other sections
    bleed in and corrupts the name.
    """
    present = {str(x) for x in ids}
    best = None
    for rule in rules:
        combo = {str(item) for item in rule.get("ids", [])}
        if combo and combo.issubset(present) and (best is None or len(combo) > len(best[0])):
            best = (combo, rule)
    return best[1] if best else None


def _first_combo(ids: list[str], rules: list[dict[str, Any]]) -> tuple[int, dict[str, Any]] | None:
    rule = _combo_word(ids, rules)
    return (0, rule) if rule else None


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
    section_data = strategy.get(section, {})
    item = _first_combo(ids, section_data.get("rules", []))
    rule = item[1] if item else _first_single(ids, section_data.get("singles", []))
    if not rule:
        rule = section_data.get("default")
    return (rule.get(key) or rule.get("en", "")).strip() if rule else ""


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


def _heavy_barrel_internal(item_id: int, ids: list[str]) -> str:
    """The internal part string of the present barrel, from the index (authoritative)."""
    for part_id in ids:
        ref = _part_ref(item_id, part_id)
        if str(ref.get("category") or "").strip() == "barrel":
            return str(ref.get("part") or "").lower()
    return ""


def _heavy_barrel_kind(internal: str) -> tuple[str, bool]:
    """Classify a barrel's internal string -> (section, is_special).

    section is "barrel1"/"barrel2"/"" ; is_special is True for a named (non-base) barrel.
    Base barrels are exactly part_barrel_01 / part_barrel_02. Anything else with a 01/02
    (splatoon, flak, ravenfire...) is a special barrel on that subtype; barrels with no
    subtype at all (javelin, dahlfather, loiter) have section "" and are always special.
    """
    if internal in ("part_barrel_01", "part_barrel_02"):
        return ("barrel1" if internal.endswith("_01") else "barrel2"), False
    match = re.search(r"barrel_(01|02)", internal)
    if match:
        return ("barrel1" if match.group(1) == "01" else "barrel2"), True
    return "", True


def _heavy_name(item_id: int, ids: list[str], lang: str) -> tuple[str, str]:
    # Prefix comes only from the body section (body_acc stacking); barrel ids must not
    # leak into it (that is how an effect word like "+伤害" used to corrupt the name).
    sections = _heavy_canonical_parts(item_id, ids)
    prefix = _heavy_strategy_word(item_id, sections["body"], "body", lang)
    if any(str(_part_ref(item_id, part_id).get("disable_prefixes", "")).casefold() == "true" for part_id in ids):
        prefix = ""

    internal = _heavy_barrel_internal(item_id, ids)
    section, is_special = _heavy_barrel_kind(internal)
    barrel_name = ""
    source = "heavy_strategy"

    if internal:
        barrel_row = _heavy_barrel_row(item_id, ids)
        if is_special and _heavy_has_legendary_rarity(item_id, ids):
            barrel_name = _heavy_legendary_skin_name(item_id, ids, lang) or (
                _title_from_text(_text(barrel_row, lang)) if barrel_row else "")
            source = "heavy_skin"
        elif section:
            # Base barrel: name from that section's stacked accessories.
            section_key = "barrel1" if section == "barrel1" else "barrel2"
            barrel_name = _heavy_strategy_word(item_id, sections["barrel_01" if section == "barrel1" else "barrel_02"], section_key, lang)
        if not barrel_name and barrel_row:
            # Special barrel without a legendary rarity, or a section with no naming rule:
            # keep the pipeline-exported base name (CSV Stat), like the weapon tab does.
            barrel_name = _title_from_text(_text(barrel_row, lang))
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


def resolve_equipment_stats(decoded_full: str, item_type: str) -> dict[str, Any]:
    if item_type not in {"Grenade", "Shield", "Repkit", HEAVY_TYPE}:
        return {}
    try:
        return equipment_display_stats.equipment_card_stats_from_serial(decoded_full, _item_index(), item_type)
    except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError):
        return {}


def format_weapon_stat(key: str, value: Any, lang: str = "zh-CN") -> str:
    if value is None or value == "":
        return ""
    if key == "accuracy":
        return f"{int(value)}%"
    if key in {"dps", "elemental_dps", "elemental_dps_mode02"}:
        return f"{int(value):,}"
    if key == "fire_rate":
        return f"{float(value):.1f}/s"
    if key == "reload_time":
        return f"{float(value):.1f}s"
    if key in {"ads_time", "equip_time"}:
        return f"{float(value):.2f}s"
    if key == "critical_damage":
        return f"{int(value):+d}%" if value else "0%"
    if key in {"elemental_chance", "elemental_chance_mode02", "cryo_efficiency", "cryo_efficiency_mode02"}:
        return f"{int(value)}%"
    if key == "ammo_cost":
        suffix = {"zh-CN": "发", "ru": "выстрел", "ua": "постріл"}.get(lang, "shot")
        return f"{int(value)}/{suffix}"
    if key == "splash_radius":
        return f"{int(value)}cm"
    return str(value)


def format_equipment_stat(key: str, value: Any, lang: str = "zh-CN") -> str:
    if value is None or value == "":
        return ""
    if key == "accuracy":
        return f"{int(value)}%"
    if key in {"dps", "elemental_dps", "elemental_dps_mode02"}:
        return f"{int(value):,}"
    if key in {"fire_rate", "recharge_rate"}:
        suffix = "/秒" if _lang_is_zh(lang) else "/s"
        return f"{float(value):.1f}{suffix}" if key == "fire_rate" else f"{int(value):,}{suffix}"
    if key == "recharge_delay":
        return f"{float(value):.1f}{'秒' if _lang_is_zh(lang) else 's'}"
    if key in {"cooldown", "duration"}:
        return f"{int(value)}{'秒' if _lang_is_zh(lang) else 's'}"
    if key in {"radius", "splash_radius"}:
        return f"{int(value)}{'厘米' if _lang_is_zh(lang) else 'cm'}"
    if key == "critical_damage":
        return f"{int(value):+d}%" if value else "0%"
    if key in {"elemental_chance", "elemental_chance_mode02", "cryo_efficiency", "cryo_efficiency_mode02"}:
        return f"{int(value)}%"
    if key == "critical_chance":
        return f"{int(value)}%"
    if key == "damage_reduction":
        return f"{int(value)}%"
    if key in {"capacity", "healing", "instant_healing", "health_over_time", "damage"}:
        return f"{int(value):,}" if not isinstance(value, str) or value.isdigit() else value
    return str(value)


EQUIPMENT_PART_STAT_LABELS = {
    "damage": ("伤害", "Damage"),
    "radius": ("爆炸范围", "Blast Radius"),
    "cooldown": ("冷却", "Cooldown"),
    "charges": ("充能次数", "Charges"),
    "critical_damage": ("暴击伤害", "Critical Damage"),
    "critical_chance": ("暴击几率", "Critical Chance"),
    "capacity": ("护盾容量", "Shield Capacity"),
    "recharge_delay": ("恢复延迟", "Recharge Delay"),
    "recharge_rate": ("恢复速率", "Recharge Rate"),
    "armor_segments": ("护甲段数", "Armor Segments"),
    "damage_reduction": ("伤害减免", "Damage Reduction"),
    "healing": ("治疗量", "Healing"),
    "instant_healing": ("即时治疗", "Instant Healing"),
    "health_over_time": ("持续治疗", "Healing Over Time"),
    "duration": ("持续时间", "Duration"),
    "accuracy": ("精准度", "Accuracy"),
    "fire_rate": ("射速", "Fire Rate"),
    "magazine": ("弹容", "Magazine"),
    "splash_radius": ("爆炸范围", "Splash Radius"),
}

SKILL_TEXT_STYLES = {
    "primary": "color: #EB7300; font-weight: 600;",
    "secondary": "color: #2D95CA; font-weight: 600;",
    "flavor": "color: #3F769D; font-style: italic;",
    "fire": "color: #FF5224;",
    "shock": "color: #2F63F9;",
    "cryo": "color: #53FBFB;",
    "corrosive": "color: #72F800;",
    "radiation": "color: #F1FF00;",
    "kinetic": "color: #E4D9CE;",
}
SKILL_IMAGE_TAGS = {
    "corrosive_icon", "cryo_icon", "elemental_icon", "fire_icon", "frtn_icon",
    "kinetic_icon", "radiation_icon", "shock_icon", "wfll_icon",
}


def render_skill_markup(value: Any) -> str:
    """Render the game's localized skill markup into Qt-compatible rich text."""
    text = escape(str(value or "")).replace("[newline]", "<br>").replace("\n", "<br>")
    for tag in SKILL_IMAGE_TAGS:
        text = text.replace(f"[{tag}]", "")
    for tag, style in SKILL_TEXT_STYLES.items():
        text = text.replace(f"[{tag}]", f"<span style='{style}'>")
        text = text.replace(f"[/{tag}]", "</span>")
    text = text.replace("[nowrap]", "<span style='white-space: nowrap;'>").replace("[/nowrap]", "</span>")
    text = text.replace("[glyph]", "<span style='color: #F9F3DE; font-weight: 600;'>").replace("[/glyph]", "</span>")
    return re.sub(r"\[/?[a-z][a-z0-9_]*\]", "", text, flags=re.IGNORECASE).strip()


def equipment_part_internal(ref_key: str) -> str:
    """Return the index's internal part string (e.g. ``part_barrel_02_a``).

    This is the authoritative, pipeline-exported identity of a part. The heavy tab
    derives a barrel's T1/T2 subtype from it (``barrel_01``/``barrel_02``) instead of
    the hand-written CSV ``String`` column, which is unreliable (e.g. 289:24 reads
    ``Barrel_01_GammaVoid`` but is really ``part_barrel_02_gammavoid``).
    """
    index = _item_index()
    ref = (index.get("part_refs") or {}).get(ref_key) or {}
    return str(ref.get("part") or "")


def equipment_firmware_parts(owner: Any) -> list[tuple[str, str]]:
    """List ``(part_id, internal_part)`` for every firmware ref of one family owner.

    The firmware pool is shared across the four equipment families but each family
    assigns its own serial child ids (the DLC firmwares are 244:26-29 on heavy yet
    245:87-90 on grenade), so pickers must enumerate the family's own refs from the
    index rather than read a shared id list.
    """
    index = _item_index()
    out: list[tuple[str, str]] = []
    for key, ref in (index.get("part_refs") or {}).items():
        owner_key, _, part_id = str(key).partition(":")
        if owner_key == str(owner) and ref.get("category") == "firmware" and part_id.isdigit():
            out.append((part_id, str(ref.get("part") or "")))
    return sorted(out, key=lambda item: int(item[0]))


def equipment_part_name(ref_key: str, lang: str = "zh-CN", fallback: str = "") -> str:
    index = _item_index()
    ref = (index.get("part_refs") or {}).get(ref_key) or {}
    key = "zh" if _lang_is_zh(lang) else "en"
    if ref.get("category") == "firmware":
        # Firmware names live in the shared table, keyed by the internal part string.
        try:
            entry = _equipment_firmware_entry(ref_key, "", lang)
        except (KeyError, OSError, TypeError, ValueError):
            entry = None
        name = str((entry or {}).get("name") or "").strip()
        if name:
            return name
    name = (ref.get("name") or {}).get(key) or (ref.get("name") or {}).get("en") or ""
    if ref.get("category") == "barrel" and _valid_name(name):
        return name
    for ui_id in ref.get("uistats_include") or ref.get("uistats", []):
        ui_key = str(ui_id).casefold()
        if any(marker in ui_key for marker in ("redtext", "red_text", "typeline", "_manu_")):
            continue
        ui = (index.get("uistats") or {}).get(ui_key) or {}
        title = _title_from_text(ui.get(key) or ui.get("en") or "")
        if _valid_name(title):
            return title
    if _valid_name(name):
        return name
    fallback = str(fallback or "").strip()
    if not _valid_name(fallback):
        return ""
    return re.split(r"\s+[-–—]\s+", fallback, maxsplit=1)[0].strip()


def _serial_without_equipment_part(decoded: str, root_id: str, ref_key: str) -> str:
    owner_wanted, part_wanted = ref_key.split(":", 1)
    removed = False

    def remove(match: re.Match[str]) -> str:
        nonlocal removed
        owner, separator, payload = match.group(1).partition(":")
        owner = owner.strip()
        if not separator:
            if not removed and owner_wanted == root_id and owner == part_wanted:
                removed = True
                return ""
            return match.group(0)
        if removed or owner != owner_wanted:
            return match.group(0)
        ids = re.findall(r"\d+", payload)
        if part_wanted not in ids:
            return match.group(0)
        ids.remove(part_wanted)
        removed = True
        if not ids:
            return ""
        return f"{{{owner}:{ids[0]}}}" if len(ids) == 1 else f"{{{owner}:[{' '.join(ids)}]}}"

    return re.sub(r"\{([^{}]+)\}", remove, decoded)


@lru_cache(maxsize=4096)
def format_equipment_part_description(
    decoded_full: str,
    item_type: str,
    ref_key: str,
    lang: str = "zh-CN",
    strict_delta: bool = False,
) -> str:
    """Render official UIStat values and current-build final stats for one equipment part.

    With ``strict_delta`` the leave-one-out comparison is skipped whenever the
    baseline serial cannot be evaluated. Removing the rarity-bearing ``inv_comp``
    part makes the baseline raise "no indexed rarity", which otherwise leaves
    ``before`` empty and misreports the item's whole stat block as that single
    part's contribution. Existing callers keep the old lenient behaviour.
    """
    index = _item_index()
    lines = []
    try:
        official = equipment_display_stats.equipment_part_uistat_descriptions(
            decoded_full, index, item_type, ref_key, lang
        )
    except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError):
        official = []
    for text in official:
        for separator in (" - ", " – "):
            if separator in text:
                text = text.split(separator, 1)[1].strip()
                break
        if text and text not in lines:
            lines.append(text)

    ref = (index.get("part_refs") or {}).get(ref_key) or {}
    if ref.get("category") == "element":
        try:
            root_id, _level = equipment_display_stats._header(decoded_full)
            _family, model, _root = equipment_display_stats._family_model(index, root_id, item_type)
            defaults = model.get("attribute_defaults") or {}
            resist = next(
                (
                    equipment_display_stats._effect_value(effect, defaults)
                    for effect in ref.get("weapon_attribute_effects", [])
                    if effect.get("attribute") == "shield_elemental_damage_reduction"
                ),
                None,
            )
            if resist is not None:
                text = f"{abs(resist):.0%}抗性" if _lang_is_zh(lang) else f"{abs(resist):.0%} Resistance"
                if text not in lines:
                    lines.append(text)
        except (KeyError, TypeError, ValueError):
            pass

    if ref.get("category") == "firmware":
        # Firmware text comes from the shared pipeline-exported table (see
        # _equipment_firmware_entry). The serial contains one firmware identity,
        # not three repeated tokens, so show the complete L1/L2/L3 progression.
        try:
            entry = _equipment_firmware_entry(ref_key, item_type, lang)
        except (KeyError, OSError, TypeError, ValueError):
            entry = None
        descs = list((entry or {}).get("descs") or [])
        if descs:
            for level, text in enumerate(descs, 1):
                text = f"L{level}: {text}" if text else ""
                if text and text not in lines:
                    lines.append(text)

    try:
        root_id, _level = equipment_display_stats._header(decoded_full)
        candidate = equipment_display_stats._candidate_serial(decoded_full, index, root_id, ref_key)
        selected = ref_key in weapon_display_stats._serial_part_keys(decoded_full, root_id)
        baseline = _serial_without_equipment_part(decoded_full, root_id, ref_key) if selected else decoded_full
        baseline_failed = False
        try:
            before = equipment_display_stats.equipment_card_stats_from_serial(baseline, index, item_type)
        except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError):
            before = {}
            baseline_failed = True
        after = equipment_display_stats.equipment_card_stats_from_serial(candidate, index, item_type)
        if strict_delta and baseline_failed:
            after = {}
    except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError):
        after = {}
        before = {}

    for key, labels in EQUIPMENT_PART_STAT_LABELS.items():
        if key not in after or after.get(key) == before.get(key):
            continue
        value = format_equipment_stat(key, after[key], lang)
        label = labels[0] if _lang_is_zh(lang) else labels[1]
        joined = " ".join(lines).casefold()
        if label.casefold() in joined or (
            key == "critical_chance"
            and (("暴击" in joined and "几率" in joined) or ("critical" in joined and "chance" in joined))
        ):
            continue
        text = f"{label} {value}"
        if text not in lines:
            lines.append(text)
    return ", ".join(lines)


_EQUIPMENT_ELEMENT_KEYS = {
    "corrosive": "corrosive",
    "cryo": "cryo",
    "fire": "fire",
    "incendiary": "fire",
    "radiation": "radiation",
    "shock": "shock",
    "electric": "shock",
    "kinetic": "kinetic",
    "sonic": "sonic",
}

# Firmware names and per-level descriptions are shared across all four equipment
# families (same internal parts, only the serial child ids differ per family), so they
# live in one pipeline-exported table keyed by the internal part string instead of a
# firmware section in every *_main_perk.csv.
_EQUIPMENT_FIRMWARE_TABLE = "Firmware/firmware.csv"


def limit_item_card_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one Pearl row plus the native 1 legendary / 3 normal card budget."""
    pearl = [entry for entry in entries if entry.get("display_kind") == "pearl"][:1]
    legendary = [entry for entry in entries if entry.get("display_kind") == "legendary"][:1]
    normal = [entry for entry in entries if entry.get("display_kind") not in {"pearl", "legendary"}]
    return [*pearl, *legendary, *normal[:3 if legendary else 4]]


def item_card_entry_kind(ref: dict[str, Any]) -> str:
    if ref.get("category") == "pearl_elem":
        return "pearl"
    ui_ids = [*ref.get("uistats", []), *ref.get("uistats_include", [])]
    if any("redtext" in str(ui_id).casefold() or "red_text" in str(ui_id).casefold() for ui_id in ui_ids):
        return "legendary"
    return "normal"


def _equipment_firmware_entry(ref_key: str, item_type: str, lang: str) -> dict[str, Any] | None:
    internal = str((_item_index().get("part_refs") or {}).get(ref_key, {}).get("part") or "")
    if not internal:
        return None
    row = next((r for r in _rows_by_file(_EQUIPMENT_FIRMWARE_TABLE) if (r.get("part") or "").strip() == internal), None)
    if row is None:
        return None
    zh = _lang_is_zh(lang)

    def pick(stem: str) -> str:
        if zh:
            return (row.get(f"{stem}_ZH") or "").strip() or (row.get(f"{stem}_EN") or "").strip()
        return (row.get(f"{stem}_EN") or "").strip() or (row.get(f"{stem}_ZH") or "").strip()

    name = pick("Name")
    descs = [pick(f"Desc_L{level}") for level in (1, 2, 3)]
    return {
        "id": ref_key.partition(":")[2],
        "name": name,
        "text": name,
        "category": "firmware",
        "internal": internal,
        "descs": descs,
        "level_descs": [
            {"level": level, "text": text}
            for level, text in enumerate(descs, 1)
            if text
        ],
        "count": 1,
        "level": 0,
        "max_level": 3,
    }


@lru_cache(maxsize=2048)
def resolve_equipment_card_details(
    decoded_full: str,
    item_type: str,
    lang: str = "zh-CN",
) -> dict[str, Any]:
    """Return the official effect rows needed by the Item-tab equipment card."""
    if item_type not in {"Grenade", "Shield", "Repkit", HEAVY_TYPE}:
        return {}
    try:
        root_id, _level = equipment_display_stats._header(decoded_full)
        ref_keys = weapon_display_stats._serial_part_keys(decoded_full, root_id)
    except (KeyError, TypeError, ValueError):
        return {}

    index = _item_index()
    rows: list[str] = []
    entries: list[dict[str, Any]] = []
    red_texts: list[str] = []
    firmware: list[dict[str, Any]] = []
    element = ""
    element_text = ""
    for ref_key in ref_keys:
        ref = (index.get("part_refs") or {}).get(ref_key) or {}
        category = str(ref.get("category") or "")
        part_name = str(ref.get("part") or "").casefold()
        if category == "firmware":
            existing = next((entry for entry in firmware if entry["id"] == ref_key.partition(":")[2]), None)
            if existing:
                existing["count"] += 1
            elif entry := _equipment_firmware_entry(ref_key, item_type, lang):
                firmware.append(entry)
            continue
        if category in {"element", "body_ele"}:
            element = next((value for marker, value in _EQUIPMENT_ELEMENT_KEYS.items() if marker in part_name), element)
            description = format_equipment_part_description(decoded_full, item_type, ref_key, lang)
            if "抗性" in description or "resistance" in description.casefold():
                element_text = description
            continue

        try:
            official = equipment_display_stats.equipment_part_uistat_descriptions(
                decoded_full, index, item_type, ref_key, lang, with_ids=True
            )
        except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError):
            official = []
        for entry in official:
            text = str(entry.get("text") or "")
            if text and text not in rows:
                rows.append(text)
                ui_key = str(entry.get("uistat") or "").casefold()
                ui = (index.get("uistats") or {}).get(ui_key) or {}
                entries.append({
                    "text": text,
                    "icon_asset": str(ui.get("icon_asset") or ref.get("icon_asset") or ""),
                    "ref_key": ref_key,
                    "uistat": ui_key,
                    "category": category,
                    "display_kind": item_card_entry_kind(ref),
                })

        for ui_id in ref.get("uistats_include") or ref.get("uistats", []):
            ui_key = str(ui_id).casefold()
            if not any(marker in ui_key for marker in ("redtext", "red_text")):
                continue
            ui = (index.get("uistats") or {}).get(ui_key) or {}
            text = _clean_markup(ui.get("zh" if _lang_is_zh(lang) else "en") or ui.get("en") or "")
            if text and "{" not in text and text not in red_texts:
                red_texts.append(text)

    return {
        "rows": rows,
        "entries": entries,
        "display_entries": limit_item_card_entries(entries),
        "red_texts": red_texts,
        "display_red_texts": red_texts[:1],
        "firmware": firmware,
        "element": element,
        "element_text": element_text,
    }


def _localized_uistat_text(ui: dict[str, Any], lang: str) -> str:
    text = str(ui.get("zh" if _lang_is_zh(lang) else "en") or ui.get("en") or "")
    if not _lang_is_zh(lang):
        return text
    try:
        repaired = text.encode("latin1").decode("gbk")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    return repaired if len(re.findall(r"[\u4e00-\u9fff]", repaired)) > len(re.findall(r"[\u4e00-\u9fff]", text)) else text


def _classmod_skill_stat_lines(
    skill_key: str,
    level: int,
    ranks: dict[tuple[str, str], int],
    lang: str,
) -> list[str]:
    model = _item_index().get("classmod_skill_model") or {}
    stats = ((model.get("skills") or {}).get(skill_key) or {}).get("stats") or []
    resolvers = model.get("attribute_resolvers") or {}
    cache: dict[str, float | None] = {}
    resolving: set[str] = set()

    def number(value: Any) -> float | None:
        return equipment_display_stats._number(value)

    def attribute_name(value: Any) -> str:
        return equipment_display_stats._ref_name(value)

    def rank_value(node: dict[str, Any]) -> float:
        ref = node.get("progressgraphnoderef") or {}
        graph = attribute_name(ref.get("progressgraph"))
        name = str(ref.get("nodename") or "").casefold()
        return float(ranks.get((graph, name), 0))

    def atom(node: Any) -> float | None:
        direct = number(node)
        if direct is not None:
            return direct
        if not isinstance(node, dict):
            return None
        if node.get("attribute"):
            return resolve_attribute(attribute_name(node["attribute"]))
        if (value := number(node.get("resolved_value"))) is not None:
            return value
        if (value := atom(node.get("datatablevalue"))) is not None:
            return value
        if (value := number(node.get("constant"))) is not None:
            return value
        kind = str(node.get("type") or "").casefold()
        if kind == "attribute":
            return resolve_attribute(attribute_name(node.get("value")))
        if kind in {"datatable", "float", "int"}:
            return atom(node.get("value"))
        if (value := atom(node.get("attributeinit"))) is not None:
            scale = number((node.get("attributeinit") or {}).get("basescale")) or 1.0
            post = number((node.get("attributeinit") or {}).get("postscale")) or 1.0
            return value * scale * post
        return atom(node.get("defaultvalue"))

    def expression_value(expression: dict[str, Any]) -> float | None:
        if isinstance(expression, str):
            expression = {"formula": expression}
        if not isinstance(expression, dict):
            return None
        formula = str(expression.get("formula") or "")
        values: dict[str, float] = {}
        pairs = (((expression.get("variables") or {}).get("variablevalues") or {}).get("pairs") or {})
        for pair in pairs.values() if isinstance(pairs, dict) else ():
            name = str(pair.get("key") or "")
            value = atom((pair.get("value") or {}).get("value"))
            if name and value is not None:
                values[name] = value

        def replace_attribute(match: re.Match[str]) -> str:
            key = f"a{len(values)}"
            value = resolve_attribute(attribute_name(match.group(1)))
            if value is None:
                raise ValueError("unresolved attribute")
            values[key] = value
            return key

        try:
            formula = re.sub(r"\battr\(\s*([^()]+?)\s*\)", replace_attribute, formula, flags=re.I)
        except ValueError:
            return None
        return equipment_display_stats._safe_arithmetic(formula, values)

    def resolve_attribute(name: str) -> float | None:
        name = attribute_name(name)
        if name in {"pawn_experience_level", "inventory_experience_level", "weapon_level"}:
            return float(level)
        if name.endswith("resource_pct"):
            return 0.0
        if name in cache:
            return cache[name]
        if not name or name in resolving:
            return None
        resolving.add(name)
        definition = resolvers.get(name) or {}
        value = definition.get("value") or {}
        kind = attribute_name(value.get("structtype"))
        result: float | None = None
        progress = value.get("progressgraphnoderef") or definition.get("progressgraphnoderef")
        if progress:
            result = rank_value({"progressgraphnoderef": progress})
        elif "balancestatevalueresolver" in kind and str(value.get("valuetoresolve") or "").casefold() == "experiencelevel":
            result = float(level)
        elif "expressionvalueresolver" in kind:
            result = expression_value(value.get("expression") or {})
        elif "balanceformulavalueresolver" in kind:
            multiplier = atom(value.get("multiplier"))
            balance_level = atom(value.get("level")) if value.get("level") else 1.0
            power = atom(value.get("power")) if value.get("power") else 1.0
            if multiplier is not None and balance_level is not None and power is not None:
                result = multiplier * (balance_level**power) * (atom(value.get("scalar")) or 1.0)
        elif any(token in kind for token in ("datatablevalueresolver", "constantattributevalueresolver")) or value.get("attributeinit"):
            result = atom(value.get("attributeinit") or value)
        elif "conditionalattributevalueresolver" in kind:
            result = atom(value.get("defaultvalue"))
            if result is None:
                result = 0.0
        elif "skilltokenstackvalueresolver" in kind:
            result = 0.0
        elif "blackboardvalueresolver" in kind:
            result = atom(value.get("defaultvalue"))
            if result is None:
                result = 0.0
        resolving.remove(name)
        cache[name] = result
        return result

    def condition_matches(condition: dict[str, Any]) -> bool:
        if not condition:
            return True
        attribute = str(condition.get("attribute") or "")
        if not attribute:
            return True
        value = resolve_attribute(attribute)
        compare = number(condition.get("compare_value")) or 0.0
        if value is None:
            return False
        return {
            "greaterthan": value > compare,
            "greaterorequal": value >= compare,
            "lessthan": value < compare,
            "lessorequal": value <= compare,
            "equal": value == compare,
            "notequal": value != compare,
        }.get(str(condition.get("compare_type") or "equal").casefold(), value != 0)

    def localized(value: Any, fallback: str) -> str:
        if not isinstance(value, dict):
            return fallback
        return str(value.get("zh" if _lang_is_zh(lang) else "en") or value.get("en") or fallback)

    def display_number(arg: dict[str, Any]) -> str | None:
        if not condition_matches(arg.get("displaycondition") or {}):
            return None
        value = resolve_attribute(str(arg.get("attribute") or ""))
        if value is None:
            return None
        if str(arg.get("signstyle") or "").casefold() == "negative":
            value = -abs(value)
        percentage = bool(arg.get("bdisplayaspercentage"))
        if percentage:
            value *= 100.0
        precision = int(number(arg.get("floatprecision")) or 0)
        if str(arg.get("roundingmode") or "").casefold() == "roundtoint":
            precision = 0
        if precision:
            rendered = f"{value:,.{precision}f}"
        elif abs(value) >= 100 or abs(value - round(value)) < 0.0001:
            rendered = f"{round(value):,}"
        else:
            rendered = f"{value:,.2f}".rstrip("0").rstrip(".")
        if value > 0 and (arg.get("bdisplayplussign") or str(arg.get("signstyle") or "").casefold() == "positive"):
            rendered = f"+{rendered}"
        return f"{rendered}%" if percentage else rendered

    lines: list[str] = []
    for stat in stats:
        kind = attribute_name(stat.get("structtype"))
        text = localized(stat.get("formattext"), "$VALUE$")
        if kind.endswith("numericdisplayvalue"):
            value = display_number(stat)
            if value is None:
                continue
            text = text.replace("$VALUE$", value)
        elif kind.endswith("stringdisplayvalue"):
            args = list((stat.get("args") or {}).items())
            eligible = [
                (key, arg) for key, arg in args
                if "nextlevel" not in str(arg.get("attribute") or "").replace("_", "").casefold()
                and condition_matches(arg.get("displaycondition") or {})
            ]
            active = [(key, arg) for key, arg in eligible if not arg.get("bshowmodifierdelta")] or eligible[:1]
            if any(not arg.get("bshowstatmodifier") for _key, arg in active):
                active = [(key, arg) for key, arg in active if not arg.get("bshowstatmodifier")]
            replaced = False
            used_groups: set[str] = set()
            for key, arg in active:
                group = str(arg.get("keygroup") or key).casefold()
                if group in used_groups:
                    continue
                value = display_number(arg)
                if value is None:
                    continue
                text, count = re.subn(r"\{" + re.escape(group) + r"\}", value, text, flags=re.I)
                replaced |= bool(count)
                used_groups.add(group)
            if not replaced:
                continue
            text = re.sub(r"\{\w+\}", "", text)
        else:
            continue
        text = re.sub(r"[ \t]+", " ", text).strip()
        if text and text not in lines:
            lines.append(text)
    return lines


@lru_cache(maxsize=1024)
def resolve_classmod_card_details(
    decoded_full: str,
    lang: str = "zh-CN",
    skill_limit: int = 6,
    experience_level: int | None = None,
) -> dict[str, Any]:
    """Resolve localized Class Mod skills, perks and legendary text for an item card."""
    root = re.match(r"\s*(\d+)", decoded_full or "")
    if not root:
        return {}
    item_id = int(root.group(1))
    components = _parse_components(decoded_full.split("||", 1)[-1])
    simple_ids = _simple_ids(components)
    skill_rows = [
        row for row in _rows_by_file("class_mods/Skills.csv")
        if row.get("class_ID", "").strip() == str(item_id)
    ]
    skills_by_code: dict[str, dict[str, str]] = {}
    for row in skill_rows:
        for index in range(1, 6):
            code = row.get(f"skill_ID_{index}", "").strip()
            if code:
                skills_by_code[code] = row

    counts: Counter[str] = Counter()
    order: list[str] = []
    selected_codes: dict[str, list[str]] = {}
    rows_by_key: dict[str, dict[str, str]] = {}
    for part_id in simple_ids:
        if _part_ref(item_id, part_id).get("category") != "passive_points":
            continue
        row = skills_by_code.get(part_id)
        if not row:
            continue
        key = row.get("skill_key") or f"{item_id}:{row.get('skill_name_EN', '')}"
        if key not in counts:
            order.append(key)
            rows_by_key[key] = row
        counts[key] += 1
        selected_codes.setdefault(key, []).append(part_id)

    class_name = next((row.get("class_name", "") for row in skill_rows if row.get("class_name")), "")
    try:
        _root_id, item_level = equipment_display_stats._header(decoded_full)
    except (TypeError, ValueError):
        item_level = 1
    level = experience_level if experience_level is not None and experience_level > 0 else item_level
    ranks = {
        (row.get("graph_name", "").casefold(), row.get("node_name", "").casefold()): counts[key]
        for key, row in rows_by_key.items()
    }
    skills = []
    for key in order[:max(0, skill_limit)]:
        row = rows_by_key[key]
        codes = [row.get(f"skill_ID_{index}", "").strip() for index in range(1, 6)]
        name = row.get("skill_name_ZH" if _lang_is_zh(lang) else "skill_name_EN", "") or row.get("skill_name_EN", "")
        if class_name == "C4sh":
            name = re.sub(r" [BGR]$", "", name)
        skills.append({
            "key": key,
            "name": name,
            "description": row.get("description_ZH" if _lang_is_zh(lang) else "description_EN", "") or row.get("description_EN", ""),
            "points": counts[key],
            "max_points": sum(bool(code) for code in codes),
            "selected_codes": selected_codes[key],
            "skill_type": row.get("skill_type", ""),
            "tree_color": row.get("tree_color", ""),
            "tree_name": row.get("tree_name_ZH" if _lang_is_zh(lang) else "tree_name_EN", "") or row.get("tree_name_EN", ""),
            "graph_name": row.get("graph_name", ""),
            "node_name": row.get("node_name", ""),
            "skill_internal": row.get("skill_internal", ""),
            "icon_file": row.get("icon_file", ""),
            "icon_asset": row.get("icon_asset", ""),
            "stat_lines": _classmod_skill_stat_lines(key, level, ranks, lang),
        })

    perk_ids = _group_sub_ids(components, "234")
    perk_ids.extend(value for value in re.findall(r'"([^"]+)"', decoded_full.split("||", 1)[-1]) if value != "c")
    perk_rows = {row.get("perk_ID", "").strip(): row for row in _rows_by_file("class_mods/Class_perk.csv")}
    perk_counts = Counter(perk_ids)
    perks = []
    firmware = []
    for perk_id in dict.fromkeys(perk_ids):
        ref_key = f"234:{perk_id}"
        ref = _part_ref(234, perk_id)
        row = perk_rows.get(perk_id)
        if ref.get("category") == "firmware":
            entry = _equipment_firmware_entry(ref_key, "Class Mod", lang)
            if entry:
                firmware.append({**entry, "count": perk_counts[perk_id]})
            elif row:
                name = row.get("perk_name_ZH" if _lang_is_zh(lang) else "perk_name_EN", "") or row.get("perk_name_EN", "")
                firmware.append({
                    "id": perk_id,
                    "name": name,
                    "text": name,
                    "count": perk_counts[perk_id],
                    "category": "firmware",
                    "internal": row.get("perk_internal", ""),
                    "level": 0,
                    "max_level": 3,
                })
            continue
        if not row:
            continue
        entry = {
            "id": perk_id,
            "name": row.get("perk_name_ZH" if _lang_is_zh(lang) else "perk_name_EN", "") or row.get("perk_name_EN", ""),
            "count": perk_counts[perk_id],
            "category": row.get("perk_category", ""),
            "internal": row.get("perk_internal", ""),
        }
        if entry["category"] == "firmware":
            shared = _equipment_firmware_entry(ref_key, "Class Mod", lang)
            firmware.append({**(shared or entry), "count": perk_counts[perk_id], "level": 0, "max_level": 3})
        else:
            perks.append(entry)

    effects: list[dict[str, str]] = []
    red_texts: list[str] = []
    index = _item_index()
    seen_uistats: set[str] = set()
    for part_id in simple_ids:
        ref = _part_ref(item_id, part_id)
        if ref.get("category") != "class_mod_body":
            continue
        for ui_id in ref.get("uistats_include") or ref.get("uistats", []):
            ui_key = str(ui_id).casefold()
            if ui_key in seen_uistats:
                continue
            seen_uistats.add(ui_key)
            ui = (index.get("uistats") or {}).get(ui_key) or {}
            text = _localized_uistat_text(ui, lang)
            if not text:
                continue
            if "redtext" in ui_key or "red_text" in ui_key:
                red_texts.append(_clean_markup(text))
            else:
                effects.append({"text": text, "icon_asset": str(ui.get("icon_asset") or "")})

    return {
        "class_name": class_name,
        "skills": skills,
        "skill_count": len(order),
        "omitted_skills": max(0, len(order) - max(0, skill_limit)),
        "perks": perks,
        "firmware": firmware,
        "effects": effects,
        "red_texts": red_texts,
        "display_red_texts": red_texts[:1],
    }


@lru_cache(maxsize=1024)
def resolve_enhancement_card_details(decoded_full: str, lang: str = "zh-CN") -> dict[str, Any]:
    """Resolve localized Enhancement core effects, stat rolls and firmware."""
    root = re.match(r"\s*(\d+)", decoded_full or "")
    if not root:
        return {}
    item_id = int(root.group(1))
    components = _parse_components(decoded_full.split("||", 1)[-1])
    simple_ids = _simple_ids(components)
    shared_ids = _group_sub_ids(components, "247")
    core_rows = {
        (row.get("manufacturers_ID", "").strip(), row.get("perk_ID", "").strip()): row
        for row in _rows_by_file("enhancement/Enhancement_manufacturers.csv")
    }
    shared_rows = {
        row.get("perk_ID", "").strip(): row
        for row in _rows_by_file("enhancement/Enhancement_perk.csv")
        if row.get("manufacturers_ID", "").strip() == "247"
    }
    localized = "perk_name_ZH" if _lang_is_zh(lang) else "perk_name_EN"

    effects = []
    for part_id in simple_ids:
        if _part_ref(item_id, part_id).get("category") != "core_augment":
            continue
        row = core_rows.get((str(item_id), part_id))
        if row:
            effects.append({"id": part_id, "text": row.get(localized, "") or row.get("perk_name_EN", "")})

    stacked_counts: Counter[tuple[str, str]] = Counter()
    stacked_order: list[tuple[str, str]] = []
    for component in components:
        owner = str(component.get("id", ""))
        if owner == "247":
            continue
        part_ids = component.get("sub_ids", []) if component.get("type") == "group" else (
            [component.get("sub_id")] if component.get("type") == "elemental" else []
        )
        for part_id in map(str, filter(None, part_ids)):
            key = (owner, part_id)
            if key not in core_rows:
                continue
            if key not in stacked_counts:
                stacked_order.append(key)
            stacked_counts[key] += 1
    stacked_effects = []
    for owner, part_id in stacked_order:
        row = core_rows[(owner, part_id)]
        stacked_effects.append({
            "manufacturer_id": owner,
            "manufacturer": row.get("manufacturers_name", ""),
            "id": part_id,
            "text": row.get(localized, "") or row.get("perk_name_EN", ""),
            "count": stacked_counts[(owner, part_id)],
        })

    stats = []
    firmware = []
    for part_id in shared_ids:
        ref = _part_ref(247, part_id)
        category = ref.get("category")
        if category == "firmware":
            entry = _equipment_firmware_entry(f"247:{part_id}", "Enhancement", lang)
            if entry:
                firmware.append(entry)
            else:
                row = shared_rows.get(part_id)
                if row:
                    text = row.get(localized, "") or row.get("perk_name_EN", "")
                    firmware.append({
                        "id": part_id,
                        "text": text,
                        "name": text,
                        "category": "firmware",
                        "internal": str(ref.get("part") or ""),
                        "level": 0,
                        "max_level": 3,
                    })
            continue
        row = shared_rows.get(part_id)
        if not row:
            continue
        text = row.get(localized, "") or row.get("perk_name_EN", "")
        entry = {"id": part_id, "text": text}
        if category in {"stat_group1", "stat_group2", "stat_group3"}:
            entry["group"] = category
            stats.append(entry)

    unique_effects: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in [*effects, *stacked_effects]:
        key = (str(entry.get("manufacturer_id") or item_id), str(entry.get("id") or ""))
        unique_effects.setdefault(key, entry)
    display_effects = list(unique_effects.values())[:4]
    display_stats = list({entry["id"]: entry for entry in stats}.values())[:6]
    return {
        "effects": effects,
        "stacked_effects": stacked_effects,
        "stats": stats,
        "firmware": firmware,
        "display_effects": display_effects,
        "display_stats": display_stats,
    }


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
        name, rarity, source = _classmod_name(item_id, simple_ids, lang)
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
