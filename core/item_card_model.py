"""Item card model: the fields the game's own card shows, independent of rendering.

The game draws its item card from a data model (``$data`` in
``uiresources/item_card/item_card.html``): name, rarity, type label, level,
thumbnail, manufacturer, a headline (DPS / healing), primary and tertiary stat
boxes, an element row, augment rows (perks with an icon), class mod skills,
enhancement core stats, firmware, red text and the manufacturer footer. This
module computes the same fields from a save item so the QML ``ItemCard`` can
lay them out like the game (``core/data/item_card_theme.json`` holds the colours).

Card budgets that keep modded gear from blowing the card up are kept from the
previous HTML cards: one pearl + one legendary + 3-4 normal augments, four class
mod skills (then "... ... ..."), three class mod perks, one red text.

Paths are relative to the resource root (``assets/...``, ``class_mods/...``) so
the QML side can resolve them and the tint provider can load them.
"""

from __future__ import annotations

import re
from functools import lru_cache
from html import escape
from typing import Any

from core import item_display_resolver, resource_loader
from core.item_card_data import (
    CLASSMOD_PORTRAITS,
    EQUIPMENT_CARD_FIELDS,
    FIRMWARE_ICON_ALIASES,
    GRENADE_CARD_TYPE_ICONS,
    RARITY_HEADER_KEYS,
    WEAPON_CARD_PRIMARY_STATS,
    WEAPON_CARD_SECONDARY_ICONS,
    WEAPON_CARD_TYPE_ICONS,
    _element_card_text,
    _manufacturer_card_key,
    _repkit_element_card_modes,
    _repkit_element_card_text,
    _secondary_stat_keys,
    _weapon_card_details,
)

UI_ASSETS = "assets/item_card/game"
CLASSMOD_SKILL_LIMIT = 4
CLASSMOD_PERK_LIMIT = 3
ELEMENT_ALIASES = {"electric": "shock", "incendiary": "fire"}


@lru_cache(maxsize=1)
def theme() -> dict[str, Any]:
    return resource_loader.load_json_resource("core/data/item_card_theme.json") or {}


def rarity_key(rarity: Any) -> str:
    return RARITY_HEADER_KEYS.get(str(rarity or "").strip().casefold(), "common")


def _zh(lang: str) -> bool:
    return str(lang).lower().startswith("zh")


def _ui_asset(name: str) -> str:
    """Relative path of an exported card texture, or "" when it is missing."""
    rel = f"{UI_ASSETS}/{name}"
    return rel if name and resource_loader.get_resource_path(rel).exists() else ""


def _existing(rel: str) -> str:
    return rel if rel and resource_loader.get_resource_path(rel).exists() else ""


# --------------------------------------------------------------------------- #
# markup -> QML StyledText
# --------------------------------------------------------------------------- #
_TAG_RE = re.compile(r"\[(/?)([A-Za-z][A-Za-z0-9_]*)\]")


def markup_to_styled(text: Any, icon_px: int = 18) -> str:
    """Game markup (``[secondary]x[/secondary]``, ``[shock_icon]``) as QML StyledText.

    Colours and inline icons come from the game's ``oak_markup.css`` (theme);
    unknown tags are dropped, ``{placeholders}`` without a value show as ``?``.
    """
    colors = theme().get("markup_colors") or {}
    icons = theme().get("markup_icons") or {}
    raw = re.sub(r"\[glyph\].*?\[/glyph\]", "", str(text or ""), flags=re.IGNORECASE | re.S)
    raw = re.sub(r"\{[A-Za-z0-9_]+\}", "?", raw)
    out: list[str] = []
    open_tags: list[str] = []
    cursor = 0
    for match in _TAG_RE.finditer(raw):
        out.append(escape(raw[cursor:match.start()]).replace("\n", "<br>"))
        cursor = match.end()
        closing, tag = match.group(1) == "/", match.group(2).lower()
        if tag == "newline":
            out.append("<br>")
        elif tag in icons and not closing:
            path = _ui_asset(str(icons[tag].get("file") or ""))
            if path:
                uri = resource_loader.get_resource_path(path).as_uri()
                out.append(f'<img src="{uri}" width="{icon_px}" height="{icon_px}" align="middle">')
        elif tag in colors:
            if closing:
                if tag in open_tags:
                    out.append("</font>")
                    open_tags.remove(tag)
            else:
                out.append(f'<font color="{colors[tag]}">')
                open_tags.append(tag)
    out.append(escape(raw[cursor:]).replace("\n", "<br>"))
    out.extend("</font>" for _ in open_tags)
    return " ".join("".join(out).split()).replace(" <br> ", "<br>")


