# -*- coding: utf-8 -*-
"""
YAML 树模型：把 SaveGameController.yaml_obj 暴露为可编辑的 QTreeView 模型。

设计要点：
- 懒加载：子节点只在展开时构造，3k+ 节点的存档无压力；
- 值实时从 controller 按路径读取，不会因视图缓存而陈旧；
- 所有编辑通过 edit_callback 路由给外部（QUndoCommand → controller），
  模型本身不直接改数据；
- annotation_provider / change_provider 两个注入点用于领域标注与变更对比着色。
"""
from typing import Any, Callable, List, Optional

import yaml
from PyQt6.QtCore import QAbstractItemModel, QModelIndex, Qt
from PyQt6.QtGui import QColor, QFont

COL_KEY = 0
COL_VALUE = 1
COL_NOTE = 2

# 值类型配色（浅色主题）
_LIGHT_COLORS = {
    "str": QColor("#993556"),
    "num": QColor("#854F0B"),
    "bool": QColor("#185FA5"),
    "null": QColor("#5F5E5A"),
    "key": QColor("#2C2C2A"),
    "added_bg": QColor(234, 243, 222, 140),
    "modified_bg": QColor(250, 238, 218, 160),
}
# 值类型配色（夜间主题，提高亮度保证可读性）
_DARK_COLORS = {
    "str": QColor("#ED93B1"),
    "num": QColor("#EF9F27"),
    "bool": QColor("#85B7EB"),
    "null": QColor("#9B9A94"),
    "key": QColor("#E8E8EC"),
    "added_bg": QColor(99, 153, 34, 70),
    "modified_bg": QColor(239, 159, 39, 70),
}

# 兼容旧引用（默认浅色）
COLOR_STR = _LIGHT_COLORS["str"]
COLOR_NUM = _LIGHT_COLORS["num"]
COLOR_BOOL = _LIGHT_COLORS["bool"]
COLOR_NULL = _LIGHT_COLORS["null"]
COLOR_KEY = _LIGHT_COLORS["key"]

_SEARCH_CAP = 1000


def format_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def parse_scalar(text: str, old_value: Any) -> tuple:
    """按原值类型把输入文本解析回 Python 值。返回 (value, ok)。"""
    text = text.strip()
    if isinstance(old_value, bool):
        low = text.lower()
        if low in ("true", "1", "yes", "on"):
            return True, True
        if low in ("false", "0", "no", "off"):
            return False, True
        return old_value, False
    if isinstance(old_value, int):
        try:
            return int(text), True
        except ValueError:
            return old_value, False
    if isinstance(old_value, float):
        try:
            return float(text), True
        except ValueError:
            return old_value, False
    if old_value is None:
        try:
            return yaml.safe_load(text), True
        except yaml.YAMLError:
            return text, True
    # 原值是字符串：直接采用文本（不做隐式转换，避免串型）
    return text, True


def scalar_type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    return "str"


class TreeItem:
    __slots__ = ("key", "path", "parent", "children")

    def __init__(self, key: Any, path: tuple, parent: Optional["TreeItem"]):
        self.key = key          # dict 键（str）或 list 下标（int）；根为 None
        self.path = path        # 从根出发的路径元组
        self.parent = parent
        self.children: Optional[List["TreeItem"]] = None  # None = 未展开构造


