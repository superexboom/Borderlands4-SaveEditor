"""Unified Weapons tab: edit an existing weapon or build a fresh one.

- Static two-column parts table. Every slot in ``SLOT_LAYOUT_ORDER`` renders
  every time; ``_LEFT_COLUMN_PRIMARIES`` and ``_RIGHT_COLUMN_PRIMARIES`` are
  hard-locked so layout doesn't shift with weapon shape. Filled rows carry
  a ``PositionalTokenRow`` with ``[↑][#][↓]`` swap controls; empty rows show
  a blank dropdown and disabled controls.
- Empty rows emit NO tokens. Fresh serials contain only the header + the
  trailing ``|`` closer; picking a value in a blank row inserts a fresh
  typed token at the schema-ordered position via ``state.insert``. Blanking
  a filled row calls ``state.remove_with_whitespace``.
- Cross-mfg parts appear in every dropdown, split into two labelled
  sections ("same weapon type" and "other weapon types") beneath the
  same-mfg entries. Options are labeled ``[<Mfg>]`` (with a
  ``<weapon-type>`` suffix when two mfg_ids share the same display
  label) and encode as ``{other_mfg:[part_id]}`` (kind='list'). The game
  reads the mfg_id from the token to pick the correct part_type table,
  so cross-mfg combinations resolve unambiguously even when raw pids
  overlap across mfgs. This is the "cheat weapons" feature — intentional.
- ``TokenOrderedState`` is the single source of truth. Every parts_data
  dict carries a ``_tok`` back-ref to its state Token so lookups stay
  identity-based (survives ``state.swap`` reordering without needing
  parts_data to stay parallel).
"""

from PyQt6 import QtWidgets, QtCore, QtGui
import pandas as pd
import random
import re
from functools import partial

# ``{123}`` at the start of a components section is a rarity token by
# convention — used by ``_resolve_stats`` to decide whether the empty
# resolver result stems from a missing rarity (safe to splice in a
# fallback) or something else (splicing would fabricate wrong stats).
_HAS_LEADING_SIMPLE_TOKEN = re.compile(r'^\{\d+\}')

from core import bl4_functions as bl4f
from core import b_encoder
from core import decoder_logic
from core import item_display_resolver
from core import resource_loader
from tabs.qt_item_browser import ItemBrowser, PositionalTokenRow, ROW_HEIGHT
from tabs.qt_editor_shared import (
    Token,
    TokenOrderedState,
    block_signals,
    emit_update_or_warn,
    load_tab_ui_loc,
    log_editor,
    make_header_getter,
    parse_component_string_with_skin,
    populate_flag_combo,
    summarize_item,
)


