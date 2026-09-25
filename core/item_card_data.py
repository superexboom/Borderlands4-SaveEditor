"""Item card data helpers shared by the card model and the legacy HTML cards.

Moved verbatim from ``tabs/qt_items_tab.py`` (which re-exports them) so the
card model in ``core`` does not depend on the widget module.
"""

import re
from typing import Any, Dict, List

from core import item_display_resolver, resource_loader, weapon_display_stats


WEAPON_CARD_TYPE_ICONS = {
    "Pistol": "ico_art_item_card_weap_pistol.png",
    "Shotgun": "ico_art_item_card_weap_shotgun.png",
    "SMG": "ico_art_item_card_weap_smg.png",
    "Assault Rifle": "ico_art_item_card_weap_assault.png",
    "Sniper": "ico_art_item_card_weap_sniper.png",
}


WEAPON_CARD_PRIMARY_STATS = (
    ("damage", "ico_ui_art_wpn_dmg.png"),
    ("accuracy", "ico_ui_art_wpn_prmry_accuracy.png"),
    ("reload_time", "ico_ui_art_wpn_prmry_reload_time.png"),
    ("fire_rate", "ico_ui_art_wpn_prmry_fire_rate.png"),
    ("magazine", "ico_ui_art_wpn_prmry_mag_size.png"),
)


WEAPON_CARD_SECONDARY_ICONS = {
    "critical_damage": "ico_ui_art_wpn_scndry_crit_hit_dmg.png",
    "ammo_cost": "ico_ui_art_wpn_scndry_ammo_per_shot.png",
    "splash_radius": "ico_ui_art_wpn_scndry_dmg_radius.png",
}


GRENADE_CARD_TYPE_ICONS = {
    "borg": "ico_art_item_card_grenade_borg.png",
    "ripper": "ico_art_item_card_grenade_borg.png",
    "daedalus": "ico_art_item_card_grenade_daedalus.png",
    "jakobs": "ico_art_item_card_grenade_jakobs.png",
    "maliwan": "ico_art_item_card_grenade_maliwan.png",
    "order": "ico_art_item_card_grenade_order.png",
    "tediore": "ico_art_item_card_grenade_tediore.png",
    "torgue": "ico_art_item_card_grenade_torgue.png",
    "vladof": "ico_art_item_card_grenade_vladof.png",
}


EQUIPMENT_CARD_FIELDS = {
    "Grenade": (
        ("cooldown", "ico_ui_art_item_cooldown.png"),
        ("damage", "ico_ui_art_gdgt_grenade_damage.png"),
        ("radius", "ico_ui_art_gdgt_grenade_radius.png"),
        ("charges", "ico_ui_art_gdgt_grenade_charges.png"),
        ("critical_damage", "ico_ui_art_wpn_scndry_crit_hit_dmg.png"),
    ),
    "Shield": (
        ("capacity", "ico_ui_art_shield_capacity.png"),
        ("recharge_rate", "ico_ui_art_shield_recharge_rate.png"),
        ("recharge_delay", "ico_ui_art_shield_recharge_delay.png"),
        ("armor_segments", "ico_ui_art_shield_armor_segments.png"),
        ("damage_reduction", "ico_ui_art_shield_dmg_reduction.png"),
    ),
    "Repkit": (
        ("instant_healing", "ico_ui_art_repkit_prmry_health_burst.png"),
        ("health_over_time", "ico_ui_art_repkit_prmry_health_over_time.png"),
        ("cooldown", "ico_ui_art_item_cooldown.png"),
    ),
    "Heavy Weapon": (
        ("cooldown", "ico_ui_art_item_cooldown.png"),
        ("damage", "ico_ui_art_wpn_dmg.png"),
        ("accuracy", "ico_ui_art_wpn_prmry_accuracy.png"),
        ("fire_rate", "ico_ui_art_wpn_prmry_fire_rate.png"),
        ("magazine", "ico_ui_art_wpn_prmry_mag_size.png"),
        ("critical_damage", "ico_ui_art_wpn_scndry_crit_hit_dmg.png"),
        ("splash_radius", "ico_ui_art_wpn_scndry_dmg_radius.png"),
    ),
}


