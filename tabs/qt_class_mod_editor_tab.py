import json
import random
import re
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QComboBox, QListWidget, QTreeWidget, QTreeWidgetItem,
    QScrollArea, QMessageBox, QInputDialog, QAbstractItemView, QSpinBox
)
from PyQt6.QtGui import QIcon, QFontMetrics, QFont
from PyQt6.QtWidgets import QToolTip
from PyQt6.QtCore import pyqtSignal, Qt, QSize

from core import b_encoder
from core import resource_loader

# Load all skill descriptions at startup
skill_descriptions = resource_loader.load_all_skill_descriptions()

class SkillPointWidget(QWidget):
    valueChanged = pyqtSignal(int)

    def __init__(self, current_val=0, max_val=5, parent=None, loc_data=None):
        super().__init__(parent)
        self.current = current_val
        self.max_val = max_val
        self.loc = loc_data

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        min_text = self.loc['min'] if self.loc else "Min"
        max_text = self.loc['max'] if self.loc else "Max"

        self.btn_min = QPushButton(min_text)
        self.btn_min.setFixedSize(QSize(55, 35)) # Increased size
        self.btn_min.clicked.connect(self.to_min)

        self.btn_minus = QPushButton("-")
        self.btn_minus.setFixedSize(QSize(35, 35)) # Increased size
        self.btn_minus.clicked.connect(self.decrease)
        
        self.input_field = QLineEdit(str(self.current))
        self.input_field.setFixedSize(QSize(35, 35)) # Adjusted width and height matching buttons
        self.input_field.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.input_field.editingFinished.connect(self.update_from_text)

        self.btn_plus = QPushButton("+")
        self.btn_plus.setFixedSize(QSize(35, 35)) # Increased size
        self.btn_plus.clicked.connect(self.increase)

        self.btn_max = QPushButton(max_text)
        self.btn_max.setFixedSize(QSize(55, 35)) # Increased size
        self.btn_max.clicked.connect(self.to_max)

        layout.addWidget(self.btn_min)
        layout.addWidget(self.btn_minus)
        layout.addWidget(self.input_field)
        layout.addWidget(self.btn_plus)
        layout.addWidget(self.btn_max)
        
        self.update_ui()

    def to_min(self):
        if self.current > 0:
            self.current = 0
            self.update_ui()
            self.valueChanged.emit(self.current)

    def to_max(self):
        if self.current < self.max_val:
            self.current = self.max_val
            self.update_ui()
            self.valueChanged.emit(self.current)

    def decrease(self):
        if self.current > 0:
            self.current -= 1
            self.update_ui()
            self.valueChanged.emit(self.current)

    def increase(self):
        if self.current < self.max_val:
            self.current += 1
            self.update_ui()
            self.valueChanged.emit(self.current)
            
    def update_from_text(self):
        text = self.input_field.text()
        if text.isdigit():
            val = int(text)
            if val < 0: val = 0
            if val > self.max_val: val = self.max_val
            self.current = val
        else:
            pass
        self.update_ui()
        self.valueChanged.emit(self.current)

    def update_ui(self):
        self.input_field.setText(str(self.current))
        self.btn_minus.setEnabled(self.current > 0)
        self.btn_min.setEnabled(self.current > 0)
        self.btn_plus.setEnabled(self.current < self.max_val)
        self.btn_max.setEnabled(self.current < self.max_val)

