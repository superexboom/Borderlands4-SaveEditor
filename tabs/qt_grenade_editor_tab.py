import pandas as pd
import random
from functools import lru_cache

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QComboBox, QListWidget, QListWidgetItem,
    QScrollArea, QMessageBox, QSpinBox, QSplitter
)
from PyQt6.QtCore import pyqtSignal, Qt

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
    populate_checkboxes,
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
def load_grenade_data(lang='zh-CN'):
    try:
        df_main = resource_loader.load_localized_csv_resource('grenade/grenade_main_perk.csv', lang)
        df_mfg = resource_loader.load_localized_csv_resource('grenade/manufacturer_rarity_perk.csv', lang)
        
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
    update_item_requested = pyqtSignal(dict)
    # Re-emit from ``self.browser.item_delete_requested`` — connected inside
    # _build_ui after browser creation so it survives language-switch rebuilds.
    item_delete_requested = pyqtSignal(list)

    # Log tag for shared log_editor calls — the tab-specific string was passed
    # positionally at ~10 sites before promotion.
    _LOG_TAG = "grenade"

    # Parent-ID under which grenade secondary sub-parts live: element radios,
    # firmware radios, and universal perks all share {245:...} in the serial.
    _SECONDARY_PARENT = 245

    # Fixed by game data — never mutated at runtime, so a class constant
    # beats a per-instance list.
    _MFG_IDS: tuple[int, ...] = (263, 267, 270, 272, 278, 291, 298, 311)

    def __init__(self, main_app=None, parent=None):
        super().__init__(parent)
        self.main_app = main_app
        self.current_lang = 'zh-CN'
        self._character_level = "50"
        self.df_main, self.df_mfg, self.localization = load_grenade_data(self.current_lang)

        self._load_ui_localization()

        if self.df_main is None:
            layout = QVBoxLayout(self); layout.addWidget(QLabel(self.ui_loc.get('dialogs', {}).get('load_error', "错误: 手雷数据(grenade data)无法加载。"))); return

        self.mfg_perk_widgets = []
        self.element_widgets = []
        self.firmware_widgets = []

        # State for backpack browser + reverse-parser flow
        self.selected_item_path = None
        self._is_loading = False
        # Set on every rebuild_output; init here so getattr defaults aren't
        # needed at the two read sites (_add_to_backpack / _update_grenade).
        self._encode_error = False
        # Token-preserving state (fresh on every load). Populated by
        # ``_load_grenade_item``; empty for fresh items. Every rebuild routes
        # through ``state.render()`` — the token stream is authoritative.
        # All widget changes translate to surgical ``state.insert()`` /
        # ``state.remove()``
        # calls (see the ``_on_*`` structural handlers) or pick up via bindings
        # (rarity + secondary-aggregation). Unknown source tokens are preserved
        # verbatim across every edit — top-level unknowns stay raw in the
        # token stream, {245:[...]} unknowns live in ``_preserved_unknowns``
        # and get re-emitted by the aggregation getter.
        self._token_state = TokenOrderedState([])
        # Per-parent-id unknown children preserved across widget edits. Keys
        # are parent-IDs like _SECONDARY_PARENT (245); values are the source
        # children that didn't map to any widget slot. Aggregation getters
        # (see _secondary_aggregation_getter) append these to their emission
        # so a load-then-structural-edit-then-save preserves the unknowns.
        self._preserved_unknowns: dict[int, list[int]] = {}
        # Session-random seed for fresh items. Backpack loads preserve the
        # source header via make_header_getter(seed_getter=None), so the source
        # seed rides through state.render() unmodified — this only fires when
        # the user creates a fresh grenade via mfg-change / Add-to-Backpack.
        # Randomized to match weapon/heavy/enhancement so multiple fresh
        # grenades don't collide on a single hardcoded seed.
        self._current_seed = str(random.randint(100, 9999))
        # Guards signal-driven structural handlers from firing during widget
        # populate (e.g. on_mfg_change replaces the mfg-perk checkbox row —
        # populate_checkboxes fires .toggled once per created widget). Set
        # around any bulk widget-population routine.
        self._populating = False

        self._build_ui()
        self.populate_initial_data()
        self._connect_signals()
        self.on_mfg_change()
        self.refresh_backpack_items()

    def _load_ui_localization(self):
        self.ui_loc = load_tab_ui_loc("grenade_tab", self.current_lang)

    def update_language(self, lang):
        log_editor(self.main_app, self._LOG_TAG, f"Updating language for {self.__class__.__name__} to {lang}...")
        self.current_lang = lang
        self.df_main, self.df_mfg, self.localization = load_grenade_data(lang)

        if self.df_main is None:
            log_editor(self.main_app, self._LOG_TAG, f"load_grenade_data failed for {self.__class__.__name__}")
            return

        self._load_ui_localization()

        if not self.ui_loc:
            log_editor(self.main_app, self._LOG_TAG, f"UI localization missing for {self.__class__.__name__}")
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

        self.mfg_combo.blockSignals(True)
        self.populate_initial_data()
        self.mfg_combo.blockSignals(False)
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
                    self._load_grenade_item(current)
        log_editor(self.main_app, self._LOG_TAG, f"Finished updating language for {self.__class__.__name__}.")

    def _(self, text): return self.localization.get(str(text), str(text))

    def _build_ui(self):
        main_layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        main_layout.addWidget(splitter)

        # Left: shared backpack browser
        self.browser = ItemBrowser(
            main_app=self.main_app,
            item_filter=self._is_grenade_item,
            row_builder=self._grenade_browser_row,
            header_label=self.ui_loc.get('labels', {}).get('load_from_backpack', 'Load from Backpack'),
            search_placeholder=self.ui_loc.get('labels', {}).get('search_grenade_placeholder', 'Search grenade...'),
            empty_placeholder=self.ui_loc.get('dialogs', {}).get('no_grenades_in_backpack', 'No grenades in backpack'),
            no_save_placeholder=self.ui_loc.get('dialogs', {}).get('decrypt_save_to_show', 'Decrypt save first'),
            summary_formatter=self._summarize_grenade,
            summary_none_text=self.ui_loc.get('summary', {}).get('none_selected', 'No backpack grenade selected'),
        )
        # Re-emit so main_window can wire once to a signal that survives
        # _build_ui rebuilds (browser gets recreated on language switch).
        self.browser.item_delete_requested.connect(self.item_delete_requested.emit)
        self.browser.item_selected.connect(self._load_grenade_item)
        splitter.addWidget(self.browser)

        # Right: existing scrollable editor content
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        container = QWidget(); scroll.setWidget(container); layout = QVBoxLayout(container)
        self._create_output_group(layout); self._create_top_controls(layout)

        self.perks_group = QGroupBox(self.ui_loc['groups']['perks']); perks_layout = QGridLayout(self.perks_group)
        self.mfg_perk_group, self.mfg_perk_frame, self.mfg_perk_widgets = self._create_scrollable_checkbox_group(self.ui_loc['groups']['mfg_perks'])
        self.element_group, self.element_frame, self.element_widgets = self._create_scrollable_radio_group(self.ui_loc['groups']['element'])
        self.firmware_group, self.firmware_frame, self.firmware_widgets = self._create_scrollable_radio_group(self.ui_loc['groups']['firmware'])
        perks_layout.addWidget(self.mfg_perk_group, 0, 0); perks_layout.addWidget(self.element_group, 0, 1); perks_layout.addWidget(self.firmware_group, 0, 2)
        self.legendary_group = self._create_list_perk_group(self.ui_loc['groups']['legendary'], key='legendary', use_multiplier=False)
        self.universal_group = self._create_list_perk_group(self.ui_loc['groups']['universal'], key='universal', use_multiplier=True)
        perks_layout.addWidget(self.legendary_group, 1, 0, 1, 3); perks_layout.addWidget(self.universal_group, 2, 0, 1, 3)
        layout.addWidget(self.perks_group)

        splitter.addWidget(scroll)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([320, 1040])

    def _create_output_group(self, layout):
        self.output_group = QGroupBox(self.ui_loc['groups']['output']); grid = QGridLayout(self.output_group)
        self.raw_output_edit = QLineEdit(); self.raw_output_edit.setReadOnly(True)
        self.b85_output_edit = QLineEdit(); self.b85_output_edit.setReadOnly(True)
        self.copy_raw_btn = QPushButton(self.ui_loc['buttons']['copy'])
        self.copy_b85_btn = QPushButton(self.ui_loc['buttons']['copy'])
        self.add_to_pack_btn = QPushButton(self.ui_loc['buttons']['add_to_backpack'])
        self.update_grenade_btn = QPushButton(self.ui_loc.get('buttons', {}).get('update_grenade', 'Update'))
        self.update_grenade_btn.setEnabled(False)

        self.flag_combo = QComboBox()
        self._populate_flags()

        self.raw_label = QLabel(self.ui_loc['labels']['raw'])
        self.b85_label = QLabel(self.ui_loc['labels']['base85'])
        grid.addWidget(self.raw_label, 0, 0); grid.addWidget(self.raw_output_edit, 0, 1); grid.addWidget(self.copy_raw_btn, 0, 2)
        grid.addWidget(self.b85_label, 1, 0); grid.addWidget(self.b85_output_edit, 1, 1); grid.addWidget(self.copy_b85_btn, 1, 2)
        grid.addWidget(self.flag_combo, 1, 3); grid.addWidget(self.add_to_pack_btn, 1, 4); grid.addWidget(self.update_grenade_btn, 1, 5)
        self.copy_raw_btn.clicked.connect(lambda: self._copy_to_clipboard(self.raw_output_edit))
        self.copy_b85_btn.clicked.connect(lambda: self._copy_to_clipboard(self.b85_output_edit))
        self.update_grenade_btn.clicked.connect(self._update_grenade)
        layout.addWidget(self.output_group)

    def _create_top_controls(self, layout):
        self.base_attrs_group = QGroupBox(self.ui_loc['groups']['base_attrs']); controls_layout = QHBoxLayout(self.base_attrs_group)
        self.mfg_combo = QComboBox(); self.level_edit = QLineEdit(self._character_level); self.rarity_combo = QComboBox()
        self.level_edit.setFixedWidth(100)
        self.rarity_combo.setFixedWidth(300)
        
        self.mfg_label = QLabel(self.ui_loc['labels']['manufacturer'])
        self.level_label = QLabel(self.ui_loc['labels']['level'])
        self.rarity_label = QLabel(self.ui_loc['labels']['rarity'])
        
        controls_layout.addWidget(self.mfg_label); controls_layout.addWidget(self.mfg_combo)
        controls_layout.addWidget(self.level_label); controls_layout.addWidget(self.level_edit)
        controls_layout.addWidget(self.rarity_label); controls_layout.addWidget(self.rarity_combo)
        controls_layout.addStretch(); layout.addWidget(self.base_attrs_group)

    def _create_scrollable_radio_group(self, title): return self._create_scrollable_group(title)
    def _create_scrollable_checkbox_group(self, title): return self._create_scrollable_group(title)

    def _create_scrollable_group(self, title):
        group_box=QGroupBox(title); scroll_area=ContainedWheelScrollArea(); scroll_area.setWidgetResizable(True); container=QWidget()
        scroll_area.setMinimumHeight(200)
        layout=QVBoxLayout(container); scroll_area.setWidget(container); main_layout=QVBoxLayout(group_box); main_layout.addWidget(scroll_area)
        return group_box, layout, []

    def _create_list_perk_group(self, title, key, single_select=False, use_multiplier=False):
        group=QGroupBox(title); layout=QGridLayout(group)
        avail, sel = ContainedWheelListWidget(), ContainedWheelListWidget()
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

        setattr(self, f"{key}_avail_list", avail)
        setattr(self, f"{key}_sel_list", sel)
        setattr(self, f"{key}_clear_btn", clear_btn)
        if multiplier_box:
            setattr(self, f"{key}_multiplier", multiplier_box)
            
        move_btn.clicked.connect(lambda: self._move_selected_items(avail, sel, single_select, multiplier_box))
        remove_btn.clicked.connect(lambda: self._remove_selected_items(sel))
        clear_btn.clicked.connect(lambda: self._clear_list(sel))
        
        return group
        
    def _connect_signals(self):
        self.mfg_combo.currentTextChanged.connect(self.on_mfg_change)
        self.level_edit.textChanged.connect(self.rebuild_output)
        # Rarity is a value edit when a rarity token already exists; otherwise
        # structural (insert). Handler covers both cases via ``_on_rarity_changed``.
        self.rarity_combo.currentTextChanged.connect(self._on_rarity_changed)
        self.add_to_pack_btn.clicked.connect(self._add_to_backpack)
        # NOTE: mfg_perk / element / firmware widget signals are wired inside
        # populate_checkboxes / populate_radio_buttons; those helpers now dispatch
        # to structural handlers via on_toggle callbacks (see populate_initial_data
        # + on_mfg_change).
        # Legendary sel_list add/remove → structural rebuild of legendary tokens
        # only (surgical: remove all legendary-owned tokens, insert current).
        # Universal sel_list add/remove → aggregation ensure/rebind.
        self.legendary_sel_list.model().rowsInserted.connect(self._on_legendary_changed)
        self.legendary_sel_list.model().rowsRemoved.connect(self._on_legendary_changed)
        self.legendary_sel_list.model().dataChanged.connect(self._on_legendary_changed)
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
        mfg_map = {mid: self._get_mfg_name(mid) for mid in self._MFG_IDS}
        self.mfg_combo.addItems([f"{v} - {k}" for k, v in sorted(mfg_map.items(), key=lambda x: x[1])])

        # Element / firmware radios contribute to the {245:[...]} secondary
        # aggregation token — the aggregation getter reads the currently-selected
        # radio's part_id on each render, so a flip between data radios is a
        # value edit (no state mutation). Toggling between "None" and a data
        # radio may need to insert/remove the aggregation token — the
        # _on_secondary_widget_changed handler dispatches to _ensure_secondary_token.
        self.element_widgets, self.element_none_rb = populate_radio_buttons(
            self.element_frame,
            self._radio_entries(self.df_main[self.df_main['Part_type'] == 'Element']),
            on_toggle=self._on_secondary_widget_changed,
            none_label=self.ui_loc['misc']['none'],
        )
        self.firmware_widgets, self.firmware_none_rb = populate_radio_buttons(
            self.firmware_frame,
            self._radio_entries(self.df_main[self.df_main['Part_type'] == 'Firmware']),
            on_toggle=self._on_secondary_widget_changed,
            none_label=self.ui_loc['misc']['none'],
        )
        self._populate_listbox(self.universal_avail_list, self.df_main[self.df_main['Part_type'] == 'Perk'])

    def _radio_entries(self, df):
        """Prepare ``(text, part_id)`` entries for populate_radio_buttons.
        Same shape as the checkbox entries — kept split so the description
        merge lives in one place."""
        entries = []
        for _, r in df.iterrows():
            text = self._(r['Stat'])
            if 'Description' in r and pd.notna(r['Description']):
                text += f" - {r['Description']}"
            entries.append((text, r['Part_ID']))
        return entries

    def _populate_listbox(self, listbox, df):
        listbox.clear()
        for _, r in df.iterrows():
            text = self._(r['Stat'])
            if 'Description' in r and pd.notna(r['Description']): text += f" - {r['Description']}"
            item=QListWidgetItem(text); item.setData(Qt.ItemDataRole.UserRole, r['Part_ID']); listbox.addItem(item)

    def on_mfg_change(self, *args):
        mfg_id = selected_mfg_id_from_combo(self.mfg_combo)
        if mfg_id is None:
            return
        
        self.rarity_combo.blockSignals(True)
        self.rarity_combo.clear()
        for _, r in self.df_mfg[(self.df_mfg['Manufacturer ID'] == mfg_id) & (self.df_mfg['Part_type'] == 'Rarity')].iterrows():
            desc = r['Description']
            self.rarity_combo.addItem(f"{self._(r['Stat'])} - {desc if pd.notna(desc) else ''}", r['Part_ID'])
        self.rarity_combo.blockSignals(False)

        # Mfg-perk checkbox toggles ADD or REMOVE standalone {X} tokens in the
        # serial — routed through _on_mfg_perk_toggled so state mutates first.
        self._populating = True
        try:
            self.mfg_perk_widgets = populate_checkboxes(
                self.mfg_perk_frame,
                self._radio_entries(self.df_mfg[(self.df_mfg['Manufacturer ID'] == mfg_id) & (self.df_mfg['Part_type'] == 'Perk')]),
                on_toggle=self._on_mfg_perk_toggled,
            )
        finally:
            self._populating = False
        self.legendary_avail_list.clear()
        df_leg = self.df_mfg[self.df_mfg['Part_type'] == 'Legendary Perk']
        for _, r in df_leg.iterrows():
            desc = r['Description']
            mfg_name = self._get_mfg_name(r['Manufacturer ID'])
            display_text = f"{mfg_name} - {self._(r['Stat'])} - {desc if pd.notna(desc) else ''}"
            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, (r['Part_ID'], r['Manufacturer ID']))
            self.legendary_avail_list.addItem(item)
        # on_mfg_change reshapes the mfg-scoped widgets (rarity/mfg_perks/
        # legendary_avail); the item type effectively changed, so start a
        # fresh state (Option 1: unknowns from the previous item are discarded
        # — they wouldn't apply to a different mfg anyway).
        if not self._is_loading:
            self._reset_state_to_fresh_item(mfg_id)

    def rebuild_output(self, *args):
        """State-first render. All widget values flow through bindings on
        ``self._token_state`` (rarity + {245:[...]} aggregation) or through
        the token's raw form (unbound tokens — unknown parts, mfg-perk simple
        tokens, legendary tokens). Structural mutations happen surgically in
        ``_on_*`` handlers via ``state.insert()`` / ``state.remove()``, so
        this path is a pure ``state.render()`` emission — no widget-splice
        fallback ever runs.
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
            log_editor(self.main_app, self._LOG_TAG, f"grenade rebuild error: {e}")

    # ---- Structural handlers ------------------------------------------
    #
    # Each handler mutates ``self._token_state`` via ``state.insert()`` /
    # ``state.remove_with_whitespace()`` for exactly the affected tokens.
    # No handler rebuilds the whole state; unknown source tokens (top-level
    # simples we didn't recognize on load, or unknown children preserved in
    # ``self._preserved_unknowns``) always survive.

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
            insert_at = self._insert_idx_after_header()
            pid = int(data)
            self._token_state.insert(insert_at, Token(raw=" ", kind="raw"))
            self._token_state.insert(insert_at + 1, Token(
                raw=f"{{{pid}}}", kind='simple', value=pid,
            ))
            self._token_state.bind(insert_at + 1, self._rarity_getter())
        # Otherwise: existing rarity token binding fires on next render.
        self.rebuild_output()

    def _on_mfg_perk_toggled(self, checked, *args):
        """Structural: insert or remove a standalone ``{pid}`` simple token
        for the sender checkbox. Unknown top-level simples are left alone —
        they neither match a mfg_perk pid nor a rarity id, so this handler
        never touches them.
        """
        if self._is_loading or self._populating:
            return
        if not self._token_state.tokens:
            return
        cb = self.sender()
        pid_prop = cb.property("part_id") if cb is not None else None
        if pid_prop is None:
            return
        pid = int(pid_prop)
        # Find an existing standalone token with this value (not rarity — rarity
        # is bound, so its raw is stale after a rarity change; but rarity's
        # currentData never collides with a mfg_perk pid in grenade data).
        idx = self._find_standalone_simple_idx(pid)
        if checked and idx == -1:
            insert_at = self._insert_idx_before_secondary()
            self._token_state.insert(insert_at, Token(raw=" ", kind="raw"))
            self._token_state.insert(insert_at + 1, Token(
                raw=f"{{{pid}}}", kind='simple', value=pid,
            ))
        elif not checked and idx != -1:
            self._token_state.remove_with_whitespace(idx)
        self.rebuild_output()

    def _on_legendary_changed(self, *args):
        """Structural: legendary sel_list add/remove/count-change. Legendary
        tokens are either same-mfg standalone ``{X}`` simples or cross-mfg
        ``{P:X}`` / ``{P:[a b c]}`` group tokens; both shapes are removed and
        re-inserted from current sel_list state. Rarity + mfg_perk simples +
        universal aggregation + unknown tokens are untouched — this handler
        only owns the legendary category.
        """
        if self._is_loading or self._populating:
            return
        if not self._token_state.tokens:
            return
        mfg_id = selected_mfg_id_from_combo(self.mfg_combo)
        if mfg_id is None:
            return
        # Remove any legendary tokens currently in state (identified via the
        # legendary_avail_list keys, so unknown same-mfg simples aren't
        # mistakenly removed).
        legendary_pairs = set()
        for i in range(self.legendary_avail_list.count()):
            av_item = self.legendary_avail_list.item(i)
            data = av_item.data(Qt.ItemDataRole.UserRole)
            if isinstance(data, tuple) and len(data) == 2:
                legendary_pairs.add((int(data[0]), int(data[1])))
        # First pass: mark indices to remove (walk backwards on removal).
        to_remove: list[int] = []
        for idx, tok in enumerate(self._token_state.tokens):
            if tok.kind == 'simple' and tok.parent is None and (tok.value, mfg_id) in legendary_pairs:
                to_remove.append(idx)
            elif tok.kind == 'single' and tok.parent is not None and tok.parent != self._SECONDARY_PARENT:
                if (tok.value, tok.parent) in legendary_pairs:
                    to_remove.append(idx)
            elif tok.kind == 'list' and tok.parent is not None and tok.parent != self._SECONDARY_PARENT:
                if any((c, tok.parent) in legendary_pairs for c in tok.children):
                    to_remove.append(idx)
        for idx in reversed(to_remove):
            self._token_state.remove_with_whitespace(idx)

        # Re-insert from current sel_list state: same-mfg entries emit as
        # simple {N} tokens; cross-mfg entries group under {parent:X} for
        # a single child or {parent:[a b c]} for multiple.
        insert_at = self._insert_idx_before_secondary()
        cross_mfg: dict[int, list[int]] = {}
        for i in range(self.legendary_sel_list.count()):
            it = self.legendary_sel_list.item(i)
            count, _ = parse_stack_count(it.text())
            data = it.data(Qt.ItemDataRole.UserRole)
            if not (isinstance(data, tuple) and len(data) == 2):
                continue
            part_id, item_mfg_id = int(data[0]), int(data[1])
            for _ in range(count):
                if item_mfg_id == mfg_id:
                    self._token_state.insert(insert_at, Token(raw=" ", kind="raw"))
                    self._token_state.insert(insert_at + 1, Token(
                        raw=f"{{{part_id}}}", kind='simple', value=part_id,
                    ))
                    insert_at += 2
                else:
                    cross_mfg.setdefault(item_mfg_id, []).append(part_id)
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
        """Structural: element/firmware radio flip OR universal sel_list
        change. Aggregation getter emits current widget state + preserved
        unknowns; this handler only needs to ensure the {245:...} token
        exists iff there's anything to emit.
        """
        if self._is_loading or self._populating:
            return
        if not self._token_state.tokens:
            return
        self._ensure_secondary_token()
        self.rebuild_output()

    # ---- Bindings + state-reset helpers -------------------------------

    def _rarity_getter(self):
        def getter():
            data = self.rarity_combo.currentData()
            return f"{{{int(data)}}}" if data is not None else None
        return getter

    def _current_secondary_children(self) -> list[int]:
        """Ordered children for the {245:[...]} token: currently-selected
        element + firmware radios (each contributes 0 or 1 entry), then
        universal picker entries (with stack counts), then preserved unknowns.
        """
        parts: list[int] = []
        for rb in self.element_widgets:
            if rb.isChecked() and rb.property("part_id"):
                parts.append(int(rb.property("part_id")))
                break
        for rb in self.firmware_widgets:
            if rb.isChecked() and rb.property("part_id"):
                parts.append(int(rb.property("part_id")))
                break
        for i in range(self.universal_sel_list.count()):
            item = self.universal_sel_list.item(i)
            count, _ = parse_stack_count(item.text())
            pid_data = item.data(Qt.ItemDataRole.UserRole)
            if pid_data is None:
                continue
            pid = int(pid_data)
            for _ in range(count):
                parts.append(pid)
        parts.extend(self._preserved_unknowns.get(self._SECONDARY_PARENT, []))
        return parts

    def _secondary_aggregation_getter(self):
        """Getter that emits the {245:[...]} token from current widget state
        + preserved source unknowns. Returns ``None`` when the aggregation
        is empty — caller should have removed the token structurally, but
        None-fallback keeps render defensively safe."""
        parent = self._SECONDARY_PARENT
        def getter():
            parts = self._current_secondary_children()
            if not parts:
                return None
            if len(parts) == 1:
                return f"{{{parent}:{parts[0]}}}"
            body = " ".join(str(p) for p in parts)
            return f"{{{parent}:[{body}]}}"
        return getter

    def _ensure_secondary_token(self) -> None:
        """Insert/remove the {245:...} aggregation token per emptiness state."""
        parts = self._current_secondary_children()
        idx = self._find_secondary_token_idx()
        if not parts and idx != -1:
            self._token_state.remove_with_whitespace(idx)
        elif parts and idx == -1:
            insert_at = self._insert_idx_before_trailing_pipe()
            self._token_state.insert(insert_at, Token(raw=" ", kind="raw"))
            # Real payload — the binding will replace .raw during render.
            self._token_state.insert(insert_at + 1, Token(
                raw="", kind='list', parent=self._SECONDARY_PARENT, children=[],
            ))
            self._token_state.bind(insert_at + 1, self._secondary_aggregation_getter())

    # ---- Index-finding helpers ----------------------------------------

    def _find_rarity_token_idx(self) -> int:
        """First bound-rarity token (simple with a getter). Falls back to any
        simple whose value is in rarity_combo's known ids."""
        rarity_ids = combo_data_ids(self.rarity_combo)
        for idx, tok in enumerate(self._token_state.tokens):
            if tok.kind == 'simple' and tok.parent is None and tok.value in rarity_ids:
                return idx
        return -1

    def _find_standalone_simple_idx(self, pid: int) -> int:
        rarity_ids = combo_data_ids(self.rarity_combo)
        for idx, tok in enumerate(self._token_state.tokens):
            if tok.kind == 'simple' and tok.parent is None and tok.value == pid:
                # Skip the rarity slot even if pid==rarity_id (shouldn't happen
                # for mfg_perks, but defensive).
                if tok.value in rarity_ids and self._token_state.has_binding(idx):
                    continue
                return idx
        return -1

    def _find_secondary_token_idx(self) -> int:
        for idx, tok in enumerate(self._token_state.tokens):
            if tok.parent == self._SECONDARY_PARENT and tok.kind in ('single', 'list'):
                return idx
        return -1

    def _insert_idx_after_header(self) -> int:
        # Header is token 0; insert-idx immediately after is 1 (list.insert
        # semantics: inserting at 1 places the new token after tokens[0]).
        return 1

    def _insert_idx_before_secondary(self) -> int:
        """Insert idx for a new standalone simple: just before the {245:...}
        token if present, else just before the trailing '|' raw."""
        for idx, tok in enumerate(self._token_state.tokens):
            if tok.parent == self._SECONDARY_PARENT and tok.kind in ('single', 'list'):
                # Prefer the space-raw before the token, not the token itself.
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
        """Discard current state and build a minimal fresh-item state:
        [header, ' ', {rarity}, ' |']. Used on mfg change (Option 1: fresh
        item — no source unknowns carry over).

        Uses ``self._current_seed`` (session-random, set in ``__init__``) so
        fresh items don't share a single hardcoded seed the way the pre-
        migration widget-splice rebuild did. Backpack loads preserve their
        own source seed via make_header_getter(seed_getter=None); only the
        fresh-item path reaches this method.
        """
        self._preserved_unknowns = {}
        level = self.level_edit.text() or self._character_level
        header_raw = f"{mfg_id}, 0, 1, {level}| 2, {self._current_seed}||"
        tokens = [Token(raw=header_raw, kind='raw')]
        self._token_state = TokenOrderedState(tokens)
        self._token_state.bind(0, make_header_getter(
            header_raw,
            level_getter=lambda: self.level_edit.text(),
            seed_getter=None,
        ))
        # Trailing " |" (game shape); rarity + downstream inserted lazily.
        self._token_state.insert(len(self._token_state.tokens),
                                 Token(raw=" |", kind='raw'))
        # Insert initial rarity token if the combo has a selection.
        data = self.rarity_combo.currentData()
        if data is not None:
            insert_at = self._insert_idx_after_header()
            pid = int(data)
            self._token_state.insert(insert_at, Token(raw=" ", kind="raw"))
            self._token_state.insert(insert_at + 1, Token(
                raw=f"{{{pid}}}", kind='simple', value=pid,
            ))
            self._token_state.bind(insert_at + 1, self._rarity_getter())
        # Ensure secondary token if radios happen to be selected already (e.g.
        # a defaults-loaded radio state).
        self._ensure_secondary_token()
        self.rebuild_output()

    def _bind_token_state_widgets(self):
        """Attach getters to loaded state: rarity ONLY. All ``{245:...}``
        bucket tokens stay UNBOUND so their source raw form is emitted
        verbatim on value edits — this preserves source order, split-list
        shape, and unknown children across rarity/level changes.
        Structural handlers (``_on_mfg_perk_toggled``,
        ``_on_legendary_changed``, ``_on_secondary_widget_changed`` via
        ``_ensure_secondary_token``) surgically mutate bucket tokens and
        bind the aggregation getter onto freshly-inserted tokens; unknowns
        persist across those rebuilds via ``self._preserved_unknowns``.
        """
        if not self._token_state.tokens:
            return
        # Rarity: first simple token whose value matches a rarity_combo entry.
        rarity_ids = combo_data_ids(self.rarity_combo)
        for idx, tok in enumerate(self._token_state.tokens):
            if tok.kind == 'simple' and tok.parent is None and tok.value in rarity_ids:
                self._token_state.bind(idx, self._rarity_getter())
                break

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
                    current_count, current_name = parse_stack_count(sel_item.text())
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

    def _remove_selected_items(self, list_widget):
        for item in list_widget.selectedItems(): list_widget.takeItem(list_widget.row(item))
        # rowsRemoved on the sel_list model fires _on_legendary_changed /
        # _on_secondary_widget_changed via the signal wiring in _connect_signals.

    def _clear_list(self, list_widget):
        list_widget.clear()
        # rowsRemoved fires the appropriate structural handler.

    def _populate_flags(self):
        populate_flag_combo(self.flag_combo, self.current_lang)

    def _copy_to_clipboard(self, line_edit): QApplication.clipboard().setText(line_edit.text()); QMessageBox.information(self, self.ui_loc['dialogs']['success'], self.ui_loc['dialogs']['copied'])
        
    def _add_to_backpack(self):
        serial = self.b85_output_edit.text()
        if not serial or self._encode_error: QMessageBox.warning(self, self.ui_loc['dialogs']['no_valid_code'], self.ui_loc['dialogs']['gen_first']); return
        self.add_to_backpack_requested.emit(serial, self.flag_combo.currentText().split(" ")[0])

    # ---- Backpack browser integration ---------------------------------

    @staticmethod
    def _is_grenade_item(item):
        return item.get("type_en") == "Grenade" and "Backpack" in (item.get("container") or "")

    def _grenade_browser_row(self, item):
        """Build the vertical-card row widget for a grenade in the browser.

        Returns (display_name, detail_text, row_widget) — the browser puts
        the widget in the QListWidgetItem and uses the strings for tooltips
        and search-blob. No grenade_stats resolver exists yet, so the
        five-column strip renders placeholders; matches the weapon-editor
        visual so a future resolver drops in cleanly.
        """
        manufacturer = item.get("manufacturer") or self.ui_loc.get('parts', {}).get('unknown', 'Unknown')
        type_label = item.get("type") or self.ui_loc.get('parts', {}).get('unknown_item', 'Grenade')
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

        # Compact 5-column stat strip — placeholders until a grenade_stats
        # resolver lands. Kept for visual parity with the weapon browser.
        stat_titles = self.ui_loc.get('stats', {})
        stats_layout = QGridLayout()
        stats_layout.setContentsMargins(0, 2, 0, 0)
        stats_layout.setHorizontalSpacing(4)
        stats_layout.setVerticalSpacing(1)
        for column, key in enumerate(("damage", "cooldown", "radius", "count", "element")):
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

    def _summarize_grenade(self, item):
        return summarize_item(
            item,
            template=self.ui_loc.get('summary', {}).get('selected', 'Selected · {name} · Lv.{level}'),
            none_text=self.ui_loc.get('summary', {}).get('none_selected', 'No backpack grenade selected'),
            fallback_name=self.ui_loc.get('summary', {}).get('fallback_name', 'Grenade'),
        )

    def refresh_backpack_items(self):
        if hasattr(self, "browser"):
            self.browser.refresh()

    # ---- Reverse parser (backpack grenade -> editor widgets) ----------

    def _load_grenade_item(self, item):
        """Populate editor fields from a decoded grenade in the backpack.

        Uses the shared token grammar (see ``_parse_component_string``). The
        token stream is authoritative — ``rebuild_output`` always routes
        through ``state.render()``. Value edits (rarity, level, element/
        firmware/universal picks) flow through bindings; structural edits
        (checkbox toggle, radio toggle, picker add/remove) mutate state
        surgically via ``state.insert()`` / ``state.remove_with_whitespace()``.
        Unknown source tokens are preserved verbatim across BOTH value and
        structural edits — top-level unknowns stay as raw tokens; unknown
        children of {245:[...]} live in ``self._preserved_unknowns`` and get
        re-emitted by the secondary aggregation getter on every render.
        """
        if not item:
            return

        decoded = item.get("decoded_full", "") or ""
        if "||" not in decoded:
            log_editor(self.main_app, self._LOG_TAG, f"grenade load: no components in {item.get('name', 'unknown')}")
            return

        self._is_loading = True
        try:
            self.selected_item_path = item.get("original_path")

            # Parse source into token state. Bind the header so ``state.render()``
            # picks up level edits; seed_getter=None preserves source seed on
            # the load-then-save path.
            self._token_state = self.browser.token_state_for(item, skin=False)
            if self._token_state.tokens:
                header_raw = self._token_state.tokens[0].raw
                self._token_state.bind(0, make_header_getter(
                    header_raw,
                    level_getter=lambda: self.level_edit.text(),
                    seed_getter=None,
                ))

            header, component = decoded.split("||", 1)
            header_fields = header.strip().split("|")[0].strip().split(",")
            try:
                mfg_id = int(header_fields[0])
                level = int(header_fields[3])
            except (ValueError, IndexError):
                log_editor(self.main_app, self._LOG_TAG, f"grenade load: bad header for {item.get('name', 'unknown')}")
                return

            # Snap mfg to the matching combo entry, then run on_mfg_change to
            # repopulate rarity/mfg-perks/legendary-avail for that mfg. The
            # _is_loading guard suppresses the trailing rebuild inside it.
            self.mfg_combo.blockSignals(True)
            mfg_idx = find_mfg_combo_index(self.mfg_combo, mfg_id)
            if mfg_idx >= 0:
                self.mfg_combo.setCurrentIndex(mfg_idx)
            self.mfg_combo.blockSignals(False)
            self.on_mfg_change()

            self.level_edit.blockSignals(True)
            self.level_edit.setText(str(level))
            self.level_edit.blockSignals(False)

            # Reset toggle-state widgets before parsing components. widget_list
            # holds only data-driven radios post shared-populate; the None
            # radio is on ``self.{group}_none_rb`` — check it explicitly to
            # restore the "none" state (radios share a parent so exclusive
            # semantics unset the previously-selected data radio).
            for cb in self.mfg_perk_widgets:
                cb.setChecked(False)
            self.element_none_rb.setChecked(True)
            self.firmware_none_rb.setChecked(True)
            self.legendary_sel_list.clear()
            self.universal_sel_list.clear()

            # Build lookup tables from the widgets on-screen (post on_mfg_change).
            rarity_ids = combo_data_ids(self.rarity_combo)
            mfg_perk_by_id = {
                cb.property("part_id"): cb for cb in self.mfg_perk_widgets if cb.property("part_id")
            }
            element_by_id = {
                rb.property("part_id"): rb for rb in self.element_widgets if rb.property("part_id")
            }
            firmware_by_id = {
                rb.property("part_id"): rb for rb in self.firmware_widgets if rb.property("part_id")
            }
            legendary_by_id = legendary_lookup(self.legendary_avail_list)
            universal_by_id = list_widget_by_userrole(self.universal_avail_list)

            self._preserved_unknowns = {}
            for token in parse_component_string(component):
                self._apply_token(
                    token, mfg_id,
                    rarity_ids=rarity_ids,
                    mfg_perk_by_id=mfg_perk_by_id,
                    element_by_id=element_by_id,
                    firmware_by_id=firmware_by_id,
                    universal_by_id=universal_by_id,
                    legendary_by_id=legendary_by_id,
                    item_name=item.get("name", "unknown"),
                )

            set_flag_from_item(self.flag_combo, item, main_app=self.main_app, tag=self._LOG_TAG)
            self.update_grenade_btn.setEnabled(True)
            # Bind downstream tokens (rarity + first {245:...}) so subsequent
            # value edits are picked up on the next state.render() call. Runs
            # BEFORE the _is_loading guard drops so the render fires exactly
            # once from the finally clause.
            self._bind_token_state_widgets()
        finally:
            self._is_loading = False
            # State is source-parsed with bindings live — emit verbatim.
            self.rebuild_output()

    def _apply_token(self, token, mfg_id, *, rarity_ids, mfg_perk_by_id,
                     element_by_id, firmware_by_id, universal_by_id,
                     legendary_by_id, item_name):
        ttype = token['type']
        if ttype == 'simple':
            pid = token['id']
            if pid in rarity_ids:
                set_rarity_by_id(self.rarity_combo, pid, main_app=self.main_app, tag=self._LOG_TAG)
            elif pid in mfg_perk_by_id:
                # setChecked fires stateChanged → _on_mfg_perk_toggled, which
                # would insert a duplicate token. Suppress via _is_loading
                # (the outer guard already covers this since we're inside
                # _load_grenade_item's _is_loading=True block).
                mfg_perk_by_id[pid].setChecked(True)
            elif (pid, mfg_id) in legendary_by_id:
                stack_into_sel_list(self.legendary_sel_list, legendary_by_id[(pid, mfg_id)])
            else:
                log_editor(self.main_app, self._LOG_TAG, f"grenade load: unknown simple id {pid} in {item_name}")
            return

        # elemental and group share dispatch — either under the secondary parent
        # or as cross-mfg legendary. iter_children normalizes the difference.
        parent = token['id']
        for child in iter_children(token):
            if parent == self._SECONDARY_PARENT:
                self._dispatch_secondary_child(child, parent, element_by_id, firmware_by_id, universal_by_id, item_name)
            elif (child, parent) in legendary_by_id:
                stack_into_sel_list(self.legendary_sel_list, legendary_by_id[(child, parent)])
            else:
                log_editor(self.main_app, self._LOG_TAG, f"grenade load: unknown cross-mfg leg {parent}:{child} in {item_name}")

    def _dispatch_secondary_child(self, pid, parent, element_by_id, firmware_by_id, universal_by_id, item_name):
        """Route a Part_ID under ``self._SECONDARY_PARENT`` to the right
        widget: element radio, firmware radio, or (fallback) universal perk.
        Unknown ids are recorded in ``self._preserved_unknowns`` so the
        aggregation getter re-emits them on every render — that is what keeps
        unknown children of {245:[...]} alive across BOTH value edits and
        structural edits.
        """
        if pid in element_by_id:
            element_by_id[pid].setChecked(True)
        elif pid in firmware_by_id:
            firmware_by_id[pid].setChecked(True)
        elif pid in universal_by_id:
            stack_into_sel_list(self.universal_sel_list, universal_by_id[pid], use_prefix=True)
        else:
            self._preserved_unknowns.setdefault(parent, []).append(int(pid))
            log_editor(self.main_app, self._LOG_TAG, f"grenade load: unknown {parent}-child id {pid} preserved in {item_name}")

    def _update_grenade(self):
        emit_update_or_warn(
            self,
            new_serial=self.b85_output_edit.text(),
            no_selection_title=self.ui_loc.get('dialogs', {}).get('no_selection', 'No Selection'),
            no_selection_msg=self.ui_loc.get('dialogs', {}).get('select_grenade_first', 'Select a grenade first'),
            no_valid_code_title=self.ui_loc.get('dialogs', {}).get('no_valid_code', 'No Valid Code'),
            no_valid_code_msg=self.ui_loc.get('dialogs', {}).get('gen_first', 'Generate a valid grenade first'),
            success_msg=self.ui_loc.get('dialogs', {}).get('update_success', 'Grenade updated'),
        )

    def set_character_level(self, level: str):
        """Update the default level shown in level_edit.
        设置角色等级，更新默认等级显示。"""
        self._character_level = level if level else "50"
        if hasattr(self, 'level_edit'):
            self.level_edit.setText(self._character_level)
