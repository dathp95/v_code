import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QGroupBox, QPlainTextEdit, QProgressBar


class LogAnalyzerDetailPanelTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_action_panel_has_independent_detail_areas(self):
        from gui.widgets.log_analyzer.action_panel import ActionPanel

        panel = ActionPanel()
        self.addCleanup(panel.deleteLater)

        self.assertIsInstance(panel.grp_quick_filter_info, QGroupBox)
        self.assertIsInstance(panel.grp_transaction_info, QGroupBox)
        self.assertEqual(panel.grp_quick_filter_info.title(), "Quick Filter")
        self.assertEqual(panel.grp_transaction_info.title(), "Transaction")
        self.assertIsInstance(panel.txt_quick_filter_info, QPlainTextEdit)
        self.assertIsInstance(panel.txt_transaction_info, QPlainTextEdit)
        self.assertTrue(panel.txt_quick_filter_info.isReadOnly())
        self.assertTrue(panel.txt_transaction_info.isReadOnly())

        self.assertEqual(
            panel.txt_quick_filter_info.toPlainText(),
            "Name: -\n\nECU: -\n\nRequest: -\n\nResponse: -",
        )
        self.assertEqual(
            panel.txt_transaction_info.toPlainText(),
            "ECU: -\n\nTime: -\n\nActivity: -\n\nRequest: -\n\nResponse: -\n\nRT (ms): -\n\nStatus: -",
        )

    def test_action_panel_keeps_quick_filter_and_transaction_details_separate(self):
        from gui.widgets.log_analyzer.action_panel import ActionPanel

        panel = ActionPanel()
        self.addCleanup(panel.deleteLater)

        panel.fn_set_quick_filter_info(
            {
                "name": "Filter 22 F1 90",
                "filters": {
                    "ecu": "MHU",
                    "request": "22 F1 90",
                    "response": "62 F1 90",
                },
            }
        )
        panel.fn_set_transaction_info(
            {
                "ECU": "VCU",
                "Time": "125.320",
                "Activity": "Read VIN",
                "Request": "22 F1 90",
                "Response": "7F 22 31",
                "RT (ms)": "18.50",
                "Status": "Negative",
            }
        )

        self.assertEqual(
            panel.txt_quick_filter_info.toPlainText(),
            "Name: Filter 22 F1 90\n\n"
            "ECU: MHU\n\n"
            "Request: 22 F1 90\n\n"
            "Response: 62 F1 90",
        )
        self.assertEqual(
            panel.txt_transaction_info.toPlainText(),
            "ECU: VCU\n\n"
            "Time: 125.320\n\n"
            "Activity: Read VIN\n\n"
            "Request: 22 F1 90\n\n"
            "Response: 7F 22 31\n\n"
            "RT (ms): 18.50\n\n"
            "Status: Negative",
        )

        panel.fn_set_quick_filter_info(
            {
                "name": "Filter 19 02",
                "filters": {
                    "ecu": "ECU2",
                    "request": "19 02",
                    "response": "59 02",
                },
            }
        )

        self.assertIn("Name: Filter 19 02", panel.txt_quick_filter_info.toPlainText())
        self.assertIn("ECU: VCU", panel.txt_transaction_info.toPlainText())

        panel.fn_clear_detail_panels()
        self.assertEqual(
            panel.txt_quick_filter_info.toPlainText(),
            "Name: -\n\nECU: -\n\nRequest: -\n\nResponse: -",
        )
        self.assertEqual(
            panel.txt_transaction_info.toPlainText(),
            "ECU: -\n\nTime: -\n\nActivity: -\n\nRequest: -\n\nResponse: -\n\nRT (ms): -\n\nStatus: -",
        )


    def test_action_panel_has_analysis_progress_above_analyze(self):
        from gui.widgets.log_analyzer.action_panel import ActionPanel

        panel = ActionPanel()
        self.addCleanup(panel.deleteLater)

        layout = panel.layout()

        self.assertLess(
            layout.indexOf(panel.grp_analysis_progress),
            layout.indexOf(panel.btn_run),
        )
        self.assertEqual(panel.grp_analysis_progress.title(), "Analysis Progress")
        self.assertEqual(panel.lbl_analysis_status.text(), "Ready")
        self.assertIsInstance(panel.progress_analysis, QProgressBar)
        self.assertEqual(panel.progress_analysis.minimum(), 0)
        self.assertEqual(panel.progress_analysis.maximum(), 100)
        self.assertEqual(panel.progress_analysis.value(), 0)

    def test_action_panel_analysis_running_and_completion_states(self):
        from gui.widgets.log_analyzer.action_panel import ActionPanel

        panel = ActionPanel()
        self.addCleanup(panel.deleteLater)
        panel.fn_set_analyzed_state()

        panel.fn_set_analysis_started()

        self.assertEqual(panel.lbl_analysis_status.text(), "Starting analysis...")
        self.assertEqual(panel.progress_analysis.minimum(), 0)
        self.assertEqual(panel.progress_analysis.maximum(), 0)
        self.assertEqual(panel.btn_run.text(), "ANALYZING...")
        self.assertFalse(panel.btn_run.isEnabled())
        self.assertFalse(panel.btn_export.isEnabled())
        self.assertFalse(panel.btn_copy.isEnabled())
        self.assertFalse(panel.btn_clear.isEnabled())

        panel.fn_set_analysis_status("Reading log...")
        self.assertEqual(panel.lbl_analysis_status.text(), "Reading log...")

        panel.fn_set_analysis_completed()
        self.assertEqual(panel.lbl_analysis_status.text(), "Completed")
        self.assertEqual(panel.progress_analysis.minimum(), 0)
        self.assertEqual(panel.progress_analysis.maximum(), 100)
        self.assertEqual(panel.progress_analysis.value(), 100)
        self.assertEqual(panel.btn_run.text(), "Analyze")

        panel.fn_set_analysis_failed("Broken")
        self.assertEqual(panel.lbl_analysis_status.text(), "Failed")
        self.assertEqual(panel.progress_analysis.value(), 0)
        self.assertEqual(panel.btn_run.text(), "Analyze")

    def test_right_panel_shares_remaining_height_between_detail_areas(self):
        from gui.widgets.log_analyzer.right_panel import RightPanel

        panel = RightPanel()
        self.addCleanup(panel.deleteLater)

        right_layout = panel.layout()
        action_layout = panel.action_panel.layout()
        quick_filter_index = action_layout.indexOf(
            panel.action_panel.grp_quick_filter_info
        )
        transaction_index = action_layout.indexOf(
            panel.action_panel.grp_transaction_info
        )

        self.assertEqual(right_layout.count(), 1)
        self.assertIs(right_layout.itemAt(0).widget(), panel.action_panel)
        self.assertEqual(right_layout.stretch(0), 1)
        self.assertGreaterEqual(quick_filter_index, 0)
        self.assertGreaterEqual(transaction_index, 0)
        self.assertEqual(action_layout.stretch(quick_filter_index), 2)
        self.assertEqual(action_layout.stretch(transaction_index), 3)

    def test_log_analyzer_updates_details_independently_and_clears_stale_data(self):
        from gui.tabs.log_analyzer_tab import LogAnalyzerTab

        tab = LogAnalyzerTab()

        self.addCleanup(tab.deleteLater)

        tab.fn_quick_filter(
            {
                "name": "Filter 1",
                "filters": {
                    "ecu": "ECU1",
                    "request": "22 F1 90",
                    "response": "62 F1 90",
                },
            }
        )

        tab.tbl_result.set_data([
            {
                "ECU": "VCU",
                "Time": "125.320",
                "Activity": "Read VIN",
                "Request": "22 F1 90",
                "Response": "7F 22 31",
                "RT (ms)": "18.50",
                "Status": "Negative",
            }
        ])
        tab._fn_result_row_selected(0, 0)

        quick_filter_info = tab.right_panel.action_panel.txt_quick_filter_info.toPlainText()
        transaction_info = tab.right_panel.action_panel.txt_transaction_info.toPlainText()

        self.assertIn("Name: Filter 1", quick_filter_info)
        self.assertIn("ECU: ECU1", quick_filter_info)
        self.assertIn("ECU: VCU", transaction_info)
        self.assertIn("Status: Negative", transaction_info)

        tab.fn_clear_clicked()

        self.assertEqual(
            tab.right_panel.action_panel.txt_quick_filter_info.toPlainText(),
            "Name: -\n\nECU: -\n\nRequest: -\n\nResponse: -",
        )
        self.assertEqual(
            tab.right_panel.action_panel.txt_transaction_info.toPlainText(),
            "ECU: -\n\nTime: -\n\nActivity: -\n\nRequest: -\n\nResponse: -\n\nRT (ms): -\n\nStatus: -",
        )


if __name__ == "__main__":
    unittest.main()
