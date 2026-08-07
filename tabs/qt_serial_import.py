"""Small shared UI/helpers for importing an item as an editable copy."""

import re

from PyQt6 import QtCore, QtWidgets

from core import decoder_logic
from tabs.qt_catalog_picker import ContainedWheelListWidget


_SOURCE_TEXTS = {
    "zh-CN": {
        "new_source": "来源：新建物品",
        "backpack": "从背包选择",
        "base85": "导入 Base85",
        "reset": "重置为新建",
        "backpack_title": "选择背包物品",
        "search": "搜索名称、厂商或类型…",
        "base85_title": "导入 Base85",
        "base85_label": "粘贴物品 Base85 序列：",
        "imported": "来源：{name}（副本）",
        "no_save": "请先加载存档。",
        "wrong_type": "该序列不是此编辑器支持的物品。",
        "import_error": "导入失败",
    },
    "en-US": {
        "new_source": "Source: New item",
        "backpack": "Backpack",
        "base85": "Import Base85",
        "reset": "Reset to new",
        "backpack_title": "Select backpack item",
        "search": "Search name, manufacturer, or type…",
        "base85_title": "Import Base85",
        "base85_label": "Paste an item Base85 serial:",
        "imported": "Source: {name} (copy)",
        "no_save": "Load a save before choosing from the backpack.",
        "wrong_type": "This serial is not an item supported by this editor.",
        "import_error": "Import failed",
    },
    "ru": {
        "new_source": "Источник: новый предмет",
        "backpack": "Из рюкзака",
        "base85": "Base85",
        "reset": "Новый",
        "backpack_title": "Выбор предмета из рюкзака",
        "search": "Поиск по имени, производителю или типу…",
        "base85_title": "Импорт Base85",
        "base85_label": "Вставьте Base85 предмета:",
        "imported": "Источник: {name} (копия)",
        "no_save": "Сначала загрузите сохранение.",
        "wrong_type": "Этот код не поддерживается данным редактором.",
        "import_error": "Ошибка импорта",
    },
    "ua": {
        "new_source": "Джерело: новий предмет",
        "backpack": "З рюкзака",
        "base85": "Base85",
        "reset": "Новий",
        "backpack_title": "Вибір предмета з рюкзака",
        "search": "Пошук за назвою, виробником або типом…",
        "base85_title": "Імпорт Base85",
        "base85_label": "Вставте Base85 предмета:",
        "imported": "Джерело: {name} (копія)",
        "no_save": "Спочатку завантажте збереження.",
        "wrong_type": "Цей код не підтримується цим редактором.",
        "import_error": "Помилка імпорту",
    },
}


def source_texts(lang):
    return _SOURCE_TEXTS.get(lang, _SOURCE_TEXTS["en-US"])


def select_flag_value(combo, value=None, *, default="3"):
    target = str(default if value in (None, "") else value).strip().split(" ", 1)[0]
    for index in range(combo.count()):
        if combo.itemText(index).split(" ", 1)[0] == target:
            combo.setCurrentIndex(index)
            return
    combo.addItem(target)
    combo.setCurrentIndex(combo.count() - 1)


class SerialSourceBar(QtWidgets.QFrame):
    backpack_requested = QtCore.pyqtSignal()
    base85_requested = QtCore.pyqtSignal()
    reset_requested = QtCore.pyqtSignal()

    def __init__(self, *, new_text, backpack_text, base85_text, reset_text, parent=None):
        super().__init__(parent)
        self.setObjectName("SerialSourceBar")
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        self.source_label = QtWidgets.QLabel(new_text)
        self.source_label.setObjectName("SerialSourceLabel")
        self.source_label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.source_label, 1)

        self.backpack_btn = QtWidgets.QPushButton(backpack_text)
        self.base85_btn = QtWidgets.QPushButton(base85_text)
        self.reset_btn = QtWidgets.QPushButton(reset_text)
        self.reset_btn.setEnabled(False)
        layout.addWidget(self.backpack_btn)
        layout.addWidget(self.base85_btn)
        layout.addWidget(self.reset_btn)

        self.backpack_btn.clicked.connect(self.backpack_requested)
        self.base85_btn.clicked.connect(self.base85_requested)
        self.reset_btn.clicked.connect(self.reset_requested)

    def set_source(self, text, *, imported):
        self.source_label.setText(text)
        self.source_label.setToolTip(text)
        self.reset_btn.setEnabled(imported)


def choose_backpack_item(parent, items, predicate, *, title, search_placeholder):
    matches = [item for item in items if predicate(item)]
    dialog = QtWidgets.QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.resize(620, 520)
    layout = QtWidgets.QVBoxLayout(dialog)

    search = QtWidgets.QLineEdit()
    search.setClearButtonEnabled(True)
    search.setPlaceholderText(search_placeholder)
    layout.addWidget(search)

    item_list = ContainedWheelListWidget()
    item_list.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
    item_list.verticalScrollBar().setSingleStep(20)
    layout.addWidget(item_list, 1)

    buttons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.StandardButton.Ok
        | QtWidgets.QDialogButtonBox.StandardButton.Cancel
    )
    buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setEnabled(False)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)

    for item in matches:
        name = item.get("name") or item.get("manufacturer") or item.get("type") or "Item"
        detail = " · ".join(
            str(value) for value in (item.get("manufacturer"), item.get("type"), f"Lv.{item.get('level', '?')}")
            if value
        )
        row = QtWidgets.QListWidgetItem(f"{name}\n{detail}" if detail else str(name))
        row.setData(QtCore.Qt.ItemDataRole.UserRole, item)
        row.setData(QtCore.Qt.ItemDataRole.UserRole + 1, f"{name} {detail}".casefold())
        item_list.addItem(row)

    def apply_filter(text):
        query = (text or "").strip().casefold()
        for index in range(item_list.count()):
            row = item_list.item(index)
            row.setHidden(bool(query and query not in row.data(QtCore.Qt.ItemDataRole.UserRole + 1)))

    def update_ok(current, _previous=None):
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setEnabled(current is not None)

    search.textChanged.connect(apply_filter)
    item_list.currentItemChanged.connect(update_ok)
    item_list.itemDoubleClicked.connect(lambda _item: dialog.accept())

    if not matches:
        empty = QtWidgets.QListWidgetItem("—")
        empty.setFlags(QtCore.Qt.ItemFlag.NoItemFlags)
        item_list.addItem(empty)

    if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
        return None
    current = item_list.currentItem()
    return current.data(QtCore.Qt.ItemDataRole.UserRole) if current else None


