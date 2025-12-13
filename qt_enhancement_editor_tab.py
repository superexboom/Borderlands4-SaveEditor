from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit, QPushButton, QGroupBox, QComboBox, QCheckBox, QListWidget, QMessageBox, QAbstractItemView, QScrollArea, QSpinBox
from PyQt6.QtCore import pyqtSignal, Qt
import random
import re

import b_encoder
import resource_loader

enhancement_data = resource_loader.get_enhancement_data()

class QtEnhancementEditorTab(QWidget):
    add_to_backpack_requested = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_lang = 'zh-CN'
        self.localization_data = self._load_game_localization()
        self.ui_loc = self._load_ui_localization()
        self.perk_vars = {}
        self.stack_map = {}
        self.list247 = []
        self.rnd_seed = random.randint(1000, 9999)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        if not enhancement_data:
            self.main_layout.addWidget(QLabel(self.ui_loc['dialogs']['error_load']))
            return
            
        self._build_ui()
        self.populate_initial_data()

    def _load_game_localization(self, lang=None):
        if lang is None: lang = self.current_lang
        if lang in ['en-US', 'ru', 'ua']: return {}
        # 使用从CSV加载的本地化数据
        if enhancement_data and 'localization' in enhancement_data:
            return enhancement_data['localization']
        return {}

    def _(self, text):
        return self.localization_data.get(text, text)

    def update_language(self, lang):
        print(f"DEBUG: Updating language for {self.__class__.__name__} to {lang}...")
        self.current_lang = lang
        self.ui_loc = self._load_ui_localization(lang)
        self.localization_data = self._load_game_localization(lang)
        
        self._build_ui()
        self.populate_initial_data()
        
        print(f"DEBUG: Finished updating language for {self.__class__.__name__}.")

    def _load_ui_localization(self, lang=None):
        if lang is None: lang = self.current_lang
        filename = resource_loader.get_ui_localization_file(lang)
        data = resource_loader.load_json_resource(filename)
        if data and "enhancement_tab" in data:
            return data["enhancement_tab"]
        else:
            # Fallback
            return {
                "groups": {"output": "Output", "base85": "Base85", "perks_mfg": "Perks", "perk_stacking": "Stacking", "builder_247": "Builder 247"},
                "labels": {"selected_stacks": "Selected Stacks", "manufacturer": "Manufacturer", "rarity": "Rarity"},
                "buttons": {"copy": "Copy", "add_to_backpack": "Add", "clear": "Clear"},
                "flags": {"1": "1", "3": "3", "5": "5", "17": "17", "33": "33", "65": "65", "129": "129"},
                "dialogs": {"error_load": "Error loading data", "copied": "Copied", "copy_raw_msg": "Copied raw", "copy_b85_msg": "Copied base85",
                            "no_valid_code": "No valid code", "gen_valid_first": "Generate first"}
            }

    def _build_ui(self):
        # Clear layout content
        while self.main_layout.count():
            item = self.main_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        self.main_layout.addWidget(scroll_area)

        container = QWidget()
        scroll_area.setWidget(container)
        main_layout = QVBoxLayout(container)

        # Outputs
        raw_output_group = QGroupBox(self.ui_loc['groups']['output'])
        raw_layout = QHBoxLayout(raw_output_group)
        self.raw_output_var = QLineEdit()
        self.raw_output_var.setReadOnly(True)
        raw_layout.addWidget(self.raw_output_var)
        copy_raw_btn = QPushButton(self.ui_loc['buttons']['copy'])
        copy_raw_btn.clicked.connect(self.copy_raw_output)
        raw_layout.addWidget(copy_raw_btn)
        main_layout.addWidget(raw_output_group)

        b85_group = QGroupBox(self.ui_loc['groups']['base85'])
        b85_layout = QHBoxLayout(b85_group)
        self.b85_output_var = QLineEdit()
        self.b85_output_var.setReadOnly(True)
        b85_layout.addWidget(self.b85_output_var)

        action_frame = QHBoxLayout()
        self.add_to_backpack_btn = QPushButton(self.ui_loc['buttons']['add_to_backpack'])
        self.add_to_backpack_btn.clicked.connect(self.add_item_to_backpack)
        action_frame.addWidget(self.add_to_backpack_btn)
        self.flag_var = QComboBox()
        flags = self.ui_loc['flags']
        flag_options_loc = [flags["1"], flags["3"], flags["5"], flags["17"], flags["33"], flags["65"], flags["129"]]
        self.flag_var.addItems(flag_options_loc)
        action_frame.addWidget(self.flag_var)
        b85_layout.addLayout(action_frame)

        copy_b85_btn = QPushButton(self.ui_loc['buttons']['copy'])
        copy_b85_btn.clicked.connect(self.copy_b85_output)
        b85_layout.addWidget(copy_b85_btn)
        main_layout.addWidget(b85_group)

        # Manufacturer and Rarity
        mfg_rarity_layout = QHBoxLayout()
        mfg_layout = QVBoxLayout()
        mfg_layout.addWidget(QLabel(self.ui_loc['labels']['manufacturer']))
        self.mfg_sel = QComboBox()
        self.mfg_sel.currentTextChanged.connect(self.on_mfg_change)
        mfg_layout.addWidget(self.mfg_sel)
        mfg_rarity_layout.addLayout(mfg_layout)

        rarity_layout = QVBoxLayout()
        rarity_layout.addWidget(QLabel(self.ui_loc['labels']['rarity']))
        self.rarity_sel = QComboBox()
        self.rarity_sel.currentTextChanged.connect(self.rebuild_output)
        rarity_layout.addWidget(self.rarity_sel)
        mfg_rarity_layout.addLayout(rarity_layout)

        level_layout = QVBoxLayout()
        level_layout.addWidget(QLabel(self.ui_loc['labels']['level']))
        self.level_edit = QLineEdit("50")
        self.level_edit.textChanged.connect(self.rebuild_output)
        level_layout.addWidget(self.level_edit)
        mfg_rarity_layout.addLayout(level_layout)

        main_layout.addLayout(mfg_rarity_layout)

        # Grids
        perks_group = QGroupBox(self.ui_loc['groups']['perks_mfg'])
        self.perks_box = QVBoxLayout(perks_group)
        main_layout.addWidget(perks_group)

        stacking_group = QGroupBox(self.ui_loc['groups']['perk_stacking'])
        stacking_layout = QVBoxLayout(stacking_group)

        stacking_layout.addWidget(QLabel(self.ui_loc['labels']['selected_stacks']))
        self.stack_sel_list = QListWidget()
        self.stack_sel_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.stack_sel_list.setStyleSheet("QListWidget::item { background-color: transparent; }")
        self.stack_sel_list.setMinimumHeight(200)
        stacking_layout.addWidget(self.stack_sel_list)

        self.stack_filter_var = QLineEdit()
        self.stack_filter_var.textChanged.connect(self.build_unified_available)
        stacking_layout.addWidget(self.stack_filter_var)

        avail_layout = QHBoxLayout()
        self.stack_avail_list = QListWidget()
        self.stack_avail_list.setMinimumHeight(200)
        self.stack_avail_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        avail_layout.addWidget(self.stack_avail_list)
        
        buttons_stack = QVBoxLayout()
        
        self.stack_multiplier = QSpinBox()
        self.stack_multiplier.setRange(1, 999)
        self.stack_multiplier.setValue(1)
        buttons_stack.addWidget(self.stack_multiplier)
        
        add_stack_btn = QPushButton("»")
        add_stack_btn.clicked.connect(self.add_selected_stacks)
        buttons_stack.addWidget(add_stack_btn)
        
        remove_stack_btn = QPushButton("«")
        remove_stack_btn.clicked.connect(self.remove_selected_stacks)
        buttons_stack.addWidget(remove_stack_btn)
        
        clear_stack_btn = QPushButton(self.ui_loc['buttons']['clear'])
        clear_stack_btn.clicked.connect(self.clear_stacks)
        buttons_stack.addWidget(clear_stack_btn)
        
        avail_layout.addLayout(buttons_stack)
        stacking_layout.addLayout(avail_layout)

        main_layout.addWidget(stacking_group)

        # 247 Builder
        builder_247_group = QGroupBox(self.ui_loc['groups']['builder_247'])
        builder_247_layout = QGridLayout(builder_247_group)
        filter_247_layout = QHBoxLayout()
        self.filter_247_var = QLineEdit()
        self.filter_247_var.textChanged.connect(self.set_247_lists)
        filter_247_layout.addWidget(self.filter_247_var)
        builder_247_layout.addLayout(filter_247_layout, 0, 0, 1, 3)

        self.avail_247_list = QListWidget()
        self.avail_247_list.setMinimumHeight(200)
        self.avail_247_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        builder_247_layout.addWidget(self.avail_247_list, 1, 0)
        
        buttons_247 = QVBoxLayout()
        self.stats_multiplier = QSpinBox()
        self.stats_multiplier.setRange(1, 999)
        self.stats_multiplier.setValue(1)
        buttons_247.addWidget(self.stats_multiplier)
        
        add_247_btn = QPushButton("»")
        add_247_btn.clicked.connect(self.add_247)
        buttons_247.addWidget(add_247_btn)
        
        rem_247_btn = QPushButton("«")
        rem_247_btn.clicked.connect(self.rem_247)
        buttons_247.addWidget(rem_247_btn)
        
        clear_247_btn = QPushButton(self.ui_loc['buttons']['clear'])
        clear_247_btn.clicked.connect(self.clear_247)
        buttons_247.addWidget(clear_247_btn)
        
        builder_247_layout.addLayout(buttons_247, 1, 1)
        self.sel_247_list = QListWidget()
        self.sel_247_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.sel_247_list.setMinimumHeight(200)
        builder_247_layout.addWidget(self.sel_247_list, 1, 2)
        main_layout.addWidget(builder_247_group)
        main_layout.addStretch()

    def populate_initial_data(self):
        mfg_names = sorted(enhancement_data.get('manufacturers', {}).keys())
        self.mfg_sel.addItems([self._(name) for name in mfg_names])
        if mfg_names:
            self.mfg_sel.setCurrentText(self._(mfg_names[0]))
        self.on_mfg_change()
        self.set_247_lists()

    def on_mfg_change(self, *args):
        self.set_rarities_for_mfg()
        self.set_perk_checkboxes()
        self.build_unified_available()
        self.rebuild_output()

    def set_rarities_for_mfg(self):
        mfg_name = self._get_current_mfg_en_name()
        if not mfg_name: return
        rarities = enhancement_data['manufacturers'][mfg_name]['rarities']
        rarity_order = ['Common', 'Uncommon', 'Rare', 'Epic', 'Legendary']
        self.rarity_sel.clear()
        self.rarity_sel.addItems([self._(r) for r in rarity_order if r in rarities])
        if self.rarity_sel.count() > 0:
            self.rarity_sel.setCurrentIndex(0)
    
    def set_perk_checkboxes(self):
        while self.perks_box.count():
            child = self.perks_box.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.perk_vars = {}
        
        mfg_name = self._get_current_mfg_en_name()
        if not mfg_name: return
        perks = enhancement_data['manufacturers'][mfg_name]['perks']
        perk_map = {p['index']: p['name'] for p in perks}
        order = [1, 2, 3, 9]

        for index in order:
            if index in perk_map:
                var = QCheckBox(self._(perk_map[index]))
                var.stateChanged.connect(self.rebuild_output)
                self.perks_box.addWidget(var)
                self.perk_vars[index] = var

    def build_unified_available(self, *args):
        self.stack_avail_list.clear()
        current_mfg_en = self._get_current_mfg_en_name()
        if not current_mfg_en: return 
        query = self.stack_filter_var.text().lower()

        all_perks = []
        for mfg, data in enhancement_data.get('manufacturers', {}).items():
            if mfg == current_mfg_en: continue
            for perk in data.get('perks', []):
                 if perk.get('index') in [1, 2, 3, 9]:
                    all_perks.append({'mfg': mfg, 'perk': perk})

        for item in sorted(all_perks, key=lambda x: (x['mfg'], x['perk']['index'])):
            mfg_name, perk_data = item['mfg'], item['perk']
            text = f"[{perk_data['index']}] {self._(perk_data['name'])} — {self._(mfg_name)}"
            if not query or query in text.lower():
                self.stack_avail_list.addItem(text)
        
    def add_selected_stacks(self):
        multiplier = self.stack_multiplier.value()
        for item in self.stack_avail_list.selectedItems():
            stack_name = item.text()
            
            existing_item = None
            for i in range(self.stack_sel_list.count()):
                sel_item = self.stack_sel_list.item(i)
                sel_text = sel_item.text()
                
                match = re.match(r"\((\d+)\)\s+(.*)", sel_text)
                if match:
                    current_count = int(match.group(1))
                    current_name = match.group(2)
                else:
                    current_count = 1
                    current_name = sel_text
                
                if current_name == stack_name:
                    existing_item = sel_item
                    break
            
            if existing_item:
                new_count = current_count + multiplier
                existing_item.setText(f"({new_count}) {stack_name}")
            else:
                self.stack_sel_list.addItem(f"({multiplier}) {stack_name}")
                
        self.rebuild_output()

    def remove_selected_stacks(self):
        for item in self.stack_sel_list.selectedItems():
            self.stack_sel_list.takeItem(self.stack_sel_list.row(item))
        self.rebuild_output()

    def clear_stacks(self):
        self.stack_sel_list.clear()
        self.rebuild_output()

    def set_247_lists(self, *args):
        self.avail_247_list.clear()
        query = self.filter_247_var.text().lower()
        stats = enhancement_data.get('secondary_247', [])
        for stat in stats:
            text = f"[{stat['code']}] {self._(stat['name'])}"
            if not query or query in text.lower():
                self.avail_247_list.addItem(text)

    def add_247(self):
        multiplier = self.stats_multiplier.value()
        for item in self.avail_247_list.selectedItems():
            stat_name = item.text()
            
            existing_item = None
            for i in range(self.sel_247_list.count()):
                sel_item = self.sel_247_list.item(i)
                sel_text = sel_item.text()
                
                match = re.match(r"\((\d+)\)\s+(.*)", sel_text)
                if match:
                    current_count = int(match.group(1))
                    current_name = match.group(2)
                else:
                    current_count = 1
                    current_name = sel_text
                
                if current_name == stat_name:
                    existing_item = sel_item
                    break
            
            if existing_item:
                new_count = current_count + multiplier
                existing_item.setText(f"({new_count}) {stat_name}")
            else:
                self.sel_247_list.addItem(f"({multiplier}) {stat_name}")
                
        self.rebuild_output()

    def rem_247(self):
        for item in self.sel_247_list.selectedItems():
            self.sel_247_list.takeItem(self.sel_247_list.row(item))
        self.rebuild_output()
        
    def clear_247(self):
        self.sel_247_list.clear()
        self.rebuild_output()

    def rebuild_output(self, *args):
        parts = []
        mfg_en = self._get_current_mfg_en_name()
        if not mfg_en: return
        mfg_code = enhancement_data['manufacturers'][mfg_en]['code']
        
        level_val = self.level_edit.text() if hasattr(self, 'level_edit') else "50"
        if not level_val: level_val = "50"
        
        parts.append(f"{mfg_code}, 0, 1, {level_val}| 2, {self.rnd_seed}||")
        rarity_en = self._get_current_rarity_en_name()
        if not rarity_en: return
        rarity_code = enhancement_data['manufacturers'][mfg_en]['rarities'][rarity_en]
        parts.append(f"{{{rarity_code}}}")

        rarity_247_code = enhancement_data['rarity_map_247'][rarity_en]
        parts.append(f"{{247:{rarity_247_code}}}")

        for index, var in self.perk_vars.items():
            if var.isChecked():
                parts.append(f"{{{index}}}")

        stacked_perks = {}
        for i in range(self.stack_sel_list.count()):
            item_text = self.stack_sel_list.item(i).text()
            match = re.match(r"\((\d+)\)\s+(.*)", item_text)
            if match:
                count = int(match.group(1))
                display_text = match.group(2)
            else:
                count = 1
                display_text = item_text
                
            mfg_name_loc = display_text.split('—')[-1].strip()
            perk_idx = int(display_text[1:display_text.find(']')])
            mfg_en_stack = self._get_en_name_from_loc(mfg_name_loc, list(enhancement_data['manufacturers'].keys()))
            if mfg_en_stack:
                mfg_code_stack = enhancement_data['manufacturers'][mfg_en_stack]['code']
                if mfg_code_stack not in stacked_perks:
                    stacked_perks[mfg_code_stack] = []
                for _ in range(count):
                    stacked_perks[mfg_code_stack].append(perk_idx)
        
        for code, indices in stacked_perks.items():
             parts.append(f"{{{code}:[{' '.join(map(str, sorted(indices)))}]}}")

        stats_247 = []
        for i in range(self.sel_247_list.count()):
            item_text = self.sel_247_list.item(i).text()
            match = re.match(r"\((\d+)\)\s+(.*)", item_text)
            if match:
                count = int(match.group(1))
                display_text = match.group(2)
            else:
                count = 1
                display_text = item_text
            
            val = int(display_text.split(']')[0][1:])
            for _ in range(count):
                stats_247.append(val)
                
        if stats_247:
            parts.append(f"{{247:[{' '.join(map(str, stats_247))}]}}")

        full_string = " ".join(parts).replace("  ", " ").strip() + "|"
        self.raw_output_var.setText(full_string)

        encoded_serial, err = b_encoder.encode_to_base85(full_string)
        if err:
            encoded_serial = f"Error: {err}"
        self.b85_output_var.setText(encoded_serial)

    def _get_current_mfg_en_name(self):
        loc_name = self.mfg_sel.currentText()
        return self._get_en_name_from_loc(loc_name, list(enhancement_data['manufacturers'].keys()))

    def _get_current_rarity_en_name(self):
        loc_name = self.rarity_sel.currentText()
        return self._get_en_name_from_loc(loc_name, list(enhancement_data['rarity_map_247'].keys()))

    def _get_en_name_from_loc(self, loc_name, key_list):
        for key in key_list:
            if self._(key) == loc_name:
                return key
        return None

    def copy_raw_output(self):
        QApplication.clipboard().setText(self.raw_output_var.text())
        QMessageBox.information(self, self.ui_loc['dialogs']['copied'], self.ui_loc['dialogs']['copy_raw_msg'])

    def copy_b85_output(self):
        QApplication.clipboard().setText(self.b85_output_var.text())
        QMessageBox.information(self, self.ui_loc['dialogs']['copied'], self.ui_loc['dialogs']['copy_b85_msg'])

    def add_item_to_backpack(self):
        serial = self.b85_output_var.text()
        if not serial or "Error" in serial:
            QMessageBox.warning(self, self.ui_loc['dialogs']['no_valid_code'], self.ui_loc['dialogs']['gen_valid_first'])
            return
        flag = self.flag_var.currentText().split(" ")[0]
        self.add_to_backpack_requested.emit(serial, flag)
