"""QML 前端的本地化支持。

复用主线 i18n/ui_localization*.json 资源，按点路径取词（如 "main_window.tabs.items"）。
缺失键回退到中文资源，再回退到键名本身，保证任何语言下界面不出现空白。
"""

from __future__ import annotations

from typing import Any

from core import resource_loader

LANGUAGES = (
    ("zh-CN", "中文"),
    ("en-US", "English"),
    ("ru", "Русский"),
    ("ua", "Українська"),
)
DEFAULT_LANGUAGE = "zh-CN"
_LANGUAGE_ALIASES = {
    "zh": "zh-CN",
    "zh_cn": "zh-CN",
    "zh-cn": "zh-CN",
    "en": "en-US",
    "en_us": "en-US",
    "en-us": "en-US",
    "english": "en-US",
    "ru-ru": "ru",
    "uk": "ua",
    "uk-ua": "ua",
    "ua-ua": "ua",
}


def normalize_language(lang: object) -> str:
    """Return one of the canonical UI language codes.

    Older QWidget settings and some platform locale providers may leave
    aliases such as ``en`` or ``en_US`` in QSettings. Treat those as aliases
    instead of silently selecting the Chinese fallback catalog.
    """
    raw = str(lang or "").strip()
    if raw in dict(LANGUAGES):
        return raw
    return _LANGUAGE_ALIASES.get(raw.casefold(), DEFAULT_LANGUAGE)


class Localizer:
    def __init__(self, lang: str = DEFAULT_LANGUAGE):
        self.lang = normalize_language(lang)
        self._data: dict[str, Any] = {}
        self._fallback: dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        self._data = resource_loader.load_json_resource(
            resource_loader.get_ui_localization_file(self.lang)
        ) or {}
        self._fallback = resource_loader.load_json_resource(
            resource_loader.get_ui_localization_file(DEFAULT_LANGUAGE)
        ) or {}

    def set_language(self, lang: str) -> None:
        lang = normalize_language(lang)
        if lang not in dict(LANGUAGES):
            return
        self.lang = lang
        self.reload()

    def section(self, path: str) -> dict[str, Any]:
        value = self._lookup(self._data, path)
        if isinstance(value, dict):
            return value
        value = self._lookup(self._fallback, path)
        return value if isinstance(value, dict) else {}

    def tr(self, path: str, *args: Any, **kwargs: Any) -> str:
        default = kwargs.pop("default", None)
        value: Any = self._lookup(self._data, path)
        if not isinstance(value, str):
            value = self._lookup(self._fallback, path)
        if not isinstance(value, str):
            return default if isinstance(default, str) else path
        if args or kwargs:
            try:
                return value.format(*args, **kwargs)
            except (KeyError, IndexError, ValueError):
                return value
        return value

    @staticmethod
    def _lookup(data: dict[str, Any], path: str) -> Any:
        node: Any = data
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node
