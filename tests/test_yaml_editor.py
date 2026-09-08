# -*- coding: utf-8 -*-
"""YAML 编辑器现代化改造的回归测试：路径 API、树模型、原子保存。"""
import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml
from core.save_game_controller import SaveGameController

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SAMPLE = {
    "state": {
        "char_name": "测试",
        "experience": [{"type": "Character", "level": 50, "points": 100}],
        "inventory": {"items": {"backpack": {
            "slot_0": {"serial": "@Ugaaa", "state_flags": 1},
            "slot_1": {"serial": "@Ugbbb", "state_flags": 17},
            "slot_3": {"serial": "@Ugccc", "state_flags": 513},
        }}},
        "blackmarket_cooldown": 0,
    },
    "globals": {"a": 1},
}


def make_controller():
    c = SaveGameController()
    c.yaml_obj = copy.deepcopy(SAMPLE)
    c._snapshot = copy.deepcopy(SAMPLE)
    return c


class ControllerPathApiTest(unittest.TestCase):
    def test_get_set_roundtrip(self):
        c = make_controller()
        self.assertEqual(c.get_node(("state", "experience", 0, "level")), 50)
        c.set_value(("state", "experience", 0, "level"), 51)
        self.assertEqual(c.get_node(("state", "experience", 0, "level")), 51)
        self.assertTrue(c.dirty)

    def test_rename_preserves_order(self):
        c = make_controller()
        keys_before = list(c.yaml_obj["state"].keys())
        idx = keys_before.index("char_name")
        c.rename_key(("state", "char_name"), "renamed")
        keys_after = list(c.yaml_obj["state"].keys())
        self.assertEqual(keys_after.index("renamed"), idx)
        self.assertEqual(len(keys_after), len(keys_before))

    def test_add_delete_restore(self):
        c = make_controller()
        new_path = c.add_child(("state",), "new_key", {"x": 1})
        self.assertEqual(new_path, ("state", "new_key"))
        removed = c.delete_node(("state", "new_key"))
        self.assertNotIn("new_key", c.yaml_obj["state"])
        c.restore_nodes([(("state", "new_key"), removed)])
        self.assertEqual(c.yaml_obj["state"]["new_key"], {"x": 1})

    def test_delete_nodes_list_indices_descending(self):
        c = make_controller()
        c.yaml_obj["state"]["experience"].append({"type": "Specialization", "level": 7})
        c.yaml_obj["state"]["experience"].append({"type": "Extra", "level": 9})
        deleted = c.delete_nodes([("state", "experience", 0), ("state", "experience", 1)])
        self.assertEqual(len(deleted), 2)
        self.assertEqual(len(c.get_node(("state", "experience"))), 1)
        self.assertEqual(c.get_node(("state", "experience", 0, "type")), "Extra")
        c.restore_nodes(deleted)
        self.assertEqual(c.get_node(("state", "experience", 0, "type")), "Character")
        self.assertEqual(c.get_node(("state", "experience", 1, "type")), "Specialization")

    def test_backpack_range_delete(self):
        c = make_controller()
        deleted = c.delete_backpack_range(0, 3)
        self.assertEqual(len(deleted), 3)  # slot_0/1/3 都在范围内
        bp = c.get_node(("state", "inventory", "items", "backpack"))
        self.assertEqual(len(bp), 0)
        c.restore_nodes(deleted)
        self.assertEqual(len(bp), 3)

    def test_diff_from_snapshot(self):
        c = make_controller()
        c.set_value(("state", "blackmarket_cooldown"), 9)
        c.delete_node(("globals", "a"))
        c.add_child(("state",), "added_key", 1)
        added, removed, modified = c.diff_from_snapshot()
        self.assertIn(("state", "added_key"), added)
        self.assertIn(("globals", "a"), removed)
        self.assertIn(("state", "blackmarket_cooldown"), modified)

    def test_atomic_save_and_digest_dedup(self):
        c = make_controller()
        c.platform, c.user_id = "steam", "76561198000000001"
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "1.sav"
            target.write_bytes(b"old-bytes")
            c.save_path = target
            saved = c.save_to_disk()
            self.assertTrue(saved.exists())
            self.assertFalse(c.dirty)
            # 旧内容已轮转
            self.assertEqual((Path(tmp) / "1.sav.prev.bak").read_bytes(), b"old-bytes")
            # 内容一致判定 → 不重复写盘
            self.assertTrue(c.is_content_saved())
            # 写盘结果可被解密回读
            plain = c._try_once(c._key_steam(c.user_id), saved.read_bytes(), False)
            data = yaml.load(plain, Loader=c._get_yaml_loader())
            self.assertEqual(data["state"]["char_name"], "测试")


class YamlTreeModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_model_browse_and_edit(self):
        from PyQt6.QtCore import QModelIndex, Qt
        from core.yaml_model import YamlTreeModel
        c = make_controller()
        model = YamlTreeModel(c)
        edits = []
        model.edit_callback = lambda action, path, payload: edits.append((action, path, payload)) or True

        self.assertEqual(model.rowCount(QModelIndex()), 2)  # state / globals
        idx = model.index_for_path(("state", "experience", 0, "level"))
        self.assertTrue(idx.isValid())
        self.assertEqual(idx.siblingAtColumn(1).data(), "50")

        ok = model.setData(idx.siblingAtColumn(1), "51", Qt.ItemDataRole.EditRole)
        self.assertTrue(ok)
        self.assertEqual(edits[-1], ("set", ("state", "experience", 0, "level"), 51))

        # 非法输入被拒绝
        ok = model.setData(idx.siblingAtColumn(1), "abc", Qt.ItemDataRole.EditRole)
        self.assertFalse(ok)

        # bool 解析
        c.yaml_obj["state"]["flag"] = True
        model.reload()
        bidx = model.index_for_path(("state", "flag"))
        ok = model.setData(bidx.siblingAtColumn(1), "false", Qt.ItemDataRole.EditRole)
        self.assertTrue(ok)
        self.assertEqual(edits[-1][2], False)

    def test_model_search(self):
        from core.yaml_model import YamlTreeModel
        c = make_controller()
        model = YamlTreeModel(c)
        hits = model.search("char_name")
        self.assertIn(("state", "char_name"), hits)
        hits = model.search("@ugbb")
        self.assertTrue(any(p[-1] == "serial" for p in hits))
        self.assertEqual(model.count_nodes(), 23)


class YamlEditorUiRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def _make_tab(self):
        from PyQt6.QtWidgets import QWidget
        from tabs.qt_yaml_editor_tab import QtYamlEditorTab

        parent = QWidget()
        parent.controller = make_controller()
        tab = QtYamlEditorTab(parent)
        tab.sync_from_controller()
        return parent, tab

    def test_language_switch_refreshes_every_static_yaml_control(self):
        expected = {
            "zh-CN": ("树状", "当前节点", "添加子节点", "上一个搜索结果", "状态标志"),
            "en-US": ("Tree", "Current node", "Add child", "Previous search result", "State flags"),
            "ru": ("Дерево", "Текущий узел", "Добавить узел", "Предыдущий результат поиска", "Флаги состояния"),
            "ua": ("Дерево", "Поточний вузол", "Додати вузол", "Попередній результат пошуку", "Прапорці стану"),
        }
        parent, tab = self._make_tab()
        try:
            for lang, values in expected.items():
                tab.update_language(lang)
                self.app.processEvents()
                tree, path, add_child, previous, state_flags = values
                self.assertEqual(tree, tab.tree_btn.text())
                self.assertEqual(path, tab.path_title.text())
                self.assertEqual(add_child, tab.add_child_btn.text())
                self.assertEqual(previous, tab.prev_btn.toolTip())
                self.assertEqual(state_flags, tab.loc["inspector"]["state_flags"])
                self.assertEqual(tab.loc["inspector"]["serial_title"], tab.serial_title.text())
                self.assertEqual(tab.loc["inspector"]["open_in_editor"], tab.open_editor_btn.text())
                self.assertEqual(tab.loc["inspector"]["ops_title"], tab.ops_title.text())
                self.assertEqual(tab.loc["ops"]["rename"], tab.rename_btn.text())
                self.assertEqual(tab.loc["ops"]["duplicate"], tab.duplicate_btn.text())
                self.assertEqual(tab.loc["ops"]["copy_path"], tab.copy_path_btn.text())
                self.assertEqual(tab.loc["ops"]["copy_value"], tab.copy_value_btn.text())
                self.assertEqual(tab.loc["ops"]["delete"], tab.delete_btn.text())
                self.assertEqual(tab.loc["ops"]["range_delete"], tab.range_delete_btn.text())
                self.assertEqual(tab.loc["search"]["placeholder"], tab.search_edit.placeholderText())
                self.assertEqual(tab.loc["search"]["next_tooltip"], tab.next_btn.toolTip())
                self.assertEqual(tab.loc["tooltips"]["undo"], tab.undo_action.toolTip())
                self.assertEqual(tab.loc["tooltips"]["redo"], tab.redo_action.toolTip())
                self.assertEqual(tab.loc["tooltips"]["undo"], tab.undo_btn.toolTip())
                self.assertEqual(tab.loc["tooltips"]["redo"], tab.redo_btn.toolTip())
                self.assertEqual("↩", tab.undo_btn.text())
                self.assertEqual("↪", tab.redo_btn.text())
                self.assertEqual(tab.loc["shortcuts"]["hint"], tab.hint_label.text())
                self.assertTrue(tab.loc["dialogs"]["confirm"])
                self.assertTrue(tab.loc["dialogs"]["cancel"])
            tab._on_model_edit("set", ("state", "blackmarket_cooldown"), 9)
            self.app.processEvents()
            self.assertEqual("↩", tab.undo_btn.text())
            self.assertEqual("↪", tab.redo_btn.text())
            self.assertTrue(tab.undo_btn.isEnabled())
        finally:
            tab.deleteLater()
            parent.deleteLater()

    def test_inline_editor_keeps_usable_geometry(self):
        from PyQt6.QtCore import QRect
        from PyQt6.QtWidgets import QComboBox, QLineEdit, QStyleOptionViewItem
        from tabs.qt_yaml_editor_tab import YamlEditDelegate

        parent, tab = self._make_tab()
        try:
            delegate = YamlEditDelegate(tab.tree_view)
            option = QStyleOptionViewItem()
            option.rect = QRect(10, 20, 300, 21)

            value_index = tab.model.index_for_path(
                ("state", "experience", 0, "level")
            ).siblingAtColumn(1)
            line_edit = delegate.createEditor(tab.tree_view.viewport(), option, value_index)
            self.assertIsInstance(line_edit, QLineEdit)
            self.assertIn("padding: 0 4px", line_edit.styleSheet())
            delegate.updateEditorGeometry(line_edit, option, value_index)
            self.assertEqual(QRect(10, 21, 300, 19), line_edit.geometry())

            tab.controller.yaml_obj["state"]["flag"] = True
            tab.model.reload()
            bool_index = tab.model.index_for_path(("state", "flag")).siblingAtColumn(1)
            combo = delegate.createEditor(tab.tree_view.viewport(), option, bool_index)
            self.assertIsInstance(combo, QComboBox)
            self.assertIn("padding: 0 4px", combo.styleSheet())
            delegate.updateEditorGeometry(combo, option, bool_index)
            self.assertEqual(QRect(10, 21, 300, 19), combo.geometry())
        finally:
            tab.deleteLater()
            parent.deleteLater()


if __name__ == "__main__":
    unittest.main()
