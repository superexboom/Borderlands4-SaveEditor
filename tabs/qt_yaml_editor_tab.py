# -*- coding: utf-8 -*-
"""
现代化 YAML 编辑器页：
- 可编辑树（懒加载 + 类型化内联编辑 + 右键菜单 + 多选删除 + 背包范围删除）
- 源码视图（语法高亮 + 行号），树 ⇄ 源码双向同步
- 检查器面板（路径面包屑 + serial 解码预览 + 节点操作）
- 搜索、变更对比（与加载快照 diff）、QUndoStack 撤销/重做

数据源始终是 controller.yaml_obj；本页不持有第二份数据。
"""
import copy
import re

import yaml
from PyQt6.QtCore import (QModelIndex, QRect, QSize, Qt, QTimer, pyqtSignal)
from PyQt6.QtGui import (QColor, QFont, QKeySequence, QPainter, QPen, QShortcut,
                         QSyntaxHighlighter, QTextCharFormat, QTextCursor, QTextFormat,
                         QUndoCommand, QUndoStack)
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog,
                             QDialogButtonBox, QFormLayout, QFrame, QGridLayout,
                             QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox,
                             QPlainTextEdit, QPushButton, QSpinBox, QSplitter,
                             QStackedWidget, QStyledItemDelegate, QStyle, QTextEdit,
                             QToolButton, QTreeView, QVBoxLayout, QWidget)

from core import resource_loader
from core.yaml_model import (COLOR_BOOL, COLOR_KEY, COLOR_NULL, COLOR_NUM,
                             COLOR_STR, YamlTreeModel, format_scalar)


# 界面元素配色（状态栏、面包屑、行号栏等），随主题切换
_CHROME_LIGHT = {
    "valid": "#3B6D11", "invalid": "#A32D2D", "modified": "#BA7517",
    "hint": "#9B9A94", "crumb_bg": "#F1EFE8", "crumb_text": "#2C2C2A",
    "ln_bg": "#F5F5F3", "ln_fg": "#9B9A94", "cur_line": "#F1EFE8",
    "pinned": "#5F5E5A",
}
_CHROME_DARK = {
    "valid": "#97C459", "invalid": "#F09595", "modified": "#EF9F27",
    "hint": "#a0a0a8", "crumb_bg": "#3a3a45", "crumb_text": "#e8e8ec",
    "ln_bg": "#2a2a32", "ln_fg": "#a0a0a8", "cur_line": "#3a3a45",
    "pinned": "#a0a0a8",
}


def get_yaml_loader():
    class AnyTagLoader(yaml.SafeLoader): pass
    def _ignore_any(loader: AnyTagLoader, tag_suffix: str, node: 'yaml.Node'):
        if isinstance(node, yaml.ScalarNode): return loader.construct_scalar(node)
        if isinstance(node, yaml.SequenceNode): return loader.construct_sequence(node)
        if isinstance(node, yaml.MappingNode): return loader.construct_mapping(node)
        return None
    AnyTagLoader.add_multi_constructor("", _ignore_any)
    return AnyTagLoader


# ----------------------------------------------------------------------
# 撤销命令
# ----------------------------------------------------------------------
class _CmdSetValue(QUndoCommand):
    def __init__(self, tab, path, new_value, text):
        super().__init__(text)
        self.tab, self.path, self.new = tab, tuple(path), new_value
        self.old = copy.deepcopy(tab.controller.get_node(self.path))

    def redo(self):
        self.tab.controller.set_value(self.path, copy.deepcopy(self.new))
        self.tab._after_mutation()

    def undo(self):
        self.tab.controller.set_value(self.path, copy.deepcopy(self.old))
        self.tab._after_mutation()


class _CmdRename(QUndoCommand):
    def __init__(self, tab, path, new_key, text):
        super().__init__(text)
        self.tab, self.path, self.new_key = tab, tuple(path), new_key
        self.old_key = self.path[-1]

    def redo(self):
        self.tab.controller.rename_key(self.path, self.new_key)
        self.tab._after_mutation()

    def undo(self):
        self.tab.controller.rename_key(self.path[:-1] + (self.new_key,), self.old_key)
        self.tab._after_mutation()


class _CmdAddChild(QUndoCommand):
    def __init__(self, tab, path, key, value, text):
        super().__init__(text)
        self.tab, self.path, self.key, self.value = tab, tuple(path), key, value
        self.new_path = None

    def redo(self):
        self.new_path = self.tab.controller.add_child(self.path, self.key, copy.deepcopy(self.value))
        self.tab._after_mutation()

    def undo(self):
        if self.new_path:
            self.tab.controller.delete_node(self.new_path)
            self.tab._after_mutation()


class _CmdDelete(QUndoCommand):
    def __init__(self, tab, paths, text):
        super().__init__(text)
        self.tab, self.paths = tab, [tuple(p) for p in paths]
        self.deleted = []

    def redo(self):
        self.deleted = self.tab.controller.delete_nodes(self.paths)
        self.tab._after_mutation()

    def undo(self):
        self.tab.controller.restore_nodes(self.deleted)
        self.tab._after_mutation()


# ----------------------------------------------------------------------
# 源码编辑器：行号 + YAML 语法高亮
# ----------------------------------------------------------------------
class _LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self.editor.line_number_area_paint_event(event)


class YamlSourceEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._ln_bg = QColor("#F5F5F3")
        self._ln_fg = QColor("#9B9A94")
        self._cur_line_bg = QColor("#F1EFE8")
        self._line_area = _LineNumberArea(self)
        self.blockCountChanged.connect(self._update_area_width)
        self.updateRequest.connect(self._update_area)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self._update_area_width(0)
        self._highlight_current_line()
        f = QFont()
        f.setFamily("Consolas")
        f.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(f)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(' ') * 2)

    def apply_theme(self, ln_bg: str, ln_fg: str, cur_line_bg: str):
        """主题切换时更新行号栏与当前行配色。"""
        self._ln_bg = QColor(ln_bg)
        self._ln_fg = QColor(ln_fg)
        self._cur_line_bg = QColor(cur_line_bg)
        self._highlight_current_line()
        self._line_area.update()

    def line_number_area_width(self):
        digits = max(2, len(str(max(1, self.blockCount()))))
        return 10 + self.fontMetrics().horizontalAdvance('9') * digits

    def _update_area_width(self, _):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_area(self, rect, dy):
        if dy:
            self._line_area.scroll(0, dy)
        else:
            self._line_area.update(0, rect.y(), self._line_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_area.setGeometry(QRect(cr.left(), cr.top(),
                                          self.line_number_area_width(), cr.height()))

    def line_number_area_paint_event(self, event):
        painter = QPainter(self._line_area)
        painter.fillRect(event.rect(), self._ln_bg)
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        offset = self.contentOffset()
        top = self.blockBoundingGeometry(block).translated(offset).top()
        bottom = top + self.blockBoundingRect(block).height()
        painter.setPen(self._ln_fg)
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.drawText(0, int(top), self._line_area.width() - 5,
                                 self.fontMetrics().height(),
                                 Qt.AlignmentFlag.AlignRight, str(block_number + 1))
            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            block_number += 1

    def _highlight_current_line(self):
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(self._cur_line_bg)
        selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection] if not self.isReadOnly() else [])


class YamlHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self.rules = []
        self._build_rules(COLOR_KEY, COLOR_STR, COLOR_NUM, COLOR_BOOL, COLOR_NULL)

    def _build_rules(self, c_key, c_str, c_num, c_bool, c_null):
        fmt_key = QTextCharFormat(); fmt_key.setForeground(c_key); fmt_key.setFontWeight(QFont.Weight.Medium)
        fmt_str = QTextCharFormat(); fmt_str.setForeground(c_str)
        fmt_num = QTextCharFormat(); fmt_num.setForeground(c_num)
        fmt_bool = QTextCharFormat(); fmt_bool.setForeground(c_bool)
        fmt_comment = QTextCharFormat(); fmt_comment.setForeground(c_null); fmt_comment.setFontItalic(True)
        self.rules = [
            (re.compile(r'^\s*-\s+[^:#\s][^:]*(?=:\s)'), fmt_key),
            (re.compile(r'^\s*[^:#\s][^:]*(?=:\s|$)'), fmt_key),
            (re.compile(r'"[^"\n]*"|\'[^\'\n]*\''), fmt_str),
            (re.compile(r'(?<=:\s)-?\d+(\.\d+)?\s*$'), fmt_num),
            (re.compile(r'(?<=:\s)(true|false|null|~)\s*$'), fmt_bool),
            (re.compile(r'#.*$'), fmt_comment),
        ]

    def apply_theme(self, colors: dict):
        """用模型同款配色重建规则并重刷全文。"""
        self._build_rules(colors["key"], colors["str"], colors["num"],
                          colors["bool"], colors["null"])
        self.rehighlight()

    def highlightBlock(self, text):
        for pattern, fmt in self.rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


# ----------------------------------------------------------------------
# 类型化编辑委托：bool → 下拉，其余 → 行内文本（模型负责解析校验）
# ----------------------------------------------------------------------
class YamlEditDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        if index.column() == 1:
            item = index.internalPointer()
            value = index.model()._value_of(item)
            if isinstance(value, bool):
                combo = QComboBox(parent)
                combo.setStyleSheet("padding: 0 4px;")
                combo.addItems(["true", "false"])
                combo.setCurrentText("true" if value else "false")
                return combo
        editor = QLineEdit(parent)
        editor.setFrame(False)
        editor.setStyleSheet("padding: 0 4px;")
        return editor

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect.adjusted(0, 1, 0, -1))

    def setEditorData(self, editor, index):
        value = index.data(Qt.ItemDataRole.DisplayRole)
        if isinstance(editor, QComboBox):
            editor.setCurrentText(str(value))
        else:
            editor.setText("" if value is None else str(value))
            editor.selectAll()

    def setModelData(self, editor, model, index):
        if isinstance(editor, QComboBox):
            model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)
        else:
            model.setData(index, editor.text(), Qt.ItemDataRole.EditRole)


