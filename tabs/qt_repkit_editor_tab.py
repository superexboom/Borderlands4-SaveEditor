import pandas as pd
from functools import lru_cache
import re

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QComboBox, QRadioButton, QListWidget, QListWidgetItem,
    QScrollArea, QMessageBox, QSpinBox
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QColor

from core import b_encoder
from core import resource_loader
from tabs.qt_catalog_picker import ContainedWheelListWidget, ContainedWheelScrollArea
from tabs.qt_serial_import import (
    SerialSourceBar, build_header, choose_backpack_item, decode_base85,
    parse_components, prompt_base85, select_flag_value, source_texts, split_decoded,
)
from core import lookup
from core import bl4_functions as bl4f

@lru_cache(maxsize=None)
def load_repkit_data(lang='zh-CN'):
    """使用资源加载器加载修复套件数据。"""
    try:
        df_main = resource_loader.load_localized_csv_resource('repkit/repkit_main_perk.csv', lang)
        df_mfg = resource_loader.load_localized_csv_resource('repkit/repkit_manufacturer_perk.csv', lang)
        
        localization = {}
        if lang == 'zh-CN':
            localization = resource_loader.load_json_resource('repkit/Repkit_localization_zh-CN.json')
            if not localization:
                print("警告: 无法加载Repkit_localization_zh-CN.json")
                localization = {}
            
        return df_main, df_mfg, localization
    except Exception as e:
        full_loc = resource_loader.load_json_resource(resource_loader.get_ui_localization_file(lang)) or {}
        dialogs = full_loc.get('repkit_tab', {}).get('dialogs', {})
        QMessageBox.critical(
            None,
            dialogs.get('load_fail_title', "加载数据失败"),
            dialogs.get('parse_error', "无法加载或解析修复套件数据文件: {error}").format(error=e),
        )
        return None, None, None

