from html import escape
import re
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QEvent, QModelIndex, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyle,
    QToolTip,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

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


def _card_header_color(rarity: Any) -> str:
    base = (10, 34, 43)
    tint = _weapon_card_rarity_dim_color(rarity).lstrip("#")
    overlay = tuple(int(tint[index : index + 2], 16) for index in (0, 2, 4))
    return "#" + "".join(f"{round(bg * 0.58 + fg * 0.42):02X}" for bg, fg in zip(base, overlay))


def _card_asset_uri(filename: str) -> str:
    return resource_loader.get_resource_path(f"assets/item_card/{filename}").as_uri()


def _card_header_row(
    item: Dict[str, Any],
    current_lang: str,
    level_label: str,
    right_html: str,
    headline_html: str = "",
) -> str:
    rarity = item.get("rarity")
    rarity_key = str(rarity or "").strip().casefold()
    rarity_color = _weapon_card_rarity_color(rarity)
    pip_file = RARITY_PIP_FILES.get(rarity_key)
    rarity_pip = f"<img src='{_card_asset_uri(pip_file)}' height='12'>" if pip_file else ""
    level = escape(str(item.get("level", "")))
    level_text = f"{level}级" if current_lang == "zh-CN" else f"{escape(level_label)} {level}"
    header_key = RARITY_HEADER_KEYS.get(rarity_key, "common")
    header_uri = _card_asset_uri(f"item_card_header_{header_key}.png")
    return (
        "<tr><td colspan='2' width='520' valign='top' "
        f"style=\"background-color:{_card_header_color(rarity)}; background-image:url('{header_uri}');\">"
        "<table width='520' height='110' cellspacing='0' cellpadding='0'><tr>"
        "<td width='300' valign='top' style='padding:9px 10px'>"
        f"<span style='font-size:20px; font-weight:600; color:#f3ead1'>{escape(str(item.get('name') or '-'))}</span><br>"
        f"{rarity_pip} <span style='font-size:14px; color:{rarity_color}'>{escape(str(rarity or ''))}</span> "
        f"<span style='font-size:14px; color:{rarity_color}'>· {escape(str(item.get('type') or ''))}</span>{headline_html}"
        "</td><td width='200' align='right' valign='top' style='padding:6px 10px'>"
        f"<span style='font-size:18px; color:#e5ecee'>{level_text}</span><br>{right_html}"
        "</td></tr></table></td></tr>"
    )


def _effect_icon_uri(asset: str) -> str:
    package = str(asset or "").split(".", 1)[0]
    filename = f"{package.rsplit('/', 1)[-1]}.png" if package else ""
    path = resource_loader.get_resource_path(f"assets/item_card_icons/{filename}")
    return path.as_uri() if filename and path.exists() else ""


def _effect_icon_cell(icon_html: str, size: int = 38) -> str:
    return (
        "<td width='44' align='center' valign='top' style='padding:2px'>"
        f"<table width='{size}' height='{size}' cellspacing='0' cellpadding='0' bgcolor='#164653'>"
        f"<tr><td width='{size}' height='{size}' align='center' valign='middle'>{icon_html}</td></tr>"
        "</table></td>"
    )


def _card_section_divider_html() -> str:
    return (
        "<tr><td colspan='2' style='padding:2px 10px'>"
        f"<img src='{_card_asset_uri('item_card_section_divider.png')}' width='500' height='2'>"
        "</td></tr>"
    )


def _firmware_card_html(entries: List[Dict[str, Any]], current_lang: str) -> str:
    if not entries:
        return ""
    raw_name = str(entries[0].get("name") or entries[0].get("text") or "")
    name = re.sub(r"\s*[-–]\s*(?:Firmware|固件)\s*$", "", raw_name, flags=re.IGNORECASE).strip()
    name = name or ("技能工艺" if current_lang == "zh-CN" else "Skillcraft")
    internal = str(entries[0].get("internal") or "").casefold().removeprefix("part_firmware_")
    icon_stem = FIRMWARE_ICON_ALIASES.get(internal, internal)
    icon_path = resource_loader.get_resource_path(f"assets/item_card/ico_firmware_{icon_stem}_big.png")
    icon_html = f"<img src='{icon_path.as_uri()}' width='46'>" if icon_stem and icon_path.exists() else ""
    level = max(0, min(3, int(entries[0].get("level") or 0)))
    bars = "".join(
        "<td width='94' align='center'>"
        f"<img src='{_card_asset_uri('item_card_firmware_bar_filled.png' if index < level else 'item_card_firmware_bar_empty.png')}' "
        "width='90' height='8'></td>"
        for index in range(3)
    )
    return (
        "<tr><td colspan='2' bgcolor='#0a222b' style='padding:2px 10px'>"
        "<table width='500' cellspacing='0' cellpadding='0'>"
        "<tr><td width='52' align='center' valign='middle' style='padding:3px 3px'>"
        f"{icon_html}</td><td width='350' valign='middle' style='padding:2px 4px'>"
        f"<span style='font-size:16px; font-weight:600; color:#39BCE8'>{escape(name)}</span><br>"
        "<table width='286' cellspacing='1' cellpadding='0'><tr>"
        f"{bars}</tr></table></td>"
        "<td width='86' align='right' valign='top' style='padding:4px'>"
        "<span style='font-size:18px; font-weight:700; color:#39BCE8'>0/3</span></td></tr>"
        "</table></td></tr>"
    )


def _classmod_skill_icon_uri(class_name: str, filename: str) -> str:
    path = resource_loader.get_class_mods_image_path(class_name, filename)
    return path.as_uri() if path and path.exists() else ""


def _element_row_html(element_text: str, element_keys: List[str], primary_element: str) -> str:
    if not element_text or primary_element not in ELEMENT_CARD_TEXT_COLORS:
        return ""
    icons = []
    for key in dict.fromkeys(element_keys):
        if key not in ELEMENT_CARD_TEXT_COLORS:
            continue
        filename = f"ico_ui_art_elemental_{key}_tinted.png"
        if resource_loader.get_resource_path(f"assets/item_card/{filename}").exists():
            icons.append(f"<img src='{_card_asset_uri(filename)}' width='25' height='25'>")
    backing = f"item_card_element_row_{primary_element}.png"
    if not icons or not resource_loader.get_resource_path(f"assets/item_card/{backing}").exists():
        return ""
    return (
        "<tr><td colspan='2' bgcolor='#091923' style='padding:6px 10px'>"
        "<table width='500' height='40' cellspacing='0' cellpadding='0'><tr>"
        f"<td width='500' height='40' align='center' valign='middle' "
        f"style=\"background-image:url('{_card_asset_uri(backing)}');\">"
        "<table align='center' cellspacing='0' cellpadding='2'><tr>"
        f"<td align='right' valign='middle'>{''.join(icons)}</td>"
        f"<td align='left' valign='middle'><span style='font-size:16px; font-weight:600; "
        f"color:{ELEMENT_CARD_TEXT_COLORS[primary_element]}'>{escape(element_text)}</span></td>"
        "</tr></table></td></tr></table></td></tr>"
    )


