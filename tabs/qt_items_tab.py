from html import escape
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from core import item_display_resolver, resource_loader


WEAPON_CARD_TYPE_ICONS = {
    "Pistol": "ico_art_item_card_weap_pistol.png",
    "Shotgun": "ico_art_item_card_weap_shotgun.png",
    "SMG": "ico_art_item_card_weap_smg.png",
    "Assault Rifle": "ico_art_item_card_weap_assault.png",
    "Sniper": "ico_art_item_card_weap_sniper.png",
}
WEAPON_CARD_PRIMARY_STATS = (
    ("damage", "ico_ui_art_wpn_dmg.png"),
    ("accuracy", "ico_ui_art_wpn_prmry_accuracy.png"),
    ("reload_time", "ico_ui_art_wpn_prmry_reload_time.png"),
    ("fire_rate", "ico_ui_art_wpn_prmry_fire_rate.png"),
    ("magazine", "ico_ui_art_wpn_prmry_mag_size.png"),
)
WEAPON_CARD_SECONDARY_ICONS = {
    "critical_damage": "ico_ui_art_wpn_scndry_crit_hit_dmg.png",
    "ammo_cost": "ico_ui_art_wpn_scndry_ammo_per_shot.png",
    "splash_radius": "ico_ui_art_wpn_scndry_dmg_radius.png",
}
WEAPON_CARD_RARITY_COLORS = {
    "common": "#FFFFFF",
    "普通": "#FFFFFF",
    "uncommon": "#209A30",
    "罕见": "#209A30",
    "rare": "#0074F9",
    "稀有": "#0074F9",
    "epic": "#9747FF",
    "史诗": "#9747FF",
    "legendary": "#E0A100",
    "传奇": "#E0A100",
    "pearl": "#17B7B5",
    "珠光": "#17B7B5",
}


def _weapon_card_rarity_color(rarity: Any) -> str:
    return WEAPON_CARD_RARITY_COLORS.get(str(rarity or "").strip().casefold(), "#78909C")


def _secondary_stat_keys(stats: Dict[str, Any]) -> List[str]:
    return [
        key
        for key, visible in (
            ("critical_damage", stats.get("critical_damage") not in (None, "", 0, 0.0)),
            ("ammo_cost", (stats.get("ammo_cost") or 0) > 1),
            ("splash_radius", stats.get("splash_radius") not in (None, "", 0, 0.0)),
        )
        if visible
    ]


