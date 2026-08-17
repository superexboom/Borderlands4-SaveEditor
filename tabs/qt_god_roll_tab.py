from __future__ import annotations

import threading
from typing import Any

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core import item_display_resolver, lookup, resource_loader, serial_inspect
from core.weapon_optimizer import AUTO, ELEMENT_GROUPS, NONE, GodRollRequest, WeaponGodRollOptimizer
from .qt_catalog_picker import PopupOnlyWheelComboBox
from .qt_weapon_roll_dialog import WeaponRollResultsPage


class GodRollResultsPage(WeaponRollResultsPage):
    """God Roll result browser with its own per-part detail cards."""

    def __init__(self, parent=None, texts=None):
        super().__init__(parent=parent, texts=texts)
        self.open_editor_button.setVisible(True)
        self.score_title = QLabel()
        self.score_title.setObjectName("genSectionTitle")
        self.score_label = QLabel()
        self.score_label.setObjectName("rollScoreExplanation")
        self.score_label.setWordWrap(True)
        self.parts_title = QLabel()
        self.parts_title.setObjectName("genSectionTitle")
        self.parts_scroll = QScrollArea()
        self.parts_scroll.setWidgetResizable(True)
        self.parts_scroll.setMinimumHeight(190)
        self.parts_body = QWidget()
        self.parts_layout = QVBoxLayout(self.parts_body)
        self.parts_layout.setContentsMargins(0, 0, 0, 0)
        self.parts_layout.setSpacing(6)
        self.parts_scroll.setWidget(self.parts_body)
        detail_layout = self.detail_card.layout()
        detail_layout.insertWidget(3, self.score_title)
        detail_layout.insertWidget(4, self.score_label)
        detail_layout.insertWidget(5, self.parts_title)
        detail_layout.insertWidget(6, self.parts_scroll, 1)
        self.update_texts(texts or {})
        self._render_score()
        self._render_parts()

    def update_texts(self, texts):
        super().update_texts(texts)
        if hasattr(self, "parts_title"):
            self.parts_title.setText(self._t.get("parts_title", "Part Details"))
            self.score_title.setText(self._t.get("score_explanation", "Score explanation"))
            self._render_score()
            self._render_parts()

    def _render_score(self):
        if not hasattr(self, "score_label"):
            return
        result = self._current_result()
        if not result:
            self.score_label.setText("—")
            return
        profile = str(result.get("score_profile") or "sustained_dps")
        profile_label = self._t.get(f"score_profile_{profile}", profile)
        lines = [
            f"{self._t.get('score_total', 'Score')}: {float(result.get('score') or 0):.2f}",
            f"{self._t.get('score_profile', 'Profile')}: {profile_label}",
        ]
        for row in result.get("score_breakdown") or ():
            key = str(row.get("key") or "")
            label = self._t.get(f"score_metric_{key}", key)
            raw = row.get("raw_display")
            if raw in (None, ""):
                raw = "—"
            weight = float(row.get("weight") or 0.0)
            lines.append(
                f"{label} × {weight:.0%}: {float(row.get('contribution') or 0):+.2f} "
                f"({raw})"
            )
        lines.append(self._t.get("score_warning", "Paper score; some mechanics are not modeled."))
        missing = [str(value).split(":", 1)[1] for value in (result.get("score_warnings") or ()) if str(value).startswith("missing:")]
        if missing:
            labels = [self._t.get(f"score_metric_{key}", key) for key in missing]
            lines.append(self._t.get("score_missing", "Unavailable metrics: {metrics}").format(metrics=", ".join(labels)))
        self.score_label.setText("\n".join(lines))

    def _clear_parts(self):
        if not hasattr(self, "parts_layout"):
            return
        while self.parts_layout.count():
            item = self.parts_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _render_parts(self):
        if not hasattr(self, "parts_layout"):
            return
        self._clear_parts()
        result = self._current_result()
        rows = list((result or {}).get("part_details") or ())
        if not rows:
            empty = QLabel(self._t.get("no_part_details", "No part details"))
            empty.setWordWrap(True)
            self.parts_layout.addWidget(empty)
            self.parts_layout.addStretch()
            return
        for index, row in enumerate(rows, 1):
            card = QFrame()
            card.setObjectName("rollPartCard")
            layout = QVBoxLayout(card)
            layout.setContentsMargins(8, 7, 8, 7)
            layout.setSpacing(3)
            group_label = str(row.get("group_label") or "—")
            name = str(row.get("name") or row.get("ref") or "—")
            title_text = group_label if name == group_label else f"{group_label} · {name}"
            title = QLabel(f"{index}. {title_text}")
            title.setObjectName("rollPartName")
            title.setWordWrap(True)
            layout.addWidget(title)
            meta = QLabel(" · ".join(filter(None, (row.get("ref"), row.get("source_label")))))
            meta.setObjectName("rollPartMeta")
            meta.setWordWrap(True)
            layout.addWidget(meta)
            description = QLabel(str(row.get("description") or self._t.get("no_part_effect", "No stat changes")))
            description.setObjectName("rollPartDescription")
            description.setWordWrap(True)
            layout.addWidget(description)
            internal = str(row.get("internal") or "")
            if internal:
                card.setToolTip(internal)
            self.parts_layout.addWidget(card)
        self.parts_layout.addStretch()

    def _show_result(self, row):
        super()._show_result(row)
        self._render_score()
        self._render_parts()


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


