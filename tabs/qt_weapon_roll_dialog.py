"""Weapon roll option dialog and the generator's embedded result page."""

from __future__ import annotations

from typing import Any, Iterable

from PyQt6 import QtCore, QtGui, QtWidgets

from .qt_items_tab import WEAPON_CARD_RARITY_COLORS


def _text(value: Any) -> str:
    return str(value or "").strip()


def _catalog_value(row: dict[str, Any], field: str) -> Any:
    return row.get({
        "manufacturer": "manufacturer",
        "weapon_type": "weapon_type",
        "rarity": "rarity",
        "composition_ref": "composition_ref",
    }[field])


class WeaponRollOptionsWidget(QtWidgets.QWidget):
    """Compact filters embedded in the lucky button's native menu."""

    roll_requested = QtCore.pyqtSignal(dict, int)

    def __init__(self, catalog: Iterable[dict[str, Any]], parent=None, texts=None,
                 constraints=None, count=5):
        super().__init__(parent)
        self.setObjectName("weaponRollOptionsWidget")
        self._catalog = [dict(row) for row in catalog]
        self._t = dict(texts or {})
        self._syncing_named = False
        self.setMinimumWidth(390)

        root = QtWidgets.QVBoxLayout(self)
        title = QtWidgets.QLabel(self._t.get("constraints_title", "Roll Options"))
        title.setObjectName("genSectionTitle")
        root.addWidget(title)
        form = QtWidgets.QFormLayout()
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.manufacturer_combo = self._combo("manufacturer", "manufacturer_label")
        self.weapon_type_combo = self._combo("weapon_type", "weapon_type_label")
        self.rarity_combo = self._combo("rarity", "rarity_label")
        self.named_weapon_combo = self._named_combo()
        self.count_spin = QtWidgets.QSpinBox()
        self.count_spin.setRange(1, 50)
        self.count_spin.setValue(max(1, min(50, int(count))))
        form.addRow(self._t.get("manufacturer", "Manufacturer"), self.manufacturer_combo)
        form.addRow(self._t.get("weapon_type", "Weapon Type"), self.weapon_type_combo)
        form.addRow(self._t.get("rarity", "Rarity"), self.rarity_combo)
        form.addRow(self._t.get("named_weapon", "Named Weapon"), self.named_weapon_combo)
        form.addRow(self._t.get("count", "Quantity"), self.count_spin)
        root.addLayout(form)

        context = QtWidgets.QLabel(self._t.get("current_context", "Uses the current level and Flag"))
        context.setObjectName("genContextHint")
        root.addWidget(context)
        hint = QtWidgets.QLabel(self._t.get("roll_scope_tip", ""))
        hint.setObjectName("genHint")
        hint.setWordWrap(True)
        root.addWidget(hint)
        self.match_label = QtWidgets.QLabel()
        root.addWidget(self.match_label)

        self.roll_button = QtWidgets.QPushButton(self._t.get("roll", "Roll"))
        self.roll_button.setObjectName("genRollButton")
        self.roll_button.clicked.connect(
            lambda: self.roll_requested.emit(self.constraints(), self.count_spin.value())
        )
        root.addWidget(self.roll_button)

        self.named_weapon_combo.currentIndexChanged.connect(self._on_named_changed)
        for combo in (self.manufacturer_combo, self.weapon_type_combo, self.rarity_combo):
            combo.currentIndexChanged.connect(self._update_match_count)

        for field, combo in (
            ("manufacturer", self.manufacturer_combo),
            ("weapon_type", self.weapon_type_combo),
            ("rarity", self.rarity_combo),
            ("composition_ref", self.named_weapon_combo),
        ):
            self._set_combo_data(combo, (constraints or {}).get(field))
        self._on_named_changed()

    def _combo(self, value_key, label_key):
        combo = QtWidgets.QComboBox()
        combo.addItem(self._t.get("random", "Random"), None)
        values = {}
        for row in self._catalog:
            value = row.get(value_key)
            if value not in (None, ""):
                values.setdefault(value, row.get(label_key) or value)
        for value, label in sorted(values.items(), key=lambda item: str(item[1]).casefold()):
            combo.addItem(str(label), value)
        return combo

    def _named_combo(self):
        combo = QtWidgets.QComboBox()
        combo.addItem(self._t.get("random", "Random"), None)
        rows = []
        for row in self._catalog:
            if not row.get("is_named"):
                continue
            detail = " · ".join(filter(None, (
                row.get("manufacturer_label"), row.get("weapon_type_label"), row.get("rarity_label")
            )))
            rows.append((f"{row.get('name')} — {detail}", row.get("composition_ref")))
        for label, ref in sorted(rows, key=lambda item: item[0].casefold()):
            combo.addItem(label, ref)
        return combo

    @staticmethod
    def _set_combo_data(combo, value):
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _on_named_changed(self):
        if self._syncing_named:
            return
        ref = self.named_weapon_combo.currentData()
        row = next((item for item in self._catalog if item.get("composition_ref") == ref), None)
        self._syncing_named = True
        try:
            if row:
                self._set_combo_data(self.manufacturer_combo, row.get("manufacturer"))
                self._set_combo_data(self.weapon_type_combo, row.get("weapon_type"))
                self._set_combo_data(self.rarity_combo, row.get("rarity"))
            for combo in (self.manufacturer_combo, self.weapon_type_combo, self.rarity_combo):
                combo.setEnabled(row is None)
        finally:
            self._syncing_named = False
        self._update_match_count()

    def constraints(self):
        return {
            "manufacturer": self.manufacturer_combo.currentData(),
            "weapon_type": self.weapon_type_combo.currentData(),
            "rarity": self.rarity_combo.currentData(),
            "composition_ref": self.named_weapon_combo.currentData(),
        }

    def matching_catalog(self):
        selected = self.constraints()
        return [
            row for row in self._catalog
            if all(value is None or _catalog_value(row, field) == value for field, value in selected.items())
        ]

    def _update_match_count(self):
        if self._syncing_named:
            return
        count = len(self.matching_catalog())
        self.match_label.setText(
            self._t.get("matches", "Matches: {count}").format(count=count)
            if count else self._t.get("no_matches", "No matches")
        )
        self.roll_button.setEnabled(count > 0)