class YamlTreeModel(QAbstractItemModel):
    HEADERS = ("key", "value", "note")

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.root = TreeItem(None, (), None)
        self._colors = _LIGHT_COLORS
        # 注入点：标注（serial 解码等）与变更对比
        self.annotation_provider: Optional[Callable[[tuple, Any, Any], str]] = None
        self.change_provider: Optional[Callable[[tuple], Optional[str]]] = None
        # 编辑路由：callback(action, path, payload) -> bool；action ∈ {"set","rename"}
        self.edit_callback: Optional[Callable[[str, tuple, Any], bool]] = None

    def set_dark_mode(self, dark: bool) -> None:
        """切换浅/夜配色并刷新可见节点。"""
        colors = _DARK_COLORS if dark else _LIGHT_COLORS
        if colors is self._colors:
            return
        self._colors = colors
        if self.controller and self.controller.yaml_obj is not None:
            # 全量着色刷新（颜色属于展示层，无需重建懒加载缓存）
            self.dataChanged.emit(QModelIndex(), QModelIndex(), [])

    @property
    def colors(self) -> dict:
        return self._colors

    # ---------------- 数据访问 ----------------
    def _value_of(self, item: TreeItem) -> Any:
        if item.path == ():
            return self.controller.yaml_obj
        try:
            return self.controller.get_node(item.path)
        except Exception:
            return None

    def _ensure_children(self, item: TreeItem) -> None:
        if item.children is not None:
            return
        item.children = []
        value = self._value_of(item)
        if isinstance(value, dict):
            for k in value.keys():
                item.children.append(TreeItem(k, item.path + (k,), item))
        elif isinstance(value, list):
            for i in range(len(value)):
                item.children.append(TreeItem(i, item.path + (i,), item))

    def reload(self) -> None:
        """数据整体变化后调用：丢弃懒加载缓存并重建可见部分。"""
        self.beginResetModel()
        self.root.children = None
        self.endResetModel()

    # ---------------- Qt 模型接口 ----------------
    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        parent_item = parent.internalPointer() if parent.isValid() else self.root
        self._ensure_children(parent_item)
        if row < len(parent_item.children):
            return self.createIndex(row, column, parent_item.children[row])
        return QModelIndex()

    def parent(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        item: TreeItem = index.internalPointer()
        p = item.parent
        if p is None or p is self.root:
            return QModelIndex()
        grand = p.parent or self.root
        self._ensure_children(grand)
        try:
            row = grand.children.index(p)
        except ValueError:
            return QModelIndex()
        return self.createIndex(row, 0, p)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.column() > 0:
            return 0
        item = parent.internalPointer() if parent.isValid() else self.root
        self._ensure_children(item)
        return len(item.children)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 3

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        item: TreeItem = index.internalPointer()
        value = self._value_of(item)
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_KEY:
                if item.key is None:
                    return ""
                return f"[{item.key}]" if isinstance(item.key, int) else str(item.key)
            if col == COL_VALUE:
                if isinstance(value, (dict, list)):
                    return ""
                return format_scalar(value)
            if col == COL_NOTE:
                if self.annotation_provider:
                    try:
                        return self.annotation_provider(item.path, item.key, value) or ""
                    except Exception:
                        return ""
                return ""

        if role == Qt.ItemDataRole.ForegroundRole:
            if col == COL_KEY:
                return self._colors["key"]
            if col == COL_VALUE and not isinstance(value, (dict, list)):
                if value is None:
                    return self._colors["null"]
                if isinstance(value, bool):
                    return self._colors["bool"]
                if isinstance(value, (int, float)):
                    return self._colors["num"]
                return self._colors["str"]

        if role == Qt.ItemDataRole.BackgroundRole and self.change_provider and item.path:
            try:
                change = self.change_provider(item.path)
            except Exception:
                change = None
            if change == "added":
                return self._colors["added_bg"]
            if change == "modified":
                return self._colors["modified_bg"]

        if role == Qt.ItemDataRole.FontRole and col == COL_VALUE:
            f = QFont()
            f.setFamily("Consolas")
            return f

        if role == Qt.ItemDataRole.UserRole:
            return item.path
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def set_headers(self, headers: tuple) -> None:
        self.HEADERS = headers
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, 2)

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        f = super().flags(index)
        if not index.isValid():
            return f
        item: TreeItem = index.internalPointer()
        value = self._value_of(item)
        if index.column() == COL_VALUE and item.path and not isinstance(value, (dict, list)):
            f |= Qt.ItemFlag.ItemIsEditable
        elif index.column() == COL_KEY and item.path and not isinstance(item.key, int):
            f |= Qt.ItemFlag.ItemIsEditable
        return f

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if role != Qt.ItemDataRole.EditRole or not index.isValid() or not self.edit_callback:
            return False
        item: TreeItem = index.internalPointer()
        if index.column() == COL_VALUE:
            old = self._value_of(item)
            if isinstance(old, (dict, list)):
                return False
            parsed, ok = parse_scalar(str(value), old)
            if not ok or parsed == old:
                return False
            return bool(self.edit_callback("set", item.path, parsed))
        if index.column() == COL_KEY:
            new_key = str(value).strip()
            if not new_key or new_key == str(item.key) or isinstance(item.key, int):
                return False
            return bool(self.edit_callback("rename", item.path, new_key))
        return False

    # ---------------- 路径 ⇄ 索引 / 搜索 ----------------
    def index_for_path(self, path: tuple) -> QModelIndex:
        item = self.root
        idx = QModelIndex()
        for depth, part in enumerate(path):
            self._ensure_children(item)
            target = None
            for row, child in enumerate(item.children):
                if child.key == part or str(child.key) == str(part):
                    target = (row, child)
                    break
            if target is None:
                return QModelIndex()
            row, item = target
            idx = self.createIndex(row, 0, item)
        return idx

    def search(self, needle: str) -> List[tuple]:
        """全量搜索键与值（大小写不敏感子串），返回命中的叶子/容器路径。"""
        needle = needle.strip().lower()
        if not needle or self.controller.yaml_obj is None:
            return []
        results: List[tuple] = []

        def walk(node, path):
            if len(results) >= _SEARCH_CAP:
                return
            if isinstance(node, dict):
                for k, v in node.items():
                    if needle in str(k).lower():
                        results.append(path + (k,))
                    walk(v, path + (k,))
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    walk(v, path + (i,))
            else:
                if needle in format_scalar(node).lower():
                    results.append(path)

        walk(self.controller.yaml_obj, ())
        return results

    def count_nodes(self) -> int:
        count = 0

        def walk(node):
            nonlocal count
            count += 1
            if isinstance(node, dict):
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        if self.controller.yaml_obj is not None:
            walk(self.controller.yaml_obj)
        return count
