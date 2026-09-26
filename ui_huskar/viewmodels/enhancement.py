"""强化模组编辑器 VM：移植 QtEnhancementEditorTab 的全部非渲染逻辑。"""

from __future__ import annotations

import random
import threading
import re
from copy import deepcopy
from collections import Counter
from typing import Any

from PyQt6.QtCore import pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QApplication

from core import b_encoder, item_display_resolver, resource_loader
from core.legit_status import candidate_state, evaluate as evaluate_legit
from core.weapon_generation_logic import sample_composition_parts
from core.serial_import import (
    build_header,
    decode_base85,
    parse_components,
    source_texts,
    split_decoded,
)

from .base import PageViewModel, register

enhancement_data = resource_loader.get_enhancement_data()

_FLAG_CODE_ORDER = ("1", "3", "5", "17", "33", "65", "129")
_PERK_ORDER = (1, 2, 3, 9)
_CAT_KEYS = ("all", "firmware", "sniper", "shotgun", "smg", "pistol", "ar", "gun")
_SUB_KEYS = ("all", "dmg", "crit", "firerate", "acc", "reload", "mag",
             "splashdmg", "splashradius", "ads", "se_dmg", "se_chance", "equip")
_CAT_LABEL_FALLBACKS = {
    "all": "All", "firmware": "Firmware", "sniper": "Sniper", "shotgun": "Shotgun",
    "smg": "SMG", "pistol": "Pistol", "ar": "AR", "gun": "Universal",
}
_SUB_LABEL_FALLBACKS = {
    "all": "All", "dmg": "Damage", "crit": "Crit DMG", "firerate": "Fire Rate",
    "acc": "Accuracy", "reload": "Reload", "mag": "Magazine", "splashdmg": "Splash DMG",
    "splashradius": "Splash Radius", "ads": "ADS", "se_dmg": "SE DMG",
    "se_chance": "SE Chance", "equip": "Equip", "other": "Other",
}
_WEAPON_FIRST = {"Sniper": "sniper", "Shotgun": "shotgun", "SMG": "smg",
                 "Pistol": "pistol", "AR": "ar", "Gun": "gun"}
_CANDIDATE_ORDER = {"legal": 0, "warning": 1, "modified": 2, "unknown": 3}


def _candidate_sort_key(row: dict[str, Any]) -> tuple[int, str]:
    return (_CANDIDATE_ORDER.get(str(row.get("kind") or "unknown"), 3),
            str(row.get("label") or "").casefold())


def _category_state(rows: list[dict[str, Any]]) -> str:
    kinds = {str(row.get("kind") or "unknown") for row in rows}
    if "legal" in kinds:
        return "legal"
    if kinds & {"warning", "modified"}:
        return "warning"
    return "unknown"


