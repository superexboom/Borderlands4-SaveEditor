"""Base class for part-based equipment editor tabs.

Unifies the four previously copy-pasted tabs (grenade / shield / repkit /
heavy weapon) behind a single implementation. Subclasses declare their data
source and perk-group layout, and override a handful of hooks for the bits
that genuinely differ (serial assembly, import-token application, mfg change).

UI uses the modern catalog/chip pickers from ``qt_catalog_picker`` instead of
the old scrollable radio-button lists and dual-list "»/«" transfer boxes.
"""

import random
import re

import pandas as pd
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QLineEdit, QPushButton, QGroupBox, QRadioButton, QCheckBox,
    QListWidgetItem, QScrollArea, QMessageBox, QSpinBox, QFrame, QSizePolicy,
    QToolButton, QMenu, QWidgetAction, QStackedWidget, QButtonGroup,
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QColor, QFont

from core import b_encoder
from core import resource_loader
from core import lookup
from core import bl4_functions as bl4f
from core import item_display_resolver
from core.weapon_generation_logic import sample_composition_parts
from tabs.qt_catalog_picker import (
    CatalogPicker,
    InlineCatalogPicker,
    ContainedWheelListWidget,
    ContainedWheelScrollArea,
    PopupOnlyWheelComboBox,
)
from tabs.qt_weapon_roll_dialog import WeaponRollOptionsWidget, WeaponRollResultsPage
from tabs.qt_serial_import import (
    SerialSourceBar,
    build_header,
    choose_backpack_item,
    decode_base85,
    parse_components,
    prompt_base85,
    select_flag_value,
    source_texts,
    split_decoded,
)


class OptionCombo(QWidget):
    """Compact single-select option dropdown (replaces the chip grid).

    A label-less combo box holding a "none" entry plus the option list.
    Emits ``changed`` whenever the selected part id changes. Keeps the
    frosted-glass combo styling from the global theme.
    """

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._base_labels = []
        self._base_tooltips = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.combo = PopupOnlyWheelComboBox()
        self.combo.setMaxVisibleItems(20)
        lay.addWidget(self.combo)
        self.combo.currentIndexChanged.connect(self._on_index)

    def _on_index(self, _i):
        self.changed.emit()

    def set_options(self, options, preserve=False):
        """options: list of (part_id_or_None, label). First entry auto-selected."""
        selected = self.selected_pid() if preserve else None
        self.combo.blockSignals(True)
        self.combo.clear()
        self._base_labels = []
        self._base_tooltips = []
        for option in options:
            pid, label = option[:2]
            tooltip = option[2] if len(option) > 2 else label
            self.combo.addItem(label, pid)
            idx = self.combo.count() - 1
            self.combo.setItemData(idx, tooltip, Qt.ItemDataRole.ToolTipRole)
            self._base_labels.append(str(label))
            self._base_tooltips.append(str(tooltip))
        match = next(
            (index for index in range(self.combo.count()) if self.combo.itemData(index) == selected),
            0,
        )
        self.combo.setCurrentIndex(match)
        self.combo.blockSignals(False)

    def set_candidate_states(self, states):
        """Decorate options with advisory natural-generation hints.

        Options are never disabled: these editors intentionally support modified
        equipment.  The marker/background only tells the user which choices fit the
        currently selected natural composition.
        """
        states = states or {}
        for index in range(self.combo.count()):
            pid = self.combo.itemData(index)
            base = self._base_labels[index] if index < len(self._base_labels) else self.combo.itemText(index)
            state = states.get(pid) or {}
            marker = str(state.get("marker") or "").strip()
            self.combo.setItemText(index, f"{marker}  {base}" if marker else base)
            hint = str(state.get("hint") or "").strip()
            detail = self._base_tooltips[index] if index < len(self._base_tooltips) else base
            self.combo.setItemData(
                index,
                "\n\n".join(filter(None, (hint, detail))),
                Qt.ItemDataRole.ToolTipRole,
            )
            self.combo.setItemData(index, None, Qt.ItemDataRole.BackgroundRole)
            self.combo.setItemData(index, None, Qt.ItemDataRole.ForegroundRole)
            font = QFont(self.combo.font())
            font.setBold(state.get("kind") == "legal")
            self.combo.setItemData(index, font, Qt.ItemDataRole.FontRole)
            if state.get("kind") == "legal":
                self.combo.setItemData(index, QColor(74, 144, 226, 48), Qt.ItemDataRole.BackgroundRole)
            elif state.get("kind") == "warning":
                self.combo.setItemData(index, QColor(230, 164, 57, 38), Qt.ItemDataRole.BackgroundRole)

    def selected_pid(self):
        return self.combo.currentData()

    def select_pid(self, pid):
        for i in range(self.combo.count()):
            if self.combo.itemData(i) == pid:
                self.combo.setCurrentIndex(i)
                return True
        return False

    def select_none(self):
        for i in range(self.combo.count()):
            if not self.combo.itemData(i):
                self.combo.setCurrentIndex(i)
                return
        self.combo.setCurrentIndex(0)

    def option_pids(self):
        return [self.combo.itemData(i) for i in range(self.combo.count())
                if self.combo.itemData(i)]


