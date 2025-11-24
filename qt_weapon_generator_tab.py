import random
import pandas as pd
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QComboBox, QPushButton, QMessageBox, QScrollArea, QFrame, QGroupBox
)
from PyQt6.QtCore import pyqtSignal, Qt

import resource_loader
import b_encoder

class QtWeaponGeneratorTab(QWidget):
    # 自定义信号，当用户点击“添加到背包”时发射
    # 参数： serial (str), flag (str)
    add_to_backpack_requested = pyqtSignal(str, str)

    _NONE_VALUE = "None"
    
    PART_LAYOUT = {
        "Rarity": (0, 0), "Legendary Type": (0, 1),
        "Element 1": (1, 0), "Element 2": (1, 1),
        "Body": (2, 0), "Body Accessory": (2, 1),
        "Barrel": (2, 2), "Barrel Accessory": (2, 3),
        "Magazine": (3, 0), "Stat Modifier": (3, 1),
        "Grip": (3, 2), "Foregrip": (3, 3),
        "Manufacturer Part": (4, 0), "Scope": (4, 1),
        "Scope Accessory": (4, 2), "Underbarrel": (4, 3),
        "Underbarrel Accessory": (5, 3)
    }
    MULTI_SELECT_SLOTS = {
        "Body Accessory": 4, "Barrel Accessory": 4, 
        "Manufacturer Part": 4, "Scope Accessory": 4,
        "Underbarrel Accessory": 3
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.all_weapon_parts_df = None
        self.elemental_df = None
        self.weapon_rarity_df = None
        self.weapon_localization = None
        self.part_combos = {}
        self.legendary_frame = None # Initialize to None
        self.current_lang = 'zh-CN'
        
        # Main layout holds the content widget
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.content_widget = None

        self.load_data(self.current_lang)
        self.create_widgets()

    def load_data(self, lang='zh-CN'):
        try:
            suffix = "_EN" if lang == 'en-US' else ""
            
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
                raise FileNotFoundError("One or more weapon CSV file paths not found.")

            self.all_weapon_parts_df = pd.read_csv(paths["all_parts"])
            self.all_weapon_parts_df['Part ID'] = self.all_weapon_parts_df['Part ID'].astype('Int64').astype(str).replace('<NA>', '')
            self.elemental_df = pd.read_csv(paths["elemental"])
            self.weapon_rarity_df = pd.read_csv(paths["rarity"])
            
            self.weapon_localization = {}
            if lang == 'zh-CN':
                self.weapon_localization = resource_loader.load_weapon_json('weapon_localization_zh-CN.json') or {}
            
            loc_file = "ui_localization.json" if lang == 'zh-CN' else "ui_localization_EN.json"
            full_loc = resource_loader.load_json_resource(loc_file) or {}
            self.ui_loc = full_loc.get("weapon_gen_tab", {})
            self.flags_loc = full_loc.get("weapon_editor_tab", {}).get("flags", {})

        except Exception as e:
            self._handle_error(f"Error loading data: {e}")

    def update_language(self, lang):
        print(f"DEBUG: Updating language for {self.__class__.__name__} to {lang}...")
        self.current_lang = lang
        self.load_data(lang)
        
        # Save state
        current_mfg_idx = self.manufacturer_combo.currentIndex() if hasattr(self, 'manufacturer_combo') else 0
        current_wt_idx = self.weapon_type_combo.currentIndex() if hasattr(self, 'weapon_type_combo') else 0
        current_level = self.level_var.text() if hasattr(self, 'level_var') else "50"
        current_seed = self.seed_var.text() if hasattr(self, 'seed_var') else ""
        
        # Clean up internal references
        self.part_combos = {}
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

    def _handle_error(self, message):
        err_title = self.ui_loc.get('dialogs', {}).get('error_title', "错误") if self.ui_loc else "错误"
        error_label = QLabel(f"{err_title}: {message}")
        error_label.setStyleSheet("color: red;")
        error_label.setWordWrap(True)
        
        # 清空现有布局并显示错误
        for i in reversed(range(self.layout().count())): 
            self.layout().itemAt(i).widget().setParent(None)
        self.layout().addWidget(error_label)


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
        self.main_layout.addWidget(self.content_widget)

        # --- 输出框 ---
        output_frame = QFrame(self.content_widget); output_frame.setLayout(QGridLayout())
        self.serial_decoded_entry = QLineEdit(); self.serial_decoded_entry.setReadOnly(True)
        self.serial_b85_entry = QLineEdit(); self.serial_b85_entry.setReadOnly(True)
        output_frame.layout().addWidget(QLabel(self.get_localized_string("serial_decoded")), 0, 0)
        output_frame.layout().addWidget(self.serial_decoded_entry, 0, 1)
        output_frame.layout().addWidget(QLabel(self.get_localized_string("serial_b85")), 1, 0)
        output_frame.layout().addWidget(self.serial_b85_entry, 1, 1)
        main_layout.addWidget(output_frame)
        
        # --- 控制区 ---
        controls_frame = QFrame(self); controls_frame.setLayout(QHBoxLayout())
        self.manufacturer_combo = QComboBox()
        self.weapon_type_combo = QComboBox()
        controls_frame.layout().addWidget(QLabel(self.get_localized_string("manufacturer")))
        controls_frame.layout().addWidget(self.manufacturer_combo)
        controls_frame.layout().addWidget(QLabel(self.get_localized_string("weapon_type")))
        controls_frame.layout().addWidget(self.weapon_type_combo)

        self.level_var = QLineEdit("50")
        self.seed_var = QLineEdit(str(random.randint(100, 9999)))
        random_seed_btn = QPushButton("🎲"); random_seed_btn.setFixedWidth(30)
        controls_frame.layout().addWidget(QLabel(self.get_localized_string("level")))
        controls_frame.layout().addWidget(self.level_var)
        controls_frame.layout().addWidget(QLabel(self.get_localized_string("seed")))
        controls_frame.layout().addWidget(self.seed_var)
        controls_frame.layout().addWidget(random_seed_btn)
        main_layout.addWidget(controls_frame)

        # --- 部件选择 ---
        self.parts_scroll_area = QScrollArea()
        self.parts_scroll_area.setWidgetResizable(True)
        self.parts_frame = QWidget()
        self.parts_layout = QGridLayout(self.parts_frame)
        self.parts_scroll_area.setWidget(self.parts_frame)
        main_layout.addWidget(self.parts_scroll_area)

        # --- 底部操作区 ---
        action_frame = QFrame(self); action_frame.setLayout(QHBoxLayout())
        self.flag_combo = QComboBox()
        if self.flags_loc:
            flag_values = [self.flags_loc.get(k, f"{k} (Unknown)") for k in ["1", "3", "5", "17", "33", "65", "129"]]
            self.flag_combo.addItems(flag_values)
            default_flag = self.flags_loc.get("3", "3 (收藏)")
            self.flag_combo.setCurrentText(default_flag)
        else:
            flag_values = ["1 (普通)", "3 (收藏)", "5 (垃圾)", "17 (编组1)", "33 (编组2)", "65 (编组3)", "129 (编组4)"]
            self.flag_combo.addItems(flag_values)
            self.flag_combo.setCurrentText("3 (收藏)")
            
        add_to_backpack_btn = QPushButton(self.get_localized_string("add_to_backpack"))
        action_frame.layout().addWidget(QLabel(self.get_localized_string("select_flag")))
        action_frame.layout().addWidget(self.flag_combo)
        action_frame.layout().addStretch()
        action_frame.layout().addWidget(add_to_backpack_btn)
        main_layout.addWidget(action_frame)

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
        wt_list = sorted([self.get_localized_string(wt) for wt in self.all_weapon_parts_df['Weapon Type'].unique()])
        self.weapon_type_combo.addItems(wt_list)

    def on_main_selection_change(self, _=None):
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

    def _create_part_dropdowns(self):
        # 清理旧的 widgets
        while self.parts_layout.count():
            child = self.parts_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.part_combos = {}
        # IMPORTANT: Clear reference to the deleted widget to prevent crash if signal handlers traverse it
        self.legendary_frame = None
        
        selected_mfg_en = self._get_english_key(self.manufacturer_combo.currentText())
        selected_wt_en = self._get_english_key(self.weapon_type_combo.currentText())

        m_id = self._get_m_id(selected_mfg_en, selected_wt_en)
        if m_id is None: return

        self._create_special_dropdown("Rarity", m_id, self.PART_LAYOUT["Rarity"])
        self._create_special_dropdown("Legendary Type", m_id, self.PART_LAYOUT["Legendary Type"])
        
        # 元素是单选，不是下拉框
        for i, name in enumerate(["Element 1", "Element 2"]):
            self._create_element_selector(name, m_id, self.PART_LAYOUT[name])

        filtered_df = self.all_weapon_parts_df[self.all_weapon_parts_df['Manufacturer & Weapon Type ID'] == m_id]
        for part_type_en, group_df in filtered_df.groupby('Part Type'):
            if part_type_en not in self.PART_LAYOUT: continue
            
            row, col = self.PART_LAYOUT[part_type_en]
            
            group_box = QGroupBox(self.get_localized_string(part_type_en))
            group_layout = QVBoxLayout(group_box)
            
            values = [self.get_localized_string(self._NONE_VALUE)] + \
                     [f"{pid} - {stat}" if pd.notna(stat) else str(pid)
                      for pid, stat in zip(group_df['Part ID'], group_df['Stat']) if pid]

            num_slots = self.MULTI_SELECT_SLOTS.get(part_type_en, 1)
            for i in range(num_slots):
                if num_slots > 1:
                    # For multi-select, we can use a smaller label
                    pass
                combo = QComboBox()
                combo.addItems(values)
                # Add to dict BEFORE connecting signals
                self.part_combos[f"{part_type_en}_{i}"] = combo
                combo.currentTextChanged.connect(self.generate_weapon)
                
                group_layout.addWidget(combo)
            
            self.parts_layout.addWidget(group_box, row, col, Qt.AlignmentFlag.AlignTop)
        
        self.generate_weapon()

    def _create_special_dropdown(self, name, m_id, position):
        row, col = position
        
        group_box = QGroupBox(self.get_localized_string(name.replace(" ", "")))
        group_layout = QVBoxLayout(group_box)
        
        if name == "Legendary Type": self.legendary_frame = group_box

        combo = QComboBox()
        
        values = [self.get_localized_string(self._NONE_VALUE)]
        if name == "Rarity":
            df = self.weapon_rarity_df[self.weapon_rarity_df['Manufacturer & Weapon Type ID'] == m_id]
            values.extend(sorted([self.get_localized_string(r) for r in df['Stat'].unique()]))
        elif name == "Legendary Type":
            leg_df = self.weapon_rarity_df[(self.weapon_rarity_df['Manufacturer & Weapon Type ID'] == m_id) & (self.weapon_rarity_df['Stat'] == 'Legendary')]
            values.extend([f"{r['Part ID']} - {self.get_localized_string(r['Description'], r['Description'])}" for _, r in leg_df.iterrows() if pd.notna(r['Description'])])
        
        # Add to dict BEFORE connecting signals
        self.part_combos[name] = combo
        
        combo.addItems(values)
        
        # Connect signals AFTER adding items to avoid triggering on startup with incomplete state or recursive calls
        if name == "Rarity":
             combo.currentTextChanged.connect(self._on_rarity_change)
        elif name == "Legendary Type":
             # usually Legendaries selection also triggers regen
             combo.currentTextChanged.connect(self.generate_weapon)
        
        group_layout.addWidget(combo)
        self.parts_layout.addWidget(group_box, row, col, Qt.AlignmentFlag.AlignTop)
        
        if name == "Legendary Type": group_box.hide()

    def _create_element_selector(self, name, m_id, position):
        row, col = position
        group_box = QGroupBox(self.get_localized_string(name.replace(" ", "")))
        group_layout = QVBoxLayout(group_box)

        combo = QComboBox()
        none_val = self.get_localized_string(self._NONE_VALUE)
        values = [none_val] + [f"{r['Part_ID']} - {self.get_localized_string(r['Stat'])}" for _, r in self.elemental_df.iterrows()]
        combo.addItems(values)
        
        self.part_combos[name] = combo
        combo.currentTextChanged.connect(self.generate_weapon)

        group_layout.addWidget(combo)
        self.parts_layout.addWidget(group_box, row, col, Qt.AlignmentFlag.AlignTop)

    def _on_rarity_change(self, choice):
        is_legendary = self._get_english_key(choice) == "Legendary"
        # Check if legendary_frame exists AND is still a valid object (not None)
        if hasattr(self, 'legendary_frame') and self.legendary_frame:
            self.legendary_frame.setVisible(is_legendary)
        
        if not is_legendary and "Legendary Type" in self.part_combos:
            # Safely reset Legendary selection
            self.part_combos["Legendary Type"].blockSignals(True)
            self.part_combos["Legendary Type"].setCurrentText(self.get_localized_string(self._NONE_VALUE))
            self.part_combos["Legendary Type"].blockSignals(False)
            
        self.generate_weapon()

    def _get_english_key(self, localized_value):
        if not localized_value or not self.weapon_localization: return localized_value
        reverse_map = {v: k for k, v in self.weapon_localization.items()}
        return reverse_map.get(localized_value, localized_value)

    def randomize_seed(self):
        self.seed_var.setText(str(random.randint(100, 9999)))

    def generate_weapon(self, *args):
        try:
            mfg_en = self._get_english_key(self.manufacturer_combo.currentText())
            wt_en = self._get_english_key(self.weapon_type_combo.currentText())
            m_id = self._get_m_id(mfg_en, wt_en)
            if m_id is None: return

            level = self.level_var.text() if self.level_var.text().isdigit() else "50"
            seed = self.seed_var.text() if self.seed_var.text().isdigit() else str(random.randint(100, 9999))
            
            header = f"{m_id}, 0, 1, {level}| 2, {seed}||"
            parts_list = []
            
            localized_none = self.get_localized_string(self._NONE_VALUE)
            
            # Rarity / Legendary
            rarity_combo = self.part_combos.get("Rarity")
            is_legendary = self._get_english_key(rarity_combo.currentText()) == "Legendary" if rarity_combo else False

            if is_legendary:
                legendary_combo = self.part_combos.get("Legendary Type")
                if legendary_combo and legendary_combo.currentText() != localized_none:
                    part_id = legendary_combo.currentText().split(' - ')[0]
                    if part_id.isdigit(): parts_list.append(f"{{{part_id}}}")
            elif rarity_combo and rarity_combo.currentText() != localized_none:
                 selected_rarity_en = self._get_english_key(rarity_combo.currentText())
                 rarity_id_row = self.weapon_rarity_df[(self.weapon_rarity_df['Manufacturer & Weapon Type ID'] == m_id) & (self.weapon_rarity_df['Stat'] == selected_rarity_en) & (self.weapon_rarity_df['Description'].isna())]
                 if not rarity_id_row.empty: parts_list.append(f"{{{rarity_id_row.iloc[0]['Part ID']}}}")
            
            # Elements
            for i in range(1, 3):
                element_combo = self.part_combos.get(f"Element {i}")
                if element_combo and element_combo.currentText() != localized_none:
                    part_id = element_combo.currentText().split(' - ')[0]
                    if part_id.isdigit(): parts_list.append(f"{{1:{part_id}}}")
            
            # Other parts
            special_parts = {"Rarity", "Legendary Type", "Element 1", "Element 2"}
            for key, combo in self.part_combos.items():
                part_type_base = key.split('_')[0]
                if part_type_base in special_parts or key in special_parts: continue

                value = combo.currentText()
                if value != localized_none:
                    part_id = value.split(' - ')[0]
                    if part_id.isdigit(): parts_list.append(f"{{{part_id}}}")
            
            component_str = " ".join(parts_list)
            full_decoded_str = f"{header} {component_str} |"
            encoded_serial, err = b_encoder.encode_to_base85(full_decoded_str)
            if err: raise ValueError(f"编码失败: {err}")
            
            self.serial_decoded_entry.setText(full_decoded_str)
            self.serial_b85_entry.setText(encoded_serial)
        except Exception as e:
            # Maybe log this to a status bar in the future
            print(f"Weapon generation error: {e}")

    def _on_add_to_backpack(self):
        serial = self.serial_b85_entry.text()
        if not serial:
            QMessageBox.warning(self, self.ui_loc.get('dialogs', {}).get('no_serial_title', "无序列号"), 
                                self.ui_loc.get('dialogs', {}).get('gen_first', "请先生成一个武器。"))
            return
        
        flag = self.flag_combo.currentText().split(" ")[0]
        # 发射信号，让主窗口去处理
        self.add_to_backpack_requested.emit(serial, flag)