# --------------------------------------------------------------------------- #
# shared pieces
# --------------------------------------------------------------------------- #
def _base(item: dict[str, Any], lang: str, level_label: str, kind: str) -> dict[str, Any]:
    level = str(item.get("level") or "").strip()
    return {
        "kind": kind,
        "item_type": str(item.get("type_en") or ""),
        "rarity": rarity_key(item.get("rarity")),
        "name": str(item.get("name") or "-"),
        "type_label": str(item.get("type") or ""),
        "level_text": (f"{level}级" if _zh(lang) else f"{level_label} {level}") if level else "",
        "manufacturer": _manufacturer_card_key(item),
        "thumbnail": "",
        "thumbnail_kind": kind,
        "headline": None,
        "primary": [],
        "tertiary": [],
        "element": None,
        "augments": [],
        "classmod": None,
        "enhancement": None,
        "firmware": None,
        "red_text": "",
    }


def _stat(icon: str, value: Any) -> dict[str, str]:
    return {"icon": _existing(f"assets/item_card/stats/{icon}"), "value": str(value or "-")}


def _element_row(text: str, keys: list[Any], primary: str) -> dict[str, Any] | None:
    elements = theme().get("elements") or {}
    primary = ELEMENT_ALIASES.get(primary, primary)
    if not text or primary not in elements or primary == "kinetic":
        return None
    icons = []
    for key in dict.fromkeys(ELEMENT_ALIASES.get(str(k), str(k)) for k in keys if k):
        if key in elements and key != "kinetic" and (icon := _ui_asset(elements[key].get("icon", ""))):
            icons.append(icon)
    return {"key": primary, "text": text, "color": elements[primary].get("color", "#e4d9ce"),
            "backing": _ui_asset(elements[primary].get("backing", "")) or _ui_asset("item_card_element_backing.png"),
            "icons": icons[:2] or [_ui_asset(elements[primary].get("icon", ""))]}


def _augment(entry: dict[str, Any], icon_px: int) -> dict[str, Any]:
    return {
        "icon": _effect_icon(entry.get("icon_asset", "")),
        "kind": str(entry.get("display_kind") or "normal"),
        "text": markup_to_styled(entry.get("markup") or entry.get("text"), icon_px),
    }


def _effect_icon(asset: Any) -> str:
    package = str(asset or "").split(".", 1)[0]
    name = f"{package.rsplit('/', 1)[-1]}.png" if package else ""
    return _existing(f"assets/item_card/effects/{name}") if name else ""


def _firmware(entries: list[dict[str, Any]], lang: str) -> dict[str, Any] | None:
    if not entries:
        return None
    entry = entries[0]
    raw = str(entry.get("name") or entry.get("text") or "")
    name = re.sub(r"\s*[-–]\s*(?:Firmware|固件)\s*$", "", raw, flags=re.IGNORECASE).strip()
    stem = str(entry.get("internal") or "").casefold().removeprefix("part_firmware_")
    stem = FIRMWARE_ICON_ALIASES.get(stem, stem)
    icon = _ui_asset(f"ico_firmware_{stem}_big.png") or _existing(f"assets/item_card/extra/ico_firmware_{stem}_big.png")
    level = max(0, min(3, int(entry.get("level") or 0)))
    return {"name": name or ("技能工艺" if _zh(lang) else "Skillcraft"), "icon": icon,
            "level": level, "count_text": f"{level}/3"}


