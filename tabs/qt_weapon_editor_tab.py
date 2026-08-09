from PyQt6 import QtWidgets, QtCore, QtGui
import pandas as pd
import random
import re
import sys
from collections import Counter, defaultdict
from functools import partial

from core import bl4_functions as bl4f
from core import b_encoder
from core import decoder_logic
from core import item_display_resolver
from core import resource_loader
from tabs.qt_catalog_picker import CatalogPicker, ContainedWheelListWidget, ContainedWheelScrollArea, FacetedCatalogPicker


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

class WeaponEditorTab(QtWidgets.QWidget):
    add_to_backpack_requested = QtCore.pyqtSignal(str, str)
    update_item_requested = QtCore.pyqtSignal(dict)
    WEAPON_BROWSER_ROW_HEIGHT = 112
    
    # Colors are keyed by stable raw part types, never translated display text.
    PART_TYPE_COLORS = {
        "Barrel": "#B0BEC5",
        "Barrel Accessory": "#90A4AE",
        "Body": "#BCAAA4",
        "Body Accessory": "#A1887F",
        "Body Mechanism": "#8D6E63",
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
        "Body": "body", "Body Accessory": "body_accessory", "Body Mechanism": "body_mechanism",
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

    GENERATION_GROUP_TYPES = {
        "barrel": "Barrel", "barrel_acc": "Barrel Accessory",
        "body": "Body", "body_acc": "Body Accessory", "body_bolt": "Body Mechanism",
        "body_ele": "Special Element Set", "body_mag": "Manufacturer Part",
        "endgame": "Stat Modifier", "firmware": "Stat Modifier",
        "foregrip": "Foregrip", "grip": "Grip",
        "hyperion_secondary_acc": "Manufacturer Part",
        "magazine": "Magazine", "magazine_acc": "Magazine Accessory",
        "magazine_borg": "Borg Magazine Adapter",
        "magazine_ted_thrown": "Tediore Throw Reload",
        "pearl_elem": "Pearl Elements", "pearl_stat": "Pearl Stat",
        "scope": "Scope", "scope_acc": "Scope Accessory",
        "secondary_ammo": "Manufacturer Part",
        "secondary_ele": "Underbarrel Element Switch",
        "tediore_acc": "Tediore Payload",
        "tediore_secondary_acc": "Manufacturer Part",
        "underbarrel": "Underbarrel", "underbarrel_acc": "Underbarrel Accessory",
        "underbarrel_acc_vis": "Underbarrel Accessory",
    }

    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app
        self.selected_weapon_path = None
        self.parts_data = []
        self.rarity_part = None
        
        self.all_weapon_parts_df = None
        self.elemental_df = None
        self.skin_df = None
        self.weapon_rarity_df = None
        self.weapon_localization = {}
        
        self.is_handling_change = False
        self.current_lang = 'zh-CN'
        self._weapon_legality_decoded = None
        self._weapon_legality_result = None
        
        # Main layout
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.content_widget = None

        self.load_data(self.current_lang)
        self.create_widgets()

    def load_data(self, lang='zh-CN'):
        loc_file = resource_loader.get_ui_localization_file(lang)
        full_loc = resource_loader.load_json_resource(loc_file) or {}
        self.ui_localization = full_loc.get("weapon_editor_tab", {})
        self.weapon_rule_loc = full_loc.get("weapon_rules", {})
        try:
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
        self.current_lang = lang
        self.load_data(lang)
        
        # Save current state
        current_decoded = self.serial_decoded_entry.text() if hasattr(self, 'serial_decoded_entry') else ""
        current_flag_idx = self.flag_combo.currentIndex() if hasattr(self, 'flag_combo') else 0
        current_weapon_path = self.selected_weapon_path
        
        # Clean up internal state
        self.parts_data = []
        self.rarity_part = None
        self.selected_weapon_path = current_weapon_path
        
        self.create_widgets()
        content_stack = getattr(self.main_app, "content_stack", None)
        if content_stack is None or content_stack.currentWidget() is self:
            self.refresh_backpack_items()
            if hasattr(self.main_app, "_dirty_item_views"):
                self.main_app._dirty_item_views.discard("weapon")
        elif hasattr(self.main_app, "_dirty_item_views"):
            self.main_app._dirty_item_views.add("weapon")
        
        # Restore state
        if hasattr(self, 'flag_combo') and self.flag_combo.count() > current_flag_idx:
            self.flag_combo.setCurrentIndex(current_flag_idx)
            
        # If there was data loaded, reload it to refresh text
        if current_decoded:
             self.serial_decoded_entry.setText(current_decoded) # Set text first so it's available if parse fails
             self.parse_and_display_weapon(current_decoded)

    def create_widgets(self):
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

        bp_frame = QtWidgets.QFrame(); bp_frame.setObjectName("InnerFrame")
        bp_frame.setMinimumWidth(280)
        bp_layout = QtWidgets.QVBoxLayout(bp_frame)
        bp_layout.addWidget(QtWidgets.QLabel(self.get_localized_string("load_from_backpack")))
        self.weapon_search = QtWidgets.QLineEdit()
        self.weapon_search.setClearButtonEnabled(True)
        self.weapon_search.setPlaceholderText(self._loc('labels', 'search_weapon_placeholder', "Search name, manufacturer, type, level, or slot"))
        self.weapon_search.textChanged.connect(self._filter_backpack_items)
        bp_layout.addWidget(self.weapon_search)
        self.backpack_items_list = ContainedWheelListWidget()
        self.backpack_items_list.setObjectName("weaponBrowser")
        self.backpack_items_list.setMinimumHeight(220)
        self.backpack_items_list.setUniformItemSizes(True)
        self.backpack_items_list.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.backpack_items_list.verticalScrollBar().setSingleStep(20)
        self.backpack_items_list.itemActivated.connect(lambda item: self.load_weapon_data(item.data(QtCore.Qt.ItemDataRole.UserRole)))
        self.backpack_items_list.itemClicked.connect(lambda item: self.load_weapon_data(item.data(QtCore.Qt.ItemDataRole.UserRole)))
        self.backpack_items_list.currentItemChanged.connect(self._sync_weapon_browser_selection)
        bp_layout.addWidget(self.backpack_items_list, 1)
        self.selected_weapon_summary = QtWidgets.QLabel()
        self.selected_weapon_summary.setObjectName("selectedWeaponSummary")
        self.selected_weapon_summary.setWordWrap(True)
        self._update_selected_weapon_summary()
        bp_layout.addWidget(self.selected_weapon_summary)
        splitter.addWidget(bp_frame)
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
        parts_title_layout = QtWidgets.QHBoxLayout()
        parts_title_layout.setContentsMargins(0, 0, 0, 0)
        parts_title_layout.addWidget(QtWidgets.QLabel(self.get_localized_string("weapon_parts")))
        self.weapon_legality_badge = QtWidgets.QLabel("Unknown")
        self.weapon_legality_badge.setObjectName("multiBadge")
        self.weapon_legality_badge.setSizePolicy(QtWidgets.QSizePolicy.Policy.Maximum, QtWidgets.QSizePolicy.Policy.Fixed)
        self.weapon_legality_badge.setToolTip("No decoded weapon loaded.")
        parts_title_layout.addWidget(self.weapon_legality_badge)
        parts_title_layout.addStretch(1)
        parts_header_layout.addLayout(parts_title_layout, 0, 0)
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
        if self.is_handling_change or not self.serial_b85_entry.hasFocus():
            return

        self.is_handling_change = True
        if not text:
            self.clear_all_fields()
            self.is_handling_change = False
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
        self.is_handling_change = False

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

    def _parse_component_string(self, component_str):
        components, last_index = [], 0
        for match in re.finditer(r'\{(\d+)(?::(\d+|\[[\d\s]+\]))?\}|\"c\",\s*(?:(\d+)|\"([^\"]+)\")', component_str):
            components.append(component_str[last_index:match.start()])
            part_data = {'raw': match.group(0)}
            if match.group(3): part_data.update({'type': 'skin', 'id': int(match.group(3))})
            elif match.group(4): part_data.update({'type': 'skin', 'id': match.group(4)})
            else:
                outer_id, inner = int(match.group(1)), match.group(2)
                if inner: part_data.update({'type': 'group', 'id': outer_id, 'sub_ids': [int(sid) for sid in inner.strip('[]').split()]} if '[' in inner else {'type': 'elemental', 'id': outer_id, 'sub_id': int(inner)})
                else: part_data.update({'type': 'simple', 'id': outer_id})
            components.append(part_data); last_index = match.end()
        components.append(component_str[last_index:])
        return [c for c in components if c]

    def clear_all_fields(self, clear_b85=True):
        self.is_handling_change = True
        if clear_b85: self.serial_b85_entry.clear()
        self.serial_decoded_entry.clear(); self.manufacturer_entry.clear(); self.item_type_entry.clear()
        self.rarity_combo.setCurrentIndex(-1); self.level_entry.clear(); self.seed_entry.clear()
        self.weapon_name_label.setText(self.weapon_name_label_str)
        self._update_weapon_stats("")

        self._set_parts_placeholder(self.get_localized_string("parse_serial_to_show_parts"))
        self.serial_b85_entry.setReadOnly(False); self.update_weapon_btn.setEnabled(False)
        self.selected_weapon_path, self.parts_data, self.rarity_part = None, [], None
        self._select_current_backpack_item()
        self._update_selected_weapon_summary()
        self.is_handling_change = False

    def update_decoded_from_ui(self):
        if self.is_handling_change: return
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
        except Exception as e: self.main_app.log(f"Error in update_decoded_from_ui: {e}")

    def randomize_seed(self): self.seed_entry.setText(str(random.randint(100, 9999)))
    def load_weapon_data(self, weapon_data):
        if not weapon_data:
            return
        self.main_app.log(f"Loading weapon: {weapon_data.get('name')}")
        self.selected_weapon_path = weapon_data.get("original_path")
        self._select_current_backpack_item()
        self._update_selected_weapon_summary(weapon_data)
        self.is_handling_change = True
        self.serial_b85_entry.setText(weapon_data.get('serial', ''))
        decoded_str = weapon_data.get('decoded_full', '')
        self.serial_decoded_entry.setText(decoded_str)
        self.is_handling_change = False
        if not decoded_str:
            QtWidgets.QMessageBox.critical(self, self.get_localized_string("error"), self.get_localized_string("no_valid_decoded_data")); return
        self.parse_and_display_weapon(decoded_str)
        self.serial_b85_entry.setReadOnly(True); self.update_weapon_btn.setEnabled(True)

    def parse_and_display_weapon(self, decoded_str):
        try:
            header = bl4f.parse_decoded_item_header(decoded_str)
            if not header:
                raise ValueError("Invalid decoded item header")
            m_id, level = header["mfg_id"], header["level"]
            component_part = header["component"]
            m_info = self.all_weapon_parts_df[self.all_weapon_parts_df['Manufacturer & Weapon Type ID'] == m_id].iloc[0]
            self.is_handling_change = True
            self.manufacturer_entry.setText(self.get_localized_string(m_info['Manufacturer']))
            self.item_type_entry.setText(self.get_localized_string(m_info['Weapon Type']))
            self.level_entry.setText(str(level))
            self.seed_entry.setText(str(header["seed"]) if header["seed"] is not None else "")
            
            temp_parts = self._parse_component_string(component_part)
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
            self.is_handling_change = False
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, self.get_localized_string("parse_error"), f"{self.get_localized_string('parse_weapon_error')}: {e}")
            self.main_app.log(f"Error parsing weapon: {e}"); self.clear_all_fields()

    def _update_weapon_stats(self, decoded_str):
        if hasattr(self, 'weapon_stat_value_labels'):
            stats = item_display_resolver.resolve_weapon_stats(decoded_str) if decoded_str else {}
            for key, label in self.weapon_stat_value_labels.items():
                label.setText(item_display_resolver.format_weapon_stat(key, stats.get(key), self.current_lang) or "—")
        self._update_weapon_legality(decoded_str)

    def _rule_message(self, key, zh, en, **fmt):
        fallback = zh if self.current_lang == 'zh-CN' else en
        text = self.weapon_rule_loc.get(key, fallback)
        return text.format(**fmt) if fmt else text

    def _generation_group_text(self, group):
        raw = self.GENERATION_GROUP_TYPES.get(str(group).casefold())
        return self.get_localized_string(raw, raw) if raw else str(group).replace('_', ' ').title()

    def _generation_ref_text(self, ref, group=""):
        root, sep, part_id = str(ref).partition(':')
        name = item_display_resolver.weapon_part_name(int(root), part_id, self.current_lang) if sep and root.isdigit() else ""
        return name or f"{self._generation_group_text(group)} [{ref}]"

    def _generation_ref_list(self, refs, group="", limit=2):
        values = list(dict.fromkeys(map(str, refs or [])))
        text = self._rule_message("list_separator", '、', ', ').join(
            self._generation_ref_text(ref, group) for ref in values[:limit]
        )
        if len(values) > limit:
            text += self._rule_message(
                "more_items", "，另{count}个", " +{count}",
                count=len(values) - limit,
            )
        return text

    @staticmethod
    def _generation_group_for_ref(result, ref):
        for group, rule in (result.get("groups") or {}).items():
            if ref in set(rule.get("allowed") or []) | set(rule.get("selected") or []):
                return group
        return ""

    def _legality_violation_text(self, violation, result):
        code = str(violation.get("code") or "unknown")
        group = str(violation.get("group") or "")
        group_text = self._generation_group_text(group) if group else ""
        actual = violation.get("actual", violation.get("count"))

        if code == "count_above":
            return self._rule_message(
                "too_many_group", "{group}过多（{actual}/{max}）", "Too many {group} ({actual}/{max})",
                group=group_text, actual=actual, max=violation.get("max"), suffix="",
            )
        if code == "count_below":
            eligible = (result.get("groups", {}).get(group) or {}).get("remaining_eligible_refs", [])
            choices = self._generation_ref_list(eligible, group)
            suffix = self._rule_message(
                "eligible_suffix", "，可选：{parts}", "; eligible: {parts}", parts=choices,
            ) if choices else ""
            return self._rule_message(
                "missing_group", "缺少{group}（{actual}/{min}）{suffix}",
                "Missing {group} ({actual}/{min}){suffix}",
                group=group_text, actual=actual, min=violation.get("min"), suffix=suffix,
            )
        if code == "tag_count_below":
            return self._rule_message(
                "missing_combination", "缺少要求的配件组合（{actual}/{min}）",
                "Missing required part combination ({actual}/{min})",
                actual=actual, min=violation.get("min"),
            )
        if code == "duplicate_part":
            counts = Counter(result.get("selected_part_refs") or [])
            refs = violation.get("parts") or []
            names = self._rule_message("list_separator", '、', ', ').join(
                f"{self._generation_ref_text(ref, self._generation_group_for_ref(result, ref))} ×{counts.get(ref, 2)}"
                for ref in refs[:2]
            )
            return self._rule_message("duplicate_part", "重复配件：{parts}", "Duplicate part: {parts}", parts=names)
        if code == "part_not_allowed":
            names = self._generation_ref_list(violation.get("parts") or [], group)
            return self._rule_message(
                "not_allowed", "当前组合不允许：{parts}", "Not allowed by this composition: {parts}", parts=names,
            )
        if code == "foreign_root_part":
            name = self._generation_ref_text(violation.get("part", ""))
            # Distinguish another brand of the same item type from another item
            # type entirely; "another weapon" is wrong for both on gear.
            foreign_kind = str(violation.get("foreign_kind") or "")
            other = item_display_resolver.root_kind_label(
                str(violation.get("part", "")).partition(":")[0], self.current_lang
            )
            own_root = str(result.get("root_ref") or "")
            own = item_display_resolver.root_kind_label(own_root, self.current_lang) if own_root else ""
            if foreign_kind == "manufacturer":
                return self._rule_message(
                    "foreign_part_manufacturer",
                    "跨厂商配件（本物品为{own}，配件来自{other}）：{part}",
                    "Cross-manufacturer part (this item is {own}, part is from {other}): {part}",
                    own=own, other=other, part=name,
                )
            if foreign_kind == "type":
                return self._rule_message(
                    "foreign_part_type",
                    "跨类型配件（本物品为{own}，配件来自{other}）：{part}",
                    "Cross-type part (this item is {own}, part is from {other}): {part}",
                    own=own, other=other, part=name,
                )
            return self._rule_message("foreign_part", "跨来源配件：{part}", "Part from another item: {part}", part=name)
        if code == "forced_part_missing":
            names = self._generation_ref_list(violation.get("parts") or [])
            return self._rule_message(
                "missing_intrinsic", "缺少固有配件：{parts}", "Missing intrinsic part: {parts}", parts=names,
            )
        if code == "missing_required_tag":
            part = self._generation_ref_text(violation.get("part", ""), group)
            required = set(map(str, violation.get("tags") or []))
            providers = []
            for rule in result.get("groups", {}).values():
                for ref in rule.get("allowed", []):
                    root, sep, part_id = str(ref).partition(':')
                    if sep and root.isdigit() and required.intersection(
                        item_display_resolver.weapon_part_selection_tags(int(root), part_id).get("adds", [])
                    ):
                        providers.append(ref)
            choices = self._generation_ref_list(providers)
            if choices:
                return self._rule_message("requires", "{part}缺少前置：{parts}", "{part} requires {parts}", part=part, parts=choices)
            return self._rule_message(
                "unmet_dependency", "{part}的前置条件未满足", "{part} has an unmet dependency", part=part,
            )
        if code == "excluded_tag_conflict":
            refs = violation.get("parts") or ([violation.get("part")] if violation.get("part") else [])
            names = self._generation_ref_list(refs)
            return self._rule_message(
                "conflicting_parts", "配件搭配互斥：{parts}", "Conflicting parts: {parts}", parts=names,
            )
        if code == "tag_limit":
            bucket = set(map(str, violation.get("tags") or []))
            contributors = []
            for ref in result.get("selected_part_refs") or []:
                root, sep, part_id = str(ref).partition(':')
                if sep and root.isdigit() and bucket.intersection(
                    item_display_resolver.weapon_part_selection_tags(int(root), part_id).get("adds", [])
                ):
                    contributors.append(ref)
            names = self._generation_ref_list(contributors)
            suffix = (f"：{names}" if self.current_lang == "zh-CN" else f": {names}") if names else ""
            return self._rule_message(
                "too_many_tagged", "同类授权配件过多（{actual}/{max}）{suffix}",
                "Too many tagged parts ({actual}/{max}){suffix}",
                actual=actual, max=violation.get("max"), suffix=suffix,
            )
        if code == "multiple_compositions":
            names = self._generation_ref_list(violation.get("parts") or [])
            return self._rule_message(
                "multiple_compositions", "同时存在多个武器模板：{parts}", "Multiple compositions: {parts}", parts=names,
            )
        if code in {"conditional_availability"}:
            return self._rule_message(
                "conditional_availability", "仅限特定投放条件", "Available only under special conditions",
            )
        if code in {"selection_order_unchecked"}:
            return self._rule_message(
                "selection_order_unchecked", "配件过多，依赖顺序未完全验证",
                "Too many parts to verify dependency order",
            )
        if code in {
            "invalid_serial", "rules_unavailable", "weapon_rules_missing", "unknown_composition",
            "unknown_part", "unresolved_rule_parts", "inheritance_cycle", "validation_failed",
        }:
            return self._rule_message(
                "cannot_validate", "无法验证：生成规则未覆盖", "Cannot validate: generation rules are incomplete",
            )
        return code.replace('_', ' ').title()

    def _legality_reason_lines(self, result):
        priority = {
            "foreign_root_part": 0, "part_not_allowed": 1, "multiple_compositions": 1,
            "duplicate_part": 2, "count_above": 3, "tag_limit": 3,
            "missing_required_tag": 4, "excluded_tag_conflict": 4,
            "count_below": 5, "forced_part_missing": 5, "tag_count_below": 5,
            "conditional_availability": 6,
        }
        ordered = sorted(result.get("violations") or [], key=lambda item: priority.get(item.get("code"), 9))
        return list(dict.fromkeys(self._legality_violation_text(item, result) for item in ordered))

    def _update_weapon_legality(self, decoded_str, force=False):
        badge = getattr(self, "weapon_legality_badge", None)
        if badge is None:
            return
        decoded = (decoded_str or "").strip()
        if not decoded:
            result = {"status": "unknown", "violations": []}
            self._weapon_legality_decoded, self._weapon_legality_result = "", result
        elif force or decoded != self._weapon_legality_decoded:
            try:
                result = item_display_resolver.validate_weapon_generation(decoded, allow_incomplete=True)
            except Exception as exc:
                result = {"status": "unknown", "violations": [{"code": "validation_failed", "part": str(exc)}]}
                self.main_app.log(f"Weapon legality validation failed: {exc}")
            self._weapon_legality_decoded, self._weapon_legality_result = decoded, result
        else:
            result = self._weapon_legality_result or {"status": "unknown", "violations": []}

        status = str(result.get("status") or "unknown").casefold()
        labels = {
            "legal": ("status_legal", "自然生成", "Natural"),
            "conditional": ("status_conditional", "条件限定", "Conditional"),
            "incomplete": ("status_incomplete", "待补全", "Incomplete"),
            "modified": ("status_modified", "魔改", "Modified"),
            "unknown": ("status_unknown", "无法验证", "Unknown"),
        }
        label = self._rule_message(*labels.get(status, labels["unknown"]))
        reasons = self._legality_reason_lines(result)
        short = reasons[0] if reasons else ""
        if len(short) > 36:
            short = short[:35] + '…'
        tooltip = [label]
        tooltip.extend(f"• {line}" for line in reasons)
        if not reasons:
            tooltip.append(self._rule_message(
                "matches_rules" if status == "legal" else "no_weapon",
                "符合当前自然生成规则" if status == "legal" else "尚未载入可验证武器",
                "Matches the current generation rules" if status == "legal" else "No verifiable weapon loaded",
            ))
        badge.setText(f"{label} · {short}" if short else label)
        badge.setToolTip("\n".join(tooltip))
        badge.setAccessibleName(label)

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
        ordered_parts = [self.parts_data[index] for index in order]
        for slot, part in zip(slots, ordered_parts):
            self.parts_data[slot] = part
        self.regenerate_ui_and_serial()
        self._select_part_row(moved_id)

    def _current_manufacturer_id(self):
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
        self.parts_data[index], self.parts_data[target] = self.parts_data[target], self.parts_data[index]
        self.regenerate_ui_and_serial()
        self._select_part_row(moved_id)

    def delete_part(self, index):
        if 0 <= index < len(self.parts_data):
            self.parts_data.pop(index); self.regenerate_ui_and_serial()

    def regenerate_ui_and_serial(self):
        current_decoded = self.serial_decoded_entry.text()
        if '||' not in current_decoded: return
        header_part, _ = current_decoded.split('||', 1)
        try: m_id = int(header_part.strip().split('|')[0].strip().split(',')[0])
        except (ValueError, IndexError): return
        new_component_list = ([self.rarity_part['raw']] if self.rarity_part else []) + [p['raw'] if isinstance(p, dict) else p for p in self.parts_data]
        new_component_str = re.sub(r'\s{2,}', ' ', " ".join(new_component_list).strip())
        self.serial_decoded_entry.setText(f"{header_part.strip()}|| {new_component_str}")
        self.display_parts(m_id)

    def force_refresh_parts(self):
        if not (decoded_str := self.serial_decoded_entry.text()):
            QtWidgets.QMessageBox.warning(self, self.get_localized_string("no_input"), self.get_localized_string("serial_empty")); return
        self._weapon_legality_decoded = None
        self.main_app.log("Forcing parts list refresh..."); self.parse_and_display_weapon(decoded_str)
        QtWidgets.QMessageBox.information(self, self.get_localized_string("success"), self.get_localized_string("parts_refresh_success"))

    def _weapon_browser_row(self, title, detail, decoded_str):
        row = QtWidgets.QWidget()
        row.setObjectName("WeaponBrowserRow")
        row.setFixedHeight(self.WEAPON_BROWSER_ROW_HEIGHT)
        row_layout = QtWidgets.QVBoxLayout(row)
        row_layout.setContentsMargins(10, 7, 10, 7)
        row_layout.setSpacing(5)

        name_label = QtWidgets.QLabel(title)
        name_label.setObjectName("WeaponBrowserName")
        name_label.setToolTip(title)
        name_label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.NoTextInteraction)
        detail_label = QtWidgets.QLabel(detail)
        detail_label.setObjectName("WeaponBrowserMeta")
        detail_label.setToolTip(detail)
        row_layout.addWidget(name_label)
        row_layout.addWidget(detail_label)

        stats = item_display_resolver.resolve_weapon_stats(decoded_str) if decoded_str else {}
        stat_titles = self.ui_localization.get('stats', {})
        stats_layout = QtWidgets.QGridLayout()
        stats_layout.setContentsMargins(0, 2, 0, 0)
        stats_layout.setHorizontalSpacing(4)
        stats_layout.setVerticalSpacing(1)
        for column, key in enumerate(("damage", "accuracy", "fire_rate", "reload_time", "magazine")):
            title_label = QtWidgets.QLabel(stat_titles.get(key, key.replace('_', ' ').title()))
            title_label.setObjectName("WeaponBrowserStatTitle")
            title_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            title_label.setWordWrap(True)
            value = item_display_resolver.format_weapon_stat(key, stats.get(key), self.current_lang) or "—"
            value_label = QtWidgets.QLabel(value)
            value_label.setObjectName("WeaponBrowserStatValue")
            value_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            stats_layout.addWidget(title_label, 0, column)
            stats_layout.addWidget(value_label, 1, column)
            stats_layout.setColumnStretch(column, 1)
        row_layout.addLayout(stats_layout)
        return row

    def _sync_weapon_browser_selection(self, current, previous):
        self._set_row_selected(self.backpack_items_list, previous, False)
        self._set_row_selected(self.backpack_items_list, current, True)

    def refresh_backpack_items(self, items=None):
        self.backpack_items_list.clear()
        if items is None and hasattr(self.main_app, "get_items_snapshot"):
            items = self.main_app.get_items_snapshot()
        elif items is None:
            items = self.main_app.controller.get_all_items()
        if self.main_app.controller.yaml_obj is None or not items:
            self.backpack_items_list.addItem(self.get_localized_string("decrypt_save_to_show_weapons"))
            self.backpack_items_list.setEnabled(False)
            return
        
        weapon_types = {"Pistol", "Shotgun", "SMG", "Assault Rifle", "Sniper"}
        filtered = [i for i in items if i.get("type_en") in weapon_types and "Backpack" in i.get("container", "")]
        if not filtered:
            self.backpack_items_list.addItem(self.get_localized_string("no_weapons_in_backpack"))
            self.backpack_items_list.setEnabled(False)
            return

        self.backpack_items_list.setEnabled(True)

        for weapon in filtered:
            try:
                header, component = weapon.get('decoded_full', '').split('||', 1)
                m_id = int(header.strip().split('|')[0].strip().split(',')[0])
                parsed_components = self._parse_component_string(component)
                _, name, _, _ = self._get_rarity_and_weapon_name(parsed_components, m_id, weapon.get('decoded_full', ''))
                w_name = self.get_localized_string(name, name)
                unknown = self._loc('parts', 'unknown', "Unknown")
                manufacturer = weapon.get('manufacturer') or unknown
                weapon_type = weapon.get('type') or self._loc('parts', 'unknown_item', "Unknown Item")
                unknown_names = {"N/A", "Unknown", "未知", "Неизвестно", "Невідомо", unknown}
                disp_name = f"{manufacturer} {weapon_type} ({w_name})" if w_name not in unknown_names else f"{manufacturer} {weapon_type}"
                detail = f"{self.get_localized_string('level_label')} {weapon.get('level', 'N/A')}  ·  {self.get_localized_string('slot_label')} {weapon.get('slot', 'N/A').replace('slot_', '')}"
                item = QtWidgets.QListWidgetItem()
                item.setData(QtCore.Qt.ItemDataRole.UserRole, weapon)
                item.setData(QtCore.Qt.ItemDataRole.UserRole + 1, f"{weapon.get('name', '')} {disp_name} {detail}".lower())
                item.setToolTip(f"{disp_name} · {detail}")
                row_widget = self._weapon_browser_row(disp_name, detail, weapon.get('decoded_full', ''))
                item.setSizeHint(QtCore.QSize(0, self.WEAPON_BROWSER_ROW_HEIGHT))
                self.backpack_items_list.addItem(item)
                self.backpack_items_list.setItemWidget(item, row_widget)

            except Exception as e:
                self.main_app.log(f"Weapon browser item failed: serial={weapon.get('serial', 'unknown')}, error={e}")
        self._filter_backpack_items(self.weapon_search.text())
        self._select_current_backpack_item()

    def _filter_backpack_items(self, query):
        query = query.strip().lower()
        for row in range(self.backpack_items_list.count()):
            item = self.backpack_items_list.item(row)
            search_text = item.data(QtCore.Qt.ItemDataRole.UserRole + 1) or item.text().lower()
            item.setHidden(bool(query and query not in search_text))

    def _select_current_backpack_item(self):
        if not hasattr(self, "backpack_items_list"):
            return
        self.backpack_items_list.clearSelection()
        for row in range(self.backpack_items_list.count()):
            item = self.backpack_items_list.item(row)
            weapon = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if weapon and weapon.get("original_path") == self.selected_weapon_path:
                self.backpack_items_list.setCurrentItem(item)
                self.backpack_items_list.scrollToItem(item, QtWidgets.QAbstractItemView.ScrollHint.PositionAtCenter)
                return

    def _update_selected_weapon_summary(self, weapon=None):
        if not hasattr(self, "selected_weapon_summary"):
            return
        if weapon is None and hasattr(self, "backpack_items_list"):
            for row in range(self.backpack_items_list.count()):
                candidate = self.backpack_items_list.item(row).data(QtCore.Qt.ItemDataRole.UserRole)
                if candidate and candidate.get("original_path") == self.selected_weapon_path:
                    weapon = candidate
                    break
        if not weapon:
            self.selected_weapon_summary.setText(self._loc('summary', 'none_selected', "No backpack weapon selected"))
            return
        name = weapon.get("name") or weapon.get("manufacturer") or self._loc('summary', 'fallback_name', "Weapon")
        self.selected_weapon_summary.setText(
            self._loc('summary', 'selected', "Selected · {name} · Lv.{level}", name=name, level=weapon.get('level', 'N/A'))
        )

    def update_weapon(self):
        if not self.selected_weapon_path:
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
            'item_path': self.selected_weapon_path,
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
        win.setMinimumSize(1280, 760)
        win.resize(1540, 900)
        win.setModal(True)

        layout = QtWidgets.QVBoxLayout(win)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        header_label = QtWidgets.QLabel(self.get_localized_string("select_parts_to_add"))
        header_label.setObjectName("addPartDialogHeader")
        layout.addWidget(header_label)

        picker = FacetedCatalogPicker(
            stackable=True,
            search_placeholder=self._loc('catalog', 'search_part', "Search part name, effect, manufacturer, or type"),
            avail_title=self._loc('catalog', 'available_parts_hint', "Available Parts (click to preview, double-click to add)"),
            selected_title=self._loc('catalog', 'selected_parts', "Selected Parts"),
            clear_text=self._loc('catalog', 'clear', "Clear"),
            result_text=self._loc('catalog', 'result_count', "{n} / {total}"),
        )
        source, part_types, manufacturers, weapon_types, part_type_hints = self._add_part_catalog_items()
        picker.set_facets([
            (self._loc('catalog', 'facet_part_type', "Part Type"),
             [("all", self._loc('catalog', 'all', "All")),
              *[(value, (
                  f"[{part_type_hints[value]}] {self.get_localized_string(value)}"
                  if value in part_type_hints else self.get_localized_string(value)
              )) for value in part_types]], 7),
            (self._loc('catalog', 'facet_manufacturer', "Manufacturer"),
             [("all", self._loc('catalog', 'all_manufacturers', "All Manufacturers")),
              *[(value, self.get_localized_string(value)) for value in manufacturers]], 6),
            (self._loc('catalog', 'facet_weapon_type', "Weapon Type"),
             [("all", self._loc('catalog', 'all_weapon_types', "All Weapon Types")),
              *[(value, self.get_localized_string(value)) for value in weapon_types]], 5),
        ])
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
            id_label = f"ID {part_id}"
            display_name = name or part_type
            label = f"{detail or display_name}  [{metadata}] [{id_label}]"
            source.append({
                "key": f"normal:{item_id}:{part_id}", "label": label, "category": part_type,
                "subcategory": manufacturer, "tertiary": weapon_type,
                "title": f"[{id_label}] {display_name}", "detail": description,
                "badges": [self.get_localized_string(manufacturer),
                           self.get_localized_string(weapon_type),
                           self.get_localized_string(part_type)],
                "search_text": metadata,
                "_rule_ref": f"{item_id}:{part_id}",
                "data": {"id": part_id, "mfg_id": item_id, "type": "normal"},
            })

        for _, row in self.elemental_df.iterrows():
            element_id, part_id = int(row['Elemental_ID']), int(row['Part_ID'])
            name = str(row[self.elemental_stat_col])
            part_type = self._elemental_part_type(row)
            stat_text = str(row['Stat'])
            metadata = " / ".join((self.get_localized_string(elemental_type),
                                   self.get_localized_string(part_type)))
            id_label = f"ID {part_id}"
            source.append({
                "key": f"elemental:{element_id}:{part_id}",
                "label": f"{name}  [{metadata}] [{id_label}]", "category": part_type,
                "subcategory": elemental_type, "tertiary": elemental_type,
                "title": f"[{id_label}] {name}", "detail": stat_text,
                "badges": [self.get_localized_string(elemental_type),
                           self.get_localized_string(part_type)],
                "search_text": stat_text,
                "_rule_ref": f"{element_id}:{part_id}",
                "data": {"id": part_id, "mfg_id": element_id, "type": "elemental"},
            })
        try:
            context = item_display_resolver.weapon_generation_context(self.serial_decoded_entry.text())
        except Exception:
            context = {}
        self._append_missing_generation_candidates(
            source, context, part_types, manufacturers, weapon_types, level
        )
        return source, part_types, manufacturers, weapon_types, self._apply_generation_candidate_hints(source, context)

    @staticmethod
    def _generation_count_range(minimum, maximum):
        minimum, maximum = int(minimum), int(maximum)
        return str(minimum) if minimum == maximum else f"{minimum}–{maximum}"

    def _append_missing_generation_candidates(self, source, context, part_types, manufacturers, weapon_types, level):
        represented = {item.get("_rule_ref") for item in source}
        for group, rule in (context.get("groups") or {}).items():
            for ref in rule.get("allowed", []):
                if ref in represented:
                    continue
                root, sep, part_id = str(ref).partition(':')
                if not sep or not root.isdigit() or not part_id.isdigit():
                    continue
                item_id = int(root)
                part_type = self.GENERATION_GROUP_TYPES.get(group, group.replace('_', ' ').title())
                if item_id == 1:
                    manufacturer = weapon_type = "Elemental"
                    data_type = "elemental"
                else:
                    rows = self.all_weapon_parts_df[
                        self.all_weapon_parts_df['Manufacturer & Weapon Type ID'] == item_id
                    ]
                    if rows.empty:
                        continue
                    manufacturer = str(rows.iloc[0]['Manufacturer'])
                    weapon_type = str(rows.iloc[0]['Weapon Type'])
                    data_type = "normal"
                name = item_display_resolver.weapon_part_name(item_id, part_id, self.current_lang)
                preview_serial = f"{item_id}, 0, 1, {level}| 2, 0|| |"
                description = item_display_resolver.format_weapon_part_description(
                    item_id, part_id, preview_serial, self.current_lang, part_type
                )
                detail = " · ".join(filter(None, (name, description)))
                metadata = " / ".join(
                    self.get_localized_string(value) for value in (manufacturer, weapon_type, part_type)
                )
                id_label = f"ID {part_id}"
                display_name = name or part_type
                source.append({
                    "key": f"{data_type}:{item_id}:{part_id}",
                    "label": f"{detail or display_name}  [{metadata}] [{id_label}]",
                    "category": part_type,
                    "subcategory": manufacturer,
                    "tertiary": weapon_type,
                    "title": f"[{id_label}] {display_name}",
                    "detail": description,
                    "badges": [self.get_localized_string(manufacturer),
                               self.get_localized_string(weapon_type),
                               self.get_localized_string(part_type)],
                    "search_text": metadata,
                    "_rule_ref": ref,
                    "data": {"id": part_id, "mfg_id": item_id, "type": data_type},
                })
                represented.add(ref)
                if part_type not in part_types:
                    part_types.append(part_type)
                if manufacturer not in manufacturers:
                    manufacturers.append(manufacturer)
                if weapon_type not in weapon_types:
                    weapon_types.append(weapon_type)

    def _generation_candidate_condition_text(self, ref, group, context):
        if ref in set((context.get("groups", {}).get(group) or {}).get("tag_limited_refs") or []):
            return self._rule_message(
                "violation_tag_limit", "授权类配件超过上限", "Tagged part count exceeds the limit",
            )
        root, sep, part_id = str(ref).partition(':')
        if not sep or not root.isdigit():
            return ""
        candidate_tags = item_display_resolver.weapon_part_selection_tags(int(root), part_id)
        required = set(candidate_tags.get("requires", []))
        excluded = set(candidate_tags.get("excludes", []))
        ordered_groups = list(dict.fromkeys(map(str, context.get("part_types") or [])))
        ordered_groups.extend(g for g in context.get("groups", {}) if g not in ordered_groups)
        active = set(map(str, context.get("base_tags") or []))
        prior_groups = []
        for current_group in ordered_groups:
            if current_group == group:
                break
            prior_groups.append(current_group)
            for selected_ref in (context.get("groups", {}).get(current_group) or {}).get("selected", []):
                selected_root, selected_sep, selected_id = str(selected_ref).partition(':')
                if selected_sep and selected_root.isdigit():
                    active.update(item_display_resolver.weapon_part_selection_tags(
                        int(selected_root), selected_id
                    ).get("adds", []))

        missing = required - active
        conflicts = excluded & active
        providers = []
        conflicting_parts = []
        for current_group in prior_groups:
            rule = context.get("groups", {}).get(current_group) or {}
            for candidate_ref in rule.get("eligible_refs", []):
                candidate_root, candidate_sep, candidate_id = str(candidate_ref).partition(':')
                if candidate_sep and candidate_root.isdigit() and missing.intersection(
                    item_display_resolver.weapon_part_selection_tags(int(candidate_root), candidate_id).get("adds", [])
                ):
                    providers.append((candidate_ref, current_group))
            for selected_ref in rule.get("selected", []):
                selected_root, selected_sep, selected_id = str(selected_ref).partition(':')
                if selected_sep and selected_root.isdigit() and conflicts.intersection(
                    item_display_resolver.weapon_part_selection_tags(int(selected_root), selected_id).get("adds", [])
                ):
                    conflicting_parts.append((selected_ref, current_group))

        if not missing and not conflicts:
            conflicting_parts.extend(
                (selected_ref, group)
                for selected_ref in (context.get("groups", {}).get(group) or {}).get("selected", [])
                if selected_ref != ref
            )

        details = []
        if missing:
            choices = self._rule_message("list_separator", '、', ', ').join(
                self._generation_ref_text(candidate_ref, candidate_group)
                for candidate_ref, candidate_group in list(dict.fromkeys(providers))[:2]
            )
            details.append(self._rule_message(
                "requires_first" if choices else "no_prerequisite",
                "需要先选择：{parts}" if choices else "缺少可用的前置配件",
                "Requires first: {parts}" if choices else "No eligible prerequisite part is currently available",
                **({"parts": choices} if choices else {}),
            ))
        if conflicts or conflicting_parts:
            names = self._rule_message("list_separator", '、', ', ').join(
                self._generation_ref_text(selected_ref, selected_group)
                for selected_ref, selected_group in list(dict.fromkeys(conflicting_parts))[:2]
            )
            details.append(self._rule_message(
                "conflicts_selected" if names else "conflicts_composition",
                "与当前已选配件互斥：{parts}" if names else "与当前武器模板互斥",
                "Conflicts with selected part: {parts}" if names else "Conflicts with the current composition",
                **({"parts": names} if names else {}),
            ))
        return self._rule_message("semicolon", '；', '; ').join(details)

    def _apply_generation_candidate_hints(self, source, context):
        rules_ready = bool(context.get("rules_available") and context.get("composition_ref"))
        selected_counts = Counter(context.get("selected_part_refs") or [])
        ref_rules = {}
        for group, rule in (context.get("groups") or {}).items():
            for ref in rule.get("allowed", []):
                ref_rules[ref] = (group, rule)

        category_groups = defaultdict(set)
        group_categories = defaultdict(set)
        for item in source:
            ref = item.get("_rule_ref")
            matched = ref_rules.get(ref)
            if not rules_ready:
                item["candidate"] = {
                    "kind": "unknown", "marker": "",
                    "badge": self._rule_message("rules_unknown", "规则未知", "Rules unknown"),
                    "hint": self._rule_message(
                        "rules_unknown_hint",
                        "当前武器没有可识别的稀有度或传奇模板，仍可作为魔改配件添加。",
                        "The current rarity or legendary composition is unknown; the part can still be added.",
                    ),
                }
                continue
            if not matched:
                item["candidate"] = {
                    "kind": "modified", "marker": "◇",
                    "badge": self._rule_message("modified_pairing", "非自然搭配", "Modified pairing"),
                    "hint": self._rule_message(
                        "modified_pairing_hint",
                        "不在当前稀有度或传奇模板的自然生成配件池内；仍可选择作为魔改。",
                        "Outside the natural pool for this composition; it remains selectable as a modified part.",
                    ),
                }
                continue

            group, rule = matched
            item["_rule_group"] = group
            category_groups[item["category"]].add(group)
            group_categories[group].add(item["category"])
            current = len(rule.get("selected") or [])
            minimum = int(rule.get("effective_min", rule.get("min", 1)))
            maximum = int(rule.get("effective_max", rule.get("max", 1)))
            legal_range = self._generation_count_range(minimum, maximum)
            group_text = self._generation_group_text(group)
            progress = f"{current}/{legal_range}"

            if selected_counts.get(ref, 0):
                item["candidate"] = {
                    "kind": "legal", "marker": "✓",
                    "badge": self._rule_message(
                        "legal_existing_badge", "合法配件池 · 已存在 · {progress}",
                        "Natural pool · Already present · {progress}", progress=progress,
                    ),
                    "hint": self._rule_message(
                        "legal_existing_hint",
                        "该配件与当前模板合法，但 {group} 中已经存在它；请先替换/删除，直接再加会成为重复魔改。",
                        "This part is valid for the composition but already exists in {group}; replace/remove it first or adding again creates a duplicate.",
                        group=group_text,
                    ),
                }
            elif current >= maximum:
                item["candidate"] = {
                    "kind": "legal", "marker": "✓",
                    "badge": self._rule_message(
                        "legal_limit_badge", "合法配件池 · 已达上限 · {progress}",
                        "Natural pool · Limit reached · {progress}", progress=progress,
                    ),
                    "hint": self._rule_message(
                        "legal_limit_hint",
                        "该配件与当前模板合法；但 {group} 已有 {current} 个、上限为 {max}。先替换/删除可保持合法，直接添加会成为魔改。",
                        "This part is valid for the composition, but {group} is at {current}/{max}. Replace/remove first to stay natural; direct addition is modified.",
                        group=group_text, current=current, max=maximum,
                    ),
                }
            elif ref not in set(rule.get("eligible_refs") or []):
                condition = self._generation_candidate_condition_text(ref, group, context)
                condition_zh = f"{condition}；" if condition else ""
                condition_en = f" {condition};" if condition else ""
                item["candidate"] = {
                    "kind": "warning", "marker": "!",
                    "badge": self._rule_message(
                        "condition_unmet_badge", "条件未满足 · {progress}", "Condition unmet · {progress}", progress=progress,
                    ),
                    "hint": self._rule_message(
                        "condition_unmet_hint",
                        "该配件属于 {group} 的生成池，但当前条件不满足。{suffix}仍可选择。",
                        "This part belongs to the {group} pool, but its condition is not satisfied.{suffix} It remains selectable.",
                        group=group_text, suffix=condition_zh if self.current_lang == "zh-CN" else condition_en,
                    ),
                }
            else:
                item["candidate"] = {
                    "kind": "legal", "marker": "✓",
                    "badge": self._rule_message(
                        "legal_pairing_badge", "合法搭配 · {progress}", "Natural pairing · {progress}", progress=progress,
                    ),
                    "hint": self._rule_message(
                        "legal_pairing_hint",
                        "当前模板允许该 {group}；现有 {current} 个，自然生成范围为 {range}。",
                        "Allowed by the current composition. Existing: {current}; natural range: {range}.",
                        group=group_text, current=current, range=legal_range,
                    ),
                }

        hints = {
            str(item.get("category")): self._rule_message(
                "current_legal_zero", "当前{current}/合法—", "{current}/—", current=0,
            )
            for item in source if rules_ready and item.get("category")
        }
        groups = context.get("groups") or {}
        for category, native_groups in category_groups.items():
            current = minimum = maximum = 0
            for group in native_groups:
                rule = groups[group]
                current += len(rule.get("selected") or [])
                minimum += int(rule.get("effective_min", rule.get("min", 1)))
                maximum += int(rule.get("effective_max", rule.get("max", 1)))
            legal_range = self._generation_count_range(minimum, maximum)
            shared = any(len(group_categories[group]) > 1 for group in native_groups)
            hints[category] = self._rule_message(
                "shared_current_legal" if shared else "current_legal",
                "共享配额 当前{current}/合法{range}" if shared else "当前{current}/合法{range}",
                "shared {current}/{range}" if shared else "{current}/{range}",
                current=current, range=legal_range,
            )
        return hints

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

        new_part_data = self._parse_component_string(" ".join(new_parts_list))

        # Find the last non-skin part index to insert after
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
        
        self.regenerate_ui_and_serial()
        self.main_app.log(f"Added {len(new_part_data)} new part(s).")
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
            'raw': f'"c", "{new_skin_id}"' if is_text_id else f'"c", {int(new_skin_id)}',
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
            self.parts_data[target_index] = skin
        else:
            self.parts_data.append(skin)
            self.parts_data.append('|')
        self.regenerate_ui_and_serial()
        self.main_app.log(f"Weapon skin updated to ID: {new_skin_id}")
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
    editor = WeaponEditorTab(mock_app)
    layout.addWidget(editor)
    main_win.show()
    sys.exit(app.exec())
