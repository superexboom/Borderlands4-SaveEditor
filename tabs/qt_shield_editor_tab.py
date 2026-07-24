import pandas as pd
import random
from dataclasses import dataclass
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
    populate_flag_combo,
    populate_radio_buttons,
    selected_mfg_id_from_combo,
    set_flag_from_item,
    set_rarity_by_id,
    summarize_item,
)
from core import lookup
from core import bl4_functions as bl4f

@dataclass
class ShieldLoadContext:
    """Bundle of load-time state passed to _apply_shield_token and its route helpers.

    Shield's token dispatch previously took 9 kwargs; grouping them into a
    dataclass lets the call site stay short and gives one obvious place to
    add a new lookup without touching every call site.
    """
    # Identity — who is loading and what is its label.
    mfg_id: int
    mfg_type: str            # "Energy" | "Armor"
    item_name: str
    # Load-time flags — silently-skipped auto-injected tokens.
    model_id: int | None     # auto-injected {Model} token; skip on load
    # Sets / dispatch tables keyed by part_id.
    rarity_ids: set
    element_by_id: dict
    firmware_by_id: dict
    legendary_by_id: dict
    universal_by_id: dict
    energy_by_id: dict
    armor_by_id: dict


@lru_cache(maxsize=None)
def load_shield_data(lang='zh-CN'):
    try:
        df_main = resource_loader.load_localized_csv_resource('shield/shield_main_perk.csv', lang)
        df_mfg = resource_loader.load_localized_csv_resource('shield/manufacturer_perk.csv', lang)
        
        localization = {}
        if lang == 'zh-CN':
            localization = resource_loader.load_json_resource('shield/Shield_localization_zh-CN.json') or {}
            
        return df_main, df_mfg, localization
    except Exception as e:
        print(f"Error loading shield data: {e}")
        return None, None, None

