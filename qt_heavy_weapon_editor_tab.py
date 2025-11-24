import pandas as pd
from functools import lru_cache
import random
import re

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QComboBox, QRadioButton, QListWidget, QListWidgetItem,
    QScrollArea, QMessageBox, QAbstractItemView, QSpinBox
)
from PyQt6.QtCore import pyqtSignal, Qt

import b_encoder
import resource_loader
import lookup
import bl4_functions as bl4f

@lru_cache(maxsize=None)
def load_heavy_weapon_data(lang='zh-CN'):
    try:
        suffix = "_EN" if lang == 'en-US' else ""
        main_perk_path = resource_loader.get_heavy_data_path(f'heavy_main_perk{suffix}.csv')
        mfg_perk_path = resource_loader.get_heavy_data_path(f'heavy_manufacturer_perk{suffix}.csv')
        
        df_main = pd.read_csv(main_perk_path)
        df_mfg = pd.read_csv(mfg_perk_path)
        df_mfg['Manufacturer ID'] = pd.to_numeric(df_mfg['Manufacturer ID'], errors='coerce')
        df_mfg.dropna(subset=['Manufacturer ID'], inplace=True)
        df_mfg['Manufacturer ID'] = df_mfg['Manufacturer ID'].astype(int)

        localization = {}
        if lang == 'zh-CN':
            localization = resource_loader.load_json_resource('heavy/Heavy_localization_zh-CN.json') or {}
            
        return df_main, df_mfg, localization
    except Exception as e:
        print(f"Error loading heavy weapon data: {e}")
        return None, None, None

