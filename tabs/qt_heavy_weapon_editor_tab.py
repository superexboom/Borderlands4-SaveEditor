import pandas as pd
from functools import lru_cache
import random

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QComboBox, QListWidgetItem,
    QScrollArea, QMessageBox, QAbstractItemView, QSpinBox, QSplitter
)
from PyQt6.QtCore import pyqtSignal, Qt

from core import b_encoder
from core import resource_loader
from core import item_display_resolver
from tabs.qt_catalog_picker import ContainedWheelListWidget, ContainedWheelScrollArea
from tabs.qt_item_browser import ItemBrowser, ROW_HEIGHT, list_widget_by_userrole, parse_stack_count, stack_into_sel_list
from tabs.qt_editor_shared import (
    Token,
    TokenOrderedState,
    combo_data_ids,
    emit_update_or_warn,
    find_mfg_combo_index,
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
def load_heavy_weapon_data(lang='zh-CN'):
    try:
        df_main = resource_loader.load_localized_csv_resource('heavy/heavy_main_perk.csv', lang)
        df_mfg = resource_loader.load_localized_csv_resource('heavy/heavy_manufacturer_perk.csv', lang)
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
    update_item_requested = pyqtSignal(dict)
    # Re-emit from ``self.browser.item_delete_requested`` — connected inside
    # _build_ui after browser creation so it survives language-switch rebuilds.
    item_delete_requested = pyqtSignal(list)

    _LOG_TAG = "heavy"

    # Manufacturer parent-IDs surfaced in the mfg picker, in display order.
    # Never mutated at runtime — promoted to a class constant so the mfg list
    # lives in exactly one place.
    _MFG_IDS: tuple[int, ...] = (282, 273, 275, 289)

    def __init__(self, main_app=None, parent=None):
        super().__init__(parent)
        self.main_app = main_app
        self.current_lang = 'zh-CN'
        self._character_level = "50"
        self.df_main, self.df_mfg, self.localization = load_heavy_weapon_data(self.current_lang)

        self._load_ui_localization()

        if self.df_main is None:
            layout = QVBoxLayout(self)
            layout.addWidget(QLabel(self.ui_loc.get('dialogs', {}).get('load_error', "错误: 重武器数据(heavy weapon data)无法加载。")))
            return

        self.barrel_widgets = []
        self.element_widgets = []
        self.firmware_widgets = []

        # State for backpack browser + reverse-parser flow
        self.selected_item_path = None
        self._is_loading = False
        # Set on every rebuild_output; init here so getattr defaults aren't
        # needed at the two read sites (_add_to_backpack / _update_heavy).
        self._encode_error = False
        # Session-random seed for fresh items. Backpack loads preserve the
        # source header via make_header_getter (seed_getter=None), so the
        # source seed rides through state.render() unmodified. See grenade
        # tab for the state-first rebuild pattern.
        self._current_seed = str(random.randint(100, 9999))
        # Token-preserving state; every rebuild routes through state.render()
        # — the token stream is authoritative. Value edits (rarity/level)
        # pick up widget state via bindings; structural edits (radio flip, sel_list
        # add/remove) surgically mutate state via ``state.insert()`` /
        # ``state.remove_with_whitespace()``. Unknown top-level simples stay
        # unbound (raw pass-through). Heavy has no aggregation buckets — every
        # widget contributes its own individual token.
        self._token_state = TokenOrderedState([])
        self._populating = False

        self._build_ui()
        self.populate_initial_data()
        self._connect_signals()
        self.refresh_backpack_items()

    def _load_ui_localization(self):
        self.ui_loc = load_tab_ui_loc("heavy_weapon_tab", self.current_lang)

    def update_language(self, lang):
        log_editor(self.main_app, self._LOG_TAG, f"Updating language for {self.__class__.__name__} to {lang}...")
        self.current_lang = lang
        self.df_main, self.df_mfg, self.localization = load_heavy_weapon_data(lang)

        if self.df_main is None:
            log_editor(self.main_app, self._LOG_TAG, f"load_heavy_weapon_data failed for {self.__class__.__name__}")
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
                    self._load_heavy_item(current)
        log_editor(self.main_app, self._LOG_TAG, f"Finished updating language for {self.__class__.__name__}.")

    def _(self, text):
        return self.localization.get(str(text), str(text))

    def _build_ui(self):
        tab_layout = QVBoxLayout(self)
        tab_layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        tab_layout.addWidget(splitter)

        # Left: shared backpack browser
        self.browser = ItemBrowser(
            main_app=self.main_app,
            item_filter=self._is_heavy_item,
            row_builder=self._heavy_browser_row,
            header_label=self.ui_loc.get('labels', {}).get('load_from_backpack', 'Load from Backpack'),
            search_placeholder=self.ui_loc.get('labels', {}).get('search_heavy_placeholder', 'Search heavy weapon...'),
            empty_placeholder=self.ui_loc.get('dialogs', {}).get('no_heavies_in_backpack', 'No heavy weapons in backpack'),
            no_save_placeholder=self.ui_loc.get('dialogs', {}).get('decrypt_save_to_show', 'Decrypt save first'),
            summary_formatter=self._summarize_heavy,
            summary_none_text=self.ui_loc.get('summary', {}).get('none_selected', 'No backpack heavy weapon selected'),
        )
        # Re-emit so main_window can wire once to a signal that survives
        # _build_ui rebuilds (browser gets recreated on language switch).
        self.browser.item_delete_requested.connect(self.item_delete_requested.emit)
        self.browser.item_selected.connect(self._load_heavy_item)
        splitter.addWidget(self.browser)

        # Right: existing scrollable editor content
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
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
        main_layout.addStretch()  # Ensure content is pushed to the top within the scroll area

        splitter.addWidget(scroll_area)
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
        self.update_heavy_btn = QPushButton(self.ui_loc.get('buttons', {}).get('update_heavy', 'Update'))
        self.update_heavy_btn.setEnabled(False)
        self.flag_combo = QComboBox()
        self._populate_flags()

        self.b85_label = QLabel(self.ui_loc['labels']['base85'])
        grid.addWidget(self.b85_label, 1, 0)
        grid.addWidget(self.b85_output_edit, 1, 1)
        grid.addWidget(self.copy_b85_btn, 1, 2)
        grid.addWidget(self.flag_combo, 1, 3)
        grid.addWidget(self.add_to_pack_btn, 1, 4)
        grid.addWidget(self.update_heavy_btn, 1, 5)
        self.update_heavy_btn.clicked.connect(self._update_heavy)

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

    def _create_radio_perk_groups(self, layout):
        self.barrel_group, self.barrel_frame = self._create_scrollable_radio_group(self.ui_loc['groups']['barrel'])
        self.element_group, self.element_frame = self._create_scrollable_radio_group(self.ui_loc['groups']['element'])
        self.firmware_group, self.firmware_frame = self._create_scrollable_radio_group(self.ui_loc['groups']['firmware'])
        
        layout.addWidget(self.barrel_group, 0, 0)
        layout.addWidget(self.element_group, 0, 1)
        layout.addWidget(self.firmware_group, 0, 2)
        layout.setRowStretch(0, 1)
        layout.setRowStretch(1, 1)
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
        scroll_area = ContainedWheelScrollArea()
        scroll_area.setMinimumHeight(200)
        scroll_area.setWidgetResizable(True)
        widget_in_scroll = QWidget()
        layout = QVBoxLayout(widget_in_scroll)
        scroll_area.setWidget(widget_in_scroll)
        main_layout = QVBoxLayout(group_box)
        main_layout.addWidget(scroll_area)
        return group_box, layout

    def _create_list_perk_group(self, title, key, use_multiplier=False):
        group_box = QGroupBox(title)
        layout = QGridLayout(group_box)

        avail_list = ContainedWheelListWidget()
        avail_list.setMinimumHeight(200)
        avail_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        sel_list = ContainedWheelListWidget()
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

        prefix = key
        setattr(self, f"{prefix}_avail_list", avail_list)
        setattr(self, f"{prefix}_sel_list", sel_list)
        setattr(self, f"{prefix}_clear_btn", clear_btn)

        if multiplier_box:
            setattr(self, f"{prefix}_multiplier", multiplier_box)

        # Connect signals
        move_btn.clicked.connect(lambda: self._move_selected_items(avail_list, sel_list, multiplier_box))
        remove_btn.clicked.connect(lambda: self._remove_selected_items(sel_list))
        clear_btn.clicked.connect(lambda: self._clear_list(sel_list))

        return group_box
        
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

        # Element / firmware radio toggles add or remove {1:X} / {244:X}
        # single tokens in the serial — structural, so route through
        # _on_structural_change so state mutates before render.
        self.element_widgets, self.element_none_rb = populate_radio_buttons(
            self.element_frame,
            self._radio_entries(self.df_main[self.df_main['Heavy_perk_main_ID'] == 1]),
            on_toggle=self._on_radio_toggled,
            none_label=self.ui_loc['misc']['none'],
        )
        self.firmware_widgets, self.firmware_none_rb = populate_radio_buttons(
            self.firmware_frame,
            self._radio_entries(self.df_main[self.df_main['Heavy_perk_main_ID'] == 244]),
            on_toggle=self._on_radio_toggled,
            none_label=self.ui_loc['misc']['none'],
        )
        self.on_mfg_change()

    def _radio_entries(self, df):
        """Prepare ``(text, part_id)`` entries for populate_radio_buttons.

        Element/firmware rows carry a Heavy_perk_main_ID column — those store
        their part_id as ``"parent:child"`` (see ``_prefixed_part_id``) so
        the same child value can coexist under different parents. Barrel
        rows have no Heavy_perk_main_ID and get the plain int part_id.
        """
        entries = []
        for _, row in df.iterrows():
            desc = row['Description'] if 'Description' in row and pd.notna(row['Description']) else ''
            display_text = f"{self._(row['Stat'])} - {desc}" if desc else self._(row['Stat'])
            # Cast on ingestion: pandas hands out numpy.int64.
            part_id = int(row['Part_ID'])
            if 'Heavy_perk_main_ID' in row and pd.notna(row['Heavy_perk_main_ID']):
                part_id = self._prefixed_part_id(int(row['Heavy_perk_main_ID']), part_id)
            entries.append((display_text, part_id))
        return entries

    def _populate_barrel_radiobuttons(self):
        mfg_id = selected_mfg_id_from_combo(self.mfg_combo)
        if mfg_id is None:
            return
        filtered_df = self.df_mfg[(self.df_mfg['Part_type'] == 'Barrel') & (self.df_mfg['Manufacturer ID'] == mfg_id)]
        # Barrel radio toggle adds or removes a standalone {X} token —
        # structural, so route through _on_structural_change.
        self.barrel_widgets, self.barrel_none_rb = populate_radio_buttons(
            self.barrel_frame,
            self._radio_entries(filtered_df),
            on_toggle=self._on_radio_toggled,
            none_label=self.ui_loc['misc']['none'],
        )
        
    def _connect_signals(self):
        self.mfg_combo.currentTextChanged.connect(self.on_mfg_change)
        self.level_edit.textChanged.connect(self.rebuild_output)
        self.rarity_combo.currentTextChanged.connect(self._on_rarity_changed)

        self.copy_raw_btn.clicked.connect(lambda: self._copy_to_clipboard(self.raw_output_edit))
        self.copy_b85_btn.clicked.connect(lambda: self._copy_to_clipboard(self.b85_output_edit))
        self.add_to_pack_btn.clicked.connect(self._add_to_backpack)

        # Accessory sel_list changes: surgical rebuild of that category's
        # standalone {X} simple tokens; unknown top-level simples untouched.
        self.barrel_acc_sel_list.model().rowsInserted.connect(self._on_barrel_acc_changed)
        self.barrel_acc_sel_list.model().rowsRemoved.connect(self._on_barrel_acc_changed)
        self.barrel_acc_sel_list.model().dataChanged.connect(self._on_barrel_acc_changed)
        self.body_acc_sel_list.model().rowsInserted.connect(self._on_body_acc_changed)
        self.body_acc_sel_list.model().rowsRemoved.connect(self._on_body_acc_changed)
        self.body_acc_sel_list.model().dataChanged.connect(self._on_body_acc_changed)
        
    def on_mfg_change(self, *args):
        mfg_id = selected_mfg_id_from_combo(self.mfg_combo)
        if mfg_id is None:
            return
        
        # Populate Rarity
        self.rarity_combo.blockSignals(True)
        self.rarity_combo.clear()
        rarities_df = self.df_mfg[(self.df_mfg['Manufacturer ID'] == mfg_id) & (self.df_mfg['Part_type'] == 'Rarity')]
        for _, row in rarities_df.iterrows():
            desc_val = row['Description']
            desc = f" - {desc_val}" if pd.notna(desc_val) else ""
            self.rarity_combo.addItem(f"{self._(row['Stat'])}{desc}", userData=int(row['Part_ID']))
        self.rarity_combo.blockSignals(False)

        self._populating = True
        try:
            self._populate_barrel_radiobuttons() # Refresh barrels on mfg change
            self.populate_accessory_lists()
        finally:
            self._populating = False
        # Item type effectively changed — fresh state (Option 1).
        if not self._is_loading:
            self._reset_state_to_fresh_item(mfg_id)

    def populate_accessory_lists(self):
        mfg_id = selected_mfg_id_from_combo(self.mfg_combo)
        if mfg_id is None:
            return

        # --- Barrel Accessories ---
        self.barrel_acc_avail_list.clear()

        barrel_acc_df = self.df_mfg[self.df_mfg['Part_type'] == 'Barrel Accessory'].copy()
        barrel_acc_df.dropna(subset=['String'], inplace=True)
        barrel_acc_df = barrel_acc_df.drop_duplicates(subset=['Part_ID', 'Manufacturer ID'])
        barrel_acc_df = barrel_acc_df[barrel_acc_df['Manufacturer ID'] == mfg_id] # Filter for current manufacturer
        barrel_acc_df = barrel_acc_df.sort_values(by=['String', 'Part_ID'])

        barrel_subtype_names = {}
        barrel_subtypes_df = self.df_mfg[
            (self.df_mfg['Part_type'] == 'Barrel') & 
            (~self.df_mfg['Stat'].str.contains(r'[（(]', na=False, regex=True))
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
            item.setData(Qt.ItemDataRole.UserRole, int(row['Part_ID']))
            self.barrel_acc_avail_list.addItem(item)

        # --- Body Accessories ---
        self.body_acc_avail_list.clear()
        body_df = self.df_mfg[self.df_mfg['Part_type'] == 'Body Accessory'].copy()
        body_df = body_df.drop_duplicates(subset=['Part_ID', 'Manufacturer ID'])
        body_df = body_df[body_df['Manufacturer ID'] == mfg_id] # Filter for current manufacturer
        body_df = body_df.sort_values(by=['Part_ID'])

        for _, row in body_df.iterrows():
            mfg_name = self._get_mfg_name(row['Manufacturer ID'])
            display_text = f"{mfg_name} - {row['Stat']} - ID:{row['Part_ID']}"
            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, int(row['Part_ID']))
            self.body_acc_avail_list.addItem(item)

    def rebuild_output(self, *args):
        """State-first render. Widget values flow through bindings (rarity)
        or raw pass-through. Structural mutations happen surgically in
        ``_on_*`` handlers.
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
            log_editor(self.main_app, self._LOG_TAG, f"heavy rebuild error: {e}")

    # ---- Structural handlers ------------------------------------------

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

    def _on_radio_toggled(self, *args):
        """Surgical rebuild of radio-contributed tokens for the sender's
        group. Barrel radios contribute standalone simple; element radios
        contribute {1:X} single; firmware radios contribute {244:X} single.
        """
        if self._is_loading or self._populating:
            return
        if not self._token_state.tokens:
            return
        rb = self.sender()
        if rb is None:
            return
        # Identify which group. Match against group's data-radio list.
        if rb in self.barrel_widgets or rb is getattr(self, 'barrel_none_rb', None):
            self._rebuild_barrel_token()
        elif rb in self.element_widgets or rb is getattr(self, 'element_none_rb', None):
            self._rebuild_single_group(parent_id=1, widgets=self.element_widgets)
        elif rb in self.firmware_widgets or rb is getattr(self, 'firmware_none_rb', None):
            self._rebuild_single_group(parent_id=244, widgets=self.firmware_widgets)
        self.rebuild_output()

    def _on_barrel_acc_changed(self, *args):
        if self._is_loading or self._populating:
            return
        if not self._token_state.tokens:
            return
        self._rebuild_acc_tokens(self.barrel_acc_sel_list, self.barrel_acc_avail_list)
        self.rebuild_output()

    def _on_body_acc_changed(self, *args):
        if self._is_loading or self._populating:
            return
        if not self._token_state.tokens:
            return
        self._rebuild_acc_tokens(self.body_acc_sel_list, self.body_acc_avail_list)
        self.rebuild_output()

    # ---- Category-specific surgical rebuilds --------------------------

    def _rebuild_barrel_token(self):
        """Remove any current barrel simple; insert new one if selected."""
        barrel_ids = {int(rb.property("part_id")) for rb in self.barrel_widgets
                      if rb.property("part_id") is not None}
        to_remove: list[int] = []
        for idx, tok in enumerate(self._token_state.tokens):
            if tok.kind == 'simple' and tok.parent is None and tok.value in barrel_ids:
                to_remove.append(idx)
        for idx in reversed(to_remove):
            self._token_state.remove_with_whitespace(idx)
        selected_barrel: int | None = None
        for rb in self.barrel_widgets:
            if rb.isChecked() and rb.property("part_id") is not None:
                selected_barrel = int(rb.property("part_id"))
                break
        if selected_barrel is not None:
            insert_at = self._insert_idx_before_acc_and_pipe()
            self._token_state.insert(insert_at, Token(raw=" ", kind="raw"))
            self._token_state.insert(insert_at + 1, Token(
                raw=f"{{{selected_barrel}}}", kind='simple', value=selected_barrel,
            ))

    def _rebuild_single_group(self, *, parent_id, widgets):
        """Remove any {parent_id:X} single; insert new one if a data radio is
        selected. Uses the group's "parent:child" prefixed part_id.
        """
        to_remove: list[int] = []
        for idx, tok in enumerate(self._token_state.tokens):
            if tok.parent == parent_id and tok.kind == 'single':
                to_remove.append(idx)
        for idx in reversed(to_remove):
            self._token_state.remove_with_whitespace(idx)
        selected_child: int | None = None
        for rb in widgets:
            if rb.isChecked() and rb.property("part_id"):
                pref = str(rb.property("part_id"))
                if ':' in pref:
                    try:
                        _, child_s = pref.split(':', 1)
                        selected_child = int(child_s)
                    except ValueError:
                        selected_child = None
                break
        if selected_child is not None:
            insert_at = self._insert_idx_before_acc_and_pipe()
            self._token_state.insert(insert_at, Token(raw=" ", kind="raw"))
            self._token_state.insert(insert_at + 1, Token(
                raw=f"{{{parent_id}:{selected_child}}}",
                kind='single', parent=parent_id, value=selected_child,
            ))

    def _rebuild_acc_tokens(self, sel_list, avail_list):
        """Remove all tokens whose value matches an entry in avail_list, then
        re-insert one per stack-count from sel_list. Because barrel_acc and
        body_acc share the standalone-simple shape, this must scope removal
        to only the IDs owned by the caller's avail_list (so we don't touch
        the OTHER acc category's tokens or unrelated unknowns).
        """
        avail_ids = set()
        for i in range(avail_list.count()):
            item = avail_list.item(i)
            data = item.data(Qt.ItemDataRole.UserRole)
            if data is not None:
                avail_ids.add(int(data))
        to_remove: list[int] = []
        for idx, tok in enumerate(self._token_state.tokens):
            if tok.kind == 'simple' and tok.parent is None and tok.value in avail_ids:
                to_remove.append(idx)
        for idx in reversed(to_remove):
            self._token_state.remove_with_whitespace(idx)
        insert_at = self._insert_idx_before_trailing_pipe()
        for i in range(sel_list.count()):
            item = sel_list.item(i)
            count, _ = parse_stack_count(item.text())
            pid_data = item.data(Qt.ItemDataRole.UserRole)
            if pid_data is None:
                continue
            pid = int(pid_data)
            for _ in range(count):
                self._token_state.insert(insert_at, Token(raw=" ", kind="raw"))
                self._token_state.insert(insert_at + 1, Token(
                    raw=f"{{{pid}}}", kind='simple', value=pid,
                ))
                insert_at += 2

    # ---- Helpers ------------------------------------------------------

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

    def _insert_idx_before_acc_and_pipe(self) -> int:
        """Insert index for barrel/element/firmware tokens: before acc
        entries and the trailing pipe. We identify acc tokens by their value
        appearing in either acc avail list, and pipe by '|' in raw."""
        acc_ids: set[int] = set()
        for lw in (self.barrel_acc_avail_list, self.body_acc_avail_list):
            for i in range(lw.count()):
                data = lw.item(i).data(Qt.ItemDataRole.UserRole)
                if data is not None:
                    acc_ids.add(int(data))
        for idx, tok in enumerate(self._token_state.tokens):
            if tok.kind == 'simple' and tok.parent is None and tok.value in acc_ids:
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
        """Fresh state: [header, ' |']. Body token (mfg-auto) + rarity
        inserted lazily via handlers. Option 1 for mfg change."""
        level = self.level_edit.text() or "50"
        header_raw = f"{mfg_id}, 0, 1, {level}| 2, {self._current_seed}||"
        tokens = [Token(raw=header_raw, kind='raw'), Token(raw=" |", kind='raw')]
        self._token_state = TokenOrderedState(tokens)
        self._token_state.bind(0, make_header_getter(
            header_raw,
            level_getter=lambda: self.level_edit.text(),
            seed_getter=None,
        ))
        # Insert rarity + auto-emitted Body via specific handlers.
        self._on_rarity_changed()
        body_row = self.df_mfg[(self.df_mfg['Manufacturer ID'] == mfg_id) & (self.df_mfg['Part_type'] == 'Body')]
        if not body_row.empty:
            pid = int(body_row.iloc[0]['Part_ID'])
            insert_at = self._insert_idx_before_acc_and_pipe()
            self._token_state.insert(insert_at, Token(raw=" ", kind="raw"))
            self._token_state.insert(insert_at + 1, Token(
                raw=f"{{{pid}}}", kind='simple', value=pid,
            ))
        # Emit acc lists (fresh = empty), barrel/element/firmware groups (also
        # empty until user selects). No-ops when nothing selected.
        self._rebuild_barrel_token()
        self._rebuild_single_group(parent_id=1, widgets=self.element_widgets)
        self._rebuild_single_group(parent_id=244, widgets=self.firmware_widgets)
        self._rebuild_acc_tokens(self.barrel_acc_sel_list, self.barrel_acc_avail_list)
        self._rebuild_acc_tokens(self.body_acc_sel_list, self.body_acc_avail_list)
        self.rebuild_output()

    def _bind_token_state_widgets(self):
        """Attach getters to loaded state: rarity only. All other tokens
        stay UNBOUND; structural handlers surgically insert/remove them.
        """
        if not self._token_state.tokens:
            return
        rarity_ids = combo_data_ids(self.rarity_combo)
        for idx, tok in enumerate(self._token_state.tokens):
            if tok.kind == 'simple' and tok.parent is None and tok.value in rarity_ids:
                self._token_state.bind(idx, self._rarity_getter())
                break

    def _move_selected_items(self, source_list, dest_list, multiplier_box=None):
        count_val = multiplier_box.value() if multiplier_box else 1
        for item in source_list.selectedItems():
            if item.flags() & Qt.ItemFlag.ItemIsEnabled:
                 base_text = item.text()
                 
                 existing_item = None
                 current_count = 1
                 for i in range(dest_list.count()):
                    sel_item = dest_list.item(i)
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
                    dest_list.addItem(new_item)
        # rowsInserted on the sel_list model fires _on_structural_change via
        # signal wiring; no explicit rebuild call needed here.

    def _remove_selected_items(self, list_widget):
        for item in list_widget.selectedItems():
            list_widget.takeItem(list_widget.row(item))
        # rowsRemoved fires _on_structural_change; no explicit call needed.

    def _clear_list(self, list_widget):
        list_widget.clear()
        # rowsRemoved fires _on_structural_change; no explicit call needed.

    def _copy_to_clipboard(self, line_edit):
        clipboard = QApplication.clipboard()
        clipboard.setText(line_edit.text())
        QMessageBox.information(self, self.ui_loc['dialogs']['success'], self.ui_loc['dialogs']['copied'])
        
    def _add_to_backpack(self):
        serial = self.b85_output_edit.text()
        if not serial or self._encode_error:
            QMessageBox.warning(self, self.ui_loc['dialogs']['no_valid_code'], self.ui_loc['dialogs']['gen_first'])
            return
        flag = self.flag_combo.currentText().split(" ")[0]
        self.add_to_backpack_requested.emit(serial, flag)

    def _populate_flags(self):
        populate_flag_combo(self.flag_combo, self.current_lang)

    # ---- Backpack browser integration ---------------------------------

    @staticmethod
    def _is_heavy_item(item):
        return item.get("type_en") == "Heavy Weapon" and "Backpack" in (item.get("container") or "")

    def _heavy_browser_row(self, item):
        """Vertical-card row for a heavy weapon in the browser.

        Unlike grenade/shield/repkit (which show "—" placeholders in the
        stat strip), heavy shares the weapon-stat pipeline via
        ``item_display_resolver.resolve_weapon_stats``, so rows show real
        damage/accuracy/fire-rate/reload/magazine numbers.
        """
        manufacturer = item.get("manufacturer") or self.ui_loc.get('parts', {}).get('unknown', 'Unknown')
        type_label = item.get("type") or self.ui_loc.get('parts', {}).get('unknown_item', 'Heavy')
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

        # Heavies share the weapon-stat pipeline — real numbers, no placeholders.
        decoded_str = item.get('decoded_full', '') or ''
        stats = item_display_resolver.resolve_weapon_stats(decoded_str) if decoded_str else {}
        stat_titles = self.ui_loc.get('stats', {})
        stats_layout = QGridLayout()
        stats_layout.setContentsMargins(0, 2, 0, 0)
        stats_layout.setHorizontalSpacing(4)
        stats_layout.setVerticalSpacing(1)
        for column, key in enumerate(("damage", "accuracy", "fire_rate", "reload_time", "magazine")):
            title_label = QLabel(stat_titles.get(key, key.replace('_', ' ').title()))
            title_label.setObjectName("ItemBrowserStatTitle")
            title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title_label.setWordWrap(True)
            value = item_display_resolver.format_weapon_stat(key, stats.get(key), self.current_lang) or "—"
            value_label = QLabel(value)
            value_label.setObjectName("ItemBrowserStatValue")
            value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            stats_layout.addWidget(title_label, 0, column)
            stats_layout.addWidget(value_label, 1, column)
            stats_layout.setColumnStretch(column, 1)
        row_layout.addLayout(stats_layout)
        return display_name, detail, row

    def _summarize_heavy(self, item):
        return summarize_item(
            item,
            template=self.ui_loc.get('summary', {}).get('selected', 'Selected · {name} · Lv.{level}'),
            none_text=self.ui_loc.get('summary', {}).get('none_selected', 'No backpack heavy weapon selected'),
            fallback_name=self.ui_loc.get('summary', {}).get('fallback_name', 'Heavy'),
        )

    def refresh_backpack_items(self):
        if hasattr(self, "browser"):
            self.browser.refresh()

    # ---- Reverse parser (backpack heavy -> editor widgets) ------------

    def _load_heavy_item(self, item):
        """Populate editor fields from a decoded heavy weapon in the backpack.

        Heavy-specific dispatch differs from grenade:
          - element/firmware radios store their part_id as the PREFIXED STRING
            ``"1:X"`` (element) or ``"244:X"`` (firmware); elemental tokens
            ``{1:X}`` / ``{244:X}`` in the serial must be looked up by that
            string (see ``_prefixed_part_id``)
          - the mfg's Body row Part_ID is auto-appended on rebuild — skip it
            on load (no widget owns it)
          - no legendary or universal lists — only barrel_acc/body_acc dual
            lists, both scoped to the current mfg
          - numeric lookup keys (barrel/body/acc) are cast to plain ``int`` on
            ingestion for hash parity against parser tokens

        Token stream is authoritative — ``rebuild_output`` routes through
        ``state.render()``. The source header (with seed) rides through
        unchanged via ``make_header_getter(seed_getter=None)``.
        """
        if not item:
            return
        decoded = item.get("decoded_full", "") or ""
        if "||" not in decoded:
            log_editor(self.main_app, self._LOG_TAG, f"heavy load: no components in {item.get('name', 'unknown')}")
            return

        self._is_loading = True
        try:
            self.selected_item_path = item.get("original_path")

            # Parse into token state; bind header so state.render() picks up
            # level edits. seed_getter=None preserves source seed unchanged.
            self._token_state = self.browser.token_state_for(item, skin=False)
            if self._token_state.tokens:
                header_raw = self._token_state.tokens[0].raw
                self._token_state.bind(0, make_header_getter(
                    header_raw,
                    level_getter=lambda: self.level_edit.text(),
                    seed_getter=None,
                ))

            header, component = decoded.split("||", 1)
            header_pipe_parts = header.strip().split("|")
            header_fields = header_pipe_parts[0].strip().split(",")
            try:
                mfg_id = int(header_fields[0])
                level = int(header_fields[3])
            except (ValueError, IndexError):
                log_editor(self.main_app, self._LOG_TAG, f"heavy load: bad header for {item.get('name', 'unknown')}")
                return

            # Snap mfg → run on_mfg_change (rebuilds barrel radios + acc lists).
            self.mfg_combo.blockSignals(True)
            mfg_idx = find_mfg_combo_index(self.mfg_combo, mfg_id)
            if mfg_idx >= 0:
                self.mfg_combo.setCurrentIndex(mfg_idx)
            self.mfg_combo.blockSignals(False)
            self.on_mfg_change()

            self.level_edit.blockSignals(True)
            self.level_edit.setText(str(level))
            self.level_edit.blockSignals(False)

            # Reset radios via each group's None radio (stored on
            # ``self.<group>_none_rb`` by the shared populate helper). Radios
            # share a parent widget so Qt's auto-exclusive semantics unset the
            # previous data selection automatically.
            self.barrel_none_rb.setChecked(True)
            self.element_none_rb.setChecked(True)
            self.firmware_none_rb.setChecked(True)
            self.barrel_acc_sel_list.clear()
            self.body_acc_sel_list.clear()

            # Build lookups. Barrel + acc lists store numeric Part_IDs from
            # pandas (numpy.int64). Cast to plain int for stable dict-lookup
            # against tokens the parser produces as Python ints — future
            # pandas versions may change hash semantics of numpy scalars.
            rarity_ids = combo_data_ids(self.rarity_combo)
            body_id = self._current_body_id(mfg_id)
            # Barrel widgets store plain ints as part_id (cast at ingestion in
            # _radio_entries); no extra cast needed here.
            barrel_by_id = {
                rb.property("part_id"): rb
                for rb in self.barrel_widgets
                if rb.property("part_id") is not None
            }
            # Element/firmware widgets store prefixed string ids like "1:5"
            element_by_prefixed = {
                rb.property("part_id"): rb for rb in self.element_widgets if rb.property("part_id")
            }
            firmware_by_prefixed = {
                rb.property("part_id"): rb for rb in self.firmware_widgets if rb.property("part_id")
            }
            barrel_acc_by_id = list_widget_by_userrole(self.barrel_acc_avail_list)
            body_acc_by_id = list_widget_by_userrole(self.body_acc_avail_list)

            for token in parse_component_string(component):
                self._apply_heavy_token(
                    token,
                    rarity_ids=rarity_ids,
                    body_id=body_id,
                    barrel_by_id=barrel_by_id,
                    element_by_prefixed=element_by_prefixed,
                    firmware_by_prefixed=firmware_by_prefixed,
                    barrel_acc_by_id=barrel_acc_by_id,
                    body_acc_by_id=body_acc_by_id,
                    item_name=item.get("name", "unknown"),
                )

            set_flag_from_item(self.flag_combo, item, main_app=self.main_app, tag=self._LOG_TAG)
            self.update_heavy_btn.setEnabled(True)
            # Bind downstream tokens (rarity, etc.) so subsequent value edits
            # are picked up on the next state.render() call.
            self._bind_token_state_widgets()
        finally:
            self._is_loading = False
            # State is source-parsed with bindings live — emit verbatim.
            self.rebuild_output()

    def _apply_heavy_token(self, token, *, rarity_ids, body_id, barrel_by_id,
                           element_by_prefixed, firmware_by_prefixed,
                           barrel_acc_by_id, body_acc_by_id, item_name):
        ttype = token['type']
        if ttype == 'simple':
            pid = token['id']
            if pid in rarity_ids:
                set_rarity_by_id(self.rarity_combo, pid, main_app=self.main_app, tag=self._LOG_TAG)
            elif body_id is not None and pid == body_id:
                return  # auto-emitted Body part; ignored on load
            elif pid in barrel_by_id:
                barrel_by_id[pid].setChecked(True)
            elif pid in barrel_acc_by_id:
                stack_into_sel_list(self.barrel_acc_sel_list, barrel_acc_by_id[pid], use_prefix=True)
            elif pid in body_acc_by_id:
                stack_into_sel_list(self.body_acc_sel_list, body_acc_by_id[pid], use_prefix=True)
            else:
                log_editor(self.main_app, self._LOG_TAG, f"heavy load: unknown simple id {pid} in {item_name}")
        elif ttype == 'elemental':
            # element/firmware radios are keyed on the prefixed string.
            key = self._prefixed_part_id(token['id'], token['sub_id'])
            if key in element_by_prefixed:
                element_by_prefixed[key].setChecked(True)
            elif key in firmware_by_prefixed:
                firmware_by_prefixed[key].setChecked(True)
            else:
                log_editor(self.main_app, self._LOG_TAG, f"heavy load: unknown elemental id {key} in {item_name}")
        elif ttype == 'group':
            # No known group tokens for heavies; log defensively if encountered.
            log_editor(self.main_app, self._LOG_TAG, f"heavy load: unexpected group token {token['id']}:{token['sub_ids']} in {item_name}")

    @staticmethod
    def _prefixed_part_id(parent, child):
        """Compose the ``"parent:child"`` string convention used by heavy's
        element and firmware radios.

        Stored as a string (not int) so the same child value can appear under
        different parent categories without collision — element 1:5 and
        firmware 244:5 are distinct radios keyed independently.
        """
        return f"{parent}:{child}"

    def _current_body_id(self, mfg_id):
        """Return this mfg's auto-emitted Body Part_ID as ``int``, or ``None``."""
        row = self.df_mfg[(self.df_mfg['Manufacturer ID'] == mfg_id) & (self.df_mfg['Part_type'] == 'Body')]
        if row.empty:
            return None
        return int(row.iloc[0]['Part_ID'])

    def _update_heavy(self):
        emit_update_or_warn(
            self,
            new_serial=self.b85_output_edit.text(),
            no_selection_title=self.ui_loc.get('dialogs', {}).get('no_selection', 'No Selection'),
            no_selection_msg=self.ui_loc.get('dialogs', {}).get('select_heavy_first', 'Select a heavy weapon first'),
            no_valid_code_title=self.ui_loc.get('dialogs', {}).get('no_valid_code', 'No Valid Code'),
            no_valid_code_msg=self.ui_loc.get('dialogs', {}).get('gen_first', 'Generate a valid heavy weapon first'),
            success_msg=self.ui_loc.get('dialogs', {}).get('update_success', 'Heavy weapon updated'),
        )

    def set_character_level(self, level: str):
        """Update the default level shown in level_edit."""
        self._character_level = level if level else "50"
        if hasattr(self, 'level_edit'):
            self.level_edit.setText(self._character_level)
