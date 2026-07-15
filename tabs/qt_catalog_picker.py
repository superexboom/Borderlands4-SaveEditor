"""Shared modern "catalog -> cart" picker widgets.

Replaces the old dual-list ("»«" transfer + separate multiplier spinbox) pattern
used by the class-mod and enhancement tabs with:

- a category chip bar + search box that filter a scrollable catalog,
- double-click to add an item to a compact "selected" cart,
- per-row inline +/- steppers and a remove button in the cart.

The widgets are intentionally data-agnostic: callers push a list of item dicts
via ``set_source`` and read the current selection back via ``entries``.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem, QButtonGroup, QSizePolicy,
    QFrame, QScrollArea
)
from PyQt6.QtCore import pyqtSignal, Qt, QSize, QTimer


class ContainedWheelListWidget(QListWidget):
    """Keep wheel input inside a list, including at its scroll boundaries."""

    def wheelEvent(self, event):
        super().wheelEvent(event)
        event.accept()


class ContainedWheelScrollArea(QScrollArea):
    """Keep wheel input inside a nested candidate area at its boundaries."""

    def wheelEvent(self, event):
        super().wheelEvent(event)
        event.accept()


class CategoryChipBar(QWidget):
    """A row of mutually-exclusive, checkable category chips (wraps into a grid)."""

    changed = pyqtSignal(str)  # current category key

    def __init__(self, columns=8, parent=None):
        super().__init__(parent)
        self._columns = columns
        self._building = False
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(6)
        self._grid.setVerticalSpacing(6)
        self._group.buttonToggled.connect(self._on_toggled)

    def _on_toggled(self, button, checked):
        if checked and not self._building:
            self.changed.emit(button.property("catKey"))

    def current_key(self):
        b = self._group.checkedButton()
        return b.property("catKey") if b is not None else None

    def _clear(self):
        for b in list(self._group.buttons()):
            self._group.removeButton(b)
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        # 清掉上一轮构建残留的列拉伸，避免影响新的等宽计算
        for c in range(64):
            self._grid.setColumnStretch(c, 0)

    def set_categories(self, categories, columns=None):
        """categories: list of (key, label). First one is auto-selected.

        芯片按固定列数排布，且每列等宽（等拉伸 + 芯片横向 Expanding 填满单元格）。
        这样同一 columns 的多个筛选条彼此列宽一致，横竖都对齐，不再犬牙交错。
        """
        if columns:
            self._columns = columns
        cols = max(1, self._columns)
        self._building = True
        self._clear()
        for i, (key, label) in enumerate(categories):
            btn = QPushButton(label)
            btn.setObjectName("catalogChip")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setProperty("catKey", key)
            self._group.addButton(btn)
            self._grid.addWidget(btn, i // cols, i % cols)
        for c in range(cols):
            self._grid.setColumnStretch(c, 1)
        if categories:
            self._group.buttons()[0].setChecked(True)
        self._building = False


class SelectedRow(QWidget):
    """One row in the selected cart: label + optional [-] N [+] + remove."""

    countChanged = pyqtSignal()
    removed = pyqtSignal()
    ROW_HEIGHT = 40

    def __init__(self, label, count=1, stackable=True, parent=None):
        super().__init__(parent)
        self._count = max(1, count)
        self._stackable = stackable
        self.setMinimumHeight(self.ROW_HEIGHT)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(8)
        lay.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._label = QLabel(label)
        self._label.setToolTip(label)
        self._label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(self._label, 1, Qt.AlignmentFlag.AlignVCenter)

        if stackable:
            self.btn_minus = QPushButton("\u2212")  # minus sign
            self.btn_minus.setObjectName("rowStepBtn")
            self.btn_minus.setFixedSize(QSize(26, 26))
            self.btn_minus.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_minus.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.btn_minus.clicked.connect(self._dec)

            self.count_lbl = QLabel(str(self._count))
            self.count_lbl.setObjectName("rowCount")
            self.count_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.count_lbl.setFixedSize(QSize(32, 26))

            self.btn_plus = QPushButton("+")
            self.btn_plus.setObjectName("rowStepBtn")
            self.btn_plus.setFixedSize(QSize(26, 26))
            self.btn_plus.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_plus.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.btn_plus.clicked.connect(self._inc)

            lay.addWidget(self.btn_minus, 0, Qt.AlignmentFlag.AlignVCenter)
            lay.addWidget(self.count_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
            lay.addWidget(self.btn_plus, 0, Qt.AlignmentFlag.AlignVCenter)

        self.btn_del = QPushButton("\u2715")  # multiplication x
        self.btn_del.setObjectName("rowDelBtn")
        self.btn_del.setFixedSize(QSize(26, 26))
        self.btn_del.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_del.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_del.clicked.connect(self.removed.emit)
        lay.addWidget(self.btn_del, 0, Qt.AlignmentFlag.AlignVCenter)

    def sizeHint(self):
        return QSize(super().sizeHint().width(), self.ROW_HEIGHT)

    def minimumSizeHint(self):
        return self.sizeHint()

    def count(self):
        return self._count

    def set_count(self, c):
        self._count = max(1, int(c))
        if self._stackable:
            self.count_lbl.setText(str(self._count))
        self.countChanged.emit()

    def _inc(self):
        self._count += 1
        self.count_lbl.setText(str(self._count))
        self.countChanged.emit()

    def _dec(self):
        if self._count > 1:
            self._count -= 1
            self.count_lbl.setText(str(self._count))
            self.countChanged.emit()
        else:
            self.removed.emit()


class CatalogPicker(QWidget):
    """Catalog (filterable) on the left, selected cart on the right.

    Item dicts pushed via ``set_source`` look like::

        {"key": <hashable unique>, "label": <str shown>,
         "category": <str or None>, "subcategory": <str or None>,
         "tertiary": <str or None>,
         "data": <opaque payload returned by entries()>}
    """

    changed = pyqtSignal()

    def __init__(self, stackable=True, search_placeholder="",
                 avail_title="", selected_title="", clear_text="Clear",
                 parent=None):
        super().__init__(parent)
        self._stackable = stackable
        self._source = []
        self._selected_keys = {}  # key -> QListWidgetItem

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # Filters: search + up to three independent category chip rows.
        self.search = QLineEdit()
        self.search.setPlaceholderText(search_placeholder)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._refilter)
        root.addWidget(self.search)

        self.cat_bar = CategoryChipBar()
        self.cat_bar.changed.connect(lambda *_: self._refilter())
        self.cat_bar.hide()
        root.addWidget(self.cat_bar)

        self.sub_bar = CategoryChipBar()
        self.sub_bar.changed.connect(lambda *_: self._refilter())
        self.sub_bar.hide()
        root.addWidget(self.sub_bar)

        self.third_bar = CategoryChipBar()
        self.third_bar.changed.connect(lambda *_: self._refilter())
        self.third_bar.hide()
        root.addWidget(self.third_bar)

        # Body: available | selected
        body = QHBoxLayout()
        body.setSpacing(10)

        avail_card = QFrame()
        avail_card.setObjectName("catalogCard")
        avail_v = QVBoxLayout(avail_card)
        avail_v.setContentsMargins(8, 8, 8, 8)
        avail_v.setSpacing(6)
        if avail_title:
            lbl = QLabel(avail_title)
            lbl.setObjectName("catalogColTitle")
            avail_v.addWidget(lbl)
        self.avail = ContainedWheelListWidget()
        self.avail.setMinimumHeight(200)
        self.avail.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.avail.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.avail.itemDoubleClicked.connect(self._on_avail_double)
        avail_v.addWidget(self.avail)
        body.addWidget(avail_card, 1)

        sel_card = QFrame()
        sel_card.setObjectName("catalogCard")
        sel_v = QVBoxLayout(sel_card)
        sel_v.setContentsMargins(8, 8, 8, 8)
        sel_v.setSpacing(6)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self._sel_title = selected_title
        self.count_lbl = QLabel(self._fmt_count(0))
        self.count_lbl.setObjectName("catalogCount")
        header.addWidget(self.count_lbl, 1)
        self.clear_btn = QPushButton(clear_text)
        self.clear_btn.setObjectName("catalogClearBtn")
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.clicked.connect(self.clear)
        header.addWidget(self.clear_btn)
        sel_v.addLayout(header)
        self.selected = ContainedWheelListWidget()
        self.selected.setObjectName("catalogSelectedList")
        self.selected.setMinimumHeight(200)
        self.selected.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        sel_v.addWidget(self.selected)
        body.addWidget(sel_card, 1)

        root.addLayout(body)

    # ------------------------------------------------------------------ #
    # Configuration
    # ------------------------------------------------------------------ #
    def set_categories(self, categories, columns=8):
        if categories:
            self.cat_bar.set_categories(categories, columns)
            self.cat_bar.show()
        else:
            self.cat_bar.hide()

    def set_subcategories(self, subcategories, columns=8):
        if subcategories:
            self.sub_bar.set_categories(subcategories, columns)
            self.sub_bar.show()
        else:
            self.sub_bar.hide()

    def set_third_categories(self, categories, columns=8):
        if categories:
            self.third_bar.set_categories(categories, columns)
            self.third_bar.show()
        else:
            self.third_bar.hide()

    def set_source(self, items):
        """Replace the catalog pool. Current selection is preserved."""
        self._source = list(items)
        self._refilter()

    # ------------------------------------------------------------------ #
    # Filtering
    # ------------------------------------------------------------------ #
    def _refilter(self, *args):
        self.avail.clear()
        cat = self.cat_bar.current_key() if not self.cat_bar.isHidden() else None
        sub = self.sub_bar.current_key() if not self.sub_bar.isHidden() else None
        third = self.third_bar.current_key() if not self.third_bar.isHidden() else None
        query = self.search.text().lower().strip()
        for it in self._source:
            if cat not in (None, "all") and it.get("category") != cat:
                continue
            if sub not in (None, "all") and it.get("subcategory") != sub:
                continue
            if third not in (None, "all") and it.get("tertiary") != third:
                continue
            if query and query not in str(it.get("label", "")).lower():
                continue
            lwi = QListWidgetItem(it.get("label", ""))
            lwi.setData(Qt.ItemDataRole.UserRole, it)
            lwi.setToolTip(it.get("label", ""))
            self.avail.addItem(lwi)

    # ------------------------------------------------------------------ #
    # Selection
    # ------------------------------------------------------------------ #
    def _on_avail_double(self, item):
        it = item.data(Qt.ItemDataRole.UserRole)
        if it:
            self.add_item(it)

    def add_item(self, it, count=1):
        key = it["key"]
        if key in self._selected_keys:
            if self._stackable:
                row = self.selected.itemWidget(self._selected_keys[key])
                if row is not None:
                    row.set_count(row.count() + count)
            return

        lwi = QListWidgetItem()
        lwi.setData(Qt.ItemDataRole.UserRole, it)
        self.selected.addItem(lwi)
        row = SelectedRow(it.get("label", ""), count=count, stackable=self._stackable)
        hint = row.sizeHint()
        lwi.setSizeHint(QSize(max(hint.width(), 200), hint.height()))
        self.selected.setItemWidget(lwi, row)
        self._selected_keys[key] = lwi
        row.countChanged.connect(self.changed.emit)
        # 延迟到下一轮事件循环再删除，避免在按钮自身点击槽内销毁其宿主控件导致崩溃
        row.removed.connect(lambda k=key: QTimer.singleShot(0, lambda: self._remove_key(k)))
        self._update_count()
        self.changed.emit()

    def _remove_key(self, key):
        lwi = self._selected_keys.pop(key, None)
        if lwi is not None:
            self.selected.takeItem(self.selected.row(lwi))
        self._update_count()
        self.changed.emit()

    def remove_key(self, key):
        if key in self._selected_keys:
            self._remove_key(key)

    def clear(self):
        if not self._selected_keys and self.selected.count() == 0:
            return
        self.selected.clear()
        self._selected_keys = {}
        self._update_count()
        self.changed.emit()

    def entries(self):
        """Return [{data, count, key, label}, ...] in selection order."""
        result = []
        for i in range(self.selected.count()):
            lwi = self.selected.item(i)
            it = lwi.data(Qt.ItemDataRole.UserRole)
            row = self.selected.itemWidget(lwi)
            count = row.count() if row is not None else 1
            result.append({
                "data": it.get("data"),
                "count": count,
                "key": it.get("key"),
                "label": it.get("label"),
            })
        return result

    def selected_keys(self):
        return set(self._selected_keys.keys())

    def set_search_placeholder(self, text):
        self.search.setPlaceholderText(text)

    def _fmt_count(self, n):
        return f"{self._sel_title}  ({n})" if self._sel_title else f"({n})"

    def _update_count(self):
        self.count_lbl.setText(self._fmt_count(self.selected.count()))


class InlineCatalogRow(QFrame):
    """Single catalog row with an inline selector or bounded stepper."""

    countChanged = pyqtSignal(int)
    ROW_HEIGHT = 58
    ACCENTS = {
        "red": "#d75b67",
        "green": "#52b879",
        "blue": "#4c8ed9",
    }

    def __init__(self, item, count=0, stackable=True, parent=None):
        super().__init__(parent)
        self._count = max(0, int(count))
        self._max_count = max(1, int(item.get("max_count", 99)))
        self._stackable = stackable
        self.setObjectName("inlineCatalogRow")
        self.setMinimumHeight(self.ROW_HEIGHT)
        accent = self.ACCENTS.get(item.get("accent"), "#607d8b")
        self.setStyleSheet(f"QFrame#inlineCatalogRow {{ border-left: 3px solid {accent}; }}")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 8, 6)
        layout.setSpacing(10)

        icon = item.get("icon")
        if icon and not icon.isNull():
            icon_label = QLabel()
            icon_label.setPixmap(icon.pixmap(QSize(38, 38)))
            icon_label.setFixedSize(QSize(40, 40))
            icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(icon_label)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)
        title = QLabel(item.get("label", ""))
        title.setObjectName("inlineCatalogTitle")
        title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        title.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        text_layout.addWidget(title)
        detail_text = item.get("detail", "")
        if detail_text:
            detail = QLabel(detail_text)
            detail.setObjectName("inlineCatalogDetail")
            detail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            detail.setToolTip(detail_text)
            detail.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            text_layout.addWidget(detail)
        layout.addLayout(text_layout, 1)

        tooltip = item.get("tooltip", "")
        if tooltip:
            self.setToolTip(tooltip)
            title.setToolTip(tooltip)

        if stackable:
            self.minus_btn = QPushButton("−")
            self.minus_btn.setObjectName("rowStepBtn")
            self.minus_btn.setFixedSize(QSize(28, 28))
            self.minus_btn.clicked.connect(self._decrease)
            self.count_label = QLabel(str(self._count))
            self.count_label.setObjectName("rowCount")
            self.count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.count_label.setFixedSize(QSize(32, 28))
            self.plus_btn = QPushButton("+")
            self.plus_btn.setObjectName("rowStepBtn")
            self.plus_btn.setFixedSize(QSize(28, 28))
            self.plus_btn.clicked.connect(self._increase)
            layout.addWidget(self.minus_btn)
            layout.addWidget(self.count_label)
            layout.addWidget(self.plus_btn)
        else:
            self.toggle_btn = QPushButton("✓" if self._count else "+")
            self.toggle_btn.setObjectName("inlineCatalogToggle")
            self.toggle_btn.setCheckable(True)
            self.toggle_btn.setChecked(bool(self._count))
            self.toggle_btn.setFixedSize(QSize(32, 32))
            self.toggle_btn.toggled.connect(self._toggle)
            layout.addWidget(self.toggle_btn)
        self._update_controls()

    def sizeHint(self):
        return QSize(super().sizeHint().width(), self.ROW_HEIGHT)

    def _increase(self):
        self.set_count(min(self._max_count, self._count + 1))

    def _decrease(self):
        self.set_count(max(0, self._count - 1))

    def _toggle(self, checked):
        self._count = 1 if checked else 0
        self._update_controls()
        self.countChanged.emit(self._count)

    def set_count(self, count):
        count = max(0, min(self._max_count, int(count)))
        if count == self._count:
            return
        self._count = count
        self._update_controls()
        self.countChanged.emit(count)

    def _update_controls(self):
        selected = self._count > 0
        if self.property("selected") != selected:
            self.setProperty("selected", selected)
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()
        if self._stackable:
            self.count_label.setText(str(self._count))
            self.minus_btn.setEnabled(self._count > 0)
            self.plus_btn.setEnabled(self._count < self._max_count)
        else:
            checked = bool(self._count)
            self.toggle_btn.blockSignals(True)
            self.toggle_btn.setChecked(checked)
            self.toggle_btn.setText("✓" if checked else "+")
            self.toggle_btn.blockSignals(False)


class InlineCatalogPicker(QWidget):
    """Filterable one-list catalog; selection controls live on each row."""

    changed = pyqtSignal()

    def __init__(self, stackable=True, search_placeholder="", clear_text="Clear", parent=None):
        super().__init__(parent)
        self._stackable = stackable
        self._source = []
        self._counts = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        header = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(search_placeholder)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._refilter)
        header.addWidget(self.search, 1)
        self.count_lbl = QLabel("0")
        self.count_lbl.setObjectName("catalogCount")
        header.addWidget(self.count_lbl)
        self.clear_btn = QPushButton(clear_text)
        self.clear_btn.setObjectName("catalogClearBtn")
        self.clear_btn.clicked.connect(self.clear)
        header.addWidget(self.clear_btn)
        root.addLayout(header)

        self.cat_bar = CategoryChipBar(columns=4)
        self.cat_bar.changed.connect(self._refilter)
        self.cat_bar.hide()
        root.addWidget(self.cat_bar)

        self.list = ContainedWheelListWidget()
        self.list.setObjectName("inlineCatalogList")
        self.list.setMinimumHeight(220)
        self.list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(self.list)

    def set_categories(self, categories, columns=4):
        if categories:
            self.cat_bar.set_categories(categories, columns)
            self.cat_bar.show()
        else:
            self.cat_bar.hide()
        self._refilter()

    def set_source(self, items):
        self._source = list(items)
        valid = {item["key"] for item in self._source}
        self._counts = {key: count for key, count in self._counts.items() if key in valid and count > 0}
        self._refilter()
        self._update_count()

    def _refilter(self, *args):
        self.list.clear()
        category = self.cat_bar.current_key() if not self.cat_bar.isHidden() else None
        query = self.search.text().casefold().strip()
        for item in self._source:
            if category not in (None, "all") and item.get("category") != category:
                continue
            search_text = " ".join((str(item.get("label", "")), str(item.get("detail", "")), str(item.get("search_text", "")))).casefold()
            if query and query not in search_text:
                continue
            list_item = QListWidgetItem()
            list_item.setData(Qt.ItemDataRole.UserRole, item)
            row = InlineCatalogRow(item, self._counts.get(item["key"], 0), self._stackable)
            row.countChanged.connect(lambda count, key=item["key"]: self._set_count(key, count))
            list_item.setSizeHint(row.sizeHint())
            self.list.addItem(list_item)
            self.list.setItemWidget(list_item, row)

    def _set_count(self, key, count):
        if count > 0:
            self._counts[key] = count
        else:
            self._counts.pop(key, None)
        self._update_count()
        self.changed.emit()

    def add_item(self, item, count=1):
        maximum = max(1, int(item.get("max_count", 99)))
        self._counts[item["key"]] = min(maximum, self._counts.get(item["key"], 0) + count)
        self._refilter()
        self._update_count()
        self.changed.emit()

    def remove_key(self, key):
        if key in self._counts:
            self._counts.pop(key)
            self._refilter()
            self._update_count()
            self.changed.emit()

    def clear(self):
        if not self._counts:
            return
        self._counts.clear()
        self._refilter()
        self._update_count()
        self.changed.emit()

    def entries(self):
        return [
            {
                "data": item.get("data"),
                "count": self._counts[item["key"]],
                "key": item["key"],
                "label": item.get("label", ""),
            }
            for item in self._source
            if self._counts.get(item["key"], 0) > 0
        ]

    def selected_keys(self):
        return set(self._counts)

    def set_search_placeholder(self, text):
        self.search.setPlaceholderText(text)

    def _update_count(self):
        selected = len(self._counts)
        total = sum(self._counts.values())
        self.count_lbl.setText(str(total) if self._stackable else str(selected))
