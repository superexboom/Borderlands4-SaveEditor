import pandas as pd
from functools import lru_cache
import random
import re

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QComboBox, QRadioButton, QListWidget, QListWidgetItem,
    QScrollArea, QMessageBox, QSpinBox
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QColor

import b_encoder
import resource_loader
import lookup
import bl4_functions as bl4f

@lru_cache(maxsize=None)
def load_repkit_data(lang='zh-CN'):
    """使用资源加载器加载修复套件数据。"""
    try:
        suffix = "_EN" if lang in ['en-US', 'ru', 'ua'] else ""
        main_perk_path = resource_loader.get_repkit_data_path(f'repkit_main_perk{suffix}.csv')
        mfg_perk_path = resource_loader.get_repkit_data_path(f'repkit_manufacturer_perk{suffix}.csv')
        
        if not main_perk_path or not mfg_perk_path:
            QMessageBox.critical(None, "加载数据失败", "无法找到修复套件CSV文件路径。")
            return None, None, None

        df_main = pd.read_csv(main_perk_path)
        df_mfg = pd.read_csv(mfg_perk_path)
        
        localization = {}
        if lang == 'zh-CN':
            localization = resource_loader.load_json_resource('repkit/Repkit_localization_zh-CN.json')
            if not localization:
                print("警告: 无法加载Repkit_localization_zh-CN.json")
                localization = {}
            
        return df_main, df_mfg, localization
    except Exception as e:
        QMessageBox.critical(None, "加载数据失败", f"无法加载或解析修复套件数据文件: {e}")
        return None, None, None

