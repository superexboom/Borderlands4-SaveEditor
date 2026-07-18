import random
import re
from html import escape
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QComboBox,
    QScrollArea, QMessageBox
)
from PyQt6.QtGui import QIcon, QFont
from PyQt6.QtWidgets import QToolTip
from PyQt6.QtCore import pyqtSignal

from core import b_encoder
from core import resource_loader

from .qt_catalog_picker import InlineCatalogPicker

# Current NCS uimarkuptextstyle0 FLinearColor values converted to CSS sRGB.
SKILL_TEXT_STYLES = {
    'primary': 'color: #EB7300; font-weight: 600;',
    'secondary': 'color: #2D95CA; font-weight: 600;',
    'flavor': 'color: #3F769D; font-style: italic;',
    'fire': 'color: #FF5224;',
    'shock': 'color: #2F63F9;',
    'cryo': 'color: #53FBFB;',
    'corrosive': 'color: #72F800;',
    'radiation': 'color: #F1FF00;',
    'kinetic': 'color: #E4D9CE;',
}

SKILL_IMAGE_TAGS = {
    'corrosive_icon', 'cryo_icon', 'elemental_icon', 'fire_icon', 'frtn_icon',
    'kinetic_icon', 'radiation_icon', 'shock_icon', 'wfll_icon',
}