WEAPON_CARD_RARITY_COLORS = {
    "common": "#BDBBD1",
    "普通": "#BDBBD1",
    "uncommon": "#5AC54F",
    "罕见": "#5AC54F",
    "rare": "#00A0CE",
    "稀有": "#00A0CE",
    "epic": "#B648DB",
    "史诗": "#B648DB",
    "legendary": "#FFD900",
    "传奇": "#FFD900",
    "pearl": "#97FFD2",
    "pearlescent": "#97FFD2",
    "珠光": "#97FFD2",
}


WEAPON_CARD_RARITY_DIM_COLORS = {
    "common": "#9290A8",
    "普通": "#9290A8",
    "uncommon": "#1A892C",
    "罕见": "#1A892C",
    "rare": "#2361B0",
    "稀有": "#2361B0",
    "epic": "#8A1AB3",
    "史诗": "#8A1AB3",
    "legendary": "#A96B1B",
    "传奇": "#A96B1B",
    "pearl": "#0EAFAD",
    "pearlescent": "#0EAFAD",
    "珠光": "#0EAFAD",
}


RARITY_PIP_FILES = {
    "common": "rarity_pip_01_common_tinted.png",
    "普通": "rarity_pip_01_common_tinted.png",
    "uncommon": "rarity_pip_02_uncommon_tinted.png",
    "罕见": "rarity_pip_02_uncommon_tinted.png",
    "rare": "rarity_pip_03_rare_tinted.png",
    "稀有": "rarity_pip_03_rare_tinted.png",
    "epic": "rarity_pip_04_epic_tinted.png",
    "史诗": "rarity_pip_04_epic_tinted.png",
    "legendary": "rarity_pip_05_legendary_tinted.png",
    "传奇": "rarity_pip_05_legendary_tinted.png",
    "pearl": "rarity_pip_06_pearl_tinted.png",
    "pearlescent": "rarity_pip_06_pearl_tinted.png",
    "珠光": "rarity_pip_06_pearl_tinted.png",
}


RARITY_HEADER_KEYS = {
    "common": "common",
    "普通": "common",
    "uncommon": "uncommon",
    "罕见": "uncommon",
    "rare": "rare",
    "稀有": "rare",
    "epic": "epic",
    "史诗": "epic",
    "legendary": "legendary",
    "传奇": "legendary",
    "pearl": "pearl",
    "pearlescent": "pearl",
    "珠光": "pearl",
}


MANUFACTURER_CARD_KEYS = {
    "atlas": "atlas",
    "cov": "cov",
    "childrenofthevault": "cov",
    "daedalus": "daedalus",
    "hyperion": "hyperion",
    "jakobs": "jakobs",
    "maliwan": "maliwan",
    "order": "order",
    "theorder": "order",
    "ripper": "ripper",
    "borg": "ripper",
    "tediore": "tediore",
    "torgue": "torgue",
    "vladof": "vladof",
}


ELEMENT_CARD_TEXT_COLORS = {
    "corrosive": "#2BEF00",
    "cryo": "#16F6F6",
    "fire": "#FF1604",
    "radiation": "#E0FF00",
    "shock": "#2F63F9",
}


CLASSMOD_TREE_COLORS = {
    "red": "#DB834E",
    "blue": "#3CAFAE",
    "green": "#7DCD75",
}


CLASSMOD_PORTRAITS = {
    "Amon": "item_card_class_header_amon.png",
    "Harlowe": "item_card_class_header_harlowe.png",
    "Rafa": "item_card_class_header_rafa.png",
    "Vex": "item_card_class_header_vex.png",
    "C4sh": "item_card_class_header_c4sh.png",
}


FIRMWARE_ICON_ALIASES = {
    "atlas_infinum": "atlas_infinium",
    "daeddy_o": "daedy_o",
    "get_throwin": "get_throwd",
    "active_fire": "activefire",
}