def _card_markup(text: Any) -> str:
    return item_display_resolver.render_skill_markup(re.sub(r"\{\d+\}", "?", str(text or "")))


def _skill_card_description(text: Any) -> str:
    paragraphs = re.split(
        r"(?:\s*\[newline\]\s*){2,}|\n\s*\n",
        str(text or ""),
        maxsplit=1,
        flags=re.IGNORECASE,
    )
    rendered = _card_markup(paragraphs[0].strip())
    if len(paragraphs) > 1:
        rendered += " <span style='color:#EB7300; font-weight:700'>... ... ...</span>"
    return rendered


def _other_item_card_html(
    item: Dict[str, Any],
    current_lang: str,
    level_label: str,
    right_html: str,
    body_html: str,
) -> str:
    rarity = item.get("rarity")
    rarity_color = _weapon_card_rarity_color(rarity)
    card_font = "'Microsoft YaHei UI','Segoe UI'" if current_lang == "zh-CN" else "'Industry-Medium','Segoe UI'"
    manufacturer_key = _manufacturer_card_key(item)
    logo_file = f"ui_art_manu_itemcard_logotype_{manufacturer_key}.png" if manufacturer_key else ""
    footer = (
        "<tr><td colspan='2' bgcolor='#154653' style='padding:4px 8px'>"
        f"<img src='{_card_asset_uri(logo_file)}' width='175'></td></tr>"
        if logo_file else ""
    )
    return (
        f"<table width='522' cellspacing='0' cellpadding='1' bgcolor='{rarity_color}'><tr><td>"
        f"<table width='520' cellspacing='0' cellpadding='0' bgcolor='#0a222b' style=\"font-family:{card_font};\">"
        f"{_card_header_row(item, current_lang, level_label, right_html)}"
        f"{body_html}{footer}</table></td></tr></table>"
    )


def _manufacturer_card_key(item: Dict[str, Any]) -> str:
    raw = str(item.get("manufacturer_en") or item.get("manufacturer") or "")
    normalized = "".join(ch for ch in raw.casefold() if ch.isalnum())
    return MANUFACTURER_CARD_KEYS.get(normalized, "")


def _header_thumbnail_html(item: Dict[str, Any], content_html: str) -> str:
    manufacturer_key = _manufacturer_card_key(item)
    watermark = f"ui_art_manu_itemcard_logomark_{manufacturer_key}_header.png"
    watermark_path = resource_loader.get_resource_path(f"assets/item_card/{watermark}")
    background = (
        f" style=\"background-image:url('{watermark_path.as_uri()}');\""
        if manufacturer_key and watermark_path.exists()
        else ""
    )
    return (
        "<table width='180' height='90' align='right' cellspacing='0' cellpadding='0'><tr>"
        f"<td width='180' height='90' align='center' valign='middle'{background}>{content_html}</td>"
        "</tr></table>"
    )


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


def _render_weapon_uistat(entry: Dict[str, Any], stats: Dict[str, Any], current_lang: str) -> str:
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

    return _clean_card_markup(_CARD_PLACEHOLDER_RE.sub(replacement, text))


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