class QtClassModEditorTab(QWidget):
    add_to_backpack_requested = pyqtSignal(str, str)
    
    # 职业ID常量
    CLASS_IDS = {'Amon': 255, 'Harlowe': 259, 'Rafa': 256, 'Vex': 254, 'C4sh': 404}
    CLASS_NAMES = ['Amon', 'Harlowe', 'Rafa', 'Vex', 'C4sh']  # 保持顺序一致

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_lang = 'zh-CN'
        self._character_level = "50"
        
        self.ui_loc = self._load_ui_localization()
        self.localization = self._load_localization()  # 仅用于职业/稀有度名称
        self.image_cache = {}
        
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

        # Special Thanks banner
        thanks_data = self.ui_loc.get('special_thanks', {})
        thanks_title = thanks_data.get('title', 'Special Thanks')
        thanks_content = thanks_data.get('content', '')
        if thanks_content:
            thanks_label = QLabel(f"<b>✨ {thanks_title}</b><br>{thanks_content.replace(chr(10), '<br>')}")
            thanks_label.setWordWrap(True)
            thanks_label.setOpenExternalLinks(True)
            thanks_label.setStyleSheet("""
                QLabel {
                    background-color: rgba(0, 150, 136, 0.08);
                    border: 1px solid rgba(0, 150, 136, 0.30);
                    border-radius: 6px;
                    color: #4dd0c8;
                    font-size: 13px;
                    padding: 8px 12px;
                    margin-top: 8px;
                }
            """)
            self.container_layout.addWidget(thanks_label)

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

    def _pick_text(self, zh, en):
        # Two-language picker retained only for CSV columns that ship just
        # zh/en data (e.g. tree_name_ZH/EN); RU/UA legitimately fall back to en
        # there because no RU/UA data exists. UI chrome uses _loc instead.
        # 仅保留用于只有 zh/en 数据的 CSV 列（如 tree_name_ZH/EN）的双语选择器；
        # 那里 RU/UA 合理回退到英文，因不存在 RU/UA 数据。界面文字改用 _loc。
        return zh if self.current_lang == 'zh-CN' else en

    def _loc(self, section, key, en, **fmt):
        """Read class_mod_tab.<section>.<key> for the active language with an
        English fallback (never Chinese/raw key), then format. All four
        languages resolve from the JSON.
        按当前语言读取 class_mod_tab.<section>.<key>，缺失时回退英文，再格式化。"""
        text = self.ui_loc.get(section, {}).get(key) or en
        return text.format(**fmt) if fmt else text

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

    def _format_perk_code(self, perk_id: str) -> str:
        """Format perk IDs for the 234 perk list.

        Numeric IDs keep the existing compact form. GB path IDs are emitted as
        quoted strings, matching the raw serial syntax used by the game.
        """
        perk_id = str(perk_id).strip()
        if not perk_id:
            return ""
        if perk_id.isdigit():
            return perk_id
        if perk_id.startswith('"') and perk_id.endswith('"'):
            return perk_id
        return f'"{perk_id}"'

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
                "tooltips": {"type": "Type"},
                "special_thanks": {"title": "Special Thanks", "content": "The design inspiration and data for this page come from @Mattmab and @Whiteshark\nIf you like this design, visit save-editor.be to try their web version"}
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
        self.level_edit = QLineEdit(self._character_level)
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

    def _create_legendary_group(self):
        leg_group = QGroupBox(self.ui_loc['legendary']['title'])
        layout = QVBoxLayout(leg_group)

        self.leg_picker = InlineCatalogPicker(
            stackable=False,
            search_placeholder=self._loc('legendary', 'search_placeholder', "Search..."),
            clear_text=self.ui_loc['legendary'].get('clear', self._pick_text("清空", "Clear")),
        )
        self.leg_picker.changed.connect(self.update_string)
        layout.addWidget(self.leg_picker)

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
        flags_map = resource_loader.get_flag_labels(self.current_lang)
        flag_values = [flags_map[k] for k in ("1", "3", "5", "17", "33", "65", "129")]
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
        
        self.skill_picker = InlineCatalogPicker(
            stackable=True,
            search_placeholder=self.ui_loc['skills']['search_placeholder'],
            clear_text=self.ui_loc['perks'].get('clear', self._pick_text("清空", "Clear")),
        )
        self.skill_picker.list.setMinimumHeight(420)
        self.skill_picker.changed.connect(self.update_string)
        skills_layout.addWidget(self.skill_picker)
        
        self.container_layout.addWidget(skills_group, 3)

        # Perks
        perks_group = QGroupBox(self.ui_loc['perks']['title'])
        perks_group.setMinimumHeight(250)
        perks_layout = QVBoxLayout(perks_group)
        self.perk_picker = InlineCatalogPicker(
            stackable=True,
            search_placeholder=self.ui_loc['perks'].get('search_placeholder', self._pick_text("搜索…", "Search...")),
            clear_text=self.ui_loc['perks'].get('clear', self._pick_text("清空", "Clear")),
        )
        self.perk_picker.list.setMinimumHeight(286)
        self.perk_picker.changed.connect(self.update_string)
        perks_layout.addWidget(self.perk_picker)
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
        self.skill_picker.clear()
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

    def update_string(self, *args):
        """生成序列化字符串 - 使用CSV数据源"""
        if not self.names_data or not self.name_combo.currentText():
            self.full_string_output.setText("...")
            self.base85_output.setText("...")
            return

        try:
            current_class_en = self._get_current_class_en()
            current_class_id = str(self.CLASS_IDS.get(current_class_en, 0))
            
            level_val = self.level_edit.text() if hasattr(self, 'level_edit') else self._character_level
            if not level_val: level_val = self._character_level
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
                    "Amon": {"Common": 70, "Uncommon": 69, "Rare": 68, "Epic": 67},
                    "C4sh": {"Common": 52, "Uncommon": 53, "Rare": 54, "Epic": 55}
                }
                rarity_code_val = PER_CLASS_RARITIES.get(current_class_en, {}).get(rarity_en, "")
            rarity_chunk = f"{{{rarity_code_val}}}" if rarity_code_val else ""

            # 传奇附加
            leg_extras_codes = [f"{{{e['data']['name_code']}}}" for e in self.leg_picker.entries()]
            leg_extras_chunk = " ".join(leg_extras_codes)

            skill_chunks = []
            for entry in self.skill_picker.entries():
                codes = entry["data"]["codes"]
                skill_chunks.extend([f"{{{code}}}" for code in codes[:entry["count"]]])
            skills_chunk = " ".join(skill_chunks)
            
            # Perks - numeric IDs go into 234; GB path IDs are emitted as standalone quoted fields.
            perk_codes = []
            special_perk_codes = []
            for e in self.perk_picker.entries():
                perk_id = e["data"]["perk_id"]
                count = e["count"]
                if not perk_id:
                    continue
                perk_code = self._format_perk_code(perk_id)
                for _ in range(count):
                    if str(perk_id).strip().isdigit():
                        perk_codes.append(perk_code)
                    else:
                        special_perk_codes.append(perk_code)

            perks_chunk = f" {{234:[{ ' '.join(perk_codes) }]}}" if perk_codes else ""
            special_perks_chunk = " ".join(special_perk_codes)

            parts = [header, rarity_chunk, name_chunk, leg_extras_chunk, skills_chunk, perks_chunk, special_perks_chunk]
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
        """填充传奇附加目录 - 使用 CatalogPicker"""
        is_legendary = self.rarity_combo.currentText() == self._("Legendary")
        self.leg_picker.setEnabled(is_legendary)

        if not is_legendary:
            self.leg_picker.clear()
            self.leg_picker.set_source([])
            return

        current_class_en = self._get_current_class_en()
        current_class_id = str(self.CLASS_IDS.get(current_class_en, 0))
        if not current_class_en:
            return

        legendary_names = self.names_by_class_rarity.get((current_class_id, 'legendary'), [])
        primary_name_display = self.name_combo.currentText()

        items = []
        primary_key = None
        for name_row in legendary_names:
            name_en = name_row.get('name_EN', '')
            name_zh = name_row.get('name_ZH', '')
            name_code = name_row.get('name_code', '')

            display_name = name_zh if (self.current_lang == 'zh-CN' and name_zh) else name_en

            if display_name == primary_name_display:
                primary_key = name_code
                continue

            items.append({
                "key": name_code,
                "label": f"{display_name} {{{name_code}}}",
                "category": None,
                "subcategory": None,
                "data": {"name_code": name_code},
            })

        if not preserve_selection:
            self.leg_picker.clear()
        self.leg_picker.set_source(items)
        # 主名不能同时作为传奇附加
        if primary_key is not None:
            self.leg_picker.remove_key(primary_key)

    def populate_perks(self):
        """填充可筛选的通用专长目录。"""
        categories = [
            ("all", self._loc('perk_filters', 'all', "All")),
            ("weapon", self._loc('perk_filters', 'weapon', "Weapon")),
            ("skill", self._loc('perk_filters', 'skill', "Skill")),
            ("element", self._loc('perk_filters', 'element', "Element")),
            ("defense", self._loc('perk_filters', 'defense', "Defense")),
            ("utility", self._loc('perk_filters', 'utility', "Utility")),
            ("firmware", self._loc('perk_filters', 'firmware', "Firmware")),
            ("other", self._loc('perk_filters', 'other', "Other")),
        ]
        self.perk_picker.set_categories(categories, columns=4)
        items = []
        for perk_row in self.perks_data:
            perk_id = perk_row.get('perk_ID', '')
            perk_en = perk_row.get('perk_name_EN', '')
            perk_zh = perk_row.get('perk_name_ZH', '')
            internal = perk_row.get('perk_internal', '')
            category = perk_row.get('perk_category', 'other') or 'other'
            display_name = perk_zh if self.current_lang == 'zh-CN' and perk_zh else perk_en
            detail = f"{internal}  ·  ID {perk_id}" if internal else f"ID {perk_id}"

            items.append({
                "key": perk_id,
                "label": display_name,
                "detail": detail,
                "category": category,
                "accent": "blue" if category == "firmware" else None,
                "search_text": f"{perk_id} {internal} {perk_en} {perk_zh}",
                "tooltip": escape(detail),
                "data": {"perk_id": perk_id},
            })
        self.perk_picker.set_source(items)

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

    def get_skill_icon(self, icon_file, class_name):
        if not icon_file:
            return QIcon()
        cache_key = f"{class_name}/{icon_file}"
        if cache_key in self.image_cache:
            return self.image_cache[cache_key]

        try:
            path = resource_loader.get_class_mods_image_path(class_name, icon_file)
            if path and Path(path).exists():
                icon = QIcon(str(path))
                self.image_cache[cache_key] = icon
                return icon
        except Exception as e:
            print(f"Could not load icon {icon_file}: {e}")
        return QIcon() # Return empty icon on failure

    @staticmethod
    def _skill_description_html(value):
        text = escape(str(value or '')).replace('[newline]', '<br>').replace('\n', '<br>')
        for tag in SKILL_IMAGE_TAGS:
            text = text.replace(f'[{tag}]', '')
        for tag, style in SKILL_TEXT_STYLES.items():
            text = text.replace(f'[{tag}]', f"<span style='{style}'>")
            text = text.replace(f'[/{tag}]', '</span>')
        text = text.replace('[nowrap]', "<span style='white-space: nowrap;'>").replace('[/nowrap]', '</span>')
        text = text.replace('[glyph]', "<span style='color: #F9F3DE; font-weight: 600;'>").replace('[/glyph]', '</span>')
        return re.sub(r'\[/?[a-z][a-z0-9_]*\]', '', text, flags=re.IGNORECASE).strip()

    def populate_skills(self):
        """填充按三色技能树筛选的单列技能目录。"""
        current_class_en = self._get_current_class_en()
        current_class_id = str(self.CLASS_IDS.get(current_class_en, 0))
        if not current_class_en: return

        skills_list = self.skills_by_class.get(current_class_id, [])
        tree_names = {}
        for row in skills_list:
            color = row.get('tree_color', '')
            if color:
                tree_names[color] = self._pick_text(row.get('tree_name_ZH', ''), row.get('tree_name_EN', ''))
        color_labels = {
            "red": self._loc('skill_trees', 'red', "Red"),
            "green": self._loc('skill_trees', 'green', "Green"),
            "blue": self._loc('skill_trees', 'blue', "Blue"),
        }
        categories = [("all", self._loc('skill_trees', 'all_skills', "All Skills"))]
        for color in ("red", "green", "blue"):
            name = tree_names.get(color, color_labels[color])
            categories.append((color, f"{color_labels[color]} · {name}"))
        self.skill_picker.set_categories(categories, columns=4)

        items = []
        color_order = {"red": 0, "green": 1, "blue": 2}
        for skill_row in sorted(skills_list, key=lambda row: (color_order.get(row.get('tree_color', ''), 9), row.get('skill_name_EN', ''))):
            skill_en = skill_row.get('skill_name_EN', '')
            skill_zh = skill_row.get('skill_name_ZH', '')
            localized_name = skill_zh if self.current_lang == 'zh-CN' and skill_zh else skill_en
            display_name = re.sub(r" [BGR]$", "", localized_name) if current_class_en == "C4sh" else localized_name

            codes = []
            for i in range(1, 6):
                code = skill_row.get(f'skill_ID_{i}', '')
                if code:
                    codes.append(int(code))

            tooltip_html = ""
            desc_text = self._pick_text(
                skill_row.get('description_ZH', ''),
                skill_row.get('description_EN', ''),
            )
            if desc_text:
                skill_type = self._loc('skill_trees', 'passive', "Passive") if skill_row.get('skill_type') == 'passive' else skill_row.get('skill_type', '')
                desc_html = self._skill_description_html(desc_text)
                tooltip_html = f"""
                    <div style='width: 390px; white-space: normal;'>
                        <p><b>{escape(display_name)}</b></p>
                        <p><i>{escape(self.ui_loc['tooltips']['type'])}: {escape(str(skill_type))}</i></p>
                        <hr>
                        <p>{desc_html}</p>
                    </div>
                """
            color = skill_row.get('tree_color', '')
            tree_name = self._pick_text(skill_row.get('tree_name_ZH', ''), skill_row.get('tree_name_EN', ''))
            stable_key = skill_row.get('skill_key') or f"{current_class_id}:{codes[0] if codes else skill_en}"
            items.append({
                "key": stable_key,
                "label": display_name,
                "detail": tree_name,
                "category": color,
                "accent": color,
                "icon": self.get_skill_icon(skill_row.get('icon_file', ''), current_class_en),
                "tooltip": tooltip_html,
                "max_count": len(codes),
                "search_text": f"{skill_en} {skill_zh} {tree_name} {skill_row.get('skill_internal', '')}",
                "data": {"codes": codes, "skill_key": stable_key},
            })
        self.skill_picker.set_source(items)

    def set_character_level(self, level: str):
        """设置角色等级，更新默认等级显示。"""
        self._character_level = level if level else "50"
        if hasattr(self, 'level_edit'):
            self.level_edit.setText(self._character_level)
