"""YAML 编辑器 VM：移植 QtYamlEditorTab 的全部非渲染逻辑。

树以扁平行模型暴露（展开/折叠状态在 VM），类型化编辑经 QUndoStack 落到
controller；源码视图经 text 属性双向同步（语法高亮由 QML 侧 textDocument
挂 YamlHighlighter 实现）；检查器（面包屑 + serial 预览 + 节点操作）、
搜索、变更对比、撤销/重做齐全。
"""

from __future__ import annotations

import copy
from typing import Any

import yaml
from PyQt6.QtCore import pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QUndoCommand, QUndoStack
from PyQt6.QtWidgets import QApplication

from core.yaml_io import dump_yaml, get_yaml_loader
from core.yaml_model import format_scalar, parse_scalar, scalar_type_name

from .base import PageViewModel, register

_SEARCH_CAP = 1000
_TYPE_KEYS = ("str", "int", "float", "bool", "null", "dict", "list")


# ----------------------------------------------------------------------
# 撤销命令（与主线一致）
# ----------------------------------------------------------------------
class _CmdSetValue(QUndoCommand):
    def __init__(self, vm, path, new_value, text):
        super().__init__(text)
        self.vm, self.path, self.new = vm, tuple(path), new_value
        self.old = copy.deepcopy(vm.controller.get_node(self.path))

    def redo(self):
        self.vm.controller.set_value(self.path, copy.deepcopy(self.new))
        self.vm._after_mutation()

    def undo(self):
        self.vm.controller.set_value(self.path, copy.deepcopy(self.old))
        self.vm._after_mutation()


class _CmdRename(QUndoCommand):
    def __init__(self, vm, path, new_key, text):
        super().__init__(text)
        self.vm, self.path, self.new_key = vm, tuple(path), new_key
        self.old_key = self.path[-1]

    def redo(self):
        self.vm.controller.rename_key(self.path, self.new_key)
        self.vm._after_mutation()

    def undo(self):
        self.vm.controller.rename_key(self.path[:-1] + (self.new_key,), self.old_key)
        self.vm._after_mutation()


class _CmdAddChild(QUndoCommand):
    def __init__(self, vm, path, key, value, text):
        super().__init__(text)
        self.vm, self.path, self.key, self.value = vm, tuple(path), key, value
        self.new_path = None

    def redo(self):
        self.new_path = self.vm.controller.add_child(self.path, self.key, copy.deepcopy(self.value))
        self.vm._after_mutation()

    def undo(self):
        if self.new_path:
            self.vm.controller.delete_node(self.new_path)
            self.vm._after_mutation()


class _CmdDelete(QUndoCommand):
    def __init__(self, vm, paths, text):
        super().__init__(text)
        self.vm, self.paths = vm, [tuple(p) for p in paths]
        self.deleted = []

    def redo(self):
        self.deleted = self.vm.controller.delete_nodes(self.paths)
        self.vm._after_mutation()

    def undo(self):
        self.vm.controller.restore_nodes(self.deleted)
        self.vm._after_mutation()