@register("enhancement", "EnhancementPage.qml")
class EnhancementViewModel(PageViewModel):
    STRINGS_SECTION = "enhancement_tab"

    dataChanged = pyqtSignal()
    rollFinished = pyqtSignal(bool)

    def __init__(self, app, parent=None):
        super().__init__(app, parent)
        self.current_lang = str(app.language)
        self._character_level = "50"
        self._imported = False
        self._import_header = None
        self._import_seed = None
        self._import_unknown_tokens: list[str] = []
        self._import_unknown_stats: list[int] = []
        self._import_unknown_stacks: dict[int, list[int]] = {}
        self._import_source_name = ""
        self._loading_import = False
        self._mfg_index = 0
        self._rarity_index = 0
        self._level = self._character_level
        self._flag_index = 0
        self._perk_checked: dict[int, bool] = {}
        self._stack_entries: list[dict[str, Any]] = []
        self._stat_entries: list[dict[str, Any]] = []
        self._raw_output = ""
        self._b85_output = ""
        self._encode_error = False
        self._legit_status: dict[str, Any] = {
            "status": "unknown", "label": "未知", "detail": ""
        }
        self._generation_context: dict[str, Any] = {}
        self._roll_results: list[dict[str, Any]] = []
        self._roll_summary = ""
        # 幸运 Roll 的约束与当前编辑器解耦，但默认沿用当前厂商/稀有度。
        self._roll_constraints: dict[str, Any] = {}
        self._roll_count = 5
        self._roll_busy = False
        self._roll_thread: threading.Thread | None = None
        self._rnd_seed = random.randint(1000, 9999)
        self._flags = resource_loader.get_flag_labels(self.current_lang)
        self._flag_labels = [self._flags[k] for k in _FLAG_CODE_ORDER if k in self._flags]
        self._flag_index = self._default_flag_index()
        self._backpack_items: list[dict[str, str]] = []
        self._load_lang_data()
        self._rebuild()
        self._roll_constraints = {
            "manufacturer": self._current_mfg_en(),
            "rarity": self._current_rarity_en(),
        }

    # ------------------------------------------------------------------ #
    # 本地化
    # ------------------------------------------------------------------ #
    def _load_lang_data(self) -> None:
        self.current_lang = str(self.app.language)
        self.localization_data = (
            enhancement_data.get("localization", {}) if enhancement_data else {})
        self._flags = resource_loader.get_flag_labels(self.current_lang)
        self._flag_labels = [self._flags[k] for k in _FLAG_CODE_ORDER if k in self._flags]

    def _(self, text: Any) -> str:
        return self.localization_data.get(str(text), str(text))

    def _display_text(self, english: Any, chinese: Any = "") -> str:
        """Use the translated catalog only for Chinese; keep English source text elsewhere."""
        if self.current_lang == "zh-CN" and str(chinese or "").strip():
            return str(chinese)
        return str(english or "")

    def _loc(self, section: str, key: str, en: str, **fmt: Any) -> str:
        text = self.strings.get(section, {}).get(key) or en
        return text.format(**fmt) if fmt else text

    def on_language_changed(self) -> None:
        imported_serial = self._b85_output if self._imported else ""
        imported_name = self._import_source_name
        imported_flag = self._flag_value() if self._imported else None
        super().on_language_changed()
        self._load_lang_data()
        if imported_serial:
            try:
                self._load_decoded_copy(decode_base85(imported_serial),
                                        source_name=imported_name, state_flags=imported_flag)
            except ValueError:
                self._reset_import()
        else:
            self._rebuild()

    def refresh(self) -> None:
        try:
            data = self.controller.get_character_data() or {}
            level = str(data.get("角色等级") or "")
        except Exception:
            level = ""
        if level and level != self._character_level:
            self._character_level = level
            if not self._imported:
                self._level = level
        if str(self.app.language) != self.current_lang:
            self.on_language_changed()
            return
        self._rebuild()

    # ------------------------------------------------------------------ #
    # QML 属性
    # ------------------------------------------------------------------ #
    @pyqtProperty(bool, notify=dataChanged)
    def dataLoaded(self) -> bool:
        return bool(enhancement_data)

    @pyqtProperty(str, notify=dataChanged)
    def loadErrorText(self) -> str:
        return self._loc("dialogs", "error_load", "Error loading data")

    @pyqtProperty(list, notify=dataChanged)
    def mfgOptions(self) -> list[dict[str, Any]]:
        if not enhancement_data:
            return []
        return [{"label": self._display_text(name, self.localization_data.get(name)), "value": name}
                for name in sorted(enhancement_data.get("manufacturers", {}).keys())]

    @pyqtProperty(int, notify=dataChanged)
    def mfgIndex(self) -> int:
        return self._mfg_index

    @pyqtProperty(list, notify=dataChanged)
    def rarityOptions(self) -> list[dict[str, Any]]:
        mfg_en = self._current_mfg_en()
        if not mfg_en:
            return []
        rarities = enhancement_data["manufacturers"][mfg_en]["rarities"]
        order = ["Common", "Uncommon", "Rare", "Epic", "Legendary"]
        return [{"label": self._display_text(r, self.localization_data.get(r)), "value": r}
                for r in order if r in rarities]

    @pyqtProperty(int, notify=dataChanged)
    def rarityIndex(self) -> int:
        return self._rarity_index

    @pyqtProperty(str, notify=dataChanged)
    def level(self) -> str:
        return self._level

    @pyqtProperty(list, notify=dataChanged)
    def flagOptions(self) -> list[dict[str, Any]]:
        return [{"label": label, "value": label.split(" ", 1)[0]} for label in self._flag_labels]

    @pyqtProperty(int, notify=dataChanged)
    def flagIndex(self) -> int:
        return self._flag_index

    @pyqtProperty(list, notify=dataChanged)
    def perkChecks(self) -> list[dict[str, Any]]:
        mfg_en = self._current_mfg_en()
        if not mfg_en:
            return []
        perk_map = {p["index"]: p for p in enhancement_data["manufacturers"][mfg_en]["perks"]}
        root = str(enhancement_data["manufacturers"][mfg_en]["code"])
        result = []
        for idx in _PERK_ORDER:
            if idx not in perk_map:
                continue
            perk = perk_map[idx]
            full = self._display_text(perk.get("name"), perk.get("name_zh"))
            label, detail = full, ""
            if " -" in full:
                label, detail = full.split(" -", 1)
            else:
                # A few English source rows omit the space before the
                # manufacturer clause (``Trauma Bond-Guns``). Split only when
                # the hyphen is followed by a capitalized clause, preserving
                # names such as ``Extend-a-Friend``.
                match = re.search(r"-(?=[A-Z])", full)
                if match:
                    label, detail = full[:match.start()], full[match.end():]
            result.append({"index": idx, "label": label.strip(), "detail": detail.strip(),
                 "checked": bool(self._perk_checked.get(idx, False)),
                 **candidate_state(self._generation_context, f"{root}:{idx}", self.current_lang,
                                   label=label.strip())})
        return result

    @pyqtProperty(list, notify=dataChanged)
    def stackCategories(self) -> list[dict[str, str]]:
        cats = [{"key": "all", "label": self._loc("categories", "all", "All")}]
        current = self._current_mfg_en()
        for mfg in sorted(enhancement_data.get("manufacturers", {}).keys()):
            if mfg != current:
                cats.append({"key": mfg, "label": self._display_text(mfg, self.localization_data.get(mfg))})
        options = self.stackOptions
        for category in cats:
            rows = options if category["key"] == "all" else [
                row for row in options if row.get("category") == category["key"]]
            category["candidateState"] = _category_state(rows)
        return cats

    @pyqtProperty(list, notify=dataChanged)
    def stackOptions(self) -> list[dict[str, Any]]:
        current = self._current_mfg_en()
        items = []
        for mfg, data in enhancement_data.get("manufacturers", {}).items():
            if mfg == current:
                continue
            for perk in data.get("perks", []):
                if perk.get("index") in _PERK_ORDER:
                    idx = perk["index"]
                    items.append({
                        "key": f"{mfg}:{idx}",
                        "label": f"{self._display_text(perk['name'], perk.get('name_zh'))} — {self._display_text(mfg, self.localization_data.get(mfg))}",
                        "category": mfg,
                        "searchText": f"{perk['name']} {perk.get('name_zh', '')} {mfg} {self.localization_data.get(mfg, '')}",
                        "data": {"mfg": mfg, "idx": idx},
                        **candidate_state(
                            self._generation_context, f"{data['code']}:{idx}", self.current_lang,
                            label=f"{self._display_text(perk['name'], perk.get('name_zh'))} — {self._display_text(mfg, self.localization_data.get(mfg))}"),
                    })
        return sorted(items, key=lambda x: (
            _CANDIDATE_ORDER.get(str(x.get("kind") or "unknown"), 3),
            x["category"], x["data"]["idx"],
        ))

    @pyqtProperty(list, notify=dataChanged)
    def stackEntries(self) -> list[dict[str, Any]]:
        options = {row["key"]: row for row in self.stackOptions}
        return [{**row, **{k: options.get(row["key"], {}).get(k, "")
                           for k in ("kind", "marker", "hint", "badge")}}
                for row in self._stack_entries]

    @pyqtProperty(list, notify=dataChanged)
    def statCategories(self) -> list[dict[str, str]]:
        categories = [{"key": k, "label": self._loc("categories", k, _CAT_LABEL_FALLBACKS.get(k, k))}
                      for k in _CAT_KEYS]
        options = self.statOptions
        for category in categories:
            rows = options if category["key"] == "all" else [
                row for row in options if row.get("category") == category["key"]]
            category["candidateState"] = _category_state(rows)
        return categories

    @pyqtProperty(list, notify=dataChanged)
    def statSubcategories(self) -> list[dict[str, str]]:
        subcategories = [{"key": k, "label": self._loc("subcategories", k, _SUB_LABEL_FALLBACKS.get(k, k))}
                         for k in _SUB_KEYS]
        options = self.statOptions
        for subcategory in subcategories:
            rows = options if subcategory["key"] == "all" else [
                row for row in options if row.get("subcategory") == subcategory["key"]]
            subcategory["candidateState"] = _category_state(rows)
        return subcategories

    @pyqtProperty(list, notify=dataChanged)
    def statOptions(self) -> list[dict[str, Any]]:
        items = []
        for stat in enhancement_data.get("secondary_247", []):
            code = stat["code"]
            name_en = stat["name"]
            firmware = item_display_resolver.equipment_firmware_entry(
                f"247:{code}", "Enhancement", self.current_lang)
            if firmware:
                name = firmware["name"]
                descs = firmware.get("descs") or []
                cat, sub = "firmware", None
                tooltip = "\n".join(f"L{level}: {text}" for level, text in enumerate(descs, 1) if text)
                search_text = " ".join((str(code), firmware.get("internal", ""), name, *descs))
            else:
                name = self._display_text(name_en, self.localization_data.get(name_en))
                cat, sub = self._classify_247(name_en)
                tooltip = name
                search_text = f"{code} {name_en} {name}"
            items.append({
                "key": str(code),
                "label": f"[{code}] {name}",
                "category": cat,
                "subcategory": sub,
                "tooltip": tooltip,
                "searchText": search_text,
                "data": {"code": code},
                **candidate_state(self._generation_context, f"247:{code}", self.current_lang, label=name),
            })
        return sorted(items, key=lambda x: (
            _CANDIDATE_ORDER.get(str(x.get("kind") or "unknown"), 3),
            str(x.get("category") or ""),
            str(x.get("subcategory") or ""),
            str(x.get("label") or "").casefold(),
        ))

    @pyqtProperty(list, notify=dataChanged)
    def statEntries(self) -> list[dict[str, Any]]:
        options = {row["key"]: row for row in self.statOptions}
        return [{**row, **{k: options.get(row["key"], {}).get(k, "")
                           for k in ("kind", "marker", "hint", "badge")}}
                for row in self._stat_entries]

    @pyqtProperty(str, notify=dataChanged)
    def rawOutput(self) -> str:
        return self._raw_output

    @pyqtProperty(str, notify=dataChanged)
    def base85Output(self) -> str:
        return self._b85_output

    @pyqtProperty(bool, notify=dataChanged)
    def encodeError(self) -> bool:
        return self._encode_error

    @pyqtProperty(bool, notify=dataChanged)
    def importedCopy(self) -> bool:
        return self._imported

    @pyqtProperty("QVariantMap", notify=dataChanged)
    def legitBadge(self) -> dict[str, Any]:
        return self._legit_status

    def _group_progress(self, group_names: tuple[str, ...]) -> str:
        specs = [self._generation_context.get("groups", {}).get(name) for name in group_names]
        specs = [spec for spec in specs if isinstance(spec, dict)
                 and (int(spec.get("effective_max", spec.get("max", 0))) > 0 or spec.get("selected"))]
        actual = sum(len(spec.get("selected") or []) for spec in specs)
        low = sum(int(spec.get("effective_min", spec.get("min", 0))) for spec in specs)
        high = sum(int(spec.get("effective_max", spec.get("max", 0))) for spec in specs)
        target = str(low) if low == high else f"{low}–{high}"
        return f"{actual}/{target}" if specs else "—"

    @pyqtProperty(str, notify=dataChanged)
    def coreGuidance(self) -> str:
        return self._group_progress(("core_augment",))

    @pyqtProperty(str, notify=dataChanged)
    def stackGuidance(self) -> str:
        return "跨厂商项通常为魔改" if self.current_lang == "zh-CN" else "Cross-manufacturer parts are usually modified"

    @pyqtProperty(str, notify=dataChanged)
    def statGuidance(self) -> str:
        return self._group_progress(("firmware", "stat_group1", "stat_group2", "stat_group3"))

    @pyqtProperty(str, notify=dataChanged)
    def sourceText(self) -> str:
        texts = source_texts(self.current_lang)
        if self._imported:
            return texts["imported"].format(name=self._import_source_name or "Enhancement")
        return texts["new_source"]

    @pyqtProperty("QVariantMap", notify=dataChanged)
    def sourceTexts(self) -> dict[str, str]:
        return source_texts(self.current_lang)

    @pyqtProperty("QVariantMap", notify=dataChanged)
    def specialThanks(self) -> dict[str, str]:
        return self.strings.get("special_thanks", {})

    @pyqtProperty(list, notify=dataChanged)
    def backpackItems(self) -> list[dict[str, str]]:
        return self._backpack_items

    # ------------------------------------------------------------------ #
    # QML 槽
    # ------------------------------------------------------------------ #
    @pyqtSlot(int)
    def setMfgIndex(self, index: int) -> None:
        if self._imported or not 0 <= index < len(self.mfgOptions):
            return
        if index == self._mfg_index:
            return
        old_mfg = self._current_mfg_en()
        self._mfg_index = index
        self._rarity_index = 0
        self._perk_checked = {}
        if self._roll_constraints.get("manufacturer") == old_mfg:
            self._roll_constraints["manufacturer"] = self._current_mfg_en()
            self._roll_constraints["rarity"] = self._current_rarity_en()
        self._rebuild()

    @pyqtSlot(int)
    def setRarityIndex(self, index: int) -> None:
        if not 0 <= index < len(self.rarityOptions):
            return
        old_rarity = self._current_rarity_en()
        self._rarity_index = index
        if self._roll_constraints.get("rarity") == old_rarity:
            self._roll_constraints["rarity"] = self._current_rarity_en()
        self._rebuild()

    @pyqtSlot(str)
    def setLevel(self, text: str) -> None:
        self._level = text
        self._rebuild()

    @pyqtSlot(int)
    def setFlagIndex(self, index: int) -> None:
        if 0 <= index < len(self._flag_labels):
            self._flag_index = index
            self.dataChanged.emit()

    @pyqtSlot(int, bool)
    def setPerkChecked(self, index: int, checked: bool) -> None:
        self._perk_checked[int(index)] = bool(checked)
        self._rebuild()

    @staticmethod
    def _roll_part_tags(ref: str) -> dict[str, Any]:
        index = item_display_resolver._item_index()
        rules = index.get("weapon_generation_rules") or {}
        return (
            (rules.get("part_selection_tags") or {}).get(str(ref))
            or (index.get("part_refs") or {}).get(str(ref), {}).get("selection_tags")
            or {}
        )

    def _apply_lucky_refs(self, selected: list[str]) -> None:
        root_id = str(enhancement_data["manufacturers"][self._current_mfg_en()]["code"])
        part_refs = item_display_resolver._item_index().get("part_refs") or {}
        core_ids: set[int] = set()
        stat_counts: Counter[str] = Counter()
        for ref in selected:
            owner, sep, part_id = str(ref).partition(":")
            if not sep:
                continue
            group = str((part_refs.get(str(ref)) or {}).get("selection_group") or "").casefold()
            if group == "body":
                continue
            if owner == root_id and part_id.isdigit():
                core_ids.add(int(part_id))
            elif owner == "247":
                stat_counts[part_id] += 1

        self._perk_checked = {index: index in core_ids for index in _PERK_ORDER}
        self._stack_entries = []
        stat_options = {str(row["key"]): row for row in self.statOptions}
        self._stat_entries = []
        for key, count in stat_counts.items():
            option = stat_options.get(key)
            if option is not None:
                self._stat_entries.append({
                    "key": key, "label": option["label"],
                    "data": option["data"], "count": count,
                })

    def _build_lucky_current(self) -> bool:
        """Fill the current manufacturer/rarity template with one natural build."""
        index = item_display_resolver._item_index()
        rules = index.get("weapon_generation_rules") or {}
        mfg_en = self._current_mfg_en()
        if not mfg_en:
            return False
        root_id = str(enhancement_data["manufacturers"][mfg_en]["code"])
        weapon = (rules.get("weapons") or {}).get(root_id) or {}
        context = item_display_resolver.weapon_generation_context(self._raw_output, index=index)
        composition_ref = str(context.get("composition_ref") or "")
        composition = (weapon.get("compositions") or {}).get(composition_ref)
        if not composition:
            self.app.toast(self._loc("dialogs", "gen_valid_first", "No natural generation rule is available for this template."), "warning")
            return False

        rng = random.SystemRandom()
        excluded = set((rules.get("part_availability") or {}).keys())
        for _attempt in range(64):
            selected = sample_composition_parts(
                composition=composition,
                part_types=weapon.get("part_types") or (),
                tags_for_ref=self._roll_part_tags,
                excluded_refs=excluded,
                rng=rng,
            )
            previous = (self._perk_checked, self._stack_entries, self._stat_entries)
            self._apply_lucky_refs(selected)
            self._imported = False
            self._import_header = None
            self._import_seed = None
            self._import_unknown_tokens = []
            self._import_unknown_stats = []
            self._import_unknown_stacks = {}
            self._import_source_name = ""
            self._rnd_seed = rng.randint(1000, 9999)
            self._rebuild(emit=False)
            if self._legit_status.get("rawStatus") == "legal":
                return True
            self._perk_checked, self._stack_entries, self._stat_entries = previous

        self._rebuild(emit=False)
        return False

    def _capture_roll_state(self) -> dict[str, Any]:
        names = (
            "_imported", "_import_header", "_import_seed", "_import_unknown_tokens",
            "_import_unknown_stats", "_import_unknown_stacks", "_import_source_name",
            "_perk_checked", "_stack_entries", "_stat_entries", "_raw_output", "_b85_output",
            "_encode_error", "_legit_status", "_generation_context", "_rnd_seed",
            "_mfg_index", "_rarity_index", "_level", "_flag_index",
        )
        return {name: deepcopy(getattr(self, name)) for name in names}

    def _restore_roll_state(self, state: dict[str, Any]) -> None:
        for name, value in state.items():
            setattr(self, name, deepcopy(value))

    def _enhancement_roll_result(self) -> dict[str, Any]:
        core = []
        for row in self.perkChecks:
            if row.get("checked"):
                core.append({"level": "", "title": row.get("label", ""),
                             "description": row.get("detail", ""), "accent": "#39BCE8"})
        stats = []
        firmware = []
        options = {str(row["key"]): row for row in self.statOptions}
        for entry in self._stat_entries:
            row = options.get(str(entry["key"]), {})
            item = {"level": f"×{entry.get('count', 1)}", "title": row.get("label", entry.get("label", "")),
                    "description": row.get("tooltip", ""), "accent": "#39BCE8"}
            (firmware if row.get("category") == "firmware" else stats).append(item)
        return {
            "name": f"{self._display_text(self._current_mfg_en(), self.localization_data.get(self._current_mfg_en()))} · {'强化模组' if self.current_lang == 'zh-CN' else 'Enhancement'}",
            "manufacturer": self._display_text(self._current_mfg_en(), self.localization_data.get(self._current_mfg_en())),
            "rarity": self._current_rarity_en() or "",
            "level": self._level,
            "status": self._legit_status.get("rawStatus", "unknown"),
            "statusLabel": self._legit_status.get("label", ""),
            "serial": self._raw_output,
            "base85": self._b85_output,
            "core": core,
            "stats": stats,
            "firmware": firmware,
        }

    @pyqtProperty("QVariantMap", notify=dataChanged)
    def rollConstraintOptions(self) -> dict[str, Any]:
        random_label = "随机" if self.current_lang == "zh-CN" else "Random"
        mfgs = [{"label": random_label, "value": None}, *self.mfgOptions]
        rarity_values = []
        for data in enhancement_data.get("manufacturers", {}).values():
            for value in data.get("rarities", {}):
                if value not in rarity_values:
                    rarity_values.append(value)
        order = {value: index for index, value in enumerate(("Common", "Uncommon", "Rare", "Epic", "Legendary"))}
        rarities = [{"label": random_label, "value": None}]
        rarities.extend({"label": self._display_text(value, self.localization_data.get(value)), "value": value}
                        for value in sorted(rarity_values, key=lambda value: order.get(value, 99)))
        return {"manufacturers": mfgs, "rarities": rarities}

    @pyqtSlot("QVariantMap", result=int)
    def rollMatchCount(self, constraints) -> int:
        constraints = dict(constraints or {})
        manufacturers = list(enhancement_data.get("manufacturers", {}).items())
        if constraints.get("manufacturer"):
            manufacturers = [(name, data) for name, data in manufacturers
                             if name == str(constraints["manufacturer"])]
        count = 0
        for _name, data in manufacturers:
            rarities = data.get("rarities", {})
            if constraints.get("rarity"):
                count += int(str(constraints["rarity"]) in rarities)
            else:
                count += len(rarities)
        return count

    def _reset_roll_template(self) -> None:
        self._perk_checked = {}
        self._stack_entries = []
        self._stat_entries = []
        self._imported = False
        self._import_header = None
        self._import_seed = None
        self._import_unknown_tokens = []
        self._import_unknown_stats = []
        self._import_unknown_stacks = {}
        self._import_source_name = ""

    def _roll_impl(self, constraints, count: int, *, notify: bool = True) -> bool:
        constraints = {key: value for key, value in dict(constraints or {}).items()
                       if value is not None and value != ""}
        self._roll_constraints = constraints
        self._roll_count = max(1, min(50, int(count)))
        candidates = []
        for mfg, data in enhancement_data.get("manufacturers", {}).items():
            if constraints.get("manufacturer") and mfg != str(constraints["manufacturer"]):
                continue
            for rarity in data.get("rarities", {}):
                if constraints.get("rarity") and rarity != str(constraints["rarity"]):
                    continue
                candidates.append((mfg, rarity))
        if not candidates:
            if notify:
                self.app.toast(self.rollTexts.get("no_legal_result", "No legal result"), "warning")
            self._roll_results = []
            self._roll_summary = ""
            self.rollFinished.emit(False)
            return False

        saved = self._capture_roll_state()
        rng = random.SystemRandom()
        results = []
        seen = set()
        try:
            for _index in range(self._roll_count):
                result = None
                for _attempt in range(24):
                    mfg, rarity = rng.choice(candidates)
                    mfg_index = next((index for index, row in enumerate(self.mfgOptions)
                                      if row.get("value") == mfg), 0)
                    self._mfg_index = mfg_index
                    rarity_index = next((index for index, row in enumerate(self.rarityOptions)
                                         if row.get("value") == rarity), 0)
                    self._rarity_index = rarity_index
                    self._reset_roll_template()
                    self._rebuild(emit=False)
                    if not self._build_lucky_current():
                        continue
                    result = self._enhancement_roll_result()
                    signature = (
                        result.get("manufacturer"), result.get("rarity"),
                        tuple(row.get("title") for row in result.get("core", [])),
                        tuple(row.get("title") for row in result.get("stats", [])),
                        tuple(row.get("title") for row in result.get("firmware", [])),
                    )
                    if signature in seen:
                        result = None
                        continue
                    seen.add(signature)
                    break
                if result is not None:
                    results.append(result)
        finally:
            self._restore_roll_state(saved)
        self._roll_results = results
        self._roll_summary = (
            f"已生成 {len(results)} 个合法强化模组" if self.current_lang == "zh-CN"
            else f"Generated {len(results)} legal enhancements"
        )
        self.dataChanged.emit()
        self.rollFinished.emit(bool(results))
        return bool(results)

    @pyqtSlot("QVariantMap", int, result=bool)
    def roll(self, constraints, count: int) -> bool:
        if self._roll_busy:
            return False
        return self._roll_impl(constraints, count)

    def _start_roll_thread(self, constraints, count: int) -> bool:
        if self._roll_busy:
            return False
        self._roll_busy = True
        self.dataChanged.emit()

        def worker() -> None:
            try:
                self._roll_impl(dict(constraints or {}), int(count), notify=False)
            finally:
                self._roll_busy = False
                self._roll_thread = None
                self.dataChanged.emit()

        self._roll_thread = threading.Thread(target=worker, name="huskar-enhancement-roll", daemon=True)
        self._roll_thread.start()
        return True

    @pyqtSlot("QVariantMap", int, result=bool)
    def startRoll(self, constraints, count: int) -> bool:
        return self._start_roll_thread(constraints, count)

    @pyqtSlot(result=bool)
    def startQuickRoll(self) -> bool:
        return self._start_roll_thread(self._roll_constraints, self._roll_count)

    @pyqtSlot(result=bool)
    def quickRoll(self) -> bool:
        return self.roll(self._roll_constraints, self._roll_count)

    @pyqtSlot(result=bool)
    def luckyRoll(self) -> bool:
        return self.quickRoll()

    @pyqtProperty(list, notify=rollFinished)
    def rollResults(self) -> list[dict[str, Any]]:
        return self._roll_results

    @pyqtProperty(str, notify=rollFinished)
    def rollSummaryText(self) -> str:
        return self._roll_summary

    @pyqtProperty("QVariantMap", notify=dataChanged)
    def rollConstraints(self) -> dict[str, Any]:
        return dict(self._roll_constraints)

    @pyqtProperty(int, notify=dataChanged)
    def rollCount(self) -> int:
        return self._roll_count

    @pyqtProperty(bool, notify=dataChanged)
    def rollBusy(self) -> bool:
        return self._roll_busy

    @pyqtProperty("QVariantMap", notify=dataChanged)
    def rollTexts(self) -> dict[str, str]:
        zh = self.current_lang == "zh-CN"
        return {
            "lucky": "手气不错" if zh else "I'm Feeling Lucky",
            "rolling": "生成中…" if zh else "Generating…",
            "results_title": "强化模组随机结果" if zh else "Enhancement Roll Results",
            "select_result": "从左侧选择一个强化模组" if zh else "Select an enhancement",
            "add_one": "加入背包" if zh else "Add to Backpack",
            "copy": "复制 Base85" if zh else "Copy Base85",
            "constraints_title": "随机选项" if zh else "Roll Options",
            "manufacturer": "厂商" if zh else "Manufacturer",
            "rarity": "稀有度" if zh else "Rarity",
            "count": "数量" if zh else "Count",
            "matches": "可用模板：{count}" if zh else "Matching templates: {count}",
            "no_matches": "没有可用模板" if zh else "No matching templates",
            "roll": "开始 Roll" if zh else "Roll",
            "no_legal_result": "没有可生成的合法强化模组" if zh else "No legal enhancement result",
            "core": "核心强化 / 厂商专长" if zh else "Core / Manufacturer Perks",
            "stats": "次要属性" if zh else "Secondary Stats",
            "firmware": "固件" if zh else "Firmware",
            "add_all": self.app.tr("weapon_gen_tab.buttons.add_all", default="全部加入背包" if zh else "Add All"),
            "add_done": self.app.tr("weapon_gen_tab.dialogs.roll_add_done",
                                    default="已加入 {success} 件，失败 {fail} 件" if zh else "Added {success}; failed {fail}"),
        }

    @pyqtSlot("QVariantList")
    def addLuckyRollToBackpack(self, indices) -> None:
        results = self._roll_results
        serials = [results[int(index)].get("base85", "") for index in indices or []
                   if 0 <= int(index) < len(results)]
        self.app.add_serials_to_backpack(serials, self._flag_value(), self.rollTexts["add_done"])

    @pyqtSlot()
    def addAllLuckyRolls(self) -> None:
        """Roll 结果全部加入背包（离线写存档 / live 分批刷进游戏）。"""
        self.addLuckyRollToBackpack(list(range(len(self._roll_results))))

    @pyqtSlot(int)
    def copyLuckyRoll(self, index: int) -> None:
        if 0 <= int(index) < len(self._roll_results):
            QApplication.clipboard().setText(self._roll_results[int(index)].get("base85", ""))
            self.app.toast(self._loc("dialogs", "copy_b85_msg", "Copied Base85"), "success")

    def _add_stack_key(self, key: str) -> bool:
        option = next((o for o in self.stackOptions if o["key"] == str(key)), None)
        if option is None:
            return False
        # 主线 stack picker 为 stackable=False 且禁用重复来源
        if any(e["key"] == str(key) for e in self._stack_entries):
            return False
        self._stack_entries.append({"key": str(key), "label": option["label"],
                                    "data": option["data"], "count": 1})
        return True

    @pyqtSlot(str)
    def addStackItem(self, key: str) -> None:
        if self._add_stack_key(key):
            self._rebuild()

    @pyqtSlot(list)
    def addStackItems(self, keys: list) -> None:
        changed = False
        for key in keys or []:
            changed = self._add_stack_key(str(key)) or changed
        if changed:
            self._rebuild()

    @pyqtSlot(int)
    def removeStackItem(self, index: int) -> None:
        if 0 <= index < len(self._stack_entries):
            self._stack_entries.pop(index)
            self._rebuild()

    @pyqtSlot()
    def clearStack(self) -> None:
        self._stack_entries = []
        self._rebuild()

    def _add_stat_key(self, key: str) -> bool:
        option = next((o for o in self.statOptions if o["key"] == str(key)), None)
        if option is None:
            return False
        for entry in self._stat_entries:
            if entry["key"] == str(key):
                entry["count"] += 1
                return True
        self._stat_entries.append({"key": str(key), "label": option["label"],
                                   "data": option["data"], "count": 1})
        return True

    @pyqtSlot(str)
    def addStatItem(self, key: str) -> None:
        if self._add_stat_key(key):
            self._rebuild()

    @pyqtSlot(list)
    def addStatItems(self, keys: list) -> None:
        changed = False
        for key in keys or []:
            changed = self._add_stat_key(str(key)) or changed
        if changed:
            self._rebuild()

    @pyqtSlot(int)
    def removeStatItem(self, index: int) -> None:
        if 0 <= index < len(self._stat_entries):
            self._stat_entries.pop(index)
            self._rebuild()

    @pyqtSlot(int, int)
    def setStatItemCount(self, index: int, count: int) -> None:
        if 0 <= index < len(self._stat_entries):
            self._stat_entries[index]["count"] = max(1, int(count))
            self._rebuild()

    @pyqtSlot(list, int)
    def setStatItemsCount(self, indices: list, count: int) -> None:
        changed = False
        for index in indices or []:
            index = int(index)
            if 0 <= index < len(self._stat_entries):
                new_count = max(1, int(count))
                if new_count != self._stat_entries[index]["count"]:
                    self._stat_entries[index]["count"] = new_count
                    changed = True
        if changed:
            self._rebuild()

    @pyqtSlot(list, int)
    def stepStatItemsCount(self, indices: list, delta: int) -> None:
        """已选 247 条目相对步进（每个目标各自 ±delta，下限 1）；一次重建。"""
        changed = False
        for index in indices or []:
            index = int(index)
            if 0 <= index < len(self._stat_entries):
                new_count = max(1, int(self._stat_entries[index].get("count", 1)) + int(delta))
                if new_count != self._stat_entries[index]["count"]:
                    self._stat_entries[index]["count"] = new_count
                    changed = True
        if changed:
            self._rebuild()

    @pyqtSlot()
    def clearStat(self) -> None:
        self._stat_entries = []
        self._rebuild()

    @pyqtSlot()
    def copyRawToClipboard(self) -> None:
        QApplication.clipboard().setText(self._raw_output)
        self.app.toast(self._loc("dialogs", "copy_raw_msg", "Copied raw"), "success")

    @pyqtSlot()
    def copyBase85ToClipboard(self) -> None:
        QApplication.clipboard().setText(self._b85_output)
        self.app.toast(self._loc("dialogs", "copy_b85_msg", "Copied base85"), "success")

    @pyqtSlot()
    def addToBackpack(self) -> None:
        if not self._b85_output or self._encode_error:
            self.app.toast(self._loc("dialogs", "gen_valid_first", "Generate first"), "warning")
            return
        self.app.addSerialToBackpack(self._b85_output, self._flag_value())

    @pyqtSlot(result=int)
    def prepareBackpackImport(self) -> int:
        texts = source_texts(self.current_lang)
        if not self.controller.yaml_obj:
            self.app.toast(texts["no_save"], "warning")
            return 0
        try:
            items = [it for it in self.controller.get_all_items()
                     if it.get("type_en") == "Enhancement" and it.get("container") == "Backpack"]
        except Exception:
            items = []
        self._backpack_items = []
        for item in items:
            name = str(item.get("name") or item.get("manufacturer") or item.get("type") or "Item")
            detail = " · ".join(
                str(v) for v in (item.get("manufacturer"), item.get("type"),
                                 f"Lv.{item.get('level', '?')}") if v)
            self._backpack_items.append({
                "name": name, "detail": detail,
                "decoded": str(item.get("decoded_full", "")),
                "flag": str(item.get("state_flags", "") or ""),
            })
        self.dataChanged.emit()
        return len(self._backpack_items)

    @pyqtSlot(int)
    def importBackpackItem(self, index: int) -> None:
        if not 0 <= index < len(self._backpack_items):
            return
        item = self._backpack_items[index]
        texts = source_texts(self.current_lang)
        try:
            self._load_decoded_copy(item["decoded"], source_name=item["name"] or "Enhancement",
                                    state_flags=item["flag"])
        except ValueError as exc:
            self._reset_import()
            self.app.toast(f"{texts['import_error']}: {exc}", "error")

    @pyqtSlot(str)
    def importBase85(self, serial: str) -> None:
        serial = (serial or "").strip()
        if not serial:
            return
        texts = source_texts(self.current_lang)
        try:
            decoded = decode_base85(serial)
            self._load_decoded_copy(decoded, source_name="Base85")
        except ValueError as exc:
            self._reset_import()
            self.app.toast(f"{texts['import_error']}: {exc}", "error")

    @pyqtSlot()
    def resetSource(self) -> None:
        self._reset_import()

    def open_item_serial(self, item: dict) -> None:
        """公开入口：从 YAML 编辑器/物品快照跳转加载（对齐主线同名方法）。"""
        flags = item.get("state_flags")
        try:
            flags = int(str(flags).strip()) if str(flags).strip() else None
        except ValueError:
            flags = None
        self._load_decoded_copy(str(item.get("decoded_full", "") or ""),
                                source_name=str(item.get("name", "Backpack") or "Backpack"),
                                state_flags=flags)

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _current_mfg_en(self) -> str | None:
        options = self.mfgOptions
        if 0 <= self._mfg_index < len(options):
            return options[self._mfg_index]["value"]
        return None

    def _current_rarity_en(self) -> str | None:
        options = self.rarityOptions
        if 0 <= self._rarity_index < len(options):
            return options[self._rarity_index]["value"]
        return None

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

    def _set_flag_value(self, value) -> None:
        target = str("3" if value in (None, "") else value).strip().split(" ", 1)[0]
        for index, label in enumerate(self._flag_labels):
            if label.split(" ", 1)[0] == target:
                self._flag_index = index
                return

    def _stat_subcategory(self, name_en: str) -> str:
        n = name_en.lower()
        checks = [
            ("crit dmg", "crit"), ("splash dmg", "splashdmg"), ("splash radius", "splashradius"),
            ("spalsh radius", "splashradius"), ("status effect dmg", "se_dmg"),
            ("status effect chance", "se_chance"), ("status effect smg", "se_dmg"),
            ("effect chance", "se_chance"), ("fire rate", "firerate"), ("reload", "reload"),
            ("mag", "mag"), ("ads", "ads"), ("acc", "acc"), ("equip", "equip"),
            ("splash", "splashdmg"), ("dmg", "dmg"),
        ]
        for kw, key in checks:
            if kw in n:
                return key
        return "other"

    def _classify_247(self, name_en: str) -> tuple[str, str | None]:
        first = name_en.split(" ", 1)[0] if name_en else ""
        category = _WEAPON_FIRST.get(first, "firmware")
        if category == "firmware":
            return "firmware", None
        return category, self._stat_subcategory(name_en)

    def _reset_import(self) -> None:
        self._imported = False
        self._import_header = None
        self._import_seed = None
        self._import_unknown_tokens = []
        self._import_unknown_stats = []
        self._import_unknown_stacks = {}
        self._import_source_name = ""
        self._level = self._character_level
        self._rnd_seed = random.randint(1000, 9999)
        self._flag_index = self._default_flag_index()
        self._stack_entries = []
        self._stat_entries = []
        self._perk_checked = {}
        self._rebuild()

    @staticmethod
    def _component_text(token) -> str:
        if token["type"] == "simple":
            return f"{{{token['id']}}}"
        if token["type"] == "single":
            return f"{{{token['id']}:{token['value']}}}"
        if token["type"] == "group":
            values = " ".join(map(str, token["children"]))
            return f"{{{token['id']}:[{values}]}}"
        return f'"{token["value"]}"'

    def _load_decoded_copy(self, decoded: str, *, source_name: str, state_flags=None) -> bool:
        header = split_decoded(decoded)
        mfg_en = next((name for name, data in enhancement_data["manufacturers"].items()
                       if data.get("code") == header["mfg_id"]), None)
        if not mfg_en:
            raise ValueError(source_texts(self.current_lang)["wrong_type"])

        tokens = list(parse_components(header["component"]))
        rarity_by_code = {int(code): name for name, code in
                          enhancement_data["manufacturers"][mfg_en]["rarities"].items()}
        rarity_by_247 = {int(code): name for name, code in enhancement_data["rarity_map_247"].items()}
        rarity_en = next((rarity_by_code[token["id"]] for token in tokens
                          if token["type"] == "simple" and token["id"] in rarity_by_code), None)
        if rarity_en is None:
            rarity_en = next((rarity_by_247[token["value"]] for token in tokens
                              if token["type"] == "single" and token["id"] == 247
                              and token["value"] in rarity_by_247), None)
        if rarity_en is None:
            raise ValueError("Enhancement rarity is not recognized.")

        known_stats = {int(item["code"]) for item in enhancement_data.get("secondary_247", [])}
        mfg_by_code = {int(data["code"]): name for name, data in enhancement_data["manufacturers"].items()}
        known_stack_keys = {
            (int(data["code"]), int(perk["index"]))
            for name, data in enhancement_data["manufacturers"].items() if name != mfg_en
            for perk in data.get("perks", []) if perk.get("index") in _PERK_ORDER
        }
        known_perks = {int(perk["index"]) for perk in
                       enhancement_data["manufacturers"][mfg_en].get("perks", [])}
        perk_ids = set()
        stats = Counter()
        stacks = Counter()
        unknown_stats = []
        unknown_stacks: dict[int, list[int]] = {}
        unknown_tokens = []

        for token in tokens:
            token_type = token["type"]
            if token_type == "simple":
                if token["id"] in rarity_by_code:
                    continue
                if token["id"] in known_perks:
                    perk_ids.add(token["id"])
                else:
                    unknown_tokens.append(self._component_text(token))
            elif token_type == "single" and token["id"] == 247:
                if token["value"] in rarity_by_247:
                    continue
                if token["value"] in known_stats:
                    stats[token["value"]] += 1
                else:
                    unknown_tokens.append(self._component_text(token))
            elif token_type == "group" and token["id"] == 247:
                for code in token["children"]:
                    if code in known_stats:
                        stats[code] += 1
                    else:
                        unknown_stats.append(code)
            elif token_type == "group" and token["id"] in mfg_by_code:
                for code in token["children"]:
                    if (token["id"], code) in known_stack_keys:
                        stacks[(token["id"], code)] += 1
                    else:
                        unknown_stacks.setdefault(token["id"], []).append(code)
            else:
                unknown_tokens.append(self._component_text(token))

        self._loading_import = True
        try:
            self._imported = True
            self._import_header = header
            self._import_seed = header["seed"]
            self._import_unknown_tokens = unknown_tokens
            self._import_unknown_stats = unknown_stats
            self._import_unknown_stacks = unknown_stacks
            self._import_source_name = source_name

            self._mfg_index = next(i for i, o in enumerate(self.mfgOptions) if o["value"] == mfg_en)
            self._rarity_index = next(i for i, o in enumerate(self.rarityOptions) if o["value"] == rarity_en)
            self._level = str(header["level"])
            self._perk_checked = {idx: idx in perk_ids for idx in _PERK_ORDER}
            self._stack_entries = []
            self._stat_entries = []
            for (parent, code), count in stacks.items():
                label = next((o["label"] for o in self.stackOptions
                              if o["key"] == f"{mfg_by_code[parent]}:{code}"), f"{mfg_by_code[parent]}:{code}")
                self._stack_entries.append({
                    "key": f"{mfg_by_code[parent]}:{code}", "label": label,
                    "data": {"mfg": mfg_by_code[parent], "idx": code}, "count": count})
            for code, count in stats.items():
                label = next((o["label"] for o in self.statOptions if o["key"] == str(code)), f"[{code}]")
                self._stat_entries.append({
                    "key": str(code), "label": label, "data": {"code": code}, "count": count})
            self._set_flag_value(state_flags)
        finally:
            self._loading_import = False
        self._rebuild()
        return True

    def _rebuild(self, *, emit: bool = True) -> None:
        if self._loading_import or not enhancement_data:
            return
        parts = []
        mfg_en = self._current_mfg_en()
        if not mfg_en:
            return
        mfg_code = enhancement_data["manufacturers"][mfg_en]["code"]
        level_val = self._level or self._character_level
        seed = self._import_seed if self._imported else self._rnd_seed
        if self._imported:
            parts.append(build_header(self._import_header, mfg_id=mfg_code,
                                      level=level_val, seed=seed) + "||")
        else:
            parts.append(f"{mfg_code}, 0, 1, {level_val}| 2, {seed}||")
        rarity_en = self._current_rarity_en()
        if not rarity_en:
            return
        rarity_code = enhancement_data["manufacturers"][mfg_en]["rarities"][rarity_en]
        parts.append(f"{{{rarity_code}}}")
        rarity_247_code = enhancement_data["rarity_map_247"][rarity_en]
        parts.append(f"{{247:{rarity_247_code}}}")
        for index in _PERK_ORDER:
            if self._perk_checked.get(index):
                parts.append(f"{{{index}}}")

        stacked_perks: dict[int, list[int]] = {}
        for e in self._stack_entries:
            mfg_code_stack = enhancement_data["manufacturers"][e["data"]["mfg"]]["code"]
            stacked_perks.setdefault(mfg_code_stack, [])
            for _ in range(int(e.get("count", 1))):
                stacked_perks[mfg_code_stack].append(e["data"]["idx"])
        if self._imported:
            for code, indices in self._import_unknown_stacks.items():
                stacked_perks.setdefault(code, []).extend(indices)
        for code, indices in stacked_perks.items():
            parts.append(f"{{{code}:[{' '.join(map(str, sorted(indices)))}]}}")

        stats_247 = list(self._import_unknown_stats) if self._imported else []
        for e in self._stat_entries:
            for _ in range(int(e.get("count", 1))):
                stats_247.append(e["data"]["code"])
        if stats_247:
            parts.append(f"{{247:[{' '.join(map(str, stats_247))}]}}")

        if self._imported:
            parts.extend(self._import_unknown_tokens)

        self._raw_output = " ".join(parts).replace("  ", " ").strip() + "|"
        self._generation_context = item_display_resolver.weapon_generation_context(self._raw_output)
        encoded_serial, err = b_encoder.encode_to_base85(self._raw_output)
        self._encode_error = bool(err)
        self._b85_output = f"Error: {err}" if err else encoded_serial
        self._legit_status = evaluate_legit(self._raw_output, self.current_lang)
        if emit:
            self.dataChanged.emit()