class QtHeavyWeaponEditorTab(QWidget):
    add_to_backpack_requested = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_lang = 'zh-CN'
        self.df_main, self.df_mfg, self.localization = load_heavy_weapon_data(self.current_lang)
        
        self._load_ui_localization()

        if self.df_main is None:
            layout = QVBoxLayout(self)
            layout.addWidget(QLabel(self.ui_loc.get('dialogs', {}).get('load_error', "错误: 重武器数据(heavy weapon data)无法加载。")))
            return

        self.mfg_ids = [282, 273, 275, 289]
        self.barrel_widgets = []
        self.element_widgets = []
        self.firmware_widgets = []
        
        self._build_ui()
        self.populate_initial_data()
        self._connect_signals()

    def _load_ui_localization(self):
        loc_file = "ui_localization.json" if self.current_lang == 'zh-CN' else "ui_localization_EN.json"
        full_loc = resource_loader.load_json_resource(loc_file) or {}
        self.ui_loc = full_loc.get("heavy_weapon_tab", {})
        self.flags_loc = full_loc.get("weapon_editor_tab", {}).get("flags", {})

    def update_language(self, lang):
        print(f"DEBUG: Updating language for {self.__class__.__name__} to {lang}...")
        self.current_lang = lang
        self.df_main, self.df_mfg, self.localization = load_heavy_weapon_data(lang)
        
        if self.df_main is None:
            print(f"DEBUG: load_heavy_weapon_data failed for {self.__class__.__name__}")
            return

        self._load_ui_localization()
        
        if not self.ui_loc:
            print(f"DEBUG: UI localization missing for {self.__class__.__name__}")
            return
        
        # Refresh UI Texts
        self.output_group.setTitle(self.ui_loc.get('groups', {}).get('output', 'Output'))
        self.raw_label.setText(self.ui_loc.get('labels', {}).get('raw', 'Raw'))
        self.copy_raw_btn.setText(self.ui_loc.get('buttons', {}).get('copy', 'Copy'))
        self.b85_label.setText(self.ui_loc.get('labels', {}).get('base85', 'Base85'))
        self.copy_b85_btn.setText(self.ui_loc.get('buttons', {}).get('copy', 'Copy'))
        self.add_to_pack_btn.setText(self.ui_loc.get('buttons', {}).get('add_to_backpack', 'Add'))
        
        self.base_attrs_group.setTitle(self.ui_loc.get('groups', {}).get('base_attrs', 'Attributes'))
        self.mfg_label.setText(self.ui_loc.get('labels', {}).get('manufacturer', 'Mfg'))
        self.level_label.setText(self.ui_loc.get('labels', {}).get('level', 'Level'))
        self.rarity_label.setText(self.ui_loc.get('labels', {}).get('rarity', 'Rarity'))
        
        self.perks_frame.setTitle(self.ui_loc.get('groups', {}).get('perks', 'Perks'))
        self.barrel_group.setTitle(self.ui_loc.get('groups', {}).get('barrel', 'Barrel'))
        self.element_group.setTitle(self.ui_loc.get('groups', {}).get('element', 'Element'))
        self.firmware_group.setTitle(self.ui_loc.get('groups', {}).get('firmware', 'FW'))
        self.barrel_acc_group.setTitle(self.ui_loc.get('groups', {}).get('barrel_acc', 'Barrel Acc'))
        self.body_acc_group.setTitle(self.ui_loc.get('groups', {}).get('body_acc', 'Body Acc'))
        
        self.barrel_acc_clear_btn.setText(self.ui_loc.get('buttons', {}).get('clear', 'Clear'))
        self.body_acc_clear_btn.setText(self.ui_loc.get('buttons', {}).get('clear', 'Clear'))
        
        self._populate_flags()

        # Refresh Data
        self.mfg_combo.blockSignals(True)
        # Block rarity combo signal as well to prevent unwanted updates during data refresh
        self.rarity_combo.blockSignals(True)
        self.populate_initial_data()
        self.mfg_combo.blockSignals(False)
        self.rarity_combo.blockSignals(False)
        self.on_mfg_change()
        print(f"DEBUG: Finished updating language for {self.__class__.__name__}.")

    def _rebuild_and_connect(self, frame_layout, widget_list):
        for widget in widget_list:
            if isinstance(widget, QRadioButton):
                widget.toggled.connect(self.rebuild_output)
                
    def _(self, text):
        return self.localization.get(str(text), str(text))

    def _build_ui(self):
        # Main layout for the tab itself, containing only the scroll area
        tab_layout = QVBoxLayout(self)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        tab_layout.addWidget(scroll_area)

        # Container widget for all the content that will be scrolled
        container = QWidget()
        scroll_area.setWidget(container)
        main_layout = QVBoxLayout(container)
        
        # --- Top Output ---
        self._create_output_group(main_layout)
        
        # --- Top Controls ---
        self._create_top_controls(main_layout)

        # --- Perks ---
        self.perks_frame = QGroupBox(self.ui_loc['groups']['perks'])
        perks_layout = QGridLayout(self.perks_frame)
        self._create_perk_groups(perks_layout)
        main_layout.addWidget(self.perks_frame)
        main_layout.addStretch() # Ensure content is pushed to the top within the scroll area
        
    def _create_output_group(self, layout):
        self.output_group = QGroupBox(self.ui_loc['groups']['output'])
        grid = QGridLayout(self.output_group)
        
        self.raw_output_edit = QLineEdit()
        self.raw_output_edit.setReadOnly(True)
        self.copy_raw_btn = QPushButton(self.ui_loc['buttons']['copy'])
        
        self.raw_label = QLabel(self.ui_loc['labels']['raw'])
        grid.addWidget(self.raw_label, 0, 0)
        grid.addWidget(self.raw_output_edit, 0, 1)
        grid.addWidget(self.copy_raw_btn, 0, 2)
        
        self.b85_output_edit = QLineEdit()
        self.b85_output_edit.setReadOnly(True)
        self.copy_b85_btn = QPushButton(self.ui_loc['buttons']['copy'])
        self.add_to_pack_btn = QPushButton(self.ui_loc['buttons']['add_to_backpack'])
        self.flag_combo = QComboBox()
        self._populate_flags()
        
        self.b85_label = QLabel(self.ui_loc['labels']['base85'])
        grid.addWidget(self.b85_label, 1, 0)
        grid.addWidget(self.b85_output_edit, 1, 1)
        grid.addWidget(self.copy_b85_btn, 1, 2)
        grid.addWidget(self.flag_combo, 1, 3)
        grid.addWidget(self.add_to_pack_btn, 1, 4)

        layout.addWidget(self.output_group)

    def _create_top_controls(self, layout):
        self.base_attrs_group = QGroupBox(self.ui_loc['groups']['base_attrs'])
        controls_layout = QHBoxLayout(self.base_attrs_group)
        
        self.mfg_combo = QComboBox()
        self.level_edit = QLineEdit("50")
        self.rarity_combo = QComboBox()
        self.rarity_combo.setFixedWidth(600)
        
        self.mfg_label = QLabel(self.ui_loc['labels']['manufacturer'])
        self.level_label = QLabel(self.ui_loc['labels']['level'])
        self.rarity_label = QLabel(self.ui_loc['labels']['rarity'])
        
        controls_layout.addWidget(self.mfg_label)
        controls_layout.addWidget(self.mfg_combo)
        controls_layout.addWidget(self.level_label)
        controls_layout.addWidget(self.level_edit)
        controls_layout.addWidget(self.rarity_label)
        controls_layout.addWidget(self.rarity_combo)
        controls_layout.addStretch()
        
        layout.addWidget(self.base_attrs_group)

    def _create_radio_perk_groups(self, layout):
        self.barrel_group, self.barrel_frame = self._create_scrollable_radio_group(self.ui_loc['groups']['barrel'])
        self.element_group, self.element_frame = self._create_scrollable_radio_group(self.ui_loc['groups']['element'])
        self.firmware_group, self.firmware_frame = self._create_scrollable_radio_group(self.ui_loc['groups']['firmware'])
        
        layout.addWidget(self.barrel_group, 0, 0)
        layout.addWidget(self.element_group, 0, 1)
        layout.addWidget(self.firmware_group, 0, 2)
        layout.setRowStretch(0, 1) # Less stretch for top radio buttons
        layout.setRowStretch(1, 1) # More stretch for the list views below
        layout.setRowStretch(2, 1)

    def _create_list_perk_groups(self, layout):
        self.barrel_acc_group = self._create_list_perk_group(self.ui_loc['groups']['barrel_acc'], "barrel_acc", use_multiplier=True)
        self.body_acc_group = self._create_list_perk_group(self.ui_loc['groups']['body_acc'], "body_acc", use_multiplier=True)
        layout.addWidget(self.barrel_acc_group, 1, 0, 1, 3)
        layout.addWidget(self.body_acc_group, 2, 0, 1, 3)
        
    def _create_perk_groups(self, layout):
        self._create_radio_perk_groups(layout)
        self._create_list_perk_groups(layout)

    def _create_scrollable_radio_group(self, title):
        group_box = QGroupBox(title)
        scroll_area = QScrollArea()
        scroll_area.setMinimumHeight(200)
        scroll_area.setWidgetResizable(True)
        widget_in_scroll = QWidget()
        layout = QVBoxLayout(widget_in_scroll)
        scroll_area.setWidget(widget_in_scroll)
        main_layout = QVBoxLayout(group_box)
        main_layout.addWidget(scroll_area)
        return group_box, layout

    def _create_list_perk_group(self, title, key=None, use_multiplier=False):
        group_box = QGroupBox(title)
        layout = QGridLayout(group_box)
        
        avail_list = QListWidget()
        avail_list.setMinimumHeight(200)
        avail_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        sel_list = QListWidget()
        sel_list.setMinimumHeight(200)
        sel_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        
        button_layout = QVBoxLayout()
        
        multiplier_box = None
        if use_multiplier:
            multiplier_box = QSpinBox()
            multiplier_box.setRange(1, 999)
            multiplier_box.setValue(1)
            button_layout.addWidget(multiplier_box)
            
        move_btn = QPushButton("»")
        remove_btn = QPushButton("«")
        clear_btn = QPushButton(self.ui_loc['buttons']['clear'])
        
        button_layout.addWidget(move_btn)
        button_layout.addWidget(remove_btn)
        button_layout.addWidget(clear_btn)
        button_layout.addStretch()

        layout.addWidget(avail_list, 0, 0)
        layout.addLayout(button_layout, 0, 1)
        layout.addWidget(sel_list, 0, 2)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(2, 1)

        # Store widgets for later access
        if key:
            prefix = key
        else:
            # Fallback (should not be reached if key is provided)
            if '枪管' in title or 'Barrel' in title:
                prefix = 'barrel_acc'
            elif '枪身' in title or 'Body' in title:
                prefix = 'body_acc'
            else:
                prefix = 'other'
            
        setattr(self, f"{prefix}_avail_list", avail_list)
        setattr(self, f"{prefix}_sel_list", sel_list)
        setattr(self, f"{prefix}_clear_btn", clear_btn)
        
        if multiplier_box:
            setattr(self, f"{prefix}_multiplier", multiplier_box)
        
        # Connect signals
        move_btn.clicked.connect(lambda: self._move_selected_items(avail_list, sel_list, multiplier_box))
        remove_btn.clicked.connect(lambda: self._remove_selected_items(sel_list))
        clear_btn.clicked.connect(lambda: self._clear_list(sel_list))
        
        # Store buttons for connecting signals later (legacy, though using direct connect above is better)
        setattr(self, f"{prefix}_move_btn", move_btn)
        setattr(self, f"{prefix}_remove_btn", remove_btn)

        return group_box
        
    def _get_mfg_name(self, mfg_id):
        if mfg_id in lookup.REVERSE_ID_MAP:
            mfg_en = lookup.REVERSE_ID_MAP[mfg_id][0]
            return bl4f.get_localized_string(mfg_en)
        return "Unknown"

    def populate_initial_data(self):
        self.mfg_combo.clear()
        
        items = []
        for k in self.mfg_ids:
            name = self._get_mfg_name(k)
            items.append((f"{name} - {k}", k))
        
        items.sort(key=lambda x: x[1])
        self.mfg_combo.addItems([x[0] for x in items])

        self._populate_radio_buttons(self.element_frame, self.df_main[self.df_main['Heavy_perk_main_ID'] == 1], self.element_widgets)
        self._populate_radio_buttons(self.firmware_frame, self.df_main[self.df_main['Heavy_perk_main_ID'] == 244], self.firmware_widgets)
        self.on_mfg_change()

    def _populate_radio_buttons(self, frame_layout, df, widget_list, name_key='Stat', desc_key='Description'):
        # Clear existing
        while frame_layout.count():
            child = frame_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        widget_list.clear()

        none_rb = QRadioButton(self.ui_loc['misc']['none'])
        none_rb.setChecked(True)
        frame_layout.addWidget(none_rb)
        widget_list.append(none_rb)

        for _, row in df.iterrows():
            desc = row[desc_key] if desc_key in row and pd.notna(row[desc_key]) else ''
            display_text = f"{self._(row[name_key])} - {desc}" if desc else self._(row[name_key])
            rb = QRadioButton(display_text)
            
            part_id = row['Part_ID']
            # 如果存在 Heavy_perk_main_ID，则将其作为前缀
            if 'Heavy_perk_main_ID' in row and pd.notna(row['Heavy_perk_main_ID']):
                part_id = f"{int(row['Heavy_perk_main_ID'])}:{part_id}"
            
            rb.setProperty("part_id", part_id)
            frame_layout.addWidget(rb)
            widget_list.append(rb)
        frame_layout.addStretch()
        self._rebuild_and_connect(frame_layout, widget_list)
        
    def _populate_barrel_radiobuttons(self):
        mfg_id = int(self.mfg_combo.currentText().split(' - ')[-1])
        filtered_df = self.df_mfg[(self.df_mfg['Part_type'] == 'Barrel') & (self.df_mfg['Manufacturer ID'] == mfg_id)]
        self._populate_radio_buttons(self.barrel_frame, filtered_df, self.barrel_widgets, name_key='Stat', desc_key='Description')
        
    def _connect_signals(self):
        self.mfg_combo.currentTextChanged.connect(self.on_mfg_change)
        self.level_edit.textChanged.connect(self.rebuild_output)
        self.rarity_combo.currentTextChanged.connect(self.rebuild_output)
        
        self.copy_raw_btn.clicked.connect(lambda: self._copy_to_clipboard(self.raw_output_edit))
        self.copy_b85_btn.clicked.connect(lambda: self._copy_to_clipboard(self.b85_output_edit))
        self.add_to_pack_btn.clicked.connect(self._add_to_backpack)

        # List signals for updates
        if hasattr(self, 'barrel_acc_sel_list'):
            self.barrel_acc_sel_list.model().rowsInserted.connect(self.rebuild_output)
            self.barrel_acc_sel_list.model().rowsRemoved.connect(self.rebuild_output)
        if hasattr(self, 'body_acc_sel_list'):
            self.body_acc_sel_list.model().rowsInserted.connect(self.rebuild_output)
            self.body_acc_sel_list.model().rowsRemoved.connect(self.rebuild_output)
        
    def on_mfg_change(self):
        if not self.mfg_combo.currentText(): return
        mfg_id = int(self.mfg_combo.currentText().split(' - ')[-1])
        
        # Populate Rarity
        self.rarity_combo.blockSignals(True)
        self.rarity_combo.clear()
        rarities_df = self.df_mfg[(self.df_mfg['Manufacturer ID'] == mfg_id) & (self.df_mfg['Part_type'] == 'Rarity')]
        for _, row in rarities_df.iterrows():
            desc_val = row['Description']
            desc = f" - {desc_val}" if pd.notna(desc_val) else ""
            self.rarity_combo.addItem(f"{self._(row['Stat'])}{desc}", userData=row['Part_ID'])
        self.rarity_combo.blockSignals(False)
        
        self._populate_barrel_radiobuttons() # Refresh barrels on mfg change
        self.populate_accessory_lists()
        self.rebuild_output()

    def populate_accessory_lists(self):
        mfg_id = int(self.mfg_combo.currentText().split(' - ')[-1])

        # --- Barrel Accessories ---
        if hasattr(self, 'barrel_acc_avail_list'):
            self.barrel_acc_avail_list.clear()
        else:
            # Should not happen with correct key
            return

        barrel_acc_df = self.df_mfg[self.df_mfg['Part_type'] == 'Barrel Accessory'].copy()
        barrel_acc_df.dropna(subset=['String'], inplace=True)
        barrel_acc_df = barrel_acc_df.drop_duplicates(subset=['Part_ID', 'Manufacturer ID'])
        barrel_acc_df = barrel_acc_df[barrel_acc_df['Manufacturer ID'] == mfg_id] # Filter for current manufacturer
        barrel_acc_df = barrel_acc_df.sort_values(by=['String', 'Part_ID'])

        barrel_subtype_names = {}
        barrel_subtypes_df = self.df_mfg[
            (self.df_mfg['Part_type'] == 'Barrel') & 
            (~self.df_mfg['Stat'].str.contains('（', na=False))
        ]
        for _, row in barrel_subtypes_df.iterrows():
            if pd.notna(row['String']):
                barrel_subtype_names[(row['Manufacturer ID'], row['String'])] = row['Stat']
        
        for _, row in barrel_acc_df.iterrows():
            barrel_string_base = '_'.join(row['String'].split('_')[:2])
            subtype_name = barrel_subtype_names.get((row['Manufacturer ID'], barrel_string_base), '')
            
            desc = row['Description'] if pd.notna(row['Description']) else ''
            display_text = f"{subtype_name} - {row['Stat']} - {desc} - ID:{row['Part_ID']}"

            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, row['Part_ID'])
            if hasattr(self, 'barrel_acc_avail_list'):
                self.barrel_acc_avail_list.addItem(item)

        # --- Body Accessories ---
        if hasattr(self, 'body_acc_avail_list'):
            self.body_acc_avail_list.clear()
        body_df = self.df_mfg[self.df_mfg['Part_type'] == 'Body Accessory'].copy()
        body_df = body_df.drop_duplicates(subset=['Part_ID', 'Manufacturer ID'])
        body_df = body_df[body_df['Manufacturer ID'] == mfg_id] # Filter for current manufacturer
        body_df = body_df.sort_values(by=['Part_ID'])

        for _, row in body_df.iterrows():
            mfg_name = self._get_mfg_name(row['Manufacturer ID'])
            display_text = f"{mfg_name} - {row['Stat']} - ID:{row['Part_ID']}"
            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, row['Part_ID'])
            if hasattr(self, 'body_acc_avail_list'):
                self.body_acc_avail_list.addItem(item)

    def rebuild_output(self, *args):
        mfg_id = int(self.mfg_combo.currentText().split(' - ')[-1])
        level = self.level_edit.text()
        rarity_id = self.rarity_combo.currentData()
        
        main_parts = [f"{mfg_id}, 0, 1, {level}| 2, {random.randint(100,9999)}||"]
        skill_parts = []
        
        if rarity_id: skill_parts.append(f"{{{rarity_id}}}")
        
        body_row = self.df_mfg[(self.df_mfg['Manufacturer ID'] == mfg_id) & (self.df_mfg['Part_type'] == 'Body')]
        if not body_row.empty: skill_parts.append(f"{{{body_row.iloc[0]['Part_ID']}}}")

        for rb in self.barrel_widgets + self.element_widgets + self.firmware_widgets:
            if rb.isChecked() and rb.property("part_id"):
                skill_parts.append(f"{{{rb.property('part_id')}}}")

        lists_to_check = []
        if hasattr(self, 'barrel_acc_sel_list'): lists_to_check.append(self.barrel_acc_sel_list)
        if hasattr(self, 'body_acc_sel_list'): lists_to_check.append(self.body_acc_sel_list)

        for list_widget in lists_to_check:
            for i in range(list_widget.count()):
                item = list_widget.item(i)
                # Handle count
                count = 1
                match = re.match(r"\((\d+)\)\s+(.*)", item.text())
                if match:
                    count = int(match.group(1))
                
                part_id = item.data(Qt.ItemDataRole.UserRole)
                for _ in range(count):
                    skill_parts.append(f"{{{part_id}}}")

        final_string = " ".join(main_parts) + " " + " ".join(skill_parts) + " |"
        self.raw_output_edit.setText(final_string)
        
        encoded, err = b_encoder.encode_to_base85(final_string)
        self.b85_output_edit.setText(encoded if not err else f"错误: {err}")

    def _move_selected_items(self, source_list, dest_list, multiplier_box=None):
        count_val = multiplier_box.value() if multiplier_box else 1
        for item in source_list.selectedItems():
            if item.flags() & Qt.ItemFlag.ItemIsEnabled:
                 base_text = item.text()
                 
                 existing_item = None
                 for i in range(dest_list.count()):
                    sel_item = dest_list.item(i)
                    sel_text = sel_item.text()
                    
                    match = re.match(r"\((\d+)\)\s+(.*)", sel_text)
                    if match:
                        current_count = int(match.group(1))
                        current_name = match.group(2)
                    else:
                        current_count = 1
                        current_name = sel_text
                    
                    if current_name == base_text:
                        existing_item = sel_item
                        break
                
                 if existing_item:
                    new_count = current_count + count_val
                    existing_item.setText(f"({new_count}) {base_text}")
                 else:
                    new_item = item.clone()
                    if multiplier_box:
                        new_item.setText(f"({count_val}) {base_text}")
                    dest_list.addItem(new_item)
        self.rebuild_output()

    def _remove_selected_items(self, list_widget):
        for item in list_widget.selectedItems():
            list_widget.takeItem(list_widget.row(item))
        self.rebuild_output()

    def _clear_list(self, list_widget):
        list_widget.clear()
        self.rebuild_output()

    def _copy_to_clipboard(self, line_edit):
        clipboard = QApplication.clipboard()
        clipboard.setText(line_edit.text())
        QMessageBox.information(self, self.ui_loc['dialogs']['success'], self.ui_loc['dialogs']['copied'])
        
    def _add_to_backpack(self):
        serial = self.b85_output_edit.text()
        if not serial or "错误" in serial:
            QMessageBox.warning(self, self.ui_loc['dialogs']['no_valid_code'], self.ui_loc['dialogs']['gen_first'])
            return
        flag = self.flag_combo.currentText().split(" ")[0]
        self.add_to_backpack_requested.emit(serial, flag)

    def _populate_flags(self):
        self.flag_combo.clear()
        
        flags_map = {
            "1": "1 (Common)" if self.current_lang == 'en-US' else "1 (普通)",
            "3": "3 (Favorites)" if self.current_lang == 'en-US' else "3 (收藏)",
            "5": "5 (Trash)" if self.current_lang == 'en-US' else "5 (垃圾)",
            "17": "17 (Group 1)" if self.current_lang == 'en-US' else "17 (编组1)",
            "33": "33 (Group 2)" if self.current_lang == 'en-US' else "33 (编组2)",
            "65": "65 (Group 3)" if self.current_lang == 'en-US' else "65 (编组3)",
            "129": "129 (Group 4)" if self.current_lang == 'en-US' else "129 (编组4)"
        }
        
        if self.flags_loc:
            flags_map = {k: self.flags_loc.get(k, v) for k, v in flags_map.items()}

        flag_values = [flags_map["1"], flags_map["3"], flags_map["5"], flags_map["17"], flags_map["33"], flags_map["65"], flags_map["129"]]
        self.flag_combo.addItems(flag_values)
        for i in range(self.flag_combo.count()):
            if flags_map["3"] == self.flag_combo.itemText(i):
                self.flag_combo.setCurrentIndex(i)