def weapon_card_html(
    item: Dict[str, Any],
    current_lang: str,
    level_label: str,
    stat_labels: Optional[Dict[str, str]] = None,
) -> str:
    stats = item.get("weapon_stats") or {}
    weapon_icon = WEAPON_CARD_TYPE_ICONS.get(item.get("type_en", ""))
    if not stats or not weapon_icon:
        return ""
    weapon_icon_width = 120 if item.get("type_en") == "Pistol" else 180

    def image_uri(folder: str, filename: str) -> str:
        return resource_loader.get_resource_path(f"assets/{folder}/{filename}").as_uri()

    def value(key: str) -> str:
        formatted = item_display_resolver.format_weapon_stat(key, stats.get(key), current_lang)
        return escape(formatted or "-")

    primary_cells = "".join(
        f"<td width='100' align='center' valign='middle'>"
        f"<img src='{image_uri('item_stats_icon', icon)}' width='36' height='36'><br>"
        f"<nobr><span style='font-size:18px; color:#eef5f6'>{value(key)}</span></nobr></td>"
        for key, icon in WEAPON_CARD_PRIMARY_STATS
    )
    secondary_keys = _secondary_stat_keys(stats)
    secondary_cells = "".join(
        f"<td width='{500 // len(secondary_keys)}' align='center' valign='middle'>"
        f"<img src='{image_uri('item_stats_icon', WEAPON_CARD_SECONDARY_ICONS[key])}' width='38' height='38'><br>"
        f"<nobr><span style='font-size:18px; color:#eef5f6'>{value(key)}</span></nobr></td>"
        for key in secondary_keys
    )
    secondary_row = (
        f"<tr><td colspan='2' bgcolor='#0d2d38'><table width='500' cellspacing='0' cellpadding='5'>"
        f"<tr>{secondary_cells}</tr></table></td></tr>"
        if secondary_cells
        else ""
    )
    rarity = item.get("rarity")
    rarity_color = _weapon_card_rarity_color(rarity)
    identity = " · ".join(
        escape(str(part)) for part in (item.get("manufacturer"), item.get("type")) if part
    )
    meta_parts = []
    if identity:
        meta_parts.append(f"<span style='font-size:13px; color:#c9d4d7'>{identity}</span>")
    if rarity:
        meta_parts.append(
            f"<span style='font-size:13px; font-weight:600; color:{rarity_color}'>{escape(str(rarity))}</span>"
        )
    meta = " · ".join(meta_parts)
    level = escape(str(item.get("level", "")))
    level_text = f"{level}级" if current_lang == "zh-CN" else f"{escape(level_label)} {level}"
    dps = item_display_resolver.format_weapon_stat("dps", stats.get("dps"), current_lang)
    dps_label = (stat_labels or {}).get("dps", "DPS")
    dps_line = (
        f"<br><span style='font-size:22px; color:#f3ead1'>{escape(dps)}</span> "
        f"<span style='font-size:13px; color:#aebfc3'>{escape(dps_label)}</span>"
        if dps
        else ""
    )
    return (
        f"<table width='526' cellspacing='0' cellpadding='2' bgcolor='{rarity_color}'>"
        "<tr><td>"
        "<table width='520' cellspacing='0' cellpadding='0' bgcolor='#0a222b' "
        "style=\"font-family:'Microsoft YaHei UI','Segoe UI';\">"
        f"<tr><td colspan='2' height='3' bgcolor='{rarity_color}'></td></tr>"
        "<tr><td width='325' valign='top' style='padding:12px'>"
        f"<span style='font-size:20px; font-weight:600; color:#f3ead1'>{escape(str(item.get('name') or '-'))}</span><br>"
        f"{meta}{dps_line}"
        "</td><td width='195' align='right' valign='top' style='padding:8px'>"
        f"<span style='font-size:18px; color:#e5ecee'>{level_text}</span><br>"
        f"<img src='{image_uri('item_card_type', weapon_icon)}' width='{weapon_icon_width}'>"
        "</td></tr>"
        "<tr><td colspan='2' bgcolor='#103b49'><table width='500' cellspacing='0' cellpadding='6'>"
        f"<tr>{primary_cells}</tr></table></td></tr>"
        f"{secondary_row}"
        f"<tr><td colspan='2' height='2' bgcolor='{rarity_color}'></td></tr>"
        "</table></td></tr></table>"
    )


