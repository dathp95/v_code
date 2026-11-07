import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from gui.widgets.log_analyzer.filter_box import FilterBox


class FilterBoxDebounceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make(self, interval=60):
        box = FilterBox()
        self.addCleanup(box.deleteLater)
        box.show()
        box.edit_filter.setFocus()
        box._debounce_timer.setInterval(interval)  # Short, so tests stay fast.
        emitted = []
        box.filter_changed.connect(emitted.append)
        return box, emitted

    def wait_past_debounce(self, box):
        QTest.qWait(box._debounce_timer.interval() + 120)

    def test_default_delay_is_a_quarter_of_a_second(self):
        self.assertEqual(FilterBox.DEBOUNCE_MS, 250)
        box = FilterBox()
        self.addCleanup(box.deleteLater)
        self.assertEqual(box._debounce_timer.interval(), 250)

    def test_a_burst_of_typing_filters_once_with_the_final_text(self):
        box, emitted = self.make()
        QTest.keyClicks(box.edit_filter, '22F190')
        self.assertEqual(emitted, [])  # Nothing while the user is still typing.
        self.wait_past_debounce(box)
        self.assertEqual(emitted, [box.edit_filter.text()])
        self.assertEqual(box.edit_filter.text(), '22 F1 90')  # The payload formatting still happens at once.

    def test_each_keystroke_restarts_the_wait(self):
        box, emitted = self.make(interval=150)
        for character in '2F':
            QTest.keyClick(box.edit_filter, character)
            QTest.qWait(80)  # Shorter than the delay: the timer keeps being pushed back.
        self.assertEqual(emitted, [])
        self.wait_past_debounce(box)
        self.assertEqual(len(emitted), 1)

    def test_enter_applies_the_filter_immediately(self):
        box, emitted = self.make(interval=5000)
        QTest.keyClicks(box.edit_filter, '22F1')
        QTest.keyClick(box.edit_filter, Qt.Key_Return)
        self.assertEqual(emitted, ['22 F1'])
        self.assertFalse(box._debounce_timer.isActive())

    def test_programmatic_changes_apply_immediately_and_drop_a_pending_typed_one(self):
        box, emitted = self.make(interval=5000)
        QTest.keyClicks(box.edit_filter, 'ab')
        self.assertEqual(emitted, [])
        box.clear()  # What Refresh does: no stale filter may fire afterwards.
        self.assertEqual(emitted, [''])
        self.assertFalse(box._debounce_timer.isActive())
        box.set_text('BCM')
        box.edit_filter.setText('ACU')
        self.assertEqual(emitted, ['', 'BCM', 'ACU'])

    def test_delete_key_path_is_debounced_too_and_emits_the_formatted_text(self):
        box, emitted = self.make()
        box.edit_filter.setText('22 F3 19 0')
        emitted.clear()
        box.edit_filter.setCursorPosition(5)
        QTest.keyClick(box.edit_filter, Qt.Key_Delete)
        self.assertEqual(emitted, [])
        self.wait_past_debounce(box)
        self.assertEqual(emitted, ['22 F3 90'])

    def test_a_typed_change_followed_by_nothing_does_not_leave_later_changes_delayed(self):
        box, emitted = self.make(interval=5000)
        box._on_user_edit('x')  # An edit signal with no text change after it must not stick.
        QTest.qWait(30)
        box.edit_filter.setText('BCM')
        self.assertEqual(emitted, ['BCM'])

    def test_tab_filters_the_table_once_per_burst_not_per_key(self):
        from gui.tabs.log_analyzer_tab import LogAnalyzerTab
        tab = LogAnalyzerTab()
        self.addCleanup(tab.deleteLater)
        tab.filter_box._debounce_timer.setInterval(60)
        tab.show()
        tab.filter_box.edit_filter.setFocus()
        with patch.object(tab.tbl_result, 'fn_search') as search:
            QTest.keyClicks(tab.filter_box.edit_filter, '22F190')
            self.assertEqual(search.call_count, 0)
            QTest.qWait(250)
        self.assertEqual(search.call_count, 1)
        self.assertEqual(search.call_args.args[0], '22 F1 90')


if __name__ == '__main__':
    unittest.main()
