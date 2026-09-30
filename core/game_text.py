"""Pick game text (item names, perks, manufacturers ...) for the UI language.

Game text is stored per text language: ``{"en": ..., "zh": ..., "ru": ..., "de": ...}``
in the JSON data and ``<base>_EN/_ZH/_RU/_DE`` columns in the CSV data. The
update pipeline (``localize-saveeditor``) fills Russian and German from the
game's own localization, keyed by the reviewed English/Chinese pair.

Missing text falls back to English: the game shows English wherever its own
table has no entry, and Ukrainian has no game localization at all, so game text
stays English there while the interface is Ukrainian.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Mapping

from . import resource_loader

#: UI language -> game text language
TEXT_LANGS = {"zh-CN": "zh", "en-US": "en", "ru": "ru", "de": "de", "ua": "en"}
TERMS_FILE = "data/i18n/game_terms.json"

#: Spellings the data uses for a game term (element "Fire" is "Incendiary" ...).
TERM_ALIASES = {
    "fire": "Incendiary", "pearl": "Pearlescent", "sniper": "Sniper Rifle",
    "ar": "Assault Rifle", "cov": "CoV", "the order": "Order", "c4sh": "C4SH",
}


def text_lang(lang: object) -> str:
    """Game text language for a UI language (``zh``/``en``/``ru``/``de``)."""
    return TEXT_LANGS.get(str(lang), "en")


def is_chinese(lang: object) -> bool:
    return text_lang(lang) == "zh"


def pick(mapping: Any, lang: object, fallback: str = "") -> str:
    """Localized value of a ``{"en", "zh", "ru", "de"}`` mapping."""
    if not isinstance(mapping, Mapping):
        return str(mapping) if mapping not in (None, "") else fallback
    code = text_lang(lang)
    for key in (code, "en", "zh"):
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return fallback


def pick_field(mapping: Mapping[str, Any], base: str, lang: object, fallback: str = "") -> str:
    """``base_<lang>`` of a flat mapping (``name_en``/``name_zh``/``name_ru`` ...)."""
    code = text_lang(lang)
    for suffix in (code, "en", "zh"):
        for key in (f"{base}_{suffix}", f"{base}_{suffix.upper()}"):
            value = mapping.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return fallback


def csv_text(row: Mapping[str, Any], base: str, lang: object, fallback: str = "") -> str:
    """Localized cell of a CSV row with ``<base>_EN/_ZH/_RU/_DE`` columns."""
    code = text_lang(lang).upper()
    for suffix in (code, "EN", "ZH"):
        value = row.get(f"{base}_{suffix}")
        if isinstance(value, str) and value.strip() and value.strip().lower() != "nan":
            return value
    return fallback


def csv_column(base: str, lang: object) -> str:
    """Column name holding ``base`` in the given language."""
    return f"{base}_{text_lang(lang).upper()}"


@lru_cache(maxsize=1)
def terms() -> dict[str, dict[str, dict[str, str]]]:
    data = resource_loader.load_json_resource(TERMS_FILE) or {}
    return {kind: value for kind, value in data.items() if isinstance(value, dict)}


@lru_cache(maxsize=1)
def _term_index() -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for kind in ("manufacturer", "rarity", "item_type", "element"):
        for english, entry in terms().get(kind, {}).items():
            index.setdefault(english.casefold(), entry)
    return index


def term_entry(value: object) -> dict[str, str] | None:
    key = str(value or "").strip().casefold()
    if not key:
        return None
    index = _term_index()
    return index.get(key) or index.get(TERM_ALIASES.get(key, "").casefold())


def term(value: object, lang: object, default: str | None = None) -> str:
    """Localized manufacturer, rarity, item type or element; else ``default``/value.

    English keeps the data's own spelling ("Sniper", "Pearl"), as it always has.
    """
    entry = term_entry(value)
    if entry:
        return str(value) if text_lang(lang) == "en" else pick(entry, lang, str(value))
    return str(value) if default is None else default


def character(name: object, lang: object) -> str:
    """Display name of a playable character.

    Chinese has always shown the class title (锻造骑士 for Amon); the other
    languages show the character's own name as the game spells it.
    """
    key = str(name or "").strip()
    wanted = TERM_ALIASES.get(key.casefold(), key)
    for english in terms().get("character", {}):
        if english.casefold() == wanted.casefold():
            if is_chinese(lang):
                return pick(terms().get("class", {}).get(english), lang, key)
            return pick(terms()["character"][english], lang, key)
    return key


@lru_cache(maxsize=1)
def _english_index() -> dict[str, str]:
    """Any language's spelling of a term -> its English key (for colour/icon lookups)."""
    index: dict[str, str] = {}
    for kind in ("manufacturer", "rarity", "item_type", "element"):
        for english, entry in terms().get(kind, {}).items():
            for text in (english, *entry.values()):
                index.setdefault(str(text).strip().casefold(), english)
    return index


def english_term(value: object) -> str:
    """English key of a manufacturer/rarity/type/element written in any language."""
    key = str(value or "").strip().casefold()
    entry = term_entry(key)
    if entry:
        return entry.get("en", str(value))
    return _english_index().get(key, str(value or ""))


def localize_label(value: object, lang: object) -> str:
    """Term or character name, else the value unchanged."""
    text = str(value or "")
    localized = term(text, lang, default="")
    if localized:
        return localized
    return character(text, lang)


def frame_column(frame: Any, lang: object, columns: Mapping[str, str]) -> Any:
    """Series of ``columns[<text language>]`` with English cells filling the gaps.

    ``columns`` maps a text language to its column (``{"en": "Stat", "zh": "Stat_ZH",
    "ru": "Stat_RU", "de": "Stat_DE"}``); the weapon tables predate the
    ``<base>_<LANG>`` naming, so each caller names its own columns.
    """
    english = frame[columns["en"]] if columns.get("en") in frame.columns else None
    column = columns.get(text_lang(lang))
    if column not in frame.columns:
        return english
    values = frame[column]
    if english is None or column == columns["en"]:
        return values
    filled = values.notna() & (values.astype(str).str.strip() != "")
    return values.where(filled, english)
