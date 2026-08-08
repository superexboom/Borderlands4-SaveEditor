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
    QFrame, QScrollArea, QSplitter
)
from PyQt6.QtCore import pyqtSignal, Qt, QSize, QTimer
from PyQt6.QtGui import QColor


class ContainedWheelListWidget(QListWidget):
    """Keep wheel input inside a list, including at its scroll boundaries."""

    activated = pyqtSignal()  # Enter/Return pressed

    def wheelEvent(self, event):
        super().wheelEvent(event)
        event.accept()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.activated.emit()
            event.accept()
            return
        super().keyPressEvent(event)


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
    increaseRequested = pyqtSignal()
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
            self.btn_plus.clicked.connect(self.increaseRequested.emit)

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

    def set_label(self, label):
        self._label.setText(label)
        self._label.setToolTip(label)

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
                 disable_selected_source=False,
                 parent=None):
        super().__init__(parent)
        self._stackable = stackable
        self._disable_selected_source = disable_selected_source
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
        self.avail.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.avail.itemDoubleClicked.connect(self._on_avail_double)
        self.avail.activated.connect(self.add_selected)
        avail_v.addWidget(self.avail)
        # 多选批量加入：按钮 + 回车均可触发，与双击共用同一逻辑
        self.add_sel_btn = QPushButton("添加所选 →")
        self.add_sel_btn.setObjectName("catalogAddBtn")
        self.add_sel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_sel_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.add_sel_btn.clicked.connect(self.add_selected)
        avail_v.addWidget(self.add_sel_btn)
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
        self.selected.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
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
        by_key = {item["key"]: item for item in self._source}
        for key, list_item in self._selected_keys.items():
            item = by_key.get(key)
            if item is None:
                continue
            list_item.setData(Qt.ItemDataRole.UserRole, item)
            row = self.selected.itemWidget(list_item)
            if row is not None:
                row.set_label(item.get("label", ""))
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
            if self._disable_selected_source and it.get("key") in self._selected_keys:
                lwi.setFlags(lwi.flags() & ~Qt.ItemFlag.ItemIsEnabled & ~Qt.ItemFlag.ItemIsSelectable)
            self.avail.addItem(lwi)

    # ------------------------------------------------------------------ #
    # Selection
    # ------------------------------------------------------------------ #
    def _on_avail_double(self, item):
        # 双击加入"当前全部选中项"；若双击项不在选区里则只加它自己
        selected = self.avail.selectedItems()
        if item not in selected:
            selected = [item]
        self._add_rows(selected)

    def add_selected(self):
        """把候选栏当前所有选中项加入右侧已选区（批量）。"""
        self._add_rows(self.avail.selectedItems())

    def _add_rows(self, rows):
        items = [row.data(Qt.ItemDataRole.UserRole) for row in rows
                 if row.flags() & Qt.ItemFlag.ItemIsEnabled]
        for it in filter(None, items):
            self.add_item(it, refresh=False)
        self._refilter()

    def add_item(self, it, count=1, refresh=True):
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
        if self._stackable:
            row.increaseRequested.connect(lambda k=key: self._increase_key(k))
        # 延迟到下一轮事件循环再删除，避免在按钮自身点击槽内销毁其宿主控件导致崩溃
        row.removed.connect(lambda k=key: QTimer.singleShot(0, lambda: self._remove_key(k)))
        self._update_count()
        if refresh:
            self._refilter()
        self.changed.emit()

    def _increase_key(self, key):
        clicked = self._selected_keys.get(key)
        selected = self.selected.selectedItems()
        targets = selected if clicked in selected and len(selected) > 1 else [clicked]
        for lwi in filter(None, targets):
            row = self.selected.itemWidget(lwi)
            if row is not None:
                row.set_count(row.count() + 1)

    def _remove_key(self, key):
        lwi = self._selected_keys.pop(key, None)
        if lwi is not None:
            self.selected.takeItem(self.selected.row(lwi))
        self._update_count()
        self._refilter()
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
        self._refilter()
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

    def set_count_limit(self, limit, tooltip=""):
        """Show how many of this slot the game actually rolls, alongside the count.

        Advisory only: nothing is disabled, because the editor is legitimately used to
        build items the game would never drop. Verified over 80 dumped shields that each
        augment side holds at most one part, so a picker reading "(2 / 1)" tells the user
        their build cannot roll naturally rather than refusing the edit.
        ``limit`` of None clears the hint.
        """
        self._count_limit = limit
        if tooltip:
            self.count_lbl.setToolTip(tooltip)
        self._update_count()

    def _fmt_count(self, n):
        limit = getattr(self, "_count_limit", None)
        shown = f"{n}" if limit is None else f"{n} / {limit}"
        return f"{self._sel_title}  ({shown})" if self._sel_title else f"({shown})"

    def _update_count(self):
        count = self.selected.count()
        self.count_lbl.setText(self._fmt_count(count))
        limit = getattr(self, "_count_limit", None)
        over = limit is not None and count > limit
        if self.count_lbl.property("overLimit") != over:
            self.count_lbl.setProperty("overLimit", over)
            self.count_lbl.style().unpolish(self.count_lbl)
            self.count_lbl.style().polish(self.count_lbl)


