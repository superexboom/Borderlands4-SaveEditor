import random
import re
import traceback
from html import escape
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QComboBox, QToolTip,
    QScrollArea, QMessageBox, QSplitter
)
from PyQt6.QtGui import QIcon, QFont
from PyQt6.QtCore import pyqtSignal, Qt

from core import b_encoder
from core import item_display_resolver, resource_loader

from tabs.qt_catalog_picker import InlineCatalogPicker
from tabs.qt_item_browser import ItemBrowser, ROW_HEIGHT
from tabs.qt_editor_shared import (
    Token,
    TokenOrderedState,
    C4SH_TREE_SUFFIX_RE,
    emit_update_or_warn,
    log_editor,
    make_header_getter,
    set_flag_from_item,
    summarize_item,
)

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
    update_item_requested = pyqtSignal(dict)

    _LOG_TAG = "class_mod"

    # 职业ID常量
    CLASS_IDS = {'Amon': 255, 'Harlowe': 259, 'Rafa': 256, 'Vex': 254, 'C4sh': 404}
    CLASS_NAMES = ['Amon', 'Harlowe', 'Rafa', 'Vex', 'C4sh']  # 保持顺序一致

    # {27} is appended after the primary name for Harlowe legendaries; not a
    # widget-owned token, must be silently skipped by the reverse parser.
    _HARLOWE_LEGENDARY_MARKER = 27

    def __init__(self, main_app=None, parent=None):
        super().__init__(parent)
        self.main_app = main_app
        self.current_lang = 'zh-CN'
        self._character_level = "50"

        self.ui_loc = self._load_ui_localization()
        self.localization = self._load_localization()  # 仅用于职业/稀有度名称
        self.image_cache = {}

        # State for backpack browser + reverse-parser flow
        self.selected_item_path = None
        self._is_loading = False
        # Token-preserving state; fixes the sub-part sort bug — source
        # {234:[96 61]} was rebuilt as sorted [61 96]. Every rebuild routes
        # through ``state.render()``; the token stream is authoritative. Value edits
        # (level/seed) are picked up via the header binding; the {234:[...]}
        # perk list stays UNBOUND so its source raw form is emitted verbatim
        # on load-then-level-edit-then-save (preserves the [96 61] source
        # order and any unknown perk children). Structural edits (picker add/
        # remove, class/rarity/name change) surgically remove class-mod-derived
        # tokens (those whose values match known rarity/name/skill/perk IDs
        # for the current class) and re-insert from widget state. Any token
        # NOT in a known category — including unknown perk-list groups and
        # unknown standalone simples — is preserved verbatim.
        self._token_state = TokenOrderedState([])
        self._preserved_unknowns: dict[int, list[int]] = {}
        self._populating = False

        # 加载CSV数据
        self._load_csv_data()

        # Set a global font for tooltips for better readability
        font = QFont()
        font.setPointSize(12) # Larger font size
        QToolTip.setFont(font)

        # Splitter + browser are built ONCE here — _rebuild_ui only recreates
        # the inner scroll_area widget on language change, so the browser must
        # sit outside that hierarchy to survive.
        main_layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        main_layout.addWidget(splitter)

        self.browser = ItemBrowser(
            main_app=self.main_app,
            item_filter=self._is_class_mod_item,
            row_builder=self._class_mod_browser_row,
            header_label=self.ui_loc.get('labels', {}).get('load_from_backpack', 'Load from Backpack'),
            search_placeholder=self.ui_loc.get('labels', {}).get('search_class_mod_placeholder', 'Search class mod...'),
            empty_placeholder=self.ui_loc.get('dialogs', {}).get('no_class_mods_in_backpack', 'No class mods in backpack'),
            no_save_placeholder=self.ui_loc.get('dialogs', {}).get('decrypt_save_to_show', 'Decrypt save first'),
            summary_formatter=self._summarize_class_mod,
            summary_none_text=self.ui_loc.get('summary', {}).get('none_selected', 'No backpack class mod selected'),
        )
        self.browser.item_selected.connect(self._load_class_mod_item)
        splitter.addWidget(self.browser)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        splitter.addWidget(self.scroll_area)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([320, 1040])

        self._rebuild_ui()
        self.refresh_backpack_items()

    def _rebuild_ui(self):
        # Clean up old container if exists
        old_widget = self.scroll_area.widget()
        if old_widget:
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
            thanks_label.setObjectName("classModThanksBanner")
            thanks_label.setWordWrap(True)
            thanks_label.setOpenExternalLinks(True)
            self.container_layout.addWidget(thanks_label)

        self.populate_initial_data()
        self._connect_signals()
        
    def _(self, text):
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

    def _display_name(self, zh, en):
        """Return the zh name in Chinese mode when populated, else en.

        Shared by every CSV-driven picker row that carries paired name_ZH /
        name_EN columns (names / legendary extras / perks / skills)."""
        return zh if (self.current_lang == 'zh-CN' and zh) else en

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
        discovered_classes = {}
        for row in [*self.names_data, *self.skills_data]:
            class_id = str(row.get('class_ID', '')).strip()
            class_name = str(row.get('class_name', '')).strip()
            if class_id.isdigit() and class_name:
                discovered_classes[class_name] = int(class_id)
        if discovered_classes:
            known = [name for name in type(self).CLASS_NAMES if name in discovered_classes]
            self.CLASS_NAMES = known + [name for name in discovered_classes if name not in known]
            self.CLASS_IDS = {**type(self).CLASS_IDS, **discovered_classes}

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

        # 按 (class_ID, L_name_ID) 索引 legendary item card IDs. update_string's
        # rebuild used to walk legendary_map_data linearly per rebuild — indexing
        # once here turns the O(N) scan into a dict lookup and, more usefully,
        # gives a single place a future data change updates.
        self.legendary_code_by_class_name = {}
        for row in self.legendary_map_data:
            # Cast on ingestion — future CSV loads may hand back int-typed
            # L_name_ID (pandas type inference on an all-numeric column),
            # while the lookup site (~L552) always keys with str(name_code).
            # Mismatched key types would silently miss and return default.
            key = (str(row.get('class_ID', '')), str(row.get('L_name_ID', '')))
            self.legendary_code_by_class_name[key] = str(row.get('item_card_ID', ''))

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
        if lang in ('en-US', 'ru', 'ua'):
            return {}
        try:
            return resource_loader.load_class_mods_json("class_localization.json") or {}
        except Exception as e:
            log_editor(self.main_app, self._LOG_TAG, f"加载本地化文件失败: {e}")
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
        log_editor(self.main_app, self._LOG_TAG, f"Updating language for {self.__class__.__name__} to {lang}...")
        self.current_lang = lang
        self.ui_loc = self._load_ui_localization(lang)
        self.localization = self._load_localization(lang)

        # Save state — seed_edit is unconditionally recreated by _rebuild_ui →
        # _create_top_controls, so no hasattr guard is needed post-rebuild.
        curr_seed = self.seed_edit.text() if hasattr(self, 'seed_edit') else ""

        self._rebuild_ui()

        if curr_seed:
            self.seed_edit.setText(curr_seed)

        # Rebuild the browser with the new locale, preserving current selection.
        # Re-run the reverse parser afterwards: _rebuild_ui destroyed and
        # replaced every editor widget (including update_class_mod_btn), so
        # the loaded state is gone. Reloading restores editor + button state.
        if hasattr(self, "browser"):
            selected_path = self.selected_item_path
            self.browser.refresh()
            if selected_path:
                self.browser.set_selected_path(selected_path)
                current = self.browser.current_item()
                if current:
                    self._load_class_mod_item(current)
        log_editor(self.main_app, self._LOG_TAG, f"Finished updating language for {self.__class__.__name__}.")

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
        # Level / seed are value edits — the header binding picks up the new
        # widget values on the next state.render() call, no state mutation.
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
        # Picker add/remove is structural — rebuild state first.
        self.leg_picker.changed.connect(self._rebuild_derived_tokens_and_emit)
        layout.addWidget(self.leg_picker)

        self.container_layout.addWidget(leg_group, 1)

    def _create_output_group(self):
        output_group = QGroupBox(self.ui_loc['output']['title'])
        layout = QGridLayout(output_group)

        # Base85
        layout.addWidget(QLabel(self.ui_loc['output']['base85']), 0, 0)
        self.b85_output_edit = QLineEdit()
        self.b85_output_edit.setReadOnly(True)
        layout.addWidget(self.b85_output_edit, 0, 1)
        
        add_to_pack_btn = QPushButton(self.ui_loc['output']['add_to_backpack'])
        add_to_pack_btn.clicked.connect(self._add_to_backpack)
        layout.addWidget(add_to_pack_btn, 0, 2)

        self.flag_combo = QComboBox()
        self._populate_flags()
        layout.addWidget(self.flag_combo, 0, 3)

        self.update_class_mod_btn = QPushButton(self.ui_loc.get('output', {}).get('update_class_mod', 'Update'))
        self.update_class_mod_btn.setEnabled(False)
        self.update_class_mod_btn.clicked.connect(self._update_class_mod)
        layout.addWidget(self.update_class_mod_btn, 0, 4)

        # Full String
        layout.addWidget(QLabel(self.ui_loc['output']['deserialize']), 1, 0)
        self.full_string_output = QLineEdit()
        self.full_string_output.setReadOnly(True)
        layout.addWidget(self.full_string_output, 1, 1)
        
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
        # Picker add/remove/count is structural — rebuild state first.
        self.skill_picker.changed.connect(self._rebuild_derived_tokens_and_emit)
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
        # Picker add/remove/count is structural — rebuild state first.
        self.perk_picker.changed.connect(self._rebuild_derived_tokens_and_emit)
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
        # Class change means a different class_id in the header — the loaded
        # source's derived tokens no longer apply. Reset to fresh state
        # (Option 1); preserved unknowns from previous item are DISCARDED
        # (different class → different perk pool anyway).
        self._populating = True
        try:
            self.skill_picker.clear()
            self.populate_names()
            self.populate_legendary_extras()
            self.populate_skills()
        finally:
            self._populating = False
        if not self._is_loading:
            self._reset_state_to_fresh_item()
            self._rebuild_derived_tokens_and_emit()

    def on_rarity_change(self):
        self._populating = True
        try:
            self.populate_names()
            self.populate_legendary_extras()
        finally:
            self._populating = False
        self._rebuild_derived_tokens_and_emit()

    def on_name_change(self):
        self._populating = True
        try:
            self.populate_legendary_extras(preserve_selection=True)
        finally:
            self._populating = False
        # Name change alters which codes get emitted — structural.
        self._rebuild_derived_tokens_and_emit()

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

        for name_row in names_list:
            name_en = name_row.get('name_EN', '')
            name_zh = name_row.get('name_ZH', '')
            name_code = name_row.get('name_code', '')

            display_name = self._display_name(name_zh, name_en)

            self.name_combo.addItem(display_name)
            # name_code is a free-form string in the CSV — matches _name_codes_for's
            # ``str(code).isdigit()`` guard so a non-numeric row parks a 0 rather
            # than crashing int().
            self.name_code_map[display_name] = int(name_code) if str(name_code).isdigit() else 0

        self.name_combo.blockSignals(False)
        # populate_names changes which name_code will be emitted → structural.
        self._rebuild_derived_tokens_and_emit()

    def update_string(self, *args):
        """State-first render. Level/seed value edits fire the header binding
        (no state mutation). Structural edits (class/rarity/name/picker
        change) surgically remove class-mod-derived tokens (identity trio,
        legendary extras, skill codes, perk list, standalone quoted perks)
        and re-insert from widget state — any token that ISN'T in a known
        category (top-level unknowns, unknown perk children in {234:[...]})
        survives verbatim.
        """
        if self._is_loading:
            return
        if not self._token_state.tokens:
            self.full_string_output.setText("...")
            self.b85_output_edit.setText("...")
            return
        try:
            decoded = self.browser.render_from_state(self._token_state)
            self.full_string_output.setText(decoded)
            encoded, err = b_encoder.encode_to_base85(decoded)
            self._encode_error = bool(err)
            if err:
                self.b85_output_edit.setText(
                    self.ui_loc['dialogs']['coding_error'].format(error=err)
                )
            else:
                self.b85_output_edit.setText(encoded)
        except Exception as e:
            self._encode_error = True
            traceback.print_exc()
            self.full_string_output.setText(self.ui_loc['dialogs']['gen_error'].format(error=e))
            self.b85_output_edit.setText("...")

    def _rebuild_derived_tokens_and_emit(self, *args):
        """Structural handler: surgically remove all class-mod-derived
        tokens (identity trio + legendary extras + skill codes + {234:[...]}
        perk group + standalone quoted perks) and re-insert from widget
        state. Unknown tokens (top-level simples not in a category, unknown
        children of {234:[...]}) are preserved verbatim — top-level ones
        stay untouched in the token stream, and {234:[...]} unknowns are
        recorded in ``self._preserved_unknowns[234]`` on load and re-emitted
        here.
        """
        if self._is_loading or self._populating:
            return
        if not self._token_state.tokens:
            return
        if not self.names_data or not self.name_combo.currentText():
            return
        current_class_en = self._get_current_class_en()
        if not current_class_en or current_class_en not in self.CLASS_IDS:
            return
        current_class_id = str(self.CLASS_IDS[current_class_en])

        # ---- Compute the "known category IDs" for the current class ----
        # Any simple whose value matches these gets removed on rebuild —
        # unknowns (values NOT in the union) are preserved as-is.
        known_simple_ids: set[int] = set()
        # rarity codes (all class rarities) + legendary card IDs
        for rarity_en in ("Common", "Uncommon", "Rare", "Epic"):
            code_raw = item_display_resolver.classmod_rarity_code(current_class_id, rarity_en)
            try:
                known_simple_ids.add(int(code_raw))
            except (TypeError, ValueError):
                pass
        for row in self.legendary_map_data:
            if row.get('class_ID') == current_class_id:
                card_id = row.get('item_card_ID', '')
                if str(card_id).isdigit():
                    known_simple_ids.add(int(card_id))
        # all name codes (primary + legendary extras) for this class
        for rarity_key in ("normal", "legendary"):
            for name_row in self.names_by_class_rarity.get((current_class_id, rarity_key), []):
                code = name_row.get('name_code', '')
                if str(code).isdigit():
                    known_simple_ids.add(int(code))
        # Harlowe marker
        known_simple_ids.add(self._HARLOWE_LEGENDARY_MARKER)
        # All skill codes for this class
        for skill_row in self.skills_by_class.get(current_class_id, []):
            for i in range(1, 6):
                code_str = skill_row.get(f'skill_ID_{i}', '')
                if code_str and str(code_str).isdigit():
                    known_simple_ids.add(int(code_str))

        # ---- Remove class-mod-derived tokens ----
        to_remove: list[int] = []
        for idx, tok in enumerate(self._token_state.tokens):
            if tok.kind == 'simple' and tok.parent is None and tok.value in known_simple_ids:
                to_remove.append(idx)
            elif tok.kind == 'list' and tok.parent == 234:
                to_remove.append(idx)
            elif tok.kind == 'quoted':
                # Class-mod quoted perks are paths like "Path/..." — value=None
                # for path form; only remove if it looks like a class-mod perk
                # (value in perks_by_id keys). Numeric-quoted don't exist here.
                raw = tok.raw.strip()
                if raw.startswith('"') and raw.endswith('"'):
                    inner = raw[1:-1]
                    if inner in self.perks_by_id:
                        to_remove.append(idx)
        for idx in reversed(to_remove):
            self._token_state.remove_with_whitespace(idx)

        # ---- Re-insert from widget state (in canonical order) ----
        insert_at = self._insert_idx_before_trailing_pipe()
        rarity_en = self._get_english_key(self.rarity_combo.currentText())
        name_code = self.name_code_map.get(self.name_combo.currentText(), 0)

        # Rarity code
        rarity_code_val: str = ""
        if rarity_en == "Legendary":
            rarity_code_val = self.legendary_code_by_class_name.get(
                (current_class_id, str(name_code)), ''
            )
        else:
            rarity_code_val = item_display_resolver.classmod_rarity_code(current_class_id, rarity_en)
        if rarity_code_val:
            try:
                pid = int(rarity_code_val)
                self._token_state.insert(insert_at, Token(raw=" ", kind="raw"))
                self._token_state.insert(insert_at + 1, Token(
                    raw=f"{{{pid}}}", kind='simple', value=pid,
                ))
                insert_at += 2
            except (TypeError, ValueError):
                pass

        # Primary name + Harlowe marker
        if name_code:
            try:
                pid = int(name_code)
                self._token_state.insert(insert_at, Token(raw=" ", kind="raw"))
                self._token_state.insert(insert_at + 1, Token(
                    raw=f"{{{pid}}}", kind='simple', value=pid,
                ))
                insert_at += 2
            except (TypeError, ValueError):
                pass
            if rarity_en == "Legendary" and current_class_en == "Harlowe":
                pid = self._HARLOWE_LEGENDARY_MARKER
                self._token_state.insert(insert_at, Token(raw=" ", kind="raw"))
                self._token_state.insert(insert_at + 1, Token(
                    raw=f"{{{pid}}}", kind='simple', value=pid,
                ))
                insert_at += 2

        # Legendary extras
        for e in self.leg_picker.entries():
            code = e['data'].get('name_code', '')
            try:
                pid = int(code)
            except (TypeError, ValueError):
                continue
            self._token_state.insert(insert_at, Token(raw=" ", kind="raw"))
            self._token_state.insert(insert_at + 1, Token(
                raw=f"{{{pid}}}", kind='simple', value=pid,
            ))
            insert_at += 2

        # Skill boost codes (N copies of codes[:N])
        for entry in self.skill_picker.entries():
            codes = entry["data"]["codes"]
            for code in codes[:entry["count"]]:
                try:
                    pid = int(code)
                except (TypeError, ValueError):
                    continue
                self._token_state.insert(insert_at, Token(raw=" ", kind="raw"))
                self._token_state.insert(insert_at + 1, Token(
                    raw=f"{{{pid}}}", kind='simple', value=pid,
                ))
                insert_at += 2

        # Perks: numeric → {234:[...]} + preserved unknowns; GB-path → quoted
        perk_pieces: list[str] = []
        perk_children_int: list[int] = []
        special_perk_pieces: list[str] = []
        for e in self.perk_picker.entries():
            perk_id = e["data"].get("perk_id")
            count = e["count"]
            if not perk_id:
                continue
            perk_code = self._format_perk_code(perk_id)
            for _ in range(count):
                if str(perk_id).strip().isdigit():
                    perk_pieces.append(perk_code)
                    try:
                        perk_children_int.append(int(perk_id))
                    except (TypeError, ValueError):
                        pass
                else:
                    special_perk_pieces.append(perk_code)
        # Append preserved unknowns to the numeric perk list to keep them alive.
        preserved = self._preserved_unknowns.get(234, [])
        for u in preserved:
            perk_pieces.append(str(u))
            perk_children_int.append(int(u))
        if perk_pieces:
            body = ' '.join(perk_pieces)
            self._token_state.insert(insert_at, Token(raw=" ", kind="raw"))
            self._token_state.insert(insert_at + 1, Token(
                raw=f"{{234:[{body}]}}", kind='list',
                parent=234, children=list(perk_children_int),
            ))
            insert_at += 2
        for qtok in special_perk_pieces:
            self._token_state.insert(insert_at, Token(raw=" ", kind="raw"))
            self._token_state.insert(insert_at + 1, Token(
                raw=qtok, kind='quoted',
            ))
            insert_at += 2

        self.update_string()

    def _insert_idx_before_trailing_pipe(self) -> int:
        n = len(self._token_state.tokens)
        for idx in range(n - 1, -1, -1):
            tok = self._token_state.tokens[idx]
            if tok.kind == 'raw' and '|' in tok.raw:
                return idx
        return n

    def _reset_state_to_fresh_item(self) -> None:
        """Fresh-item state on class change: [header, '|']. All derived
        tokens are inserted via _rebuild_derived_tokens_and_emit."""
        self._preserved_unknowns = {}
        current_class_en = self._get_current_class_en()
        if not current_class_en or current_class_en not in self.CLASS_IDS:
            return
        class_id_int = self.CLASS_IDS[current_class_en]
        level_val = self.level_edit.text() or self._character_level
        seed_val = self.seed_edit.text() or "1"
        header_raw = f"{class_id_int}, 0, 1, {level_val}| 2, {seed_val}||"
        tokens = [Token(raw=header_raw, kind='raw'), Token(raw="|", kind='raw')]
        self._token_state = TokenOrderedState(tokens)
        self._token_state.bind(0, make_header_getter(
            header_raw,
            level_getter=lambda: self.level_edit.text(),
            seed_getter=lambda: self.seed_edit.text(),
        ))
        # Derived tokens inserted by _rebuild_derived_tokens_and_emit — the
        # caller of _reset_state_to_fresh_item is responsible for firing it.

    def _bind_token_state_widgets(self):
        """No-op — class mod uses category-scoped structural rebuilds via
        ``_rebuild_derived_tokens_and_emit`` for every widget change.
        Level/seed value edits fire the header binding (attached at load)."""
        # Reserved: intentionally empty. Header is bound by the load path;
        # every derived token is (re-)inserted by the structural handler
        # rather than bound. Kept as a method for parity with sibling tabs
        # and future extension.
        return

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

            display_name = self._display_name(name_zh, name_en)

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
            display_name = self._display_name(perk_zh, perk_en)
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

    @staticmethod
    def _inverse_lookup(mapping, value, default=None):
        """Return the first key in ``mapping`` whose value equals ``value``,
        else ``default``. Used to turn a localized display name back into its
        canonical English key (class name, rarity, etc.)."""
        for key, val in mapping.items():
            if val == value:
                return key
        return default

    def _get_current_class_en(self):
        # When localization has no entry for the current display text (e.g.
        # user is running in EN and the combo already shows EN), fall back to
        # the display text itself — it's already the canonical key.
        display = self.class_combo.currentText()
        return self._inverse_lookup(self.localization, display, default=display)

    def _get_english_key(self, localized_value):
        return self._inverse_lookup(self.localization, localized_value, default=localized_value)

    def _add_to_backpack(self):
        serial = self.b85_output_edit.text()
        if not serial or getattr(self, '_encode_error', False):
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
            log_editor(self.main_app, self._LOG_TAG, f"Could not load icon {icon_file}: {e}")
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
        self.skill_picker.set_categories(categories, columns=2)

        items = []
        color_order = {"red": 0, "green": 1, "blue": 2}
        for skill_row in sorted(skills_list, key=lambda row: (color_order.get(row.get('tree_color', ''), 9), row.get('skill_name_EN', ''))):
            skill_en = skill_row.get('skill_name_EN', '')
            skill_zh = skill_row.get('skill_name_ZH', '')
            localized_name = self._display_name(skill_zh, skill_en)
            display_name = C4SH_TREE_SUFFIX_RE.sub("", localized_name) if current_class_en == "C4sh" else localized_name

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

    # ---- Backpack browser integration ---------------------------------

    @staticmethod
    def _is_class_mod_item(item):
        return item.get("type_en") == "Class Mod" and "Backpack" in (item.get("container") or "")

    def _class_mod_browser_row(self, item):
        """Vertical-card row for class mods. Shows class prominently since a
        class mod for Vex is meaningfully different from one for Amon."""
        manufacturer = item.get("manufacturer") or self.ui_loc.get('parts', {}).get('unknown', 'Unknown')
        type_label = item.get("type") or self.ui_loc.get('parts', {}).get('unknown_item', 'Class Mod')
        rarity = item.get("rarity") or ""
        name = item.get("name") or ""

        # manufacturer field for class mods is typically the class name in this app
        if name and name not in {manufacturer, type_label}:
            display_name = f"{manufacturer} · {name}"
        else:
            display_name = f"{manufacturer} {type_label}"

        level_label = self.ui_loc.get('labels', {}).get('level', 'Lv')
        slot_label = self.ui_loc.get('labels', {}).get('slot', 'Slot')
        slot_value = (item.get("slot") or "N/A").replace("slot_", "")
        detail_bits = [f"{level_label} {item.get('level', 'N/A')}", f"{slot_label} {slot_value}"]
        if rarity:
            detail_bits.append(rarity)
        detail = "  ·  ".join(detail_bits)

        row = QWidget()
        row.setObjectName("ItemBrowserRow")
        row.setFixedHeight(ROW_HEIGHT)
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(10, 7, 10, 7)
        row_layout.setSpacing(5)

        name_label = QLabel(display_name)
        name_label.setObjectName("ItemBrowserName")
        name_label.setToolTip(display_name)
        name_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        detail_label = QLabel(detail)
        detail_label.setObjectName("ItemBrowserMeta")
        detail_label.setToolTip(detail)
        row_layout.addWidget(name_label)
        row_layout.addWidget(detail_label)

        # No resolve_class_mod_stats — placeholders until one exists.
        stat_titles = self.ui_loc.get('stats', {})
        stats_layout = QGridLayout()
        stats_layout.setContentsMargins(0, 2, 0, 0)
        stats_layout.setHorizontalSpacing(4)
        stats_layout.setVerticalSpacing(1)
        for column, key in enumerate(("class", "rarity", "primary_skill", "secondary_skill", "perk_count")):
            title_label = QLabel(stat_titles.get(key, key.replace('_', ' ').title()))
            title_label.setObjectName("ItemBrowserStatTitle")
            title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title_label.setWordWrap(True)
            value_label = QLabel("—")
            value_label.setObjectName("ItemBrowserStatValue")
            value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            stats_layout.addWidget(title_label, 0, column)
            stats_layout.addWidget(value_label, 1, column)
            stats_layout.setColumnStretch(column, 1)
        row_layout.addLayout(stats_layout)
        return display_name, detail, row

    def _summarize_class_mod(self, item):
        return summarize_item(
            item,
            template=self.ui_loc.get('summary', {}).get('selected', 'Selected · {name} · Lv.{level}'),
            none_text=self.ui_loc.get('summary', {}).get('none_selected', 'No backpack class mod selected'),
            fallback_name=self.ui_loc.get('summary', {}).get('fallback_name', 'Class Mod'),
        )

    def refresh_backpack_items(self):
        # browser is unconditionally constructed in __init__ before _rebuild_ui,
        # so no hasattr guard is needed.
        self.browser.refresh()

    # ---- Reverse parser (backpack class mod -> editor widgets) --------

    def _load_class_mod_item(self, item):
        """Populate editor fields from a decoded class mod in the backpack.

        Class-mod-specific reverse-parser bits:
          - {27} appended after Harlowe legendary names is a marker, not a
            widget-owned token — skipped
          - skill boost VALUES are encoded as N copies of consecutive skill
            codes (data['codes'][:count]), not as {skill_id:value}. Reverse:
            build a {code -> (skill_key, position_within_codes)} lookup and
            walk the token stream accumulating per-skill occurrence counts
          - perks live in TWO places: numeric IDs wrapped in {234:[...]},
            GB-path IDs emitted as standalone "Path/..." quoted tokens
            (outside any brace). Second regex pass captures the quoted form.
        """
        if not item:
            return
        decoded = item.get("decoded_full", "") or ""
        if "||" not in decoded:
            log_editor(self.main_app, self._LOG_TAG, f"class mod load: no components in {item.get('name', 'unknown')}")
            return

        self._is_loading = True
        try:
            self.selected_item_path = item.get("original_path")
            item_name = item.get('name', 'unknown')

            # Parse into token state; bind header so state.render() picks up
            # level + seed edits. Class-mod's header is the same shape as the
            # other tabs'.
            self._token_state = self.browser.token_state_for(item, skin=False)
            if self._token_state.tokens:
                header_raw = self._token_state.tokens[0].raw
                self._token_state.bind(0, make_header_getter(
                    header_raw,
                    level_getter=lambda: self.level_edit.text(),
                    seed_getter=lambda: self.seed_edit.text(),
                ))

            header, component = decoded.split("||", 1)
            header_fields = header.strip().split("|")[0].strip().split(",")
            try:
                class_id = int(header_fields[0])
                level = int(header_fields[3])
            except (ValueError, IndexError):
                log_editor(self.main_app, self._LOG_TAG, f"class mod load: bad header for {item_name}")
                return

            # Seed: "| 2, {seed}"
            seed_match = re.search(r'\|\s*2\s*,\s*(\d+)', header)
            seed = seed_match.group(1) if seed_match else self.seed_edit.text()

            # Snap class combo → triggers on_class_change under normal flow;
            # _is_loading guard suppresses the trailing update_string.
            class_en = self._class_en_for_id(class_id)
            if not class_en:
                # Unknown class: bail out entirely rather than populating widgets
                # against the wrong class's data (would silently corrupt the load).
                log_editor(self.main_app, self._LOG_TAG, f"class mod load: unknown class_id {class_id} in {item_name}")
                return
            localized_class = self._(class_en)
            self.class_combo.blockSignals(True)
            idx = self.class_combo.findText(localized_class)
            if idx >= 0:
                self.class_combo.setCurrentIndex(idx)
            self.class_combo.blockSignals(False)
            self.on_class_change()   # repopulates names/skills/leg-extras for this class

            self.level_edit.blockSignals(True)
            self.level_edit.setText(str(level))
            self.level_edit.blockSignals(False)
            self.seed_edit.blockSignals(True)
            self.seed_edit.setText(seed)
            self.seed_edit.blockSignals(False)

            # Reset skill/perk pickers; leg_picker is reset by on_rarity_change
            # once we set rarity below (which fires populate_legendary_extras).
            self.skill_picker.clear()
            self.perk_picker.clear()

            simple_tokens, group_tokens, quoted_tokens = self._parse_class_mod_components(component)

            # 1) Identify rarity from the first simple token whose value is a
            #    known rarity code for this class.
            consumed_simple = set()
            rarity_en = self._identify_rarity(class_id, simple_tokens, consumed_simple)
            if rarity_en:
                self.rarity_combo.blockSignals(True)
                self.rarity_combo.setCurrentText(self._(rarity_en))
                self.rarity_combo.blockSignals(False)
                # Manual call — on_rarity_change would fire populate_names again
                # (idempotent) plus populate_legendary_extras which we need here.
                self.populate_names()
                self.populate_legendary_extras()

            # 2) Identify the primary name from the next simple token whose value
            #    matches a name_code for (class, rarity).
            name_codes_this_class_rarity = self._name_codes_for(class_id, rarity_en)
            primary_name_display = None
            for i, tok_id in enumerate(simple_tokens):
                if i in consumed_simple:
                    continue
                if tok_id in name_codes_this_class_rarity:
                    primary_name_display = name_codes_this_class_rarity[tok_id]
                    consumed_simple.add(i)
                    break
            if primary_name_display:
                self.name_combo.blockSignals(True)
                idx = self.name_combo.findText(primary_name_display)
                if idx >= 0:
                    self.name_combo.setCurrentIndex(idx)
                self.name_combo.blockSignals(False)
                # Populate legendary extras against the newly-set primary name
                self.populate_legendary_extras()

            # 3) Consume any remaining tokens that match this class+rarity's
            #    legendary name_codes as "legendary extras" (the leg_picker
            #    entries). Skip {27} Harlowe marker.
            leg_name_codes = self._name_codes_for(class_id, "Legendary") if rarity_en == "Legendary" else {}
            for i, tok_id in enumerate(simple_tokens):
                if i in consumed_simple:
                    continue
                if tok_id == self._HARLOWE_LEGENDARY_MARKER:
                    consumed_simple.add(i)
                    continue
                if tok_id in leg_name_codes:
                    self._add_leg_extra(tok_id)
                    consumed_simple.add(i)

            # 4) Skill boost counts — see _apply_skill_codes for the reverse
            #    of the rebuild's `codes[:count]` slice semantics.
            self._apply_skill_codes(simple_tokens, consumed_simple, item_name)

            # 5) Numeric-id perks in {234:[...]}. Unknown perk IDs (not in
            #    perks_by_id) get recorded in _preserved_unknowns[234] so the
            #    structural rebuild re-emits them on every mutation.
            self._preserved_unknowns = {}
            for group in group_tokens:
                parent = group['id']
                if parent == 234:
                    for pid in group['sub_ids_raw']:
                        pid_str = str(pid).strip('"')
                        if pid_str in self.perks_by_id:
                            self._add_perk(pid_str, item_name)
                        else:
                            try:
                                self._preserved_unknowns.setdefault(234, []).append(int(pid_str))
                            except (TypeError, ValueError):
                                log_editor(self.main_app, self._LOG_TAG, f"class mod load: unhandled non-numeric perk {pid_str!r} in {item_name}")
                else:
                    log_editor(self.main_app, self._LOG_TAG, f"class mod load: unexpected group parent {parent} in {item_name}")

            # 6) Standalone quoted-path perks (outside any {...} block)
            for qpath in quoted_tokens:
                self._add_perk(qpath, item_name)

            set_flag_from_item(self.flag_combo, item, main_app=self.main_app, tag=self._LOG_TAG)
            self.update_class_mod_btn.setEnabled(True)
            # Bind downstream tokens so subsequent value edits picked up on
            # the next state.render(). Runs BEFORE the _is_loading guard
            # drops so the emit fires exactly once.
            self._bind_token_state_widgets()
        finally:
            self._is_loading = False
            # State is source-parsed with bindings live — emit verbatim.
            self.update_string()

    def _parse_class_mod_components(self, component_str):
        """Tokenize the class-mod component section.

        Returns (simple_ids, group_dicts, quoted_paths):
          - simple_ids: list[int] in order for each {N} token
          - group_dicts: list of {'id': int, 'sub_ids_raw': list[str]} for {N:[a b c]}
            or {N:X}. Sub-ids are strings so quoted-path perks inside {234:[...]}
            (e.g. {234:["Path/..." 12 15]}) can round-trip if the game ever
            emits them that way.
          - quoted_paths: list[str] for standalone "Path/..." tokens outside braces
        """
        # Standard brace-token pass (numeric ids inside braces only)
        simple, groups = [], []
        for match in re.finditer(r'\{(\d+)(?::(\d+|\[[^\]]+\]))?\}', component_str):
            outer_id = int(match.group(1))
            inner = match.group(2)
            if inner is None:
                simple.append(outer_id)
            elif '[' in inner:
                # Sub-ids can mix numeric and quoted (for future safety)
                raw = inner.strip('[]').split()
                groups.append({'id': outer_id, 'sub_ids_raw': raw})
            else:
                # {N:X} — single sub-id
                groups.append({'id': outer_id, 'sub_ids_raw': [inner]})

        # Strip everything inside braces before scanning for standalone quotes,
        # so quoted sub-ids don't get double-counted as standalone tokens.
        stripped = re.sub(r'\{[^}]*\}', '', component_str)
        quoted = [m.group(1) for m in re.finditer(r'"([^"]+)"', stripped)]
        return simple, groups, quoted

    def _identify_rarity(self, class_id, simple_tokens, consumed_simple_out):
        """Return the English rarity name whose code appears first in the token
        stream, or None. Marks the consumed token index in consumed_simple_out.
        """
        class_id_str = str(class_id)
        # Non-legendary: look up code via classmod_rarity_code(class_id, rarity_en)
        for rarity_en in ("Common", "Uncommon", "Rare", "Epic"):
            code_raw = item_display_resolver.classmod_rarity_code(class_id_str, rarity_en)
            try:
                code = int(code_raw)
            except (TypeError, ValueError):
                continue
            for i, tok_id in enumerate(simple_tokens):
                if i in consumed_simple_out:
                    continue
                if tok_id == code:
                    consumed_simple_out.add(i)
                    return rarity_en
        # Legendary: any token matching an item_card_ID from legendary_map_data
        legendary_codes = set()
        for row in self.legendary_map_data:
            if row.get('class_ID') == class_id_str:
                card_id = row.get('item_card_ID', '')
                if str(card_id).isdigit():
                    legendary_codes.add(int(card_id))
        for i, tok_id in enumerate(simple_tokens):
            if i in consumed_simple_out:
                continue
            if tok_id in legendary_codes:
                consumed_simple_out.add(i)
                return "Legendary"
        return None

    def _name_codes_for(self, class_id, rarity_en):
        """Return {name_code:int -> display_name:str} for (class, rarity)."""
        if not rarity_en:
            return {}
        rarity_key = "legendary" if rarity_en == "Legendary" else "normal"
        rows = self.names_by_class_rarity.get((str(class_id), rarity_key), [])
        out = {}
        for name_row in rows:
            code = name_row.get('name_code', '')
            if not str(code).isdigit():
                continue
            name_zh = name_row.get('name_ZH', '')
            name_en = name_row.get('name_EN', '')
            display = self._display_name(name_zh, name_en)
            out[int(code)] = display
        return out

    def _apply_skill_codes(self, simple_tokens, consumed, item_name):
        """Reverse of the rebuild's ``codes[:count]`` slice.

        For each remaining simple token, find the skill that owns it and note
        the token's position (0-indexed) within that skill's codes list. The
        skill's final count is ``max_position_seen + 1`` — reconstructed from
        occurrence-in-serial rather than an explicit count, because the game
        format encodes counts as N copies of the sub-codes, not as ``{id:N}``.
        """
        code_to_skill = self._skill_code_index()
        max_position = {}
        for i, tok_id in enumerate(simple_tokens):
            if i in consumed:
                continue
            entry = code_to_skill.get(tok_id)
            if entry is None:
                log_editor(self.main_app, self._LOG_TAG, f"class mod load: unknown skill/simple id {tok_id} in {item_name}")
                continue
            skill_key, position = entry
            if position > max_position.get(skill_key, -1):
                max_position[skill_key] = position
        for skill_key, pos in max_position.items():
            self.skill_picker.set_entry_count(skill_key, pos + 1)

    def _skill_code_index(self):
        """Build {skill_code:int -> (skill_key:str, position:int)} for the
        currently-active class. Position is the 0-indexed offset within the
        skill's codes list; a skill with count=3 emits codes[:3].

        stable_key falls back to ``{class_id}:{codes[0] if codes else skill_en}``
        — the same convention ``populate_skills`` uses. Earlier drafts used
        ``skill_ID_1`` here, which diverged when ``skill_ID_1`` was empty but
        later ``skill_ID_N`` were populated (rare but real in the data) —
        the two sides then built different keys and the reverse-parser could
        not find the skill on load.
        """
        table = {}
        current_class_en = self._get_current_class_en()
        current_class_id = str(self.CLASS_IDS.get(current_class_en, 0))
        skills_list = self.skills_by_class.get(current_class_id, [])
        for skill_row in skills_list:
            codes = []
            for i in range(1, 6):
                code_str = skill_row.get(f'skill_ID_{i}', '')
                if code_str and str(code_str).isdigit():
                    codes.append(int(code_str))
            skill_en = skill_row.get('skill_name_EN', '')
            stable_key = skill_row.get('skill_key') or f"{current_class_id}:{codes[0] if codes else skill_en}"
            for position, code in enumerate(codes):
                table[code] = (stable_key, position)
        return table

    def _class_en_for_id(self, class_id):
        return self._inverse_lookup(self.CLASS_IDS, class_id)

    def _add_leg_extra(self, name_code):
        """Add a legendary extra entry to leg_picker by name_code."""
        # leg_picker's source items use key=name_code (string form)
        self.leg_picker.set_entry_count(str(name_code), 1)

    def _add_perk(self, perk_id, item_name="unknown"):
        """Bump a perk entry's count in perk_picker by perk_id.

        Unknown perk_ids (missing from perks_by_id) log rather than silently
        dropping — they would round-trip to nothing on the next rebuild.
        """
        if perk_id not in self.perks_by_id:
            log_editor(self.main_app, self._LOG_TAG, f"class mod load: unknown perk {perk_id} in {item_name}")
            return
        current = next(
            (e.get("count", 0) for e in self.perk_picker.entries()
             if str(e.get("data", {}).get("perk_id", "")) == perk_id),
            0,
        )
        self.perk_picker.set_entry_count(perk_id, current + 1)

    def _update_class_mod(self):
        emit_update_or_warn(
            self,
            new_serial=self.b85_output_edit.text(),
            no_selection_title=self.ui_loc.get('dialogs', {}).get('no_selection', 'No Selection'),
            no_selection_msg=self.ui_loc.get('dialogs', {}).get('select_class_mod_first', 'Select a class mod first'),
            no_valid_code_title=self.ui_loc.get('dialogs', {}).get('no_valid_code', 'No Valid Code'),
            no_valid_code_msg=self.ui_loc.get('dialogs', {}).get('gen_first', 'Generate a valid class mod first'),
            success_msg=self.ui_loc.get('dialogs', {}).get('update_success', 'Class mod updated'),
        )

    def set_character_level(self, level: str):
        """设置角色等级，更新默认等级显示。"""
        self._character_level = level if level else "50"
        if hasattr(self, 'level_edit'):
            self.level_edit.setText(self._character_level)
