"""职业模组编辑器 VM：移植 QtClassModEditorTab 的全部非渲染逻辑。"""

from __future__ import annotations

import random
import re
import html
import threading
from copy import deepcopy
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from PyQt6.QtCore import pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QApplication

from core import b_encoder, item_display_resolver, resource_loader
from core.legit_status import candidate_state, evaluate as evaluate_legit
from core.serial_import import (
    build_header,
    decode_base85,
    parse_components,
    source_texts,
    split_decoded,
)

from .base import PageViewModel, register

_FLAG_CODE_ORDER = ("1", "3", "5", "17", "33", "65", "129")
_RARITIES = ("Common", "Uncommon", "Rare", "Epic", "Legendary")
_CANDIDATE_ORDER = {"legal": 0, "warning": 1, "modified": 2, "unknown": 3}


def _candidate_sort_key(row: dict[str, Any]) -> tuple[int, str]:
    """Keep immediately addable rows at the top of every picker view."""
    return (_CANDIDATE_ORDER.get(str(row.get("kind") or "unknown"), 3),
            str(row.get("label") or "").casefold())


def _category_state(rows: list[dict[str, Any]]) -> str:
    """Return the compact green/yellow state used by filter chips."""
    kinds = {str(row.get("kind") or "unknown") for row in rows}
    if "legal" in kinds:
        return "legal"
    if kinds & {"warning", "modified"}:
        return "warning"
    return "unknown"



@lru_cache(maxsize=None)
def _skill_icon_url(icon_file: str, class_name: str) -> str:
    """file:// URL of a skill icon, "" when missing (cached: option lists ask for every skill)."""
    if not icon_file:
        return ""
    try:
        path = resource_loader.get_class_mods_image_path(class_name, icon_file)
        if path and Path(path).exists():
            return Path(path).as_uri()
    except Exception:
        pass
    return ""


