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

import b_encoder
import resource_loader

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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_lang = 'zh-CN'
        
        self.ui_loc = self._load_ui_localization()
        self.data = self._load_class_data()
        self.localization = self._load_localization()
        self.skill_descriptions = skill_descriptions
        self.image_cache = {}
        self.current_skill_points = {}

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
        
    def _(self, text):
        # Fallback for keys that might not be in the loaded localization file
        default_map = {"Vex": "Vex", "Rafa": "Rafa", "Harlowe": "Harlowe", "Amon": "Amon"}
        return self.localization.get(text, default_map.get(text, text))

    def _load_class_data(self):
        try:
            return resource_loader.load_class_mods_json("class_code.json", use_literal_eval=True)
        except Exception as e:
            QMessageBox.critical(self, self.ui_loc['dialogs']['error'], self.ui_loc['dialogs']['load_error_code'].format(error=e))
            return {}

    def _load_localization(self, lang=None):
        if lang is None: lang = self.current_lang
        # If English, we assume keys are English and don't need translation mapping (return empty dict)
        # unless there's a specific EN file. For now assuming keys are EN.
        if lang in ['en-US', 'ru', 'ua']:
            return {}
        try:
            return resource_loader.load_class_mods_json("class_localization.json")
        except Exception as e:
             QMessageBox.warning(self, self.ui_loc['dialogs']['warning'], self.ui_loc['dialogs']['load_error_loc'].format(error=e))
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
        if not self.data:
            return
            
        class_names = [self._(c) for c in self.data.get('classes', {}).keys()]
        self.class_combo.addItems(class_names)
        
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
        self.name_combo.blockSignals(True)
        self.name_combo.clear()
        
        # Get English key for class
        current_class_display = self.class_combo.currentText()
        current_class_en = ""
        for key, value in self.localization.items():
            if value == current_class_display:
                current_class_en = key
                break
        if not current_class_en: current_class_en = current_class_display # Fallback

        # Get English key for rarity
        rarity_display = self.rarity_combo.currentText()
        rarity_en = ""
        for key, value in self.localization.items():
            if value == rarity_display:
                rarity_en = key
                break
        if not rarity_en: rarity_en = rarity_display # Fallback
        
        name_key = "legendary" if rarity_en == "Legendary" else "normal"
        
        names_data = self.data.get("classes", {}).get(current_class_en, {}).get("names", {}).get(name_key, [])
        
        self.name_code_map = {}
        for name_data in names_data:
            eng_name = name_data['name']
            localized_name = self._(eng_name)
            self.name_combo.addItem(localized_name)
            self.name_code_map[localized_name] = name_data['code']
            
        self.name_combo.blockSignals(False)
        self.update_string()

    def on_skill_point_change(self, skill_name, points):
        self.current_skill_points[skill_name] = points
        self.update_string()

    def update_string(self, *args):
        if not self.data or not self.name_combo.currentText():
            self.full_string_output.setText("...")
            self.base85_output.setText("...")
            return

        try:
            current_class_en = self._get_current_class_en()
            level_val = self.level_edit.text() if hasattr(self, 'level_edit') else "50"
            if not level_val: level_val = "50"
            header = f"{self.data['ids'][current_class_en]}, 0, 1, {level_val}| 2, {self.seed_edit.text()}||"
            
            rarity_en = self._get_english_key(self.rarity_combo.currentText())
            name_code = self.name_code_map.get(self.name_combo.currentText())
            name_chunk = f"{{{name_code}}}" if name_code else ""

            rarity_code_val = ""
            if rarity_en == "Legendary":
                rarity_code_val = self.data['legendaryMap'][current_class_en].get(str(name_code), '')
                if current_class_en == "Harlowe": name_chunk += " {27}"
            else:
                PER_CLASS_RARITIES = {"Vex": {"Common": 217, "Uncommon": 218, "Rare": 219, "Epic": 220},"Rafa": {"Common": 66, "Uncommon": 67, "Rare": 68, "Epic": 69},"Harlowe": {"Common": 224, "Uncommon": 223, "Rare": 222, "Epic": 221},"Amon": {"Common": 70, "Uncommon": 69, "Rare": 68, "Epic": 67}}
                rarity_code_val = PER_CLASS_RARITIES.get(current_class_en, {}).get(rarity_en, "")
            rarity_chunk = f"{{{rarity_code_val}}}" if rarity_code_val else ""

            leg_extras_codes = [f"{{{self.leg_sel_list.item(i).text().split('{')[-1].strip()}" for i in range(self.leg_sel_list.count())]
            leg_extras_chunk = " ".join(leg_extras_codes)

            skill_chunks = []
            skills_data = self.data.get("classes", {}).get(current_class_en, {}).get("skills", {})
            for eng_name, codes in sorted(skills_data.items()):
                points = self.current_skill_points.get(eng_name, 0)
                if points > 0:
                    skill_chunks.extend([f"{{{c}}}" for c in codes[:points]])
            skills_chunk = " ".join(skill_chunks)
            
            perk_codes = []
            for i in range(self.perk_sel_list.count()):
                item_text = self.perk_sel_list.item(i).text()
                # Check for (count) prefix
                match = re.match(r"\((\d+)\)\s+(.*)", item_text)
                if match:
                    count = int(match.group(1))
                    perk_display_name = match.group(2)
                else:
                    count = 1
                    perk_display_name = item_text
                
                perk_eng_name = self._get_english_key(perk_display_name)
                perk_data = next((p for p in self.data['perks'] if p['name'] == perk_eng_name), None)
                
                if perk_data:
                    for _ in range(count):
                        perk_codes.append(str(perk_data['code']))

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
            self.full_string_output.setText(self.ui_loc['dialogs']['gen_error'].format(error=e))
            self.base85_output.setText("...")

    def populate_legendary_extras(self, preserve_selection=False):
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
        if not current_class_en: return

        legendary_names_data = self.data["classes"][current_class_en]["names"]["legendary"]
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

        for item in legendary_names_data:
            localized_name = self._(item['name'])
            item_str = f"{localized_name} {{{item['code']}}}"
            
            if localized_name == primary_name_display:
                continue
            
            if item_str not in preserved_set:
                self.leg_avail_list.addItem(item_str)

    def populate_perks(self):
        self.perk_avail_list.clear()
        query = self.perk_search_edit.text().lower()
        perks = self.data.get("perks", [])
        for perk in perks:
            name = self._(perk['name'])
            if not query or query in name.lower():
                self.perk_avail_list.addItem(name)

    def add_perks(self):
        multiplier = self.perk_multiplier.value()
        for item in self.perk_avail_list.selectedItems():
            perk_name = item.text()
            
            # Check if already exists in selection list to update count
            existing_item = None
            for i in range(self.perk_sel_list.count()):
                sel_item = self.perk_sel_list.item(i)
                sel_text = sel_item.text()
                
                # Check for (count) prefix
                match = re.match(r"\((\d+)\)\s+(.*)", sel_text)
                if match:
                    current_count = int(match.group(1))
                    current_name = match.group(2)
                else:
                    current_count = 1
                    current_name = sel_text
                
                if current_name == perk_name:
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
        safe_name = re.sub(r"[^a-zA-Z0-9_!]", "", skill_name.replace("'", "").replace("’", "").replace(" ", "_")).lower()
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
        self.skill_tree.clear()
        self.skill_widgets = {}
        current_class_en = self._get_current_class_en()
        if not current_class_en: return

        query = self.skill_search_edit.text().lower()
        skills_data = self.data.get("classes", {}).get(current_class_en, {}).get("skills", {})

        for eng_name, codes in sorted(skills_data.items()):
            localized_name = self._(eng_name)
            if query and query not in eng_name.lower() and query not in localized_name.lower():
                continue

            icon = self.get_skill_icon(eng_name, current_class_en)
            item = QTreeWidgetItem(self.skill_tree)

            # Set styled tooltip using pre-loaded descriptions
            description_info = self.skill_descriptions.get(eng_name)
            if not description_info:
                description_info = self.skill_descriptions.get(eng_name.lower())

            if description_info:
                skill_type = self._(description_info.get('type', 'N/A'))
                lang_key = 'zh' if self.current_lang == 'zh-CN' else 'en'
                desc_text = description_info.get(lang_key, description_info.get('en', 'No description found.'))
                
                tooltip_html = f"""
                    <div style='width: 300px;'>
                        <p><b>{localized_name}</b></p>
                        <p><i>{self.ui_loc['tooltips']['type']}: {skill_type}</i></p>
                        <hr>
                        <p>{desc_text}</p>
                    </div>
                """
                item.setToolTip(1, tooltip_html)

            item.setIcon(0, icon)
            item.setText(1, localized_name)
            item.setText(2, f"{{{', '.join(map(str, codes[:5]))}}}")
            item.setData(1, Qt.ItemDataRole.UserRole, {"eng_name": eng_name, "codes": codes[:5]})
            
            max_points = len(codes[:5])
            current_points = self.current_skill_points.get(eng_name, 0)
            sp_widget = SkillPointWidget(current_points, max_points, loc_data=self.ui_loc['skill_point_widget'])
            sp_widget.valueChanged.connect(lambda val, name=eng_name: self.on_skill_point_change(name, val))
            
            self.skill_tree.setItemWidget(item, 3, sp_widget)
            self.skill_widgets[eng_name] = item
