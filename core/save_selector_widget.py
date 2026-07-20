import json
from . import resource_loader
from .save_game_controller import infer_user_id_from_save_path
import os
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QTreeView, QAbstractItemView, QHeaderView, QFileDialog, QMessageBox, QSizePolicy
)
from PyQt6.QtGui import QStandardItemModel, QStandardItem
from PyQt6.QtCore import pyqtSignal, Qt, QStandardPaths
from typing import List, Dict, Any

class SaveSelectorWidget(QWidget):
    """
    一个用于显示、选择和打开存档文件的欢迎界面。
    """
    # 信号：存档路径，用户ID
    open_save_requested = pyqtSignal(str, str)
    
    CONFIG_FILE = "config.json"

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.current_lang = 'zh-CN'
        self.current_save_files = [] # Store for language updates
        self.custom_save_path = None
        self.custom_backup_path = None
        self.game_install_path = None
        self._auto_user_id = ""
        self._load_config()
        self._load_localization()

        # --- Main Layout ---
        layout = QVBoxLayout(self)
        
        # --- Top Toolbar ---
        toolbar_layout = QVBoxLayout()
        directory_layout = QHBoxLayout()
        user_id_layout = QHBoxLayout()
        self.refresh_button = QPushButton(self.loc['buttons']['refresh'])
        self.select_game_dir_btn = QPushButton(self.loc['buttons'].get('select_game_dir', 'Set Game Directory'))
        self.select_save_folder_btn = QPushButton(self.loc['buttons']['select_save_folder'])
        self.select_backup_folder_btn = QPushButton(self.loc['buttons']['select_backup_folder'])
        
        self.user_id_label = QLabel(self.loc['labels']['user_id_input'])
        self.user_id_input = QLineEdit()
        self.user_id_input.setPlaceholderText(self.loc['placeholders']['user_id_input'])
        self.user_id_input.textEdited.connect(self._clear_auto_user_id)
        
        directory_layout.addWidget(self.refresh_button)
        directory_layout.addWidget(self.select_game_dir_btn)
        directory_layout.addWidget(self.select_save_folder_btn)
        directory_layout.addWidget(self.select_backup_folder_btn)
        directory_layout.addStretch()
        user_id_layout.addWidget(self.user_id_label)
        user_id_layout.addWidget(self.user_id_input, 1)
        toolbar_layout.addLayout(directory_layout)
        toolbar_layout.addLayout(user_id_layout)
        layout.addLayout(toolbar_layout)
        
        # --- Path Info Labels (Optional, but good for UX) ---
        self.path_info_layout = QVBoxLayout()
        self.game_dir_label = QLabel()
        self.save_path_label = QLabel()
        self.backup_path_label = QLabel()
        for label in (self.game_dir_label, self.save_path_label, self.backup_path_label):
            label.setWordWrap(True)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._update_path_labels()
        self.path_info_layout.addWidget(self.game_dir_label)
        self.path_info_layout.addWidget(self.save_path_label)
        self.path_info_layout.addWidget(self.backup_path_label)
        layout.addLayout(self.path_info_layout)

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
        self.select_game_dir_btn.clicked.connect(self._on_select_game_dir_clicked)
        self.select_save_folder_btn.clicked.connect(self._on_select_save_folder_clicked)
        self.select_backup_folder_btn.clicked.connect(self._on_select_backup_folder_clicked)

        # Check if game directory needs to be configured on startup
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(500, self._check_initial_game_dir)

    def _load_config(self):
        if os.path.exists(self.CONFIG_FILE):
            try:
                with open(self.CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.custom_save_path = config.get("custom_save_path")
                    self.custom_backup_path = config.get("custom_backup_path")
                    self.game_install_path = config.get("game_install_path")
            except Exception as e:
                print(f"Error loading config: {e}")

    def _save_config(self):
        config = {
            "custom_save_path": self.custom_save_path,
            "custom_backup_path": self.custom_backup_path,
            "game_install_path": self.game_install_path
        }
        try:
            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving config: {e}")

    def _load_localization(self):
        filename = resource_loader.get_ui_localization_file(self.current_lang)
        localized_data = resource_loader.load_json_resource(filename)
        if localized_data and "save_selector" in localized_data:
            self.loc = localized_data["save_selector"]
        else:
            # Fallback to hardcoded English if localization file is missing or invalid
            self.loc = {
                "headers": {"file": "File", "user_id": "Platform 64bit ID", "modified": "Modified", "size": "Size", "path": "Path"},
                "buttons": {"refresh": "Refresh", "open": "Open Selected Save with ID", "select_save_folder": "Select Save Folder", "select_backup_folder": "Select Backup Folder"},
                "labels": {
                    "user_id_input": "Manual User ID:", 
                    "status_loading": "Scanning for saves...", 
                    "status_no_saves": "No save files found.", 
                    "status_found_saves": "Found {count} save files.",
                    "current_save_path": "Current Save Path: {path}",
                    "current_backup_path": "Current Backup Path: {path}"
                },
                "placeholders": {"user_id_input": "Enter User ID here if auto-detection is incorrect"}
            }

    def set_header_labels(self, labels: List[str]):
        self.model.setHorizontalHeaderLabels(labels)
        header = self.tree_view.header()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
    
    def _update_path_labels(self):
        game_dir_display = self.game_install_path if self.game_install_path else self.loc['labels'].get('not_set', 'Not Set')
        save_path_display = self.custom_save_path if self.custom_save_path else self._derive_save_path_from_game_dir() or self.loc['labels'].get('not_set', 'Not Set')
        backup_path_display = self.custom_backup_path if self.custom_backup_path else self.loc['labels'].get('not_set', 'Not Set')
        
        self.game_dir_label.setText(self.loc['labels'].get('current_game_dir', 'Game Directory: {path}').format(path=game_dir_display))
        self.save_path_label.setText(self.loc['labels'].get('current_save_path', 'Current Save Path: {path}').format(path=save_path_display))
        self.backup_path_label.setText(self.loc['labels'].get('current_backup_path', 'Current Backup Path: {path}').format(path=backup_path_display))

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
        self.select_game_dir_btn.setText(self.loc['buttons'].get('select_game_dir', 'Set Game Directory'))
        self.select_save_folder_btn.setText(self.loc['buttons']['select_save_folder'])
        self.select_backup_folder_btn.setText(self.loc['buttons']['select_backup_folder'])
        self.user_id_label.setText(self.loc['labels']['user_id_input'])
        self.user_id_input.setPlaceholderText(self.loc['placeholders']['user_id_input'])
        self.open_button.setText(self.loc['buttons']['open'])
        self._update_path_labels()
        
        # Re-render the list to update headers and status text
        self.update_view(self.current_save_files)
        
        print(f"DEBUG: Finished updating language for {self.__class__.__name__}.")

    def _on_selection_changed(self):
        selection_model = self.tree_view.selectionModel()
        if not selection_model.hasSelection():
            return
        
        selected_index = selection_model.selectedRows(0)[0]
        id_from_selection = self.model.itemFromIndex(selected_index).data(Qt.ItemDataRole.UserRole + 2)
        
        # Follow the selected account until the user explicitly edits this field.
        if not self.user_id_input.text().strip() or self._auto_user_id:
            self.user_id_input.setText(id_from_selection or "")
            self._auto_user_id = id_from_selection or ""

    def _clear_auto_user_id(self):
        self._auto_user_id = ""

    def _derive_save_path_from_game_dir(self) -> str:
        """Honor an explicit install folder, then use the redirected Documents root."""
        if self.game_install_path:
            game_dir = Path(self.game_install_path)
            for root in (game_dir, *list(game_dir.parents)[:4]):
                for candidate in (root / "OakGame" / "Saved" / "SaveGames", root / "Saved" / "SaveGames"):
                    if candidate.is_dir():
                        return str(candidate)

        documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        documents_save = Path(documents) / "My Games" / "Borderlands 4" / "Saved" / "SaveGames"
        if documents and documents_save.is_dir():
            return str(documents_save)
        
        return None

    def _check_initial_game_dir(self):
        """启动时检查是否需要设定游戏目录。"""
        # 如果已有 custom_save_path 或 game_install_path，不需要提示
        if self.custom_save_path or self._derive_save_path_from_game_dir():
            return
        
        msg = self.loc.get('dialogs', {}).get('game_dir_needed', 
            'Game save location has been changed in a recent update.\n'
            'Please set your Borderlands 4 game directory to locate saves.\n\n'
            'You can select any folder under the Borderlands 4 installation.')
        QMessageBox.information(self, 
            self.loc.get('dialogs', {}).get('game_dir_needed_title', 'Set Game Directory'), 
            msg)
        self._on_select_game_dir_clicked()

    def _on_select_game_dir_clicked(self):
        """选择游戏安装目录，智能判断路径层级。"""
        dir_path = QFileDialog.getExistingDirectory(
            self, 
            self.loc['buttons'].get('select_game_dir', 'Set Game Directory')
        )
        if not dir_path:
            return
        
        path_obj = Path(dir_path)
        self.game_install_path = str(path_obj)
        
        # 尝试从选择的目录推导存档路径
        derived_path = self._derive_save_path_from_game_dir()
        if derived_path:
            info_msg = self.loc.get('dialogs', {}).get('game_dir_found',
                'Save folder auto-detected at:\n{path}').format(path=derived_path)
            QMessageBox.information(self, 
                self.loc.get('dialogs', {}).get('success', 'Success'), 
                info_msg)
        else:
            warn_msg = self.loc.get('dialogs', {}).get('game_dir_not_found',
                'Could not auto-detect save folder from the selected directory.\n'
                'You may need to use "Select Save Folder" to manually choose the SaveGames folder.')
            QMessageBox.warning(self, 
                self.loc.get('dialogs', {}).get('warning', 'Warning'), 
                warn_msg)
        
        self._save_config()
        self._update_path_labels()
        self.refresh_button.click()

    def _on_select_save_folder_clicked(self):
        dir_path = QFileDialog.getExistingDirectory(self, self.loc['buttons']['select_save_folder'])
        if dir_path:
            self.custom_save_path = str(Path(dir_path))
            self._save_config()
            self._update_path_labels()
            self.refresh_button.click() # Trigger refresh

    def _on_select_backup_folder_clicked(self):
        dir_path = QFileDialog.getExistingDirectory(self, self.loc['buttons']['select_backup_folder'])
        if dir_path:
            self.custom_backup_path = dir_path
            self._save_config()
            self._update_path_labels()

    def get_custom_save_path(self):
        """返回存档路径，优先 custom_save_path，其次从 game_install_path 推导。"""
        if self.custom_save_path:
            return self.custom_save_path
        return self._derive_save_path_from_game_dir()

    def get_custom_backup_path(self):
        return self.custom_backup_path

    def _on_open_button_clicked(self):
        """
        打开文件选择对话框，让用户手动选择存档文件。
        """
        # 尝试定位到默认的存档路径作为起始目录
        resolved_path = self.get_custom_save_path()
        if resolved_path and os.path.exists(resolved_path):
            initial_path = resolved_path
        else:
            initial_path = os.path.expanduser('~')

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.loc['buttons']['open'], # 使用 Open 按钮的文本作为标题
            initial_path,
            self.loc['dialogs'].get('save_filter', "Borderlands 4 Saves (*.sav);;All Files (*.*)")
        )

        if not file_path:
            return

        inferred_id = infer_user_id_from_save_path(file_path)

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