def _headline(value: str, zh_label: str, en_label: str, lang: str) -> dict[str, str] | None:
    return {"value": value, "label": zh_label if _zh(lang) else en_label} if value else None


# --------------------------------------------------------------------------- #
# builders
# --------------------------------------------------------------------------- #
def _weapon(item: dict[str, Any], lang: str, level_label: str, icon_px: int) -> dict[str, Any] | None:
    stats = item.get("weapon_stats") or {}
    icon = WEAPON_CARD_TYPE_ICONS.get(item.get("type_en", ""))
    if not stats or not icon:
        return None
    card = _base(item, lang, level_label, "weapon")
    card["thumbnail"] = _existing(f"assets/item_card/types/{icon}")
    card["thumbnail_kind"] = "pistol" if item.get("type_en") == "Pistol" else "weapon"

    def value(key: str) -> str:
        return item_display_resolver.format_weapon_stat(key, stats.get(key), lang) or "-"

    card["primary"] = [_stat(icon_file, value(key)) for key, icon_file in WEAPON_CARD_PRIMARY_STATS]
    card["tertiary"] = [_stat(WEAPON_CARD_SECONDARY_ICONS[key], value(key)) for key in _secondary_stat_keys(stats)]
    card["headline"] = _headline(item_display_resolver.format_weapon_stat("dps", stats.get("dps"), lang),
                                 "伤害输出", "Damage Output", lang)
    details = _weapon_card_details(str(item.get("decoded_full") or ""), stats, lang)
    card["augments"] = [_augment(entry, icon_px) for entry in details.get("display_entries", details["entries"])]
    suffix = "_mode02" if stats.get("element_mode02") else ""
    element = str(stats.get("element_mode02") or stats.get("element") or details.get("element") or "")
    card["element"] = _element_row(_element_card_text(stats, element, lang, suffix),
                                   [*(details.get("elements") or []), stats.get("element"), stats.get("element_mode02")],
                                   element)
    card["red_text"] = next(iter(details.get("display_red_texts") or details.get("red_texts") or []), "")
    return card