class QtRepkitEditorTab(QWidget):
    add_to_backpack_requested = pyqtSignal(str, str)

    def __init__(self, main_app=None, parent=None):
        super().__init__(parent)
        self.main_app = main_app
        self.current_lang = 'zh-CN'
        self._character_level = "50"
        self._is_loading = False
        self._imported = False
        self._import_header = None
        self._import_unknown_tokens = []
        self._import_source_name = ""
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

    def update_language(self, lang):
        restore_serial = self.b85_output_edit.text() if getattr(self, '_imported', False) else ""
        restore_source = self._import_source_name
        restore_flag = self.flag_combo.currentText().split(" ")[0] if hasattr(self, 'flag_combo') else "3"
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
        self._update_source_bar_texts()

        # Refresh Data
        self._populate_flags()
        self.mfg_combo.blockSignals(True)
        # We should also block signal for rarity during population to prevent issues
        self.rarity_combo.blockSignals(True)
        self.populate_initial_data()
        self.mfg_combo.blockSignals(False)
        self.rarity_combo.blockSignals(False)
        self.on_mfg_change()
        if restore_serial:
            self._load_serial_copy(restore_serial, restore_source, restore_flag)
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

        self.source_bar = SerialSourceBar(
            new_text=self._source_text('new'),
            backpack_text=self._source_text('backpack'),
            base85_text=self._source_text('base85'),
            reset_text=self._source_text('reset'),
        )
        self.source_bar.backpack_requested.connect(self._import_from_backpack)
        self.source_bar.base85_requested.connect(self._import_from_base85)
        self.source_bar.reset_requested.connect(self._reset_import_source)
        layout.addWidget(self.source_bar)

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
        self.level_edit = QLineEdit(self._character_level)
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
        group_box=QGroupBox(title); scroll_area=ContainedWheelScrollArea(); scroll_area.setWidgetResizable(True); container=QWidget()
        scroll_area.setMinimumHeight(200)
        layout=QVBoxLayout(container); scroll_area.setWidget(container); main_layout=QVBoxLayout(group_box); main_layout.addWidget(scroll_area)
        return group_box, layout, []

    def _create_list_perk_group(self, title, use_multiplier=False):
        group = QGroupBox(title); layout = QGridLayout(group)
        avail = ContainedWheelListWidget(); sel = ContainedWheelListWidget()
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
        if self._is_loading:
            return
        main_parts = []
        skill_parts = []
        secondary_skill_parts = {}

        mfg_str = self.mfg_combo.currentText()
        if not mfg_str: return
        current_mfg_id = int(mfg_str.split(' - ')[-1])
        try:
            level = int(self.level_edit.text())
            if not 1 <= level <= 99: level = int(self._character_level)
        except ValueError:
            level = int(self._character_level)
        if self._imported and self._import_header:
            main_parts.append(f"{build_header(self._import_header, level=level)}||")
        else:
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

        if self._imported:
            skill_parts.extend(self._import_unknown_tokens)
        
        final_string = " ".join(main_parts) + " " + " ".join(skill_parts)
        final_string = final_string.strip() + " |"
        self.raw_output_edit.setText(final_string)
        
        encoded_serial, err = b_encoder.encode_to_base85(final_string)
        self._encode_error = bool(err)
        if err:
            self.b85_output_edit.setText(f"{self.ui_loc.get('dialogs', {}).get('error', 'Error')}: {err}")
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
        
        flags_map = resource_loader.get_flag_labels(self.current_lang)
        flag_values = [flags_map[k] for k in ("1", "3", "5", "17", "33", "65", "129")]
        self.flag_combo.addItems(flag_values)
        for i in range(self.flag_combo.count()):
            if flags_map["3"] == self.flag_combo.itemText(i):
                self.flag_combo.setCurrentIndex(i)
                break

    def _source_text(self, key):
        return source_texts(self.current_lang)[{'new': 'new_source', 'copy': 'imported'}.get(key, key)]

    def _update_source_bar_texts(self):
        if not hasattr(self, 'source_bar'):
            return
        self.source_bar.backpack_btn.setText(self._source_text('backpack'))
        self.source_bar.base85_btn.setText(self._source_text('base85'))
        self.source_bar.reset_btn.setText(self._source_text('reset'))
        text = self._source_text('copy').format(name=self._import_source_name) if self._imported else self._source_text('new')
        self.source_bar.set_source(text, imported=self._imported)

    def _import_from_backpack(self):
        texts = source_texts(self.current_lang)
        if not self.main_app or not hasattr(self.main_app, 'get_items_snapshot'):
            QMessageBox.warning(self, texts['import_error'], texts['no_save'])
            return
        item = choose_backpack_item(
            self,
            self.main_app.get_items_snapshot(),
            lambda candidate: candidate.get('container') == 'Backpack'
            and (candidate.get('type_en') == 'Repkit' or candidate.get('id') in self.mfg_ids),
            title=texts['backpack_title'],
            search_placeholder=texts['search'],
        )
        if item:
            self._load_serial_copy(item.get('serial', ''), item.get('name') or 'Repkit', item.get('state_flags'))

    def _import_from_base85(self):
        texts = source_texts(self.current_lang)
        serial = prompt_base85(self, title=texts['base85_title'], label=texts['base85_label'])
        if serial:
            self._load_serial_copy(serial, 'Base85')

    def open_item_serial(self, item: dict):
        """公开入口：从 YAML 编辑器/物品快照跳转加载一件物品。类型不符时抛 ValueError。"""
        flags = item.get('state_flags')
        try:
            flags = int(str(flags).strip()) if str(flags).strip() else None
        except ValueError:
            flags = None
        self._load_serial_copy(item.get('serial', ''), source_name=item.get('name', 'Backpack'),
                               state_flags=flags)

    def _load_serial_copy(self, serial, source_name='Base85', state_flags=None):
        texts = source_texts(self.current_lang)
        try:
            decoded = decode_base85(serial)
            header = split_decoded(decoded)
            if header['mfg_id'] not in self.mfg_ids:
                raise ValueError(texts['wrong_type'])
            component = header['component']
            self._is_loading = True
            self._imported = True
            self._import_header = header
            self._import_unknown_tokens = []
            self._import_source_name = source_name

            index = self.mfg_combo.findText(str(header['mfg_id']), Qt.MatchFlag.MatchEndsWith)
            if index < 0:
                raise ValueError(texts['wrong_type'])
            self.mfg_combo.setEnabled(True)
            self.mfg_combo.blockSignals(True)
            self.mfg_combo.setCurrentIndex(index)
            self.mfg_combo.blockSignals(False)
            self.on_mfg_change()
            self.mfg_combo.setEnabled(False)
            self.level_edit.setText(str(header['level']))
            self._clear_import_widgets()
            self._apply_imported_components(component)
            self._set_flag_value(state_flags)
            self.source_bar.set_source(self._source_text('copy').format(name=source_name), imported=True)
        except Exception as exc:
            self._reset_import_source()
            QMessageBox.warning(self, texts['import_error'], str(exc))
            return False
        finally:
            self._is_loading = False
        self.rebuild_output()
        return True

    def _clear_import_widgets(self):
        for group in (self.prefix_group, self.firmware_group, self.resistance_group):
            radios = group.findChildren(QRadioButton)
            none_radio = next((radio for radio in radios if radio.property('part_id') is None), None)
            if none_radio:
                none_radio.setChecked(True)
        self.legendary_sel_list.clear()
        self.universal_sel_list.clear()

    def _apply_imported_components(self, component):
        current_mfg = self._current_mfg_id()
        rarity_ids = {int(self.rarity_combo.itemData(i)) for i in range(self.rarity_combo.count()) if self.rarity_combo.itemData(i) is not None}
        model_rows = self.df_mfg[(self.df_mfg['Manufacturer ID'] == current_mfg) & (self.df_mfg['Part_type'] == 'Model')]
        model_id = int(model_rows.iloc[0]['Part_ID']) if not model_rows.empty else None
        secondary = {}
        for category, widgets in (
            ('prefix', self.prefix_widgets),
            ('firmware', self.firmware_widgets),
            ('resistance', self.resistance_widgets),
        ):
            secondary.update({int(rb.property('part_id')): (rb, category) for rb in widgets if rb.property('part_id') is not None})
        universal = self._list_lookup(self.universal_avail_list)
        legendary = self._legendary_lookup()
        derived = {98, 99, 100, 101, 102}
        selected_radio = {}
        pending_derived = []
        extra_secondary = []

        for token in parse_components(component):
            kind = token['type']
            if kind == 'simple':
                part_id = token['id']
                if part_id in rarity_ids:
                    self._set_combo_data(self.rarity_combo, part_id)
                elif part_id == model_id:
                    continue
                elif (part_id, current_mfg) in legendary:
                    self._stack_selected(self.legendary_sel_list, legendary[(part_id, current_mfg)])
                else:
                    self._import_unknown_tokens.append(f"{{{part_id}}}")
                continue

            if kind in ('single', 'group'):
                parent = token['id']
                children = [token['value']] if kind == 'single' else token['children']
                unknown = []
                for child in children:
                    if parent == 243 and child in derived:
                        pending_derived.append(child)
                        continue
                    if parent == 243 and child in secondary:
                        radio, category = secondary[child]
                        if category in selected_radio:
                            extra_secondary.append(selected_radio[category])
                        selected_radio[category] = child
                        radio.setChecked(True)
                    elif parent == 243 and child in universal:
                        self._stack_selected(self.universal_sel_list, universal[child])
                    elif (child, parent) in legendary:
                        self._stack_selected(self.legendary_sel_list, legendary[(child, parent)])
                    else:
                        unknown.append(child)
                if unknown:
                    self._import_unknown_tokens.append(self._format_group(parent, unknown))
                continue

            self._import_unknown_tokens.append(f'"{token["value"]}"')

        generated_derived = []
        for rb in self.resistance_widgets:
            if rb.isChecked():
                generated = self._derived_model_plus(int(rb.property('part_id')))
                if generated is not None:
                    generated_derived.append(generated)
        for child in pending_derived:
            if child in generated_derived:
                generated_derived.remove(child)
            else:
                extra_secondary.append(child)
        if extra_secondary:
            self._import_unknown_tokens.append(self._format_group(243, extra_secondary))

    def _reset_import_source(self):
        self._is_loading = True
        self._imported = False
        self._import_header = None
        self._import_unknown_tokens = []
        self._import_source_name = ""
        if hasattr(self, 'mfg_combo'):
            self.mfg_combo.setEnabled(True)
            self.level_edit.setText(self._character_level)
            self.on_mfg_change()
            self._clear_import_widgets()
            self._set_flag_value(None)
        if hasattr(self, 'source_bar'):
            self.source_bar.set_source(self._source_text('new'), imported=False)
        self._is_loading = False
        if hasattr(self, 'mfg_combo'):
            self.rebuild_output()

    def _current_mfg_id(self):
        return int(self.mfg_combo.currentText().split(' - ')[-1])

    @staticmethod
    def _set_combo_data(combo, value):
        for index in range(combo.count()):
            if combo.itemData(index) is not None and int(combo.itemData(index)) == int(value):
                combo.setCurrentIndex(index)
                return True
        return False

    @staticmethod
    def _list_lookup(list_widget):
        return {int(list_widget.item(i).data(Qt.ItemDataRole.UserRole)): list_widget.item(i) for i in range(list_widget.count())}

    def _legendary_lookup(self):
        result = {}
        for index in range(self.legendary_avail_list.count()):
            item = self.legendary_avail_list.item(index)
            part_id, mfg_id = item.data(Qt.ItemDataRole.UserRole)
            result[(int(part_id), int(mfg_id))] = item
        return result

    @staticmethod
    def _stack_selected(dest, source):
        data = source.data(Qt.ItemDataRole.UserRole)
        for index in range(dest.count()):
            current = dest.item(index)
            if current.data(Qt.ItemDataRole.UserRole) == data:
                match = re.match(r"\((\d+)\)\s+(.*)", current.text())
                current.setText(f"({int(match.group(1)) + 1 if match else 2}) {match.group(2) if match else current.text()}")
                return
        dest.addItem(source.clone())

    @staticmethod
    def _format_group(parent, children):
        return f"{{{parent}:{children[0]}}}" if len(children) == 1 else f"{{{parent}:[{' '.join(map(str, children))}]}}"

    @staticmethod
    def _derived_model_plus(part_id):
        for values, derived in (
            ({24, 50, 29, 44}, 98), ({23, 47, 28, 43}, 99),
            ({26, 51, 31, 46}, 100), ({22, 49, 27, 42}, 101),
            ({25, 48, 30, 45}, 102),
        ):
            if part_id in values:
                return derived
        return None

    def _set_flag_value(self, value):
        select_flag_value(self.flag_combo, value)

    def _copy_to_clipboard(self, line_edit):
        QApplication.clipboard().setText(line_edit.text())
        QMessageBox.information(self, self.ui_loc['dialogs']['success'], self.ui_loc['dialogs']['copied'])
        
    def _add_to_backpack(self):
        serial = self.b85_output_edit.text()
        if not serial or getattr(self, '_encode_error', False):
            QMessageBox.warning(self, self.ui_loc['dialogs']['no_valid_code'], self.ui_loc['dialogs']['gen_first'])
            return
        self.add_to_backpack_requested.emit(serial, self.flag_combo.currentText().split(" ")[0])

    def set_character_level(self, level: str):
        """设置角色等级，更新默认等级显示。"""
        self._character_level = level if level else "50"
        if hasattr(self, 'level_edit') and not self._imported:
            self.level_edit.setText(self._character_level)