class QtGodRollTab(QWidget):
    add_to_backpack_requested = pyqtSignal(str, str)
    batch_add_to_backpack_requested = pyqtSignal(list, str)
    open_editor_requested = pyqtSignal(dict)
    worker_started = pyqtSignal(object)

    _FALLBACK = {
        "title": "God Roll Optimizer",
        "source": "Target weapon",
        "manufacturer": "Manufacturer",
        "weapon_type": "Weapon Type",
        "rarity": "Rarity",
        "weapon": "Weapon",
        "mode": "Mode",
        "legal": "Legal build",
        "unrestricted": "Cross-manufacturer",
        "level": "Level",
        "barrel": "Fixed barrel",
        "torgue": "Torgue requirement",
        "torgue_any": "No requirement",
        "torgue_sticky": "Must include sticky",
        "torgue_impact": "Must include impact/normal",
        "base_element": "Base element",
        "secondary_element": "Dual/secondary element",
        "pearl_element": "Pearl override",
        "auto": "Auto optimize",
        "auto_available": "Auto optimize (candidate available, not guaranteed)",
        "unavailable": "Unavailable for this weapon",
        "none": "No element",
        "force_element": "Allow forced illegal element",
        "force_hint": "The result is marked modified when only the element violates the native build rules.",
        "score_note": "Ranking uses a paper stat model; red-text, ricochet, and delayed sticky mechanics are not fully modeled.",
        "score_profile": "Score profile",
        "score_profile_sustained_dps": "Sustained DPS",
        "score_profile_burst": "Burst Damage",
        "score_profile_crit_element": "Crit / Element",
        "score_profile_balanced": "Balanced",
        "score_explanation": "Score explanation",
        "score_total": "Score",
        "score_short": "Score",
        "score_metric_dps": "Sustained DPS",
        "score_metric_damage": "Damage",
        "score_metric_fire_rate": "Fire Rate",
        "score_metric_magazine": "Magazine",
        "score_metric_critical_damage": "Critical Damage",
        "score_metric_elemental_dps": "Elemental DPS",
        "score_metric_reload_time": "Reload",
        "score_warning": "Paper score; red text, ricochet, and delayed sticky mechanics are not modeled.",
        "score_missing": "Unavailable metrics: {metrics}",
        "open_editor": "Open in Weapon Editor",
        "limits": "Unrestricted group limits",
        "group": "Group",
        "pool": "Pool",
        "minimum": "Min",
        "maximum": "Max",
        "effort": "Search budget",
        "fast": "Fast (3 seconds)",
        "balanced": "Balanced (8 seconds)",
        "deep": "Deep (30 seconds)",
        "top_n": "Results",
        "search": "Find God Rolls",
        "cancel": "Cancel",
        "idle": "Choose a target and start searching.",
        "running": "Explored {attempted} · valid {accepted} · best score {best}",
        "done": "Found {count} builds from {attempted} attempts in {elapsed:.1f}s. Budget-best; global optimum is not yet proven.",
        "done_exact": "Exhausted {frontier} legal builds in {elapsed:.1f}s and proved the Top {count}.",
        "cancelled": "Search cancelled; showing the best results found so far.",
        "no_results": "No build matched the selected constraints.",
        "error": "God Roll search failed: {error}",
        "offline_only": "God Roll generation is an offline save feature.",
        "select_flag": "Flag",
        "add_start": "Adding {count} item(s)...",
        "add_progress": "Adding {current}/{total} · success {success} · failed {fail}",
        "add_done": "Added {success}; failed {fail}",
        "results_scope": "{mode} · {profile} · fixed barrel {barrel} · budget-best Top {count}",
        "results_scope_exact": "{mode} · {profile} · fixed barrel {barrel} · proven Top {count}",
        "parts_title": "Part Details",
        "no_part_details": "No part details",
        "no_part_effect": "No stat changes",
        "source_current": "Current weapon",
        "source_universal": "Universal pool",
        "status_element_modified": "Element-only Modified",
    }

    _RARITY_ORDER = ("Common", "Uncommon", "Rare", "Epic", "Legendary", "Pearl")
    _TYPE_KEYS = {
        "Assault Rifle": "assault_rifle",
        "Pistol": "pistol",
        "Shotgun": "shotgun",
        "SMG": "smg",
        "Sniper": "sniper",
    }
    _GROUP_KEYS = {
        "inv_comp": "rarity",
        "body": "body",
        "body_acc": "body_accessory",
        "body_mech": "body_mechanism",
        "barrel": "barrel",
        "barrel_acc": "barrel_accessory",
        "magazine": "magazine",
        "magazine_acc": "manufacturer_part",
        "magazine_ted_thrown": "tediore_payload",
        "scope": "scope",
        "scope_acc": "scope_accessory",
        "grip": "grip",
        "foregrip": "foregrip",
        "underbarrel": "underbarrel",
        "underbarrel_acc": "underbarrel_accessory",
        "body_ele": "element",
        "secondary_ele": "element_switch",
        "pearl_elem": "pearl_elements",
        "pearl_stat": "pearl_stat",
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_lang = "zh-CN"
        self._character_level = 60
        self._live_mode = False
        self._worker = None
        self._add_busy = False
        self._refreshing_options = False
        self._torgue_selectable = False
        self._secondary_selectable = False
        self._pearl_selectable = False
        self._raw_results = []
        self._last_result_meta = None
        self.taxonomy = {}
        self.stats_loc = {}
        self.rule_loc = {}
        self.generator_labels = {}
        self.generator_buttons = {}
        self.item_names = {}
        self.item_index = resource_loader.load_item_json("item_name_index.json") or {}
        self.optimizer = WeaponGodRollOptimizer(self.item_index)
        self.catalog = self.optimizer.catalog()
        self._catalog_rows = []
        self._group_limit_spins = {}
        self._build_ui()
        self.update_language(self.current_lang)

    def _text(self, key):
        return str((self.loc or {}).get(key) or self._FALLBACK.get(key) or key)

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
            canonical = {
                "borg": "Ripper",
                "order": "Order",
            }.get(str(value or "").casefold(), self._humanize(value))
        return str(self.item_names.get(canonical) or canonical)

    def _weapon_type_label(self, value):
        canonical = "Assault Rifle" if str(value or "") == "AssaultRifle" else str(value or "")
        return str(self.taxonomy.get(self._TYPE_KEYS.get(canonical, "")) or canonical)

    def _rarity_label(self, value):
        return str(self.taxonomy.get(str(value or "").casefold()) or value or "—")

    def _group_label(self, value):
        key = str(value or "").casefold()
        return str(self.taxonomy.get(self._GROUP_KEYS.get(key, "")) or self._humanize(key) or "—")

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

    def _localize_result(self, result):
        row = dict(result or {})
        root_id = str(row.get("root_id") or "")
        composition_ref = str(row.get("composition_ref") or "")
        composition = (
            ((self.optimizer.weapons.get(root_id) or {}).get("compositions") or {}).get(composition_ref)
            or {}
        )
        names = composition.get("name") or {}
        preferred_name = names.get("zh") if self.current_lang == "zh-CN" else names.get("en")
        row["name"] = str(
            preferred_name or names.get("en") or names.get("zh")
            or composition.get("part") or row.get("name") or "—"
        )
        manufacturer_key = str(row.get("manufacturer_key") or row.get("manufacturer") or "")
        weapon_type_key = str(row.get("weapon_type_key") or row.get("weapon_type") or "")
        rarity_key = str(row.get("rarity_key") or row.get("rarity") or "")
        row["manufacturer_key"] = manufacturer_key
        row["weapon_type_key"] = weapon_type_key
        row["manufacturer"] = self._manufacturer_label(manufacturer_key, root_id)
        row["weapon_type"] = self._weapon_type_label(weapon_type_key)
        row["rarity"] = self._rarity_label(rarity_key)
        if row.get("status") == "legal":
            row["status_label"] = self.rule_loc.get("status_legal") or self._text("legal")
        elif row.get("element_only_modified"):
            row["status_label"] = self._text("status_element_modified")
        else:
            row["status_label"] = self.rule_loc.get("status_modified") or "Modified"
        stats = row.get("stats") or {}
        row["formatted_stats"] = {
            key: item_display_resolver.format_weapon_stat(key, stats.get(key), self.current_lang) or "—"
            for key in item_display_resolver.WEAPON_STAT_KEYS
        }
        details = []
        try:
            part_rows = serial_inspect.part_rows(
                str(row.get("decoded") or ""), int(root_id), weapon_type_key, self.current_lang
            )
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
        torgue = str(row.get("torgue_mode") or "")
        variant = []
        if torgue == "sticky":
            variant.append(self._text("torgue_sticky"))
        elif torgue == "impact":
            variant.append(self._text("torgue_impact"))
        variant.extend(part["name"] for part in details if part["group_label"] and part["name"] not in variant)
        row["variant_summary"] = " · ".join(variant[:5])
        row["tooltip"] = "\n".join([
            str(row.get("name") or "—"),
            f"{row['manufacturer']} · {row['weapon_type']} · {row['rarity']}",
            str(row.get("status_label") or ""),
            *(f"{part['ref']} · {part['name']} · {part['description']}" for part in details),
            f"Base85: {row.get('serial') or ''}",
        ])
        return row

    @staticmethod
    def _find_data(combo, value):
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                return index
        return -1

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(10)

        self.live_banner = QLabel("")
        self.live_banner.setObjectName("genBuildStatus")
        self.live_banner.setWordWrap(True)
        self.live_banner.hide()
        root.addWidget(self.live_banner)

        self.page_stack = QStackedWidget()
        root.addWidget(self.page_stack, 1)

        config_page = QWidget()
        config_layout = QVBoxLayout(config_page)
        config_layout.setContentsMargins(0, 0, 0, 0)
        config_layout.setSpacing(10)

        source_card = QFrame()
        source_card.setObjectName("genConfigCard")
        source_grid = QGridLayout(source_card)
        source_grid.setContentsMargins(14, 12, 14, 12)
        source_grid.setHorizontalSpacing(10)
        source_grid.setVerticalSpacing(6)

        self.title_label = QLabel()
        self.title_label.setObjectName("genSectionTitle")
        source_grid.addWidget(self.title_label, 0, 0, 1, 3)
        self.rarity_combo = PopupOnlyWheelComboBox()
        self.manufacturer_combo = PopupOnlyWheelComboBox()
        self.weapon_type_combo = PopupOnlyWheelComboBox()
        self.weapon_combo = PopupOnlyWheelComboBox()
        self.mode_combo = PopupOnlyWheelComboBox()
        self.level_spin = QSpinBox()
        self.level_spin.setRange(1, 999)
        self.level_spin.setValue(self._character_level)
        self.flag_combo = PopupOnlyWheelComboBox()
        source_widgets = (
            self.rarity_combo, self.manufacturer_combo, self.weapon_type_combo, self.weapon_combo,
            self.mode_combo, self.level_spin, self.flag_combo,
        )
        self.source_labels = [QLabel() for _ in range(len(source_widgets))]
        for index, (label, widget) in enumerate(zip(self.source_labels, source_widgets)):
            block, column = divmod(index, 3)
            source_grid.addWidget(label, 1 + block * 2, column)
            source_grid.addWidget(widget, 2 + block * 2, column)
        source_grid.setColumnStretch(0, 1)
        source_grid.setColumnStretch(1, 1)
        source_grid.setColumnStretch(2, 2)
        config_layout.addWidget(source_card)

        constraints_card = QFrame()
        constraints_card.setObjectName("genAttrCard")
        constraints_grid = QGridLayout(constraints_card)
        constraints_grid.setContentsMargins(14, 12, 14, 12)
        constraints_grid.setHorizontalSpacing(12)
        constraints_grid.setVerticalSpacing(6)
        self.barrel_combo = PopupOnlyWheelComboBox()
        self.torgue_combo = PopupOnlyWheelComboBox()
        self.base_element_combo = PopupOnlyWheelComboBox()
        self.secondary_element_combo = PopupOnlyWheelComboBox()
        self.pearl_element_combo = PopupOnlyWheelComboBox()
        self.constraint_labels = [QLabel() for _ in range(5)]
        widgets = (
            self.barrel_combo, self.torgue_combo, self.base_element_combo,
            self.secondary_element_combo, self.pearl_element_combo,
        )
        for index, (label, widget) in enumerate(zip(self.constraint_labels, widgets)):
            block, column = divmod(index, 3)
            constraints_grid.addWidget(label, block * 2, column)
            constraints_grid.addWidget(widget, block * 2 + 1, column)
        for column in range(3):
            constraints_grid.setColumnStretch(column, 1)
        self.force_element_check = QCheckBox()
        self.force_element_check.setToolTip(self._FALLBACK["force_hint"])
        self.force_element_check.toggled.connect(self._refresh_options)
        constraints_grid.addWidget(self.force_element_check, 4, 0, 1, 3)
        self.score_note_label = QLabel()
        self.score_note_label.setWordWrap(True)
        constraints_grid.addWidget(self.score_note_label, 5, 0, 1, 3)
        config_layout.addWidget(constraints_card)

        self.limits_card = QFrame()
        self.limits_card.setObjectName("genPartsCard")
        limits_layout = QVBoxLayout(self.limits_card)
        limits_layout.setContentsMargins(14, 12, 14, 12)
        self.limits_title = QLabel()
        self.limits_title.setObjectName("genSectionTitle")
        limits_layout.addWidget(self.limits_title)
        self.limits_scroll = QScrollArea()
        self.limits_scroll.setWidgetResizable(True)
        self.limits_scroll.setMaximumHeight(230)
        self.limits_body = QWidget()
        self.limits_grid = QGridLayout(self.limits_body)
        self.limits_grid.setContentsMargins(0, 0, 0, 0)
        self.limits_scroll.setWidget(self.limits_body)
        limits_layout.addWidget(self.limits_scroll)
        config_layout.addWidget(self.limits_card)

        run_card = QFrame()
        run_card.setObjectName("genConfigCard")
        run_layout = QGridLayout(run_card)
        run_layout.setContentsMargins(14, 12, 14, 12)
        self.effort_label = QLabel()
        self.top_n_label = QLabel()
        self.score_profile_label = QLabel()
        self.effort_combo = PopupOnlyWheelComboBox()
        self.score_profile_combo = PopupOnlyWheelComboBox()
        self.top_n_spin = QSpinBox()
        self.top_n_spin.setRange(1, 10)
        self.top_n_spin.setValue(10)
        self.search_button = QPushButton()
        self.search_button.setObjectName("genAddButton")
        self.cancel_button = QPushButton()
        self.cancel_button.setEnabled(False)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        run_layout.addWidget(self.effort_label, 0, 0)
        run_layout.addWidget(self.top_n_label, 0, 1)
        run_layout.addWidget(self.score_profile_label, 0, 2)
        run_layout.addWidget(self.effort_combo, 1, 0)
        run_layout.addWidget(self.top_n_spin, 1, 1)
        run_layout.addWidget(self.score_profile_combo, 1, 2)
        run_layout.addWidget(self.search_button, 1, 3)
        run_layout.addWidget(self.cancel_button, 2, 3)
        run_layout.addWidget(self.status_label, 2, 0, 1, 3)
        run_layout.setColumnStretch(0, 2)
        run_layout.setColumnStretch(1, 1)
        run_layout.setColumnStretch(2, 1)
        run_layout.setColumnStretch(3, 1)
        config_layout.addWidget(run_card)
        config_layout.addStretch()
        config_scroll = QScrollArea()
        config_scroll.setWidgetResizable(True)
        config_scroll.setFrameShape(QFrame.Shape.NoFrame)
        config_scroll.setWidget(config_page)
        self.page_stack.addWidget(config_scroll)

        self.results_page = GodRollResultsPage(texts={})
        self.results_page.add_requested.connect(self._request_add)
        self.results_page.open_editor_requested.connect(self.open_editor_requested)
        self.results_page.close_requested.connect(lambda: self.page_stack.setCurrentIndex(0))
        self.page_stack.addWidget(self.results_page)

        self.rarity_combo.currentIndexChanged.connect(self._rarity_changed)
        self.manufacturer_combo.currentIndexChanged.connect(self._manufacturer_changed)
        self.weapon_type_combo.currentIndexChanged.connect(self._refresh_weapon_filters)
        self.weapon_combo.currentIndexChanged.connect(self._refresh_options)
        self.mode_combo.currentIndexChanged.connect(self._refresh_options)
        self.barrel_combo.currentIndexChanged.connect(self._refresh_dependent_elements)
        self.base_element_combo.currentIndexChanged.connect(self._refresh_dependent_elements)
        self.score_profile_combo.currentIndexChanged.connect(self._score_profile_changed)
        self.search_button.clicked.connect(self._start_search)
        self.cancel_button.clicked.connect(self._cancel_search)

    def _retranslate(self):
        self.title_label.setText(self._text("title"))
        for label, key in zip(self.source_labels, (
            "rarity", "manufacturer", "weapon_type", "weapon", "mode", "level", "select_flag"
        )):
            label.setText(self._text(key))
        for label, key in zip(self.constraint_labels, (
            "barrel", "torgue", "base_element", "secondary_element", "pearl_element"
        )):
            label.setText(self._text(key))
        self.force_element_check.setText(self._text("force_element"))
        self.force_element_check.setToolTip(self._text("force_hint"))
        self.score_note_label.setText(self._text("score_note"))
        self.limits_title.setText(self._text("limits"))
        self.effort_label.setText(self._text("effort"))
        self.top_n_label.setText(self._text("top_n"))
        self.score_profile_label.setText(self._text("score_profile"))
        self.search_button.setText(self._text("search"))
        self.cancel_button.setText(self._text("cancel"))
        if not self._worker:
            self.status_label.setText(self._text("idle"))
        self.live_banner.setText(self._text("offline_only"))

        current_mode = self.mode_combo.currentData()
        self.mode_combo.blockSignals(True)
        self.mode_combo.clear()
        self.mode_combo.addItem(self._text("legal"), "legal")
        self.mode_combo.addItem(self._text("unrestricted"), "unrestricted")
        index = self.mode_combo.findData(current_mode or "legal")
        self.mode_combo.setCurrentIndex(max(0, index))
        self.mode_combo.blockSignals(False)

        current_effort = self.effort_combo.currentData()
        self.effort_combo.clear()
        for key in ("fast", "balanced", "deep"):
            self.effort_combo.addItem(self._text(key), key)
        self.effort_combo.setCurrentIndex(max(0, self.effort_combo.findData(current_effort or "balanced")))

        current_profile = self.score_profile_combo.currentData()
        self.score_profile_combo.blockSignals(True)
        self.score_profile_combo.clear()
        for key in ("sustained_dps", "burst", "crit_element", "balanced"):
            self.score_profile_combo.addItem(self._text(f"score_profile_{key}"), key)
        profile_index = self.score_profile_combo.findData(current_profile or "sustained_dps")
        self.score_profile_combo.setCurrentIndex(max(0, profile_index))
        self.score_profile_combo.blockSignals(False)

        flags = resource_loader.get_flag_labels(self.current_lang)
        current_flag = self.flag_combo.currentText().split(" ")[0] if self.flag_combo.count() else "3"
        self.flag_combo.clear()
        self.flag_combo.addItems([flags[key] for key in ("1", "3", "5", "17", "33", "65", "129")])
        target = next((value for value in (flags[key] for key in flags) if value.startswith(current_flag + " ")), flags["3"])
        self.flag_combo.setCurrentText(target)

        result_texts = {
            "generated": self.generator_labels.get("generated", "Generated {count} legal weapons"),
            "no_results": self._text("no_results"),
            "select_result": self.generator_labels.get("select_result", "Select a generated weapon"),
            "no_element": self.generator_labels.get("no_element", "No Element"),
            "level_value": self.generator_labels.get("level_value", "Lv{level}"),
            "close": self.generator_buttons.get("close", self._text("cancel")),
            "add_one": self.generator_buttons.get("add_one", "Add This"),
            "add_all": self.generator_buttons.get("add_all", "Add All"),
            "copy_base85": self.generator_buttons.get("copy_base85", "Copy Base85"),
            "open_editor": self._text("open_editor"),
            "copied": (self.full_loc.get("weapon_gen_tab") or {}).get("dialogs", {}).get("base85_copied", "Base85 copied"),
            "legal": self.rule_loc.get("status_legal", self._text("legal")),
            "parts_title": self._text("parts_title"),
            "no_part_details": self._text("no_part_details"),
            "no_part_effect": self._text("no_part_effect"),
            "score_explanation": self._text("score_explanation"),
            "score_total": self._text("score_total"),
            "score_profile": self._text("score_profile"),
            "score_warning": self._text("score_warning"),
            "score_missing": self._text("score_missing"),
            "score_short": self._text("score_short"),
            **{f"score_profile_{key}": self._text(f"score_profile_{key}") for key in (
                "sustained_dps", "burst", "crit_element", "balanced"
            )},
            **{f"score_metric_{key}": self._text(f"score_metric_{key}") for key in (
                "dps", "damage", "fire_rate", "magazine", "critical_damage", "elemental_dps", "reload_time"
            )},
            **{key: self.stats_loc.get(key, key) for key in (
                "damage", "dps", "accuracy", "fire_rate", "reload_time", "magazine"
            )},
        }
        self.results_page.update_texts(result_texts)
        self._populate_filters()

    def update_language(self, lang):
        self.current_lang = lang
        full = resource_loader.load_json_resource(resource_loader.get_ui_localization_file(lang)) or {}
        self.full_loc = full
        self.loc = full.get("god_roll_tab") or {}
        self.taxonomy = (full.get("weapon_editor_tab") or {}).get("taxonomy") or {}
        self.stats_loc = (full.get("weapon_editor_tab") or {}).get("stats") or {}
        self.rule_loc = full.get("weapon_rules") or {}
        generator = full.get("weapon_gen_tab") or {}
        self.generator_labels = generator.get("labels") or {}
        self.generator_buttons = generator.get("buttons") or {}
        self.item_names = (
            resource_loader.load_json_resource("i18n/item_localization_zh-CN.json") or {}
            if lang == "zh-CN" else {}
        )
        self._retranslate()
        self._render_last_results()

    def _render_last_results(self):
        meta = self._last_result_meta
        if meta is None:
            return
        current_row = self.results_page.result_list.currentRow()
        results = [self._localize_result(row) for row in self._raw_results]
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
        mode = self._text(str(meta.get("mode") or "legal"))
        scope = self._text(
            "results_scope_exact" if meta.get("complete") else "results_scope"
        ).format(
            mode=mode,
            barrel=str(meta.get("barrel") or "—"),
            count=int(meta.get("top_n") or len(results)),
            profile=self._text(f"score_profile_{meta.get('score_profile') or 'sustained_dps'}"),
        )
        self.results_page.set_results(results, text, scope)
        if results and current_row >= 0:
            self.results_page.result_list.setCurrentRow(min(current_row, len(results) - 1))

    def _catalog_name(self, row):
        name = row.get("name_zh") if self.current_lang == "zh-CN" else row.get("name_en")
        name = name or row.get("name_en") or row.get("name_zh") or row.get("part")
        return str(name or row.get("composition_ref"))

    def _populate_filters(self):
        selected_rarity = self.rarity_combo.currentData() or "Legendary"
        selected_mfg = self.manufacturer_combo.currentData()
        selected_type = self.weapon_type_combo.currentData()
        selected_weapon = self.weapon_combo.currentData()
        self.rarity_combo.blockSignals(True)
        self.manufacturer_combo.blockSignals(True)
        self.weapon_type_combo.blockSignals(True)
        self.rarity_combo.clear()
        self.manufacturer_combo.clear()
        self.weapon_type_combo.clear()
        available_rarities = {row["rarity"] for row in self.catalog}
        for rarity in self._RARITY_ORDER:
            if rarity in available_rarities:
                self.rarity_combo.addItem(self._rarity_label(rarity), rarity)
        rarity_index = self.rarity_combo.findData(selected_rarity)
        self.rarity_combo.setCurrentIndex(rarity_index if rarity_index >= 0 else 0)
        selected_rarity = self.rarity_combo.currentData()
        rarity_rows = [row for row in self.catalog if row["rarity"] == selected_rarity]
        self.manufacturer_combo.addItem(self._text("auto"), None)
        self.weapon_type_combo.addItem(self._text("auto"), None)
        manufacturers = sorted({row["manufacturer"] for row in rarity_rows})
        for value in manufacturers:
            sample = next(row for row in rarity_rows if row["manufacturer"] == value)
            self.manufacturer_combo.addItem(self._manufacturer_label(value, sample["root_id"]), value)
        mfg_index = self.manufacturer_combo.findData(selected_mfg)
        self.manufacturer_combo.setCurrentIndex(mfg_index if mfg_index >= 0 else 0)
        selected_mfg = self.manufacturer_combo.currentData()
        type_rows = [
            row for row in rarity_rows
            if selected_mfg is None or row["manufacturer"] == selected_mfg
        ]
        for value in sorted({row["weapon_type"] for row in type_rows}):
            self.weapon_type_combo.addItem(self._weapon_type_label(value), value)
        type_index = self.weapon_type_combo.findData(selected_type)
        self.weapon_type_combo.setCurrentIndex(type_index if type_index >= 0 else 0)
        self.rarity_combo.blockSignals(False)
        self.manufacturer_combo.blockSignals(False)
        self.weapon_type_combo.blockSignals(False)
        self._refresh_weapon_filters(selected_weapon)

    def _rarity_changed(self, _index=None):
        self._populate_filters()

    def _manufacturer_changed(self, _index=None):
        selected_type = self.weapon_type_combo.currentData()
        selected_weapon = self.weapon_combo.currentData() if self.weapon_combo.count() else None
        rarity = self.rarity_combo.currentData()
        manufacturer = self.manufacturer_combo.currentData()
        rows = [
            row for row in self.catalog
            if row["rarity"] == rarity
            and (manufacturer is None or row["manufacturer"] == manufacturer)
        ]
        self.weapon_type_combo.blockSignals(True)
        self.weapon_type_combo.clear()
        self.weapon_type_combo.addItem(self._text("auto"), None)
        for value in sorted({row["weapon_type"] for row in rows}):
            self.weapon_type_combo.addItem(self._weapon_type_label(value), value)
        type_index = self.weapon_type_combo.findData(selected_type)
        self.weapon_type_combo.setCurrentIndex(type_index if type_index >= 0 else 0)
        self.weapon_type_combo.blockSignals(False)
        self._refresh_weapon_filters(selected_weapon)

    def _refresh_weapon_filters(self, selected=None):
        if isinstance(selected, int) or selected is None:
            selected = self.weapon_combo.currentData() if self.weapon_combo.count() else None
        rarity = self.rarity_combo.currentData()
        manufacturer = self.manufacturer_combo.currentData()
        weapon_type = self.weapon_type_combo.currentData()
        rows = [
            row for row in self.catalog
            if row["rarity"] == rarity
            and (manufacturer is None or row["manufacturer"] == manufacturer)
            and (weapon_type is None or row["weapon_type"] == weapon_type)
        ]
        rows.sort(key=lambda row: (row["weapon_type"], row["manufacturer"], self._catalog_name(row).casefold()))
        self._catalog_rows = rows
        self.weapon_combo.blockSignals(True)
        self.weapon_combo.clear()
        for row in rows:
            label = (
                f"{self._catalog_name(row)} · "
                f"{self._manufacturer_label(row['manufacturer'], row['root_id'])} "
                f"{self._weapon_type_label(row['weapon_type'])} · {self._rarity_label(row['rarity'])}"
            )
            self.weapon_combo.addItem(label, (row["root_id"], row["composition_ref"]))
        index = self._find_data(self.weapon_combo, selected)
        self.weapon_combo.setCurrentIndex(max(0, index))
        self.weapon_combo.blockSignals(False)
        self._refresh_options()

    def _element_name(self, ref):
        part = self.optimizer.part_label(ref).casefold()
        names = [key for key in self._ELEMENT_NAMES if key in part]
        labels = [self._ELEMENT_NAMES[key].get(self.current_lang, self._ELEMENT_NAMES[key]["en-US"]) for key in names]
        return " + ".join(dict.fromkeys(labels)) or f"{ref} · {self.optimizer.part_label(ref)}"

    def _fill_part_combo(
        self,
        combo,
        options,
        *,
        allow_none=False,
        none_legal=True,
        preserve=True,
        show_unavailable=False,
    ):
        previous = combo.currentData() if preserve else AUTO
        force = self.force_element_check.isChecked()
        selectable = force or any(row.get("legal", True) for row in options)
        combo.blockSignals(True)
        combo.clear()
        if show_unavailable and not selectable:
            combo.addItem(f"⚠ {self._text('unavailable')}", AUTO)
            combo.setToolTip(self._text("unavailable"))
            combo.blockSignals(False)
            return False
        combo.setToolTip("")
        combo.addItem(self._text("auto_available"), AUTO)
        if allow_none:
            combo.addItem(self._text("none"), NONE)
            item = combo.model().item(combo.count() - 1)
            if item is not None:
                item.setEnabled(bool(none_legal) or force)
        for row in options:
            label = self._element_name(row["ref"])
            if not row.get("legal", True):
                label = f"⚠ {label}"
            combo.addItem(label, row["ref"])
            item = combo.model().item(combo.count() - 1)
            if item is not None:
                item.setEnabled(bool(row.get("legal", True)) or force)
        selected_index = combo.findData(previous)
        if selected_index < 0 or not combo.model().item(selected_index).isEnabled():
            selected_index = 0
        combo.setCurrentIndex(selected_index)
        combo.blockSignals(False)
        return selectable

    def _refresh_options(self, *_args):
        if self._refreshing_options:
            return
        selected = self.weapon_combo.currentData()
        if not selected:
            self.search_button.setEnabled(False)
            return
        self._refreshing_options = True
        try:
            self.search_button.setEnabled(not self._live_mode and self._worker is None)
            root_id, composition_ref = selected
            mode = self.mode_combo.currentData() or "legal"
            previous_barrel = self.barrel_combo.currentData()
            self.barrel_combo.blockSignals(True)
            self.barrel_combo.clear()
            for row in self.optimizer.barrel_options(root_id, composition_ref):
                self.barrel_combo.addItem(f"{row['ref']} · {row['label']}", row["ref"])
            barrel_index = self.barrel_combo.findData(previous_barrel)
            self.barrel_combo.setCurrentIndex(barrel_index if barrel_index >= 0 else 0)
            self.barrel_combo.blockSignals(False)

            options = self.optimizer.composition_options(
                root_id,
                composition_ref,
                mode,
                fixed_barrel_ref=self.barrel_combo.currentData(),
            )
            previous_torgue = self.torgue_combo.currentData()
            torgue_modes = options.get("torgue_modes") or {}
            self._torgue_selectable = any(torgue_modes.get(key) for key in ("sticky", "impact"))
            self.torgue_combo.blockSignals(True)
            self.torgue_combo.clear()
            if not self._torgue_selectable:
                self.torgue_combo.addItem(f"⚠ {self._text('unavailable')}", "any")
                self.torgue_combo.setToolTip(self._text("unavailable"))
            else:
                self.torgue_combo.setToolTip("")
                self.torgue_combo.addItem(self._text("torgue_any"), "any")
                for key in ("sticky", "impact"):
                    reachable = bool(torgue_modes.get(key))
                    label = self._text(f"torgue_{key}")
                    self.torgue_combo.addItem(label if reachable else f"⚠ {label}", key)
                    item = self.torgue_combo.model().item(self.torgue_combo.count() - 1)
                    if item is not None:
                        item.setEnabled(reachable)
                torgue_index = self.torgue_combo.findData(previous_torgue)
                if torgue_index < 0 or not self.torgue_combo.model().item(torgue_index).isEnabled():
                    torgue_index = 0
                self.torgue_combo.setCurrentIndex(torgue_index)
            self.torgue_combo.blockSignals(False)
            self.torgue_combo.setEnabled(
                not self._live_mode and self._worker is None and self._torgue_selectable
            )

            none_legal = options.get("element_none_legal") or {}
            self._fill_part_combo(
                self.base_element_combo, options["body_elements"], allow_none=True,
                none_legal=none_legal.get("body_ele", True),
            )
            self._rebuild_group_limits(options["groups"])
            self.limits_card.setVisible(mode == "unrestricted")
        finally:
            self._refreshing_options = False
        self._refresh_dependent_elements()

    def _refresh_dependent_elements(self, *_args):
        if self._refreshing_options:
            return
        selected = self.weapon_combo.currentData()
        if not selected:
            return
        root_id, composition_ref = selected
        mode = self.mode_combo.currentData() or "legal"
        options = self.optimizer.composition_options(
            root_id,
            composition_ref,
            mode,
            fixed_barrel_ref=self.barrel_combo.currentData(),
            base_element_ref=self.base_element_combo.currentData(),
        )
        none_legal = options.get("element_none_legal") or {}
        self._secondary_selectable = self._fill_part_combo(
            self.secondary_element_combo, options["secondary_elements"], allow_none=True,
            none_legal=none_legal.get("secondary_ele", True),
            show_unavailable=True,
        )
        self._pearl_selectable = self._fill_part_combo(
            self.pearl_element_combo, options["pearl_elements"], allow_none=False,
            show_unavailable=True,
        )
        controls_enabled = not self._live_mode and self._worker is None
        self.secondary_element_combo.setEnabled(controls_enabled and self._secondary_selectable)
        self.pearl_element_combo.setEnabled(controls_enabled and self._pearl_selectable)

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _rebuild_group_limits(self, groups):
        self._clear_layout(self.limits_grid)
        self._group_limit_spins = {}
        for column, key in enumerate(("group", "pool", "minimum", "maximum")):
            self.limits_grid.addWidget(QLabel(self._text(key)), 0, column)
        row_index = 1
        for group, row in sorted(groups.items()):
            if group == "barrel":
                continue
            hard_max = max(0, int(row.get("hard_max", row.get("max", 1))))
            minimum = QSpinBox()
            maximum = QSpinBox()
            minimum.setRange(0, hard_max)
            maximum.setRange(0, hard_max)
            minimum.setValue(min(int(row.get("min", 0)), hard_max))
            maximum.setValue(min(int(row.get("max", hard_max)), hard_max))
            minimum.valueChanged.connect(lambda value, other=maximum: other.setValue(max(other.value(), value)))
            maximum.valueChanged.connect(lambda value, other=minimum: other.setValue(min(other.value(), value)))
            self.limits_grid.addWidget(QLabel(self._group_label(group)), row_index, 0)
            self.limits_grid.addWidget(QLabel(str(row.get("pool_size", 0))), row_index, 1)
            self.limits_grid.addWidget(minimum, row_index, 2)
            self.limits_grid.addWidget(maximum, row_index, 3)
            self._group_limit_spins[group] = (minimum, maximum)
            row_index += 1
        self.limits_grid.setColumnStretch(0, 1)

    def _request(self):
        root_id, composition_ref = self.weapon_combo.currentData()
        effort = self.effort_combo.currentData() or "balanced"
        samples, seconds = {
            "fast": (7_500, 3.0),
            "balanced": (25_000, 8.0),
            "deep": (150_000, 30.0),
        }[effort]
        limits = {
            group: (minimum.value(), maximum.value())
            for group, (minimum, maximum) in self._group_limit_spins.items()
        }
        return GodRollRequest(
            root_id=str(root_id),
            composition_ref=str(composition_ref),
            level=self.level_spin.value(),
            mode=str(self.mode_combo.currentData() or "legal"),
            fixed_barrel_ref=self.barrel_combo.currentData(),
            torgue_mode=str(self.torgue_combo.currentData() or "any"),
            base_element_ref=self.base_element_combo.currentData(),
            secondary_element_ref=self.secondary_element_combo.currentData(),
            pearl_element_ref=self.pearl_element_combo.currentData(),
            allow_illegal_elements=self.force_element_check.isChecked(),
            group_limits=limits,
            top_n=self.top_n_spin.value(),
            max_samples=samples,
            time_limit=seconds,
            score_profile=str(self.score_profile_combo.currentData() or "sustained_dps"),
        )

    def _score_profile_changed(self, _index):
        """Never leave an old result page mislabeled with a new profile."""
        if not self._last_result_meta:
            return
        current = str(self.score_profile_combo.currentData() or "sustained_dps")
        if current == str(self._last_result_meta.get("score_profile") or "sustained_dps"):
            return
        self._raw_results = []
        self._last_result_meta = None
        self.results_page.set_results([])
        self.page_stack.setCurrentIndex(0)
        self.status_label.setText(self._text("idle"))

    def _set_busy(self, busy):
        self.search_button.setEnabled(not busy and not self._live_mode and bool(self.weapon_combo.currentData()))
        self.cancel_button.setEnabled(busy)
        for widget in (
            self.rarity_combo, self.manufacturer_combo, self.weapon_type_combo, self.weapon_combo, self.mode_combo,
            self.level_spin, self.barrel_combo, self.torgue_combo, self.base_element_combo,
            self.force_element_check, self.effort_combo, self.top_n_spin,
            self.score_profile_combo,
        ):
            widget.setEnabled(not busy and not self._live_mode)
        controls_enabled = not busy and not self._live_mode
        self.torgue_combo.setEnabled(controls_enabled and self._torgue_selectable)
        self.secondary_element_combo.setEnabled(controls_enabled and self._secondary_selectable)
        self.pearl_element_combo.setEnabled(controls_enabled and self._pearl_selectable)

    def _start_search(self):
        if self._worker is not None or self._live_mode or not self.weapon_combo.currentData():
            return
        try:
            request = self._request()
        except Exception as exc:
            QMessageBox.warning(self, self._text("title"), str(exc))
            return
        worker = _GodRollWorker(self.optimizer, request, self.current_lang, self)
        worker.progress.connect(self._on_progress)
        worker.completed.connect(self._on_completed)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._worker_finished)
        self._worker = worker
        self._set_busy(True)
        self.status_label.setText(self._text("running").format(attempted=0, accepted=0, best="—"))
        self.worker_started.emit(worker)
        worker.start()

    def _cancel_search(self):
        if self._worker is not None:
            self._worker.cancel()
            self.cancel_button.setEnabled(False)

    def _on_progress(self, row):
        best = float(row.get("best_score") or row.get("best_dps") or 0)
        self.status_label.setText(self._text("running").format(
            attempted=row.get("attempted", 0), accepted=row.get("accepted", 0), best=f"{best:.2f}"
        ))

    def _on_completed(self, result):
        self._raw_results = [dict(row) for row in (result.get("results") or ())]
        self._last_result_meta = {
            "complete": bool(result.get("complete")),
            "cancelled": bool(result.get("cancelled")),
            "attempted": result.get("attempted", 0),
            "exact_examined": result.get("exact_examined", result.get("attempted", 0)),
            "elapsed": float(result.get("elapsed") or 0),
            "mode": str(self.mode_combo.currentData() or "legal"),
            "score_profile": str(result.get("score_profile") or self.score_profile_combo.currentData() or "sustained_dps"),
            "barrel": self.barrel_combo.currentText() or "—",
            "top_n": self.top_n_spin.value(),
        }
        self._render_last_results()
        self.results_page.set_add_status("", busy=False)
        self.page_stack.setCurrentIndex(1)

    def _on_failed(self, error):
        QMessageBox.critical(self, self._text("title"), self._text("error").format(error=error))
        self.status_label.setText(self._text("error").format(error=error))

    def _worker_finished(self):
        worker = self.sender()
        if worker is self._worker:
            self._worker = None
            self._set_busy(False)
        worker.deleteLater()

    def _request_add(self, serials):
        if not serials or self._add_busy or self._live_mode:
            return
        self._add_busy = True
        self.results_page.set_add_status(self._text("add_start").format(count=len(serials)), busy=True)
        flag = self.flag_combo.currentText().split(" ")[0]
        self.batch_add_to_backpack_requested.emit(list(serials), flag)

    def update_roll_add_progress(self, current, total, success, fail):
        self.results_page.set_add_status(self._text("add_progress").format(
            current=current, total=total, success=success, fail=fail
        ), busy=True)

    def finalize_roll_batch_add(self, success, fail):
        self._add_busy = False
        self.results_page.set_add_status(self._text("add_done").format(success=success, fail=fail), busy=False)

    def reject_roll_batch_add(self, message):
        self._add_busy = False
        self.results_page.set_add_status(str(message), busy=False)

    def set_character_level(self, level):
        try:
            self._character_level = max(1, int(level))
        except (TypeError, ValueError):
            return
        self.level_spin.setValue(self._character_level)

    def set_live_mode(self, enabled):
        self._live_mode = bool(enabled)
        self.live_banner.setVisible(self._live_mode)
        if self._live_mode:
            self._cancel_search()
        self._set_busy(self._worker is not None)
        self.results_page.set_add_status(
            self.results_page.status_label.text(),
            busy=self._live_mode or self._add_busy,
        )
