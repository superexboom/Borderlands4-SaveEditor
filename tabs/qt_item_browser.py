"""Shared ItemBrowser widget.

A vertical column of item rows on the left of an editor tab, driven by
callbacks the host tab supplies. Consumed by every editor — weapon, grenade,
shield, repkit, class-mod, enhancement, and heavy-weapon — so the seven tabs
share one layout, filter, and selection-sync path instead of seven copies.

Token preservation lives here too: ``ItemBrowser.token_state_for(item)`` parses
an item's decoded serial into a ``TokenOrderedState`` that editor tabs bind
widgets against, and ``render_from_state(state)`` emits the serial back out
in source order — preserving unknown tokens and interstitial whitespace so
edits never silently drop or reorder anything the parser didn't recognize.

Callers provide:
  - item_filter    : predicate(item_dict) -> bool
  - row_builder    : callable(item_dict) -> (display_name, detail, QWidget)
                     where QWidget is the fully-styled row widget
                     (host owns row objectNames + stat rendering)

Callers subscribe to item_selected(item_dict) to react to clicks/activation.
"""

import re

from PyQt6 import QtCore, QtWidgets

from tabs.qt_catalog_picker import ContainedWheelListWidget
from tabs.qt_editor_shared import (
    TokenOrderedState,
    log_editor,
    parse_component_tokens,
    parse_component_tokens_with_skin,
)


ROW_HEIGHT = 112
SELECTED_PROPERTY = "selected"

# Matches the "(N) text" prefix that _move_selected_items / stack_into_sel_list
# put on stacked entries so callers can round-trip through rebuild_output.
_COUNT_PREFIX_RE = re.compile(r"\((\d+)\)\s+(.*)")


def list_widget_by_userrole(list_widget):
    """Build ``{userRole_value: QListWidgetItem}`` from a list widget.

    Used by every editor's reverse parser to look up an available-perk item by
    its Part_ID. Items whose UserRole is ``None`` are skipped (placeholders).
    Numeric IDs are cast to plain ``int`` — pandas hands out ``numpy.int64``
    from the CSV data, and the token stream produces Python ``int``; casting
    on ingestion makes both hash to the same dict slot regardless of any
    future pandas / numpy hashing changes.
    """
    table = {}
    for i in range(list_widget.count()):
        av_item = list_widget.item(i)
        pid = av_item.data(QtCore.Qt.ItemDataRole.UserRole)
        if pid is None:
            continue
        key = int(pid) if hasattr(pid, "__int__") else pid
        table[key] = av_item
    return table


def parse_stack_count(text):
    """Return ``(count, base_text)`` for a stack entry like ``"(3) Fire perk"``.

    Falls back to ``(1, text)`` if no ``(N) `` prefix is present. Used by
    ``stack_into_sel_list`` and by every editor's ``rebuild_output`` /
    ``_move_selected_items`` — one regex, one place to change if the display
    convention ever moves.
    """
    match = _COUNT_PREFIX_RE.match(text)
    if match:
        return int(match.group(1)), match.group(2)
    return 1, text


def stack_into_sel_list(sel_list, avail_item, use_prefix=False):
    """Add ``avail_item`` to ``sel_list`` (or bump its ``(N) `` counter if
    the same base text is already there).

    ``use_prefix=True`` writes ``"(1) text"`` on the first insert to match the
    universal-perk convention that ``rebuild_output`` parses via
    ``parse_stack_count``. Legendary lists write bare text (count=1 implicit),
    so callers pass ``use_prefix=False`` there.
    """
    base_text = avail_item.text()
    for i in range(sel_list.count()):
        sel_item = sel_list.item(i)
        count, name = parse_stack_count(sel_item.text())
        if name == base_text:
            sel_item.setText(f"({count + 1}) {base_text}")
            return
    new_item = avail_item.clone()
    if use_prefix:
        new_item.setText(f"(1) {base_text}")
    sel_list.addItem(new_item)