def _equipment(item: dict[str, Any], lang: str, level_label: str, icon_px: int) -> dict[str, Any] | None:
    stats = item.get("equipment_stats") or {}
    item_type = item.get("type_en", "")
    fields = EQUIPMENT_CARD_FIELDS.get(item_type)
    if not stats or not fields:
        return None
    card = _base(item, lang, level_label, {"Grenade": "grenade", "Shield": "shield", "Repkit": "repkit"}.get(item_type, "heavy"))
    if item_type == "Grenade":
        manufacturer = str(item.get("manufacturer_en") or item.get("manufacturer") or "").casefold()
        icon = next((file for name, file in GRENADE_CARD_TYPE_ICONS.items() if name in manufacturer),
                    "ico_art_item_card_grenade_torgue.png")
    elif item_type == "Shield":
        icon = ("ico_art_item_card_armor_shield.png" if stats.get("armor_segments") not in (None, "", 0, 0.0)
                else "ico_art_item_card_energy_shield.png")
    elif item_type == "Repkit":
        icon = "ico_art_item_card_rep_kit.png"
    else:
        icon = "ico_art_item_card_heavy_weapon_generic.png"
    card["thumbnail"] = _existing(f"assets/item_card/types/{icon}")

    def value(key: str, raw: Any) -> str:
        try:
            formatted = item_display_resolver.format_equipment_stat(key, raw, lang)
        except (TypeError, ValueError, OverflowError):
            formatted = ""
        if formatted and key == "health_over_time" and stats.get("duration") not in (None, ""):
            duration = item_display_resolver.format_equipment_stat("duration", stats["duration"], lang)
            return f"{formatted}{'，持续' if _zh(lang) else ', '}{duration}"
        return str(formatted or raw)

    visible = [(key, icon_file, stats[key]) for key, icon_file in fields if stats.get(key) not in (None, "")]
    dps = stats.get("dps") if item_type == "Heavy Weapon" else None
    healing = stats.get("healing") if item_type == "Repkit" else None
    if not visible and dps in (None, "") and healing in (None, ""):
        return None
    first = {"Grenade": 4, "Shield": 3, "Repkit": 3, "Heavy Weapon": 5}[item_type]
    card["primary"] = [_stat(icon_file, value(key, raw)) for key, icon_file, raw in visible[:first]]
    card["tertiary"] = [_stat(icon_file, value(key, raw)) for key, icon_file, raw in visible[first:]]
    if dps not in (None, ""):
        card["headline"] = _headline(value("dps", dps), "伤害输出", "Damage Output", lang)
    elif healing not in (None, ""):
        card["headline"] = _headline(value("healing", healing), "治疗", "Healing", lang)

    details = item_display_resolver.resolve_equipment_card_details(str(item.get("decoded_full") or ""), item_type, lang)
    entries = list(details.get("entries", []))
    charges = stats.get("charges")
    if item_type == "Repkit" and isinstance(charges, (int, float)) and charges > 1:
        manufacturer = str(item.get("manufacturer") or "")
        text = (f"[secondary]{manufacturer}[/secondary] - 该修复套件拥有[secondary]{int(charges)}[/secondary]个能量点"
                if _zh(lang) else
                f"[secondary]{manufacturer}[/secondary] - This Repkit has [secondary]{int(charges)}[/secondary] charges")
        if not any("能量点" in str(e.get("text")) or "charges" in str(e.get("text")).casefold() for e in entries):
            entries.append({"text": text, "markup": text, "icon_asset": "", "display_kind": "normal"})
    card["augments"] = [_augment(entry, icon_px) for entry in item_display_resolver.limit_item_card_entries(entries)]

    element_key = str(details.get("element") or "")
    if item_type == "Repkit":
        modes = _repkit_element_card_modes(element_key, details.get("entries", []))
        keys = [key for key, _mode in modes]
        text = _repkit_element_card_text(element_key, details.get("entries", []), lang)
        primary = keys[0] if keys else element_key
    else:
        keys, primary = [element_key], element_key
        text = str(details.get("element_text") or "") or _element_card_text(stats, element_key, lang)
    card["element"] = _element_row(text, keys, primary)
    card["firmware"] = _firmware(details.get("firmware", []), lang)
    card["red_text"] = next(iter(details.get("display_red_texts") or details.get("red_texts") or []), "")
    return card


def _skill_description(text: Any, icon_px: int) -> str:
    paragraphs = re.split(r"(?:\s*\[newline\]\s*){2,}|\n\s*\n", str(text or ""), maxsplit=1, flags=re.IGNORECASE)
    rendered = markup_to_styled(paragraphs[0].strip(), icon_px)
    if len(paragraphs) > 1:
        rendered += f' <font color="{(theme().get("markup_colors") or {}).get("primary", "#eb7300")}">... ... ...</font>'
    return rendered


def _classmod(item: dict[str, Any], lang: str, level_label: str, icon_px: int,
              character_level: int | None) -> dict[str, Any] | None:
    if item.get("type_en") != "Class Mod":
        return None
    details = item_display_resolver.resolve_classmod_card_details(
        str(item.get("decoded_full") or ""), lang, CLASSMOD_SKILL_LIMIT, character_level)
    if not details:
        return None
    card = _base(item, lang, level_label, "classmod")
    class_name = str(details.get("class_name") or item.get("manufacturer_en") or "")
    portrait = CLASSMOD_PORTRAITS.get(class_name, "")
    card["thumbnail"] = _existing(f"assets/item_card/extra/{portrait}") if portrait else ""
    skills = []
    for skill in details.get("skills", [])[:CLASSMOD_SKILL_LIMIT]:
        tree = str(skill.get("tree_color") or "").casefold()
        icon = resource_loader.get_class_mods_image_path(class_name, str(skill.get("icon_file") or ""))
        stats = [line.get("text", "") if isinstance(line, dict) else line
                 for line in (skill.get("stat_lines") or skill.get("stats") or [])]
        skills.append({
            "name": str(skill.get("name") or ""),
            "tree": tree if tree in ("red", "blue", "green") else "blue",
            "tree_name": str(skill.get("tree_name") or ""),
            "icon": f"data/class_mods/{class_name}/{skill.get('icon_file')}" if icon and icon.exists() else "",
            "points": f"+{int(skill.get('points') or 0)}/{int(skill.get('max_points') or 0)}",
            "text": _skill_description(skill.get("description"), icon_px),
            "stats": " · ".join(markup_to_styled(line, icon_px) for line in stats if line),
        })
    card["classmod"] = {
        "class_name": class_name,
        "skills": skills,
        "omitted": int(details.get("omitted_skills") or 0),
        "effects": [markup_to_styled(entry.get("text"), icon_px) for entry in details.get("effects", [])],
        "perks": [{"text": escape(str(perk.get("name") or "")), "count": int(perk.get("count") or 1)}
                  for perk in details.get("perks", [])[:CLASSMOD_PERK_LIMIT]],
    }
    card["firmware"] = _firmware(details.get("firmware", []), lang)
    card["red_text"] = next(iter(details.get("red_texts") or []), "")
    return card


