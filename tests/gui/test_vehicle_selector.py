import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton, QApplication

from gui.tabs.log_analyzer_tab import LogAnalyzerTab
from gui.tabs.vehicle_manager_tab import VehicleManagerTab
from gui.dialogs.import_ecu_dialog import ImportECUDialog
from gui.dialogs.export_vehicle_dialog import ExportVehicleDialog
from gui.dialogs.import_display_names_dialog import ImportDisplayNamesDialog
from gui.widgets.controls.cancel_button import CancelButton
from gui.widgets.vehicle_manager.vehicle_selector import VehicleSelectorWidget
from models.ecu import ECU
from models.vehicle import Vehicle


class VehicleSelectorWidgetTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_can_leave_vehicle_unselected(self):
        selector = VehicleSelectorWidget()

        selector.fn_set_vehicles(
            ["VF3", "VF6"],
            allow_empty_selection=True,
        )

        self.assertEqual(selector.fn_vehicle(), "")

    def test_vehicle_popup_uses_opaque_background(self):
        selector = VehicleSelectorWidget()

        self.assertTrue(
            selector.cmb_vehicle.view().testAttribute(
                Qt.WA_OpaquePaintEvent
            )
        )
        self.assertTrue(
            selector.cmb_vehicle.view().viewport().testAttribute(
                Qt.WA_OpaquePaintEvent
            )
        )
        self.assertTrue(
            selector.cmb_vehicle.view().viewport().testAttribute(
                Qt.WA_StyledBackground
            )
        )
        self.assertIn(
            "QComboBox QAbstractItemView",
            selector.cmb_vehicle.styleSheet(),
        )

    def test_vehicle_manager_no_longer_has_the_display_names_buttons(self):
        tab = VehicleManagerTab()
        self.addCleanup(tab.deleteLater)

        self.assertFalse(hasattr(tab, "btn_import_display_names"))
        self.assertFalse(hasattr(tab, "btn_import_display_rules"))
        texts = {button.text() for button in tab.findChildren(QPushButton)}
        self.assertNotIn("Import File Display Names", texts)
        self.assertNotIn("Import Rules Display Names", texts)

    def test_vehicle_manager_starts_without_selected_vehicle_or_ecus(self):
        tab = VehicleManagerTab()
        self.addCleanup(tab.deleteLater)

        self.assertEqual(tab.vehicle_selector.fn_vehicle(), "")
        self.assertEqual(tab.ecu_list.rowCount(), 0)
        self.assertIsNone(tab._current_vehicle)
        self.assertFalse(tab.btn_add_ecu.isEnabled())
        self.assertFalse(tab.btn_import_ecus.isEnabled())
        self.assertFalse(tab.btn_export_vehicle.isEnabled())

    def test_vehicle_manager_enables_export_after_vehicle_selection(self):
        tab = VehicleManagerTab()
        self.addCleanup(tab.deleteLater)
        vehicle = Vehicle(
            name="VF3",
            ecus=[
                ECU(
                    name="BCM",
                    request_id="681",
                    response_id="601",
                )
            ],
        )

        with patch.object(
            tab._controller,
            "load_vehicle",
            return_value=vehicle,
        ):
            tab._on_vehicle_changed("VF3")

        self.assertTrue(tab.btn_export_vehicle.isEnabled())

    def test_vehicle_manager_exports_selected_vehicle_ecu_list(self):
        tab = VehicleManagerTab()
        self.addCleanup(tab.deleteLater)
        tab._current_vehicle_name = "VF3"

        with patch.object(
            tab._controller,
            "export_vehicle_ecu_list",
            return_value="BCM|681|601",
        ) as export_list, patch(
            "gui.tabs.vehicle_manager_tab.ExportVehicleDialog"
        ) as dialog:
            tab._on_export_vehicle_clicked()

        export_list.assert_called_once_with("VF3")
        dialog.assert_called_once_with(
            "VF3",
            "BCM|681|601",
            tab,
        )
        dialog.return_value.exec.assert_called_once_with()

    def test_vehicle_manager_save_renamed_ecu_uses_original_name(self):
        tab = VehicleManagerTab()
        self.addCleanup(tab.deleteLater)
        original_ecu = ECU(
            name="BCM",
            request_id="681",
            response_id="601",
        )
        tab._current_vehicle_name = "VF3"
        tab._current_vehicle = Vehicle(
            name="VF3",
            ecus=[original_ecu],
        )
        tab._current_ecu = original_ecu
        tab.ecu_info.fn_set_ecu(original_ecu)
        tab.ecu_info.txt_name.setText("BCM_NEW")

        with patch.object(
            tab._controller,
            "save_ecu",
        ) as save_ecu, patch.object(
            tab._controller,
            "delete_ecu",
        ) as delete_ecu, patch.object(
            tab,
            "_reload_current_vehicle",
        ) as reload_vehicle, patch.object(
            tab,
            "_show_auto_close_info",
        ), patch.object(
            tab,
            "_notify_vehicle_data_changed",
        ):
            tab._on_save_clicked()

        saved_ecu = save_ecu.call_args.args[1]
        self.assertEqual(saved_ecu.name, "BCM_NEW")
        save_ecu.assert_called_once_with(
            "VF3",
            saved_ecu,
            existing_ecu_name="BCM",
        )
        delete_ecu.assert_called_once_with(
            "VF3",
            "BCM",
        )
        reload_vehicle.assert_called_once_with(
            selected_ecu_name="BCM_NEW"
        )

    def test_export_vehicle_dialog_uses_import_ecu_list_format(self):
        dialog = ExportVehicleDialog(
            "VF3",
            "BCM|681|601\nACM|688|608",
        )
        self.addCleanup(dialog.deleteLater)

        self.assertEqual(
            dialog.fn_export_text(),
            "BCM|681|601\nACM|688|608",
        )
        self.assertTrue(dialog.txt_ecus.isReadOnly())

    def test_import_dialog_cancel_buttons_use_neutral_cancel_control(self):
        ecu_dialog = ImportECUDialog()
        display_dialog = ImportDisplayNamesDialog()
        self.addCleanup(ecu_dialog.deleteLater)
        self.addCleanup(display_dialog.deleteLater)

        self.assertIsInstance(ecu_dialog.btn_cancel, CancelButton)
        self.assertIsInstance(display_dialog.btn_cancel, CancelButton)

    def test_display_rules_dialog_keeps_input_after_invalid_import(self):
        dialog = ImportDisplayNamesDialog()
        self.addCleanup(dialog.deleteLater)
        dialog.txt_rules.setPlainText("22 F1 GG|Broken")

        with patch(
            "gui.dialogs.import_display_names_dialog.QMessageBox.warning"
        ) as warning:
            dialog._on_import_clicked()

        warning.assert_called_once()
        self.assertEqual(dialog.result(), 0)
        self.assertEqual(
            dialog.txt_rules.toPlainText(),
            "22 F1 GG|Broken",
        )


class LogAnalyzerTabTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tab = LogAnalyzerTab()

    def tearDown(self):
        self.tab.deleteLater()

    def _write_log(self, content: str) -> Path:
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".asc",
            encoding="utf-8",
            delete=False,
        )
        self.addCleanup(Path(handle.name).unlink, missing_ok=True)
        handle.write(content)
        handle.close()
        return Path(handle.name)

    def _assert_action_buttons(
        self,
        *,
        analyze: bool,
        export: bool,
        copy: bool,
        clear: bool,
    ) -> None:
        panel = self.tab.right_panel.action_panel

        self.assertEqual(panel.btn_run.isEnabled(), analyze)
        self.assertEqual(panel.btn_export.isEnabled(), export)
        self.assertEqual(panel.btn_copy.isEnabled(), copy)
        self.assertEqual(panel.btn_clear.isEnabled(), clear)

    def _select_valid_single_channel_inputs(self) -> None:
        log_file = self._write_log(
            "0.001 2 681 Rx d 8 03 22 F1 90 00 00 00 00\n"
        )
        self.tab._current_vehicle = object()
        self.tab.log_selector.set_path(str(log_file))

        with patch.object(self.tab, "_fn_start_log_channel_thread"):
            self.tab.fn_log_file_changed(str(log_file))

        with patch("gui.tabs.log_analyzer_tab.QMessageBox.information"):
            self.tab._fn_log_channels_loaded([2])

    def _select_log_for_async_discovery(self) -> None:
        log_file = self._write_log(
            "0.001 2 681 Rx d 8 03 22 F1 90 00 00 00 00\n"
        )
        self.tab._current_vehicle = object()
        self.tab.log_selector.set_path(str(log_file))

        with patch.object(self.tab, "_fn_start_log_channel_thread"):
            self.tab.fn_log_file_changed(str(log_file))

    def _successful_analysis_result(self) -> dict:
        return {
            "transactions": [
                {
                    "ecu": "VCU",
                    "request": {
                        "timestamp": 0.001,
                        "payload": "22 F1 90",
                    },
                    "positive_response": {
                        "payload": "62 F1 90",
                    },
                    "response_time": 0.001,
                    "display_name": "Read DID",
                    "status": "OK",
                }
            ]
        }

    def test_starts_without_a_vehicle_selection(self):
        self.assertEqual(self.tab.vehicle_selector.fn_vehicle(), "")
        self.assertIsNone(self.tab.analysis_controller.pipeline_result)
        self.assertFalse(hasattr(self.tab, "pipeline_result"))
        self._assert_action_buttons(
            analyze=False,
            export=False,
            copy=False,
            clear=False,
        )

    def test_analyze_waits_for_vehicle_after_selecting_valid_log(self):
        log_file = self._write_log(
            "0.001 1 681 Rx d 8 03 22 F1 90 00 00 00 00\n"
        )
        self.tab.log_selector.set_path(str(log_file))
        with patch.object(self.tab, "_fn_start_log_channel_thread"):
            self.tab.fn_log_file_changed(str(log_file))
        with patch("gui.tabs.log_analyzer_tab.QMessageBox.information"):
            self.tab._fn_log_channels_loaded([1])

        self.assertEqual(self.tab.channel_selector.fn_channel(), 1)
        self.assertFalse(self.tab.right_panel.action_panel.btn_run.isEnabled())

    def test_valid_inputs_enable_only_analyze_before_analysis(self):
        self._select_valid_single_channel_inputs()

        self._assert_action_buttons(
            analyze=True,
            export=False,
            copy=False,
            clear=False,
        )

    def test_multi_channel_log_requires_channel_selection(self):
        log_file = self._write_log(
            "0.001 2 681 Rx d 8 03 22 F1 90 00 00 00 00\n"
            "0.002 1 682 Rx d 8 03 22 F1 91 00 00 00 00\n"
        )
        self.tab._current_vehicle = object()
        self.tab.log_selector.set_path(str(log_file))
        with patch.object(self.tab, "_fn_start_log_channel_thread"):
            self.tab.fn_log_file_changed(str(log_file))
        with patch("gui.tabs.log_analyzer_tab.QMessageBox.information"):
            self.tab._fn_log_channels_loaded([1, 2])

        self.assertTrue(self.tab.channel_selector.cmb_channel.isEnabled())
        self.assertEqual(self.tab.channel_selector.cmb_channel.currentIndex(), -1)
        self.assertIsNone(self.tab.channel_selector.fn_channel())
        self.assertFalse(self.tab.right_panel.action_panel.btn_run.isEnabled())

        self.tab.channel_selector.cmb_channel.setCurrentIndex(0)

        self.assertEqual(self.tab.channel_selector.fn_channel(), 1)
        self.assertTrue(self.tab.right_panel.action_panel.btn_run.isEnabled())

    def test_analyze_passes_selected_channel_to_worker_start(self):
        log_file = self._write_log(
            "0.001 2 681 Rx d 8 03 22 F1 90 00 00 00 00\n"
        )
        self.tab._current_vehicle = object()
        self.tab.log_selector.set_path(str(log_file))
        with patch.object(self.tab, "_fn_start_log_channel_thread"):
            self.tab.fn_log_file_changed(str(log_file))
        with patch("gui.tabs.log_analyzer_tab.QMessageBox.information"):
            self.tab._fn_log_channels_loaded([2])

        with patch.object(self.tab, "_fn_start_analysis_thread") as start_thread:
            self.tab.fn_run_clicked()

        start_thread.assert_called_once_with(
            str(log_file),
            self.tab._current_vehicle,
            2,
        )

    def test_non_sequential_selected_channel_is_passed_as_item_data(self):
        log_file = self._write_log(
            "0.001 2 681 Rx d 8 03 22 F1 90 00 00 00 00\n"
            "0.002 5 682 Rx d 8 03 22 F1 91 00 00 00 00\n"
            "0.003 12 683 Rx d 8 03 22 F1 92 00 00 00 00\n"
        )
        self.tab._current_vehicle = object()
        self.tab.log_selector.set_path(str(log_file))
        with patch.object(self.tab, "_fn_start_log_channel_thread"):
            self.tab.fn_log_file_changed(str(log_file))
        with patch("gui.tabs.log_analyzer_tab.QMessageBox.information"):
            self.tab._fn_log_channels_loaded([2, 5, 12])
        self.tab.channel_selector.cmb_channel.setCurrentIndex(1)

        with patch.object(self.tab, "_fn_start_analysis_thread") as start_thread:
            self.tab.fn_run_clicked()

        start_thread.assert_called_once_with(
            str(log_file),
            self.tab._current_vehicle,
            5,
        )

    def test_loading_new_file_clears_previous_channel_selection(self):
        first_log = self._write_log(
            "0.001 1 681 Rx d 8 03 22 F1 90 00 00 00 00\n"
            "0.002 2 682 Rx d 8 03 22 F1 91 00 00 00 00\n"
            "0.003 3 683 Rx d 8 03 22 F1 92 00 00 00 00\n"
        )
        second_log = self._write_log(
            "0.001 4 681 Rx d 8 03 22 F1 90 00 00 00 00\n"
            "0.002 5 682 Rx d 8 03 22 F1 91 00 00 00 00\n"
        )
        self.tab._current_vehicle = object()
        self.tab.log_selector.set_path(str(first_log))
        with patch.object(self.tab, "_fn_start_log_channel_thread"):
            self.tab.fn_log_file_changed(str(first_log))
        with patch("gui.tabs.log_analyzer_tab.QMessageBox.information"):
            self.tab._fn_log_channels_loaded([1, 2, 3])
        self.tab.channel_selector.cmb_channel.setCurrentIndex(1)
        self.assertEqual(self.tab.channel_selector.fn_channel(), 2)

        self.tab.log_selector.set_path(str(second_log))
        with patch.object(self.tab, "_fn_start_log_channel_thread"):
            self.tab.fn_log_file_changed(str(second_log))
        with patch("gui.tabs.log_analyzer_tab.QMessageBox.information"):
            self.tab._fn_log_channels_loaded([4, 5])

        self.assertEqual(self.tab.channel_selector.cmb_channel.currentIndex(), -1)
        self.assertIsNone(self.tab.channel_selector.fn_channel())
        self.assertEqual(self.tab.channel_selector.cmb_channel.count(), 2)
        self.assertEqual(
            [
                self.tab.channel_selector.cmb_channel.itemData(index)
                for index in range(self.tab.channel_selector.cmb_channel.count())
            ],
            [4, 5],
        )
        self.assertFalse(self.tab.right_panel.action_panel.btn_run.isEnabled())


    def test_analyze_click_starts_background_worker_and_locks_inputs(self):
        log_file = self._write_log(
            "0.001 2 681 Rx d 8 03 22 F1 90 00 00 00 00\n"
        )
        self.tab._current_vehicle = object()
        self.tab.log_selector.set_path(str(log_file))
        with patch.object(self.tab, "_fn_start_log_channel_thread"):
            self.tab.fn_log_file_changed(str(log_file))
        with patch("gui.tabs.log_analyzer_tab.QMessageBox.information"):
            self.tab._fn_log_channels_loaded([2])

        with patch.object(self.tab, "_fn_start_analysis_thread") as start_thread, patch.object(
            self.tab.analysis_controller,
            "fn_run",
        ) as run_analysis:
            self.tab.fn_run_clicked()
            self.tab.fn_run_clicked()

        start_thread.assert_called_once_with(
            str(log_file),
            self.tab._current_vehicle,
            2,
        )
        run_analysis.assert_not_called()
        self.assertTrue(self.tab._analysis_running)
        self.assertFalse(self.tab.vehicle_selector.isEnabled())
        self.assertFalse(self.tab.channel_selector.isEnabled())
        self.assertFalse(self.tab.log_selector.isEnabled())
        self.assertEqual(
            self.tab.right_panel.action_panel.btn_run.text(),
            "ANALYZING...",
        )
        self.assertEqual(
            self.tab.right_panel.action_panel.progress_analysis.maximum(),
            0,
        )
        self._assert_action_buttons(
            analyze=False,
            export=False,
            copy=False,
            clear=False,
        )

    def test_starting_new_analysis_invalidates_previous_result(self):
        old_result = self._successful_analysis_result()
        self._select_valid_single_channel_inputs()
        self.tab.analysis_controller.pipeline_result = old_result
        self.tab.right_panel.action_panel.fn_set_analyzed_state()

        with patch.object(self.tab, "_fn_start_analysis_thread"):
            self.tab.fn_run_clicked()

        self.assertIsNone(self.tab.analysis_controller.pipeline_result)
        self._assert_action_buttons(
            analyze=False,
            export=False,
            copy=False,
            clear=False,
        )

    def test_failed_new_analysis_does_not_keep_previous_result_exportable(self):
        old_result = self._successful_analysis_result()
        self._select_valid_single_channel_inputs()
        self.tab.analysis_controller.pipeline_result = old_result

        with patch.object(self.tab, "_fn_start_analysis_thread"):
            self.tab.fn_run_clicked()

        with patch("gui.tabs.log_analyzer_tab.QMessageBox.warning"):
            self.tab._fn_analysis_failed("Broken log")

        self.assertIsNone(self.tab.analysis_controller.pipeline_result)
        self.assertEqual(
            self.tab.right_panel.action_panel.lbl_analysis_status.text(),
            "Failed",
        )
        self._assert_action_buttons(
            analyze=True,
            export=False,
            copy=False,
            clear=False,
        )

    def test_analysis_success_updates_results_and_restores_inputs(self):
        self.tab._analysis_running = True
        self.tab._fn_set_analysis_inputs_enabled(False)
        result = {
            "transactions": [
                {
                    "timestamp": 0.001,
                    "ecu": "VCU",
                    "request_payload": "22 F1 90",
                    "response_payload": "62 F1 90",
                    "status": "Positive",
                }
            ]
        }

        self.tab.analysis_controller.pipeline_result = result

        with patch(
            "gui.tabs.log_analyzer_tab.fn_build_transaction_rows",
            return_value=[{"ECU": "VCU", "Time": "0.001", "Activity": "Read DID", "Request": "22 F1 90", "Response": "62 F1 90", "RT (ms)": "1.00", "Status": "Positive"}],
        ):
            self.tab._fn_analysis_finished(result)

        self.assertFalse(hasattr(self.tab, "pipeline_result"))
        self.assertIs(self.tab.analysis_controller.pipeline_result, result)
        self.assertFalse(self.tab._analysis_running)
        self.assertTrue(self.tab.vehicle_selector.isEnabled())
        self.assertTrue(self.tab.channel_selector.isEnabled())
        self.assertTrue(self.tab.log_selector.isEnabled())
        self.assertEqual(
            self.tab.right_panel.action_panel.lbl_analysis_status.text(),
            "Completed",
        )
        self.assertEqual(self.tab.tbl_result.rowCount(), 1)
        self.assertTrue(self.tab.right_panel.action_panel.btn_export.isEnabled())
        self.assertTrue(self.tab.right_panel.action_panel.btn_copy.isEnabled())
        self.assertTrue(self.tab.right_panel.action_panel.btn_clear.isEnabled())

    def test_clear_with_valid_inputs_resets_result_and_returns_to_ready(self):
        result = self._successful_analysis_result()
        self._select_valid_single_channel_inputs()
        self.tab.analysis_controller.pipeline_result = result
        self.tab._fn_analysis_finished(result)

        self.tab.fn_clear_clicked()

        self.assertIsNone(self.tab.analysis_controller.pipeline_result)
        self.assertFalse(hasattr(self.tab, "pipeline_result"))
        self.assertEqual(
            self.tab.right_panel.action_panel.lbl_analysis_status.text(),
            "Ready",
        )
        self._assert_action_buttons(
            analyze=True,
            export=False,
            copy=False,
            clear=False,
        )

    def test_analysis_failure_restores_ready_state_without_analyzed_actions(self):
        log_file = self._write_log(
            "0.001 2 681 Rx d 8 03 22 F1 90 00 00 00 00\n"
        )
        self.tab._current_vehicle = object()
        self.tab.log_selector.set_path(str(log_file))
        with patch.object(self.tab, "_fn_start_log_channel_thread"):
            self.tab.fn_log_file_changed(str(log_file))
        with patch("gui.tabs.log_analyzer_tab.QMessageBox.information"):
            self.tab._fn_log_channels_loaded([2])
        self.tab._analysis_running = True
        self.tab._fn_set_analysis_inputs_enabled(False)

        with patch("gui.tabs.log_analyzer_tab.QMessageBox.warning") as warning:
            self.tab._fn_analysis_failed("Broken log")

        warning.assert_called_once()
        self.assertFalse(self.tab._analysis_running)
        self.assertTrue(self.tab.vehicle_selector.isEnabled())
        self.assertTrue(self.tab.channel_selector.isEnabled())
        self.assertTrue(self.tab.log_selector.isEnabled())
        self.assertEqual(
            self.tab.right_panel.action_panel.lbl_analysis_status.text(),
            "Failed",
        )
        self.assertTrue(self.tab.right_panel.action_panel.btn_run.isEnabled())
        self.assertFalse(self.tab.right_panel.action_panel.btn_export.isEnabled())
        self.assertFalse(self.tab.right_panel.action_panel.btn_copy.isEnabled())
        self.assertFalse(self.tab.right_panel.action_panel.btn_clear.isEnabled())

    def test_vehicle_change_invalidates_previous_result_and_export(self):
        result = self._successful_analysis_result()
        self._select_valid_single_channel_inputs()
        self.tab.analysis_controller.pipeline_result = result
        self.tab.right_panel.action_panel.fn_set_analyzed_state()

        with patch.object(
            self.tab.vehicle_service,
            "load_vehicle",
            return_value=object(),
        ):
            self.tab.fn_vehicle_changed("VF6")

        self.assertIsNone(self.tab.analysis_controller.pipeline_result)
        self._assert_action_buttons(
            analyze=True,
            export=False,
            copy=False,
            clear=False,
        )

    def test_log_file_change_invalidates_previous_result_and_export(self):
        result = self._successful_analysis_result()
        self._select_valid_single_channel_inputs()
        self.tab.analysis_controller.pipeline_result = result
        self.tab.right_panel.action_panel.fn_set_analyzed_state()
        log_file = self._write_log(
            "0.001 3 681 Rx d 8 03 22 F1 90 00 00 00 00\n"
        )

        self.tab.log_selector.set_path(str(log_file))
        with patch.object(self.tab, "_fn_start_log_channel_thread"):
            self.tab.fn_log_file_changed(str(log_file))

        self.assertIsNone(self.tab.analysis_controller.pipeline_result)
        self._assert_action_buttons(
            analyze=False,
            export=False,
            copy=False,
            clear=False,
        )

        with patch("gui.tabs.log_analyzer_tab.QMessageBox.information"):
            self.tab._fn_log_channels_loaded([3])

        self._assert_action_buttons(
            analyze=True,
            export=False,
            copy=False,
            clear=False,
        )

    def test_channel_change_invalidates_previous_result_and_export(self):
        log_file = self._write_log(
            "0.001 2 681 Rx d 8 03 22 F1 90 00 00 00 00\n"
            "0.002 5 682 Rx d 8 03 22 F1 91 00 00 00 00\n"
        )
        self.tab._current_vehicle = object()
        self.tab.log_selector.set_path(str(log_file))
        with patch.object(self.tab, "_fn_start_log_channel_thread"):
            self.tab.fn_log_file_changed(str(log_file))
        with patch("gui.tabs.log_analyzer_tab.QMessageBox.information"):
            self.tab._fn_log_channels_loaded([2, 5])
        self.tab.channel_selector.cmb_channel.setCurrentIndex(0)
        result = self._successful_analysis_result()
        self.tab.analysis_controller.pipeline_result = result
        self.tab.right_panel.action_panel.fn_set_analyzed_state()

        self.tab.channel_selector.cmb_channel.setCurrentIndex(1)

        self.assertIsNone(self.tab.analysis_controller.pipeline_result)
        self._assert_action_buttons(
            analyze=True,
            export=False,
            copy=False,
            clear=False,
        )

    def test_selecting_log_enters_loading_state_and_locks_controls(self):
        self.tab.analysis_controller.pipeline_result = self._successful_analysis_result()
        self.tab.right_panel.action_panel.fn_set_analysis_completed()
        self.tab.right_panel.action_panel.fn_set_analyzed_state()
        log_file = self._write_log(
            "0.001 2 681 Rx d 8 03 22 F1 90 00 00 00 00\n"
        )

        self.tab.log_selector.set_path(str(log_file))
        with patch.object(self.tab, "_fn_start_log_channel_thread") as start_thread:
            self.tab.fn_log_file_changed(str(log_file))

        start_thread.assert_called_once_with(str(log_file))
        self.assertTrue(self.tab._log_loading)
        self.assertIsNone(self.tab.analysis_controller.pipeline_result)
        self.assertEqual(
            self.tab.right_panel.action_panel.lbl_analysis_status.text(),
            "Reading log channels...",
        )
        self.assertEqual(
            self.tab.right_panel.action_panel.progress_analysis.maximum(),
            0,
        )
        self.assertFalse(self.tab.vehicle_selector.isEnabled())
        self.assertFalse(self.tab.channel_selector.isEnabled())
        self.assertFalse(self.tab.log_selector.isEnabled())
        self.assertFalse(self.tab.filter_box.isEnabled())
        self.assertFalse(self.tab.left_panel.isEnabled())
        self.assertFalse(self.tab.tbl_result.isEnabled())
        self._assert_action_buttons(
            analyze=False,
            export=False,
            copy=False,
            clear=False,
        )

    def test_log_channel_success_single_channel_restores_ready_state(self):
        self._select_log_for_async_discovery()

        with patch("gui.tabs.log_analyzer_tab.QMessageBox.information") as info:
            self.tab._fn_log_channels_loaded([2])

        self.assertFalse(self.tab._log_loading)
        self.assertEqual(self.tab.channel_selector.fn_channel(), 2)
        self.assertFalse(self.tab.channel_selector.cmb_channel.isEnabled())
        self.assertEqual(
            self.tab.right_panel.action_panel.lbl_analysis_status.text(),
            "Log loaded",
        )
        self.assertEqual(
            self.tab.right_panel.action_panel.progress_analysis.value(),
            100,
        )
        self._assert_action_buttons(
            analyze=True,
            export=False,
            copy=False,
            clear=False,
        )
        info.assert_called_once()
        self.assertIn("Detected 1 CAN channel.", info.call_args.args[2])

    def test_log_channel_success_multiple_channels_waits_for_channel_selection(self):
        self._select_log_for_async_discovery()

        with patch("gui.tabs.log_analyzer_tab.QMessageBox.information") as info:
            self.tab._fn_log_channels_loaded([1, 2, 4])

        self.assertFalse(self.tab._log_loading)
        self.assertTrue(self.tab.channel_selector.cmb_channel.isEnabled())
        self.assertIsNone(self.tab.channel_selector.fn_channel())
        self.assertEqual(
            [
                self.tab.channel_selector.cmb_channel.itemData(index)
                for index in range(self.tab.channel_selector.cmb_channel.count())
            ],
            [1, 2, 4],
        )
        self._assert_action_buttons(
            analyze=False,
            export=False,
            copy=False,
            clear=False,
        )
        info.assert_called_once()
        self.assertIn("Detected 3 CAN channels.", info.call_args.args[2])

        self.tab.channel_selector.cmb_channel.setCurrentIndex(1)

        self.assertEqual(self.tab.channel_selector.fn_channel(), 2)
        self._assert_action_buttons(
            analyze=True,
            export=False,
            copy=False,
            clear=False,
        )

    def test_log_channel_success_with_no_channels_is_failure(self):
        self._select_log_for_async_discovery()

        with patch("gui.tabs.log_analyzer_tab.QMessageBox.information") as info, patch(
            "gui.tabs.log_analyzer_tab.QMessageBox.warning"
        ) as warning:
            self.tab._fn_log_channels_loaded([])

        self.assertFalse(self.tab._log_loading)
        self.assertEqual(
            self.tab.right_panel.action_panel.lbl_analysis_status.text(),
            "Log load failed",
        )
        self.assertEqual(
            self.tab.right_panel.action_panel.progress_analysis.value(),
            0,
        )
        self.assertFalse(self.tab.right_panel.action_panel.btn_run.isEnabled())
        info.assert_not_called()
        warning.assert_called_once()

    def test_log_channel_failure_restores_controls_without_stale_result(self):
        self._select_log_for_async_discovery()
        self.tab.analysis_controller.pipeline_result = self._successful_analysis_result()

        with patch("gui.tabs.log_analyzer_tab.QMessageBox.warning") as warning:
            self.tab._fn_log_channels_failed("Broken log")

        self.assertFalse(self.tab._log_loading)
        self.assertIsNone(self.tab.analysis_controller.pipeline_result)
        self.assertTrue(self.tab.vehicle_selector.isEnabled())
        self.assertTrue(self.tab.log_selector.isEnabled())
        self.assertEqual(
            self.tab.right_panel.action_panel.lbl_analysis_status.text(),
            "Log load failed",
        )
        self._assert_action_buttons(
            analyze=False,
            export=False,
            copy=False,
            clear=False,
        )
        warning.assert_called_once()

    def test_log_channel_thread_finished_clears_references(self):
        self.tab._log_channel_thread = object()
        self.tab._log_channel_worker = object()

        self.tab._fn_log_channel_thread_finished()

        self.assertIsNone(self.tab._log_channel_thread)
        self.assertIsNone(self.tab._log_channel_worker)


    def test_refresh_button_aligns_with_the_log_row_end_button_across_resizes(self):
        self.assertFalse(self.tab.filter_box.btn_refresh.isEnabled())

        for width in (1200, 820):
            with self.subTest(width=width):
                self.tab.resize(width, 800)
                self.tab.show()
                self.application.processEvents()

                browse_button = self.tab.log_selector.settings_button
                refresh_button = self.tab.filter_box.btn_refresh
                browse_left = browse_button.mapTo(
                    self.tab,
                    browse_button.rect().topLeft(),
                ).x()
                browse_right = browse_button.mapTo(
                    self.tab,
                    browse_button.rect().topRight(),
                ).x()
                refresh_left = refresh_button.mapTo(
                    self.tab,
                    refresh_button.rect().topLeft(),
                ).x()
                refresh_right = refresh_button.mapTo(
                    self.tab,
                    refresh_button.rect().topRight(),
                ).x()

                self.assertEqual(refresh_button.width(), browse_button.width())
                self.assertEqual(refresh_button.height(), browse_button.height())
                self.assertEqual(refresh_left, browse_left)
                self.assertEqual(refresh_right, browse_right)
                self.assertEqual(
                    self.tab.log_selector.browse_button.x()
                    - self.tab.log_selector.edit_path.geometry().right()
                    - 1,
                    8,
                )
                self.assertEqual(
                    refresh_button.x()
                    - self.tab.filter_box.edit_filter.geometry().right()
                    - 1,
                    8,
                )

    def test_refresh_table_resets_filtered_view_without_reanalysis(self):
        result = self._successful_analysis_result()
        self.tab.analysis_controller.pipeline_result = result
        rows = [
            {
                "ECU": "ECU1",
                "Time": "0.001",
                "Activity": "Read DID",
                "Request": "22 F1 90",
                "Response": "62 F1 90",
                "RT (ms)": "1.00",
                "Status": "OK",
            },
            {
                "ECU": "ECU2",
                "Time": "0.002",
                "Activity": "Read DID",
                "Request": "22 F1 91",
                "Response": "7F 22 31",
                "RT (ms)": "",
                "Status": "NRC_ONLY",
            },
        ]

        with patch(
            "gui.tabs.log_analyzer_tab.fn_build_transaction_rows",
            return_value=rows,
        ):
            self.tab._fn_analysis_finished(result)

        self.assertTrue(self.tab.filter_box.btn_refresh.isEnabled())
        self.tab.left_panel.quick_access.selected_filter = {
            "name": "Filter ECU1",
            "filters": {
                "ecu": "ECU1",
                "request": "22 F1 90",
                "response": "62 F1 90",
            },
        }
        self.tab.fn_quick_filter(self.tab.left_panel.quick_access.selected_filter)
        self.tab.filter_box.set_text("ECU1")
        self.tab.tbl_result.selectRow(0)
        self.tab.tbl_result.setCurrentCell(0, 0)
        pipeline_result = self.tab.analysis_controller.pipeline_result

        with patch("gui.tabs.log_analyzer_tab.refresh_display_names"), patch(
            "gui.tabs.log_analyzer_tab.fn_build_transaction_rows",
            return_value=rows,
        ), patch.object(self.tab.analysis_controller, "fn_run") as run_analysis, patch.object(
            self.tab,
            "_fn_start_analysis_thread",
        ) as start_analysis, patch.object(
            self.tab,
            "_fn_start_log_channel_thread",
        ) as start_channel:
            self.tab.fn_refresh_table()

        run_analysis.assert_not_called()
        start_analysis.assert_not_called()
        start_channel.assert_not_called()
        self.assertIs(self.tab.analysis_controller.pipeline_result, pipeline_result)
        self.assertEqual(self.tab.tbl_result.rowCount(), 2)
        self.assertEqual(self.tab.filter_box.text(), "")
        self.assertFalse(self.tab.tbl_result.isRowHidden(0))
        self.assertFalse(self.tab.tbl_result.isRowHidden(1))
        self.assertEqual(self.tab.tbl_result.currentRow(), -1)
        self.assertIsNone(self.tab.left_panel.quick_access.selected_filter)
        self.assertIn(
            "Name: -",
            self.tab.right_panel.action_panel.txt_quick_filter_info.toPlainText(),
        )
        self.assertIn(
            "ECU: -",
            self.tab.right_panel.action_panel.txt_transaction_info.toPlainText(),
        )
        self.assertTrue(self.tab.filter_box.btn_refresh.isEnabled())

    def test_refresh_button_enable_lifecycle(self):
        self.assertFalse(self.tab.filter_box.btn_refresh.isEnabled())

        self._select_valid_single_channel_inputs()
        self.assertFalse(self.tab.filter_box.btn_refresh.isEnabled())

        self.tab._log_loading = True
        self.tab._update_analyze_state()
        self.assertFalse(self.tab.filter_box.btn_refresh.isEnabled())
        self.tab._log_loading = False

        with patch.object(self.tab, "_fn_start_analysis_thread"):
            self.tab.fn_run_clicked()

        self.assertFalse(self.tab.filter_box.btn_refresh.isEnabled())

        with patch("gui.tabs.log_analyzer_tab.QMessageBox.warning"):
            self.tab._fn_analysis_failed("Broken log")

        self.assertFalse(self.tab.filter_box.btn_refresh.isEnabled())

        result = self._successful_analysis_result()
        self.tab.analysis_controller.pipeline_result = result
        self.tab._analysis_running = True
        self.tab._fn_set_analysis_inputs_enabled(False)
        self.tab._fn_analysis_finished(result)
        self.assertTrue(self.tab.filter_box.btn_refresh.isEnabled())

        with patch.object(
            self.tab.vehicle_service,
            "load_vehicle",
            return_value=object(),
        ):
            self.tab.fn_vehicle_changed("VF6")
        self.assertFalse(self.tab.filter_box.btn_refresh.isEnabled())

        self.tab.analysis_controller.pipeline_result = result
        self.tab.filter_box.fn_set_refresh_enabled(True)
        self.tab.fn_clear_clicked()
        self.assertFalse(self.tab.filter_box.btn_refresh.isEnabled())

    def test_does_not_reject_log_with_multiple_pt_bo_info_markers(self):
        log_file = self._write_log(
            "PT BO INFO\n"
            "PT BO INFO\n"
            "0.001 1 681 Rx d 8 03 22 F1 90 00 00 00 00\n"
        )
        self.tab.log_selector.set_path(str(log_file))

        with patch("gui.tabs.log_analyzer_tab.QMessageBox.warning") as warning, patch.object(
            self.tab,
            "_fn_start_log_channel_thread",
        ):
            self.tab.fn_log_file_changed(str(log_file))

        with patch("gui.tabs.log_analyzer_tab.QMessageBox.information"):
            self.tab._fn_log_channels_loaded([1])

        self.assertEqual(self.tab.log_selector.path(), str(log_file))
        self.assertEqual(self.tab.channel_selector.fn_channel(), 1)
        warning.assert_not_called()