@register("class_mod", "ClassModPage.qml")
class ClassModViewModel(PageViewModel):
    STRINGS_SECTION = "class_mod_tab"

    CLASS_IDS = {"Amon": 255, "Harlowe": 259, "Rafa": 256, "Vex": 254, "C4sh": 404}
    CLASS_NAMES = ["Amon", "Harlowe", "Rafa", "Vex", "C4sh"]

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
        self._import_unknown_perks: list[str] = []
        self._import_skill_codes: dict[str, list[int]] = {}
        self._import_skill_counts: dict[str, int] = {}
        self._import_source_name = ""
        self._loading_import = False
        self._class_index = 0
        self._rarity_index = 4  # Legendary
        self._name_index = 0
        self._level = self._character_level
        self._seed = str(random.randint(1, 9999))
        self._flag_index = 0
        self._leg_entries: list[dict[str, Any]] = []
        self._skill_entries: list[dict[str, Any]] = []
        self._perk_entries: list[dict[str, Any]] = []
        self._raw_output = ""
        self._b85_output = ""
        self._encode_error = False
        self._legit_status: dict[str, Any] = {
            "status": "unknown", "label": "未知", "detail": ""
        }
        self._generation_context: dict[str, Any] = {}
        self._roll_results: list[dict[str, Any]] = []
        self._roll_summary = ""
        # 与装备页一致：幸运 Roll 使用独立的约束状态，不改写当前编辑器。
        self._roll_constraints: dict[str, Any] = {}
        self._roll_count = 5
        self._roll_busy = False
        self._roll_thread: threading.Thread | None = None
        self._flags = resource_loader.get_flag_labels(self.current_lang)
        self._flag_labels = [self._flags[k] for k in _FLAG_CODE_ORDER if k in self._flags]
        self._flag_index = self._default_flag_index()
        self._backpack_items: list[dict[str, str]] = []
        self._load_csv_data()
        self._load_lang_data()
        self._rebuild()
        self._roll_constraints = {
            "class": self._current_class_en(),
            "rarity": self._current_rarity_en(),
        }

    # ------------------------------------------------------------------ #
    # 数据
    # ------------------------------------------------------------------ #
    def _load_csv_data(self) -> None:
        self.names_data = resource_loader.load_class_mods_csv("Class_rarity_name.csv")
        self.skills_data = resource_loader.load_class_mods_csv("Skills.csv")
        self.perks_data = resource_loader.load_class_mods_csv("Class_perk.csv")
        self.legendary_map_data = resource_loader.load_class_mods_csv("Class_legendary_map.csv")
        self._build_data_indexes()

    def _build_data_indexes(self) -> None:
        discovered_classes = {}
        for row in [*self.names_data, *self.skills_data]:
            class_id = str(row.get("class_ID", "")).strip()
            class_name = str(row.get("class_name", "")).strip()
            if class_id.isdigit() and class_name:
                discovered_classes[class_name] = int(class_id)
        if discovered_classes:
            known = [name for name in type(self).CLASS_NAMES if name in discovered_classes]
            self.CLASS_NAMES = known + [name for name in discovered_classes if name not in known]
            self.CLASS_IDS = {**type(self).CLASS_IDS, **discovered_classes}

        self.skills_by_class: dict[str, list] = {}
        for skill in self.skills_data:
            self.skills_by_class.setdefault(skill.get("class_ID", ""), []).append(skill)
        self.names_by_class_rarity: dict[tuple, list] = {}
        for name in self.names_data:
            key = (name.get("class_ID", ""), name.get("rarity", ""))
            self.names_by_class_rarity.setdefault(key, []).append(name)
        self.perks_by_id = {p["perk_ID"]: p for p in self.perks_data}

    def _load_lang_data(self) -> None:
        self.current_lang = str(self.app.language)
        if self.current_lang in ("en-US", "ru", "ua"):
            self.localization = {}
        else:
            self.localization = resource_loader.load_class_mods_json("class_localization.json") or {}
        self._flags = resource_loader.get_flag_labels(self.current_lang)
        self._flag_labels = [self._flags[k] for k in _FLAG_CODE_ORDER if k in self._flags]

    def _(self, text: Any) -> str:
        return self.localization.get(str(text), str(text))

    def _pick_text(self, zh: str, en: str) -> str:
        return zh if self.current_lang == "zh-CN" else en

    def _loc(self, section: str, key: str, en: str, **fmt: Any) -> str:
        text = self.strings.get(section, {}).get(key) or en
        return text.format(**fmt) if fmt else text

    def on_language_changed(self) -> None:
        imported_serial = self._b85_output if self._imported and not self._encode_error else ""
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
        return bool(self.names_data)

    @pyqtProperty(list, notify=dataChanged)
    def classOptions(self) -> list[dict[str, Any]]:
        return [{"label": self._(c), "value": c} for c in self.CLASS_NAMES]

    @pyqtProperty(int, notify=dataChanged)
    def classIndex(self) -> int:
        return self._class_index

    @pyqtProperty(list, notify=dataChanged)
    def rarityOptions(self) -> list[dict[str, Any]]:
        return [{"label": self._(r), "value": r} for r in _RARITIES]

    @pyqtProperty(int, notify=dataChanged)
    def rarityIndex(self) -> int:
        return self._rarity_index

    @pyqtProperty(list, notify=dataChanged)
    def nameOptions(self) -> list[dict[str, Any]]:
        options = []
        for row in self._name_rows():
            name_en = row.get("name_EN", "")
            name_zh = row.get("name_ZH", "")
            display = name_zh if (self.current_lang == "zh-CN" and name_zh) else name_en
            code = str(row.get("name_code", ""))
            effect = self._legendary_effect(code) if self.legendaryEnabled else ""
            options.append({"label": display, "value": display,
                            "tooltip": effect, "detail": effect})
        return options

    @pyqtProperty(int, notify=dataChanged)
    def nameIndex(self) -> int:
        return self._name_index

    @pyqtProperty(str, notify=dataChanged)
    def level(self) -> str:
        return self._level

    @pyqtProperty(str, notify=dataChanged)
    def seed(self) -> str:
        return self._seed

    @pyqtProperty(list, notify=dataChanged)
    def flagOptions(self) -> list[dict[str, Any]]:
        return [{"label": label, "value": label.split(" ", 1)[0]} for label in self._flag_labels]

    @pyqtProperty(int, notify=dataChanged)
    def flagIndex(self) -> int:
        return self._flag_index

    @pyqtProperty(bool, notify=dataChanged)
    def legendaryEnabled(self) -> bool:
        return self._current_rarity_en() == "Legendary"

    @pyqtProperty("QVariantMap", notify=dataChanged)
    def legitBadge(self) -> dict[str, Any]:
        return self._legit_status

    def _candidate(self, ref: str, label: str = "") -> dict[str, Any]:
        return candidate_state(self._generation_context, ref, self.current_lang, label=label)

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
    def legendaryGuidance(self) -> str:
        return "额外名称均为魔改" if self.current_lang == "zh-CN" else "Extra names are modified"

    @pyqtProperty(str, notify=dataChanged)
    def skillGuidance(self) -> str:
        return self._group_progress(("passive_points", "action_skill_mod"))

    @pyqtProperty(str, notify=dataChanged)
    def perkGuidance(self) -> str:
        return self._group_progress(("stat_group1", "stat_group2", "stat_group3", "firmware", "special_passive"))

    def _legendary_effect(self, name_code: str) -> str:
        """Resolve the effect/red text belonging to one legendary name.

        A legendary class mod stores the visible name and its item-card body as a
        pair.  Looking up the name alone only shows the label; temporarily
        substituting the pair into the current serial lets the resolver return the
        authoritative localized effect text from the pipeline uistat index.
        """
        class_id = str(self.CLASS_IDS.get(self._current_class_en(), 0))
        mapping = next((row for row in self.legendary_map_data
                        if str(row.get("class_ID", "")) == class_id
                        and str(row.get("L_name_ID", "")) == str(name_code)), None)
        if not mapping:
            return ""
        card_id = str(mapping.get("item_card_ID", ""))
        if not card_id.isdigit():
            return ""
        raw = self._raw_output or ""
        # During an import/rebuild the selector can be evaluated before the
        # new raw serial is published. Resolve against a minimal serial for
        # the current class in that window instead of returning an empty tip.
        if not re.match(rf"\s*{re.escape(class_id)}\s*,", raw):
            raw = f"{class_id}, 0, 1, {self._level or self._character_level}| 2, {self._seed}||"
        if re.search(r"\{\d+\}\s+\{\d+\}", raw):
            candidate = re.sub(r"\{\d+\}\s+\{\d+\}",
                               f"{{{card_id}}} {{{name_code}}}", raw, count=1)
        else:
            candidate = raw.rstrip("|") + f" {{{card_id}}} {{{name_code}}}|"
        try:
            details = item_display_resolver.resolve_classmod_card_details(
                candidate, self.current_lang, 64)
        except Exception:
            return ""
        # NCS keeps the named legendary's small exclusive bonus in a separate
        # red-text channel. It is not a 234 perk and must travel with the name
        # into tooltips and Roll results as well.
        pieces = [entry.get("text", "") for entry in details.get("effects") or []]
        pieces.extend(details.get("display_red_texts") or details.get("red_texts") or [])
        # The resolver uses the game's [primary]/[secondary]/[element] markup.
        # Convert it to a small safe HTML subset for QML RichText and intentionally
        # omit red text: the effect itself is the useful information here.
        cleaned = []
        for piece in pieces:
            text = html.escape(str(piece or ""), quote=False)
            colors = {
                "primary": "#4a90e2", "secondary": "#d7dee8", "fire": "#ef6c45",
                "cryo": "#62c4e8", "shock": "#c9a8ff", "corrosive": "#8ccf5f",
                "radiation": "#e6d35c", "poison": "#9bd36a", "nowrap": "#d7dee8",
            }
            for tag, color in colors.items():
                text = re.sub(
                    rf"\[{tag}\](.*?)\[/{tag}\]",
                    rf'<font color="{color}">\1</font>', text, flags=re.I | re.S)
            text = re.sub(r"\[/?(?:fire_icon|cryo_icon|shock_icon|corrosive_icon|radiation_icon)\]", "", text, flags=re.I)
            text = re.sub(r"\[/?[a-z_]+\]", "", text, flags=re.I)
            text = re.sub(r"\s+", " ", text).strip()
            if text and text not in cleaned:
                cleaned.append(text)
        return "<br>".join(cleaned)

    @pyqtProperty(list, notify=dataChanged)
    def legOptions(self) -> list[dict[str, Any]]:
        if not self.legendaryEnabled:
            return []
        current_class_en = self._current_class_en()
        current_class_id = str(self.CLASS_IDS.get(current_class_en, 0))
        legendary_names = self.names_by_class_rarity.get((current_class_id, "legendary"), [])
        primary_display = self._current_name_display()
        items = []
        for name_row in legendary_names:
            name_en = name_row.get("name_EN", "")
            name_zh = name_row.get("name_ZH", "")
            name_code = name_row.get("name_code", "")
            display_name = name_zh if (self.current_lang == "zh-CN" and name_zh) else name_en
            if display_name == primary_display:
                continue
            effect = self._legendary_effect(str(name_code))
            state = self._candidate(f"{current_class_id}:{name_code}", display_name)
            items.append({
                "key": str(name_code),
                "label": display_name or str(name_code),
                "detail": effect,
                "tooltip": effect,
                "searchText": f"{name_en} {name_zh} {name_code} {effect}",
                "data": {"name_code": name_code},
                **state,
            })
        return items

    @pyqtProperty(list, notify=dataChanged)
    def legEntries(self) -> list[dict[str, Any]]:
        options = {row["key"]: row for row in self.legOptions}
        return [{**row, **{k: options.get(row["key"], {}).get(k, "")
                           for k in ("kind", "marker", "hint", "badge")}}
                for row in self._leg_entries]

    @pyqtProperty(list, notify=dataChanged)
    def skillCategories(self) -> list[dict[str, str]]:
        current_class_id = str(self.CLASS_IDS.get(self._current_class_en(), 0))
        skills_list = self.skills_by_class.get(current_class_id, [])
        tree_names = {}
        for row in skills_list:
            color = row.get("tree_color", "")
            if color:
                tree_names[color] = self._pick_text(row.get("tree_name_ZH", ""), row.get("tree_name_EN", ""))
        color_labels = {
            "red": self._loc("skill_trees", "red", "Red"),
            "green": self._loc("skill_trees", "green", "Green"),
            "blue": self._loc("skill_trees", "blue", "Blue"),
        }
        options = self.skillOptions
        categories = [{"key": "all", "label": self._loc("skill_trees", "all_skills", "All Skills"),
                       "candidateState": _category_state(options)}]
        for color in ("red", "green", "blue"):
            name = tree_names.get(color, color_labels[color])
            categories.append({
                "key": color,
                "label": f"{color_labels[color]} · {name}",
                "candidateState": _category_state([row for row in options if row.get("category") == color]),
            })
        return categories

    @pyqtProperty(list, notify=dataChanged)
    def skillOptions(self) -> list[dict[str, Any]]:
        current_class_en = self._current_class_en()
        current_class_id = str(self.CLASS_IDS.get(current_class_en, 0))
        skills_list = self.skills_by_class.get(current_class_id, [])
        counts = {e["key"]: int(e.get("count", 0)) for e in self._skill_entries}
        items = []
        color_order = {"red": 0, "green": 1, "blue": 2}
        for skill_row in skills_list:
            skill_en = skill_row.get("skill_name_EN", "")
            skill_zh = skill_row.get("skill_name_ZH", "")
            localized_name = skill_zh if self.current_lang == "zh-CN" and skill_zh else skill_en
            display_name = re.sub(r" [BGR]$", "", localized_name) if current_class_en == "C4sh" else localized_name
            codes = []
            for i in range(1, 6):
                code = skill_row.get(f"skill_ID_{i}", "")
                if code:
                    codes.append(int(code))
            color = skill_row.get("tree_color", "")
            tree_name = self._pick_text(skill_row.get("tree_name_ZH", ""), skill_row.get("tree_name_EN", ""))
            stable_key = skill_row.get("skill_key") or f"{current_class_id}:{codes[0] if codes else skill_en}"
            count = counts.get(stable_key, 0)
            next_code = codes[min(count, len(codes) - 1)] if codes else None
            state = self._candidate(f"{current_class_id}:{next_code}" if next_code is not None else "", display_name)
            items.append({
                "key": stable_key,
                "label": display_name,
                "detail": tree_name,
                "category": color,
                "accent": color,
                "iconUrl": self._skill_icon_url(skill_row.get("icon_file", ""), current_class_en),
                "tooltip": self._skill_tooltip(skill_row, display_name),
                "maxCount": len(codes),
                "count": count,
                "searchText": f"{skill_en} {skill_zh} {tree_name} {skill_row.get('skill_internal', '')}",
                "data": {"codes": codes, "skill_key": stable_key},
                **state,
            })
        return sorted(items, key=lambda row: (
            _CANDIDATE_ORDER.get(str(row.get("kind") or "unknown"), 3),
            color_order.get(str(row.get("category") or ""), 9),
            str(row.get("label") or "").casefold(),
        ))

    @pyqtProperty(list, notify=dataChanged)
    def skillEntries(self) -> list[dict[str, Any]]:
        return self._skill_entries

    @pyqtProperty(list, notify=dataChanged)
    def perkCategories(self) -> list[dict[str, str]]:
        categories = [
            ("all", self._loc("perk_filters", "all", "All")),
            ("weapon", self._loc("perk_filters", "weapon", "Weapon")),
            ("skill", self._loc("perk_filters", "skill", "Skill")),
            ("element", self._loc("perk_filters", "element", "Element")),
            ("defense", self._loc("perk_filters", "defense", "Defense")),
            ("utility", self._loc("perk_filters", "utility", "Utility")),
            ("firmware", self._loc("perk_filters", "firmware", "Firmware")),
            ("other", self._loc("perk_filters", "other", "Other")),
        ] and [{"key": k, "label": v} for k, v in [
            ("all", self._loc("perk_filters", "all", "All")),
            ("weapon", self._loc("perk_filters", "weapon", "Weapon")),
            ("skill", self._loc("perk_filters", "skill", "Skill")),
            ("element", self._loc("perk_filters", "element", "Element")),
            ("defense", self._loc("perk_filters", "defense", "Defense")),
            ("utility", self._loc("perk_filters", "utility", "Utility")),
            ("firmware", self._loc("perk_filters", "firmware", "Firmware")),
            ("other", self._loc("perk_filters", "other", "Other")),
        ]]
        options = self.perkOptions
        for category in categories:
            rows = options if category["key"] == "all" else [
                row for row in options if row.get("category") == category["key"]]
            category["candidateState"] = _category_state(rows)
        return categories

    @pyqtProperty(list, notify=dataChanged)
    def perkOptions(self) -> list[dict[str, Any]]:
        counts = {e["key"]: int(e.get("count", 0)) for e in self._perk_entries}
        items = []
        for perk_row in self.perks_data:
            perk_id = perk_row.get("perk_ID", "")
            perk_en = perk_row.get("perk_name_EN", "")
            perk_zh = perk_row.get("perk_name_ZH", "")
            internal = perk_row.get("perk_internal", "")
            category = perk_row.get("perk_category", "other") or "other"
            firmware = (
                item_display_resolver.equipment_firmware_entry(
                    f"234:{perk_id}", "Class Mod", self.current_lang)
                if category == "firmware" else None
            )
            if firmware:
                display_name = firmware["name"]
                descs = firmware.get("descs") or []
                detail = next((text for text in descs if text), "")
                tooltip_lines = [f"{internal}  ·  ID {perk_id}"]
                tooltip_lines.extend(f"L{level}: {text}" for level, text in enumerate(descs, 1) if text)
                search_text = " ".join((perk_id, internal, display_name, *descs))
                tooltip = "\n".join(tooltip_lines)
            else:
                display_name = perk_zh if self.current_lang == "zh-CN" and perk_zh else perk_en
                detail = f"{internal}  ·  ID {perk_id}" if internal else f"ID {perk_id}"
                search_text = f"{perk_id} {internal} {perk_en} {perk_zh}"
                tooltip = detail
            ref = f"234:{perk_id}"
            state = self._candidate(ref, display_name)
            items.append({
                "key": str(perk_id),
                "label": display_name,
                "detail": detail,
                "category": category,
                "accent": "blue" if category == "firmware" else None,
                "searchText": search_text,
                "tooltip": tooltip,
                "count": counts.get(str(perk_id), 0),
                "maxCount": 99,
                "data": {"perk_id": perk_id},
                **state,
            })
        return sorted(items, key=_candidate_sort_key)

    @pyqtProperty(list, notify=dataChanged)
    def perkEntries(self) -> list[dict[str, Any]]:
        return self._perk_entries

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

    @pyqtProperty(str, notify=dataChanged)
    def sourceText(self) -> str:
        texts = source_texts(self.current_lang)
        if self._imported:
            return texts["imported"].format(name=self._import_source_name or "Class Mod")
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
    def setClassIndex(self, index: int) -> None:
        if self._imported or not 0 <= index < len(self.CLASS_NAMES):
            return
        if index == self._class_index:
            return
        old_class = self._current_class_en()
        self._class_index = index
        self._name_index = 0
        self._leg_entries = []
        self._skill_entries = []
        if self._roll_constraints.get("class") == old_class:
            self._roll_constraints["class"] = self._current_class_en()
            self._roll_constraints["rarity"] = self._current_rarity_en()
            self._roll_constraints.pop("name", None)
        self._rebuild()

    @pyqtSlot(int)
    def setRarityIndex(self, index: int) -> None:
        if not 0 <= index < len(_RARITIES):
            return
        old_rarity = self._current_rarity_en()
        self._rarity_index = index
        self._name_index = 0
        self._leg_entries = []
        if self._roll_constraints.get("rarity") == old_rarity:
            self._roll_constraints["rarity"] = self._current_rarity_en()
            self._roll_constraints.pop("name", None)
        self._rebuild()

    @pyqtSlot(int)
    def setNameIndex(self, index: int) -> None:
        if not 0 <= index < len(self._name_display_list()):
            return
        self._name_index = index
        # 主名不能同时作为传奇附加
        primary_code = self._current_name_code()
        self._leg_entries = [e for e in self._leg_entries
                             if str(e["data"].get("name_code")) != str(primary_code)]
        self._rebuild()

    @pyqtSlot(str)
    def setLevel(self, text: str) -> None:
        self._level = text
        self._rebuild()

    @pyqtSlot(str)
    def setSeed(self, text: str) -> None:
        self._seed = text
        self._rebuild()

    @pyqtSlot()
    def randomizeSeed(self) -> None:
        self._seed = str(random.randint(1, 9999))
        self._rebuild()

    def _build_lucky_current(self) -> bool:
        """Fill the current class/rarity/name template with one natural build."""
        if not self._generation_context.get("composition_ref"):
            self.app.toast(self._pick_text("当前模板没有可用的自然生成规则。", "No natural generation rule is available for this template."), "warning")
            return False

        state_fields = (
            "_imported", "_import_header", "_import_seed", "_import_unknown_tokens",
            "_import_unknown_perks", "_import_skill_codes", "_import_skill_counts",
            "_import_source_name", "_leg_entries", "_skill_entries", "_perk_entries", "_seed",
        )
        previous = {name: deepcopy(getattr(self, name)) for name in state_fields}
        rng = random.SystemRandom()
        root_id = str(self.CLASS_IDS.get(self._current_class_en(), 0))
        skill_options = {str(row["key"]): row for row in self.skillOptions}
        perk_options = {str(row["key"]): row for row in self.perkOptions}
        skill_refs = {
            f"{root_id}:{code}": str(row["key"])
            for row in skill_options.values()
            for code in row.get("data", {}).get("codes", [])
        }
        perk_refs = {f"234:{key}": key for key in perk_options}
        rejected_refs: set[str] = set()
        self._leg_entries = []
        self._skill_entries = []
        self._perk_entries = []
        self._imported = False
        self._import_header = None
        self._import_seed = None
        self._import_unknown_tokens = []
        self._import_unknown_perks = []
        self._import_skill_codes = {}
        self._import_skill_counts = {}
        self._import_source_name = ""
        self._seed = str(rng.randint(1, 9999))

        for _attempt in range(64):
            self._rebuild(emit=False)
            if self._legit_status.get("rawStatus") == "legal":
                return True
            choices: list[tuple[int, str, str, str]] = []
            part_refs = item_display_resolver._item_index().get("part_refs") or {}
            for group_name, spec in (self._generation_context.get("groups") or {}).items():
                minimum = int(spec.get("effective_min", spec.get("min", 0)))
                if len(spec.get("selected") or []) >= minimum:
                    continue
                # Pick only parts that are legal at this exact step. The
                # remaining pool also contains future tiers reachable after
                # prerequisites; selecting one of those early creates a
                # deliberate modified build.
                for ref in spec.get("eligible_refs") or []:
                    if ref in set(spec.get("selected") or ()):
                        continue
                    actual_group = str((part_refs.get(str(ref)) or {}).get("selection_group")
                                       or (part_refs.get(str(ref)) or {}).get("category") or "").casefold()
                    if actual_group and actual_group != str(group_name).casefold():
                        continue
                    if ref in rejected_refs:
                        continue
                    group_priority = {
                        "action_skill_mod": 0, "passive_points": 1,
                        "stat_group1": 2, "stat_group2": 3, "stat_group3": 4,
                        "firmware": 5,
                    }.get(str(group_name).casefold(), 6)
                    if ref in skill_refs:
                        choices.append((group_priority, "skill", skill_refs[ref], ref))
                    elif ref in perk_refs:
                        choices.append((group_priority, "perk", perk_refs[ref], ref))
            if not choices:
                break
            best_priority = min(row[0] for row in choices)
            _priority, kind, key, ref = rng.choice(
                [row for row in choices if row[0] == best_priority]
            )
            before_skill = deepcopy(self._skill_entries)
            before_perk = deepcopy(self._perk_entries)
            if kind == "skill":
                option = skill_options[key]
                entry = next((row for row in self._skill_entries if row["key"] == key), None)
                try:
                    rank = option["data"]["codes"].index(int(str(ref).partition(":")[2])) + 1
                except (ValueError, TypeError):
                    rank = 1
                if entry is None:
                    self._skill_entries.append({
                        "key": key, "label": option["label"], "detail": option.get("detail", ""),
                        "iconUrl": option.get("iconUrl", ""), "data": option["data"],
                        "count": rank, "maxCount": int(option.get("maxCount") or 1),
                    })
                else:
                    entry["count"] = max(int(entry["count"]), rank)
            else:
                option = perk_options[key]
                self._perk_entries.append({
                    "key": key, "label": option["label"], "detail": option.get("detail", ""),
                    "data": option["data"], "count": 1,
                })
            self._rebuild(emit=False)
            if self._legit_status.get("rawStatus") == "modified":
                rejected_refs.add(ref)
                self._skill_entries = before_skill
                self._perk_entries = before_perk

        for name, value in previous.items():
            setattr(self, name, value)
        self._rebuild(emit=False)
        return False

    @staticmethod
    def _roll_target_counts(minimum: int, maximum: int, chance: Any) -> list[int]:
        """Return possible native target counts for one generation group."""
        minimum, maximum = max(0, int(minimum)), max(0, int(maximum))
        if maximum < minimum:
            maximum = minimum
        if maximum == minimum:
            return [minimum]
        try:
            chance = float(chance)
        except (TypeError, ValueError):
            chance = 0.5
        if chance <= 0:
            return [minimum]
        if chance >= 1:
            return [maximum]
        return list(range(minimum, maximum + 1))

    def _sample_lucky_parts(self, rng: Any) -> list[str] | None:
        """Sample a legal class-mod composition without rebuilding per pick.

        ``_build_lucky_current`` predates the result page and validates every
        tentative pick by re-running the full resolver. That is correct but can
        take 10+ seconds on deep Epic trees. This path mirrors the NCS
        shrink-only pool with a bounded DFS, then performs one authoritative
        ``_rebuild`` validation at the end.
        """
        if not self._generation_context.get("composition_ref"):
            return None
        index = item_display_resolver._item_index()
        rules = index.get("weapon_generation_rules") or {}
        root = str(self.CLASS_IDS.get(self._current_class_en(), ""))
        weapon = (rules.get("weapons") or {}).get(root) or {}
        composition = (weapon.get("compositions") or {}).get(
            str(self._generation_context.get("composition_ref")))
        if not composition:
            return None

        groups = {str(name).casefold(): data
                  for name, data in (composition.get("groups") or {}).items()}
        ordered = list(dict.fromkeys(str(name).casefold()
                                    for name in (weapon.get("part_types") or ())))
        ordered.extend(sorted(set(groups) - set(ordered)))
        tag_rules = [
            ({str(tag).casefold() for tag in row.get("tags", ())},
             int(row.get("max", 1)))
            for row in composition.get("tag_rules") or ()
        ]
        active = {str(tag).casefold() for tag in composition.get("base_tags") or ()}
        tag_counts = [0] * len(tag_rules)
        selected: list[str] = []

        def ref_tags(ref: str) -> dict[str, set[str]]:
            raw = item_display_resolver._weapon_generation_tags(index, rules, ref)
            return {key: {str(value).casefold() for value in raw.get(key, ())}
                    for key in ("adds", "requires", "excludes")}

        def apply_tags(ref: str, current_active: set[str], current_counts: list[int]):
            tags = ref_tags(ref)
            next_active = set(current_active)
            next_active.update(tags["adds"])
            next_counts = list(current_counts)
            for pos, (bucket, _limit) in enumerate(tag_rules):
                next_counts[pos] += bool(tags["adds"] & bucket)
            return next_active, next_counts

        def allowed(ref: str, current_active: set[str], current_counts: list[int]) -> bool:
            tags = ref_tags(ref)
            if not tags["requires"] <= current_active:
                return False
            if tags["excludes"] & current_active:
                return False
            return not any(tags["adds"] & bucket and current_counts[pos] >= limit
                           for pos, (bucket, limit) in enumerate(tag_rules))

        def search_group(allowed_refs: list[str], target: int,
                         start_active: set[str], start_counts: list[int]):
            # A hard cap keeps malformed/custom NCS snapshots from blocking the UI.
            visited = 0

            def walk(chosen: list[str], current_active: set[str], current_counts: list[int]):
                nonlocal visited
                visited += 1
                if visited > 20000:
                    return None
                if len(chosen) >= target:
                    return chosen
                pool = [ref for ref in allowed_refs
                        if ref not in chosen and allowed(ref, current_active, current_counts)]
                rng.shuffle(pool)
                for ref in pool:
                    next_active, next_counts = apply_tags(ref, current_active, current_counts)
                    result = walk(chosen + [ref], next_active, next_counts)
                    if result is not None:
                        return result
                return None

            return walk([], set(start_active), list(start_counts))

        for group in ordered:
            rule = groups.get(group)
            if not rule:
                continue
            allowed_refs = [str(ref) for ref in rule.get("allowed_part_refs") or ()]
            if group == "class_mod_body":
                # The visible class/name pair already selects this body. Do not
                # sample another body, or its tree tags no longer match the name.
                body = ((self._generation_context.get("groups") or {})
                        .get("class_mod_body", {}).get("selected") or [])
                allowed_refs = [str(body[0])] if body else allowed_refs
            # ``effective_*`` already accounts for terminal dependency chains
            # (for example a Legendary tree whose declared min is 7 but whose
            # current NCS body reaches a legal terminal at 3).  Using the raw
            # composition min here makes those templates look unsampleable.
            context_group = ((self._generation_context.get("groups") or {}).get(group)
                             or {})
            minimum = context_group.get("effective_min", rule.get("min", 1))
            maximum = context_group.get("effective_max", rule.get("max", 1))
            targets = self._roll_target_counts(minimum, maximum,
                                               rule.get("additional_chance"))
            rng.shuffle(targets)
            picked = None
            for target in targets:
                picked = search_group(allowed_refs, target, active, tag_counts)
                if picked is not None:
                    break
            if picked is None:
                return None
            for ref in picked:
                active, tag_counts = apply_tags(ref, active, tag_counts)
            selected.extend(picked)
        return selected

    def _build_lucky_sample(self, rng: Any) -> bool:
        """Fill the current class/name template from one native legal sample."""
        for _attempt in range(10):
            selected = self._sample_lucky_parts(rng)
            if selected is None:
                return False
            root = str(self.CLASS_IDS.get(self._current_class_en(), ""))
            skill_options = {str(row["key"]): row for row in self.skillOptions}
            skill_refs = {
                f"{root}:{code}": str(row["key"])
                for row in skill_options.values()
                for code in row.get("data", {}).get("codes", [])
            }
            perk_options = {str(row["key"]): row for row in self.perkOptions}
            perk_refs = {f"234:{key}": key for key in perk_options}
            self._skill_entries = []
            self._perk_entries = []
            for ref in selected:
                if ref in skill_refs:
                    key = skill_refs[ref]
                    option = skill_options[key]
                    try:
                        rank = option["data"]["codes"].index(int(str(ref).partition(":")[2])) + 1
                    except (ValueError, TypeError):
                        rank = 1
                    entry = next((row for row in self._skill_entries if row["key"] == key), None)
                    if entry is None:
                        self._skill_entries.append({
                            "key": key, "label": option["label"],
                            "detail": option.get("detail", ""),
                            "iconUrl": option.get("iconUrl", ""),
                            "data": option["data"], "count": rank,
                            "maxCount": int(option.get("maxCount") or 1),
                        })
                    else:
                        entry["count"] = max(int(entry.get("count", 1)), rank)
                elif ref in perk_refs:
                    key = perk_refs[ref]
                    option = perk_options[key]
                    entry = next((row for row in self._perk_entries if row["key"] == key), None)
                    if entry is None:
                        self._perk_entries.append({
                            "key": key, "label": option["label"],
                            "detail": option.get("detail", ""),
                            "data": option["data"], "count": 1,
                        })
                    else:
                        entry["count"] = int(entry.get("count", 1)) + 1
            self._seed = str(rng.randint(1, 9999))
            self._rebuild(emit=False)
            if self._legit_status.get("rawStatus") == "legal":
                return True
        return False

    def _capture_roll_state(self) -> dict[str, Any]:
        names = (
            "_imported", "_import_header", "_import_seed", "_import_unknown_tokens",
            "_import_unknown_perks", "_import_skill_codes", "_import_skill_counts",
            "_import_source_name", "_leg_entries", "_skill_entries", "_perk_entries",
            "_raw_output", "_b85_output", "_encode_error", "_legit_status",
            "_generation_context", "_seed", "_class_index", "_rarity_index",
            "_name_index", "_level", "_flag_index",
        )
        return {name: deepcopy(getattr(self, name)) for name in names}

    def _restore_roll_state(self, state: dict[str, Any]) -> None:
        for name, value in state.items():
            setattr(self, name, deepcopy(value))

    def _class_roll_result(self) -> dict[str, Any]:
        skills = []
        skill_options = {row["key"]: row for row in self.skillOptions}
        for entry in self._skill_entries:
            option = skill_options.get(entry["key"], {})
            skills.append({
                "level": f"L{entry.get('count', 1)}",
                "title": entry.get("label", ""),
                "description": option.get("tooltip", ""),
                "icon": option.get("iconUrl", ""),
                "accent": "#39BCE8",
            })
        perks = []
        perk_options = {row["key"]: row for row in self.perkOptions}
        for entry in self._perk_entries:
            option = perk_options.get(entry["key"], {})
            perks.append({
                "level": "",
                "title": entry.get("label", ""),
                "description": option.get("tooltip", entry.get("detail", "")),
                "accent": "#d7dee8",
            })
        legendary = self._legendary_effect(str(self._current_name_code())) if self.legendaryEnabled else ""
        return {
            "name": self._current_name_display(),
            "manufacturer": self._current_class_en(),
            "rarity": self._current_rarity_en(),
            "level": self._level,
            "status": self._legit_status.get("rawStatus", "unknown"),
            "statusLabel": self._legit_status.get("label", ""),
            "serial": self._raw_output,
            "base85": self._b85_output,
            "legendary": self._current_name_display() if legendary else "",
            "legendary_detail": legendary,
            "skills": skills,
            "perks": perks,
        }

    def _roll_catalog(self) -> list[dict[str, Any]]:
        catalog = []
        for class_en in self.CLASS_NAMES:
            class_id = str(self.CLASS_IDS.get(class_en, ""))
            for rarity_en in _RARITIES:
                rarity_key = "legendary" if rarity_en == "Legendary" else "normal"
                for row in self.names_by_class_rarity.get((class_id, rarity_key), []):
                    name_code = str(row.get("name_code", ""))
                    if not name_code.isdigit():
                        continue
                    label = self._pick_text(row.get("name_ZH", ""), row.get("name_EN", ""))
                    catalog.append({
                        "class": class_en, "rarity": rarity_en,
                        "name": label, "name_code": name_code,
                        "key": f"{class_en}|{rarity_en}|{name_code}",
                    })
        return catalog

    @pyqtProperty("QVariantMap", notify=dataChanged)
    def rollConstraintOptions(self) -> dict[str, Any]:
        random_label = "随机" if self.current_lang == "zh-CN" else "Random"
        classes = [{"label": random_label, "value": None}, *self.classOptions]
        rarities = [{"label": random_label, "value": None}, *self.rarityOptions]
        names = [{"label": random_label, "value": None}]
        for row in self._roll_catalog():
            names.append({
                "label": f"{self._(row['class'])} · {self._(row['rarity'])} · {row['name']}",
                "value": row["key"], "classValue": row["class"],
                "rarityValue": row["rarity"],
            })
        return {"classes": classes, "rarities": rarities, "named_items": names}

    @pyqtSlot("QVariantMap", result=int)
    def rollMatchCount(self, constraints) -> int:
        constraints = dict(constraints or {})
        catalog = self._roll_catalog()
        name_value = constraints.get("name")
        if name_value:
            catalog = [row for row in catalog if row["key"] == str(name_value)]
        if constraints.get("class"):
            catalog = [row for row in catalog if row["class"] == str(constraints["class"])]
        if constraints.get("rarity"):
            catalog = [row for row in catalog if row["rarity"] == str(constraints["rarity"])]
        return len(catalog)

    def _reset_roll_template(self) -> None:
        self._leg_entries = []
        self._skill_entries = []
        self._perk_entries = []
        self._imported = False
        self._import_header = None
        self._import_seed = None
        self._import_unknown_tokens = []
        self._import_unknown_perks = []
        self._import_skill_codes = {}
        self._import_skill_counts = {}
        self._import_source_name = ""

    def _roll_impl(self, constraints, count: int, *, notify: bool = True) -> bool:
        """Roll independent class/name templates and show only legal results."""
        constraints = {key: value for key, value in dict(constraints or {}).items()
                       if value is not None and value != ""}
        self._roll_constraints = constraints
        self._roll_count = max(1, min(50, int(count)))
        catalog = self._roll_catalog()
        if constraints.get("name"):
            catalog = [row for row in catalog if row["key"] == str(constraints["name"])]
        if constraints.get("class"):
            catalog = [row for row in catalog if row["class"] == str(constraints["class"])]
        if constraints.get("rarity"):
            catalog = [row for row in catalog if row["rarity"] == str(constraints["rarity"])]
        if not catalog:
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
        failed_templates: set[str] = set()
        try:
            for _index in range(self._roll_count):
                result = None
                for _attempt in range(48):
                    viable_catalog = [row for row in catalog
                                      if row["key"] not in failed_templates]
                    if not viable_catalog:
                        break
                    candidate = rng.choice(viable_catalog)
                    self._class_index = self.CLASS_NAMES.index(candidate["class"])
                    self._rarity_index = _RARITIES.index(candidate["rarity"])
                    names = self._name_display_list()
                    self._name_index = next((i for i, name in enumerate(names)
                                             if name == candidate["name"]), 0)
                    self._reset_roll_template()
                    self._rebuild(emit=False)
                    if not self._build_lucky_sample(rng):
                        # A template whose NCS dependency graph cannot be
                        # completed should not be retried up to 48 times in
                        # this same batch. This was the remaining source of
                        # visible multi-second stalls on some Legendary sets.
                        failed_templates.add(candidate["key"])
                        continue
                    result = self._class_roll_result()
                    signature = (
                        result.get("name"), result.get("manufacturer"), result.get("rarity"),
                        tuple((row.get("title"), row.get("level")) for row in result.get("skills", [])),
                        tuple(row.get("title") for row in result.get("perks", [])),
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
            f"已生成 {len(results)} 个合法职业模组" if self.current_lang == "zh-CN"
            else f"Generated {len(results)} legal class mods"
        )
        self.dataChanged.emit()
        self.rollFinished.emit(bool(results))
        return bool(results)

    @pyqtSlot("QVariantMap", int, result=bool)
    def roll(self, constraints, count: int) -> bool:
        """Synchronous API retained for tests and non-visual callers."""
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

        self._roll_thread = threading.Thread(target=worker, name="huskar-class-roll", daemon=True)
        self._roll_thread.start()
        return True

    @pyqtSlot("QVariantMap", int, result=bool)
    def startRoll(self, constraints, count: int) -> bool:
        """Start a visual Roll off the Qt GUI thread."""
        return self._start_roll_thread(constraints, count)

    @pyqtSlot(result=bool)
    def startQuickRoll(self) -> bool:
        return self._start_roll_thread(self._roll_constraints, self._roll_count)

    @pyqtSlot(result=bool)
    def quickRoll(self) -> bool:
        return self.roll(self._roll_constraints, self._roll_count)

    @pyqtSlot(result=bool)
    def luckyRoll(self) -> bool:
        # Compatibility alias used by older QML/tests.
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
            "results_title": "职业模组随机结果" if zh else "Class Mod Roll Results",
            "select_result": "从左侧选择一个职业模组" if zh else "Select a class mod",
            "add_one": "加入背包" if zh else "Add to Backpack",
            "copy": "复制 Base85" if zh else "Copy Base85",
            "constraints_title": "随机选项" if zh else "Roll Options",
            "class": "职业" if zh else "Class",
            "rarity": "稀有度" if zh else "Rarity",
            "named_item": "传奇名称" if zh else "Named Class Mod",
            "count": "数量" if zh else "Count",
            "matches": "可用模板：{count}" if zh else "Matching templates: {count}",
            "no_matches": "没有可用模板" if zh else "No matching templates",
            "roll": "开始 Roll" if zh else "Roll",
            "no_legal_result": "没有可生成的合法职业模组" if zh else "No legal class-mod result",
            "legendary": "传奇专属加成" if zh else "Legendary Bonus",
            "skills": "技能" if zh else "Skills",
            "perks": "专长" if zh else "Perks",
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
            self.app.toast(self._loc("dialogs", "copied", "Copied"), "success")

    @pyqtSlot(int)
    def setFlagIndex(self, index: int) -> None:
        if 0 <= index < len(self._flag_labels):
            self._flag_index = index
            self.dataChanged.emit()

    def _add_leg_key(self, key: str) -> bool:
        option = next((o for o in self.legOptions if o["key"] == str(key)), None)
        if option is None or any(e["key"] == str(key) for e in self._leg_entries):
            return False
        self._leg_entries.append({"key": str(key), "label": option["label"],
                                  "detail": option.get("detail", ""),
                                  "data": option["data"], "count": 1})
        return True

    @pyqtSlot(str)
    def addLegItem(self, key: str) -> None:
        if self._add_leg_key(key):
            self._rebuild()

    @pyqtSlot(list)
    def addLegItems(self, keys: list) -> None:
        changed = False
        for key in keys or []:
            changed = self._add_leg_key(str(key)) or changed
        if changed:
            self._rebuild()

    @pyqtSlot(int)
    def removeLegItem(self, index: int) -> None:
        if 0 <= index < len(self._leg_entries):
            self._leg_entries.pop(index)
            self._rebuild()

    @pyqtSlot()
    def clearLeg(self) -> None:
        self._leg_entries = []
        self._rebuild()

    def _add_skill_key(self, key: str) -> bool:
        option = next((o for o in self.skillOptions if o["key"] == str(key)), None)
        if option is None:
            return False
        for entry in self._skill_entries:
            if entry["key"] == str(key):
                if entry["count"] < int(option.get("maxCount") or 1):
                    entry["count"] += 1
                return True
        self._skill_entries.append({"key": str(key), "label": option["label"],
                                    "detail": option.get("detail", ""),
                                    "iconUrl": option.get("iconUrl", ""),
                                    "data": option["data"], "count": 1,
                                    "maxCount": int(option.get("maxCount") or 1)})
        return True

    @pyqtSlot(str)
    def addSkillItem(self, key: str) -> None:
        if self._add_skill_key(key):
            self._rebuild()

    @pyqtSlot(list)
    def addSkillItems(self, keys: list) -> None:
        changed = False
        for key in keys or []:
            changed = self._add_skill_key(str(key)) or changed
        if changed:
            self._rebuild()

    @pyqtSlot(int)
    def removeSkillItem(self, index: int) -> None:
        if 0 <= index < len(self._skill_entries):
            self._skill_entries.pop(index)
            self._rebuild()

    @pyqtSlot(int, int)
    def setSkillItemCount(self, index: int, count: int) -> None:
        if 0 <= index < len(self._skill_entries):
            entry = self._skill_entries[index]
            entry["count"] = max(1, min(int(count), int(entry.get("maxCount") or 1)))
            self._rebuild()

    @pyqtSlot(list, int)
    def setSkillItemsCount(self, indices: list, count: int) -> None:
        changed = False
        for index in indices or []:
            index = int(index)
            if 0 <= index < len(self._skill_entries):
                entry = self._skill_entries[index]
                new_count = max(1, min(int(count), int(entry.get("maxCount") or 1)))
                if new_count != entry["count"]:
                    entry["count"] = new_count
                    changed = True
        if changed:
            self._rebuild()

    @pyqtSlot(list, int)
    def setSkillCounts(self, keys: list, count: int) -> None:
        """按 key 设定技能点数（行内目录步进器）：0=移除，超上限截断；一次重建。"""
        count = int(count)
        options = {o["key"]: o for o in self.skillOptions}
        changed = False
        for raw_key in keys or []:
            key = str(raw_key)
            if count <= 0:
                next_entries = [e for e in self._skill_entries if e["key"] != key]
                changed = len(next_entries) != len(self._skill_entries) or changed
                self._skill_entries = next_entries
                continue
            option = options.get(key)
            if option is None:
                continue
            cap = int(option.get("maxCount") or 1)
            new_count = min(count, cap)
            for entry in self._skill_entries:
                if entry["key"] == key:
                    changed = entry["count"] != new_count or changed
                    entry["count"] = new_count
                    break
            else:
                self._skill_entries.append({
                    "key": key, "label": option["label"],
                    "detail": option.get("detail", ""),
                    "iconUrl": option.get("iconUrl", ""),
                    "data": option["data"], "count": new_count,
                    "maxCount": cap})
                changed = True
        if changed:
            self._rebuild()

    @pyqtSlot(list, int)
    def stepSkillCounts(self, keys: list, delta: int) -> None:
        """按 key 相对步进技能点数（每个目标各自 ±delta，下限 0=移除）；一次重建。"""
        options = {o["key"]: o for o in self.skillOptions}
        changed = False
        for raw_key in keys or []:
            key = str(raw_key)
            option = options.get(key)
            for entry in self._skill_entries:
                if entry["key"] == key:
                    cap = int(option.get("maxCount") or 1) if option else 1
                    new_count = max(0, min(int(entry["count"]) + int(delta), cap))
                    if new_count != entry["count"]:
                        if new_count == 0:
                            self._skill_entries.remove(entry)
                        else:
                            entry["count"] = new_count
                        changed = True
                    break
            else:
                if delta > 0 and option is not None:
                    self._skill_entries.append({
                        "key": key, "label": option["label"],
                        "detail": option.get("detail", ""),
                        "iconUrl": option.get("iconUrl", ""),
                        "data": option["data"], "count": 1,
                        "maxCount": int(option.get("maxCount") or 1)})
                    changed = True
        if changed:
            self._rebuild()

    @pyqtSlot()
    def clearSkill(self) -> None:
        self._skill_entries = []
        self._rebuild()

    def _add_perk_key(self, key: str) -> bool:
        option = next((o for o in self.perkOptions if o["key"] == str(key)), None)
        if option is None:
            return False
        for entry in self._perk_entries:
            if entry["key"] == str(key):
                entry["count"] += 1
                return True
        self._perk_entries.append({"key": str(key), "label": option["label"],
                                   "detail": option.get("detail", ""),
                                   "data": option["data"], "count": 1})
        return True

    @pyqtSlot(str)
    def addPerkItem(self, key: str) -> None:
        if self._add_perk_key(key):
            self._rebuild()

    @pyqtSlot(list)
    def addPerkItems(self, keys: list) -> None:
        changed = False
        for key in keys or []:
            changed = self._add_perk_key(str(key)) or changed
        if changed:
            self._rebuild()

    @pyqtSlot(int)
    def removePerkItem(self, index: int) -> None:
        if 0 <= index < len(self._perk_entries):
            self._perk_entries.pop(index)
            self._rebuild()

    @pyqtSlot(int, int)
    def setPerkItemCount(self, index: int, count: int) -> None:
        if 0 <= index < len(self._perk_entries):
            self._perk_entries[index]["count"] = max(1, int(count))
            self._rebuild()

    @pyqtSlot(list, int)
    def setPerkItemsCount(self, indices: list, count: int) -> None:
        changed = False
        for index in indices or []:
            index = int(index)
            if 0 <= index < len(self._perk_entries):
                new_count = max(1, int(count))
                if new_count != self._perk_entries[index]["count"]:
                    self._perk_entries[index]["count"] = new_count
                    changed = True
        if changed:
            self._rebuild()

    @pyqtSlot(list, int)
    def setPerkCounts(self, keys: list, count: int) -> None:
        """按 key 设定 perk 数量（行内目录步进器）：0=移除；一次重建。"""
        count = int(count)
        options = {o["key"]: o for o in self.perkOptions}
        changed = False
        for raw_key in keys or []:
            key = str(raw_key)
            if count <= 0:
                next_entries = [e for e in self._perk_entries if e["key"] != key]
                changed = len(next_entries) != len(self._perk_entries) or changed
                self._perk_entries = next_entries
                continue
            option = options.get(key)
            if option is None:
                continue
            new_count = max(1, min(count, 99))
            for entry in self._perk_entries:
                if entry["key"] == key:
                    changed = entry["count"] != new_count or changed
                    entry["count"] = new_count
                    break
            else:
                self._perk_entries.append({
                    "key": key, "label": option["label"],
                    "detail": option.get("detail", ""),
                    "data": option["data"], "count": new_count})
                changed = True
        if changed:
            self._rebuild()

    @pyqtSlot(list, int)
    def stepPerkCounts(self, keys: list, delta: int) -> None:
        """按 key 相对步进 perk 数量（每个目标各自 ±delta，下限 0=移除）；一次重建。"""
        options = {o["key"]: o for o in self.perkOptions}
        changed = False
        for raw_key in keys or []:
            key = str(raw_key)
            option = options.get(key)
            for entry in self._perk_entries:
                if entry["key"] == key:
                    new_count = max(0, min(int(entry["count"]) + int(delta), 99))
                    if new_count != entry["count"]:
                        if new_count == 0:
                            self._perk_entries.remove(entry)
                        else:
                            entry["count"] = new_count
                        changed = True
                    break
            else:
                if delta > 0 and option is not None:
                    self._perk_entries.append({
                        "key": key, "label": option["label"],
                        "detail": option.get("detail", ""),
                        "data": option["data"], "count": 1})
                    changed = True
        if changed:
            self._rebuild()

    @pyqtSlot()
    def clearPerk(self) -> None:
        self._perk_entries = []
        self._rebuild()

    @pyqtSlot()
    def copyRawToClipboard(self) -> None:
        QApplication.clipboard().setText(self._raw_output)
        self.app.toast(self._loc("dialogs", "copied", "Copied"), "success")

    @pyqtSlot()
    def copyBase85ToClipboard(self) -> None:
        QApplication.clipboard().setText(self._b85_output)
        self.app.toast(self._loc("dialogs", "copied", "Copied"), "success")

    @pyqtSlot()
    def addToBackpack(self) -> None:
        if not self._b85_output or self._encode_error:
            self.app.toast(self._loc("dialogs", "no_valid_base85", "No valid Base85"), "warning")
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
                     if it.get("type_en") == "Class Mod" and it.get("container") == "Backpack"]
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
            self._load_decoded_copy(item["decoded"], source_name=item["name"] or "Class Mod",
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
    def _current_class_en(self) -> str:
        if 0 <= self._class_index < len(self.CLASS_NAMES):
            return self.CLASS_NAMES[self._class_index]
        return self.CLASS_NAMES[0]

    def _current_rarity_en(self) -> str:
        return _RARITIES[self._rarity_index] if 0 <= self._rarity_index < len(_RARITIES) else "Legendary"

    def _name_rows(self) -> list:
        current_class_id = str(self.CLASS_IDS.get(self._current_class_en(), 0))
        rarity_key = "legendary" if self._current_rarity_en() == "Legendary" else "normal"
        return self.names_by_class_rarity.get((current_class_id, rarity_key), [])

    def _name_display_list(self) -> list[str]:
        result = []
        for name_row in self._name_rows():
            name_en = name_row.get("name_EN", "")
            name_zh = name_row.get("name_ZH", "")
            result.append(name_zh if (self.current_lang == "zh-CN" and name_zh) else name_en)
        return result

    def _current_name_display(self) -> str:
        names = self._name_display_list()
        if 0 <= self._name_index < len(names):
            return names[self._name_index]
        return ""

    def _current_name_code(self) -> int:
        display = self._current_name_display()
        for name_row in self._name_rows():
            name_en = name_row.get("name_EN", "")
            name_zh = name_row.get("name_ZH", "")
            candidate = name_zh if (self.current_lang == "zh-CN" and name_zh) else name_en
            if candidate == display:
                code = name_row.get("name_code", "")
                return int(code) if str(code).isdigit() else 0
        return 0

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

    def _skill_icon_url(self, icon_file: str, class_name: str) -> str:
        return _skill_icon_url(str(icon_file or ""), str(class_name or ""))

    def _skill_tooltip(self, skill_row, display_name: str) -> str:
        from html import escape
        desc_text = self._pick_text(skill_row.get("description_ZH", ""), skill_row.get("description_EN", ""))
        if not desc_text:
            return ""
        skill_type = (self._loc("skill_trees", "passive", "Passive")
                      if skill_row.get("skill_type") == "passive" else str(skill_row.get("skill_type", "")))
        desc_html = item_display_resolver.render_skill_markup(desc_text)
        return (f"<b>{escape(display_name)}</b><br><i>{escape(self.strings.get('tooltips', {}).get('type', 'Type'))}: "
                f"{escape(skill_type)}</i><hr>{desc_html}")

    def _reset_import(self) -> None:
        self._imported = False
        self._import_header = None
        self._import_seed = None
        self._import_unknown_tokens = []
        self._import_unknown_perks = []
        self._import_skill_codes = {}
        self._import_skill_counts = {}
        self._import_source_name = ""
        self._level = self._character_level
        self._seed = str(random.randint(1, 9999))
        self._flag_index = self._default_flag_index()
        self._leg_entries = []
        self._skill_entries = []
        self._perk_entries = []
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

    @staticmethod
    def _format_perk_code(perk_id: str) -> str:
        perk_id = str(perk_id).strip()
        if not perk_id:
            return ""
        if perk_id.isdigit():
            return perk_id
        # Named perks are spelled the way the game writes them back ("ClassMod.<part>";
        # the data tables use CLASSMOD.). Another spelling still materialises, but
        # the returned item then no longer matches the requested serial, and a live
        # add waits for it until the bridge times out.
        name = perk_id.strip('"')
        prefix, dot, rest = name.partition(".")
        if dot and prefix.casefold() == "classmod":
            name = f"ClassMod.{rest}"
        return f'"{name}"'

    def _load_decoded_copy(self, decoded: str, *, source_name: str, state_flags=None) -> bool:
        header = split_decoded(decoded)
        class_en = next((name for name, code in self.CLASS_IDS.items() if code == header["mfg_id"]), None)
        if not class_en:
            raise ValueError(source_texts(self.current_lang)["wrong_type"])

        class_id = str(header["mfg_id"])
        tokens = list(parse_components(header["component"]))
        simple_positions = [(index, token["id"]) for index, token in enumerate(tokens)
                            if token["type"] == "simple"]

        rarity_by_code = {}
        for rarity in ("Common", "Uncommon", "Rare", "Epic"):
            code = item_display_resolver.classmod_rarity_code(class_id, rarity)
            if str(code).isdigit():
                rarity_by_code[int(code)] = rarity
        for row in self.legendary_map_data:
            if str(row.get("class_ID", "")) == class_id and str(row.get("item_card_ID", "")).isdigit():
                rarity_by_code[int(row["item_card_ID"])] = "Legendary"

        rarity_pos = next(((index, rarity_by_code[code]) for index, code in simple_positions
                           if code in rarity_by_code), None)
        if not rarity_pos:
            raise ValueError("Class Mod rarity is not recognized.")
        rarity_index, rarity_en = rarity_pos
        rarity_key = "legendary" if rarity_en == "Legendary" else "normal"
        name_rows = self.names_by_class_rarity.get((class_id, rarity_key), [])
        names_by_code = {int(row["name_code"]): row for row in name_rows
                         if str(row.get("name_code", "")).isdigit()}
        name_pos = next(((index, code) for index, code in simple_positions
                         if index > rarity_index and code in names_by_code), None)
        if not name_pos:
            raise ValueError("Class Mod name is not recognized.")
        name_index, name_code = name_pos

        skill_counts = {}
        source_skill_codes = {}
        skill_codes = set()
        for row in self.skills_by_class.get(class_id, []):
            codes = [int(row[f"skill_ID_{i}"]) for i in range(1, 6)
                     if str(row.get(f"skill_ID_{i}", "")).isdigit()]
            skill_codes.update(codes)
            source_codes = [code for _index, code in simple_positions if code in codes]
            count = min(len(codes), len(source_codes))
            if count:
                key = row.get("skill_key") or f"{class_id}:{codes[0]}"
                skill_counts[key] = count
                source_skill_codes[key] = source_codes

        known_numeric_perks = {int(key) for key in self.perks_by_id if str(key).isdigit()}
        # quoted perks: the game writes "ClassMod.x", the tables CLASSMOD.x
        known_path_perks = {str(key).casefold(): str(key) for key in self.perks_by_id if not str(key).isdigit()}
        perk_counts = Counter()
        path_counts = Counter()
        unknown_perks = []
        unknown_tokens = []
        legendary_extras = Counter()

        for index, token in enumerate(tokens):
            token_type = token["type"]
            if token_type == "simple":
                code = token["id"]
                if index in (rarity_index, name_index):
                    continue
                if rarity_en == "Legendary" and code in names_by_code:
                    legendary_extras[code] += 1
                elif code in skill_codes:
                    continue
                elif class_en == "Harlowe" and rarity_en == "Legendary" and code == 27:
                    continue
                else:
                    unknown_tokens.append(self._component_text(token))
            elif token_type == "group" and token["id"] == 234:
                for code in token["children"]:
                    if code in known_numeric_perks:
                        perk_counts[str(code)] += 1
                    else:
                        unknown_perks.append(str(code))
            elif token_type == "single" and token["id"] == 234:
                if token["value"] in known_numeric_perks:
                    perk_counts[str(token["value"])] += 1
                else:
                    unknown_perks.append(str(token["value"]))
            elif token_type == "quoted" and str(token["value"]).casefold() in known_path_perks:
                path_counts[known_path_perks[str(token["value"]).casefold()]] += 1
            else:
                unknown_tokens.append(self._component_text(token))

        self._loading_import = True
        try:
            self._imported = True
            self._import_header = header
            self._import_seed = header["seed"]
            self._import_unknown_tokens = unknown_tokens
            self._import_unknown_perks = unknown_perks
            self._import_skill_codes = source_skill_codes
            self._import_skill_counts = dict(skill_counts)
            self._import_source_name = source_name

            self._class_index = self.CLASS_NAMES.index(class_en)
            self._rarity_index = _RARITIES.index(rarity_en)
            display_name = next(
                (name_zh if (self.current_lang == "zh-CN" and name_zh) else name_en
                 for row in name_rows
                 for name_en, name_zh in [(row.get("name_EN", ""), row.get("name_ZH", ""))]
                 if str(row.get("name_code", "")).isdigit() and int(row["name_code"]) == name_code),
                None)
            if not display_name:
                raise ValueError("Class Mod name is unavailable in the current catalog.")
            names = self._name_display_list()
            self._name_index = names.index(display_name) if display_name in names else 0
            self._level = str(header["level"])
            self._seed = str(header["seed"])
            self._leg_entries = []
            self._skill_entries = []
            self._perk_entries = []
            leg_options = {o["key"]: o for o in self.legOptions}
            for code, count in legendary_extras.items():
                option = leg_options.get(str(code))
                if option:
                    self._leg_entries.append({"key": str(code), "label": option["label"],
                                              "detail": option.get("detail", ""),
                                              "data": option["data"], "count": count})
            skill_options = {o["key"]: o for o in self.skillOptions}
            for key, count in skill_counts.items():
                option = skill_options.get(key)
                if option:
                    self._skill_entries.append({
                        "key": key, "label": option["label"], "detail": option.get("detail", ""),
                        "iconUrl": option.get("iconUrl", ""), "data": option["data"],
                        "count": count, "maxCount": int(option.get("maxCount") or 1)})
            perk_options = {o["key"]: o for o in self.perkOptions}
            for key, count in (perk_counts + path_counts).items():
                option = perk_options.get(str(key))
                if option:
                    self._perk_entries.append({"key": str(key), "label": option["label"],
                                               "detail": option.get("detail", ""),
                                               "data": option["data"], "count": count})
            self._set_flag_value(state_flags)
        finally:
            self._loading_import = False
        self._rebuild()
        return True

    def _rebuild(self, *, emit: bool = True) -> None:
        if self._loading_import:
            return
        if not self.names_data or not self._current_name_display():
            self._raw_output = "..."
            self._b85_output = "..."
            self._legit_status = evaluate_legit("", self.current_lang)
            if emit:
                self.dataChanged.emit()
            return
        try:
            current_class_en = self._current_class_en()
            current_class_id = str(self.CLASS_IDS.get(current_class_en, 0))
            level_val = self._level or self._character_level
            if self._imported:
                header = build_header(self._import_header, mfg_id=self.CLASS_IDS[current_class_en],
                                      level=level_val, seed=self._seed) + "||"
            else:
                header = f"{self.CLASS_IDS[current_class_en]}, 0, 1, {level_val}| 2, {self._seed}||"

            rarity_en = self._current_rarity_en()
            name_code = self._current_name_code()
            name_chunk = f"{{{name_code}}}" if name_code else ""

            rarity_code_val = ""
            if rarity_en == "Legendary":
                for row in self.legendary_map_data:
                    if row.get("class_ID") == current_class_id and row.get("L_name_ID") == str(name_code):
                        rarity_code_val = row.get("item_card_ID", "")
                        break
                if current_class_en == "Harlowe":
                    name_chunk += " {27}"
            else:
                rarity_code_val = item_display_resolver.classmod_rarity_code(current_class_id, rarity_en)
            rarity_chunk = f"{{{rarity_code_val}}}" if rarity_code_val else ""

            leg_extras_chunk = " ".join(f"{{{e['data']['name_code']}}}" for e in self._leg_entries)

            skill_chunks = []
            for entry in self._skill_entries:
                codes = entry["data"]["codes"]
                selected_codes = codes[:entry["count"]]
                if self._imported and self._import_skill_counts.get(entry["key"]) == entry["count"]:
                    selected_codes = self._import_skill_codes.get(entry["key"], selected_codes)
                skill_chunks.extend(f"{{{code}}}" for code in selected_codes)
            skills_chunk = " ".join(skill_chunks)

            perk_codes = list(self._import_unknown_perks) if self._imported else []
            special_perk_codes = []
            for e in self._perk_entries:
                perk_id = e["data"]["perk_id"]
                count = int(e.get("count", 1))
                if not perk_id:
                    continue
                perk_code = self._format_perk_code(perk_id)
                for _ in range(count):
                    if str(perk_id).strip().isdigit():
                        perk_codes.append(perk_code)
                    else:
                        special_perk_codes.append(perk_code)
            perks_chunk = f" {{234:[{' '.join(perk_codes)}]}}" if perk_codes else ""
            special_perks_chunk = " ".join(special_perk_codes)

            parts = [header, rarity_chunk, name_chunk, leg_extras_chunk, skills_chunk,
                     perks_chunk, special_perks_chunk]
            if self._imported:
                parts.extend(self._import_unknown_tokens)
            self._raw_output = " ".join(p for p in parts if p).replace("  ", " ").strip() + "|"

            self._generation_context = item_display_resolver.weapon_generation_context(self._raw_output)

            encoded_serial, error = b_encoder.encode_to_base85(self._raw_output)
            self._encode_error = bool(error)
            self._b85_output = (self._loc("dialogs", "coding_error", "Error: {error}").format(error=error)
                                if error else encoded_serial)
            self._legit_status = evaluate_legit(self._raw_output, self.current_lang)
        except Exception as exc:
            self._encode_error = True
            self._raw_output = self._loc("dialogs", "gen_error", "Error: {error}").format(error=exc)
            self._b85_output = "..."
            self._generation_context = {}
            self._legit_status = evaluate_legit("", self.current_lang)
        if emit:
            self.dataChanged.emit()