@register("yaml_editor", "YamlEditorPage.qml")
class YamlEditorViewModel(PageViewModel):
    STRINGS_SECTION = "yaml_tab"

    dataChanged = pyqtSignal()
    revealRequested = pyqtSignal(int)  # 需要滚动定位的行号

    VIEW_TREE, VIEW_SOURCE, VIEW_SPLIT = 0, 1, 2

    def __init__(self, app, parent=None):
        super().__init__(app, parent)
        self.undo_stack = QUndoStack(self)
        self.undo_stack.canUndoChanged.connect(lambda _v: self.dataChanged.emit())
        self.undo_stack.canRedoChanged.connect(lambda _v: self.dataChanged.emit())
        self._synced_version = -1
        self._source_valid = True
        self._source_error = ""
        self._diff_enabled = False
        self._diff_added: set = set()
        self._diff_modified: set = set()
        self._diff_removed_count = 0
        self._serial_info_map: dict | None = None
        self._search_text = ""
        self._search_results: list[tuple] = []
        self._search_pos = -1
        self._view_mode = self.VIEW_TREE
        self._source_text = ""
        self._expanded: set[tuple] = {("state",), ("domains",)}
        self._rows: list[dict[str, Any]] = []
        self._selected_row = -1
        self._multi_selected: set[tuple] = set()

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        self.sync_from_controller()

    @pyqtSlot()
    def sync_from_controller(self) -> None:
        """版本号不一致才重建（与主线一致）。"""
        if self.controller.yaml_obj is None:
            self._rows = []
            self.dataChanged.emit()
            return
        if self._synced_version == self.controller.version:
            return
        self._rebuild_rows()
        self._source_text = self.controller.get_yaml_string()
        self._synced_version = self.controller.version
        self._serial_info_map = None
        self.undo_stack.clear()
        if self._diff_enabled:
            self._recompute_diff()
        self.dataChanged.emit()

    def on_language_changed(self) -> None:
        super().on_language_changed()
        self._synced_version = -1
        self.sync_from_controller()

    # ------------------------------------------------------------------ #
    # 扁平行模型
    # ------------------------------------------------------------------ #
    def _rebuild_rows(self) -> None:
        rows: list[dict[str, Any]] = []

        def walk(node, path, depth):
            for key, value in (node.items() if isinstance(node, dict)
                               else enumerate(node) if isinstance(node, list) else []):
                child_path = path + (key,)
                is_container = isinstance(value, (dict, list))
                rows.append({
                    "path": [str(p) for p in child_path],
                    "pathTuple": child_path,
                    "depth": depth,
                    "key": str(key),
                    "isIntKey": isinstance(key, int),
                    "isContainer": is_container,
                    "expanded": child_path in self._expanded,
                    "valueText": "" if is_container else format_scalar(value),
                    "valueType": "container" if is_container else scalar_type_name(value),
                    "annotation": self._annotation_for(child_path, key, value),
                    "change": self._change_for(child_path),
                })
                if is_container and child_path in self._expanded:
                    walk(value, child_path, depth + 1)

        if self.controller.yaml_obj is not None:
            walk(self.controller.yaml_obj, (), 0)
        self._rows = rows

    # ------------------------------------------------------------------ #
    # QML 属性
    # ------------------------------------------------------------------ #
    @pyqtProperty(list, notify=dataChanged)
    def rows(self) -> list[dict[str, Any]]:
        return [{k: v for k, v in row.items() if k != "pathTuple"} for row in self._rows]

    @pyqtProperty(bool, notify=dataChanged)
    def saveLoaded(self) -> bool:
        return self.controller.yaml_obj is not None

    @pyqtProperty(int, notify=dataChanged)
    def viewMode(self) -> int:
        return self._view_mode

    @pyqtProperty(str, notify=dataChanged)
    def sourceText(self) -> str:
        return self._source_text

    @pyqtProperty(bool, notify=dataChanged)
    def sourceValid(self) -> bool:
        return self._source_valid

    @pyqtProperty(str, notify=dataChanged)
    def statusValidText(self) -> str:
        status = self.strings.get("status", {})
        if not self._source_valid:
            return status.get("invalid", "YAML 无效：{error}").format(error=self._source_error)
        return status.get("valid", "YAML 有效")

    @pyqtProperty(str, notify=dataChanged)
    def statusNodesText(self) -> str:
        if self.controller.yaml_obj is None:
            return ""
        return self.strings.get("status", {}).get("nodes", "共 {count} 个节点").format(
            count=self._count_nodes())

    @pyqtProperty(str, notify=dataChanged)
    def statusModifiedText(self) -> str:
        if self.controller.yaml_obj is None:
            return ""
        return self.strings.get("status", {}).get("modified", "● {count} 处未保存修改").format(
            count=1 if self.controller.dirty else 0)

    @pyqtProperty(bool, notify=dataChanged)
    def canUndo(self) -> bool:
        return self.undo_stack.canUndo()

    @pyqtProperty(bool, notify=dataChanged)
    def canRedo(self) -> bool:
        return self.undo_stack.canRedo()

    @pyqtProperty(bool, notify=dataChanged)
    def diffEnabled(self) -> bool:
        return self._diff_enabled

    @pyqtProperty(str, notify=dataChanged)
    def diffButtonText(self) -> str:
        label = self.strings.get("buttons", {}).get("diff", "变更对比")
        n = len(self._diff_added) + len(self._diff_modified) + self._diff_removed_count
        return f"{label} · {n}" if n else label

    @pyqtProperty(str, notify=dataChanged)
    def searchText(self) -> str:
        return self._search_text

    @pyqtProperty(str, notify=dataChanged)
    def searchCountText(self) -> str:
        if not self._search_text:
            return ""
        if not self._search_results:
            return "0/0"
        return self.strings.get("search", {}).get("count", "{current}/{total}").format(
            current=self._search_pos + 1, total=len(self._search_results))

    # -- 检查器 ------------------------------------------------------------- #
    @pyqtProperty(str, notify=dataChanged)
    def breadcrumbText(self) -> str:
        row = self._row_at(self._selected_row)
        if row is None:
            return self.strings.get("inspector", {}).get("no_selection", "未选择节点")
        return " › ".join(row["path"]) if row["path"] else "—"

    @pyqtProperty(bool, notify=dataChanged)
    def serialInfoVisible(self) -> bool:
        return self._serial_preview_item() is not None

    @pyqtProperty(str, notify=dataChanged)
    def serialInfoText(self) -> str:
        item = self._serial_preview_item()
        if not item:
            return ""
        ins = self.strings.get("inspector", {})
        return (
            f"{item.get('name', '')}\n"
            f"{ins.get('level', '等级')}: {item.get('level', '?')}  ·  "
            f"{ins.get('type', '类型')}: {item.get('type', '?')}  ·  "
            f"{ins.get('manufacturer', '制造商')}: {item.get('manufacturer', '?')}\n"
            f"{ins.get('container', '位置')}: {item.get('container', '?')}  ·  "
            f"{ins.get('slot', '槽位')}: {item.get('slot', '?')}  ·  "
            f"{ins.get('state_flags', '状态标志')}: {item.get('state_flags', '')}"
        )

    @pyqtProperty(str, notify=dataChanged)
    def pinnedText(self) -> str:
        ins = self.strings.get("inspector", {})
        return ins.get("pinned", "常用路径：") + "  " + " · ".join(
            ["state.currencies", "state.experience", "state.ammo", "state.inventory"])

    # ------------------------------------------------------------------ #
    # QML 槽：视图 / 树
    # ------------------------------------------------------------------ #
    @pyqtSlot(int)
    def setViewMode(self, mode: int) -> None:
        self._view_mode = int(mode)
        if mode in (self.VIEW_SOURCE, self.VIEW_SPLIT):
            self._source_text = self.controller.get_yaml_string() if self.controller.yaml_obj else self._source_text
        self.dataChanged.emit()

    @pyqtSlot(int)
    def toggleRow(self, row: int) -> None:
        item = self._row_at(row)
        if item is None or not item["isContainer"]:
            return
        path = item["pathTuple"]
        if path in self._expanded:
            self._expanded.discard(path)
        else:
            self._expanded.add(path)
        self._rebuild_rows()
        self.dataChanged.emit()

    @pyqtSlot(int)
    def selectRow(self, row: int) -> None:
        self._selected_row = int(row)
        self.dataChanged.emit()

    @pyqtSlot(int, bool)
    def setRowMultiSelected(self, row: int, selected: bool) -> None:
        item = self._row_at(row)
        if item is None:
            return
        if selected:
            self._multi_selected.add(item["pathTuple"])
        else:
            self._multi_selected.discard(item["pathTuple"])

    @pyqtSlot()
    def clearMultiSelection(self) -> None:
        self._multi_selected = set()

    # -- 编辑 ---------------------------------------------------------------- #
    @pyqtSlot(int, str, result=bool)
    def editValue(self, row: int, text: str) -> bool:
        item = self._row_at(row)
        if item is None or item["isContainer"]:
            return False
        path = item["pathTuple"]
        old_value = self.controller.get_node(path)
        new_value, ok = parse_scalar(text, old_value)
        if not ok:
            self.app.toast(self.strings.get("dialogs", {}).get("error", "错误"), "error")
            return False
        self.undo_stack.push(_CmdSetValue(self, path, new_value,
                                          self.strings.get("ops", {}).get("set_value", "修改值")))
        return True

    @pyqtSlot(int, str, result=bool)
    def renameKey(self, row: int, new_key: str) -> bool:
        item = self._row_at(row)
        if item is None or item["isIntKey"] or not new_key.strip():
            return False
        self.undo_stack.push(_CmdRename(self, item["pathTuple"], new_key.strip(),
                                        self.strings.get("ops", {}).get("rename", "重命名键")))
        return True

    @pyqtSlot(int, str, str, result=bool)
    def addChild(self, row: int, key: str, type_key: str) -> bool:
        item = self._row_at(row)
        if item is None:
            return False
        path = item["pathTuple"]
        value = self.controller.get_node(path)
        if not isinstance(value, (dict, list)):
            return False
        defaults = {"str": "", "int": 0, "float": 0.0, "bool": False, "null": None, "dict": {}, "list": []}
        new_value = defaults.get(type_key)
        child_key = key.strip() if isinstance(value, dict) else None
        if isinstance(value, dict) and not child_key:
            return False
        cmd = _CmdAddChild(self, path, child_key, new_value,
                           self.strings.get("ops", {}).get("add_child", "添加子节点"))
        self.undo_stack.push(cmd)
        if cmd.new_path:
            self._expanded.add(path)
            self._reveal_path(cmd.new_path)
        return True

    @pyqtSlot(int, result=bool)
    def duplicateRow(self, row: int) -> bool:
        item = self._row_at(row)
        if item is None:
            return False
        path = item["pathTuple"]
        value = copy.deepcopy(self.controller.get_node(path))
        parent_path, key = path[:-1], path[-1]
        parent = self.controller.get_node(parent_path)
        if isinstance(parent, dict):
            base, n = f"{key}_copy", 2
            new_key = base
            while new_key in parent:
                new_key = f"{base}_{n}"
                n += 1
            self.undo_stack.push(_CmdAddChild(self, parent_path, new_key, value,
                                              self.strings.get("ops", {}).get("duplicate", "复制节点")))
        elif isinstance(parent, list):
            self.undo_stack.push(_CmdAddChild(self, parent_path, None, value,
                                              self.strings.get("ops", {}).get("duplicate", "复制节点")))
        else:
            return False
        return True

    @pyqtSlot(result=int)
    def deleteSelectionCount(self) -> int:
        """返回待删除节点数（QML 据此决定是否弹确认）。"""
        return len(self._deletion_paths())

    @pyqtSlot()
    def deleteSelection(self) -> None:
        paths = self._deletion_paths()
        if not paths:
            return
        self.undo_stack.push(_CmdDelete(self, paths,
                                        f"{self.strings.get('ops', {}).get('delete', '删除')} ({len(paths)})"))
        self._multi_selected = set()

    @pyqtSlot(int)
    def copyPath(self, row: int) -> None:
        item = self._row_at(row)
        if item is None:
            return
        path = item["pathTuple"]
        text = ".".join(f"[{p}]" if isinstance(p, int) else str(p) for p in path)
        QApplication.clipboard().setText(text)

    @pyqtSlot(int)
    def copyValue(self, row: int) -> None:
        item = self._row_at(row)
        if item is None:
            return
        value = self.controller.get_node(item["pathTuple"])
        text = dump_yaml(value, sort_keys=False, allow_unicode=True) \
            if isinstance(value, (dict, list)) else format_scalar(value)
        QApplication.clipboard().setText(text)

    # -- 范围删除 -------------------------------------------------------------- #
    @pyqtSlot(result="QVariantMap")
    def rangeDeleteInfo(self) -> dict[str, Any]:
        found = self.controller.find_backpack()
        if not found:
            return {}
        bp_path, backpack = found
        slot_nums = sorted(int(k[5:]) for k in backpack
                           if str(k).startswith("slot_") and str(k)[5:].isdigit())
        if not slot_nums:
            return {}
        return {"min": slot_nums[0], "max": slot_nums[-1], "path": [str(p) for p in bp_path]}

    @pyqtSlot(int, int, result=int)
    def rangeDeleteCount(self, from_slot: int, to_slot: int) -> int:
        found = self.controller.find_backpack()
        if not found:
            return 0
        _bp_path, backpack = found
        a, b = sorted((from_slot, to_slot))
        return sum(1 for n in range(a, b + 1) if f"slot_{n}" in backpack)

    @pyqtSlot(int, int)
    def rangeDelete(self, from_slot: int, to_slot: int) -> None:
        found = self.controller.find_backpack()
        if not found:
            return
        bp_path, backpack = found
        a, b = sorted((from_slot, to_slot))
        paths = [tuple(bp_path) + (f"slot_{n}",) for n in range(a, b + 1) if f"slot_{n}" in backpack]
        if paths:
            self.undo_stack.push(_CmdDelete(
                self, paths,
                f"{self.strings.get('ops', {}).get('range_delete', '批量删除')} [{a}, {b}] ({len(paths)})"))

    # -- 撤销/重做/对比 ---------------------------------------------------------- #
    @pyqtSlot()
    def undo(self) -> None:
        self.undo_stack.undo()

    @pyqtSlot()
    def redo(self) -> None:
        self.undo_stack.redo()

    @pyqtSlot(bool)
    def setDiffEnabled(self, on: bool) -> None:
        self._diff_enabled = bool(on)
        if on:
            self._recompute_diff()
        else:
            self._diff_added, self._diff_modified = set(), set()
            self._diff_removed_count = 0
            self._rebuild_rows()
        self.dataChanged.emit()

    # -- 源码编辑 ---------------------------------------------------------------- #
    @pyqtSlot(str)
    def applySourceText(self, text: str) -> None:
        """源码视图提交（QML 防抖后调用）。"""
        self._source_text = text
        try:
            yaml.load(text, Loader=get_yaml_loader())
        except yaml.YAMLError as exc:
            self._source_valid = False
            self._source_error = str(exc).split("\n")[0]
            self.dataChanged.emit()
            return
        self._source_valid = True
        self._source_error = ""
        if self.controller.update_yaml_object(text):
            self._after_mutation(source_edit=True)
        self.dataChanged.emit()

    # -- 搜索 ------------------------------------------------------------------- #
    @pyqtSlot(str)
    def setSearchText(self, text: str) -> None:
        self._search_text = text
        self._search_results = self._search(text)
        self._search_pos = -1
        if self._search_results:
            self.cycleSearch(1)
        self.dataChanged.emit()

    @pyqtSlot(int)
    def cycleSearch(self, step: int) -> None:
        if not self._search_results:
            return
        self._search_pos = (self._search_pos + step) % len(self._search_results)
        self._reveal_path(self._search_results[self._search_pos])
        self.dataChanged.emit()

    # -- 检查器操作 ---------------------------------------------------------------- #
    @pyqtSlot()
    def openInItemEditor(self) -> None:
        item = self._serial_preview_item()
        if item:
            self.app.openItemFromYaml(dict(item))

    @pyqtSlot("QVariant")
    def attachSourceHighlighter(self, text_document) -> None:
        """给 QML TextArea 的 textDocument 挂 YAML 语法高亮。"""
        try:
            from core.yaml_model import YamlTreeModel
            from ui_huskar.yaml_highlighter import YamlHighlighter
        except ImportError:
            return
        doc = text_document
        if doc is None:
            return
        self._highlighter = YamlHighlighter(doc)
        probe = YamlTreeModel(self.controller)
        probe.set_dark_mode(self.app.dark)
        self._highlighter.apply_theme(probe.colors)

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _row_at(self, row: int) -> dict[str, Any] | None:
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def _reveal_path(self, path: tuple) -> None:
        for depth in range(1, len(path)):
            self._expanded.add(path[:depth])
        self._rebuild_rows()
        for index, row in enumerate(self._rows):
            if row["pathTuple"] == tuple(path):
                self._selected_row = index
                self.revealRequested.emit(index)
                break
        self.dataChanged.emit()

    def _deletion_paths(self) -> list[tuple]:
        paths = list(self._multi_selected)
        if not paths and self._selected_row >= 0:
            row = self._row_at(self._selected_row)
            if row is not None:
                paths = [row["pathTuple"]]
        # 去掉被选祖先覆盖的子路径，避免重复删除
        paths = sorted(set(paths), key=len)
        result = []
        for p in paths:
            if not any(len(a) < len(p) and p[:len(a)] == a for a in result):
                result.append(p)
        return result

    def _after_mutation(self, source_edit: bool = False) -> None:
        self._rebuild_rows()
        self._synced_version = self.controller.version
        self._serial_info_map = None
        if not source_edit:
            self._source_text = self.controller.get_yaml_string()
        if self._diff_enabled:
            self._recompute_diff()
        self.app._mark_items_stale()
        self.dataChanged.emit()

    def _recompute_diff(self) -> None:
        added, removed, modified = self.controller.diff_from_snapshot()
        self._diff_added, self._diff_modified = set(added), set(modified)
        self._diff_removed_count = len(removed)
        self._rebuild_rows()

    def _search(self, needle: str) -> list[tuple]:
        needle = needle.strip().lower()
        if not needle or self.controller.yaml_obj is None:
            return []
        results: list[tuple] = []

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

    def _count_nodes(self) -> int:
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

    def _build_serial_info_map(self) -> None:
        self._serial_info_map = {}
        try:
            for item in self.controller.get_all_items() or []:
                path = tuple(item.get("original_path") or ())
                if path:
                    self._serial_info_map[path + ("serial",)] = item
        except Exception:
            pass

    def _annotation_for(self, path, key, value) -> str:
        status = self.strings.get("status", {})
        if isinstance(value, dict):
            return status.get("object_items", "对象 · {count} 项").format(count=len(value))
        if isinstance(value, list):
            return status.get("list_items", "列表 · {count} 项").format(count=len(value))
        if key == "serial" and isinstance(value, str) and value.startswith("@U"):
            if self._serial_info_map is None:
                self._build_serial_info_map()
            item = (self._serial_info_map or {}).get(tuple(path))
            if item:
                return status.get("serial_ok", "已解码 · Lv{level} {name}").format(
                    level=item.get("level", "?"), name=item.get("name", ""))
            return self.strings.get("inspector", {}).get("unresolved", "未识别")
        if key == "state_flags" and isinstance(value, int) and not isinstance(value, bool):
            bits = [str(i) for i in range(value.bit_length()) if value & (1 << i)]
            return status.get("flags_bits", "位 {bits}").format(bits=" + ".join(bits)) if bits else "0"
        return ""

    def _change_for(self, path) -> str | None:
        if not self._diff_enabled:
            return None
        if tuple(path) in self._diff_added:
            return "added"
        if tuple(path) in self._diff_modified:
            return "modified"
        return None

    def _serial_preview_item(self) -> dict | None:
        row = self._row_at(self._selected_row)
        if row is None:
            return None
        if self._serial_info_map is None:
            self._build_serial_info_map()
        smap = self._serial_info_map or {}
        path = row["pathTuple"]
        if row["key"] == "serial":
            return smap.get(tuple(path))
        return smap.get(tuple(path) + ("serial",))