class WeaponRollResultsPage(QtWidgets.QWidget):
    """Embedded result browser matching the generator's two-page layout."""

    add_requested = QtCore.pyqtSignal(list)
    close_requested = QtCore.pyqtSignal()
    _STAT_KEYS = ("damage", "dps", "accuracy", "fire_rate", "reload_time", "magazine")

    def __init__(self, parent=None, texts=None):
        super().__init__(parent)
        self.setObjectName("weaponRollResultsPage")
        self._t = dict(texts or {})
        self._results = []

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        summary_row = QtWidgets.QHBoxLayout()
        self.summary_label = QtWidgets.QLabel(self._t.get("no_results", "No generated weapons yet"))
        self.summary_label.setObjectName("rollSummary")
        self.summary_label.setWordWrap(True)
        self.scope_label = QtWidgets.QLabel("")
        self.scope_label.setObjectName("rollScope")
        self.scope_label.setWordWrap(True)
        summary_row.addWidget(self.summary_label)
        summary_row.addWidget(self.scope_label, 1)
        root.addLayout(summary_row)

        body = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        body.setChildrenCollapsible(False)
        self.result_list = QtWidgets.QListWidget()
        self.result_list.setObjectName("rollResultList")
        self.result_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.result_list.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.result_list.setUniformItemSizes(True)
        self.result_list.setWordWrap(True)
        self.result_list.setTextElideMode(QtCore.Qt.TextElideMode.ElideNone)
        self.result_list.currentRowChanged.connect(self._show_result)
        self.result_list.itemDoubleClicked.connect(lambda _item: self._add_current())
        body.addWidget(self.result_list)

        self.detail_card = QtWidgets.QFrame()
        self.detail_card.setObjectName("rollDetailCard")
        detail = QtWidgets.QVBoxLayout(self.detail_card)
        detail.setContentsMargins(18, 16, 18, 16)
        detail.setSpacing(10)

        title_row = QtWidgets.QHBoxLayout()
        self.detail_name = QtWidgets.QLabel("—")
        self.detail_name.setObjectName("rollDetailName")
        self.detail_name.setWordWrap(True)
        title_row.addWidget(self.detail_name, 1)
        self.detail_status = QtWidgets.QLabel("—")
        self.detail_status.setObjectName("rollDetailStatus")
        title_row.addWidget(self.detail_status, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        detail.addLayout(title_row)
        self.detail_meta = QtWidgets.QLabel("—")
        self.detail_meta.setObjectName("rollDetailMeta")
        self.detail_meta.setWordWrap(True)
        detail.addWidget(self.detail_meta)

        stats_frame = QtWidgets.QFrame()
        stats_frame.setObjectName("rollDetailStats")
        stats_grid = QtWidgets.QGridLayout(stats_frame)
        stats_grid.setContentsMargins(0, 0, 0, 0)
        stats_grid.setSpacing(1)
        self.stat_values = {}
        for index, key in enumerate(self._STAT_KEYS):
            row, column = divmod(index, 3)
            cell = QtWidgets.QFrame()
            cell.setObjectName("rollStatCell")
            cell_layout = QtWidgets.QVBoxLayout(cell)
            cell_layout.setContentsMargins(8, 8, 8, 8)
            label = QtWidgets.QLabel(self._t.get(key, key))
            label.setObjectName("rollStatName")
            label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            value = QtWidgets.QLabel("—")
            value.setObjectName("rollStatValue")
            value.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            cell_layout.addWidget(label)
            cell_layout.addWidget(value)
            stats_grid.addWidget(cell, row, column)
            stats_grid.setColumnStretch(column, 1)
            self.stat_values[key] = value
        detail.addWidget(stats_frame)

        actions = QtWidgets.QHBoxLayout()
        self.add_one_button = QtWidgets.QPushButton(self._t.get("add_one", "Add This"))
        self.add_one_button.setObjectName("genAddButton")
        self.copy_button = QtWidgets.QPushButton(self._t.get("copy_base85", "Copy Base85"))
        self.add_one_button.clicked.connect(self._add_current)
        self.copy_button.clicked.connect(self._copy_current)
        actions.addWidget(self.add_one_button)
        actions.addWidget(self.copy_button)
        actions.addStretch()
        detail.addLayout(actions)
        detail.addStretch()
        body.addWidget(self.detail_card)
        body.setStretchFactor(0, 2)
        body.setStretchFactor(1, 3)
        body.setSizes([440, 660])
        root.addWidget(body, 1)

        footer = QtWidgets.QHBoxLayout()
        self.status_label = QtWidgets.QLabel("")
        footer.addWidget(self.status_label, 1)
        close_button = QtWidgets.QPushButton(self._t.get("close", "Close"))
        self.add_all_button = QtWidgets.QPushButton(self._t.get("add_all", "Add All"))
        self.add_all_button.setObjectName("genAddButton")
        close_button.clicked.connect(self.close_requested)
        self.add_all_button.clicked.connect(self._add_all)
        footer.addWidget(close_button)
        footer.addWidget(self.add_all_button)
        root.addLayout(footer)
        self._show_result(-1)

    @staticmethod
    def _serial(result):
        return _text((result or {}).get("serial"))

    def set_results(self, results: Iterable[dict[str, Any]], summary="", scope=""):
        self._results = [dict(result) for result in results]
        self.result_list.clear()
        for result in self._results:
            formatted = result.get("formatted_stats") or {}
            meta = " · ".join(filter(None, (
                result.get("manufacturer"), result.get("weapon_type"),
                result.get("rarity"), result.get("element") or self._t.get("no_element", "No Element"),
            )))
            stats = " · ".join((
                f"{self._t.get('damage', 'Damage')} {formatted.get('damage') or '—'}",
                f"DPS {formatted.get('dps') or '—'}",
                f"{self._t.get('accuracy', 'Accuracy')} {formatted.get('accuracy') or '—'}",
                f"{self._t.get('fire_rate', 'Fire Rate')} {formatted.get('fire_rate') or '—'}",
                f"{self._t.get('reload_time', 'Reload')} {formatted.get('reload_time') or '—'}",
                f"{self._t.get('magazine', 'Magazine')} {formatted.get('magazine') or '—'}",
            ))
            item = QtWidgets.QListWidgetItem(f"{result.get('name') or '—'}\n{meta}\n{stats}")
            item.setData(QtCore.Qt.ItemDataRole.UserRole, result)
            item.setToolTip(_text(result.get("tooltip")))
            item.setSizeHint(QtCore.QSize(0, 96))
            rarity_key = _text(result.get("rarity_key") or result.get("rarity")).casefold()
            color = QtGui.QColor(WEAPON_CARD_RARITY_COLORS.get(rarity_key, "#78909C"))
            background = QtGui.QColor(color)
            background.setAlpha(28)
            item.setBackground(QtGui.QBrush(background))
            self.result_list.addItem(item)
        self.summary_label.setText(summary or self._t.get("generated", "Generated {count} legal weapons").format(
            count=len(self._results)
        ))
        self.scope_label.setText(scope)
        self.add_all_button.setEnabled(bool(self._results))
        self.result_list.setCurrentRow(0 if self._results else -1)

    def _current_result(self):
        item = self.result_list.currentItem()
        return item.data(QtCore.Qt.ItemDataRole.UserRole) if item else None

    def _show_result(self, _row):
        result = self._current_result()
        enabled = bool(result and self._serial(result))
        self.add_one_button.setEnabled(enabled)
        self.copy_button.setEnabled(enabled)
        if not result:
            self.detail_name.setText("—")
            self.detail_meta.setText(self._t.get("select_result", "Select a generated weapon"))
            self.detail_status.setText("—")
            self.detail_status.setProperty("ruleStatus", "unknown")
            self.detail_status.style().unpolish(self.detail_status)
            self.detail_status.style().polish(self.detail_status)
            for value in self.stat_values.values():
                value.setText("—")
            return
        self.detail_name.setText(_text(result.get("name")) or "—")
        self.detail_meta.setText(" · ".join(filter(None, (
            result.get("manufacturer"), result.get("weapon_type"), result.get("rarity"),
            self._t.get("level_value", "Lv{level}").format(level=result.get("level") or "—"),
        ))))
        self.detail_status.setText(f"✓ {result.get('status_label') or self._t.get('legal', 'Legal')}")
        self.detail_status.setProperty("ruleStatus", result.get("status") or "legal")
        self.detail_status.style().unpolish(self.detail_status)
        self.detail_status.style().polish(self.detail_status)
        formatted = result.get("formatted_stats") or {}
        for key, value in self.stat_values.items():
            value.setText(str(formatted.get(key) or "—"))

    def _add_current(self):
        serial = self._serial(self._current_result())
        if serial:
            self.add_requested.emit([serial])

    def _add_all(self):
        serials = [self._serial(result) for result in self._results]
        serials = [serial for serial in serials if serial]
        if serials:
            self.add_requested.emit(serials)

    def _copy_current(self):
        serial = self._serial(self._current_result())
        if serial:
            QtWidgets.QApplication.clipboard().setText(serial)
            self.status_label.setText(self._t.get("copied", "Base85 copied"))

    def set_add_status(self, text: str, busy: bool = False):
        self.status_label.setText(text)
        self.add_one_button.setEnabled(not busy and bool(self._serial(self._current_result())))
        self.add_all_button.setEnabled(not busy and bool(self._results))