def prompt_base85(parent, *, title, label):
    text, ok = QtWidgets.QInputDialog.getMultiLineText(parent, title, label)
    return text.strip() if ok else ""


def decode_base85(serial):
    decoded, _parts, error = decoder_logic.decode_serial_to_string((serial or "").strip())
    if error or not decoded or "||" not in decoded:
        raise ValueError(error or "Invalid item serial")
    return decoded


HEADER_RE = re.compile(r"^\s*(.*?)\s*\|\|(.*)$", re.DOTALL)

# A level-1 item is written with a short header: the level field and the whole
# second segment are dropped, and field[2] carries 2 instead of 1.
#
#   level 60 -> '274, 0, 1, 60| 2, 3865'   (mfg, u1, 1, level | u3, seed)
#   level 1  -> '274, 0, 2, 3865'          (mfg, u1, 2, seed)
#
# Both forms were observed on the *same* repair kit, with byte-identical
# components and an exact base85 round trip, so this is real game output rather
# than a truncated dump. Across 2477 two-segment samples field[2] is always 1 and
# the second segment always starts with 2, so treating the constants as fixed is
# consistent with every sample we have.
_SHORT_HEADER_MARKER = 2
_LONG_HEADER_MARKER = 1
_IMPLICIT_LEVEL = 1


def split_decoded(decoded):
    match = HEADER_RE.match(decoded or "")
    if not match:
        raise ValueError("Invalid decoded item header")
    header, component = match.groups()
    segments = [segment.strip() for segment in header.split("|")]
    try:
        first_fields = [int(value.strip()) for value in segments[0].split(",")]
        last_fields = [int(value.strip()) for value in segments[-1].split(",")]
    except ValueError as exc:
        raise ValueError("Invalid decoded item header") from exc
    if len(segments) == 1:
        # Short form: no level field, no second segment. Expose it through the
        # same keys as the long form so every caller keeps working, and remember
        # the shape so build_header can reproduce it byte-for-byte.
        if len(first_fields) < 4:
            raise ValueError("Invalid decoded item header")
        return {
            "mfg_id": first_fields[0],
            "unknown1": first_fields[1],
            "unknown2": _LONG_HEADER_MARKER,
            "level": _IMPLICIT_LEVEL,
            "unknown3": first_fields[2],
            "seed": first_fields[3],
            "header_first": [
                first_fields[0], first_fields[1], _LONG_HEADER_MARKER, _IMPLICIT_LEVEL,
            ],
            "header_middle": [],
            "header_last": [first_fields[2], first_fields[3]],
            "short_header": True,
            "component": component,
        }
    if len(first_fields) < 4 or len(last_fields) < 2:
        raise ValueError("Invalid decoded item header")
    return {
        "mfg_id": first_fields[0],
        "unknown1": first_fields[1],
        "unknown2": first_fields[2],
        "level": first_fields[3],
        "unknown3": last_fields[0],
        "seed": last_fields[1],
        "header_first": first_fields,
        "header_middle": segments[1:-1],
        "header_last": last_fields,
        "short_header": False,
        "component": component,
    }


def build_header(parts, *, mfg_id=None, level=None, seed=None):
    first_fields = list(parts["header_first"])
    last_fields = list(parts["header_last"])
    if mfg_id is not None:
        first_fields[0] = int(mfg_id)
    if level is not None:
        first_fields[3] = int(level)
    if seed is not None:
        last_fields[1] = int(seed)
    # Keep the short form only while it still encodes level 1; raising the level
    # needs the long form, and lowering an edited item back to 1 should return to
    # the short form so the output matches what the game itself writes.
    if (
        parts.get("short_header")
        and not parts.get("header_middle")
        and first_fields[3] == _IMPLICIT_LEVEL
    ):
        return ", ".join(
            map(str, [first_fields[0], first_fields[1], _SHORT_HEADER_MARKER, last_fields[1]])
        )
    segments = [
        ", ".join(map(str, first_fields)),
        *parts.get("header_middle", []),
        ", ".join(map(str, last_fields)),
    ]
    return "| ".join(segments)



def parse_components(text):
    for match in re.finditer(r'\{(\d+)(?::(\d+|\[[^\]]*\]))?\}|"([^"]+)"', text or ""):
        if match.group(3) is not None:
            yield {"type": "quoted", "value": match.group(3)}
            continue
        parent = int(match.group(1))
        inner = match.group(2)
        if inner is None:
            yield {"type": "simple", "id": parent}
        elif inner.startswith("["):
            children = [int(value) for value in re.findall(r"\d+", inner)]
            yield {"type": "group", "id": parent, "children": children}
        else:
            yield {"type": "single", "id": parent, "value": int(inner)}
