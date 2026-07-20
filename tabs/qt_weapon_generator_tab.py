import random
import pandas as pd
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QComboBox, QPushButton, QMessageBox, QScrollArea, QFrame, QGroupBox,
    QSizePolicy, QButtonGroup
)
from PyQt6.QtCore import pyqtSignal, Qt

from core import b_encoder, item_display_resolver, resource_loader


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


class ElementChipSelector(QWidget):
    """单选芯片组：把固定的小选项集渲染成一排可点选的圆角芯片（含 None）。
    对外暴露与 QComboBox 兼容的 currentText()，方便沿用既有生成逻辑。"""

    changed = pyqtSignal()
    _COLUMNS = 3

    def __init__(self, none_text, parent=None):
        super().__init__(parent)
        self._none_text = none_text
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(6)
        self._grid.setVerticalSpacing(6)
        self._grid.setColumnStretch(self._COLUMNS, 1)
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
            btn = QPushButton(self._label_of(v))
            btn.setObjectName("elemChip")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            lines = btn.text().count("\n") + 1
            btn.setMinimumHeight(max(28, lines * btn.fontMetrics().lineSpacing() + 12))
            btn.setProperty("chipValue", v)
            btn.setToolTip(v)
            self._group.addButton(btn)
            self._grid.addWidget(btn, i // self._COLUMNS, i % self._COLUMNS)
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

    _NONE_VALUE = "None"
    RARITY_ORDER = ("Common", "Uncommon", "Rare", "Epic", "Legendary", "Pearl")

    # 纯元素（元素1 可选）与首元素解析关键字
    _PURE_ELEMENTS = {"Corrosive", "Cryo", "Fire", "Radiation", "Shock"}
    _ELEM_KEYWORDS = ["Shock", "Radiation", "Incendiary", "Cryo", "Corrosive"]

    # 属性卡片内的布局：元素1 → 珠光属性 → 珠光元素 → 元素2
    ATTR_LAYOUT = {
        "Rarity": (0, 0), "Legendary Type": (0, 1), "Pearl Type": (0, 1),
        "Element 1": (1, 0), "Pearl Stat": (1, 1),
        "Pearl Elements": (2, 0), "Element 2": (2, 1),
    }

    # 部件容器内的布局：按武器结构顺序，主件在左、其附件/相关件在右
    PART_LAYOUT = {
        "Body": (0, 0), "Body Accessory": (0, 1),
        "Barrel": (1, 0), "Barrel Accessory": (1, 1),
        "Magazine": (2, 0), "Stat Modifier": (2, 1),
        "Grip": (3, 0), "Foregrip": (3, 1),
        "Scope": (4, 0), "Scope Accessory": (4, 1),
        "Underbarrel": (5, 0), "Underbarrel Accessory": (5, 1),
        "Manufacturer Part": (6, 0), "Tediore Payload": (6, 1),
        "Tediore Throw Reload": (7, 0), "Borg Magazine Adapter": (7, 1),
        "Special Element Set": (8, 0),
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
        'elem2_hint': 'Underbarrel element switch appears after selecting the related part.',
        'need_elem1': 'Select Element 1 first',
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.all_weapon_parts_df = None
        self.elemental_df = None
        self.weapon_rarity_df = None
        self.weapon_localization = None
        self.part_combos = {}
        self.part_combo_rows = {}
        self.part_group_boxes = {}
        self.part_detail_labels = {}
        self.legendary_frame = None # Initialize to None
        self.elem2_hint = None
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
        self.stats_loc = full_loc.get("weapon_editor_tab", {}).get("stats", {})
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
        self.part_detail_labels = {}
        self.legendary_frame = None
        self.elem2_hint = None
        
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
        main_layout = QVBoxLayout(self.content_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(10)
        self.main_layout.addWidget(self.content_widget)

        # --- 输出框（序列展示，保持不动） ---
        output_frame = QFrame(self.content_widget); output_frame.setLayout(QGridLayout())
        self.serial_decoded_entry = QLineEdit(); self.serial_decoded_entry.setReadOnly(True)
        self.serial_b85_entry = QLineEdit(); self.serial_b85_entry.setReadOnly(True)
        output_frame.layout().addWidget(QLabel(self.get_localized_string("serial_decoded")), 0, 0)
        output_frame.layout().addWidget(self.serial_decoded_entry, 0, 1)
        output_frame.layout().addWidget(QLabel(self.get_localized_string("serial_b85")), 1, 0)
        output_frame.layout().addWidget(self.serial_b85_entry, 1, 1)
        main_layout.addWidget(output_frame)

        # --- 配置卡片（固定在滚动区之外）：厂商 / 武器类型 / 等级 / 种子 ---
        config_card = QFrame(self.content_widget)
        config_card.setObjectName("genConfigCard")
        config_v = QVBoxLayout(config_card)
        config_v.setContentsMargins(14, 12, 14, 12)
        config_v.setSpacing(8)
        config_v.addWidget(self._make_section_title(self._section_text('config')))

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
        main_layout.addWidget(config_card)

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
        main_layout.addWidget(stats_frame)

        # --- 滚动区：属性卡片 + 部件容器 ---
        self.parts_scroll_area = QScrollArea()
        self.parts_scroll_area.setWidgetResizable(True)
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
        attr_v.addWidget(self._make_section_title(self._section_text('attributes')))
        attr_grid_holder = QWidget()
        self.attr_layout = QGridLayout(attr_grid_holder)
        self.attr_layout.setContentsMargins(0, 0, 0, 0)
        self.attr_layout.setHorizontalSpacing(12)
        self.attr_layout.setVerticalSpacing(10)
        attr_v.addWidget(attr_grid_holder)
        scroll_layout.addWidget(attr_card)

        # 部件容器
        parts_card = QFrame()
        parts_card.setObjectName("genPartsContainer")
        parts_v = QVBoxLayout(parts_card)
        parts_v.setContentsMargins(14, 12, 14, 12)
        parts_v.setSpacing(8)
        parts_v.addWidget(self._make_section_title(self._section_text('parts')))
        self.parts_frame = QWidget()
        self.parts_layout = QGridLayout(self.parts_frame)
        self.parts_layout.setContentsMargins(0, 0, 0, 0)
        self.parts_layout.setHorizontalSpacing(12)
        self.parts_layout.setVerticalSpacing(10)
        self.parts_layout.setColumnStretch(0, 1)
        self.parts_layout.setColumnStretch(1, 1)
        parts_v.addWidget(self.parts_frame)
        scroll_layout.addWidget(parts_card)
        scroll_layout.addStretch()

        self.parts_scroll_area.setWidget(scroll_content)
        main_layout.addWidget(self.parts_scroll_area, 1)

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
        self._clear_layout(self.parts_layout)
        self.part_combos = {}
        self.part_combo_rows = {}
        self.part_group_boxes = {}
        self.part_detail_labels = {}
        # IMPORTANT: Clear reference to the deleted widget to prevent crash if signal handlers traverse it
        self.legendary_frame = None
        self.pearl_frame = None
        self.elem2_hint = None
        
        selected_mfg_en = self._get_english_key(self.manufacturer_combo.currentText())
        selected_wt_en = self._get_english_key(self.weapon_type_combo.currentText())

        m_id = self._get_m_id(selected_mfg_en, selected_wt_en)
        if m_id is None: return

        self._create_special_dropdown("Rarity", m_id, self.ATTR_LAYOUT["Rarity"])
        self._create_special_dropdown("Legendary Type", m_id, self.ATTR_LAYOUT["Legendary Type"])
        self._create_special_dropdown("Pearl Type", m_id, self.ATTR_LAYOUT["Pearl Type"])

        # 元素 / 珠光：芯片单选。顺序：元素1 → 珠光属性 → 珠光元素 → 元素2
        self._create_element_selector("Element 1", self.ATTR_LAYOUT["Element 1"])
        self._create_pearl_selector("Pearl Stat", self.ATTR_LAYOUT["Pearl Stat"])
        self._create_pearl_selector("Pearl Elements", self.ATTR_LAYOUT["Pearl Elements"])
        self._create_element_selector("Element 2", self.ATTR_LAYOUT["Element 2"])

        filtered_df = self.all_weapon_parts_df[self.all_weapon_parts_df['Manufacturer & Weapon Type ID'] == m_id]
        for part_type_en, group_df in filtered_df.groupby('Part Type'):
            if part_type_en not in self.PART_LAYOUT: continue
            
            row, col = self.PART_LAYOUT[part_type_en]
            
            group_box = QGroupBox(self.get_localized_string(part_type_en))
            group_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
            group_layout = QVBoxLayout(group_box)
            self.part_group_boxes[part_type_en] = group_box

            num_slots = self.MULTI_SELECT_SLOTS.get(part_type_en, 1)
            if num_slots > 1:
                badge = QLabel(f"{self._section_text('multi')} ×{num_slots}")
                badge.setObjectName("multiBadge")
                badge.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
                group_layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignLeft)

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
                detail.hide()
                self.part_detail_labels[combo_key] = detail
                group_layout.addWidget(detail)
            
            self.parts_layout.addWidget(group_box, row, col, Qt.AlignmentFlag.AlignTop)

        # 部件建好后，依据元素1 / 下挂初始化元素2 的可选项
        self._refresh_conditional_part_options()
        self._refresh_element2()
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
        for _ in range(2):
            available_tags = self._selected_part_adds(item_id)
            for key, rows in self.part_combo_rows.items():
                part_type = key.rsplit('_', 1)[0]
                if part_type not in self.CONDITIONAL_PART_TYPES:
                    continue
                combo = self.part_combos[key]
                selected = combo.currentData()
                decoded = self.serial_decoded_entry.text() if hasattr(self, 'serial_decoded_entry') else ""
                allowed = []
                for _, row in rows.iterrows():
                    part_id = str(row['Part ID'])
                    tags = item_display_resolver.weapon_part_selection_tags(item_id, part_id)
                    if set(tags.get("requires", [])) <= available_tags and not set(tags.get("excludes", [])).intersection(available_tags):
                        allowed.append((part_id, row))
                combo.blockSignals(True)
                combo.clear()
                combo.addItem(none_text, None)
                for part_id, row in allowed:
                    combo.addItem(self._part_option_text(item_id, part_id, row, decoded), part_id)
                    combo.setItemData(combo.count() - 1, combo.itemText(combo.count() - 1), Qt.ItemDataRole.ToolTipRole)
                selected_index = combo.findData(selected)
                combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)
                combo.blockSignals(False)
                group = self.part_group_boxes.get(part_type)
                if group is not None:
                    group.setVisible(bool(allowed))

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
                detail.setVisible(bool(description))
            elif detail is not None:
                detail.hide()

    def _create_special_dropdown(self, name, m_id, position):
        row, col = position
        
        group_box = QGroupBox(self.get_localized_string(name.replace(" ", ""), name))
        group_layout = QVBoxLayout(group_box)
        
        if name == "Legendary Type": self.legendary_frame = group_box
        if name == "Pearl Type": self.pearl_frame = group_box

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
        
        group_layout.addWidget(combo)
        self.attr_layout.addWidget(group_box, row, col, Qt.AlignmentFlag.AlignTop)
        
        if name in {"Legendary Type", "Pearl Type"}: group_box.hide()

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
                if str(r['Stat']) in self._PURE_ELEMENTS]

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
        stat = str(rows.iloc[0]['Stat'])
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
            # 元素1 未选：元素2 置灰，只有 None，并提示先选元素1
            elem2.set_values([])
            elem2.setEnabled(False)
            if self.elem2_hint is not None:
                self.elem2_hint.setText(self._section_text('need_elem1'))
            self.generate_weapon()
            return

        elem2.setEnabled(True)
        values = []
        for r in self._normal_switch_rows():
            if self._switch_first_element(str(r['Stat'])) == elem_name:
                values.append(self._fmt_elem_value(r))
        if self._underbarrel_has_malswitch():
            for r in self._underbarrel_switch_rows():
                if self._switch_first_element(str(r['Stat'])) == elem_name:
                    values.append(self._fmt_elem_value(r))

        elem2.set_values(values)  # 保留原选择；若失效则自动回退 None
        if self.elem2_hint is not None:
            self.elem2_hint.setText(self._section_text('elem2_hint'))
        self.generate_weapon()

    def _on_element1_changed(self):
        self._refresh_element2()

    def _create_element_selector(self, name, position):
        row, col = position
        group_box = QGroupBox(self.get_localized_string(name.replace(" ", "")))
        group_layout = QVBoxLayout(group_box)

        none_val = self.get_localized_string(self._NONE_VALUE)
        selector = ElementChipSelector(none_val)
        self.part_combos[name] = selector

        if name == "Element 1":
            selector.set_values(self._element1_values())
            selector.changed.connect(self._on_element1_changed)
        else:  # Element 2 的可选项由 _refresh_element2 动态填充
            selector.changed.connect(self.generate_weapon)

        group_layout.addWidget(selector)

        if name == "Element 2":
            self.elem2_hint = QLabel(self._section_text('elem2_hint'))
            self.elem2_hint.setObjectName("genHint")
            self.elem2_hint.setWordWrap(True)
            group_layout.addWidget(self.elem2_hint)

        self.attr_layout.addWidget(group_box, row, col, Qt.AlignmentFlag.AlignTop)

    def _create_pearl_selector(self, name, position):
        row, col = position
        title_key = 'pearl_stat' if name == "Pearl Stat" else 'pearl_elements'
        group_box = QGroupBox(self._section_text(title_key))
        group_layout = QVBoxLayout(group_box)

        none_val = self.get_localized_string(self._NONE_VALUE)
        selector = ElementChipSelector(none_val)
        values = self._pearl_stat_values() if name == "Pearl Stat" else self._pearl_element_values()
        selector.set_values(values)
        selector.changed.connect(self.generate_weapon)
        self.part_combos[name] = selector

        group_layout.addWidget(selector)
        self.attr_layout.addWidget(group_box, row, col, Qt.AlignmentFlag.AlignTop)

    def _on_rarity_change(self, choice):
        selected = self._get_english_key(choice)
        for rarity, frame in (("Legendary", self.legendary_frame), ("Pearl", self.pearl_frame)):
            frame.setVisible(selected == rarity)
            combo = self.part_combos[f"{rarity} Type"]
            if selected != rarity:
                combo.blockSignals(True)
                combo.setCurrentIndex(0)
                combo.blockSignals(False)
            
        self.generate_weapon()

    def _get_english_key(self, localized_value):
        if not localized_value or not self.weapon_localization: return localized_value
        reverse_map = {v: k for k, v in self.weapon_localization.items()}
        return reverse_map.get(localized_value, localized_value)

    def randomize_seed(self):
        self.seed_var.setText(str(random.randint(100, 9999)))

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
        except Exception as e:
            self._encode_error = True
            self.serial_b85_entry.clear()
            # Maybe log this to a status bar in the future
            print(f"Weapon generation error: {e}")
            self._update_weapon_stats("")

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