class BaseEquipmentEditorTab(QWidget):
    """Shared behaviour for part-based equipment editors.

    Subclass contract:
      * class attrs: ``EQUIP_TYPE``, ``UI_LOC_KEY``, ``DEFAULT_SEED``,
        ``MFG_IDS``, ``BACKPACK_TYPE_EN``, ``ITEM_LABEL``
      * ``load_data(lang)`` -> ``(df_main, df_mfg, localization)``
      * ``_declare_perk_groups()`` -> list of group-config dicts
      * ``_group_items(key, mfg_id)`` -> list[dict] for "picker" groups
      * ``_group_rows(key, mfg_id)`` -> (df, part_id_formatter) for radio/checkbox
      * ``_build_skill_parts(mfg_id)`` -> (skill_parts, secondary)
      * ``_apply_components(component)`` -> None (import back-fill)
      * optional: ``_default_new_header``, ``_extra_reset_state``,
        ``_on_mfg_changed_extra``, ``_populate_initial_extra``,
        ``_update_language_texts_extra``
    """

    add_to_backpack_requested = pyqtSignal(str, str)
    batch_add_to_backpack_requested = pyqtSignal(list, str)

    # --- subclass-provided class attributes -------------------------------
    EQUIP_TYPE = ""
    UI_LOC_KEY = ""
    DEFAULT_SEED = 305
    MFG_IDS = []
    BACKPACK_TYPE_EN = ""
    ITEM_LABEL = "Item"
    PREVIEW_FIELDS = {
        "Grenade": ("damage", "cooldown", "radius", "charges", "critical_damage", "critical_chance"),
        "Shield": ("capacity", "recharge_rate", "recharge_delay", "armor_segments", "damage_reduction"),
        "Repkit": ("healing", "instant_healing", "health_over_time", "duration", "cooldown", "charges"),
        "Heavy Weapon": ("damage", "dps", "accuracy", "fire_rate", "magazine", "cooldown", "critical_damage", "splash_radius"),
    }

    def __init__(self, main_app=None, parent=None):
        super().__init__(parent)
        self.main_app = main_app
        self.current_lang = 'zh-CN'
        self._character_level = "50"
        self._loading_import = False
        self._imported_copy = False
        self._source_seed = self.DEFAULT_SEED
        self._source_header = None
        self._source_name = ""
        self._preserved_tokens = []
        self._preserved_children = {}
        self._encode_error = False
        self._refreshing_descriptions = False
        self._roll_constraints = {}
        self._roll_count = 5
        self._roll_add_busy = False
        self._roll_menu = None
        self._roll_options_widget = None
        self.df_main, self.df_mfg, self.localization = self.load_data(self.current_lang)

        self._load_ui_localization()

        if self.df_main is None:
            layout = QVBoxLayout(self)
            layout.addWidget(QLabel(self.ui_loc.get('dialogs', {}).get(
                'load_error', f"错误: {self.ITEM_LABEL} 数据无法加载。")))
            return

        self.mfg_ids = list(self.MFG_IDS)
        self._group_widgets = {}   # key -> list[radio/checkbox]
        self._group_pickles = {}   # key -> CatalogPicker | InlineCatalogPicker
        self._group_cfgs = {}      # key -> config dict

        self._build_ui()
        self.populate_initial_data()
        self._connect_signals()
        self.on_mfg_change()

    # ------------------------------------------------------------------ #
    # Data / localization
    # ------------------------------------------------------------------ #
    def load_data(self, lang):  # pragma: no cover - abstract
        raise NotImplementedError

    def _load_ui_localization(self):
        loc_file = resource_loader.get_ui_localization_file(self.current_lang)
        full_loc = resource_loader.load_json_resource(loc_file) or {}
        self._full_loc = full_loc
        self.ui_loc = full_loc.get(self.UI_LOC_KEY, {})
        self.legit_loc = full_loc.get("equipment_legit", {})

    def _(self, text):
        return self.localization.get(str(text), str(text))

    def _get_mfg_name(self, mfg_id):
        if mfg_id in lookup.REVERSE_ID_MAP:
            mfg_en = lookup.REVERSE_ID_MAP[mfg_id][0]
            return bl4f.get_localized_string(mfg_en)
        return "Unknown"

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        page_nav = QHBoxLayout()
        page_nav.setSpacing(8)
        texts = self._roll_texts()
        self.editor_page_button = QPushButton(texts["main_page"])
        self.roll_results_button = QPushButton(texts["results_page"])
        self.page_button_group = QButtonGroup(self)
        self.page_button_group.setExclusive(True)
        for index, button in enumerate((self.editor_page_button, self.roll_results_button)):
            button.setObjectName("genPageTab")
            button.setCheckable(True)
            self.page_button_group.addButton(button, index)
            page_nav.addWidget(button)
        page_nav.addStretch()
        main_layout.addLayout(page_nav)

        self.page_stack = QStackedWidget()
        self.editor_page = QWidget()
        editor_layout = QVBoxLayout(self.editor_page)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        editor_layout.addWidget(scroll)
        container = QWidget(); scroll.setWidget(container)
        layout = QVBoxLayout(container)

        self._create_source_bar(layout)
        self._create_output_group(layout)
        self._create_top_controls(layout)
        self._create_stats_preview(layout)
        self._create_generation_guidance(layout)

        self.perks_group = QGroupBox(self.ui_loc['groups']['perks'])
        perks_layout = QGridLayout(self.perks_group)
        self._build_perk_groups(perks_layout)
        layout.addWidget(self.perks_group)
        layout.addStretch()

        self.roll_results_page = WeaponRollResultsPage(
            texts=texts,
            stat_keys=self._preview_stat_keys(),
            stat_columns=4,
        )
        self.roll_results_page.add_requested.connect(self._request_roll_add)
        self.roll_results_page.close_requested.connect(lambda: self._set_workspace_page(0))
        self.page_stack.addWidget(self.editor_page)
        self.page_stack.addWidget(self.roll_results_page)
        main_layout.addWidget(self.page_stack, 1)
        self.page_button_group.idClicked.connect(self._set_workspace_page)
        self._set_workspace_page(0)

    def _build_perk_groups(self, perks_layout):
        cfgs = self._declare_perk_groups()
        for cfg in cfgs:
            key = cfg["key"]
            title = self.ui_loc['groups'].get(cfg["title_key"], cfg["title_key"])
            self._group_cfgs[key] = cfg
            mode = cfg.get("mode", "picker")
            if mode == "picker":
                picker = CatalogPicker(
                    stackable=cfg.get("stackable", True),
                    search_placeholder=self._search_placeholder(),
                    avail_title=self._avail_title(),
                    selected_title=title,
                    clear_text=self.ui_loc['buttons'].get('clear', 'Clear'),
                )
                picker.add_sel_btn.setText(self._add_selected_text())
                # The group title already shows the rule-backed current/legal count.
                # Hide the legacy cart count, which only counted rows/stacks and could
                # disagree with conditional generation groups.
                picker.count_lbl.hide()
                picker.list_min_height = cfg.get("min_height", 200)
                picker.avail.setMinimumHeight(cfg.get("min_height", 200))
                picker.selected.setMinimumHeight(cfg.get("min_height", 200))
                picker.changed.connect(self.rebuild_output)
                self._group_pickles[key] = picker
                group = QGroupBox(title)
                v = QVBoxLayout(group)
                v.addWidget(picker)
            elif mode == "inline":
                picker = InlineCatalogPicker(
                    stackable=cfg.get("stackable", True),
                    search_placeholder=self._search_placeholder(),
                    clear_text=self.ui_loc['buttons'].get('clear', 'Clear'),
                    multi_select=True,
                )
                picker.list.setMinimumHeight(cfg.get("min_height", 220))
                picker.changed.connect(self.rebuild_output)
                self._group_pickles[key] = picker
                group = QGroupBox(title)
                v = QVBoxLayout(group)
                v.addWidget(picker)
            elif mode == "chip":
                group = QGroupBox(title)
                v = QVBoxLayout(group)
                combo = OptionCombo()
                combo.changed.connect(self.rebuild_output)
                v.addWidget(combo)
                cfg["_chip"] = combo
            else:  # radio / checkbox scroll group
                wtype = QRadioButton if mode == "radio" else QCheckBox
                group, frame, widgets = self._create_scrollable_group(title, wtype)
                self._group_widgets[key] = widgets
                cfg["_frame"] = frame
            cfg["_group_box"] = group
            row, col, rowspan, colspan = cfg.get("grid", (0, 0, 1, 1))
            perks_layout.addWidget(group, row, col, rowspan, colspan)

    def _search_placeholder(self):
        return self.ui_loc.get('misc', {}).get('search', '搜索…' if self.current_lang == 'zh-CN' else 'Search…')

    def _avail_title(self):
        return self.ui_loc.get('misc', {}).get('available', '可选' if self.current_lang == 'zh-CN' else 'Available')

    def _add_selected_text(self):
        return self.ui_loc.get('buttons', {}).get('add_selected',
               '添加所选 →' if self.current_lang == 'zh-CN' else 'Add selected →')

    def _create_scrollable_group(self, title, widget_type):
        group_box = QGroupBox(title)
        scroll_area = ContainedWheelScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setMinimumHeight(180)
        container = QWidget()
        layout = QVBoxLayout(container)
        scroll_area.setWidget(container)
        main_layout = QVBoxLayout(group_box)
        main_layout.addWidget(scroll_area)
        return group_box, layout, []

    def _create_source_bar(self, layout):
        texts = source_texts(self.current_lang)
        self.source_bar = SerialSourceBar(
            new_text=texts['new_source'],
            backpack_text=texts['backpack'],
            base85_text=texts['base85'],
            reset_text=texts['reset'],
        )
        self.source_bar.backpack_requested.connect(self._import_from_backpack)
        self.source_bar.base85_requested.connect(self._import_from_base85)
        self.source_bar.reset_requested.connect(self._reset_import_source)
        self.source_bar.backpack_btn.setEnabled(self.main_app is not None)
        layout.addWidget(self.source_bar)

    def _create_output_group(self, layout):
        self.output_group = QGroupBox(self.ui_loc['groups']['output'])
        grid = QGridLayout(self.output_group)
        self.raw_output_edit = QLineEdit(); self.raw_output_edit.setReadOnly(True)
        self.b85_output_edit = QLineEdit(); self.b85_output_edit.setReadOnly(True)
        self.copy_raw_btn = QPushButton(self.ui_loc['buttons']['copy'])
        self.copy_b85_btn = QPushButton(self.ui_loc['buttons']['copy'])
        self.add_to_pack_btn = QPushButton(self.ui_loc['buttons']['add_to_backpack'])
        self.flag_combo = PopupOnlyWheelComboBox()
        self._populate_flags()
        self.raw_label = QLabel(self.ui_loc['labels']['raw'])
        self.b85_label = QLabel(self.ui_loc['labels']['base85'])
        grid.addWidget(self.raw_label, 0, 0); grid.addWidget(self.raw_output_edit, 0, 1); grid.addWidget(self.copy_raw_btn, 0, 2)
        grid.addWidget(self.b85_label, 1, 0); grid.addWidget(self.b85_output_edit, 1, 1); grid.addWidget(self.copy_b85_btn, 1, 2)
        grid.addWidget(self.flag_combo, 1, 3); grid.addWidget(self.add_to_pack_btn, 1, 4)
        self.copy_raw_btn.clicked.connect(lambda: self._copy_to_clipboard(self.raw_output_edit))
        self.copy_b85_btn.clicked.connect(lambda: self._copy_to_clipboard(self.b85_output_edit))
        layout.addWidget(self.output_group)

    def _create_top_controls(self, layout):
        self.base_attrs_group = QGroupBox(self.ui_loc['groups']['base_attrs'])
        controls_layout = QHBoxLayout(self.base_attrs_group)
        self.mfg_combo = PopupOnlyWheelComboBox()
        self.level_edit = QLineEdit(self._character_level)
        self.rarity_combo = PopupOnlyWheelComboBox()
        self.level_edit.setFixedWidth(100)
        self.rarity_combo.setFixedWidth(300)
        self.mfg_label = QLabel(self.ui_loc['labels']['manufacturer'])
        self.level_label = QLabel(self.ui_loc['labels']['level'])
        self.rarity_label = QLabel(self.ui_loc['labels']['rarity'])
        controls_layout.addWidget(self.mfg_label); controls_layout.addWidget(self.mfg_combo)
        controls_layout.addWidget(self.level_label); controls_layout.addWidget(self.level_edit)
        controls_layout.addWidget(self.rarity_label); controls_layout.addWidget(self.rarity_combo)
        controls_layout.addStretch()
        self.lucky_button = QToolButton()
        self.lucky_button.setObjectName("genLuckyButton")
        self.lucky_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.lucky_button.clicked.connect(self._quick_roll)
        controls_layout.addWidget(self.lucky_button)
        self._setup_roll_menu()
        layout.addWidget(self.base_attrs_group)

    def _preview_stat_keys(self):
        return tuple(self.PREVIEW_FIELDS.get(self.BACKPACK_TYPE_EN, ()))

    def _create_stats_preview(self, layout):
        self.stats_preview = QFrame()
        self.stats_preview.setObjectName("rollDetailCard")
        root = QVBoxLayout(self.stats_preview)
        root.setContentsMargins(12, 9, 12, 9)
        root.setSpacing(6)
        self.stats_preview_title = QLabel(self._roll_texts()["live_stats"])
        self.stats_preview_title.setObjectName("genSectionTitle")
        root.addWidget(self.stats_preview_title)

        self.stats_preview_grid = QGridLayout()
        self.stats_preview_grid.setContentsMargins(0, 0, 0, 0)
        self.stats_preview_grid.setSpacing(1)
        self.stats_preview_cells = {}
        self.stats_preview_names = {}
        self.stats_preview_values = {}
        labels = self._equipment_stat_labels()
        for key in self._preview_stat_keys():
            cell = QFrame()
            cell.setObjectName("rollStatCell")
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(7, 5, 7, 5)
            cell_layout.setSpacing(2)
            name = QLabel(labels.get(key, key.replace("_", " ").title()))
            name.setObjectName("rollStatName")
            name.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value = QLabel("—")
            value.setObjectName("rollStatValue")
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cell_layout.addWidget(name)
            cell_layout.addWidget(value)
            self.stats_preview_cells[key] = cell
            self.stats_preview_names[key] = name
            self.stats_preview_values[key] = value
        root.addLayout(self.stats_preview_grid)
        self.stats_preview_empty = QLabel("—")
        self.stats_preview_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.stats_preview_empty)
        layout.addWidget(self.stats_preview)

    def _create_generation_guidance(self, layout):
        self.generation_guidance = QFrame()
        self.generation_guidance.setObjectName("equipmentLegitCard")
        row = QHBoxLayout(self.generation_guidance)
        row.setContentsMargins(12, 9, 12, 9)
        row.setSpacing(12)

        self.generation_status_badge = QLabel("—")
        self.generation_status_badge.setObjectName("genBuildStatus")
        self.generation_status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.generation_status_badge.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        row.addWidget(self.generation_status_badge)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)
        self.generation_reason_label = QLabel("")
        self.generation_reason_label.setObjectName("equipmentLegitReason")
        self.generation_reason_label.setWordWrap(True)
        self.generation_groups_label = QLabel("")
        self.generation_groups_label.setObjectName("equipmentLegitGroups")
        self.generation_groups_label.setWordWrap(True)
        text_col.addWidget(self.generation_reason_label)
        text_col.addWidget(self.generation_groups_label)
        row.addLayout(text_col, 1)
        layout.addWidget(self.generation_guidance)

    def _connect_signals(self):
        self.mfg_combo.currentTextChanged.connect(self.on_mfg_change)
        self.level_edit.textChanged.connect(self.rebuild_output)
        self.rarity_combo.currentTextChanged.connect(self.rebuild_output)
        self.add_to_pack_btn.clicked.connect(self._add_to_backpack)

    # ------------------------------------------------------------------ #
    # Population
    # ------------------------------------------------------------------ #
    def populate_initial_data(self):
        self.mfg_combo.blockSignals(True)
        self.mfg_combo.clear()
        items = [(self._manufacturer_option_label(k), k) for k in self.mfg_ids]
        items.sort(key=lambda x: x[1])
        self.mfg_combo.addItems([x[0] for x in items])
        self.mfg_combo.blockSignals(False)
        self._populate_initial_extra()

    def _manufacturer_option_label(self, mfg_id):
        return f"{self._get_mfg_name(mfg_id)} - {mfg_id}"

    def _populate_initial_extra(self):
        """Hook: populate mfg-independent groups (element/firmware/etc)."""

    def _firmware_group_df(self, owner_col, owner_id):
        """Synthetic firmware rows for a chip group, enumerated from the index.

        Firmware names/descriptions live in the shared Firmware/firmware.csv (keyed by
        internal part string) since the pool is shared across families; only the serial
        child ids are family-specific, which is why the rows come from the index for
        this family's owner instead of a per-family CSV section. ``equipment_part_name``
        resolves the shared name for category=firmware refs, so the standard row
        formatters work unchanged on these rows.
        """
        rows = [
            {owner_col: owner_id, "Part_ID": int(part_id), "Part_type": "Firmware", "Stat": "", "Description": ""}
            for part_id, _internal in item_display_resolver.equipment_firmware_parts(owner_id)
        ]
        return pd.DataFrame(rows, columns=[owner_col, "Part_ID", "Part_type", "Stat", "Description"])

    def _current_mfg_id(self):
        try:
            return int(self.mfg_combo.currentText().split(' - ')[-1])
        except (ValueError, IndexError):
            return None

    def on_mfg_change(self, *args):
        if not self.mfg_combo.currentText():
            return
        mfg_id = self._current_mfg_id()
        if mfg_id is None:
            return
        # rarity
        self.rarity_combo.blockSignals(True)
        self.rarity_combo.clear()
        rarity_rows = self.df_mfg[
            (self.df_mfg['Manufacturer ID'] == mfg_id) & (self.df_mfg['Part_type'] == 'Rarity')
        ].copy()
        rarity_order = {"common": 0, "uncommon": 1, "rare": 2, "epic": 3, "legendary": 4, "pearl": 5}
        rarity_rows["_sort_rarity"] = rarity_rows["Stat"].map(
            lambda value: rarity_order.get(str(value).strip().casefold(), 99)
        )
        rarity_rows = rarity_rows.sort_values(["_sort_rarity", "Part_ID"], kind="stable")
        for _, r in rarity_rows.iterrows():
            desc = r['Description']
            self.rarity_combo.addItem(f"{self._(r['Stat'])} - {desc if pd.notna(desc) else ''}".strip(" -"), r['Part_ID'])
        self.rarity_combo.blockSignals(False)
        self.rarity_combo.setFixedWidth(300)
        # perk groups
        for key, cfg in self._group_cfgs.items():
            mode = cfg.get("mode", "picker")
            if mode in ("picker", "inline"):
                self._group_pickles[key].set_source(self._group_items(key, mfg_id))
            elif mode == "chip":
                rows = self._group_rows(key, mfg_id)
                if rows is None:
                    continue
                df, fmt = rows
                self._populate_chip_group(cfg, df, fmt)
            else:
                rows = self._group_rows(key, mfg_id)
                if rows is None:
                    continue  # mfg-independent group; populated once elsewhere
                df, fmt = rows
                self._populate_button_group(cfg, df, fmt)
        self._on_mfg_changed_extra(mfg_id)
        self.rebuild_output()

    def _on_mfg_changed_extra(self, mfg_id):
        """Hook for subclass-specific mfg-change behaviour."""

    def _group_items(self, key, mfg_id):  # pragma: no cover - abstract
        raise NotImplementedError

    def _group_rows(self, key, mfg_id):  # pragma: no cover - abstract
        raise NotImplementedError

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _populate_chip_group(self, cfg, df, fmt):
        options = [(None, self.ui_loc['misc']['none'])]
        for _, r in df.iterrows():
            text, part_id = fmt(r)
            if cfg.get("key") == "firmware":
                name = item_display_resolver.equipment_part_name(
                    self._row_ref_key(r), self.current_lang, self._(r.get('Stat', ''))
                )
                match = re.search(r"(?:^|,\s*)L1:\s*(.*?)(?=,\s*L2:|$)", text)
                compact = " - ".join(filter(None, (name, match.group(1).strip() if match else ""))) or name or text
                options.append((part_id, compact, text))
            else:
                options.append((part_id, text))
        cfg["_chip"].set_options(options, preserve=self._refreshing_descriptions)

    def _populate_button_group(self, cfg, df, fmt):
        frame = cfg["_frame"]
        widgets = self._group_widgets[cfg["key"]]
        self._clear_layout(frame)
        widgets.clear()
        if cfg.get("mode") == "radio":
            none_rb = QRadioButton(self.ui_loc['misc']['none'])
            none_rb.setChecked(True)
            frame.addWidget(none_rb); widgets.append(none_rb)
        for _, r in df.iterrows():
            text, part_id = fmt(r)
            w = QRadioButton(text) if cfg.get("mode") == "radio" else QCheckBox(text)
            w.setProperty("part_id", part_id)
            frame.addWidget(w); widgets.append(w)
        frame.addStretch()
        for w in widgets:
            w.toggled.connect(self.rebuild_output)

    def _fmt_row(self, r, extra=None):
        """Default display formatter -> (text, part_id)."""
        text = item_display_resolver.equipment_part_name(
            self._row_ref_key(r), self.current_lang, self._(r['Stat'])
        )
        description = self._row_description(r)
        if description:
            text += f" - {description}"
        if extra:
            text = f"{extra}{text}"
        return text, r['Part_ID']

    @staticmethod
    def _row_ref_key(r):
        owner = next(
            (
                r[column]
                for column in (
                    "Grenade_perk_main_ID",
                    "Shield_perk_main_ID",
                    "Repkit_perk_main_ID",
                    "Heavy_perk_main_ID",
                    "Manufacturer ID",
                )
                if column in r and pd.notna(r[column])
            ),
            None,
        )
        try:
            return f"{int(owner)}:{int(r['Part_ID'])}"
        except (TypeError, ValueError, KeyError):
            return ""

    def _row_description(self, r):
        fallback = ""
        if 'Description' in r and pd.notna(r['Description']) and r['Description']:
            fallback = str(r['Description'])
        formatter = getattr(item_display_resolver, "format_equipment_part_description", None)
        decoded = self.raw_output_edit.text() if hasattr(self, "raw_output_edit") else ""
        ref_key = self._row_ref_key(r)
        if not formatter or not decoded or not ref_key:
            return fallback
        try:
            return formatter(decoded, self.BACKPACK_TYPE_EN, ref_key, self.current_lang) or fallback
        except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError):
            return fallback

    def _refresh_dynamic_descriptions(self):
        if self._refreshing_descriptions or self._loading_import or not self.raw_output_edit.text():
            return
        mfg_id = self._current_mfg_id()
        if mfg_id is None:
            return
        self._refreshing_descriptions = True
        try:
            self._populate_initial_extra()
            for key, cfg in self._group_cfgs.items():
                mode = cfg.get("mode", "picker")
                if mode in ("picker", "inline"):
                    self._group_pickles[key].set_source(self._group_items(key, mfg_id))
                elif mode == "chip":
                    rows = self._group_rows(key, mfg_id)
                    if rows is not None:
                        df, fmt = rows
                        self._populate_chip_group(cfg, df, fmt)
        finally:
            self._refreshing_descriptions = False

    # ------------------------------------------------------------------ #
    # Serial assembly (output)
    # ------------------------------------------------------------------ #
    def rebuild_output(self, *args):
        if self._loading_import:
            return
        try:
            mfg_id = self._current_mfg_id()
            if mfg_id is None:
                return
            level = self.level_edit.text()
            rarity_id = self.rarity_combo.currentData()
            header = (
                build_header(self._source_header, mfg_id=mfg_id, level=level, seed=self._source_seed)
                if self._imported_copy and self._source_header
                else self._default_new_header(mfg_id, level)
            )
            skill_parts, secondary = self._build_skill_parts(mfg_id)
            if rarity_id:
                skill_parts.insert(0, f"{{{rarity_id}}}")
            if self._imported_copy:
                skill_parts.extend(self._preserved_tokens)
                for parent_id, children in self._preserved_children.items():
                    secondary.setdefault(parent_id, []).extend(children)
            for k, v in secondary.items():
                if v:
                    skill_parts.append(f"{{{k}:[{' '.join(map(str, sorted(v)))}]}}" if len(v) > 1 else f"{{{k}:{v[0]}}}")
            final_str = f"{header}|| " + " ".join(skill_parts) + " |"
            self.raw_output_edit.setText(final_str)
            encoded, err = b_encoder.encode_to_base85(final_str)
            self._encode_error = bool(err)
            self.b85_output_edit.setText(f"{self.ui_loc.get('dialogs', {}).get('error', 'Error')}: {err}" if err else encoded)
            self._update_equipment_stats(final_str if not err else "")
            self._refresh_dynamic_descriptions()
            self._update_generation_guidance(final_str)
        except Exception as e:
            self._update_equipment_stats("")
            print(f"Rebuild error ({self.EQUIP_TYPE}): {e}")

    def _equipment_stat_labels(self):
        return dict(((self._full_loc.get("items_tab") or {}).get("columns") or {}))

    def _update_equipment_stats(self, decoded):
        try:
            stats = item_display_resolver.resolve_equipment_stats(decoded, self.BACKPACK_TYPE_EN) if decoded else {}
        except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError):
            stats = {}
        labels = self._equipment_stat_labels()
        visible = []
        for column in range(4):
            self.stats_preview_grid.setColumnStretch(column, 0)
        for key, cell in self.stats_preview_cells.items():
            self.stats_preview_grid.removeWidget(cell)
            raw = stats.get(key)
            present = raw not in (None, "")
            cell.setVisible(present)
            self.stats_preview_names[key].setText(labels.get(key, key.replace("_", " ").title()))
            if present:
                value = item_display_resolver.format_equipment_stat(key, raw, self.current_lang)
                self.stats_preview_values[key].setText(str(value) if value != "" else str(raw))
                visible.append(key)
        columns = min(4, max(1, len(visible)))
        for index, key in enumerate(visible):
            self.stats_preview_grid.addWidget(
                self.stats_preview_cells[key], index // columns, index % columns
            )
            self.stats_preview_grid.setColumnStretch(index % columns, 1)
        self.stats_preview_empty.setVisible(not visible)

    # ------------------------------------------------------------------ #
    # Natural-generation guidance (advisory, never enforced)
    # ------------------------------------------------------------------ #
    # Slot budgets are declared per composition in
    # weapon_generation_rules.weapons[root].compositions[*].groups[*].{min,max}, and the
    # same validator the inspector uses resolves them for the current build. Reading them
    # here means a balance patch or a new item type flows through automatically; measuring
    # budgets from sample items would break on the first new item.
    #
    # Mapping a tab picker onto rule groups is per-family, so subclasses declare it.
    # Empty mapping = the family opts out and no badge is shown.
    RULE_GROUPS_BY_PICKER: dict[str, tuple[str, ...]] = {}

    def _legit_text(self, key, fallback):
        return str((self.legit_loc or {}).get(key) or fallback)

    def _generation_group_text(self, group):
        groups = (self.legit_loc or {}).get("groups") or {}
        return str(groups.get(str(group), group))

    @staticmethod
    def _generation_range(spec):
        low = int(spec.get("effective_min", spec.get("min", 0)))
        high = int(spec.get("effective_max", spec.get("max", 0)))
        return str(low) if low == high else f"{low}–{high}"

    def _is_gold_skin_selected(self):
        mfg_id = self._current_mfg_id()
        part_id = self.rarity_combo.currentData() if hasattr(self, "rarity_combo") else None
        if mfg_id is None or part_id is None:
            return False
        try:
            rows = self.df_mfg[
                (self.df_mfg['Manufacturer ID'] == int(mfg_id))
                & (self.df_mfg['Part_ID'] == int(part_id))
                & (self.df_mfg['Part_type'] == 'Rarity')
            ]
        except (KeyError, TypeError, ValueError):
            return False
        if rows.empty:
            return False
        row = rows.iloc[0]
        values = [row.get("Description", ""), row.get("Description_ZH", ""), row.get("Description_EN", "")]
        normalized = {str(value).strip().casefold() for value in values if pd.notna(value)}
        return bool(normalized.intersection({"gold skin", "goldskin", "金皮肤"}))

    def _generation_ref_for_option(self, key, data):
        """Subclass hook: turn one picker/chip payload into ``owner:part``."""
        return ""

    def _generation_violation_text(self, violation):
        code = str(violation.get("code") or "")
        group = self._generation_group_text(violation.get("group") or "")
        if code == "count_below":
            template = self._legit_text("reason_count_below", "Missing {group} ({actual}/{limit})")
            return template.format(group=group, actual=violation.get("actual", 0), limit=violation.get("min", 0))
        if code == "count_above":
            template = self._legit_text("reason_count_above", "Too many {group} ({actual}/{limit})")
            return template.format(group=group, actual=violation.get("actual", 0), limit=violation.get("max", 0))
        mapping = {
            "part_not_allowed": "reason_part_not_allowed",
            "duplicate_part": "reason_duplicate_part",
            "missing_required_tag": "reason_missing_dependency",
            "excluded_tag_conflict": "reason_conflict",
            "foreign_root_part": "reason_foreign_part",
            "unknown_part": "reason_unknown_part",
            "unknown_composition": "reason_unknown_composition",
            "multiple_compositions": "reason_multiple_compositions",
            "unresolved_rule_parts": "reason_rule_gap",
            "conditional_availability": "reason_conditional",
        }
        fallbacks = {
            "reason_part_not_allowed": "A selected part is outside this natural template",
            "reason_duplicate_part": "The same part is selected more than once",
            "reason_missing_dependency": "A selected part is missing its dependency",
            "reason_conflict": "Selected parts conflict",
            "reason_foreign_part": "A cross-family part is selected",
            "reason_unknown_part": "An unknown part is present",
            "reason_unknown_composition": "Select a recognized item template",
            "reason_multiple_compositions": "More than one item template is selected",
            "reason_rule_gap": "Generation rules are incomplete",
            "reason_conditional": "This build requires conditional content",
        }
        key = mapping.get(code, "reason_modified")
        return self._legit_text(key, fallbacks.get(key, "Does not match the natural-generation rules"))

    def _candidate_state(self, ref, rule_keys, groups):
        ref = str(ref or "")
        if not ref:
            return {}
        matched = [groups[key] for key in rule_keys if key in groups and ref in set(groups[key].get("allowed") or [])]
        if not matched:
            return {
                "kind": "neutral",
                "marker": "",
                "hint": self._legit_text("candidate_not_allowed", "Not part of this natural template; still selectable as a modified part."),
            }
        if not any(int(spec.get("effective_max", spec.get("max", 0))) > 0 or ref in set(spec.get("selected") or []) for spec in matched):
            return {
                "kind": "neutral",
                "marker": "",
                "hint": self._legit_text("candidate_not_allowed", "Not active in this natural template; still selectable as a modified part."),
            }
        selected = any(ref in set(spec.get("selected") or []) for spec in matched)
        remaining = any(ref in set(spec.get("remaining_eligible_refs") or []) for spec in matched)
        eligible = any(ref in set(spec.get("eligible_refs") or []) for spec in matched)
        names = " / ".join(self._generation_group_text(key) for key in rule_keys if key in groups and ref in set(groups[key].get("allowed") or []))
        if selected or remaining:
            template = self._legit_text("candidate_legal", "Natural candidate: {group}")
            return {"kind": "legal", "marker": "✓", "hint": template.format(group=names)}
        if eligible:
            template = self._legit_text("candidate_slot_full", "Natural candidate for {group}; replace an existing part to stay legal.")
            return {"kind": "warning", "marker": "!", "hint": template.format(group=names)}
        template = self._legit_text("candidate_dependency", "Belongs to {group}, but the current pairing or dependency is not satisfied.")
        return {"kind": "warning", "marker": "!", "hint": template.format(group=names)}

    def _candidate_state_for_option(self, key, data, ref, rule_keys, groups):
        """Subclass hook for macro/dependency-aware candidate guidance."""
        return self._candidate_state(ref, rule_keys, groups)

    def _set_group_guidance(self, key, rule_keys, groups, ready):
        cfg = self._group_cfgs.get(key) or {}
        group_box = cfg.get("_group_box")
        base_title = self.ui_loc.get('groups', {}).get(cfg.get("title_key"), cfg.get("title_key", key))
        if not ready:
            if group_box is not None:
                group_box.setTitle(base_title)
            picker = self._group_pickles.get(key)
            if picker is not None:
                if hasattr(picker, "set_count_limit"):
                    picker.set_count_limit(None)
                source = []
                for item in picker._source:
                    undecorated = dict(item)
                    undecorated.pop("candidate", None)
                    source.append(undecorated)
                picker.set_source(source)
            if cfg.get("mode") == "chip" and cfg.get("_chip"):
                cfg["_chip"].set_candidate_states({})
            return

        specs = [(rule_key, groups.get(rule_key)) for rule_key in rule_keys]
        specs = [(rule_key, spec) for rule_key, spec in specs if isinstance(spec, dict)]
        visible = [
            (rule_key, spec)
            for rule_key, spec in specs
            if int(spec.get("effective_max", spec.get("max", 0))) > 0 or spec.get("selected")
        ]
        bits = []
        for rule_key, spec in visible:
            actual = len(spec.get("selected") or [])
            value = f"{actual}/{self._generation_range(spec)}"
            if len(visible) > 1:
                value = f"{self._generation_group_text(rule_key)} {value}"
            bits.append(value)
        if group_box is not None:
            group_box.setTitle(f"{base_title} · {' · '.join(bits)}" if bits else f"{base_title} · —")

        picker = self._group_pickles.get(key)
        if picker is not None:
            maximum = sum(int(spec.get("effective_max", spec.get("max", 0))) for _, spec in visible)
            if hasattr(picker, "set_count_limit"):
                picker.set_count_limit(maximum if visible else 0, self._legit_text("slot_budget_hint", "Natural slot budget"))
            source = []
            for item in picker._source:
                decorated = dict(item)
                ref = self._generation_ref_for_option(key, item.get("data"))
                decorated["candidate"] = self._candidate_state_for_option(
                    key, item.get("data"), ref, rule_keys, groups
                )
                source.append(decorated)
            picker.set_source(source)
        elif cfg.get("mode") == "chip" and cfg.get("_chip"):
            states = {}
            for pid in cfg["_chip"].option_pids():
                ref = self._generation_ref_for_option(key, pid)
                states[pid] = self._candidate_state_for_option(key, pid, ref, rule_keys, groups)
            cfg["_chip"].set_candidate_states(states)

    def _update_generation_guidance(self, decoded):
        mapping = self.RULE_GROUPS_BY_PICKER
        if not mapping or not decoded:
            return
        if self._is_gold_skin_selected():
            self.generation_status_badge.setText(self._legit_text("status_gold", "Gold skin"))
            self.generation_status_badge.setProperty("ruleStatus", "suppressed")
            self.generation_reason_label.setText(self._legit_text(
                "gold_reason",
                "Gold Skin is only a legendary-skin foundation, so natural-build guidance is disabled.",
            ))
            self.generation_groups_label.clear()
            self.generation_status_badge.setToolTip(self.generation_reason_label.text())
            self.generation_status_badge.style().unpolish(self.generation_status_badge)
            self.generation_status_badge.style().polish(self.generation_status_badge)
            for key, rule_keys in mapping.items():
                self._set_group_guidance(key, rule_keys, {}, False)
            return
        try:
            result = item_display_resolver.validate_weapon_generation(decoded, allow_incomplete=True)
        except Exception as exc:
            self.generation_status_badge.setText(self._legit_text("status_unknown", "Unknown"))
            self.generation_status_badge.setProperty("ruleStatus", "unknown")
            self.generation_reason_label.setText(str(exc))
            return
        groups = result.get("groups") or {}
        ready = bool(result.get("rules_available") and result.get("composition_ref"))
        status = str(result.get("status") or "unknown")
        status_labels = {
            "legal": self._legit_text("status_legal", "Natural"),
            "incomplete": self._legit_text("status_incomplete", "Incomplete"),
            "modified": self._legit_text("status_modified", "Modified"),
            "conditional": self._legit_text("status_conditional", "Conditional"),
            "unknown": self._legit_text("status_unknown", "Unknown"),
        }
        reasons = list(dict.fromkeys(self._generation_violation_text(item) for item in result.get("violations") or []))
        if not reasons:
            reasons = [self._legit_text("reason_legal", "Matches the current natural-generation rules.")]
        self.generation_status_badge.setText(status_labels.get(status, status_labels["unknown"]))
        self.generation_status_badge.setProperty("ruleStatus", status if status in status_labels else "unknown")
        self.generation_status_badge.style().unpolish(self.generation_status_badge)
        self.generation_status_badge.style().polish(self.generation_status_badge)
        self.generation_reason_label.setText(" · ".join(reasons[:2]))
        tooltip = "\n".join(reasons)
        self.generation_status_badge.setToolTip(tooltip)
        self.generation_reason_label.setToolTip(tooltip)

        ordered = []
        for rule_keys in mapping.values():
            for rule_key in rule_keys:
                if rule_key not in ordered:
                    ordered.append(rule_key)
        group_bits = []
        for rule_key in ordered:
            spec = groups.get(rule_key)
            if not isinstance(spec, dict):
                continue
            maximum = int(spec.get("effective_max", spec.get("max", 0)))
            actual = len(spec.get("selected") or [])
            if maximum <= 0 and actual <= 0:
                continue
            group_bits.append(
                f"{self._generation_group_text(rule_key)} {actual}/{self._generation_range(spec)}"
            )
        self.generation_groups_label.setText(" · ".join(group_bits))
        for picker_key, rule_keys in mapping.items():
            self._set_group_guidance(picker_key, rule_keys, groups, ready)

    # ------------------------------------------------------------------ #
    # Legal random generation
    # ------------------------------------------------------------------ #
    def _roll_texts(self):
        weapon = self._full_loc.get("weapon_gen_tab") or {}
        generic = self._full_loc.get("equipment_roll") or {}
        labels = weapon.get("labels") or {}
        buttons = weapon.get("buttons") or {}
        sections = weapon.get("sections") or {}
        dialogs = weapon.get("dialogs") or {}
        stat_labels = self._equipment_stat_labels()
        texts = {
            "constraints_title": sections.get("roll_options", "Roll Options"),
            "results_title": sections.get("roll_results", "Roll Results"),
            "manufacturer": labels.get("manufacturer", "Manufacturer"),
            "weapon_type": generic.get("shield_type", labels.get("weapon_type", "Type")),
            "rarity": labels.get("rarity", "Rarity"),
            "named_weapon": generic.get("named_item", labels.get("named_weapon", "Named Item")),
            "named_item": generic.get("named_item", labels.get("named_weapon", "Named Item")),
            "count": labels.get("quantity", "Quantity"),
            "random": labels.get("random", "Random"),
            "name": labels.get("name", "Name"),
            "weapon": labels.get("weapon", "Manufacturer / Type"),
            "element": labels.get("element", "Element"),
            "matches": labels.get("matches", "Matches: {count}"),
            "no_matches": labels.get("no_matches", "No matches"),
            "selected_count": labels.get("selected_count", "Selected {count} / {total}"),
            "double_click": labels.get("double_click", "Double-click a row to add it"),
            "current_context": labels.get("current_context", "Uses the current level and Flag"),
            "generated": generic.get("generated", "Generated {count} legal items"),
            "no_results": generic.get("no_results", "No generated items yet"),
            "select_result": generic.get("select_result", "Select an item from the list"),
            "no_element": labels.get("no_element", "No Element"),
            "level_value": labels.get("level_value", "Lv{level}"),
            "legal": labels.get("legal", "Legal"),
            "scope_template": labels.get(
                "scope_template",
                "Manufacturer: {manufacturer} · Type: {weapon_type} · Rarity: {rarity}",
            ),
            "roll": buttons.get("roll", "Roll"),
            "cancel": buttons.get("cancel", "Cancel"),
            "close": buttons.get("close", "Close"),
            "add_one": generic.get("add_one", buttons.get("add_one", "Add This")),
            "copy_base85": buttons.get("copy_base85", "Copy Base85"),
            "add_selected": buttons.get("add_selected", "Add Selected"),
            "add_all": buttons.get("add_all", "Add All"),
            "copied": dialogs.get("base85_copied", "Base85 copied"),
            "roll_scope_tip": dialogs.get("roll_scope_tip", ""),
            "roll_failed": dialogs.get("roll_failed", "Roll failed: {error}"),
            "roll_running": dialogs.get("roll_running", "Generating legal builds…"),
            "no_legal_result": dialogs.get("no_legal_result", "No legal build matches the filters."),
            "roll_add_start": dialogs.get("roll_add_start", "Adding {count} item(s)…"),
            "roll_add_progress": dialogs.get(
                "roll_add_progress", "Adding {current}/{total} · success {success} · failed {fail}"
            ),
            "roll_add_done": dialogs.get("roll_add_done", "Added {success}; failed {fail}"),
            "main_page": generic.get("main_page", "Main Editor"),
            "results_page": generic.get("results_page", labels.get("results_page", "Random Results")),
            "live_stats": generic.get("live_stats", "Live Stats"),
        }
        texts.update(stat_labels)
        return texts

    def _localized_item_type(self):
        key = {
            "Grenade": "grenade",
            "Shield": "shield",
            "Repkit": "repkit",
            "Heavy Weapon": "heavy_weapon",
        }.get(self.BACKPACK_TYPE_EN, "")
        return str((self._full_loc.get("tabs") or {}).get(key) or self.ITEM_LABEL)

    def _roll_type_value(self, root_id):
        return str((getattr(self, "MFG_TYPE_BASE", {}) or {}).get(int(root_id)) or self.BACKPACK_TYPE_EN)

    def _roll_type_label(self, value):
        if self.BACKPACK_TYPE_EN == "Shield" and hasattr(self, "_shield_type_text"):
            return self._shield_type_text(value)
        return self._localized_item_type()

    def _gold_composition_refs(self):
        try:
            rows = self.df_mfg[self.df_mfg["Part_type"] == "Rarity"]
        except (KeyError, TypeError):
            return set()
        refs = set()
        for _, row in rows.iterrows():
            zh = str(row.get("Description_ZH") or "").strip()
            en = str(row.get("Description_EN") or "").strip().casefold()
            if zh == "金皮肤" or en == "gold skin":
                refs.add(f"{int(row['Manufacturer ID'])}:{int(row['Part_ID'])}")
        return refs

    @staticmethod
    def _strip_skin_suffix(value):
        value = str(value or "").strip()
        value = re.sub(r"\s+skin$", "", value, flags=re.IGNORECASE)
        return value[:-2].strip() if value.endswith("皮肤") else value

    def _roll_catalog_name(self, root_id, composition_ref, composition):
        names = composition.get("name") or {}
        preferred = names.get("zh") if self.current_lang == "zh-CN" else names.get("en")
        name = str(preferred or names.get("en") or names.get("zh") or "").strip()
        if name:
            return name
        part_id = int(str(composition_ref).partition(":")[2])
        rows = self.df_mfg[
            (self.df_mfg["Manufacturer ID"] == int(root_id))
            & (self.df_mfg["Part_ID"] == part_id)
            & (self.df_mfg["Part_type"] == "Rarity")
        ]
        if rows.empty:
            return ""
        row = rows.iloc[0]
        value = row.get("Description")
        if pd.isna(value) or not str(value).strip():
            value = row.get("Description_EN")
        return self._strip_skin_suffix(value)

    def _equipment_roll_catalog(self):
        rules = (item_display_resolver._item_index().get("weapon_generation_rules") or {})
        weapons = rules.get("weapons") or {}
        gold = self._gold_composition_refs()
        taxonomy = ((self._full_loc.get("weapon_editor_tab") or {}).get("taxonomy") or {})
        catalog = []
        for root_id in self.mfg_ids:
            weapon = weapons.get(str(root_id)) or {}
            if not weapon:
                continue
            manufacturer_en = str((lookup.REVERSE_ID_MAP.get(int(root_id)) or ("Unknown",))[0])
            manufacturer_label = self._get_mfg_name(root_id)
            type_value = self._roll_type_value(root_id)
            type_label = self._roll_type_label(type_value)
            for composition_ref, composition in (weapon.get("compositions") or {}).items():
                if composition.get("availability") != "coregame" or composition_ref in gold:
                    continue
                tags = {str(tag).casefold() for tag in composition.get("base_tags") or []}
                if "npc_weapon" in tags:
                    continue
                rarity = str(composition.get("rarity") or "")
                name = self._roll_catalog_name(root_id, composition_ref, composition)
                catalog.append({
                    "root_id": str(root_id),
                    "composition_ref": str(composition_ref),
                    "manufacturer": manufacturer_en,
                    "manufacturer_label": manufacturer_label,
                    "weapon_type": type_value,
                    "weapon_type_label": type_label,
                    "rarity": rarity,
                    "rarity_label": str(taxonomy.get(rarity.casefold()) or self._(rarity)),
                    "name": name,
                    "is_named": bool(name and rarity in {"Legendary", "Pearl"}),
                })
        return catalog

    def _setup_roll_menu(self):
        if not hasattr(self, "lucky_button"):
            return
        if self._roll_options_widget is not None:
            self._roll_constraints = self._roll_options_widget.constraints()
            self._roll_count = self._roll_options_widget.count_spin.value()
        texts = self._roll_texts()
        catalog = self._equipment_roll_catalog()
        self.lucky_button.setText(f"🎲 {((self._full_loc.get('weapon_gen_tab') or {}).get('labels') or {}).get('lucky', 'Lucky')}")
        self.lucky_button.setToolTip(texts["roll_scope_tip"])
        self._roll_menu = QMenu(self.lucky_button)
        self._roll_options_widget = WeaponRollOptionsWidget(
            catalog,
            texts=texts,
            constraints=self._roll_constraints,
            count=self._roll_count,
            show_weapon_type=len({row["weapon_type"] for row in catalog}) > 1,
        )
        self._roll_options_widget.roll_requested.connect(self._roll_from_menu)
        action = QWidgetAction(self._roll_menu)
        action.setDefaultWidget(self._roll_options_widget)
        self._roll_menu.addAction(action)
        self.lucky_button.setMenu(self._roll_menu)

    @staticmethod
    def _roll_serial_token(ref, root_id):
        owner, _sep, part_id = str(ref).partition(":")
        return f"{{{part_id}}}" if owner == str(root_id) else f"{{{owner}:{part_id}}}"

    @staticmethod
    def _filter_roll_catalog(catalog, constraints):
        return [
            row for row in catalog
            if (constraints.get("manufacturer") is None or row["manufacturer"] == constraints["manufacturer"])
            and (constraints.get("weapon_type") is None or row["weapon_type"] == constraints["weapon_type"])
            and (constraints.get("rarity") is None or row["rarity"] == constraints["rarity"])
            and (constraints.get("composition_ref") is None or row["composition_ref"] == constraints["composition_ref"])
        ]

    @staticmethod
    def _roll_part_tags(ref):
        index = item_display_resolver._item_index()
        rules = index.get("weapon_generation_rules") or {}
        return (
            (rules.get("part_selection_tags") or {}).get(str(ref))
            or (index.get("part_refs") or {}).get(str(ref), {}).get("selection_tags")
            or {}
        )

    def _roll_element_text(self, decoded, root_id):
        from core import serial_inspect

        values = []
        for row in serial_inspect.part_rows(decoded, int(root_id), self.BACKPACK_TYPE_EN, self.current_lang):
            if row.get("category") not in {"element", "body_ele", "secondary_ele", "pearl_elem"}:
                continue
            if str(row.get("part") or "").casefold().endswith("part_normal"):
                continue
            name = str(row.get("name") or "").strip()
            if name and name not in values:
                values.append(name)
        return " / ".join(values)

    def _roll_one_equipment(self, candidate, rng):
        index = item_display_resolver._item_index()
        rules = index.get("weapon_generation_rules") or {}
        root_id = candidate["root_id"]
        weapon = (rules.get("weapons") or {})[root_id]
        composition = weapon["compositions"][candidate["composition_ref"]]
        selected = sample_composition_parts(
            composition=composition,
            part_types=weapon.get("part_types") or (),
            tags_for_ref=self._roll_part_tags,
            excluded_refs=set((rules.get("part_availability") or {}).keys()),
            rng=rng,
        )
        level = self.level_edit.text() if self.level_edit.text().isdigit() else self._character_level
        seed = rng.randint(100, 9999)
        refs = [candidate["composition_ref"], *selected]
        components = " ".join(self._roll_serial_token(ref, root_id) for ref in refs)
        decoded = f"{root_id}, 0, 1, {level}| 2, {seed}|| {components} |"
        serial, error = b_encoder.encode_to_base85(decoded)
        if error:
            raise ValueError(error)
        validation = item_display_resolver.validate_weapon_generation(decoded)
        if validation.get("status") != "legal":
            raise ValueError(", ".join(
                str(item.get("code")) for item in validation.get("violations") or ()
            ) or str(validation.get("status")))
        display = item_display_resolver.resolve_item_display(
            int(root_id), candidate["manufacturer"], self.BACKPACK_TYPE_EN,
            decoded, self.current_lang,
        )
        stats = item_display_resolver.resolve_equipment_stats(decoded, self.BACKPACK_TYPE_EN)
        formatted = {
            key: item_display_resolver.format_equipment_stat(key, stats.get(key), self.current_lang)
            for key in self._preview_stat_keys()
            if stats.get(key) not in (None, "")
        }
        name = str(display.get("display_name") or candidate.get("name") or "—")
        rarity = str(display.get("rarity") or candidate["rarity_label"])
        element = self._roll_element_text(decoded, root_id)
        labels = self._equipment_stat_labels()
        tooltip = [
            name,
            f"{candidate['manufacturer_label']} · {candidate['weapon_type_label']} · {rarity}",
            *(f"{labels.get(key, key)}: {value}" for key, value in formatted.items()),
            f"Base85: {serial}",
        ]
        return {
            **candidate,
            "serial": serial,
            "decoded": decoded,
            "level": level,
            "name": name,
            "manufacturer": candidate["manufacturer_label"],
            "weapon_type": candidate["weapon_type_label"],
            "rarity": rarity,
            "rarity_key": candidate["rarity"],
            "element": element,
            "status": "legal",
            "status_label": self._legit_text("status_legal", "Legal"),
            "stats": stats,
            "formatted_stats": formatted,
            "tooltip": "\n".join(tooltip),
        }

    def _roll_equipment(self, constraints, count):
        constraints = dict(constraints or {})
        count = max(1, min(50, int(count)))
        self._roll_constraints = constraints
        self._roll_count = count
        catalog = self._filter_roll_catalog(self._equipment_roll_catalog(), constraints)
        texts = self._roll_texts()
        if not catalog:
            QMessageBox.warning(self, texts["constraints_title"], texts["no_legal_result"])
            return
        rng = random.SystemRandom()
        roots = sorted({row["root_id"] for row in catalog}, key=int)
        results = []
        self.roll_results_page.set_add_status(texts["roll_running"], busy=True)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for _ in range(count):
                last_error = None
                for _attempt in range(24):
                    root_id = rng.choice(roots)
                    candidate = rng.choice([row for row in catalog if row["root_id"] == root_id])
                    try:
                        results.append(self._roll_one_equipment(candidate, rng))
                        break
                    except Exception as exc:
                        last_error = exc
                else:
                    raise RuntimeError(last_error or "no legal result")
        except Exception as exc:
            self.roll_results_page.set_add_status("", busy=False)
            QMessageBox.critical(
                self, texts["constraints_title"], texts["roll_failed"].format(error=exc)
            )
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.roll_results_page.set_results(
            results,
            texts["generated"].format(count=len(results)),
            self._roll_scope_text(constraints),
        )
        self.roll_results_page.set_add_status("", busy=False)
        self._set_workspace_page(1)

    def _roll_scope_text(self, constraints):
        texts = self._roll_texts()
        catalog = self._equipment_roll_catalog()

        def label(field, label_field):
            value = constraints.get(field)
            if value is None:
                return texts["random"]
            row = next((item for item in catalog if item.get(field) == value), None)
            return str((row or {}).get(label_field) or value)

        return texts["scope_template"].format(
            manufacturer=label("manufacturer", "manufacturer_label"),
            weapon_type=label("weapon_type", "weapon_type_label"),
            rarity=label("rarity", "rarity_label"),
        )

    def _quick_roll(self, _checked=False):
        if self._roll_options_widget is None:
            self._roll_equipment({}, self._roll_count)
            return
        self._roll_equipment(
            self._roll_options_widget.constraints(), self._roll_options_widget.count_spin.value()
        )

    def _roll_from_menu(self, constraints, count):
        if self._roll_menu is not None:
            self._roll_menu.hide()
        self._roll_equipment(constraints, count)

    def _request_roll_add(self, serials):
        if not serials or self._roll_add_busy:
            return
        self._roll_add_busy = True
        texts = self._roll_texts()
        self.roll_results_page.set_add_status(
            texts["roll_add_start"].format(count=len(serials)), busy=True
        )
        self.batch_add_to_backpack_requested.emit(
            list(serials), self.flag_combo.currentText().split(" ")[0]
        )

    def update_roll_add_progress(self, current, total, success, fail):
        self.roll_results_page.set_add_status(
            self._roll_texts()["roll_add_progress"].format(
                current=current, total=total, success=success, fail=fail
            ),
            busy=True,
        )

    def finalize_roll_batch_add(self, success, fail):
        self._roll_add_busy = False
        self.roll_results_page.set_add_status(
            self._roll_texts()["roll_add_done"].format(success=success, fail=fail),
            busy=False,
        )

    def reject_roll_batch_add(self, message):
        self._roll_add_busy = False
        self.roll_results_page.set_add_status(str(message), busy=False)

    def _set_workspace_page(self, index):
        index = 1 if int(index) == 1 else 0
        self.page_stack.setCurrentIndex(index)
        self.editor_page_button.setChecked(index == 0)
        self.roll_results_button.setChecked(index == 1)

    def _default_new_header(self, mfg_id, level):
        return f"{mfg_id}, 0, 1, {level}| 2, {self._source_seed}"

    def _build_skill_parts(self, mfg_id):  # pragma: no cover - abstract
        raise NotImplementedError

    # -- helpers available to subclasses ---------------------------------- #
    def _checked_part_ids(self, *keys):
        ids = []
        for key in keys:
            cfg = self._group_cfgs.get(key, {})
            if cfg.get("mode") == "chip":
                pid = cfg["_chip"].selected_pid()
                if pid:
                    ids.append(pid)
                continue
            for w in self._group_widgets.get(key, []):
                if w.isChecked() and w.property("part_id"):
                    ids.append(w.property("part_id"))
        return ids

    def _picker_entries(self, key):
        picker = self._group_pickles.get(key)
        return picker.entries() if picker is not None else []

    @staticmethod
    def _count_of(entry):
        return entry.get("count", 1)

    def _selected_button_pid(self, key):
        cfg = self._group_cfgs.get(key, {})
        if cfg.get("mode") == "chip":
            return cfg["_chip"].selected_pid()
        for w in self._group_widgets.get(key, []):
            if w.isChecked() and w.property("part_id"):
                return w.property("part_id")
        return None

    def _select_group_pid(self, key, pid):
        """Select a radio/chip option by part id. Returns True if matched."""
        cfg = self._group_cfgs.get(key, {})
        if cfg.get("mode") == "chip":
            return cfg["_chip"].select_pid(pid)
        for w in self._group_widgets.get(key, []):
            if w.property("part_id") == pid:
                w.setChecked(True)
                return True
        return False

    # ------------------------------------------------------------------ #
    # Import / reset
    # ------------------------------------------------------------------ #
    def _import_from_backpack(self):
        texts = source_texts(self.current_lang)
        if self.main_app is None or not hasattr(self.main_app, 'get_items_snapshot'):
            QMessageBox.warning(self, texts['import_error'], texts['no_save'])
            return
        item = choose_backpack_item(
            self,
            self.main_app.get_items_snapshot(),
            self._backpack_predicate,
            title=texts['backpack_title'],
            search_placeholder=texts['search'],
        )
        if not item:
            return
        try:
            self._load_serial_copy(item.get('serial', ''), name=item.get('name') or self.ITEM_LABEL, state_flags=item.get('state_flags'))
        except ValueError as exc:
            self._reset_import_source()
            QMessageBox.warning(self, texts['import_error'], str(exc))

    def _backpack_predicate(self, value):
        return value.get('type_en') == self.BACKPACK_TYPE_EN and value.get('container') == 'Backpack'

    def _import_from_base85(self):
        texts = source_texts(self.current_lang)
        serial = prompt_base85(self, title=texts['base85_title'], label=texts['base85_label'])
        if not serial:
            return
        try:
            self._load_serial_copy(serial, name="Base85")
        except ValueError as exc:
            self._reset_import_source()
            QMessageBox.warning(self, texts['import_error'], str(exc))

    def open_item_serial(self, item: dict):
        flags = item.get('state_flags')
        try:
            flags = int(str(flags).strip()) if str(flags).strip() else None
        except ValueError:
            flags = None
        self._load_serial_copy(item.get('serial', ''), name=item.get('name', ''), state_flags=flags)

    def _load_serial_copy(self, serial, *, name="", state_flags=None, source_name=None):
        parsed = split_decoded(decode_base85(serial))
        if parsed['mfg_id'] not in self.mfg_ids:
            raise ValueError(source_texts(self.current_lang)['wrong_type'])
        if source_name is not None:
            name = source_name
        self._loading_import = True
        try:
            self._imported_copy = True
            self._source_seed = parsed['seed']
            self._source_header = parsed
            self._source_name = name
            self._preserved_tokens = []
            self._preserved_children = self._initial_preserved_children()
            self._extra_reset_state()
            mfg_index = next(
                (i for i in range(self.mfg_combo.count())
                 if self.mfg_combo.itemText(i).rstrip().endswith(f" - {parsed['mfg_id']}")),
                -1,
            )
            if mfg_index < 0:
                raise ValueError(source_texts(self.current_lang)['wrong_type'])
            self.mfg_combo.setCurrentIndex(mfg_index)
            self.on_mfg_change()
            self.level_edit.setText(str(parsed['level']))
            self.rarity_combo.setCurrentIndex(-1)
            self._clear_import_widgets()
            self._apply_components(parsed['component'])
            self._set_flag_value(state_flags)
        finally:
            self._loading_import = False
        self._update_source_bar()
        self.rebuild_output()
        if self._encode_error:
            raise ValueError(f"The imported {self.ITEM_LABEL} could not be rebuilt.")
        return True

    def _initial_preserved_children(self):
        return {}

    def _apply_components(self, component):  # pragma: no cover - abstract
        raise NotImplementedError

    def _clear_import_widgets(self):
        for key, cfg in self._group_cfgs.items():
            mode = cfg.get("mode", "picker")
            if mode == "chip":
                cfg["_chip"].select_none()
            elif mode == "radio":
                none_rb = next((w for w in self._group_widgets.get(key, []) if not w.property('part_id')), None)
                if none_rb:
                    none_rb.setChecked(True)
            elif mode == "checkbox":
                for w in self._group_widgets.get(key, []):
                    w.setChecked(False)
        for picker in self._group_pickles.values():
            picker.clear()

    def _reset_import_source(self):
        self._loading_import = True
        try:
            self._imported_copy = False
            self._source_seed = self.DEFAULT_SEED
            self._source_header = None
            self._source_name = ""
            self._preserved_tokens = []
            self._preserved_children = self._initial_preserved_children()
            self._extra_reset_state()
            self.mfg_combo.setEnabled(True)
            self.level_edit.setText(self._character_level)
            self.on_mfg_change()
            self._clear_import_widgets()
            self._populate_flags()
        finally:
            self._loading_import = False
        self._update_source_bar()
        self.rebuild_output()

    def _extra_reset_state(self):
        """Hook for subclass import-state reset."""

    def _update_source_bar(self):
        if not hasattr(self, 'source_bar'):
            return
        texts = source_texts(self.current_lang)
        self.source_bar.backpack_btn.setText(texts['backpack'])
        self.source_bar.base85_btn.setText(texts['base85'])
        self.source_bar.reset_btn.setText(texts['reset'])
        if self._imported_copy:
            name = self._source_name or "Base85"
            self.source_bar.set_source(texts['imported'].format(name=name), imported=True)
        else:
            self.source_bar.set_source(texts['new_source'], imported=False)
        self.mfg_combo.setEnabled(not self._imported_copy)

    # -- import lookup helpers -------------------------------------------- #
    def _rarity_index_map(self):
        return {
            int(self.rarity_combo.itemData(i)): i
            for i in range(self.rarity_combo.count())
            if self.rarity_combo.itemData(i) is not None
        }

    def _button_pid_map(self, key):
        cfg = self._group_cfgs.get(key, {})
        if cfg.get("mode") == "chip":
            return {int(pid): pid for pid in cfg["_chip"].option_pids()}
        return {
            int(w.property('part_id')): w
            for w in self._group_widgets.get(key, [])
            if w.property('part_id')
        }

    def _picker_item_map(self, key):
        """Map a picker group's source data-payload -> item dict (for re-add)."""
        picker = self._group_pickles.get(key)
        result = {}
        if picker is None:
            return result
        for it in picker._source:  # source dicts carry our custom payload
            data = it.get("data")
            if data is None:
                continue
            result[self._picker_data_key(data)] = it
        return result

    @staticmethod
    def _picker_data_key(data):
        if isinstance(data, tuple):
            return tuple(int(x) for x in data)
        try:
            return int(data)
        except (TypeError, ValueError):
            return data

    def _picker_add(self, key, item, count=1):
        picker = self._group_pickles.get(key)
        if picker is not None and item is not None:
            picker.add_item(item, count=count)

    # ------------------------------------------------------------------ #
    # Misc
    # ------------------------------------------------------------------ #
    def _set_flag_value(self, value):
        select_flag_value(self.flag_combo, value)

    def _populate_flags(self):
        self.flag_combo.clear()
        flags_map = resource_loader.get_flag_labels(self.current_lang)
        flag_values = [flags_map[k] for k in ("1", "3", "5", "17", "33", "65", "129")]
        self.flag_combo.addItems(flag_values)
        for i in range(self.flag_combo.count()):
            if flags_map["3"] == self.flag_combo.itemText(i):
                self.flag_combo.setCurrentIndex(i)
                break

    def _copy_to_clipboard(self, line_edit):
        QApplication.clipboard().setText(line_edit.text())
        QMessageBox.information(self, self.ui_loc['dialogs']['success'], self.ui_loc['dialogs']['copied'])

    def _add_to_backpack(self):
        serial = self.b85_output_edit.text()
        if not serial or getattr(self, '_encode_error', False):
            QMessageBox.warning(self, self.ui_loc['dialogs']['no_valid_code'], self.ui_loc['dialogs']['gen_first'])
            return
        self.add_to_backpack_requested.emit(serial, self.flag_combo.currentText().split(" ")[0])

    def set_character_level(self, level: str):
        self._character_level = level if level else "50"
        if hasattr(self, 'level_edit') and not self._imported_copy:
            self.level_edit.setText(self._character_level)

    # ------------------------------------------------------------------ #
    # Language
    # ------------------------------------------------------------------ #
    def update_language(self, lang):
        imported_serial = self.b85_output_edit.text() if getattr(self, '_imported_copy', False) else ""
        imported_name = getattr(self, '_source_name', '')
        imported_flag = self.flag_combo.currentText().split(" ")[0] if hasattr(self, 'flag_combo') else None
        self.current_lang = lang
        self.df_main, self.df_mfg, self.localization = self.load_data(lang)
        if self.df_main is None:
            return
        self._load_ui_localization()
        if not self.ui_loc:
            return
        # static texts
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
        # group titles + picker texts
        for key, cfg in self._group_cfgs.items():
            title = self.ui_loc['groups'].get(cfg["title_key"], cfg["title_key"])
            mode = cfg.get("mode", "picker")
            cfg["_group_box"].setTitle(title)
            if mode in ("picker", "inline"):
                picker = self._group_pickles[key]
                picker.set_search_placeholder(self._search_placeholder())
                picker.clear_btn.setText(self.ui_loc['buttons'].get('clear', 'Clear'))
                if mode == "picker":
                    picker.add_sel_btn.setText(self._add_selected_text())
                    picker._sel_title = title
                    picker._update_count()
        self._populate_flags()
        self._update_language_texts_extra()
        self._refresh_roll_language()
        # data refresh
        self.mfg_combo.blockSignals(True)
        self.populate_initial_data()
        self.mfg_combo.blockSignals(False)
        if imported_serial:
            try:
                self._load_serial_copy(imported_serial, name=imported_name, state_flags=imported_flag)
            except ValueError as exc:
                print(f"DEBUG: restore after language change failed: {exc}")
                self._reset_import_source()
        else:
            self.on_mfg_change()
            self._update_source_bar()

    def _refresh_roll_language(self):
        if not hasattr(self, "editor_page_button"):
            return
        texts = self._roll_texts()
        self.editor_page_button.setText(texts["main_page"])
        self.roll_results_button.setText(texts["results_page"])
        self.stats_preview_title.setText(texts["live_stats"])
        self.roll_results_page.update_texts(texts)
        self.roll_results_page.set_results([], texts["no_results"], "")
        self._setup_roll_menu()
        self._update_equipment_stats(self.raw_output_edit.text())
        self._set_workspace_page(0)

    def _update_language_texts_extra(self):
        """Hook for subclass-specific language-refresh."""
