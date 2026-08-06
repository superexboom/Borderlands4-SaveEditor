import random
import pandas as pd
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QComboBox, QPushButton, QMessageBox, QScrollArea, QFrame,
    QSizePolicy, QButtonGroup, QToolButton, QApplication, QStackedWidget,
    QMenu, QWidgetAction
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QColor

from core import b_encoder, item_display_resolver, resource_loader
from core.weapon_generation_logic import sample_composition_parts
from .qt_weapon_roll_dialog import WeaponRollOptionsWidget, WeaponRollResultsPage


class NoScrollComboBox(QComboBox):
    """下拉框：仅在获得焦点（已点选/展开过）时才响应滚轮改值，
    否则把滚轮事件交给父级 QScrollArea 用于滚动页面，避免误切换选项。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 悬停不抢焦点，必须点击才聚焦
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class ElidedChipButton(QPushButton):
    """Chip text stays inside its grid cell; the full value remains in the tooltip."""

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self._full_text = str(text)

    def resizeEvent(self, event):
        available = max(12, event.size().width() - 24)
        text = "\n".join(
            self.fontMetrics().elidedText(line, Qt.TextElideMode.ElideRight, available)
            for line in self._full_text.splitlines() or [self._full_text]
        )
        if text != self.text():
            self.setText(text)
        super().resizeEvent(event)


class ElementChipSelector(QWidget):
    """单选芯片组：把固定的小选项集渲染成一排可点选的圆角芯片（含 None）。
    对外暴露与 QComboBox 兼容的 currentText()，方便沿用既有生成逻辑。"""

    changed = pyqtSignal()
    def __init__(self, none_text, parent=None, columns=3):
        super().__init__(parent)
        self._none_text = none_text
        self._columns = max(1, int(columns))
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(6)
        self._grid.setVerticalSpacing(6)
        for column in range(self._columns):
            self._grid.setColumnStretch(column, 1)
        self._building = False
        self._group.buttonToggled.connect(self._on_toggled)
        self.set_values([])

    def _on_toggled(self, button, checked):
        if checked and not self._building:
            self.changed.emit()

    def _label_of(self, value):
        if value == self._none_text:
            return self._none_text
        return value.split(' - ', 1)[1] if ' - ' in value else value

    def _clear(self):
        for b in list(self._group.buttons()):
            self._group.removeButton(b)
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def set_values(self, values, keep_selection=True):
        prev = self.current_text() if keep_selection else self._none_text
        self._building = True
        self._clear()
        all_values = [self._none_text] + list(values)
        for i, v in enumerate(all_values):
            btn = ElidedChipButton(self._label_of(v))
            btn.setObjectName("elemChip")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setMinimumWidth(0)
            btn.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            lines = btn.text().count("\n") + 1
            btn.setMinimumHeight(max(28, lines * btn.fontMetrics().lineSpacing() + 12))
            btn.setProperty("chipValue", v)
            btn.setToolTip(v)
            self._group.addButton(btn)
            self._grid.addWidget(btn, i // self._columns, i % self._columns)
        self._building = False
        target = prev if prev in all_values else self._none_text
        self.set_current_text(target, silent=True)

    def set_current_text(self, text, silent=False):
        for b in self._group.buttons():
            if b.property("chipValue") == text:
                if silent:
                    self._building = True
                b.setChecked(True)
                if silent:
                    self._building = False
                return
        # 回退到 None
        for b in self._group.buttons():
            if b.property("chipValue") == self._none_text:
                if silent:
                    self._building = True
                b.setChecked(True)
                if silent:
                    self._building = False
                return

    def current_text(self):
        b = self._group.checkedButton()
        return b.property("chipValue") if b is not None else self._none_text

    # 与 QComboBox 接口对齐，方便复用生成逻辑
    def currentText(self):
        return self.current_text()


class QtWeaponGeneratorTab(QWidget):
    # 自定义信号，当用户点击“添加到背包”时发射
    # 参数： serial (str), flag (str)
    add_to_backpack_requested = pyqtSignal(str, str)
    batch_add_to_backpack_requested = pyqtSignal(list, str)

    _NONE_VALUE = "None"
    RARITY_ORDER = ("Common", "Uncommon", "Rare", "Epic", "Legendary", "Pearl")

    # 纯元素（元素1 可选）与首元素解析关键字
    _PURE_ELEMENTS = {"Corrosive", "Cryo", "Fire", "Radiation", "Shock"}
    _ELEM_KEYWORDS = ["Shock", "Radiation", "Incendiary", "Cryo", "Corrosive"]

    # 属性卡片内的布局：稀有度、普通元素、珠光覆盖各自成行。
    ATTR_LAYOUT = {
        "Rarity": (0, 0), "Legendary Type": (0, 1), "Pearl Type": (0, 1),
        "Element 1": (1, 0), "Element 2": (2, 0),
    }
    PEARL_LAYOUT = {"Pearl Stat": (0, 0), "Pearl Elements": (0, 1)}

    # 部件容器内的布局：按武器结构顺序，主件在左、其附件/相关件在右
    PART_LAYOUT = {
        "Body": (0, 0), "Body Mechanism": (0, 1),
        "Body Accessory": (1, 0),
        "Barrel": (2, 0), "Barrel Accessory": (2, 1),
        "Magazine": (3, 0), "Magazine Accessory": (3, 1),
        "Grip": (4, 0), "Foregrip": (4, 1),
        "Scope": (5, 0), "Scope Accessory": (5, 1),
        "Underbarrel": (6, 0), "Underbarrel Accessory": (6, 1),
        "Manufacturer Part": (7, 0), "Tediore Payload": (7, 1),
        "Tediore Throw Reload": (8, 0), "Borg Magazine Adapter": (8, 1),
        "Special Element Set": (9, 0), "Stat Modifier": (9, 1),
    }
    CONDITIONAL_PART_TYPES = {"Tediore Throw Reload", "Borg Magazine Adapter", "Special Element Set"}
    MULTI_SELECT_SLOTS = {
        "Body Accessory": 4, "Barrel Accessory": 4,
        "Manufacturer Part": 4, "Scope Accessory": 4,
        "Underbarrel Accessory": 3
    }

    _SECTION_FALLBACKS = {
        'config': 'Weapon Config', 'attributes': 'Rarity / Elements', 'parts': 'Weapon Parts', 'multi': 'Multi',
        'pearl_stat': 'Pearl Stat', 'pearl_elements': 'Pearl Elements',
        'available_only': 'Only current options are shown',
        'attribute_hint': 'Secondary and Pearl fields appear only when the current build supports them.',
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.all_weapon_parts_df = None
        self.elemental_df = None
        self.weapon_rarity_df = None
        self.weapon_localization = None
        self.weapon_taxonomy = {}
        self.item_index = {}
        self.weapon_rules = {}
        self.part_combos = {}
        self.part_combo_rows = {}
        self.part_group_boxes = {}
        self.part_title_labels = {}
        self.part_detail_labels = {}
        self.part_rule_badges = {}
        self.element_frames = {}
        self.element2_frame = None
        self.generation_rule_badge = None
        self.legendary_frame = None # Initialize to None
        self._roll_menu = None
        self._roll_options_widget = None
        self._roll_constraints = {}
        self._roll_count = 5
        self._roll_add_busy = False
        self.current_lang = 'zh-CN'
        self._character_level = "50"
        
        # Main layout holds the content widget
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.content_widget = None

        self.load_data(self.current_lang)
        self.create_widgets()

    def load_data(self, lang='zh-CN'):
        loc_file = resource_loader.get_ui_localization_file(lang)
        full_loc = resource_loader.load_json_resource(loc_file) or {}
        self.ui_loc = full_loc.get("weapon_gen_tab", {})
        self.weapon_rule_loc = full_loc.get("weapon_rules", {})
        self.stats_loc = full_loc.get("weapon_editor_tab", {}).get("stats", {})
        self.weapon_taxonomy = full_loc.get("weapon_editor_tab", {}).get("taxonomy", {})
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

            paths = {
                "all_parts": get_path('all_weapon_part.csv'),
                "elemental": get_path('elemental.csv'),
                "rarity": get_path('weapon_rarity.csv')
            }
            
            # Filter out None paths (though get_weapon_data_path usually returns path even if not exists, check implementation)
            # resource_loader.get_resource_path returns path object. 
            # But get_path checks .exists(). 
            # If fallback also fails, it might return None if we changed logic, but resource_loader returns Path object usually.
            # But resource_loader.get_weapon_data_path calls get_resource_path.
            
            if not all(paths.values()) or not all(p.exists() for p in paths.values()):
                raise FileNotFoundError(
                    self.ui_loc.get('dialogs', {}).get('file_not_found', "One or more weapon CSV file paths not found.")
                )

            self.all_weapon_parts_df = pd.read_csv(paths["all_parts"])
            self.all_weapon_parts_df['Part ID'] = self.all_weapon_parts_df['Part ID'].astype('Int64').astype(str).replace('<NA>', '')
            self.elemental_df = pd.read_csv(resource_loader.get_weapon_data_path('elemental.csv'))
            self.elemental_stat_col = 'Stat_ZH' if lang == 'zh-CN' else 'Stat'
            self.weapon_rarity_df = pd.read_csv(paths["rarity"])
            self.rarity_desc_col = 'Description_ZH' if lang == 'zh-CN' else 'Description'
            self.item_index = resource_loader.load_item_json('item_name_index.json') or {}
            self.weapon_rules = self.item_index.get('weapon_generation_rules') or {}
            
            self.weapon_localization = {}
            if lang == 'zh-CN':
                self.weapon_localization = resource_loader.load_weapon_json('weapon_localization_zh-CN.json') or {}
            
        except Exception as e:
            template = self.ui_loc.get('dialogs', {}).get('load_error', "Error loading data: {error}")
            self._handle_error(template.format(error=e))

    def update_language(self, lang):
        print(f"DEBUG: Updating language for {self.__class__.__name__} to {lang}...")
        self.current_lang = lang
        self.load_data(lang)
        
        # Save state
        current_mfg_idx = self.manufacturer_combo.currentIndex() if hasattr(self, 'manufacturer_combo') else 0
        current_wt_idx = self.weapon_type_combo.currentIndex() if hasattr(self, 'weapon_type_combo') else 0
        current_level = self.level_var.text() if hasattr(self, 'level_var') else self._character_level
        current_seed = self.seed_var.text() if hasattr(self, 'seed_var') else ""
        
        # Clean up internal references
        self.part_combos = {}
        self.part_combo_rows = {}
        self.part_group_boxes = {}
        self.part_title_labels = {}
        self.part_detail_labels = {}
        self.part_rule_badges = {}
        self.element_frames = {}
        self.element2_frame = None
        self.legendary_frame = None
        
        self.create_widgets()
        
        # Restore state
        if hasattr(self, 'manufacturer_combo') and self.manufacturer_combo.count() > current_mfg_idx:
            self.manufacturer_combo.setCurrentIndex(current_mfg_idx)
        if hasattr(self, 'weapon_type_combo') and self.weapon_type_combo.count() > current_wt_idx:
            self.weapon_type_combo.setCurrentIndex(current_wt_idx)
        if hasattr(self, 'level_var'): self.level_var.setText(current_level)
        if hasattr(self, 'seed_var') and current_seed: self.seed_var.setText(current_seed)
        print(f"DEBUG: Finished updating language for {self.__class__.__name__}.")

    def get_localized_string(self, key, default=''):
        if self.ui_loc:
            if key in self.ui_loc.get('labels', {}): return self.ui_loc['labels'][key]
            if key in self.ui_loc.get('buttons', {}): return self.ui_loc['buttons'][key]
            if key in self.ui_loc.get('dialogs', {}): return self.ui_loc['dialogs'][key]
        return self.weapon_localization.get(str(key), default or str(key))

    def _section_text(self, key):
        """获取分区标题/徽标/提示文案，按当前语言回退到英文。"""
        return self.ui_loc.get('sections', {}).get(key) or self._SECTION_FALLBACKS.get(key, key)

    def _handle_error(self, message):
        error_label = QLabel(message)
        error_label.setStyleSheet("color: red;")
        error_label.setWordWrap(True)
        
        # 清空现有布局并显示错误
        for i in reversed(range(self.layout().count())): 
            self.layout().itemAt(i).widget().setParent(None)
        self.layout().addWidget(error_label)

    def _make_section_title(self, text):
        """卡片小标题标签。"""
        lbl = QLabel(text)
        lbl.setObjectName("genSectionTitle")
        return lbl

    def create_widgets(self):
        # Clean up old content
        if self.content_widget:
            self.main_layout.removeWidget(self.content_widget)
            self.content_widget.deleteLater()
            self.content_widget = None

        if self.all_weapon_parts_df is None: 
            return

        # Create new content widget
        self.content_widget = QWidget()
        shell_layout = QVBoxLayout(self.content_widget)
        shell_layout.setContentsMargins(8, 8, 8, 8)
        shell_layout.setSpacing(10)
        self.main_layout.addWidget(self.content_widget)

        page_nav = QHBoxLayout()
        page_nav.setSpacing(8)
        self.generator_page_button = QPushButton(self.get_localized_string("generator_page", "Main Generator"))
        self.roll_results_button = QPushButton(self.get_localized_string("results_page", "Random Results"))
        self.page_button_group = QButtonGroup(self.content_widget)
        self.page_button_group.setExclusive(True)
        for index, button in enumerate((self.generator_page_button, self.roll_results_button)):
            button.setObjectName("genPageTab")
            button.setCheckable(True)
            self.page_button_group.addButton(button, index)
            page_nav.addWidget(button)
        page_nav.addStretch()
        shell_layout.addLayout(page_nav)

        self.page_stack = QStackedWidget()
        self.page_stack.setObjectName("genPageStack")
        self.generator_page = QWidget()
        generator_layout = QVBoxLayout(self.generator_page)
        generator_layout.setContentsMargins(0, 0, 0, 0)
        generator_layout.setSpacing(10)
        self.roll_results_page = WeaponRollResultsPage(texts=self._roll_texts())
        self.roll_results_page.add_requested.connect(self._request_roll_add)
        self.roll_results_page.close_requested.connect(lambda: self._set_workspace_page(0))
        self.page_stack.addWidget(self.generator_page)
        self.page_stack.addWidget(self.roll_results_page)
        shell_layout.addWidget(self.page_stack, 1)
        self.page_button_group.idClicked.connect(self._set_workspace_page)
        self._set_workspace_page(0)

        # --- 输出框（序列展示，保持不动） ---
        output_frame = QFrame(self.content_widget); output_frame.setLayout(QGridLayout())
        self.serial_decoded_entry = QLineEdit(); self.serial_decoded_entry.setReadOnly(True)
        self.serial_b85_entry = QLineEdit(); self.serial_b85_entry.setReadOnly(True)
        output_frame.layout().addWidget(QLabel(self.get_localized_string("serial_decoded")), 0, 0)
        output_frame.layout().addWidget(self.serial_decoded_entry, 0, 1)
        output_frame.layout().addWidget(QLabel(self.get_localized_string("serial_b85")), 1, 0)
        output_frame.layout().addWidget(self.serial_b85_entry, 1, 1)
        generator_layout.addWidget(output_frame)

        # --- 配置卡片（固定在滚动区之外）：厂商 / 武器类型 / 等级 / 种子 ---
        config_card = QFrame(self.content_widget)
        config_card.setObjectName("genConfigCard")
        config_v = QVBoxLayout(config_card)
        config_v.setContentsMargins(14, 12, 14, 12)
        config_v.setSpacing(8)
        config_header = QHBoxLayout()
        config_header.addWidget(self._make_section_title(self._section_text('config')))
        config_header.addStretch()
        self.lucky_button = QToolButton()
        self.lucky_button.setObjectName("genLuckyButton")
        lucky_text = self.get_localized_string("lucky", "I'm Feeling Lucky")
        self.lucky_button.setText(f"🎲 {lucky_text}")
        self.lucky_button.setToolTip(self.ui_loc.get('dialogs', {}).get(
            'roll_scope_tip', 'Generate structurally legal builds; native drop weights are not simulated.'
        ))
        self.lucky_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self._roll_menu = QMenu(self.lucky_button)
        self._roll_options_widget = WeaponRollOptionsWidget(
            self._weapon_roll_catalog(), texts=self._roll_texts(),
            constraints=self._roll_constraints, count=self._roll_count,
        )
        self._roll_options_widget.roll_requested.connect(self._roll_from_menu)
        roll_options_action = QWidgetAction(self._roll_menu)
        roll_options_action.setDefaultWidget(self._roll_options_widget)
        self._roll_menu.addAction(roll_options_action)
        self.lucky_button.setMenu(self._roll_menu)
        self.lucky_button.clicked.connect(self._quick_roll)
        config_header.addWidget(self.lucky_button)
        config_v.addLayout(config_header)

        config_grid = QGridLayout()
        config_grid.setHorizontalSpacing(14)
        config_grid.setVerticalSpacing(4)

        self.manufacturer_combo = NoScrollComboBox()
        self.weapon_type_combo = NoScrollComboBox()
        self.level_var = QLineEdit(self._character_level)
        self.seed_var = QLineEdit(str(random.randint(100, 9999)))
        random_seed_btn = QPushButton("🎲"); random_seed_btn.setFixedWidth(34)

        # Row 0: labels, Row 1: inputs（标签在上、输入在下）
        config_grid.addWidget(QLabel(self.get_localized_string("manufacturer")), 0, 0)
        config_grid.addWidget(self.manufacturer_combo, 1, 0)
        config_grid.addWidget(QLabel(self.get_localized_string("weapon_type")), 0, 1)
        config_grid.addWidget(self.weapon_type_combo, 1, 1)
        config_grid.addWidget(QLabel(self.get_localized_string("level")), 0, 2)
        config_grid.addWidget(self.level_var, 1, 2)

        seed_row = QHBoxLayout()
        seed_row.setContentsMargins(0, 0, 0, 0)
        seed_row.setSpacing(6)
        seed_row.addWidget(self.seed_var)
        seed_row.addWidget(random_seed_btn)
        config_grid.addWidget(QLabel(self.get_localized_string("seed")), 0, 3)
        config_grid.addLayout(seed_row, 1, 3)

        # Flag 选择 + 添加到背包（并入配置卡片右侧，取代原底部操作条）
        self.flag_combo = NoScrollComboBox()
        flags = resource_loader.get_flag_labels(self.current_lang)
        self.flag_combo.addItems([flags[k] for k in ("1", "3", "5", "17", "33", "65", "129")])
        self.flag_combo.setCurrentText(flags["3"])
        add_to_backpack_btn = QPushButton(self.get_localized_string("add_to_backpack"))
        add_to_backpack_btn.setObjectName("genAddButton")
        config_grid.addWidget(QLabel(self.get_localized_string("select_flag")), 0, 4)
        config_grid.addWidget(self.flag_combo, 1, 4)
        # 只放在输入行，与左侧下拉框对齐（不占标签行，避免顶部高出）
        config_grid.addWidget(add_to_backpack_btn, 1, 5)

        # 厂商 / 武器类型 占更多宽度
        config_grid.setColumnStretch(0, 3)
        config_grid.setColumnStretch(1, 3)
        config_grid.setColumnStretch(2, 1)
        config_grid.setColumnStretch(3, 2)
        config_grid.setColumnStretch(4, 2)
        config_v.addLayout(config_grid)
        generator_layout.addWidget(config_card)

        stats_frame = QFrame()
        stats_frame.setObjectName("InnerFrame")
        stats_layout = QGridLayout(stats_frame)
        self.weapon_stat_value_labels = {}
        for index, key in enumerate(item_display_resolver.WEAPON_STAT_KEYS):
            row, column = divmod(index, 4)
            title = QLabel(self.stats_loc.get(key, key.replace("_", " ").title()))
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title.setWordWrap(True)
            value = QLabel("—")
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value.setMinimumWidth(72)
            value.setObjectName("WeaponStatValue")
            stats_layout.addWidget(title, row * 2, column)
            stats_layout.addWidget(value, row * 2 + 1, column)
            stats_layout.setColumnStretch(column, 1)
            self.weapon_stat_value_labels[key] = value
        status_index = len(item_display_resolver.WEAPON_STAT_KEYS)
        status_row, status_column = divmod(status_index, 4)
        status_title = QLabel(self.get_localized_string("build_status", "Build Status"))
        status_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.generation_rule_badge = QLabel("—")
        self.generation_rule_badge.setObjectName("genBuildStatus")
        self.generation_rule_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.generation_rule_badge.setMinimumWidth(72)
        stats_layout.addWidget(status_title, status_row * 2, status_column)
        stats_layout.addWidget(self.generation_rule_badge, status_row * 2 + 1, status_column)
        stats_layout.setColumnStretch(status_column, 1)
        generator_layout.addWidget(stats_frame)

        # --- 滚动区：属性卡片 + 部件容器 ---
        self.parts_scroll_area = QScrollArea()
        self.parts_scroll_area.setWidgetResizable(True)
        self.parts_scroll_area.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored
        )
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(10)

        # 属性卡片
        attr_card = QFrame()
        attr_card.setObjectName("genAttrCard")
        attr_v = QVBoxLayout(attr_card)
        attr_v.setContentsMargins(14, 12, 14, 12)
        attr_v.setSpacing(8)
        attr_header = QHBoxLayout()
        attr_header.addWidget(self._make_section_title(self._section_text('attributes')))
        attr_header.addStretch()
        available_hint = QLabel(self._section_text('available_only'))
        available_hint.setObjectName("genHeaderHint")
        attr_header.addWidget(available_hint)
        attr_v.addLayout(attr_header)
        attr_grid_holder = QWidget()
        self.attr_layout = QGridLayout(attr_grid_holder)
        self.attr_layout.setContentsMargins(0, 0, 0, 0)
        self.attr_layout.setHorizontalSpacing(12)
        self.attr_layout.setVerticalSpacing(8)
        self.attr_layout.setColumnStretch(0, 2)
        self.attr_layout.setColumnStretch(1, 3)
        attr_v.addWidget(attr_grid_holder)
        self.pearl_settings_frame = QFrame()
        self.pearl_settings_frame.setObjectName("genPearlSettings")
        self.pearl_layout = QGridLayout(self.pearl_settings_frame)
        self.pearl_layout.setContentsMargins(0, 0, 0, 0)
        self.pearl_layout.setHorizontalSpacing(12)
        self.pearl_layout.setVerticalSpacing(8)
        self.pearl_layout.setColumnStretch(0, 1)
        self.pearl_layout.setColumnStretch(1, 1)
        attr_v.addWidget(self.pearl_settings_frame)
        self._set_pearl_expanded(False)
        divider = QFrame()
        divider.setObjectName("genAttrDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        attr_v.addWidget(divider)
        attr_hint = QLabel(self._section_text('attribute_hint'))
        attr_hint.setObjectName("genHint")
        attr_hint.setWordWrap(True)
        attr_v.addWidget(attr_hint)
        scroll_layout.addWidget(attr_card)

        # 部件容器
        parts_card = QFrame()
        parts_card.setObjectName("genPartsContainer")
        parts_v = QVBoxLayout(parts_card)
        parts_v.setContentsMargins(0, 0, 0, 0)
        parts_v.setSpacing(4)
        self.parts_frame = QWidget()
        self.parts_layout = QGridLayout(self.parts_frame)
        self.parts_layout.setContentsMargins(0, 0, 0, 0)
        self.parts_layout.setHorizontalSpacing(12)
        self.parts_layout.setVerticalSpacing(6)
        self.parts_layout.setColumnStretch(0, 1)
        self.parts_layout.setColumnStretch(1, 1)
        parts_v.addWidget(self.parts_frame)
        scroll_layout.addWidget(parts_card)
        scroll_layout.addStretch()

        self.parts_scroll_area.setWidget(scroll_content)
        generator_layout.addWidget(self.parts_scroll_area, 1)

        # --- 连接信号 ---
        self.manufacturer_combo.currentTextChanged.connect(self.on_main_selection_change)
        self.weapon_type_combo.currentTextChanged.connect(self.on_main_selection_change)
        self.level_var.textChanged.connect(self.generate_weapon)
        self.seed_var.textChanged.connect(self.generate_weapon)
        random_seed_btn.clicked.connect(self.randomize_seed)
        add_to_backpack_btn.clicked.connect(self._on_add_to_backpack)
        
        self._populate_initial_selectors()
        self.on_main_selection_change()

    def _populate_initial_selectors(self):
        m_list = sorted([self.get_localized_string(m) for m in self.all_weapon_parts_df['Manufacturer'].unique()])
        self.manufacturer_combo.addItems(m_list)
        self._populate_weapon_types()

    def _populate_weapon_types(self):
        manufacturer = self._get_english_key(self.manufacturer_combo.currentText())
        available = sorted(self.all_weapon_parts_df[self.all_weapon_parts_df['Manufacturer'] == manufacturer]['Weapon Type'].unique())
        localized = [self.get_localized_string(value) for value in available]
        current = self.weapon_type_combo.currentText()
        if [self.weapon_type_combo.itemText(i) for i in range(self.weapon_type_combo.count())] == localized:
            return
        self.weapon_type_combo.blockSignals(True)
        self.weapon_type_combo.clear()
        self.weapon_type_combo.addItems(localized)
        if current in localized:
            self.weapon_type_combo.setCurrentText(current)
        self.weapon_type_combo.blockSignals(False)

    def on_main_selection_change(self, _=None):
        self._populate_weapon_types()
        self._create_part_dropdowns()
        self.generate_weapon()

    def _get_m_id(self, mfg_en, wt_en):
        if not mfg_en or not wt_en: return None
        try:
            return self.all_weapon_parts_df.loc[
                (self.all_weapon_parts_df['Manufacturer'] == mfg_en) & 
                (self.all_weapon_parts_df['Weapon Type'] == wt_en), 'Manufacturer & Weapon Type ID'
            ].iloc[0]
        except IndexError:
            return None

    def _current_m_id(self):
        mfg_en = self._get_english_key(self.manufacturer_combo.currentText())
        wt_en = self._get_english_key(self.weapon_type_combo.currentText())
        return self._get_m_id(mfg_en, wt_en)

    def _clear_layout(self, layout):
        if layout is None:
            return
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _create_part_dropdowns(self):
        # 清理旧的 widgets（属性卡片 + 部件容器）
        self._clear_layout(self.attr_layout)
        self._clear_layout(self.pearl_layout)
        self._clear_layout(self.parts_layout)
        self.part_combos = {}
        self.part_combo_rows = {}
        self.part_group_boxes = {}
        self.part_title_labels = {}
        self.part_detail_labels = {}
        self.part_rule_badges = {}
        self.element_frames = {}
        self.element2_frame = None
        # IMPORTANT: Clear reference to the deleted widget to prevent crash if signal handlers traverse it
        self.legendary_frame = None
        self.pearl_frame = None
        
        selected_mfg_en = self._get_english_key(self.manufacturer_combo.currentText())
        selected_wt_en = self._get_english_key(self.weapon_type_combo.currentText())

        m_id = self._get_m_id(selected_mfg_en, selected_wt_en)
        if m_id is None: return

        self._create_special_dropdown("Rarity", m_id, self.ATTR_LAYOUT["Rarity"])
        self._create_special_dropdown("Legendary Type", m_id, self.ATTR_LAYOUT["Legendary Type"])
        self._create_special_dropdown("Pearl Type", m_id, self.ATTR_LAYOUT["Pearl Type"])

        # 元素 / 珠光：芯片单选。顺序：元素1 → 珠光属性 → 珠光元素 → 元素2
        self._create_element_selector("Element 1", self.ATTR_LAYOUT["Element 1"])
        self._create_element_selector("Element 2", self.ATTR_LAYOUT["Element 2"])
        self._create_pearl_selector("Pearl Stat", self.PEARL_LAYOUT["Pearl Stat"])
        self._create_pearl_selector("Pearl Elements", self.PEARL_LAYOUT["Pearl Elements"])

        filtered_df = self.all_weapon_parts_df[self.all_weapon_parts_df['Manufacturer & Weapon Type ID'] == m_id]
        for part_type_en, group_df in filtered_df.groupby('Part Type'):
            if part_type_en not in self.PART_LAYOUT: continue
            
            row, col = self.PART_LAYOUT[part_type_en]
            
            group_box = QFrame()
            group_box.setObjectName("genPartGroup")
            group_box.setProperty("partType", part_type_en)
            group_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
            group_layout = QVBoxLayout(group_box)
            group_layout.setContentsMargins(0, 2, 0, 6)
            group_layout.setSpacing(5)
            self.part_group_boxes[part_type_en] = group_box

            header = QHBoxLayout()
            header.setContentsMargins(0, 0, 0, 0)
            title = QLabel(self.get_localized_string(part_type_en))
            title.setObjectName("genPartTitle")
            title.setProperty("partType", part_type_en)
            header.addWidget(title)
            header.addStretch()
            num_slots = self.MULTI_SELECT_SLOTS.get(part_type_en, 1)
            badge = QLabel("—")
            badge.setObjectName("multiBadge")
            badge.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            badge.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            header.addWidget(badge)
            group_layout.addLayout(header)
            self.part_title_labels[part_type_en] = title
            self.part_rule_badges[part_type_en] = badge

            for i in range(num_slots):
                combo = NoScrollComboBox()
                self._configure_part_combo(combo)
                combo.addItem(self.get_localized_string(self._NONE_VALUE), None)
                for _, part_row in group_df.iterrows():
                    part_id = str(part_row['Part ID'])
                    if part_id:
                        combo.addItem(self._part_option_text(m_id, part_id, part_row), part_id)
                        combo.setItemData(combo.count() - 1, combo.itemText(combo.count() - 1), Qt.ItemDataRole.ToolTipRole)
                # Add to dict BEFORE connecting signals
                combo_key = f"{part_type_en}_{i}"
                self.part_combos[combo_key] = combo
                self.part_combo_rows[combo_key] = group_df
                combo.currentTextChanged.connect(self.generate_weapon)
                # 下挂变化会影响元素2 的可选项（元素切换下挂）
                if part_type_en == "Underbarrel":
                    combo.currentTextChanged.connect(self._refresh_element2)
                
                group_layout.addWidget(combo)
                detail = QLabel()
                detail.setObjectName("genPartDetail")
                detail.setWordWrap(True)
                detail.setMaximumHeight(detail.fontMetrics().lineSpacing() * 2 + 8)
                detail.hide()
                self.part_detail_labels[combo_key] = detail
                group_layout.addWidget(detail)
            
            self.parts_layout.addWidget(group_box, row, col, Qt.AlignmentFlag.AlignTop)

        # 部件建好后，依据元素1 / 下挂初始化元素2 的可选项
        self._refresh_conditional_part_options()
        self._refresh_element2()
        rarity_combo = self.part_combos.get("Rarity")
        rarity = self._get_english_key(rarity_combo.currentText()) if rarity_combo else ""
        self._sync_pearl_visibility(rarity)
        self.generate_weapon()

    def _part_option_text(self, item_id, part_id, row, decoded_str=""):
        return item_display_resolver.format_weapon_part_option(
            int(item_id), str(part_id), decoded_str, self.current_lang, row
        )

    @staticmethod
    def _configure_part_combo(combo):
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(22)
        combo.setMinimumWidth(0)
        combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        combo.view().setMinimumWidth(620)

    def _apply_part_rule_colors(self, part_type, item_id, eligible_refs=(), allowed_refs=()):
        eligible_refs, allowed_refs = set(eligible_refs), set(allowed_refs)
        for key, combo in self.part_combos.items():
            if not key.startswith(f"{part_type}_") or not isinstance(combo, QComboBox):
                continue
            for index in range(combo.count()):
                combo.setItemData(index, None, Qt.ItemDataRole.BackgroundRole)
                combo.setItemData(index, None, Qt.ItemDataRole.ForegroundRole)
                combo.setItemData(index, None, Qt.ItemDataRole.FontRole)
                part_id = combo.itemData(index)
                if item_id is None or part_id is None:
                    continue
                ref = f"{item_id}:{part_id}"
                if ref in eligible_refs:
                    font = combo.font()
                    font.setBold(True)
                    combo.setItemData(index, QColor("#0E7490"), Qt.ItemDataRole.BackgroundRole)
                    combo.setItemData(index, QColor("#F0FDFA"), Qt.ItemDataRole.ForegroundRole)
                    combo.setItemData(index, font, Qt.ItemDataRole.FontRole)
                elif ref in allowed_refs:
                    combo.setItemData(index, QColor("#F59E0B"), Qt.ItemDataRole.BackgroundRole)
                    combo.setItemData(index, QColor("#1C1917"), Qt.ItemDataRole.ForegroundRole)

    def _set_part_group_rule_title(self, part_type, current, legal_range, shared=False):
        title = self.part_title_labels.get(part_type)
        if title is not None:
            title.setText(self.get_localized_string(part_type))
        badge = self.part_rule_badges.get(part_type)
        if badge is not None:
            badge.setProperty("shared", bool(shared))

    def _selected_part_adds(self, item_id):
        adds = set()
        for combo in self.part_combos.values():
            if not isinstance(combo, QComboBox):
                continue
            part_id = combo.currentData()
            if part_id is not None and str(part_id).isdigit():
                adds.update(item_display_resolver.weapon_part_selection_tags(item_id, str(part_id)).get("adds", []))
        return adds

    def _refresh_conditional_part_options(self):
        item_id = self._current_m_id()
        if item_id is None:
            return
        none_text = self.get_localized_string(self._NONE_VALUE)
        for key, rows in self.part_combo_rows.items():
            part_type = key.rsplit('_', 1)[0]
            if part_type not in self.CONDITIONAL_PART_TYPES:
                continue
            combo = self.part_combos[key]
            selected = combo.currentData()
            decoded = self.serial_decoded_entry.text() if hasattr(self, 'serial_decoded_entry') else ""
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(none_text, None)
            for _, row in rows.iterrows():
                part_id = str(row['Part ID'])
                combo.addItem(self._part_option_text(item_id, part_id, row, decoded), part_id)
                combo.setItemData(combo.count() - 1, combo.itemText(combo.count() - 1), Qt.ItemDataRole.ToolTipRole)
            selected_index = combo.findData(selected)
            combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)
            combo.blockSignals(False)
            group = self.part_group_boxes.get(part_type)
            if group is not None:
                group.setVisible(not rows.empty)

    def _refresh_part_descriptions(self, decoded_str):
        item_id = self._current_m_id()
        if item_id is None:
            return
        for key, rows in self.part_combo_rows.items():
            combo = self.part_combos.get(key)
            if not isinstance(combo, QComboBox):
                continue
            combo.blockSignals(True)
            for index in range(1, combo.count()):
                part_id = str(combo.itemData(index) or "")
                matches = rows[rows['Part ID'] == part_id]
                if not matches.empty:
                    text = self._part_option_text(item_id, part_id, matches.iloc[0], decoded_str)
                    combo.setItemText(index, text)
                    combo.setItemData(index, text, Qt.ItemDataRole.ToolTipRole)
            combo.blockSignals(False)
            detail = self.part_detail_labels.get(key)
            selected = combo.currentData()
            if detail is not None and selected is not None:
                matches = rows[rows['Part ID'] == str(selected)]
                description = item_display_resolver.format_weapon_part_description(
                    int(item_id), str(selected), decoded_str, self.current_lang,
                    str(matches.iloc[0]['Part Type']) if not matches.empty else "",
                )
                detail.setText(description)
                detail.setToolTip(description)
                detail.setVisible(bool(description))
            elif detail is not None:
                detail.setToolTip("")
                detail.hide()

    def _rule_message(self, key, zh, en, **fmt):
        fallback = zh if self.current_lang == 'zh-CN' else en
        text = self.weapon_rule_loc.get(key, fallback)
        return text.format(**fmt) if fmt else text

    def _rule_violation_text(self, violation):
        labels = {
            "rules_unavailable": ("violation_rules_unavailable", "规则数据不可用", "Rule data unavailable"),
            "weapon_rules_missing": ("violation_weapon_rules_missing", "缺少该武器规则", "Weapon rules missing"),
            "unknown_composition": ("violation_unknown_composition", "未选择或无法识别武器模板", "Weapon composition is missing or unknown"),
            "multiple_compositions": ("violation_multiple_compositions", "存在多个武器模板", "Multiple weapon compositions"),
            "foreign_root_part": ("violation_foreign_root_part", "存在跨来源配件", "Foreign part"),
            # Same item type, different brand vs. a different item class entirely.
            "foreign_root_part_manufacturer": (
                "violation_foreign_root_part_manufacturer", "存在跨厂商配件", "Cross-manufacturer part",
            ),
            "foreign_root_part_type": (
                "violation_foreign_root_part_type", "存在跨类型配件", "Cross-type part",
            ),
            "unknown_part": ("violation_unknown_part", "存在未知配件", "Unknown weapon part"),
            "part_not_allowed": ("violation_part_not_allowed", "存在非自然生成配件", "Part is outside the natural pool"),
            "count_below": ("violation_count_below", "配件尚未补齐", "Required parts are missing"),
            "count_above": ("violation_count_above", "配件数量超过自然上限", "Part count exceeds the natural maximum"),
            "duplicate_part": ("violation_duplicate_part", "存在重复配件", "Duplicate part"),
            "missing_required_tag": ("violation_missing_required_tag", "配件依赖未满足", "Part dependency is not satisfied"),
            "excluded_tag_conflict": ("violation_excluded_tag_conflict", "配件条件冲突", "Part conditions conflict"),
            "tag_limit": ("violation_tag_limit", "授权类配件超过上限", "Tagged part count exceeds the limit"),
            "forced_part_missing": ("violation_forced_part_missing", "缺少模板固有配件", "Forced composition part is missing"),
            "conditional_availability": ("violation_conditional_availability", "仅在特定条件下生成", "Available only in a special context"),
            "unresolved_rule_parts": ("violation_unresolved_rule_parts", "规则仍有未解析配件", "Rule contains unresolved parts"),
            "inheritance_cycle": ("violation_inheritance_cycle", "模板规则继承异常", "Composition rule inheritance cycle"),
        }
        code = violation.get("code")
        foreign_kind = str(violation.get("foreign_kind") or "")
        if code == "foreign_root_part" and foreign_kind:
            code = f"{code}_{foreign_kind}"
        key, zh, en = labels.get(code, ("", str(code or ""), str(code or "")))
        text = self._rule_message(key, zh, en) if key else en
        actual = violation.get("actual")
        limit = violation.get("min", violation.get("max"))
        if actual is not None and limit is not None:
            text += f" ({actual}/{limit})"
        return text

    def _rule_candidate_text(self, ref, rows):
        root_id, _, part_id = str(ref).partition(":")
        matches = rows[rows['Part ID'] == part_id] if rows is not None else None
        row = matches.iloc[0] if matches is not None and not matches.empty else None
        name = item_display_resolver.weapon_part_name(
            int(root_id), part_id, self.current_lang, row
        ) if root_id.isdigit() else ""
        return f"{ref} — {name}" if name else str(ref)

    def _selected_ui_part_count(self, part_type):
        prefix = f"{part_type}_"
        return sum(
            combo.currentData() is not None
            for key, combo in self.part_combos.items()
            if key.startswith(prefix) and isinstance(combo, QComboBox)
        )

    def _update_generation_rule_guidance(self, decoded_str):
        if self.generation_rule_badge is None:
            return
        try:
            result = item_display_resolver.validate_weapon_generation(
                decoded_str, allow_incomplete=True
            )
        except Exception as exc:
            result = {
                "status": "unknown",
                "groups": {},
                "violations": [{"code": f"rule_error: {exc}"}],
                "rules_available": False,
                "composition_ref": "",
            }

        status_labels = {
            "legal": ("status_legal", "自然生成", "Legal"),
            "incomplete": ("status_incomplete", "待补齐", "Incomplete"),
            "modified": ("status_modified", "魔改", "Modified"),
            "conditional": ("status_conditional", "条件限定", "Conditional"),
            "unknown": ("status_unknown", "规则未知", "Rules unknown"),
        }
        status = str(result.get("status") or "unknown")
        status_key, status_zh, status_en = status_labels.get(status, status_labels["unknown"])
        status_text = self._rule_message(status_key, status_zh, status_en)
        self.generation_rule_badge.setText(status_text)
        self.generation_rule_badge.setProperty("ruleStatus", status)
        self.generation_rule_badge.style().unpolish(self.generation_rule_badge)
        self.generation_rule_badge.style().polish(self.generation_rule_badge)
        violations = [
            self._rule_violation_text(item)
            for item in result.get("violations", [])
        ]
        self.generation_rule_badge.setToolTip(
            "\n".join(violations) or self._rule_message(
                "matches_rules", "符合当前自然生成规则", "Matches the current generation rules"
            )
        )

        rules_ready = bool(result.get("rules_available") and result.get("composition_ref"))
        groups = result.get("groups") or {}
        item_id = self._current_m_id()
        display_matches = {}
        group_categories = {}
        if rules_ready and item_id is not None:
            for part_type in self.part_rule_badges:
                rows = self.part_combo_rows.get(f"{part_type}_0")
                candidate_refs = {
                    f"{item_id}:{part_id}"
                    for part_id in (rows['Part ID'].tolist() if rows is not None else [])
                    if str(part_id)
                }
                matched_groups = [
                    group
                    for group, group_rule in groups.items()
                    if (set(group_rule.get("allowed") or []) | set(group_rule.get("selected") or [])) & candidate_refs
                ]
                display_matches[part_type] = (rows, candidate_refs, matched_groups)
                for group in matched_groups:
                    group_categories.setdefault(group, set()).add(part_type)

        for part_type, badge in self.part_rule_badges.items():
            current = self._selected_ui_part_count(part_type)
            if not rules_ready or item_id is None:
                badge.setText(f"{current} / —")
                badge.setToolTip(self._rule_message(
                    "select_composition", "选择武器模板后显示合法范围", "Select a composition to show its legal range"
                ))
                self._set_part_group_rule_title(part_type, current, "—")
                self._apply_part_rule_colors(part_type, item_id)
                continue

            rows, candidate_refs, matched_groups = display_matches.get(part_type, (None, set(), []))

            if not matched_groups:
                badge.setText(f"{current} / —")
                badge.setToolTip(self._rule_message(
                    "no_group_rule", "该显示分组没有独立生成规则", "No separate generation rule for this display group"
                ))
                self._set_part_group_rule_title(part_type, current, "—")
                self._apply_part_rule_colors(part_type, item_id)
                continue

            matched = [groups[group] for group in matched_groups]
            current = sum(len(group_rule.get("selected") or []) for group_rule in matched)
            shared = any(len(group_categories.get(group, ())) > 1 for group in matched_groups)
            legal_min = sum(int(group_rule.get("effective_min", 0)) for group_rule in matched)
            legal_max = sum(int(group_rule.get("effective_max", 0)) for group_rule in matched)
            legal_range = str(legal_min) if legal_min == legal_max else f"{legal_min}–{legal_max}"
            badge.setText(self._rule_message(
                "shared_current_legal" if shared else "current_legal",
                "共享配额 当前{current}/合法{range}" if shared else "当前{current}/合法{range}",
                "shared {current}/{range}" if shared else "{current}/{range}",
                current=current, range=legal_range,
            ))
            self._set_part_group_rule_title(part_type, current, legal_range, shared)

            eligible = sorted({
                ref
                for group_rule in matched
                for ref in group_rule.get("eligible_refs") or []
                if ref in candidate_refs
                and (
                    len(group_rule.get("selected") or []) < int(group_rule.get("effective_max", 1))
                    or ref in set(group_rule.get("selected") or [])
                )
            }, key=lambda ref: tuple(map(int, ref.split(":"))))
            allowed = {
                ref
                for group_rule in matched
                for ref in group_rule.get("allowed") or []
                if ref in candidate_refs
            }
            self._apply_part_rule_colors(part_type, item_id, eligible, allowed)
            lines = [
                self._rule_message("current", "当前：{current}", "Current: {current}", current=current),
                self._rule_message("legal_count", "合法数量：{range}", "Legal count: {range}", range=legal_range),
            ]
            if eligible:
                lines.append(self._rule_message("legal_candidates", "合法候选：", "Legal candidates:"))
                lines.extend(self._rule_candidate_text(ref, rows) for ref in eligible)
            else:
                lines.append(self._rule_message(
                    "no_legal_candidates", "当前配件条件下没有合法候选",
                    "No legal candidates under the current part conditions",
                ))
            badge.setToolTip("\n".join(lines))

    def _create_special_dropdown(self, name, m_id, position):
        row, col = position

        field = QFrame()
        field.setObjectName("genAttrField")
        field.setProperty("attributeType", name)
        field_layout = QVBoxLayout(field)
        field_layout.setContentsMargins(0, 0, 0, 0)
        field_layout.setSpacing(4)
        label_key = "rarity" if name == "Rarity" else "named_weapon"
        label = QLabel(self.get_localized_string(label_key, name))
        label.setObjectName("genAttrLabel")
        field_layout.addWidget(label)

        if name == "Legendary Type": self.legendary_frame = field
        if name == "Pearl Type": self.pearl_frame = field

        combo = NoScrollComboBox()
        
        values = [self.get_localized_string(self._NONE_VALUE)]
        if name == "Rarity":
            df = self.weapon_rarity_df[self.weapon_rarity_df['Manufacturer & Weapon Type ID'] == m_id]
            available = list(df['Stat'].dropna().unique())
            ordered = [rarity for rarity in self.RARITY_ORDER if rarity in available]
            ordered.extend(sorted(set(available) - set(ordered)))
            values.extend(self.get_localized_string(rarity) for rarity in ordered)
        else:
            rarity = name.split()[0]
            special_df = self.weapon_rarity_df[(self.weapon_rarity_df['Manufacturer & Weapon Type ID'] == m_id) & (self.weapon_rarity_df['Stat'] == rarity)]
            values.extend([f"{r['Part ID']} - {r[self.rarity_desc_col]}" for _, r in special_df.iterrows() if pd.notna(r[self.rarity_desc_col]) and r[self.rarity_desc_col]])
        
        # Add to dict BEFORE connecting signals
        self.part_combos[name] = combo
        
        combo.addItem(values[0], None)
        if name == "Rarity":
            for value in values[1:]:
                combo.addItem(value, self._get_english_key(value))
        else:
            for _, rarity_row in special_df.iterrows():
                description = rarity_row[self.rarity_desc_col]
                if pd.notna(description) and description:
                    combo.addItem(f"{rarity_row['Part ID']} - {description}", str(rarity_row['Part ID']))
        
        # Connect signals AFTER adding items to avoid triggering on startup with incomplete state or recursive calls
        if name == "Rarity":
             combo.currentTextChanged.connect(self._on_rarity_change)
        else:
             combo.currentTextChanged.connect(self.generate_weapon)
        
        field_layout.addWidget(combo)
        self.attr_layout.addWidget(field, row, col, Qt.AlignmentFlag.AlignTop)
        
        if name in {"Legendary Type", "Pearl Type"}: field.hide()

    # ------------------------------------------------------------------ #
    # 元素数据分类工具
    # ------------------------------------------------------------------ #
    def _fmt_elem_value(self, row):
        return f"{row['Part_ID']} - {row[self.elemental_stat_col]}"

    def _fmt_pearl_value(self, row):
        """珠光项去掉“珠光属性:/Pearl Stat:”这类前缀及冒号，避免英文下选项过长。"""
        display = str(row[self.elemental_stat_col])
        for sep in (':', '：'):
            if sep in display:
                display = display.split(sep, 1)[1].strip()
                break
        display = display.replace(", ", "\n")
        return f"{row['Part_ID']} - {display}"

    def _element1_values(self):
        """纯元素（腐蚀/冰冻/燃烧/辐射/电击）。"""
        return [self._fmt_elem_value(r) for _, r in self.elemental_df.iterrows()
                if str(r['Stat']).split(' (', 1)[0] in self._PURE_ELEMENTS]

    def _pearl_stat_values(self):
        return [self._fmt_pearl_value(r) for _, r in self.elemental_df.iterrows()
                if str(r['Stat']).startswith("Pearl Stat")]

    def _pearl_element_values(self):
        return [self._fmt_pearl_value(r) for _, r in self.elemental_df.iterrows()
                if str(r['Stat']).startswith("Pearl Elements")]

    def _normal_switch_rows(self):
        return [r for _, r in self.elemental_df.iterrows()
                if str(r['Stat']).startswith("switch between")]

    def _underbarrel_switch_rows(self):
        return [r for _, r in self.elemental_df.iterrows()
                if str(r['Stat']).startswith("Maliwan Underbarrel-switch")]

    def _element_name_of_selection(self, value):
        """由元素1 的选中值解析出元素名（英文），Fire→Incendiary。"""
        none_val = self.get_localized_string(self._NONE_VALUE)
        if not value or value == none_val:
            return None
        pid = value.split(' - ')[0]
        if not pid.isdigit():
            return None
        rows = self.elemental_df[self.elemental_df['Part_ID'] == int(pid)]
        if rows.empty:
            return None
        stat = str(rows.iloc[0]['Stat']).split(' (', 1)[0]
        return "Incendiary" if stat == "Fire" else stat

    def _switch_first_element(self, stat_en):
        """用关键字最小下标法取切换文案的首元素（对漏空格的脏数据也稳）。"""
        best = None
        best_idx = None
        for kw in self._ELEM_KEYWORDS:
            idx = stat_en.find(kw)
            if idx != -1 and (best_idx is None or idx < best_idx):
                best_idx = idx
                best = kw
        return best

    def _underbarrel_has_malswitch(self):
        """当前下挂槽是否选择了“马里旺元素切换下挂”（按 String 判定，语言无关）。"""
        combo = self.part_combos.get("Underbarrel_0")
        if combo is None:
            return False
        pid = combo.currentData()
        if pid is None:
            return False
        pid = str(pid)
        if not pid.isdigit():
            return False
        m_id = self._current_m_id()
        if m_id is None:
            return False
        rows = self.all_weapon_parts_df[
            (self.all_weapon_parts_df['Manufacturer & Weapon Type ID'] == m_id) &
            (self.all_weapon_parts_df['Part Type'] == 'Underbarrel') &
            (self.all_weapon_parts_df['Part ID'] == pid)
        ]
        for _, r in rows.iterrows():
            if 'malswitch' in str(r['String']).lower():
                return True
        return False

    def _refresh_element2(self, *args):
        """依据元素1 首元素 + 下挂是否为 malswitch，重建元素2 可选项。"""
        elem2 = self.part_combos.get("Element 2")
        if elem2 is None:
            return
        elem1 = self.part_combos.get("Element 1")
        elem1_val = elem1.currentText() if elem1 is not None else None
        elem_name = self._element_name_of_selection(elem1_val)

        if elem_name is None:
            elem2.set_values([])
            elem2.setEnabled(False)
            if self.element2_frame is not None:
                self.element2_frame.hide()
            self.generate_weapon()
            return

        values = []
        for r in self._normal_switch_rows():
            if self._switch_first_element(str(r['Stat'])) == elem_name:
                values.append(self._fmt_elem_value(r))
        if self._underbarrel_has_malswitch():
            for r in self._underbarrel_switch_rows():
                if self._switch_first_element(str(r['Stat'])) == elem_name:
                    values.append(self._fmt_elem_value(r))

        elem2.set_values(values)  # 保留原选择；若失效则自动回退 None
        elem2.setEnabled(bool(values))
        if self.element2_frame is not None:
            self.element2_frame.setVisible(bool(values))
        self.generate_weapon()

    def _on_element1_changed(self):
        self._refresh_element2()

    def _create_element_selector(self, name, position):
        row, col = position
        frame = QFrame()
        frame.setObjectName("genElementRow")
        frame.setProperty("attributeType", name)
        row_layout = QHBoxLayout(frame)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(10)
        label_key = "main_element" if name == "Element 1" else "secondary_element"
        label = QLabel(self.get_localized_string(label_key, name))
        label.setObjectName("genAttrLabel")
        label.setMinimumWidth(64)
        row_layout.addWidget(label)

        none_val = self.get_localized_string(self._NONE_VALUE)
        selector = ElementChipSelector(none_val, columns=6 if name == "Element 1" else 4)
        selector.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.part_combos[name] = selector
        self.element_frames[name] = frame

        if name == "Element 1":
            selector.set_values(self._element1_values())
            selector.changed.connect(self._on_element1_changed)
        else:  # Element 2 的可选项由 _refresh_element2 动态填充
            selector.changed.connect(self.generate_weapon)
            self.element2_frame = frame
            frame.hide()

        row_layout.addWidget(selector, 1)
        self.attr_layout.addWidget(frame, row, col, 1, 2, Qt.AlignmentFlag.AlignTop)

    def _create_pearl_selector(self, name, position):
        row, col = position
        title_key = 'pearl_stat' if name == "Pearl Stat" else 'pearl_elements'
        field = QFrame()
        field.setObjectName("genAttrField")
        field.setProperty("attributeType", name)
        field_layout = QVBoxLayout(field)
        field_layout.setContentsMargins(0, 0, 0, 0)
        field_layout.setSpacing(4)
        label = QLabel(self._section_text(title_key))
        label.setObjectName("genAttrLabel")
        field_layout.addWidget(label)

        none_val = self.get_localized_string(self._NONE_VALUE)
        selector = ElementChipSelector(none_val, columns=3)
        values = self._pearl_stat_values() if name == "Pearl Stat" else self._pearl_element_values()
        selector.set_values(values)
        selector.changed.connect(self.generate_weapon)
        self.part_combos[name] = selector

        field_layout.addWidget(selector)
        self.pearl_layout.addWidget(field, row, col, Qt.AlignmentFlag.AlignTop)

    def _set_pearl_expanded(self, expanded):
        self.pearl_settings_frame.setVisible(bool(expanded))

    def _sync_pearl_visibility(self, rarity):
        self._set_pearl_expanded(rarity == "Pearl")

    def _on_rarity_change(self, choice):
        selected = self._get_english_key(choice)
        for rarity, frame in (("Legendary", self.legendary_frame), ("Pearl", self.pearl_frame)):
            frame.setVisible(selected == rarity)
            combo = self.part_combos[f"{rarity} Type"]
            if selected != rarity:
                combo.blockSignals(True)
                combo.setCurrentIndex(0)
                combo.blockSignals(False)

        self._sync_pearl_visibility(selected)
        self.generate_weapon()

    def _get_english_key(self, localized_value):
        if not localized_value or not self.weapon_localization: return localized_value
        reverse_map = {v: k for k, v in self.weapon_localization.items()}
        return reverse_map.get(localized_value, localized_value)

    def randomize_seed(self):
        self.seed_var.setText(str(random.randint(100, 9999)))

    def _set_workspace_page(self, index):
        if not hasattr(self, "page_stack"):
            return
        index = 1 if int(index) == 1 else 0
        self.page_stack.setCurrentIndex(index)
        self.generator_page_button.setChecked(index == 0)
        self.roll_results_button.setChecked(index == 1)

    def _roll_texts(self):
        labels = self.ui_loc.get('labels', {})
        buttons = self.ui_loc.get('buttons', {})
        sections = self.ui_loc.get('sections', {})
        return {
            "constraints_title": sections.get("roll_options", "Roll Options"),
            "results_title": sections.get("roll_results", "Roll Results"),
            "manufacturer": labels.get("manufacturer", "Manufacturer"),
            "weapon_type": labels.get("weapon_type", "Weapon Type"),
            "rarity": labels.get("rarity", "Rarity"),
            "named_weapon": labels.get("named_weapon", "Named Weapon"),
            "count": labels.get("quantity", "Quantity"),
            "random": labels.get("random", "Random"),
            "name": labels.get("name", "Name"),
            "weapon": labels.get("weapon", "Manufacturer / Type"),
            "element": labels.get("element", "Element"),
            "matches": labels.get("matches", "Matches: {count}"),
            "no_matches": labels.get("no_matches", "No matching weapon"),
            "selected_count": labels.get("selected_count", "Selected {count} / {total}"),
            "double_click": labels.get("double_click", "Double-click a row to add it"),
            "current_context": labels.get("current_context", "Uses the current level and Flag"),
            "generated": labels.get("generated", "Generated {count} legal weapons"),
            "no_results": labels.get("no_results", "No generated weapons yet"),
            "select_result": labels.get("select_result", "Select a generated weapon"),
            "no_element": labels.get("no_element", "No Element"),
            "level_value": labels.get("level_value", "Lv{level}"),
            "legal": labels.get("legal", "Legal"),
            "scope_template": labels.get("scope_template", "Manufacturer: {manufacturer} · Type: {weapon_type} · Rarity: {rarity}"),
            "roll": buttons.get("roll", "Roll"),
            "cancel": buttons.get("cancel", "Cancel"),
            "close": buttons.get("close", "Close"),
            "add_one": buttons.get("add_one", "Add This"),
            "copy_base85": buttons.get("copy_base85", "Copy Base85"),
            "add_selected": buttons.get("add_selected", "Add Selected"),
            "add_all": buttons.get("add_all", "Add All"),
            "copied": self.ui_loc.get('dialogs', {}).get("base85_copied", "Base85 copied"),
            "roll_scope_tip": self.ui_loc.get('dialogs', {}).get("roll_scope_tip", ""),
            **{key: self.stats_loc.get(key, key) for key in (
                "damage", "dps", "accuracy", "fire_rate", "reload_time", "magazine"
            )},
        }

    def _weapon_roll_catalog(self):
        catalog = []
        weapons = self.weapon_rules.get("weapons") or {}
        root_column = pd.to_numeric(
            self.all_weapon_parts_df['Manufacturer & Weapon Type ID'], errors='coerce'
        )
        for root_id, weapon in weapons.items():
            rows = self.all_weapon_parts_df[root_column == int(root_id)]
            if rows.empty:
                continue
            manufacturer = str(rows.iloc[0]['Manufacturer'])
            weapon_type = str(rows.iloc[0]['Weapon Type'])
            manufacturer_label = self.get_localized_string(manufacturer, manufacturer)
            weapon_type_label = self.weapon_taxonomy.get(
                weapon_type.casefold().replace(" ", "_"),
                self.get_localized_string(weapon_type, weapon_type),
            )
            for composition_ref, composition in (weapon.get("compositions") or {}).items():
                if composition.get("availability") != "coregame":
                    continue
                if "npc_weapon" in {str(tag).casefold() for tag in composition.get("base_tags", ())}:
                    continue
                rarity = str(composition.get("rarity") or "")
                names = composition.get("name") or {}
                named = bool(str(names.get("en") or "").strip() or str(names.get("zh") or "").strip())
                preferred_name = names.get("zh") if self.current_lang == 'zh-CN' else names.get("en")
                name = str(preferred_name or names.get("en") or names.get("zh") or "").strip()
                rarity_label = self.weapon_taxonomy.get(
                    rarity.casefold(), self.get_localized_string(rarity, rarity)
                )
                catalog.append({
                    "root_id": str(root_id),
                    "composition_ref": str(composition_ref),
                    "manufacturer": manufacturer,
                    "manufacturer_label": manufacturer_label,
                    "weapon_type": weapon_type,
                    "weapon_type_label": weapon_type_label,
                    "rarity": rarity,
                    "rarity_label": rarity_label,
                    "name": name if named else "",
                    "is_named": named and rarity in {"Legendary", "Pearl"},
                })
        return catalog

    @staticmethod
    def _roll_serial_token(ref, root_id):
        ref_root, _, part_id = str(ref).partition(":")
        return f"{{{part_id}}}" if ref_root == str(root_id) else f"{{{ref_root}:{part_id}}}"

    def _roll_part_tags(self, ref):
        return (
            (self.weapon_rules.get("part_selection_tags") or {}).get(str(ref))
            or (self.item_index.get("part_refs") or {}).get(str(ref), {}).get("selection_tags")
            or {}
        )

    def _roll_element_text(self, selected_refs):
        values = []
        part_refs = self.item_index.get("part_refs") or {}
        for ref in selected_refs:
            group = str((part_refs.get(str(ref)) or {}).get("selection_group") or "").casefold()
            if group not in {"body_ele", "secondary_ele", "pearl_elem"}:
                continue
            _root, _sep, part_id = str(ref).partition(":")
            if not part_id.isdigit():
                continue
            rows = self.elemental_df[self.elemental_df['Part_ID'] == int(part_id)]
            if rows.empty:
                continue
            value = str(rows.iloc[0].get(self.elemental_stat_col) or "").strip()
            if group == "pearl_elem" and ':' in value:
                value = value.split(':', 1)[1].strip()
            if value and value not in values:
                values.append(value)
        return " / ".join(values)

    @staticmethod
    def _filter_roll_catalog(catalog, constraints):
        return [
            row for row in catalog
            if (constraints.get("manufacturer") is None or row["manufacturer"] == constraints["manufacturer"])
            and (constraints.get("weapon_type") is None or row["weapon_type"] == constraints["weapon_type"])
            and (constraints.get("rarity") is None or row["rarity"] == constraints["rarity"])
            and (constraints.get("composition_ref") is None or row["composition_ref"] == constraints["composition_ref"])
        ]

    def _roll_one_weapon(self, candidate, rng):
        root_id = candidate["root_id"]
        weapon = (self.weapon_rules.get("weapons") or {})[root_id]
        composition = weapon["compositions"][candidate["composition_ref"]]
        selected = sample_composition_parts(
            composition=composition,
            part_types=weapon.get("part_types") or (),
            tags_for_ref=self._roll_part_tags,
            excluded_refs=set((self.weapon_rules.get("part_availability") or {}).keys()),
            rng=rng,
        )
        level = self.level_var.text() if self.level_var.text().isdigit() else self._character_level
        seed = rng.randint(100, 9999)
        refs = [candidate["composition_ref"], *selected]
        components = " ".join(self._roll_serial_token(ref, root_id) for ref in refs)
        decoded = f"{root_id}, 0, 1, {level}| 2, {seed}|| {components} |"
        serial, error = b_encoder.encode_to_base85(decoded)
        if error:
            raise ValueError(error)
        validation = item_display_resolver.validate_weapon_generation(decoded)
        if validation.get("status") != "legal":
            raise ValueError(", ".join(
                str(item.get("code")) for item in validation.get("violations", ())
            ) or str(validation.get("status")))
        display = item_display_resolver.resolve_item_display(
            int(root_id), candidate["manufacturer"], candidate["weapon_type"], decoded, self.current_lang
        )
        stats = item_display_resolver.resolve_weapon_stats(decoded)
        formatted_stats = {
            key: item_display_resolver.format_weapon_stat(key, stats.get(key), self.current_lang) or "—"
            for key in item_display_resolver.WEAPON_STAT_KEYS
        }
        name = display.get("display_name") or candidate.get("name") or "—"
        rarity = display.get("rarity") or candidate["rarity_label"]
        element = self._roll_element_text(selected)
        type_label = f"{candidate['manufacturer_label']} · {candidate['weapon_type_label']}"
        tooltip_lines = [name, type_label, f"{self.get_localized_string('rarity', 'Rarity')}: {rarity}"]
        if element:
            tooltip_lines.append(f"{self.get_localized_string('element', 'Element')}: {element}")
        tooltip_lines.extend(
            f"{self.stats_loc.get(key, key)}: {formatted_stats[key]}"
            for key in item_display_resolver.WEAPON_STAT_KEYS
        )
        tooltip_lines.append(f"Base85: {serial}")
        return {
            **candidate,
            "serial": serial,
            "decoded": decoded,
            "level": level,
            "name": name,
            "manufacturer": candidate["manufacturer_label"],
            "weapon_type": candidate["weapon_type_label"],
            "type_label": type_label,
            "rarity": rarity,
            "rarity_key": candidate["rarity"],
            "element": element,
            "status": "legal",
            "status_label": self._rule_message("status_legal", "自然生成", "Legal"),
            "stats": stats,
            "formatted_stats": formatted_stats,
            "tooltip": "\n".join(tooltip_lines),
        }

    def _roll_weapons(self, constraints, count):
        constraints = dict(constraints or {})
        count = max(1, min(50, int(count)))
        self._roll_constraints = constraints
        self._roll_count = count
        catalog = self._filter_roll_catalog(self._weapon_roll_catalog(), constraints)
        if not catalog:
            QMessageBox.warning(
                self,
                self._section_text('roll_options'),
                self.ui_loc.get('dialogs', {}).get('no_legal_result', 'No legal build matches the filters.'),
            )
            return
        rng = random.SystemRandom()
        roots = sorted({row["root_id"] for row in catalog}, key=int)
        results = []
        self.roll_results_page.set_add_status(
            self.ui_loc.get('dialogs', {}).get('roll_running', 'Rolling...'), busy=True
        )
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for _ in range(int(count)):
                last_error = None
                for _attempt in range(24):
                    root_id = rng.choice(roots)
                    candidate = rng.choice([row for row in catalog if row["root_id"] == root_id])
                    try:
                        results.append(self._roll_one_weapon(candidate, rng))
                        break
                    except Exception as exc:
                        last_error = exc
                else:
                    raise RuntimeError(last_error or "no legal result")
        except Exception as exc:
            self.roll_results_page.set_add_status("", busy=False)
            QMessageBox.critical(
                self,
                self._section_text('roll_options'),
                self.ui_loc.get('dialogs', {}).get('roll_failed', 'Roll failed: {error}').format(error=exc),
            )
            return
        finally:
            QApplication.restoreOverrideCursor()
        texts = self._roll_texts()
        self.roll_results_page.set_results(
            results,
            texts["generated"].format(count=len(results)),
            self._roll_scope_text(constraints),
        )
        self.roll_results_page.set_add_status("", busy=False)
        self._set_workspace_page(1)

    def _roll_scope_text(self, constraints):
        texts = self._roll_texts()
        catalog = self._weapon_roll_catalog()
        random_text = texts["random"]

        def label(field, label_field):
            value = constraints.get(field)
            if value is None:
                return random_text
            row = next((item for item in catalog if item.get(field) == value), None)
            return str((row or {}).get(label_field) or value)

        return texts["scope_template"].format(
            manufacturer=label("manufacturer", "manufacturer_label"),
            weapon_type=label("weapon_type", "weapon_type_label"),
            rarity=label("rarity", "rarity_label"),
        )

    def _quick_roll(self, _checked=False):
        if self._roll_options_widget is None:
            self._roll_weapons({}, self._roll_count)
            return
        self._roll_weapons(
            self._roll_options_widget.constraints(), self._roll_options_widget.count_spin.value()
        )

    def _roll_from_menu(self, constraints, count):
        if self._roll_menu is not None:
            self._roll_menu.hide()
        self._roll_weapons(constraints, count)

    def _request_roll_add(self, serials):
        if not serials or self._roll_add_busy:
            return
        self._roll_add_busy = True
        flag = self.flag_combo.currentText().split(" ")[0]
        self.roll_results_page.set_add_status(
            self.ui_loc.get('dialogs', {}).get('roll_add_start', 'Adding {count} item(s)...').format(
                count=len(serials)
            ),
            busy=True,
        )
        self.batch_add_to_backpack_requested.emit(list(serials), flag)

    def update_roll_add_progress(self, current, total, success, fail):
        self.roll_results_page.set_add_status(
            self.ui_loc.get('dialogs', {}).get(
                'roll_add_progress', 'Adding {current}/{total} · success {success} · failed {fail}'
            ).format(current=current, total=total, success=success, fail=fail),
            busy=True,
        )

    def finalize_roll_batch_add(self, success, fail):
        self._roll_add_busy = False
        self.roll_results_page.set_add_status(
            self.ui_loc.get('dialogs', {}).get(
                'roll_add_done', 'Added {success}; failed {fail}'
            ).format(success=success, fail=fail),
            busy=False,
        )

    def generate_weapon(self, *args):
        try:
            self._refresh_conditional_part_options()
            mfg_en = self._get_english_key(self.manufacturer_combo.currentText())
            wt_en = self._get_english_key(self.weapon_type_combo.currentText())
            m_id = self._get_m_id(mfg_en, wt_en)
            if m_id is None:
                self._update_weapon_stats("")
                return

            level = self.level_var.text() if self.level_var.text().isdigit() else self._character_level
            seed = self.seed_var.text() if self.seed_var.text().isdigit() else str(random.randint(100, 9999))
            
            header = f"{m_id}, 0, 1, {level}| 2, {seed}||"
            parts_list = []
            
            localized_none = self.get_localized_string(self._NONE_VALUE)
            
            # Rarity / named Legendary or Pearl skin
            rarity_combo = self.part_combos.get("Rarity")
            selected_rarity = self._get_english_key(rarity_combo.currentText()) if rarity_combo else ""

            if selected_rarity in {"Legendary", "Pearl"}:
                special_combo = self.part_combos.get(f"{selected_rarity} Type")
                if special_combo and special_combo.currentData() is not None:
                    part_id = str(special_combo.currentData())
                    if part_id.isdigit(): parts_list.append(f"{{{part_id}}}")
            elif rarity_combo and rarity_combo.currentText() != localized_none:
                 rarity_id_row = self.weapon_rarity_df[(self.weapon_rarity_df['Manufacturer & Weapon Type ID'] == m_id) & (self.weapon_rarity_df['Stat'] == selected_rarity) & (self.weapon_rarity_df['Description'].isna())]
                 if not rarity_id_row.empty: parts_list.append(f"{{{rarity_id_row.iloc[0]['Part ID']}}}")
            
            # Elements / Pearl（均属 elemental，Elemental_ID=1，编码为 {1:pid}）
            for name in ["Element 1", "Element 2", "Pearl Stat", "Pearl Elements"]:
                selector = self.part_combos.get(name)
                if selector and selector.currentText() != localized_none:
                    part_id = selector.currentText().split(' - ')[0]
                    if part_id.isdigit(): parts_list.append(f"{{1:{part_id}}}")
            
            # Other parts
            special_parts = {"Rarity", "Legendary Type", "Pearl Type", "Element 1", "Element 2", "Pearl Stat", "Pearl Elements"}
            for key, combo in self.part_combos.items():
                part_type_base = key.split('_')[0]
                if part_type_base in special_parts or key in special_parts: continue

                value = combo.currentText()
                if value != localized_none and combo.currentData() is not None:
                    part_id = str(combo.currentData())
                    if part_id.isdigit(): parts_list.append(f"{{{part_id}}}")
            
            component_str = " ".join(parts_list)
            full_decoded_str = f"{header} {component_str} |"
            encoded_serial, err = b_encoder.encode_to_base85(full_decoded_str)
            self._encode_error = bool(err)
            if err:
                self.serial_b85_entry.clear()
                raise ValueError(err)
            
            self.serial_decoded_entry.setText(full_decoded_str)
            self.serial_b85_entry.setText(encoded_serial)
            self._update_weapon_stats(full_decoded_str)
            self._refresh_part_descriptions(full_decoded_str)
            self._update_generation_rule_guidance(full_decoded_str)
        except Exception as e:
            self._encode_error = True
            self.serial_b85_entry.clear()
            # Maybe log this to a status bar in the future
            print(f"Weapon generation error: {e}")
            self._update_weapon_stats("")
            self._update_generation_rule_guidance("")

    def _update_weapon_stats(self, decoded_str):
        stats = item_display_resolver.resolve_weapon_stats(decoded_str) if decoded_str else {}
        for key, label in self.weapon_stat_value_labels.items():
            label.setText(item_display_resolver.format_weapon_stat(key, stats.get(key), self.current_lang) or "—")

    def _on_add_to_backpack(self):
        serial = self.serial_b85_entry.text()
        if not serial or getattr(self, '_encode_error', False):
            QMessageBox.warning(self, self.ui_loc.get('dialogs', {}).get('no_serial_title', "No serial"),
                                self.ui_loc.get('dialogs', {}).get('gen_first', "Please generate a weapon first."))
            return
        
        flag = self.flag_combo.currentText().split(" ")[0]
        # 发射信号，让主窗口去处理
        self.add_to_backpack_requested.emit(serial, flag)

    def set_character_level(self, level: str):
        """设置角色等级，更新默认等级显示。"""
        self._character_level = level if level else "50"
        if hasattr(self, 'level_var'):
            self.level_var.setText(self._character_level)
