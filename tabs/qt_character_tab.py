from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QGroupBox, QFormLayout, QComboBox, QDialog, QDialogButtonBox, QSizePolicy,
    QScrollArea, QGridLayout
)
from PyQt6.QtCore import pyqtSignal, Qt, QLocale, QSettings
from PyQt6.QtGui import QDoubleValidator, QIntValidator
from typing import Dict, Any
import json
import re
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
    runtime_action_requested = pyqtSignal(str, object)

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
        self._live_vault_cards = []
        self._live_currencies = []
        self._live_position = {}
        self._live_lost_loot = {}
        self._runtime_busy = False
        self._inventory_mutation_blocked = False
        self._settings = QSettings('SuperExboom', 'BL4SaveEditor')
        self._position_bookmarks = self._load_position_bookmarks()
        self.is_profile_save = False
        self._live_mode = False

        # --- UI元素直接定义为实例属性 ---
        self.name_edit = QLineEdit(self)
        self.difficulty_edit = QLineEdit(self)
        self.level_edit = QLineEdit(self)
        self.xp_edit = QLineEdit(self)
        self.spec_level_edit = QLineEdit(self)
        self.spec_points_edit = QLineEdit(self)
        self.money_edit = QLineEdit(self)
        self.eridium_edit = QLineEdit(self)

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page_layout.addWidget(self.scroll_area)

        content = QWidget()
        self.scroll_area.setWidget(content)
        main_layout = QVBoxLayout(content)
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

        # Online mode reuses this page for a compact runtime control panel.
        # Save-file presets are deliberately hidden because they cannot mutate
        # the running game's profile/mission state safely.
        self.ui_groups['live_runtime'] = QGroupBox(self.loc['groups']['live_runtime'])
        live_layout = QGridLayout(self.ui_groups['live_runtime'])
        live_layout.setHorizontalSpacing(8)
        live_layout.setVerticalSpacing(6)
        for column in range(4):
            live_layout.setColumnStretch(column, 1)
        self.ui_labels['live_runtime_hint'] = QLabel(self.loc['labels']['live_runtime_hint'])
        self.ui_labels['live_runtime_hint'].setWordWrap(True)
        self.ui_labels['live_runtime_hint'].setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        live_layout.addWidget(self.ui_labels['live_runtime_hint'], 0, 0, 1, 4)

        self.live_runtime_buttons = {}
        self.live_runtime_button_keys = {}
        self.live_runtime_section_labels = {}
        self.live_runtime_value_labels = {}
        self.live_runtime_toggle_actions = {
            'toggle_no_spread', 'toggle_no_recoil', 'toggle_instant_reload',
            'toggle_no_overheat', 'toggle_health_lock',
            'toggle_shield_lock', 'toggle_repairkit_no_cd', 'toggle_skill_no_cd',
            'toggle_gadget_no_cd', 'toggle_stamina_lock', 'toggle_guaranteed_crit',
            'toggle_dedicated_drop_100', 'toggle_infinite_jump',
        }

        def add_section(row, key):
            label = QLabel(self.loc['labels'][key])
            label.setObjectName('liveRuntimeSection')
            label.setWordWrap(True)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            live_layout.addWidget(label, row, 0, 1, 4)
            self.live_runtime_section_labels[key] = label
            return row + 1

        def add_actions(row, actions, columns=2):
            span = 4 // columns
            for index, (key, action) in enumerate(actions):
                button = QPushButton(self.loc['buttons'][key])
                if action in self.live_runtime_toggle_actions:
                    button.setCheckable(True)
                    button.clicked.connect(
                        lambda checked=False, value=action: self.runtime_action_requested.emit(
                            value, {'enabled': bool(checked)}
                        )
                    )
                else:
                    button.clicked.connect(
                        lambda checked=False, value=action: self.runtime_action_requested.emit(value, {})
                    )
                live_layout.addWidget(
                    button,
                    row + index // columns,
                    (index % columns) * span,
                    1,
                    span,
                )
                if action == 'toggle_dedicated_drop_100':
                    button.setToolTip(self.loc['labels']['live_dedicated_drop_hint'])
                elif action == 'max_sdu_tokens':
                    button.setToolTip(self.loc['labels']['live_max_sdu_tokens_hint'])
                self.live_runtime_buttons[action] = button
                self.live_runtime_button_keys[action] = key
            return row + (len(actions) + columns - 1) // columns

        row = 1
        row = add_section(row, 'live_survival')
        row = add_actions(row, (
            ('toggle_health_lock', 'toggle_health_lock'),
            ('toggle_shield_lock', 'toggle_shield_lock'),
            ('toggle_demigod', 'toggle_demigod'),
            ('toggle_stamina_lock', 'toggle_stamina_lock'),
        ))
        row = add_section(row, 'live_weapon')
        row = add_actions(row, (
            ('toggle_infinite_ammo', 'toggle_infinite_ammo'),
            ('refill_ammo', 'refill_ammo'),
            ('toggle_instant_reload', 'toggle_instant_reload'),
            ('toggle_no_overheat', 'toggle_no_overheat'),
            ('toggle_no_spread', 'toggle_no_spread'),
            ('toggle_no_recoil', 'toggle_no_recoil'),
            ('toggle_guaranteed_crit', 'toggle_guaranteed_crit'),
        ))
        row = add_section(row, 'live_cooldown')
        row = add_actions(row, (
            ('toggle_repairkit_no_cd', 'toggle_repairkit_no_cd'),
            ('toggle_skill_no_cd', 'toggle_skill_no_cd'),
            ('toggle_gadget_no_cd', 'toggle_gadget_no_cd'),
        ))

        row = add_section(row, 'live_progress')
        row = add_actions(row, (
            ('max_money', 'max_currency'),
            ('max_eridium', 'max_eridium'),
            ('max_level', 'max_level'),
            ('max_specialization', 'max_specialization'),
            ('max_sdu_tokens', 'max_sdu_tokens'),
            ('toggle_infinite_jump', 'toggle_infinite_jump'),
        ))

        self.live_vault_card_combo = QComboBox(self)
        self.live_vault_card_level_edit = QLineEdit(self)
        self.live_vault_card_level_edit.setValidator(QIntValidator(0, 9_999_999, self))
        self.live_currency_combo = QComboBox(self)
        self.live_currency_amount_edit = QLineEdit(self)
        self.live_currency_amount_edit.setValidator(QIntValidator(1, 2147483647, self))
        self.live_currency_amount_edit.setText('1000')
        self.live_bank_size_edit = QLineEdit(self)
        self.live_bank_size_edit.setValidator(QIntValidator(1, 5000, self))

        resource_rows = (
            ('live_vault_card', self.live_vault_card_combo, self.live_vault_card_level_edit,
             'set_vault_card_level', 'set_vault_card_level', self._emit_set_vault_card_level),
            ('live_currency', self.live_currency_combo, self.live_currency_amount_edit,
             'give_currency', 'give_currency', self._emit_give_currency),
        )
        for label_key, selector, editor, button_key, action, callback in resource_rows:
            label = QLabel(self.loc['labels'][label_key])
            label.setWordWrap(True)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            selector.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            editor.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button = QPushButton(self.loc['buttons'][button_key])
            button.clicked.connect(callback)
            live_layout.addWidget(label, row, 0)
            controls = QHBoxLayout()
            controls.setContentsMargins(0, 0, 0, 0)
            controls.setSpacing(8)
            controls.addWidget(selector, 2)
            controls.addWidget(editor, 1)
            controls.addWidget(button, 1)
            live_layout.addLayout(controls, row, 1, 1, 3)
            self.live_runtime_value_labels[label_key] = label
            self.live_runtime_buttons[action] = button
            self.live_runtime_button_keys[action] = button_key
            row += 1

        bank_label = QLabel(self.loc['labels']['bank_size'])
        bank_label.setWordWrap(True)
        bank_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.live_bank_size_edit.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        bank_apply = QPushButton(self.loc['buttons']['apply_bank_size'])
        bank_apply.clicked.connect(self._emit_set_bank_size)
        live_layout.addWidget(bank_label, row, 0)
        bank_controls = QHBoxLayout()
        bank_controls.setContentsMargins(0, 0, 0, 0)
        bank_controls.setSpacing(8)
        bank_controls.addWidget(self.live_bank_size_edit, 3)
        bank_controls.addWidget(bank_apply, 1)
        live_layout.addLayout(bank_controls, row, 1, 1, 3)
        self.live_runtime_value_labels['bank_size'] = bank_label
        self.live_runtime_buttons['set_bank_size'] = bank_apply
        self.live_runtime_button_keys['set_bank_size'] = 'apply_bank_size'
        row += 1

        self.live_vault_card_combo.currentIndexChanged.connect(
            self._sync_live_vault_card_target
        )
        self.live_vault_card_level_edit.textChanged.connect(
            self._update_live_resource_button_state
        )
        self.live_currency_combo.currentIndexChanged.connect(
            self._update_live_resource_button_state
        )
        self.live_currency_amount_edit.textChanged.connect(
            self._update_live_resource_button_state
        )
        self.live_bank_size_edit.textChanged.connect(
            self._update_live_resource_button_state
        )
        self._refresh_live_resource_controls()

        row = add_section(row, 'live_tuning')
        self.live_fire_rate_combo = QComboBox(self)
        for value in (1, 2, 5, 10, 20):
            self.live_fire_rate_combo.addItem(f'{value}x', float(value))
        self.live_movement_combo = QComboBox(self)
        for value in (1, 1.5, 2, 3, 5, 10):
            self.live_movement_combo.addItem(f'{value:g}x', float(value))
        self.live_jump_combo = QComboBox(self)
        for value in (1, 1.5, 2, 3, 5, 10):
            self.live_jump_combo.addItem(f'{value:g}x', float(value))
        self.live_critical_damage_combo = QComboBox(self)
        for value in (1, 2, 5, 10, 20, 50):
            self.live_critical_damage_combo.addItem(f'{value:g}x', float(value))
        self.live_experience_reward_combo = QComboBox(self)
        self.live_cash_reward_combo = QComboBox(self)
        self.live_eridium_reward_combo = QComboBox(self)
        for combo in (
            self.live_experience_reward_combo,
            self.live_cash_reward_combo,
            self.live_eridium_reward_combo,
        ):
            for value in (1, 2, 3, 5, 10):
                combo.addItem(f'{value}x', float(value))
        self.live_backpack_edit = QLineEdit(self)
        self.live_backpack_edit.setValidator(QIntValidator(20, 5000, self))
        self.live_backpack_edit.setText('999')
        self.live_base_fov_edit = QLineEdit(self)
        self.live_viewmodel_fov_edit = QLineEdit(self)
        for editor, minimum in (
            (self.live_base_fov_edit, 60.0),
            (self.live_viewmodel_fov_edit, 40.0),
        ):
            validator = QDoubleValidator(minimum, 150.0, 2, editor)
            validator.setLocale(QLocale.c())
            editor.setValidator(validator)
        self.live_magazine_capacity_edit = QLineEdit(self)
        self.live_projectile_speed_edit = QLineEdit(self)
        for editor in (self.live_magazine_capacity_edit, self.live_projectile_speed_edit):
            validator = QDoubleValidator(0.1, 100.0, 2, editor)
            validator.setLocale(QLocale.c())
            editor.setValidator(validator)
            editor.setText('1')

        tuning_rows = (
            ('fire_rate_scale', self.live_fire_rate_combo, 'apply_fire_rate', 'set_fire_rate',
             lambda: {'value': self.live_fire_rate_combo.currentData()}),
            ('movement_speed_scale', self.live_movement_combo, 'apply_movement_speed', 'set_movement_speed',
             lambda: {'value': self.live_movement_combo.currentData()}),
            ('jump_height_scale', self.live_jump_combo, 'apply_jump_height', 'set_jump_height',
             lambda: {'value': self.live_jump_combo.currentData()}),
            ('critical_damage_scale', self.live_critical_damage_combo, 'apply_critical_damage', 'set_critical_damage',
             lambda: {'value': self.live_critical_damage_combo.currentData()}),
            ('experience_reward_scale', self.live_experience_reward_combo,
             'apply_experience_multiplier', 'set_experience_multiplier',
             lambda: {'value': self.live_experience_reward_combo.currentData()}),
            ('cash_reward_scale', self.live_cash_reward_combo,
             'apply_cash_multiplier', 'set_cash_multiplier',
             lambda: {'value': self.live_cash_reward_combo.currentData()}),
            ('eridium_reward_scale', self.live_eridium_reward_combo,
             'apply_eridium_multiplier', 'set_eridium_multiplier',
             lambda: {'value': self.live_eridium_reward_combo.currentData()}),
            ('backpack_size', self.live_backpack_edit, 'apply_backpack_size', 'set_backpack_size',
             lambda: {'value': int(self.live_backpack_edit.text() or 0)}),
            ('base_fov', self.live_base_fov_edit, 'apply_base_fov', ('set_fov', 'set_base_fov'),
             lambda: {'base_fov': float(self.live_base_fov_edit.text() or 0)}),
            ('viewmodel_fov', self.live_viewmodel_fov_edit, 'apply_viewmodel_fov', ('set_fov', 'set_viewmodel_fov'),
             lambda: {'viewmodel_fov': float(self.live_viewmodel_fov_edit.text() or 0)}),
            ('magazine_capacity_scale', self.live_magazine_capacity_edit,
             'apply_magazine_capacity', 'set_magazine_capacity_scale',
             lambda: {'value': float(self.live_magazine_capacity_edit.text() or 1)}),
            ('projectile_speed_scale', self.live_projectile_speed_edit,
             'apply_projectile_speed', 'set_projectile_speed_scale',
             lambda: {'value': float(self.live_projectile_speed_edit.text() or 1)}),
        )
        for label_key, editor, button_key, action, params in tuning_rows:
            emit_action, registry_action = action if isinstance(action, tuple) else (action, action)
            label = QLabel(self.loc['labels'][label_key])
            label.setWordWrap(True)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            editor.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            self.live_runtime_value_labels[label_key] = label
            button = QPushButton(self.loc['buttons'][button_key])
            button.clicked.connect(
                lambda checked=False, value=emit_action, make_params=params: self.runtime_action_requested.emit(
                    value, make_params()
                )
            )
            live_layout.addWidget(label, row, 0)
            live_layout.addWidget(editor, row, 1, 1, 2)
            live_layout.addWidget(button, row, 3)
            self.live_runtime_buttons[registry_action] = button
            self.live_runtime_button_keys[registry_action] = button_key
            self.live_runtime_buttons.setdefault(emit_action, button)
            self.live_runtime_button_keys.setdefault(emit_action, button_key)
            row += 1

        reset_fov = QPushButton(self.loc['buttons']['reset_fov'])
        reset_fov.clicked.connect(
            lambda checked=False: self.runtime_action_requested.emit('reset_fov', {})
        )
        live_layout.addWidget(reset_fov, row, 0, 1, 4)
        self.live_runtime_buttons['reset_fov'] = reset_fov
        self.live_runtime_button_keys['reset_fov'] = 'reset_fov'
        row += 1

        row = add_section(row, 'live_position')
        self.live_position_value = QLabel(self.loc['labels']['position_unavailable'])
        self.live_position_value.setWordWrap(True)
        self.live_position_value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        position_refresh = QPushButton(self.loc['buttons']['refresh_position'])
        position_refresh.clicked.connect(
            lambda checked=False: self.runtime_action_requested.emit('position_state', {})
        )
        live_layout.addWidget(self.live_position_value, row, 0, 1, 3)
        live_layout.addWidget(position_refresh, row, 3)
        self.live_runtime_buttons['position_state'] = position_refresh
        self.live_runtime_button_keys['position_state'] = 'refresh_position'
        row += 1

        self.live_bookmark_name_edit = QLineEdit(self)
        self.live_bookmark_name_edit.setPlaceholderText(self.loc['labels']['bookmark_name'])
        save_bookmark = QPushButton(self.loc['buttons']['save_position'])
        save_bookmark.clicked.connect(self._save_position_bookmark)
        live_layout.addWidget(self.live_bookmark_name_edit, row, 0, 1, 3)
        live_layout.addWidget(save_bookmark, row, 3)
        self.live_save_bookmark_button = save_bookmark
        row += 1

        self.live_bookmark_combo = QComboBox(self)
        self.live_bookmark_combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        teleport_button = QPushButton(self.loc['buttons']['teleport_position'])
        delete_button = QPushButton(self.loc['buttons']['delete_position'])
        teleport_button.clicked.connect(self._teleport_position_bookmark)
        delete_button.clicked.connect(self._delete_position_bookmark)
        live_layout.addWidget(self.live_bookmark_combo, row, 0, 1, 4)
        row += 1
        live_layout.addWidget(teleport_button, row, 0, 1, 2)
        live_layout.addWidget(delete_button, row, 2, 1, 2)
        self.live_runtime_buttons['teleport_position'] = teleport_button
        self.live_runtime_button_keys['teleport_position'] = 'teleport_position'
        self.live_delete_bookmark_button = delete_button
        self.live_bookmark_combo.currentIndexChanged.connect(self._update_position_controls)
        self._refresh_position_bookmarks()
        row += 1

        row = add_section(row, 'live_lost_loot')
        self.live_lost_loot_value = QLabel(self.loc['labels']['lost_loot_unavailable'])
        self.live_lost_loot_value.setWordWrap(True)
        self.live_lost_loot_value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lost_refresh = QPushButton(self.loc['buttons']['refresh_lost_loot'])
        lost_claim = QPushButton(self.loc['buttons']['claim_lost_loot'])
        lost_refresh.clicked.connect(
            lambda checked=False: self.runtime_action_requested.emit('lost_loot_state', {})
        )
        lost_claim.clicked.connect(
            lambda checked=False: self.runtime_action_requested.emit('claim_lost_loot', {})
        )
        live_layout.addWidget(self.live_lost_loot_value, row, 0, 1, 4)
        row += 1
        live_layout.addWidget(lost_refresh, row, 0, 1, 2)
        live_layout.addWidget(lost_claim, row, 2, 1, 2)
        self.live_runtime_buttons['lost_loot_state'] = lost_refresh
        self.live_runtime_button_keys['lost_loot_state'] = 'refresh_lost_loot'
        self.live_runtime_buttons['claim_lost_loot'] = lost_claim
        self.live_runtime_button_keys['claim_lost_loot'] = 'claim_lost_loot'
        self._refresh_lost_loot_display()
        row += 1

        row = add_section(row, 'live_loot')
        self.live_dedicated_drop_combo = QComboBox(self)
        for value in range(1, 11):
            self.live_dedicated_drop_combo.addItem(f'{value}x', value)
        dedicated_label = QLabel(self.loc['labels']['dedicated_drop_multiplier'])
        dedicated_label.setWordWrap(True)
        dedicated_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.live_dedicated_drop_combo.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        self.live_runtime_value_labels['dedicated_drop_multiplier'] = dedicated_label
        dedicated_apply = QPushButton(self.loc['buttons']['apply_dedicated_drop_multiplier'])
        dedicated_apply.clicked.connect(
            lambda checked=False: self.runtime_action_requested.emit(
                'set_dedicated_drop_multiplier',
                {'value': int(self.live_dedicated_drop_combo.currentData() or 1)},
            )
        )
        live_layout.addWidget(dedicated_label, row, 0)
        live_layout.addWidget(self.live_dedicated_drop_combo, row, 1, 1, 2)
        live_layout.addWidget(dedicated_apply, row, 3)
        self.live_runtime_buttons['set_dedicated_drop_multiplier'] = dedicated_apply
        self.live_runtime_button_keys['set_dedicated_drop_multiplier'] = 'apply_dedicated_drop_multiplier'
        row += 1
        row = add_actions(row, (
            ('toggle_dedicated_drop_100', 'toggle_dedicated_drop_100'),
            ('rarity_legendary', 'rarity_legendary'),
            ('rarity_pearlescent', 'rarity_pearlescent'),
            ('rarity_reset', 'rarity_reset'),
            ('reset_runtime_modifiers', 'reset_runtime_modifiers'),
        ))

        self.ui_labels['live_runtime_status'] = QLabel(self.loc['labels']['live_runtime_idle'])
        self.ui_labels['live_runtime_status'].setWordWrap(True)
        self.ui_labels['live_runtime_status'].setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        live_layout.addWidget(self.ui_labels['live_runtime_status'], row, 0, 1, 4)
        main_layout.addWidget(self.ui_groups['live_runtime'])
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
                "groups": {"character_info": "Character", "currency": "Currency", "world_presets": "Profile / Shared", "char_presets": "Character Save", "live_runtime": "Live Runtime"},
                "labels": {
                    "name": "Name:", "difficulty": "Difficulty:", "level": "Level:", "xp": "XP:",
                    "spec_level": "Spec Level:", "spec_points": "Spec Points:", "money": "Money:", "eridium": "Eridium:",
                    "vault_card_tokens": "Vault Card {number} Tokens:",
                    "xp_auto_hint": "Enter your target level to auto-calculate the required XP",
                    "profile_only_hint": "Profile save only. Disabled on character saves.",
                    "character_only_hint": "Character save only. Disabled on profile saves.",
                    "preset_mode_profile": "Current save type: Profile. Profile presets enabled, character presets disabled.",
                    "preset_mode_character": "Current save type: Character save. Character presets enabled, profile presets disabled.",
                    "live_runtime_hint": "Runtime controls affect only the current game session and automatically follow weapon swaps.",
                    "live_runtime_idle": "Ready.",
                    "live_dedicated_drop_hint": "Adds guaranteed draws only from the defeated actor's NCS dedicated pool. The multiplier controls the extra draws; world-drop pools are not added.",
                    "live_max_sdu_tokens_hint": "Tops up ECHO/SDU tokens without reducing existing higher values or forcing mission/equipment-slot unlocks.",
                    "live_survival": "Survival / movement",
                    "live_weapon": "Weapon handling",
                    "live_cooldown": "Cooldowns",
                    "live_progress": "Progression / currency",
                    "live_tuning": "Scalars / capacity",
                    "live_loot": "Loot rarity",
                    "live_vault_card": "Vault Card",
                    "live_vault_card_item": "{name} · Lv{level}",
                    "live_currency": "Currency",
                    "live_currency_item": "{name} · {amount}",
                    "bank_size": "Bank capacity",
                    "base_fov": "Base FOV", "viewmodel_fov": "Viewmodel FOV",
                    "magazine_capacity_scale": "Magazine capacity",
                    "projectile_speed_scale": "Projectile speed",
                    "live_position": "Position bookmarks", "position_unavailable": "Position unavailable.",
                    "position_value": "{map} · X {x:.1f} · Y {y:.1f} · Z {z:.1f}",
                    "bookmark_name": "Bookmark name", "bookmark_default": "Bookmark {number}",
                    "bookmark_item": "{name} · {map}", "position_map_mismatch": "Bookmark is on another map.",
                    "live_lost_loot": "Lost Loot", "lost_loot_unavailable": "Lost Loot is unavailable.",
                    "lost_loot_value": "{count} item(s) · {free_slots} free backpack slot(s)",
                    "vault_card_name": "Vault Card {number}", "live_currency_cash": "Cash",
                    "live_currency_eridium": "Eridium",
                    "fire_rate_scale": "Fire rate",
                    "movement_speed_scale": "Movement speed",
                    "jump_height_scale": "Jump height",
                    "critical_damage_scale": "Critical damage",
                    "experience_reward_scale": "Combat XP multiplier",
                    "cash_reward_scale": "Cash multiplier",
                    "eridium_reward_scale": "Eridium multiplier",
                    "dedicated_drop_multiplier": "Dedicated drop multiplier",
                    "backpack_size": "Backpack capacity",
                    "preset_credit": ""
                },
                "buttons": {"apply_changes": "Apply Changes", "apply_profile_changes": "Apply Profile Currency Changes", "sync_levels": "Sync Item Levels", "toggle_infinite_ammo": "Toggle Infinite Ammo", "refill_ammo": "Refill Ammo", "toggle_demigod": "Toggle Demigod", "toggle_health_lock": "Health Lock", "toggle_shield_lock": "Shield Lock", "toggle_stamina_lock": "Unlimited Vault Power", "toggle_instant_reload": "Instant Reload", "toggle_no_overheat": "No Overheat", "toggle_no_spread": "No Spread", "toggle_no_recoil": "No Recoil", "toggle_guaranteed_crit": "Guaranteed Crit", "toggle_repairkit_no_cd": "Repkit No CD", "toggle_skill_no_cd": "Skill No CD", "toggle_gadget_no_cd": "Gear No CD", "toggle_dedicated_drop_100": "Dedicated Drop 100%", "max_money": "Max Money", "max_eridium": "Max Eridium", "max_level": "Max Character Level", "max_specialization": "Max Specialization", "max_sdu_tokens": "Max SDU Tokens", "toggle_infinite_jump": "Infinite Jump", "set_vault_card_level": "Set Level", "give_currency": "Add", "apply_bank_size": "Apply", "apply_fire_rate": "Apply", "apply_movement_speed": "Apply", "apply_jump_height": "Apply", "apply_critical_damage": "Apply", "apply_experience_multiplier": "Apply", "apply_cash_multiplier": "Apply", "apply_eridium_multiplier": "Apply", "apply_backpack_size": "Apply", "apply_base_fov": "Apply", "apply_viewmodel_fov": "Apply", "apply_magazine_capacity": "Apply", "apply_projectile_speed": "Apply", "reset_fov": "Reset FOV", "refresh_position": "Refresh", "save_position": "Save", "teleport_position": "Teleport", "delete_position": "Delete", "refresh_lost_loot": "Refresh", "claim_lost_loot": "Claim", "apply_dedicated_drop_multiplier": "Apply", "rarity_legendary": "Legendary Drops", "rarity_pearlescent": "Pearlescent Drops", "rarity_reset": "Reset Drop Rates", "reset_runtime_modifiers": "Reset Session Mods"},
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
        self.loc["groups"].setdefault("live_runtime", "Live Runtime")

        self.loc["labels"].setdefault("profile_only_hint", "Profile save only. Disabled on character saves.")
        self.loc["labels"].setdefault("character_only_hint", "Character save only. Disabled on profile saves.")
        self.loc["labels"].setdefault("preset_mode_profile", "Current save type: Profile. Profile presets enabled, character presets disabled.")
        self.loc["labels"].setdefault("preset_mode_character", "Current save type: Character save. Character presets enabled, profile presets disabled.")
        self.loc["labels"].setdefault("live_runtime_hint", "Runtime controls affect only the current game session and automatically follow weapon swaps.")
        self.loc["labels"].setdefault("live_runtime_idle", "Ready.")
        self.loc["labels"].setdefault("live_dedicated_drop_hint", "Adds guaranteed draws only from the defeated actor's NCS dedicated pool. The multiplier controls the extra draws; world-drop pools are not added.")
        self.loc["labels"].setdefault("live_max_sdu_tokens_hint", "Tops up ECHO/SDU tokens without reducing existing higher values or forcing mission/equipment-slot unlocks.")
        for key, value in {
            "live_survival": "Survival / movement", "live_weapon": "Weapon handling",
            "live_cooldown": "Cooldowns", "live_progress": "Progression / currency",
            "live_tuning": "Scalars / capacity",
            "live_loot": "Loot rarity", "fire_rate_scale": "Fire rate",
            "movement_speed_scale": "Movement speed", "backpack_size": "Backpack capacity",
            "jump_height_scale": "Jump height", "critical_damage_scale": "Critical damage",
            "experience_reward_scale": "Combat XP multiplier",
            "cash_reward_scale": "Cash multiplier", "eridium_reward_scale": "Eridium multiplier",
            "dedicated_drop_multiplier": "Dedicated drop multiplier",
            "live_vault_card": "Vault Card", "live_currency": "Currency",
            "live_vault_card_item": "{name} · Lv{level}",
            "live_currency_item": "{name} · {amount}",
            "bank_size": "Bank capacity",
            "base_fov": "Base FOV", "viewmodel_fov": "Viewmodel FOV",
            "magazine_capacity_scale": "Magazine capacity", "projectile_speed_scale": "Projectile speed",
            "live_position": "Position bookmarks", "position_unavailable": "Position unavailable.",
            "position_value": "{map} · X {x:.1f} · Y {y:.1f} · Z {z:.1f}",
            "bookmark_name": "Bookmark name", "bookmark_default": "Bookmark {number}",
            "bookmark_item": "{name} · {map}", "position_map_mismatch": "Bookmark is on another map.",
            "live_lost_loot": "Lost Loot", "lost_loot_unavailable": "Lost Loot is unavailable.",
            "lost_loot_value": "{count} item(s) · {free_slots} free backpack slot(s)",
            "vault_card_name": "Vault Card {number}", "live_currency_cash": "Cash",
            "live_currency_eridium": "Eridium",
        }.items():
            self.loc["labels"].setdefault(key, value)
        self.loc["labels"].setdefault("preset_credit", "")
        self.loc["labels"].setdefault("vault_card_tokens", "Vault Card {number} Tokens:")
        self.loc["buttons"].setdefault("apply_profile_changes", "Apply Profile Currency Changes")
        self.loc["buttons"].setdefault("toggle_infinite_ammo", "Toggle Infinite Ammo")
        self.loc["buttons"].setdefault("toggle_demigod", "Toggle Demigod")
        for key, value in {
            "toggle_health_lock": "Health Lock", "toggle_shield_lock": "Shield Lock",
            "toggle_stamina_lock": "Unlimited Vault Power",
            "refill_ammo": "Refill Ammo",
            "toggle_instant_reload": "Instant Reload", "toggle_no_overheat": "No Overheat",
            "toggle_no_spread": "No Spread", "toggle_no_recoil": "No Recoil",
            "toggle_guaranteed_crit": "Guaranteed Crit", "toggle_repairkit_no_cd": "Repkit No CD",
            "toggle_skill_no_cd": "Skill No CD", "toggle_gadget_no_cd": "Gear No CD",
            "toggle_dedicated_drop_100": "Dedicated Drop 100%",
            "max_money": "Max Money", "max_eridium": "Max Eridium",
            "max_level": "Max Character Level", "max_specialization": "Max Specialization",
            "max_sdu_tokens": "Max SDU Tokens",
            "toggle_infinite_jump": "Infinite Jump",
            "set_vault_card_level": "Set Level", "give_currency": "Add",
            "apply_bank_size": "Apply",
            "apply_fire_rate": "Apply", "apply_movement_speed": "Apply",
            "apply_jump_height": "Apply", "apply_critical_damage": "Apply",
            "apply_experience_multiplier": "Apply", "apply_cash_multiplier": "Apply",
            "apply_eridium_multiplier": "Apply",
            "apply_backpack_size": "Apply", "apply_base_fov": "Apply",
            "apply_viewmodel_fov": "Apply", "apply_magazine_capacity": "Apply",
            "apply_projectile_speed": "Apply", "reset_fov": "Reset FOV",
            "refresh_position": "Refresh", "save_position": "Save",
            "teleport_position": "Teleport", "delete_position": "Delete",
            "refresh_lost_loot": "Refresh", "claim_lost_loot": "Claim",
            "apply_dedicated_drop_multiplier": "Apply",
            "reset_runtime_modifiers": "Reset Session Mods",
        }.items():
            self.loc["buttons"].setdefault(key, value)
        self.loc["buttons"].setdefault("rarity_legendary", "Legendary Drops")
        self.loc["buttons"].setdefault("rarity_pearlescent", "Pearlescent Drops")
        self.loc["buttons"].setdefault("rarity_reset", "Reset Drop Rates")
        self.loc["presets"].setdefault("unlock_vault_cards", "Unlock All Vault Card Rewards")
        self.loc["presets"].setdefault("max_ammo", "Refill Ammo")

    def _vault_card_label(self, card):
        number = card.get('number', card.get('card_id', ''))
        return self.loc['labels'].get('vault_card_tokens', 'Vault Card {number} Tokens:').format(number=number)

    def update_language(self, lang):
        self.current_lang = lang
        self._load_localization()
        
        # Groups
        self.ui_groups['character_info'].setTitle(self.loc['groups']['character_info'])
        self.ui_groups['currency'].setTitle(self.loc['groups']['currency'])
        self.ui_groups['world_presets'].setTitle(self.loc['groups']['world_presets'])
        self.ui_groups['char_presets'].setTitle(self.loc['groups']['char_presets'])
        self.ui_groups['live_runtime'].setTitle(self.loc['groups']['live_runtime'])
        
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
        self.ui_labels['live_runtime_hint'].setText(self.loc['labels']['live_runtime_hint'])
        self.ui_labels['live_runtime_status'].setText(self.loc['labels']['live_runtime_idle'])
        self.ui_labels['live_runtime_status'].setStyleSheet("")
        self.live_bookmark_name_edit.setPlaceholderText(self.loc['labels']['bookmark_name'])
        
        # Buttons
        self.ui_buttons['sync_levels'].setText(self.loc['buttons']['sync_levels'])
        
        # Dynamic Buttons
        for key, btn in self.world_btns_widgets:
            btn.setText(self.loc['presets'][key])
            
        for key, btn in self.char_btns_widgets:
            btn.setText(self.loc['presets'][key])

        for action, btn in self.live_runtime_buttons.items():
            key = self.live_runtime_button_keys.get(action, action)
            btn.setText(self.loc['buttons'][key])
        dedicated_button = self.live_runtime_buttons.get('toggle_dedicated_drop_100')
        if dedicated_button is not None:
            dedicated_button.setToolTip(self.loc['labels']['live_dedicated_drop_hint'])
        sdu_button = self.live_runtime_buttons.get('max_sdu_tokens')
        if sdu_button is not None:
            sdu_button.setToolTip(self.loc['labels']['live_max_sdu_tokens_hint'])
        for key, label in self.live_runtime_section_labels.items():
            label.setText(self.loc['labels'][key])
        for key, label in self.live_runtime_value_labels.items():
            label.setText(self.loc['labels'][key])
        self._refresh_live_resource_controls()
        self._refresh_position_bookmarks()
        self._refresh_position_display()
        self._refresh_lost_loot_display()

        self._apply_preset_button_state()

    def _apply_preset_button_state(self):
        if self._live_mode:
            for _, btn in self.world_btns_widgets + self.char_btns_widgets:
                btn.setEnabled(False)
            self.ui_groups['character_info'].setVisible(True)
            self.ui_groups['currency'].setVisible(False)
            self.ui_groups['world_presets'].setVisible(False)
            self.ui_groups['char_presets'].setVisible(False)
            self.ui_groups['live_runtime'].setVisible(True)
            self.ui_buttons['apply_changes'].setVisible(False)
            self.ui_buttons['sync_levels'].setVisible(False)
            self.ui_labels['sync_warning'].setVisible(False)
            self.ui_labels['preset_mode_hint'].setVisible(False)
            self.ui_labels['xp_auto_hint'].setVisible(False)
            return

        for _, btn in self.world_btns_widgets:
            btn.setEnabled(self.is_profile_save)

        for _, btn in self.char_btns_widgets:
            btn.setEnabled(not self.is_profile_save)

        self.ui_groups['character_info'].setVisible(not self.is_profile_save)
        self.ui_groups['currency'].setVisible(True)
        self.ui_groups['world_presets'].setVisible(True)
        self.ui_groups['char_presets'].setVisible(True)
        self.ui_groups['live_runtime'].setVisible(False)
        self.ui_buttons['apply_changes'].setVisible(True)
        self.ui_labels['preset_mode_hint'].setVisible(True)
        self.ui_labels['xp_auto_hint'].setVisible(not self.is_profile_save)
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

    def set_live_mode(self, enabled: bool):
        self._live_mode = bool(enabled)
        edits = [
            self.name_edit, self.difficulty_edit, self.level_edit, self.xp_edit,
            self.spec_level_edit, self.spec_points_edit, self.money_edit,
            self.eridium_edit, *self.vault_card_edits.values(),
        ]
        for edit in edits:
            edit.setReadOnly(self._live_mode or edit is self.xp_edit)
        self._apply_preset_button_state()

    def set_runtime_result(self, message: str, ok: bool = True):
        label = self.ui_labels['live_runtime_status']
        label.setText(str(message or self.loc['labels']['live_runtime_idle']))
        label.setStyleSheet("color: #78dba9;" if ok else "color: #ff6b6b;")

    def set_runtime_busy(self, busy: bool):
        self._runtime_busy = bool(busy)
        for button in set(self.live_runtime_buttons.values()):
            button.setEnabled(not self._runtime_busy)
        if not self._runtime_busy:
            self._update_live_resource_button_state()
            self._update_position_controls()
            self._refresh_lost_loot_display()

    def set_inventory_mutation_blocked(self, blocked: bool):
        self._inventory_mutation_blocked = bool(blocked)
        self._refresh_lost_loot_display()

    def _refresh_live_resource_controls(self):
        current_vault = self.live_vault_card_combo.currentData()
        self.live_vault_card_combo.blockSignals(True)
        self.live_vault_card_combo.clear()
        for card in self._live_vault_cards:
            name = self._friendly_live_resource_name(
                card.get('name') or card.get('token') or card.get('track', '')
            )
            level = int(card.get('level', 0) or 0)
            text = self.loc['labels']['live_vault_card_item'].format(name=name, level=level)
            self.live_vault_card_combo.addItem(text, dict(card))
        self.live_vault_card_combo.blockSignals(False)
        if isinstance(current_vault, dict):
            for index in range(self.live_vault_card_combo.count()):
                card = self.live_vault_card_combo.itemData(index)
                if card.get('track') == current_vault.get('track'):
                    self.live_vault_card_combo.setCurrentIndex(index)
                    break

        current_currency = self.live_currency_combo.currentData()
        self.live_currency_combo.clear()
        for currency in self._live_currencies:
            name = self._friendly_live_resource_name(
                currency.get('name') or currency.get('token') or ''
            )
            amount = int(currency.get('amount', 0) or 0)
            text = self.loc['labels']['live_currency_item'].format(name=name, amount=f'{amount:,}')
            self.live_currency_combo.addItem(text, dict(currency))
        if isinstance(current_currency, dict):
            for index in range(self.live_currency_combo.count()):
                currency = self.live_currency_combo.itemData(index)
                if currency.get('token') == current_currency.get('token'):
                    self.live_currency_combo.setCurrentIndex(index)
                    break

        self._sync_live_vault_card_target()
        self._update_live_resource_button_state()

    def _friendly_live_resource_name(self, value):
        name = str(value or '').strip()
        match = re.search(r'VaultCard0*(\d+)_(?:Experience|Tokens)$', name, re.IGNORECASE)
        if match:
            return self.loc['labels']['vault_card_name'].format(number=int(match.group(1)))
        normalized = re.sub(r'[^a-z0-9]+', '', name.casefold())
        if normalized in {'cash', 'money', 'currencycash'}:
            return self.loc['labels']['live_currency_cash']
        if normalized in {'eridium', 'eridiumcurrency', 'currencyeridium'}:
            return self.loc['labels']['live_currency_eridium']
        return name

    def _sync_live_vault_card_target(self):
        card = self.live_vault_card_combo.currentData()
        if isinstance(card, dict):
            self.live_vault_card_level_edit.setText(str(int(card.get('level', 0) or 0)))
        elif not self.live_vault_card_level_edit.hasFocus():
            self.live_vault_card_level_edit.clear()
        self._update_live_resource_button_state()

    def _update_live_resource_button_state(self):
        controls = (
            ('set_vault_card_level', self.live_vault_card_combo.count() > 0
             and bool(self.live_vault_card_level_edit.text().strip())),
            ('give_currency', self.live_currency_combo.count() > 0
             and bool(self.live_currency_amount_edit.text().strip())),
            ('set_bank_size', bool(self.live_bank_size_edit.text().strip())),
        )
        for action, enabled in controls:
            button = self.live_runtime_buttons.get(action)
            if button is not None:
                button.setEnabled(bool(enabled) and not self._runtime_busy)

    def _emit_set_vault_card_level(self):
        card = self.live_vault_card_combo.currentData()
        if not isinstance(card, dict) or not self.live_vault_card_level_edit.text().strip():
            return
        params = {'level': int(self.live_vault_card_level_edit.text())}
        if card.get('track') is not None:
            params['track'] = int(card['track'])
        elif card.get('token'):
            params['token'] = str(card['token'])
        else:
            return
        self.runtime_action_requested.emit('set_vault_card_level', params)

    def _emit_give_currency(self):
        currency = self.live_currency_combo.currentData()
        if not isinstance(currency, dict) or not self.live_currency_amount_edit.text().strip():
            return
        token = str(currency.get('token') or '').strip()
        kind = str(currency.get('kind') or currency.get('currency') or '').strip()
        params = {'amount': int(self.live_currency_amount_edit.text())}
        if token:
            params['token'] = token
        elif kind:
            params['kind'] = kind
        else:
            return
        self.runtime_action_requested.emit('give_currency', params)

    def _emit_set_bank_size(self):
        if self.live_bank_size_edit.text().strip():
            self.runtime_action_requested.emit(
                'set_bank_size', {'value': int(self.live_bank_size_edit.text())}
            )

    def _load_position_bookmarks(self):
        raw = self._settings.value('live/position_bookmarks', '[]')
        try:
            rows = json.loads(str(raw or '[]'))
        except (TypeError, ValueError):
            return []
        result = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or not str(row.get('map') or '').strip():
                continue
            try:
                result.append({
                    'name': str(row.get('name') or '').strip(),
                    'map': str(row['map']),
                    **{key: float(row.get(key, 0.0) or 0.0)
                       for key in ('x', 'y', 'z', 'pitch', 'yaw', 'roll')},
                })
            except (TypeError, ValueError):
                continue
        return result[:100]

    def _store_position_bookmarks(self):
        self._settings.setValue(
            'live/position_bookmarks',
            json.dumps(self._position_bookmarks, ensure_ascii=False, separators=(',', ':')),
        )

    def _refresh_position_bookmarks(self):
        current = self.live_bookmark_combo.currentData() if hasattr(self, 'live_bookmark_combo') else None
        self.live_bookmark_combo.blockSignals(True)
        self.live_bookmark_combo.clear()
        for index, bookmark in enumerate(self._position_bookmarks, 1):
            name = bookmark.get('name') or self.loc['labels']['bookmark_default'].format(number=index)
            self.live_bookmark_combo.addItem(
                self.loc['labels']['bookmark_item'].format(name=name, map=bookmark['map']),
                dict(bookmark),
            )
        if isinstance(current, dict):
            for index in range(self.live_bookmark_combo.count()):
                candidate = self.live_bookmark_combo.itemData(index)
                if candidate == current:
                    self.live_bookmark_combo.setCurrentIndex(index)
                    break
        self.live_bookmark_combo.blockSignals(False)
        self._update_position_controls()

    def _save_position_bookmark(self):
        if not self._position_available():
            self.set_runtime_result(self.loc['labels']['position_unavailable'], False)
            return
        name = self.live_bookmark_name_edit.text().strip()
        if not name:
            name = self.loc['labels']['bookmark_default'].format(
                number=len(self._position_bookmarks) + 1
            )
        bookmark = {
            'name': name,
            'map': str(self._live_position['map']),
            **{key: float(self._live_position.get(key, 0.0) or 0.0)
               for key in ('x', 'y', 'z', 'pitch', 'yaw', 'roll')},
        }
        self._position_bookmarks.append(bookmark)
        self._store_position_bookmarks()
        self.live_bookmark_name_edit.clear()
        self._refresh_position_bookmarks()
        self.live_bookmark_combo.setCurrentIndex(self.live_bookmark_combo.count() - 1)

    def _teleport_position_bookmark(self):
        bookmark = self.live_bookmark_combo.currentData()
        if not isinstance(bookmark, dict):
            return
        current_map = str(self._live_position.get('map') or '').strip()
        if (
            not current_map
            or str(bookmark.get('map') or '').strip().casefold() != current_map.casefold()
        ):
            self.set_runtime_result(self.loc['labels']['position_map_mismatch'], False)
            return
        self.runtime_action_requested.emit('teleport_position', dict(bookmark))

    def _delete_position_bookmark(self):
        index = self.live_bookmark_combo.currentIndex()
        if 0 <= index < len(self._position_bookmarks):
            del self._position_bookmarks[index]
            self._store_position_bookmarks()
            self._refresh_position_bookmarks()

    def _position_available(self):
        return bool(self._live_position.get('available', True)) and bool(
            str(self._live_position.get('map') or '').strip()
        )

    def _update_position_controls(self):
        current_ok = self._position_available()
        bookmark = self.live_bookmark_combo.currentData()
        has_bookmark = isinstance(bookmark, dict)
        same_map = has_bookmark and current_ok and (
            str(bookmark.get('map') or '').strip().casefold()
            == str(self._live_position.get('map') or '').strip().casefold()
        )
        if hasattr(self, 'live_save_bookmark_button'):
            self.live_save_bookmark_button.setEnabled(current_ok)
        button = self.live_runtime_buttons.get('teleport_position') if hasattr(self, 'live_runtime_buttons') else None
        if button is not None:
            button.setEnabled(bool(same_map) and not self._runtime_busy)
        if hasattr(self, 'live_delete_bookmark_button'):
            self.live_delete_bookmark_button.setEnabled(has_bookmark)

    def _refresh_position_display(self):
        if not self._position_available():
            self.live_position_value.setText(self.loc['labels']['position_unavailable'])
        else:
            position = self._live_position
            self.live_position_value.setText(self.loc['labels']['position_value'].format(
                map=position.get('map', ''),
                x=float(position.get('x', 0.0) or 0.0),
                y=float(position.get('y', 0.0) or 0.0),
                z=float(position.get('z', 0.0) or 0.0),
            ))
        self._update_position_controls()

    def _refresh_lost_loot_display(self):
        state = self._live_lost_loot
        available = bool(state.get('available', False))
        count = int(state.get('count', 0) or 0)
        free_slots = int(state.get('free_slots', 0) or 0)
        if available:
            self.live_lost_loot_value.setText(self.loc['labels']['lost_loot_value'].format(
                count=count, free_slots=free_slots
            ))
        else:
            self.live_lost_loot_value.setText(self.loc['labels']['lost_loot_unavailable'])
        button = self.live_runtime_buttons.get('claim_lost_loot')
        if button is not None:
            button.setEnabled(
                available and count > 0 and free_slots >= count
                and not self._runtime_busy and not self._inventory_mutation_blocked
            )

    def apply_runtime_state(self, state: Dict[str, Any]):
        if not isinstance(state, dict):
            return
        action_to_feature = {
            'toggle_no_spread': 'no_spread', 'toggle_no_recoil': 'no_recoil',
            'toggle_instant_reload': 'instant_reload',
            'toggle_no_overheat': 'no_overheat', 'toggle_health_lock': 'health_lock',
            'toggle_shield_lock': 'shield_lock', 'toggle_repairkit_no_cd': 'repairkit_no_cd',
            'toggle_skill_no_cd': 'skill_no_cd', 'toggle_gadget_no_cd': 'gadget_no_cd',
            'toggle_stamina_lock': 'stamina_lock', 'toggle_guaranteed_crit': 'guaranteed_crit',
            'toggle_dedicated_drop_100': 'dedicated_drop_100',
            'toggle_infinite_jump': 'infinite_jump',
        }
        for action, feature in action_to_feature.items():
            button = self.live_runtime_buttons.get(action)
            if button is not None:
                button.blockSignals(True)
                button.setChecked(bool(state.get(feature, False)))
                button.blockSignals(False)
        for combo, key in (
            (self.live_fire_rate_combo, 'fire_rate_scale'),
            (self.live_movement_combo, 'movement_speed_scale'),
            (self.live_jump_combo, 'jump_height_scale'),
            (self.live_critical_damage_combo, 'critical_damage_scale'),
            (self.live_experience_reward_combo, 'experience_reward_scale'),
            (self.live_cash_reward_combo, 'cash_reward_scale'),
            (self.live_eridium_reward_combo, 'eridium_reward_scale'),
            (self.live_dedicated_drop_combo, 'dedicated_drop_multiplier'),
        ):
            value = float(state.get(key, 1.0) or 1.0)
            index = combo.findData(value)
            if index >= 0:
                combo.setCurrentIndex(index)
        camera = state.get('camera') if isinstance(state.get('camera'), dict) else {}
        for editor, key, default, clear_zero in (
            (self.live_base_fov_edit, 'base_fov', 0.0, True),
            (self.live_viewmodel_fov_edit, 'viewmodel_fov', 0.0, True),
            (self.live_magazine_capacity_edit, 'magazine_capacity_scale', 1.0, False),
            (self.live_projectile_speed_edit, 'projectile_speed_scale', 1.0, False),
        ):
            if key not in state:
                continue
            value = float(state.get(key, default) or default)
            if clear_zero and value <= 0 and camera.get(key) is not None:
                value = float(camera[key])
                clear_zero = False
            editor.setText('' if clear_zero and value <= 0 else f'{value:g}')
        size = int(state.get('backpack_size', 0) or 0)
        if size > 0:
            self.live_backpack_edit.setText(str(size))
        bank_size = int(state.get('bank_size', 0) or 0)
        if bank_size > 0:
            self.live_bank_size_edit.setText(str(bank_size))
        vault_cards = state.get('vault_cards')
        if isinstance(vault_cards, list):
            self._live_vault_cards = [card for card in vault_cards if isinstance(card, dict)]
        currencies = state.get('currencies')
        if isinstance(currencies, list):
            self._live_currencies = [currency for currency in currencies if isinstance(currency, dict)]
        if isinstance(vault_cards, list) or isinstance(currencies, list):
            self._refresh_live_resource_controls()
        position = state.get('position') or state.get('position_state')
        if isinstance(position, dict):
            self._live_position = dict(position)
            self._refresh_position_display()
        lost_loot = state.get('lost_loot') or state.get('lost_loot_state')
        if isinstance(lost_loot, dict):
            self._live_lost_loot = dict(lost_loot)
            self._refresh_lost_loot_display()

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