def _weapon_card_rarity_color(rarity: Any) -> str:
    return WEAPON_CARD_RARITY_COLORS.get(str(rarity or "").strip().casefold(), "#78909C")


def _weapon_card_rarity_dim_color(rarity: Any) -> str:
    return WEAPON_CARD_RARITY_DIM_COLORS.get(str(rarity or "").strip().casefold(), "#36515A")


def _effect_icon_uri(asset: str) -> str:
    package = str(asset or "").split(".", 1)[0]
    filename = f"{package.rsplit('/', 1)[-1]}.png" if package else ""
    path = resource_loader.get_resource_path(f"assets/item_card_icons/{filename}")
    return path.as_uri() if filename and path.exists() else ""


def _manufacturer_card_key(item: Dict[str, Any]) -> str:
    raw = str(item.get("manufacturer_en") or item.get("manufacturer") or "")
    normalized = "".join(ch for ch in raw.casefold() if ch.isalnum())
    return MANUFACTURER_CARD_KEYS.get(normalized, "")


def _secondary_stat_keys(stats: Dict[str, Any]) -> List[str]:
    return [
        key
        for key, visible in (
            ("critical_damage", stats.get("critical_damage") not in (None, "", 0, 0.0)),
            ("ammo_cost", (stats.get("ammo_cost") or 0) > 1),
            ("splash_radius", stats.get("splash_radius") not in (None, "", 0, 0.0)),
        )
        if visible
    ]


_CARD_MARKUP_RE = re.compile(r"\[[^\]]+\]")


_CARD_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z0-9_]+)\}")


_GENERIC_WEAPON_UISTAT_PREFIXES = (
    "uistat_damage",
    "uistat_dps_headline",
    "uistat_hw_typeline",
    "uistat_reload_speed",
)


_ELEMENT_NAMES = {
    "kinetic": {"zh": "动能伤害", "en": "Kinetic Damage"},
    "shock": {"zh": "电击伤害", "en": "Shock Damage"},
    "radiation": {"zh": "辐射伤害", "en": "Radiation Damage"},
    "corrosive": {"zh": "腐蚀伤害", "en": "Corrosive Damage"},
    "cryo": {"zh": "冰冻伤害", "en": "Cryo Damage"},
    "fire": {"zh": "燃烧伤害", "en": "Incendiary Damage"},
}


def _clean_card_markup(text: Any) -> str:
    return re.sub(r"\s+", " ", _CARD_MARKUP_RE.sub("", str(text or ""))).strip()


def _element_card_text(stats: Dict[str, Any], element: str, current_lang: str, suffix: str = "") -> str:
    if not element or element == "kinetic":
        return ""
    cryo_key = f"cryo_efficiency{suffix}"
    if element == "cryo" and stats.get(cryo_key) not in (None, ""):
        value = int(stats[cryo_key])
        return f"{value}%冰冻效率" if current_lang == "zh-CN" else f"{value}% Cryo Efficiency"
    dps = stats.get(f"elemental_dps{suffix}")
    chance = stats.get(f"elemental_chance{suffix}")
    if dps not in (None, "") and chance not in (None, ""):
        return (
            f"{int(dps):,}伤害/秒 | {int(chance)}%几率"
            if current_lang == "zh-CN"
            else f"{int(dps):,} DMG/s | {int(chance)}% Chance"
        )
    lang_key = "zh" if current_lang == "zh-CN" else "en"
    return (_ELEMENT_NAMES.get(element) or {}).get(lang_key, "")


def _repkit_element_card_modes(
    element: str,
    entries: List[Dict[str, Any]],
) -> List[tuple[str, str]]:
    """Return every visible Repkit resistance/immunity pair in serial order."""
    refs = item_display_resolver._item_index().get("part_refs") or {}
    modes: List[tuple[str, str]] = []
    for entry in entries:
        category = str(entry.get("category") or "")
        if category not in {"augment_element_resist", "augment_element_immunity"}:
            continue
        ref = refs.get(str(entry.get("ref_key") or "")) or {}
        part_name = str(ref.get("part") or "").casefold()
        key = next((name for name in _ELEMENT_NAMES if name != "kinetic" and name in part_name), "")
        if key:
            modes.append((key, "immunity" if category == "augment_element_immunity" else "resistance"))
    if not modes and element:
        immunity = any(entry.get("category") == "augment_element_immunity" for entry in entries)
        modes.append((element, "immunity" if immunity else "resistance"))
    return list(dict.fromkeys(modes))