# ----------------------------------------------------------------------
# 主 Tab
# ----------------------------------------------------------------------
class QtYamlEditorTab(QWidget):
    yaml_text_changed = pyqtSignal(str)      # 源码编辑且解析成功（保持与旧版兼容）
    structure_changed = pyqtSignal()          # 树编辑导致结构/值变化
    open_item_requested = pyqtSignal(dict)    # 请求跳转到物品编辑器

    VIEW_TREE, VIEW_SOURCE, VIEW_SPLIT = 0, 1, 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_lang = 'zh-CN'
        self._load_localization(self.current_lang)
        self.main_window = parent
        self.controller = getattr(parent, 'controller', None)

        self.undo_stack = QUndoStack(self)
        self.model = YamlTreeModel(self.controller, self)
        self.model.edit_callback = self._on_model_edit
        self.model.annotation_provider = self._annotation_for
        self.model.change_provider = self._change_for

        self._synced_version = -1
        self._source_valid = True
        self._diff_enabled = False
        self._diff_added, self._diff_modified = set(), set()
        self._serial_info_map = None
        self._search_results = []
        self._search_pos = -1
        self._view_mode = self.VIEW_TREE
        self._chrome = _CHROME_LIGHT

        self.update_timer = QTimer(self)
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self._apply_source_edit)
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self._run_search)

        self._build_ui()
        self._apply_toolbar_state()

    # ------------------------------------------------------------------
    # 本地化
    # ------------------------------------------------------------------
    def _load_localization(self, lang='zh-CN'):
        file_name = resource_loader.get_ui_localization_file(lang)
        data = resource_loader.load_json_resource(file_name)
        fallback = {
            "tree_headers": {"key": "键", "value": "值", "note": "备注"},
            "buttons": {"tree_view": "树状", "source_view": "源码", "split_view": "分屏",
                        "diff": "变更对比", "yaml_view": "YAML视图"},
            "search": {"placeholder": "搜索键或值…", "count": "{current}/{total}",
                       "previous_tooltip": "上一个搜索结果", "next_tooltip": "下一个搜索结果"},
            "inspector": {"path": "当前节点", "no_selection": "未选择节点",
                          "serial_title": "Serial 解码预览", "ops_title": "节点操作",
                          "open_in_editor": "在物品编辑器中打开", "pinned": "常用路径：",
                          "level": "等级", "type": "类型", "manufacturer": "制造商",
                          "container": "位置", "slot": "槽位", "state_flags": "状态标志",
                          "unresolved": "未识别"},
            "ops": {"set_value": "修改值", "rename": "重命名键", "add_child": "添加子节点",
                    "delete": "删除", "duplicate": "复制节点", "copy_path": "复制路径",
                    "copy_value": "复制值", "range_delete": "批量删除槽位范围…"},
            "dialogs": {"yaml_error": "YAML错误", "parse_error": "无法解析YAML: {error}",
                        "add_child_title": "添加子节点", "child_key": "键名：", "child_type": "类型：",
                        "range_delete_title": "批量删除背包槽位", "range_from": "起始槽位：",
                        "range_to": "结束槽位：", "range_preview": "将删除 {count} 个物品（slot_{from} ~ slot_{to}）",
                        "range_none": "该范围内没有物品", "range_confirm": "删除",
                        "delete_confirm": "确认删除 {count} 个节点？", "error": "错误",
                        "delete": "删除", "confirm": "确定", "cancel": "取消"},
            "types": {"str": "字符串", "int": "整数", "float": "小数", "bool": "布尔",
                      "null": "null", "dict": "对象", "list": "列表"},
            "status": {"valid": "YAML 有效", "invalid": "YAML 无效：{error}",
                       "nodes": "共 {count} 个节点", "modified": "● {count} 处未保存修改",
                       "object_items": "对象 · {count} 项", "list_items": "列表 · {count} 项",
                       "flags_bits": "位 {bits}", "serial_ok": "已解码 · Lv{level} {name}"},
            "tooltips": {"undo": "撤销 (Ctrl+Z)", "redo": "重做 (Ctrl+Y)"},
            "shortcuts": {"hint": "Ctrl+Z 撤销 · Ctrl+F 搜索 · F2 重命名 · Del 删除"},
        }
        loc = (data or {}).get("yaml_tab") or {}
        # 深合并：fallback 为底，i18n 覆盖
        merged = copy.deepcopy(fallback)
        for k, v in loc.items():
            if isinstance(v, dict) and isinstance(merged.get(k), dict):
                merged[k].update(v)
            else:
                merged[k] = v
        self.loc = merged

    def update_language(self, lang):
        self.current_lang = lang
        self._load_localization(lang)
        self._refresh_ui_text()

    def apply_theme(self, dark: bool):
        """由主窗口在启动与切换主题时调用：刷新全部配色。"""
        self._chrome = _CHROME_DARK if dark else _CHROME_LIGHT
        self.model.set_dark_mode(dark)
        self.highlighter.apply_theme(self.model.colors)
        self.source_edit.apply_theme(self._chrome["ln_bg"], self._chrome["ln_fg"],
                                     self._chrome["cur_line"])
        self._apply_chrome_styles()
        self._update_status_bar()

    def _apply_chrome_styles(self):
        c = self._chrome
        self.breadcrumb.setStyleSheet(
            f"font-family: Consolas; background: {c['crumb_bg']}; color: {c['crumb_text']};"
            "border-radius: 6px; padding: 6px;")
        self.hint_label.setStyleSheet(f"color: {c['hint']};")
        self.pinned_label.setStyleSheet(f"color: {c['pinned']};")

    def _refresh_ui_text(self):
        b = self.loc['buttons']
        ops = self.loc['ops']
        ins = self.loc['inspector']
        self.model.set_headers((self.loc['tree_headers']['key'],
                                self.loc['tree_headers']['value'],
                                self.loc['tree_headers']['note']))
        self.model.dataChanged.emit(QModelIndex(), QModelIndex(), [])
        self.tree_btn.setText(b['tree_view'])
        self.source_btn.setText(b['source_view'])
        self.split_btn.setText(b['split_view'])
        self.search_edit.setPlaceholderText(self.loc['search']['placeholder'])
        self.prev_btn.setToolTip(self.loc['search']['previous_tooltip'])
        self.prev_btn.setAccessibleName(self.loc['search']['previous_tooltip'])
        self.next_btn.setToolTip(self.loc['search']['next_tooltip'])
        self.next_btn.setAccessibleName(self.loc['search']['next_tooltip'])
        self.undo_action.setToolTip(self.loc['tooltips']['undo'])
        self.redo_action.setToolTip(self.loc['tooltips']['redo'])
        self.undo_btn.setToolTip(self.loc['tooltips']['undo'])
        self.redo_btn.setToolTip(self.loc['tooltips']['redo'])
        self.undo_btn.setAccessibleName(self.loc['tooltips']['undo'])
        self.redo_btn.setAccessibleName(self.loc['tooltips']['redo'])
        self.hint_label.setText(self.loc['shortcuts']['hint'])
        self.path_title.setText(ins['path'])
        self.serial_title.setText(ins['serial_title'])
        self.open_editor_btn.setText(ins['open_in_editor'])
        self.ops_title.setText(ins['ops_title'])
        self.add_child_btn.setText(ops['add_child'])
        self.rename_btn.setText(ops['rename'])
        self.duplicate_btn.setText(ops['duplicate'])
        self.copy_path_btn.setText(ops['copy_path'])
        self.copy_value_btn.setText(ops['copy_value'])
        self.delete_btn.setText(ops['delete'])
        self.range_delete_btn.setText(ops['range_delete'])
        self.pinned_label.setText(ins['pinned'] + "  " + " · ".join(
            ["state.currencies", "state.experience", "state.ammo", "state.inventory"]))
        self._update_diff_button_text()
        self._update_status_bar()
        self._update_inspector(self.tree_view.currentIndex())

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ---- 工具栏 ----
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self.search_edit = QLineEdit()
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMaximumWidth(260)
        self.search_edit.textChanged.connect(lambda: self.search_timer.start(250))
        self.search_edit.returnPressed.connect(lambda: self._cycle_search(1))
        toolbar.addWidget(self.search_edit)
        self.search_count_label = QLabel("")
        self.search_count_label.setMinimumWidth(52)
        toolbar.addWidget(self.search_count_label)
        self.prev_btn = QToolButton(); self.prev_btn.setText("↑"); self.prev_btn.clicked.connect(lambda: self._cycle_search(-1))
        self.next_btn = QToolButton(); self.next_btn.setText("↓"); self.next_btn.clicked.connect(lambda: self._cycle_search(1))
        toolbar.addWidget(self.prev_btn); toolbar.addWidget(self.next_btn)
        QShortcut(QKeySequence.StandardKey.Find, self, self.search_edit.setFocus)

        toolbar.addSpacing(12)
        self.tree_btn = QPushButton(); self.tree_btn.setCheckable(True)
        self.source_btn = QPushButton(); self.source_btn.setCheckable(True)
        self.split_btn = QPushButton(); self.split_btn.setCheckable(True)
        self.tree_btn.clicked.connect(lambda: self._set_view_mode(self.VIEW_TREE))
        self.source_btn.clicked.connect(lambda: self._set_view_mode(self.VIEW_SOURCE))
        self.split_btn.clicked.connect(lambda: self._set_view_mode(self.VIEW_SPLIT))
        toolbar.addWidget(self.tree_btn); toolbar.addWidget(self.source_btn); toolbar.addWidget(self.split_btn)

        toolbar.addSpacing(12)
        self.undo_action = self.undo_stack.createUndoAction(self)
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.redo_action = self.undo_stack.createRedoAction(self)
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        self.addActions([self.undo_action, self.redo_action])
        self.undo_btn = QToolButton(); self.undo_btn.setText("↩"); self.undo_btn.clicked.connect(self.undo_stack.undo)
        self.redo_btn = QToolButton(); self.redo_btn.setText("↪"); self.redo_btn.clicked.connect(self.undo_stack.redo)
        self.undo_btn.setEnabled(self.undo_stack.canUndo())
        self.redo_btn.setEnabled(self.undo_stack.canRedo())
        self.undo_stack.canUndoChanged.connect(self.undo_btn.setEnabled)
        self.undo_stack.canRedoChanged.connect(self.redo_btn.setEnabled)
        toolbar.addWidget(self.undo_btn); toolbar.addWidget(self.redo_btn)

        toolbar.addSpacing(12)
        self.diff_btn = QPushButton(); self.diff_btn.setCheckable(True)
        self.diff_btn.toggled.connect(self._toggle_diff)
        toolbar.addWidget(self.diff_btn)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        # ---- 主区域 ----
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.tree_view = QTreeView()
        self.tree_view.setModel(self.model)
        self.tree_view.setItemDelegate(YamlEditDelegate(self.tree_view))
        self.tree_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree_view.setUniformRowHeights(True)
        self.tree_view.setHeaderHidden(False)
        self.tree_view.setColumnWidth(0, 280)
        self.tree_view.setColumnWidth(1, 320)
        self.tree_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_view.customContextMenuRequested.connect(self._show_context_menu)
        self.tree_view.selectionModel().currentChanged.connect(self._update_inspector)
        self.tree_view.setEditTriggers(QAbstractItemView.EditTrigger.EditKeyPressed |
                                       QAbstractItemView.EditTrigger.SelectedClicked |
                                       QAbstractItemView.EditTrigger.DoubleClicked)
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self.tree_view, self._delete_selection,
                  context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence(Qt.Key.Key_F2), self.tree_view, self._rename_current,
                  context=Qt.ShortcutContext.WidgetWithChildrenShortcut)

        self.right_stack = QStackedWidget()
        self.inspector_page = self._build_inspector()
        self.source_page = self._build_source_page()
        self.right_stack.addWidget(self.inspector_page)
        self.right_stack.addWidget(self.source_page)

        self.splitter.addWidget(self.tree_view)
        self.splitter.addWidget(self.right_stack)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        layout.addWidget(self.splitter, 1)

        # ---- 状态栏 ----
        status = QHBoxLayout()
        status.setContentsMargins(6, 0, 6, 0)
        self.valid_label = QLabel()
        self.node_count_label = QLabel()
        self.modified_label = QLabel()
        self.hint_label = QLabel()
        status.addWidget(self.valid_label)
        status.addSpacing(14)
        status.addWidget(self.node_count_label)
        status.addSpacing(14)
        status.addWidget(self.modified_label)
        status.addStretch(1)
        status.addWidget(self.hint_label)
        layout.addLayout(status)

        self._set_view_mode(self.VIEW_TREE)
        self._apply_chrome_styles()

    def _build_inspector(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(10)

        self.path_title = QLabel(self.loc['inspector']['path'])
        v.addWidget(self.path_title)
        self.breadcrumb = QLabel("—")
        self.breadcrumb.setWordWrap(True)
        self.breadcrumb.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(self.breadcrumb)

        self.serial_box = QFrame()
        self.serial_box.setFrameShape(QFrame.Shape.StyledPanel)
        sb_layout = QVBoxLayout(self.serial_box)
        self.serial_title = QLabel(self.loc['inspector']['serial_title'])
        self.serial_title.setStyleSheet("font-weight: 500;")
        self.serial_info = QLabel()
        self.serial_info.setWordWrap(True)
        self.serial_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.open_editor_btn = QPushButton(self.loc['inspector']['open_in_editor'])
        self.open_editor_btn.clicked.connect(self._emit_open_item)
        sb_layout.addWidget(self.serial_title)
        sb_layout.addWidget(self.serial_info)
        sb_layout.addWidget(self.open_editor_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        self.serial_box.setVisible(False)
        v.addWidget(self.serial_box)

        ops_box = QFrame()
        ops_box.setFrameShape(QFrame.Shape.StyledPanel)
        op_layout = QVBoxLayout(ops_box)
        self.ops_title = QLabel(self.loc['inspector']['ops_title'])
        op_layout.addWidget(self.ops_title)
        ops_grid = QGridLayout()
        ops_grid.setSpacing(6)
        self.add_child_btn = QPushButton(self.loc['ops']['add_child'])
        self.rename_btn = QPushButton(self.loc['ops']['rename'])
        self.duplicate_btn = QPushButton(self.loc['ops']['duplicate'])
        self.copy_path_btn = QPushButton(self.loc['ops']['copy_path'])
        self.copy_value_btn = QPushButton(self.loc['ops']['copy_value'])
        self.delete_btn = QPushButton(self.loc['ops']['delete'])
        self.range_delete_btn = QPushButton(self.loc['ops']['range_delete'])
        # 统一 3 列网格：所有按钮同宽（含范围删除）
        ops_grid.addWidget(self.add_child_btn, 0, 0)
        ops_grid.addWidget(self.rename_btn, 0, 1)
        ops_grid.addWidget(self.duplicate_btn, 0, 2)
        ops_grid.addWidget(self.copy_path_btn, 1, 0)
        ops_grid.addWidget(self.copy_value_btn, 1, 1)
        ops_grid.addWidget(self.delete_btn, 1, 2)
        ops_grid.addWidget(self.range_delete_btn, 2, 0)
        for col in range(3):
            ops_grid.setColumnStretch(col, 1)
        op_layout.addLayout(ops_grid)
        v.addWidget(ops_box)

        self.add_child_btn.clicked.connect(self._add_child_dialog)
        self.rename_btn.clicked.connect(self._rename_current)
        self.duplicate_btn.clicked.connect(self._duplicate_current)
        self.copy_path_btn.clicked.connect(self._copy_current_path)
        self.copy_value_btn.clicked.connect(self._copy_current_value)
        self.delete_btn.clicked.connect(self._delete_selection)
        self.range_delete_btn.clicked.connect(self._range_delete_dialog)

        self.pinned_label = QLabel()
        self.pinned_label.setWordWrap(True)
        v.addWidget(self.pinned_label)
        v.addStretch(1)
        return page

    def _build_source_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        self.source_edit = YamlSourceEditor()
        self.highlighter = YamlHighlighter(self.source_edit.document())
        self.source_edit.textChanged.connect(self._on_source_changed)
        v.addWidget(self.source_edit)
        return page

    # ------------------------------------------------------------------
    # 视图模式
    # ------------------------------------------------------------------
    def _set_view_mode(self, mode):
        self._view_mode = mode
        self.tree_btn.setChecked(mode == self.VIEW_TREE)
        self.source_btn.setChecked(mode == self.VIEW_SOURCE)
        self.split_btn.setChecked(mode == self.VIEW_SPLIT)
        self.tree_view.setVisible(mode != self.VIEW_SOURCE)
        self.right_stack.setCurrentWidget(self.inspector_page if mode == self.VIEW_TREE else self.source_page)
        if mode in (self.VIEW_SOURCE, self.VIEW_SPLIT):
            self._sync_source_from_controller()

    def _apply_toolbar_state(self):
        self._refresh_ui_text()

    # ------------------------------------------------------------------
    # 与 controller 同步（外部刷新入口）
    # ------------------------------------------------------------------
    def sync_from_controller(self):
        """版本号不一致才重建，避免无谓的全量重绘。"""
        if self.controller is None or self.controller.yaml_obj is None:
            return
        if self._synced_version == self.controller.version:
            return
        expanded = self._expanded_paths()
        self.model.reload()
        self._restore_expansion(expanded)
        if not self.source_edit.hasFocus():
            self._set_source_text(self.controller.get_yaml_string())
        self._synced_version = self.controller.version
        self._serial_info_map = None
        self.undo_stack.clear()
        self._update_status_bar()
        if self._diff_enabled:
            self._recompute_diff()

    def set_yaml_text(self, text):
        """兼容旧调用：内容以 controller 为准，走版本检测。"""
        self.sync_from_controller()

    def get_yaml_text(self):
        if self._view_mode in (self.VIEW_SOURCE, self.VIEW_SPLIT):
            return self.source_edit.toPlainText()
        return self.controller.get_yaml_string() if self.controller and self.controller.yaml_obj else self.source_edit.toPlainText()

    def _set_source_text(self, text):
        if self.source_edit.toPlainText() == text:
            return
        self.source_edit.blockSignals(True)
        cursor = self.source_edit.textCursor()
        pos = cursor.position()
        self.source_edit.setPlainText(text)
        cursor = self.source_edit.textCursor()
        cursor.setPosition(min(pos, len(text)))
        self.source_edit.setTextCursor(cursor)
        self.source_edit.blockSignals(False)

    def _sync_source_from_controller(self):
        if self.controller and self.controller.yaml_obj and not self.source_edit.hasFocus():
            self._set_source_text(self.controller.get_yaml_string())

    # ------------------------------------------------------------------
    # 源码编辑 → controller
    # ------------------------------------------------------------------
    def _on_source_changed(self):
        self.update_timer.start(500)

    def _apply_source_edit(self):
        text = self.source_edit.toPlainText()
        try:
            yaml.load(text, Loader=get_yaml_loader())
        except yaml.YAMLError as e:
            self._source_valid = False
            self._update_status_bar(str(e).split('\n')[0])
            return
        self._source_valid = True
        self._update_status_bar()
        self.yaml_text_changed.emit(text)
        # controller 版本已 bump，同步树
        self._synced_version = self.controller.version
        expanded = self._expanded_paths()
        self.model.reload()
        self._restore_expansion(expanded)
        self._serial_info_map = None

    # ------------------------------------------------------------------
    # 树编辑（经 QUndoStack → controller）
    # ------------------------------------------------------------------
    def _on_model_edit(self, action, path, payload):
        try:
            if action == "set":
                cmd = _CmdSetValue(self, path, payload, self.loc['ops']['set_value'])
            elif action == "rename":
                cmd = _CmdRename(self, path, payload, self.loc['ops']['rename'])
            else:
                return False
            self.undo_stack.push(cmd)   # push 会触发 redo()
            return True
        except Exception as e:
            QMessageBox.critical(self, self.loc['dialogs']['error'], str(e))
            return False

    def _after_mutation(self):
        """每次撤销/重做后的统一刷新。"""
        expanded = self._expanded_paths()
        self.model.reload()
        self._restore_expansion(expanded)
        self._synced_version = self.controller.version
        self._serial_info_map = None
        self._sync_source_from_controller()
        self._update_status_bar()
        if self._diff_enabled:
            self._recompute_diff()
        self.structure_changed.emit()

    # ------------------------------------------------------------------
    # 标注 / 变更对比
    # ------------------------------------------------------------------
    def _build_serial_info_map(self):
        self._serial_info_map = {}
        mw = self.main_window
        if mw is None or not hasattr(mw, 'get_items_snapshot'):
            return
        try:
            for item in mw.get_items_snapshot() or []:
                path = tuple(item.get("original_path") or ())
                if path:
                    self._serial_info_map[path + ("serial",)] = item
        except Exception:
            pass

    def _annotation_for(self, path, key, value):
        if isinstance(value, dict):
            return self.loc['status']['object_items'].format(count=len(value))
        if isinstance(value, list):
            return self.loc['status']['list_items'].format(count=len(value))
        if key == 'serial' and isinstance(value, str) and value.startswith('@U'):
            if self._serial_info_map is None:
                self._build_serial_info_map()
            item = (self._serial_info_map or {}).get(tuple(path))
            if item:
                return self.loc['status']['serial_ok'].format(level=item.get("level", "?"),
                                                              name=item.get("name", ""))
            return self.loc['inspector']['unresolved']
        if key == 'state_flags' and isinstance(value, int) and not isinstance(value, bool):
            bits = [str(i) for i in range(value.bit_length()) if value & (1 << i)]
            return self.loc['status']['flags_bits'].format(bits=" + ".join(bits)) if bits else "0"
        return ""

    def _change_for(self, path):
        if not self._diff_enabled:
            return None
        if path in self._diff_added:
            return "added"
        if path in self._diff_modified:
            return "modified"
        return None

    def _toggle_diff(self, on):
        self._diff_enabled = on
        if on:
            self._recompute_diff()
        else:
            self._diff_added, self._diff_modified = set(), set()
            self.model.reload()

    def _recompute_diff(self):
        added, removed, modified = self.controller.diff_from_snapshot()
        self._diff_added, self._diff_modified = set(added), set(modified)
        self._diff_removed_count = len(removed)
        self._update_diff_button_text()
        self.model.reload()

    def _update_diff_button_text(self):
        n = len(self._diff_added) + len(self._diff_modified) + getattr(self, '_diff_removed_count', 0)
        self.diff_btn.setText(f"{self.loc['buttons']['diff']} · {n}" if n else self.loc['buttons']['diff'])

    # ------------------------------------------------------------------
    # 状态栏 / 检查器
    # ------------------------------------------------------------------
    def _update_status_bar(self, error=None):
        c = self._chrome
        if error or not self._source_valid:
            self.valid_label.setText(f"● {self.loc['status']['invalid'].format(error=error or '')}")
            self.valid_label.setStyleSheet(f"color: {c['invalid']};")
        else:
            self.valid_label.setText(f"● {self.loc['status']['valid']}")
            self.valid_label.setStyleSheet(f"color: {c['valid']};")
        if self.controller and self.controller.yaml_obj is not None:
            self.node_count_label.setText(self.loc['status']['nodes'].format(count=self.model.count_nodes()))
            self.modified_label.setText(self.loc['status']['modified'].format(count=1) if self.controller.dirty
                                        else self.loc['status']['modified'].format(count=0))
            self.modified_label.setStyleSheet(
                f"color: {c['modified']};" if self.controller.dirty else f"color: {c['hint']};")
        else:
            self.node_count_label.setText("")
            self.modified_label.setText("")

    def _selected_paths(self):
        paths = []
        for idx in self.tree_view.selectionModel().selectedIndexes():
            if idx.column() == 0:
                item = idx.internalPointer()
                if item and item.path:
                    paths.append(item.path)
        # 去掉被选祖先覆盖的子路径，避免重复删除
        paths = sorted(set(paths), key=len)
        result = []
        for p in paths:
            if not any(len(a) < len(p) and p[:len(a)] == a for a in result):
                result.append(p)
        return result

    def _update_inspector(self, current: QModelIndex, _prev=None):
        ins = self.loc['inspector']
        if not current.isValid():
            self.breadcrumb.setText(ins['no_selection'])
            self.serial_box.setVisible(False)
            return
        item = current.internalPointer()
        path = item.path
        self.breadcrumb.setText(" › ".join(str(p) for p in path) if path else "—")

        # serial 节点本身，或其父级 slot 节点，都展示物品信息
        info_item = None
        if self._serial_info_map is None:
            self._build_serial_info_map()
        smap = self._serial_info_map or {}
        if item.key == 'serial':
            info_item = smap.get(tuple(path))
        else:
            candidate = smap.get(tuple(path) + ("serial",))
            if candidate:
                info_item = candidate
        if info_item:
            self.serial_info.setText(
                f"{info_item.get('name', '')}\n"
                f"{ins['level']}: {info_item.get('level', '?')}  ·  "
                f"{ins['type']}: {info_item.get('type', '?')}  ·  "
                f"{ins['manufacturer']}: {info_item.get('manufacturer', '?')}\n"
                f"{ins['container']}: {info_item.get('container', '?')}  ·  "
                f"{ins['slot']}: {info_item.get('slot', '?')}  ·  "
                f"{ins['state_flags']}: {info_item.get('state_flags', '')}"
            )
            self.serial_box.setVisible(True)
            self._pending_open_item = info_item
        else:
            self.serial_box.setVisible(False)
            self._pending_open_item = None

        pinned = ["state.currencies", "state.experience", "state.ammo", "state.inventory"]
        self.pinned_label.setText(ins['pinned'] + "  " + " · ".join(pinned))

    def _emit_open_item(self):
        item = getattr(self, '_pending_open_item', None)
        if item:
            self.open_item_requested.emit(item)

    # ------------------------------------------------------------------
    # 节点操作
    # ------------------------------------------------------------------
    def _current_index(self):
        idx = self.tree_view.currentIndex()
        return idx if idx.isValid() else None

    def _rename_current(self):
        idx = self._current_index()
        if not idx:
            return
        key_idx = idx.siblingAtColumn(0)
        item = key_idx.internalPointer()
        if item and item.path and not isinstance(item.key, int):
            self.tree_view.edit(key_idx)

    def _delete_selection(self):
        paths = self._selected_paths()
        if not paths:
            return
        if len(paths) > 1:
            box = QMessageBox(QMessageBox.Icon.Question, self.loc['dialogs']['delete'],
                              self.loc['dialogs']['delete_confirm'].format(count=len(paths)),
                              QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
            yes_btn = box.button(QMessageBox.StandardButton.Yes)
            yes_btn.setText(self.loc['dialogs']['delete'])
            box.button(QMessageBox.StandardButton.No).setText(self.loc['dialogs']['cancel'])
            box.exec()
            if box.standardButton(box.clickedButton()) != QMessageBox.StandardButton.Yes:
                return
        self.undo_stack.push(_CmdDelete(self, paths, f"{self.loc['ops']['delete']} ({len(paths)})"))

    def _duplicate_current(self):
        idx = self._current_index()
        if not idx:
            return
        item = idx.internalPointer()
        if not item or not item.path:
            return
        value = copy.deepcopy(self.controller.get_node(item.path))
        parent_path, key = item.path[:-1], item.path[-1]
        try:
            parent = self.controller.get_node(parent_path)
            if isinstance(parent, dict):
                base, n = f"{key}_copy", 2
                new_key = base
                while new_key in parent:
                    new_key = f"{base}_{n}"
                    n += 1
                self.undo_stack.push(_CmdAddChild(self, parent_path, new_key, value,
                                                  self.loc['ops']['duplicate']))
            elif isinstance(parent, list):
                self.undo_stack.push(_CmdAddChild(self, parent_path, None, value,
                                                  self.loc['ops']['duplicate']))
        except Exception as e:
            QMessageBox.critical(self, self.loc['dialogs']['error'], str(e))

    def _add_child_dialog(self):
        idx = self._current_index()
        if not idx:
            return
        item = idx.internalPointer()
        if not item:
            return
        path = item.path
        try:
            value = self.controller.get_node(path)
        except Exception as e:
            QMessageBox.critical(self, self.loc['dialogs']['error'], str(e))
            return
        if not isinstance(value, (dict, list)):
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(self.loc['dialogs']['add_child_title'])
        form = QFormLayout(dlg)
        key_edit = QLineEdit()
        type_combo = QComboBox()
        t = self.loc['types']
        type_keys = ["str", "int", "float", "bool", "null", "dict", "list"]
        for k in type_keys:
            type_combo.addItem(t[k], k)
        if isinstance(value, dict):
            form.addRow(self.loc['dialogs']['child_key'], key_edit)
        form.addRow(self.loc['dialogs']['child_type'], type_combo)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(self.loc['dialogs']['confirm'])
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(self.loc['dialogs']['cancel'])
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        defaults = {"str": "", "int": 0, "float": 0.0, "bool": False, "null": None, "dict": {}, "list": []}
        new_value = defaults[type_combo.currentData()]
        try:
            key = key_edit.text().strip() if isinstance(value, dict) else None
            if isinstance(value, dict) and not key:
                return
            cmd = _CmdAddChild(self, path, key, new_value, self.loc['ops']['add_child'])
            self.undo_stack.push(cmd)
            if cmd.new_path:
                new_idx = self.model.index_for_path(cmd.new_path)
                if new_idx.isValid():
                    self.tree_view.setCurrentIndex(new_idx)
                    parent_idx = self.model.index_for_path(path)
                    self.tree_view.expand(parent_idx)
        except Exception as e:
            QMessageBox.critical(self, self.loc['dialogs']['error'], str(e))

    def _copy_current_path(self):
        idx = self._current_index()
        if not idx:
            return
        path = idx.internalPointer().path
        text = ".".join(f"[{p}]" if isinstance(p, int) else str(p) for p in path)
        QApplication.clipboard().setText(text)

    def _copy_current_value(self):
        idx = self._current_index()
        if not idx:
            return
        value = self.controller.get_node(idx.internalPointer().path)
        if isinstance(value, (dict, list)):
            text = yaml.safe_dump(value, sort_keys=False, allow_unicode=True)
        else:
            text = format_scalar(value)
        QApplication.clipboard().setText(text)

    def _range_delete_dialog(self):
        found = self.controller.find_backpack() if self.controller else None
        if not found:
            QMessageBox.warning(self, self.loc['dialogs']['error'],
                                self.loc['dialogs']['range_none'])
            return
        bp_path, backpack = found
        slot_nums = sorted(int(k[5:]) for k in backpack if str(k).startswith("slot_") and str(k)[5:].isdigit())
        if not slot_nums:
            QMessageBox.warning(self, self.loc['dialogs']['error'],
                                self.loc['dialogs']['range_none'])
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(self.loc['dialogs']['range_delete_title'])
        form = QFormLayout(dlg)
        from_spin = QSpinBox(); from_spin.setRange(slot_nums[0], slot_nums[-1]); from_spin.setValue(slot_nums[0])
        to_spin = QSpinBox(); to_spin.setRange(slot_nums[0], slot_nums[-1]); to_spin.setValue(slot_nums[-1])
        preview = QLabel()
        preview.setStyleSheet(f"color: {self._chrome['modified']};")

        def update_preview():
            a, b = sorted((from_spin.value(), to_spin.value()))
            count = sum(1 for n in range(a, b + 1) if f"slot_{n}" in backpack)
            preview.setText(self.loc['dialogs']['range_preview'].format(count=count, **{"from": a, "to": b}))
            ok_btn.setEnabled(count > 0)
        from_spin.valueChanged.connect(update_preview)
        to_spin.valueChanged.connect(update_preview)
        form.addRow(self.loc['dialogs']['range_from'], from_spin)
        form.addRow(self.loc['dialogs']['range_to'], to_spin)
        form.addRow(preview)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setText(self.loc['dialogs']['range_confirm'])
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(self.loc['dialogs']['cancel'])
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        update_preview()
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        a, b = sorted((from_spin.value(), to_spin.value()))
        paths = [tuple(bp_path) + (f"slot_{n}",) for n in range(a, b + 1) if f"slot_{n}" in backpack]
        if paths:
            self.undo_stack.push(_CmdDelete(self, paths,
                                            f"{self.loc['ops']['range_delete']} [{a}, {b}] ({len(paths)})"))

    # ------------------------------------------------------------------
    # 右键菜单
    # ------------------------------------------------------------------
    def _show_context_menu(self, pos):
        idx = self.tree_view.indexAt(pos)
        menu = QMenu(self)
        ops = self.loc['ops']
        item = idx.internalPointer() if idx.isValid() else None
        value = None
        if item and item.path:
            try:
                value = self.controller.get_node(item.path)
            except Exception:
                value = None

        if item and isinstance(value, (dict, list)):
            menu.addAction(ops['add_child'], self._add_child_dialog)
        if item and item.path and not isinstance(item.key, int):
            menu.addAction(ops['rename'], self._rename_current)
        if item and item.path:
            menu.addAction(ops['duplicate'], self._duplicate_current)
            menu.addSeparator()
            menu.addAction(ops['copy_path'], self._copy_current_path)
            menu.addAction(ops['copy_value'], self._copy_current_value)
            menu.addSeparator()
            menu.addAction(ops['delete'], self._delete_selection)
            # 背包节点（或其后代）上提供范围删除
            bp = self.controller.find_backpack() if self.controller else None
            if bp:
                bp_path = tuple(bp[0])
                if item.path[:len(bp_path)] == bp_path:
                    menu.addAction(ops['range_delete'], self._range_delete_dialog)
        if not menu.isEmpty():
            menu.exec(self.tree_view.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------
    # 搜索
    # ------------------------------------------------------------------
    def _run_search(self):
        needle = self.search_edit.text()
        self._search_results = self.model.search(needle)
        self._search_pos = -1
        if self._search_results:
            self._cycle_search(1)
        else:
            self.search_count_label.setText("0/0" if needle else "")

    def _cycle_search(self, step):
        results = self._search_results
        if not results:
            return
        self._search_pos = (self._search_pos + step) % len(results)
        path = results[self._search_pos]
        self.search_count_label.setText(self.loc['search']['count'].format(
            current=self._search_pos + 1, total=len(results)))
        idx = self.model.index_for_path(path)
        if idx.isValid():
            # 展开所有祖先
            for depth in range(1, len(path) + 1):
                anc = self.model.index_for_path(path[:depth])
                if anc.isValid():
                    self.tree_view.expand(anc)
            self.tree_view.setCurrentIndex(idx)
            self.tree_view.scrollTo(idx, QAbstractItemView.ScrollHint.PositionAtCenter)

    # ------------------------------------------------------------------
    # 展开状态保持
    # ------------------------------------------------------------------
    def _expanded_paths(self):
        paths = set()

        def walk(idx):
            if self.tree_view.isExpanded(idx):
                item = idx.internalPointer()
                if item:
                    paths.add(item.path)
                for r in range(self.model.rowCount(idx)):
                    walk(self.model.index(r, 0, idx))
        walk(QModelIndex())
        return paths

    def _restore_expansion(self, paths):
        if not paths:
            return

        def walk(idx):
            for r in range(self.model.rowCount(idx)):
                child = self.model.index(r, 0, idx)
                ci = child.internalPointer()
                if ci and ci.path in paths:
                    self.tree_view.setExpanded(child, True)
                walk(child)
        walk(QModelIndex())
