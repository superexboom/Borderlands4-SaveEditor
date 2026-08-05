"""Base class for part-based equipment editor tabs.

Unifies the four previously copy-pasted tabs (grenade / shield / repkit /
heavy weapon) behind a single implementation. Subclasses declare their data
source and perk-group layout, and override a handful of hooks for the bits
that genuinely differ (serial assembly, import-token application, mfg change).

UI uses the modern catalog/chip pickers from ``qt_catalog_picker`` instead of
the old scrollable radio-button lists and dual-list "»/«" transfer boxes.
"""

import re

import pandas as pd
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QLineEdit, QPushButton, QGroupBox, QComboBox, QRadioButton, QCheckBox,
    QListWidgetItem, QScrollArea, QMessageBox, QSpinBox,
)
from PyQt6.QtCore import pyqtSignal, Qt

from core import b_encoder
from core import resource_loader
from core import lookup
from core import bl4_functions as bl4f
from core import item_display_resolver
from tabs.qt_catalog_picker import (
    CatalogPicker,
    InlineCatalogPicker,
    ContainedWheelListWidget,
    ContainedWheelScrollArea,
)
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
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.combo = QComboBox()
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
        for pid, label in options:
            self.combo.addItem(label, pid)
            idx = self.combo.count() - 1
            self.combo.setItemData(idx, label, Qt.ItemDataRole.ToolTipRole)
        match = next(
            (index for index in range(self.combo.count()) if self.combo.itemData(index) == selected),
            0,
        )
        self.combo.setCurrentIndex(match)
        self.combo.blockSignals(False)

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

    # --- subclass-provided class attributes -------------------------------
    EQUIP_TYPE = ""
    UI_LOC_KEY = ""
    DEFAULT_SEED = 305
    MFG_IDS = []
    BACKPACK_TYPE_EN = ""
    ITEM_LABEL = "Item"

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
        self.ui_loc = full_loc.get(self.UI_LOC_KEY, {})

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
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        main_layout.addWidget(scroll)
        container = QWidget(); scroll.setWidget(container)
        layout = QVBoxLayout(container)

        self._create_source_bar(layout)
        self._create_output_group(layout)
        self._create_top_controls(layout)

        self.perks_group = QGroupBox(self.ui_loc['groups']['perks'])
        perks_layout = QGridLayout(self.perks_group)
        self._build_perk_groups(perks_layout)
        layout.addWidget(self.perks_group)
        layout.addStretch()

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
        self.flag_combo = QComboBox()
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
        self.mfg_combo = QComboBox()
        self.level_edit = QLineEdit(self._character_level)
        self.rarity_combo = QComboBox()
        self.level_edit.setFixedWidth(100)
        self.rarity_combo.setFixedWidth(300)
        self.mfg_label = QLabel(self.ui_loc['labels']['manufacturer'])
        self.level_label = QLabel(self.ui_loc['labels']['level'])
        self.rarity_label = QLabel(self.ui_loc['labels']['rarity'])
        controls_layout.addWidget(self.mfg_label); controls_layout.addWidget(self.mfg_combo)
        controls_layout.addWidget(self.level_label); controls_layout.addWidget(self.level_edit)
        controls_layout.addWidget(self.rarity_label); controls_layout.addWidget(self.rarity_combo)
        controls_layout.addStretch()
        layout.addWidget(self.base_attrs_group)

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
        items = [(f"{self._get_mfg_name(k)} - {k}", k) for k in self.mfg_ids]
        items.sort(key=lambda x: x[1])
        self.mfg_combo.addItems([x[0] for x in items])
        self.mfg_combo.blockSignals(False)
        self._populate_initial_extra()

    def _populate_initial_extra(self):
        """Hook: populate mfg-independent groups (element/firmware/etc)."""

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
        for _, r in self.df_mfg[(self.df_mfg['Manufacturer ID'] == mfg_id) & (self.df_mfg['Part_type'] == 'Rarity')].iterrows():
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
            self._refresh_dynamic_descriptions()
        except Exception as e:
            print(f"Rebuild error ({self.EQUIP_TYPE}): {e}")

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

    def _update_language_texts_extra(self):
        """Hook for subclass-specific language-refresh."""
