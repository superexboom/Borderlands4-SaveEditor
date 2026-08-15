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

from core import resource_loader
from core.weapon_optimizer import AUTO, NONE, GodRollRequest, WeaponGodRollOptimizer
from .qt_catalog_picker import PopupOnlyWheelComboBox
from .qt_weapon_roll_dialog import WeaponRollResultsPage


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
    worker_started = pyqtSignal(object)

    _FALLBACK = {
        "title": "God Roll Optimizer",
        "source": "Target weapon",
        "manufacturer": "Manufacturer",
        "weapon_type": "Weapon Type",
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
        "none": "No element",
        "force_element": "Allow forced illegal element",
        "force_hint": "The result is marked modified when only the element violates the native build rules.",
        "score_note": "Ranking uses verified paper sustained DPS; some red-text, ricochet, and delayed sticky mechanics are not fully modeled.",
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
        "running": "Explored {attempted} · valid {accepted} · best DPS {best}",
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
        "results_scope": "{mode} · fixed barrel {barrel} · budget-best Top {count}",
        "results_scope_exact": "{mode} · fixed barrel {barrel} · proven Top {count}",
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
        self.manufacturer_combo = PopupOnlyWheelComboBox()
        self.weapon_type_combo = PopupOnlyWheelComboBox()
        self.weapon_combo = PopupOnlyWheelComboBox()
        self.mode_combo = PopupOnlyWheelComboBox()
        self.level_spin = QSpinBox()
        self.level_spin.setRange(1, 999)
        self.level_spin.setValue(self._character_level)
        self.flag_combo = PopupOnlyWheelComboBox()
        source_widgets = (
            self.manufacturer_combo, self.weapon_type_combo, self.weapon_combo,
            self.mode_combo, self.level_spin, self.flag_combo,
        )
        self.source_labels = [QLabel() for _ in range(6)]
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
        self.effort_combo = PopupOnlyWheelComboBox()
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
        run_layout.addWidget(self.effort_combo, 1, 0)
        run_layout.addWidget(self.top_n_spin, 1, 1)
        run_layout.addWidget(self.search_button, 1, 2)
        run_layout.addWidget(self.cancel_button, 1, 3)
        run_layout.addWidget(self.status_label, 2, 0, 1, 4)
        run_layout.setColumnStretch(0, 2)
        run_layout.setColumnStretch(1, 1)
        run_layout.setColumnStretch(2, 1)
        run_layout.setColumnStretch(3, 1)
        config_layout.addWidget(run_card)
        config_layout.addStretch()
        self.page_stack.addWidget(config_page)

        self.results_page = WeaponRollResultsPage(texts={})
        self.results_page.add_requested.connect(self._request_add)
        self.results_page.close_requested.connect(lambda: self.page_stack.setCurrentIndex(0))
        self.page_stack.addWidget(self.results_page)

        self.manufacturer_combo.currentIndexChanged.connect(self._refresh_weapon_filters)
        self.weapon_type_combo.currentIndexChanged.connect(self._refresh_weapon_filters)
        self.weapon_combo.currentIndexChanged.connect(self._refresh_options)
        self.mode_combo.currentIndexChanged.connect(self._refresh_options)
        self.search_button.clicked.connect(self._start_search)
        self.cancel_button.clicked.connect(self._cancel_search)

    def _retranslate(self):
        self.title_label.setText(self._text("title"))
        for label, key in zip(self.source_labels, (
            "manufacturer", "weapon_type", "weapon", "mode", "level", "select_flag"
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

        flags = resource_loader.get_flag_labels(self.current_lang)
        current_flag = self.flag_combo.currentText().split(" ")[0] if self.flag_combo.count() else "3"
        self.flag_combo.clear()
        self.flag_combo.addItems([flags[key] for key in ("1", "3", "5", "17", "33", "65", "129")])
        target = next((value for value in (flags[key] for key in flags) if value.startswith(current_flag + " ")), flags["3"])
        self.flag_combo.setCurrentText(target)

        result_texts = {
            "generated": self._text("done"),
            "no_results": self._text("no_results"),
            "close": self._text("cancel"),
            "add_one": "添加此结果" if self.current_lang == "zh-CN" else "Add This",
            "add_all": "全部添加" if self.current_lang == "zh-CN" else "Add All",
            "copy_base85": "复制 Base85" if self.current_lang == "zh-CN" else "Copy Base85",
            "legal": self._text("legal"),
        }
        self.results_page.update_texts(result_texts)
        self._populate_filters()

    def update_language(self, lang):
        self.current_lang = lang
        full = resource_loader.load_json_resource(resource_loader.get_ui_localization_file(lang)) or {}
        self.loc = full.get("god_roll_tab") or {}
        self._retranslate()

    def _catalog_name(self, row):
        name = row.get("name_zh") if self.current_lang == "zh-CN" else row.get("name_en")
        name = name or row.get("name_en") or row.get("name_zh") or row.get("part")
        return str(name or row.get("composition_ref"))

    def _populate_filters(self):
        selected_mfg = self.manufacturer_combo.currentData()
        selected_type = self.weapon_type_combo.currentData()
        selected_weapon = self.weapon_combo.currentData()
        self.manufacturer_combo.blockSignals(True)
        self.weapon_type_combo.blockSignals(True)
        self.manufacturer_combo.clear()
        self.weapon_type_combo.clear()
        self.manufacturer_combo.addItem(self._text("auto"), None)
        self.weapon_type_combo.addItem(self._text("auto"), None)
        for value in sorted({row["manufacturer"] for row in self.catalog}):
            self.manufacturer_combo.addItem(self._humanize(value), value)
        for value in sorted({row["weapon_type"] for row in self.catalog}):
            self.weapon_type_combo.addItem(self._humanize(value), value)
        self.manufacturer_combo.setCurrentIndex(max(0, self.manufacturer_combo.findData(selected_mfg)))
        self.weapon_type_combo.setCurrentIndex(max(0, self.weapon_type_combo.findData(selected_type)))
        self.manufacturer_combo.blockSignals(False)
        self.weapon_type_combo.blockSignals(False)
        self._refresh_weapon_filters(selected_weapon)

    def _refresh_weapon_filters(self, selected=None):
        if isinstance(selected, int) or selected is None:
            selected = self.weapon_combo.currentData() if self.weapon_combo.count() else None
        manufacturer = self.manufacturer_combo.currentData()
        weapon_type = self.weapon_type_combo.currentData()
        rows = [
            row for row in self.catalog
            if (manufacturer is None or row["manufacturer"] == manufacturer)
            and (weapon_type is None or row["weapon_type"] == weapon_type)
        ]
        rows.sort(key=lambda row: (row["weapon_type"], row["manufacturer"], self._catalog_name(row).casefold()))
        self._catalog_rows = rows
        self.weapon_combo.blockSignals(True)
        self.weapon_combo.clear()
        for row in rows:
            label = f"{self._catalog_name(row)} · {self._humanize(row['manufacturer'])} {row['weapon_type']} · {row['rarity']}"
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
    ):
        previous = combo.currentData() if preserve else AUTO
        force = self.force_element_check.isChecked()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(self._text("auto"), AUTO)
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

    def _refresh_options(self):
        selected = self.weapon_combo.currentData()
        if not selected:
            self.search_button.setEnabled(False)
            return
        self.search_button.setEnabled(not self._live_mode and self._worker is None)
        root_id, composition_ref = selected
        mode = self.mode_combo.currentData() or "legal"
        options = self.optimizer.composition_options(root_id, composition_ref, mode)
        previous_barrel = self.barrel_combo.currentData()
        self.barrel_combo.clear()
        for row in options["barrels"]:
            self.barrel_combo.addItem(f"{row['ref']} · {row['label']}", row["ref"])
        self.barrel_combo.setCurrentIndex(max(0, self.barrel_combo.findData(previous_barrel)))

        previous_torgue = self.torgue_combo.currentData()
        self.torgue_combo.clear()
        self.torgue_combo.addItem(self._text("torgue_any"), "any")
        self.torgue_combo.addItem(self._text("torgue_sticky"), "sticky")
        self.torgue_combo.addItem(self._text("torgue_impact"), "impact")
        self.torgue_combo.setCurrentIndex(max(0, self.torgue_combo.findData(previous_torgue)))
        for index, key in ((1, "sticky"), (2, "impact")):
            item = self.torgue_combo.model().item(index)
            if item is not None:
                item.setEnabled(bool(options["torgue_modes"].get(key)) or mode == "unrestricted")
        selected_torgue = str(self.torgue_combo.currentData() or "any")
        if selected_torgue in ("sticky", "impact") and not (
            options["torgue_modes"].get(selected_torgue) or mode == "unrestricted"
        ):
            self.torgue_combo.setCurrentIndex(0)

        none_legal = options.get("element_none_legal") or {}
        self._fill_part_combo(
            self.base_element_combo, options["body_elements"], allow_none=True,
            none_legal=none_legal.get("body_ele", True),
        )
        self._fill_part_combo(
            self.secondary_element_combo, options["secondary_elements"], allow_none=True,
            none_legal=none_legal.get("secondary_ele", True),
        )
        self._fill_part_combo(self.pearl_element_combo, options["pearl_elements"], allow_none=False)
        self._rebuild_group_limits(options["groups"])
        self.limits_card.setVisible(mode == "unrestricted")

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
            self.limits_grid.addWidget(QLabel(self._humanize(group)), row_index, 0)
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
        )

    def _set_busy(self, busy):
        self.search_button.setEnabled(not busy and not self._live_mode and bool(self.weapon_combo.currentData()))
        self.cancel_button.setEnabled(busy)
        for widget in (
            self.manufacturer_combo, self.weapon_type_combo, self.weapon_combo, self.mode_combo,
            self.level_spin, self.barrel_combo, self.torgue_combo, self.base_element_combo,
            self.secondary_element_combo, self.pearl_element_combo, self.force_element_check,
            self.effort_combo, self.top_n_spin,
        ):
            widget.setEnabled(not busy and not self._live_mode)

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
        best = int(float(row.get("best_dps") or 0))
        self.status_label.setText(self._text("running").format(
            attempted=row.get("attempted", 0), accepted=row.get("accepted", 0), best=f"{best:,}"
        ))

    def _on_completed(self, result):
        results = list(result.get("results") or ())
        text = self._text("done_exact" if result.get("complete") else "done").format(
            count=len(results),
            attempted=result.get("attempted", 0),
            frontier=result.get("exact_examined", result.get("attempted", 0)),
            elapsed=float(result.get("elapsed") or 0),
        )
        if result.get("cancelled"):
            text = self._text("cancelled") + " " + text
        if not results:
            text = self._text("no_results")
        barrel = self.barrel_combo.currentText() or "—"
        scope = self._text("results_scope_exact" if result.get("complete") else "results_scope").format(
            mode=self.mode_combo.currentText(), barrel=barrel, count=self.top_n_spin.value()
        )
        self.results_page.set_results(results, text, scope)
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
