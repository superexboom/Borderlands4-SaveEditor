import pandas as pd
from functools import lru_cache
import random
import re

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QComboBox, QRadioButton, QCheckBox, QListWidget, QListWidgetItem,
    QScrollArea, QMessageBox, QSpinBox
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QColor

from core import b_encoder
from core import resource_loader
import lookup
from core import bl4_functions as bl4f

@lru_cache(maxsize=None)
def load_grenade_data(lang='zh-CN'):
    try:
        suffix = "_EN" if lang in ['en-US', 'ru', 'ua'] else ""
        df_main = pd.read_csv(resource_loader.get_grenade_data_path(f'grenade_main_perk{suffix}.csv'))
        df_mfg = pd.read_csv(resource_loader.get_grenade_data_path(f'manufacturer_rarity_perk{suffix}.csv'))
        
        # Load localization json if available, mainly for Chinese
        localization = {}
        if lang == 'zh-CN':
            localization = resource_loader.load_json_resource('grenade/Grenade_localization_zh-CN.json') or {}
            
        return df_main, df_mfg, localization
    except Exception as e:
        print(f"Error loading grenade data ({lang}): {e}")
        return None, None, None

class QtGrenadeEditorTab(QWidget):
    add_to_backpack_requested = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_lang = 'zh-CN'
        self.df_main, self.df_mfg, self.localization = load_grenade_data(self.current_lang)
        
        self._load_ui_localization()

        if self.df_main is None:
            layout = QVBoxLayout(self); layout.addWidget(QLabel(self.ui_loc.get('dialogs', {}).get('load_error', "错误: 手雷数据(grenade data)无法加载。"))); return

        self.mfg_ids = [263, 267, 270, 272, 278, 291, 298, 311]
        self.mfg_perk_widgets = []
        self.element_widgets = []
        self.firmware_widgets = []
        
        self._build_ui()
        self.populate_initial_data()
        self._connect_signals()
        self.on_mfg_change()

    def _load_ui_localization(self):
        loc_file = resource_loader.get_ui_localization_file(self.current_lang)
        full_loc = resource_loader.load_json_resource(loc_file) or {}
        self.ui_loc = full_loc.get("grenade_tab", {})
        self.flags_loc = full_loc.get("weapon_editor_tab", {}).get("flags", {})

    def update_language(self, lang):
        print(f"DEBUG: Updating language for {self.__class__.__name__} to {lang}...")
        self.current_lang = lang
        self.df_main, self.df_mfg, self.localization = load_grenade_data(lang)
        
        if self.df_main is None:
            print(f"DEBUG: load_grenade_data failed for {self.__class__.__name__}")
            return

        self._load_ui_localization()
        
        if not self.ui_loc:
            print(f"DEBUG: UI localization missing for {self.__class__.__name__}")
            return
        
        # Refresh UI Texts
        self.output_group.setTitle(self.ui_loc.get('groups', {}).get('output', 'Output'))
        self.copy_raw_btn.setText(self.ui_loc.get('buttons', {}).get('copy', 'Copy'))
        self.copy_b85_btn.setText(self.ui_loc.get('buttons', {}).get('copy', 'Copy'))
        self.add_to_pack_btn.setText(self.ui_loc.get('buttons', {}).get('add_to_backpack', 'Add'))
        self.raw_label.setText(self.ui_loc.get('labels', {}).get('raw', 'Raw'))
        self.b85_label.setText(self.ui_loc.get('labels', {}).get('base85', 'Base85'))
        
        self.base_attrs_group.setTitle(self.ui_loc.get('groups', {}).get('base_attrs', 'Attributes'))
        self.mfg_label.setText(self.ui_loc.get('labels', {}).get('manufacturer', 'Mfg'))
        self.level_label.setText(self.ui_loc.get('labels', {}).get('level', 'Level'))
        self.rarity_label.setText(self.ui_loc.get('labels', {}).get('rarity', 'Rarity'))
        
        self.perks_group.setTitle(self.ui_loc.get('groups', {}).get('perks', 'Perks'))
        self.mfg_perk_group.setTitle(self.ui_loc.get('groups', {}).get('mfg_perks', 'Mfg Perks'))
        self.element_group.setTitle(self.ui_loc.get('groups', {}).get('element', 'Element'))
        self.firmware_group.setTitle(self.ui_loc.get('groups', {}).get('firmware', 'FW'))
        self.legendary_group.setTitle(self.ui_loc.get('groups', {}).get('legendary', 'Legendary'))
        self.universal_group.setTitle(self.ui_loc.get('groups', {}).get('universal', 'Universal'))
        
        self.legendary_clear_btn.setText(self.ui_loc.get('buttons', {}).get('clear', 'Clear'))
        self.universal_clear_btn.setText(self.ui_loc.get('buttons', {}).get('clear', 'Clear'))
        
        self._populate_flags()

        # Refresh Data
        self.mfg_combo.blockSignals(True)
        self.populate_initial_data()
        self.mfg_combo.blockSignals(False)
        self.on_mfg_change()
        print(f"DEBUG: Finished updating language for {self.__class__.__name__}.")

    def _(self, text): return self.localization.get(str(text), str(text))

    def _build_ui(self):
        main_layout = QVBoxLayout(self); scroll = QScrollArea(); scroll.setWidgetResizable(True); main_layout.addWidget(scroll)
        container = QWidget(); scroll.setWidget(container); layout = QVBoxLayout(container)
        self._create_output_group(layout); self._create_top_controls(layout)
        
        self.perks_group = QGroupBox(self.ui_loc['groups']['perks']); perks_layout = QGridLayout(self.perks_group)
        self.mfg_perk_group, self.mfg_perk_frame, self.mfg_perk_widgets = self._create_scrollable_checkbox_group(self.ui_loc['groups']['mfg_perks'])
        self.element_group, self.element_frame, self.element_widgets = self._create_scrollable_radio_group(self.ui_loc['groups']['element'])
        self.firmware_group, self.firmware_frame, self.firmware_widgets = self._create_scrollable_radio_group(self.ui_loc['groups']['firmware'])
        perks_layout.addWidget(self.mfg_perk_group, 0, 0); perks_layout.addWidget(self.element_group, 0, 1); perks_layout.addWidget(self.firmware_group, 0, 2)
        self.legendary_group = self._create_list_perk_group(self.ui_loc['groups']['legendary'], use_multiplier=False)
        self.universal_group = self._create_list_perk_group(self.ui_loc['groups']['universal'], use_multiplier=True)
        perks_layout.addWidget(self.legendary_group, 1, 0, 1, 3); perks_layout.addWidget(self.universal_group, 2, 0, 1, 3)
        layout.addWidget(self.perks_group)

    def _create_output_group(self, layout):
        self.output_group = QGroupBox(self.ui_loc['groups']['output']); grid = QGridLayout(self.output_group)
        self.raw_output_edit = QLineEdit(); self.raw_output_edit.setReadOnly(True)
        self.b85_output_edit = QLineEdit(); self.b85_output_edit.setReadOnly(True)
        self.copy_raw_btn = QPushButton(self.ui_loc['buttons']['copy'])
        self.copy_b85_btn = QPushButton(self.ui_loc['buttons']['copy'])
        self.add_to_pack_btn = QPushButton(self.ui_loc['buttons']['add_to_backpack'])
        
        self.flag_combo = QComboBox()
        self._populate_flags()
            
        self.raw_label = QLabel(self.ui_loc['labels']['raw'])
        self.b85_label = QLabel(self.ui_loc['labels']['base85'])
        grid.addWidget(self.raw_label, 0, 0); grid.addWidget(self.raw_output_edit, 0, 1); grid.addWidget(self.copy_raw_btn, 0, 2)
        grid.addWidget(self.b85_label, 1, 0); grid.addWidget(self.b85_output_edit, 1, 1); grid.addWidget(self.copy_b85_btn, 1, 2)
        grid.addWidget(self.flag_combo, 1, 3); grid.addWidget(self.add_to_pack_btn, 1, 4)
        self.copy_raw_btn.clicked.connect(lambda: self._copy_to_clipboard(self.raw_output_edit))
        self.copy_b85_btn.clicked.connect(lambda: self._copy_to_clipboard(self.b85_output_edit))
        layout.addWidget(self.output_group)

    def _create_top_controls(self, layout):
        self.base_attrs_group = QGroupBox(self.ui_loc['groups']['base_attrs']); controls_layout = QHBoxLayout(self.base_attrs_group)
        self.mfg_combo = QComboBox(); self.level_edit = QLineEdit("50"); self.rarity_combo = QComboBox()
        self.level_edit.setFixedWidth(100)
        self.rarity_combo.setFixedWidth(300)
        
        self.mfg_label = QLabel(self.ui_loc['labels']['manufacturer'])
        self.level_label = QLabel(self.ui_loc['labels']['level'])
        self.rarity_label = QLabel(self.ui_loc['labels']['rarity'])
        
        controls_layout.addWidget(self.mfg_label); controls_layout.addWidget(self.mfg_combo)
        controls_layout.addWidget(self.level_label); controls_layout.addWidget(self.level_edit)
        controls_layout.addWidget(self.rarity_label); controls_layout.addWidget(self.rarity_combo)
        controls_layout.addStretch(); layout.addWidget(self.base_attrs_group)

    def _create_scrollable_radio_group(self, title): return self._create_scrollable_group(title, QRadioButton)
    def _create_scrollable_checkbox_group(self, title): return self._create_scrollable_group(title, QCheckBox)

    def _create_scrollable_group(self, title, widget_type):
        group_box=QGroupBox(title); scroll_area=QScrollArea(); scroll_area.setWidgetResizable(True); container=QWidget()
        scroll_area.setMinimumHeight(200)
        layout=QVBoxLayout(container); scroll_area.setWidget(container); main_layout=QVBoxLayout(group_box); main_layout.addWidget(scroll_area)
        return group_box, layout, []

    def _create_list_perk_group(self, title, single_select=False, use_multiplier=False):
        group=QGroupBox(title); layout=QGridLayout(group)
        avail, sel = QListWidget(), QListWidget()
        avail.setMinimumHeight(200)
        sel.setMinimumHeight(200)
        if not single_select:
            avail.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
            sel.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        else:
            sel.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        
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
        
        # Determine prefix based on key keywords, to support multiple languages
        # '传奇' or 'Legendary' -> legendary
        # '通用' or 'Universal' -> universal
        if '传奇' in title or 'Legendary' in title:
            prefix = 'legendary'
        else:
            prefix = 'universal'
            
        setattr(self, f"{prefix}_avail_list", avail)
        setattr(self, f"{prefix}_sel_list", sel)
        setattr(self, f"{prefix}_clear_btn", clear_btn)
        if multiplier_box:
            setattr(self, f"{prefix}_multiplier", multiplier_box)
            
        move_btn.clicked.connect(lambda: self._move_selected_items(avail, sel, single_select, multiplier_box))
        remove_btn.clicked.connect(lambda: self._remove_selected_items(sel))
        clear_btn.clicked.connect(lambda: self._clear_list(sel))
        
        return group
        
    def _connect_signals(self):
        self.mfg_combo.currentTextChanged.connect(self.on_mfg_change)
        self.level_edit.textChanged.connect(self.rebuild_output)
        self.rarity_combo.currentTextChanged.connect(self.rebuild_output)
        self.add_to_pack_btn.clicked.connect(self._add_to_backpack)
        for widgets in [self.mfg_perk_widgets, self.element_widgets, self.firmware_widgets]:
            for w in widgets: w.toggled.connect(self.rebuild_output)
        for name in ["legendary", "universal"]:
            sel_list = getattr(self, f"{name}_sel_list")
            sel_list.model().rowsInserted.connect(self.rebuild_output); sel_list.model().rowsRemoved.connect(self.rebuild_output)

    def _get_mfg_name(self, mfg_id):
        if mfg_id in lookup.REVERSE_ID_MAP:
            mfg_en = lookup.REVERSE_ID_MAP[mfg_id][0]
            return bl4f.get_localized_string(mfg_en)
        return "Unknown"

    def populate_initial_data(self):
        self.mfg_combo.clear()
        # Generate map dynamically
        mfg_map = {mid: self._get_mfg_name(mid) for mid in self.mfg_ids}
        self.mfg_combo.addItems([f"{v} - {k}" for k, v in sorted(mfg_map.items(), key=lambda x: x[1])]) # Sort by name? or Keep ID? Original sorted by items() which sorts by ID.
        # Original: sorted(self.mfg_map.items()) -> sorted by ID
        
        self._populate_radio_buttons(self.element_frame, self.df_main[self.df_main['Part_type'] == 'Element'], self.element_widgets)
        self._populate_radio_buttons(self.firmware_frame, self.df_main[self.df_main['Part_type'] == 'Firmware'], self.firmware_widgets)
        self._populate_listbox(self.universal_avail_list, self.df_main[self.df_main['Part_type'] == 'Perk'])
        
    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _populate_radio_buttons(self, frame, df, widget_list):
        self._clear_layout(frame)
        widget_list.clear(); none_rb = QRadioButton(self.ui_loc['misc']['none']); none_rb.setChecked(True); frame.addWidget(none_rb); widget_list.append(none_rb)
        for _, r in df.iterrows():
            text = self._(r['Stat'])
            if 'Description' in r and pd.notna(r['Description']): text += f" - {r['Description']}"
            rb = QRadioButton(text); rb.setProperty("part_id", r['Part_ID']); frame.addWidget(rb); widget_list.append(rb)
        frame.addStretch(); [rb.toggled.connect(self.rebuild_output) for rb in widget_list]

    def _populate_checkboxes(self, frame, df, widget_list):
        self._clear_layout(frame)
        widget_list.clear()
        for _, r in df.iterrows():
            text = self._(r['Stat'])
            if 'Description' in r and pd.notna(r['Description']): text += f" - {r['Description']}"
            cb = QCheckBox(text); cb.setProperty("part_id", r['Part_ID']); frame.addWidget(cb); widget_list.append(cb)
        frame.addStretch(); [cb.toggled.connect(self.rebuild_output) for cb in widget_list]

    def _populate_listbox(self, listbox, df):
        listbox.clear()
        for _, r in df.iterrows():
            text = self._(r['Stat'])
            if 'Description' in r and pd.notna(r['Description']): text += f" - {r['Description']}"
            item=QListWidgetItem(text); item.setData(Qt.ItemDataRole.UserRole, r['Part_ID']); listbox.addItem(item)

    def on_mfg_change(self, *args):
        if not self.mfg_combo.currentText(): return
        try:
            mfg_id = int(self.mfg_combo.currentText().split(' - ')[-1])
        except ValueError:
            return # Should not happen with formatted strings
        
        self.rarity_combo.blockSignals(True)
        self.rarity_combo.clear()
        for _, r in self.df_mfg[(self.df_mfg['Manufacturer ID'] == mfg_id) & (self.df_mfg['Part_type'] == 'Rarity')].iterrows():
            desc = r['Description']
            self.rarity_combo.addItem(f"{self._(r['Stat'])} - {desc if pd.notna(desc) else ''}", r['Part_ID'])
        self.rarity_combo.blockSignals(False)
        self.rarity_combo.setFixedWidth(300)  # Re-apply width after populating
        
        self._populate_checkboxes(self.mfg_perk_frame, self.df_mfg[(self.df_mfg['Manufacturer ID'] == mfg_id) & (self.df_mfg['Part_type'] == 'Perk')], self.mfg_perk_widgets)
        self.legendary_avail_list.clear()
        df_leg = self.df_mfg[self.df_mfg['Part_type'] == 'Legendary Perk']
        for _, r in df_leg.iterrows():
            desc = r['Description']
            mfg_name = self._get_mfg_name(r['Manufacturer ID'])
            display_text = f"{mfg_name} - {self._(r['Stat'])} - {desc if pd.notna(desc) else ''}"
            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, (r['Part_ID'], r['Manufacturer ID']))
            self.legendary_avail_list.addItem(item)
        self.rebuild_output()

    def rebuild_output(self, *args):
        try:
            mfg_id = int(self.mfg_combo.currentText().split(' - ')[-1]); level = self.level_edit.text(); rarity_id = self.rarity_combo.currentData()
            main_parts = [f"{mfg_id}, 0, 1, {level}| 2, {305}||"]; skill_parts = []; secondary = {}
            if rarity_id: skill_parts.append(f"{{{rarity_id}}}")
           
            leg_items = [self.legendary_sel_list.item(i) for i in range(self.legendary_sel_list.count())]
            if leg_items:
                other_mfg_perks = {}
                for it in leg_items:
                    # Handle (count) prefix if present, though not explicitly enabled for legendary yet
                    text = it.text()
                    count = 1
                    match = re.match(r"\((\d+)\)\s+(.*)", text)
                    if match:
                         count = int(match.group(1))
                    
                    part_id, item_mfg_id = it.data(Qt.ItemDataRole.UserRole)
                    
                    for _ in range(count):
                        if item_mfg_id == mfg_id:
                            skill_parts.append(f"{{{part_id}}}")
                        else:
                            if item_mfg_id not in other_mfg_perks:
                                other_mfg_perks[item_mfg_id] = []
                            other_mfg_perks[item_mfg_id].append(part_id)
                for item_mfg_id, ids in other_mfg_perks.items():
                    if len(ids) == 1:
                        skill_parts.append(f"{{{item_mfg_id}:{ids[0]}}}")
                    else:
                        sorted_ids = sorted(ids)
                        skill_parts.append(f"{{{item_mfg_id}:[{' '.join(map(str, sorted_ids))}]}}")

            for rb in self.element_widgets + self.firmware_widgets:
                if rb.isChecked() and rb.property("part_id"): secondary.setdefault(245, []).append(rb.property("part_id"))
            for cb in self.mfg_perk_widgets:
                if cb.isChecked() and cb.property("part_id"): skill_parts.append(f"{{{cb.property('part_id')}}}")
            for l, pid_key in [(self.universal_sel_list, 245)]:
                for i in range(l.count()): 
                    item = l.item(i)
                    text = item.text()
                    count = 1
                    match = re.match(r"\((\d+)\)\s+(.*)", text)
                    if match:
                         count = int(match.group(1))
                    
                    pid = item.data(Qt.ItemDataRole.UserRole)
                    for _ in range(count):
                        secondary.setdefault(pid_key, []).append(pid)
            
            for k, v in secondary.items():
                if v:
                    skill_parts.append(f"{{{k}:[{' '.join(map(str, sorted(v)))}]}}" if len(v) > 1 else f"{{{k}:{v[0]}}}")

            final_str = " ".join(main_parts) + " " + " ".join(skill_parts) + " |"
            self.raw_output_edit.setText(final_str)
            encoded, err = b_encoder.encode_to_base85(final_str); self.b85_output_edit.setText(encoded if not err else f"错误: {err}")
        except Exception as e: print(f"Rebuild error: {e}")

    def _move_selected_items(self, src, dest, single, multiplier_box=None):
        if single and dest.count() > 0: return
        
        count_val = multiplier_box.value() if multiplier_box else 1
        
        items_to_move = src.selectedItems()
        for item in items_to_move:
            if item.flags() & Qt.ItemFlag.ItemIsEnabled:
                base_text = item.text()
                
                # Check existing
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
                
                if existing_item and not single:
                    new_count = current_count + count_val
                    existing_item.setText(f"({new_count}) {base_text}")
                else:
                    new_item = item.clone()
                    if not single and multiplier_box:
                        new_item.setText(f"({count_val}) {base_text}")
                    dest.addItem(new_item)
        
        if not single:
            pass # Allow stacking

    def _remove_selected_items(self, list_widget):
        for item in list_widget.selectedItems(): list_widget.takeItem(list_widget.row(item))
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

    def _copy_to_clipboard(self, line_edit): QApplication.clipboard().setText(line_edit.text()); QMessageBox.information(self, self.ui_loc['dialogs']['success'], self.ui_loc['dialogs']['copied'])
        
    def _add_to_backpack(self):
        serial = self.b85_output_edit.text()
        if not serial or "Error" in serial or "错误" in serial: QMessageBox.warning(self, self.ui_loc['dialogs']['no_valid_code'], self.ui_loc['dialogs']['gen_first']); return
        self.add_to_backpack_requested.emit(serial, self.flag_combo.currentText().split(" ")[0])
