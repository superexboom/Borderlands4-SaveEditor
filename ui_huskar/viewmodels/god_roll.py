"""God Roll 优化器 VM：移植 QtGodRollTab 的全部非渲染逻辑。"""

from __future__ import annotations

import threading
from typing import Any

from PyQt6.QtCore import QObject, QThread, pyqtProperty, pyqtSignal, pyqtSlot

from core import item_display_resolver, lookup, resource_loader, serial_inspect
from core.weapon_optimizer import AUTO, ELEMENT_GROUPS, NONE, GodRollRequest, WeaponGodRollOptimizer
from tabs import qt_items_tab

from .base import PageViewModel, register

_FLAG_CODE_ORDER = ("1", "3", "5", "17", "33", "65", "129")
_RARITY_ORDER = ("Common", "Uncommon", "Rare", "Epic", "Legendary", "Pearl")
# 结果列表行的关键属性列（对齐旧版 WeaponRollResultsPage._STAT_KEYS）
_LIST_STAT_KEYS = ("damage", "dps", "accuracy", "fire_rate", "reload_time", "magazine")
_TYPE_KEYS = {
    "Assault Rifle": "assault_rifle", "Pistol": "pistol", "Shotgun": "shotgun",
    "SMG": "smg", "Sniper": "sniper",
}
_GROUP_KEYS = {
    "inv_comp": "rarity", "body": "body", "body_acc": "body_accessory",
    "body_mech": "body_mechanism", "barrel": "barrel", "barrel_acc": "barrel_accessory",
    "magazine": "magazine", "magazine_acc": "manufacturer_part",
    "magazine_ted_thrown": "tediore_payload", "scope": "scope",
    "scope_acc": "scope_accessory", "grip": "grip", "foregrip": "foregrip",
    "underbarrel": "underbarrel", "underbarrel_acc": "underbarrel_accessory",
    "body_ele": "element", "secondary_ele": "element_switch",
    "pearl_elem": "pearl_elements", "pearl_stat": "pearl_stat",
}
_ELEMENT_NAMES = {
    "corrosive": {"zh-CN": "腐蚀", "en-US": "Corrosive"},
    "cryo": {"zh-CN": "冰冻", "en-US": "Cryo"},
    "fire": {"zh-CN": "火焰", "en-US": "Fire"},
    "incendiary": {"zh-CN": "火焰", "en-US": "Fire"},
    "radiation": {"zh-CN": "辐射", "en-US": "Radiation"},
    "shock": {"zh-CN": "电击", "en-US": "Shock"},
    "normal": {"zh-CN": "无元素", "en-US": "No Element"},
}
_EFFORTS = {"fast": (7_500, 3.0), "balanced": (25_000, 8.0), "deep": (150_000, 30.0)}

_FALLBACK = {
    "title": "God Roll Optimizer", "source": "Target weapon", "manufacturer": "Manufacturer",
    "weapon_type": "Weapon Type", "rarity": "Rarity", "weapon": "Weapon", "mode": "Mode",
    "legal": "Legal build", "unrestricted": "Cross-manufacturer", "level": "Level",
    "barrel": "Fixed barrel", "torgue": "Torgue requirement", "torgue_any": "No requirement",
    "torgue_sticky": "Must include sticky", "torgue_impact": "Must include impact/normal",
    "base_element": "Base element", "secondary_element": "Dual/secondary element",
    "pearl_element": "Pearl override", "auto": "Auto optimize",
    "auto_available": "Auto optimize (candidate available, not guaranteed)",
    "unavailable": "Unavailable for this weapon", "none": "No element",
    "force_element": "Allow forced illegal element",
    "force_hint": "The result is marked modified when only the element violates the native build rules.",
    "score_note": "Ranking uses a paper stat model; red-text, ricochet, and delayed sticky mechanics are not fully modeled.",
    "score_profile": "Score profile", "score_profile_sustained_dps": "Sustained DPS",
    "score_profile_burst": "Burst Damage", "score_profile_crit_element": "Crit / Element",
    "score_profile_balanced": "Balanced", "score_explanation": "Score explanation",
    "score_total": "Score", "score_short": "Score", "score_metric_dps": "Sustained DPS",
    "score_metric_damage": "Damage", "score_metric_fire_rate": "Fire Rate",
    "score_metric_magazine": "Magazine", "score_metric_critical_damage": "Critical Damage",
    "score_metric_elemental_dps": "Elemental DPS", "score_metric_reload_time": "Reload",
    "score_warning": "Paper score; red text, ricochet, and delayed sticky mechanics are not modeled.",
    "score_missing": "Unavailable metrics: {metrics}", "open_editor": "Open in Weapon Editor",
    "limits": "Unrestricted group limits", "group": "Group", "pool": "Pool",
    "minimum": "Min", "maximum": "Max", "effort": "Search budget",
    "fast": "Fast (3 seconds)", "balanced": "Balanced (8 seconds)", "deep": "Deep (30 seconds)",
    "top_n": "Results", "search": "Find God Rolls", "cancel": "Cancel",
    "idle": "Choose a target and start searching.",
    "running": "Explored {attempted} · valid {accepted} · best score {best}",
    "done": "Found {count} builds from {attempted} attempts in {elapsed:.1f}s. Budget-best; global optimum is not yet proven.",
    "done_exact": "Exhausted {frontier} legal builds in {elapsed:.1f}s and proved the Top {count}.",
    "cancelled": "Search cancelled; showing the best results found so far.",
    "no_results": "No build matched the selected constraints.",
    "error": "God Roll search failed: {error}",
    "offline_only": "God Roll generation is an offline save feature.",
    "select_flag": "Flag", "add_start": "Adding {count} item(s)...",
    "add_done": "Added {success}; failed {fail}",
    "results_scope": "{mode} · {profile} · fixed barrel {barrel} · budget-best Top {count}",
    "results_scope_exact": "{mode} · {profile} · fixed barrel {barrel} · proven Top {count}",
    "parts_title": "Part Details", "no_part_details": "No part details",
    "effects_title": "Skills",
    "no_part_effect": "No stat changes", "source_current": "Current weapon",
    "source_universal": "Universal pool", "status_element_modified": "Element-only Modified",
    "generated": "Generated {count} legal weapons", "select_result": "Select a generated weapon",
    "no_element": "No Element", "level_value": "Lv{level}", "close": "Close",
    "add_one": "Add This", "add_all": "Add All", "copy_base85": "Copy Base85",
    "copied": "Base85 copied", "back": "Back",
}


