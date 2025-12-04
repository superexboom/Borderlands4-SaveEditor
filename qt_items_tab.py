from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QFormLayout, QTreeView, QSplitter, QComboBox,
    QMessageBox
)
from PyQt6.QtGui import QStandardItemModel, QStandardItem
from PyQt6.QtCore import pyqtSignal, Qt, QModelIndex
from typing import Dict, List, Any, Optional
import resource_loader

class QtItemsTab(QWidget):
    add_item_requested = pyqtSignal(str, str)
    update_item_requested = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_lang = 'zh-CN'
        self._load_localization()
        self.model = QStandardItemModel()
        cols = self.loc['columns']
        self.model.setHorizontalHeaderLabels([cols['name'], cols['type'], cols['slot'], cols['level']])
        self.item_lookup = {}
        self.current_selected_item: Optional[Dict[str, Any]] = None

        self.ui_labels = {}
        self.ui_buttons = {}
        self.ui_groups = {}
        self.ui_placeholders = {}

        main_layout = QVBoxLayout(self)

        # --- Top "Add Item" Bar ---
        self._create_add_item_bar(main_layout)

        # --- Main Content ---
        splitter = QSplitter(Qt.Orientation.Horizontal)
        # Add splitter with a stretch factor of 1 to make it expand vertically
        main_layout.addWidget(splitter, 1)

        # Left Pane: Tree View
        left_pane = QWidget()
        left_layout = QVBoxLayout(left_pane)
        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText(self.loc['search_placeholder'])
        self.search_entry.textChanged.connect(self.filter_tree)
        left_layout.addWidget(self.search_entry)

        self.tree_view = QTreeView()
        self.tree_view.setModel(self.model)
        self.tree_view.selectionModel().selectionChanged.connect(self.on_item_selected)
        left_layout.addWidget(self.tree_view)
        splitter.addWidget(left_pane)

        # Right Pane: Details
        right_pane = QWidget()
        right_layout = QVBoxLayout(right_pane)
        right_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._create_details_pane(right_layout)
        splitter.addWidget(right_pane)
        
        splitter.setSizes([600, 400])

    def _create_add_item_bar(self, layout: QVBoxLayout):
        add_item_frame = QWidget()
        add_item_layout = QHBoxLayout(add_item_frame)
        
        self.ui_labels['label_serial'] = QLabel(self.loc['add_item']['label_serial'])
        add_item_layout.addWidget(self.ui_labels['label_serial'])
        
        self.add_serial_entry = QLineEdit()
        self.add_serial_entry.setPlaceholderText(self.loc['add_item']['placeholder_serial'])
        self.ui_placeholders['add_serial'] = self.add_serial_entry
        add_item_layout.addWidget(self.add_serial_entry)

        self.add_flag_combo = QComboBox()
        self._populate_flags()
        
        self.ui_labels['label_flag'] = QLabel(self.loc['add_item']['label_flag'])
        add_item_layout.addWidget(self.ui_labels['label_flag'])
        add_item_layout.addWidget(self.add_flag_combo)

        self.ui_buttons['button_add'] = QPushButton(self.loc['add_item']['button_add'])
        self.ui_buttons['button_add'].clicked.connect(self._on_add_item_clicked)
        add_item_layout.addWidget(self.ui_buttons['button_add'])
        layout.addWidget(add_item_frame)

    def _populate_flags(self):
        self.add_flag_combo.clear()
        flags = self.loc['add_item']['flags']
        flag_values = [flags["1"], flags["3"], flags["5"], flags["17"], flags["33"], flags["65"], flags["129"]]
        self.add_flag_combo.addItems(flag_values)

    def _create_details_pane(self, layout: QVBoxLayout):
        self.detail_fields: Dict[str, QLineEdit] = {}
        self.summary_labels: Dict[str, QLabel] = {}
        self.summary_title_labels: Dict[str, QLabel] = {}
        self.field_title_labels: Dict[str, QLabel] = {}

        self.ui_groups['group_summary'] = QGroupBox(self.loc['details']['group_summary'])
        summary_layout = QGridLayout(self.ui_groups['group_summary'])
        
        summary_map = {
            "物品": self.loc['details']['item'],
            "容器": self.loc['details']['container'],
            "所在格": self.loc['details']['slot'],
            "厂商": self.loc['details']['manufacturer'],
            "类型": self.loc['details']['type']
        }
        
        summary_keys = ["物品", "容器", "所在格", "厂商", "类型"]
        for i, key in enumerate(summary_keys):
            row, col = divmod(i, 2)
            label = QLabel(f"{summary_map[key]}:")
            self.summary_title_labels[key] = label
            summary_layout.addWidget(label, row, col * 2)
            
            value_label = QLabel("")
            summary_layout.addWidget(value_label, row, col * 2 + 1)
            self.summary_labels[key] = value_label
            
        layout.addWidget(self.ui_groups['group_summary'])

        self.ui_groups['group_fields'] = QGroupBox(self.loc['details']['group_fields'])
        fields_layout = QFormLayout(self.ui_groups['group_fields'])
        
        fields_map = {
            "等级": self.loc['details']['level'],
            "序列": self.loc['details']['serial'],
            "解码ID": self.loc['details']['decoded_id']
        }
        field_keys = ["等级", "序列", "解码ID"]
        for key in field_keys:
            line_edit = QLineEdit()
            if key == "序列":
                line_edit.setReadOnly(True)
            self.detail_fields[key] = line_edit
            
            label = QLabel(f"{fields_map[key]}:")
            self.field_title_labels[key] = label
            fields_layout.addRow(label, line_edit)
            
        layout.addWidget(self.ui_groups['group_fields'])

        self.ui_buttons['button_update'] = QPushButton(self.loc['details']['button_update'])
        self.ui_buttons['button_update'].clicked.connect(self._on_update_item_clicked)
        layout.addWidget(self.ui_buttons['button_update'])

    def update_tree(self, items: List[Dict[str, Any]]):
        self.model.clear()
        cols = self.loc['columns']
        self.model.setHorizontalHeaderLabels([cols['name'], cols['type'], cols['slot'], cols['level']])
        self.item_lookup.clear()
        self.current_selected_item = None
        self._clear_details()

        if not items:
            return

        # 预处理和分组 (容器 -> 类型 -> 物品列表)
        items_by_container = {}
        for i, item in enumerate(items):
            self.item_lookup[i] = item
            
            container_raw = item.get('container')
            if not container_raw:
                container_name = self.loc['defaults']['unknown_container']
            else:
                container_name = self.loc.get('containers', {}).get(container_raw, container_raw)
            
            item_type = item.get('type', self.loc['defaults']['unknown_type'])
            
            if container_name not in items_by_container:
                items_by_container[container_name] = {}
            if item_type not in items_by_container[container_name]:
                items_by_container[container_name][item_type] = []
            
            items_by_container[container_name][item_type].append(item)

        # 填充模型
        root_node = self.model.invisibleRootItem()
        for container_name, types_dict in sorted(items_by_container.items()):
            container_node = QStandardItem(container_name)
            container_node.setEditable(False)
            root_node.appendRow(container_node)

            for item_type, item_list in sorted(types_dict.items()):
                type_node = QStandardItem(f"{item_type} ({len(item_list)})")
                type_node.setEditable(False)
                container_node.appendRow(type_node)

                for item in sorted(item_list, key=lambda x: x.get('name', '')):
                    slot = item.get('slot', '—')
                    container_slot_text = f"{container_name}/{slot}" if slot != '—' else container_name
                    
                    name_item = QStandardItem(item.get("name", ""))
                    name_item.setData(item, Qt.ItemDataRole.UserRole) # 存储完整数据
                    name_item.setEditable(False)
                    
                    type_item = QStandardItem(item.get("type", ""))
                    type_item.setEditable(False)
                    
                    container_slot_item = QStandardItem(container_slot_text)
                    container_slot_item.setEditable(False)
                    
                    level_item = QStandardItem(str(item.get("level", "")))
                    level_item.setEditable(False)

                    type_node.appendRow([name_item, type_item, container_slot_item, level_item])
        
        self.tree_view.expandAll()

        # 默认折叠 "Lost Loot" 和 "Equipped"
        containers_loc = self.loc.get('containers', {})
        collapsed_names = {containers_loc.get('Lost Loot', 'Lost Loot'), 
                           containers_loc.get('Equipped', 'Equipped')}
        
        root = self.model.invisibleRootItem()
        for i in range(root.rowCount()):
            item = root.child(i)
            if item.text() in collapsed_names:
                self.tree_view.collapse(self.model.indexFromItem(item))

        for i in range(self.model.columnCount()):
            self.tree_view.resizeColumnToContents(i)

    def on_item_selected(self, selected, deselected):
        indexes = selected.indexes()
        if not indexes:
            self.current_selected_item = None
            self._clear_details()
            return
        
        index = indexes[0]
        # 向上遍历以查找拥有数据的父项
        parent_index = index
        while parent_index.isValid():
            item_data = self.model.data(parent_index, Qt.ItemDataRole.UserRole)
            if item_data:
                break
            parent_index = parent_index.parent()
        else: # 如果循环完成但未找到数据
             item_data = self.model.data(index, Qt.ItemDataRole.UserRole)

        if not item_data:  # 如果仍然没有数据 (可能选中了容器行)
            self.current_selected_item = None
            self._clear_details()
            return

        self.current_selected_item = item_data
        self.summary_labels["物品"].setText(item_data.get("name", "N/A"))
        
        raw_container = item_data.get("container")
        container_display = self.loc.get('containers', {}).get(raw_container, raw_container) if raw_container else "N/A"
        self.summary_labels["容器"].setText(container_display)
        
        self.summary_labels["所在格"].setText(str(item_data.get("slot", "—")))
        self.summary_labels["厂商"].setText(item_data.get("manufacturer", "N/A"))
        self.summary_labels["类型"].setText(item_data.get("type", "N/A"))

        self.detail_fields["等级"].setText(str(item_data.get("level", "")))
        self.detail_fields["序列"].setText(item_data.get("serial", ""))
        self.detail_fields["解码ID"].setText(item_data.get("decoded_parts", ""))

    def _clear_details(self):
        for label in self.summary_labels.values():
            label.setText("")
        for field in self.detail_fields.values():
            field.setText("")

    def _load_localization(self):
        filename = resource_loader.get_ui_localization_file(self.current_lang)
        data = resource_loader.load_json_resource(filename)
        if data and "items_tab" in data:
            self.loc = data["items_tab"]
        else:
            # Fallback (simplified)
            self.loc = {
                "columns": {"name": "Name", "type": "Type", "slot": "Slot", "level": "Level"},
                "containers": {"Backpack": "Backpack", "Bank": "Bank", "Lost Loot": "Lost Loot", "Equipped": "Equipped"},
                "search_placeholder": "Search...",
                "add_item": {
                    "label_serial": "Serial:", "placeholder_serial": "Enter code...", "label_flag": "Flag:", "button_add": "Add",
                    "flags": {"1": "1", "3": "3", "5": "5", "17": "17", "33": "33", "65": "65", "129": "129"}
                },
                "details": {
                    "group_summary": "Summary", "group_fields": "Fields", "item": "Item", "container": "Container", 
                    "slot": "Slot", "manufacturer": "Mfr", "type": "Type", "level": "Level", "serial": "Serial", 
                    "decoded_id": "Decoded ID", "button_update": "Update"
                },
                "defaults": {"unknown_container": "Unknown", "unknown_type": "Unknown"},
                "dialogs": {
                    "input_error": "Error", "enter_serial": "Enter serial", "no_selection": "No selection", 
                    "select_item": "Select item", "error": "Error", "missing_path": "Missing path",
                    "update_success": "Item updated successfully"
                }
            }

    def update_language(self, lang):
        print(f"DEBUG: Updating language for {self.__class__.__name__} to {lang}...")
        self.current_lang = lang
        self._load_localization()
        
        # Headers
        cols = self.loc['columns']
        self.model.setHorizontalHeaderLabels([cols['name'], cols['type'], cols['slot'], cols['level']])
        
        # Add Item Bar
        self.ui_labels['label_serial'].setText(self.loc['add_item']['label_serial'])
        self.ui_placeholders['add_serial'].setPlaceholderText(self.loc['add_item']['placeholder_serial'])
        self.ui_labels['label_flag'].setText(self.loc['add_item']['label_flag'])
        self.ui_buttons['button_add'].setText(self.loc['add_item']['button_add'])
        self._populate_flags()
        
        # Search
        self.search_entry.setPlaceholderText(self.loc['search_placeholder'])
        
        # Details
        self.ui_groups['group_summary'].setTitle(self.loc['details']['group_summary'])
        self.ui_groups['group_fields'].setTitle(self.loc['details']['group_fields'])
        
        summary_map = {
            "物品": self.loc['details']['item'],
            "容器": self.loc['details']['container'],
            "所在格": self.loc['details']['slot'],
            "厂商": self.loc['details']['manufacturer'],
            "类型": self.loc['details']['type']
        }
        for key, label in self.summary_title_labels.items():
            label.setText(f"{summary_map[key]}:")
            
        fields_map = {
            "等级": self.loc['details']['level'],
            "序列": self.loc['details']['serial'],
            "解码ID": self.loc['details']['decoded_id']
        }
        for key, label in self.field_title_labels.items():
            label.setText(f"{fields_map[key]}:")
            
        self.ui_buttons['button_update'].setText(self.loc['details']['button_update'])
        print(f"DEBUG: Finished updating language for {self.__class__.__name__}.")

    def _on_add_item_clicked(self):
        serial = self.add_serial_entry.text().strip()
        if not serial:
            QMessageBox.warning(self, self.loc['dialogs']['input_error'], self.loc['dialogs']['enter_serial'])
            return
        flag = self.add_flag_combo.currentText().split(" ")[0]
        self.add_item_requested.emit(serial, flag)

    def _on_update_item_clicked(self):
        if not self.current_selected_item:
            QMessageBox.warning(self, self.loc['dialogs']['no_selection'], self.loc['dialogs']['select_item'])
            return

        # 只收集UI上的新数据，将处理逻辑完全交给主窗口
        try:
            level_val = int(self.detail_fields["等级"].text())
        except ValueError:
            level_val = 0 # Default or handle error appropriately

        new_data = {
            "level": level_val,
            "decoded_parts": self.detail_fields["解码ID"].text(),
            # 我们不再从UI发送可能过时的序列号
        }

        # 确保我们有路径和原始数据以供比较
        payload = {
            "item_path": self.current_selected_item.get("original_path"),
            "original_item_data": self.current_selected_item,
            "new_item_data": new_data,
            "success_msg": self.loc['dialogs'].get('update_success', 'Item updated successfully')
        }

        if not payload["item_path"]:
            QMessageBox.critical(self, self.loc['dialogs']['error'], self.loc['dialogs']['missing_path'])
            return

        self.update_item_requested.emit(payload)
    
    def filter_tree(self, text: str):
        query = text.lower()
        root = self.model.invisibleRootItem()

        for i in range(root.rowCount()): # 遍历容器
            container_item = root.child(i)
            container_is_visible = False
            
            for j in range(container_item.rowCount()): # 遍历类型
                type_item = container_item.child(j)
                type_is_visible = False

                for k in range(type_item.rowCount()): # 遍历物品
                    item_name = type_item.child(k, 0).text().lower()
                    item_type_col = type_item.child(k, 1).text().lower()
                    
                    is_match = query in item_name or query in item_type_col
                    self.tree_view.setRowHidden(k, type_item.index(), not is_match)
                    if is_match:
                        type_is_visible = True

                self.tree_view.setRowHidden(j, container_item.index(), not type_is_visible)
                if type_is_visible:
                    container_is_visible = True
            
            self.tree_view.setRowHidden(i, root.index(), not container_is_visible)