def weapon_card_html(
    item: Dict[str, Any],
    current_lang: str,
    level_label: str,
    stat_labels: Optional[Dict[str, str]] = None,
) -> str:
    stats = item.get("weapon_stats") or {}
    weapon_icon = WEAPON_CARD_TYPE_ICONS.get(item.get("type_en", ""))
    if not stats or not weapon_icon:
        return ""
    weapon_icon_width = 120 if item.get("type_en") == "Pistol" else 180

    def image_uri(folder: str, filename: str) -> str:
        return resource_loader.get_resource_path(f"assets/{folder}/{filename}").as_uri()

    def value(key: str) -> str:
        formatted = item_display_resolver.format_weapon_stat(key, stats.get(key), current_lang)
        return escape(formatted or "-")

    primary_cells = "".join(
        f"<td width='100' align='center' valign='middle'>"
        f"<img src='{image_uri('item_stats_icon', icon)}' width='36' height='36'><br>"
        f"<nobr><span style='font-size:18px; color:#eef5f6'>{value(key)}</span></nobr></td>"
        for key, icon in WEAPON_CARD_PRIMARY_STATS
    )
    secondary_keys = _secondary_stat_keys(stats)
    secondary_cells = "".join(
        f"<td width='{500 // len(secondary_keys)}' align='center' valign='middle'>"
        f"<img src='{image_uri('item_stats_icon', WEAPON_CARD_SECONDARY_ICONS[key])}' width='38' height='38'><br>"
        f"<nobr><span style='font-size:18px; color:#eef5f6'>{value(key)}</span></nobr></td>"
        for key in secondary_keys
    )
    secondary_row = (
        "<tr><td colspan='2' bgcolor='#0d2d38'>"
        f"<table width='500' cellspacing='0' cellpadding='5'><tr>{secondary_cells}</tr></table></td></tr>"
        if secondary_cells
        else ""
    )
    rarity = item.get("rarity")
    rarity_color = _weapon_card_rarity_color(rarity)
    dps = item_display_resolver.format_weapon_stat("dps", stats.get("dps"), current_lang)
    dps_line = (
        f"<br><span style='font-size:22px; color:#f3ead1'>{escape(dps)}</span> "
        f"<span style='font-size:13px; color:#aebfc3'>{'伤害输出' if current_lang == 'zh-CN' else 'Damage Output'}</span>"
        if dps
        else ""
    )

    details = _weapon_card_details(str(item.get("decoded_full") or ""), stats, current_lang)
    effect_rows = []
    for entry in details.get("display_entries", details["entries"]):
        text = entry["text"]
        title = str(text)
        description = ""
        for separator in (" - ", " – "):
            if separator in title:
                title, description = title.split(separator, maxsplit=1)
                break
        rendered = f"<span style='font-weight:600; color:#39bce8'>{escape(title)}</span>"
        if description:
            rendered += f"<span style='color:#aebfc3'> - {escape(description)}</span>"
        icon_uri = _effect_icon_uri(entry.get("icon_asset", ""))
        icon_html = (
            f"<img src='{icon_uri}' width='28' height='28'>"
            if icon_uri
            else f"<img src='{_card_asset_uri('item_card_enhancement_bullet.png')}' width='5' height='24'>"
        )
        effect_rows.append(
            f"<tr>{_effect_icon_cell(icon_html)}"
            f"<td width='456' valign='middle' style='padding:1px 6px; font-size:13px; line-height:1.1'>{rendered}</td></tr>"
        )
    effect_gap = "<tr><td colspan='2' height='1'></td></tr>"
    effects_table = (
        "<tr><td colspan='2' bgcolor='#0a222b' style='padding:1px 0'><table width='500' cellspacing='0' cellpadding='0'>"
        f"{effect_gap.join(effect_rows)}</table></td></tr>"
        if effect_rows
        else ""
    )

    mode_suffix = "_mode02" if stats.get("element_mode02") else ""
    element_key = str(stats.get("element_mode02") or stats.get("element") or details.get("element") or "")
    element_text = _element_card_text(stats, element_key, current_lang, mode_suffix)
    element_row = _element_row_html(
        element_text,
        [*(details.get("elements") or []), stats.get("element"), stats.get("element_mode02")],
        element_key,
    )

    red_rows = "".join(
        f"<tr><td colspan='2' align='center' style='padding:4px 18px; color:#f33a47; font-size:14px'><i>{escape(text)}</i></td></tr>"
        for text in details.get("display_red_texts", details["red_texts"][:1])
    )
    manufacturer_key = _manufacturer_card_key(item)
    logo_file = f"ui_art_manu_itemcard_logotype_{manufacturer_key}.png" if manufacturer_key else ""
    manufacturer_footer = (
        "<tr><td colspan='2' bgcolor='#154653' style='padding:4px 8px'>"
        f"<img src='{_card_asset_uri(logo_file)}' width='175'></td></tr>"
        if logo_file
        else ""
    )
    card_font = "'Microsoft YaHei UI','Segoe UI'" if current_lang == "zh-CN" else "'Industry-Medium','Segoe UI'"
    weapon_html = _header_thumbnail_html(
        item, f"<img src='{image_uri('item_card_type', weapon_icon)}' width='{weapon_icon_width}'>"
    )
    red_divider = _card_section_divider_html() if red_rows else ""
    return (
        f"<table width='522' cellspacing='0' cellpadding='1' bgcolor='{rarity_color}'>"
        "<tr><td>"
        f"<table width='520' cellspacing='0' cellpadding='0' bgcolor='#0a222b' style=\"font-family:{card_font};\">"
        f"{_card_header_row(item, current_lang, level_label, weapon_html, dps_line)}"
        "<tr><td colspan='2' bgcolor='#103b49'><table width='500' cellspacing='0' cellpadding='6'>"
        f"<tr>{primary_cells}</tr></table></td></tr>"
        f"{secondary_row}"
        f"{element_row}"
        f"{effects_table}"
        f"{red_divider}"
        f"{red_rows}"
        f"{manufacturer_footer}"
        "</table></td></tr></table>"
    )