def _repkit_element_card_text(element: str, entries: List[Dict[str, Any]], current_lang: str) -> str:
    modes = _repkit_element_card_modes(element, entries)
    if not modes:
        return ""
    lang_key = "zh" if current_lang == "zh-CN" else "en"
    labels = []
    for key, mode in modes:
        base = (_ELEMENT_NAMES.get(key) or {}).get(lang_key, "")
        base = base.removesuffix("伤害") if current_lang == "zh-CN" else base.removesuffix(" Damage")
        labels.append(
            f"{base}{'免疫' if mode == 'immunity' else '抗性'}"
            if current_lang == "zh-CN"
            else f"{base} {'Immunity' if mode == 'immunity' else 'Resistance'}"
        )
    return " / ".join(labels)


def _part_element_keys(part_name: str) -> List[str]:
    return [
        name
        for _, name in sorted(
            (part_name.find(name), name)
            for name in _ELEMENT_NAMES
            if name != "kinetic" and part_name.find(name) >= 0
        )
    ]


def _weapon_card_parts(decoded_full: str) -> List[tuple[str, Dict[str, Any]]]:
    root = re.match(r"\s*(\d+)", decoded_full or "")
    if not root:
        return []
    refs = (item_display_resolver._item_index().get("part_refs") or {})
    return [
        (key, refs[key])
        for key in dict.fromkeys(weapon_display_stats._serial_part_keys(decoded_full, root.group(1)))
        if key in refs
    ]


def _weapon_stat_arg_value(attribute: str, stats: Dict[str, Any]) -> Any:
    damage = str(stats.get("damage") or "")
    damage_match = re.match(r"\s*([\d,.]+)(?:\s*[x×]\s*(\d+))?", damage)
    values = {
        "weapon_damage": damage_match.group(1) if damage_match else stats.get("damage"),
        "weapon_projectile_per_shot": (
            int(damage_match.group(2)) if damage_match and damage_match.group(2) else 1
        ),
        "weapon_max_loaded_ammo": stats.get("magazine"),
        "weapon_fire_rate": stats.get("fire_rate"),
        "weapon_reload_time": stats.get("reload_time"),
        "weapon_damage_radius": stats.get("splash_radius"),
        "weapon_shot_cost": stats.get("ammo_cost"),
        "weapon_critical_hit_damage": stats.get("critical_damage"),
    }
    return values.get(str(attribute or "").casefold())


def _format_weapon_arg(raw: Any) -> str:
    if raw in (None, ""):
        return "—"
    if isinstance(raw, float):
        return f"{raw:,.2f}".rstrip("0").rstrip(".")
    if isinstance(raw, int):
        return f"{raw:,}"
    return str(raw)


def _render_weapon_uistat(entry: Dict[str, Any], stats: Dict[str, Any], current_lang: str,
                          keep_markup: bool = False) -> str:
    lang_key = "zh" if current_lang == "zh-CN" else "en"
    text = str(entry.get(lang_key) or entry.get("en") or "")
    args = ((entry.get("statvalue") or {}).get("args") or {})

    def replacement(match: re.Match[str]) -> str:
        arg = args.get(match.group(1)) or {}
        template = arg.get("formattext") or {}
        template_text = str(template.get(lang_key) or template.get("en") or "")
        value = _format_weapon_arg(_weapon_stat_arg_value(arg.get("attribute", ""), stats))
        if template_text and "$VALUE$" not in template_text:
            return _clean_card_markup(template_text)
        return template_text.replace("$VALUE$", value) if template_text else value

    rendered = _CARD_PLACEHOLDER_RE.sub(replacement, text)
    # keep_markup: the item card colours [secondary]/[rarity_*] spans and draws icon tags.
    return " ".join(rendered.split()) if keep_markup else _clean_card_markup(rendered)