def _enhancement(item: dict[str, Any], lang: str, level_label: str, icon_px: int) -> dict[str, Any] | None:
    if item.get("type_en") != "Enhancement":
        return None
    details = item_display_resolver.resolve_enhancement_card_details(str(item.get("decoded_full") or ""), lang)
    if not details:
        return None
    card = _base(item, lang, level_label, "enhancement")
    card["thumbnail"] = _existing("assets/item_card/types/ico_art_item_card_enhancement.png")
    colors = theme().get("markup_colors") or {}
    core = []
    for entry in details.get("display_effects", [*details.get("effects", []), *details.get("stacked_effects", [])]):
        text = str(entry.get("text") or "")
        title, sep, rest = text.partition(" -")
        rendered = (f'<font color="{colors.get("secondary", "#2d95ca")}">{escape(title)}</font>'
                    + (f"{escape(sep + rest)}" if sep else ""))
        count = int(entry.get("count") or 1)
        if count > 1:
            rendered += f' <font color="{colors.get("secondary", "#2d95ca")}">×{count}</font>'
        core.append(rendered)
    card["enhancement"] = {
        "core": core,
        "stats": [escape(str(entry.get("text") or "")) for entry in details.get("display_stats", details.get("stats", []))],
    }
    card["firmware"] = _firmware(details.get("firmware", []), lang)
    card["red_text"] = next(iter(details.get("red_texts") or []), "")
    return card


def item_from_report(report: dict[str, Any]) -> dict[str, Any]:
    """Adapt a ``serial_inspect.inspect_serial`` report to the item dict ``build_card`` reads.

    The builders read the same keys as ``ProcessedItem``; the inspector has no
    save context, so container/slot are left blank.
    """
    return {
        "name": report.get("display_name") or "",
        "type": report.get("type") or "",
        "type_en": report.get("type_en") or "",
        "container": "",
        "slot": "",
        "manufacturer": report.get("manufacturer") or "",
        "manufacturer_en": report.get("manufacturer_en") or "",
        "id": report.get("item_id"),
        "level": report.get("level"),
        "serial": report.get("base85") or "",
        "decoded_full": report.get("decoded_full") or "",
        "decoded_parts": report.get("decoded_parts") or "",
        "rarity": report.get("rarity") or "",
        "weapon_stats": report.get("weapon_stats") or {},
        "equipment_stats": report.get("equipment_stats") or {},
    }


def build_card(item: dict[str, Any], lang: str = "zh-CN", level_label: str = "Lv",
               character_level: int | None = None, icon_px: int = 18) -> dict[str, Any] | None:
    """Card model for a processed save item, or None when the item has no card."""
    for builder in (_weapon, _equipment):
        try:
            card = builder(item, lang, level_label, icon_px)
        except Exception:  # a broken item must never take the list down
            card = None
        if card:
            return card
    try:
        return (_classmod(item, lang, level_label, icon_px, character_level)
                or _enhancement(item, lang, level_label, icon_px))
    except Exception:
        return None