def equipment_card_html(
    item: Dict[str, Any],
    current_lang: str,
    level_label: str,
    stat_labels: Optional[Dict[str, str]] = None,
) -> str:
    stats = item.get("equipment_stats") or {}
    item_type = item.get("type_en", "")
    fields = EQUIPMENT_CARD_FIELDS.get(item_type)
    if not stats or not fields:
        return ""

    if item_type == "Grenade":
        manufacturer = str(item.get("manufacturer_en") or item.get("manufacturer") or "").casefold()
        card_icon = next(
            (icon for name, icon in GRENADE_CARD_TYPE_ICONS.items() if name in manufacturer),
            "ico_art_item_card_grenade_torgue.png",
        )
        card_icon_width = 130
    elif item_type == "Shield":
        card_icon = (
            "ico_art_item_card_armor_shield.png"
            if stats.get("armor_segments") not in (None, "", 0, 0.0)
            else "ico_art_item_card_energy_shield.png"
        )
        card_icon_width = 80
    elif item_type == "Repkit":
        card_icon = "ico_art_item_card_rep_kit.png"
        card_icon_width = 80
    else:
        card_icon = "ico_art_item_card_heavy_weapon_generic.png"
        card_icon_width = 150

    def image_uri(folder: str, filename: str) -> str:
        return resource_loader.get_resource_path(f"assets/{folder}/{filename}").as_uri()

    def value(key: str, raw_value: Any) -> str:
        formatter = getattr(item_display_resolver, "format_equipment_stat", None)
        if formatter:
            try:
                formatted = formatter(key, raw_value, current_lang)
            except (TypeError, ValueError, OverflowError):
                formatted = ""
            if formatted:
                if key == "health_over_time" and stats.get("duration") not in (None, ""):
                    duration = item_display_resolver.format_equipment_stat("duration", stats["duration"], current_lang)
                    separator = "，持续" if current_lang == "zh-CN" else ", "
                    return escape(f"{formatted}{separator}{duration}")
                return escape(str(formatted))
        return escape(str(raw_value))

    visible_fields = [
        (key, icon, stats[key])
        for key, icon in fields
        if stats.get(key) not in (None, "")
    ]
    dps = stats.get("dps") if item_type == "Heavy Weapon" else None
    healing = stats.get("healing") if item_type == "Repkit" else None
    if not visible_fields and dps in (None, "") and healing in (None, ""):
        return ""

    labels = stat_labels or {}
    first_row_size = {"Grenade": 4, "Shield": 3, "Repkit": 3, "Heavy Weapon": 5}[item_type]
    field_rows = [visible_fields[:first_row_size], visible_fields[first_row_size:]]
    stat_rows = []
    for row in (row for row in field_rows if row):
        width = 500 // len(row)
        cells = "".join(
            f"<td width='{width}' align='center' valign='middle'>"
            f"<img src='{image_uri('item_stats_icon', icon)}' width='34' height='34'><br>"
            f"<nobr><span style='font-size:18px; color:#eef5f6'>{value(key, raw)}</span></nobr></td>"
            for key, icon, raw in row
        )
        stat_rows.append(f"<tr>{cells}</tr>")

    rarity = item.get("rarity")
    rarity_color = _weapon_card_rarity_color(rarity)
    headline_line = (
        f"<br><span style='font-size:22px; color:#f3ead1'>{value('dps', dps)}</span> "
        f"<span style='font-size:13px; color:#aebfc3'>{'伤害输出' if current_lang == 'zh-CN' else 'Damage Output'}</span>"
        if dps not in (None, "")
        else (
            f"<br><span style='font-size:22px; color:#f3ead1'>{value('healing', healing)}</span> "
            f"<span style='font-size:13px; color:#aebfc3'>{'治疗' if current_lang == 'zh-CN' else 'Healing'}</span>"
            if healing not in (None, "")
            else ""
        )
    )
    stats_table = (
        "<tr><td colspan='2' bgcolor='#103b49'>"
        "<table width='500' cellspacing='0' cellpadding='7'>"
        f"{''.join(stat_rows)}</table></td></tr>"
        if stat_rows
        else ""
    )

    details = item_display_resolver.resolve_equipment_card_details(
        str(item.get("decoded_full") or ""), item_type, current_lang
    )
    detail_entries = list(details.get("entries", []))
    detail_rows = [str(entry.get("text") or "") for entry in detail_entries]
    charges = stats.get("charges")
    if item_type == "Repkit" and isinstance(charges, (int, float)) and charges > 1:
        manufacturer = str(item.get("manufacturer") or "")
        charge_text = (
            f"{manufacturer} - 该修复套件拥有{int(charges)}个能量点"
            if current_lang == "zh-CN"
            else f"{manufacturer} - This Repkit has {int(charges)} charges"
        )
        if not any("能量点" in row or "charges" in row.casefold() for row in detail_rows):
            detail_rows.append(charge_text)
            detail_entries.append({"text": charge_text, "icon_asset": "", "display_kind": "normal"})
    detail_entries = item_display_resolver.limit_item_card_entries(detail_entries)
    effect_rows = []
    for entry in detail_entries:
        text = str(entry.get("text") or "")
        title, separator, description = str(text).partition(" - ")
        rendered = f"<span style='font-weight:600; color:#39bce8'>{escape(title)}</span>"
        if separator:
            rendered += f"<span style='color:#aebfc3'> - {escape(description)}</span>"
        icon_uri = _effect_icon_uri(str(entry.get("icon_asset") or ""))
        icon_html = (
            f"<img src='{icon_uri}' width='28' height='28'>"
            if icon_uri
            else f"<img src='{_card_asset_uri('item_card_enhancement_bullet.png')}' width='5' height='24'>"
        )
        effect_rows.append(
            f"<tr>{_effect_icon_cell(icon_html)}"
            f"<td width='456' valign='middle' style='padding:1px 6px; font-size:13px; line-height:1.1'>{rendered}</td></tr>"
        )
    effect_gap = "<tr><td colspan='2' height='1'></td></tr>"
    effects_table = (
        "<tr><td colspan='2' bgcolor='#0a222b' style='padding:1px 0'><table width='500' cellspacing='0' cellpadding='0'>"
        f"{effect_gap.join(effect_rows)}</table></td></tr>"
        if effect_rows
        else ""
    )

    element_key = str(details.get("element") or "")
    if item_type == "Repkit":
        repkit_modes = _repkit_element_card_modes(element_key, details.get("entries", []))
        element_keys = [key for key, _mode in repkit_modes]
        element_text = _repkit_element_card_text(element_key, details.get("entries", []), current_lang)
        primary_element = element_keys[0] if element_keys else element_key
    else:
        element_keys = [element_key]
        primary_element = element_key
        element_text = str(details.get("element_text") or "") or _element_card_text(stats, element_key, current_lang)
    element_row = _element_row_html(element_text, element_keys, primary_element)

    red_rows = "".join(
        f"<tr><td colspan='2' align='center' style='padding:4px 18px; color:#f33a47; font-size:14px'><i>{escape(text)}</i></td></tr>"
        for text in details.get("display_red_texts", details.get("red_texts", [])[:1])
    )
    firmware_html = _firmware_card_html(details.get("firmware", []), current_lang)
    firmware_divider = _card_section_divider_html() if effects_table and firmware_html else ""
    red_divider = _card_section_divider_html() if firmware_html and red_rows else ""
    manufacturer_key = _manufacturer_card_key(item)
    logo_file = f"ui_art_manu_itemcard_logotype_{manufacturer_key}.png" if manufacturer_key else ""
    manufacturer_footer = (
        "<tr><td colspan='2' bgcolor='#154653' style='padding:4px 8px'>"
        f"<img src='{_card_asset_uri(logo_file)}' width='175'></td></tr>"
        if logo_file
        else ""
    )
    card_font = "'Microsoft YaHei UI','Segoe UI'" if current_lang == "zh-CN" else "'Industry-Medium','Segoe UI'"
    equipment_icon_html = _header_thumbnail_html(
        item, f"<img src='{image_uri('item_card_type', card_icon)}' width='{card_icon_width}'>"
    )
    return (
        f"<table width='522' cellspacing='0' cellpadding='1' bgcolor='{rarity_color}'>"
        "<tr><td>"
        f"<table width='520' cellspacing='0' cellpadding='0' bgcolor='#0a222b' style=\"font-family:{card_font};\">"
        f"{_card_header_row(item, current_lang, level_label, equipment_icon_html, headline_line)}"
        f"{stats_table}"
        f"{element_row}"
        f"{effects_table}"
        f"{firmware_divider}"
        f"{firmware_html}"
        f"{red_divider}"
        f"{red_rows}"
        f"{manufacturer_footer}"
        "</table></td></tr></table>"
    )