class QtRepkitEditorTab(QWidget):
    add_to_backpack_requested = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_lang = 'zh-CN'
        self.df_main, self.df_mfg, self.localization = load_repkit_data(self.current_lang)
        
        self._load_ui_localization()

        if self.df_main is None or self.df_mfg is None:
            layout = QVBoxLayout(self)
            layout.addWidget(QLabel(self.ui_loc.get('dialogs', {}).get('load_error', "错误: 修复套件数据(repkit data)无法加载。")))
            return

        # 初始化变量
        self.mfg_ids = [277, 265, 266, 285, 274, 290, 261, 269]
        self.rarity_map = {}
        self.legendary_perk_map = {}
        self.prefix_map = {}
        self.firmware_map = {}
        self.resistance_map = {} 
        self.universal_perk_map = {}
        self.prefix_widgets = []
        self.firmware_widgets = []
        self.resistance_widgets = []

        self._build_ui()
        self.populate_initial_data()
        self._connect_signals()
        self.on_mfg_change()

    def _load_ui_localization(self):
        loc_file = resource_loader.get_ui_localization_file(self.current_lang)
        full_loc = resource_loader.load_json_resource(loc_file) or {}
        self.ui_loc = full_loc.get("repkit_tab", {})
        self.flags_loc = full_loc.get("weapon_editor_tab", {}).get("flags", {})

    def update_language(self, lang):
        print(f"DEBUG: Updating language for {self.__class__.__name__} to {lang}...")
        self.current_lang = lang
        self.df_main, self.df_mfg, self.localization = load_repkit_data(lang)
        
        if self.df_main is None or self.df_mfg is None:
            print(f"DEBUG: load_repkit_data failed for {self.__class__.__name__}")
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
        
        self.perks_group.setTitle(self.ui_loc.get('groups', {}).get('perks', 'Perks'))
        self.prefix_group.setTitle(self.ui_loc.get('groups', {}).get('prefix', 'Prefix'))
        self.resistance_group.setTitle(self.ui_loc.get('groups', {}).get('resistance', 'Resist'))
        self.firmware_group.setTitle(self.ui_loc.get('groups', {}).get('firmware', 'FW'))
        self.legendary_group.setTitle(self.ui_loc.get('groups', {}).get('legendary', 'Legendary'))
        self.universal_group.setTitle(self.ui_loc.get('groups', {}).get('universal', 'Universal'))
        
        self.legendary_clear_btn.setText(self.ui_loc.get('buttons', {}).get('clear', 'Clear'))
        self.universal_clear_btn.setText(self.ui_loc.get('buttons', {}).get('clear', 'Clear'))

        # Refresh Data
        self._populate_flags()
        self.mfg_combo.blockSignals(True)
        # We should also block signal for rarity during population to prevent issues
        self.rarity_combo.blockSignals(True)
        self.populate_initial_data()
        self.mfg_combo.blockSignals(False)
        self.rarity_combo.blockSignals(False)
        self.on_mfg_change()
        print(f"DEBUG: Finished updating language for {self.__class__.__name__}.")

    def _(self, text):
        return self.localization.get(str(text), str(text))

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        main_layout.addWidget(scroll)
        
        container = QWidget()
        scroll.setWidget(container)
        layout = QVBoxLayout(container)

        self._create_output_group(layout)
        self._create_top_controls(layout)
        
        self.perks_group = QGroupBox(self.ui_loc['groups']['perks'])
        perks_layout = QGridLayout(self.perks_group)
        
        self.prefix_group, self.prefix_frame, self.prefix_widgets = self._create_scrollable_radio_group(self.ui_loc['groups']['prefix'])
        self.resistance_group, self.resistance_frame, self.resistance_widgets = self._create_scrollable_radio_group(self.ui_loc['groups']['resistance'])
        self.firmware_group, self.firmware_frame, self.firmware_widgets = self._create_scrollable_radio_group(self.ui_loc['groups']['firmware'])
        
        perks_layout.addWidget(self.prefix_group, 0, 0)
        perks_layout.addWidget(self.resistance_group, 0, 1)
        perks_layout.addWidget(self.firmware_group, 0, 2)
        
        self.legendary_group = self._create_list_perk_group(self.ui_loc['groups']['legendary'], use_multiplier=False)
        self.universal_group = self._create_list_perk_group(self.ui_loc['groups']['universal'], use_multiplier=True)
        
        perks_layout.addWidget(self.legendary_group, 1, 0, 1, 3)
        perks_layout.addWidget(self.universal_group, 2, 0, 1, 3)
        
        layout.addWidget(self.perks_group)

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

        self.copy_raw_btn.clicked.connect(lambda: self._copy_to_clipboard(self.raw_output_edit))
        self.copy_b85_btn.clicked.connect(lambda: self._copy_to_clipboard(self.b85_output_edit))
        
        layout.addWidget(self.output_group)

    def _create_top_controls(self, layout):
        self.base_attrs_group = QGroupBox(self.ui_loc['groups']['base_attrs'])
        controls_layout = QHBoxLayout(self.base_attrs_group)

        self.mfg_combo = QComboBox()
        self.level_edit = QLineEdit("50")
        self.level_edit.setFixedWidth(100)
        self.rarity_combo = QComboBox()
        self.rarity_combo.setFixedWidth(300)

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
    
    def _create_scrollable_radio_group(self, title):
        group_box=QGroupBox(title); scroll_area=QScrollArea(); scroll_area.setWidgetResizable(True); container=QWidget()
        scroll_area.setMinimumHeight(200)
        layout=QVBoxLayout(container); scroll_area.setWidget(container); main_layout=QVBoxLayout(group_box); main_layout.addWidget(scroll_area)
        return group_box, layout, []

    def _create_list_perk_group(self, title, use_multiplier=False):
        group = QGroupBox(title); layout = QGridLayout(group)
        avail = QListWidget(); sel = QListWidget()
        avail.setMinimumHeight(200); sel.setMinimumHeight(200)
        avail.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        sel.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)

        btn_layout = QVBoxLayout()
        
        multiplier_box = None
        if use_multiplier:
            multiplier_box = QSpinBox()
            multiplier_box.setRange(1, 999)
            multiplier_box.setValue(1)
            btn_layout.addWidget(multiplier_box)
            
        move_btn = QPushButton("»")
        remove_btn = QPushButton("«")
        clear_btn = QPushButton(self.ui_loc['buttons']['clear'])
        
        btn_layout.addWidget(move_btn)
        btn_layout.addWidget(remove_btn)
        btn_layout.addWidget(clear_btn)
        btn_layout.addStretch()
        
        layout.addWidget(avail, 0, 0); layout.addLayout(btn_layout, 0, 1); layout.addWidget(sel, 0, 2)
        
        if '传奇' in title or 'Legendary' in title:
            prefix = 'legendary'
        else:
            prefix = 'universal'
            
        setattr(self, f"{prefix}_avail_list", avail)
        setattr(self, f"{prefix}_sel_list", sel)
        setattr(self, f"{prefix}_clear_btn", clear_btn)
        if multiplier_box:
            setattr(self, f"{prefix}_multiplier", multiplier_box)

        move_btn.clicked.connect(lambda: self._move_selected_items(avail, sel, multiplier_box))
        remove_btn.clicked.connect(lambda: self._remove_selected_items(sel))
        clear_btn.clicked.connect(lambda: self._clear_list(sel))
        
        return group

    def _connect_signals(self):
        self.mfg_combo.currentTextChanged.connect(self.on_mfg_change)
        self.level_edit.textChanged.connect(self.rebuild_output)
        self.rarity_combo.currentTextChanged.connect(self.rebuild_output)
        self.add_to_pack_btn.clicked.connect(self._add_to_backpack)
        
        self.legendary_avail_list.model().rowsInserted.connect(self.rebuild_output)
        self.legendary_avail_list.model().rowsRemoved.connect(self.rebuild_output)
        self.universal_avail_list.model().rowsInserted.connect(self.rebuild_output)
        self.universal_avail_list.model().rowsRemoved.connect(self.rebuild_output)

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

        df_243 = self.df_main[self.df_main['Repkit_perk_main_ID'] == 243]
        
        self.prefix_map = self._get_datamap_from_df(df_243, 'Perfix')
        self._populate_radio_buttons(self.prefix_frame, self.prefix_map, self.prefix_widgets)

        self.firmware_map = self._get_datamap_from_df(df_243, 'Firmware')
        self._populate_radio_buttons(self.firmware_frame, self.firmware_map, self.firmware_widgets)

        self.resistance_map = self._get_datamap_from_df(df_243, ['Resistance', 'Immunity'])
        self._populate_radio_buttons(self.resistance_frame, self.resistance_map, self.resistance_widgets)

        self.universal_perk_map = self._populate_listbox(self.universal_avail_list, df_243, 'Perk')

    def on_mfg_change(self, *args):
        if not self.mfg_combo.currentText(): return
        mfg_id = int(self.mfg_combo.currentText().split(' - ')[-1])

        self.rarity_combo.blockSignals(True)
        self.rarity_combo.clear()
        self.rarity_map.clear()
        rarities_df = self.df_mfg[(self.df_mfg['Manufacturer ID'] == mfg_id) & (self.df_mfg['Part_type'] == 'Rarity')]
        for _, row in rarities_df.iterrows():
            desc = f" - {row['Description']}" if pd.notna(row['Description']) and row['Description'] else ""
            display_text = f"{self._(row['Stat'])}{desc}"
            self.rarity_combo.addItem(display_text, row['Part_ID'])
            self.rarity_map[display_text] = row['Part_ID']
        self.rarity_combo.blockSignals(False)
        self.rarity_combo.setFixedWidth(300)  # Re-apply width after populating

        self.legendary_avail_list.clear()
        self.legendary_perk_map.clear()
        legendary_perks_df = self.df_mfg[self.df_mfg['Part_type'] == 'Legendary Perk'].copy()
        legendary_perks_df['sort_key'] = legendary_perks_df['Manufacturer ID'].apply(lambda x: 0 if x == mfg_id else 1)
        legendary_perks_df = legendary_perks_df.sort_values(by=['sort_key', 'Manufacturer ID', 'Part_ID'])

        for _, row in legendary_perks_df.iterrows():
            mfg_name = self._get_mfg_name(row['Manufacturer ID'])
            display_text = f"{mfg_name} - {row['Stat']} - {row['Description']}"
            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, (row['Part_ID'], row['Manufacturer ID']))
            self.legendary_avail_list.addItem(item)
            self.legendary_perk_map[display_text] = { "id": row['Part_ID'], "mfg": row['Manufacturer ID'] }
            if row['Manufacturer ID'] != mfg_id:
                item.setForeground(QColor('#aaa'))

        self.rebuild_output()

    def rebuild_output(self, *args):
        main_parts = []
        skill_parts = []
        secondary_skill_parts = {}

        mfg_str = self.mfg_combo.currentText()
        if not mfg_str: return
        current_mfg_id = int(mfg_str.split(' - ')[-1])
        try:
            level = int(self.level_edit.text())
            if not 1 <= level <= 99: level = 50
        except ValueError:
            level = 50
        main_parts.append(f"{current_mfg_id}, 0, 1, {level}| 2, 307||")

        rarity_id = self.rarity_combo.currentData()
        if rarity_id: skill_parts.append(f"{{{rarity_id}}}")

        model_row = self.df_mfg[(self.df_mfg['Manufacturer ID'] == current_mfg_id) & (self.df_mfg['Part_type'] == 'Model')]
        if not model_row.empty: skill_parts.append(f"{{{model_row.iloc[0]['Part_ID']}}}")

        other_mfg_perks = {}
        for i in range(self.legendary_sel_list.count()):
            item = self.legendary_sel_list.item(i)
            # Handle potential count, though not explicitly requested
            count = 1
            match = re.match(r"\((\d+)\)\s+(.*)", item.text())
            if match:
                count = int(match.group(1))
            
            perk_id, perk_mfg = item.data(Qt.ItemDataRole.UserRole)
            for _ in range(count):
                if perk_mfg == current_mfg_id:
                    skill_parts.append(f"{{{perk_id}}}")
                else:
                    if perk_mfg not in other_mfg_perks: other_mfg_perks[perk_mfg] = []
                    other_mfg_perks[perk_mfg].append(perk_id)
        
        for mfg_id, ids in other_mfg_perks.items():
            sorted_ids = sorted(ids)
            skill_parts.append(f"{{{mfg_id}:[{' '.join(map(str, sorted_ids))}]}}" if len(ids) > 1 else f"{{{mfg_id}:{ids[0]}}}")

        for widgets in [self.prefix_widgets, self.firmware_widgets, self.resistance_widgets]:
            for rb in widgets:
                if rb.isChecked() and rb.property("part_id"):
                    part_id = rb.property("part_id")
                    secondary_skill_parts.setdefault(243, []).append(part_id)
                    
                    # Logic for Model Plus based on Resistance/Immunity
                    combustion_ids = [24, 50, 29, 44]
                    radiation_ids = [23, 47, 28, 43]
                    corrosive_ids = [26, 51, 31, 46]
                    shock_ids = [22, 49, 27, 42]
                    cryo_ids = [25, 48, 30, 45]
                    
                    if part_id in combustion_ids:
                        secondary_skill_parts.setdefault(243, []).append(98)
                    elif part_id in radiation_ids:
                        secondary_skill_parts.setdefault(243, []).append(99)
                    elif part_id in corrosive_ids:
                        secondary_skill_parts.setdefault(243, []).append(100)
                    elif part_id in shock_ids:
                        secondary_skill_parts.setdefault(243, []).append(101)
                    elif part_id in cryo_ids:
                        secondary_skill_parts.setdefault(243, []).append(102)

        for i in range(self.universal_sel_list.count()):
            item = self.universal_sel_list.item(i)
            # Handle count
            count = 1
            match = re.match(r"\((\d+)\)\s+(.*)", item.text())
            if match:
                count = int(match.group(1))
            
            perk_id = item.data(Qt.ItemDataRole.UserRole)
            if perk_id: 
                for _ in range(count):
                    secondary_skill_parts.setdefault(243, []).append(perk_id)

        for mfg_id, ids in secondary_skill_parts.items():
            sorted_ids = sorted(ids)
            skill_parts.append(f"{{{mfg_id}:[{' '.join(map(str, sorted_ids))}]}}" if len(ids) > 1 else f"{{{mfg_id}:{ids[0]}}}")
        
        final_string = " ".join(main_parts) + " " + " ".join(skill_parts)
        final_string = final_string.strip() + " |"
        self.raw_output_edit.setText(final_string)
        
        encoded_serial, err = b_encoder.encode_to_base85(final_string)
        if err:
            self.b85_output_edit.setText(f"错误: {err}")
        else:
            self.b85_output_edit.setText(encoded_serial)

    def _populate_radio_buttons(self, frame, data_map, widget_list):
        while frame.count():
            child = frame.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        widget_list.clear()
        none_rb = QRadioButton(self.ui_loc['misc']['none'])
        none_rb.setChecked(True)
        none_rb.toggled.connect(self.rebuild_output)
        frame.addWidget(none_rb)
        
        for text, part_id in data_map.items():
            rb = QRadioButton(text)
            rb.setProperty("part_id", part_id)
            rb.toggled.connect(self.rebuild_output)
            frame.addWidget(rb)
            widget_list.append(rb)
        frame.addStretch()

    def _populate_listbox(self, listbox, df, part_type):
        listbox.clear()
        item_map = {}
        items_df = df[df['Part_type'] == part_type]
        for _, row in items_df.iterrows():
            name = self._(row['Stat'])
            desc = row['Description'] if pd.notna(row['Description']) else ''
            display_text = f"{name} - {desc} [{row['Part_ID']}]" if desc else f"{name} [{row['Part_ID']}]"
            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, row['Part_ID'])
            listbox.addItem(item)
            item_map[display_text] = row['Part_ID']
        return item_map

    def _get_datamap_from_df(self, df, part_type, use_desc=True):
        item_map = {}
        if isinstance(part_type, str): part_type = [part_type]
        items_df = df[df['Part_type'].isin(part_type)]
        for _, row in items_df.iterrows():
            stat = self._(row['Stat'])
            desc = row['Description'] if use_desc and pd.notna(row['Description']) and row['Description'] else ''
            display_text = f"{stat} - {desc}" if desc else f"{stat}"
            item_map[display_text.strip(" -")] = row['Part_ID']
        return item_map

    def _move_selected_items(self, src, dest, multiplier_box=None):
        count_val = multiplier_box.value() if multiplier_box else 1
        for item in src.selectedItems():
             base_text = item.text()
             
             existing_item = None
             for i in range(dest.count()):
                sel_item = dest.item(i)
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
                dest.addItem(new_item)
        self.rebuild_output()

    def _remove_selected_items(self, list_widget):
        for item in list_widget.selectedItems():
            list_widget.takeItem(list_widget.row(item))
        self.rebuild_output()
        
    def _clear_list(self, list_widget):
        list_widget.clear()
        self.rebuild_output()

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
                break

    def _copy_to_clipboard(self, line_edit):
        QApplication.clipboard().setText(line_edit.text())
        QMessageBox.information(self, self.ui_loc['dialogs']['success'], self.ui_loc['dialogs']['copied'])
        
    def _add_to_backpack(self):
        serial = self.b85_output_edit.text()
        if not serial or "错误" in serial:
            QMessageBox.warning(self, self.ui_loc['dialogs']['no_valid_code'], self.ui_loc['dialogs']['gen_first'])
            return
        self.add_to_backpack_requested.emit(serial, self.flag_combo.currentText().split(" ")[0])
