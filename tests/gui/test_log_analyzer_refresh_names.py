import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication

import core.uds_lookup as uds_lookup
from core.pipeline import refresh_display_names, run_pipeline
from gui.tabs.log_analyzer_tab import LogAnalyzerTab
from models.ecu import ECU
from models.vehicle import Vehicle

LOG = (
    '0.001 2 681 Rx d 8 03 22 F1 90 00 00 00 00\n'
    '0.011 2 601 Rx d 8 06 62 F1 90 4D 47 55 00\n'
    '0.101 2 681 Rx d 8 02 10 03 00 00 00 00 00\n'
    '0.111 2 601 Rx d 8 02 50 03 00 00 00 00 00\n'
)


class RefreshDisplayNamesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.directory.cleanup)
        self.log = Path(self.directory.name) / 'log.asc'
        self.log.write_text(LOG, encoding='utf-8')
        self.vehicle = Vehicle(name='V', ecus=[ECU(name='BCM', request_id='681', response_id='601')])
        self.tab = LogAnalyzerTab()
        self.addCleanup(self.tab.deleteLater)
        self.names = dict(uds_lookup.DISPLAY_NAME_MAP)
        patcher = patch.dict(uds_lookup.DISPLAY_NAME_MAP, self.names, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def analyse(self):
        result = run_pipeline(str(self.log), self.vehicle, channel=2)
        self.tab.analysis_controller.pipeline_result = result
        self.tab._fn_analysis_finished(result)
        return result

    def activities(self):
        table = self.tab.tbl_result
        column = list(table.TRANSACTION_FIELDS).index('Activity')
        return [table.item(row, column).text() for row in range(table.rowCount())]

    def import_names(self, **names):
        """What Import Display Names does: the mapping used by the next lookups changes."""
        uds_lookup.DISPLAY_NAME_MAP.update({key.replace('_', ' '): value for key, value in names.items()})

    # --- the Refresh button ----------------------------------------------------------
    def test_refresh_applies_new_names_without_running_the_analysis_again(self):
        self.analyse()
        before = self.activities()
        self.import_names(**{'22_F1_90': 'READ VIN 1'})
        self.assertEqual(self.activities(), before)  # Importing alone changes nothing on screen yet.
        with patch('gui.tabs.log_analyzer_tab.run_pipeline', create=True) as rerun, \
                patch.object(self.tab.analysis_controller, 'fn_run') as run:
            self.tab.filter_box.btn_refresh.click()
        rerun.assert_not_called()
        run.assert_not_called()
        after = self.activities()
        self.assertEqual(after[0], 'READ VIN 1')
        self.assertEqual(after[1:], before[1:])  # Other rows untouched.

    def test_only_the_name_changes_not_the_analysis_data(self):
        result = self.analyse()
        table = self.tab.tbl_result
        snapshot = [[table.item(row, column).text() for column in range(table.columnCount())
                     if table.horizontalHeaderItem(column).text() != 'Activity'] for row in range(table.rowCount())]
        statuses = [tx['status'] for tx in result['transactions']]
        self.import_names(**{'22_F1_90': 'READ VIN 1'})
        self.tab.fn_refresh_table()
        after = [[table.item(row, column).text() for column in range(table.columnCount())
                  if table.horizontalHeaderItem(column).text() != 'Activity'] for row in range(table.rowCount())]
        self.assertEqual(after, snapshot)
        self.assertEqual([tx['status'] for tx in result['transactions']], statuses)

    def test_result_used_for_export_follows_the_new_names_too(self):
        result = self.analyse()
        self.import_names(**{'22_F1_90': 'READ VIN 1'})
        self.tab.fn_refresh_table()
        self.assertEqual(result['transactions'][0]['display_name'], 'READ VIN 1')
        activities = [a['display_name'] for report in result['ecu_reports'].values() for a in report['activities']]
        self.assertIn('READ VIN 1', activities)
        self.assertIs(self.tab.analysis_controller.pipeline_result, result)
        self.assertTrue(result['summary'])

    def test_renaming_back_and_repeating_the_refresh_is_stable(self):
        self.analyse()
        original = self.activities()
        self.import_names(**{'22_F1_90': 'READ VIN 1'})
        self.tab.fn_refresh_table()
        self.tab.fn_refresh_table()
        self.assertEqual(self.activities()[0], 'READ VIN 1')
        self.import_names(**{'22_F1_90': original[0]})
        self.tab.fn_refresh_table()
        self.assertEqual(self.activities(), original)

    def test_refresh_still_resets_filter_selection_and_panels_like_before(self):
        self.analyse()
        self.tab.filter_box.edit_filter.setText('10 03')
        self.tab.tbl_result.setCurrentCell(0, 0)
        self.tab.fn_refresh_table()
        self.assertEqual(self.tab.filter_box.edit_filter.text(), '')
        self.assertEqual(self.tab.tbl_result.currentRow(), -1)
        self.assertEqual(sum(not self.tab.tbl_result.isRowHidden(r) for r in range(self.tab.tbl_result.rowCount())),
                         self.tab.tbl_result.rowCount())

    def test_refresh_with_nothing_analysed_does_not_fail(self):
        self.assertIsNone(self.tab.analysis_controller.pipeline_result)
        self.tab.fn_refresh_table()
        self.assertEqual(self.tab.tbl_result.rowCount(), 0)

    # --- the message after Import ----------------------------------------------------
    def test_import_message_points_to_refresh_when_a_result_is_on_screen(self):
        self.analyse()
        controller = self.tab.display_names_import
        with patch('gui.controllers.display_names_import_controller.ImportDisplayNamesDialog') as dialog, \
                patch('gui.controllers.display_names_import_controller.import_display_name_rules'), \
                patch('gui.controllers.display_names_import_controller.reload_display_names'), \
                patch('gui.controllers.display_names_import_controller.QMessageBox') as box:
            dialog.return_value.exec.return_value = 1
            dialog.return_value.fn_rules.return_value = '22 F1 90 | READ VIN 1'
            controller.import_rules()
        self.assertIn('Refresh', box.return_value.setText.call_args.args[0])

    def test_import_message_has_no_hint_without_a_result(self):
        controller = self.tab.display_names_import
        with patch('gui.controllers.display_names_import_controller.ImportDisplayNamesDialog') as dialog, \
                patch('gui.controllers.display_names_import_controller.import_display_name_rules'), \
                patch('gui.controllers.display_names_import_controller.reload_display_names'), \
                patch('gui.controllers.display_names_import_controller.QMessageBox') as box:
            dialog.return_value.exec.return_value = 1
            dialog.return_value.fn_rules.return_value = '22 F1 90 | READ VIN 1'
            controller.import_rules()
        self.assertNotIn('Refresh', box.return_value.setText.call_args.args[0])

    # --- the core helper -------------------------------------------------------------
    def test_refresh_display_names_helper_handles_a_missing_payload(self):
        result = {'transactions': [], 'ecu_reports': {}, 'summary': []}
        self.assertIs(refresh_display_names(result), result)
        self.assertEqual(result['transactions'], [])


if __name__ == '__main__':
    unittest.main()
