import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication, QHeaderView

from tabs.qt_items_tab import QtItemsTab


APP = QApplication.instance() or QApplication([])


def mouse_move(x):
    pos = QPointF(x, x)
    return QMouseEvent(
        QEvent.Type.MouseMove,
        pos,
        pos,
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )


class ItemCardHoverEventTests(unittest.TestCase):
    def test_mouse_move_delays_card_and_cancels_the_previous_row(self):
        tab = QtItemsTab()
        first = {"serial": "first"}
        second = {"serial": "second"}
        tooltip = Mock()
        tooltip.windowType.return_value = Qt.WindowType.ToolTip
        tab._item_data_from_index = Mock(side_effect=[first, second, second, None])
        tab._weapon_card_html = Mock(side_effect=lambda item: item["serial"])

        with (
            patch("tabs.qt_items_tab.QToolTip.showText") as show,
            patch("tabs.qt_items_tab.QToolTip.hideText") as hide,
            patch("tabs.qt_items_tab.QCursor.pos", return_value=QPoint(2, 2)),
            patch("tabs.qt_items_tab.QApplication.topLevelWidgets", return_value=[tooltip]),
        ):
            tab.eventFilter(tab.tree_view.viewport(), mouse_move(1))
            self.assertTrue(tab._hover_timer.isActive())
            self.assertEqual("first", tab._pending_hover_item["serial"])
            show.assert_not_called()

            tab.eventFilter(tab.tree_view.viewport(), mouse_move(2))
            self.assertTrue(tab._hover_timer.isActive())
            self.assertEqual("second", tab._pending_hover_item["serial"])
            tab._show_pending_hover_card()

            tab.eventFilter(tab.tree_view.viewport(), mouse_move(3))
            tab.eventFilter(tab.tree_view.viewport(), QEvent(QEvent.Type.Leave))

        self.assertTrue(tab.tree_view.viewport().hasMouseTracking())
        show.assert_called_once()
        self.assertEqual("second", show.call_args.args[1])
        self.assertGreaterEqual(hide.call_count, 4)
        tooltip.setAttribute.assert_called_once()
        self.assertIsNone(tab._hover_card_key)
        self.assertIsNone(tab._pending_hover_key)

    def test_timeout_rechecks_the_row_under_the_cursor(self):
        tab = QtItemsTab()
        first = {"serial": "first"}
        second = {"serial": "second"}
        tab._item_data_from_index = Mock(side_effect=[first, second])
        tab._weapon_card_html = Mock(return_value="first")

        with (
            patch("tabs.qt_items_tab.QToolTip.showText") as show,
            patch("tabs.qt_items_tab.QToolTip.hideText"),
            patch("tabs.qt_items_tab.QCursor.pos", return_value=QPoint(2, 2)),
            patch("tabs.qt_items_tab.QApplication.topLevelWidgets", return_value=[]),
        ):
            tab.eventFilter(tab.tree_view.viewport(), mouse_move(1))
            tab._show_pending_hover_card()

        show.assert_not_called()
        tab._weapon_card_html.assert_not_called()
        self.assertIsNone(tab._hover_card_key)

    def test_hide_closes_qt_tooltip_window_immediately(self):
        tab = QtItemsTab()
        tooltip = Mock()
        tooltip.windowType.return_value = Qt.WindowType.ToolTip

        with (
            patch("tabs.qt_items_tab.QToolTip.hideText"),
            patch("tabs.qt_items_tab.QApplication.topLevelWidgets", return_value=[tooltip]),
        ):
            tab._hide_hover_card()

        tooltip.hide.assert_called_once_with()

    def test_delayed_tooltip_event_is_consumed_without_reopening_a_stale_card(self):
        tab = QtItemsTab()
        tab._hover_card_key = ("zh-CN", "", "old")
        with patch("tabs.qt_items_tab.QToolTip.showText") as show:
            handled = tab.eventFilter(tab.tree_view.viewport(), QEvent(QEvent.Type.ToolTip))
        self.assertTrue(handled)
        show.assert_not_called()


class ItemFilterTests(unittest.TestCase):
    ITEMS = [
        {
            "name": "Alpha", "type": "手枪", "type_en": "Pistol",
            "manufacturer": "雅各布斯", "manufacturer_en": "Jakobs",
            "rarity": "传奇", "rarity_en": "Legendary", "level": 60,
            "state_flags": "3", "container": "Backpack", "serial": "@U1",
        },
        {
            "name": "Beta", "type": "冲锋枪", "type_en": "SMG",
            "manufacturer": "马里旺", "manufacturer_en": "Maliwan",
            "rarity": "史诗", "rarity_en": "Epic", "level": 40,
            "state_flags": "5", "container": "Bank", "serial": "@U2",
        },
        {
            "name": "Gamma", "type": "手枪", "type_en": "Pistol",
            "manufacturer": "雅各布斯", "manufacturer_en": "Jakobs",
            "rarity": "稀有", "rarity_en": "Rare", "level": 35,
            "state_flags": "5", "container": "Backpack", "serial": "@U3",
        },
    ]

    @staticmethod
    def leaf_names(tab):
        names = []
        root = tab.model.invisibleRootItem()
        for container_row in range(root.rowCount()):
            container = root.child(container_row)
            for type_row in range(container.rowCount()):
                item_type = container.child(type_row)
                for item_row in range(item_type.rowCount()):
                    if not tab.tree_view.isRowHidden(item_row, item_type.index()):
                        names.append(item_type.child(item_row, 0).text())
        return names

    def test_filters_combine_and_clear(self):
        tab = QtItemsTab()
        tab.update_tree(self.ITEMS)
        tab.filter_combos["type"].setCurrentIndex(tab.filter_combos["type"].findData("Pistol"))
        tab.filter_combos["flags"].setCurrentIndex(tab.filter_combos["flags"].findData("5"))
        tab.filter_min_level.setValue(30)
        tab.filter_max_level.setValue(40)
        APP.processEvents()
        self.assertEqual(["Gamma"], self.leaf_names(tab))
        self.assertIn("1/3", tab.filter_count_label.text())
        tab._clear_filters()
        self.assertCountEqual(["Alpha", "Beta", "Gamma"], self.leaf_names(tab))
        self.assertIn("3/3", tab.filter_count_label.text())
        tab.deleteLater()

    def test_name_column_is_bounded_and_all_columns_are_user_resizable(self):
        tab = QtItemsTab()
        tab.update_tree(self.ITEMS)
        header = tab.tree_view.header()
        self.assertEqual(QHeaderView.ResizeMode.Interactive, header.sectionResizeMode(0))
        self.assertEqual(240, tab.tree_view.columnWidth(0))
        self.assertLess(tab.tree_view.columnWidth(0), 320)
        self.assertEqual(180, tab.tree_view.columnWidth(6))
        tab.deleteLater()


if __name__ == "__main__":
    unittest.main()