class InlineCatalogRow(QFrame):
    """Single catalog row with an inline selector or bounded stepper."""

    countChanged = pyqtSignal(int)
    increaseRequested = pyqtSignal()
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
            self.plus_btn.clicked.connect(self.increaseRequested.emit)
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

    def __init__(self, stackable=True, search_placeholder="", clear_text="Clear",
                 multi_select=False, parent=None):
        super().__init__(parent)
        self._stackable = stackable
        self._multi_select = bool(multi_select and stackable)
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
        mode = (QListWidget.SelectionMode.ExtendedSelection if self._multi_select
                else QListWidget.SelectionMode.NoSelection)
        self.list.setSelectionMode(mode)
        self.list.itemSelectionChanged.connect(self._sync_selection_style)
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
            row.increaseRequested.connect(lambda key=item["key"]: self._increase_key(key))
            list_item.setSizeHint(row.sizeHint())
            self.list.addItem(list_item)
            self.list.setItemWidget(list_item, row)
        self._sync_selection_style()

    def _increase_key(self, key):
        targets = [key]
        if self._multi_select:
            selected = [
                item.data(Qt.ItemDataRole.UserRole)["key"]
                for item in self.list.selectedItems()
            ]
            if key in selected:
                targets = selected

        source = {item["key"]: item for item in self._source}
        changed = False
        for target in targets:
            item = source.get(target)
            if item is None:
                continue
            maximum = max(1, int(item.get("max_count", 99)))
            count = min(maximum, self._counts.get(target, 0) + 1)
            if count == self._counts.get(target, 0):
                continue
            self._counts[target] = count
            for row_index in range(self.list.count()):
                list_item = self.list.item(row_index)
                row_item = list_item.data(Qt.ItemDataRole.UserRole)
                if row_item["key"] != target:
                    continue
                row = self.list.itemWidget(list_item)
                row.blockSignals(True)
                row.set_count(count)
                row.blockSignals(False)
                break
            changed = True
        if changed:
            self._update_count()
            self.changed.emit()

    def _sync_selection_style(self):
        for index in range(self.list.count()):
            item = self.list.item(index)
            row = self.list.itemWidget(item)
            selected = self._multi_select and item.isSelected()
            if row is None or row.property("batchSelected") == selected:
                continue
            row.setProperty("batchSelected", selected)
            row.style().unpolish(row)
            row.style().polish(row)
            row.update()

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