def classmod_card_html(
    item: Dict[str, Any],
    current_lang: str,
    level_label: str,
    stat_labels: Optional[Dict[str, str]] = None,
    character_level: Optional[int] = None,
    skill_limit: int = 4,
) -> str:
    if item.get("type_en") != "Class Mod":
        return ""
    details = item_display_resolver.resolve_classmod_card_details(
        str(item.get("decoded_full") or ""), current_lang, skill_limit, character_level
    )
    if not details:
        return ""

    class_name = str(details.get("class_name") or item.get("manufacturer_en") or "")
    portrait = CLASSMOD_PORTRAITS.get(class_name, "")
    portrait_html = (
        f"<img src='{_card_asset_uri(portrait)}' width='86'>"
        if portrait and resource_loader.get_resource_path(f"assets/item_card/{portrait}").exists()
        else ""
    )
    right_html = (
        "<table width='150' align='right' cellspacing='0' cellpadding='0'><tr>"
        f"<td width='150' align='center' valign='middle'>{portrait_html}</td></tr></table>"
    )

    skill_rows = []
    for skill in details.get("skills", []):
        color = CLASSMOD_TREE_COLORS.get(str(skill.get("tree_color") or "").casefold(), "#69BFD0")
        icon_uri = _classmod_skill_icon_uri(class_name, str(skill.get("icon_file") or ""))
        icon_html = f"<img src='{icon_uri}' width='32' height='32'>" if icon_uri else ""
        points = f"+{int(skill.get('points') or 0)}/{int(skill.get('max_points') or 0)}"
        tree_name = escape(str(skill.get("tree_name") or ""))
        stat_lines = []
        for stat_line in skill.get("stat_lines") or skill.get("stats") or []:
            text = stat_line.get("text", "") if isinstance(stat_line, dict) else stat_line
            if text:
                stat_lines.append(_card_markup(text))
        stats_html = (
            "<br><span style='font-size:12px; color:#aebfc3'>"
            + " <span style='color:#52727C'>·</span> ".join(stat_lines)
            + "</span>"
            if stat_lines else ""
        )
        skill_rows.append(
            "<tr>"
            "<td width='116' valign='top' style='padding:1px 4px 1px 0'>"
            f"<span style='font-size:11px; font-weight:600; color:{color}'>{escape(str(skill.get('name') or ''))}</span><br>"
            "<table width='108' height='36' cellspacing='0' cellpadding='0' bgcolor='#113C49'><tr>"
            f"<td width='38' align='center' valign='middle'>{icon_html}</td>"
            f"<td width='70' align='center' valign='middle'><span style='font-size:17px; font-weight:700; color:{color}'>{points}</span></td>"
            "</tr></table></td>"
            f"<td width='384' valign='middle' style='padding:1px 5px; font-size:13px; line-height:1.1'>"
            f"<span style='font-size:11px; color:{color}'>{tree_name}</span>"
            f"{'<br>' if tree_name else ''}{_skill_card_description(skill.get('description'))}{stats_html}</td></tr>"
        )
    skill_gap = "<tr><td colspan='2' height='1'></td></tr>"
    skills_html = (
        "<tr><td colspan='2' bgcolor='#0a222b' style='padding:2px 10px'>"
        f"<table width='500' cellspacing='0' cellpadding='0'>{skill_gap.join(skill_rows)}</table></td></tr>"
        if skill_rows else ""
    )
    if details.get("omitted_skills"):
        skills_html += (
            "<tr><td colspan='2' align='center' style='padding:3px; color:#EB7300; "
            "font-size:16px; font-weight:700'>... ... ...</td></tr>"
        )

    effect_rows = []
    for entry in details.get("effects", []):
        effect_rows.append(
            "<tr><td width='500' valign='middle' "
            f"style='padding:1px 6px; font-size:13px; line-height:1.12'>{_card_markup(entry.get('text'))}</td></tr>"
        )
    perk_rows = []
    for perk in details.get("perks", [])[:3]:
        count = int(perk.get("count") or 1)
        suffix = f" ×{count}" if count > 1 else ""
        perk_rows.append(
            "<tr><td width='20' align='center' valign='middle'>"
            f"<img src='{_card_asset_uri('item_card_enhancement_bullet.png')}' width='5' height='20'></td>"
            f"<td width='480' valign='middle' style='padding:0 5px; font-size:13px; line-height:1.08; color:#aebfc3'>"
            f"{escape(str(perk.get('name') or ''))}<span style='color:#69cde7'>{suffix}</span></td></tr>"
        )
    effects_html = (
        "<tr><td colspan='2' bgcolor='#0a222b' style='padding:1px 10px'>"
        f"<table width='500' cellspacing='0' cellpadding='0'>{skill_gap.join(effect_rows)}</table></td></tr>"
        if effect_rows else ""
    )
    perks_html = (
        "<tr><td colspan='2' bgcolor='#0d2d38' style='padding:2px 10px'>"
        f"<table width='500' cellspacing='0' cellpadding='0'>{''.join(perk_rows)}</table></td></tr>"
        if perk_rows else ""
    )
    red_html = "".join(
        f"<tr><td colspan='2' align='center' style='padding:4px 18px; color:#f33a47; font-size:14px'><i>{escape(text)}</i></td></tr>"
        for text in details.get("red_texts", [])[:1]
    )
    firmware_html = _firmware_card_html(details.get("firmware", []), current_lang)
    perk_divider = _card_section_divider_html() if effects_html and perks_html else ""
    firmware_divider = _card_section_divider_html() if perks_html and firmware_html else ""
    red_divider = _card_section_divider_html() if firmware_html and red_html else ""
    return _other_item_card_html(
        item, current_lang, level_label, right_html,
        f"{skills_html}{effects_html}{perk_divider}{perks_html}"
        f"{firmware_divider}{firmware_html}{red_divider}{red_html}",
    )


def enhancement_card_html(
    item: Dict[str, Any],
    current_lang: str,
    level_label: str,
    stat_labels: Optional[Dict[str, str]] = None,
) -> str:
    if item.get("type_en") != "Enhancement":
        return ""
    details = item_display_resolver.resolve_enhancement_card_details(
        str(item.get("decoded_full") or ""), current_lang
    )
    if not details:
        return ""
    icon_uri = resource_loader.get_resource_path("assets/item_card_type/ico_art_item_card_enhancement.png").as_uri()
    right_html = _header_thumbnail_html(item, f"<img src='{icon_uri}' width='64'>")

    effect_rows = []
    for entry in details.get("display_effects", [*details.get("effects", []), *details.get("stacked_effects", [])]):
        count = int(entry.get("count") or 1)
        suffix = f" ×{count}" if count > 1 else ""
        text = str(entry.get("text") or "")
        title, separator, description = text.partition(" -")
        rendered = f"<span style='font-weight:600; color:#39bce8'>{escape(title)}</span>"
        if separator:
            rendered += f"<span style='color:#aebfc3'> -{escape(description)}</span>"
        rendered += f"<span style='font-weight:700; color:#69cde7'>{suffix}</span>"
        enhancement_icon = f"<img src='{_card_asset_uri('item_card_enhancement_small.png')}' width='26' height='26'>"
        effect_rows.append(
            f"<tr>{_effect_icon_cell(enhancement_icon, 34)}"
            f"<td width='456' valign='middle' style='padding:0 5px; font-size:13px; line-height:1.05'>{rendered}</td></tr>"
        )

    bullet_uri = _card_asset_uri("item_card_enhancement_bullet.png")
    stat_rows = []
    for entry in details.get("display_stats", details.get("stats", [])):
        stat_rows.append(
            "<tr><td width='20' align='center' valign='middle'>"
            f"<img src='{bullet_uri}' width='5' height='20'></td>"
            f"<td width='480' valign='middle' style='padding:0 5px; color:#aebfc3; font-size:13px; line-height:1.08'>"
            f"{escape(str(entry.get('text') or ''))}</td></tr>"
        )
    gap = "<tr><td colspan='2' height='1'></td></tr>"
    body = ""
    if effect_rows:
        body += (
            "<tr><td colspan='2' bgcolor='#0a222b' style='padding:1px 10px'>"
            f"<table width='500' cellspacing='0' cellpadding='0'>{gap.join(effect_rows)}</table></td></tr>"
        )
    if stat_rows:
        body += (
            "<tr><td colspan='2' bgcolor='#0d2d38' style='padding:2px 10px'>"
            f"<table width='500' cellspacing='0' cellpadding='0'>{''.join(stat_rows)}</table></td></tr>"
        )
    firmware_html = _firmware_card_html(details.get("firmware", []), current_lang)
    if stat_rows and firmware_html:
        body += _card_section_divider_html()
    body += firmware_html
    red_html = "".join(
        f"<tr><td colspan='2' align='center' style='padding:4px 18px; color:#f33a47; font-size:14px'><i>{escape(text)}</i></td></tr>"
        for text in details.get("red_texts", [])[:1]
    )
    if firmware_html and red_html:
        body += _card_section_divider_html()
    body += red_html
    return _other_item_card_html(item, current_lang, level_label, right_html, body)