class QtItemsTab(QWidget):
    add_item_requested = pyqtSignal(str, str)

    COLUMN_KEYS = [
        ("name", "name"),
        ("type", "type"),
        ("manufacturer", "manufacturer"),
        ("rarity", "rarity"),
        ("level", "level"),
        ("flags", "state_flags"),
        ("serial", "serial"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_lang = "zh-CN"
        self._load_localization()

        self.model = QStandardItemModel()
        self.model.setHorizontalHeaderLabels(self._headers())
        self.item_lookup: Dict[int, Dict[str, Any]] = {}
        self.current_selected_item: Optional[Dict[str, Any]] = None

        self.ui_labels: Dict[str, QLabel] = {}
        self.ui_buttons: Dict[str, QPushButton] = {}
        self.ui_placeholders: Dict[str, QLineEdit] = {}

        main_layout = QVBoxLayout(self)
        self._create_add_item_bar(main_layout)

        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText(self.loc["search_placeholder"])
        self.search_entry.textChanged.connect(self.filter_tree)
        main_layout.addWidget(self.search_entry)

        self.tree_view = QTreeView()
        self.tree_view.setModel(self.model)
        self.tree_view.setAlternatingRowColors(True)
        self.tree_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_view.customContextMenuRequested.connect(self._show_context_menu)
        self.tree_view.selectionModel().selectionChanged.connect(self.on_item_selected)
        header = self.tree_view.header()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(60)
        self.tree_view.horizontalScrollBar().setTracking(False)
        main_layout.addWidget(self.tree_view, 1)

    def _headers(self) -> List[str]:
        cols = self.loc["columns"]
        return [cols.get(key, key) for key, _ in self.COLUMN_KEYS]

    def _create_add_item_bar(self, layout: QVBoxLayout):
        add_item_frame = QWidget()
        add_item_layout = QHBoxLayout(add_item_frame)
        add_item_layout.setContentsMargins(0, 0, 0, 0)

        self.ui_labels["label_serial"] = QLabel(self.loc["add_item"]["label_serial"])
        add_item_layout.addWidget(self.ui_labels["label_serial"])

        self.add_serial_entry = QLineEdit()
        self.add_serial_entry.setPlaceholderText(self.loc["add_item"]["placeholder_serial"])
        self.ui_placeholders["add_serial"] = self.add_serial_entry
        add_item_layout.addWidget(self.add_serial_entry, 1)

        self.ui_labels["label_flag"] = QLabel(self.loc["add_item"]["label_flag"])
        add_item_layout.addWidget(self.ui_labels["label_flag"])

        self.add_flag_combo = QComboBox()
        self._populate_flags()
        add_item_layout.addWidget(self.add_flag_combo)

        self.ui_buttons["button_add"] = QPushButton(self.loc["add_item"]["button_add"])
        self.ui_buttons["button_add"].clicked.connect(self._on_add_item_clicked)
        add_item_layout.addWidget(self.ui_buttons["button_add"])

        layout.addWidget(add_item_frame)

    def _populate_flags(self):
        self.add_flag_combo.clear()
        flags = self.loc["add_item"]["flags"]
        self.add_flag_combo.addItems(
            [flags["1"], flags["3"], flags["5"], flags["17"], flags["33"], flags["65"], flags["129"]]
        )

    def update_tree(self, items: List[Dict[str, Any]]):
        self.model.clear()
        self.model.setHorizontalHeaderLabels(self._headers())
        self.item_lookup.clear()
        self.current_selected_item = None

        if not items:
            return

        items_by_container: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
        for i, item in enumerate(items):
            self.item_lookup[i] = item
            container_name = self._container_display(item.get("container"))
            item_type = item.get("type", self.loc["defaults"]["unknown_type"])
            items_by_container.setdefault(container_name, {}).setdefault(item_type, []).append(item)

        root_node = self.model.invisibleRootItem()
        for container_name, types_dict in sorted(items_by_container.items()):
            container_node = self._group_row(container_name)
            root_node.appendRow(container_node)

            for item_type, item_list in sorted(types_dict.items()):
                type_node = self._group_row(f"{item_type} ({len(item_list)})")
                container_node[0].appendRow(type_node)

                for item in sorted(item_list, key=self._slot_sort_key):
                    type_node[0].appendRow(self._item_row(item, container_name))

        self.tree_view.expandAll()
        self._collapse_default_groups()
        self._resize_columns()
        if self.search_entry.text():
            self.filter_tree(self.search_entry.text())

    def _group_row(self, text: str) -> List[QStandardItem]:
        row = [QStandardItem(text)]
        row.extend(QStandardItem("") for _ in range(len(self.COLUMN_KEYS) - 1))
        for item in row:
            item.setEditable(False)
        return row

    def _item_row(self, item: Dict[str, Any], container_name: str) -> List[QStandardItem]:
        row: List[QStandardItem] = []
        for key, data_key in self.COLUMN_KEYS:
            value = self._column_value(item, key, data_key, container_name)
            cell = QStandardItem(value)
            cell.setEditable(False)
            row.append(cell)
        card = self._weapon_card_html(item)
        for cell in row:
            cell.setToolTip(card)
        row[0].setData(item, Qt.ItemDataRole.UserRole)
        return row

    def _weapon_card_html(self, item: Dict[str, Any]) -> str:
        return weapon_card_html(item, self.current_lang, self.loc["columns"]["level"], self.loc["columns"])

    @staticmethod
    def _slot_sort_key(item: Dict[str, Any]):
        slot = str(item.get("slot", ""))
        if slot.startswith("slot_"):
            try:
                return (0, int(slot.removeprefix("slot_")))
            except ValueError:
                pass
        return (1, str(item.get("name", "")))

    def _column_value(self, item: Dict[str, Any], key: str, data_key: str, container_name: str) -> str:
        if key == "flags":
            return self._flag_display(item.get(data_key, ""))
        return str(item.get(data_key, "") or "")

    def _flag_display(self, flag: Any) -> str:
        text = self.loc.get("add_item", {}).get("flags", {}).get(str(flag), str(flag or ""))
        if "(" in text and ")" in text:
            return text.split("(", 1)[1].split(")", 1)[0]
        return text

    def _container_display(self, container_raw: Any) -> str:
        if not container_raw:
            return self.loc["defaults"]["unknown_container"]
        return self.loc.get("containers", {}).get(container_raw, str(container_raw))

    def _collapse_default_groups(self):
        containers_loc = self.loc.get("containers", {})
        collapsed_names = {
            containers_loc.get("Lost Loot", "Lost Loot"),
            containers_loc.get("Equipped", "Equipped"),
        }
        root = self.model.invisibleRootItem()
        for i in range(root.rowCount()):
            item = root.child(i)
            if item.text() in collapsed_names:
                self.tree_view.collapse(self.model.indexFromItem(item))

    def _resize_columns(self):
        header = self.tree_view.header()
        flexible_columns = []
        for i in range(self.model.columnCount()):
            if self.COLUMN_KEYS[i][0] == "serial":
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
                self.tree_view.setColumnWidth(i, self.tree_view.fontMetrics().horizontalAdvance("0" * 20) + 20)
            else:
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
                self.tree_view.resizeColumnToContents(i)
                width = self.tree_view.columnWidth(i) + 30
                if self.COLUMN_KEYS[i][0] == "name":
                    width += 40
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
                self.tree_view.setColumnWidth(i, width)
                flexible_columns.append(i)
        extra = self.tree_view.viewport().width() - sum(self.tree_view.columnWidth(i) for i in range(self.model.columnCount()))
        if extra > 0 and flexible_columns:
            add = extra // len(flexible_columns)
            for i in flexible_columns:
                self.tree_view.setColumnWidth(i, self.tree_view.columnWidth(i) + add)

    def on_item_selected(self, selected, _deselected):
        indexes = selected.indexes()
        self.current_selected_item = self._item_data_from_index(indexes[0]) if indexes else None

    def _item_data_from_index(self, index: QModelIndex) -> Optional[Dict[str, Any]]:
        cursor = index
        while cursor.isValid():
            data = self.model.data(cursor.siblingAtColumn(0), Qt.ItemDataRole.UserRole)
            if data:
                return data
            cursor = cursor.parent()
        return None

    def _show_context_menu(self, pos):
        item = self._item_data_from_index(self.tree_view.indexAt(pos))
        if not item:
            return

        actions = self.loc.get("actions", {})
        menu = QMenu(self)
        copy_name = menu.addAction(actions.get("copy_name", "Copy name"))
        copy_serial = menu.addAction(actions.get("copy_serial", "Copy serial"))
        copy_decoded = menu.addAction(actions.get("copy_decoded", "Copy decoded"))
        copy_parts = menu.addAction(actions.get("copy_parts", "Copy parts"))

        selected = menu.exec(self.tree_view.viewport().mapToGlobal(pos))
        if selected == copy_name:
            self._copy_text(item.get("name", ""))
        elif selected == copy_serial:
            self._copy_text(item.get("serial", ""))
        elif selected == copy_decoded:
            self._copy_text(item.get("decoded_full", ""))
        elif selected == copy_parts:
            self._copy_text(item.get("decoded_parts", ""))

    def _copy_text(self, text: Any):
        QApplication.clipboard().setText(str(text or ""))

    def _load_localization(self):
        filename = resource_loader.get_ui_localization_file(self.current_lang)
        data = resource_loader.load_json_resource(filename)
        if data and "items_tab" in data:
            self.loc = data["items_tab"]
            return

        self.loc = {
            "columns": {
                "name": "Name",
                "type": "Type",
                "manufacturer": "Manufacturer",
                "rarity": "Rarity",
                "level": "Level",
                "flags": "Flags",
                "damage": "Damage",
                "dps": "DPS",
                "accuracy": "Accuracy",
                "fire_rate": "Fire Rate",
                "reload_time": "Reload",
                "magazine": "Magazine",
                "critical_damage": "Critical Damage",
                "ammo_cost": "Ammo Cost",
                "splash_radius": "Splash Radius",
                "ads_time": "ADS Time",
                "equip_time": "Equip Time",
                "serial": "Serial",
            },
            "containers": {"Backpack": "Backpack", "Bank": "Bank", "Lost Loot": "Lost Loot", "Equipped": "Equipped"},
            "search_placeholder": "Search items...",
            "add_item": {
                "label_serial": "Serial:",
                "placeholder_serial": "Enter code...",
                "label_flag": "Flag:",
                "button_add": "Add",
                "flags": {"1": "1", "3": "3", "5": "5", "17": "17", "33": "33", "65": "65", "129": "129"},
            },
            "actions": {
                "copy_name": "Copy name",
                "copy_serial": "Copy serial",
                "copy_decoded": "Copy decoded",
                "copy_parts": "Copy parts",
            },
            "defaults": {"unknown_container": "Unknown", "unknown_type": "Unknown"},
            "dialogs": {"input_error": "Error", "enter_serial": "Enter serial"},
        }

    def update_language(self, lang):
        self.current_lang = lang
        self._load_localization()
        self.model.setHorizontalHeaderLabels(self._headers())
        self.ui_labels["label_serial"].setText(self.loc["add_item"]["label_serial"])
        self.ui_placeholders["add_serial"].setPlaceholderText(self.loc["add_item"]["placeholder_serial"])
        self.ui_labels["label_flag"].setText(self.loc["add_item"]["label_flag"])
        self.ui_buttons["button_add"].setText(self.loc["add_item"]["button_add"])
        self.search_entry.setPlaceholderText(self.loc["search_placeholder"])
        self._populate_flags()
        self._resize_columns()

    def _on_add_item_clicked(self):
        serial = self.add_serial_entry.text().strip()
        if not serial:
            QMessageBox.warning(self, self.loc["dialogs"]["input_error"], self.loc["dialogs"]["enter_serial"])
            return
        flag = self.add_flag_combo.currentText().split(" ")[0]
        self.add_item_requested.emit(serial, flag)

    def filter_tree(self, text: str):
        query = text.lower().strip()
        root = self.model.invisibleRootItem()

        for i in range(root.rowCount()):
            container_item = root.child(i)
            container_is_visible = False

            for j in range(container_item.rowCount()):
                type_item = container_item.child(j)
                type_is_visible = False

                for k in range(type_item.rowCount()):
                    haystack = self._row_search_text(type_item, k)
                    is_match = not query or query in haystack
                    self.tree_view.setRowHidden(k, type_item.index(), not is_match)
                    if is_match:
                        type_is_visible = True

                self.tree_view.setRowHidden(j, container_item.index(), not type_is_visible)
                if type_is_visible:
                    container_is_visible = True

            self.tree_view.setRowHidden(i, root.index(), not container_is_visible)

    def _row_search_text(self, parent: QStandardItem, row: int) -> str:
        values = []
        for col in range(self.model.columnCount()):
            child = parent.child(row, col)
            if child:
                values.append(child.text())
        data = parent.child(row, 0).data(Qt.ItemDataRole.UserRole) if parent.child(row, 0) else None
        if data:
            values.extend([data.get("serial", ""), data.get("decoded_full", ""), data.get("base_name", "")])
        return " ".join(str(value) for value in values).lower()
