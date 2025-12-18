from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit, QPushButton, 
    QGroupBox, QFormLayout, QComboBox, QDialog, QDialogButtonBox
)
from PyQt6.QtCore import pyqtSignal, Qt
from typing import Dict, Any
from core.unlock_data import CHARACTER_CLASSES
from core import resource_loader

class QtCharacterTab(QWidget):
    character_data_changed = pyqtSignal(dict)
    sync_levels_requested = pyqtSignal()
    unlock_requested = pyqtSignal(str, dict)  # action_name, params

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.current_lang = 'zh-CN'
        self._load_localization()
        self.cur_paths: Dict[str, Any] = {}

        self.ui_labels = {}
        self.ui_buttons = {}
        self.ui_groups = {}
        self.world_btns_widgets = [] # store (action, widget)
        self.char_btns_widgets = []

        # --- UI元素直接定义为实例属性 ---
        self.name_edit = QLineEdit(self)
        self.difficulty_edit = QLineEdit(self)
        self.level_edit = QLineEdit(self)
        self.xp_edit = QLineEdit(self)
        self.spec_level_edit = QLineEdit(self)
        self.spec_points_edit = QLineEdit(self)
        self.money_edit = QLineEdit(self)
        self.eridium_edit = QLineEdit(self)

        main_layout = QVBoxLayout(self)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # --- 角色信息区 ---
        self.ui_groups['character_info'] = QGroupBox(self.loc['groups']['character_info'])
        char_form_layout = QFormLayout(self.ui_groups['character_info'])
        
        self.ui_labels['name'] = QLabel(self.loc['labels']['name'])
        char_form_layout.addRow(self.ui_labels['name'], self.name_edit)
        
        self.ui_labels['difficulty'] = QLabel(self.loc['labels']['difficulty'])
        char_form_layout.addRow(self.ui_labels['difficulty'], self.difficulty_edit)
        
        self.ui_labels['level'] = QLabel(self.loc['labels']['level'])
        char_form_layout.addRow(self.ui_labels['level'], self.level_edit)
        
        self.ui_labels['xp'] = QLabel(self.loc['labels']['xp'])
        char_form_layout.addRow(self.ui_labels['xp'], self.xp_edit)
        
        self.ui_labels['spec_level'] = QLabel(self.loc['labels']['spec_level'])
        char_form_layout.addRow(self.ui_labels['spec_level'], self.spec_level_edit)
        
        self.ui_labels['spec_points'] = QLabel(self.loc['labels']['spec_points'])
        char_form_layout.addRow(self.ui_labels['spec_points'], self.spec_points_edit)
        
        main_layout.addWidget(self.ui_groups['character_info'])
        
        # --- 货币区 ---
        self.ui_groups['currency'] = QGroupBox(self.loc['groups']['currency'])
        currency_form_layout = QFormLayout(self.ui_groups['currency'])
        
        self.ui_labels['money'] = QLabel(self.loc['labels']['money'])
        currency_form_layout.addRow(self.ui_labels['money'], self.money_edit)
        
        self.ui_labels['eridium'] = QLabel(self.loc['labels']['eridium'])
        currency_form_layout.addRow(self.ui_labels['eridium'], self.eridium_edit)
        
        main_layout.addWidget(self.ui_groups['currency'])

        # --- 操作按钮 ---
        self.ui_buttons['apply_changes'] = QPushButton(self.loc['buttons']['apply_changes'])
        self.ui_buttons['apply_changes'].clicked.connect(self._on_apply_changes)
        main_layout.addWidget(self.ui_buttons['apply_changes'])

        self.ui_buttons['sync_levels'] = QPushButton(self.loc['buttons']['sync_levels'])
        self.ui_buttons['sync_levels'].clicked.connect(self.sync_levels_requested.emit)
        
        self.ui_labels['sync_warning'] = QLabel(self.loc['warnings']['sync_warning'])
        self.ui_labels['sync_warning'].setStyleSheet("color: orange;")
        self.ui_labels['sync_warning'].setWordWrap(True)
        
        main_layout.addWidget(self.ui_buttons['sync_levels'])
        main_layout.addWidget(self.ui_labels['sync_warning'])

        # --- 解锁预设区域 ---
        presets_layout = QHBoxLayout()
        
        # --- 世界预设 ---
        self.ui_groups['world_presets'] = QGroupBox(self.loc['groups']['world_presets'])
        world_layout = QVBoxLayout(self.ui_groups['world_presets'])
        
        world_buttons = [
            ("clear_fog", self.loc['presets']['clear_fog'], "clear_map_fog"),
            ("discover_locs", self.loc['presets']['discover_locs'], "discover_all_locations"),
            ("unlock_safehouses", self.loc['presets']['unlock_safehouses'], "complete_all_safehouse_missions"),
            ("unlock_collectibles", self.loc['presets']['unlock_collectibles'], "complete_all_collectibles"),
            ("complete_challenges", self.loc['presets']['complete_challenges'], "complete_all_challenges"),
            ("complete_achievements", self.loc['presets']['complete_achievements'], "complete_all_achievements"),
            ("skip_story", self.loc['presets']['skip_story'], "complete_all_story_missions"),
            ("skip_all", self.loc['presets']['skip_all'], "complete_all_missions"),
        ]
        
        for key, label, action in world_buttons:
            btn = QPushButton(label)
            btn.clicked.connect(lambda checked, a=action: self.unlock_requested.emit(a, {}))
            world_layout.addWidget(btn)
            self.world_btns_widgets.append((key, btn))
            
        presets_layout.addWidget(self.ui_groups['world_presets'])
        
        # --- 角色预设 ---
        self.ui_groups['char_presets'] = QGroupBox(self.loc['groups']['char_presets'])
        char_layout = QVBoxLayout(self.ui_groups['char_presets'])
        
        char_buttons = [
            ("change_class", self.loc['presets']['change_class'], "change_class_popup"),
            ("max_level", self.loc['presets']['max_level'], "set_character_to_max_level"),
            ("max_sdu", self.loc['presets']['max_sdu'], "set_max_sdu"),
            ("unlock_vault", self.loc['presets']['unlock_vault'], "unlock_vault_powers"),
            ("unlock_vehicles", self.loc['presets']['unlock_vehicles'], "unlock_all_hover_drives"),
            ("unlock_specs", self.loc['presets']['unlock_specs'], "unlock_all_specialization"),
            ("unlock_uvhm", self.loc['presets']['unlock_uvhm'], "unlock_postgame"),
            ("unlock_max", self.loc['presets']['unlock_max'], "unlock_max_everything"),
        ]
        
        for key, label, action in char_buttons:
            btn = QPushButton(label)
            if action == "change_class_popup":
                btn.clicked.connect(self._show_change_class_popup)
            else:
                btn.clicked.connect(lambda checked, a=action: self.unlock_requested.emit(a, {}))
            char_layout.addWidget(btn)
            self.char_btns_widgets.append((key, btn))
            
        presets_layout.addWidget(self.ui_groups['char_presets'])
        
        main_layout.addLayout(presets_layout)

    def _show_change_class_popup(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(self.loc['dialogs']['change_class_title'])
        layout = QVBoxLayout(dialog)
        
        label = QLabel(self.loc['dialogs']['select_class'])
        layout.addWidget(label)
        
        combo = QComboBox()
        class_keys = list(CHARACTER_CLASSES.keys())
        for key in class_keys:
            info = CHARACTER_CLASSES[key]
            combo.addItem(f"{info['class']} ({info['name']})", key)
        layout.addWidget(combo)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            class_key = combo.currentData()
            self.unlock_requested.emit("set_character_class", {"class_key": class_key})

    def _load_localization(self):
        filename = resource_loader.get_ui_localization_file(self.current_lang)
        data = resource_loader.load_json_resource(filename)
        if data and "character_tab" in data:
            self.loc = data["character_tab"]
        else:
            # Fallback
            self.loc = {
                "groups": {"character_info": "Character", "currency": "Currency", "world_presets": "World", "char_presets": "Character"},
                "labels": {"name": "Name:", "difficulty": "Difficulty:", "level": "Level:", "xp": "XP:", "spec_level": "Spec Level:", "spec_points": "Spec Points:", "money": "Money:", "eridium": "Eridium:"},
                "buttons": {"apply_changes": "Apply Changes", "sync_levels": "Sync Item Levels"},
                "warnings": {"sync_warning": "Warning: May unequip items."},
                "presets": {"clear_fog": "Clear Fog", "discover_locs": "Discover Locations", "unlock_safehouses": "Unlock Safehouses", 
                            "unlock_collectibles": "Unlock Collectibles", "complete_challenges": "Complete Challenges", 
                            "complete_achievements": "Complete Achievements", "skip_story": "Skip Story", "skip_all": "Skip All Missions",
                            "change_class": "Change Class", "max_level": "Max Level", "max_sdu": "Max SDU", 
                            "unlock_vault": "Unlock Vault", "unlock_vehicles": "Unlock Vehicles", "unlock_specs": "Unlock Specs",
                            "unlock_uvhm": "Unlock UVHM", "unlock_max": "Unlock Max"},
                "dialogs": {"change_class_title": "Change Class", "select_class": "Select Class:"}
            }

    def update_language(self, lang):
        print(f"DEBUG: Updating language for {self.__class__.__name__} to {lang}...")
        self.current_lang = lang
        self._load_localization()
        
        # Groups
        self.ui_groups['character_info'].setTitle(self.loc['groups']['character_info'])
        self.ui_groups['currency'].setTitle(self.loc['groups']['currency'])
        self.ui_groups['world_presets'].setTitle(self.loc['groups']['world_presets'])
        self.ui_groups['char_presets'].setTitle(self.loc['groups']['char_presets'])
        
        # Labels
        self.ui_labels['name'].setText(self.loc['labels']['name'])
        self.ui_labels['difficulty'].setText(self.loc['labels']['difficulty'])
        self.ui_labels['level'].setText(self.loc['labels']['level'])
        self.ui_labels['xp'].setText(self.loc['labels']['xp'])
        self.ui_labels['spec_level'].setText(self.loc['labels']['spec_level'])
        self.ui_labels['spec_points'].setText(self.loc['labels']['spec_points'])
        self.ui_labels['money'].setText(self.loc['labels']['money'])
        self.ui_labels['eridium'].setText(self.loc['labels']['eridium'])
        self.ui_labels['sync_warning'].setText(self.loc['warnings']['sync_warning'])
        
        # Buttons
        self.ui_buttons['apply_changes'].setText(self.loc['buttons']['apply_changes'])
        self.ui_buttons['sync_levels'].setText(self.loc['buttons']['sync_levels'])
        
        # Dynamic Buttons
        for key, btn in self.world_btns_widgets:
            btn.setText(self.loc['presets'][key])
            
        for key, btn in self.char_btns_widgets:
            btn.setText(self.loc['presets'][key])
        print(f"DEBUG: Finished updating language for {self.__class__.__name__}.")

    def update_fields(self, data: Dict[str, Any]):
        """用从控制器获取的数据填充UI字段。"""
        if not data:
            return

        self.cur_paths = data.get('cur_paths', {})
        self.name_edit.setText(data.get("名称", ""))
        self.difficulty_edit.setText(data.get("难度", ""))
        self.level_edit.setText(data.get("角色等级", ""))
        self.xp_edit.setText(data.get("角色经验值", ""))
        self.spec_level_edit.setText(data.get("专精等级", ""))
        self.spec_points_edit.setText(data.get("专精点数", ""))
        self.money_edit.setText(data.get("金钱", ""))
        self.eridium_edit.setText(data.get("镒矿", ""))
    
    def _on_apply_changes(self):
        """收集UI数据并发出信号。"""
        data_to_apply = {
            "名称": self.name_edit.text(),
            "难度": self.difficulty_edit.text(),
            "角色等级": self.level_edit.text(),
            "角色经验值": self.xp_edit.text(),
            "专精等级": self.spec_level_edit.text(),
            "专精点数": self.spec_points_edit.text(),
            "金钱": self.money_edit.text(),
            "镒矿": self.eridium_edit.text(),
            "cur_paths": self.cur_paths  # 附加货币路径
        }
        self.character_data_changed.emit(data_to_apply)
