from PyQt6 import QtWidgets, QtCore, QtGui
import pandas as pd
import random
import re
import sys
from functools import partial

from core import bl4_functions as bl4f
from core import b_encoder
from core import resource_loader

class WeaponEditorTab(QtWidgets.QWidget):
    add_to_backpack_requested = QtCore.pyqtSignal(str, str)
    update_item_requested = QtCore.pyqtSignal(dict)
    
    # Part type color mapping based on QSS stylesheet
    PART_TYPE_COLORS = {
        # English
        "Barrel": "#90A4AE",
        "Barrel Accessory": "#78909C",
        "Body": "#A1887F",
        "Body Accessory": "#8D6E63",
        "Foregrip": "#9CCC65",
        "Grip": "#7CB342",
        "Magazine": "#FFB300",
        "Manufacturer Part": "#5C6BC0",
        "Scope": "#4DD0E1",
        "Scope Accessory": "#26C6DA",
        "Stat Modifier": "#F06292",
        "Underbarrel": "#8D6E63",
        "Underbarrel Accessory": "#795548",
        "Elemental": "#EF9A9A",
        "Element": "#EF9A9A",
        "Skin": "#FFEA00",
        "Rarity": "#B39DDB",
        "Legendary": "#FF8A65",
        # Chinese
        "枪管": "#90A4AE",
        "枪管附件": "#78909C",
        "枪身": "#A1887F",
        "枪身附属": "#8D6E63",
        "前握把": "#9CCC65",
        "后握把/枪托": "#7CB342",
        "弹匣": "#FFB300",
        "厂商授权部件": "#5C6BC0",
        "瞄准镜": "#4DD0E1",
        "瞄准镜附件": "#26C6DA",
        "属性修改组件": "#F06292",
        "下挂": "#8D6E63",
        "下挂附件": "#795548",
        "元素": "#EF9A9A",
        "皮肤": "#FFEA00",
        "稀有度": "#B39DDB",
        "传奇": "#FF8A65",
        # Russian
        "Стихия": "#EF9A9A",
        "Скин": "#FFEA00",
        # Ukrainian  
        "Стихія": "#EF9A9A",
        "Скін": "#FFEA00",
    }

    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app
        self.selected_weapon_path = None
        self.parts_data = []
        self.rarity_part = None
        
        self.all_weapon_parts_df = None
        self.elemental_df = None
        self.weapon_name_df = None
        self.skin_df = None
        self.weapon_rarity_df = None
        self.weapon_localization = {}
        
        self.is_handling_change = False
        self.current_lang = 'zh-CN'
        
        # Main layout
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.content_widget = None

        self.load_data(self.current_lang)
        self.create_widgets()

    def load_data(self, lang='zh-CN'):
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

            self.all_weapon_parts_df = pd.read_csv(get_path('all_weapon_part.csv'))
            self.elemental_df = pd.read_csv(get_path('elemental.csv')) 
            self.weapon_name_df = pd.read_csv(get_path('weapon_name.csv'))
            self.skin_df = pd.read_csv(get_path('skin.csv'))
            self.weapon_rarity_df = pd.read_csv(get_path('weapon_rarity.csv'))
            
            self.weapon_localization = {}
            if lang == 'zh-CN':
                self.weapon_localization = resource_loader.load_weapon_json('weapon_localization_zh-CN.json') or {}
            
            # Load UI localization
            loc_file = resource_loader.get_ui_localization_file(lang)
            full_loc = resource_loader.load_json_resource(loc_file) or {}
            self.ui_localization = full_loc.get("weapon_editor_tab", {})
            
            # Re-enable if data loaded successfully (in case it was disabled previously)
            self.setEnabled(True)
            
        except FileNotFoundError as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Missing required file: {e}")
            self.setEnabled(False)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"An error occurred while loading data: {e}")
            self.setEnabled(False)

    def update_language(self, lang):
        print(f"DEBUG: Updating language for {self.__class__.__name__} to {lang}...")
        self.current_lang = lang
        self.load_data(lang)
        
        # Save current state
        current_decoded = self.serial_decoded_entry.text() if hasattr(self, 'serial_decoded_entry') else ""
        current_flag_idx = self.flag_combo.currentIndex() if hasattr(self, 'flag_combo') else 0
        
        # Clean up internal state
        self.parts_data = []
        self.rarity_part = None
        self.selected_weapon_path = None
        
        self.create_widgets()
        
        # Restore state
        if hasattr(self, 'flag_combo') and self.flag_combo.count() > current_flag_idx:
            self.flag_combo.setCurrentIndex(current_flag_idx)
            
        # If there was data loaded, reload it to refresh text
        if current_decoded:
             self.serial_decoded_entry.setText(current_decoded) # Set text first so it's available if parse fails
             self.parse_and_display_weapon(current_decoded)
        print(f"DEBUG: Finished updating language for {self.__class__.__name__}.")

    def create_widgets(self):
        # Clean up old content
        while self.main_layout.count():
            item = self.main_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
        self.content_widget = None

        # Create new content widget
        self.content_widget = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout(self.content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        
        self.main_layout.addWidget(self.content_widget)

        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)
        content_layout.addWidget(scroll_area)

        main_frame = QtWidgets.QFrame()
        scroll_area.setWidget(main_frame)
        layout = QtWidgets.QGridLayout(main_frame)
        layout.setColumnStretch(0, 1)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)  # Align all items to top

        bp_frame = QtWidgets.QFrame(); bp_frame.setObjectName("InnerFrame")
        bp_layout = QtWidgets.QVBoxLayout(bp_frame)
        bp_layout.addWidget(QtWidgets.QLabel(self.get_localized_string("load_from_backpack")))
        self.backpack_items_frame = QtWidgets.QScrollArea()
        self.backpack_items_frame.setWidgetResizable(True)
        self.backpack_items_frame.setFixedHeight(200)  # Fixed height to prevent flickering
        bp_scroll_content = QtWidgets.QWidget()
        self.backpack_items_layout = QtWidgets.QVBoxLayout(bp_scroll_content)
        self.backpack_items_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        self.backpack_items_frame.setWidget(bp_scroll_content)
        self.backpack_items_layout.addWidget(QtWidgets.QLabel(self.get_localized_string("decrypt_save_to_show_weapons")))
        bp_layout.addWidget(self.backpack_items_frame)
        layout.addWidget(bp_frame, 0, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        
        s_frame = QtWidgets.QFrame(); s_frame.setObjectName("InnerFrame")
        s_layout = QtWidgets.QGridLayout(s_frame)
        s_layout.setColumnStretch(1, 1)
        s_layout.addWidget(QtWidgets.QLabel(self.get_localized_string("serial_b85")), 0, 0)
        self.serial_b85_entry = QtWidgets.QLineEdit()
        s_layout.addWidget(self.serial_b85_entry, 0, 1)
        s_layout.addWidget(QtWidgets.QLabel(self.get_localized_string("serial_decoded")), 1, 0)
        self.serial_decoded_entry = QtWidgets.QLineEdit()
        s_layout.addWidget(self.serial_decoded_entry, 1, 1)
        layout.addWidget(s_frame, 1, 0)

        act_frame = QtWidgets.QFrame()
        act_layout = QtWidgets.QGridLayout(act_frame)
        self.update_weapon_btn = QtWidgets.QPushButton(self.get_localized_string("update_weapon"))
        self.add_to_backpack_btn = QtWidgets.QPushButton(self.get_localized_string("add_to_backpack"))
        self.flag_combo = QtWidgets.QComboBox()
        
        # Load flags from UI localization
        flags = self.ui_localization.get('flags', {})
        if flags:
            flag_options = [flags.get(k, f"{k} (Unknown)") for k in ["1", "3", "5", "17", "33", "65", "129"]]
            self.flag_combo.addItems(flag_options)
        else:
            self.flag_combo.addItems(["1 (普通)", "3 (收藏)", "5 (垃圾)", "17 (编组1)", "33 (编组2)", "65 (编组3)", "129 (编组4)"])
            
        act_layout.addWidget(self.update_weapon_btn, 0, 0)
        act_layout.addWidget(self.add_to_backpack_btn, 0, 1)
        act_layout.addWidget(self.flag_combo, 0, 2)
        layout.addWidget(act_frame, 2, 0)
        
        editor_frame = QtWidgets.QFrame(); editor_frame.setObjectName("InnerFrame")
        editor_layout = QtWidgets.QGridLayout(editor_frame)
        for i in range(5): editor_layout.setColumnStretch(i, 1)
        
        labels = ["manufacturer", "weapon_type", "rarity", "level", "seed"]
        for i, lbl_key in enumerate(labels):
            editor_layout.addWidget(QtWidgets.QLabel(self.get_localized_string(lbl_key)), 0, i, QtCore.Qt.AlignmentFlag.AlignCenter)

        self.manufacturer_entry = QtWidgets.QLineEdit(); self.manufacturer_entry.setReadOnly(True)
        editor_layout.addWidget(self.manufacturer_entry, 1, 0)
        self.item_type_entry = QtWidgets.QLineEdit(); self.item_type_entry.setReadOnly(True)
        editor_layout.addWidget(self.item_type_entry, 1, 1)
        self.rarity_combo = QtWidgets.QComboBox()
        rarity_values = [self.get_localized_string(r) for r in ["Common", "Uncommon", "Rare", "Epic"]]
        self.rarity_combo.addItems(rarity_values)
        editor_layout.addWidget(self.rarity_combo, 1, 2)
        self.level_entry = QtWidgets.QLineEdit()
        self.level_entry.setValidator(QtGui.QIntValidator(1, 100))
        editor_layout.addWidget(self.level_entry, 1, 3)
        
        seed_layout = QtWidgets.QGridLayout()
        seed_frame = QtWidgets.QFrame(); seed_frame.setLayout(seed_layout)
        self.seed_entry = QtWidgets.QLineEdit(); self.seed_entry.setValidator(QtGui.QIntValidator())
        seed_layout.addWidget(self.seed_entry, 0, 0)
        self.random_seed_btn = QtWidgets.QPushButton("🎲"); self.random_seed_btn.setFixedWidth(40)
        seed_layout.addWidget(self.random_seed_btn, 0, 1)
        editor_layout.addWidget(seed_frame, 1, 4)
        
        self.weapon_name_label_str = self.get_localized_string("weapon_name_label")
        self.weapon_name_label = QtWidgets.QLabel(self.weapon_name_label_str)
        self.weapon_name_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        editor_layout.addWidget(self.weapon_name_label, 2, 0, 1, 5)
        layout.addWidget(editor_frame, 3, 0)
        
        parts_frame = QtWidgets.QFrame(); parts_frame.setObjectName("InnerFrame")
        parts_layout = QtWidgets.QVBoxLayout(parts_frame)
        
        parts_header_frame = QtWidgets.QFrame()
        parts_header_layout = QtWidgets.QGridLayout(parts_header_frame)
        parts_header_layout.addWidget(QtWidgets.QLabel(self.get_localized_string("weapon_parts")), 0, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
        parts_header_layout.setColumnStretch(0, 1)
        self.refresh_parts_btn = QtWidgets.QPushButton("🔄"); self.refresh_parts_btn.setFixedWidth(30)
        parts_header_layout.addWidget(self.refresh_parts_btn, 0, 1, QtCore.Qt.AlignmentFlag.AlignRight)
        self.add_part_btn = QtWidgets.QPushButton(self.get_localized_string("add_part")); self.add_part_btn.setFixedWidth(100)
        parts_header_layout.addWidget(self.add_part_btn, 0, 2, QtCore.Qt.AlignmentFlag.AlignRight)
        parts_layout.addWidget(parts_header_frame)
        
        # Parts list container - no independent scroll, uses page scroll
        parts_list_content = QtWidgets.QWidget()
        self.parts_list_layout = QtWidgets.QVBoxLayout(parts_list_content)
        self.parts_list_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        self.parts_list_layout.setContentsMargins(0, 0, 0, 0)
        self.parts_list_layout.addWidget(QtWidgets.QLabel(self.get_localized_string("parse_serial_to_show_parts")))
        parts_layout.addWidget(parts_list_content)
        layout.addWidget(parts_frame, 4, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        main_frame.setLayout(layout) # Set the grid layout to the main frame
        
        self.serial_b85_entry.textChanged.connect(self.handle_b85_change)
        self.serial_decoded_entry.textChanged.connect(self.handle_decoded_change)
        self.rarity_combo.currentIndexChanged.connect(self.update_decoded_from_ui)
        self.level_entry.textChanged.connect(self.update_decoded_from_ui)
        self.seed_entry.textChanged.connect(self.update_decoded_from_ui)
        self.random_seed_btn.clicked.connect(self.randomize_seed)
        self.update_weapon_btn.clicked.connect(self.update_weapon)
        self.add_to_backpack_btn.clicked.connect(self.add_new_weapon_to_backpack)
        self.refresh_parts_btn.clicked.connect(self.force_refresh_parts)
        self.add_part_btn.clicked.connect(self.open_add_part_window)

    def get_localized_string(self, key, default=''):
        # Check UI localization first (flattened check or mapped)
        # We map keys to sections in ui_localization
        if not self.ui_localization:
             return self.weapon_localization.get(key, default or key)
             
        # Map common keys to UI structure
        ui_map = {
            # Labels
            "load_from_backpack": self.ui_localization.get('labels', {}).get('load_from_backpack'),
            "decrypt_save_to_show_weapons": self.ui_localization.get('labels', {}).get('decrypt_save_to_show_weapons'),
            "serial_b85": self.ui_localization.get('labels', {}).get('serial_b85'),
            "serial_decoded": self.ui_localization.get('labels', {}).get('serial_decoded'),
            "manufacturer": self.ui_localization.get('labels', {}).get('manufacturer'),
            "weapon_type": self.ui_localization.get('labels', {}).get('weapon_type'),
            "rarity": self.ui_localization.get('labels', {}).get('rarity'),
            "level": self.ui_localization.get('labels', {}).get('level'),
            "seed": self.ui_localization.get('labels', {}).get('seed'),
            "weapon_name_label": self.ui_localization.get('labels', {}).get('weapon_name_label'),
            "weapon_parts": self.ui_localization.get('labels', {}).get('weapon_parts'),
            "parts_list": self.ui_localization.get('labels', {}).get('parts_list'),
            "parse_serial_to_show_parts": self.ui_localization.get('labels', {}).get('parse_serial_to_show_parts'),
            "level_label": self.ui_localization.get('labels', {}).get('level_label'),
            "slot_label": self.ui_localization.get('labels', {}).get('slot_label'),
            
            # Buttons
            "update_weapon": self.ui_localization.get('buttons', {}).get('update_weapon'),
            "add_to_backpack": self.ui_localization.get('buttons', {}).get('add_to_backpack'),
            "add_part": self.ui_localization.get('buttons', {}).get('add_part'),
            "confirm_add": self.ui_localization.get('buttons', {}).get('confirm_add'),
            
            # Dialogs/Messages
            "error": self.ui_localization.get('dialogs', {}).get('error'),
            "no_weapons_in_backpack": self.ui_localization.get('dialogs', {}).get('no_weapons_in_backpack'),
            "no_valid_decoded_data": self.ui_localization.get('dialogs', {}).get('no_valid_decoded_data'),
            "parse_error": self.ui_localization.get('dialogs', {}).get('parse_error'),
            "parse_weapon_error": self.ui_localization.get('dialogs', {}).get('parse_weapon_error'),
            "parts_not_found": self.ui_localization.get('dialogs', {}).get('parts_not_found'),
            "no_selection": self.ui_localization.get('dialogs', {}).get('no_selection'),
            "select_weapon_first": self.ui_localization.get('dialogs', {}).get('select_weapon_first'),
            "encoding_fail": self.ui_localization.get('dialogs', {}).get('encoding_fail'),
            "cannot_reencode_serial": self.ui_localization.get('dialogs', {}).get('cannot_reencode_serial'),
            "cannot_encode_serial": self.ui_localization.get('dialogs', {}).get('cannot_encode_serial'),
            "success": self.ui_localization.get('dialogs', {}).get('success'),
            "no_input": self.ui_localization.get('dialogs', {}).get('no_input'),
            "serial_empty": self.ui_localization.get('dialogs', {}).get('serial_empty'),
            "no_weapon": self.ui_localization.get('dialogs', {}).get('no_weapon'),
            "load_weapon_first": self.ui_localization.get('dialogs', {}).get('load_weapon_first'),
            "add_part_title": self.ui_localization.get('dialogs', {}).get('add_part_title'),
            "select_parts_to_add": self.ui_localization.get('dialogs', {}).get('select_parts_to_add'),
            "cannot_determine_mfg": self.ui_localization.get('dialogs', {}).get('cannot_determine_mfg'),
            "Select Skin": self.ui_localization.get('dialogs', {}).get('select_skin_title'),
            "Select a skin to apply": self.ui_localization.get('dialogs', {}).get('select_skin_msg'),
            "update_success": self.ui_localization.get('dialogs', {}).get('update_success'),
            
            # Misc
            "Skin": self.ui_localization.get('misc', {}).get('skin'),
            "Elemental": self.ui_localization.get('misc', {}).get('elemental'),
            "elements": self.ui_localization.get('misc', {}).get('elements'),
            "element_switch": self.ui_localization.get('misc', {}).get('element_switch'),
        }
        
        if key in ui_map and ui_map[key]:
            return ui_map[key]
            
        return self.weapon_localization.get(key, default or key)

    def handle_b85_change(self, text):
        if self.is_handling_change or not self.serial_b85_entry.hasFocus():
            return

        self.is_handling_change = True
        if not text:
            self.clear_all_fields()
            self.is_handling_change = False
            return

        decoded_str, _, err = bl4f.decode_serial_to_string(text)
        if not err:
            self.serial_decoded_entry.blockSignals(True)
            self.serial_decoded_entry.setText(decoded_str)
            self.serial_decoded_entry.blockSignals(False)
            self.parse_and_display_weapon(decoded_str)
            self.serial_b85_entry.setReadOnly(True)
            self.update_weapon_btn.setEnabled(True)
        else:
            self.serial_decoded_entry.clear()
        self.is_handling_change = False

    def handle_decoded_change(self, text):
        if not self.serial_decoded_entry.hasFocus():
            return
        self.update_b85_from_decoded()
        if not text:
            self.clear_all_fields(clear_b85=False)
            return
        self.parse_and_display_weapon(text)

    def update_b85_from_decoded(self):
        decoded_str = self.serial_decoded_entry.text()
        if not decoded_str: return
        new_b85, err = b_encoder.encode_to_base85(decoded_str)
        if not err:
            self.serial_b85_entry.blockSignals(True)
            self.serial_b85_entry.setText(new_b85)
            self.serial_b85_entry.blockSignals(False)

    def _get_rarity_and_weapon_name(self, parts, m_id):
        rarity, weapon_name, rarity_part, display_rarity, remaining_parts = "Unknown", "Unknown", None, "Unknown", list(parts)
        for p in parts:
            if not isinstance(p, dict) or p.get('type') != 'simple':
                continue
            part_id = p.get('id')
            if not part_id:
                continue
            part_details = self.all_weapon_parts_df[(self.all_weapon_parts_df['Manufacturer & Weapon Type ID'] == m_id) & (self.all_weapon_parts_df['Part ID'] == part_id)]
            if not part_details.empty and part_details.iloc[0]['Part Type'] == 'Barrel':
                name_info = self.weapon_name_df[(self.weapon_name_df['Manufacturer & Weapon Type ID'] == m_id) & (self.weapon_name_df['Part ID'] == part_id)]
                if not name_info.empty: weapon_name = name_info.iloc[0]['Name']; break
        simple_parts = [p for p in parts if isinstance(p, dict) and p.get('type') == 'simple']
        if simple_parts and 'id' in simple_parts[0]:
            rarity_info = self.weapon_rarity_df[(self.weapon_rarity_df['Manufacturer & Weapon Type ID'] == m_id) & (self.weapon_rarity_df['Part ID'] == simple_parts[0]['id'] )]
            if not rarity_info.empty:
                details = rarity_info.iloc[0]; rarity, desc = details['Stat'], details['Description']
                display_rarity = f"{rarity} - {desc}" if rarity == "Legendary" and pd.notna(desc) else rarity
                rarity_part = simple_parts[0]
        if not rarity_part: display_rarity = rarity = "Legendary"
        if rarity_part: remaining_parts = [p for p in remaining_parts if p is not rarity_part]
        return display_rarity, weapon_name, rarity_part, remaining_parts

    def _parse_component_string(self, component_str):
        components, last_index = [], 0
        for match in re.finditer(r'\{(\d+)(?::(\d+|\[[\d\s]+\]))?\}|\"c\",\s*(\d+)', component_str):
            components.append(component_str[last_index:match.start()])
            part_data = {'raw': match.group(0)}
            if match.group(3): part_data.update({'type': 'skin', 'id': int(match.group(3))})
            else:
                outer_id, inner = int(match.group(1)), match.group(2)
                if inner: part_data.update({'type': 'group', 'id': outer_id, 'sub_ids': [int(sid) for sid in inner.strip('[]').split()]} if '[' in inner else {'type': 'elemental', 'id': outer_id, 'sub_id': int(inner)})
                else: part_data.update({'type': 'simple', 'id': outer_id})
            components.append(part_data); last_index = match.end()
        components.append(component_str[last_index:])
        return [c for c in components if c]

    def clear_all_fields(self, clear_b85=True):
        self.is_handling_change = True
        if clear_b85: self.serial_b85_entry.clear()
        self.serial_decoded_entry.clear(); self.manufacturer_entry.clear(); self.item_type_entry.clear()
        self.rarity_combo.setCurrentIndex(-1); self.level_entry.clear(); self.seed_entry.clear()
        self.weapon_name_label.setText(self.weapon_name_label_str)

        while self.parts_list_layout.count():
            item = self.parts_list_layout.takeAt(0)
            if (widget := item.widget()):
                widget.deleteLater()
            elif (layout := item.layout()):
                while layout.count():
                    sub_item = layout.takeAt(0)
                    if (sub_widget := sub_item.widget()):
                        sub_widget.deleteLater()

        self.parts_list_layout.addWidget(QtWidgets.QLabel(self.get_localized_string("parse_serial_to_show_parts")))
        self.serial_b85_entry.setReadOnly(False); self.update_weapon_btn.setEnabled(False)
        self.selected_weapon_path, self.parts_data, self.rarity_part = None, [], None
        self.is_handling_change = False

    def update_decoded_from_ui(self):
        if self.is_handling_change: return
        current_decoded = self.serial_decoded_entry.text()
        if not current_decoded: return
        try:
            updated_str = bl4f.update_level_in_decoded_str(current_decoded, self.level_entry.text())
            parts = updated_str.split('|')
            if len(parts) > 1 and len(parts[1].split(',')) > 1:
                seed_parts = parts[1].split(','); seed_parts[1] = f" {self.seed_entry.text()}"; parts[1] = ",".join(seed_parts)
                updated_str = "|".join(parts)

            if self.rarity_part and "Legendary" not in self.rarity_combo.currentText():
                rarity_map = {self.get_localized_string(k): k for k in ["Common", "Uncommon", "Rare", "Epic"]}
                if rarity_en := rarity_map.get(self.rarity_combo.currentText()):
                    m_id = int(updated_str.split('||')[0].strip().split('|')[0].strip().split(',')[0])
                    info = self.weapon_rarity_df[(self.weapon_rarity_df['Manufacturer & Weapon Type ID'] == m_id) & (self.weapon_rarity_df['Stat'] == rarity_en) & (self.weapon_rarity_df['Part Type'] == 'Rarity')]
                    if not info.empty:
                        new_id = info.iloc[0]['Part ID']
                        updated_str = updated_str.replace(self.rarity_part['raw'], f"{{{new_id}}}")
                        self.rarity_part['id'], self.rarity_part['raw'] = new_id, f"{{{new_id}}}"

            if self.serial_decoded_entry.text() != updated_str: self.serial_decoded_entry.setText(updated_str)
        except Exception as e: self.main_app.log(f"Error in update_decoded_from_ui: {e}")

    def randomize_seed(self): self.seed_entry.setText(str(random.randint(100, 9999)))
    def load_weapon_data(self, weapon_data):
        self.main_app.log(f"Loading weapon: {weapon_data.get('name')}")
        self.selected_weapon_path = weapon_data.get("original_path")
        self.is_handling_change = True
        self.serial_b85_entry.setText(weapon_data.get('serial', ''))
        decoded_str = weapon_data.get('decoded_full', '')
        self.serial_decoded_entry.setText(decoded_str)
        self.is_handling_change = False
        if not decoded_str:
            QtWidgets.QMessageBox.critical(self, self.get_localized_string("error"), self.get_localized_string("no_valid_decoded_data")); return
        self.parse_and_display_weapon(decoded_str)
        self.serial_b85_entry.setReadOnly(True); self.update_weapon_btn.setEnabled(True)

    def parse_and_display_weapon(self, decoded_str):
        try:
            header_part, component_part = decoded_str.split('||', 1)
            sections = header_part.strip().split('|')
            m_id, level = int(sections[0].strip().split(',')[0]), int(sections[0].strip().split(',')[3])
            m_info = self.all_weapon_parts_df[self.all_weapon_parts_df['Manufacturer & Weapon Type ID'] == m_id].iloc[0]
            self.is_handling_change = True
            self.manufacturer_entry.setText(self.get_localized_string(m_info['Manufacturer']))
            self.item_type_entry.setText(self.get_localized_string(m_info['Weapon Type']))
            self.level_entry.setText(str(level))
            self.seed_entry.setText(sections[1].strip().split(',')[1].strip() if len(sections) > 1 and len(sections[1].strip().split(',')) > 1 else "")
            
            temp_parts = self._parse_component_string(component_part)
            display_rarity, weapon_name, self.rarity_part, remaining_parts = self._get_rarity_and_weapon_name(temp_parts, m_id)
            
            rarity_parts = display_rarity.split(' - ')
            base_rarity, localized_base = rarity_parts[0], self.get_localized_string(rarity_parts[0])
            final_display_rarity = f"{localized_base} - {self.get_localized_string(rarity_parts[1], rarity_parts[1])}" if len(rarity_parts) > 1 else localized_base
            
            if base_rarity == "Legendary":
                self.rarity_combo.setEditable(True); self.rarity_combo.lineEdit().setText(final_display_rarity); self.rarity_combo.setEnabled(False)
            else:
                self.rarity_combo.setEditable(False); self.rarity_combo.setEnabled(True)
                if (index := self.rarity_combo.findText(localized_base)) != -1: self.rarity_combo.setCurrentIndex(index)

            self.weapon_name_label.setText(f"{self.weapon_name_label_str} {self.get_localized_string(weapon_name, weapon_name)}")
            self.parts_data = remaining_parts; self.display_parts(m_id)
            self.is_handling_change = False
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, self.get_localized_string("parse_error"), f"{self.get_localized_string('parse_weapon_error')}: {e}")
            self.main_app.log(f"Error parsing weapon: {e}"); self.clear_all_fields()

    def display_parts(self, manufacturer_id):
        while self.parts_list_layout.count():
            item = self.parts_list_layout.takeAt(0)
            if (widget := item.widget()):
                widget.deleteLater()
            elif (layout := item.layout()):
                while layout.count():
                    sub_item = layout.takeAt(0)
                    if (sub_widget := sub_item.widget()):
                        sub_widget.deleteLater()

        if not self.parts_data:
            self.parts_list_layout.addWidget(QtWidgets.QLabel(self.get_localized_string("parts_not_found"))); return
        for i, part_info in enumerate(self.parts_data):
            if isinstance(part_info, str): continue
            frame = self._create_collapsible_part_frame(part_info, i) if part_info.get('type') == 'group' else self._create_simple_part_frame(part_info, manufacturer_id, i)
            if frame: self.parts_list_layout.addWidget(frame)

    def _create_simple_part_frame(self, part_info, m_id, index):
        frame = QtWidgets.QFrame(); frame.setObjectName('PartFrame')
        layout = QtWidgets.QGridLayout(frame); layout.setColumnStretch(2, 1)
        part_id = part_info.get('id'); info = {'type': "未知", 'str': "错误", 'stat': ""}
        is_skin, is_elemental = (part_info.get('type') == 'skin'), (part_info.get('type') == 'elemental')
        if is_skin:
            if not (d := self.skin_df[self.skin_df['Skin_ID'] == part_id]).empty: info.update({'type': self.get_localized_string("Skin"), 'str': d.iloc[0]['Stat']})
        elif is_elemental:
            if not (d := self.elemental_df[self.elemental_df['Part_ID'] == part_info['sub_id']]).empty: info.update({'type': self.get_localized_string("Elemental"), 'str': self.get_localized_string(d.iloc[0]['Stat'])})
        else:
            d = self.all_weapon_parts_df[(self.all_weapon_parts_df['Manufacturer & Weapon Type ID'] == m_id) & (self.all_weapon_parts_df['Part ID'] == part_id)]
            if not d.empty: info.update({'type': self.get_localized_string(d.iloc[0]['Part Type']), 'str': d.iloc[0]['String'], 'stat': d.iloc[0]['Stat']})
        display_text = f"  {part_id}  " if not is_elemental else f"  {part_info['id']}:{part_info['sub_id']}  "
        id_label = QtWidgets.QLabel(display_text); id_label.setStyleSheet("background-color: #4a4a4a; border-radius: 5px; padding: 2px;")
        type_color = self.PART_TYPE_COLORS.get(info['type'], "#e0e0e0")
        type_label = QtWidgets.QLabel(info['type']); type_label.setStyleSheet(f"color: {type_color}; font-weight: bold;")
        layout.addWidget(id_label, 0, 0); layout.addWidget(type_label, 0, 1)
        layout.addWidget(QtWidgets.QLabel(info['str']), 0, 2); layout.addWidget(QtWidgets.QLabel(str(info['stat']) if pd.notna(info['stat']) else ""), 0, 3)
        layout.addWidget(self._add_action_buttons(index, is_skin), 0, 4, QtCore.Qt.AlignmentFlag.AlignRight)
        return frame

    def _create_collapsible_part_frame(self, part_info, index):
        container = QtWidgets.QFrame(); container.setObjectName('PartGroupFrame')
        container_layout = QtWidgets.QVBoxLayout(container); container_layout.setSpacing(0); container_layout.setContentsMargins(0,0,0,0)
        header, content = QtWidgets.QFrame(), QtWidgets.QFrame(); content.setVisible(False)
        header_layout, content_layout = QtWidgets.QGridLayout(header), QtWidgets.QVBoxLayout(content)
        group_id = part_info.get('id', 0); mfg_name, is_known = "未知厂商", False
        try:
            mfg_name = self.get_localized_string(self.all_weapon_parts_df[self.all_weapon_parts_df['Manufacturer & Weapon Type ID'] == group_id].iloc[0]['Manufacturer']); is_known = True
        except (IndexError, KeyError): pass
        toggle_btn = QtWidgets.QPushButton("▶"); toggle_btn.setFixedSize(24, 24)
        toggle_btn.clicked.connect(lambda checked, b=toggle_btn, c=content: self._toggle_group_visibility(b, c))
        header_layout.addWidget(toggle_btn, 0, 0); header_layout.addWidget(QtWidgets.QLabel(f"折叠组: {part_info['raw']} {'(未知)' if not is_known else ''}"), 0, 1)
        header_layout.setColumnStretch(1, 1)
        action_buttons = self._add_action_buttons(index)
        header_layout.addWidget(action_buttons, 0, 2, QtCore.Qt.AlignmentFlag.AlignRight)
        for sub_id in part_info.get('sub_ids', []):
            sub_frame = QtWidgets.QFrame(); sub_layout = QtWidgets.QGridLayout(sub_frame); sub_layout.setColumnStretch(2, 1)
            sub_layout.addWidget(QtWidgets.QLabel(f"  {sub_id}  "), 0, 0)
            p_type, p_str, p_stat = "未知", "无法解析", ""
            d = self.all_weapon_parts_df[(self.all_weapon_parts_df['Manufacturer & Weapon Type ID'] == group_id) & (self.all_weapon_parts_df['Part ID'] == sub_id)]
            if not d.empty: p_type, p_str, p_stat = self.get_localized_string(d.iloc[0]['Part Type']), d.iloc[0]['String'], d.iloc[0]['Stat']
            sub_layout.addWidget(QtWidgets.QLabel(f"{mfg_name} - {p_type}"), 0, 1); sub_layout.addWidget(QtWidgets.QLabel(p_str), 0, 2)
            sub_layout.addWidget(QtWidgets.QLabel(str(p_stat) if pd.notna(p_stat) else ""), 0, 3)
            content_layout.addWidget(sub_frame)
        content.setLayout(content_layout); container_layout.addWidget(header); container_layout.addWidget(content)
        return container
        
    def _add_action_buttons(self, index, is_skin=False):
        frame = QtWidgets.QFrame()
        layout = QtWidgets.QHBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        if is_skin:
            edit_btn = QtWidgets.QPushButton("🖌️"); edit_btn.setFixedWidth(35); edit_btn.clicked.connect(partial(self.open_select_skin_window, index)); layout.addWidget(edit_btn)
        else:
            up_btn = QtWidgets.QPushButton("⬆"); up_btn.setFixedWidth(35); up_btn.clicked.connect(partial(self.move_part, index, -1)); layout.addWidget(up_btn)
            down_btn = QtWidgets.QPushButton("⬇"); down_btn.setFixedWidth(35); down_btn.clicked.connect(partial(self.move_part, index, 1)); layout.addWidget(down_btn)
        del_btn = QtWidgets.QPushButton("❌"); del_btn.setFixedWidth(35); del_btn.setStyleSheet("background-color: firebrick;"); del_btn.clicked.connect(partial(self.delete_part, index)); layout.addWidget(del_btn)
        return frame

    def move_part(self, index, direction):
        if not 0 <= index < len(self.parts_data): return
        new_index = index + direction
        if not 0 <= new_index < len(self.parts_data): return
        self.parts_data.insert(new_index, self.parts_data.pop(index)); self.regenerate_ui_and_serial()

    def delete_part(self, index):
        if 0 <= index < len(self.parts_data):
            self.parts_data.pop(index); self.regenerate_ui_and_serial()

    def regenerate_ui_and_serial(self):
        current_decoded = self.serial_decoded_entry.text()
        if '||' not in current_decoded: return
        header_part, _ = current_decoded.split('||', 1)
        try: m_id = int(header_part.strip().split('|')[0].strip().split(',')[0])
        except (ValueError, IndexError): return
        new_component_list = ([self.rarity_part['raw']] if self.rarity_part else []) + [p['raw'] if isinstance(p, dict) else p for p in self.parts_data]
        new_component_str = re.sub(r'\s{2,}', ' ', " ".join(new_component_list).strip())
        self.serial_decoded_entry.setText(f"{header_part.strip()}|| {new_component_str}")
        self.display_parts(m_id)

    def force_refresh_parts(self):
        if not (decoded_str := self.serial_decoded_entry.text()):
            QtWidgets.QMessageBox.warning(self, self.get_localized_string("no_input"), self.get_localized_string("serial_empty")); return
        self.main_app.log("Forcing parts list refresh..."); self.parse_and_display_weapon(decoded_str)
        QtWidgets.QMessageBox.information(self, self.get_localized_string("success"), self.get_localized_string("parts_refresh_success"))

    def refresh_backpack_items(self):
        while self.backpack_items_layout.count():
            item = self.backpack_items_layout.takeAt(0)
            if (widget := item.widget()): widget.deleteLater()
            elif (layout := item.layout()):
                while layout.count():
                    sub_item = layout.takeAt(0)
                    if (sub_widget := sub_item.widget()): sub_widget.deleteLater()
        
        if self.main_app.controller.yaml_obj is None or not (items := self.main_app.controller.get_all_items()):
            self.backpack_items_layout.addWidget(QtWidgets.QLabel(self.get_localized_string("decrypt_save_to_show_weapons"))); return
        
        weapon_types = {"Pistol", "Shotgun", "SMG", "Assault Rifle", "Sniper"}
        filtered = [i for i in items if i.get("type_en") in weapon_types and "Backpack" in i.get("container", "")]
        if not filtered:
            self.backpack_items_layout.addWidget(QtWidgets.QLabel(self.get_localized_string("no_weapons_in_backpack"))); return

        for weapon in filtered:
            try:
                self.main_app.log(f"开始处理背包中的武器，序列号: {weapon.get('serial', 'N/A')}")
                header, component = weapon.get('decoded_full', '').split('||', 1)
                self.main_app.log("  - 已成功分离头部和组件")
                
                m_id = int(header.strip().split('|')[0].strip().split(',')[0])
                self.main_app.log(f"  - 已解析制造商ID: {m_id}")

                parsed_components = self._parse_component_string(component)
                self.main_app.log(f"  - 已解析出 {len(parsed_components)} 个组件")

                _, name, _, _ = self._get_rarity_and_weapon_name(parsed_components, m_id)
                self.main_app.log(f"  - 已获取武器名称: {name}")
                
                w_name = self.get_localized_string(name, name)
                disp_name = f"{weapon.get('manufacturer', '未知')} {weapon.get('type', '未知物品')} ({w_name})" if w_name not in ["N/A", "Unknown", "未知"] else f"{weapon.get('manufacturer', '未知')} {weapon.get('type', '未知物品')}"
                btn_text = f"{disp_name} - {self.get_localized_string('level_label')}: {weapon.get('level', 'N/A')} - {self.get_localized_string('slot_label')}: {weapon.get('slot', 'N/A').replace('slot_', '')}"
                btn = QtWidgets.QPushButton(btn_text)
                btn.clicked.connect(partial(self.load_weapon_data, weapon))
                self.backpack_items_layout.addWidget(btn)
                self.main_app.log(f"  - 成功创建并添加武器按钮: {btn_text}")

            except Exception as e:
                self.main_app.log(f"在处理背包武器时发生严重错误。序列号: {weapon.get('serial', '未知')}，错误: {e}")
                # 创建一个错误按钮以提供反馈
                error_btn = QtWidgets.QPushButton(f"错误: 无法加载序列号为 {weapon.get('serial', '未知')} 的武器")
                error_btn.setStyleSheet("background-color: #581b1b;")
                self.backpack_items_layout.addWidget(error_btn)

    def update_weapon(self):
        if not self.selected_weapon_path:
            QtWidgets.QMessageBox.warning(self, self.get_localized_string("no_selection"), self.get_localized_string("select_weapon_first"))
            return

        new_serial, err = b_encoder.encode_to_base85(self.serial_decoded_entry.text().strip())
        if err:
            QtWidgets.QMessageBox.critical(self, self.get_localized_string("encoding_fail"), f"{self.get_localized_string('cannot_reencode_serial')}: {err}")
            return

        # 构造符合新 update_item 签名的载荷
        # 我们假设原始数据没有改变，只更新序列号
        # original_item_data 和 new_item_data 可以是部分数据
        payload = {
            'item_path': self.selected_weapon_path,
            'original_item_data': {}, # 留空，让controller自行处理
            'new_item_data': {'serial': new_serial},
            'success_msg': self.get_localized_string('update_success')
        }
        self.update_item_requested.emit(payload)

    def add_new_weapon_to_backpack(self):
        new_decoded = self.serial_decoded_entry.text().strip()
        if not new_decoded:
            QtWidgets.QMessageBox.warning(self, self.get_localized_string("no_input"), self.get_localized_string("serial_empty"))
            return
        new_serial, err = b_encoder.encode_to_base85(new_decoded)
        if err:
            QtWidgets.QMessageBox.critical(self, self.get_localized_string("encoding_fail"), f"{self.get_localized_string('cannot_encode_serial')}: {err}")
            return
        
        # 使用 flag_combo 的值
        self.add_to_backpack_requested.emit(new_serial, self.flag_combo.currentText().split(" ")[0])

    def open_add_part_window(self):
        if not self.serial_decoded_entry.text():
            QtWidgets.QMessageBox.warning(self, self.get_localized_string("no_weapon"), self.get_localized_string("load_weapon_first")); return
        
        win = QtWidgets.QDialog(self)
        win.setObjectName("addPartDialog")
        win.setWindowTitle(self.get_localized_string("add_part_title"))
        win.setMinimumSize(900, 700)
        win.setModal(True)
        
        layout = QtWidgets.QVBoxLayout(win)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # Header label with objectName for theme-aware styling
        header_label = QtWidgets.QLabel(self.get_localized_string("select_parts_to_add"))
        header_label.setObjectName("addPartDialogHeader")
        layout.addWidget(header_label)
        
        self.selected_parts_to_add = []
        
        # Scroll area for part categories (styled by QSS)
        scroll_frame = QtWidgets.QScrollArea()
        scroll_frame.setWidgetResizable(True)
        
        scroll_content = QtWidgets.QWidget()
        scroll_layout = QtWidgets.QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(8)
        scroll_layout.setContentsMargins(5, 5, 5, 5)
        
        # Elemental category
        elemental_container = self._create_add_part_category(
            self.get_localized_string("Elemental"), 
            lambda p, d: self.create_elemental_list(p, d), 
            self.elemental_df,
            color="#EF9A9A"
        )
        scroll_layout.addWidget(elemental_container)
        
        # Weapon type categories
        for wt, group in self.all_weapon_parts_df.groupby('Weapon Type'):
            localized_wt = self.get_localized_string(wt)
            scroll_layout.addWidget(self._create_add_part_category(
                localized_wt, 
                self.create_manufacturer_list, 
                group,
                color="#64B5F6"
            ))
        
        scroll_layout.addStretch()
        scroll_frame.setWidget(scroll_content)
        layout.addWidget(scroll_frame, 1)  # stretch factor 1
        
        # Confirm button with styling
        confirm_btn = QtWidgets.QPushButton(self.get_localized_string("confirm_add"))
        confirm_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                padding: 12px 24px;
                border-radius: 5px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #66BB6A;
            }
            QPushButton:pressed {
                background-color: #388E3C;
            }
        """)
        confirm_btn.clicked.connect(lambda: self.add_selected_parts(win))
        layout.addWidget(confirm_btn)
        
        win.exec()

    def _create_add_part_category(self, title, content_creator_func, data, color="#e0e0e0"):
        container = QtWidgets.QFrame()
        container.setObjectName("addPartCategoryFrame")
        container_layout = QtWidgets.QVBoxLayout(container)
        container_layout.setContentsMargins(8, 8, 8, 8)
        container_layout.setSpacing(5)
        
        # Header with toggle button and styled title
        header = QtWidgets.QFrame()
        header_layout = QtWidgets.QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        
        content = QtWidgets.QFrame()
        content.setVisible(False)
        
        toggle_btn = QtWidgets.QPushButton("▶")
        toggle_btn.setFixedSize(28, 28)
        # Use minimal styling, let theme handle colors
        toggle_btn.setObjectName("addPartToggleBtn")
        toggle_btn.clicked.connect(lambda: self._toggle_lazy_load(content, toggle_btn, content_creator_func, data))
        
        title_label = QtWidgets.QLabel(title)
        title_label.setObjectName("addPartTitleLabel")
        # Store category color as property; theme stylesheet will handle base text color for readability
        title_label.setProperty("partColor", color)
        
        header_layout.addWidget(toggle_btn)
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        
        container_layout.addWidget(header)
        container_layout.addWidget(content)
        return container

    def _toggle_lazy_load(self, frame, button, creator_func, data):
        if not frame.layout(): layout = QtWidgets.QVBoxLayout(frame); creator_func(layout, data)
        is_visible = not frame.isVisible(); frame.setVisible(is_visible)
        button.setText("▼" if is_visible else "▶")
        
    def create_elemental_list(self, parent_layout, df):
        # Use English keys for localization - "elements" and "element_switch" are in weapon_localization
        self._create_elemental_subsection(parent_layout, "elements", df[df['Part_ID'].between(10, 14)])
        self._create_elemental_subsection(parent_layout, "element_switch", df[~df['Part_ID'].between(10, 14)])

    def _create_elemental_subsection(self, parent_layout, title, df):
        parent_layout.addWidget(self._create_add_part_category(self.get_localized_string(title), self._populate_elemental_parts, df))

    def _populate_elemental_parts(self, layout, df):
        for _, row in df.iterrows():
            var = QtWidgets.QCheckBox(f"{row['Elemental_ID']}:{row['Part_ID']} | {self.get_localized_string(row['Stat'])}")
            layout.addWidget(var)
            self.selected_parts_to_add.append({'var': var, 'id': row['Part_ID'], 'mfg_id': 1, 'type': 'elemental'})

    def create_manufacturer_list(self, parent_layout, data_group):
        for mfg, mfg_group in data_group.groupby('Manufacturer'):
            parent_layout.addWidget(self._create_add_part_category(self.get_localized_string(mfg), self.populate_add_part_list, mfg_group))

    def populate_add_part_list(self, parent_layout, parts_group):
        for _, row in parts_group.iterrows():
            part_frame = QtWidgets.QFrame(); part_layout = QtWidgets.QHBoxLayout(part_frame); part_layout.setContentsMargins(0,0,0,0); part_layout.setSpacing(5)
            var = QtWidgets.QCheckBox(f"{row['Part ID']} | {self.get_localized_string(row['Part Type'])} | {row['String']} | {str(row['Stat']) if pd.notna(row['Stat']) else ''}")
            qty_entry = QtWidgets.QLineEdit("1"); qty_entry.setFixedWidth(40); qty_entry.setVisible(False)
            var.toggled.connect(qty_entry.setVisible)
            part_layout.addWidget(var); part_layout.addWidget(qty_entry); parent_layout.addWidget(part_frame)
            self.selected_parts_to_add.append({'var': var, 'id': row['Part ID'], 'mfg_id': row['Manufacturer & Weapon Type ID'], 'entry': qty_entry})

    def _build_part_strings(self, parts_by_mfg, current_weapon_mfg_id):
        new_parts_list = []
        for mfg_id, parts in parts_by_mfg.items():
            elemental_parts = [f"{{1:{p['id']}}}" for p in parts if p['type'] == 'elemental']
            normal_parts = [p['id'] for p in parts if p['type'] == 'normal']

            if mfg_id == 1:  # Elemental parts mfg_id is 1
                new_parts_list.extend(elemental_parts)
            elif mfg_id == current_weapon_mfg_id:
                new_parts_list.extend([f"{{{pid}}}" for pid in normal_parts])
            elif normal_parts:
                new_parts_list.append(f"{{{mfg_id}:[{' '.join(map(str, sorted(normal_parts)))}]}}")
        return new_parts_list

    def add_selected_parts(self, window):
        parts_by_mfg = {}
        try:
            current_weapon_mfg_id = int(self.serial_decoded_entry.text().split(',')[0])
        except (ValueError, IndexError):
            QtWidgets.QMessageBox.critical(self, self.get_localized_string("error"), self.get_localized_string("cannot_determine_mfg"))
            return window.close()

        for item in self.selected_parts_to_add:
            if item['var'].isChecked():
                mfg_id = int(item['mfg_id'])
                parts_by_mfg.setdefault(mfg_id, [])
                if item.get('type') == 'elemental':
                    parts_by_mfg[mfg_id].append({'id': item['id'], 'type': 'elemental'})
                elif 'entry' in item and (num_parts := item['entry'].text()).isdigit():
                    parts_by_mfg[mfg_id].extend([{'id': item['id'], 'type': 'normal'}] * int(num_parts))

        if not parts_by_mfg:
            return window.close()

        new_parts_list = self._build_part_strings(parts_by_mfg, current_weapon_mfg_id)
        if not new_parts_list:
            return window.close()

        new_part_data = self._parse_component_string(" ".join(new_parts_list))

        # Find the last non-skin part index to insert after
        insertion_index = len(self.parts_data)
        for i in range(len(self.parts_data) - 1, -1, -1):
            part = self.parts_data[i]
            if isinstance(part, dict) and part.get('type') != 'skin':
                insertion_index = i + 1
                break
        
        # Insert a space if needed before adding new parts
        if insertion_index > 0:
            prev_item = self.parts_data[insertion_index - 1]
            if (isinstance(prev_item, dict)) or (isinstance(prev_item, str) and prev_item.strip()):
                self.parts_data.insert(insertion_index, ' ')
                insertion_index += 1
        
        self.parts_data[insertion_index:insertion_index] = new_part_data
        
        self.regenerate_ui_and_serial()
        self.main_app.log(f"Added {len(new_part_data)} new part(s).")
        window.close()

    def open_select_skin_window(self, part_index):
        win = QtWidgets.QDialog(self); win.setWindowTitle(self.get_localized_string("Select Skin"))
        win.setMinimumSize(400, 500); win.setModal(True)
        layout = QtWidgets.QVBoxLayout(win); layout.addWidget(QtWidgets.QLabel(self.get_localized_string("Select a skin to apply")))
        scroll_area = QtWidgets.QScrollArea(); scroll_area.setWidgetResizable(True)
        scroll_content = QtWidgets.QWidget(); scroll_layout = QtWidgets.QVBoxLayout(scroll_content)
        for _, row in self.skin_df.iterrows():
            btn = QtWidgets.QPushButton(f"{row['Skin_ID']}: {self.get_localized_string(row['Stat'], row['Stat'])}")
            btn.clicked.connect(partial(self.update_skin, part_index, row['Skin_ID'], win)); scroll_layout.addWidget(btn)
        scroll_area.setWidget(scroll_content); layout.addWidget(scroll_area); win.exec()
    
    def _toggle_group_visibility(self, button, content_frame):
        is_visible = not content_frame.isVisible()
        content_frame.setVisible(is_visible)
        button.setText("▼" if is_visible else "▶")

    def update_skin(self, part_index, new_skin_id, window):
        if 0 <= part_index < len(self.parts_data) and isinstance(part_info := self.parts_data[part_index], dict) and part_info.get('type') == 'skin':
            part_info['id'], part_info['raw'] = new_skin_id, f' "c", {new_skin_id}'
            self.regenerate_ui_and_serial(); self.main_app.log(f"Weapon skin updated to ID: {new_skin_id}")
        else: QtWidgets.QMessageBox.critical(self, "Error", "The selected part is not a skin part.")
        window.close()

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QLabel, QLineEdit, QComboBox, QScrollArea, QFrame, QGridLayout, QMessageBox, QDialog, QCheckBox
    from PyQt6.QtGui import QIntValidator
except ImportError:
    print("PyQt6 is not installed. Please install it with: pip install PyQt6")
    sys.exit(1)

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    class MockApp:
        def log(self, m): print(f"[LOG] {m}")
        def handle_add_to_backpack(self, serial, flag): print(f"Adding to backpack: {serial}")
        @property
        def controller(self):
            class MockController:
                yaml_obj = True
                def get_all_items(self): return []
            return MockController()

    mock_app = MockApp()
    main_win = QtWidgets.QWidget()
    main_win.setWindowTitle("QT Weapon Editor Test")
    main_win.setGeometry(100, 100, 1024, 768)
    layout = QtWidgets.QVBoxLayout(main_win)
    editor = WeaponEditorTab(mock_app)
    layout.addWidget(editor)
    main_win.show()
    sys.exit(app.exec())