class QtShieldEditorTab(QWidget):
    add_to_backpack_requested = pyqtSignal(str, str)
    update_item_requested = pyqtSignal(dict)

    _LOG_TAG = "shield"

    # Rarity combo has to be a fixed width so the localized text doesn't push
    # the neighbouring level box around on language change.
    _RARITY_COMBO_WIDTH: int = 300

    # Parent-IDs used in the serial. Shared (246) covers element/firmware
    # radios and universal perks; the other two are exclusive per mfg_type.
    _PARENT_SHARED = 246
    _PARENT_ENERGY = 248
    _PARENT_ARMOR = 237

    # Manufacturer → shield type (Energy | Armor). Fixed by game data — never
    # mutated at runtime, so a class constant beats a per-instance attribute.
    _MFG_TYPES = {279: "Energy", 283: "Armor", 287: "Armor", 293: "Energy",
                  300: "Energy", 306: "Armor", 312: "Energy", 321: "Armor"}

    # Manufacturer parent-IDs surfaced in the mfg picker. Derived from
    # _MFG_TYPES.keys() so the mfg list and type map stay in lockstep — no
    # parallel source of truth to drift.
    _MFG_IDS: tuple[int, ...] = tuple(_MFG_TYPES.keys())

    def __init__(self, main_app=None, parent=None):
        super().__init__(parent)
        self.main_app = main_app
        self.current_lang = 'zh-CN'
        self._character_level = "50"
        self.df_main, self.df_mfg, self.localization = load_shield_data(self.current_lang)

        self._load_ui_localization()

        if self.df_main is None:
            layout = QVBoxLayout(self); layout.addWidget(QLabel(self.ui_loc.get('dialogs', {}).get('load_error', "错误: 护盾数据(shield data)无法加载。"))); return

        # Localized labels for the two shield types come from ui_loc; the
        # Manufacturer→type map itself lives on the class as ``_MFG_TYPES``.
        self.mfg_model_map = {row['Manufacturer ID']: row['Part_ID'] for _, row in self.df_mfg[self.df_mfg['Part_type'] == 'Model'].iterrows()}

        # State for backpack browser + reverse-parser flow
        self.selected_item_path = None
        self._is_loading = False
        # Set on every rebuild_output; init here so getattr defaults aren't
        # needed at the two read sites (_add_to_backpack / _update_shield).
        self._encode_error = False
        # Token-preserving state — every rebuild routes through
        # ``state.render()``; the token stream is authoritative. Value edits are
        # picked up via bindings; structural edits (checkbox/radio toggle,
        # picker add/remove) mutate state surgically via
        # ``state.insert()`` / ``state.remove_with_whitespace()``.
        # Fixes two shield bugs:
        #   (1) seed hardcoded to 306 — make_header_getter(seed_getter=None)
        #       preserves source seed on load-then-save AND load-then-value-
        #       edit-then-save.
        #   (2) unknown-part drop {246:[..44 46 48..]} → {246:[10 22]} —
        #       aggregation getter includes preserved unknowns from
        #       ``self._preserved_unknowns`` on every render.
        self._token_state = TokenOrderedState([])
        # Per-parent-id unknown children preserved across widget edits.
        self._preserved_unknowns: dict[int, list[int]] = {}
        # Session-random seed for fresh items. Backpack loads preserve the
        # source header via make_header_getter(seed_getter=None); this only
        # fires when the user creates a fresh shield via mfg-change /
        # Add-to-Backpack. Randomized to match weapon/heavy/enhancement so
        # multiple fresh shields don't collide on a single hardcoded seed.
        self._current_seed = str(random.randint(100, 9999))
        # Guards signal-driven structural handlers from firing during widget
        # populate (e.g. legendary_sel_list.clear on load fires rowsRemoved).
        self._populating = False

        self._build_ui()
        self.populate_initial_data()
        self._connect_signals()
        # populate_initial_data already calls on_mfg_change at the end, so no
        # second call is needed here — the widgets are fully populated before
        # signals are connected.
        self.refresh_backpack_items()

    def _load_ui_localization(self):
        self.ui_loc = load_tab_ui_loc("shield_tab", self.current_lang)

    def update_language(self, lang):
        log_editor(self.main_app, self._LOG_TAG, f"Updating language for {self.__class__.__name__} to {lang}...")
        self.current_lang = lang
        self.df_main, self.df_mfg, self.localization = load_shield_data(lang)

        if self.df_main is None:
            log_editor(self.main_app, self._LOG_TAG, f"load_shield_data failed for {self.__class__.__name__}")
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
        self.element_group.setTitle(self.ui_loc.get('groups', {}).get('element', 'Element'))
        self.firmware_group.setTitle(self.ui_loc.get('groups', {}).get('firmware', 'FW'))
        self.legendary_group.setTitle(self.ui_loc.get('groups', {}).get('legendary', 'Legendary'))
        self.energy_group.setTitle(self.ui_loc.get('groups', {}).get('energy', 'Energy'))
        self.armor_group.setTitle(self.ui_loc.get('groups', {}).get('armor', 'Armor'))
        self.universal_group.setTitle(self.ui_loc.get('groups', {}).get('universal', 'Universal'))
        
        self.legendary_clear_btn.setText(self.ui_loc.get('buttons', {}).get('clear', 'Clear'))
        self.energy_clear_btn.setText(self.ui_loc.get('buttons', {}).get('clear', 'Clear'))
        self.armor_clear_btn.setText(self.ui_loc.get('buttons', {}).get('clear', 'Clear'))
        self.universal_clear_btn.setText(self.ui_loc.get('buttons', {}).get('clear', 'Clear'))
        
        self._populate_flags()

        # Refresh Data
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
                    self._load_shield_item(current)
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
            item_filter=self._is_shield_item,
            row_builder=self._shield_browser_row,
            header_label=self.ui_loc.get('labels', {}).get('load_from_backpack', 'Load from Backpack'),
            search_placeholder=self.ui_loc.get('labels', {}).get('search_shield_placeholder', 'Search shield...'),
            empty_placeholder=self.ui_loc.get('dialogs', {}).get('no_shields_in_backpack', 'No shields in backpack'),
            no_save_placeholder=self.ui_loc.get('dialogs', {}).get('decrypt_save_to_show', 'Decrypt save first'),
            summary_formatter=self._summarize_shield,
            summary_none_text=self.ui_loc.get('summary', {}).get('none_selected', 'No backpack shield selected'),
        )
        self.browser.item_selected.connect(self._load_shield_item)
        splitter.addWidget(self.browser)

        # Right: existing scrollable editor content
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        container = QWidget(); scroll.setWidget(container); layout = QVBoxLayout(container)

        self._create_output_group(layout)
        self._create_top_controls(layout)

        self.perks_group = QGroupBox(self.ui_loc['groups']['perks']); perks_layout = QGridLayout(self.perks_group)
        self.element_group, self.element_frame, self.element_widgets = self._create_scrollable_radio_group(self.ui_loc['groups']['element'])
        self.firmware_group, self.firmware_frame, self.firmware_widgets = self._create_scrollable_radio_group(self.ui_loc['groups']['firmware'])
        perks_layout.addWidget(self.element_group, 0, 0); perks_layout.addWidget(self.firmware_group, 0, 1)

        self.legendary_group = self._create_list_perk_group(self.ui_loc['groups']['legendary'], key='legendary', use_multiplier=False)
        self.energy_group = self._create_list_perk_group(self.ui_loc['groups']['energy'], key='energy', use_multiplier=True)
        self.armor_group = self._create_list_perk_group(self.ui_loc['groups']['armor'], key='armor', use_multiplier=True)
        self.universal_group = self._create_list_perk_group(self.ui_loc['groups']['universal'], key='universal', use_multiplier=True)
        perks_layout.addWidget(self.legendary_group, 1, 0, 1, 2); perks_layout.addWidget(self.energy_group, 2, 0, 1, 2)
        perks_layout.addWidget(self.armor_group, 3, 0, 1, 2); perks_layout.addWidget(self.universal_group, 4, 0, 1, 2)
        layout.addWidget(self.perks_group)

        splitter.addWidget(scroll)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([320, 1040])

    def _create_output_group(self, layout):
        self.output_group = QGroupBox(self.ui_loc['groups']['output']); grid = QGridLayout(self.output_group)
        self.raw_output_edit = QLineEdit(); self.raw_output_edit.setReadOnly(True)
        self.b85_output_edit = QLineEdit(); self.b85_output_edit.setReadOnly(True)
        self.copy_raw_btn = QPushButton(self.ui_loc['buttons']['copy']); self.copy_b85_btn = QPushButton(self.ui_loc['buttons']['copy'])
        self.add_to_pack_btn = QPushButton(self.ui_loc['buttons']['add_to_backpack'])
        self.update_shield_btn = QPushButton(self.ui_loc.get('buttons', {}).get('update_shield', 'Update'))
        self.update_shield_btn.setEnabled(False)
        self.flag_combo = QComboBox()
        self._populate_flags()

        self.raw_label = QLabel(self.ui_loc['labels']['raw'])
        self.b85_label = QLabel(self.ui_loc['labels']['base85'])
        grid.addWidget(self.raw_label, 0, 0); grid.addWidget(self.raw_output_edit, 0, 1); grid.addWidget(self.copy_raw_btn, 0, 2)
        grid.addWidget(self.b85_label, 1, 0); grid.addWidget(self.b85_output_edit, 1, 1); grid.addWidget(self.copy_b85_btn, 1, 2)
        grid.addWidget(self.flag_combo, 1, 3); grid.addWidget(self.add_to_pack_btn, 1, 4); grid.addWidget(self.update_shield_btn, 1, 5)
        self.copy_raw_btn.clicked.connect(lambda: self._copy_to_clipboard(self.raw_output_edit))
        self.copy_b85_btn.clicked.connect(lambda: self._copy_to_clipboard(self.b85_output_edit))
        self.update_shield_btn.clicked.connect(self._update_shield)
        layout.addWidget(self.output_group)

    def _create_top_controls(self, layout):
        self.base_attrs_group = QGroupBox(self.ui_loc['groups']['base_attrs']); controls_layout = QHBoxLayout(self.base_attrs_group)
        self.mfg_combo = QComboBox(); self.level_edit = QLineEdit(self._character_level); self.rarity_combo = QComboBox()
        self.level_edit.setFixedWidth(100)
        self.rarity_combo.setFixedWidth(self._RARITY_COMBO_WIDTH)
        
        self.mfg_label = QLabel(self.ui_loc['labels']['manufacturer'])
        self.level_label = QLabel(self.ui_loc['labels']['level'])
        self.rarity_label = QLabel(self.ui_loc['labels']['rarity'])
        
        controls_layout.addWidget(self.mfg_label); controls_layout.addWidget(self.mfg_combo)
        controls_layout.addWidget(self.level_label); controls_layout.addWidget(self.level_edit)
        controls_layout.addWidget(self.rarity_label); controls_layout.addWidget(self.rarity_combo)
        controls_layout.addStretch(); layout.addWidget(self.base_attrs_group)

    def _create_scrollable_radio_group(self, title):
        group_box = QGroupBox(title); scroll_area = ContainedWheelScrollArea(); scroll_area.setWidgetResizable(True)
        scroll_area.setMinimumHeight(200)
        scroll_area.setMaximumHeight(200)
        widget_in_scroll = QWidget(); layout = QVBoxLayout(widget_in_scroll)
        scroll_area.setWidget(widget_in_scroll); main_layout = QVBoxLayout(group_box); main_layout.addWidget(scroll_area)
        return group_box, layout, []

    def _create_list_perk_group(self, title, key, single_select=False, use_multiplier=False):
        group = QGroupBox(title); layout = QGridLayout(group)
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
        
        prefix = key
        setattr(self, f"{prefix}_avail_list", avail); setattr(self, f"{prefix}_sel_list", sel)
        setattr(self, f"{prefix}_clear_btn", clear_btn)
        setattr(self, f"{prefix}_move_btn", move_btn)
        setattr(self, f"{prefix}_remove_btn", remove_btn)
        if multiplier_box:
            setattr(self, f"{prefix}_multiplier", multiplier_box)
        
        # Create placeholder label for energy/armor type mismatch message
        if prefix in ['energy', 'armor']:
            placeholder_label = QLabel()
            placeholder_label.setObjectName("shieldTypePlaceholderLabel")
            placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder_label.setWordWrap(True)
            placeholder_label.hide()  # Hidden by default
            layout.addWidget(placeholder_label, 1, 0, 1, 3)  # Span all columns
            setattr(self, f"{prefix}_placeholder_label", placeholder_label)
        
        move_btn.clicked.connect(lambda: self._move_selected_items(avail, sel, single_select, multiplier_box))
        remove_btn.clicked.connect(lambda: self._remove_selected_items(sel))
        clear_btn.clicked.connect(lambda: self._clear_list(sel))
        return group
        
    def _connect_signals(self):
        self.mfg_combo.currentTextChanged.connect(self.on_mfg_change)
        self.level_edit.textChanged.connect(self.rebuild_output)
        # Rarity is a value edit when the rarity token exists; structural when
        # it doesn't (fresh item + first rarity pick).
        self.rarity_combo.currentTextChanged.connect(self._on_rarity_changed)
        self.add_to_pack_btn.clicked.connect(self._add_to_backpack)
        # Legendary: surgical rebuild of legendary-only tokens on any change.
        # Energy/armor/universal: aggregation bucket getters; structural handler
        # only ensures token existence based on emptiness.
        self.legendary_sel_list.model().rowsInserted.connect(self._on_legendary_changed)
        self.legendary_sel_list.model().rowsRemoved.connect(self._on_legendary_changed)
        self.legendary_sel_list.model().dataChanged.connect(self._on_legendary_changed)
        for name, parent_attr in [
            ("energy", "_PARENT_ENERGY"),
            ("armor", "_PARENT_ARMOR"),
            ("universal", "_PARENT_SHARED"),
        ]:
            sel_list = getattr(self, f"{name}_sel_list")
            handler = self._make_bucket_change_handler(getattr(self, parent_attr))
            sel_list.model().rowsInserted.connect(handler)
            sel_list.model().rowsRemoved.connect(handler)
            sel_list.model().dataChanged.connect(handler)

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
            type_base = self._MFG_TYPES.get(k, "Unknown")
            # Shield_localization_zh-CN.json ships "Energy"/"Armor" keys so all
            # four languages resolve through self._ (no hardcoded fallbacks).
            type_loc = self._(type_base)
            items.append((f"{name} ({type_loc}) - {k}", k))

        items.sort(key=lambda x: x[1])

        self.mfg_combo.addItems([x[0] for x in items])

        shared = self.df_main[self.df_main['Shield_perk_main_ID'] == self._PARENT_SHARED]
        # Element/firmware radios contribute to the {246:[...]} shared bucket.
        # Aggregation getter reads current radio state on every render, so a
        # radio flip is a value edit; going None→data or data→None may need
        # to insert/remove the aggregation token (see _ensure_bucket_token).
        shared_handler = self._make_bucket_change_handler(self._PARENT_SHARED)
        self.element_widgets, self.element_none_rb = populate_radio_buttons(
            self.element_frame,
            self._radio_entries(shared, part_type='Elemental Resistance'),
            on_toggle=shared_handler,
            none_label=self.ui_loc['misc']['none'],
        )
        self.firmware_widgets, self.firmware_none_rb = populate_radio_buttons(
            self.firmware_frame,
            self._radio_entries(shared, part_type='Firmware'),
            on_toggle=shared_handler,
            none_label=self.ui_loc['misc']['none'],
        )
        self._populate_listbox(self.universal_avail_list, self.df_main[(self.df_main['Shield_perk_main_ID'] == self._PARENT_SHARED) & (self.df_main['Part_type'] == 'Perk')])
        self._populate_listbox(self.energy_avail_list, self.df_main[(self.df_main['Shield_perk_main_ID'] == self._PARENT_ENERGY) & (self.df_main['Part_type'] == 'Perk')])
        self._populate_listbox(self.armor_avail_list, self.df_main[(self.df_main['Shield_perk_main_ID'] == self._PARENT_ARMOR) & (self.df_main['Part_type'] == 'Perk')])
        self.on_mfg_change()

    def _radio_entries(self, df, *, part_type):
        """Prepare ``(text, part_id)`` entries for populate_radio_buttons —
        filters ``df`` by ``part_type`` and merges Description into the label."""
        entries = []
        for _, row in df[df['Part_type'] == part_type].iterrows():
            description = row['Description']
            display_text = f"{self._(row['Stat'])} - {description if pd.notna(description) else ''}"
            entries.append((display_text.removesuffix(" - "), row['Part_ID']))
        return entries
        
    def _populate_listbox(self, listbox, df):
        listbox.clear()
        for _, row in df.iterrows():
            item = QListWidgetItem(f"{self._(row['Stat'])} - {row['Description'] if pd.notna(row['Description']) else ''}")
            item.setData(Qt.ItemDataRole.UserRole, row['Part_ID'])
            listbox.addItem(item)
            
    def on_mfg_change(self, *args):
        mfg_id = selected_mfg_id_from_combo(self.mfg_combo)
        if mfg_id is None:
            return

        # Unknown mfg falls through to Energy rather than None so downstream
        # visibility checks (see _set_side_visibility) don't misbehave on a
        # future data addition.
        mfg_type = self._MFG_TYPES.get(mfg_id, "Energy")
        
        self.rarity_combo.blockSignals(True)
        self.rarity_combo.clear()
        df_rarities = self.df_mfg[(self.df_mfg['Manufacturer ID'] == mfg_id) & (self.df_mfg['Part_type'] == 'Rarity')]
        for _, row in df_rarities.iterrows():
            description = row['Description']
            display_text = f"{self._(row['Stat'])} - {description if pd.notna(description) else ''}"
            self.rarity_combo.addItem(display_text.removesuffix(" - "), row['Part_ID'])
        self.rarity_combo.blockSignals(False)

        self.legendary_avail_list.clear()
        df_leg = self.df_mfg[self.df_mfg['Part_type'] == 'Legendary Perk']
        for _, row in df_leg.iterrows():
            description = row['Description']
            display_text = f"{self._get_mfg_name(row['Manufacturer ID'])} - {self._(row['Stat'])} - {description if pd.notna(description) else ''}"
            item = QListWidgetItem(display_text.removesuffix(" - "))
            item.setData(Qt.ItemDataRole.UserRole, (row['Part_ID'], row['Manufacturer ID']))
            self.legendary_avail_list.addItem(item)
        
        # Localized type labels once per call; per-side blocks look these up
        # in the mismatch template.
        energy_type_name = self.ui_loc.get('misc', {}).get('shield_type_energy', 'Energy')
        armor_type_name = self.ui_loc.get('misc', {}).get('shield_type_armor', 'Armor')

        self._set_side_visibility('energy', mfg_type == 'Energy',
                                  incompatible_type=energy_type_name,
                                  shield_type=armor_type_name)
        self._set_side_visibility('armor', mfg_type == 'Armor',
                                  incompatible_type=armor_type_name,
                                  shield_type=energy_type_name)

        # on_mfg_change reshapes mfg-scoped widgets (rarity/legendary_avail /
        # side visibility); item type effectively changed → fresh state.
        if not self._is_loading:
            self._reset_state_to_fresh_item(mfg_id)

    def _set_side_visibility(self, side, is_active, *, incompatible_type, shield_type):
        """Toggle visibility of one side (energy/armor) group's 5 widgets plus
        the optional multiplier, and swap the placeholder label between hidden
        (active) and a localized "cannot add {incompatible} on {shield}" msg.

        Replaces two 15-line mirror blocks that previously lived inline in
        ``on_mfg_change`` — the only per-side variance is the widget-name
        prefix and which type-name plugs into the mismatch template.
        """
        for suffix in ('avail_list', 'sel_list', 'move_btn', 'remove_btn', 'clear_btn'):
            getattr(self, f"{side}_{suffix}").setVisible(is_active)
        multiplier = getattr(self, f"{side}_multiplier", None)
        if multiplier is not None:
            multiplier.setVisible(is_active)
        placeholder = getattr(self, f"{side}_placeholder_label", None)
        if placeholder is None:
            return
        if is_active:
            placeholder.hide()
            return
        template = self.ui_loc.get('misc', {}).get(
            'perk_type_mismatch',
            'Current shield type is {shield_type}.\nCannot add {incompatible_type} type perks.',
        )
        placeholder.setText(template.format(shield_type=shield_type, incompatible_type=incompatible_type))
        placeholder.show()

    def rebuild_output(self, *args):
        """State-first render. All widget values flow through bindings
        (rarity + three aggregation buckets 246/248/237) or through the
        token's raw form (unbound tokens — legendary tokens, unknown
        top-level simples). Structural mutations happen surgically in
        ``_on_*`` handlers via ``state.insert()`` / ``state.remove_with_whitespace()``,
        so this path is pure ``state.render()`` — the token stream is
        authoritative. Unknown children of {246:[...]} / {248:[...]} / {237:[...]} live in
        ``self._preserved_unknowns`` and are re-emitted by the aggregation
        getters on every render.
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
            log_editor(self.main_app, self._LOG_TAG, f"shield rebuild error: {e}")

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
            insert_at = 1  # after header
            pid = int(data)
            self._token_state.insert(insert_at, Token(raw=" ", kind="raw"))
            self._token_state.insert(insert_at + 1, Token(
                raw=f"{{{pid}}}", kind='simple', value=pid,
            ))
            self._token_state.bind(insert_at + 1, self._rarity_getter())
        self.rebuild_output()

    def _on_legendary_changed(self, *args):
        """Rebuild legendary tokens only. If empty, inject the mfg's Model
        part so the serial always carries a valid Model token.
        """
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
        # Also collect Model IDs so the auto-injected Model token from a prior
        # empty-legendary state gets removed when the user picks a legendary.
        model_ids = {int(v) for v in self.mfg_model_map.values()}

        to_remove: list[int] = []
        secondary_parents = (self._PARENT_SHARED, self._PARENT_ENERGY, self._PARENT_ARMOR)
        for idx, tok in enumerate(self._token_state.tokens):
            if tok.kind == 'simple' and tok.parent is None:
                if (tok.value, mfg_id) in legendary_pairs or tok.value in model_ids:
                    to_remove.append(idx)
            elif tok.kind == 'single' and tok.parent is not None and tok.parent not in secondary_parents:
                if (tok.value, tok.parent) in legendary_pairs:
                    to_remove.append(idx)
            elif tok.kind == 'list' and tok.parent is not None and tok.parent not in secondary_parents:
                if any((c, tok.parent) in legendary_pairs for c in tok.children):
                    to_remove.append(idx)
        for idx in reversed(to_remove):
            self._token_state.remove_with_whitespace(idx)

        insert_at = self._insert_idx_before_buckets()
        leg_items = [self.legendary_sel_list.item(i) for i in range(self.legendary_sel_list.count())]
        if not leg_items:
            if mfg_id in self.mfg_model_map:
                pid = int(self.mfg_model_map[mfg_id])
                self._token_state.insert(insert_at, Token(raw=" ", kind="raw"))
                self._token_state.insert(insert_at + 1, Token(
                    raw=f"{{{pid}}}", kind='simple', value=pid,
                ))
        else:
            cross_mfg: dict[int, list[int]] = {}
            for it in leg_items:
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

    def _make_bucket_change_handler(self, parent_id):
        """Return a handler for one aggregation bucket (parent_id). The
        handler calls ``_ensure_bucket_token(parent_id)`` and rebuilds output.
        Closes over ``parent_id`` so the same handler shape serves all three
        parents (SHARED/ENERGY/ARMOR).
        """
        def handler(*args):
            if self._is_loading or self._populating:
                return
            if not self._token_state.tokens:
                return
            self._ensure_bucket_token(parent_id)
            self.rebuild_output()
        return handler

    # ---- Bucket getters + ensure_token helpers ------------------------

    def _rarity_getter(self):
        def getter():
            data = self.rarity_combo.currentData()
            return f"{{{int(data)}}}" if data is not None else None
        return getter

    def _bucket_children(self, parent_id: int) -> list[int]:
        """Ordered children for one bucket parent: radios (for SHARED) +
        matching sel_list entries + preserved unknowns.

        Energy/armor sel_lists gate on ``isVisible`` — a hidden list is the
        inactive side after a mfg swap and its entries would leak into the
        wrong bucket. Universal is always active for shields (any mfg type),
        so it contributes unconditionally.
        """
        parts: list[int] = []
        gate_visible = True
        if parent_id == self._PARENT_SHARED:
            for rb in self.element_widgets:
                if rb.isChecked() and rb.property("part_id"):
                    parts.append(int(rb.property("part_id")))
                    break
            for rb in self.firmware_widgets:
                if rb.isChecked() and rb.property("part_id"):
                    parts.append(int(rb.property("part_id")))
                    break
            sel_list = self.universal_sel_list
            gate_visible = False  # universal always contributes
        elif parent_id == self._PARENT_ENERGY:
            sel_list = self.energy_sel_list
        elif parent_id == self._PARENT_ARMOR:
            sel_list = self.armor_sel_list
        else:
            return parts
        if not gate_visible or sel_list.isVisible():
            for i in range(sel_list.count()):
                item = sel_list.item(i)
                count, _ = parse_stack_count(item.text())
                pid_data = item.data(Qt.ItemDataRole.UserRole)
                if pid_data is None:
                    continue
                pid = int(pid_data)
                for _ in range(count):
                    parts.append(pid)
        parts.extend(self._preserved_unknowns.get(parent_id, []))
        return parts

    def _bucket_getter(self, parent_id: int):
        def getter():
            parts = self._bucket_children(parent_id)
            if not parts:
                return None
            if len(parts) == 1:
                return f"{{{parent_id}:{parts[0]}}}"
            body = " ".join(str(p) for p in parts)
            return f"{{{parent_id}:[{body}]}}"
        return getter

    def _ensure_bucket_token(self, parent_id: int) -> None:
        # Placeholder Token: raw='', kind='list', children=[] are ONLY chosen
        # to satisfy _find_bucket_token_idx's ``kind in ('single','list')``
        # filter — the bound bucket getter fully determines the rendered
        # output on every state.render(). The kind may not reflect the true
        # emitted shape (getter emits `{P:X}` when len(parts)==1 and
        # `{P:[a b c]}` otherwise); the raw is never emitted because getter
        # always returns non-None whenever we insert (parts is non-empty).
        parts = self._bucket_children(parent_id)
        idx = self._find_bucket_token_idx(parent_id)
        if not parts and idx != -1:
            self._token_state.remove_with_whitespace(idx)
        elif parts and idx == -1:
            insert_at = self._insert_idx_before_trailing_pipe()
            self._token_state.insert(insert_at, Token(raw=" ", kind="raw"))
            self._token_state.insert(insert_at + 1, Token(
                raw="", kind='list', parent=parent_id, children=[],
            ))
            self._token_state.bind(insert_at + 1, self._bucket_getter(parent_id))

    # ---- Index-finding helpers ----------------------------------------

    def _find_rarity_token_idx(self) -> int:
        rarity_ids = combo_data_ids(self.rarity_combo)
        for idx, tok in enumerate(self._token_state.tokens):
            if tok.kind == 'simple' and tok.parent is None and tok.value in rarity_ids:
                return idx
        return -1

    def _find_bucket_token_idx(self, parent_id: int) -> int:
        for idx, tok in enumerate(self._token_state.tokens):
            if tok.parent == parent_id and tok.kind in ('single', 'list'):
                return idx
        return -1

    def _insert_idx_before_buckets(self) -> int:
        """Insert idx for legendary tokens: before the first aggregation
        bucket or the trailing pipe."""
        secondary_parents = (self._PARENT_SHARED, self._PARENT_ENERGY, self._PARENT_ARMOR)
        for idx, tok in enumerate(self._token_state.tokens):
            if tok.parent in secondary_parents and tok.kind in ('single', 'list'):
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
        [header, ' |']. Rarity is auto-inserted via ``_on_rarity_changed``
        if the combo currently has a selection. Aggregation buckets are
        inserted lazily by their ensure_token helpers when a widget is
        toggled. Legendary is inserted by ``_on_legendary_changed`` (which
        also handles the empty→Model auto-inject).

        Option 1 for mfg change: preserved unknowns from a previous item
        are DISCARDED — the user chose a different mfg, so those unknowns
        wouldn't be valid anyway. Documented in the design.
        """
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
        # Trigger initial rarity + legendary auto-inject via their handlers.
        # _on_legendary_changed emits the Model token when sel_list is empty.
        self._on_rarity_changed()
        self._on_legendary_changed()

    def _bind_token_state_widgets(self):
        """Attach getters to loaded state: rarity ONLY. All ``{246:...}`` /
        ``{248:...}`` / ``{237:...}`` bucket tokens stay UNBOUND so their
        source raw form is emitted verbatim on value edits — this preserves
        source order, split-list shape, and unknown children across
        rarity/level changes. Structural handlers (``_on_legendary_changed``,
        ``_on_secondary_widget_changed`` via ``_ensure_bucket_token``)
        surgically mutate the bucket tokens and bind aggregation getters
        onto the freshly-inserted tokens; unknowns persist across those
        rebuilds via ``self._preserved_unknowns``.
        """
        if not self._token_state.tokens:
            return
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
                 
                 existing_item = None
                 current_count = 1
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
        # rowsRemoved on the underlying model fires _on_structural_change
        # via the sel_list signal wiring; no extra call needed here.

    def _clear_list(self, list_widget):
        list_widget.clear()
        # rowsRemoved fires _on_structural_change; no extra call needed.

    def _populate_flags(self):
        populate_flag_combo(self.flag_combo, self.current_lang)

    def _copy_to_clipboard(self, line_edit): QApplication.clipboard().setText(line_edit.text()); QMessageBox.information(self, self.ui_loc['dialogs']['success'], self.ui_loc['dialogs']['copied'])
        
    def _add_to_backpack(self):
        serial = self.b85_output_edit.text()
        if not serial or self._encode_error: QMessageBox.warning(self, self.ui_loc['dialogs']['no_valid_code'], self.ui_loc['dialogs']['gen_first']); return
        self.add_to_backpack_requested.emit(serial, self.flag_combo.currentText().split(" ")[0])

    # ---- Backpack browser integration ---------------------------------

    @staticmethod
    def _is_shield_item(item):
        return item.get("type_en") == "Shield" and "Backpack" in (item.get("container") or "")

    def _shield_browser_row(self, item):
        """Vertical-card row for the browser. Mirrors weapon/grenade layout;
        placeholders in the stat strip until a resolve_shield_stats resolver
        exists."""
        manufacturer = item.get("manufacturer") or self.ui_loc.get('parts', {}).get('unknown', 'Unknown')
        type_label = item.get("type") or self.ui_loc.get('parts', {}).get('unknown_item', 'Shield')
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
        for column, key in enumerate(("capacity", "recharge_delay", "recharge_rate", "damage_reduction", "element")):
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

    def _summarize_shield(self, item):
        return summarize_item(
            item,
            template=self.ui_loc.get('summary', {}).get('selected', 'Selected · {name} · Lv.{level}'),
            none_text=self.ui_loc.get('summary', {}).get('none_selected', 'No backpack shield selected'),
            fallback_name=self.ui_loc.get('summary', {}).get('fallback_name', 'Shield'),
        )

    def refresh_backpack_items(self):
        if hasattr(self, "browser"):
            self.browser.refresh()

    # ---- Reverse parser (backpack shield -> editor widgets) -----------

    def _load_shield_item(self, item):
        """Populate editor fields from a decoded shield in the backpack.

        Shield-specific dispatch differs from grenade in three ways:
          - secondary parents are ``_PARENT_SHARED`` (element/firmware/universal),
            ``_PARENT_ENERGY`` (energy), and ``_PARENT_ARMOR`` (armor) —
            grenade uses a single ``_SECONDARY_PARENT``
          - no mfg-perk checkboxes (shields have four dual-list groups instead)
          - the auto-injected {mfg_model_map[mfg_id]} token must be silently
            skipped (rebuild will re-emit it if legendary_sel_list is empty)
        """
        if not item:
            return
        decoded = item.get("decoded_full", "") or ""
        if "||" not in decoded:
            log_editor(self.main_app, self._LOG_TAG, f"shield load: no components in {item.get('name', 'unknown')}")
            return

        self._is_loading = True
        try:
            self.selected_item_path = item.get("original_path")

            # Parse into token state; bind header so state.render() picks up
            # level edits and preserves source seed on the load-then-save
            # AND load-then-value-edit-then-save paths (fixes hardcoded 306).
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
                log_editor(self.main_app, self._LOG_TAG, f"shield load: bad header for {item.get('name', 'unknown')}")
                return

            # Snap mfg → run on_mfg_change (reconfigures energy/armor visibility).
            self.mfg_combo.blockSignals(True)
            mfg_idx = find_mfg_combo_index(self.mfg_combo, mfg_id)
            if mfg_idx >= 0:
                self.mfg_combo.setCurrentIndex(mfg_idx)
            self.mfg_combo.blockSignals(False)
            self.on_mfg_change()

            self.level_edit.blockSignals(True)
            self.level_edit.setText(str(level))
            self.level_edit.blockSignals(False)

            # Reset element/firmware radios via their None radio (stored on
            # ``self.<group>_none_rb`` by the shared populate helper). Radios
            # share a parent QWidget so auto-exclusive semantics unset the
            # previous data radio automatically.
            self.element_none_rb.setChecked(True)
            self.firmware_none_rb.setChecked(True)
            self.legendary_sel_list.clear()
            self.energy_sel_list.clear()
            self.armor_sel_list.clear()
            self.universal_sel_list.clear()

            # Lookups built post-on_mfg_change so per-mfg widgets exist.
            ctx = ShieldLoadContext(
                mfg_id=mfg_id,
                mfg_type=self._MFG_TYPES.get(mfg_id, "Energy"),
                model_id=self.mfg_model_map.get(mfg_id),
                rarity_ids=combo_data_ids(self.rarity_combo),
                element_by_id={rb.property("part_id"): rb for rb in self.element_widgets if rb.property("part_id")},
                firmware_by_id={rb.property("part_id"): rb for rb in self.firmware_widgets if rb.property("part_id")},
                legendary_by_id=legendary_lookup(self.legendary_avail_list),
                universal_by_id=list_widget_by_userrole(self.universal_avail_list),
                energy_by_id=list_widget_by_userrole(self.energy_avail_list),
                armor_by_id=list_widget_by_userrole(self.armor_avail_list),
                item_name=item.get("name", "unknown"),
            )

            self._preserved_unknowns = {}
            for token in parse_component_string(component):
                self._apply_shield_token(token, ctx)

            set_flag_from_item(self.flag_combo, item, main_app=self.main_app, tag=self._LOG_TAG)
            self.update_shield_btn.setEnabled(True)
            # Bind rarity + first {246/248/237:...} tokens so subsequent value
            # edits are picked up on the next state.render() call. Runs BEFORE
            # the _is_loading guard drops so the render fires exactly once.
            self._bind_token_state_widgets()
        finally:
            self._is_loading = False
            # State is source-parsed with bindings live — emit verbatim.
            self.rebuild_output()

    def _apply_shield_token(self, token, ctx):
        ttype = token['type']
        if ttype == 'simple':
            pid = token['id']
            if pid in ctx.rarity_ids:
                set_rarity_by_id(self.rarity_combo, pid, main_app=self.main_app, tag=self._LOG_TAG)
            elif pid == ctx.model_id:
                # Auto-injected when legendary list is empty; ignore on load.
                return
            elif (pid, ctx.mfg_id) in ctx.legendary_by_id:
                stack_into_sel_list(self.legendary_sel_list, ctx.legendary_by_id[(pid, ctx.mfg_id)])
            else:
                log_editor(self.main_app, self._LOG_TAG, f"shield load: unknown simple id {pid} in {ctx.item_name}")
            return

        # elemental and group share dispatch — iter_children normalizes the
        # difference so each parent gets one branch instead of two mirrors.
        parent = token['id']
        for child in iter_children(token):
            if parent == self._PARENT_SHARED:
                self._route_shared(child, ctx)
            elif parent == self._PARENT_ENERGY:
                self._add_to_sel_list(self.energy_sel_list, ctx.energy_by_id, child, "energy", ctx)
            elif parent == self._PARENT_ARMOR:
                self._add_to_sel_list(self.armor_sel_list, ctx.armor_by_id, child, "armor", ctx)
            elif (child, parent) in ctx.legendary_by_id:
                stack_into_sel_list(self.legendary_sel_list, ctx.legendary_by_id[(child, parent)])
            else:
                log_editor(self.main_app, self._LOG_TAG, f"shield load: unknown cross-mfg leg {parent}:{child} in {ctx.item_name}")

    def _route_shared(self, pid, ctx):
        """Route a Part_ID under ``_PARENT_SHARED`` in priority order:
        element radio → firmware radio → universal-perk sel list → preserved
        unknown. Unknowns are stored so the aggregation getter re-emits them
        on every render (preserves the unknown-part bug fix across BOTH value
        and structural edits).
        """
        if pid in ctx.element_by_id:
            ctx.element_by_id[pid].setChecked(True)
        elif pid in ctx.firmware_by_id:
            ctx.firmware_by_id[pid].setChecked(True)
        elif pid in ctx.universal_by_id:
            stack_into_sel_list(self.universal_sel_list, ctx.universal_by_id[pid], use_prefix=True)
        else:
            self._preserved_unknowns.setdefault(self._PARENT_SHARED, []).append(int(pid))
            log_editor(self.main_app, self._LOG_TAG, f"shield load: unknown {self._PARENT_SHARED}-child id {pid} preserved in {ctx.item_name}")

    def _add_to_sel_list(self, sel_list, avail_by_id, pid, side, ctx):
        """Add a numeric perk to energy/armor sel list. Guards against a serial
        carrying perks for the opposite type from what the current mfg supports.
        Unknown pids are stored as preserved unknowns for that bucket so the
        aggregation getter keeps re-emitting them.
        """
        parent_id = self._PARENT_ENERGY if side == "energy" else self._PARENT_ARMOR
        if side == "energy" and ctx.mfg_type != "Energy":
            log_editor(self.main_app, self._LOG_TAG, f"shield load: energy perk {pid} on armor shield ({ctx.item_name}) — skipped")
            return
        if side == "armor" and ctx.mfg_type != "Armor":
            log_editor(self.main_app, self._LOG_TAG, f"shield load: armor perk {pid} on energy shield ({ctx.item_name}) — skipped")
            return
        if pid in avail_by_id:
            stack_into_sel_list(sel_list, avail_by_id[pid], use_prefix=True)
        else:
            self._preserved_unknowns.setdefault(parent_id, []).append(int(pid))
            log_editor(self.main_app, self._LOG_TAG, f"shield load: unknown {side} perk id {pid} preserved in {ctx.item_name}")

    def _update_shield(self):
        emit_update_or_warn(
            self,
            new_serial=self.b85_output_edit.text(),
            no_selection_title=self.ui_loc.get('dialogs', {}).get('no_selection', 'No Selection'),
            no_selection_msg=self.ui_loc.get('dialogs', {}).get('select_shield_first', 'Select a shield first'),
            no_valid_code_title=self.ui_loc.get('dialogs', {}).get('no_valid_code', 'No Valid Code'),
            no_valid_code_msg=self.ui_loc.get('dialogs', {}).get('gen_first', 'Generate a valid shield first'),
            success_msg=self.ui_loc.get('dialogs', {}).get('update_success', 'Shield updated'),
        )

    def set_character_level(self, level: str):
        """设置角色等级，更新默认等级显示。"""
        self._character_level = level if level else "50"
        if hasattr(self, 'level_edit'):
            self.level_edit.setText(self._character_level)
