import pandas as pd
import random
from collections import defaultdict
from functools import lru_cache

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QComboBox, QListWidget, QListWidgetItem,
    QScrollArea, QMessageBox, QSpinBox, QSplitter
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QColor

from core import b_encoder
from core import resource_loader
from tabs.qt_catalog_picker import ContainedWheelListWidget, ContainedWheelScrollArea
from tabs.qt_item_browser import ItemBrowser, ROW_HEIGHT, list_widget_by_userrole, parse_stack_count, stack_into_sel_list
from tabs.qt_editor_shared import (
    Token,
    TokenOrderedState,
    combo_data_ids,
    emit_update_or_warn,
    find_mfg_combo_index,
    iter_children,
    legendary_lookup,
    load_tab_ui_loc,
    log_editor,
    make_header_getter,
    parse_component_string,
    populate_flag_combo,
    populate_radio_buttons,
    selected_mfg_id_from_combo,
    set_flag_from_item,
    set_rarity_by_id,
    summarize_item,
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
    update_item_requested = pyqtSignal(dict)
    # Re-emit from ``self.browser.item_delete_requested`` — connected inside
    # _build_ui after browser creation so it survives language-switch rebuilds.
    item_delete_requested = pyqtSignal(list)

    _LOG_TAG = "repkit"

    # Rarity combo has to be a fixed width so the localized text doesn't push
    # the neighbouring level box around on language change. Used twice in
    # _create_top_controls and on_mfg_change.
    _RARITY_COMBO_WIDTH = 300

    # Parent-ID under which every repkit secondary sub-part lives: prefix,
    # firmware, resistance radios, universal perks, and Model-Plus derivatives
    # all share {243:...} in the serial.
    _SECONDARY_PARENT = 243

    # Manufacturer parent-IDs surfaced in the mfg picker, in display order.
    # Never mutated at runtime — promoted to a class constant for parity with
    # _SECONDARY_PARENT and to make the ordering intent explicit.
    _MFG_IDS: tuple[int, ...] = (277, 265, 266, 285, 274, 290, 261, 269)

    # Map of {trigger_part_id: derived_model_plus_id}. rebuild_output uses this
    # to auto-append the model-plus token whenever a matching resistance/immunity
    # part is selected; _load_repkit_item uses the value-set to silently skip
    # those derived tokens (the widget state re-derives them on rebuild).
    #
    # Consolidating trigger + derived into one dict lets a future data change
    # touch a single place instead of updating parallel lists.
    _MODEL_PLUS_MAP = {
        # combustion → 98
        24: 98, 50: 98, 29: 98, 44: 98,
        # radiation → 99
        23: 99, 47: 99, 28: 99, 43: 99,
        # corrosive → 100
        26: 100, 51: 100, 31: 100, 46: 100,
        # shock → 101
        22: 101, 49: 101, 27: 101, 42: 101,
        # cryo → 102
        25: 102, 48: 102, 30: 102, 45: 102,
    }
    _MODEL_PLUS_IDS = frozenset(_MODEL_PLUS_MAP.values())

    def __init__(self, main_app=None, parent=None):
        super().__init__(parent)
        self.main_app = main_app
        self.current_lang = 'zh-CN'
        self._character_level = "50"
        self.df_main, self.df_mfg, self.localization = load_repkit_data(self.current_lang)

        self._load_ui_localization()

        if self.df_main is None or self.df_mfg is None:
            layout = QVBoxLayout(self)
            layout.addWidget(QLabel(self.ui_loc.get('dialogs', {}).get('load_error', "错误: 修复套件数据(repkit data)无法加载。")))
            return

        # State initialization.  初始化变量
        self.prefix_widgets = []
        self.firmware_widgets = []
        self.resistance_widgets = []

        # State for backpack browser + reverse-parser flow
        self.selected_item_path = None
        self._is_loading = False
        self._encode_error = False
        # Token-preserving state — every rebuild routes through
        # ``state.render()``; the token stream is authoritative. Value edits
        # (rarity, level) are picked up via bindings — the {243:...} tokens
        # stay UNBOUND so their source raw form is preserved verbatim (this
        # is what keeps the split-list ``{243:[105 99]} {243:90}`` shape
        # across rarity/level edits). Structural edits (radio flip, picker
        # add/remove, legendary change) surgically remove the affected
        # category's tokens and re-insert; unknown top-level simples stay
        # untouched, and unknown children of {243:...} live in
        # ``_preserved_unknowns`` so the re-inserted token includes them.
        self._token_state = TokenOrderedState([])
        self._preserved_unknowns: dict[int, list[int]] = {}
        # Session-random seed for fresh items. Backpack loads preserve the
        # source header via make_header_getter(seed_getter=None); this only
        # fires when the user creates a fresh repkit via mfg-change /
        # Add-to-Backpack. Randomized to match weapon/heavy/enhancement so
        # multiple fresh repkits don't collide on a single hardcoded seed.
        self._current_seed = str(random.randint(100, 9999))
        self._populating = False

        self._build_ui()
        self.populate_initial_data()
        self._connect_signals()
        self.on_mfg_change()
        self.refresh_backpack_items()

    def _load_ui_localization(self):
        self.ui_loc = load_tab_ui_loc("repkit_tab", self.current_lang)

    def update_language(self, lang):
        log_editor(self.main_app, self._LOG_TAG, f"Updating language for {self.__class__.__name__} to {lang}...")
        self.current_lang = lang
        self.df_main, self.df_mfg, self.localization = load_repkit_data(lang)

        if self.df_main is None or self.df_mfg is None:
            log_editor(self.main_app, self._LOG_TAG, f"load_repkit_data failed for {self.__class__.__name__}")
            return

        self._load_ui_localization()

        if not self.ui_loc:
            log_editor(self.main_app, self._LOG_TAG, f"UI localization missing for {self.__class__.__name__}")
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

        # Rebuild the browser with the new locale, preserving current selection.
        # Re-run the reverse parser afterwards: populate_initial_data wiped the
        # editor state to defaults, so the row-highlight would otherwise drift
        # from what's actually in the editor.
        if hasattr(self, "browser"):
            selected_path = self.selected_item_path
            self.browser.refresh()
            if selected_path:
                self.browser.set_selected_path(selected_path)
                current = self.browser.current_item()
                if current:
                    self._load_repkit_item(current)
        log_editor(self.main_app, self._LOG_TAG, f"Finished updating language for {self.__class__.__name__}.")

    def _(self, text):
        return self.localization.get(str(text), str(text))

    def _build_ui(self):
        main_layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        main_layout.addWidget(splitter)

        # Left: shared backpack browser
        self.browser = ItemBrowser(
            main_app=self.main_app,
            item_filter=self._is_repkit_item,
            row_builder=self._repkit_browser_row,
            header_label=self.ui_loc.get('labels', {}).get('load_from_backpack', 'Load from Backpack'),
            search_placeholder=self.ui_loc.get('labels', {}).get('search_repkit_placeholder', 'Search repkit...'),
            empty_placeholder=self.ui_loc.get('dialogs', {}).get('no_repkits_in_backpack', 'No repkits in backpack'),
            no_save_placeholder=self.ui_loc.get('dialogs', {}).get('decrypt_save_to_show', 'Decrypt save first'),
            summary_formatter=self._summarize_repkit,
            summary_none_text=self.ui_loc.get('summary', {}).get('none_selected', 'No backpack repkit selected'),
        )
        # Re-emit so main_window can wire once to a signal that survives
        # _build_ui rebuilds (browser gets recreated on language switch).
        self.browser.item_delete_requested.connect(self.item_delete_requested.emit)
        self.browser.item_selected.connect(self._load_repkit_item)
        splitter.addWidget(self.browser)

        # Right: existing scrollable editor content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

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
        
        self.legendary_group = self._create_list_perk_group(self.ui_loc['groups']['legendary'], 'legendary', use_multiplier=False)
        self.universal_group = self._create_list_perk_group(self.ui_loc['groups']['universal'], 'universal', use_multiplier=True)
        
        perks_layout.addWidget(self.legendary_group, 1, 0, 1, 3)
        perks_layout.addWidget(self.universal_group, 2, 0, 1, 3)

        layout.addWidget(self.perks_group)

        splitter.addWidget(scroll)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([320, 1040])

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
        self.update_repkit_btn = QPushButton(self.ui_loc.get('buttons', {}).get('update_repkit', 'Update'))
        self.update_repkit_btn.setEnabled(False)
        self.flag_combo = QComboBox()
        self._populate_flags()

        self.b85_label = QLabel(self.ui_loc['labels']['base85'])
        grid.addWidget(self.b85_label, 1, 0)
        grid.addWidget(self.b85_output_edit, 1, 1)
        grid.addWidget(self.copy_b85_btn, 1, 2)
        grid.addWidget(self.flag_combo, 1, 3)
        grid.addWidget(self.add_to_pack_btn, 1, 4)
        grid.addWidget(self.update_repkit_btn, 1, 5)

        self.copy_raw_btn.clicked.connect(lambda: self._copy_to_clipboard(self.raw_output_edit))
        self.copy_b85_btn.clicked.connect(lambda: self._copy_to_clipboard(self.b85_output_edit))
        self.update_repkit_btn.clicked.connect(self._update_repkit)

        layout.addWidget(self.output_group)

    def _create_top_controls(self, layout):
        self.base_attrs_group = QGroupBox(self.ui_loc['groups']['base_attrs'])
        controls_layout = QHBoxLayout(self.base_attrs_group)

        self.mfg_combo = QComboBox()
        self.level_edit = QLineEdit(self._character_level)
        self.level_edit.setFixedWidth(100)
        self.rarity_combo = QComboBox()
        self.rarity_combo.setFixedWidth(self._RARITY_COMBO_WIDTH)

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

    def _create_list_perk_group(self, title, key, use_multiplier=False):
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

        setattr(self, f"{key}_avail_list", avail)
        setattr(self, f"{key}_sel_list", sel)
        setattr(self, f"{key}_clear_btn", clear_btn)
        if multiplier_box:
            setattr(self, f"{key}_multiplier", multiplier_box)

        move_btn.clicked.connect(lambda: self._move_selected_items(avail, sel, multiplier_box))
        remove_btn.clicked.connect(lambda: self._remove_selected_items(sel))
        clear_btn.clicked.connect(lambda: self._clear_list(sel))
        
        return group

    def _connect_signals(self):
        self.mfg_combo.currentTextChanged.connect(self.on_mfg_change)
        self.level_edit.textChanged.connect(self.rebuild_output)
        self.rarity_combo.currentTextChanged.connect(self._on_rarity_changed)
        self.add_to_pack_btn.clicked.connect(self._add_to_backpack)
        # Legendary: surgical rebuild of legendary-only tokens on change.
        self.legendary_sel_list.model().rowsInserted.connect(self._on_legendary_changed)
        self.legendary_sel_list.model().rowsRemoved.connect(self._on_legendary_changed)
        self.legendary_sel_list.model().dataChanged.connect(self._on_legendary_changed)
        # Universal: surgical rebuild of {243:...} bucket tokens on change.
        self.universal_sel_list.model().rowsInserted.connect(self._on_secondary_widget_changed)
        self.universal_sel_list.model().rowsRemoved.connect(self._on_secondary_widget_changed)
        self.universal_sel_list.model().dataChanged.connect(self._on_secondary_widget_changed)

    def _get_mfg_name(self, mfg_id):
        if mfg_id in lookup.REVERSE_ID_MAP:
            mfg_en = lookup.REVERSE_ID_MAP[mfg_id][0]
            return bl4f.get_localized_string(mfg_en)
        return "Unknown"

    def populate_initial_data(self):
        self.mfg_combo.clear()
        
        items = []
        for k in self._MFG_IDS:
            name = self._get_mfg_name(k)
            items.append((f"{name} - {k}", k))
        
        items.sort(key=lambda x: x[1])
        self.mfg_combo.addItems([x[0] for x in items])

        df_secondary = self.df_main[self.df_main['Repkit_perk_main_ID'] == self._SECONDARY_PARENT]

        # Each map feeds populate_radio_buttons and isn't read anywhere else,
        # so no instance state needed.
        # Prefix / firmware / resistance radios contribute to the {243:[...]}
        # list token in the serial; adding or removing an entry there is a
        # structural change, so all three radio groups route through
        # _on_structural_change (which also handles the auto-derived Model
        # Plus token that shadows resistance selection — see _MODEL_PLUS_MAP).
        self.prefix_widgets, self.prefix_none_rb = populate_radio_buttons(
            self.prefix_frame,
            list(self._get_datamap_from_df(df_secondary, 'Perfix').items()),
            on_toggle=self._on_secondary_widget_changed,
            none_label=self.ui_loc['misc']['none'],
        )
        self.firmware_widgets, self.firmware_none_rb = populate_radio_buttons(
            self.firmware_frame,
            list(self._get_datamap_from_df(df_secondary, 'Firmware').items()),
            on_toggle=self._on_secondary_widget_changed,
            none_label=self.ui_loc['misc']['none'],
        )
        self.resistance_widgets, self.resistance_none_rb = populate_radio_buttons(
            self.resistance_frame,
            list(self._get_datamap_from_df(df_secondary, ['Resistance', 'Immunity']).items()),
            on_toggle=self._on_secondary_widget_changed,
            none_label=self.ui_loc['misc']['none'],
        )
        self._populate_listbox(self.universal_avail_list, df_secondary, 'Perk')

    def on_mfg_change(self, *args):
        mfg_id = selected_mfg_id_from_combo(self.mfg_combo)
        if mfg_id is None:
            return

        self.rarity_combo.blockSignals(True)
        self.rarity_combo.clear()
        rarities_df = self.df_mfg[(self.df_mfg['Manufacturer ID'] == mfg_id) & (self.df_mfg['Part_type'] == 'Rarity')]
        for _, row in rarities_df.iterrows():
            desc = f" - {row['Description']}" if pd.notna(row['Description']) and row['Description'] else ""
            display_text = f"{self._(row['Stat'])}{desc}"
            self.rarity_combo.addItem(display_text, int(row['Part_ID']))
        self.rarity_combo.blockSignals(False)

        self.legendary_avail_list.clear()
        legendary_perks_df = self.df_mfg[self.df_mfg['Part_type'] == 'Legendary Perk'].copy()
        legendary_perks_df['sort_key'] = legendary_perks_df['Manufacturer ID'].apply(lambda x: 0 if x == mfg_id else 1)
        legendary_perks_df = legendary_perks_df.sort_values(by=['sort_key', 'Manufacturer ID', 'Part_ID'])

        for _, row in legendary_perks_df.iterrows():
            mfg_name = self._get_mfg_name(row['Manufacturer ID'])
            display_text = f"{mfg_name} - {row['Stat']} - {row['Description']}"
            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, (int(row['Part_ID']), int(row['Manufacturer ID'])))
            self.legendary_avail_list.addItem(item)
            if row['Manufacturer ID'] != mfg_id:
                item.setForeground(QColor('#aaa'))

        # on_mfg_change reshapes the mfg-scoped widgets (rarity + legendary
        # avail); item type effectively changed → fresh state (Option 1).
        if not self._is_loading:
            self._reset_state_to_fresh_item(mfg_id)

    def rebuild_output(self, *args):
        """State-first render. Widget values flow through bindings (rarity)
        or through the token's raw form (everything else). Structural edits
        surgically mutate state in ``_on_*`` handlers via ``state.insert()``
        / ``state.remove_with_whitespace()``. The {243:...} tokens stay
        UNBOUND so their source raw form is preserved verbatim across value
        edits — this is what keeps the split-list shape alive on
        load-then-rarity-edit.
        """
        if self._is_loading:
            return
        if not self._token_state.tokens:
            return
        try:
            decoded = self.browser.render_from_state(self._token_state)
            self.raw_output_edit.setText(decoded)
            encoded, err = b_encoder.encode_to_base85(decoded)
            self._encode_error = bool(err)
            self.b85_output_edit.setText(
                f"{self.ui_loc.get('dialogs', {}).get('error', 'Error')}: {err}"
                if err else encoded
            )
        except Exception as e:
            log_editor(self.main_app, self._LOG_TAG, f"repkit rebuild error: {e}")

    # ---- Structural handlers ------------------------------------------
    #
    # Structural changes collapse split ``{243:[..]} {243:X}`` into a single
    # aggregated token; the split-preservation invariant only holds on VALUE
    # edits (where the {243:...} tokens stay unbound and raw-emit). Unknowns
    # are preserved even on structural edits via ``self._preserved_unknowns``.

    def _on_rarity_changed(self, *args):
        if self._is_loading or self._populating:
            return
        if not self._token_state.tokens:
            return
        data = self.rarity_combo.currentData()
        idx = self._find_rarity_token_idx()
        if data is None:
            if idx != -1:
                self._token_state.remove_with_whitespace(idx)
            self.rebuild_output()
            return
        if idx == -1:
            insert_at = 1
            pid = int(data)
            self._token_state.insert(insert_at, Token(raw=" ", kind="raw"))
            self._token_state.insert(insert_at + 1, Token(
                raw=f"{{{pid}}}", kind='simple', value=pid,
            ))
            self._token_state.bind(insert_at + 1, self._rarity_getter())
        self.rebuild_output()

    def _on_legendary_changed(self, *args):
        """Surgical rebuild of legendary tokens + auto-emitted Model token."""
        if self._is_loading or self._populating:
            return
        if not self._token_state.tokens:
            return
        mfg_id = selected_mfg_id_from_combo(self.mfg_combo)
        if mfg_id is None:
            return
        legendary_pairs = set()
        for i in range(self.legendary_avail_list.count()):
            av_item = self.legendary_avail_list.item(i)
            data = av_item.data(Qt.ItemDataRole.UserRole)
            if isinstance(data, tuple) and len(data) == 2:
                legendary_pairs.add((int(data[0]), int(data[1])))
        # Model IDs across all mfgs so we can drop a stale auto-emitted one.
        model_ids: set[int] = set()
        for _, row in self.df_mfg[self.df_mfg['Part_type'] == 'Model'].iterrows():
            model_ids.add(int(row['Part_ID']))

        to_remove: list[int] = []
        for idx, tok in enumerate(self._token_state.tokens):
            if tok.kind == 'simple' and tok.parent is None:
                if (tok.value, mfg_id) in legendary_pairs or tok.value in model_ids:
                    to_remove.append(idx)
            elif tok.kind == 'single' and tok.parent is not None and tok.parent != self._SECONDARY_PARENT:
                if (tok.value, tok.parent) in legendary_pairs:
                    to_remove.append(idx)
            elif tok.kind == 'list' and tok.parent is not None and tok.parent != self._SECONDARY_PARENT:
                if any((c, tok.parent) in legendary_pairs for c in tok.children):
                    to_remove.append(idx)
        for idx in reversed(to_remove):
            self._token_state.remove_with_whitespace(idx)

        insert_at = self._insert_idx_before_secondary()
        # Auto-emit the Model row's Part_ID so the serial always carries a
        # valid Model token even when the legendary sel_list is empty.
        model_row = self.df_mfg[
            (self.df_mfg['Manufacturer ID'] == mfg_id)
            & (self.df_mfg['Part_type'] == 'Model')
        ]
        model_pid = int(model_row.iloc[0]['Part_ID']) if not model_row.empty else None

        cross_mfg: dict[int, list[int]] = defaultdict(list)
        has_legendary = self.legendary_sel_list.count() > 0
        if model_pid is not None:
            # Model token emitted unconditionally — game always expects one.
            self._token_state.insert(insert_at, Token(raw=" ", kind="raw"))
            self._token_state.insert(insert_at + 1, Token(
                raw=f"{{{model_pid}}}", kind='simple', value=model_pid,
            ))
            insert_at += 2
        _ = has_legendary  # unused; model emits regardless of legendary content

        for i in range(self.legendary_sel_list.count()):
            it = self.legendary_sel_list.item(i)
            count, _c = parse_stack_count(it.text())
            perk_id, perk_mfg = it.data(Qt.ItemDataRole.UserRole)
            perk_id, perk_mfg = int(perk_id), int(perk_mfg)
            for _ in range(count):
                if perk_mfg == mfg_id:
                    self._token_state.insert(insert_at, Token(raw=" ", kind="raw"))
                    self._token_state.insert(insert_at + 1, Token(
                        raw=f"{{{perk_id}}}", kind='simple', value=perk_id,
                    ))
                    insert_at += 2
                else:
                    cross_mfg[perk_mfg].append(perk_id)
        for parent, ids in cross_mfg.items():
            self._token_state.insert(insert_at, Token(raw=" ", kind="raw"))
            if len(ids) == 1:
                self._token_state.insert(insert_at + 1, Token(
                    raw=f"{{{parent}:{ids[0]}}}", kind='single',
                    parent=parent, value=ids[0],
                ))
            else:
                body = " ".join(str(i) for i in ids)
                self._token_state.insert(insert_at + 1, Token(
                    raw=f"{{{parent}:[{body}]}}", kind='list',
                    parent=parent, children=list(ids),
                ))
            insert_at += 2
        self.rebuild_output()

    def _on_secondary_widget_changed(self, *args):
        """Surgical rebuild of {243:...} bucket tokens. Collapses split-list
        into a single aggregated token; unknown children preserved via
        ``self._preserved_unknowns[_SECONDARY_PARENT]``.
        """
        if self._is_loading or self._populating:
            return
        if not self._token_state.tokens:
            return
        # Remove ALL {243:...} tokens.
        to_remove: list[int] = []
        for idx, tok in enumerate(self._token_state.tokens):
            if tok.parent == self._SECONDARY_PARENT and tok.kind in ('single', 'list'):
                to_remove.append(idx)
        for idx in reversed(to_remove):
            self._token_state.remove_with_whitespace(idx)
        # Compose fresh aggregation and insert.
        parts = self._secondary_children_from_widgets()
        parts.extend(self._preserved_unknowns.get(self._SECONDARY_PARENT, []))
        if parts:
            insert_at = self._insert_idx_before_trailing_pipe()
            self._token_state.insert(insert_at, Token(raw=" ", kind="raw"))
            if len(parts) == 1:
                self._token_state.insert(insert_at + 1, Token(
                    raw=f"{{{self._SECONDARY_PARENT}:{parts[0]}}}",
                    kind='single', parent=self._SECONDARY_PARENT, value=parts[0],
                ))
            else:
                body = " ".join(str(p) for p in parts)
                self._token_state.insert(insert_at + 1, Token(
                    raw=f"{{{self._SECONDARY_PARENT}:[{body}]}}",
                    kind='list', parent=self._SECONDARY_PARENT, children=list(parts),
                ))
        self.rebuild_output()

    def _secondary_children_from_widgets(self) -> list[int]:
        """Ordered widget-contributed children (no preserved unknowns)."""
        parts: list[int] = []
        for widgets in [self.prefix_widgets, self.firmware_widgets, self.resistance_widgets]:
            for rb in widgets:
                if rb.isChecked() and rb.property("part_id"):
                    part_id = int(rb.property("part_id"))
                    parts.append(part_id)
                    derived = self._MODEL_PLUS_MAP.get(part_id)
                    if derived is not None:
                        parts.append(int(derived))
                    break
        for i in range(self.universal_sel_list.count()):
            item = self.universal_sel_list.item(i)
            count, _ = parse_stack_count(item.text())
            perk_id = item.data(Qt.ItemDataRole.UserRole)
            if perk_id is not None:
                for _ in range(count):
                    parts.append(int(perk_id))
        return parts

    def _rarity_getter(self):
        def getter():
            data = self.rarity_combo.currentData()
            return f"{{{int(data)}}}" if data is not None else None
        return getter

    def _find_rarity_token_idx(self) -> int:
        rarity_ids = combo_data_ids(self.rarity_combo)
        for idx, tok in enumerate(self._token_state.tokens):
            if tok.kind == 'simple' and tok.parent is None and tok.value in rarity_ids:
                return idx
        return -1

    def _insert_idx_before_secondary(self) -> int:
        for idx, tok in enumerate(self._token_state.tokens):
            if tok.parent == self._SECONDARY_PARENT and tok.kind in ('single', 'list'):
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

    def _reset_state_to_fresh_item(self, mfg_id: int) -> None:
        """Fresh-item state: [header, ' |']. Rarity + Model token + secondary
        inserted lazily via handlers. Option 1 for mfg change."""
        self._preserved_unknowns = {}
        level = self.level_edit.text() or self._character_level
        # Fresh-item seed comes from session-random ``_current_seed`` (see
        # __init__), matching weapon/heavy/enhancement. Bound header still
        # passes seed_getter=None so loaded items preserve their source seed
        # byte-identical.
        header_raw = f"{mfg_id}, 0, 1, {level}| 2, {self._current_seed}||"
        tokens = [Token(raw=header_raw, kind='raw'), Token(raw=" |", kind='raw')]
        self._token_state = TokenOrderedState(tokens)
        self._token_state.bind(0, make_header_getter(
            header_raw,
            level_getter=lambda: self.level_edit.text(),
            seed_getter=None,
        ))
        self._on_rarity_changed()
        self._on_legendary_changed()
        self._on_secondary_widget_changed()

    def _bind_token_state_widgets(self):
        """Attach getters to loaded state: rarity only. The {243:...} tokens
        stay UNBOUND so their source raw form is emitted verbatim on value
        edits (preserves split-list shape). Structural handlers surgically
        rebuild the {243:...} category.
        """
        if not self._token_state.tokens:
            return
        rarity_ids = combo_data_ids(self.rarity_combo)
        for idx, tok in enumerate(self._token_state.tokens):
            if tok.kind == 'simple' and tok.parent is None and tok.value in rarity_ids:
                self._token_state.bind(idx, self._rarity_getter())
                break

    def _populate_listbox(self, listbox, df, part_type):
        listbox.clear()
        items_df = df[df['Part_type'] == part_type]
        for _, row in items_df.iterrows():
            name = self._(row['Stat'])
            desc = row['Description'] if pd.notna(row['Description']) else ''
            display_text = f"{name} - {desc} [{row['Part_ID']}]" if desc else f"{name} [{row['Part_ID']}]"
            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, row['Part_ID'])
            listbox.addItem(item)

    def _get_datamap_from_df(self, df, part_type):
        item_map = {}
        if isinstance(part_type, str): part_type = [part_type]
        items_df = df[df['Part_type'].isin(part_type)]
        for _, row in items_df.iterrows():
            stat = self._(row['Stat'])
            desc = row['Description'] if pd.notna(row['Description']) and row['Description'] else ''
            display_text = f"{stat} - {desc}" if desc else f"{stat}"
            item_map[display_text.strip(" -")] = row['Part_ID']
        return item_map

    def _move_selected_items(self, src, dest, multiplier_box=None):
        count_val = multiplier_box.value() if multiplier_box else 1
        for item in src.selectedItems():
            base_text = item.text()

            existing_item = None
            current_count = 1
            for i in range(dest.count()):
                sel_item = dest.item(i)
                current_count, current_name = parse_stack_count(sel_item.text())
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
        # rowsInserted on the underlying model fires _on_structural_change
        # via the sel_list signal wiring; no extra call needed here.

    def _remove_selected_items(self, list_widget):
        for item in list_widget.selectedItems():
            list_widget.takeItem(list_widget.row(item))
        # rowsRemoved fires _on_structural_change; no extra call needed.

    def _clear_list(self, list_widget):
        list_widget.clear()
        # rowsRemoved fires _on_structural_change; no extra call needed.

    def _populate_flags(self):
        populate_flag_combo(self.flag_combo, self.current_lang)

    def _copy_to_clipboard(self, line_edit):
        QApplication.clipboard().setText(line_edit.text())
        QMessageBox.information(self, self.ui_loc['dialogs']['success'], self.ui_loc['dialogs']['copied'])
        
    def _add_to_backpack(self):
        serial = self.b85_output_edit.text()
        if not serial or getattr(self, '_encode_error', False):
            QMessageBox.warning(self, self.ui_loc['dialogs']['no_valid_code'], self.ui_loc['dialogs']['gen_first'])
            return
        self.add_to_backpack_requested.emit(serial, self.flag_combo.currentText().split(" ")[0])

    # ---- Backpack browser integration ---------------------------------

    @staticmethod
    def _is_repkit_item(item):
        return item.get("type_en") == "Repkit" and "Backpack" in (item.get("container") or "")

    def _repkit_browser_row(self, item):
        manufacturer = item.get("manufacturer") or self.ui_loc.get('parts', {}).get('unknown', 'Unknown')
        type_label = item.get("type") or self.ui_loc.get('parts', {}).get('unknown_item', 'Repkit')
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

        stat_titles = self.ui_loc.get('stats', {})
        stats_layout = QGridLayout()
        stats_layout.setContentsMargins(0, 2, 0, 0)
        stats_layout.setHorizontalSpacing(4)
        stats_layout.setVerticalSpacing(1)
        for column, key in enumerate(("heal_amount", "cooldown", "duration", "aoe", "charges")):
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

    def _summarize_repkit(self, item):
        return summarize_item(
            item,
            template=self.ui_loc.get('summary', {}).get('selected', 'Selected · {name} · Lv.{level}'),
            none_text=self.ui_loc.get('summary', {}).get('none_selected', 'No backpack repkit selected'),
            fallback_name=self.ui_loc.get('summary', {}).get('fallback_name', 'Repkit'),
        )

    def refresh_backpack_items(self):
        if hasattr(self, "browser"):
            self.browser.refresh()

    # ---- Reverse parser (backpack repkit -> editor widgets) -----------

    def _load_repkit_item(self, item):
        """Populate editor fields from a decoded repkit in the backpack.

        Repkit-specific dispatch differs from grenade:
          - secondary parent is ``self._SECONDARY_PARENT`` (grenade uses its own)
          - Model Plus IDs {98,99,100,101,102} are auto-derived from resistance
            selection — silently skip on load; rebuild re-emits them
          - the Model row's part_id (from df_mfg[Part_type=='Model']) is
            auto-emitted per mfg — silently skip on load too
          - three secondary radio groups (prefix / firmware / resistance)
            rather than grenade's two (element / firmware); no mfg-perk
            checkbox group
        """
        if not item:
            return
        decoded = item.get("decoded_full", "") or ""
        if "||" not in decoded:
            log_editor(self.main_app, self._LOG_TAG, f"repkit load: no components in {item.get('name', 'unknown')}")
            return

        self._is_loading = True
        try:
            header, component = decoded.split("||", 1)
            header_fields = header.strip().split("|")[0].strip().split(",")
            try:
                mfg_id = int(header_fields[0])
                level = int(header_fields[3])
            except (ValueError, IndexError):
                log_editor(self.main_app, self._LOG_TAG, f"repkit load: bad header for {item.get('name', 'unknown')}")
                return

            # Unknown mfg → bail out before touching any widget state; leaving
            # the Update button disabled and the path unset prevents emitting a
            # bogus serial for a repkit we can't represent.
            mfg_idx = find_mfg_combo_index(self.mfg_combo, mfg_id)
            if mfg_idx < 0:
                log_editor(self.main_app, self._LOG_TAG, f"repkit load: unknown mfg {mfg_id} in {item.get('name', 'unknown')}")
                return

            self.selected_item_path = item.get("original_path")

            # Parse into token state; bind header via make_header_getter so
            # ``state.render()`` preserves the source seed on load-then-save
            # (fixes the hardcoded 307 bug) and picks up level edits.
            self._token_state = self.browser.token_state_for(item, skin=False)
            if self._token_state.tokens:
                header_raw = self._token_state.tokens[0].raw
                self._token_state.bind(0, make_header_getter(
                    header_raw,
                    level_getter=lambda: self.level_edit.text(),
                    seed_getter=None,
                ))

            # Snap mfg → run on_mfg_change (repopulates rarity + legendary_avail).
            self.mfg_combo.blockSignals(True)
            self.mfg_combo.setCurrentIndex(mfg_idx)
            self.mfg_combo.blockSignals(False)
            self.on_mfg_change()

            self.level_edit.blockSignals(True)
            self.level_edit.setText(str(level))
            self.level_edit.blockSignals(False)

            # Reset the three secondary radio groups; reset the two sel lists.
            # widget_list holds only the data-driven radios (populate helper
            # keeps the None radio separately as ``self.{group}_none_rb``), so
            # ``_widgets[0]`` is the first real perk — checking it here would
            # emit a bogus token. Check the group's None radio instead; radios
            # share a parent widget so auto-exclusive semantics unset any
            # previously-selected data radio automatically.
            self.prefix_none_rb.setChecked(True)
            self.firmware_none_rb.setChecked(True)
            self.resistance_none_rb.setChecked(True)
            self.legendary_sel_list.clear()
            self.universal_sel_list.clear()

            rarity_ids = combo_data_ids(self.rarity_combo)
            model_id = self._current_model_id(mfg_id)
            prefix_by_id = {
                rb.property("part_id"): rb for rb in self.prefix_widgets if rb.property("part_id")
            }
            firmware_by_id = {
                rb.property("part_id"): rb for rb in self.firmware_widgets if rb.property("part_id")
            }
            resistance_by_id = {
                rb.property("part_id"): rb for rb in self.resistance_widgets if rb.property("part_id")
            }
            universal_by_id = list_widget_by_userrole(self.universal_avail_list)
            legendary_by_id = legendary_lookup(self.legendary_avail_list)

            self._preserved_unknowns = {}
            for token in parse_component_string(component):
                self._apply_repkit_token(
                    token, mfg_id,
                    rarity_ids=rarity_ids,
                    model_id=model_id,
                    prefix_by_id=prefix_by_id,
                    firmware_by_id=firmware_by_id,
                    resistance_by_id=resistance_by_id,
                    universal_by_id=universal_by_id,
                    legendary_by_id=legendary_by_id,
                    item_name=item.get("name", "unknown"),
                )

            set_flag_from_item(self.flag_combo, item, main_app=self.main_app, tag=self._LOG_TAG)
            self.update_repkit_btn.setEnabled(True)
            # Bind downstream tokens (rarity) so subsequent value edits are
            # picked up on the next state.render() call. Runs BEFORE the
            # _is_loading guard drops so the render fires exactly once.
            self._bind_token_state_widgets()
        finally:
            self._is_loading = False
            # State is source-parsed with bindings live — emit verbatim.
            self.rebuild_output()

    def _apply_repkit_token(self, token, mfg_id, *, rarity_ids, model_id,
                            prefix_by_id, firmware_by_id, resistance_by_id,
                            universal_by_id, legendary_by_id, item_name):
        ttype = token['type']
        if ttype == 'simple':
            pid = token['id']
            if pid in rarity_ids:
                set_rarity_by_id(self.rarity_combo, pid, main_app=self.main_app, tag=self._LOG_TAG)
            elif model_id is not None and pid == model_id:
                return  # auto-emitted Model token; ignored on load
            elif (pid, mfg_id) in legendary_by_id:
                stack_into_sel_list(self.legendary_sel_list, legendary_by_id[(pid, mfg_id)])
            else:
                log_editor(self.main_app, self._LOG_TAG, f"repkit load: unknown simple id {pid} in {item_name}")
            return

        # elemental and group share dispatch — iter_children normalizes the
        # difference so each parent gets one branch instead of two mirrors.
        parent = token['id']
        for child in iter_children(token):
            if parent == self._SECONDARY_PARENT:
                self._dispatch_secondary_child(child, prefix_by_id, firmware_by_id, resistance_by_id, universal_by_id, item_name)
            elif (child, parent) in legendary_by_id:
                stack_into_sel_list(self.legendary_sel_list, legendary_by_id[(child, parent)])
            else:
                log_editor(self.main_app, self._LOG_TAG, f"repkit load: unknown cross-mfg leg {parent}:{child} in {item_name}")

    def _dispatch_secondary_child(self, pid, prefix_by_id, firmware_by_id, resistance_by_id, universal_by_id, item_name):
        """Route a Part_ID under ``self._SECONDARY_PARENT`` in priority order:
        Model Plus derivative (skip) → prefix / firmware / resistance radio →
        universal perk sel list → preserved unknown. Unknowns are stored so the
        structural rebuild handler re-emits them on every mutation.
        """
        if pid in self._MODEL_PLUS_IDS:
            return  # derived from resistance state; rebuild re-emits
        if pid in prefix_by_id:
            prefix_by_id[pid].setChecked(True)
        elif pid in firmware_by_id:
            firmware_by_id[pid].setChecked(True)
        elif pid in resistance_by_id:
            resistance_by_id[pid].setChecked(True)
        elif pid in universal_by_id:
            stack_into_sel_list(self.universal_sel_list, universal_by_id[pid], use_prefix=True)
        else:
            self._preserved_unknowns.setdefault(self._SECONDARY_PARENT, []).append(int(pid))
            log_editor(self.main_app, self._LOG_TAG, f"repkit load: unknown {self._SECONDARY_PARENT}-child id {pid} preserved in {item_name}")

    def _current_model_id(self, mfg_id):
        # Cast on ingestion: pandas hands out numpy.int64; the token stream
        # produces Python int. See list_widget_by_userrole for full rationale.
        model_row = self.df_mfg[(self.df_mfg['Manufacturer ID'] == mfg_id) & (self.df_mfg['Part_type'] == 'Model')]
        if model_row.empty:
            return None
        return int(model_row.iloc[0]['Part_ID'])

    def _update_repkit(self):
        emit_update_or_warn(
            self,
            new_serial=self.b85_output_edit.text(),
            no_selection_title=self.ui_loc.get('dialogs', {}).get('no_selection', 'No Selection'),
            no_selection_msg=self.ui_loc.get('dialogs', {}).get('select_repkit_first', 'Select a repkit first'),
            no_valid_code_title=self.ui_loc.get('dialogs', {}).get('no_valid_code', 'No Valid Code'),
            no_valid_code_msg=self.ui_loc.get('dialogs', {}).get('gen_first', 'Generate a valid repkit first'),
            success_msg=self.ui_loc.get('dialogs', {}).get('update_success', 'Repkit updated'),
        )

    def set_character_level(self, level: str):
        """Update the default level shown in level_edit.
        设置角色等级，更新默认等级显示。"""
        self._character_level = level if level else "50"
        if hasattr(self, 'level_edit'):
            self.level_edit.setText(self._character_level)