class QtWeaponsTab(QtWidgets.QWidget):
    add_to_backpack_requested = QtCore.pyqtSignal(str, str)
    update_item_requested = QtCore.pyqtSignal(dict)
    # Re-emit from ``self.browser.item_delete_requested`` — connected inside
    # _build_ui after browser creation so it survives language-switch rebuilds.
    item_delete_requested = QtCore.pyqtSignal(list)

    _WEAPON_TYPES = frozenset({"Pistol", "Shotgun", "SMG", "Assault Rifle", "Sniper"})
    _LOG_TAG = "weapons"

    # STATIC slot schema — every Part Type here renders as a row (or as
    # several rows for multi-select accessories), always. If the current
    # weapon shape can't legally populate a slot, its dropdown just stays
    # on "(none)". This is
    # the "UI continuity" contract — the parts table looks identical across
    # every mfg / weapon-type pairing.
    SLOT_LAYOUT_ORDER = (
        "Body", "Body Accessory",
        "Barrel", "Barrel Accessory",
        "Underbarrel", "Underbarrel Accessory",
        "Magazine", "Magazine Accessory",
        "Foregrip", "Grip",
        "Scope", "Scope Accessory",
        "Manufacturer Part", "Tediore Payload",
        "Tediore Throw Reload", "Borg Magazine Adapter",
        "Special Element Set",
        "Element",  # sourced from elemental.csv (Elemental_ID=1), 2 slots.
    )

    # Sxb's multi-select accessory row counts. Hard-capped at
    # MAX_SUBPART_COUNT because the game accepts at most 4 subparts per
    # accessory slot type. All non-listed Part Types get a single row.
    MULTI_SELECT_SLOTS = {
        "Body Accessory": 4, "Barrel Accessory": 4,
        "Manufacturer Part": 4, "Scope Accessory": 4,
        "Underbarrel Accessory": 3,
        "Element": 2,
    }
    MAX_SUBPART_COUNT = 4
    _ELEMENT_PARENT_ID = 1  # {1:X} tokens are the Element-family encoding

    PART_TYPE_COLORS = {
        "Barrel": "#B0BEC5",
        "Barrel Accessory": "#90A4AE",
        "Body": "#BCAAA4",
        "Body Accessory": "#A1887F",
        "Foregrip": "#9CCC65",
        "Grip": "#AED581",
        "Magazine": "#FFB300",
        "Magazine Accessory": "#FFCA28",
        "Manufacturer Part": "#9FA8DA",
        "Scope": "#4DD0E1",
        "Scope Accessory": "#26C6DA",
        "Stat Modifier": "#F06292",
        "Underbarrel": "#BCAAA4",
        "Underbarrel Accessory": "#A1887F",
        "Elemental": "#EF9A9A",
        "Element": "#EF9A9A",
        "Element Switch": "#EF9A9A",
        "Underbarrel Element Switch": "#EF9A9A",
        "Pearl Elements": "#80CBC4",
        "Pearl Stat": "#CE93D8",
        "Skin": "#FFEA00",
        "Rarity": "#B39DDB",
        "Legendary": "#FF8A65",
    }

    TAXONOMY_KEYS = {
        "Body": "body", "Body Accessory": "body_accessory",
        "Barrel": "barrel", "Barrel Accessory": "barrel_accessory",
        "Manufacturer Part": "manufacturer_part", "Tediore Payload": "tediore_payload",
        "Tediore Throw Reload": "tediore_throw_reload", "Magazine": "magazine",
        "Magazine Accessory": "magazine_accessory", "Scope": "scope",
        "Scope Accessory": "scope_accessory", "Grip": "grip",
        "Underbarrel": "underbarrel", "Underbarrel Accessory": "underbarrel_accessory",
        "Foregrip": "foregrip", "Borg Magazine Adapter": "borg_magazine_adapter",
        "Special Element Set": "special_element_set", "Stat Modifier": "stat_modifier",
        "Elemental": "elemental", "Element": "element", "Element Switch": "element_switch",
        "Underbarrel Element Switch": "underbarrel_element_switch",
        "Pearl Elements": "pearl_elements", "Pearl Stat": "pearl_stat",
        "Skin": "skin", "Rarity": "rarity", "Common": "common",
        "Uncommon": "uncommon", "Rare": "rare", "Epic": "epic",
        "Legendary": "legendary", "Pearl": "pearl",
        "Assault Rifle": "assault_rifle", "Pistol": "pistol", "Shotgun": "shotgun",
        "SMG": "smg", "Sniper": "sniper",
    }

    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app
        self.current_lang = 'zh-CN'
        self._character_level = "50"

        self.selected_item_path = None
        self._is_loading = False
        self._is_fresh = False
        self._encode_error = False

        self.parts_data = []
        self.rarity_part = None
        self._token_state = TokenOrderedState([])
        self._current_seed = str(random.randint(100, 9999))

        # Positional rows (one per filled schema slot). Populated by
        # _rebuild_parts_table; used by _resync_positional_indices to
        # refresh every row's [#] label after any state.swap / state.move.
        self._positional_rows: list[PositionalTokenRow] = []

        # Schema-driven table state. _slot_schema and _slot_parts are always
        # parallel lists (equal length). Each _slot_parts entry is either a
        # part-dict from parts_data (filled slot) or None (empty slot).
        # _slot_row_widgets holds the corresponding UI row for each slot so
        # index sync + selective mutations can update just the affected row.
        self._slot_schema: list[dict] = []
        self._slot_parts: list[dict | None] = []
        self._slot_row_widgets: list[QtWidgets.QWidget] = []

        self.all_weapon_parts_df = None
        self.elemental_df = None
        self.skin_df = None
        self.weapon_rarity_df = None
        self.weapon_localization = {}

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.content_widget = None

        self.load_data(self.current_lang)
        self._build_ui()

    # ---------- data loading -----------

    def _load_ui_localization(self) -> None:
        """Refresh ``ui_loc`` from the language JSON. Matches the sibling
        editor tabs' shape so language switches follow one convention."""
        self.ui_loc = load_tab_ui_loc("weapon_editor_tab", self.current_lang)

    def load_data(self, lang='zh-CN'):
        self.current_lang = lang
        self._load_ui_localization()
        try:
            suffix = "_EN" if lang in ['en-US', 'ru', 'ua'] else ""

            def get_path(base_name):
                name_with_suffix = base_name.replace('.csv', f'{suffix}.csv')
                path = resource_loader.get_weapon_data_path(name_with_suffix)
                if path and path.exists():
                    return path
                return resource_loader.get_weapon_data_path(base_name)

            self.all_weapon_parts_df = pd.read_csv(get_path('all_weapon_part.csv'))
            self.elemental_df = pd.read_csv(resource_loader.get_weapon_data_path('elemental.csv'))
            self.elemental_stat_col = 'Stat_ZH' if lang == 'zh-CN' else 'Stat'
            self.skin_df = pd.read_csv(resource_loader.get_weapon_data_path('skin.csv'))
            self.skin_df['Skin_ID'] = self.skin_df['Skin_ID'].astype(str)
            self.skin_stat_col = 'Stat_EN' if lang in ['en-US', 'ru', 'ua'] else 'Stat'
            self.weapon_rarity_df = pd.read_csv(get_path('weapon_rarity.csv'))
            self.rarity_desc_col = 'Description_ZH' if lang == 'zh-CN' else 'Description'

            self.weapon_localization = {}
            if lang == 'zh-CN':
                self.weapon_localization = resource_loader.load_weapon_json('weapon_localization_zh-CN.json') or {}

            self._load_label_overrides()
            self.setEnabled(True)

        except FileNotFoundError as e:
            QtWidgets.QMessageBox.critical(
                self,
                self._loc('dialogs', 'error', "Error"),
                self._loc('dialogs', 'missing_required_file', "Missing required file: {error}", error=e),
            )
            self.setEnabled(False)
        except (pd.errors.EmptyDataError, KeyError, ValueError) as e:
            QtWidgets.QMessageBox.critical(
                self,
                self._loc('dialogs', 'error', "Error"),
                self._loc('dialogs', 'data_load_error', "An error occurred while loading data: {error}", error=e),
            )
            self.setEnabled(False)

    def update_language(self, lang):
        log_editor(self.main_app, self._LOG_TAG, f"Updating language for {self.__class__.__name__} to {lang}...")
        self.current_lang = lang
        self.load_data(lang)

        current_decoded = self.serial_decoded_entry.text() if hasattr(self, 'serial_decoded_entry') else ""
        current_flag_idx = self.flag_combo.currentIndex() if hasattr(self, 'flag_combo') else 0
        current_weapon_path = self.selected_item_path

        self.parts_data = []
        self.rarity_part = None
        self.selected_item_path = current_weapon_path
        self._positional_rows = []
        self._slot_schema = []
        self._slot_parts = []
        self._slot_row_widgets = []

        self._build_ui()
        self.refresh_backpack_items()

        if hasattr(self, 'flag_combo') and self.flag_combo.count() > current_flag_idx:
            self.flag_combo.setCurrentIndex(current_flag_idx)

        if current_decoded:
            self.serial_decoded_entry.setText(current_decoded)
            self.parse_and_display_weapon(current_decoded)
        log_editor(self.main_app, self._LOG_TAG, f"Finished updating language for {self.__class__.__name__}.")

    # ---------- UI construction ----------

    def _build_ui(self):
        while self.main_layout.count():
            item = self.main_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
        self.content_widget = None

        self.content_widget = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout(self.content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.addWidget(self.content_widget)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        content_layout.addWidget(splitter)

        self.browser = ItemBrowser(
            main_app=self.main_app,
            item_filter=self._is_weapon_item,
            row_builder=self._weapon_browser_row,
            header_label=self.get_localized_string("load_from_backpack"),
            search_placeholder=self._loc('labels', 'search_weapon_placeholder',
                                        "Search name, manufacturer, type, level, or slot"),
            empty_placeholder=self.get_localized_string("no_weapons_in_backpack"),
            no_save_placeholder=self.get_localized_string("decrypt_save_to_show_weapons"),
            summary_formatter=self._summarize_weapon,
            summary_none_text=self._loc('summary', 'none_selected', "No backpack weapon selected"),
        )
        # Re-emit so main_window can wire once to a signal that survives
        # _build_ui rebuilds (browser gets recreated on language switch).
        self.browser.item_delete_requested.connect(self.item_delete_requested.emit)
        self.browser.item_selected.connect(self._load_weapon_item)
        splitter.addWidget(self.browser)

        editor = self._build_editor()
        splitter.addWidget(editor)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([320, 1040])

    def _build_editor(self) -> QtWidgets.QWidget:
        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)
        main_frame = QtWidgets.QFrame()
        scroll_area.setWidget(main_frame)
        layout = QtWidgets.QGridLayout(main_frame)
        layout.setColumnStretch(0, 1)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)

        # --- serial output row ---
        s_frame = QtWidgets.QFrame(); s_frame.setObjectName("InnerFrame")
        s_layout = QtWidgets.QGridLayout(s_frame)
        s_layout.setColumnStretch(1, 1)
        s_layout.addWidget(QtWidgets.QLabel(self.get_localized_string("serial_b85")), 0, 0)
        self.serial_b85_entry = QtWidgets.QLineEdit()
        s_layout.addWidget(self.serial_b85_entry, 0, 1)
        s_layout.addWidget(QtWidgets.QLabel(self.get_localized_string("serial_decoded")), 1, 0)
        self.serial_decoded_entry = QtWidgets.QLineEdit()
        s_layout.addWidget(self.serial_decoded_entry, 1, 1)
        layout.addWidget(s_frame, 0, 0)

        # --- config strip: EVERYTHING on ONE row --------------------------
        # Nine columns: mfg | type | rarity | level | seed | generate |
        # update | add-to-pack | category. Labels only above the five config
        # combos (cols 0..4); buttons/flag combo (cols 5..8) speak for
        # themselves.
        editor_frame = QtWidgets.QFrame(); editor_frame.setObjectName("InnerFrame")
        editor_layout = QtWidgets.QGridLayout(editor_frame)
        for i in range(9):
            editor_layout.setColumnStretch(i, 1)

        for i, lbl_key in enumerate(("manufacturer", "weapon_type", "rarity", "level", "seed")):
            editor_layout.addWidget(
                QtWidgets.QLabel(self.get_localized_string(lbl_key)),
                0, i, QtCore.Qt.AlignmentFlag.AlignCenter,
            )

        # mfg / type are combos so fresh mode can drive them; disabled while
        # editing a loaded weapon so the user can't switch shape mid-edit.
        self.manufacturer_combo = QtWidgets.QComboBox()
        self.type_combo = QtWidgets.QComboBox()
        self.manufacturer_combo.setEnabled(False)
        self.type_combo.setEnabled(False)
        editor_layout.addWidget(self.manufacturer_combo, 1, 0)
        editor_layout.addWidget(self.type_combo, 1, 1)

        self.rarity_combo = QtWidgets.QComboBox()
        rarity_values = [self.get_localized_string(r) for r in ["Common", "Uncommon", "Rare", "Epic"]]
        self.rarity_combo.addItems(rarity_values)
        editor_layout.addWidget(self.rarity_combo, 1, 2)

        self.level_edit = QtWidgets.QLineEdit()
        self.level_edit.setValidator(QtGui.QIntValidator(1, 100))
        editor_layout.addWidget(self.level_edit, 1, 3)

        seed_layout = QtWidgets.QGridLayout()
        seed_frame = QtWidgets.QFrame(); seed_frame.setLayout(seed_layout)
        self.seed_entry = QtWidgets.QLineEdit()
        self.seed_entry.setValidator(QtGui.QIntValidator())
        seed_layout.addWidget(self.seed_entry, 0, 0)
        self.random_seed_btn = QtWidgets.QPushButton("🎲")
        self.random_seed_btn.setFixedWidth(40)
        seed_layout.addWidget(self.random_seed_btn, 0, 1)
        editor_layout.addWidget(seed_frame, 1, 4)

        self.generate_btn = QtWidgets.QPushButton(
            self._loc('buttons', 'generate', "Generate")
        )
        self.update_weapon_btn = QtWidgets.QPushButton(self.get_localized_string("update_weapon"))
        self.add_to_backpack_btn = QtWidgets.QPushButton(self.get_localized_string("add_to_backpack"))
        self.flag_combo = QtWidgets.QComboBox()
        populate_flag_combo(self.flag_combo, self.current_lang)
        # Category (flag_combo) sits right after seed, then the action buttons.
        editor_layout.addWidget(self.flag_combo, 1, 5)
        editor_layout.addWidget(self.generate_btn, 1, 6)
        editor_layout.addWidget(self.update_weapon_btn, 1, 7)
        editor_layout.addWidget(self.add_to_backpack_btn, 1, 8)

        # weapon-name label + stats grid
        self.weapon_name_label_str = self.get_localized_string("weapon_name_label")
        self.weapon_name_label = QtWidgets.QLabel(self.weapon_name_label_str)
        self.weapon_name_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        editor_layout.addWidget(self.weapon_name_label, 2, 0, 1, 9)

        stats_layout = QtWidgets.QGridLayout()
        stats_loc = self.ui_loc.get('stats', {})
        self.weapon_stat_value_labels = {}
        for index, key in enumerate(item_display_resolver.WEAPON_STAT_KEYS):
            row, column = divmod(index, 4)
            title_row = row * 2
            title = QtWidgets.QLabel(stats_loc.get(key, key.replace('_', ' ').title()))
            title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            title.setWordWrap(True)
            value = QtWidgets.QLabel("—")
            value.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            value.setMinimumWidth(72)
            value.setObjectName("WeaponStatValue")
            stats_layout.addWidget(title, title_row, column)
            stats_layout.addWidget(value, title_row + 1, column)
            stats_layout.setColumnStretch(column, 1)
            self.weapon_stat_value_labels[key] = value
        editor_layout.addLayout(stats_layout, 3, 0, 1, 9)
        layout.addWidget(editor_frame, 1, 0)

        # --- parts table (positional rows) ---
        parts_frame = QtWidgets.QFrame(); parts_frame.setObjectName("InnerFrame")
        parts_layout = QtWidgets.QVBoxLayout(parts_frame)

        parts_header_frame = QtWidgets.QFrame()
        parts_header_layout = QtWidgets.QGridLayout(parts_header_frame)
        parts_header_layout.addWidget(
            QtWidgets.QLabel(self.get_localized_string("weapon_parts")), 0, 0,
            QtCore.Qt.AlignmentFlag.AlignLeft,
        )
        parts_header_layout.setColumnStretch(0, 1)
        self.clear_parts_btn = QtWidgets.QPushButton(
            self._loc('buttons', 'clear_parts', "Clear")
        )
        self.clear_parts_btn.setMinimumWidth(100)
        parts_header_layout.addWidget(self.clear_parts_btn, 0, 1, QtCore.Qt.AlignmentFlag.AlignRight)
        parts_layout.addWidget(parts_header_frame)

        # Host container: two side-by-side columns, each a QVBoxLayout of
        # slot rows. Column assignments are hard-locked via
        # ``_LEFT_COLUMN_PRIMARIES`` / ``_RIGHT_COLUMN_PRIMARIES``.
        self._parts_table_host = QtWidgets.QWidget()
        _parts_columns_layout = QtWidgets.QHBoxLayout(self._parts_table_host)
        _parts_columns_layout.setContentsMargins(0, 0, 0, 0)
        _parts_columns_layout.setSpacing(8)

        _left_col = QtWidgets.QWidget()
        self._parts_table_left_layout = QtWidgets.QVBoxLayout(_left_col)
        self._parts_table_left_layout.setContentsMargins(0, 0, 0, 0)
        self._parts_table_left_layout.setSpacing(4)
        self._parts_table_left_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        _parts_columns_layout.addWidget(_left_col, 1)

        _right_col = QtWidgets.QWidget()
        self._parts_table_right_layout = QtWidgets.QVBoxLayout(_right_col)
        self._parts_table_right_layout.setContentsMargins(0, 0, 0, 0)
        self._parts_table_right_layout.setSpacing(4)
        self._parts_table_right_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        _parts_columns_layout.addWidget(_right_col, 1)

        parts_layout.addWidget(self._parts_table_host)

        self._parts_placeholder = QtWidgets.QLabel(
            self.get_localized_string("parse_serial_to_show_parts")
        )
        self._parts_placeholder.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        parts_layout.addWidget(self._parts_placeholder)

        layout.addWidget(parts_frame, 2, 0, QtCore.Qt.AlignmentFlag.AlignTop)

        main_frame.setLayout(layout)

        # --- signal wiring ---
        self.serial_b85_entry.textChanged.connect(self.handle_b85_change)
        self.serial_decoded_entry.textChanged.connect(self.handle_decoded_change)
        self.serial_decoded_entry.textChanged.connect(self._update_weapon_stats)
        self.rarity_combo.currentIndexChanged.connect(self.update_decoded_from_ui)
        self.level_edit.textChanged.connect(self.update_decoded_from_ui)
        self.seed_entry.textChanged.connect(self.update_decoded_from_ui)
        self.random_seed_btn.clicked.connect(self.randomize_seed)
        self.update_weapon_btn.clicked.connect(self._update_weapon)
        self.add_to_backpack_btn.clicked.connect(self._add_to_backpack)
        self.generate_btn.clicked.connect(self._generate_new_weapon)
        self.clear_parts_btn.clicked.connect(self._clear_all_parts)
        self.manufacturer_combo.currentTextChanged.connect(self._on_type_or_mfg_changed)
        self.type_combo.currentTextChanged.connect(self._on_type_or_mfg_changed)

        return scroll_area

    def _make_skin_slot_row(self) -> QtWidgets.QWidget:
        """Slot-style skin row rendered through the same shape as an empty
        schema slot: disabled position controls + a badge + dropdown inner.
        Skin doesn't participate in reorderable state (it sits after
        ``||``), so the controls are always decorative."""
        inner = QtWidgets.QWidget()
        inner_layout = QtWidgets.QHBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(6)

        badge = QtWidgets.QLabel(self.get_localized_string("Skin"))
        badge.setObjectName("PartTypeBadge")
        color = self.PART_TYPE_COLORS.get("Skin", "#e0e0e0")
        badge.setStyleSheet(f"color: {color}; border-color: {color};")
        badge.setMinimumWidth(140)
        inner_layout.addWidget(badge)

        self.skin_combo = QtWidgets.QComboBox()
        self.skin_combo.addItem(self._loc('parts', 'no_skin', "(none)"), None)
        current_skin_id = self._current_skin_id()
        current_idx = 0
        for i, (_, srow) in enumerate(self.skin_df.iterrows(), start=1):
            sid = srow['Skin_ID']
            # Skin labels always come from the CSV in the current language
            # (skin.csv carries Stat + Stat_EN); TSV overrides are skipped
            # here so a user's zh-CN edits don't force-render into en-US
            # sessions and vice-versa.
            name = srow[self.skin_stat_col] if pd.notna(srow.get(self.skin_stat_col)) else srow.get('Stat', '')
            label = f"{sid}: {self.get_localized_string(str(name), str(name))}"
            self.skin_combo.addItem(label, sid)
            if current_skin_id is not None and str(sid) == str(current_skin_id):
                current_idx = i
        self.skin_combo.setCurrentIndex(current_idx)
        self.skin_combo.currentIndexChanged.connect(self._on_skin_selection_changed)
        inner_layout.addWidget(self.skin_combo, 1)

        return self._make_empty_slot_row(inner)

    def _current_skin_id(self):
        for part in self.parts_data:
            if isinstance(part, dict) and part.get('type') == 'skin':
                return part.get('id')
        return None

    def _on_skin_selection_changed(self, _idx):
        """Skin dropdown changed → update parts_data + state.tokens directly."""
        if self._is_loading:
            return
        new_id = self.skin_combo.currentData()
        # Existing skin slot in parts_data?
        skin_index = next(
            (i for i, p in enumerate(self.parts_data)
             if isinstance(p, dict) and p.get('type') == 'skin'),
            None,
        )
        if new_id is None:
            # Clear.
            if skin_index is not None:
                self._remove_skin_from_state(self.parts_data[skin_index])
                self.parts_data.pop(skin_index)
                # Drop the paired '|' string that _append_skin_to_state added
                # (or a source `'| '` variant) so parts_data and state stay
                # length-consistent across cycles.
                if (skin_index < len(self.parts_data)
                        and isinstance(self.parts_data[skin_index], str)
                        and self.parts_data[skin_index].strip() == '|'):
                    self.parts_data.pop(skin_index)
        elif skin_index is not None:
            # Swap id in place, both in parts_data and the state token.
            self._update_skin_in_state(self.parts_data[skin_index], new_id)
        else:
            # Insert fresh skin at end.
            self._append_skin_to_state(new_id)
        self.rebuild_output()

    @staticmethod
    def _normalize_skin_id(sid) -> tuple[object, str]:
        """Return ``(display_id, raw)`` for a skin id — a numeric id becomes
        an int and encodes bare (``"c", 12``), a path-form id stays a string
        and encodes quoted (``"c", "path"``)."""
        is_text_id = isinstance(sid, str) and not sid.isdigit()
        if is_text_id:
            return sid, f' "c", "{sid}"'
        as_int = int(sid)
        return as_int, f' "c", {as_int}'

    def _append_skin_to_state(self, sid):
        """Insert a fresh skin at the tail: the paired ``(quoted, '|')``
        tokens match the source format ``...part| "c", X|``. The trailing
        ``|`` is added regardless of what was there — the skinless format
        already ends with a single ``|``, and ``_remove_skin_from_state``
        pairs its removal so cycles don't accumulate delimiters.
        """
        skin_id, raw = self._normalize_skin_id(sid)
        skin_tok = Token(
            raw=raw, kind='quoted',
            value=skin_id if isinstance(skin_id, int) else None,
        )
        skin = {'type': 'skin', 'id': skin_id, 'raw': raw, '_tok': skin_tok}
        self.parts_data.append(skin)
        self.parts_data.append('|')
        self._token_state.insert(len(self._token_state.tokens), skin_tok)
        self._token_state.insert(len(self._token_state.tokens), Token(raw='|', kind='raw'))

    def _update_skin_in_state(self, skin_part, new_id):
        skin_id, raw = self._normalize_skin_id(new_id)
        state_idx = self._state_idx_of_part(skin_part)
        if state_idx is not None:
            tok = self._token_state.tokens[state_idx]
            tok.raw = raw
            tok.value = skin_id if isinstance(skin_id, int) else None
        skin_part['id'] = skin_id
        skin_part['raw'] = raw

    def _remove_skin_from_state(self, skin_part):
        """Drop the skin token AND its paired trailing ``|`` closer if we
        added one (the token immediately after is a ``'|'`` raw). The
        section-terminating ``|`` from the pre-skin state stays put. Pairing
        skin+closer prevents ``|`` accumulation across add/remove cycles.
        """
        state_idx = self._state_idx_of_part(skin_part)
        if state_idx is None:
            return
        tokens = self._token_state.tokens
        if (state_idx + 1 < len(tokens)
                and tokens[state_idx + 1].kind == 'raw'
                and tokens[state_idx + 1].raw == '|'):
            self._token_state.remove(state_idx + 1)
        self._token_state.remove(state_idx)

    # ---------- browser helpers ----------

    @classmethod
    def _is_weapon_item(cls, item):
        return item.get("type_en") in cls._WEAPON_TYPES and "Backpack" in (item.get("container") or "")

    def _derive_weapon_display(self, weapon):
        header, component = weapon.get('decoded_full', '').split('||', 1)
        m_id = int(header.strip().split('|')[0].strip().split(',')[0])
        parsed_components = parse_component_string_with_skin(component)
        _, name, _, _ = self._get_rarity_and_weapon_name(parsed_components, m_id, weapon.get('decoded_full', ''))
        w_name = self.get_localized_string(name, name)
        unknown = self._loc('parts', 'unknown', "Unknown")
        manufacturer = weapon.get('manufacturer') or unknown
        weapon_type = weapon.get('type') or self._loc('parts', 'unknown_item', "Unknown Item")
        unknown_names = {"N/A", "Unknown", "未知", "Неизвестно", "Невідомо", unknown}
        display_name = (
            f"{manufacturer} {weapon_type} ({w_name})"
            if w_name not in unknown_names else f"{manufacturer} {weapon_type}"
        )
        detail = (
            f"{self.get_localized_string('level_label')} {weapon.get('level', 'N/A')}"
            f"  ·  {self.get_localized_string('slot_label')} {weapon.get('slot', 'N/A').replace('slot_', '')}"
        )
        return display_name, detail

    def _weapon_browser_row(self, weapon):
        disp_name, detail = self._derive_weapon_display(weapon)
        row = QtWidgets.QWidget()
        row.setObjectName("ItemBrowserRow")
        row.setFixedHeight(ROW_HEIGHT)
        row_layout = QtWidgets.QVBoxLayout(row)
        row_layout.setContentsMargins(10, 7, 10, 7)
        row_layout.setSpacing(5)
        name_label = QtWidgets.QLabel(disp_name)
        name_label.setObjectName("ItemBrowserName")
        name_label.setToolTip(disp_name)
        name_label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.NoTextInteraction)
        detail_label = QtWidgets.QLabel(detail)
        detail_label.setObjectName("ItemBrowserMeta")
        detail_label.setToolTip(detail)
        row_layout.addWidget(name_label)
        row_layout.addWidget(detail_label)

        stats = self._resolve_stats(weapon.get('decoded_full', ''))
        stat_titles = self.ui_loc.get('stats', {})
        stats_layout = QtWidgets.QGridLayout()
        stats_layout.setContentsMargins(0, 2, 0, 0)
        stats_layout.setHorizontalSpacing(4)
        stats_layout.setVerticalSpacing(1)
        for column, key in enumerate(("damage", "accuracy", "fire_rate", "reload_time", "magazine")):
            title_label = QtWidgets.QLabel(stat_titles.get(key, key.replace('_', ' ').title()))
            title_label.setObjectName("ItemBrowserStatTitle")
            title_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            title_label.setWordWrap(True)
            value = item_display_resolver.format_weapon_stat(key, stats.get(key), self.current_lang) or "—"
            value_label = QtWidgets.QLabel(value)
            value_label.setObjectName("ItemBrowserStatValue")
            value_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            stats_layout.addWidget(title_label, 0, column)
            stats_layout.addWidget(value_label, 1, column)
            stats_layout.setColumnStretch(column, 1)
        row_layout.addLayout(stats_layout)
        return disp_name, detail, row

    def _summarize_weapon(self, weapon):
        return summarize_item(
            weapon,
            template=self._loc('summary', 'selected', "Selected · {name} · Lv.{level}"),
            none_text=self._loc('summary', 'none', "No weapon selected"),
            fallback_name=self._loc('summary', 'fallback_name', "Weapon"),
        )

    def refresh_backpack_items(self):
        self.browser.refresh()

    # ---------- localization helpers ----------

    def _loc(self, section, key, en, **fmt):
        text = self.ui_loc.get(section, {}).get(key) or en
        return text.format(**fmt) if fmt else text

    def get_localized_string(self, key, default=''):
        taxonomy_key = self.TAXONOMY_KEYS.get(str(key))
        if taxonomy_key:
            value = self.ui_loc.get('taxonomy', {}).get(taxonomy_key)
            if value:
                return value
        for section in ('labels', 'buttons', 'dialogs', 'misc'):
            value = self.ui_loc.get(section, {}).get(key)
            if value:
                return value
        return self.weapon_localization.get(key, default or key)

    def _character_level_int(self):
        try:
            return int(self._character_level)
        except (ValueError, TypeError):
            return 50

    def set_character_level(self, level):
        self._character_level = str(level) if level else "50"

    # ---------- serial change handlers ----------

    def handle_b85_change(self, text):
        if self._is_loading or not self.serial_b85_entry.hasFocus():
            return

        self._is_loading = True
        try:
            if not text:
                self.clear_all_fields()
                return
            decoded_str, _, err = decoder_logic.decode_serial_to_string(text)
            if not err:
                with block_signals(self.serial_decoded_entry):
                    self.serial_decoded_entry.setText(decoded_str)
                self.parse_and_display_weapon(decoded_str)
                self.serial_b85_entry.setReadOnly(True)
                self.update_weapon_btn.setEnabled(True)
            else:
                self.serial_decoded_entry.clear()
        finally:
            self._is_loading = False

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
        if not decoded_str:
            return
        new_b85, err = b_encoder.encode_to_base85(decoded_str)
        if not err:
            with block_signals(self.serial_b85_entry):
                self.serial_b85_entry.setText(new_b85)

    def _get_rarity_and_weapon_name(self, parts, m_id, decoded_str=""):
        rarity, weapon_name, rarity_part, display_rarity, remaining_parts = (
            "Unknown", "Unknown", None, "Unknown", list(parts),
        )
        for p in parts:
            if not isinstance(p, dict) or p.get('type') != 'simple':
                continue
            part_id = p.get('id')
            if not part_id:
                continue
            part_details = self.all_weapon_parts_df[
                (self.all_weapon_parts_df['Manufacturer & Weapon Type ID'] == m_id)
                & (self.all_weapon_parts_df['Part ID'] == part_id)
            ]
            if not part_details.empty and part_details.iloc[0]['Part Type'] == 'Barrel':
                part_name = item_display_resolver.weapon_part_name(m_id, part_id, self.current_lang, part_details.iloc[0])
                if part_name:
                    weapon_name = part_name
                    if weapon_name.endswith(' Barrel'):
                        weapon_name = weapon_name[:-len(' Barrel')]
                    break
        simple_parts = [p for p in parts if isinstance(p, dict) and p.get('type') == 'simple']
        if simple_parts and 'id' in simple_parts[0]:
            rarity_info = self.weapon_rarity_df[
                (self.weapon_rarity_df['Manufacturer & Weapon Type ID'] == m_id)
                & (self.weapon_rarity_df['Part ID'] == simple_parts[0]['id'])
            ]
            if not rarity_info.empty:
                details = rarity_info.iloc[0]
                rarity, desc = details['Stat'], details[self.rarity_desc_col]
                display_rarity = f"{rarity} - {desc}" if rarity in {"Legendary", "Pearl"} and pd.notna(desc) and desc else rarity
                rarity_part = simple_parts[0]
        if not rarity_part:
            display_rarity = rarity = "Legendary"
        pearl_ids = set(range(51, 61))
        if any(
            p.get('id') == 1 and (
                p.get('sub_id') in pearl_ids
                or bool(pearl_ids.intersection(p.get('sub_ids', [])))
            )
            for p in parts
            if isinstance(p, dict) and p.get('type') in {'elemental', 'group'}
        ):
            suffix = display_rarity.split(' - ', 1)[1] if ' - ' in display_rarity else ''
            rarity = "Pearl"
            display_rarity = f"Pearl - {suffix}" if suffix else "Pearl"
        if rarity_part:
            remaining_parts = [p for p in remaining_parts if p is not rarity_part]
        if decoded_str:
            m_rows = self.all_weapon_parts_df[self.all_weapon_parts_df['Manufacturer & Weapon Type ID'] == m_id]
            if not m_rows.empty:
                m_info = m_rows.iloc[0]
                display = item_display_resolver.resolve_item_display(
                    m_id,
                    str(m_info['Manufacturer']),
                    str(m_info['Weapon Type']),
                    decoded_str,
                    self.current_lang,
                )
                if display.get("display_source") != "fallback" and display.get("display_name"):
                    weapon_name = display["display_name"]
        return display_rarity, weapon_name, rarity_part, remaining_parts

    def clear_all_fields(self, clear_b85=True):
        self._is_loading = True
        try:
            if clear_b85:
                self.serial_b85_entry.clear()
            self.serial_decoded_entry.clear()
            self.rarity_combo.setCurrentIndex(-1)
            self.level_edit.clear()
            self.seed_entry.clear()
            self.weapon_name_label.setText(self.weapon_name_label_str)
            self._update_weapon_stats("")
            self._clear_parts_table()
            self._parts_placeholder.setText(self.get_localized_string("parse_serial_to_show_parts"))
            self._parts_placeholder.setVisible(True)
            self.serial_b85_entry.setReadOnly(False)
            self.update_weapon_btn.setEnabled(False)
            self.selected_item_path, self.parts_data, self.rarity_part = None, [], None
            self._token_state = TokenOrderedState([])
            self.browser.clear_selection()
        finally:
            self._is_loading = False

    def update_decoded_from_ui(self):
        """Push level / seed / rarity widget edits into state and re-render.

        Level + seed live in the header token; their per-render getter
        (bound via ``make_header_getter``) reads the widget values live, so
        we only need to trigger a rebuild. Rarity is a schema-outside
        typed token that binds to ``rarity_part['raw']`` — we mutate that
        dict in place (never a text-replace on the serial, which used to
        collide with any other part sharing the same pid).
        """
        if self._is_loading:
            return
        if not self.serial_decoded_entry.text():
            return
        try:
            if self.rarity_part and self.rarity_combo.isEnabled():
                rarity_map = {self.get_localized_string(k): k for k in ["Common", "Uncommon", "Rare", "Epic"]}
                rarity_en = rarity_map.get(self.rarity_combo.currentText())
                if rarity_en:
                    m_id = self._current_manufacturer_id()
                    if m_id is not None:
                        new_id = self._rarity_part_id(m_id, rarity_en)
                        if new_id is not None:
                            self.rarity_part['id'] = new_id
                            self.rarity_part['raw'] = f"{{{new_id}}}"
        except (ValueError, IndexError, KeyError) as e:
            log_editor(self.main_app, self._LOG_TAG, f"Error in update_decoded_from_ui: {e}")
            return
        # rebuild_output picks up: header (level/seed) via getter, rarity
        # via the mutated rarity_part['raw'] binding, everything else
        # unchanged. Also sets _encode_error + refreshes b85.
        self.rebuild_output()

    def randomize_seed(self):
        self.seed_entry.setText(str(random.randint(100, 9999)))

    # ---------- load / generate flows ----------

    def _load_weapon_item(self, weapon_data):
        if not weapon_data:
            return
        log_editor(self.main_app, self._LOG_TAG, f"Loading weapon: {weapon_data.get('name')}")
        self.selected_item_path = weapon_data.get("original_path")
        self.browser.set_selected_path(self.selected_item_path)

        raw_decoded = weapon_data.get('decoded_full', '')
        self._token_state = self.browser.token_state_for(weapon_data, skin=True)
        decoded_str = self.browser.render_from_state(
            self._token_state, expected_raw=raw_decoded,
        )

        self._is_loading = True
        try:
            self.serial_b85_entry.setText(weapon_data.get('serial', ''))
            self.serial_decoded_entry.setText(decoded_str)
        finally:
            self._is_loading = False
        if not decoded_str:
            QtWidgets.QMessageBox.critical(
                self, self.get_localized_string("error"),
                self.get_localized_string("no_valid_decoded_data"),
            )
            return

        # Edit mode: lock mfg + type combos so shape can't change mid-edit.
        self._is_fresh = False
        self.manufacturer_combo.setEnabled(False)
        self.type_combo.setEnabled(False)

        # Reuse the token_state already parsed above to avoid a double parse.
        self.parse_and_display_weapon(decoded_str, pre_parsed_state=self._token_state)
        self.serial_b85_entry.setReadOnly(True)
        self.update_weapon_btn.setEnabled(True)

    def _clear_all_parts(self):
        """Drop every filled slot → state.tokens and parts_data both shed
        the typed token. Rarity, skin, mfg/type, level, and seed are
        untouched. Rebuilds the parts table so combos re-read the now-empty
        _slot_parts.

        Just twiddling combos while _is_loading blocks the signal handler
        would leave state untouched — the handler is where state mutations
        happen. Instead we call _remove_slot_part directly on every filled
        slot (in reverse order so remaining slot indices stay valid).
        """
        if not self._slot_schema:
            return
        filled = [
            (i, part) for i, part in enumerate(self._slot_parts) if part is not None
        ]
        if not filled:
            return
        for slot_idx, part in reversed(filled):
            self._remove_slot_part(slot_idx, part)

    def _generate_new_weapon(self):
        """Fresh mode: clear state, unlock mfg + type combos, show empty table.
        User picks mfg + type → _on_type_or_mfg_changed populates the table.
        """
        self._is_loading = True
        try:
            self.selected_item_path = None
            self.parts_data = []
            self.rarity_part = None
            self._token_state = TokenOrderedState([])
            self._current_seed = str(random.randint(100, 9999))
            self.serial_b85_entry.clear()
            self.serial_decoded_entry.clear()
            self.serial_b85_entry.setReadOnly(False)
            self._clear_parts_table()
            self._parts_placeholder.setText(
                self._loc('labels', 'pick_type_mfg', "Pick manufacturer + type to build a weapon"),
            )
            self._parts_placeholder.setVisible(True)
            self.weapon_name_label.setText(self.weapon_name_label_str)
            self._update_weapon_stats("")
            self.level_edit.setText(str(self._character_level_int()))
            self.seed_entry.setText(self._current_seed)
            # Reset rarity_combo to Common — previous state could be
            # Legendary (editable line-edit locked to a unique name) if a
            # Legendary was loaded before Generate. Without this, the
            # combo displays stale text while state now carries Common,
            # and never emits currentIndexChanged so update_decoded_from_ui
            # never reconciles.
            with block_signals(self.rarity_combo):
                self.rarity_combo.setEditable(False)
                self.rarity_combo.setEnabled(True)
                self.rarity_combo.setCurrentIndex(0)
            self.browser.clear_selection()

            # Populate + unlock mfg/type combos.
            self._is_fresh = True
            self._populate_mfg_type_combos()
            self.manufacturer_combo.setEnabled(True)
            self.type_combo.setEnabled(True)
            self.update_weapon_btn.setEnabled(False)
            self.add_to_backpack_btn.setEnabled(True)
        finally:
            self._is_loading = False

        # Trigger initial population if both combos have selections.
        self._on_type_or_mfg_changed()

    def _populate_mfg_type_combos(self):
        """Fill manufacturer + type combos with localized names. Called only
        when entering fresh mode."""
        mfgs = sorted({str(m) for m in self.all_weapon_parts_df['Manufacturer'].dropna().unique()})
        types = sorted({str(t) for t in self.all_weapon_parts_df['Weapon Type'].dropna().unique()})
        with block_signals(self.manufacturer_combo, self.type_combo):
            self.manufacturer_combo.clear()
            self.type_combo.clear()
            for m in mfgs:
                self.manufacturer_combo.addItem(self.get_localized_string(m), m)
            for t in types:
                self.type_combo.addItem(self.get_localized_string(t), t)

    def _rarity_part_id(self, m_id: int, rarity_en: str) -> int | None:
        """Look up the Part ID that encodes ``rarity_en`` (e.g. 'Common',
        'Uncommon', 'Legendary') for the given mfg. Returns None if the
        CSV has no matching row.
        """
        if self.weapon_rarity_df is None:
            return None
        rows = self.weapon_rarity_df[
            (self.weapon_rarity_df['Manufacturer & Weapon Type ID'] == m_id)
            & (self.weapon_rarity_df['Stat'] == rarity_en)
            & (self.weapon_rarity_df['Part Type'] == 'Rarity')
        ]
        if rows.empty:
            return None
        try:
            return int(rows.iloc[0]['Part ID'])
        except (ValueError, TypeError):
            return None

    def _seed_default_rarity(self, m_id: int) -> None:
        """Insert a Common rarity token into the fresh-mode state so the
        stats resolver has enough context to compute values. Runs during
        ``_on_type_or_mfg_changed`` right after the header + closer are
        seeded — assumes state is ``[header, '|']``.

        Falls back to the first available rarity for this mfg when Common
        isn't in the CSV, so fresh-mode weapons always end up with a
        ``rarity_part`` (otherwise ``update_decoded_from_ui`` silently
        drops every rarity_combo change — see prior audit).
        """
        rarity_id = self._rarity_part_id(m_id, 'Common')
        if rarity_id is None and self.weapon_rarity_df is not None:
            fallback = self.weapon_rarity_df[
                (self.weapon_rarity_df['Manufacturer & Weapon Type ID'] == m_id)
                & (self.weapon_rarity_df['Part Type'] == 'Rarity')
            ]
            if not fallback.empty:
                try:
                    rarity_id = int(fallback.iloc[0]['Part ID'])
                except (ValueError, TypeError):
                    rarity_id = None
        if rarity_id is None:
            log_editor(
                self.main_app, self._LOG_TAG,
                f"_seed_default_rarity: no Rarity row in CSV for mfg {m_id}; "
                f"fresh mode will lack a rarity_part (rarity_combo edits will no-op).",
            )
            return
        raw = f"{{{rarity_id}}}"
        rarity_tok = Token(raw=raw, kind='simple', value=rarity_id)
        self.rarity_part = {
            'type': 'simple', 'id': rarity_id, 'raw': raw, '_tok': rarity_tok,
        }
        # Insert (rarity, ' ') at index 1 — right after the header, before
        # the trailing ``|`` closer.
        self._token_state.insert(1, rarity_tok)
        self._token_state.insert(2, Token(raw=' ', kind='raw'))

    def _on_type_or_mfg_changed(self, *args):
        """Fresh mode: mfg or type combo changed → rebuild parts table for
        this shape. Edit mode: combos are locked so this is a no-op.

        The fresh state carries NO placeholder part tokens — just header and
        the trailing ``|`` closer. Each dropdown starts blank; when the user
        picks a value, ``_on_slot_selection_changed`` inserts a fresh token
        at the schema-ordered position ("empty rows emit no tokens").
        """
        if not self._is_fresh or self._is_loading:
            return
        mfg_en = self.manufacturer_combo.currentData()
        type_en = self.type_combo.currentData()
        if not mfg_en or not type_en:
            return
        try:
            m_id = int(self.all_weapon_parts_df.loc[
                (self.all_weapon_parts_df['Manufacturer'] == mfg_en)
                & (self.all_weapon_parts_df['Weapon Type'] == type_en),
                'Manufacturer & Weapon Type ID'
            ].iloc[0])
        except (IndexError, ValueError):
            return

        level = self.level_edit.text() or str(self._character_level_int())
        seed = self.seed_entry.text() or self._current_seed
        header_raw = f"{m_id}, 0, 1, {level}| 2, {seed}|| "

        # Fresh state: header + trailing ``|`` closer. No slot tokens — those
        # are inserted on demand as the user picks values in the schema rows.
        # We DO seed a rarity token though — the stats resolver needs one to
        # compute anything, and fresh-mode weapons would otherwise show all
        # dashes until the user opens the rarity combo.
        self.parts_data = []
        self.rarity_part = None
        self._token_state = TokenOrderedState([
            Token(raw=header_raw, kind='raw'),
            Token(raw='|', kind='raw'),
        ])
        self._seed_default_rarity(m_id)
        self._bind_token_state_widgets()
        # Render the serial BEFORE rebuilding the parts table so
        # _disambiguate_labels / _key_part_ref can parse the fresh mfg from
        # serial_decoded_entry.text() during the table build. Otherwise the
        # first fresh-mode paint renders un-disambiguated labels.
        self.rebuild_output()
        self._rebuild_parts_table(m_id)

    # ---------- token binding / rebuild ----------

    def _bind_token_state_widgets(self):
        """Bind each typed state token to its parts_data dict by identity.

        Uses the ``_tok`` back-ref attached during parse (see
        ``_pair_parts_with_tokens``). Walking state.tokens in state order is
        essential — a positional pairing (rarity first, then parts_data in
        order) would silently mis-bind whenever a typed token precedes
        rarity in the source (e.g. an elemental ``{1:X}`` before the rarity
        token). Missing back-refs are logged; a well-formed load pairs
        everything.
        """
        if not self._token_state.tokens:
            return
        self._token_state.clear_bindings()
        self._token_state.bind(0, make_header_getter(
            self._token_state.tokens[0].raw,
            level_getter=lambda: self.level_edit.text(),
            seed_getter=lambda: self.seed_entry.text(),
        ))
        all_dicts = ([self.rarity_part] if self.rarity_part else []) + [
            p for p in self.parts_data if isinstance(p, dict)
        ]
        by_tok = {id(d['_tok']): d for d in all_dicts if d.get('_tok') is not None}
        for idx, tok in enumerate(self._token_state.tokens):
            if tok.kind == 'raw':
                continue
            part = by_tok.get(id(tok))
            if part is None:
                log_editor(
                    self.main_app, self._LOG_TAG,
                    f"_bind_token_state_widgets: no _tok back-ref matches state "
                    f"token idx={idx} kind={tok.kind} raw={tok.raw!r}",
                )
                continue
            self._token_state.bind(idx, lambda p=part: p.get('raw'))

    def parse_and_display_weapon(self, decoded_str, pre_parsed_state=None):
        """Populate widgets from a decoded serial.

        ``pre_parsed_state`` lets callers that already parsed the tokens
        (e.g. ``_load_weapon_item``) reuse them here — avoids a redundant
        second parse of the same text. When None, we parse fresh.
        """
        self._is_loading = True
        try:
            header_part, component_part = decoded_str.split('||', 1)
            sections = header_part.strip().split('|')
            header_fields = sections[0].strip().split(',')
            m_id = int(header_fields[0])
            level_src = header_fields[3].strip() if len(header_fields) > 3 else ''
            m_info = self.all_weapon_parts_df[
                self.all_weapon_parts_df['Manufacturer & Weapon Type ID'] == m_id
            ].iloc[0]

            # Populate mfg/type combos so the user sees the current shape.
            # In edit mode they're disabled, but we still want to display.
            if self.manufacturer_combo.count() == 0:
                self._populate_mfg_type_combos()
            mfg_local = self.get_localized_string(m_info['Manufacturer'])
            type_local = self.get_localized_string(m_info['Weapon Type'])
            mfg_idx = self.manufacturer_combo.findText(mfg_local)
            type_idx = self.type_combo.findText(type_local)
            with block_signals(self.manufacturer_combo, self.type_combo):
                if mfg_idx >= 0:
                    self.manufacturer_combo.setCurrentIndex(mfg_idx)
                if type_idx >= 0:
                    self.type_combo.setCurrentIndex(type_idx)

            # Use the raw source string, not str(int(...)), so a level like
            # "050" round-trips as "050" through the header getter.
            self.level_edit.setText(level_src)
            self.seed_entry.setText(
                sections[1].strip().split(',')[1].strip()
                if len(sections) > 1 and len(sections[1].strip().split(',')) > 1 else "",
            )

            temp_parts = parse_component_string_with_skin(component_part)
            # Pair each typed dict with its state Token BEFORE rarity gets
            # stripped out; downstream lookups need the ``_tok`` back-ref on
            # every dict (including rarity_part).
            token_state_for_pairing = pre_parsed_state or self.browser.token_state_for(
                {'decoded_full': decoded_str}, skin=True,
            )
            self._pair_parts_with_tokens(temp_parts, token_state_for_pairing.tokens)
            display_rarity, weapon_name, self.rarity_part, remaining_parts = (
                self._get_rarity_and_weapon_name(temp_parts, m_id, decoded_str)
            )

            rarity_parts = display_rarity.split(' - ')
            base_rarity, localized_base = rarity_parts[0], self.get_localized_string(rarity_parts[0])
            final_display_rarity = (
                f"{localized_base} - {self.get_localized_string(rarity_parts[1], rarity_parts[1])}"
                if len(rarity_parts) > 1 else localized_base
            )

            if base_rarity in {"Legendary", "Pearl"}:
                self.rarity_combo.setEditable(True)
                self.rarity_combo.lineEdit().setText(final_display_rarity)
                self.rarity_combo.setEnabled(False)
            else:
                self.rarity_combo.setEditable(False)
                self.rarity_combo.setEnabled(True)
                if (index := self.rarity_combo.findText(localized_base)) != -1:
                    self.rarity_combo.setCurrentIndex(index)

            self.weapon_name_label.setText(f"{self.weapon_name_label_str} {weapon_name}")
            self._update_weapon_stats(decoded_str)
            self.parts_data = remaining_parts

            # State was already parsed above (for _tok pairing); reuse it.
            self._token_state = token_state_for_pairing
            self._bind_token_state_widgets()
            self._rebuild_parts_table(m_id)
        except (ValueError, IndexError, KeyError) as e:
            QtWidgets.QMessageBox.critical(
                self, self.get_localized_string("parse_error"),
                f"{self.get_localized_string('parse_weapon_error')}: {e}",
            )
            log_editor(self.main_app, self._LOG_TAG, f"Error parsing weapon: {e}")
            self.clear_all_fields()
        finally:
            self._is_loading = False

    def _update_weapon_stats(self, decoded_str):
        if not hasattr(self, 'weapon_stat_value_labels'):
            return
        stats = self._resolve_stats(decoded_str)
        for key, label in self.weapon_stat_value_labels.items():
            label.setText(item_display_resolver.format_weapon_stat(key, stats.get(key), self.current_lang) or "—")

    def _resolve_stats(self, decoded_str: str) -> dict:
        """Resolve weapon stats with a fallback path for weapons that carry
        no explicit rarity token (game-generated Legendaries — Bonnie and
        Clyde etc.). The base resolver requires one; on an empty result
        AND only when the components section has no leading ``{N}`` typed
        token, we retry with a Common rarity spliced in. Guarding on the
        leading-token check prevents double-inject on weapons whose empty
        result stems from something other than missing rarity — otherwise
        the display would fabricate Common stats for a Legendary weapon
        that failed to resolve for an unrelated reason.
        """
        if not decoded_str:
            return {}
        stats = item_display_resolver.resolve_weapon_stats(decoded_str) or {}
        if stats:
            return stats
        # Guard against double-inject: only splice when the components
        # section's leading typed token is NOT already a rarity for this
        # mfg. Otherwise a resolver failure for an unrelated reason would
        # cause us to fabricate Common stats for what's actually a
        # different rarity weapon. Bonnie & Clyde-style Legendaries lack
        # any rarity token → safe to splice.
        try:
            components = decoded_str.split('||', 1)[1].lstrip()
            m_id = int(decoded_str.split('||', 1)[0].strip().split('|')[0].split(',')[0])
        except (ValueError, IndexError):
            return {}
        lead = _HAS_LEADING_SIMPLE_TOKEN.match(components)
        if lead and self.weapon_rarity_df is not None:
            try:
                first_pid = int(lead.group().strip('{}'))
            except ValueError:
                first_pid = None
            if first_pid is not None:
                rarity_rows = self.weapon_rarity_df[
                    (self.weapon_rarity_df['Manufacturer & Weapon Type ID'] == m_id)
                    & (self.weapon_rarity_df['Part Type'] == 'Rarity')
                    & (self.weapon_rarity_df['Part ID'] == first_pid)
                ]
                if not rarity_rows.empty:
                    return {}
        rid = self._rarity_part_id(m_id, 'Common')
        if rid is None:
            return {}
        injected = decoded_str.replace('||', f'|| {{{rid}}}', 1)
        return item_display_resolver.resolve_weapon_stats(injected) or {}

    # ---------- parts table (position-controls) ----------

    def _clear_parts_table(self):
        """Remove every row widget from BOTH column layouts of the parts table."""
        for column_layout in (self._parts_table_left_layout,
                              self._parts_table_right_layout):
            while column_layout.count():
                item = column_layout.takeAt(0)
                widget = item.widget()
                if widget:
                    widget.setParent(None)
                    widget.deleteLater()
        self._positional_rows = []
        self._slot_row_widgets = []

    # ---------- schema logic ----------

    def _load_label_overrides(self) -> None:
        """Read ``weapon_edit/part_labels.tsv`` into a lookup dict of
        user-curated labels for the ``weapon`` (Part Type) options.

        Element and Skin labels come straight from their CSVs in the
        current language and are NOT overridable via TSV — a single-file
        snapshot in one language would force-render into every session
        regardless of runtime language, which is the wrong ergonomic.
        Weapon-part labels are the abbreviation-oriented ones users
        actually want to hand-curate for space.
        """
        self._label_overrides: dict[tuple, str] = {}
        path = resource_loader.get_weapon_data_path('part_labels.tsv')
        if not path or not path.exists():
            return
        try:
            with open(path, encoding='utf-8') as f:
                for line in f:
                    raw = line.rstrip('\n')
                    if not raw or raw.startswith('#') or raw.startswith('['):
                        continue
                    cols = raw.split('\t')
                    if len(cols) < 5:
                        continue
                    section, mfg_s, pid_s, part_type, label = cols[:5]
                    if section != 'weapon' or not label:
                        continue
                    try:
                        key = ('weapon', int(mfg_s), int(pid_s), part_type)
                    except ValueError:
                        continue
                    self._label_overrides[key] = label
        except OSError as e:
            log_editor(self.main_app, self._LOG_TAG,
                       f"_load_label_overrides: could not read {path}: {e}")

    def _lookup_label(self, key: tuple) -> str | None:
        """Return the TSV override for a key, or None if none."""
        return self._label_overrides.get(key) if hasattr(self, '_label_overrides') else None

    def _compute_slot_schema(self) -> list[dict]:
        """Return the STATIC slot schema.

        Every Part Type in ``SLOT_LAYOUT_ORDER`` renders every time — the
        schema is shape-independent. Multi-select accessories expand to
        ``multi_total`` entries (capped at ``MAX_SUBPART_COUNT``). Slots
        the current weapon shape can't populate just show an empty
        dropdown.
        """
        schema: list[dict] = []
        for part_type in self.SLOT_LAYOUT_ORDER:
            total = min(self.MULTI_SELECT_SLOTS.get(part_type, 1), self.MAX_SUBPART_COUNT)
            for i in range(total):
                schema.append({'part_type': part_type, 'slot_index': i, 'multi_total': total})
        return schema

    def _lookup_part_type(self, part: dict, manufacturer_id: int) -> str | None:
        """Return the Part Type for a loaded part dict, or None if not
        determinable. Used for schema-slot assignment during parse."""
        if not isinstance(part, dict):
            return None
        t = part.get('type')
        # Element-family tokens use parent id 1 — cover single-form
        # ({1:X}, kind='elemental') AND list-form ({1:[X …]}, kind='group')
        # so Pearl-style multi-child elementals aren't orphaned into raw.
        if int(part.get('id') or 0) == self._ELEMENT_PARENT_ID and t in ('elemental', 'group'):
            return "Element"
        if t == 'simple':
            pid = part.get('id')
            if pid is None or self.all_weapon_parts_df is None:
                return None
            rows = self.all_weapon_parts_df[
                (self.all_weapon_parts_df['Manufacturer & Weapon Type ID'] == manufacturer_id)
                & (self.all_weapon_parts_df['Part ID'] == pid)
            ]
            if not rows.empty:
                return str(rows.iloc[0]['Part Type'])
        elif t == 'group':
            # Cross-mfg single-part reference: ``{other_mfg:[part_id]}``.
            sub_ids = part.get('sub_ids', [])
            if len(sub_ids) == 1:
                other_mfg = part.get('id')
                child = sub_ids[0]
                if other_mfg is not None and self.all_weapon_parts_df is not None:
                    rows = self.all_weapon_parts_df[
                        (self.all_weapon_parts_df['Manufacturer & Weapon Type ID'] == other_mfg)
                        & (self.all_weapon_parts_df['Part ID'] == child)
                    ]
                    if not rows.empty:
                        return str(rows.iloc[0]['Part Type'])
        return None

    def _assign_parts_to_slots(self, manufacturer_id: int, schema: list[dict]) -> list[dict | None]:
        """Assign each schema-eligible part from parts_data to a schema slot.

        Walks parts_data in order; for each dict with a determinable Part
        Type that matches a schema slot type, assigns it to the next free
        slot of that type. Anything that doesn't fit (elemental, group
        multi-child, unknown Part Type, overflow past ``multi_total``) is
        left in parts_data unbound to any slot — its binding still preserves
        its raw form so byte-identical round-trip holds.

        Returns a list parallel to ``schema``; each entry is a part dict or
        None (empty slot).
        """
        slot_parts: list[dict | None] = [None] * len(schema)
        # For each part_type: queue of schema indices still open.
        open_by_type: dict[str, list[int]] = {}
        for i, s in enumerate(schema):
            open_by_type.setdefault(s['part_type'], []).append(i)
        for part in self.parts_data:
            if not isinstance(part, dict):
                continue
            if part.get('type') == 'skin':
                continue
            pt = self._lookup_part_type(part, manufacturer_id)
            if pt is None:
                continue
            queue = open_by_type.get(pt)
            if not queue:
                continue
            slot_idx = queue.pop(0)
            slot_parts[slot_idx] = part
        return slot_parts

    # Sub Part Types → their primary. Used to build slot-groups so a
    # primary and its accessory rows always land in the same column.
    _SUB_OF_PRIMARY = {
        "Body Accessory": "Body",
        "Barrel Accessory": "Barrel",
        "Magazine Accessory": "Magazine",
        "Scope Accessory": "Scope",
        "Underbarrel Accessory": "Underbarrel",
    }

    # Hard-locked column assignment. No greedy balancing — every primary
    # (and its accessories) renders in the listed column, in this order.
    # A primary not in either tuple defaults to the right column so nothing
    # silently disappears if SLOT_LAYOUT_ORDER gains a new type. Skin
    # renders at the very BOTTOM of the right column (see
    # ``_make_skin_slot_row`` and its append in ``_rebuild_parts_table``).
    _LEFT_COLUMN_PRIMARIES = (
        "Element",           # ×2 — sourced from elemental.csv, TOP of column
        "Body",              # + Body Accessory ×4
        "Magazine",          # + Magazine Accessory ×1
        "Foregrip",
        "Grip",
        "Manufacturer Part", # ×4
        "Special Element Set",
        # Skin appended after these in _rebuild_parts_table (bottom of left).
    )
    _RIGHT_COLUMN_PRIMARIES = (
        "Barrel",            # + Barrel Accessory ×4
        "Underbarrel",       # + Underbarrel Accessory ×3
        "Scope",             # + Scope Accessory ×4
        "Tediore Payload",
        "Tediore Throw Reload",
        "Borg Magazine Adapter",
    )

    def _build_slot_groups(self) -> list[list[int]]:
        """Group the flat ``_slot_schema`` into slot-groups (primary + subs).

        Iteration order follows ``SLOT_LAYOUT_ORDER``. Sub part types listed
        in ``_SUB_OF_PRIMARY`` are NOT emitted as separate groups — they
        attach to their primary. Every other part_type present in the
        schema is its own single-primary group (Manufacturer Part × 4 →
        one 4-row group).

        Returns: list of groups; each group is a list of schema indices.
        """
        by_type: dict[str, list[int]] = {}
        for idx, slot in enumerate(self._slot_schema):
            by_type.setdefault(slot['part_type'], []).append(idx)

        seen: set[str] = set()
        groups: list[list[int]] = []
        for part_type in self.SLOT_LAYOUT_ORDER:
            if part_type in seen or part_type in self._SUB_OF_PRIMARY:
                continue
            if part_type not in by_type:
                continue
            group = list(by_type[part_type])
            seen.add(part_type)
            # Attach any subs whose primary is this part_type.
            for sub_type, pri in self._SUB_OF_PRIMARY.items():
                if pri == part_type and sub_type in by_type:
                    group.extend(by_type[sub_type])
                    seen.add(sub_type)
            groups.append(group)
        # Trailing catch-all: any schema type not yet placed becomes its own
        # single group (defensive — keeps rows visible if SLOT_LAYOUT_ORDER
        # drifts out of sync with _compute_slot_schema's ``available`` set).
        for part_type, indices in by_type.items():
            if part_type not in seen:
                groups.append(list(indices))
                seen.add(part_type)
        return groups

    def _rebuild_parts_table(self, manufacturer_id):
        """Schema-driven, TWO-COLUMN table build.

        Every entry in ``SLOT_LAYOUT_ORDER`` renders as one row with a
        per-slot part dropdown. Filled rows get a ``PositionalTokenRow``
        with real ``[↑][#][↓]`` swap controls; empty rows show a blank
        dropdown with disabled controls (no token to move). Empty rows
        emit no state tokens.

        Rows are grouped into slot-groups (a primary and its sub accessory
        rows). Column placement is hard-locked via
        ``_LEFT_COLUMN_PRIMARIES`` / ``_RIGHT_COLUMN_PRIMARIES``; a group
        is never split across columns.
        """
        self._clear_parts_table()
        self._slot_schema = self._compute_slot_schema()
        if not self._slot_schema:
            self._slot_parts = []
            self._parts_placeholder.setText(self.get_localized_string("parts_not_found"))
            self._parts_placeholder.setVisible(True)
            return
        self._slot_parts = self._assign_parts_to_slots(manufacturer_id, self._slot_schema)
        self._parts_placeholder.setVisible(False)

        # Pre-build every row (in schema order) so _slot_row_widgets stays
        # parallel to _slot_schema — downstream (_on_slot_selection_changed,
        # etc.) never needs to know about columns.
        self._slot_row_widgets = [None] * len(self._slot_schema)
        for slot_idx, slot in enumerate(self._slot_schema):
            part = self._slot_parts[slot_idx]
            row_widget = self._build_slot_row(slot_idx, slot, part, manufacturer_id)
            self._slot_row_widgets[slot_idx] = row_widget
            if isinstance(row_widget, PositionalTokenRow):
                self._positional_rows.append(row_widget)

        # Hard-locked columns. Each primary in
        # ``_LEFT_COLUMN_PRIMARIES`` / ``_RIGHT_COLUMN_PRIMARIES`` renders
        # its slot-group (primary + subs) in that column in exactly the
        # listed order. Primaries not in either tuple default to the right
        # column so nothing silently disappears if SLOT_LAYOUT_ORDER adds a
        # new type. No greedy balancing — layout stays predictable across
        # weapon shapes.
        groups_by_primary = {
            self._slot_schema[g[0]]['part_type']: g
            for g in self._build_slot_groups()
        }

        def _emit(primary_type: str, target_layout):
            group = groups_by_primary.pop(primary_type, None)
            if not group:
                return
            for schema_idx in group:
                target_layout.addWidget(self._slot_row_widgets[schema_idx])

        for primary in self._LEFT_COLUMN_PRIMARIES:
            _emit(primary, self._parts_table_left_layout)
        for primary in self._RIGHT_COLUMN_PRIMARIES:
            _emit(primary, self._parts_table_right_layout)
        # Anything schema-present but unassigned → right column (defensive).
        for primary in list(groups_by_primary.keys()):
            _emit(primary, self._parts_table_right_layout)

        # Skin at the very bottom of the left column — fixed slot
        # (post-``||``, not state-reorderable) with the same badge +
        # dropdown shape as every other slot.
        skin_row = self._make_skin_slot_row()
        self._parts_table_left_layout.addWidget(skin_row)

    def _build_slot_row(self, slot_idx: int, slot: dict, part: dict | None,
                        manufacturer_id: int) -> QtWidgets.QWidget:
        """Build one row for the parts table.

        Filled slot (``part is not None``) → ``PositionalTokenRow`` with
        the up/#/down controls wired to ``state.swap``. Empty slot → a
        plain HBox whose placeholder position controls are visually present
        (for layout consistency) but disabled.
        """
        inner = self._make_slot_inner(slot_idx, slot, part, manufacturer_id)
        if part is not None:
            token_idx = self._state_idx_of_part(part)
            if token_idx is not None:
                row = PositionalTokenRow(self._token_state, token_idx, inner)
                row.token_moved.connect(self._on_token_moved)
                return row
        # Empty slot (or filled but couldn't resolve state index — fall back
        # to a placeholder row so the schema stays visible and the dropdown is
        # usable).
        return self._make_empty_slot_row(inner)

    def _make_disabled_position_controls(self) -> QtWidgets.QWidget:
        """Build the ``[↑][—][↓]`` disabled triple used by empty schema rows
        and the skin row — matches ``PositionalTokenRow`` visual layout so
        the control column aligns across the whole table."""
        holder = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        for arrow in (QtWidgets.QStyle.StandardPixmap.SP_ArrowUp,
                      None,
                      QtWidgets.QStyle.StandardPixmap.SP_ArrowDown):
            if arrow is None:
                lbl = QtWidgets.QLabel("—")
                lbl.setObjectName("PartIdBadge")
                lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                lbl.setMinimumWidth(28)
                layout.addWidget(lbl)
            else:
                btn = QtWidgets.QPushButton()
                btn.setObjectName("PartActionButton")
                btn.setIcon(self.style().standardIcon(arrow))
                btn.setFixedSize(28, 28)
                btn.setEnabled(False)
                layout.addWidget(btn)
        return holder

    def _make_empty_slot_row(self, inner: QtWidgets.QWidget) -> QtWidgets.QWidget:
        """Row for an empty schema slot — disabled position controls +
        inner content (label + dropdown)."""
        w = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        layout.addWidget(self._make_disabled_position_controls())
        layout.addWidget(inner, 1)
        return w

    def _make_slot_inner(self, slot_idx: int, slot: dict, part: dict | None,
                         manufacturer_id: int) -> QtWidgets.QWidget:
        """Inner widget for a slot row: [label] [dropdown]."""
        w = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        raw_type = slot['part_type']
        badge_text = self.get_localized_string(raw_type) or raw_type
        if slot.get('multi_total', 1) > 1:
            badge_text = f"{badge_text} #{slot['slot_index'] + 1}"
        type_label = QtWidgets.QLabel(badge_text)
        type_label.setObjectName("PartTypeBadge")
        color = self.PART_TYPE_COLORS.get(raw_type, "#e0e0e0")
        type_label.setStyleSheet(f"color: {color}; border-color: {color};")
        type_label.setMinimumWidth(140)
        layout.addWidget(type_label)

        combo = QtWidgets.QComboBox()
        combo.addItem(self._loc('parts', 'none', "(none)"), None)
        options = self._disambiguate_labels(self._slot_options(raw_type, manufacturer_id))
        current_key = self._current_option_key(part) if part is not None else None
        # If the loaded key is filtered out of options (e.g. Pearl list-form
        # element with no matching single-form option), append a synthetic
        # entry so the combo displays the truth instead of falling back to
        # "(none)" in a slot that's actually filled.
        if (current_key is not None
                and not self._is_separator(current_key)
                and not any(k == current_key for k, _ in options)):
            options = list(options) + [(current_key, self._orphan_label(part, current_key))]
        current_idx = 0
        for i, (key, label) in enumerate(options, start=1):
            combo.addItem(label, key)
            # Separator sentinels render as disabled section-divider rows
            # (unselectable, greyed). Data holds the key tuple as usual but
            # the selection handler ignores separators via _is_separator.
            if self._is_separator(key):
                model = combo.model()
                item = model.item(i) if hasattr(model, 'item') else None
                if item is not None:
                    item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsSelectable
                                  & ~QtCore.Qt.ItemFlag.ItemIsEnabled)
            elif key == current_key:
                current_idx = i
        combo.setCurrentIndex(current_idx)

        # Type-to-filter: editable combo + case-insensitive contains-match
        # completer. NoInsert prevents the user from typing free text — the
        # completer only picks from the model. Standard Qt pattern for large
        # combos.
        if combo.count() > 20:
            combo.setEditable(True)
            combo.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
            completer = combo.completer()
            if completer is not None:
                completer.setCompletionMode(
                    QtWidgets.QCompleter.CompletionMode.PopupCompletion,
                )
                completer.setFilterMode(QtCore.Qt.MatchFlag.MatchContains)
                completer.setCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)

        combo.currentIndexChanged.connect(
            partial(self._on_slot_selection_changed, slot_idx, combo)
        )
        layout.addWidget(combo, 1)
        return w

    _LABEL_ABBREVIATIONS = (
        ("Magazine Capacity", "Mag"),
        ("Reload Time", "Reload"),
        ("Charge Time", "Charge"),
        ("Critical Damage", "Crit Dmg"),
        ("Splash Damage", "Splash Dmg"),
        ("Elemental Damage", "Elem Dmg"),
        ("Melee Damage", "Melee Dmg"),
        ("Thrown Damage", "Thrown Dmg"),
        ("Sticky Damage", "Sticky Dmg"),
        ("Splash Radius", "Splash Rad"),
        ("Fire Rate", "FR"),
        ("Accuracy", "Acc"),
        ("Damage", "Dmg"),
    )

    def _abbrev_label(self, label: str) -> str:
        for full, short in self._LABEL_ABBREVIATIONS:
            label = label.replace(full, short)
        return label

    def _orphan_label(self, part: dict, key: tuple) -> str:
        """Label for a loaded part whose option key isn't offered by the
        dropdown (Pearl list-form element, or a (mfg_id, pid) combo the
        CSV doesn't expose for this Part Type). Falls back to the raw
        serial fragment prefixed with ``!`` so the user sees the actual
        token in the slot instead of ``(none)``."""
        raw = str(part.get('raw') or f"{key}")
        return f"! {raw}"

    def _key_part_ref(self, key: tuple):
        """Return the item-index part_refs entry for a dropdown option key,
        or None if the key doesn't map to one. Only ``('simple', pid)`` and
        ``('list', mfg, pid)`` reference the weapon-part CSV; ``('elemental',
        pid)`` sources from elemental.csv (no part_refs entry); separator
        sentinels have no ref.
        """
        if self._is_separator(key):
            return None
        prefs = (item_display_resolver._item_index().get('part_refs') or {})
        if key[0] == 'simple':
            # Same-mfg options are keyed against the current manufacturer.
            m_id = self._current_manufacturer_id()
            if m_id is None:
                return None
            return prefs.get(f"{m_id}:{key[1]}")
        if key[0] == 'list':
            _, other_mfg, pid = key
            return prefs.get(f"{other_mfg}:{pid}")
        return None

    _DISAMBIGUATION_TAGS = (
        'mag_01', 'mag_02', 'mag_03', 'mag_04',
        'tor_mag', 'cov_mag', 'borg_mag',
        'ted_mag', 'hyp_mag', 'val_mag', 'mal_mag',
        'licensed_tor', 'licensed_cov', 'licensed_borg',
        'licensed_hyp', 'licensed_val', 'licensed_mal',
    )

    # Section-divider sentinel used by ``_slot_options`` to inject visually
    # disabled separator rows between same-mfg / cross-mfg buckets.
    _SEPARATOR_KEY = (None, '_sep')

    @classmethod
    def _is_separator(cls, key) -> bool:
        """True iff ``key`` is the section-divider sentinel."""
        return key == cls._SEPARATOR_KEY

    def _disambiguate_labels(self, options: list[tuple[tuple, str]]) -> list[tuple[tuple, str]]:
        """When multiple options share the same descriptive text (part_id
        prefix stripped), append a differentiating tag pulled from the CSV's
        ``weapon_tags``. Tediore Throw Reload rows all say "Thrown Reload 2s,
        Reload Complete 75%" because that IS their shared behavior — the
        actual difference is which magazine subtype they pair with. This
        surfaces that so the user can tell them apart. Separator entries
        are skipped.
        """
        # Bucket by description (everything after "<pid> - ").
        def _desc(label: str) -> str:
            return label.split(' - ', 1)[1] if ' - ' in label else label
        buckets: dict[str, list[int]] = {}
        for i, (key, label) in enumerate(options):
            if self._is_separator(key):
                continue
            buckets.setdefault(_desc(label), []).append(i)
        out = list(options)
        for desc, indices in buckets.items():
            if len(indices) < 2:
                continue
            for i in indices:
                key, label = out[i]
                ref = self._key_part_ref(key) or {}
                tags = {str(t).lower() for t in (ref.get('weapon_tags') or [])}
                hint = next((t for t in self._DISAMBIGUATION_TAGS if t in tags), None)
                if hint:
                    out[i] = (key, f"{label} [{hint}]")
        return out

    def _slot_options(self, part_type: str, manufacturer_id: int):
        """Return [(key, label), ...] for the dropdown of a schema slot.

        Layout:
          - Same-mfg parts of this Part Type → key ``('simple', part_id)``.
          - ``_SEPARATOR_KEY`` divider (rendered as a disabled row).
          - Cross-mfg parts of THIS weapon type → key
            ``('list', other_mfg_id, part_id)``.
          - ``_SEPARATOR_KEY`` divider.
          - Cross-mfg parts of OTHER weapon types (same key form).

        Cross-mfg dedup is keyed by ``(other_mfg, pid)`` so distinct game
        parts never collapse. When two entries end up with the same display
        label, a ``<weapon-type>`` suffix disambiguates them. Cross-mfg
        picks encode as ``{other_mfg:[pid]}`` (kind='list') so the game
        knows which manufacturer's part_type table to consult — the
        "cheat weapons" feature user has flagged as intentional.
        """
        options: list[tuple[tuple, str]] = []
        if not part_type:
            return options
        if part_type == "Element":
            # Element options come from elemental.csv (Elemental_ID=1). Key
            # tuple: ('elemental', part_id). Label: TSV override if present,
            # else computed ``"pid: <stat name>"``.
            if self.elemental_df is None:
                return options
            edf = self.elemental_df[self.elemental_df['Elemental_ID'] == self._ELEMENT_PARENT_ID]
            for _, row in edf.iterrows():
                pid = row.get('Part_ID')
                if pd.isna(pid):
                    continue
                pid = int(pid)
                # Element labels come from elemental.csv in the current
                # language (Stat vs Stat_ZH). TSV overrides are skipped —
                # a snapshot in one language shouldn't override runtime
                # language selection.
                name = row.get(self.elemental_stat_col) if pd.notna(row.get(self.elemental_stat_col)) else row.get('Stat')
                label = f"{pid}: {self.get_localized_string(str(name), str(name))}"
                options.append((('elemental', pid), label))
            return options
        if self.all_weapon_parts_df is None:
            return options
        decoded = self.serial_decoded_entry.text()

        # SECTION 1: same-mfg options.
        same_df = self.all_weapon_parts_df[
            (self.all_weapon_parts_df['Manufacturer & Weapon Type ID'] == manufacturer_id)
            & (self.all_weapon_parts_df['Part Type'] == part_type)
        ]
        same_opts: list[tuple[tuple, str]] = []
        for _, row in same_df.iterrows():
            pid = row['Part ID']
            if pd.isna(pid):
                continue
            pid = int(pid)
            override = self._lookup_label(('weapon', manufacturer_id, pid, part_type))
            if override:
                label = override
            else:
                label = self._abbrev_label(item_display_resolver.format_weapon_part_option(
                    manufacturer_id, pid, decoded, self.current_lang, row,
                ))
            same_opts.append((('simple', pid), label))

        # SECTIONS 2 + 3: cross-mfg, split by weapon-type match against the
        # current weapon. Our ``{other_mfg:[pid]}`` encoding tells the game
        # which mfg's part_type table to consult, so raw pid overlap in other
        # contexts is a non-issue; the dedupe below only collapses truly
        # identical DISPLAY labels (same brand-line variants).
        current_wt = self._weapon_type_of_mfg(manufacturer_id)
        cross_df = self.all_weapon_parts_df[
            (self.all_weapon_parts_df['Manufacturer & Weapon Type ID'] != manufacturer_id)
            & (self.all_weapon_parts_df['Part Type'] == part_type)
        ]
        # Key by (other_mfg, pid) — mfg_id is part of the encoded token, so
        # two rows with different mfg_ids resolve to different in-game
        # parts even when their display labels match. Dedup on the pair,
        # never on the label alone.
        same_wt_entries: dict[tuple[int, int], tuple[tuple, str, str]] = {}
        other_wt_entries: dict[tuple[int, int], tuple[tuple, str, str]] = {}
        for _, row in cross_df.iterrows():
            pid = row['Part ID']
            if pd.isna(pid):
                continue
            pid = int(pid)
            other_mfg = int(row['Manufacturer & Weapon Type ID'])
            mfg_name = self.get_localized_string(str(row['Manufacturer']))
            weapon_type = str(row['Weapon Type'])
            override = self._lookup_label(('weapon', other_mfg, pid, part_type))
            if override:
                base = override
            else:
                base = self._abbrev_label(item_display_resolver.format_weapon_part_option(
                    other_mfg, pid, decoded, self.current_lang, row,
                ))
            entry_key = (other_mfg, pid)
            bucket = same_wt_entries if weapon_type == current_wt else other_wt_entries
            # First (mfg_id, pid) wins — genuinely identical rows are rare
            # but the CSV can carry duplicates; skip re-adding.
            bucket.setdefault(
                entry_key,
                (('list', other_mfg, pid), f"[{mfg_name}] {base}", weapon_type),
            )

        def _finalize(bucket):
            """When several distinct (mfg_id, pid) entries produce the same
            display label, append a ``[weapon-type]`` suffix so the user can
            tell them apart (e.g. ``[Vladof Pistol]`` vs ``[Vladof Rifle]``)."""
            label_groups: dict[str, list[tuple[int, int]]] = {}
            for key, (_, label, _wt) in bucket.items():
                label_groups.setdefault(label, []).append(key)
            out = []
            for key, (opt_key, label, weapon_type) in bucket.items():
                if len(label_groups[label]) > 1:
                    label = f"{label} <{weapon_type}>"
                out.append((opt_key, label))
            return out

        # Assemble with sentinel separators so ``_make_slot_inner`` can render
        # disabled section-divider rows. Skip a section entirely when empty.
        options.extend(same_opts)
        if same_wt_entries:
            options.append((self._SEPARATOR_KEY, self._sep_label('cross_mfg_same_type',
                            "─── cross-mfg (same weapon type) ───")))
            options.extend(_finalize(same_wt_entries))
        if other_wt_entries:
            options.append((self._SEPARATOR_KEY, self._sep_label('cross_mfg_other_type',
                            "─── cross-mfg (other weapon types) ───")))
            options.extend(_finalize(other_wt_entries))
        return options

    def _sep_label(self, key: str, en: str) -> str:
        """Localized section-separator label. Routes through ``self._loc``
        like every other user-visible string in the tab."""
        return self._loc('parts', key, en)

    def _weapon_type_of_mfg(self, mfg_id: int) -> str | None:
        """Return the Weapon Type string for a mfg_id, or None if unknown."""
        if self.all_weapon_parts_df is None:
            return None
        rows = self.all_weapon_parts_df[
            self.all_weapon_parts_df['Manufacturer & Weapon Type ID'] == mfg_id
        ]
        if rows.empty:
            return None
        return str(rows.iloc[0]['Weapon Type'])

    @classmethod
    def _current_option_key(cls, part: dict):
        """Map a loaded part dict to its dropdown option key, or None if
        the part can't be represented by a schema-slot dropdown.

        Elemental encoding covers both single-form ({1:X}, kind='elemental')
        and list-form ({1:[X ...]}, kind='group', id=1) so Pearl doesn't
        display as ``(none)`` in a slot that actually holds a value. A
        multi-sub Pearl group returns ``('elemental_list', [subs])`` — the
        dropdown won't have a matching option for a 2-child key, so the
        combo falls back to (none), but the schema-fill still recognizes
        the token as an Element and doesn't orphan it.
        """
        if part is None:
            return None
        t = part.get('type')
        if t == 'simple':
            pid = part.get('id')
            return ('simple', int(pid)) if pid is not None else None
        if t == 'group':
            sub_ids = part.get('sub_ids', [])
            pid = part.get('id')
            if pid is not None and int(pid) == cls._ELEMENT_PARENT_ID:
                if len(sub_ids) == 1:
                    return ('elemental', int(sub_ids[0]))
                return ('elemental_list', tuple(int(s) for s in sub_ids))
            if len(sub_ids) == 1 and pid is not None:
                return ('list', int(pid), int(sub_ids[0]))
            return None
        if t == 'elemental':
            sub = part.get('sub_id')
            if sub is not None:
                return ('elemental', int(sub))
        return None

    def _state_idx_of_part(self, part: dict) -> int | None:
        """Return the current state token index for a loaded part dict, or
        None if the dict isn't currently in state.

        Uses the ``_tok`` back-reference attached at parse / insert time —
        identity-based so it stays correct after ``state.swap`` reorders
        tokens without touching ``parts_data``. A position-based lookup
        (``k``-th dict → ``k``-th typed token) would silently address the
        wrong token after any reorder.
        """
        if not isinstance(part, dict):
            return None
        tok = part.get('_tok')
        if tok is None:
            return None
        for i, t in enumerate(self._token_state.tokens):
            if t is tok:
                return i
        return None

    @staticmethod
    def _pair_parts_with_tokens(parts_list: list, tokens: list) -> None:
        """Attach ``_tok`` back-references from typed parts_data dicts to
        their state.tokens Token objects.

        Both parsers (``parse_component_string_with_skin`` and
        ``parse_component_tokens_with_skin``) walk the same text in order,
        so the k-th typed dict corresponds to the k-th non-raw token. Once
        paired, every downstream lookup becomes identity-based and survives
        arbitrary token reorderings (state.swap / state.move) without
        needing parts_data to stay parallel.
        """
        typed_dicts = [p for p in parts_list if isinstance(p, dict)]
        typed_tokens = [t for t in tokens if t.kind != 'raw']
        for d, t in zip(typed_dicts, typed_tokens):
            d['_tok'] = t

    # ---------- slot dropdown mutation ----------

    def _on_slot_selection_changed(self, slot_idx: int, combo, _idx):
        """User picked a new value in slot ``slot_idx``.

        Three cases:
          1. Empty → filled: create a fresh part dict, insert (typed token +
             trailing raw space) into state at the schema-ordered position,
             insert dict into parts_data at the matching relative position,
             mutate ``_slot_parts``; rebuild the row so it becomes a
             PositionalTokenRow.
          2. Filled → empty: locate the part's state index, drop the token
             (with adjacent whitespace) via ``remove_with_whitespace``;
             remove the dict from parts_data; rebuild the row as empty.
          3. Filled → different value (same schema slot): mutate the part
             dict's id/raw/type/sub_ids in place. Binding getter emits the
             new raw on next render; no state.tokens reshuffle needed.
        """
        if self._is_loading:
            return
        if not (0 <= slot_idx < len(self._slot_schema)):
            return
        new_key = combo.currentData()
        # Separator rows are disabled at the model level, but a completer
        # can still surface their text; ignore defensively so a stray click
        # doesn't try to insert a section-divider "part".
        if self._is_separator(new_key):
            return
        current_part = self._slot_parts[slot_idx]

        if new_key is None and current_part is None:
            return
        if new_key is None and current_part is not None:
            self._remove_slot_part(slot_idx, current_part)
            return
        if current_part is None:
            self._insert_slot_part(slot_idx, new_key)
            return
        # Filled → different value: mutate in place.
        self._mutate_part_for_key(current_part, new_key)
        self.rebuild_output()

    def _mutate_part_for_key(self, part: dict, key: tuple) -> None:
        """Rewrite a part dict in place to match a new dropdown option key.

        Encodings:
          - ``('simple', pid)`` → ``{pid}`` (same-mfg part)
          - ``('list', other_mfg, pid)`` → ``{other_mfg:[pid]}`` (cross-mfg
            single-child group)
          - ``('elemental', sub_id)`` → ``{1:sub_id}`` (element family)
        """
        # Clear any stale fields first — a mutation between kinds must not
        # leave a stale ``sub_ids`` on a simple part, ``value`` on a group,
        # etc.
        part.pop('sub_ids', None)
        part.pop('sub_id', None)
        part.pop('value', None)
        if key[0] == 'simple':
            _, pid = key
            part['type'] = 'simple'
            part['id'] = int(pid)
            part['raw'] = f"{{{int(pid)}}}"
        elif key[0] == 'list':
            _, other_mfg, pid = key
            part['type'] = 'group'
            part['id'] = int(other_mfg)
            part['sub_ids'] = [int(pid)]
            part['raw'] = f"{{{int(other_mfg)}:[{int(pid)}]}}"
        elif key[0] == 'elemental':
            _, sub_id = key
            part['type'] = 'elemental'
            part['id'] = self._ELEMENT_PARENT_ID
            part['sub_id'] = int(sub_id)
            part['raw'] = f"{{{self._ELEMENT_PARENT_ID}:{int(sub_id)}}}"

    def _insert_slot_part(self, slot_idx: int, key: tuple) -> None:
        """Empty slot → filled: create a new part dict, insert into state +
        parts_data at the correct schema-ordered position, rebuild row."""
        new_part: dict = {}
        self._mutate_part_for_key(new_part, key)

        # State insertion point: right after the trailing raw of the closest
        # already-filled slot with a lower slot_idx; else right after the
        # header token. New tokens are (typed, ' ') so the parts-section
        # invariant ``[header, part, ' ', part, ' ', ..., trailing]`` holds.
        state_insert_at = self._state_insert_point_for_slot(slot_idx)
        typed_token = self._token_for_part(new_part)
        new_part['_tok'] = typed_token  # identity back-ref for state_idx_of_part
        sep_token = Token(raw=' ', kind='raw')
        self._token_state.insert(state_insert_at, typed_token)
        self._token_state.insert(state_insert_at + 1, sep_token)

        # parts_data insertion point: mirror the state position so
        # _bind_token_state_widgets pairs them up correctly. Insert after the
        # closest lower-slot filled part dict (if any).
        parts_insert_at = self._parts_data_insert_point_for_slot(slot_idx)
        self.parts_data.insert(parts_insert_at, new_part)
        # A raw separator string in parts_data mirrors the sep token.
        self.parts_data.insert(parts_insert_at + 1, ' ')

        self._slot_parts[slot_idx] = new_part
        self._bind_token_state_widgets()
        self.rebuild_output()
        m_id = self._current_manufacturer_id()
        if m_id is not None:
            self._rebuild_parts_table(m_id)

    def _remove_slot_part(self, slot_idx: int, part: dict) -> None:
        """Filled slot → empty: drop the token from state (with adjacent
        whitespace) and remove the dict from parts_data. Rebuild the row."""
        state_idx = self._state_idx_of_part(part)
        if state_idx is not None:
            self._token_state.remove_with_whitespace(state_idx)
        # parts_data: drop the dict + one adjacent whitespace separator.
        for i, p in enumerate(self.parts_data):
            if p is part:
                self.parts_data.pop(i)
                # Drop a trailing whitespace raw string to mirror the state
                # collapse; if there's no trailing whitespace, try leading.
                if i < len(self.parts_data) and isinstance(self.parts_data[i], str) and not self.parts_data[i].strip():
                    self.parts_data.pop(i)
                elif i > 0 and isinstance(self.parts_data[i - 1], str) and not self.parts_data[i - 1].strip():
                    self.parts_data.pop(i - 1)
                break
        self._slot_parts[slot_idx] = None
        self._bind_token_state_widgets()
        self.rebuild_output()
        m_id = self._current_manufacturer_id()
        if m_id is not None:
            self._rebuild_parts_table(m_id)

    @staticmethod
    def _token_for_part(part: dict) -> Token:
        """Return a fresh Token for a schema-slot part dict."""
        t = part.get('type')
        if t == 'group':
            return Token(
                raw=part['raw'],
                kind='list',
                parent=int(part['id']),
                children=[int(c) for c in part.get('sub_ids', [])],
            )
        if t == 'elemental':
            return Token(
                raw=part['raw'],
                kind='single',
                parent=int(part['id']),
                value=int(part['sub_id']),
            )
        return Token(raw=part['raw'], kind='simple', value=int(part['id']))

    def _state_insert_point_for_slot(self, slot_idx: int) -> int:
        """Compute where to insert a new (typed, sep) pair for slot_idx.

        Anchor precedence:
          1. If a lower-schema-index slot is filled, insert AFTER its
             typed token and its trailing WHITESPACE-only raw (if any).
             A raw carrying ``|`` / ``||`` is a section delimiter — never
             step past it, else the new token lands outside the components
             section and the game silently ignores it.
          2. Else if rarity is present, insert after the rarity token (and
             its trailing whitespace raw, if any) — never at index 1 when
             that IS the rarity slot.
          3. Else insert at index 1 (right after the header).
        """
        tokens = self._token_state.tokens

        def _skip_whitespace_after(idx: int) -> int:
            nxt = idx + 1
            if nxt < len(tokens) and tokens[nxt].kind == 'raw' and not tokens[nxt].raw.strip():
                return idx + 2
            return idx + 1

        # (1) Anchor to lower-schema-index filled slot if present.
        insert_at = None
        for j in range(slot_idx):
            other = self._slot_parts[j]
            if other is None:
                continue
            j_idx = self._state_idx_of_part(other)
            if j_idx is None:
                continue
            candidate = _skip_whitespace_after(j_idx)
            insert_at = candidate if insert_at is None else max(insert_at, candidate)
        if insert_at is not None:
            return insert_at

        # (2) Anchor to rarity if present — never overwrite its slot.
        if self.rarity_part is not None:
            r_idx = self._state_idx_of_part(self.rarity_part)
            if r_idx is not None:
                return _skip_whitespace_after(r_idx)

        # (3) Fallback: right after the header token.
        return 1

    def _parts_data_insert_point_for_slot(self, slot_idx: int) -> int:
        """Compute the parts_data insertion index, mirroring the state layout."""
        insert_at = 0
        for j in range(slot_idx):
            other = self._slot_parts[j]
            if other is None:
                continue
            for i, p in enumerate(self.parts_data):
                if p is other:
                    # Skip a trailing separator string if present.
                    candidate = i + 1
                    if candidate < len(self.parts_data) and isinstance(self.parts_data[candidate], str) and not self.parts_data[candidate].strip():
                        candidate = i + 2
                    insert_at = max(insert_at, candidate)
                    break
        return insert_at

    # ---------- position control sync ----------

    def _on_token_moved(self, _old_index: int, _new_index: int):
        """PositionalTokenRow.token_moved handler. Re-scans every row and
        updates its [#] label from the new token positions, then rebuilds
        the serial from state."""
        self._resync_positional_indices()
        self.rebuild_output()

    def _resync_positional_indices(self):
        """Identity-based sync: each row captured its Token at construction,
        so we locate its current position in state.tokens directly. This
        stays correct after any state.move — no ``parts_data`` <-> state
        ordering invariant required."""
        token_to_idx = {id(tok): i for i, tok in enumerate(self._token_state.tokens)}
        for row in self._positional_rows:
            tok = row.token()
            if tok is None:
                continue
            new_idx = token_to_idx.get(id(tok))
            if new_idx is not None and new_idx != row.token_index():
                row.set_index(new_idx)

    # ---------- mutation entry points ----------

    def delete_part(self, index):
        if not (0 <= index < len(self.parts_data)):
            return
        part = self.parts_data[index]
        state_idx = self._state_idx_of_part(part) if isinstance(part, dict) else None
        self.parts_data.pop(index)
        if state_idx is not None:
            self._token_state.remove_with_whitespace(state_idx)
        self._bind_token_state_widgets()
        self.rebuild_output()
        m_id = self._current_manufacturer_id()
        if m_id is not None:
            self._rebuild_parts_table(m_id)

    def _current_manufacturer_id(self):
        """Return the current weapon's mfg id parsed from the header, or
        None if the header isn't parseable. Every caller guards on
        ``is not None`` before proceeding, so returning None (not 0) is
        essential — 0 would sail past the guard and build an empty parts
        table under a bogus mfg."""
        try:
            return int(self.serial_decoded_entry.text().split('||', 1)[0].strip().split('|')[0].split(',')[0])
        except (ValueError, IndexError):
            return None

    def rebuild_output(self):
        """State-first rebuild. Reads _token_state.render(), updates serial
        + b85 entries + stat display. Sets ``_encode_error`` so downstream
        update / add-to-pack paths can guard against stale bad encodings
        (matches the sibling tabs' convention)."""
        if not self._token_state.tokens:
            return
        new_decoded = self.browser.render_from_state(self._token_state)
        with block_signals(self.serial_decoded_entry):
            self.serial_decoded_entry.setText(new_decoded)
        new_b85, err = b_encoder.encode_to_base85(new_decoded)
        self._encode_error = bool(err)
        if not err:
            with block_signals(self.serial_b85_entry):
                self.serial_b85_entry.setText(new_b85)
        self._update_weapon_stats(new_decoded)

    # ---------- backpack + update-item emit ----------

    def _update_weapon(self):
        new_serial, _ = b_encoder.encode_to_base85(self.serial_decoded_entry.text().strip())
        emit_update_or_warn(
            self,
            new_serial=new_serial or '',
            no_selection_title=self.get_localized_string("no_selection"),
            no_selection_msg=self.get_localized_string("select_weapon_first"),
            no_valid_code_title=self.get_localized_string("encoding_fail"),
            no_valid_code_msg=self.get_localized_string("cannot_reencode_serial"),
            success_msg=self.get_localized_string('update_success'),
        )

    def _add_to_backpack(self):
        """Push the current state as a new backpack entry. Reads the b85
        entry populated by ``rebuild_output`` and consults ``_encode_error``
        instead of re-encoding — matches the sibling ``_add_to_backpack``
        shape and avoids running the encoder twice per click.
        """
        new_serial = self.serial_b85_entry.text().strip()
        if not self.serial_decoded_entry.text().strip():
            QtWidgets.QMessageBox.warning(
                self, self.get_localized_string("no_input"),
                self.get_localized_string("serial_empty"),
            )
            return
        if self._encode_error or not new_serial:
            QtWidgets.QMessageBox.critical(
                self, self.get_localized_string("encoding_fail"),
                self.get_localized_string("cannot_encode_serial"),
            )
            return
        self.add_to_backpack_requested.emit(new_serial, self.flag_combo.currentText().split(" ")[0])