class _GodRollWorker(QThread):
    progress = pyqtSignal(dict)
    completed = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, optimizer, request, language, parent=None):
        super().__init__(parent)
        self.optimizer = optimizer
        self.request = request
        self.language = language
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        try:
            result = self.optimizer.search(
                self.request,
                language=self.language,
                cancelled=self._cancel.is_set,
                progress=self.progress.emit,
            )
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.completed.emit(result)


@register("god_roll", "GodRollPage.qml")
class GodRollViewModel(PageViewModel):
    STRINGS_SECTION = "god_roll_tab"

    dataChanged = pyqtSignal()
    resultsChanged = pyqtSignal()

    def __init__(self, app, parent=None):
        super().__init__(app, parent)
        self.current_lang = str(app.language)
        self._character_level = 60
        self._worker: _GodRollWorker | None = None
        self._add_busy = False
        self._rarity_index = 0
        self._mfg_index = 0
        self._type_index = 0
        self._weapon_index = 0
        self._mode_index = 0
        self._level = self._character_level
        self._flag_index = 0
        self._barrel_index = 0
        self._torgue_index = 0
        self._base_element_index = 0
        self._secondary_index = 0
        self._pearl_index = 0
        self._force_element = False
        self._effort_index = 1
        self._top_n = 10
        self._profile_index = 0
        self._status = ""
        self._group_limits: dict[str, tuple[int, int]] = {}
        self._group_limit_rows: list[dict[str, Any]] = []
        self._raw_results: list[dict[str, Any]] = []
        # _localize_result 结果缓存：点击选中只换 index，不应整表重建（此前点一下卡一下）
        self._localized_cache: list[dict[str, Any]] | None = None
        self._last_result_meta: dict[str, Any] | None = None
        self._results_visible = False
        self._result_index = -1
        self._flags = resource_loader.get_flag_labels(self.current_lang)
        self._flag_labels = [self._flags[k] for k in _FLAG_CODE_ORDER if k in self._flags]
        self._flag_index = self._default_flag_index()
        self.item_index = resource_loader.load_item_json("item_name_index.json") or {}
        self.optimizer = WeaponGodRollOptimizer(self.item_index)
        self.catalog = self.optimizer.catalog()
        self._catalog_rows: list[dict[str, Any]] = []
        # QML evaluates model properties repeatedly during layout.  Cache
        # filtered option lists until a selector changes so page activation
        # does not rebuild the catalog on every binding pass.
        self._option_cache: dict[str, Any] = {}
        self._catalog_name_cache: dict[tuple[str, str], str] = {}
        self._load_lang_data()
        self._status = self._text("idle")

    # ------------------------------------------------------------------ #
    # 本地化
    # ------------------------------------------------------------------ #
    def _load_lang_data(self) -> None:
        self.current_lang = str(self.app.language)
        self._localized_cache = None
        self.loc = self.app.localizer.section("god_roll_tab") or {}
        self.taxonomy = (self.app.localizer.section("weapon_editor_tab") or {}).get("taxonomy") or {}
        self.stats_loc = (self.app.localizer.section("weapon_editor_tab") or {}).get("stats") or {}
        self.rule_loc = self.app.localizer.section("weapon_rules") or {}
        self.item_names = (
            resource_loader.load_json_resource("i18n/item_localization_zh-CN.json") or {}
            if self.current_lang == "zh-CN" else {})
        self._flags = resource_loader.get_flag_labels(self.current_lang)
        self._flag_labels = [self._flags[k] for k in _FLAG_CODE_ORDER if k in self._flags]
        self._option_cache.clear()
        self._catalog_name_cache.clear()

    def _text(self, key: str) -> str:
        return str((self.loc or {}).get(key) or _FALLBACK.get(key) or key)

    def on_language_changed(self) -> None:
        super().on_language_changed()
        self._load_lang_data()
        self._render_last_results()
        self.dataChanged.emit()

    @staticmethod
    def _humanize(value):
        return str(value or "").replace("weapon_sm", "SMG").replace("_", " ").strip().title()

    def _manufacturer_label(self, value, root_id=None):
        canonical = ""
        if root_id not in (None, ""):
            try:
                manufacturer, _weapon_type, found = lookup.get_kind_enums(int(root_id))
            except (TypeError, ValueError):
                found = False
            if found:
                canonical = manufacturer
        if not canonical:
            canonical = {"borg": "Ripper", "order": "Order"}.get(
                str(value or "").casefold(), self._humanize(value))
        return str(self.item_names.get(canonical) or canonical)

    def _weapon_type_label(self, value):
        canonical = "Assault Rifle" if str(value or "") == "AssaultRifle" else str(value or "")
        return str(self.taxonomy.get(_TYPE_KEYS.get(canonical, "")) or canonical)

    def _rarity_label(self, value):
        return str(self.taxonomy.get(str(value or "").casefold()) or value or "—")

    def _group_label(self, value):
        key = str(value or "").casefold()
        return str(self.taxonomy.get(_GROUP_KEYS.get(key, "")) or self._humanize(key) or "—")

    def _source_label(self, owner, root_id):
        owner = str(owner or "")
        if owner == str(root_id):
            return self._text("source_current")
        if owner == "1":
            return self._text("source_universal")
        try:
            manufacturer, weapon_type, found = lookup.get_kind_enums(int(owner))
        except (TypeError, ValueError):
            found = False
        if not found:
            return owner
        return f"{self._manufacturer_label(manufacturer, owner)} · {self._weapon_type_label(weapon_type)}"

    def _element_name(self, ref):
        part = self.optimizer.part_label(ref).casefold()
        names = [key for key in _ELEMENT_NAMES if key in part]
        labels = [_ELEMENT_NAMES[key].get(self.current_lang, _ELEMENT_NAMES[key]["en-US"]) for key in names]
        return " + ".join(dict.fromkeys(labels)) or f"{ref} · {self.optimizer.part_label(ref)}"

    def _catalog_name(self, row):
        cache_key = (str(row.get("root_id") or ""), str(row.get("composition_ref") or ""))
        cached = self._catalog_name_cache.get(cache_key)
        if cached is not None:
            return cached
        name = row.get("name_zh") if self.current_lang == "zh-CN" else row.get("name_en")
        name = name or row.get("name_en") or row.get("name_zh") or row.get("part")
        name = str(name or row.get("composition_ref"))
        if not name.casefold().startswith("comp_"):
            self._catalog_name_cache[cache_key] = name
            return name

        # Two unique weapons currently have an empty composition.name in the
        # pipeline (Hard Dark and Finnty).  Resolve a representative serial from
        # their first legal parts so the picker shows the in-game weapon title,
        # while retaining the composition key as a final fallback.
        root_id = str(row.get("root_id") or "")
        composition_ref = str(row.get("composition_ref") or "")
        composition = ((self.optimizer.weapons.get(root_id) or {}).get("compositions") or {}).get(composition_ref) or {}
        refs = []
        for group in (composition.get("groups") or {}).values():
            allowed = group.get("allowed_part_refs") or []
            if allowed:
                refs.append(str(allowed[0]))
        tokens = []
        for ref in refs:
            owner, _, part = ref.partition(":")
            if not part.isdigit():
                continue
            tokens.append(f"{{{part}}}" if owner == root_id else f"{{{owner}:{part}}}")
        if tokens:
            try:
                manufacturer, weapon_type, found = lookup.get_kind_enums(int(root_id))
                if found:
                    serial = f"{root_id}, 0, 1, 60| 2, 1|| {' '.join(tokens)} |"
                    display = item_display_resolver.resolve_item_display(
                        int(root_id), manufacturer, weapon_type, serial, self.current_lang) or {}
                    resolved = str(display.get("display_name") or "")
                    if resolved and not resolved.casefold().startswith(("comp_", "part_")):
                        self._catalog_name_cache[cache_key] = resolved
                        return resolved
            except (TypeError, ValueError, KeyError):
                pass
        self._catalog_name_cache[cache_key] = name
        return name

    # ------------------------------------------------------------------ #
    # QML 属性：筛选
    # ------------------------------------------------------------------ #
    @pyqtProperty("QVariantMap", notify=dataChanged)
    def texts(self) -> dict[str, str]:
        keys = set(_FALLBACK) | set(self.loc or {})
        return {key: self._text(key) for key in sorted(keys)}

    @pyqtProperty(bool, notify=dataChanged)
    def liveMode(self) -> bool:
        return self.app.liveActive

    @pyqtProperty(list, notify=dataChanged)
    def rarityOptions(self) -> list[dict[str, Any]]:
        cached = self._option_cache.get("rarity")
        if cached is not None:
            return cached
        available = {row["rarity"] for row in self.catalog}
        value = [{"label": self._rarity_label(r), "value": r}
                 for r in _RARITY_ORDER if r in available]
        self._option_cache["rarity"] = value
        return value

    @pyqtProperty(int, notify=dataChanged)
    def rarityIndex(self) -> int:
        return self._rarity_index

    @pyqtProperty(list, notify=dataChanged)
    def mfgOptions(self) -> list[dict[str, Any]]:
        cached = self._option_cache.get("mfg")
        if cached is not None:
            return cached
        rarity = self._current_rarity()
        rows = [row for row in self.catalog if row["rarity"] == rarity]
        options = [{"label": self._text("auto"), "value": None}]
        for value in sorted({row["manufacturer"] for row in rows}):
            sample = next(row for row in rows if row["manufacturer"] == value)
            options.append({"label": self._manufacturer_label(value, sample["root_id"]), "value": value})
        self._option_cache["mfg"] = options
        return options

    @pyqtProperty(int, notify=dataChanged)
    def mfgIndex(self) -> int:
        return self._mfg_index

    @pyqtProperty(list, notify=dataChanged)
    def weaponTypeOptions(self) -> list[dict[str, Any]]:
        cached = self._option_cache.get("weapon_type")
        if cached is not None:
            return cached
        rarity = self._current_rarity()
        mfg = self._current_mfg()
        rows = [row for row in self.catalog if row["rarity"] == rarity
                and (mfg is None or row["manufacturer"] == mfg)]
        options = [{"label": self._text("auto"), "value": None}]
        for value in sorted({row["weapon_type"] for row in rows}):
            options.append({"label": self._weapon_type_label(value), "value": value})
        self._option_cache["weapon_type"] = options
        return options

    @pyqtProperty(int, notify=dataChanged)
    def weaponTypeIndex(self) -> int:
        return self._type_index

    @pyqtProperty(list, notify=dataChanged)
    def weaponOptions(self) -> list[dict[str, Any]]:
        cached = self._option_cache.get("weapon")
        if cached is not None:
            return cached
        rarity = self._current_rarity()
        mfg = self._current_mfg()
        weapon_type = self._current_weapon_type()
        rows = [row for row in self.catalog
                if row["rarity"] == rarity
                and (mfg is None or row["manufacturer"] == mfg)
                and (weapon_type is None or row["weapon_type"] == weapon_type)]
        rows.sort(key=lambda row: (row["weapon_type"], row["manufacturer"], self._catalog_name(row).casefold()))
        self._catalog_rows = rows
        options = [{
            "label": (f"{self._catalog_name(row)} · "
                      f"{self._manufacturer_label(row['manufacturer'], row['root_id'])} "
                      f"{self._weapon_type_label(row['weapon_type'])} · {self._rarity_label(row['rarity'])}"),
            "value": [row["root_id"], row["composition_ref"]],
        } for row in rows]
        self._option_cache["weapon"] = options
        return options

    @pyqtProperty(int, notify=dataChanged)
    def weaponIndex(self) -> int:
        return self._weapon_index

    @pyqtProperty(list, notify=dataChanged)
    def modeOptions(self) -> list[dict[str, str]]:
        return [{"label": self._text("legal"), "value": "legal"},
                {"label": self._text("unrestricted"), "value": "unrestricted"}]

    @pyqtProperty(int, notify=dataChanged)
    def modeIndex(self) -> int:
        return self._mode_index

    @pyqtProperty(int, notify=dataChanged)
    def level(self) -> int:
        return self._level

    @pyqtProperty(list, notify=dataChanged)
    def flagOptions(self) -> list[dict[str, Any]]:
        return [{"label": label, "value": label.split(" ", 1)[0]} for label in self._flag_labels]

    @pyqtProperty(int, notify=dataChanged)
    def flagIndex(self) -> int:
        return self._flag_index

    # -- 约束 --------------------------------------------------------------- #
    @pyqtProperty(list, notify=dataChanged)
    def barrelOptions(self) -> list[dict[str, Any]]:
        cached = self._option_cache.get("barrel")
        if cached is not None:
            return cached
        selected = self._current_weapon()
        if not selected:
            self._option_cache["barrel"] = []
            return self._option_cache["barrel"]
        root_id, composition_ref = selected
        options = [{"label": f"{row['ref']} · {row['label']}", "value": row["ref"]}
                   for row in self.optimizer.barrel_options(root_id, composition_ref)]
        self._option_cache["barrel"] = options
        return options

    @pyqtProperty(int, notify=dataChanged)
    def barrelIndex(self) -> int:
        return self._barrel_index

    @pyqtProperty(list, notify=dataChanged)
    def torgueOptions(self) -> list[dict[str, Any]]:
        cached = self._option_cache.get("torgue")
        if cached is not None:
            return cached
        options = self._composition_options()
        torgue_modes = options.get("torgue_modes") or {}
        selectable = any(torgue_modes.get(key) for key in ("sticky", "impact"))
        if not selectable:
            value = [{"label": f"⚠ {self._text('unavailable')}", "value": "any", "enabled": False}]
            self._option_cache["torgue"] = value
            return value
        result = [{"label": self._text("torgue_any"), "value": "any", "enabled": True}]
        for key in ("sticky", "impact"):
            reachable = bool(torgue_modes.get(key))
            label = self._text(f"torgue_{key}")
            result.append({"label": label if reachable else f"⚠ {label}", "value": key, "enabled": reachable})
        self._option_cache["torgue"] = result
        return result

    @pyqtProperty(int, notify=dataChanged)
    def torgueIndex(self) -> int:
        return self._torgue_index

    def _element_options(self, key: str, allow_none: bool) -> list[dict[str, Any]]:
        cache_key = f"element:{key}"
        cached = self._option_cache.get(cache_key)
        if cached is not None:
            return cached
        options = (self._composition_options() if key == "body_elements"
                   else self._composition_options_dependent())
        none_legal = options.get("element_none_legal") or {}
        none_key = {"body_elements": "body_ele", "secondary_elements": "secondary_ele",
                    "pearl_elements": "pearl_elem"}[key]
        rows = options.get(key) or []
        result = [{"label": self._text("auto_available"), "value": AUTO, "enabled": True}]
        if allow_none:
            result.append({"label": self._text("none"), "value": NONE,
                           "enabled": bool(none_legal.get(none_key, True)) or self._force_element})
        for row in rows:
            label = self._element_name(row["ref"])
            legal = bool(row.get("legal", True))
            result.append({
                "label": label if legal else f"⚠ {label}",
                "value": row["ref"],
                "enabled": legal or self._force_element,
            })
        self._option_cache[cache_key] = result
        return result

    @pyqtProperty(list, notify=dataChanged)
    def baseElementOptions(self) -> list[dict[str, Any]]:
        return self._element_options("body_elements", allow_none=True)

    @pyqtProperty(int, notify=dataChanged)
    def baseElementIndex(self) -> int:
        return self._base_element_index

    @pyqtProperty(list, notify=dataChanged)
    def secondaryElementOptions(self) -> list[dict[str, Any]]:
        cached = self._option_cache.get("secondary_element")
        if cached is not None:
            return cached
        options = self._element_options("secondary_elements", allow_none=True)
        if len(options) <= 2 and not any(o["enabled"] for o in options[1:]):
            value = [{"label": f"⚠ {self._text('unavailable')}", "value": AUTO, "enabled": False}]
        else:
            value = options
        self._option_cache["secondary_element"] = value
        return value

    @pyqtProperty(int, notify=dataChanged)
    def secondaryElementIndex(self) -> int:
        return self._secondary_index

    @pyqtProperty(list, notify=dataChanged)
    def pearlElementOptions(self) -> list[dict[str, Any]]:
        cached = self._option_cache.get("pearl_element")
        if cached is not None:
            return cached
        options = self._element_options("pearl_elements", allow_none=False)
        if len(options) <= 1:
            value = [{"label": f"⚠ {self._text('unavailable')}", "value": AUTO, "enabled": False}]
        else:
            value = options
        self._option_cache["pearl_element"] = value
        return value

    @pyqtProperty(int, notify=dataChanged)
    def pearlElementIndex(self) -> int:
        return self._pearl_index

    @pyqtProperty(bool, notify=dataChanged)
    def forceElement(self) -> bool:
        return self._force_element

    @pyqtProperty(bool, notify=dataChanged)
    def limitsVisible(self) -> bool:
        return self._current_mode() == "unrestricted"

    @pyqtProperty(list, notify=dataChanged)
    def groupLimitRows(self) -> list[dict[str, Any]]:
        return self._group_limit_rows

    # -- 运行 --------------------------------------------------------------- #
    @pyqtProperty(list, notify=dataChanged)
    def effortOptions(self) -> list[dict[str, str]]:
        return [{"label": self._text(key), "value": key} for key in ("fast", "balanced", "deep")]

    @pyqtProperty(int, notify=dataChanged)
    def effortIndex(self) -> int:
        return self._effort_index

    @pyqtProperty(int, notify=dataChanged)
    def topN(self) -> int:
        return self._top_n

    @pyqtProperty(list, notify=dataChanged)
    def profileOptions(self) -> list[dict[str, str]]:
        return [{"label": self._text(f"score_profile_{key}"), "value": key}
                for key in ("sustained_dps", "burst", "crit_element", "balanced")]

    @pyqtProperty(int, notify=dataChanged)
    def profileIndex(self) -> int:
        return self._profile_index

    @pyqtProperty(bool, notify=dataChanged)
    def searching(self) -> bool:
        return self._worker is not None

    @pyqtProperty(bool, notify=dataChanged)
    def canSearch(self) -> bool:
        return (self._worker is None and not self.liveMode and bool(self._current_weapon()))

    @pyqtProperty(str, notify=dataChanged)
    def statusText(self) -> str:
        return self._status

    # -- 结果 --------------------------------------------------------------- #
    @pyqtProperty(bool, notify=resultsChanged)
    def resultsVisible(self) -> bool:
        return self._results_visible

    @pyqtProperty(list, notify=resultsChanged)
    def results(self) -> list[dict[str, Any]]:
        if self._localized_cache is None or len(self._localized_cache) != len(self._raw_results):
            self._localized_cache = [self._localize_result(row) for row in self._raw_results]
        return self._localized_cache

    @pyqtProperty(str, notify=resultsChanged)
    def resultsSummary(self) -> str:
        meta = self._last_result_meta
        if meta is None:
            return ""
        results = self._raw_results
        text = self._text("done_exact" if meta.get("complete") else "done").format(
            count=len(results),
            attempted=meta.get("attempted", 0),
            frontier=meta.get("exact_examined", meta.get("attempted", 0)),
            elapsed=float(meta.get("elapsed") or 0),
        )
        if meta.get("cancelled"):
            text = self._text("cancelled") + " " + text
        if not results:
            text = self._text("no_results")
        scope = self._text("results_scope_exact" if meta.get("complete") else "results_scope").format(
            mode=self._text(str(meta.get("mode") or "legal")),
            barrel=str(meta.get("barrel") or "—"),
            count=int(meta.get("top_n") or len(results)),
            profile=self._text(f"score_profile_{meta.get('score_profile') or 'sustained_dps'}"),
        )
        return f"{text}\n{scope}"

    @pyqtProperty(int, notify=resultsChanged)
    def resultIndex(self) -> int:
        return self._result_index

    @pyqtProperty("QVariantMap", notify=resultsChanged)
    def currentResult(self) -> dict[str, Any]:
        results = self.results
        if 0 <= self._result_index < len(results):
            return results[self._result_index]
        return {}

    @pyqtProperty(str, notify=resultsChanged)
    def currentScoreText(self) -> str:
        result = self.currentResult
        if not result:
            return "—"
        profile = str(result.get("score_profile") or "sustained_dps")
        lines = [
            f"{self._text('score_total')}: {float(result.get('score') or 0):.2f}",
            f"{self._text('score_profile')}: {self._text(f'score_profile_{profile}')}",
        ]
        for row in result.get("score_breakdown") or ():
            key = str(row.get("key") or "")
            label = self._text(f"score_metric_{key}")
            raw = row.get("raw_display") or "—"
            weight = float(row.get("weight") or 0.0)
            lines.append(f"{label} × {weight:.0%}: {float(row.get('contribution') or 0):+.2f} ({raw})")
        lines.append(self._text("score_warning"))
        missing = [str(value).split(":", 1)[1] for value in (result.get("score_warnings") or ())
                   if str(value).startswith("missing:")]
        if missing:
            labels = [self._text(f"score_metric_{key}") for key in missing]
            lines.append(self._text("score_missing").format(metrics=", ".join(labels)))
        return "\n".join(lines)

    @pyqtProperty(list, notify=resultsChanged)
    def currentPartDetails(self) -> list[dict[str, str]]:
        return self.currentResult.get("part_details") or []

    # ------------------------------------------------------------------ #
    # QML 槽
    # ------------------------------------------------------------------ #
    @pyqtSlot(int)
    def setRarityIndex(self, index: int) -> None:
        if not 0 <= index < len(self.rarityOptions):
            return
        self._rarity_index = index
        self._mfg_index = 0
        self._type_index = 0
        self._weapon_index = 0
        self._refresh_options()

    @pyqtSlot(int)
    def setMfgIndex(self, index: int) -> None:
        if not 0 <= index < len(self.mfgOptions):
            return
        self._mfg_index = index
        self._type_index = 0
        self._weapon_index = 0
        self._refresh_options()

    @pyqtSlot(int)
    def setWeaponTypeIndex(self, index: int) -> None:
        if not 0 <= index < len(self.weaponTypeOptions):
            return
        self._type_index = index
        self._weapon_index = 0
        self._refresh_options()

    @pyqtSlot(int)
    def setWeaponIndex(self, index: int) -> None:
        if not 0 <= index < len(self.weaponOptions):
            return
        self._weapon_index = index
        self._refresh_options()

    @pyqtSlot(int)
    def setModeIndex(self, index: int) -> None:
        if not 0 <= index < len(self.modeOptions):
            return
        self._mode_index = index
        self._refresh_options()

    @pyqtSlot(int)
    def setLevel(self, value: int) -> None:
        self._level = max(1, int(value))
        self.dataChanged.emit()

    @pyqtSlot(int)
    def setFlagIndex(self, index: int) -> None:
        if 0 <= index < len(self._flag_labels):
            self._flag_index = index
            self.dataChanged.emit()

    @pyqtSlot(int)
    def setBarrelIndex(self, index: int) -> None:
        if not 0 <= index < len(self.barrelOptions):
            return
        self._barrel_index = index
        self._refresh_dependent_elements()
        self.dataChanged.emit()

    @pyqtSlot(int)
    def setTorgueIndex(self, index: int) -> None:
        if 0 <= index < len(self.torgueOptions):
            self._torgue_index = index
            self.dataChanged.emit()

    @pyqtSlot(int)
    def setBaseElementIndex(self, index: int) -> None:
        if not 0 <= index < len(self.baseElementOptions):
            return
        self._base_element_index = index
        self._refresh_dependent_elements()
        self.dataChanged.emit()

    @pyqtSlot(int)
    def setSecondaryElementIndex(self, index: int) -> None:
        if 0 <= index < len(self.secondaryElementOptions):
            self._secondary_index = index
            self.dataChanged.emit()

    @pyqtSlot(int)
    def setPearlElementIndex(self, index: int) -> None:
        if 0 <= index < len(self.pearlElementOptions):
            self._pearl_index = index
            self.dataChanged.emit()

    @pyqtSlot(bool)
    def setForceElement(self, checked: bool) -> None:
        self._force_element = bool(checked)
        self._refresh_options()

    @pyqtSlot(int)
    def setEffortIndex(self, index: int) -> None:
        if 0 <= index < len(self.effortOptions):
            self._effort_index = index
            self.dataChanged.emit()

    @pyqtSlot(int)
    def setTopN(self, value: int) -> None:
        self._top_n = max(1, min(10, int(value)))
        self.dataChanged.emit()

    @pyqtSlot(int)
    def setProfileIndex(self, index: int) -> None:
        if not 0 <= index < len(self.profileOptions):
            return
        self._profile_index = index
        # 评分口径变化时旧结果作废（与主线一致）
        current = self.profileOptions[index]["value"]
        if self._last_result_meta and current != str(self._last_result_meta.get("score_profile")):
            self._raw_results = []
            self._localized_cache = None
            self._last_result_meta = None
            self._results_visible = False
            self._status = self._text("idle")
            self.resultsChanged.emit()
        self.dataChanged.emit()

    @pyqtSlot(str, int, int)
    def setGroupLimit(self, group: str, minimum: int, maximum: int) -> None:
        self._group_limits[group] = (max(0, int(minimum)), max(0, int(maximum)))
        for row in self._group_limit_rows:
            if row["group"] == group:
                row["minimum"] = max(0, int(minimum))
                row["maximum"] = max(0, int(maximum))
        self.dataChanged.emit()

    @pyqtSlot()
    def startSearch(self) -> None:
        if self._worker is not None or self.liveMode or not self._current_weapon():
            return
        try:
            request = self._build_request()
        except Exception as exc:
            self.app.toast(str(exc), "warning")
            return
        worker = _GodRollWorker(self.optimizer, request, self.current_lang, self)
        worker.progress.connect(self._on_progress)
        worker.completed.connect(self._on_completed)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._worker_finished)
        self._worker = worker
        self._status = self._text("running").format(attempted=0, accepted=0, best="—")
        self.dataChanged.emit()
        worker.start()

    @pyqtSlot()
    def cancelSearch(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.dataChanged.emit()

    @pyqtSlot(int)
    def setResultIndex(self, index: int) -> None:
        self._result_index = int(index)
        self.resultsChanged.emit()

    @pyqtSlot()
    def closeResults(self) -> None:
        self._results_visible = False
        self.resultsChanged.emit()

    @pyqtSlot(int)
    def copyResult(self, index: int) -> None:
        results = self.results
        if 0 <= index < len(results):
            from PyQt6.QtWidgets import QApplication
            QApplication.clipboard().setText(results[index]["serial"])
            self.app.toast(self._text("copied"), "success")

    @pyqtSlot("QVariantList")
    def addResults(self, indices) -> None:
        from core.batch import add_serial_lines

        results = self.results
        serials = [results[i]["serial"] for i in indices
                   if isinstance(i, int) and 0 <= i < len(results)]
        if not serials or self._add_busy or self.liveMode:
            return
        if not self.controller.yaml_obj:
            self.app.toast(self.tr("main_window.dialogs.load_save_first"), "warning")
            return
        self._add_busy = True
        self.app.suspend_autosave(True)
        success = fail = 0
        try:
            for _current, _total, s, f in add_serial_lines(self.controller, serials, self._flag_value()):
                success, fail = s, f
        finally:
            self.app.suspend_autosave(False)
            self._add_busy = False
        self.app.toast(self._text("add_done").format(success=success, fail=fail),
                       "success" if success else "warning")
        if success:
            self.app._mark_items_stale()

    @pyqtSlot(int)
    def openInEditor(self, index: int) -> None:
        results = self.results
        if 0 <= index < len(results):
            self.app.open_generated_weapon(dict(self._raw_results[index]))

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _current_rarity(self):
        options = self.rarityOptions
        if 0 <= self._rarity_index < len(options):
            return options[self._rarity_index]["value"]
        return options[0]["value"] if options else None

    def _current_mfg(self):
        options = self.mfgOptions
        if 0 <= self._mfg_index < len(options):
            return options[self._mfg_index]["value"]
        return None

    def _current_weapon_type(self):
        options = self.weaponTypeOptions
        if 0 <= self._type_index < len(options):
            return options[self._type_index]["value"]
        return None

    def _current_weapon(self):
        options = self.weaponOptions
        if 0 <= self._weapon_index < len(options):
            value = options[self._weapon_index]["value"]
            return (str(value[0]), str(value[1])) if value else None
        return None

    def _current_mode(self) -> str:
        return self.modeOptions[self._mode_index]["value"] if 0 <= self._mode_index < 2 else "legal"

    def _current_barrel(self):
        options = self.barrelOptions
        if 0 <= self._barrel_index < len(options):
            return options[self._barrel_index]["value"]
        return None

    def _current_element(self, options_name: str, index: int):
        options = getattr(self, options_name)
        if 0 <= index < len(options):
            return options[index]["value"]
        return AUTO

    def _composition_options(self) -> dict[str, Any]:
        """基础选项（torgue/主元素/组限制）：仅固定枪管，与主线 _refresh_options 一致。"""
        selected = self._current_weapon()
        if not selected:
            return {}
        root_id, composition_ref = selected
        return self.optimizer.composition_options(
            root_id, composition_ref, self._current_mode(),
            fixed_barrel_ref=self._current_barrel(),
        )

    def _composition_options_dependent(self) -> dict[str, Any]:
        """联动选项（副元素/珠光）：带上主元素选择，与主线 _refresh_dependent_elements 一致。"""
        selected = self._current_weapon()
        if not selected:
            return {}
        root_id, composition_ref = selected
        return self.optimizer.composition_options(
            root_id, composition_ref, self._current_mode(),
            fixed_barrel_ref=self._current_barrel(),
            base_element_ref=self._current_element("baseElementOptions", self._base_element_index),
        )

    def _refresh_options(self) -> None:
        self._option_cache.clear()
        self._barrel_index = 0
        self._torgue_index = 0
        self._base_element_index = 0
        self._secondary_index = 0
        self._pearl_index = 0
        self._rebuild_group_limits()
        self.dataChanged.emit()

    def _refresh_dependent_elements(self) -> None:
        # Barrel/base-element changes alter the dependent element pools.
        self._option_cache.pop("torgue", None)
        self._option_cache.pop("element:secondary_elements", None)
        self._option_cache.pop("element:pearl_elements", None)
        self._option_cache.pop("secondary_element", None)
        self._option_cache.pop("pearl_element", None)
        self._secondary_index = 0
        self._pearl_index = 0

    def _rebuild_group_limits(self) -> None:
        options = self._composition_options()
        groups = options.get("groups") or {}
        self._group_limit_rows = []
        self._group_limits = {}
        for group, row in sorted(groups.items()):
            if group == "barrel":
                continue
            hard_max = max(0, int(row.get("hard_max", row.get("max", 1))))
            minimum = min(int(row.get("min", 0)), hard_max)
            maximum = min(int(row.get("max", hard_max)), hard_max)
            self._group_limits[group] = (minimum, maximum)
            self._group_limit_rows.append({
                "group": group,
                "label": self._group_label(group),
                "pool": int(row.get("pool_size", 0)),
                "hardMax": hard_max,
                "minimum": minimum,
                "maximum": maximum,
            })

    def _build_request(self) -> GodRollRequest:
        root_id, composition_ref = self._current_weapon()
        samples, seconds = _EFFORTS[self.effortOptions[self._effort_index]["value"]]
        return GodRollRequest(
            root_id=str(root_id),
            composition_ref=str(composition_ref),
            level=int(self._level),
            mode=self._current_mode(),
            fixed_barrel_ref=self._current_barrel(),
            torgue_mode=str(self.torgueOptions[self._torgue_index]["value"]
                            if self.torgueOptions else "any"),
            base_element_ref=self._current_element("baseElementOptions", self._base_element_index),
            secondary_element_ref=self._current_element("secondaryElementOptions", self._secondary_index),
            pearl_element_ref=self._current_element("pearlElementOptions", self._pearl_index),
            allow_illegal_elements=self._force_element,
            group_limits=dict(self._group_limits),
            top_n=int(self._top_n),
            max_samples=samples,
            time_limit=seconds,
            score_profile=self.profileOptions[self._profile_index]["value"],
        )

    def _on_progress(self, row: dict) -> None:
        best = float(row.get("best_score") or row.get("best_dps") or 0)
        self._status = self._text("running").format(
            attempted=row.get("attempted", 0), accepted=row.get("accepted", 0), best=f"{best:.2f}")
        self.dataChanged.emit()

    def _on_completed(self, result: dict) -> None:
        self._raw_results = [dict(row) for row in (result.get("results") or ())]
        self._localized_cache = None
        self._last_result_meta = {
            "complete": bool(result.get("complete")),
            "cancelled": bool(result.get("cancelled")),
            "attempted": result.get("attempted", 0),
            "exact_examined": result.get("exact_examined", result.get("attempted", 0)),
            "elapsed": float(result.get("elapsed") or 0),
            "mode": self._current_mode(),
            "score_profile": str(result.get("score_profile")
                                 or self.profileOptions[self._profile_index]["value"]),
            "barrel": self.barrelOptions[self._barrel_index]["label"] if self.barrelOptions else "—",
            "top_n": self._top_n,
        }
        self._result_index = 0 if self._raw_results else -1
        self._results_visible = True
        self.resultsChanged.emit()

    def _on_failed(self, error: str) -> None:
        self._status = self._text("error").format(error=error)
        self.app.toast(self._status, "error")
        self.dataChanged.emit()

    def _worker_finished(self) -> None:
        worker = self.sender()
        if worker is self._worker:
            self._worker = None
            self.dataChanged.emit()
        worker.deleteLater()

    def _render_last_results(self) -> None:
        if self._last_result_meta is not None:
            self.resultsChanged.emit()

    def _localize_result(self, result) -> dict[str, Any]:
        row = dict(result or {})
        root_id = str(row.get("root_id") or "")
        composition_ref = str(row.get("composition_ref") or "")
        composition = (
            ((self.optimizer.weapons.get(root_id) or {}).get("compositions") or {}).get(composition_ref)
            or {}
        )
        manufacturer_key = str(row.get("manufacturer_key") or row.get("manufacturer") or "")
        weapon_type_key = str(row.get("weapon_type_key") or row.get("weapon_type") or "")
        rarity_key = str(row.get("rarity_key") or row.get("rarity") or "")
        row["manufacturer_key"] = manufacturer_key
        row["weapon_type_key"] = weapon_type_key
        row["rarity_key"] = rarity_key
        names = composition.get("name") or {}
        preferred_name = names.get("zh") if self.current_lang == "zh-CN" else names.get("en")
        base_name = str(
            preferred_name or names.get("en") or names.get("zh")
            or composition.get("part") or row.get("name") or "—"
        )
        # 完整武器名与旧版 Roll 列表同一数据源：core 解析解码串（前缀+标题）
        display: dict[str, Any] = {}
        try:
            display = item_display_resolver.resolve_item_display(
                int(root_id), manufacturer_key, weapon_type_key,
                str(row.get("decoded") or ""), self.current_lang) or {}
        except (TypeError, ValueError):
            display = {}
        row["name"] = str(display.get("display_name") or base_name)
        row["manufacturer"] = self._manufacturer_label(manufacturer_key, root_id)
        row["weapon_type"] = self._weapon_type_label(weapon_type_key)
        row["rarity"] = str(display.get("rarity") or "") or self._rarity_label(rarity_key)
        row["rarity_color"] = (
            qt_items_tab.WEAPON_CARD_RARITY_COLORS.get(rarity_key.casefold())
            or qt_items_tab.WEAPON_CARD_RARITY_COLORS.get(str(row["rarity"]).casefold())
            or "#78909C"
        )
        # 未选中行的淡稀有度底色（对齐旧版列表 item.setBackground alpha 28）
        row["rarity_tint"] = f"#1C{str(row['rarity_color']).lstrip('#')}"
        if row.get("status") == "legal":
            row["status_label"] = self.rule_loc.get("status_legal") or self._text("legal")
        elif row.get("element_only_modified"):
            row["status_label"] = self._text("status_element_modified")
        else:
            row["status_label"] = self.rule_loc.get("status_modified") or "Modified"
        stats = row.get("stats") or {}
        row["formatted_stats"] = [
            {"key": key, "label": self.stats_loc.get(key, key),
             "value": str(item_display_resolver.format_weapon_stat(key, stats.get(key), self.current_lang) or "—")}
            for key in item_display_resolver.WEAPON_STAT_KEYS
        ]
        details = []
        try:
            part_rows = serial_inspect.part_rows(
                str(row.get("decoded") or ""), int(root_id), weapon_type_key, self.current_lang)
        except (TypeError, ValueError):
            part_rows = []
        for part in part_rows:
            group_label = self._group_label(part.get("display_category") or part.get("category"))
            internal = str(part.get("part") or "")
            name = str(part.get("name") or internal or part.get("key") or "—")
            if name == internal or name.casefold().startswith(("part_", "comp_")):
                name = group_label
            details.append({
                "ref": str(part.get("key") or ""),
                "group_label": group_label,
                "name": name,
                "description": str(part.get("description") or self._text("no_part_effect")),
                "source_label": self._source_label(part.get("owner"), root_id),
                "internal": internal,
            })
        row["part_details"] = details
        element_names = [
            self._element_name(ref)
            for ref in row.get("selected_refs") or ()
            if str((self.optimizer.part_refs.get(str(ref)) or {}).get("selection_group") or "").casefold()
            in ELEMENT_GROUPS
        ]
        row["element"] = " / ".join(dict.fromkeys(filter(None, element_names)))
        # 旧版结果行：完整名 / 厂商·类型·稀有度·元素 / 关键属性 / 分数 / 变体部件
        row["meta_text"] = " · ".join(filter(None, (
            row["manufacturer"], row["weapon_type"], row["rarity"],
            row["element"] or self._text("no_element"))))
        formatted = {entry["key"]: entry["value"] for entry in row["formatted_stats"]}
        row["stats_text"] = " · ".join(
            f"{self.stats_loc.get(key, key)} {formatted.get(key) or '—'}"
            for key in _LIST_STAT_KEYS
        )
        row["score_text"] = (
            f"{self._text('score_short')} {float(row.get('score')):.2f}"
            if row.get("score") is not None else ""
        )
        # 变体摘要只列部件名；搜索约束文案（"必须包含xx"）不上结果行
        variant = []
        variant.extend(part["name"] for part in details if part["group_label"] and part["name"] not in variant)
        row["variant_summary"] = " · ".join(variant[:5])
        row["effect_entries"] = self._effect_entries(str(row.get("decoded") or ""), stats)
        row["tooltip"] = "\n".join([
            str(row.get("name") or "—"),
            f"{row['manufacturer']} · {row['weapon_type']} · {row['rarity']}",
            str(row.get("status_label") or ""),
            *(f"{part['ref']} · {part['name']} · {part['description']}" for part in details),
            f"Base85: {row.get('serial') or ''}",
        ])
        return row

    def _effect_entries(self, decoded: str, stats) -> list[dict[str, Any]]:
        """结果详情的图标化技能列表：与物品页武器卡同一数据源/图标资源。"""
        if not decoded:
            return []
        try:
            details = qt_items_tab._weapon_card_details(decoded, stats or {}, self.current_lang)
        except Exception:
            return []
        entries = details.get("display_entries") or details.get("entries") or []
        out: list[dict[str, Any]] = []
        for entry in entries:
            text = str(entry.get("text") or "").strip()
            if not text:
                continue
            title, description = text, ""
            for separator in (" - ", " – "):
                if separator in title:
                    title, description = title.split(separator, maxsplit=1)
                    break
            out.append({
                "title": title.strip(),
                "description": description.strip(),
                "icon": self._effect_icon_url(str(entry.get("icon_asset") or "")),
                "legendary": str(entry.get("display_kind") or "") == "legendary",
            })
        return out

    @staticmethod
    def _effect_icon_url(asset: str) -> str:
        package = str(asset or "").split(".", 1)[0]
        filename = f"{package.rsplit('/', 1)[-1]}.png" if package else ""
        if not filename:
            return ""
        try:
            path = resource_loader.get_resource_path(f"assets/item_card_icons/{filename}")
            return path.as_uri() if path.exists() else ""
        except OSError:
            return ""

    def _default_flag_index(self) -> int:
        target = self._flags.get("3")
        for index, label in enumerate(self._flag_labels):
            if label == target:
                return index
        return 0

    def _flag_value(self) -> str:
        if 0 <= self._flag_index < len(self._flag_labels):
            return self._flag_labels[self._flag_index].split(" ", 1)[0]
        return "3"

    def refresh(self) -> None:
        if str(self.app.language) != self.current_lang:
            self.on_language_changed()
            return
        try:
            data = self.controller.get_character_data() or {}
            level = int(data.get("角色等级") or 0)
            if level > 0:
                self._character_level = level
                self._level = level
        except (TypeError, ValueError):
            pass
        self.dataChanged.emit()