def _select_tediore_uistat(ids: List[str], context: str) -> List[str]:
    if len(ids) not in {4, 12} or not all("ted_" in item.casefold() for item in ids):
        return ids
    path = next((name for name in ("homing", "javelin", "legs") if f"ted_{name}" in context), "default")
    mode = next((name for name in ("replicator", "combo", "mirv") if f"ted_{name}" in context), "")
    candidates = [item for item in ids if item.casefold().endswith(f"_{path}")]
    if mode:
        mode_candidates = [item for item in candidates if f"_{mode}_" in item.casefold()]
        if mode_candidates:
            candidates = mode_candidates
    return candidates[:1] or ids[:1]


def _weapon_card_details(decoded_full: str, stats: Dict[str, Any], current_lang: str) -> Dict[str, Any]:
    index = item_display_resolver._item_index()
    uistats = index.get("uistats") or {}
    parts = _weapon_card_parts(decoded_full)
    context = " ".join(
        [str(ref.get("part") or "") for _, ref in parts]
        + [str(tag) for _, ref in parts for tag in ref.get("weapon_tags", [])]
    ).casefold()
    rows: List[str] = []
    entries: List[Dict[str, str]] = []
    red_texts: List[str] = []
    element = ""
    elements: List[str] = []
    pearl_element = ""
    for ref_key, ref in parts:
        part_name = str(ref.get("part") or "").casefold()
        category = str(ref.get("category") or "")
        if category in {"body_ele", "secondary_ele", "pearl_elem"}:
            keys = _part_element_keys(part_name)
            if "normal" in part_name:
                keys = ["kinetic"]
            if category == "pearl_elem" and not pearl_element:
                pearl_element = keys[0] if keys else ""
            else:
                for key in keys:
                    if key not in elements:
                        elements.append(key)
                if category == "body_ele" and keys:
                    element = keys[0]

        ids = list(dict.fromkeys([*ref.get("uistats_include", []), *ref.get("uistats", [])]))
        red_ids = [item for item in ids if "redtext" in item.casefold() or "red_text" in item.casefold()]
        effect_ids = [item for item in ids if item not in red_ids]
        effect_ids = _select_tediore_uistat(effect_ids, context)
        for ui_id in red_ids:
            text = _render_weapon_uistat(uistats.get(ui_id.casefold(), {}), stats, current_lang)
            if text and text not in red_texts:
                red_texts.append(text)
        for effect_index, ui_id in enumerate(effect_ids):
            if ui_id.casefold().startswith(_GENERIC_WEAPON_UISTAT_PREFIXES):
                continue
            ui = uistats.get(ui_id.casefold(), {})
            text = _render_weapon_uistat(ui, stats, current_lang)
            if text and text not in rows:
                rows.append(text)
                entries.append({
                    "text": text,
                    "markup": _render_weapon_uistat(ui, stats, current_lang, keep_markup=True),
                    "category": category,
                    "source": ref_key,
                    "display_kind": (
                        "legendary"
                        if ref.get("token_icon_asset") and item_display_resolver.item_card_entry_kind(ref) == "normal"
                        else item_display_resolver.item_card_entry_kind(ref)
                    ),
                    "icon_asset": str(
                        (ref.get("token_icon_asset") if effect_index == 0 else "")
                        or ui.get("icon_asset")
                        or ref.get("icon_asset")
                        or ""
                    ),
                })

    if pearl_element:
        elements = [pearl_element, *(key for key in elements if key not in {element, pearl_element})]
        element = pearl_element
    elif element and element not in elements:
        elements.insert(0, element)
    lang_key = "zh" if current_lang == "zh-CN" else "en"
    return {
        "rows": rows,
        "entries": entries,
        "display_entries": item_display_resolver.limit_item_card_entries(entries),
        "red_texts": red_texts,
        "display_red_texts": red_texts[:1],
        "element": element,
        "elements": elements,
        "element_text": (_ELEMENT_NAMES.get(element) or {}).get(lang_key, ""),
    }
