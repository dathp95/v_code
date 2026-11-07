import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QHeaderView

from gui.tabs.log_analyzer_tab import LogAnalyzerTab
from gui.widgets.log_analyzer.result_table import ResultTable

ROWS = [{'ECU': 'BCM', 'Time': '123.456789', 'Activity': 'System Supplier ECU Hardware Number',
         'Request': '22 F1 92', 'Response': '62 F1 92 4D 47 55 00 11 22 33 44 55', 'RT (ms)': 12.34,
         'Status': 'NRC_ONLY'} for _ in range(30)]


class ResultTableColumnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def table_at(self, width):
        table = ResultTable()
        self.addCleanup(table.deleteLater)
        table.resize(width, 500)
        table.show()
        table.set_data(ROWS)
        self.app.processEvents()
        return table

    def column(self, table, name):
        return table.TRANSACTION_FIELDS.index(name)

    def assert_every_column_visible(self, table):
        header, viewport = table.horizontalHeader(), table.viewport().width()
        self.assertEqual(table.horizontalScrollBar().maximum(), 0, 'needs a horizontal scroll bar')
        for field in table.TRANSACTION_FIELDS:
            index = self.column(table, field)
            self.assertLessEqual(header.sectionViewportPosition(index) + header.sectionSize(index), viewport, field)

    def test_every_column_including_status_fits_the_table_of_a_1366_px_screen(self):
        for width in (700, 720, 800, 1000):  # The table is about 700 px wide beside the side panels at 1366.
            with self.subTest(width=width):
                self.assert_every_column_visible(self.table_at(width))

    def test_status_and_rt_keep_a_readable_width(self):
        table = self.table_at(700)
        header = table.horizontalHeader()
        self.assertGreaterEqual(header.sectionSize(self.column(table, 'Status')), 80)
        self.assertGreaterEqual(header.sectionSize(self.column(table, 'RT (ms)')), 60)
        self.assertGreaterEqual(header.sectionSize(self.column(table, 'ECU')), 60)

    def test_activity_keeps_enough_room_for_a_typical_name_at_1366(self):
        tab = LogAnalyzerTab()
        self.addCleanup(tab.deleteLater)
        tab.resize(1366, 768)
        tab.show()
        self.app.processEvents()
        tab.tbl_result.set_data(ROWS)
        self.app.processEvents()
        header = tab.tbl_result.horizontalHeader()
        self.assertGreaterEqual(header.sectionSize(self.column(tab.tbl_result, 'Activity')), 140)
        self.assertGreaterEqual(header.sectionSize(self.column(tab.tbl_result, 'Response')), 140)

    def test_activity_and_response_take_the_leftover_space(self):
        narrow, wide = self.table_at(700), self.table_at(1100)
        for name in ('Activity', 'Response'):
            self.assertGreater(wide.horizontalHeader().sectionSize(self.column(wide, name)),
                               narrow.horizontalHeader().sectionSize(self.column(narrow, name)), name)
        # The fixed columns do not grow with the window.
        for name in ('ECU', 'Time', 'Request', 'RT (ms)', 'Status'):
            self.assertEqual(wide.horizontalHeader().sectionSize(self.column(wide, name)),
                             narrow.horizontalHeader().sectionSize(self.column(narrow, name)), name)

    def test_activity_and_response_never_collapse_when_the_window_is_small(self):
        table = self.table_at(420)
        header = table.horizontalHeader()
        for name in ('Activity', 'Response'):
            self.assertGreaterEqual(header.sectionSize(self.column(table, name)), 60, name)

    def test_columns_that_stay_fixed_can_still_be_resized_by_hand(self):
        table = self.table_at(900)
        header = table.horizontalHeader()
        self.assertEqual(header.sectionResizeMode(self.column(table, 'Request')), QHeaderView.Interactive)
        self.assertEqual(header.sectionResizeMode(self.column(table, 'Status')), QHeaderView.Interactive)

    def test_in_the_log_analyzer_at_1366_by_768_status_is_on_screen(self):
        tab = LogAnalyzerTab()
        self.addCleanup(tab.deleteLater)
        tab.resize(1366, 768)
        tab.show()
        self.app.processEvents()
        tab.tbl_result.set_data(ROWS)
        self.app.processEvents()
        self.assert_every_column_visible(tab.tbl_result)


if __name__ == '__main__':
    unittest.main()
