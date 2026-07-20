from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QGroupBox, QComboBox, QCheckBox, QMessageBox, QScrollArea
from PyQt6.QtCore import pyqtSignal
import random

from core import b_encoder
from core import resource_loader

from .qt_catalog_picker import CatalogPicker

enhancement_data = resource_loader.get_enhancement_data()

class QtEnhancementEditorTab(QWidget):
    add_to_backpack_requested = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_lang = 'zh-CN'
        self._character_level = "50"
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
                            "no_valid_code": "No valid code", "gen_valid_first": "Generate first"},
                "special_thanks": {"title": "Special Thanks", "content": "The design inspiration and data for this page come from @Mattmab and @Whiteshark\nIf you like this design, visit save-editor.be to try their web version"}
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
        self.level_edit = QLineEdit(self._character_level)
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
        self.stack_picker = CatalogPicker(
            stackable=True,
            search_placeholder=self._loc('picker', 'search_placeholder', "Search..."),
            avail_title=self._loc('picker', 'available', "Available (double-click to add)"),
            selected_title=self._loc('picker', 'selected_stacks', "Selected Stacks"),
            clear_text=self.ui_loc.get('buttons', {}).get('clear', self._pick_text("清空", "Clear")),
        )
        self.stack_picker.changed.connect(self.rebuild_output)
        stacking_layout.addWidget(self.stack_picker)
        main_layout.addWidget(stacking_group)

        # 247 Builder (secondary stats) with weapon / firmware categories
        builder_247_group = QGroupBox(self.ui_loc['groups']['builder_247'])
        builder_247_layout = QVBoxLayout(builder_247_group)
        self.stat_picker = CatalogPicker(
            stackable=True,
            search_placeholder=self._loc('picker', 'search_placeholder', "Search..."),
            avail_title=self._loc('picker', 'available', "Available (double-click to add)"),
            selected_title=self._loc('picker', 'selected_stats', "Selected Stats"),
            clear_text=self.ui_loc.get('buttons', {}).get('clear', self._pick_text("清空", "Clear")),
        )
        self.stat_picker.set_categories([(k, self._cat_label(k)) for k in
                                         ['all', 'firmware', 'sniper', 'shotgun', 'smg', 'pistol', 'ar', 'gun']], columns=4)
        self.stat_picker.set_subcategories([(k, self._sub_label(k)) for k in
                                            ['all', 'dmg', 'crit', 'firerate', 'acc', 'reload', 'mag',
                                             'splashdmg', 'splashradius', 'ads', 'se_dmg', 'se_chance', 'equip']], columns=4)
        self.stat_picker.changed.connect(self.rebuild_output)
        self._populate_stat_picker()
        builder_247_layout.addWidget(self.stat_picker)
        main_layout.addWidget(builder_247_group)

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
            main_layout.addWidget(thanks_label)

        main_layout.addStretch()

    def populate_initial_data(self):
        mfg_names = sorted(enhancement_data.get('manufacturers', {}).keys())
        self.mfg_sel.addItems([self._(name) for name in mfg_names])
        if mfg_names:
            self.mfg_sel.setCurrentText(self._(mfg_names[0]))
        self.on_mfg_change()

    def on_mfg_change(self, *args):
        self.set_rarities_for_mfg()
        self.set_perk_checkboxes()
        self._populate_stack_picker()
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

    def _pick_text(self, zh, en):
        return zh if self.current_lang == 'zh-CN' else en

    def _loc(self, section, key, en, **fmt):
        """Active-language read of enhancement_tab.<section>.<key> with an
        English fallback (never Chinese/raw key), then format.
        按当前语言读取 enhancement_tab.<section>.<key>，缺失回退英文再格式化。"""
        text = self.ui_loc.get(section, {}).get(key) or en
        return text.format(**fmt) if fmt else text

    _CAT_LABEL_FALLBACKS = {
        'all': 'All', 'firmware': 'Firmware', 'sniper': 'Sniper', 'shotgun': 'Shotgun',
        'smg': 'SMG', 'pistol': 'Pistol', 'ar': 'AR', 'gun': 'Universal',
    }
    _SUB_LABEL_FALLBACKS = {
        'all': 'All', 'dmg': 'Damage', 'crit': 'Crit DMG', 'firerate': 'Fire Rate', 'acc': 'Accuracy',
        'reload': 'Reload', 'mag': 'Magazine', 'splashdmg': 'Splash DMG', 'splashradius': 'Splash Radius',
        'ads': 'ADS', 'se_dmg': 'SE DMG', 'se_chance': 'SE Chance', 'equip': 'Equip', 'other': 'Other',
    }
    _WEAPON_FIRST = {'Sniper': 'sniper', 'Shotgun': 'shotgun', 'SMG': 'smg',
                     'Pistol': 'pistol', 'AR': 'ar', 'Gun': 'gun'}

    def _cat_label(self, key):
        return self._loc('categories', key, self._CAT_LABEL_FALLBACKS.get(key, key))

    def _sub_label(self, key):
        return self._loc('subcategories', key, self._SUB_LABEL_FALLBACKS.get(key, key))

    def _stat_subcategory(self, name_en):
        # 大小写不敏感匹配；多词关键字优先；兼容 CSV 里个别拼写错误
        n = name_en.lower()
        checks = [
            ("crit dmg", "crit"), ("splash dmg", "splashdmg"), ("splash radius", "splashradius"),
            ("spalsh radius", "splashradius"), ("status effect dmg", "se_dmg"),
            ("status effect chance", "se_chance"), ("status effect smg", "se_dmg"),
            ("effect chance", "se_chance"), ("fire rate", "firerate"), ("reload", "reload"),
            ("mag", "mag"), ("ads", "ads"), ("acc", "acc"), ("equip", "equip"),
            ("splash", "splashdmg"), ("dmg", "dmg"),
        ]
        for kw, key in checks:
            if kw in n:
                return key
        return "other"

    def _classify_247(self, name_en):
        """首词=武器类型即归对应武器；否则归“固件”。返回 (category, subcategory)。
        固件是具名整枪词条、没有属性类型，故二级分类留空(None)，不塞进“其他”。"""
        first = name_en.split(' ', 1)[0] if name_en else ""
        category = self._WEAPON_FIRST.get(first, "firmware")
        if category == "firmware":
            return "firmware", None
        return category, self._stat_subcategory(name_en)

    def _populate_stat_picker(self):
        items = []
        for stat in enhancement_data.get('secondary_247', []):
            code = stat['code']
            name_en = stat['name']
            cat, sub = self._classify_247(name_en)
            items.append({
                "key": code,
                "label": f"[{code}] {self._(name_en)}",
                "category": cat,
                "subcategory": sub,
                "data": {"code": code},
            })
        self.stat_picker.set_source(items)

    def _populate_stack_picker(self):
        current_mfg_en = self._get_current_mfg_en_name()
        cats = [("all", self._cat_label('all'))]
        items = []
        for mfg, data in enhancement_data.get('manufacturers', {}).items():
            if mfg == current_mfg_en:
                continue
            cats.append((mfg, self._(mfg)))
            for perk in data.get('perks', []):
                if perk.get('index') in [1, 2, 3, 9]:
                    idx = perk['index']
                    items.append({
                        "key": f"{mfg}:{idx}",
                        "label": f"[{idx}] {self._(perk['name'])} \u2014 {self._(mfg)}",
                        "category": mfg,
                        "subcategory": None,
                        "data": {"mfg": mfg, "idx": idx},
                    })
        items.sort(key=lambda x: (x['category'], x['data']['idx']))
        self.stack_picker.set_categories(cats)
        self.stack_picker.set_source(items)

    def rebuild_output(self, *args):
        parts = []
        mfg_en = self._get_current_mfg_en_name()
        if not mfg_en: return
        mfg_code = enhancement_data['manufacturers'][mfg_en]['code']
        
        level_val = self.level_edit.text() if hasattr(self, 'level_edit') else self._character_level
        if not level_val: level_val = self._character_level
        
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
        for e in self.stack_picker.entries():
            mfg_en_stack = e["data"]["mfg"]
            perk_idx = e["data"]["idx"]
            mfg_code_stack = enhancement_data['manufacturers'][mfg_en_stack]['code']
            stacked_perks.setdefault(mfg_code_stack, [])
            for _ in range(e["count"]):
                stacked_perks[mfg_code_stack].append(perk_idx)

        for code, indices in stacked_perks.items():
            parts.append(f"{{{code}:[{' '.join(map(str, sorted(indices)))}]}}")

        stats_247 = []
        for e in self.stat_picker.entries():
            val = e["data"]["code"]
            for _ in range(e["count"]):
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

    def set_character_level(self, level: str):
        """设置角色等级，更新默认等级显示。"""
        self._character_level = level if level else "50"
        if hasattr(self, 'level_edit'):
            self.level_edit.setText(self._character_level)