# ====================================================================== #
# FacetedCatalogPicker：筛选侧栏 + 宽列表 + 预览卡片 + 已选清单
# ====================================================================== #
class FacetGroup(QWidget):
    """一个筛选维度：标题 + 紧凑单选列表（超出 max_visible 行后滚动）。"""

    changed = pyqtSignal(str)

    ROW_H = 26

    def __init__(self, title, max_visible=6, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lbl = QLabel(title)
        lbl.setObjectName("catalogColTitle")
        lay.addWidget(lbl)
        self.list = ContainedWheelListWidget()
        self.list.setObjectName("facetList")
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.currentItemChanged.connect(self._on_change)
        self._max_visible = max_visible
        lay.addWidget(self.list)

    def _on_change(self, current, _prev):
        if current is not None:
            self.changed.emit(current.data(Qt.ItemDataRole.UserRole))

    def set_options(self, options):
        """options: [(key, label)]；第一项自动选中（通常是“全部”）。"""
        self.list.blockSignals(True)
        self.list.clear()
        for key, label in options:
            lwi = QListWidgetItem(label)
            lwi.setData(Qt.ItemDataRole.UserRole, key)
            lwi.setToolTip(label)
            self.list.addItem(lwi)
        rows = max(1, min(len(options), self._max_visible))
        self.list.setFixedHeight(rows * self.ROW_H + 10)
        if self.list.count():
            self.list.setCurrentRow(0)
        self.list.blockSignals(False)

    def current_key(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None


class FacetedCatalogPicker(QWidget):
    """三栏式现代化目录选择器。

    与 CatalogPicker 数据协议兼容：item dict 使用
    ``key/label/category/subcategory/tertiary/data``，
    并可额外携带 ``title``、``detail``、``badges``（list[str]）、``search_text``
    驱动右侧预览卡片。facet 与字段按顺序对应：
    第 1 个 facet → category，第 2 个 → subcategory，第 3 个 → tertiary。
    """

    changed = pyqtSignal()
    _FACET_FIELDS = ("category", "subcategory", "tertiary")
    _FACET_MIN_WIDTH = 220
    _FACET_MAX_WIDTH = 400

    def __init__(self, stackable=True, search_placeholder="",
                 avail_title="", selected_title="", clear_text="Clear",
                 result_text="{n} / {total}", parent=None):
        super().__init__(parent)
        self._stackable = stackable
        self._source = []
        self._selected_keys = {}
        self._result_fmt = result_text

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # 顶部：搜索 + 匹配计数
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(search_placeholder)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._refilter)
        top.addWidget(self.search, 1)
        self.result_lbl = QLabel("")
        self.result_lbl.setObjectName("facetResultCount")
        top.addWidget(self.result_lbl)
        root.addLayout(top)

        # 三栏主体（分隔条可拖）
        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左：筛选侧栏
        sidebar = QFrame()
        sidebar.setObjectName("catalogCard")
        sidebar.setMinimumWidth(self._FACET_MIN_WIDTH)
        sidebar.setMaximumWidth(self._FACET_MAX_WIDTH)
        self._sidebar_lay = QVBoxLayout(sidebar)
        self._sidebar_lay.setContentsMargins(10, 10, 10, 10)
        self._sidebar_lay.setSpacing(10)
        self._facet_groups = []
        self._sidebar_lay.addStretch(1)
        self._splitter.addWidget(sidebar)

        # 中：可用列表
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
        self.avail.setMinimumHeight(240)
        self.avail.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.avail.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.avail.itemDoubleClicked.connect(self._on_avail_double)
        self.avail.currentItemChanged.connect(self._on_avail_current)
        avail_v.addWidget(self.avail)
        self._splitter.addWidget(avail_card)

        # 右：预览卡片 + 已选清单
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(8)

        self.preview_card = QFrame()
        self.preview_card.setObjectName("previewCard")
        pv = QVBoxLayout(self.preview_card)
        pv.setContentsMargins(12, 10, 12, 10)
        pv.setSpacing(6)
        self.preview_title = QLabel("—")
        self.preview_title.setObjectName("previewTitle")
        self.preview_title.setWordWrap(True)
        pv.addWidget(self.preview_title)
        self.preview_badges = QHBoxLayout()
        self.preview_badges.setContentsMargins(0, 0, 0, 0)
        self.preview_badges.setSpacing(4)
        self.preview_badges.addStretch(1)
        pv.addLayout(self.preview_badges)
        self.preview_detail = QLabel("")
        self.preview_detail.setObjectName("previewDetail")
        self.preview_detail.setWordWrap(True)
        self.preview_detail.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        pv.addWidget(self.preview_detail, 1)
        right_lay.addWidget(self.preview_card, 2)

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
        self.selected.setMinimumHeight(140)
        self.selected.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        sel_v.addWidget(self.selected)
        right_lay.addWidget(sel_card, 3)

        self._splitter.addWidget(right)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setStretchFactor(2, 0)
        self._splitter.setSizes([self._FACET_MIN_WIDTH, 560, 300])
        self._splitter.setCollapsible(0, False)
        self._splitter.setCollapsible(1, False)
        root.addWidget(self._splitter, 1)

    # ------------------------------------------------------------------ #
    # Configuration
    # ------------------------------------------------------------------ #
    def set_facets(self, facets):
        """facets: [(title, [(key, label), ...], max_visible), ...] 最多 3 个。"""
        facets = facets[:3]
        # 清掉旧的
        for group in self._facet_groups:
            self._sidebar_lay.removeWidget(group)
            group.deleteLater()
        self._facet_groups = []
        for i, spec in enumerate(facets):
            title, options = spec[0], spec[1]
            max_visible = spec[2] if len(spec) > 2 else 6
            group = FacetGroup(title, max_visible)
            group.changed.connect(lambda *_: self._refilter())
            # 插入到 stretch 之前
            self._sidebar_lay.insertWidget(self._sidebar_lay.count() - 1, group)
            group.set_options(options)
            self._facet_groups.append(group)

        texts = [str(spec[0]) for spec in facets]
        texts.extend(str(label) for spec in facets for _, label in spec[1])
        text_width = max((self.fontMetrics().horizontalAdvance(text) for text in texts), default=0)
        sidebar_width = max(self._FACET_MIN_WIDTH,
                            min(self._FACET_MAX_WIDTH, text_width + 54))
        self._splitter.setSizes([sidebar_width, 560, 300])

    def set_source(self, items):
        self._source = list(items)
        self._refilter()

    # ------------------------------------------------------------------ #
    # Filtering / preview
    # ------------------------------------------------------------------ #
    def _facet_keys(self):
        keys = []
        for group in self._facet_groups:
            keys.append(group.current_key())
        return keys

    def _refilter(self, *args):
        self.avail.clear()
        facet_keys = self._facet_keys()
        query = self.search.text().casefold().strip()
        matched = 0
        for it in self._source:
            skip = False
            for idx, key in enumerate(facet_keys):
                if key in (None, "all"):
                    continue
                field = self._FACET_FIELDS[idx] if idx < len(self._FACET_FIELDS) else None
                if field and it.get(field) != key:
                    skip = True
                    break
            if skip:
                continue
            if query:
                hay = " ".join(str(it.get(k, "")) for k in
                               ("label", "title", "detail", "search_text")).casefold()
                if query not in hay:
                    continue
            matched += 1
            candidate = it.get("candidate") or {}
            marker = str(candidate.get("marker") or "").strip()
            label = str(it.get("label", ""))
            lwi = QListWidgetItem(f"{marker}  {label}" if marker else label)
            lwi.setData(Qt.ItemDataRole.UserRole, it)
            tooltip = [str(it.get("tooltip") or label)]
            if candidate.get("hint"):
                tooltip.insert(0, str(candidate["hint"]))
            lwi.setToolTip("\n\n".join(filter(None, tooltip)))
            if candidate.get("kind") == "legal":
                font = lwi.font()
                font.setBold(True)
                lwi.setFont(font)
                lwi.setBackground(QColor(74, 144, 226, 38))
            elif candidate.get("kind") == "warning":
                lwi.setBackground(QColor(230, 164, 57, 30))
            self.avail.addItem(lwi)
        self.result_lbl.setText(self._result_fmt.format(n=matched, total=len(self._source)))
        if self.avail.count():
            self.avail.setCurrentRow(0)
        else:
            self._show_preview(None)

    def _on_avail_current(self, current, _prev):
        it = current.data(Qt.ItemDataRole.UserRole) if current is not None else None
        self._show_preview(it)

    def _show_preview(self, it):
        # 清空 badges
        while self.preview_badges.count():
            item = self.preview_badges.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if not it:
            self.preview_title.setText("—")
            self.preview_detail.setText("")
            self.preview_badges.addStretch(1)
            return
        self.preview_title.setText(it.get("title") or it.get("label", ""))
        candidate = it.get("candidate") or {}
        if candidate.get("badge"):
            b = QLabel(str(candidate["badge"]))
            b.setObjectName("previewCandidateBadge" if candidate.get("kind") == "legal" else "previewBadge")
            self.preview_badges.addWidget(b)
        for badge_text in it.get("badges") or []:
            b = QLabel(str(badge_text))
            b.setObjectName("previewBadge")
            self.preview_badges.addWidget(b)
        self.preview_badges.addStretch(1)
        self.preview_detail.setText("\n\n".join(filter(None, (
            str(candidate.get("hint") or ""),
            str(it.get("detail") or ""),
        ))))

    # ------------------------------------------------------------------ #
    # Selection（与 CatalogPicker 语义一致）
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
        row = SelectedRow(it.get("title") or it.get("label", ""), count=count,
                          stackable=self._stackable)
        hint = row.sizeHint()
        lwi.setSizeHint(QSize(max(hint.width(), 200), hint.height()))
        self.selected.setItemWidget(lwi, row)
        self._selected_keys[key] = lwi
        row.countChanged.connect(self.changed.emit)
        if self._stackable:
            row.increaseRequested.connect(lambda r=row: r.set_count(r.count() + 1))
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
