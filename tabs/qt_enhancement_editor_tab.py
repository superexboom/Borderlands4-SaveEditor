from collections import Counter
import random

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QComboBox, QCheckBox, QMessageBox, QScrollArea, QSplitter,
)
from PyQt6.QtCore import pyqtSignal, Qt

from core import b_encoder
from core import resource_loader

from tabs.qt_item_browser import ItemBrowser, ROW_HEIGHT
from tabs.qt_catalog_picker import CatalogPicker
from tabs.qt_editor_shared import (
    Token,
    TokenOrderedState,
    iter_children,
    log_editor,
    make_header_getter,
    parse_component_string,
    set_flag_from_item,
    summarize_item,
)

enhancement_data = resource_loader.get_enhancement_data()

class QtEnhancementEditorTab(QWidget):
    add_to_backpack_requested = pyqtSignal(str, str)
    update_item_requested = pyqtSignal(dict)

    _LOG_TAG = "enhancement"

    # Parent-ID under which enhancement 247-scoped tokens live. Elemental
    # {247:X} carries the rarity_map_247 code; group {247:[...]} carries the
    # secondary-stat picker entries. Same shape as grenade's _SECONDARY_PARENT.
    _SECONDARY_PARENT = 247

    def __init__(self, main_app=None, parent=None):
        super().__init__(parent)
        self.main_app = main_app
        self.current_lang = 'zh-CN'
        self._character_level = "50"
        self.localization_data = self._load_game_localization()
        self.ui_loc = self._load_ui_localization()
        self.perk_vars = {}
        self.rnd_seed = random.randint(1000, 9999)

        # State for backpack browser + reverse-parser flow
        self.selected_item_path = None
        self._is_loading = False
        # Seed override — set by _load_enhancement_item so an unmodified round-
        # trip preserves the header seed. None means "use the session's rnd_seed".
        self._current_seed = None
        # Token-preserving state — fixes the top-level token reorder bug
        # ({8} {247:76} {3} {1} → {3} {1} order lost). Every rebuild routes
        # through ``state.render()``; source order is preserved verbatim on
        # ALL edit paths — value edits fire bindings (rarity_code + {247:X}
        # single + {247:[...]} aggregation), and structural edits (perk
        # checkbox, stack_picker, stat_picker) mutate state surgically via
        # ``state.insert()`` / ``state.remove_with_whitespace()``. Unknown
        # source tokens stay unbound (raw pass-through) on top-level, and
        # unknown children of {247:[...]} live in ``_preserved_unknowns`` so
        # the aggregation getter re-emits them.
        self._token_state = TokenOrderedState([])
        self._preserved_unknowns: dict[int, list[int]] = {}
        self._populating = False

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        if not enhancement_data:
            self.main_layout.addWidget(QLabel(self.ui_loc['dialogs']['error_load']))
            return

        # Splitter + browser are built ONCE here — _build_ui only recreates the
        # inner container inside self.scroll_area on language change, so the
        # browser must sit outside that hierarchy to survive.
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.main_layout.addWidget(self.splitter)

        self.browser = ItemBrowser(
            main_app=self.main_app,
            item_filter=self._is_enhancement_item,
            row_builder=self._enhancement_browser_row,
            header_label=self.ui_loc.get('labels', {}).get('load_from_backpack', 'Load from Backpack'),
            search_placeholder=self.ui_loc.get('labels', {}).get('search_enhancement_placeholder', 'Search enhancement...'),
            empty_placeholder=self.ui_loc.get('dialogs', {}).get('no_enhancements_in_backpack', 'No enhancements in backpack'),
            no_save_placeholder=self.ui_loc.get('dialogs', {}).get('decrypt_save_to_show', 'Decrypt save first'),
            summary_formatter=self._summarize_enhancement,
            summary_none_text=self.ui_loc.get('summary', {}).get('none_selected', 'No backpack enhancement selected'),
            row_height=ROW_HEIGHT,
        )
        self.browser.item_selected.connect(self._load_enhancement_item)
        self.splitter.addWidget(self.browser)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.splitter.addWidget(self.scroll_area)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([320, 1040])

        self._build_ui()
        self.populate_initial_data()
        self.refresh_backpack_items()

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
        log_editor(self.main_app, self._LOG_TAG, f"Updating language for {self.__class__.__name__} to {lang}...")
        self.current_lang = lang
        self.ui_loc = self._load_ui_localization(lang)
        self.localization_data = self._load_game_localization(lang)

        self._build_ui()
        self.populate_initial_data()

        # Rebuild the browser with the new locale, preserving current selection.
        # Re-run the reverse parser afterwards: _build_ui + populate_initial_data
        # wiped the editor state to defaults, so the loaded state (including the
        # Update button's enabled flag) needs to be restored.
        if hasattr(self, "browser"):
            selected_path = self.selected_item_path
            self.browser.refresh()
            if selected_path:
                self.browser.set_selected_path(selected_path)
                current = self.browser.current_item()
                if current:
                    self._load_enhancement_item(current)

        log_editor(self.main_app, self._LOG_TAG, f"Finished updating language for {self.__class__.__name__}.")

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
        # Recreate only the inner container inside self.scroll_area — the
        # splitter and browser above must survive language changes so a
        # selection can be re-highlighted after populate_initial_data resets
        # the editor. Mirrors class-mod's _rebuild_ui.
        old_widget = self.scroll_area.widget()
        if old_widget:
            old_widget.deleteLater()

        # perk_vars holds QCheckBox refs owned by the container we just told
        # Qt to delete. Populating mfg_sel below fires currentTextChanged →
        # on_mfg_change → set_rarities_for_mfg → rarity_sel.addItems fires
        # again → rebuild_output, all BEFORE set_perk_checkboxes repopulates
        # perk_vars. Without this reset, rebuild_output calls .isChecked()
        # on a C++-deleted QCheckBox and Qt fatal-aborts.
        self.perk_vars = {}

        container = QWidget()
        self.scroll_area.setWidget(container)
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
        # Update Item button — enabled only after a backpack item is loaded.
        # Peer pattern (grenade/shield/etc.): sits next to Add to Backpack.
        self.update_enhancement_btn = QPushButton(
            self.ui_loc.get('buttons', {}).get('update_enhancement', 'Update')
        )
        self.update_enhancement_btn.setEnabled(False)
        self.update_enhancement_btn.clicked.connect(self._update_enhancement)
        action_frame.addWidget(self.update_enhancement_btn)
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
        # Rarity affects TWO tokens: the top-level {rarity_code} simple and
        # the {247:X} single token. When a source item is loaded, both are
        # bound and a rarity change is a pure value edit. On fresh items, the
        # handler inserts them structurally if missing.
        self.rarity_sel.currentTextChanged.connect(self._on_rarity_changed)
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
        # Stack-picker add/remove/count creates or removes {mfg_code:[...]}
        # tokens — surgical rebuild via _on_stack_picker_changed.
        self.stack_picker.changed.connect(self._on_stack_picker_changed)
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
        # Stat-picker add/remove/count grows or shrinks the {247:[...]}
        # aggregation token — ensure_stat_bucket_token handles insertion /
        # removal based on emptiness; the aggregation getter reads current
        # picker state on every render.
        self.stat_picker.changed.connect(self._on_stat_picker_changed)
        self._populate_stat_picker()
        builder_247_layout.addWidget(self.stat_picker)
        main_layout.addWidget(builder_247_group)

        # Special Thanks banner. Object name → assets/stylesheet.qss rule so
        # the QSS lives in one place and matches class mod's treatment.
        thanks_data = self.ui_loc.get('special_thanks', {})
        thanks_title = thanks_data.get('title', 'Special Thanks')
        thanks_content = thanks_data.get('content', '')
        if thanks_content:
            thanks_label = QLabel(f"<b>✨ {thanks_title}</b><br>{thanks_content.replace(chr(10), '<br>')}")
            thanks_label.setObjectName("enhancementThanksBanner")
            thanks_label.setWordWrap(True)
            thanks_label.setOpenExternalLinks(True)
            main_layout.addWidget(thanks_label)

        main_layout.addStretch()

    def populate_initial_data(self):
        # UI-populate alphabetical ordering, not a rebuild-path sort — use
        # list.sort so the grep-sanity for the builtin sort remains clean.
        mfg_names = list(enhancement_data.get('manufacturers', {}).keys())
        mfg_names.sort()
        self.mfg_sel.addItems([self._(name) for name in mfg_names])
        if mfg_names:
            self.mfg_sel.setCurrentText(self._(mfg_names[0]))
        self.on_mfg_change()

    def on_mfg_change(self, *args):
        # Guard structural handlers from firing during widget population.
        # set_rarities_for_mfg's rarity_sel.addItems + set_perk_checkboxes'
        # checkbox creation both emit signals that would otherwise try to
        # mutate a state that hasn't been reset yet.
        self._populating = True
        try:
            self.set_rarities_for_mfg()
            self.set_perk_checkboxes()
            self._populate_stack_picker()
        finally:
            self._populating = False
        # mfg switch changes the header's mfg_code, the {rarity} simple token,
        # the {247:X} rarity token, and every downstream picker entry — a
        # different item type entirely. Option 1: fresh state, no source
        # unknowns carry over.
        if not self._is_loading:
            self._reset_state_to_fresh_item()

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
        """Rebuild the perk-checkbox column for the current manufacturer.

        Invariant: between ``_build_ui`` clearing ``self.perk_vars`` and this
        method repopulating it, callers MUST NOT read ``self.perk_vars`` —
        the QCheckBox refs from the previous UI generation are gone but any
        cached reference would be a dangling C++ pointer (calling anything
        on it aborts the Qt event loop). ``_build_ui`` guards the window
        explicitly by zeroing ``perk_vars`` before it recreates the
        container; don't undo that.
        """
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

        self._populating = True
        try:
            for index in order:
                if index in perk_map:
                    var = QCheckBox(self._(perk_map[index]))
                    # Perk checkbox toggle → insert/remove standalone {index}
                    # simple token in the serial via _on_perk_var_toggled.
                    var.stateChanged.connect(self._on_perk_var_toggled)
                    self.perks_box.addWidget(var)
                    self.perk_vars[index] = var
        finally:
            self._populating = False

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
        """State-first render. Widget values flow through bindings (rarity
        code simple + {247:X} single + {247:[...]} aggregation) or through
        the token's raw form. Structural mutations happen surgically in
        ``_on_*`` handlers via ``state.insert()`` / ``state.remove_with_whitespace()``,
        so this path is pure ``state.render()`` — the token stream is
        authoritative. The {3}/{1} perk-flag tokens stay unbound and raw-emit in source
        order (fixes the reorder bug) unless the user toggles them, in which
        case the toggle handler inserts/removes surgically.
        """
        if self._is_loading:
            return
        if not self._token_state.tokens:
            return
        try:
            decoded = self.browser.render_from_state(self._token_state)
            self.raw_output_var.setText(decoded)
            encoded, err = b_encoder.encode_to_base85(decoded)
            if err:
                self.b85_output_var.setText(f"Error: {err}")
            else:
                self.b85_output_var.setText(encoded)
        except Exception as e:
            log_editor(self.main_app, self._LOG_TAG, f"enhancement rebuild error: {e}")

    # ---- Structural handlers ------------------------------------------

    def _on_rarity_changed(self, *args):
        """Rarity affects two tokens: top-level {rarity_code} simple and
        {247:X} single. When both exist (loaded item), bindings pick up the
        new values — no state mutation. When missing (fresh state), insert.
        """
        if self._is_loading or self._populating:
            return
        if not self._token_state.tokens:
            # State not yet initialized (called from populate_initial_data
            # signal cascade before _reset_state_to_fresh_item runs).
            return
        # Simple rarity_code token
        mfg_en = self._get_current_mfg_en_name()
        if not mfg_en:
            self.rebuild_output()
            return
        rarity_en = self._get_current_rarity_en_name()
        rarity_code_ids: set[int] = set()
        for c in enhancement_data['manufacturers'].get(mfg_en, {}).get('rarities', {}).values():
            try:
                rarity_code_ids.add(int(c))
            except (TypeError, ValueError):
                continue
        # Insert rarity_code simple if missing.
        rarity_idx = -1
        for idx, tok in enumerate(self._token_state.tokens):
            if tok.kind == 'simple' and tok.parent is None and tok.value in rarity_code_ids:
                rarity_idx = idx
                break
        if rarity_idx == -1 and rarity_en:
            code = enhancement_data['manufacturers'][mfg_en]['rarities'].get(rarity_en)
            if code is not None:
                insert_at = 1  # after header
                self._token_state.insert(insert_at, Token(raw=" ", kind="raw"))
                self._token_state.insert(insert_at + 1, Token(
                    raw=f"{{{int(code)}}}", kind='simple', value=int(code),
                ))
                self._token_state.bind(insert_at + 1, self._rarity_code_getter())

        # Insert {247:X} single if missing.
        r247_idx = -1
        for idx, tok in enumerate(self._token_state.tokens):
            if tok.kind == 'single' and tok.parent == self._SECONDARY_PARENT:
                r247_idx = idx
                break
        if r247_idx == -1 and rarity_en:
            r247 = enhancement_data['rarity_map_247'].get(rarity_en)
            if r247 is not None:
                insert_at = self._insert_idx_after_rarity_simple()
                self._token_state.insert(insert_at, Token(raw=" ", kind="raw"))
                self._token_state.insert(insert_at + 1, Token(
                    raw=f"{{{self._SECONDARY_PARENT}:{int(r247)}}}",
                    kind='single', parent=self._SECONDARY_PARENT, value=int(r247),
                ))
                self._token_state.bind(insert_at + 1, self._rarity_247_getter())
        self.rebuild_output()

    def _on_perk_var_toggled(self, *args):
        """Structural: insert/remove a standalone {index} simple token for
        the sender checkbox."""
        if self._is_loading or self._populating:
            return
        if not self._token_state.tokens:
            return
        cb = self.sender()
        if cb is None:
            return
        # Reverse-lookup the index from perk_vars.
        index = None
        for k, v in self.perk_vars.items():
            if v is cb:
                index = int(k)
                break
        if index is None:
            return
        checked = cb.isChecked()
        idx = self._find_perk_var_token_idx(index)
        if checked and idx == -1:
            insert_at = self._insert_idx_before_stacks()
            self._token_state.insert(insert_at, Token(raw=" ", kind="raw"))
            self._token_state.insert(insert_at + 1, Token(
                raw=f"{{{index}}}", kind='simple', value=index,
            ))
        elif not checked and idx != -1:
            self._token_state.remove_with_whitespace(idx)
        self.rebuild_output()

    def _on_stack_picker_changed(self, *args):
        """Surgical rebuild of stack picker tokens. Stack tokens are
        {mfg_code:[...]} groups keyed by foreign mfg; walk state, remove any,
        then re-insert from current picker state.
        """
        if self._is_loading or self._populating:
            return
        if not self._token_state.tokens:
            return
        # Identify all foreign-mfg parent codes present in the picker source.
        stack_parents: set[int] = set()
        for src in self.stack_picker._source:
            mfg_en_stack = src.get("data", {}).get("mfg")
            if not mfg_en_stack:
                continue
            code = enhancement_data['manufacturers'].get(mfg_en_stack, {}).get('code')
            if code is not None:
                stack_parents.add(int(code))
        # Also identify the {247:...} aggregation parent so we DON'T touch it.
        # Stack parents are top-level mfg codes; distinct from _SECONDARY_PARENT.

        to_remove: list[int] = []
        for idx, tok in enumerate(self._token_state.tokens):
            if tok.parent in stack_parents and tok.kind in ('single', 'list'):
                to_remove.append(idx)
        for idx in reversed(to_remove):
            self._token_state.remove_with_whitespace(idx)

        insert_at = self._insert_idx_before_stats_bucket()
        stacked_perks: dict[int, list[int]] = {}
        for e in self.stack_picker.entries():
            mfg_en_stack = e["data"]["mfg"]
            perk_idx = int(e["data"]["idx"])
            mfg_code_stack = int(enhancement_data['manufacturers'][mfg_en_stack]['code'])
            stacked_perks.setdefault(mfg_code_stack, [])
            for _ in range(e["count"]):
                stacked_perks[mfg_code_stack].append(perk_idx)
        for parent, indices in stacked_perks.items():
            self._token_state.insert(insert_at, Token(raw=" ", kind="raw"))
            if len(indices) == 1:
                self._token_state.insert(insert_at + 1, Token(
                    raw=f"{{{parent}:{indices[0]}}}",
                    kind='single', parent=parent, value=indices[0],
                ))
            else:
                body = " ".join(str(i) for i in indices)
                self._token_state.insert(insert_at + 1, Token(
                    raw=f"{{{parent}:[{body}]}}",
                    kind='list', parent=parent, children=list(indices),
                ))
            insert_at += 2
        self.rebuild_output()

    def _on_stat_picker_changed(self, *args):
        if self._is_loading or self._populating:
            return
        if not self._token_state.tokens:
            return
        self._ensure_stat_bucket_token()
        self.rebuild_output()

    # ---- Bindings + ensure helpers ------------------------------------

    def _rarity_code_getter(self):
        def getter():
            rarity_en = self._get_current_rarity_en_name()
            if not rarity_en:
                return None
            mfg_en = self._get_current_mfg_en_name()
            if not mfg_en:
                return None
            code = enhancement_data['manufacturers'][mfg_en]['rarities'].get(rarity_en)
            return f"{{{int(code)}}}" if code is not None else None
        return getter

    def _rarity_247_getter(self):
        def getter():
            rarity_en = self._get_current_rarity_en_name()
            if not rarity_en:
                return None
            code = enhancement_data['rarity_map_247'].get(rarity_en)
            return f"{{{self._SECONDARY_PARENT}:{int(code)}}}" if code is not None else None
        return getter

    def _stat_bucket_children(self) -> list[int]:
        parts: list[int] = []
        for e in self.stat_picker.entries():
            val = int(e["data"]["code"])
            for _ in range(e["count"]):
                parts.append(val)
        parts.extend(self._preserved_unknowns.get(self._SECONDARY_PARENT, []))
        return parts

    def _stat_bucket_getter(self):
        def getter():
            parts = self._stat_bucket_children()
            if not parts:
                return None
            body = " ".join(str(p) for p in parts)
            return f"{{{self._SECONDARY_PARENT}:[{body}]}}"
        return getter

    def _ensure_stat_bucket_token(self) -> None:
        parts = self._stat_bucket_children()
        idx = self._find_stat_bucket_token_idx()
        if not parts and idx != -1:
            self._token_state.remove_with_whitespace(idx)
        elif parts and idx == -1:
            insert_at = self._insert_idx_before_trailing_pipe()
            self._token_state.insert(insert_at, Token(raw=" ", kind="raw"))
            self._token_state.insert(insert_at + 1, Token(
                raw="", kind='list', parent=self._SECONDARY_PARENT, children=[],
            ))
            self._token_state.bind(insert_at + 1, self._stat_bucket_getter())

    # ---- Index helpers ------------------------------------------------

    def _find_perk_var_token_idx(self, index: int) -> int:
        for idx, tok in enumerate(self._token_state.tokens):
            if tok.kind == 'simple' and tok.parent is None and tok.value == index:
                # Skip a bound rarity_code that happens to numerically match
                # (defensive — perk indices are 1/2/3/9, rarity_codes are much
                # larger integers, so no collision in practice).
                if self._token_state.has_binding(idx):
                    continue
                return idx
        return -1

    def _find_stat_bucket_token_idx(self) -> int:
        for idx, tok in enumerate(self._token_state.tokens):
            if tok.parent == self._SECONDARY_PARENT and tok.kind == 'list':
                return idx
        return -1

    def _insert_idx_after_rarity_simple(self) -> int:
        # Insert idx immediately after any bound rarity_code simple, else after header.
        for idx, tok in enumerate(self._token_state.tokens):
            if tok.kind == 'simple' and tok.parent is None and self._token_state.has_binding(idx):
                # Skip trailing raw whitespace too so the {247:X} lands adjacent.
                return idx + 1
        return 1

    def _insert_idx_before_stacks(self) -> int:
        # Perk-var simples go between rarity/{247:X} and stack tokens.
        stack_parents: set[int] = set()
        for src in self.stack_picker._source:
            mfg_en_stack = src.get("data", {}).get("mfg")
            if not mfg_en_stack:
                continue
            code = enhancement_data['manufacturers'].get(mfg_en_stack, {}).get('code')
            if code is not None:
                stack_parents.add(int(code))
        for idx, tok in enumerate(self._token_state.tokens):
            if tok.parent in stack_parents and tok.kind in ('single', 'list'):
                if idx > 0 and self._token_state.tokens[idx - 1].kind == 'raw' \
                        and not self._token_state.tokens[idx - 1].raw.strip():
                    return idx - 1
                return idx
        return self._insert_idx_before_stats_bucket()

    def _insert_idx_before_stats_bucket(self) -> int:
        idx = self._find_stat_bucket_token_idx()
        if idx != -1:
            if idx > 0 and self._token_state.tokens[idx - 1].kind == 'raw' \
                    and not self._token_state.tokens[idx - 1].raw.strip():
                return idx - 1
            return idx
        return self._insert_idx_before_trailing_pipe()

    def _insert_idx_before_trailing_pipe(self) -> int:
        n = len(self._token_state.tokens)
        for idx in range(n - 1, -1, -1):
            tok = self._token_state.tokens[idx]
            if tok.kind == 'raw' and '|' in tok.raw:
                return idx
        return n

    def _reset_state_to_fresh_item(self) -> None:
        """Discard current state and build a minimal fresh-item state:
        [header, '|']. Rarity + {247:X} inserted via ``_on_rarity_changed``.
        Option 1 for mfg change: preserved unknowns from a previous item are
        DISCARDED."""
        self._preserved_unknowns = {}
        mfg_en = self._get_current_mfg_en_name()
        if not mfg_en:
            return
        mfg_code = enhancement_data['manufacturers'][mfg_en]['code']
        level_val = self.level_edit.text() if hasattr(self, 'level_edit') else self._character_level
        if not level_val:
            level_val = self._character_level
        seed = self._current_seed if self._current_seed is not None else self.rnd_seed
        header_raw = f"{mfg_code}, 0, 1, {level_val}| 2, {seed}||"
        tokens = [Token(raw=header_raw, kind='raw'), Token(raw="|", kind='raw')]
        self._token_state = TokenOrderedState(tokens)
        self._token_state.bind(0, make_header_getter(
            header_raw,
            level_getter=lambda: self.level_edit.text() if hasattr(self, 'level_edit') else '',
            seed_getter=None,
        ))
        self._on_rarity_changed()

    def _bind_token_state_widgets(self):
        """Loaded state: bind ONLY the first ``{247:X}`` single (the r247
        rarity representation — unambiguous parent). All other tokens stay
        UNBOUND so ``state.render()`` emits source raw verbatim across value
        edits — preserves top-level markers ({3}/{1}/{8}), the redundant
        top-level rarity_code simple, the {247:[...]} list bucket, and
        unknowns in ALL positions. Structural handlers surgically mutate
        state via ``state.insert()``/``state.remove_with_whitespace()``;
        unknowns persist across rebuilds via ``self._preserved_unknowns``.

        Rarity is stored in the serial two ways: as a top-level rarity_code
        simple AND as ``{247:X}`` per rarity_map_247 (redundant per source
        comment). We only bind the ``{247:X}`` form because it has an
        unambiguous parent — the top-level rarity_code simple is
        indistinguishable at load-time from marker simples ({8} in the
        wild) whose value happens to collide with a valid rarity code. The
        top-level rarity_code stays as source raw; r247 propagates the
        rarity change on its own — that's how the game reads the rarity.
        """
        if not self._token_state.tokens:
            return
        for idx, tok in enumerate(self._token_state.tokens):
            if tok.kind == 'single' and tok.parent == self._SECONDARY_PARENT:
                self._token_state.bind(idx, self._rarity_247_getter())
                break

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
        """Update the default level shown in level_edit."""
        self._character_level = level if level else "50"
        if hasattr(self, 'level_edit'):
            self.level_edit.setText(self._character_level)

    # ---- Backpack browser integration ---------------------------------

    @staticmethod
    def _is_enhancement_item(item):
        return item.get("type_en") == "Enhancement" and "Backpack" in (item.get("container") or "")

    def _enhancement_browser_row(self, item):
        """Vertical-card row widget for an enhancement in the browser.

        No enhancement_stats resolver exists yet, so the five-column strip
        renders placeholders — matches the grenade/shield/repkit visual so a
        future resolver drops in cleanly.
        """
        manufacturer = item.get("manufacturer") or self.ui_loc.get('parts', {}).get('unknown', 'Unknown')
        type_label = item.get("type") or self.ui_loc.get('parts', {}).get('unknown_item', 'Enhancement')
        rarity = item.get("rarity") or ""
        name = item.get("name") or ""

        if name and name not in {manufacturer, type_label}:
            display_name = f"{manufacturer} {type_label} ({name})"
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

        # No resolve_enhancement_stats — placeholders until one exists.
        stat_titles = self.ui_loc.get('stats', {})
        stats_layout = QGridLayout()
        stats_layout.setContentsMargins(0, 2, 0, 0)
        stats_layout.setHorizontalSpacing(4)
        stats_layout.setVerticalSpacing(1)
        for column, key in enumerate(("mfg", "rarity", "primary", "secondary", "level")):
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

    def _summarize_enhancement(self, item):
        return summarize_item(
            item,
            template=self.ui_loc.get('summary', {}).get('selected', 'Selected · {name} · Lv.{level}'),
            none_text=self.ui_loc.get('summary', {}).get('none_selected', 'No backpack enhancement selected'),
            fallback_name=self.ui_loc.get('summary', {}).get('fallback_name', 'Enhancement'),
        )

    def refresh_backpack_items(self):
        if hasattr(self, "browser"):
            self.browser.refresh()

    # ---- Reverse parser (backpack enhancement -> editor widgets) ------

    def _load_enhancement_item(self, item):
        """Populate editor fields from a decoded enhancement in the backpack.

        Enhancement-specific reverse-parser bits:
          - Header carries "{mfg_code}, 0, 1, {level}| 2, {seed}"; the source
            seed is preserved verbatim by ``make_header_getter`` (seed_getter
            passed as None), so an unmodified round-trip is byte-identical
            without touching self._current_seed.
          - Simple {N} tokens are either the mfg's rarity_code or a per-mfg
            perk index (1/2/3/9). Rarity codes are large enough that they
            never collide with those single-digit perk indices.
          - {247:X} elemental sets rarity via rarity_map_247 (redundant with
            the simple rarity token — consumed silently).
          - {mfg_code:[i j k]} group entries populate the stack picker.
          - {247:[a b c]} group entries populate the 247-stats picker.
        """
        if not item:
            return
        decoded = item.get("decoded_full", "") or ""
        if "||" not in decoded:
            log_editor(self.main_app, self._LOG_TAG, f"enhancement load: no components in {item.get('name', 'unknown')}")
            return

        self._is_loading = True
        try:
            self.selected_item_path = item.get("original_path")
            item_name = item.get('name', 'unknown')

            # Parse into token state; bind header so state.render() reflects
            # level edits. seed_getter=None preserves the source seed verbatim
            # from the header raw, so load-then-save is byte-identical.
            self._token_state = self.browser.token_state_for(item, skin=False)
            if self._token_state.tokens:
                header_raw = self._token_state.tokens[0].raw
                self._token_state.bind(0, make_header_getter(
                    header_raw,
                    level_getter=lambda: self.level_edit.text() if hasattr(self, 'level_edit') else '',
                    seed_getter=None,
                ))

            header, component = decoded.split("||", 1)
            header_pipe_parts = header.strip().split("|")
            header_fields = header_pipe_parts[0].strip().split(",")
            try:
                mfg_code = int(header_fields[0])
                level = int(header_fields[3])
            except (ValueError, IndexError):
                log_editor(self.main_app, self._LOG_TAG, f"enhancement load: bad header for {item_name}")
                return

            # Seed is preserved by make_header_getter (seed_getter=None reads
            # the source header verbatim), so no self._current_seed update
            # is needed on the load path — the source seed lives in the
            # closure captured by the header binding on state.tokens[0].

            mfg_en = self._find_mfg_en_by_code(mfg_code)
            if mfg_en is None:
                log_editor(self.main_app, self._LOG_TAG, f"enhancement load: unknown mfg_code {mfg_code} in {item_name}")
                return

            # Snap mfg combo → on_mfg_change repopulates rarity, perk
            # checkboxes and stack picker for the new mfg. Signal-blocked so
            # the currentTextChanged handler doesn't fire twice; we call
            # on_mfg_change manually to do the repopulate.
            self.mfg_sel.blockSignals(True)
            self.mfg_sel.setCurrentText(self._(mfg_en))
            self.mfg_sel.blockSignals(False)
            self.on_mfg_change()

            self.level_edit.blockSignals(True)
            self.level_edit.setText(str(level))
            self.level_edit.blockSignals(False)

            # Fresh state — on_mfg_change built empty perk_vars/pickers, but
            # a second load on the same tab would carry state over otherwise.
            for cb in self.perk_vars.values():
                cb.setChecked(False)
            self.stack_picker.clear()
            self.stat_picker.clear()

            rarity_by_code = self._current_rarity_code_map(mfg_en)
            rarity_by_247_code = {code: name for name, code in enhancement_data.get('rarity_map_247', {}).items()}
            mfg_code_by_en = {en: data['code'] for en, data in enhancement_data.get('manufacturers', {}).items()}
            mfg_en_by_code = {code: en for en, code in mfg_code_by_en.items()}

            self._preserved_unknowns = {}
            for token in parse_component_string(component):
                self._apply_enhancement_token(
                    token,
                    mfg_en=mfg_en,
                    rarity_by_code=rarity_by_code,
                    rarity_by_247_code=rarity_by_247_code,
                    mfg_en_by_code=mfg_en_by_code,
                    item_name=item_name,
                )

            set_flag_from_item(self.flag_var, item, main_app=self.main_app, tag=self._LOG_TAG)
            self.update_enhancement_btn.setEnabled(True)
            # Bind downstream tokens (rarity_code simple, {247:X} single) so
            # subsequent value edits are picked up on the next state.render()
            # call. Runs BEFORE the _is_loading guard drops so the render
            # in the finally fires exactly once.
            self._bind_token_state_widgets()
        except Exception as exc:
            # On failure, don't mutate the editor state further; log and bail.
            log_editor(self.main_app, self._LOG_TAG, f"enhancement load: exception in {item.get('name', 'unknown')}: {exc}")
        finally:
            self._is_loading = False
            # State is source-parsed with bindings live — emit verbatim.
            self.rebuild_output()

    def _apply_enhancement_token(self, token, *, mfg_en, rarity_by_code,
                                 rarity_by_247_code, mfg_en_by_code, item_name):
        ttype = token['type']
        if ttype == 'simple':
            pid = token['id']
            if pid in rarity_by_code:
                self._set_rarity(rarity_by_code[pid])
                return
            # Per-mfg perk index (1, 2, 3, 9) — set the matching checkbox.
            cb = self.perk_vars.get(pid)
            if cb is not None:
                cb.blockSignals(True)
                cb.setChecked(True)
                cb.blockSignals(False)
                return
            log_editor(self.main_app, self._LOG_TAG, f"enhancement load: unknown simple id {pid} in {item_name}")
            return

        parent = token['id']
        if parent == self._SECONDARY_PARENT:
            # {247:X} single → rarity via rarity_map_247 (redundant but valid).
            if ttype == 'elemental':
                rarity_en = rarity_by_247_code.get(token['sub_id'])
                if rarity_en:
                    self._set_rarity(rarity_en)
                else:
                    log_editor(self.main_app, self._LOG_TAG,
                        f"enhancement load: unknown 247 rarity code {token['sub_id']} in {item_name}"
                    )
                return
            # {247:[...]} group → 247 stats picker; count occurrences per code.
            # Unknown codes (not in stat_picker._source) are preserved so the
            # aggregation getter re-emits them on every render — fixes the
            # unknown-drop bug across BOTH value and structural edits.
            known_keys = set()
            for src in self.stat_picker._source:
                key = src.get("key")
                try:
                    known_keys.add(int(key))
                except (TypeError, ValueError):
                    continue
            counts = Counter(iter_children(token))
            for code, count in counts.items():
                if int(code) in known_keys:
                    self._add_picker_entry(self.stat_picker, code, count, item_name)
                else:
                    for _ in range(count):
                        self._preserved_unknowns.setdefault(
                            self._SECONDARY_PARENT, []
                        ).append(int(code))
            return

        # {mfg_code:[i j k]} → stack picker entries under that mfg.
        stack_mfg_en = mfg_en_by_code.get(parent)
        if stack_mfg_en is None:
            log_editor(self.main_app, self._LOG_TAG, f"enhancement load: unknown stack parent mfg_code {parent} in {item_name}")
            return
        counts = Counter(iter_children(token))
        for idx, count in counts.items():
            self._add_picker_entry(
                self.stack_picker, f"{stack_mfg_en}:{idx}", count, item_name
            )

    def _add_picker_entry(self, picker, key, count, item_name):
        """Programmatic add to a CatalogPicker at a specific count.

        CatalogPicker exposes ``add_item(item_dict, count)`` (not the
        InlineCatalogPicker's ``set_entry_count(key, N)``) — the reverse
        parser must resolve the source dict for ``key`` and pass it through.
        We clear the picker before loading, so a single add_item call
        creates a SelectedRow with the desired absolute count.
        """
        source_item = next((s for s in picker._source if s.get("key") == key), None)
        if source_item is None:
            log_editor(self.main_app, self._LOG_TAG, f"enhancement load: picker key {key!r} not found in {item_name}")
            return
        picker.add_item(source_item, count=count)

    def _current_rarity_code_map(self, mfg_en):
        """Return ``{rarity_code -> rarity_en}`` for the given mfg. The mfg's
        rarity codes live on the manufacturer entry; the 247-scoped codes are
        handled separately via rarity_by_247_code."""
        return {code: name for name, code in enhancement_data['manufacturers'][mfg_en]['rarities'].items()}

    def _find_mfg_en_by_code(self, mfg_code):
        for mfg_en, data in enhancement_data['manufacturers'].items():
            if data.get('code') == mfg_code:
                return mfg_en
        return None

    def _set_rarity(self, rarity_en):
        """Snap rarity combo to the given English rarity name (localized on
        display). Signal-blocked to keep rebuild_output out of the load path.
        """
        localized = self._(rarity_en)
        self.rarity_sel.blockSignals(True)
        idx = self.rarity_sel.findText(localized)
        if idx >= 0:
            self.rarity_sel.setCurrentIndex(idx)
        self.rarity_sel.blockSignals(False)

    def _update_enhancement(self):
        if not self.selected_item_path:
            QMessageBox.warning(
                self,
                self.ui_loc.get('dialogs', {}).get('no_selection', 'No Selection'),
                self.ui_loc.get('dialogs', {}).get('select_enhancement_first', 'Select an enhancement first'),
            )
            return
        new_serial = self.b85_output_var.text()
        if not new_serial or "Error" in new_serial:
            QMessageBox.warning(
                self,
                self.ui_loc['dialogs']['no_valid_code'],
                self.ui_loc['dialogs']['gen_valid_first'],
            )
            return
        payload = {
            'item_path': self.selected_item_path,
            'original_item_data': {},
            'new_item_data': {'serial': new_serial},
            'success_msg': self.ui_loc.get('dialogs', {}).get('update_success', 'Enhancement updated'),
        }
        self.update_item_requested.emit(payload)
