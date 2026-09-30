"""Interface text for core modules (item card lines, legality badges ...).

Reads the same catalogs as the QML ``Localizer``: ``ui_localization*.json``
per language plus the multi-language files in ``EXTRA_CATALOGS`` (one section
per language, deep-merged over the main file). Core modules have no Localizer,
so they look text up here by dot path and UI language.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from . import resource_loader

DEFAULT_LANGUAGE = "zh-CN"
#: Every UI language code (ui_huskar.i18n.LANGUAGES carries their display names).
UI_LANGUAGES = ("zh-CN", "en-US", "ru", "ua", "de")
#: Multi-language catalogs merged over the per-language files:
#: ``{"zh-CN": {...}, "en-US": {...}, "ru": {...}, "ua": {...}, "de": {...}}``.
EXTRA_CATALOGS = ("data/i18n/game_progress.json", "data/i18n/ui_text.json")


def deep_merge(target: dict[str, Any], extra: dict[str, Any]) -> None:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_merge(target[key], value)
        else:
            target[key] = value


@lru_cache(maxsize=None)
def _catalog(lang: str) -> dict[str, Any]:
    data = resource_loader.load_json_resource(resource_loader.get_ui_localization_file(lang)) or {}
    data = dict(data)
    for name in EXTRA_CATALOGS:
        extra = resource_loader.load_json_resource(name) or {}
        deep_merge(data, extra.get(lang) or {})
    return data


def catalog(lang: str) -> dict[str, Any]:
    """Merged catalog for one UI language (cached; treat as read-only)."""
    return _catalog(str(lang))


def lookup(data: dict[str, Any], path: str) -> Any:
    node: Any = data
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def tr(path: str, lang: object, *args: Any, default: str | None = None, **kwargs: Any) -> str:
    """Text at ``path`` for ``lang``, then English, then ``default``/``path``."""
    value: Any = None
    for code in (str(lang), "en-US"):
        value = lookup(catalog(code), path)
        if isinstance(value, str):
            break
    if not isinstance(value, str):
        return default if default is not None else path
    if args or kwargs:
        try:
            return value.format(*args, **kwargs)
        except (KeyError, IndexError, ValueError):
            return value
    return value


def section(path: str, lang: object) -> dict[str, Any]:
    value = lookup(catalog(str(lang)), path)
    if isinstance(value, dict):
        return value
    value = lookup(catalog("en-US"), path)
    return value if isinstance(value, dict) else {}