class QtClassModEditorTab(QWidget):
    add_to_backpack_requested = pyqtSignal(str, str)
    
    # 职业ID常量
    CLASS_IDS = {'Amon': 255, 'Harlowe': 259, 'Rafa': 256, 'Vex': 254}
    CLASS_NAMES = ['Amon', 'Harlowe', 'Rafa', 'Vex']  # 保持顺序一致

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_lang = 'zh-CN'
        
        self.ui_loc = self._load_ui_localization()
        self.localization = self._load_localization()  # 仅用于职业/稀有度名称
        self.skill_descriptions = skill_descriptions
        self.image_cache = {}
        self.current_skill_points = {}
        
        # 加载CSV数据
        self._load_csv_data()

        # Set a global font for tooltips for better readability
        font = QFont()
        font.setPointSize(12) # Larger font size
        QToolTip.setFont(font)

        main_layout = QVBoxLayout(self)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        main_layout.addWidget(self.scroll_area)

        self._rebuild_ui()

    def _rebuild_ui(self):
        # Clean up old container if exists
        if self.scroll_area.widget():
            old_widget = self.scroll_area.widget()
            old_widget.deleteLater()

        container = QWidget()
        self.scroll_area.setWidget(container)
        
        self.container_layout = QVBoxLayout(container)
        
        self._create_top_controls()
        self._create_legendary_group()
        self._create_output_group()
        self._create_skills_and_perks_group()

        self.populate_initial_data()
        self._connect_signals()
        
    def _(self, text, class_name=None):
        """
        获取本地化文本
        对于职业/稀有度名称，使用localization字典
        对于技能/名称/perk，从CSV数据中获取
        """
        # 职业和稀有度名称仍使用localization
        if text in self.localization:
            return self.localization[text]
        return text

    def _load_csv_data(self):
        """加载所有CSV数据"""
        self.names_data = resource_loader.load_class_mods_csv("Class_rarity_name.csv")
        self.skills_data = resource_loader.load_class_mods_csv("Skills.csv")
        self.perks_data = resource_loader.load_class_mods_csv("Class_perk.csv")
        self.legendary_map_data = resource_loader.load_class_mods_csv("Class_legendary_map.csv")
        
        # 构建快速查找索引
        self._build_data_indexes()
    
    def _build_data_indexes(self):
        """构建数据索引以加速查找"""
        # 按class_ID索引技能
        self.skills_by_class = {}
        for skill in self.skills_data:
            class_id = skill.get('class_ID', '')
            if class_id not in self.skills_by_class:
                self.skills_by_class[class_id] = []
            self.skills_by_class[class_id].append(skill)
        
        # 按class_ID和rarity索引名称
        self.names_by_class_rarity = {}
        for name in self.names_data:
            key = (name.get('class_ID', ''), name.get('rarity', ''))
            if key not in self.names_by_class_rarity:
                self.names_by_class_rarity[key] = []
            self.names_by_class_rarity[key].append(name)
        
        # 按perk_ID索引perks
        self.perks_by_id = {p['perk_ID']: p for p in self.perks_data}

    def _load_localization(self, lang=None):
        """加载本地化数据 - 仅用于职业和稀有度名称"""
        if lang is None: lang = self.current_lang
        # 英语等语言不需要翻译
        if lang in ['en-US', 'ru', 'ua']:
            return {}
        try:
            return resource_loader.load_class_mods_json("class_localization.json") or {}
        except Exception as e:
            print(f"加载本地化文件失败: {e}")
            return {}

    def _load_ui_localization(self, lang=None):
        if lang is None: lang = self.current_lang
        filename = resource_loader.get_ui_localization_file(lang)
        data = resource_loader.load_json_resource(filename)
        if data and "class_mod_tab" in data:
            return data["class_mod_tab"]
        else:
            # Fallback
            return {
                "top_controls": {"class": "Class", "rarity": "Rarity", "name": "Name", "seed": "Seed"},
                "legendary": {"title": "Legendary Additions", "clear": "Clear"},
                "output": {"title": "Output", "base85": "Base85:", "deserialize": "Deserialize:", "add_to_backpack": "Add"},
                "skills": {"title": "Skills", "search_placeholder": "Search...", "header_icon": "Icon", "header_skill": "Skill", "header_codes": "Codes", "header_points": "Points"},
                "perks": {"title": "Perks", "search_placeholder": "Search...", "clear": "Clear"},
                "skill_point_widget": {"min": "Min", "max": "Max"},
                "dialogs": {"error": "Error", "load_error_code": "Code Load Error: {error}", "warning": "Warning", "load_error_loc": "Loc Load Error: {error}", 
                            "no_data": "No Data", "no_valid_base85": "No valid Base85", "coding_error": "Error: {error}", "gen_error": "Error: {error}"},
                "tooltips": {"type": "Type"}
            }

    def update_language(self, lang):
        print(f"DEBUG: Updating language for {self.__class__.__name__} to {lang}...")
        self.current_lang = lang
        self.ui_loc = self._load_ui_localization(lang)
        self.localization = self._load_localization(lang)
        
        # Save state
        curr_seed = self.seed_edit.text() if hasattr(self, 'seed_edit') else ""
        
        self._rebuild_ui()
        
        if curr_seed and hasattr(self, 'seed_edit'): self.seed_edit.setText(curr_seed)
        
        print(f"DEBUG: Finished updating language for {self.__class__.__name__}.")

    def _create_top_controls(self):
        top_controls_layout = QHBoxLayout()
        
        # Class
        class_group = QGroupBox(self.ui_loc['top_controls']['class'])
        class_layout = QVBoxLayout(class_group)
        self.class_combo = QComboBox()
        class_layout.addWidget(self.class_combo)
        top_controls_layout.addWidget(class_group)
        
        # Rarity
        rarity_group = QGroupBox(self.ui_loc['top_controls']['rarity'])
        rarity_layout = QVBoxLayout(rarity_group)
        self.rarity_combo = QComboBox()
        rarity_layout.addWidget(self.rarity_combo)
        top_controls_layout.addWidget(rarity_group)

        # Name
        name_group = QGroupBox(self.ui_loc['top_controls']['name'])
        name_layout = QVBoxLayout(name_group)
        self.name_combo = QComboBox()
        name_layout.addWidget(self.name_combo)
        top_controls_layout.addWidget(name_group)

        # Level
        level_group = QGroupBox(self.ui_loc['top_controls']['level'])
        level_layout = QVBoxLayout(level_group)
        self.level_edit = QLineEdit("50")
        level_layout.addWidget(self.level_edit)
        top_controls_layout.addWidget(level_group)

        # Seed
        seed_group = QGroupBox(self.ui_loc['top_controls']['seed'])
        seed_layout = QHBoxLayout(seed_group)
        self.seed_edit = QLineEdit(str(random.randint(1, 9999)))
        self.random_seed_btn = QPushButton("🎲")
        self.random_seed_btn.setFixedWidth(40)
        seed_layout.addWidget(self.seed_edit)
        seed_layout.addWidget(self.random_seed_btn)
        top_controls_layout.addWidget(seed_group)

        self.container_layout.addLayout(top_controls_layout)

    def _connect_signals(self):
        self.class_combo.currentTextChanged.connect(self.on_class_change)
        self.rarity_combo.currentTextChanged.connect(self.on_rarity_change)
        self.name_combo.currentTextChanged.connect(self.on_name_change)
        self.level_edit.textChanged.connect(self.update_string)
        self.seed_edit.textChanged.connect(self.update_string)
        self.random_seed_btn.clicked.connect(self.generate_random_seed)
        self.skill_search_edit.textChanged.connect(self.populate_skills)
        self.perk_search_edit.textChanged.connect(self.populate_perks)

        # Connect list transfer buttons
        self.leg_move_btn.clicked.connect(lambda: self._move_selected_items(self.leg_avail_list, self.leg_sel_list))
        self.leg_remove_btn.clicked.connect(self.on_legendary_remove)
        self.leg_clear_btn.clicked.connect(self.on_legendary_clear)

        self.perk_move_btn.clicked.connect(self.add_perks)
        self.perk_remove_btn.clicked.connect(lambda: self._remove_selected_items(self.perk_sel_list))
        self.perk_clear_btn.clicked.connect(lambda: self._clear_list(self.perk_sel_list))

    def _create_legendary_group(self):
        leg_group = QGroupBox(self.ui_loc['legendary']['title'])
        layout = QGridLayout(leg_group)
        
        self.leg_avail_list = QListWidget()
        self.leg_sel_list = QListWidget()
        
        layout.addWidget(self.leg_avail_list, 0, 0)
        
        button_layout = QVBoxLayout()
        self.leg_move_btn = QPushButton("»")
        self.leg_remove_btn = QPushButton("«")
        self.leg_clear_btn = QPushButton(self.ui_loc['legendary']['clear'])
        button_layout.addWidget(self.leg_move_btn)
        button_layout.addWidget(self.leg_remove_btn)
        button_layout.addWidget(self.leg_clear_btn)
        button_layout.addStretch()
        layout.addLayout(button_layout, 0, 1)

        layout.addWidget(self.leg_sel_list, 0, 2)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(2, 1)

        self.container_layout.addWidget(leg_group, 1)

    def _create_output_group(self):
        output_group = QGroupBox(self.ui_loc['output']['title'])
        layout = QGridLayout(output_group)

        # Base85
        layout.addWidget(QLabel(self.ui_loc['output']['base85']), 0, 0)
        self.base85_output = QLineEdit()
        self.base85_output.setReadOnly(True)
        layout.addWidget(self.base85_output, 0, 1)
        
        add_to_pack_btn = QPushButton(self.ui_loc['output']['add_to_backpack'])
        add_to_pack_btn.clicked.connect(self._add_to_backpack)
        layout.addWidget(add_to_pack_btn, 0, 2)

        # Full String
        layout.addWidget(QLabel(self.ui_loc['output']['deserialize']), 1, 0)
        self.full_string_output = QLineEdit()
        self.full_string_output.setReadOnly(True)
        layout.addWidget(self.full_string_output, 1, 1)

        self.flag_combo = QComboBox()
        self._populate_flags()
        layout.addWidget(self.flag_combo, 0, 3) # Add to grid
        
        self.container_layout.addWidget(output_group)

    def _populate_flags(self):
        self.flag_combo.clear()
        # Try to load from shared flags location if available, or fallback
        # We loaded 'flags' in weapon_editor_tab, let's check if we can access similar structure
        # In __init__, we loaded self.ui_loc.
        # Let's assume main window passes a common flags dict or we load it from weapon_editor_tab section or define it here.
        # Since we don't have "flags" in class_mod_tab json usually, we can try to load "weapon_editor_tab"->"flags" for consistency
        # or just define localized strings here based on self.current_lang.
        
        flags_map = {
            "1": "1 (Common)" if self.current_lang == 'en-US' else "1 (普通)",
            "3": "3 (Favorites)" if self.current_lang == 'en-US' else "3 (收藏)",
            "5": "5 (Trash)" if self.current_lang == 'en-US' else "5 (垃圾)",
            "17": "17 (Group 1)" if self.current_lang == 'en-US' else "17 (编组1)",
            "33": "33 (Group 2)" if self.current_lang == 'en-US' else "33 (编组2)",
            "65": "65 (Group 3)" if self.current_lang == 'en-US' else "65 (编组3)",
            "129": "129 (Group 4)" if self.current_lang == 'en-US' else "129 (编组4)"
        }
        
        # If we loaded flags_loc (we didn't in this file), we could use it.
        # Let's check if we can load it.
        try:
            loc_file = resource_loader.get_ui_localization_file(self.current_lang)
            full_loc = resource_loader.load_json_resource(loc_file) or {}
            flags_loc = full_loc.get("weapon_editor_tab", {}).get("flags", {})
            if flags_loc:
                flags_map = {k: flags_loc.get(k, v) for k, v in flags_map.items()}
        except:
            pass

        flag_values = [flags_map["1"], flags_map["3"], flags_map["5"], flags_map["17"], flags_map["33"], flags_map["65"], flags_map["129"]]
        self.flag_combo.addItems(flag_values)
        # Set default to Favorites
        for i in range(self.flag_combo.count()):
            if flags_map["3"] == self.flag_combo.itemText(i):
                self.flag_combo.setCurrentIndex(i)
                break

    def _create_skills_and_perks_group(self):
        # Skills
        skills_group = QGroupBox(self.ui_loc['skills']['title'])
        skills_layout = QVBoxLayout(skills_group)
        
        self.skill_search_edit = QLineEdit()
        self.skill_search_edit.setPlaceholderText(self.ui_loc['skills']['search_placeholder'])
        skills_layout.addWidget(self.skill_search_edit)

        self.skill_tree = QTreeWidget()
        self.skill_tree.setHeaderLabels([self.ui_loc['skills']['header_icon'], self.ui_loc['skills']['header_skill'], 
                                         self.ui_loc['skills']['header_codes'], self.ui_loc['skills']['header_points']])
        self.skill_tree.setIconSize(QSize(48, 48))
        self.skill_tree.setColumnWidth(0, 100)
        self.skill_tree.setColumnWidth(1, 200)
        self.skill_tree.setColumnWidth(2, 300)
        self.skill_tree.setMinimumHeight(400)
        skills_layout.addWidget(self.skill_tree)
        
        self.container_layout.addWidget(skills_group, 3)

        # Perks
        perks_group = QGroupBox(self.ui_loc['perks']['title'])
        perks_group.setMinimumHeight(250)
        perks_layout = QGridLayout(perks_group)
        self.perk_search_edit = QLineEdit()
        self.perk_search_edit.setPlaceholderText(self.ui_loc['perks']['search_placeholder'])
        perks_layout.addWidget(self.perk_search_edit, 0, 0, 1, 3)

        self.perk_avail_list = QListWidget()
        self.perk_sel_list = QListWidget()
        self.perk_avail_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.perk_sel_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        perks_layout.addWidget(self.perk_avail_list, 1, 0)
        
        button_layout = QVBoxLayout()
        self.perk_multiplier = QSpinBox()
        self.perk_multiplier.setRange(1, 999)
        self.perk_multiplier.setValue(1)
        self.perk_move_btn = QPushButton("»")
        self.perk_remove_btn = QPushButton("«")
        self.perk_clear_btn = QPushButton(self.ui_loc['perks']['clear'])
        
        button_layout.addWidget(self.perk_multiplier)
        button_layout.addWidget(self.perk_move_btn)
        button_layout.addWidget(self.perk_remove_btn)
        button_layout.addWidget(self.perk_clear_btn)
        button_layout.addStretch()
        perks_layout.addLayout(button_layout, 1, 1)

        perks_layout.addWidget(self.perk_sel_list, 1, 2)
        perks_layout.setColumnStretch(0, 1)
        perks_layout.setColumnStretch(2, 1)
        
        self.container_layout.addWidget(perks_group)

    def populate_initial_data(self):
        """填充初始数据 - 使用CSV数据源"""
        if not self.names_data:
            return
        
        # 职业名称 - 使用固定顺序
        class_names = [self._(c) for c in self.CLASS_NAMES]
        self.class_combo.addItems(class_names)
        
        # 稀有度
        rarities = [self._(r) for r in ["Common", "Uncommon", "Rare", "Epic", "Legendary"]]
        self.rarity_combo.addItems(rarities)
        self.rarity_combo.setCurrentText(self._("Legendary"))
        
        self.populate_perks()
        self.on_class_change()

    def on_class_change(self):
        self.current_skill_points.clear()
        self.populate_names()
        self.populate_legendary_extras()
        self.populate_skills()
        self.update_string()

    def on_rarity_change(self):
        self.populate_names()
        self.populate_legendary_extras()
        self.update_string()

    def on_name_change(self):
        self.populate_legendary_extras(preserve_selection=True)
        self.update_string()

    def on_legendary_remove(self):
        self._remove_selected_items(self.leg_sel_list)
        self.populate_legendary_extras(preserve_selection=True)

    def on_legendary_clear(self):
        self._clear_list(self.leg_sel_list)
        self.populate_legendary_extras(preserve_selection=True)

    def generate_random_seed(self):
        self.seed_edit.setText(str(random.randint(1, 9999)))

    def populate_names(self):
        """填充名称列表 - 使用CSV数据源"""
        self.name_combo.blockSignals(True)
        self.name_combo.clear()
        
        # 获取当前职业的英文名和ID
        current_class_en = self._get_current_class_en()
        current_class_id = str(self.CLASS_IDS.get(current_class_en, 0))

        # 获取稀有度英文名
        rarity_en = self._get_english_key(self.rarity_combo.currentText())
        rarity_key = "legendary" if rarity_en == "Legendary" else "normal"
        
        # 从索引中获取名称列表
        names_list = self.names_by_class_rarity.get((current_class_id, rarity_key), [])
        
        self.name_code_map = {}  # display_name -> name_code (int)
        self.name_en_map = {}    # display_name -> name_EN
        self.name_data_map = {}  # display_name -> full row data
        
        for name_row in names_list:
            name_en = name_row.get('name_EN', '')
            name_zh = name_row.get('name_ZH', '')
            name_code = name_row.get('name_code', '')
            
            # 根据语言选择显示名称
            if self.current_lang == 'zh-CN' and name_zh:
                display_name = name_zh
            else:
                display_name = name_en
            
            self.name_combo.addItem(display_name)
            self.name_code_map[display_name] = int(name_code) if name_code else 0
            self.name_en_map[display_name] = name_en
            self.name_data_map[display_name] = name_row
            
        self.name_combo.blockSignals(False)
        self.update_string()

    def on_skill_point_change(self, skill_name, points):
        self.current_skill_points[skill_name] = points
        self.update_string()

    def update_string(self, *args):
        """生成序列化字符串 - 使用CSV数据源"""
        if not self.names_data or not self.name_combo.currentText():
            self.full_string_output.setText("...")
            self.base85_output.setText("...")
            return

        try:
            current_class_en = self._get_current_class_en()
            current_class_id = str(self.CLASS_IDS.get(current_class_en, 0))
            
            level_val = self.level_edit.text() if hasattr(self, 'level_edit') else "50"
            if not level_val: level_val = "50"
            header = f"{self.CLASS_IDS[current_class_en]}, 0, 1, {level_val}| 2, {self.seed_edit.text()}||"
            
            rarity_en = self._get_english_key(self.rarity_combo.currentText())
            name_code = self.name_code_map.get(self.name_combo.currentText(), 0)
            name_chunk = f"{{{name_code}}}" if name_code else ""

            rarity_code_val = ""
            if rarity_en == "Legendary":
                # 从legendary_map_data查找
                for row in self.legendary_map_data:
                    if row.get('class_ID') == current_class_id and row.get('L_name_ID') == str(name_code):
                        rarity_code_val = row.get('item_card_ID', '')
                        break
                if current_class_en == "Harlowe": 
                    name_chunk += " {27}"
            else:
                PER_CLASS_RARITIES = {
                    "Vex": {"Common": 217, "Uncommon": 218, "Rare": 219, "Epic": 220},
                    "Rafa": {"Common": 66, "Uncommon": 67, "Rare": 68, "Epic": 69},
                    "Harlowe": {"Common": 224, "Uncommon": 223, "Rare": 222, "Epic": 221},
                    "Amon": {"Common": 70, "Uncommon": 69, "Rare": 68, "Epic": 67}
                }
                rarity_code_val = PER_CLASS_RARITIES.get(current_class_en, {}).get(rarity_en, "")
            rarity_chunk = f"{{{rarity_code_val}}}" if rarity_code_val else ""

            # 传奇附加
            leg_extras_codes = [f"{{{self.leg_sel_list.item(i).text().split('{')[-1].strip()}" for i in range(self.leg_sel_list.count())]
            leg_extras_chunk = " ".join(leg_extras_codes)

            # 技能 - 使用skills_by_class索引
            skill_chunks = []
            skills_list = self.skills_by_class.get(current_class_id, [])
            for skill_row in sorted(skills_list, key=lambda x: x.get('skill_name_EN', '')):
                eng_name = skill_row.get('skill_name_EN', '')
                points = self.current_skill_points.get(eng_name, 0)
                if points > 0:
                    # 获取技能ID列表
                    codes = []
                    for i in range(1, 6):
                        code = skill_row.get(f'skill_ID_{i}', '')
                        if code:
                            codes.append(code)
                    skill_chunks.extend([f"{{{c}}}" for c in codes[:points]])
            skills_chunk = " ".join(skill_chunks)
            
            # Perks - 直接从显示格式[ID]提取perk_id
            perk_codes = []
            for i in range(self.perk_sel_list.count()):
                item_text = self.perk_sel_list.item(i).text()
                # Check for (count) prefix: "(count) [id] name"
                match = re.match(r"\((\d+)\)\s+\[(\d+)\]", item_text)
                if match:
                    count = int(match.group(1))
                    perk_id = match.group(2)
                else:
                    # Try without count prefix: "[id] name"
                    match_no_count = re.match(r"\[(\d+)\]", item_text)
                    if match_no_count:
                        count = 1
                        perk_id = match_no_count.group(1)
                    else:
                        continue
                
                if perk_id:
                    for _ in range(count):
                        perk_codes.append(str(perk_id))

            perks_chunk = f" {{234:[{ ' '.join(perk_codes) }]}}" if perk_codes else ""

            parts = [header, rarity_chunk, name_chunk, leg_extras_chunk, skills_chunk, perks_chunk]
            full_string = " ".join(p for p in parts if p).replace("  ", " ").strip() + "|"
            
            self.full_string_output.setText(full_string)

            encoded_serial, error = b_encoder.encode_to_base85(full_string)
            if error:
                self.base85_output.setText(self.ui_loc['dialogs']['coding_error'].format(error=error))
            else:
                self.base85_output.setText(encoded_serial)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.full_string_output.setText(self.ui_loc['dialogs']['gen_error'].format(error=e))
            self.base85_output.setText("...")

    def populate_legendary_extras(self, preserve_selection=False):
        """填充传奇附加列表 - 使用CSV数据源"""
        saved_selections = []
        if preserve_selection:
            for i in range(self.leg_sel_list.count()):
                saved_selections.append(self.leg_sel_list.item(i).text())

        self.leg_avail_list.clear()
        self.leg_sel_list.clear()
        
        is_legendary = self.rarity_combo.currentText() == self._("Legendary")
        self.leg_avail_list.setEnabled(is_legendary)
        self.leg_sel_list.setEnabled(is_legendary)

        if not is_legendary: return

        current_class_en = self._get_current_class_en()
        current_class_id = str(self.CLASS_IDS.get(current_class_en, 0))
        if not current_class_en: return

        # 从CSV获取legendary名称
        legendary_names = self.names_by_class_rarity.get((current_class_id, 'legendary'), [])
        primary_name_display = self.name_combo.currentText()

        # Helper to extract name from "Name {Code}"
        def get_name_from_item_str(item_text):
             return item_text.rpartition(' {')[0]

        preserved_set = set()

        if preserve_selection:
            for item_text in saved_selections:
                name_part = get_name_from_item_str(item_text)
                if name_part != primary_name_display:
                    self.leg_sel_list.addItem(item_text)
                    preserved_set.add(item_text)

        for name_row in legendary_names:
            name_en = name_row.get('name_EN', '')
            name_zh = name_row.get('name_ZH', '')
            name_code = name_row.get('name_code', '')
            
            # 选择显示名称
            if self.current_lang == 'zh-CN' and name_zh:
                display_name = name_zh
            else:
                display_name = name_en
            
            item_str = f"{display_name} {{{name_code}}}"
            
            if display_name == primary_name_display:
                continue
            
            if item_str not in preserved_set:
                self.leg_avail_list.addItem(item_str)

    def populate_perks(self):
        """填充Perk列表 - 使用CSV数据源"""
        self.perk_avail_list.clear()
        query = self.perk_search_edit.text().lower()
        
        for perk_row in self.perks_data:
            perk_id = perk_row.get('perk_ID', '')
            perk_en = perk_row.get('perk_name_EN', '')
            perk_zh = perk_row.get('perk_name_ZH', '')
            
            # 选择显示名称，格式: [ID] 名称
            if self.current_lang == 'zh-CN' and perk_zh:
                display_name = f"[{perk_id}] {perk_zh}"
            else:
                display_name = f"[{perk_id}] {perk_en}"
            
            if not query or query in display_name.lower() or query in perk_en.lower():
                self.perk_avail_list.addItem(display_name)

    def add_perks(self):
        multiplier = self.perk_multiplier.value()
        for item in self.perk_avail_list.selectedItems():
            perk_name = item.text()  # 格式: [ID] 名称
            
            # 提取perk标识符 [ID]
            perk_id_match = re.match(r"\[(\d+)\]", perk_name)
            if not perk_id_match:
                continue
            perk_id = perk_id_match.group(1)
            
            # Check if already exists in selection list to update count
            existing_item = None
            for i in range(self.perk_sel_list.count()):
                sel_item = self.perk_sel_list.item(i)
                sel_text = sel_item.text()
                
                # Check for (count) prefix: "(count) [id] name"
                match = re.match(r"\((\d+)\)\s+\[(\d+)\]", sel_text)
                if match:
                    current_count = int(match.group(1))
                    current_id = match.group(2)
                else:
                    # "[id] name" without count
                    match_no_count = re.match(r"\[(\d+)\]", sel_text)
                    if match_no_count:
                        current_count = 1
                        current_id = match_no_count.group(1)
                    else:
                        continue
                
                if current_id == perk_id:
                    existing_item = sel_item
                    break
            
            if existing_item:
                # Update count
                new_count = current_count + multiplier
                existing_item.setText(f"({new_count}) {perk_name}")
            else:
                # Add new item
                self.perk_sel_list.addItem(f"({multiplier}) {perk_name}")
        
        self.update_string()

    def _move_selected_items(self, source_list, dest_list, allow_duplicates=False):
        for item in source_list.selectedItems():
            if allow_duplicates or not dest_list.findItems(item.text(), Qt.MatchFlag.MatchExactly):
                dest_list.addItem(item.text())
            if not allow_duplicates:
                source_list.takeItem(source_list.row(item))
        self.update_string()

    def _remove_selected_items(self, list_widget):
        for item in list_widget.selectedItems():
            list_widget.takeItem(list_widget.row(item))
        self.update_string()

    def _clear_list(self, list_widget):
        list_widget.clear()
        self.update_string()

    def _get_current_class_en(self):
        current_class_display = self.class_combo.currentText()
        for key, value in self.localization.items():
            if value == current_class_display:
                return key
        return current_class_display # Fallback

    def _get_english_key(self, localized_value):
        for key, value in self.localization.items():
            if value == localized_value: return key
        return localized_value

    def _add_to_backpack(self):
        serial = self.base85_output.text()
        if not serial or "Error" in serial or "错误" in serial:
            QMessageBox.warning(self, self.ui_loc['dialogs']['no_data'], self.ui_loc['dialogs']['no_valid_base85'])
            return
        
        flag = self.flag_combo.currentText().split(" ")[0]
        self.add_to_backpack_requested.emit(serial, flag)

    def get_skill_icon(self, skill_name, class_name):
        # Preserve accented Latin characters (Spanish) for proper icon matching
        safe_name = re.sub(r"[^a-zA-Z0-9_!áéíóúñÁÉÍÓÚÑ]", "", skill_name.replace("'", "").replace("'", "").replace(" ", "_")).lower()
        suffix_map = {"Vex": "_1", "Rafa": "_2", "Harlowe": "_3", "Amon": "_4"}
        suffix = suffix_map.get(class_name, "")
        filename = f"{safe_name}{suffix}.png"
        
        if filename in self.image_cache:
            return self.image_cache[filename]

        try:
            path = resource_loader.get_class_mods_image_path(class_name, filename)
            if path and Path(path).exists():
                icon = QIcon(str(path))
                self.image_cache[filename] = icon
                return icon
        except Exception as e:
            print(f"Could not load icon {filename}: {e}")
        return QIcon() # Return empty icon on failure

    def populate_skills(self):
        """填充技能列表 - 使用CSV数据源"""
        self.skill_tree.clear()
        self.skill_widgets = {}
        current_class_en = self._get_current_class_en()
        current_class_id = str(self.CLASS_IDS.get(current_class_en, 0))
        if not current_class_en: return

        query = self.skill_search_edit.text().lower()
        skills_list = self.skills_by_class.get(current_class_id, [])

        for skill_row in sorted(skills_list, key=lambda x: x.get('skill_name_EN', '')):
            skill_en = skill_row.get('skill_name_EN', '')
            skill_zh = skill_row.get('skill_name_ZH', '')
            
            # 选择显示名称
            if self.current_lang == 'zh-CN' and skill_zh:
                display_name = skill_zh
            else:
                display_name = skill_en
            
            if query and query not in skill_en.lower() and query not in display_name.lower():
                continue

            icon = self.get_skill_icon(skill_en, current_class_en)
            item = QTreeWidgetItem(self.skill_tree)

            # 获取技能ID列表
            codes = []
            for i in range(1, 6):
                code = skill_row.get(f'skill_ID_{i}', '')
                if code:
                    codes.append(int(code))

            # Set styled tooltip using pre-loaded descriptions
            description_info = self.skill_descriptions.get(skill_en)
            if not description_info:
                description_info = self.skill_descriptions.get(skill_en.lower())

            if description_info:
                skill_type = self._(description_info.get('type', 'N/A'))
                # 中文界面使用中文描述，从skill_zh获取（如果没有则回退到en）
                if self.current_lang == 'zh-CN':
                    desc_text = description_info.get('zh', description_info.get('en', 'No description found.'))
                else:
                    desc_text = description_info.get('en', 'No description found.')
                
                tooltip_html = f"""
                    <div style='width: 300px;'>
                        <p><b>{display_name}</b></p>
                        <p><i>{self.ui_loc['tooltips']['type']}: {skill_type}</i></p>
                        <hr>
                        <p>{desc_text}</p>
                    </div>
                """
                item.setToolTip(1, tooltip_html)

            item.setIcon(0, icon)
            item.setText(1, display_name)
            item.setText(2, f"{{{', '.join(map(str, codes[:5]))}}}")
            item.setData(1, Qt.ItemDataRole.UserRole, {"eng_name": skill_en, "codes": codes[:5]})
            
            max_points = len(codes[:5])
            current_points = self.current_skill_points.get(skill_en, 0)
            sp_widget = SkillPointWidget(current_points, max_points, loc_data=self.ui_loc['skill_point_widget'])
            sp_widget.valueChanged.connect(lambda val, name=skill_en: self.on_skill_point_change(name, val))
            
            self.skill_tree.setItemWidget(item, 3, sp_widget)
            self.skill_widgets[skill_en] = item