class QtItemsTab(QWidget):
    add_item_requested = pyqtSignal(str, str)

    COLUMN_KEYS = [
        ("name", "name"),
        ("type", "type"),
        ("manufacturer", "manufacturer"),
        ("rarity", "rarity"),
        ("level", "level"),
        ("flags", "state_flags"),
        ("serial", "serial"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_lang = "zh-CN"
        self._load_localization()

        self.model = QStandardItemModel()
        self.model.setHorizontalHeaderLabels(self._headers())
        self.item_lookup: Dict[int, Dict[str, Any]] = {}
        self.current_selected_item: Optional[Dict[str, Any]] = None
        self._card_cache: Dict[tuple[str, ...], str] = {}
        self._hover_card_key: Optional[tuple[str, ...]] = None
        self._pending_hover_key: Optional[tuple[str, ...]] = None
        self._pending_hover_item: Optional[Dict[str, Any]] = None
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        wake_up_delay = self.style().styleHint(QStyle.StyleHint.SH_ToolTip_WakeUpDelay)
        self._hover_timer.setInterval(wake_up_delay if wake_up_delay > 0 else 700)
        self._hover_timer.timeout.connect(self._show_pending_hover_card)
        self.character_level: Optional[int] = None

        self.ui_labels: Dict[str, QLabel] = {}
        self.ui_buttons: Dict[str, QPushButton] = {}
        self.ui_placeholders: Dict[str, QLineEdit] = {}

        main_layout = QVBoxLayout(self)
        self._create_add_item_bar(main_layout)

        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText(self.loc["search_placeholder"])
        self.search_entry.textChanged.connect(self.filter_tree)
        main_layout.addWidget(self.search_entry)

        self.tree_view = QTreeView()
        self.tree_view.setModel(self.model)
        self.tree_view.setAlternatingRowColors(True)
        self.tree_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_view.customContextMenuRequested.connect(self._show_context_menu)
        self.tree_view.selectionModel().selectionChanged.connect(self.on_item_selected)
        self.tree_view.viewport().setMouseTracking(True)
        self.tree_view.viewport().installEventFilter(self)
        header = self.tree_view.header()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(60)
        self.tree_view.horizontalScrollBar().setTracking(False)
        main_layout.addWidget(self.tree_view, 1)
        self._resize_columns()

    def _headers(self) -> List[str]:
        cols = self.loc["columns"]
        return [cols.get(key, key) for key, _ in self.COLUMN_KEYS]

    def _create_add_item_bar(self, layout: QVBoxLayout):
        add_item_frame = QWidget()
        add_item_layout = QHBoxLayout(add_item_frame)
        add_item_layout.setContentsMargins(0, 0, 0, 0)

        self.ui_labels["label_serial"] = QLabel(self.loc["add_item"]["label_serial"])
        add_item_layout.addWidget(self.ui_labels["label_serial"])

        self.add_serial_entry = QLineEdit()
        self.add_serial_entry.setPlaceholderText(self.loc["add_item"]["placeholder_serial"])
        self.ui_placeholders["add_serial"] = self.add_serial_entry
        add_item_layout.addWidget(self.add_serial_entry, 1)

        self.ui_labels["label_flag"] = QLabel(self.loc["add_item"]["label_flag"])
        add_item_layout.addWidget(self.ui_labels["label_flag"])

        self.add_flag_combo = QComboBox()
        self._populate_flags()
        add_item_layout.addWidget(self.add_flag_combo)

        self.ui_buttons["button_add"] = QPushButton(self.loc["add_item"]["button_add"])
        self.ui_buttons["button_add"].clicked.connect(self._on_add_item_clicked)
        add_item_layout.addWidget(self.ui_buttons["button_add"])

        layout.addWidget(add_item_frame)

    def _populate_flags(self):
        self.add_flag_combo.clear()
        flags = self.loc["add_item"]["flags"]
        self.add_flag_combo.addItems(
            [flags["1"], flags["3"], flags["5"], flags["17"], flags["33"], flags["65"], flags["129"]]
        )

    def update_tree(self, items: List[Dict[str, Any]]):
        self._hide_hover_card()
        self.model.clear()
        self.model.setHorizontalHeaderLabels(self._headers())
        self.item_lookup.clear()
        self.current_selected_item = None
        self._card_cache.clear()
        self._resize_columns()

        if not items:
            return

        items_by_container: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
        for i, item in enumerate(items):
            self.item_lookup[i] = item
            container_name = self._container_display(item.get("container"))
            item_type = item.get("type", self.loc["defaults"]["unknown_type"])
            items_by_container.setdefault(container_name, {}).setdefault(item_type, []).append(item)

        root_node = self.model.invisibleRootItem()
        for container_name, types_dict in sorted(items_by_container.items()):
            container_node = self._group_row(container_name)
            root_node.appendRow(container_node)

            for item_type, item_list in sorted(types_dict.items()):
                type_node = self._group_row(f"{item_type} ({len(item_list)})")
                container_node[0].appendRow(type_node)

                for item in sorted(item_list, key=self._slot_sort_key):
                    type_node[0].appendRow(self._item_row(item, container_name))

        self.tree_view.expandAll()
        self._collapse_default_groups()
        if self.search_entry.text():
            self.filter_tree(self.search_entry.text())

    def set_character_level(self, level: Any):
        try:
            parsed = int(level)
        except (TypeError, ValueError):
            parsed = None
        if parsed != self.character_level:
            self.character_level = parsed
            self._card_cache.clear()

    def _group_row(self, text: str) -> List[QStandardItem]:
        row = [QStandardItem(text)]
        row.extend(QStandardItem("") for _ in range(len(self.COLUMN_KEYS) - 1))
        for item in row:
            item.setEditable(False)
        return row

    def _item_row(self, item: Dict[str, Any], container_name: str) -> List[QStandardItem]:
        row: List[QStandardItem] = []
        for key, data_key in self.COLUMN_KEYS:
            value = self._column_value(item, key, data_key, container_name)
            cell = QStandardItem(value)
            cell.setEditable(False)
            row.append(cell)
        row[0].setData(item, Qt.ItemDataRole.UserRole)
        return row

    def eventFilter(self, watched, event):
        if watched is self.tree_view.viewport():
            event_type = event.type()
            if event_type == QEvent.Type.MouseMove:
                self._update_hover_card(event.position().toPoint())
            elif event_type in (QEvent.Type.Leave, QEvent.Type.Hide, QEvent.Type.Wheel):
                self._hide_hover_card()
            elif event_type == QEvent.Type.ToolTip:
                return True
        return super().eventFilter(watched, event)

    def _update_hover_card(self, pos):
        item = self._item_data_from_index(self.tree_view.indexAt(pos))
        if not item:
            self._hide_hover_card()
            return
        cache_key = self._hover_cache_key(item)
        if cache_key == self._hover_card_key and QToolTip.isVisible():
            return
        if cache_key == self._pending_hover_key and self._hover_timer.isActive():
            return

        self._hide_hover_card()
        self._pending_hover_key = cache_key
        self._pending_hover_item = item
        self._hover_timer.start()

    def _show_pending_hover_card(self):
        self._hover_timer.stop()
        item = self._pending_hover_item
        cache_key = self._pending_hover_key
        self._pending_hover_item = None
        self._pending_hover_key = None
        if not item or not cache_key:
            return

        global_pos = QCursor.pos()
        pos = self.tree_view.viewport().mapFromGlobal(global_pos)
        current_item = self._item_data_from_index(self.tree_view.indexAt(pos))
        if not current_item or self._hover_cache_key(current_item) != cache_key:
            return

        card = self._card_cache.get(cache_key)
        if card is None:
            card = (
                self._weapon_card_html(item)
                or self._equipment_card_html(item)
                or self._classmod_card_html(item)
                or self._enhancement_card_html(item)
            )
            self._card_cache[cache_key] = card
        if not card:
            return
        QToolTip.showText(global_pos, card, self.tree_view)
        for widget in QApplication.topLevelWidgets():
            if widget.windowType() == Qt.WindowType.ToolTip:
                widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._hover_card_key = cache_key

    def _hover_cache_key(self, item: Dict[str, Any]) -> tuple[str, ...]:
        return (
            self.current_lang,
            str(self.character_level or ""),
            str(item.get("serial") or item.get("decoded_full") or ""),
        )

    def _hide_hover_card(self):
        self._hover_timer.stop()
        self._pending_hover_key = None
        self._pending_hover_item = None
        self._hover_card_key = None
        QToolTip.hideText()
        for widget in QApplication.topLevelWidgets():
            if widget.windowType() == Qt.WindowType.ToolTip:
                widget.hide()

    def _weapon_card_html(self, item: Dict[str, Any]) -> str:
        return weapon_card_html(item, self.current_lang, self.loc["columns"]["level"], self.loc["columns"])

    def _equipment_card_html(self, item: Dict[str, Any]) -> str:
        return equipment_card_html(item, self.current_lang, self.loc["columns"]["level"], self.loc["columns"])

    def _classmod_card_html(self, item: Dict[str, Any]) -> str:
        return classmod_card_html(
            item,
            self.current_lang,
            self.loc["columns"]["level"],
            self.loc["columns"],
            self.character_level,
            4,
        )

    def _enhancement_card_html(self, item: Dict[str, Any]) -> str:
        return enhancement_card_html(item, self.current_lang, self.loc["columns"]["level"], self.loc["columns"])

    @staticmethod
    def _slot_sort_key(item: Dict[str, Any]):
        slot = str(item.get("slot", ""))
        if slot.startswith("slot_"):
            try:
                return (0, int(slot.removeprefix("slot_")))
            except ValueError:
                pass
        return (1, str(item.get("name", "")))

    def _column_value(self, item: Dict[str, Any], key: str, data_key: str, container_name: str) -> str:
        if key == "flags":
            return self._flag_display(item.get(data_key, ""))
        return str(item.get(data_key, "") or "")

    def _flag_display(self, flag: Any) -> str:
        text = self.loc.get("add_item", {}).get("flags", {}).get(str(flag), str(flag or ""))
        if "(" in text and ")" in text:
            return text.split("(", 1)[1].split(")", 1)[0]
        return text

    def _container_display(self, container_raw: Any) -> str:
        if not container_raw:
            return self.loc["defaults"]["unknown_container"]
        return self.loc.get("containers", {}).get(container_raw, str(container_raw))

    def _collapse_default_groups(self):
        containers_loc = self.loc.get("containers", {})
        collapsed_names = {
            containers_loc.get("Lost Loot", "Lost Loot"),
            containers_loc.get("Equipped", "Equipped"),
        }
        root = self.model.invisibleRootItem()
        for i in range(root.rowCount()):
            item = root.child(i)
            if item.text() in collapsed_names:
                self.tree_view.collapse(self.model.indexFromItem(item))

    def _resize_columns(self):
        header = self.tree_view.header()
        for i in range(self.model.columnCount()):
            key = self.COLUMN_KEYS[i][0]
            if key == "serial":
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
                self.tree_view.setColumnWidth(i, self.tree_view.fontMetrics().horizontalAdvance("0" * 20) + 20)
            elif key == "name":
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)

    def on_item_selected(self, selected, _deselected):
        indexes = selected.indexes()
        self.current_selected_item = self._item_data_from_index(indexes[0]) if indexes else None

    def select_item_by_path(self, original_path) -> bool:
        """按 YAML 原始路径定位并选中物品行（供 YAML 编辑器跳转）。返回是否找到。"""
        target = tuple(str(p) for p in (original_path or []))
        if not target:
            return False

        def walk(parent_item: QStandardItem) -> Optional[QModelIndex]:
            for row in range(parent_item.rowCount()):
                child = parent_item.child(row, 0)
                if child is None:
                    continue
                data = child.data(Qt.ItemDataRole.UserRole)
                if isinstance(data, dict):
                    item_path = tuple(str(p) for p in (data.get("original_path") or []))
                    if item_path == target:
                        return child.index()
                found = walk(child)
                if found is not None and found.isValid():
                    return found
            return None

        index = walk(self.model.invisibleRootItem())
        if index is None or not index.isValid():
            return False
        parent = index.parent()
        while parent.isValid():
            self.tree_view.expand(parent)
            parent = parent.parent()
        self.tree_view.setCurrentIndex(index)
        self.tree_view.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)
        return True

    def _item_data_from_index(self, index: QModelIndex) -> Optional[Dict[str, Any]]:
        cursor = index
        while cursor.isValid():
            data = self.model.data(cursor.siblingAtColumn(0), Qt.ItemDataRole.UserRole)
            if data:
                return data
            cursor = cursor.parent()
        return None

    def _show_context_menu(self, pos):
        item = self._item_data_from_index(self.tree_view.indexAt(pos))
        if not item:
            return

        actions = self.loc.get("actions", {})
        menu = QMenu(self)
        copy_name = menu.addAction(actions.get("copy_name", "Copy name"))
        copy_serial = menu.addAction(actions.get("copy_serial", "Copy serial"))
        copy_decoded = menu.addAction(actions.get("copy_decoded", "Copy decoded"))
        copy_parts = menu.addAction(actions.get("copy_parts", "Copy parts"))

        selected = menu.exec(self.tree_view.viewport().mapToGlobal(pos))
        if selected == copy_name:
            self._copy_text(item.get("name", ""))
        elif selected == copy_serial:
            self._copy_text(item.get("serial", ""))
        elif selected == copy_decoded:
            self._copy_text(item.get("decoded_full", ""))
        elif selected == copy_parts:
            self._copy_text(item.get("decoded_parts", ""))

    def _copy_text(self, text: Any):
        QApplication.clipboard().setText(str(text or ""))

    def _load_localization(self):
        filename = resource_loader.get_ui_localization_file(self.current_lang)
        data = resource_loader.load_json_resource(filename)
        if data and "items_tab" in data:
            self.loc = data["items_tab"]
            return

        self.loc = {
            "columns": {
                "name": "Name",
                "type": "Type",
                "manufacturer": "Manufacturer",
                "rarity": "Rarity",
                "level": "Level",
                "flags": "Flags",
                "damage": "Damage",
                "dps": "DPS",
                "accuracy": "Accuracy",
                "fire_rate": "Fire Rate",
                "reload_time": "Reload",
                "magazine": "Magazine",
                "critical_damage": "Critical Damage",
                "ammo_cost": "Ammo Cost",
                "splash_radius": "Splash Radius",
                "ads_time": "ADS Time",
                "equip_time": "Equip Time",
                "radius": "Blast Radius",
                "cooldown": "Cooldown",
                "charges": "Charges",
                "capacity": "Capacity",
                "recharge_delay": "Recharge Delay",
                "recharge_rate": "Recharge Rate",
                "armor_segments": "Armor Segments",
                "damage_reduction": "Damage Reduction",
                "healing": "Total Healing",
                "instant_healing": "Instant Healing",
                "health_over_time": "Healing Over Time",
                "duration": "Duration",
                "serial": "Serial",
            },
            "containers": {"Backpack": "Backpack", "Bank": "Bank", "Lost Loot": "Lost Loot", "Equipped": "Equipped"},
            "search_placeholder": "Search items...",
            "add_item": {
                "label_serial": "Serial:",
                "placeholder_serial": "Enter code...",
                "label_flag": "Flag:",
                "button_add": "Add",
                "flags": {"1": "1", "3": "3", "5": "5", "17": "17", "33": "33", "65": "65", "129": "129"},
            },
            "actions": {
                "copy_name": "Copy name",
                "copy_serial": "Copy serial",
                "copy_decoded": "Copy decoded",
                "copy_parts": "Copy parts",
            },
            "defaults": {"unknown_container": "Unknown", "unknown_type": "Unknown"},
            "dialogs": {"input_error": "Error", "enter_serial": "Enter serial"},
        }

    def update_language(self, lang):
        self._hide_hover_card()
        self.current_lang = lang
        self._load_localization()
        self._card_cache.clear()
        self.model.setHorizontalHeaderLabels(self._headers())
        self.ui_labels["label_serial"].setText(self.loc["add_item"]["label_serial"])
        self.ui_placeholders["add_serial"].setPlaceholderText(self.loc["add_item"]["placeholder_serial"])
        self.ui_labels["label_flag"].setText(self.loc["add_item"]["label_flag"])
        self.ui_buttons["button_add"].setText(self.loc["add_item"]["button_add"])
        self.search_entry.setPlaceholderText(self.loc["search_placeholder"])
        self._populate_flags()
        self._resize_columns()

    def _on_add_item_clicked(self):
        serial = self.add_serial_entry.text().strip()
        if not serial:
            QMessageBox.warning(self, self.loc["dialogs"]["input_error"], self.loc["dialogs"]["enter_serial"])
            return
        flag = self.add_flag_combo.currentText().split(" ")[0]
        self.add_item_requested.emit(serial, flag)

    def filter_tree(self, text: str):
        query = text.lower().strip()
        root = self.model.invisibleRootItem()

        for i in range(root.rowCount()):
            container_item = root.child(i)
            container_is_visible = False

            for j in range(container_item.rowCount()):
                type_item = container_item.child(j)
                type_is_visible = False

                for k in range(type_item.rowCount()):
                    haystack = self._row_search_text(type_item, k)
                    is_match = not query or query in haystack
                    self.tree_view.setRowHidden(k, type_item.index(), not is_match)
                    if is_match:
                        type_is_visible = True

                self.tree_view.setRowHidden(j, container_item.index(), not type_is_visible)
                if type_is_visible:
                    container_is_visible = True

            self.tree_view.setRowHidden(i, root.index(), not container_is_visible)

    def _row_search_text(self, parent: QStandardItem, row: int) -> str:
        values = []
        for col in range(self.model.columnCount()):
            child = parent.child(row, col)
            if child:
                values.append(child.text())
        data = parent.child(row, 0).data(Qt.ItemDataRole.UserRole) if parent.child(row, 0) else None
        if data:
            values.extend([data.get("serial", ""), data.get("decoded_full", ""), data.get("base_name", "")])
        return " ".join(str(value) for value in values).lower()
