import json
import resource_loader
import os
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QTreeView, QAbstractItemView, QHeaderView, QFileDialog
)
from PyQt6.QtGui import QStandardItemModel, QStandardItem
from PyQt6.QtCore import pyqtSignal, Qt
from typing import List, Dict, Any

class SaveSelectorWidget(QWidget):
    """
    一个用于显示、选择和打开存档文件的欢迎界面。
    """
    # 信号：存档路径，用户ID
    open_save_requested = pyqtSignal(str, str)

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.current_lang = 'zh-CN'
        self.current_save_files = [] # Store for language updates
        self._load_localization()

        # --- Main Layout ---
        layout = QVBoxLayout(self)
        
        # --- Top Toolbar ---
        toolbar_layout = QHBoxLayout()
        self.refresh_button = QPushButton(self.loc['buttons']['refresh'])
        self.user_id_label = QLabel(self.loc['labels']['user_id_input'])
        self.user_id_input = QLineEdit()
        self.user_id_input.setPlaceholderText(self.loc['placeholders']['user_id_input'])
        
        toolbar_layout.addWidget(self.refresh_button)
        toolbar_layout.addStretch()
        toolbar_layout.addWidget(self.user_id_label)
        toolbar_layout.addWidget(self.user_id_input)
        layout.addLayout(toolbar_layout)

        # --- Tree View for Saves ---
        self.tree_view = QTreeView()
        self.tree_view.setAlternatingRowColors(True)
        self.tree_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.model = QStandardItemModel()
        self.tree_view.setModel(self.model)
        layout.addWidget(self.tree_view)
        
        # --- Bottom Toolbar ---
        bottom_toolbar_layout = QHBoxLayout()
        self.status_label = QLabel(self.loc['labels']['status_loading'])
        self.open_button = QPushButton(self.loc['buttons']['open'])
        
        bottom_toolbar_layout.addWidget(self.status_label)
        bottom_toolbar_layout.addStretch()
        bottom_toolbar_layout.addWidget(self.open_button)
        layout.addLayout(bottom_toolbar_layout)

        # --- Connections ---
        self.open_button.clicked.connect(self._on_open_button_clicked)
        self.tree_view.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.tree_view.doubleClicked.connect(self._on_tree_double_clicked)

        # self._on_selection_changed() # No longer needed to disable open button

    def _load_localization(self):
        filename = "ui_localization.json" if self.current_lang == 'zh-CN' else "ui_localization_EN.json"
        localized_data = resource_loader.load_json_resource(filename)
        if localized_data and "save_selector" in localized_data:
            self.loc = localized_data["save_selector"]
        else:
            # Fallback to hardcoded English if localization file is missing or invalid
            self.loc = {
                "headers": {"file": "File", "user_id": "Platform 64bit ID", "modified": "Modified", "size": "Size", "path": "Path"},
                "buttons": {"refresh": "Refresh", "open": "Open Selected Save with ID"},
                "labels": {"user_id_input": "Manual User ID:", "status_loading": "Scanning for saves...", "status_no_saves": "No save files found.", "status_found_saves": "Found {count} save files."},
                "placeholders": {"user_id_input": "Enter User ID here if auto-detection is incorrect"}
            }

    def set_header_labels(self, labels: List[str]):
        self.model.setHorizontalHeaderLabels(labels)
        header = self.tree_view.header()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)

    def update_view(self, save_files: List[Dict[str, Any]]):
        self.current_save_files = save_files
        self.model.clear()
        headers = self.loc['headers']
        self.set_header_labels([headers['file'], headers['user_id'], headers['modified'], headers['size'], headers['path']])

        if not save_files:
            self.status_label.setText(self.loc['labels']['status_no_saves'])
            return

        for file_info in save_files:
            row = [
                QStandardItem(str(file_info.get("name", ""))),
                QStandardItem(str(file_info.get("id", ""))),
                QStandardItem(str(file_info.get("modified", ""))),
                QStandardItem(f"{file_info.get('size_kb', 0):.1f} KB"),
                QStandardItem(str(file_info.get("full_path", "")))
            ]
            
            # Store full path and id in the first item for easy access
            row[0].setData(str(file_info.get("full_path", "")), Qt.ItemDataRole.UserRole + 1)
            row[0].setData(str(file_info.get("id", "")), Qt.ItemDataRole.UserRole + 2)
            
            self.model.appendRow(row)
        
        self.status_label.setText(self.loc['labels']['status_found_saves'].format(count=len(save_files)))

    def update_language(self, lang):
        print(f"DEBUG: Updating language for {self.__class__.__name__} to {lang}...")
        self.current_lang = lang
        self._load_localization()
        
        # Update text
        self.refresh_button.setText(self.loc['buttons']['refresh'])
        self.user_id_label.setText(self.loc['labels']['user_id_input'])
        self.user_id_input.setPlaceholderText(self.loc['placeholders']['user_id_input'])
        self.open_button.setText(self.loc['buttons']['open'])
        
        # Re-render the list to update headers and status text
        self.update_view(self.current_save_files)
        
        print(f"DEBUG: Finished updating language for {self.__class__.__name__}.")

    def _on_selection_changed(self):
        selection_model = self.tree_view.selectionModel()
        if not selection_model.hasSelection():
            # self.open_button.setEnabled(False) # Open button is now independent
            return
        
        # self.open_button.setEnabled(True)
        selected_index = selection_model.selectedRows(0)[0]
        id_from_selection = self.model.itemFromIndex(selected_index).data(Qt.ItemDataRole.UserRole + 2)
        
        # 如果手动输入框为空，则自动填充检测到的ID
        if not self.user_id_input.text().strip():
            self.user_id_input.setText(id_from_selection)

    def _on_open_button_clicked(self):
        """
        打开文件选择对话框，让用户手动选择存档文件。
        """
        # 尝试定位到默认的存档路径作为起始目录
        start_dir = os.path.expanduser('~/Documents')
        possible_paths = [
            os.path.join(start_dir, "My Games", "Borderlands 4", "Saved", "SaveGames"),
            start_dir
        ]
        initial_path = start_dir
        for p in possible_paths:
            if os.path.exists(p):
                initial_path = p
                break

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.loc['buttons']['open'], # 使用 Open 按钮的文本作为标题
            initial_path,
            "Borderlands 4 Save (*.sav);;All Files (*.*)"
        )

        if not file_path:
            return

        path_obj = Path(file_path)
        # 尝试从路径中回溯获取ID
        # 结构通常为: .../SaveGames/<ID>/Profiles/client/...
        inferred_id = ""
        current_path = path_obj.parent
        
        # 防止死循环，最多向上查找5层
        for _ in range(5):
            dirname = current_path.name
            is_valid_format = False
            if dirname.isdigit() and 10 <= len(dirname) <= 20:
                is_valid_format = True
            elif dirname.replace('-', '').replace('_', '').isalnum() and 10 <= len(dirname) <= 50:
                if dirname.lower() not in ["profiles", "client", "savegames", "saved", "config"]:
                    is_valid_format = True
            
            if is_valid_format:
                inferred_id = dirname
                break
            
            if current_path.parent == current_path:
                break
            current_path = current_path.parent

        # 优先使用手动输入框的ID (如果用户虽然点了浏览，但已经在输入框填了ID)
        user_id_input = self.user_id_input.text().strip()
        final_id = user_id_input if user_id_input else inferred_id

        self.open_save_requested.emit(file_path, final_id)

    def _on_tree_double_clicked(self):
        """
        双击树形视图项时的处理（保留以前的逻辑作为快捷方式）
        """
        selection_model = self.tree_view.selectionModel()
        if not selection_model.hasSelection():
            return
            
        selected_index = selection_model.selectedRows(0)[0]
        file_path = self.model.itemFromIndex(selected_index).data(Qt.ItemDataRole.UserRole + 1)
        
        # 优先使用手动输入的ID，如果为空则使用自动检测的ID
        user_id = self.user_id_input.text().strip()
        if not user_id:
            user_id = self.model.itemFromIndex(selected_index).data(Qt.ItemDataRole.UserRole + 2)

        if file_path and user_id:
            self.open_save_requested.emit(file_path, user_id)
