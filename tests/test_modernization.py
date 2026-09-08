"""Release contracts for the optimized editor and shared presentation."""

import copy
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import yaml
from PyQt6.QtCore import qInstallMessageHandler
from PyQt6.QtWidgets import QApplication

from core import b_encoder, bl4_functions
from core.batch import add_serial_lines
from core.save_game_controller import SaveGameController
from core.yaml_io import get_yaml_loader, dump_yaml
from tabs.qt_converter_tab import BatchConverterWorker


SAMPLE = '278, 0, 1, 60| 2, 371|| {7} {2} {245:[25 29 42 76 7]}|'


def controller():
    result = SaveGameController()
    result.yaml_obj = {'state': {'inventory': {'items': {'backpack': {
        'slot_3': {'serial': '@U-old', 'state_flags': 1}, 'metadata': 'retain',
    }}}}}
    return result


class ModernizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.serial, error = b_encoder.encode_to_base85(SAMPLE)
        assert not error

    def test_safe_yaml_tags_and_encrypted_roundtrip(self):
        value = yaml.load('text: !GameText "中文\\nsecond line"\nmap: !GameMap {a: 1.25, b: [yes, null]}', Loader=get_yaml_loader())
        self.assertEqual(value['map'], {'a': 1.25, 'b': [True, None]})
        self.assertEqual(value, yaml.load(dump_yaml(value, allow_unicode=True), Loader=get_yaml_loader()))
        self.assertIs(get_yaml_loader(), bl4_functions.get_yaml_loader())
        for platform, uid in [('steam', '76561198000000001'), ('epic', 'a1234567890bcdef1234567890abcdef12')]:
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as folder:
                original = controller()
                original.yaml_obj['tagged'] = value
                original.platform, original.user_id = platform, uid
                target = Path(folder) / 'test.sav'
                original.save_to_disk(target)
                restored = SaveGameController()
                restored.decrypt_save(target, uid)
                self.assertEqual(restored.yaml_obj, original.yaml_obj)
                self.assertTrue(restored.is_content_saved())

    def test_bulk_slots_failures_order_and_one_notification(self):
        c = controller()
        changes = []
        c.add_dirty_listener(lambda: changes.append(c.version))
        result = c.add_items_to_backpack([self.serial, '', None, self.serial], '17')
        self.assertEqual([r[-1] if r else None for r in result], ['slot_4', None, None, 'slot_5'])
        self.assertEqual(changes, [1])
        before = copy.deepcopy(c.yaml_obj)
        self.assertEqual(c.add_items_to_backpack([self.serial], 'invalid'), [None])
        self.assertEqual(before, c.yaml_obj)
        self.assertEqual(c.add_item_to_backpack(self.serial, '1')[-1], 'slot_6')
        progress = list(add_serial_lines(c, [SAMPLE, self.serial, 'invalid serial'], '1'))
        self.assertEqual(progress[0], (0, 3, 0, 0))
        self.assertEqual(progress[-1], (3, 3, 2, 1))

    def test_converter_localization_results_and_throttled_progress(self):
        worker = BatchConverterWorker([self.serial, SAMPLE] * 100 + ['invalid'], {'status_error': '错误：{error}'})
        results, progress = [], []
        worker.finished.connect(results.extend)
        worker.progress.connect(lambda *args: progress.append(args))
        worker.run()
        self.assertEqual(len(results), 201)
        self.assertTrue(results[-1].startswith('错误：'))
        self.assertEqual(progress[0], (0, 201))
        self.assertEqual(progress[-1], (201, 201))
        self.assertLess(len(progress), 50)

    def test_background_dirty_notification_reaches_gui_timer(self):
        from main_window import MainWindow
        messages = []
        previous = qInstallMessageHandler(lambda kind, context, message: messages.append(message))
        try:
            with patch.object(MainWindow, 'scan_for_saves', lambda self: None):
                window = MainWindow()
                window.autosave_enabled = True
                window.controller.yaml_obj = controller().yaml_obj
                thread = threading.Thread(target=lambda: window.controller.add_item_to_backpack(self.serial, '1'))
                thread.start()
                thread.join()
                self.app.processEvents()
                self.assertTrue(window._autosave_timer.isActive())
                self.assertFalse(any('Timers cannot be started' in message for message in messages))
                window.controller.mark_clean()
                window.close()
                window.deleteLater()
        finally:
            qInstallMessageHandler(previous)

    def test_inventory_filter_reuses_rows_cards_and_reveals_deep_links(self):
        from tabs.qt_items_tab import QtItemsTab
        tab = QtItemsTab()
        items = [{'name': name, 'type': 'Weapon', 'type_en': 'Weapon', 'manufacturer': 'Torgue',
                  'manufacturer_en': 'Torgue', 'rarity': 'Epic', 'rarity_en': 'Epic',
                  'level': 60, 'serial': self.serial, 'state_flags': flag, 'container': 'Backpack',
                  'original_path': ['backpack', f'slot_{i}']} for i, (name, flag) in enumerate([('Alpha', 1), ('Beta', 3)])]
        tab.update_tree(items)
        group = tab.model.item(0).child(0)
        first, second = group.child(0), group.child(1)
        tab.select_item_by_path(items[0]['original_path'])
        tab._card_cache[('cached',)] = 'card'
        tab.search_entry.setText('ALPHA')
        self.assertTrue(tab._search_timer.isActive())
        tab._apply_filters()
        self.assertIs(first, group.child(0))
        self.assertIs(second, group.child(1))
        self.assertTrue(tab.tree_view.isRowHidden(1, group.index()))
        self.assertEqual(group.text(), 'Weapon (1)')
        self.assertEqual(tab.current_selected_item['name'], 'Alpha')
        self.assertIn(('cached',), tab._card_cache)
        self.assertTrue(tab.select_item_by_path(items[1]['original_path']))
        self.assertFalse(tab.tree_view.isRowHidden(1, group.index()))
        flags = tab.filter_combos['flags']
        flags.setCurrentIndex(flags.findData('3'))
        self.assertTrue(tab.tree_view.isRowHidden(0, group.index()))
        tab.update_tree(items)
        self.assertFalse(tab._card_cache)
        tab.close()

    def test_inline_catalog_retains_widgets_counts_and_filter_state(self):
        from tabs.qt_catalog_picker import InlineCatalogPicker
        picker = InlineCatalogPicker(multi_select=True)
        items = [{'key': i, 'label': label, 'max_count': 9} for i, label in enumerate(['Alpha', 'Beta'])]
        picker.set_source(items)
        row = picker.list.itemWidget(picker.list.item(0))
        picker.add_item(items[0], 3)
        picker.search.setText('beta')
        picker._refilter()
        self.assertTrue(picker.list.item(0).isHidden())
        self.assertIs(row, picker.list.itemWidget(picker.list.item(0)))
        self.assertEqual(picker.entries()[0]['count'], 3)
        picker.search.clear()
        picker._refilter()
        self.assertEqual(row._count, 3)
        self.assertFalse(picker.list.item(0).isHidden())
        picker.clear()
        self.assertEqual(row._count, 0)
        picker.close()


if __name__ == '__main__':
    unittest.main()