class ItemBrowser(QtWidgets.QFrame):
    """Left-column list of backpack items filtered/rendered by the host tab.

    Public API:
        refresh()                    -> repopulate from controller.get_all_items()
        set_selected_path(path)      -> select item whose original_path matches
        clear_selection()            -> deselect + clear summary
        current_item()               -> currently-selected item dict or None
        token_state_for(item)        -> parse decoded_full into TokenOrderedState
        render_from_state(state)     -> reassemble serial from a state, in order

    Signals:
        item_selected(dict)          -> fires on click and on activation (enter/dbl)
        selection_changed(cur, prev) -> arrow-key navigation without loading
    """

    item_selected = QtCore.pyqtSignal(dict)
    selection_changed = QtCore.pyqtSignal(object, object)

    def __init__(
        self,
        main_app,
        item_filter,
        row_builder,
        header_label="",
        search_placeholder="",
        empty_placeholder="",
        no_save_placeholder="",
        summary_formatter=None,
        summary_none_text="",
        row_height=ROW_HEIGHT,
        list_object_name="itemBrowser",
        parent=None,
    ):
        super().__init__(parent)
        self.main_app = main_app
        self._item_filter = item_filter
        self._row_builder = row_builder
        self._empty_placeholder = empty_placeholder
        self._no_save_placeholder = no_save_placeholder
        self._summary_formatter = summary_formatter
        self._summary_none_text = summary_none_text
        self._row_height = row_height
        self._selected_path = None

        self.setObjectName("InnerFrame")
        self.setMinimumWidth(280)

        layout = QtWidgets.QVBoxLayout(self)

        if header_label:
            layout.addWidget(QtWidgets.QLabel(header_label))

        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setClearButtonEnabled(True)
        if search_placeholder:
            self.search_edit.setPlaceholderText(search_placeholder)
        self.search_edit.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search_edit)

        self.list_widget = ContainedWheelListWidget()
        self.list_widget.setObjectName(list_object_name)
        self.list_widget.setMinimumHeight(220)
        self.list_widget.setUniformItemSizes(True)
        self.list_widget.setVerticalScrollMode(
            QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.list_widget.verticalScrollBar().setSingleStep(20)
        self.list_widget.itemActivated.connect(self._emit_selection)
        self.list_widget.itemClicked.connect(self._emit_selection)
        self.list_widget.currentItemChanged.connect(self._on_current_changed)
        layout.addWidget(self.list_widget, 1)

        self.summary_label = QtWidgets.QLabel()
        self.summary_label.setObjectName("selectedItemSummary")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self._update_summary(None)

    # ---- public --------------------------------------------------------

    def refresh(self):
        """Repopulate the list from the current save state."""
        self.list_widget.clear()
        controller = getattr(self.main_app, "controller", None)

        if controller is None or getattr(controller, "yaml_obj", None) is None:
            self._show_placeholder(self._no_save_placeholder)
            return

        try:
            items = controller.get_all_items() or []
        except Exception as exc:
            log_editor(self.main_app, "item_browser", f"ItemBrowser: get_all_items failed: {exc}")
            # Distinct message from the no-save case: the save IS loaded but
            # something else went wrong. Reuses the empty placeholder text so
            # the user sees "no items" rather than a misleading "decrypt first".
            self._show_placeholder(self._empty_placeholder)
            return

        filtered = [item for item in items if self._safe_filter(item)]
        if not filtered:
            self._show_placeholder(self._empty_placeholder)
            return

        self.list_widget.setEnabled(True)

        for item_dict in filtered:
            try:
                built = self._row_builder(item_dict)
            except Exception as exc:
                log_editor(
                    self.main_app,
                    "item_browser",
                    f"ItemBrowser: row_builder failed for "
                    f"{item_dict.get('name', 'unknown')}: {exc}",
                )
                continue
            if built is None:
                continue
            display_name, detail, row_widget = built
            list_item = QtWidgets.QListWidgetItem()
            list_item.setData(QtCore.Qt.ItemDataRole.UserRole, item_dict)
            search_blob = f"{item_dict.get('name', '')} {display_name} {detail}".casefold()
            list_item.setData(QtCore.Qt.ItemDataRole.UserRole + 1, search_blob)
            list_item.setToolTip(f"{display_name} · {detail}")
            list_item.setSizeHint(QtCore.QSize(0, self._row_height))
            self.list_widget.addItem(list_item)
            self.list_widget.setItemWidget(list_item, row_widget)

        self._apply_filter(self.search_edit.text())
        self._select_by_stored_path()

    def set_selected_path(self, path):
        """Remember a path so it's re-selected after the next refresh."""
        self._selected_path = path
        self._select_by_stored_path()

    def clear_selection(self):
        self._selected_path = None
        self.list_widget.clearSelection()
        self._update_summary(None)

    def current_item(self):
        return self._item_data(self.list_widget.currentItem())

    # ---- token-preserving parse/render --------------------------------

    def token_state_for(self, item, *, skin=True):
        """Parse ``item['decoded_full']`` into a ``TokenOrderedState``.

        ``skin`` selects the tokenizer variant: ``True`` handles weapon-style
        ``"c", N`` skin tokens; ``False`` uses the base grammar that the six
        other editors share. Returns an empty state (``TokenOrderedState([])``)
        when ``item`` has no ``decoded_full`` so callers can bind unconditionally
        without a None guard on every access.
        """
        text = (item or {}).get("decoded_full", "") or ""
        if not text:
            return TokenOrderedState([])
        tokens = (
            parse_component_tokens_with_skin(text)
            if skin else parse_component_tokens(text)
        )
        return TokenOrderedState(tokens)

    def render_from_state(self, state, expected_raw=None):
        """Reassemble a serial from ``state`` in current token order.

        Thin wrapper on ``state.render()`` so editor tabs have one place to call
        for both parse and render — parse via ``token_state_for``, render via
        this method.

        When ``expected_raw`` is supplied (typically the source ``decoded_full``
        at load time), the rendered output is compared against it; any drift
        is logged via ``log_editor`` and ``expected_raw`` is returned instead
        of the rendered string. That way a tokenizer regression can't silently
        break the load-then-regen byte-identity pin for any sibling tab that
        opts into the drift-check by passing ``expected_raw``. Passing ``None``
        (or omitting the argument) preserves the original behaviour: return
        ``state.render()`` unconditionally.
        """
        rendered = state.render()
        if expected_raw is not None and rendered != expected_raw:
            log_editor(
                self.main_app,
                "item_browser",
                f"render_from_state parity DRIFT: "
                f"raw={expected_raw!r} rendered={rendered!r}",
            )
            return expected_raw
        return rendered

    # ---- private -------------------------------------------------------

    def _safe_filter(self, item_dict):
        try:
            return bool(self._item_filter(item_dict))
        except Exception as exc:
            log_editor(self.main_app, "item_browser", f"ItemBrowser: item_filter raised: {exc}")
            return False

    def _show_placeholder(self, text):
        if text:
            self.list_widget.addItem(text)
        self.list_widget.setEnabled(False)
        self._update_summary(None)

    @staticmethod
    def _item_data(item):
        """Return the dict payload for a real item, or None for placeholder rows
        (which have no UserRole data). Guards every reader against operating on
        the ``_show_placeholder``-added text-only rows.
        """
        data = item.data(QtCore.Qt.ItemDataRole.UserRole) if item else None
        return data if isinstance(data, dict) else None

    def _apply_filter(self, query):
        query = (query or "").strip().casefold()
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            # Placeholder rows (no UserRole payload) stay visible regardless of
            # the query — hiding them would leave an empty pane with no hint.
            if self._item_data(item) is None:
                item.setHidden(False)
                continue
            blob = item.data(QtCore.Qt.ItemDataRole.UserRole + 1) or item.text().casefold()
            item.setHidden(bool(query and query not in blob))

    def _select_by_stored_path(self):
        if not self._selected_path:
            return
        self.list_widget.clearSelection()
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            # Skip hidden rows so a restored selection doesn't land invisibly
            # under an active search query.
            if item.isHidden():
                continue
            data = self._item_data(item)
            if data and data.get("original_path") == self._selected_path:
                self.list_widget.setCurrentItem(item)
                self.list_widget.scrollToItem(
                    item, QtWidgets.QAbstractItemView.ScrollHint.PositionAtCenter
                )
                return

    def _on_current_changed(self, current, previous):
        self._refresh_selected_property(self._row_for(previous), False)
        self._refresh_selected_property(self._row_for(current), True)
        cur_data = self._item_data(current)
        prev_data = self._item_data(previous)
        self.selection_changed.emit(cur_data, prev_data)
        self._update_summary(cur_data)

    def _row_for(self, item):
        return self.list_widget.itemWidget(item) if item else None

    @staticmethod
    def _refresh_selected_property(widget, selected):
        """Toggle the ``selected`` QSS property on a row widget and repolish it,
        so QSS `[selected="true"]` rules take effect on the newly-current row.
        """
        if widget is None or widget.property(SELECTED_PROPERTY) == selected:
            return
        widget.setProperty(SELECTED_PROPERTY, selected)
        for child in (widget, *widget.findChildren(QtWidgets.QWidget)):
            child.style().unpolish(child)
            child.style().polish(child)

    def _emit_selection(self, item):
        data = self._item_data(item)
        if data:
            self._selected_path = data.get("original_path")
            self.item_selected.emit(data)

    def _update_summary(self, item_dict):
        if item_dict and self._summary_formatter:
            try:
                self.summary_label.setText(self._summary_formatter(item_dict))
                return
            except Exception as exc:
                log_editor(self.main_app, "item_browser", f"ItemBrowser: summary_formatter raised: {exc}")
        self.summary_label.setText(self._summary_none_text or "")


class PositionalTokenRow(QtWidgets.QWidget):
    """Row layout: ``[up] [#] [dn]`` plus an inner editor widget.

    Wraps any editor widget (combo, checkbox, spinbox). The ``#`` label shows
    the current token index in the state; ``up`` / ``dn`` reorder tokens via
    ``state.move(index, index-1/+1)`` and emit ``token_moved`` so the host tab
    can re-render. Consumers wire the ``inner_widget`` to whatever value
    editing they need; this row owns only the positional controls.

    **Sibling-row sync invariant.** After a move, only THIS row's ``_index``
    and label update. Other rows pointing to state tokens whose positions
    shifted (everything between the moved token's old and new index) have
    stale ``_index``/label until the host tab reacts to ``token_moved`` and
    calls ``set_index(new_index)`` on each affected sibling. Host tabs that
    render N rows over state tokens MUST hook ``token_moved`` and refresh
    every row's index, or drive from a single source of truth (re-render
    rows from ``state.tokens`` on every move).

    Widget lives in the shared module; editor tabs that want positional
    controls wrap their per-token editor widgets in one of these and hook the
    ``token_moved`` signal to re-render.
    """

    token_moved = QtCore.pyqtSignal(int, int)  # (old_index, new_index)

    def __init__(self, state, index, inner_widget, parent=None):
        super().__init__(parent)
        self._state = state
        self._index = index
        self._inner = inner_widget

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        self.up_btn = QtWidgets.QPushButton()
        self.up_btn.setObjectName("PartActionButton")
        self.up_btn.setIcon(self.style().standardIcon(
            QtWidgets.QStyle.StandardPixmap.SP_ArrowUp))
        self.up_btn.setFixedSize(28, 28)
        self.up_btn.setToolTip("Move up")
        self.up_btn.clicked.connect(self._move_up)
        layout.addWidget(self.up_btn)

        self.index_label = QtWidgets.QLabel(str(index))
        self.index_label.setObjectName("PartIdBadge")
        self.index_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.index_label.setMinimumWidth(28)
        layout.addWidget(self.index_label)

        self.dn_btn = QtWidgets.QPushButton()
        self.dn_btn.setObjectName("PartActionButton")
        self.dn_btn.setIcon(self.style().standardIcon(
            QtWidgets.QStyle.StandardPixmap.SP_ArrowDown))
        self.dn_btn.setFixedSize(28, 28)
        self.dn_btn.setToolTip("Move down")
        self.dn_btn.clicked.connect(self._move_down)
        layout.addWidget(self.dn_btn)

        layout.addWidget(inner_widget, 1)

    def token_index(self):
        return self._index

    def inner_widget(self):
        return self._inner

    def set_index(self, index):
        """Update the displayed index (call after a state.move outside this
        row so the label stays in sync with the token's new position)."""
        self._index = index
        self.index_label.setText(str(index))

    def _move_up(self):
        if self._index <= 0:
            return
        new_index = self._index - 1
        self._state.move(self._index, new_index)
        old = self._index
        self._index = new_index
        self.index_label.setText(str(new_index))
        self.token_moved.emit(old, new_index)

    def _move_down(self):
        if self._index >= len(self._state.tokens) - 1:
            return
        new_index = self._index + 1
        self._state.move(self._index, new_index)
        old = self._index
        self._index = new_index
        self.index_label.setText(str(new_index))
        self.token_moved.emit(old, new_index)
