from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QGroupBox, QFormLayout, QComboBox, QDialog, QDialogButtonBox, QSizePolicy
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QIntValidator
from typing import Dict, Any
from core.unlock_data import CHARACTER_CLASSES, VAULT_CARD_TOKENS
from core import resource_loader

# --- XP Calculation ---
_XP_MULTIPLIER = 60.0
_XP_POWER = 2.8
_XP_OFFSET = 7.33

# Hardcoded cumulative XP for levels 1-10 (formula doesn't fit these)
_XP_TABLE_1_10 = {
    1: 0,
    2: 857,
    3: 1740,
    4: 3349,
    5: 5875,
    6: 9496,
    7: 14385,
    8: 20707,
    9: 28625,
    10: 38297,
}

def calc_xp_for_level(level: int) -> int:
    """Return the minimum cumulative XP required to reach *level*."""
    if level < 1:
        return 0
    if level <= 10:
        return _XP_TABLE_1_10.get(level, 0)
    return int(_XP_MULTIPLIER * (level ** _XP_POWER + _XP_OFFSET))

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
        self.vault_card_widgets = []
        self.vault_card_edits = {}
        self.is_profile_save = False

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
        
        # --- Level + XP row (half-width inputs with hint) ---
        level_xp_row = QHBoxLayout()
        self.ui_labels['level'] = QLabel(self.loc['labels']['level'])
        self.level_edit.setMaximumWidth(80)
        self.ui_labels['xp'] = QLabel(self.loc['labels']['xp'])
        self.xp_edit.setMaximumWidth(120)
        self.xp_edit.setReadOnly(True)

        self.ui_labels['xp_auto_hint'] = QLabel(self.loc['labels']['xp_auto_hint'])
        self.ui_labels['xp_auto_hint'].setStyleSheet("color: orange; font-style: italic;")
        self.ui_labels['xp_auto_hint'].setWordWrap(True)
        self.ui_labels['xp_auto_hint'].setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        level_xp_row.addWidget(self.ui_labels['level'])
        level_xp_row.addWidget(self.level_edit)
        level_xp_row.addWidget(self.ui_labels['xp'])
        level_xp_row.addWidget(self.xp_edit)
        level_xp_row.addWidget(self.ui_labels['xp_auto_hint'])
        char_form_layout.addRow(level_xp_row)
        
        self.ui_labels['spec_level'] = QLabel(self.loc['labels']['spec_level'])
        char_form_layout.addRow(self.ui_labels['spec_level'], self.spec_level_edit)
        
        self.ui_labels['spec_points'] = QLabel(self.loc['labels']['spec_points'])
        char_form_layout.addRow(self.ui_labels['spec_points'], self.spec_points_edit)
        
        main_layout.addWidget(self.ui_groups['character_info'])

        # Connect level change -> auto-calc XP
        self.level_edit.textChanged.connect(self._on_level_changed)
        
        # --- 货币区 ---
        self.ui_groups['currency'] = QGroupBox(self.loc['groups']['currency'])
        currency_form_layout = QFormLayout(self.ui_groups['currency'])
        
        self.ui_labels['money'] = QLabel(self.loc['labels']['money'])
        currency_form_layout.addRow(self.ui_labels['money'], self.money_edit)
        
        self.ui_labels['eridium'] = QLabel(self.loc['labels']['eridium'])
        currency_form_layout.addRow(self.ui_labels['eridium'], self.eridium_edit)

        self.character_currency_widgets = [
            self.ui_labels['money'], self.money_edit,
            self.ui_labels['eridium'], self.eridium_edit,
        ]
        for card in VAULT_CARD_TOKENS:
            if not isinstance(card, dict) or not isinstance(card.get('currency_key'), str):
                continue
            currency_key = card['currency_key']
            label = QLabel(self._vault_card_label(card))
            edit = QLineEdit(self)
            edit.setValidator(QIntValidator(0, 2147483647, edit))
            currency_form_layout.addRow(label, edit)
            self.vault_card_edits[currency_key] = edit
            self.vault_card_widgets.append((card, label, edit))
        
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
        self.ui_labels['preset_mode_hint'] = QLabel(self)
        self.ui_labels['preset_mode_hint'].setStyleSheet("color: #f0c674; font-weight: 600;")
        self.ui_labels['preset_mode_hint'].setWordWrap(True)
        main_layout.addWidget(self.ui_labels['preset_mode_hint'])

        presets_layout = QHBoxLayout()
        
        # --- Profile/Shared 预设 ---
        self.ui_groups['world_presets'] = QGroupBox(self.loc['groups']['world_presets'])
        world_layout = QVBoxLayout(self.ui_groups['world_presets'])
        
        world_buttons = [
            ("clear_fog", self.loc['presets']['clear_fog'], "clear_map_fog"),
            ("discover_locs", self.loc['presets']['discover_locs'], "discover_all_locations"),
            ("unlock_safehouses", self.loc['presets']['unlock_safehouses'], "complete_all_safehouse_missions"),
            ("unlock_collectibles", self.loc['presets']['unlock_collectibles'], "complete_all_collectibles"),
            ("unlock_cosmetics", self.loc['presets']['unlock_cosmetics'], "unlock_all_cosmetics"),
            ("max_sdu", self.loc['presets']['max_sdu'], "set_max_sdu"),
            ("unlock_vault", self.loc['presets']['unlock_vault'], "unlock_vault_powers"),
            ("unlock_vehicles", self.loc['presets']['unlock_vehicles'], "unlock_all_hover_drives"),
            ("unlock_vault_cards", self.loc['presets']['unlock_vault_cards'], "unlock_all_vault_card_rewards"),
        ]
        
        for key, label, action in world_buttons:
            btn = QPushButton(label)
            btn.clicked.connect(lambda checked, a=action: self.unlock_requested.emit(a, {}))
            world_layout.addWidget(btn)
            self.world_btns_widgets.append((key, btn))

        self.ui_labels['profile_only_hint'] = QLabel(self.loc['labels']['profile_only_hint'])
        self.ui_labels['profile_only_hint'].setStyleSheet("color: #9aa0a6; font-size: 11px;")
        self.ui_labels['profile_only_hint'].setWordWrap(True)
        world_layout.addWidget(self.ui_labels['profile_only_hint'])
            
        presets_layout.addWidget(self.ui_groups['world_presets'])
        
        # --- 角色存档预设 ---
        self.ui_groups['char_presets'] = QGroupBox(self.loc['groups']['char_presets'])
        char_layout = QVBoxLayout(self.ui_groups['char_presets'])
        
        char_buttons = [
            ("change_class", self.loc['presets']['change_class'], "change_class_popup"),
            ("max_level", self.loc['presets']['max_level'], "set_character_to_max_level"),
            ("complete_challenges", self.loc['presets']['complete_challenges'], "complete_all_challenges"),
            ("complete_achievements", self.loc['presets']['complete_achievements'], "complete_all_achievements"),
            ("skip_story", self.loc['presets']['skip_story'], "complete_all_story_missions"),
            ("skip_all", self.loc['presets']['skip_all'], "complete_all_missions"),
            ("unlock_specs", self.loc['presets']['unlock_specs'], "unlock_all_specialization"),
            ("unlock_uvhm", self.loc['presets']['unlock_uvhm'], "unlock_postgame"),
            ("max_ammo", self.loc['presets']['max_ammo'], "max_ammo"),
        ]
        
        for key, label, action in char_buttons:
            btn = QPushButton(label)
            if action == "change_class_popup":
                btn.clicked.connect(self._show_change_class_popup)
            else:
                btn.clicked.connect(lambda checked, a=action: self.unlock_requested.emit(a, {}))
            char_layout.addWidget(btn)
            self.char_btns_widgets.append((key, btn))

        self.ui_labels['character_only_hint'] = QLabel(self.loc['labels']['character_only_hint'])
        self.ui_labels['character_only_hint'].setStyleSheet("color: #9aa0a6; font-size: 11px;")
        self.ui_labels['character_only_hint'].setWordWrap(True)
        char_layout.addWidget(self.ui_labels['character_only_hint'])
            
        presets_layout.addWidget(self.ui_groups['char_presets'])
        
        main_layout.addLayout(presets_layout)
        self._apply_preset_button_state()

    def _show_change_class_popup(self):
        if self.is_profile_save:
            return

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
                "groups": {"character_info": "Character", "currency": "Currency", "world_presets": "Profile / Shared", "char_presets": "Character Save"},
                "labels": {
                    "name": "Name:", "difficulty": "Difficulty:", "level": "Level:", "xp": "XP:",
                    "spec_level": "Spec Level:", "spec_points": "Spec Points:", "money": "Money:", "eridium": "Eridium:",
                    "vault_card_tokens": "Vault Card {number} Tokens:",
                    "xp_auto_hint": "Enter your target level to auto-calculate the required XP",
                    "profile_only_hint": "Profile save only. Disabled on character saves.",
                    "character_only_hint": "Character save only. Disabled on profile saves.",
                    "preset_mode_profile": "Current save type: Profile. Profile presets enabled, character presets disabled.",
                    "preset_mode_character": "Current save type: Character save. Character presets enabled, profile presets disabled.",
                    "preset_credit": ""
                },
                "buttons": {"apply_changes": "Apply Changes", "apply_profile_changes": "Apply Profile Currency Changes", "sync_levels": "Sync Item Levels"},
                "warnings": {"sync_warning": "Warning: May unequip items."},
                "presets": {"clear_fog": "Clear Fog", "discover_locs": "Discover Locations", "unlock_safehouses": "Unlock Safehouses", 
                            "unlock_collectibles": "Unlock Collectibles", "complete_challenges": "Complete Challenges", 
                            "complete_achievements": "Complete Achievements", "skip_story": "Skip Story", "skip_all": "Skip All Missions",
                            "change_class": "Change Class", "max_level": "Max Level", "max_sdu": "Max SDU", 
                            "unlock_vault": "Unlock Vault", "unlock_vehicles": "Unlock Vehicles", "unlock_cosmetics": "Unlock Cosmetics", "unlock_specs": "Unlock Specs",
                            "unlock_uvhm": "Unlock UVHM", "unlock_vault_cards": "Unlock All Vault Card Rewards", "max_ammo": "Refill Ammo", "unlock_max": "Unlock Max"},
                "dialogs": {"change_class_title": "Change Class", "select_class": "Select Class:"}
            }

        self.loc.setdefault("groups", {})
        self.loc.setdefault("labels", {})
        self.loc.setdefault("buttons", {})
        self.loc.setdefault("warnings", {})
        self.loc.setdefault("presets", {})
        self.loc.setdefault("dialogs", {})

        self.loc["groups"].setdefault("world_presets", "Profile / Shared")
        self.loc["groups"].setdefault("char_presets", "Character Save")

        self.loc["labels"].setdefault("profile_only_hint", "Profile save only. Disabled on character saves.")
        self.loc["labels"].setdefault("character_only_hint", "Character save only. Disabled on profile saves.")
        self.loc["labels"].setdefault("preset_mode_profile", "Current save type: Profile. Profile presets enabled, character presets disabled.")
        self.loc["labels"].setdefault("preset_mode_character", "Current save type: Character save. Character presets enabled, profile presets disabled.")
        self.loc["labels"].setdefault("preset_credit", "")
        self.loc["labels"].setdefault("vault_card_tokens", "Vault Card {number} Tokens:")
        self.loc["buttons"].setdefault("apply_profile_changes", "Apply Profile Currency Changes")
        self.loc["presets"].setdefault("unlock_vault_cards", "Unlock All Vault Card Rewards")
        self.loc["presets"].setdefault("max_ammo", "Refill Ammo")

    def _vault_card_label(self, card):
        number = card.get('number', card.get('card_id', ''))
        return self.loc['labels'].get('vault_card_tokens', 'Vault Card {number} Tokens:').format(number=number)

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
        self.ui_labels['xp_auto_hint'].setText(self.loc['labels']['xp_auto_hint'])
        self.ui_labels['spec_level'].setText(self.loc['labels']['spec_level'])
        self.ui_labels['spec_points'].setText(self.loc['labels']['spec_points'])
        self.ui_labels['money'].setText(self.loc['labels']['money'])
        self.ui_labels['eridium'].setText(self.loc['labels']['eridium'])
        for card, label, _ in self.vault_card_widgets:
            label.setText(self._vault_card_label(card))
        self.ui_labels['sync_warning'].setText(self.loc['warnings']['sync_warning'])
        self.ui_labels['profile_only_hint'].setText(self.loc['labels']['profile_only_hint'])
        self.ui_labels['character_only_hint'].setText(self.loc['labels']['character_only_hint'])
        
        # Buttons
        self.ui_buttons['sync_levels'].setText(self.loc['buttons']['sync_levels'])
        
        # Dynamic Buttons
        for key, btn in self.world_btns_widgets:
            btn.setText(self.loc['presets'][key])
            
        for key, btn in self.char_btns_widgets:
            btn.setText(self.loc['presets'][key])

        self._apply_preset_button_state()
        print(f"DEBUG: Finished updating language for {self.__class__.__name__}.")

    def _apply_preset_button_state(self):
        for _, btn in self.world_btns_widgets:
            btn.setEnabled(self.is_profile_save)

        for _, btn in self.char_btns_widgets:
            btn.setEnabled(not self.is_profile_save)

        self.ui_groups['character_info'].setVisible(not self.is_profile_save)
        for widget in self.character_currency_widgets:
            widget.setVisible(not self.is_profile_save)
        for _, label, edit in self.vault_card_widgets:
            label.setVisible(self.is_profile_save)
            edit.setVisible(self.is_profile_save)
        self.ui_buttons['sync_levels'].setVisible(not self.is_profile_save)
        self.ui_labels['sync_warning'].setVisible(not self.is_profile_save)
        apply_key = 'apply_profile_changes' if self.is_profile_save else 'apply_changes'
        self.ui_buttons['apply_changes'].setText(self.loc['buttons'][apply_key])

        if self.is_profile_save:
            mode_text = self.loc['labels']['preset_mode_profile']
        else:
            mode_text = self.loc['labels']['preset_mode_character']

        credit_text = self.loc['labels'].get('preset_credit', '').strip()
        if credit_text:
            self.ui_labels['preset_mode_hint'].setText(f"{mode_text}\n{credit_text}")
        else:
            self.ui_labels['preset_mode_hint'].setText(mode_text)

    def update_fields(self, data: Dict[str, Any]):
        """用从控制器获取的数据填充UI字段。"""
        if not data:
            return

        self.is_profile_save = bool(data.get("is_profile_save", False))
        self._apply_preset_button_state()

        self.cur_paths = data.get('cur_paths', {})
        self.name_edit.setText(data.get("名称", ""))
        self.difficulty_edit.setText(data.get("难度", ""))

        # Block signals while loading to avoid triggering auto-calc
        self.level_edit.blockSignals(True)
        self.level_edit.setText(data.get("角色等级", ""))
        self.level_edit.blockSignals(False)
        # Show the actual XP from save (original value)
        self.xp_edit.setText(data.get("角色经验值", ""))
        # Store the original save XP so we know when user hasn't changed level
        self._original_level = data.get("角色等级", "")
        self._original_xp = data.get("角色经验值", "")

        self.spec_level_edit.setText(data.get("专精等级", ""))
        self.spec_points_edit.setText(data.get("专精点数", ""))
        self.money_edit.setText(data.get("金钱", ""))
        self.eridium_edit.setText(data.get("镒矿", ""))
        for currency_key, edit in self.vault_card_edits.items():
            edit.setText(data.get(currency_key, ""))

    def _on_level_changed(self, text: str):
        """When the user edits the level, auto-calculate XP."""
        text = text.strip()
        if not text:
            return
        try:
            level = int(text)
            if level < 1:
                level = 1
            xp = calc_xp_for_level(level)
            self.xp_edit.setText(str(xp))
        except ValueError:
            pass  # ignore non-numeric input
    
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
        for currency_key, edit in self.vault_card_edits.items():
            data_to_apply[currency_key] = edit.text()
        self.character_data_changed.emit(data_to_apply)
