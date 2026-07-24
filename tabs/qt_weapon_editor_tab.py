from PyQt6 import QtWidgets, QtCore, QtGui
import pandas as pd
import random
import re
import sys
from functools import partial

from core import bl4_functions as bl4f
from core import b_encoder
from core import decoder_logic
from core import item_display_resolver
from core import resource_loader
from tabs.qt_catalog_picker import CatalogPicker, ContainedWheelListWidget, ContainedWheelScrollArea
from tabs.qt_item_browser import ItemBrowser, ROW_HEIGHT
from tabs.qt_editor_shared import (
    Token,
    TokenOrderedState,
    log_editor,
    make_header_getter,
    parse_component_string_with_skin,
    parse_component_tokens_with_skin,
)


class PartDragHandle(QtWidgets.QLabel):
    def __init__(self, list_widget, tooltip, parent=None):
        super().__init__("⋮⋮", parent)
        self._list_widget = list_widget
        self._press_pos = None
        self._source_item = None
        self.setObjectName("PartDragHandle")
        self.setToolTip(tooltip)
        self.setCursor(QtCore.Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
            viewport_pos = self._list_widget.viewport().mapFromGlobal(event.globalPosition().toPoint())
            self._source_item = self._list_widget.itemAt(viewport_pos)
            self.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_pos is not None and event.buttons() & QtCore.Qt.MouseButton.LeftButton:
            if (event.position().toPoint() - self._press_pos).manhattanLength() >= QtWidgets.QApplication.startDragDistance():
                if item := self._source_item:
                    self._list_widget.setCurrentItem(item)
                    self._press_pos = None
                    self._source_item = None
                    self._list_widget.startDrag(QtCore.Qt.DropAction.MoveAction)
                    self.setCursor(QtCore.Qt.CursorShape.OpenHandCursor)
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._press_pos = None
        self._source_item = None
        self.setCursor(QtCore.Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)


class PartOrderListWidget(ContainedWheelListWidget):
    orderDropped = QtCore.pyqtSignal()
    INSERT_INDICATOR_HEIGHT = 20

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drop_indicator_y = None
        self._drag_global_pos = None
        self._outer_scroll_timer = QtCore.QTimer(self)
        self._outer_scroll_timer.setInterval(30)
        self._outer_scroll_timer.timeout.connect(self._scroll_outer)
        self._height_sync_timer = QtCore.QTimer(self)
        self._height_sync_timer.setSingleShot(True)
        self._height_sync_timer.timeout.connect(self.sync_content_height)
        self.setObjectName("partsOrderList")
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(QtCore.Qt.DropAction.MoveAction)
        self.setDragDropOverwriteMode(False)
        self.setDropIndicatorShown(False)
        self.setAutoScroll(False)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)

    def sync_content_height(self):
        compact = self.viewport().width() < 340
        button_width, button_spacing = (30, 1) if compact else (34, 3)
        action_size_changed = False
        for actions in self.findChildren(QtWidgets.QFrame, "PartActionFrame"):
            buttons = actions.findChildren(QtWidgets.QPushButton)
            for button in buttons:
                if button.width() != button_width:
                    button.setFixedWidth(button_width)
                    action_size_changed = True
            actions.layout().setSpacing(button_spacing)
            width = len(buttons) * button_width + max(0, len(buttons) - 1) * button_spacing
            if actions.width() != width:
                actions.setFixedWidth(width)
                action_size_changed = True
        self.doItemsLayout()
        for row in range(self.count()):
            item = self.item(row)
            widget = self.itemWidget(item)
            if widget is None:
                continue
            if layout := widget.layout():
                layout.invalidate()
            width = max(1, self.visualItemRect(item).width())
            height = widget.heightForWidth(width) if widget.hasHeightForWidth() else widget.sizeHint().height()
            item.setSizeHint(QtCore.QSize(0, max(68, height + 4)))
        self.doItemsLayout()
        rows_height = sum(max(0, self.sizeHintForRow(row)) for row in range(self.count()))
        rows_height += max(0, self.count() - 1) * self.spacing()
        self.setFixedHeight(max(72, rows_height + self.frameWidth() * 2 + 2))
        self.updateGeometry()
        if action_size_changed:
            self._height_sync_timer.start(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.oldSize().width() != event.size().width():
            self._height_sync_timer.start(0)

    def _outer_scroll_area(self):
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, QtWidgets.QScrollArea):
                return parent
            parent = parent.parentWidget()
        return None

    def wheelEvent(self, event):
        outer = self._outer_scroll_area()
        delta = event.pixelDelta().y()
        if not delta:
            delta = int(event.angleDelta().y() / 120 * max(20, outer.verticalScrollBar().singleStep() * 3)) if outer else 0
        if outer is None or not delta:
            event.ignore()
            return
        bar = outer.verticalScrollBar()
        bar.setValue(bar.value() - delta)
        event.accept()

    @staticmethod
    def _refresh_property(widget, name, value):
        if widget is None or widget.property(name) == value:
            return
        widget.setProperty(name, value)
        highlighted = bool(widget.property("selected"))
        for badge in widget.findChildren(QtWidgets.QLabel, "PartTypeBadge"):
            color = badge.property("partColor")
            if color:
                badge.setStyleSheet(f"border-color: {color};" + ("" if highlighted else f" color: {color};"))
        for child in (widget, *widget.findChildren(QtWidgets.QWidget)):
            child.style().unpolish(child)
            child.style().polish(child)
        widget.update()

    def _set_drop_indicator(self, pos):
        item = self.itemAt(pos)
        if item is None:
            y = self.visualItemRect(self.item(self.count() - 1)).bottom() + 1 if self.count() else 0
        else:
            rect = self.visualItemRect(item)
            y = rect.top() if pos.y() < rect.center().y() else rect.bottom() + 1
        if y != self._drop_indicator_y:
            self._drop_indicator_y = y
            self.viewport().update()

    def _clear_drag_feedback(self):
        self._outer_scroll_timer.stop()
        self._drag_global_pos = None
        self._drop_indicator_y = None
        self.viewport().update()

    def _scroll_outer(self):
        outer = self._outer_scroll_area()
        if outer is None or self._drag_global_pos is None:
            return
        viewport = outer.viewport()
        pos = viewport.mapFromGlobal(self._drag_global_pos)
        margin = min(64, max(32, viewport.height() // 8))
        bar = outer.verticalScrollBar()
        old_value = bar.value()
        if pos.y() < margin:
            bar.setValue(old_value - max(20, bar.singleStep() * 2))
        elif pos.y() > viewport.height() - margin:
            bar.setValue(old_value + max(20, bar.singleStep() * 2))
        if bar.value() != old_value:
            self._set_drop_indicator(self.viewport().mapFromGlobal(self._drag_global_pos))

    def dragEnterEvent(self, event):
        super().dragEnterEvent(event)
        if event.isAccepted():
            self._drag_global_pos = self.viewport().mapToGlobal(event.position().toPoint())
            self._set_drop_indicator(event.position().toPoint())
            self._outer_scroll_timer.start()

    def dragMoveEvent(self, event):
        super().dragMoveEvent(event)
        if event.isAccepted():
            self._drag_global_pos = self.viewport().mapToGlobal(event.position().toPoint())
            self._set_drop_indicator(event.position().toPoint())

    def dragLeaveEvent(self, event):
        self._clear_drag_feedback()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        super().dropEvent(event)
        self._clear_drag_feedback()
        if event.isAccepted():
            self.orderDropped.emit()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._drop_indicator_y is None:
            return
        height = self.INSERT_INDICATOR_HEIGHT
        top = max(2, min(self.viewport().height() - height - 2, self._drop_indicator_y - height // 2))
        rect = QtCore.QRect(6, top, max(0, self.viewport().width() - 12), height)
        fill = QtGui.QColor("#4a90e2"); fill.setAlpha(220)
        border = QtGui.QColor("#a8d5ff")
        painter = QtGui.QPainter(self.viewport())
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setBrush(fill)
        painter.setPen(QtGui.QPen(border, 2))
        painter.drawRoundedRect(rect, 4, 4)

class QtWeaponEditorTab(QtWidgets.QWidget):
    add_to_backpack_requested = QtCore.pyqtSignal(str, str)
    update_item_requested = QtCore.pyqtSignal(dict)
    # Backpack items whose type_en matches one of these are shown in the
    # weapon browser. Frozen set so the filter predicate doesn't rebuild
    # a literal on every backpack item.
    _WEAPON_TYPES = frozenset({"Pistol", "Shotgun", "SMG", "Assault Rifle", "Sniper"})

    # log_editor tag routed through the shared logger (parity with the other
    # editor tabs — grenade, shield, repkit, heavy, class-mod, enhancement).
    _LOG_TAG = "weapon"

    # Colors are keyed by stable raw part types, never translated display text.
    # Weapon-local rather than shared: no other editor has a comparable per-
    # part-type color scheme, so a class constant here beats an import.
    PART_TYPE_COLORS = {
        "Barrel": "#B0BEC5",
        "Barrel Accessory": "#90A4AE",
        "Body": "#BCAAA4",
        "Body Accessory": "#A1887F",
        "Foregrip": "#9CCC65",
        "Grip": "#AED581",
        "Magazine": "#FFB300",
        "Magazine Accessory": "#FFCA28",
        "Manufacturer Part": "#9FA8DA",
        "Scope": "#4DD0E1",
        "Scope Accessory": "#26C6DA",
        "Stat Modifier": "#F06292",
        "Underbarrel": "#BCAAA4",
        "Underbarrel Accessory": "#A1887F",
        "Elemental": "#EF9A9A",
        "Element": "#EF9A9A",
        "Element Switch": "#EF9A9A",
        "Underbarrel Element Switch": "#EF9A9A",
        "Pearl Elements": "#80CBC4",
        "Pearl Stat": "#CE93D8",
        "Skin": "#FFEA00",
        "Rarity": "#B39DDB",
        "Legendary": "#FF8A65",
    }

    TAXONOMY_KEYS = {
        "Body": "body", "Body Accessory": "body_accessory",
        "Barrel": "barrel", "Barrel Accessory": "barrel_accessory",
        "Manufacturer Part": "manufacturer_part", "Tediore Payload": "tediore_payload",
        "Tediore Throw Reload": "tediore_throw_reload", "Magazine": "magazine",
        "Magazine Accessory": "magazine_accessory", "Scope": "scope",
        "Scope Accessory": "scope_accessory", "Grip": "grip",
        "Underbarrel": "underbarrel", "Underbarrel Accessory": "underbarrel_accessory",
        "Foregrip": "foregrip", "Borg Magazine Adapter": "borg_magazine_adapter",
        "Special Element Set": "special_element_set", "Stat Modifier": "stat_modifier",
        "Elemental": "elemental", "Element": "element", "Element Switch": "element_switch",
        "Underbarrel Element Switch": "underbarrel_element_switch",
        "Pearl Elements": "pearl_elements", "Pearl Stat": "pearl_stat",
        "Skin": "skin", "Rarity": "rarity", "Common": "common",
        "Uncommon": "uncommon", "Rare": "rare", "Epic": "epic",
        "Legendary": "legendary", "Pearl": "pearl",
        "Assault Rifle": "assault_rifle", "Pistol": "pistol", "Shotgun": "shotgun",
        "SMG": "smg", "Sniper": "sniper",
    }

    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app
        self.selected_item_path = None
        self.parts_data = []
        self.rarity_part = None
        # TokenOrderedState of the currently-loaded weapon, bound to level /
        # seed / rarity / part widgets by ``_bind_token_state_widgets``. Empty
        # until ``_load_weapon_item`` runs. Every structural mutation
        # (move / delete / add / skin / DnD reorder) keeps the state in sync
        # with parts_data via the ``state.move`` / ``state.insert`` /
        # ``state.remove`` / ``state.reorder_subset`` helpers, so
        # ``regenerate_ui_and_serial`` always routes through
        # ``state.render()`` — the token stream is the single source of
        # truth for the emitted serial.
        self._token_state = TokenOrderedState([])
        
        self.all_weapon_parts_df = None
        self.elemental_df = None
        self.skin_df = None
        self.weapon_rarity_df = None
        self.weapon_localization = {}
        
        self._is_loading = False
        self.current_lang = 'zh-CN'
        
        # Main layout
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.content_widget = None

        self.load_data(self.current_lang)
        self._build_ui()

    def load_data(self, lang='zh-CN'):
        loc_file = resource_loader.get_ui_localization_file(lang)
        full_loc = resource_loader.load_json_resource(loc_file) or {}
        self.ui_localization = full_loc.get("weapon_editor_tab", {})
        try:
            # Weapon CSVs ship in per-language variants named `<base>_EN.csv`
            # for non-Chinese locales; fall back to the base file if the
            # variant is missing so a partial dataset still loads.
            suffix = "_EN" if lang in ['en-US', 'ru', 'ua'] else ""

            # Helper to get path with fallback
            def get_path(base_name):
                # Try with suffix first
                name_with_suffix = base_name.replace('.csv', f'{suffix}.csv')
                path = resource_loader.get_weapon_data_path(name_with_suffix)
                if path and path.exists():
                    return path
                # Fallback to base
                return resource_loader.get_weapon_data_path(base_name)

            self.all_weapon_parts_df = pd.read_csv(get_path('all_weapon_part.csv'))
            self.elemental_df = pd.read_csv(resource_loader.get_weapon_data_path('elemental.csv'))
            self.elemental_stat_col = 'Stat_ZH' if lang == 'zh-CN' else 'Stat'
            self.skin_df = pd.read_csv(resource_loader.get_weapon_data_path('skin.csv'))
            self.skin_df['Skin_ID'] = self.skin_df['Skin_ID'].astype(str)
            self.skin_stat_col = 'Stat_EN' if lang in ['en-US', 'ru', 'ua'] else 'Stat'
            self.weapon_rarity_df = pd.read_csv(get_path('weapon_rarity.csv'))
            self.rarity_desc_col = 'Description_ZH' if lang == 'zh-CN' else 'Description'
            
            self.weapon_localization = {}
            if lang == 'zh-CN':
                self.weapon_localization = resource_loader.load_weapon_json('weapon_localization_zh-CN.json') or {}
            
            # Re-enable if data loaded successfully (in case it was disabled previously)
            self.setEnabled(True)
            
        except FileNotFoundError as e:
            QtWidgets.QMessageBox.critical(
                self,
                self._loc('dialogs', 'error', "Error"),
                self._loc('dialogs', 'missing_required_file', "Missing required file: {error}", error=e),
            )
            self.setEnabled(False)
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                self._loc('dialogs', 'error', "Error"),
                self._loc('dialogs', 'data_load_error', "An error occurred while loading data: {error}", error=e),
            )
            self.setEnabled(False)

    def update_language(self, lang):
        log_editor(self.main_app, self._LOG_TAG, f"Updating language for {self.__class__.__name__} to {lang}...")
        self.current_lang = lang
        self.load_data(lang)
        
        # Save current state
        current_decoded = self.serial_decoded_entry.text() if hasattr(self, 'serial_decoded_entry') else ""
        current_flag_idx = self.flag_combo.currentIndex() if hasattr(self, 'flag_combo') else 0
        current_weapon_path = self.selected_item_path
        
        # Clean up internal state
        self.parts_data = []
        self.rarity_part = None
        self.selected_item_path = current_weapon_path
        
        self._build_ui()
        self.refresh_backpack_items()
        
        # Restore state
        if hasattr(self, 'flag_combo') and self.flag_combo.count() > current_flag_idx:
            self.flag_combo.setCurrentIndex(current_flag_idx)
            
        # If there was data loaded, reload it to refresh text
        if current_decoded:
             self.serial_decoded_entry.setText(current_decoded) # Set text first so it's available if parse fails
             self.parse_and_display_weapon(current_decoded)
        log_editor(self.main_app, self._LOG_TAG, f"Finished updating language for {self.__class__.__name__}.")

    def _build_ui(self):
        # Clean up old content
        while self.main_layout.count():
            item = self.main_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
        self.content_widget = None

        # Create new content widget
        self.content_widget = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout(self.content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        
        self.main_layout.addWidget(self.content_widget)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        content_layout.addWidget(splitter)

        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)

        main_frame = QtWidgets.QFrame()
        scroll_area.setWidget(main_frame)
        layout = QtWidgets.QGridLayout(main_frame)
        layout.setColumnStretch(0, 1)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)  # Align all items to top

        self.backpack_browser = ItemBrowser(
            main_app=self.main_app,
            item_filter=self._is_weapon_item,
            row_builder=self._weapon_browser_row,
            header_label=self.get_localized_string("load_from_backpack"),
            search_placeholder=self._loc('labels', 'search_weapon_placeholder',
                                        "Search name, manufacturer, type, level, or slot"),
            empty_placeholder=self.get_localized_string("no_weapons_in_backpack"),
            no_save_placeholder=self.get_localized_string("decrypt_save_to_show_weapons"),
            summary_formatter=self._summarize_weapon,
            summary_none_text=self._loc('summary', 'none_selected', "No backpack weapon selected"),
        )
        self.backpack_browser.item_selected.connect(self._load_weapon_item)
        splitter.addWidget(self.backpack_browser)
        splitter.addWidget(scroll_area)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([320, 1040])
        
        s_frame = QtWidgets.QFrame(); s_frame.setObjectName("InnerFrame")
        s_layout = QtWidgets.QGridLayout(s_frame)
        s_layout.setColumnStretch(1, 1)
        s_layout.addWidget(QtWidgets.QLabel(self.get_localized_string("serial_b85")), 0, 0)
        self.serial_b85_entry = QtWidgets.QLineEdit()
        s_layout.addWidget(self.serial_b85_entry, 0, 1)
        s_layout.addWidget(QtWidgets.QLabel(self.get_localized_string("serial_decoded")), 1, 0)
        self.serial_decoded_entry = QtWidgets.QLineEdit()
        s_layout.addWidget(self.serial_decoded_entry, 1, 1)
        layout.addWidget(s_frame, 0, 0)

        act_frame = QtWidgets.QFrame()
        act_layout = QtWidgets.QGridLayout(act_frame)
        self.update_weapon_btn = QtWidgets.QPushButton(self.get_localized_string("update_weapon"))
        self.add_to_backpack_btn = QtWidgets.QPushButton(self.get_localized_string("add_to_backpack"))
        self.flag_combo = QtWidgets.QComboBox()
        
        # Load flags from UI localization
        flags = resource_loader.get_flag_labels(self.current_lang)
        self.flag_combo.addItems([flags[k] for k in ("1", "3", "5", "17", "33", "65", "129")])
            
        act_layout.addWidget(self.update_weapon_btn, 0, 0)
        act_layout.addWidget(self.add_to_backpack_btn, 0, 1)
        act_layout.addWidget(self.flag_combo, 0, 2)
        layout.addWidget(act_frame, 1, 0)
        
        editor_frame = QtWidgets.QFrame(); editor_frame.setObjectName("InnerFrame")
        editor_layout = QtWidgets.QGridLayout(editor_frame)
        for i in range(5): editor_layout.setColumnStretch(i, 1)
        
        labels = ["manufacturer", "weapon_type", "rarity", "level", "seed"]
        for i, lbl_key in enumerate(labels):
            editor_layout.addWidget(QtWidgets.QLabel(self.get_localized_string(lbl_key)), 0, i, QtCore.Qt.AlignmentFlag.AlignCenter)

        self.manufacturer_entry = QtWidgets.QLineEdit(); self.manufacturer_entry.setReadOnly(True)
        editor_layout.addWidget(self.manufacturer_entry, 1, 0)
        self.item_type_entry = QtWidgets.QLineEdit(); self.item_type_entry.setReadOnly(True)
        editor_layout.addWidget(self.item_type_entry, 1, 1)
        self.rarity_combo = QtWidgets.QComboBox()
        rarity_values = [self.get_localized_string(r) for r in ["Common", "Uncommon", "Rare", "Epic"]]
        self.rarity_combo.addItems(rarity_values)
        editor_layout.addWidget(self.rarity_combo, 1, 2)
        self.level_entry = QtWidgets.QLineEdit()
        self.level_entry.setValidator(QtGui.QIntValidator(1, 100))
        editor_layout.addWidget(self.level_entry, 1, 3)
        
        seed_layout = QtWidgets.QGridLayout()
        seed_frame = QtWidgets.QFrame(); seed_frame.setLayout(seed_layout)
        self.seed_entry = QtWidgets.QLineEdit(); self.seed_entry.setValidator(QtGui.QIntValidator())
        seed_layout.addWidget(self.seed_entry, 0, 0)
        self.random_seed_btn = QtWidgets.QPushButton("🎲"); self.random_seed_btn.setFixedWidth(40)
        seed_layout.addWidget(self.random_seed_btn, 0, 1)
        editor_layout.addWidget(seed_frame, 1, 4)
        
        self.weapon_name_label_str = self.get_localized_string("weapon_name_label")
        self.weapon_name_label = QtWidgets.QLabel(self.weapon_name_label_str)
        self.weapon_name_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        editor_layout.addWidget(self.weapon_name_label, 2, 0, 1, 5)

        stats_layout = QtWidgets.QGridLayout()
        stats_loc = self.ui_localization.get('stats', {})
        self.weapon_stat_value_labels = {}
        for index, key in enumerate(item_display_resolver.WEAPON_STAT_KEYS):
            row, column = divmod(index, 4)
            title_row = row * 2
            title = QtWidgets.QLabel(stats_loc.get(key, key.replace('_', ' ').title()))
            title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            title.setWordWrap(True)
            value = QtWidgets.QLabel("—")
            value.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            value.setMinimumWidth(72)
            value.setObjectName("WeaponStatValue")
            stats_layout.addWidget(title, title_row, column)
            stats_layout.addWidget(value, title_row + 1, column)
            stats_layout.setColumnStretch(column, 1)
            self.weapon_stat_value_labels[key] = value
        editor_layout.addLayout(stats_layout, 3, 0, 1, 5)
        layout.addWidget(editor_frame, 2, 0)
        
        parts_frame = QtWidgets.QFrame(); parts_frame.setObjectName("InnerFrame")
        parts_layout = QtWidgets.QVBoxLayout(parts_frame)
        
        parts_header_frame = QtWidgets.QFrame()
        parts_header_layout = QtWidgets.QGridLayout(parts_header_frame)
        parts_header_layout.addWidget(QtWidgets.QLabel(self.get_localized_string("weapon_parts")), 0, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
        parts_header_layout.setColumnStretch(0, 1)
        self.refresh_parts_btn = QtWidgets.QPushButton()
        self.refresh_parts_btn.setObjectName("PartActionButton")
        self.refresh_parts_btn.setIcon(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_BrowserReload))
        self.refresh_parts_btn.setFixedSize(34, 34)
        self.refresh_parts_btn.setToolTip(self._loc('tooltips', 'refresh_parts', "Refresh parts"))
        parts_header_layout.addWidget(self.refresh_parts_btn, 0, 1, QtCore.Qt.AlignmentFlag.AlignRight)
        self.add_part_btn = QtWidgets.QPushButton(self.get_localized_string("add_part")); self.add_part_btn.setMinimumWidth(100)
        parts_header_layout.addWidget(self.add_part_btn, 0, 2, QtCore.Qt.AlignmentFlag.AlignRight)
        self.add_skin_btn = QtWidgets.QPushButton(self.get_localized_string("add_skin")); self.add_skin_btn.setMinimumWidth(100)
        parts_header_layout.addWidget(self.add_skin_btn, 0, 3, QtCore.Qt.AlignmentFlag.AlignRight)
        parts_layout.addWidget(parts_header_frame)
        
        self.parts_list_widget = PartOrderListWidget()
        self.parts_list_widget.currentItemChanged.connect(self._sync_part_row_selection)
        self.parts_list_widget.orderDropped.connect(self._apply_part_list_order)
        parts_layout.addWidget(self.parts_list_widget)
        self._set_parts_placeholder(self.get_localized_string("parse_serial_to_show_parts"))
        layout.addWidget(parts_frame, 3, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        main_frame.setLayout(layout) # Set the grid layout to the main frame
        
        self.serial_b85_entry.textChanged.connect(self.handle_b85_change)
        self.serial_decoded_entry.textChanged.connect(self.handle_decoded_change)
        self.serial_decoded_entry.textChanged.connect(self._update_weapon_stats)
        self.rarity_combo.currentIndexChanged.connect(self.update_decoded_from_ui)
        self.level_entry.textChanged.connect(self.update_decoded_from_ui)
        self.seed_entry.textChanged.connect(self.update_decoded_from_ui)
        self.random_seed_btn.clicked.connect(self.randomize_seed)
        self.update_weapon_btn.clicked.connect(self.update_weapon)
        self.add_to_backpack_btn.clicked.connect(self.add_new_weapon_to_backpack)
        self.refresh_parts_btn.clicked.connect(self.force_refresh_parts)
        self.add_part_btn.clicked.connect(self.open_add_part_window)
        self.add_skin_btn.clicked.connect(lambda: self.open_select_skin_window(None))

    def _loc(self, section, key, en, **fmt):
        """Read weapon_editor_tab.<section>.<key> for the active language,
        falling back to the English literal (never Chinese or a raw key), then
        apply any format params. Used for strings that were previously inline
        zh-CN/else conditionals, so all four languages resolve from the JSON.
        按当前语言读取 weapon_editor_tab.<section>.<key>，缺失时回退到英文字面量
        （绝不显示中文或原始键），再套用格式参数。用于此前内联的 zh-CN/else
        条件字符串，使四种语言均从 JSON 解析。"""
        text = self.ui_localization.get(section, {}).get(key) or en
        return text.format(**fmt) if fmt else text

    def get_localized_string(self, key, default=''):
        taxonomy_key = self.TAXONOMY_KEYS.get(str(key))
        if taxonomy_key:
            value = self.ui_localization.get('taxonomy', {}).get(taxonomy_key)
            if value:
                return value
        for section in ('labels', 'buttons', 'dialogs', 'misc'):
            value = self.ui_localization.get(section, {}).get(key)
            if value:
                return value
        return self.weapon_localization.get(key, default or key)

    def handle_b85_change(self, text):
        if self._is_loading or not self.serial_b85_entry.hasFocus():
            return

        self._is_loading = True
        if not text:
            self.clear_all_fields()
            self._is_loading = False
            return

        decoded_str, _, err = decoder_logic.decode_serial_to_string(text)
        if not err:
            self.serial_decoded_entry.blockSignals(True)
            self.serial_decoded_entry.setText(decoded_str)
            self.serial_decoded_entry.blockSignals(False)
            self.parse_and_display_weapon(decoded_str)
            self.serial_b85_entry.setReadOnly(True)
            self.update_weapon_btn.setEnabled(True)
        else:
            self.serial_decoded_entry.clear()
        self._is_loading = False

    def handle_decoded_change(self, text):
        if not self.serial_decoded_entry.hasFocus():
            return
        self.update_b85_from_decoded()
        if not text:
            self.clear_all_fields(clear_b85=False)
            return
        self.parse_and_display_weapon(text)

    def update_b85_from_decoded(self):
        decoded_str = self.serial_decoded_entry.text()
        if not decoded_str: return
        new_b85, err = b_encoder.encode_to_base85(decoded_str)
        if not err:
            self.serial_b85_entry.blockSignals(True)
            self.serial_b85_entry.setText(new_b85)
            self.serial_b85_entry.blockSignals(False)

    def _get_rarity_and_weapon_name(self, parts, m_id, decoded_str=""):
        rarity, weapon_name, rarity_part, display_rarity, remaining_parts = "Unknown", "Unknown", None, "Unknown", list(parts)
        for p in parts:
            if not isinstance(p, dict) or p.get('type') != 'simple':
                continue
            part_id = p.get('id')
            if not part_id:
                continue
            part_details = self.all_weapon_parts_df[(self.all_weapon_parts_df['Manufacturer & Weapon Type ID'] == m_id) & (self.all_weapon_parts_df['Part ID'] == part_id)]
            if not part_details.empty and part_details.iloc[0]['Part Type'] == 'Barrel':
                part_name = item_display_resolver.weapon_part_name(m_id, part_id, self.current_lang, part_details.iloc[0])
                if part_name:
                    weapon_name = part_name
                    if weapon_name.endswith(' Barrel'):
                        weapon_name = weapon_name[:-len(' Barrel')]
                    break
        simple_parts = [p for p in parts if isinstance(p, dict) and p.get('type') == 'simple']
        if simple_parts and 'id' in simple_parts[0]:
            rarity_info = self.weapon_rarity_df[(self.weapon_rarity_df['Manufacturer & Weapon Type ID'] == m_id) & (self.weapon_rarity_df['Part ID'] == simple_parts[0]['id'] )]
            if not rarity_info.empty:
                details = rarity_info.iloc[0]; rarity, desc = details['Stat'], details[self.rarity_desc_col]
                display_rarity = f"{rarity} - {desc}" if rarity in {"Legendary", "Pearl"} and pd.notna(desc) and desc else rarity
                rarity_part = simple_parts[0]
        if not rarity_part: display_rarity = rarity = "Legendary"
        pearl_ids = set(range(51, 61))
        if any(
            p.get('id') == 1
            and (
                p.get('sub_id') in pearl_ids
                or bool(pearl_ids.intersection(p.get('sub_ids', [])))
            )
            for p in parts
            if isinstance(p, dict) and p.get('type') in {'elemental', 'group'}
        ):
            suffix = display_rarity.split(' - ', 1)[1] if ' - ' in display_rarity else ''
            rarity = "Pearl"
            display_rarity = f"Pearl - {suffix}" if suffix else "Pearl"
        if rarity_part: remaining_parts = [p for p in remaining_parts if p is not rarity_part]
        if decoded_str:
            m_rows = self.all_weapon_parts_df[self.all_weapon_parts_df['Manufacturer & Weapon Type ID'] == m_id]
            if not m_rows.empty:
                m_info = m_rows.iloc[0]
                display = item_display_resolver.resolve_item_display(
                    m_id,
                    str(m_info['Manufacturer']),
                    str(m_info['Weapon Type']),
                    decoded_str,
                    self.current_lang,
                )
                if display.get("display_source") != "fallback" and display.get("display_name"):
                    weapon_name = display["display_name"]
        return display_rarity, weapon_name, rarity_part, remaining_parts

    def clear_all_fields(self, clear_b85=True):
        self._is_loading = True
        if clear_b85: self.serial_b85_entry.clear()
        self.serial_decoded_entry.clear(); self.manufacturer_entry.clear(); self.item_type_entry.clear()
        self.rarity_combo.setCurrentIndex(-1); self.level_entry.clear(); self.seed_entry.clear()
        self.weapon_name_label.setText(self.weapon_name_label_str)
        self._update_weapon_stats("")

        self._set_parts_placeholder(self.get_localized_string("parse_serial_to_show_parts"))
        self.serial_b85_entry.setReadOnly(False); self.update_weapon_btn.setEnabled(False)
        self.selected_item_path, self.parts_data, self.rarity_part = None, [], None
        self._token_state = TokenOrderedState([])
        self.backpack_browser.clear_selection()
        self._is_loading = False

    def update_decoded_from_ui(self):
        if self._is_loading: return
        current_decoded = self.serial_decoded_entry.text()
        if not current_decoded: return
        try:
            updated_str = bl4f.update_level_in_decoded_str(current_decoded, self.level_entry.text())
            parts = updated_str.split('|')
            if len(parts) > 1 and len(parts[1].split(',')) > 1:
                seed_parts = parts[1].split(','); seed_parts[1] = f" {self.seed_entry.text()}"; parts[1] = ",".join(seed_parts)
                updated_str = "|".join(parts)

            if self.rarity_part and self.rarity_combo.isEnabled():
                rarity_map = {self.get_localized_string(k): k for k in ["Common", "Uncommon", "Rare", "Epic"]}
                if rarity_en := rarity_map.get(self.rarity_combo.currentText()):
                    m_id = int(updated_str.split('||')[0].strip().split('|')[0].strip().split(',')[0])
                    info = self.weapon_rarity_df[(self.weapon_rarity_df['Manufacturer & Weapon Type ID'] == m_id) & (self.weapon_rarity_df['Stat'] == rarity_en) & (self.weapon_rarity_df['Part Type'] == 'Rarity')]
                    if not info.empty:
                        new_id = info.iloc[0]['Part ID']
                        updated_str = updated_str.replace(self.rarity_part['raw'], f"{{{new_id}}}")
                        self.rarity_part['id'], self.rarity_part['raw'] = new_id, f"{{{new_id}}}"

            if self.serial_decoded_entry.text() != updated_str: self.serial_decoded_entry.setText(updated_str)
        except Exception as e: log_editor(self.main_app, self._LOG_TAG, f"Error in update_decoded_from_ui: {e}")

    def randomize_seed(self): self.seed_entry.setText(str(random.randint(100, 9999)))
    def _load_weapon_item(self, weapon_data):
        """Populate editor fields from a decoded weapon in the backpack.

        Weapon-specific differences from the 5 sibling ``_load_XX_item``
        loaders:
          - full serial is written into ``serial_b85_entry`` and
            ``serial_decoded_entry`` (weapon has a serial-text UI; the others
            build the serial purely from widget state)
          - part parsing runs via ``parse_and_display_weapon`` (weapon carries
            structured parts with types/rarity chips, not a fixed set of
            radios/lists)
          - no dedicated ``_is_loading`` flag beyond the shared one: the same
            attribute doubles as the guard on the two serial entries and
            covers the rebuild-cascade window

        Token-state wiring: parse the item into a ``TokenOrderedState`` and
        BIND widgets to their tokens — the header token at index 0 to a getter
        that rebuilds the header from ``level_entry`` / ``seed_entry``
        (preserving the source seed unless the user edited it), and each
        typed part token to a getter that reads the matching
        ``self.rarity_part`` / ``self.parts_data`` dict.
        ``regenerate_ui_and_serial`` then always routes through
        ``state.render()``: the load-then-regen no-edit path stays byte-
        identical to source across the 29 pristine weapons, and structural
        mutations (move / delete / add / skin swap / DnD reorder) keep
        state in sync surgically via ``state.move`` / ``state.insert`` /
        ``state.remove`` / ``state.reorder_subset``.
        """
        if not weapon_data:
            return
        log_editor(self.main_app, self._LOG_TAG, f"Loading weapon: {weapon_data.get('name')}")
        self.selected_item_path = weapon_data.get("original_path")
        self.backpack_browser.set_selected_path(self.selected_item_path)

        raw_decoded = weapon_data.get('decoded_full', '')
        self._token_state = self.backpack_browser.token_state_for(weapon_data, skin=True)
        # Drift check now lives in ItemBrowser.render_from_state — passing
        # expected_raw=<source> logs any tokenizer regression and falls back
        # to the source string, keeping the 29-weapon byte-identity pin safe.
        decoded_str = self.backpack_browser.render_from_state(
            self._token_state, expected_raw=raw_decoded,
        )

        self._is_loading = True
        self.serial_b85_entry.setText(weapon_data.get('serial', ''))
        self.serial_decoded_entry.setText(decoded_str)
        self._is_loading = False
        if not decoded_str:
            QtWidgets.QMessageBox.critical(self, self.get_localized_string("error"), self.get_localized_string("no_valid_decoded_data")); return
        # parse_and_display_weapon populates self.rarity_part / self.parts_data
        # and (at its tail) calls _bind_token_state_widgets so the closures
        # over those dicts stay live — no separate re-bind pass needed here.
        self.parse_and_display_weapon(decoded_str)
        self.serial_b85_entry.setReadOnly(True); self.update_weapon_btn.setEnabled(True)

    def _make_header_getter(self, header_raw):
        """Header-token-0 getter for weapon. Thin wrapper around the shared
        ``make_header_getter`` so ``_bind_token_state_widgets`` keeps a stable
        callable name; both level and seed widgets flow through and the
        seed_getter is live (weapon has its own seed field, unlike the four
        sibling tabs that pass ``seed_getter=None`` to preserve source seed).
        """
        return make_header_getter(
            header_raw,
            level_getter=lambda: self.level_entry.text(),
            seed_getter=lambda: self.seed_entry.text(),
        )

    def _bind_token_state_widgets(self):
        """Attach getters to ``self._token_state`` tokens so ``state.render()``
        reflects current widget / part-dict values.

        - Index 0 (header raw) → rebuild header from mfg_id + level + seed.
        - Every typed token (kind != 'raw') → return the matching part
          dict's ``raw`` string. Order: ``self.rarity_part`` first (if any),
          then every dict in ``self.parts_data`` in order.
        - Raw whitespace / delimiter tokens between typed tokens stay
          unbound so their source text is preserved verbatim.

        The getters close over the DICTS, not their positions, so an in-place
        mutation (``update_decoded_from_ui`` rewriting ``rarity_part['raw']``)
        surfaces on the next render. Structural mutations — add / remove /
        reorder / replace — invalidate the token→dict mapping, so the
        mutation entry points (``move_part`` / ``delete_part`` /
        ``_apply_part_list_order`` / ``add_selected_parts`` / ``update_skin``)
        keep the state in sync via ``state.move`` / ``state.insert`` /
        ``state.remove`` / ``state.reorder_subset`` and then call this method
        to re-attach fresh closures over the current ``parts_data`` dicts.
        """
        if not self._token_state.tokens:
            return
        # Reset any bindings from a prior load — a fresh weapon must not carry
        # stale closures over the previous weapon's part dicts.
        self._token_state.clear_bindings()
        self._token_state.bind(0, self._make_header_getter(self._token_state.tokens[0].raw))
        typed_dicts = [self.rarity_part] if self.rarity_part else []
        typed_dicts.extend(p for p in self.parts_data if isinstance(p, dict))
        dict_iter = iter(typed_dicts)
        for idx, tok in enumerate(self._token_state.tokens):
            if tok.kind == 'raw':
                continue
            try:
                part = next(dict_iter)
            except StopIteration:
                log_editor(
                    self.main_app, self._LOG_TAG,
                    f"_bind_token_state_widgets: more typed tokens ({sum(1 for t in self._token_state.tokens if t.kind != 'raw')}) "
                    f"than widget dicts ({len(typed_dicts)}); token at idx={idx} left unbound",
                )
                break
            self._token_state.bind(idx, (lambda p=part: p.get('raw')))

    def parse_and_display_weapon(self, decoded_str):
        try:
            header_part, component_part = decoded_str.split('||', 1)
            sections = header_part.strip().split('|')
            header_fields = sections[0].strip().split(',')
            m_id, level = int(header_fields[0]), int(header_fields[3])
            m_info = self.all_weapon_parts_df[self.all_weapon_parts_df['Manufacturer & Weapon Type ID'] == m_id].iloc[0]
            self._is_loading = True
            self.manufacturer_entry.setText(self.get_localized_string(m_info['Manufacturer']))
            self.item_type_entry.setText(self.get_localized_string(m_info['Weapon Type']))
            self.level_entry.setText(str(level))
            self.seed_entry.setText(sections[1].strip().split(',')[1].strip() if len(sections) > 1 and len(sections[1].strip().split(',')) > 1 else "")
            
            temp_parts = parse_component_string_with_skin(component_part)
            display_rarity, weapon_name, self.rarity_part, remaining_parts = self._get_rarity_and_weapon_name(temp_parts, m_id, decoded_str)
            
            rarity_parts = display_rarity.split(' - ')
            base_rarity, localized_base = rarity_parts[0], self.get_localized_string(rarity_parts[0])
            final_display_rarity = f"{localized_base} - {self.get_localized_string(rarity_parts[1], rarity_parts[1])}" if len(rarity_parts) > 1 else localized_base
            
            if base_rarity in {"Legendary", "Pearl"}:
                self.rarity_combo.setEditable(True); self.rarity_combo.lineEdit().setText(final_display_rarity); self.rarity_combo.setEnabled(False)
            else:
                self.rarity_combo.setEditable(False); self.rarity_combo.setEnabled(True)
                if (index := self.rarity_combo.findText(localized_base)) != -1: self.rarity_combo.setCurrentIndex(index)

            self.weapon_name_label.setText(f"{self.weapon_name_label_str} {weapon_name}")
            self._update_weapon_stats(decoded_str)
            self.parts_data = remaining_parts; self.display_parts(m_id)
            # parts_data / rarity_part are fresh dicts, so any prior bindings
            # closing over the previous set are stale. Re-parse the token
            # state from decoded_str (idempotent under a correct tokenizer —
            # _load_weapon_item's expected_raw drift-check catches regressions)
            # and re-bind so state.render() closes over the fresh dicts.
            self._token_state = self.backpack_browser.token_state_for(
                {'decoded_full': decoded_str}, skin=True,
            )
            self._bind_token_state_widgets()
            self._is_loading = False
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, self.get_localized_string("parse_error"), f"{self.get_localized_string('parse_weapon_error')}: {e}")
            log_editor(self.main_app, self._LOG_TAG, f"Error parsing weapon: {e}"); self.clear_all_fields()

    def _update_weapon_stats(self, decoded_str):
        if not hasattr(self, 'weapon_stat_value_labels'):
            return
        stats = item_display_resolver.resolve_weapon_stats(decoded_str) if decoded_str else {}
        for key, label in self.weapon_stat_value_labels.items():
            label.setText(item_display_resolver.format_weapon_stat(key, stats.get(key), self.current_lang) or "—")

    def display_parts(self, manufacturer_id):
        self.parts_list_widget.clear()
        if not self.parts_data:
            self._set_parts_placeholder(self.get_localized_string("parts_not_found")); return
        for i, part_info in enumerate(self.parts_data):
            if isinstance(part_info, str): continue
            frame = self._create_collapsible_part_frame(part_info, i) if part_info.get('type') == 'group' else self._create_simple_part_frame(part_info, manufacturer_id, i)
            if frame:
                frame.setCursor(QtCore.Qt.CursorShape.OpenHandCursor)
                frame.setToolTip(self._loc('tooltips', 'drag_part', "Drag to reorder"))
                item = QtWidgets.QListWidgetItem()
                item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsDropEnabled)
                item.setData(QtCore.Qt.ItemDataRole.UserRole, i)
                item.setData(QtCore.Qt.ItemDataRole.UserRole + 1, id(part_info))
                name_label = frame.findChild(QtWidgets.QLabel, "PartName")
                item.setData(QtCore.Qt.ItemDataRole.AccessibleTextRole, name_label.text() if name_label else str(part_info.get('id', '')))
                item.setSizeHint(QtCore.QSize(0, max(68, frame.sizeHint().height() + 4)))
                self.parts_list_widget.addItem(item)
                self.parts_list_widget.setItemWidget(item, frame)
        self.parts_list_widget.sync_content_height()

    def _set_parts_placeholder(self, text):
        self.parts_list_widget.clear()
        item = QtWidgets.QListWidgetItem(text)
        item.setFlags(item.flags() & ~(QtCore.Qt.ItemFlag.ItemIsDragEnabled | QtCore.Qt.ItemFlag.ItemIsDropEnabled))
        self.parts_list_widget.addItem(item)
        self.parts_list_widget.sync_content_height()

    @staticmethod
    def _set_row_selected(list_widget, item, selected):
        row = list_widget.itemWidget(item) if item else None
        PartOrderListWidget._refresh_property(row, "selected", selected)

    def _sync_part_row_selection(self, current, previous):
        self._set_row_selected(self.parts_list_widget, previous, False)
        self._set_row_selected(self.parts_list_widget, current, True)

    def _apply_part_list_order(self):
        slots = [index for index, part in enumerate(self.parts_data) if isinstance(part, dict)]
        order = [self.parts_list_widget.item(row).data(QtCore.Qt.ItemDataRole.UserRole) for row in range(self.parts_list_widget.count())]
        if len(order) != len(slots) or any(not isinstance(index, int) for index in order):
            self.display_parts(self._current_manufacturer_id())
            return
        moved_id = self.parts_list_widget.currentItem().data(QtCore.Qt.ItemDataRole.UserRole + 1) if self.parts_list_widget.currentItem() else None

        # Mutate parts_data (existing behaviour): parts_data[slots[k]] receives
        # the dict originally at parts_data[order[k]].
        ordered_parts = [self.parts_data[index] for index in order]
        for slot, part in zip(slots, ordered_parts):
            self.parts_data[slot] = part

        # Mirror the same permutation into the token state so state.render()
        # emits parts in the new user-chosen order. Parts-typed tokens
        # (non-raw, and non-rarity if present) map 1:1 to parts_data dicts in
        # order, so the permutation on parts_data lifts to a permutation on
        # parts_typed_indices.
        parts_typed_indices = self._parts_typed_state_indices()
        if len(parts_typed_indices) == len(slots):
            slot_to_pos = {slot: k for k, slot in enumerate(slots)}
            permutation = [slot_to_pos[order[k]] for k in range(len(order))]
            self._token_state.reorder_subset(parts_typed_indices, permutation)
        else:
            log_editor(
                self.main_app, self._LOG_TAG,
                f"_apply_part_list_order: parts_typed_indices ({len(parts_typed_indices)}) "
                f"!= slots ({len(slots)}) — token state not reordered, output may drift from DnD result",
            )

        self.regenerate_ui_and_serial()
        self._select_part_row(moved_id)

    def _parts_typed_state_indices(self):
        """Return state.tokens indices of the parts_data-mapped typed tokens
        in order.

        Skips the rarity-part slot (typed_indices[0] when a ``rarity_part``
        exists — rarity lives in state but not in ``parts_data``). Returns an
        empty list when the state is empty so callers can gate on length
        without a None guard.
        """
        typed_indices = [i for i, tok in enumerate(self._token_state.tokens) if tok.kind != 'raw']
        return typed_indices[1:] if self.rarity_part else typed_indices

    def _current_manufacturer_id(self):
        # Weapon reads its mfg id off the live decoded_entry text rather than
        # a shared helper: peer editors decode from cached serial state, but
        # weapon's decoded entry is always the truth-source here.
        try:
            return int(self.serial_decoded_entry.text().split('||', 1)[0].strip().split('|')[0].split(',')[0])
        except (ValueError, IndexError):
            return 0

    def _select_part_row(self, object_id):
        if object_id is None:
            return
        for row in range(self.parts_list_widget.count()):
            item = self.parts_list_widget.item(row)
            if item.data(QtCore.Qt.ItemDataRole.UserRole + 1) == object_id:
                self.parts_list_widget.setCurrentItem(item)
                if outer := self.parts_list_widget._outer_scroll_area():
                    outer.ensureWidgetVisible(self.parts_list_widget.itemWidget(item), 0, 80)
                return

    def _create_simple_part_frame(self, part_info, m_id, index):
        frame = QtWidgets.QFrame(); frame.setObjectName('PartFrame')
        layout = QtWidgets.QVBoxLayout(frame); layout.setSpacing(3); layout.setContentsMargins(1, 4, 1, 4)
        part_id = part_info.get('id')
        info = {
            'type': self._loc('parts', 'unknown', "Unknown"),
            'raw_type': "Unknown",
            'str': "",
            'stat': self._loc('parts', 'no_stat_changes', "No stat changes"),
        }
        is_skin, is_elemental = (part_info.get('type') == 'skin'), (part_info.get('type') == 'elemental')
        if is_skin:
            if not (d := self.skin_df[self.skin_df['Skin_ID'].str.lower() == str(part_id).lower()]).empty: info.update({'type': self.get_localized_string("Skin"), 'raw_type': "Skin", 'str': d.iloc[0][self.skin_stat_col], 'stat': self._loc('parts', 'cosmetic_part', "Cosmetic part")})
        elif is_elemental:
            if not (d := self.elemental_df[self.elemental_df['Part_ID'] == part_info['sub_id']]).empty:
                row = d.iloc[0]
                raw_type = self._elemental_part_type(row)
                description = item_display_resolver.format_weapon_part_description(
                    1, str(part_info['sub_id']), self.serial_decoded_entry.text(), self.current_lang, "Elemental"
                )
                no_change = description in {"无属性变化", "No stat changes"}
                info.update({
                    'type': self.get_localized_string(raw_type),
                    'raw_type': raw_type,
                    'str': row[self.elemental_stat_col],
                    'stat': self._loc('parts', 'element_config', "Element configuration") if no_change else description,
                })
        else:
            d = self.all_weapon_parts_df[(self.all_weapon_parts_df['Manufacturer & Weapon Type ID'] == m_id) & (self.all_weapon_parts_df['Part ID'] == part_id)]
            if not d.empty:
                row = d.iloc[0]
                name = item_display_resolver.weapon_part_name(m_id, part_id, self.current_lang, row)
                description = item_display_resolver.format_weapon_part_description(
                    m_id, part_id, self.serial_decoded_entry.text(), self.current_lang, str(row['Part Type'])
                )
                info.update({
                    'type': self.get_localized_string(row['Part Type']),
                    'raw_type': str(row['Part Type']),
                    'str': name or (self._loc('parts', 'unnamed_barrel', "Unnamed Barrel") if str(row['Part Type']) == "Barrel" else ""),
                    'stat': description,
                })
        display_text = f"  {part_id}  " if not is_elemental else f"  {part_info['id']}:{part_info['sub_id']}  "
        header = QtWidgets.QHBoxLayout()
        id_label = QtWidgets.QLabel(display_text); id_label.setObjectName("PartIdBadge")
        type_color = self.PART_TYPE_COLORS.get(info['raw_type'], "#e0e0e0")
        type_label = QtWidgets.QLabel(info['type']); type_label.setObjectName("PartTypeBadge"); type_label.setProperty("partColor", type_color); type_label.setStyleSheet(f"color: {type_color}; border-color: {type_color};"); type_label.setWordWrap(True)
        drag_label = PartDragHandle(self.parts_list_widget, self._loc('tooltips', 'drag_part', "Drag to reorder"))
        header.addWidget(drag_label)
        header.addWidget(type_label)
        if info['str']:
            name_label = QtWidgets.QLabel(str(info['str'])); name_label.setObjectName("PartName"); name_label.setWordWrap(True)
            header.addWidget(name_label, 1)
        else:
            header.addStretch(1)
        header.addWidget(id_label); header.addWidget(self._add_action_buttons(index, is_skin))
        description_label = QtWidgets.QLabel(str(info['stat']) if pd.notna(info['stat']) else "")
        description_label.setObjectName("PartDescription"); description_label.setWordWrap(True)
        layout.addLayout(header); layout.addWidget(description_label)
        return frame

    def _create_collapsible_part_frame(self, part_info, index):
        container = QtWidgets.QFrame(); container.setObjectName('PartGroupFrame')
        container_layout = QtWidgets.QVBoxLayout(container); container_layout.setSpacing(0); container_layout.setContentsMargins(0,0,0,0)
        header, content = QtWidgets.QFrame(), QtWidgets.QFrame()
        header_layout, content_layout = QtWidgets.QGridLayout(header), QtWidgets.QVBoxLayout(content)
        group_id = part_info.get('id', 0)
        mfg_name = self._loc('parts', 'unknown_manufacturer', "Unknown Manufacturer")
        if group_id != 1:
            try:
                mfg_name = self.get_localized_string(self.all_weapon_parts_df[self.all_weapon_parts_df['Manufacturer & Weapon Type ID'] == group_id].iloc[0]['Manufacturer'])
            except (IndexError, KeyError):
                pass
        toggle_btn = QtWidgets.QPushButton("▾"); toggle_btn.setObjectName("PartActionButton"); toggle_btn.setFixedSize(28, 28)
        toggle_btn.clicked.connect(lambda checked, b=toggle_btn, c=content: self._toggle_group_visibility(b, c))
        if group_id == 1:
            group_title = self._loc('parts', 'element_group', "Element Configuration Group · {n} parts", n=len(part_info.get('sub_ids', [])))
        else:
            group_title = self._loc('parts', 'licensed_group', "Licensed Part Group · {mfg} · {n} parts", mfg=mfg_name, n=len(part_info.get('sub_ids', [])))
        title_label = QtWidgets.QLabel(group_title); title_label.setObjectName("PartName"); title_label.setWordWrap(True)
        drag_label = PartDragHandle(self.parts_list_widget, self._loc('tooltips', 'drag_part', "Drag to reorder"))
        header_layout.addWidget(drag_label, 0, 0); header_layout.addWidget(toggle_btn, 0, 1); header_layout.addWidget(title_label, 0, 2)
        header_layout.setColumnStretch(2, 1)
        action_buttons = self._add_action_buttons(index)
        header_layout.addWidget(action_buttons, 0, 3, QtCore.Qt.AlignmentFlag.AlignRight)
        for sub_id in part_info.get('sub_ids', []):
            sub_frame = QtWidgets.QFrame(); sub_frame.setObjectName("PartSubFrame")
            sub_layout = QtWidgets.QGridLayout(sub_frame); sub_layout.setColumnStretch(1, 1)
            id_label = QtWidgets.QLabel(f"  {sub_id}  "); id_label.setObjectName("PartIdBadge")
            sub_layout.addWidget(id_label, 0, 0)
            p_type = self._loc('parts', 'unknown', "Unknown")
            p_str = ""
            p_stat = self._loc('parts', 'no_stat_changes', "No stat changes")
            if group_id == 1:
                d = self.elemental_df[
                    (self.elemental_df['Elemental_ID'] == group_id)
                    & (self.elemental_df['Part_ID'] == sub_id)
                ]
                if not d.empty:
                    row = d.iloc[0]
                    description = item_display_resolver.format_weapon_part_description(
                        group_id, str(sub_id), self.serial_decoded_entry.text(), self.current_lang, "Elemental"
                    )
                    p_type = self.get_localized_string(self._elemental_part_type(row))
                    p_str = str(row[self.elemental_stat_col])
                    p_stat = self._loc('parts', 'element_config', "Element configuration") if description in {"无属性变化", "No stat changes"} else description
            else:
                d = self.all_weapon_parts_df[(self.all_weapon_parts_df['Manufacturer & Weapon Type ID'] == group_id) & (self.all_weapon_parts_df['Part ID'] == sub_id)]
                if not d.empty:
                    row = d.iloc[0]
                    name = item_display_resolver.weapon_part_name(group_id, sub_id, self.current_lang, row)
                    description = item_display_resolver.format_weapon_part_description(
                        group_id, sub_id, self.serial_decoded_entry.text(), self.current_lang, str(row['Part Type'])
                    )
                    p_type = self.get_localized_string(row['Part Type'])
                    p_str = name or (self._loc('parts', 'unnamed_barrel', "Unnamed Barrel") if str(row['Part Type']) == "Barrel" else "")
                    p_stat = description
            name_label = QtWidgets.QLabel(" · ".join(value for value in (p_type, p_str) if value)); name_label.setObjectName("PartName"); name_label.setWordWrap(True)
            stat_label = QtWidgets.QLabel(str(p_stat)); stat_label.setObjectName("PartDescription"); stat_label.setWordWrap(True)
            sub_layout.addWidget(name_label, 0, 1); sub_layout.addWidget(stat_label, 1, 1)
            content_layout.addWidget(sub_frame)
        content.setLayout(content_layout); container_layout.addWidget(header); container_layout.addWidget(content)
        return container
        
    def _add_action_buttons(self, index, is_skin=False):
        frame = QtWidgets.QFrame()
        frame.setObjectName("PartActionFrame")
        layout = QtWidgets.QHBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        if is_skin:
            edit_btn = QtWidgets.QPushButton("✎"); edit_btn.setToolTip(self._loc('tooltips', 'change_skin', "Change skin")); edit_btn.clicked.connect(partial(self.open_select_skin_window, index)); layout.addWidget(edit_btn)
        else:
            up_btn = QtWidgets.QPushButton(); up_btn.setIcon(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ArrowUp)); up_btn.setToolTip(self._loc('tooltips', 'move_up', "Move up")); up_btn.clicked.connect(partial(self.move_part, index, -1)); layout.addWidget(up_btn)
            down_btn = QtWidgets.QPushButton(); down_btn.setIcon(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ArrowDown)); down_btn.setToolTip(self._loc('tooltips', 'move_down', "Move down")); down_btn.clicked.connect(partial(self.move_part, index, 1)); layout.addWidget(down_btn)
        del_btn = QtWidgets.QPushButton(); del_btn.setIcon(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DialogCloseButton)); del_btn.setObjectName("PartDeleteButton"); del_btn.setToolTip(self._loc('tooltips', 'remove_part', "Remove")); del_btn.clicked.connect(partial(self.delete_part, index)); layout.addWidget(del_btn)
        buttons = frame.findChildren(QtWidgets.QPushButton)
        for button in buttons:
            if button.objectName() != "PartDeleteButton": button.setObjectName("PartActionButton")
            button.setFixedSize(34, 34)
            button.setIconSize(QtCore.QSize(18, 18))
            button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            button.setAccessibleName(button.toolTip())
        frame.setFixedSize(len(buttons) * 34 + max(0, len(buttons) - 1) * layout.spacing(), 34)
        return frame

    def move_part(self, index, direction):
        # parts_data interleaves whitespace separators with part dicts, so a raw
        # index±1 step often lands on a separator and moves nothing visible —
        # which is why moving a part took several clicks. Step over separators to
        # the adjacent real part and swap the two, so one click moves one part.
        # parts_data 中部件字典与空白分隔符交替，因此 index±1 的原始步进常落在
        # 分隔符上、视觉上毫无移动——这正是移动部件需点击多次的原因。跳过分隔符
        # 找到相邻的真实部件并交换二者，使一次点击移动一个部件。
        if not (0 <= index < len(self.parts_data)) or not isinstance(self.parts_data[index], dict):
            return
        target = index + direction
        while 0 <= target < len(self.parts_data) and not isinstance(self.parts_data[target], dict):
            target += direction
        if not 0 <= target < len(self.parts_data):
            return
        moved_id = id(self.parts_data[index])

        # Compute the state-side swap BEFORE mutating parts_data (both indices
        # need the CURRENT dict-position mapping, not the post-swap one).
        dict_positions = [i for i, p in enumerate(self.parts_data) if isinstance(p, dict)]
        parts_typed_indices = self._parts_typed_state_indices()
        state_pair = None
        if len(parts_typed_indices) == len(dict_positions):
            src_k = dict_positions.index(index)
            dst_k = dict_positions.index(target)
            i_src, i_dst = parts_typed_indices[src_k], parts_typed_indices[dst_k]
            # subset order doesn't matter; permutation [1, 0] swaps whichever
            # two positions we pass in.
            state_pair = (min(i_src, i_dst), max(i_src, i_dst))
        else:
            log_editor(
                self.main_app, self._LOG_TAG,
                f"move_part: parts_typed_indices ({len(parts_typed_indices)}) "
                f"!= dict_positions ({len(dict_positions)}) — token state not moved, output may drift from widget order",
            )

        self.parts_data[index], self.parts_data[target] = self.parts_data[target], self.parts_data[index]
        if state_pair is not None:
            self._token_state.reorder_subset(list(state_pair), [1, 0])

        self.regenerate_ui_and_serial()
        self._select_part_row(moved_id)

    def delete_part(self, index):
        if not (0 <= index < len(self.parts_data)):
            return
        part = self.parts_data[index]

        # Locate the matching typed token in state BEFORE mutating parts_data.
        # Typed-dicts order = [rarity_part?, *parts_data dicts]; identity match
        # avoids collisions between value-equal dicts (elemental groups can
        # share sub-ids in principle).
        state_idx = None
        if isinstance(part, dict):
            typed_dicts = ([self.rarity_part] if self.rarity_part else []) + [
                p for p in self.parts_data if isinstance(p, dict)
            ]
            typed_indices = [i for i, tok in enumerate(self._token_state.tokens) if tok.kind != 'raw']
            for k, td in enumerate(typed_dicts):
                if td is part and k < len(typed_indices):
                    state_idx = typed_indices[k]
                    break

        self.parts_data.pop(index)

        # Remove the typed token PLUS one adjacent raw whitespace token so the
        # rendered stream doesn't accumulate double spaces on repeated deletes
        # (the previous widget-splice path collapsed \s{2,} via regex; the
        # token-stream analog is to keep exactly one separator per gap by
        # dropping one on delete). Prefer the trailing raw so head padding
        # after "||" survives; fall back to the leading raw when we deleted
        # the last typed token. Higher index popped first so the lower index
        # doesn't shift.
        if state_idx is not None:
            tokens = self._token_state.tokens
            # Only collapse whitespace-only raw tokens — never touch a raw that
            # carries a section delimiter like '|' (parts/skin separator) or
            # '||' (header/components separator). Deleting the last non-skin
            # part would otherwise strip the '|' and corrupt the serial.
            trailing_ok = (
                state_idx + 1 < len(tokens)
                and tokens[state_idx + 1].kind == 'raw'
                and not tokens[state_idx + 1].raw.strip()
            )
            leading_ok = (
                state_idx > 0
                and tokens[state_idx - 1].kind == 'raw'
                and not tokens[state_idx - 1].raw.strip()
            )
            if trailing_ok:
                self._token_state.remove(state_idx + 1)
                self._token_state.remove(state_idx)
            elif leading_ok:
                self._token_state.remove(state_idx)
                self._token_state.remove(state_idx - 1)
            else:
                self._token_state.remove(state_idx)

        self._bind_token_state_widgets()
        self.regenerate_ui_and_serial()

    def regenerate_ui_and_serial(self):
        """Rebuild the decoded serial and re-encode to b85.

        Always routes through ``state.render()``. Every mutation entry point
        (``move_part`` / ``delete_part`` / ``_apply_part_list_order`` /
        ``add_selected_parts`` / ``update_skin``) keeps ``_token_state`` in
        sync with ``parts_data`` via the ``state.move`` / ``state.insert`` /
        ``state.remove`` / ``state.reorder_subset`` helpers, so the token
        stream is authoritative. The load-then-regen no-edit path and the
        mutation path emit through the same code, so byte-identical
        round-trip holds on both.
        """
        current_decoded = self.serial_decoded_entry.text()
        if '||' not in current_decoded: return
        header_part, _ = current_decoded.split('||', 1)
        try: m_id = int(header_part.strip().split('|')[0].strip().split(',')[0])
        except (ValueError, IndexError): return
        if not self._token_state.tokens:
            # No state yet (e.g. cleared) — nothing to render. Regenerate is
            # only called from mutation entry points that require a loaded
            # weapon, so hitting this guard indicates a caller bug we prefer
            # to no-op silently rather than trash the serial field.
            return

        new_decoded = self.backpack_browser.render_from_state(self._token_state)
        self.serial_decoded_entry.setText(new_decoded)
        new_b85, err = b_encoder.encode_to_base85(new_decoded)
        if not err:
            self.serial_b85_entry.blockSignals(True)
            self.serial_b85_entry.setText(new_b85)
            self.serial_b85_entry.blockSignals(False)
        self.display_parts(m_id)

    def force_refresh_parts(self):
        if not (decoded_str := self.serial_decoded_entry.text()):
            QtWidgets.QMessageBox.warning(self, self.get_localized_string("no_input"), self.get_localized_string("serial_empty")); return
        log_editor(self.main_app, self._LOG_TAG, "Forcing parts list refresh..."); self.parse_and_display_weapon(decoded_str)
        QtWidgets.QMessageBox.information(self, self.get_localized_string("success"), self.get_localized_string("parts_refresh_success"))

    @classmethod
    def _is_weapon_item(cls, item):
        return item.get("type_en") in cls._WEAPON_TYPES and "Backpack" in (item.get("container") or "")

    def _derive_weapon_display(self, weapon):
        """Resolve ``weapon`` into ``(display_name, detail)`` strings for the
        browser row. Separates parse/localize/format from row-widget
        construction so ``_weapon_browser_row`` matches the tighter shape used
        by every peer editor.
        """
        header, component = weapon.get('decoded_full', '').split('||', 1)
        m_id = int(header.strip().split('|')[0].strip().split(',')[0])
        parsed_components = parse_component_string_with_skin(component)
        _, name, _, _ = self._get_rarity_and_weapon_name(parsed_components, m_id, weapon.get('decoded_full', ''))
        w_name = self.get_localized_string(name, name)
        unknown = self._loc('parts', 'unknown', "Unknown")
        manufacturer = weapon.get('manufacturer') or unknown
        weapon_type = weapon.get('type') or self._loc('parts', 'unknown_item', "Unknown Item")
        unknown_names = {"N/A", "Unknown", "未知", "Неизвестно", "Невідомо", unknown}
        display_name = (
            f"{manufacturer} {weapon_type} ({w_name})"
            if w_name not in unknown_names else f"{manufacturer} {weapon_type}"
        )
        detail = (
            f"{self.get_localized_string('level_label')} {weapon.get('level', 'N/A')}"
            f"  ·  {self.get_localized_string('slot_label')} {weapon.get('slot', 'N/A').replace('slot_', '')}"
        )
        return display_name, detail

    def _weapon_browser_row(self, weapon):
        """Build the vertical-card row for a weapon in the browser.

        Returns ``(display_name, detail, row_widget)`` — the ItemBrowser
        drops the widget into the list item and uses the strings for tooltips
        and search-blob composition.
        """
        disp_name, detail = self._derive_weapon_display(weapon)

        row = QtWidgets.QWidget()
        row.setObjectName("ItemBrowserRow")
        row.setFixedHeight(ROW_HEIGHT)
        row_layout = QtWidgets.QVBoxLayout(row)
        row_layout.setContentsMargins(10, 7, 10, 7)
        row_layout.setSpacing(5)

        name_label = QtWidgets.QLabel(disp_name)
        name_label.setObjectName("ItemBrowserName")
        name_label.setToolTip(disp_name)
        name_label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.NoTextInteraction)
        detail_label = QtWidgets.QLabel(detail)
        detail_label.setObjectName("ItemBrowserMeta")
        detail_label.setToolTip(detail)
        row_layout.addWidget(name_label)
        row_layout.addWidget(detail_label)

        stats = item_display_resolver.resolve_weapon_stats(weapon.get('decoded_full', '')) or {}
        stat_titles = self.ui_localization.get('stats', {})
        stats_layout = QtWidgets.QGridLayout()
        stats_layout.setContentsMargins(0, 2, 0, 0)
        stats_layout.setHorizontalSpacing(4)
        stats_layout.setVerticalSpacing(1)
        for column, key in enumerate(("damage", "accuracy", "fire_rate", "reload_time", "magazine")):
            title_label = QtWidgets.QLabel(stat_titles.get(key, key.replace('_', ' ').title()))
            title_label.setObjectName("ItemBrowserStatTitle")
            title_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            title_label.setWordWrap(True)
            value = item_display_resolver.format_weapon_stat(key, stats.get(key), self.current_lang) or "—"
            value_label = QtWidgets.QLabel(value)
            value_label.setObjectName("ItemBrowserStatValue")
            value_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            stats_layout.addWidget(title_label, 0, column)
            stats_layout.addWidget(value_label, 1, column)
            stats_layout.setColumnStretch(column, 1)
        row_layout.addLayout(stats_layout)
        return disp_name, detail, row

    def _summarize_weapon(self, weapon):
        name = weapon.get("name") or weapon.get("manufacturer") or self._loc('summary', 'fallback_name', "Weapon")
        return self._loc(
            'summary', 'selected', "Selected · {name} · Lv.{level}",
            name=name, level=weapon.get('level', 'N/A'),
        )

    def refresh_backpack_items(self):
        self.backpack_browser.refresh()

    def update_weapon(self):
        if not self.selected_item_path:
            QtWidgets.QMessageBox.warning(self, self.get_localized_string("no_selection"), self.get_localized_string("select_weapon_first"))
            return

        new_serial, err = b_encoder.encode_to_base85(self.serial_decoded_entry.text().strip())
        if err:
            QtWidgets.QMessageBox.critical(self, self.get_localized_string("encoding_fail"), f"{self.get_localized_string('cannot_reencode_serial')}: {err}")
            return

        # 构造符合新 update_item 签名的载荷
        # 我们假设原始数据没有改变，只更新序列号
        # original_item_data 和 new_item_data 可以是部分数据
        payload = {
            'item_path': self.selected_item_path,
            'original_item_data': {}, # 留空，让controller自行处理
            'new_item_data': {'serial': new_serial},
            'success_msg': self.get_localized_string('update_success')
        }
        self.update_item_requested.emit(payload)

    def add_new_weapon_to_backpack(self):
        new_decoded = self.serial_decoded_entry.text().strip()
        if not new_decoded:
            QtWidgets.QMessageBox.warning(self, self.get_localized_string("no_input"), self.get_localized_string("serial_empty"))
            return
        new_serial, err = b_encoder.encode_to_base85(new_decoded)
        if err:
            QtWidgets.QMessageBox.critical(self, self.get_localized_string("encoding_fail"), f"{self.get_localized_string('cannot_encode_serial')}: {err}")
            return
        
        # 使用 flag_combo 的值
        self.add_to_backpack_requested.emit(new_serial, self.flag_combo.currentText().split(" ")[0])

    def open_add_part_window(self):
        if not self.serial_decoded_entry.text():
            QtWidgets.QMessageBox.warning(self, self.get_localized_string("no_weapon"), self.get_localized_string("load_weapon_first")); return

        win = QtWidgets.QDialog(self)
        win.setObjectName("addPartDialog")
        win.setWindowTitle(self.get_localized_string("add_part_title"))
        win.setMinimumSize(1050, 720)
        win.setModal(True)

        layout = QtWidgets.QVBoxLayout(win)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        header_label = QtWidgets.QLabel(self.get_localized_string("select_parts_to_add"))
        header_label.setObjectName("addPartDialogHeader")
        layout.addWidget(header_label)

        picker = CatalogPicker(
            stackable=True,
            search_placeholder=self._loc('catalog', 'search_part', "Search part name, effect, manufacturer, or type"),
            avail_title=self._loc('catalog', 'available_parts', "Available Parts"),
            selected_title=self._loc('catalog', 'selected_parts', "Selected Parts"),
            clear_text=self._loc('catalog', 'clear', "Clear"),
        )
        source, part_types, manufacturers, weapon_types = self._add_part_catalog_items()
        picker.set_categories(
            [("all", self._loc('catalog', 'all', "All")), *[(value, self.get_localized_string(value)) for value in part_types]],
            columns=3,
        )
        picker.set_subcategories(
            [("all", self._loc('catalog', 'all_manufacturers', "All Manufacturers")), *[(value, self.get_localized_string(value)) for value in manufacturers]],
            columns=4,
        )
        picker.set_third_categories(
            [("all", self._loc('catalog', 'all_weapon_types', "All Weapon Types")), *[(value, self.get_localized_string(value)) for value in weapon_types]],
            columns=3,
        )
        picker.set_source(source)
        layout.addWidget(picker, 1)

        confirm_btn = QtWidgets.QPushButton(self.get_localized_string("confirm_add"))
        confirm_btn.setObjectName("genAddButton")
        confirm_btn.clicked.connect(lambda: self.add_selected_parts(win, picker))
        layout.addWidget(confirm_btn)
        win.exec()

    def _add_part_catalog_items(self):
        source = []
        part_types = list(dict.fromkeys(str(value) for value in self.all_weapon_parts_df['Part Type'].dropna()))
        elemental_type = "Elemental"
        elemental_types = ("Element", "Element Switch", "Underbarrel Element Switch", "Pearl Elements", "Pearl Stat")
        part_types.extend(value for value in elemental_types if value not in part_types)
        manufacturers = list(dict.fromkeys(str(value) for value in self.all_weapon_parts_df['Manufacturer'].dropna()))
        manufacturers.append(elemental_type)
        weapon_types = list(dict.fromkeys(str(value) for value in self.all_weapon_parts_df['Weapon Type'].dropna()))
        weapon_types.append(elemental_type)

        try:
            level = int(self.level_entry.text())
        except ValueError:
            level = 60
        for _, row in self.all_weapon_parts_df.iterrows():
            item_id, part_id = int(row['Manufacturer & Weapon Type ID']), str(row['Part ID'])
            part_type, manufacturer = str(row['Part Type']), str(row['Manufacturer'])
            weapon_type = str(row['Weapon Type'])
            name = item_display_resolver.weapon_part_name(item_id, part_id, self.current_lang, row)
            preview_serial = f"{item_id}, 0, 1, {level}| 2, 0|| |"
            description = item_display_resolver.format_weapon_part_description(
                item_id, part_id, preview_serial, self.current_lang, part_type
            )
            name = name or (self._loc('parts', 'unnamed_barrel', "Unnamed Barrel") if part_type == "Barrel" else "")
            detail = " · ".join(value for value in (name, description) if value)
            metadata = " / ".join(self.get_localized_string(value) for value in (manufacturer, weapon_type, part_type))
            label = f"{detail}  [{metadata}]"
            source.append({
                "key": f"normal:{item_id}:{part_id}", "label": label, "category": part_type,
                "subcategory": manufacturer, "tertiary": weapon_type,
                "data": {"id": part_id, "mfg_id": item_id, "type": "normal"},
            })

        for _, row in self.elemental_df.iterrows():
            element_id, part_id = int(row['Elemental_ID']), int(row['Part_ID'])
            name = str(row[self.elemental_stat_col])
            part_type = self._elemental_part_type(row)
            source.append({
                "key": f"elemental:{element_id}:{part_id}", "label": name, "category": part_type,
                "subcategory": elemental_type, "tertiary": elemental_type,
                "data": {"id": part_id, "mfg_id": element_id, "type": "elemental"},
            })
        return source, part_types, manufacturers, weapon_types

    @staticmethod
    def _elemental_part_type(row):
        stat = str(row['Stat'])
        if stat.startswith("Pearl Stat"):
            return "Pearl Stat"
        if stat.startswith("Pearl Elements"):
            return "Pearl Elements"
        if stat.startswith("Maliwan Underbarrel-switch"):
            return "Underbarrel Element Switch"
        if stat.startswith("switch between"):
            return "Element Switch"
        return "Element"

    def _build_part_strings(self, parts_by_mfg, current_weapon_mfg_id):
        new_parts_list = []
        for mfg_id, parts in parts_by_mfg.items():
            elemental_parts = [f"{{1:{p['id']}}}" for p in parts if p['type'] == 'elemental']
            normal_parts = [p['id'] for p in parts if p['type'] == 'normal']

            if mfg_id == 1:  # Elemental parts mfg_id is 1
                new_parts_list.extend(elemental_parts)
            elif mfg_id == current_weapon_mfg_id:
                new_parts_list.extend([f"{{{pid}}}" for pid in normal_parts])
            elif normal_parts:
                new_parts_list.append(f"{{{mfg_id}:[{' '.join(map(str, sorted(normal_parts)))}]}}")
        return new_parts_list

    def add_selected_parts(self, window, picker):
        parts_by_mfg = {}
        try:
            current_weapon_mfg_id = int(self.serial_decoded_entry.text().split(',')[0])
        except (ValueError, IndexError):
            QtWidgets.QMessageBox.critical(self, self.get_localized_string("error"), self.get_localized_string("cannot_determine_mfg"))
            return window.close()

        for entry in picker.entries():
            item = entry['data']
            mfg_id = int(item['mfg_id'])
            parts_by_mfg.setdefault(mfg_id, [])
            count = 1 if item['type'] == 'elemental' else entry['count']
            parts_by_mfg[mfg_id].extend([{'id': item['id'], 'type': item['type']}] * count)

        if not parts_by_mfg:
            return window.close()

        new_parts_list = self._build_part_strings(parts_by_mfg, current_weapon_mfg_id)
        if not new_parts_list:
            return window.close()

        joined_new = " ".join(new_parts_list)
        new_part_data = parse_component_string_with_skin(joined_new)

        # Compute the state insertion point BEFORE mutating parts_data — the
        # calculation uses the CURRENT typed-dicts-to-state-tokens mapping.
        # Target: just after the last non-skin typed token so appended parts
        # come before the skin section (parity with parts_data insertion).
        typed_dicts_pre = ([self.rarity_part] if self.rarity_part else []) + [
            p for p in self.parts_data if isinstance(p, dict)
        ]
        typed_indices_pre = [i for i, tok in enumerate(self._token_state.tokens) if tok.kind != 'raw']
        state_insert_at = 1  # default: after header
        for k, d in enumerate(typed_dicts_pre):
            if k >= len(typed_indices_pre):
                break
            if d.get('type') != 'skin':
                state_insert_at = typed_indices_pre[k] + 1

        # Find the last non-skin part index to insert after (parts_data side)
        insertion_index = len(self.parts_data)
        for i in range(len(self.parts_data) - 1, -1, -1):
            part = self.parts_data[i]
            if isinstance(part, dict) and part.get('type') != 'skin':
                insertion_index = i + 1
                break

        # Insert a space if needed before adding new parts
        if insertion_index > 0:
            prev_item = self.parts_data[insertion_index - 1]
            if (isinstance(prev_item, dict)) or (isinstance(prev_item, str) and prev_item.strip()):
                self.parts_data.insert(insertion_index, ' ')
                insertion_index += 1

        self.parts_data[insertion_index:insertion_index] = new_part_data

        # Tokenize the fragment with a leading space so the first new typed
        # token has a raw separator between it and whatever preceded it in
        # state; internal separators between the new parts come from the
        # " ".join above. Insert one token at a time so the state's own
        # binding re-key pass runs per insert (bindings on shifted tokens
        # follow them intact — inherited from ``TokenOrderedState.insert``).
        new_tokens = parse_component_tokens_with_skin(" " + joined_new)
        for offset, tok in enumerate(new_tokens):
            self._token_state.insert(state_insert_at + offset, tok)

        # Fresh dicts entered parts_data at state_insert_at..; the pre-existing
        # bindings past that point still close over the correct dicts (dict
        # identity unchanged for pre-existing parts), but the newly-inserted
        # typed tokens have no binding. A full rebind covers both — cheaper
        # in code than an incremental one and guaranteed correct.
        self._bind_token_state_widgets()
        self.regenerate_ui_and_serial()
        log_editor(self.main_app, self._LOG_TAG, f"Added {len(new_part_data)} new part(s).")
        window.close()

    def open_select_skin_window(self, part_index):
        if not self.serial_decoded_entry.text():
            QtWidgets.QMessageBox.warning(self, self.get_localized_string("no_weapon"), self.get_localized_string("load_weapon_first"))
            return
        win = QtWidgets.QDialog(self); win.setWindowTitle(self.get_localized_string("select_skin_title"))
        win.setMinimumSize(400, 500); win.setModal(True)
        layout = QtWidgets.QVBoxLayout(win); layout.addWidget(QtWidgets.QLabel(self.get_localized_string("select_skin_msg")))
        scroll_area = ContainedWheelScrollArea(); scroll_area.setWidgetResizable(True)
        scroll_content = QtWidgets.QWidget(); scroll_layout = QtWidgets.QVBoxLayout(scroll_content)
        for _, row in self.skin_df.iterrows():
            skin_name = row[self.skin_stat_col] if pd.notna(row.get(self.skin_stat_col)) else row['Stat']
            btn = QtWidgets.QPushButton(f"{row['Skin_ID']}: {self.get_localized_string(skin_name, skin_name)}")
            btn.clicked.connect(partial(self.update_skin, part_index, row['Skin_ID'], win)); scroll_layout.addWidget(btn)
        scroll_area.setWidget(scroll_content); layout.addWidget(scroll_area); win.exec()
    
    def _toggle_group_visibility(self, button, content_frame):
        is_visible = not content_frame.isVisible()
        content_frame.setVisible(is_visible)
        button.setText("▾" if is_visible else "▸")
        container = content_frame.parentWidget()
        container.updateGeometry()
        self.parts_list_widget.sync_content_height()

    def update_skin(self, part_index, new_skin_id, window):
        is_text_id = isinstance(new_skin_id, str) and not new_skin_id.isdigit()
        skin = {
            'type': 'skin',
            'id': new_skin_id if is_text_id else int(new_skin_id),
            'raw': f' "c", "{new_skin_id}"' if is_text_id else f' "c", {int(new_skin_id)}',
        }
        target_index = part_index
        if target_index is None:
            target_index = next(
                (i for i, part in enumerate(self.parts_data) if isinstance(part, dict) and part.get('type') == 'skin'),
                None,
            )
        if target_index is not None and 0 <= target_index < len(self.parts_data):
            if not isinstance(self.parts_data[target_index], dict) or self.parts_data[target_index].get('type') != 'skin':
                QtWidgets.QMessageBox.critical(
                    self,
                    self._loc('dialogs', 'error', "Error"),
                    self._loc('dialogs', 'invalid_skin_part', "The selected part is not a skin part."),
                )
                window.close()
                return
            # In-place replacement: dict identity changes, so the existing
            # binding still closes over the OLD skin dict. Re-binding after
            # the swap updates the closure to the new dict — the state token
            # slot / kind stay the same, so no state.tokens mutation needed.
            self.parts_data[target_index] = skin
        else:
            # Append path: skin dict + '|' separator go on the end of
            # parts_data. State needs a matching quoted token (bound to the
            # new skin dict via _bind_token_state_widgets) plus a raw '|'
            # token. skin['raw'] already carries a leading space, so no extra
            # padding is needed between the previous token and the skin.
            self.parts_data.append(skin)
            self.parts_data.append('|')
            self._token_state.insert(
                len(self._token_state.tokens),
                Token(raw=skin['raw'], kind='quoted',
                      value=skin['id'] if isinstance(skin['id'], int) else None),
            )
            self._token_state.insert(
                len(self._token_state.tokens),
                Token(raw=' |', kind='raw'),
            )
        self._bind_token_state_widgets()
        self.regenerate_ui_and_serial()
        log_editor(self.main_app, self._LOG_TAG, f"Weapon skin updated to ID: {new_skin_id}")
        window.close()

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    class MockApp:
        def log(self, m): print(f"[LOG] {m}")
        def handle_add_to_backpack(self, serial, flag): print(f"Adding to backpack: {serial}")
        @property
        def controller(self):
            class MockController:
                yaml_obj = True
                def get_all_items(self): return []
            return MockController()

    mock_app = MockApp()
    main_win = QtWidgets.QWidget()
    main_win.setWindowTitle("QT Weapon Editor Test")
    main_win.setGeometry(100, 100, 1024, 768)
    layout = QtWidgets.QVBoxLayout(main_win)
    editor = QtWeaponEditorTab(mock_app)
    layout.addWidget(editor)
    main_win.show()
    sys.exit(app.exec())
