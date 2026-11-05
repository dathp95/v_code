import os
import unittest
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QItemSelectionModel, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QAbstractSpinBox
from PySide6.QtWidgets import QApplication, QAbstractItemView

from core.diagnostic_sequence import (
    DiagnosticExecutionSettings,
    DiagnosticStep,
    DiagnosticTestCase,
)
from gui.themes.styles.controls.spinbox_style import fn_spinbox_style
from gui.widgets.controls.primary_integer_spinbox import PrimaryIntegerSpinBox
from gui.widgets.diagnostic.diagnostic_sequence_table import DiagnosticSequenceTable
from models.ecu import ECU
from models.vehicle import Vehicle


class FakeVehicleService:

    def __init__(self, vehicles=None):
        self.vehicles = {
            "VF5NP": ["ACU", "BCM", "BMS"],
            "VF6": ["BCM", "VCU"],
            "VF7": ["ACU", "BMS"],
        } if vehicles is None else vehicles
        self.list_count = 0
        self.load_count = 0

    def list_vehicles(self):
        self.list_count += 1
        if isinstance(self.vehicles, dict):
            return list(self.vehicles)
        return list(self.vehicles)

    def load_vehicle(self, vehicle_name):
        self.load_count += 1
        if isinstance(self.vehicles, dict):
            ecu_names = self.vehicles.get(vehicle_name, [])
        else:
            ecu_names = []
        return Vehicle(
            name=vehicle_name,
            ecus=[ECU(name=ecu_name) for ecu_name in ecu_names],
        )


class DiagnosticSequenceTableTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_load_sequence_displays_execution_settings_and_steps(self):
        widget = self._create_widget()
        self.addCleanup(widget.deleteLater)
        test_case = self._test_case()

        widget.fn_load_sequence(test_case)

        self.assertEqual(widget.spn_loop.value(), 3)
        self.assertEqual(widget.spn_command_delay.value(), 250)
        self.assertEqual(widget.table.rowCount(), 1)
        self.assertEqual(widget.table.item(0, widget.COL_STEP).text(), "1")
        self.assertEqual(widget.table.item(0, widget.COL_SEQUENCE_NAME).text(), "Read VIN")
        self.assertEqual(widget.table.cellWidget(0, widget.COL_ECU).currentText(), "ACU")
        self.assertEqual(widget.table.item(0, widget.COL_REQUEST).text(), "22 F1 90")
        self.assertEqual(widget.table.item(0, widget.COL_DELAY).text(), "")
        self.assertEqual(widget.table.item(0, widget.COL_REPEAT).text(), "2")
        self.assertEqual(widget.table.item(0, widget.COL_EXPECTED).text(), "62 F1 90")
        self.assertEqual(widget.table.item(0, widget.COL_RECEIVE).text(), "")
        self.assertEqual(widget.table.item(0, widget.COL_RESULT).text(), "")

    def test_table_headers_remove_index_and_use_short_names(self):
        widget = self._create_widget()
        self.addCleanup(widget.deleteLater)

        headers = [
            widget.table.horizontalHeaderItem(column).text()
            for column in range(widget.table.columnCount())
        ]

        self.assertNotIn("Index", headers)
        self.assertEqual(
            headers,
            [
                "Step",
                "Test Sequence Name",
                "ECU",
                "TX Message",
                "DL (ms)",
                "Loop",
                "EX Message",
                "RX Message",
                "Result",
            ],
        )

    def test_table_rows_are_taller_and_multi_selectable(self):
        widget = self._create_widget()
        self.addCleanup(widget.deleteLater)

        self.assertEqual(
            widget.table.verticalHeader().defaultSectionSize(),
            widget.ROW_HEIGHT,
        )
        self.assertGreaterEqual(widget.ROW_HEIGHT, 32)
        self.assertLessEqual(widget.ROW_HEIGHT, 36)
        self.assertEqual(widget.table.selectionBehavior(), QAbstractItemView.SelectRows)
        self.assertEqual(widget.table.selectionMode(), QAbstractItemView.ExtendedSelection)

    def test_execution_row_order_has_vehicle_add_loop_delay_import_and_actions(self):
        widget = self._create_widget()
        self.addCleanup(widget.deleteLater)

        self.assertFalse(hasattr(widget, "lbl_duration"))
        self.assertIs(widget.execution_layout.itemAt(0).widget(), widget.vehicle_selector)
        self.assertIs(widget.execution_layout.itemAt(1).widget(), widget.btn_add)
        self.assertIs(widget.execution_layout.itemAt(3).widget(), widget.lbl_loop)
        self.assertIs(widget.execution_layout.itemAt(4).widget(), widget.spn_loop)
        self.assertIs(widget.execution_layout.itemAt(6).widget(), widget.lbl_command_delay)
        self.assertIs(widget.execution_layout.itemAt(7).widget(), widget.spn_command_delay)
        self.assertIs(widget.execution_layout.itemAt(8).widget(), widget.lbl_ms)
        self.assertIs(widget.execution_layout.itemAt(9).widget(), widget.btn_import_delay)
        self.assertIsNone(widget.execution_layout.itemAt(10).widget())
        self.assertIs(widget.execution_layout.itemAt(11).widget(), widget.btn_export)
        self.assertIs(widget.execution_layout.itemAt(12).widget(), widget.btn_stop)
        self.assertIs(widget.execution_layout.itemAt(13).widget(), widget.btn_run)
        self.assertIsInstance(widget.spn_loop, PrimaryIntegerSpinBox)
        self.assertIsInstance(widget.spn_command_delay, PrimaryIntegerSpinBox)
        self.assertEqual(widget.btn_add.text(), "+ Add")
        self.assertEqual(widget.btn_import_delay.text(), "Import")
        self.assertEqual(widget.btn_export.text(), "EXPORT")
        self.assertEqual(widget.btn_stop.text(), "STOP")
        self.assertEqual(widget.btn_run.text(), "RUN")

    def test_vehicle_selector_uses_vehicle_service_and_exposes_current_vehicle(self):
        service = FakeVehicleService({"VF5NP": ["ACU"], "VF6": ["BCM"]})
        widget = DiagnosticSequenceTable(vehicle_service=service)
        self.addCleanup(widget.deleteLater)

        self.assertEqual(service.list_count, 1)
        self.assertEqual(widget.vehicle_selector.cmb_vehicle.count(), 2)
        self.assertEqual(widget.vehicle_selector.cmb_vehicle.itemText(0), "VF5NP")
        self.assertEqual(widget.vehicle_selector.cmb_vehicle.itemText(1), "VF6")
        self.assertEqual(widget.fn_current_vehicle(), "VF5NP")

        widget.vehicle_selector.fn_set_vehicle("VF6")

        self.assertEqual(widget.fn_current_vehicle(), "VF6")
        self.assertEqual(service.load_count, 2)

    def test_empty_vehicle_list_is_safe(self):
        widget = DiagnosticSequenceTable(vehicle_service=FakeVehicleService([]))
        self.addCleanup(widget.deleteLater)

        self.assertEqual(widget.vehicle_selector.cmb_vehicle.count(), 0)
        self.assertEqual(widget.fn_current_vehicle(), "")

    def test_ecu_combo_is_populated_from_selected_vehicle(self):
        widget = self._create_widget()
        self.addCleanup(widget.deleteLater)
        widget.fn_load_sequence(self._test_case())

        combo = widget.table.cellWidget(0, widget.COL_ECU)

        self.assertEqual(
            [combo.itemText(index) for index in range(combo.count())],
            ["ACU", "BCM", "BMS"],
        )
        self.assertEqual(combo.currentText(), "ACU")
        self.assertIsInstance(combo.itemData(0), ECU)

    def test_missing_ecu_stays_in_model_and_combo_is_unselected(self):
        widget = self._create_widget()
        self.addCleanup(widget.deleteLater)
        test_case = self._test_case()
        test_case = replace(test_case, steps=[replace(test_case.steps[0], ecu="MISSING")])

        widget.fn_load_sequence(test_case)

        combo = widget.table.cellWidget(0, widget.COL_ECU)
        self.assertEqual(widget.fn_current_sequence().steps[0].ecu, "MISSING")
        self.assertEqual(combo.currentIndex(), -1)
        self.assertFalse(widget.fn_is_dirty())

    def test_vehicle_change_refreshes_ecu_combos_without_dirtying_sequence(self):
        widget = self._create_widget()
        self.addCleanup(widget.deleteLater)
        widget.fn_load_sequence(self._test_case())

        widget.vehicle_selector.fn_set_vehicle("VF6")

        combo = widget.table.cellWidget(0, widget.COL_ECU)
        self.assertEqual(
            [combo.itemText(index) for index in range(combo.count())],
            ["BCM", "VCU"],
        )
        self.assertEqual(widget.fn_current_sequence().steps[0].ecu, "ACU")
        self.assertEqual(combo.currentIndex(), -1)
        self.assertFalse(widget.fn_is_dirty())

    def test_vehicle_change_preserves_current_ecu_when_available(self):
        widget = self._create_widget()
        self.addCleanup(widget.deleteLater)
        test_case = self._test_case()
        test_case = replace(test_case, steps=[replace(test_case.steps[0], ecu="BCM")])
        widget.fn_load_sequence(test_case)

        widget.vehicle_selector.fn_set_vehicle("VF6")

        combo = widget.table.cellWidget(0, widget.COL_ECU)
        self.assertEqual(combo.currentText(), "BCM")
        self.assertEqual(widget.fn_current_sequence().steps[0].ecu, "BCM")
        self.assertFalse(widget.fn_is_dirty())

    def test_old_sequence_without_execution_uses_default_inputs(self):
        widget = self._create_widget()
        self.addCleanup(widget.deleteLater)
        test_case = DiagnosticTestCase(
            schema_version=1,
            name="READ VIN",
            description="",
            enabled=True,
            steps=[],
        )

        widget.fn_load_sequence(test_case)

        self.assertEqual(widget.spn_loop.value(), 1)
        self.assertEqual(widget.spn_command_delay.value(), 100)

    def test_primary_spinbox_styles_buttons_and_arrows(self):
        style = fn_spinbox_style()

        self.assertIn("QSpinBox::up-button", style)
        self.assertIn("QSpinBox::down-button", style)
        self.assertIn("QSpinBox::up-arrow", style)
        self.assertIn("QSpinBox::down-arrow", style)
        self.assertIn("QSpinBox::up-button:hover", style)
        self.assertIn("QSpinBox::down-button:pressed", style)
        self.assertIn("QSpinBox::up-arrow:disabled", style)
        self.assertIn("QSpinBox::down-arrow:disabled", style)

    def test_number_inputs_center_align_numeric_text(self):
        widget = self._create_widget()
        self.addCleanup(widget.deleteLater)

        self.assertEqual(
            widget.spn_loop.lineEdit().alignment(),
            Qt.AlignCenter,
        )
        self.assertEqual(
            widget.spn_command_delay.lineEdit().alignment(),
            Qt.AlignCenter,
        )
    def test_loop_and_delay_use_the_same_spinbox_as_q_current_wake_duration(self):
        from PySide6.QtWidgets import QDoubleSpinBox
        widget = self._create_widget()
        self.addCleanup(widget.deleteLater)

        for spinbox in (widget.spn_loop, widget.spn_command_delay):
            self.assertIsInstance(spinbox, QDoubleSpinBox)
            self.assertEqual(spinbox.decimals(), 0)
            self.assertEqual(spinbox.buttonSymbols(), QAbstractSpinBox.UpDownArrows)
            self.assertEqual(spinbox.styleSheet(), fn_spinbox_style())
            self.assertIsInstance(spinbox.value(), int)
        self.assertFalse(hasattr(widget.spn_loop, "btn_increment"))

    def test_spinbox_changes_store_whole_numbers_in_the_model(self):
        widget = self._create_widget()
        self.addCleanup(widget.deleteLater)
        widget.fn_load_sequence(self._test_case())

        widget.spn_loop.setValue(7)
        widget.spn_command_delay.setValue(450)

        execution = widget.fn_current_sequence().execution
        self.assertEqual((execution.loop, execution.command_delay_ms), (7, 450))
        self.assertIsInstance(execution.loop, int)
        self.assertIsInstance(execution.command_delay_ms, int)

    def test_loop_spinbox_range_step_and_manual_value(self):
        widget = self._create_widget()
        self.addCleanup(widget.deleteLater)
        widget.fn_load_sequence(self._test_case())

        self.assertEqual(widget.spn_loop.minimum(), 1)
        self.assertEqual(widget.spn_loop.maximum(), 9999)
        self.assertEqual(widget.spn_loop.singleStep(), 1)

        widget.spn_loop.stepUp()
        self.assertEqual(widget.spn_loop.value(), 4)
        widget.spn_loop.setValue(42)
        self.assertEqual(widget.fn_current_sequence().execution.loop, 42)
        widget.spn_loop.setValue(0)
        self.assertEqual(widget.spn_loop.value(), 1)
        self.assertEqual(widget.fn_current_sequence().execution.loop, 1)

    def test_command_delay_spinbox_range_step_and_manual_value(self):
        widget = self._create_widget()
        self.addCleanup(widget.deleteLater)
        widget.fn_load_sequence(self._test_case())

        self.assertEqual(widget.spn_command_delay.minimum(), 0)
        self.assertEqual(widget.spn_command_delay.maximum(), 60000)
        self.assertEqual(widget.spn_command_delay.singleStep(), 100)

        widget.spn_command_delay.stepUp()
        self.assertEqual(widget.spn_command_delay.value(), 350)
        widget.spn_command_delay.setValue(150)
        self.assertEqual(
            widget.fn_current_sequence().execution.command_delay_ms,
            150,
        )
        widget.spn_command_delay.setValue(-1)
        self.assertEqual(widget.spn_command_delay.value(), 0)
        self.assertEqual(
            widget.fn_current_sequence().execution.command_delay_ms,
            0,
        )

    def test_editing_loop_and_command_delay_updates_model(self):
        widget = self._create_widget()
        self.addCleanup(widget.deleteLater)
        modified = []
        widget.sequence_modified.connect(modified.append)
        widget.fn_load_sequence(self._test_case())

        widget.spn_loop.setValue(4)
        widget.spn_command_delay.setValue(500)

        current = widget.fn_current_sequence()
        self.assertEqual(current.execution.loop, 4)
        self.assertEqual(current.execution.command_delay_ms, 500)
        self.assertTrue(widget.fn_is_dirty())
        self.assertGreaterEqual(len(modified), 2)

    def test_editing_request_normalizes_hex_and_updates_model(self):
        widget = self._create_widget()
        self.addCleanup(widget.deleteLater)
        widget.fn_load_sequence(self._test_case())

        item = widget.table.item(0, widget.COL_REQUEST)
        item.setText("22 f3 90")

        self.assertEqual(widget.fn_current_sequence().steps[0].request, "22 F3 90")
        self.assertEqual(widget.table.item(0, widget.COL_REQUEST).text(), "22 F3 90")

    def test_invalid_request_restores_previous_value_without_crash(self):
        widget = self._create_widget()
        self.addCleanup(widget.deleteLater)
        widget.fn_load_sequence(self._test_case())

        item = widget.table.item(0, widget.COL_REQUEST)
        item.setText("22 F1 ZZ")

        self.assertEqual(widget.fn_current_sequence().steps[0].request, "22 F1 90")
        self.assertEqual(widget.table.item(0, widget.COL_REQUEST).text(), "22 F1 90")

    def test_blank_delay_remains_none_and_repeat_is_independent_from_loop(self):
        widget = self._create_widget()
        self.addCleanup(widget.deleteLater)
        widget.fn_load_sequence(self._test_case())

        widget.table.item(0, widget.COL_DELAY).setText("")
        widget.table.item(0, widget.COL_REPEAT).setText("5")
        widget.spn_loop.setValue(2)

        current = widget.fn_current_sequence()
        self.assertIsNone(current.steps[0].delay_ms)
        self.assertEqual(current.steps[0].repeat, 5)
        self.assertEqual(current.execution.loop, 2)

    def test_receive_and_result_are_read_only(self):
        widget = self._create_widget()
        self.addCleanup(widget.deleteLater)
        widget.fn_load_sequence(self._test_case())

        receive_flags = widget.table.item(0, widget.COL_RECEIVE).flags()
        result_flags = widget.table.item(0, widget.COL_RESULT).flags()

        self.assertFalse(receive_flags & Qt.ItemIsEditable)
        self.assertFalse(result_flags & Qt.ItemIsEditable)

    def test_switching_sequence_loads_its_own_settings(self):
        widget = self._create_widget()
        self.addCleanup(widget.deleteLater)
        widget.fn_load_sequence(self._test_case(loop=3, command_delay_ms=250))

        widget.fn_load_sequence(self._test_case(loop=1, command_delay_ms=100, name="READ CDS"))

        self.assertEqual(widget.spn_loop.value(), 1)
        self.assertEqual(widget.spn_command_delay.value(), 100)
        self.assertEqual(widget.table.item(0, widget.COL_SEQUENCE_NAME).text(), "Read VIN")
        self.assertFalse(widget.fn_is_dirty())

    def test_add_step_appends_when_no_row_selected(self):
        widget = self._create_widget()
        self.addCleanup(widget.deleteLater)
        widget.fn_load_sequence(self._test_case())
        widget.table.clearSelection()

        widget.fn_add_step_after_selected()

        current = widget.fn_current_sequence()
        self.assertEqual(widget.table.rowCount(), 2)
        self.assertEqual([step.step for step in current.steps], [1, 2])
        self.assertEqual(current.steps[1].sequence_name, "")
        self.assertEqual(current.steps[1].ecu, "ACU")
        self.assertEqual(current.steps[1].request, "")
        self.assertIsNone(current.steps[1].delay_ms)
        self.assertEqual(widget.table.currentRow(), 1)
        self.assertTrue(widget.table.item(1, widget.COL_STEP).isSelected())
        self.assertTrue(widget.fn_is_dirty())

    def test_add_step_inserts_after_selected_row_and_reindexes_steps(self):
        widget = self._create_widget()
        self.addCleanup(widget.deleteLater)
        widget.fn_load_sequence(self._test_case_with_three_steps())
        widget.table.selectRow(0)

        widget.btn_add.click()

        current = widget.fn_current_sequence()
        self.assertEqual(widget.table.rowCount(), 4)
        self.assertEqual([step.step for step in current.steps], [1, 2, 3, 4])
        self.assertEqual(current.steps[0].sequence_name, "Read VIN")
        self.assertEqual(current.steps[1].sequence_name, "")
        self.assertEqual(current.steps[1].ecu, "ACU")
        self.assertEqual(current.steps[2].sequence_name, "Read DTC")
        self.assertEqual(widget.table.currentRow(), 1)
        self.assertEqual(widget.table.item(1, widget.COL_STEP).text(), "2")
        self.assertTrue(widget.fn_is_dirty())

    def test_add_step_on_empty_table_uses_empty_ecu(self):
        widget = self._create_widget()
        self.addCleanup(widget.deleteLater)
        widget.fn_load_sequence(
            DiagnosticTestCase(
                schema_version=1,
                name="EMPTY",
                description="",
                enabled=True,
                execution=DiagnosticExecutionSettings(),
                steps=[],
            )
        )

        widget.fn_add_step_after_selected()

        current = widget.fn_current_sequence()
        combo = widget.table.cellWidget(0, widget.COL_ECU)
        self.assertEqual(current.steps[0].ecu, "")
        self.assertEqual(combo.currentIndex(), -1)

    def test_add_step_inherits_missing_ecu_but_leaves_combo_unselected(self):
        widget = self._create_widget()
        self.addCleanup(widget.deleteLater)
        test_case = self._test_case()
        test_case = replace(test_case, steps=[replace(test_case.steps[0], ecu="LEGACY")])
        widget.fn_load_sequence(test_case)

        widget.fn_add_step_after_selected()

        current = widget.fn_current_sequence()
        combo = widget.table.cellWidget(1, widget.COL_ECU)
        self.assertEqual(current.steps[1].ecu, "LEGACY")
        self.assertEqual(combo.currentIndex(), -1)

    def test_add_step_inherits_delay_and_loop_from_previous_row(self):
        widget = self._create_widget()
        self.addCleanup(widget.deleteLater)
        widget.fn_load_sequence(self._test_case_with_three_steps())
        widget.table.selectRow(1)

        widget.fn_add_step_after_selected()

        current = widget.fn_current_sequence()
        self.assertEqual(current.steps[2].ecu, "BCM")
        self.assertEqual(current.steps[2].delay_ms, 500)
        self.assertEqual(current.steps[2].repeat, 1)
        self.assertEqual(widget.table.item(2, widget.COL_DELAY).text(), "500")
        self.assertEqual(widget.table.item(2, widget.COL_REPEAT).text(), "1")

    def test_delete_key_removes_selected_rows_and_reindexes_steps(self):
        widget = self._create_widget()
        self.addCleanup(widget.deleteLater)
        widget.fn_load_sequence(self._test_case_with_three_steps())
        widget.table.selectRow(1)
        widget._is_dirty = False

        event = QKeyEvent(QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier)
        QApplication.sendEvent(widget.table, event)

        current = widget.fn_current_sequence()
        self.assertEqual(widget.table.rowCount(), 2)
        self.assertEqual([step.step for step in current.steps], [1, 2])
        self.assertEqual(
            [step.sequence_name for step in current.steps],
            ["Read VIN", "Extended Session"],
        )
        self.assertEqual(widget.table.currentRow(), 1)
        self.assertTrue(widget.fn_is_dirty())

    def test_import_updates_loop_and_delay_on_selected_rows_only(self):
        widget = self._create_widget()
        self.addCleanup(widget.deleteLater)
        widget.fn_load_sequence(self._test_case_with_three_steps())
        widget.spn_loop.setValue(4)
        widget.spn_command_delay.setValue(100)
        widget._is_dirty = False
        widget.table.clearSelection()
        selection = widget.table.selectionModel()
        selection.select(
            widget.table.model().index(0, widget.COL_STEP),
            QItemSelectionModel.Select | QItemSelectionModel.Rows,
        )
        selection.select(
            widget.table.model().index(2, widget.COL_STEP),
            QItemSelectionModel.Select | QItemSelectionModel.Rows,
        )

        widget.btn_import_delay.click()

        current = widget.fn_current_sequence()
        self.assertEqual(
            [step.delay_ms for step in current.steps],
            [100, 500, 100],
        )
        self.assertEqual(
            [step.repeat for step in current.steps],
            [4, 1, 4],
        )
        self.assertEqual(widget.table.item(0, widget.COL_DELAY).text(), "100")
        self.assertEqual(widget.table.item(1, widget.COL_DELAY).text(), "500")
        self.assertEqual(widget.table.item(2, widget.COL_DELAY).text(), "100")
        self.assertEqual(widget.table.item(0, widget.COL_REPEAT).text(), "4")
        self.assertEqual(widget.table.item(1, widget.COL_REPEAT).text(), "1")
        self.assertEqual(widget.table.item(2, widget.COL_REPEAT).text(), "4")
        self.assertTrue(widget.fn_is_dirty())

    def test_import_updates_loop_and_delay_on_all_rows_when_nothing_selected(self):
        widget = self._create_widget()
        self.addCleanup(widget.deleteLater)
        widget.fn_load_sequence(self._test_case_with_three_steps())
        widget.spn_loop.setValue(3)
        widget.spn_command_delay.setValue(250)
        widget._is_dirty = False
        widget.table.clearSelection()

        widget.fn_import_execution_values_to_rows()

        current = widget.fn_current_sequence()
        self.assertEqual(
            [step.delay_ms for step in current.steps],
            [250, 250, 250],
        )
        self.assertEqual(
            [step.repeat for step in current.steps],
            [3, 3, 3],
        )
        self.assertEqual(widget.table.item(0, widget.COL_DELAY).text(), "250")
        self.assertEqual(widget.table.item(1, widget.COL_DELAY).text(), "250")
        self.assertEqual(widget.table.item(2, widget.COL_DELAY).text(), "250")
        self.assertEqual(widget.table.item(0, widget.COL_REPEAT).text(), "3")
        self.assertEqual(widget.table.item(1, widget.COL_REPEAT).text(), "3")
        self.assertEqual(widget.table.item(2, widget.COL_REPEAT).text(), "3")
        self.assertTrue(widget.fn_is_dirty())

    @staticmethod
    def _create_widget():
        return DiagnosticSequenceTable(vehicle_service=FakeVehicleService())

    @staticmethod
    def _test_case(loop=3, command_delay_ms=250, name="READ VIN"):
        return DiagnosticTestCase(
            schema_version=1,
            name=name,
            description="Read VIN from selected ECUs",
            enabled=True,
            execution=DiagnosticExecutionSettings(
                loop=loop,
                command_delay_ms=command_delay_ms,
            ),
            steps=[
                DiagnosticStep(
                    step=1,
                    sequence_name="Read VIN",
                    ecu="ACU",
                    request="22 F1 90",
                    delay_ms=None,
                    repeat=2,
                    expected_response="62 F1 90",
                    match="prefix",
                    comment="",
                )
            ],
        )

    @staticmethod
    def _test_case_with_three_steps():
        return DiagnosticTestCase(
            schema_version=1,
            name="READ MANY",
            description="",
            enabled=True,
            execution=DiagnosticExecutionSettings(
                loop=1,
                command_delay_ms=100,
            ),
            steps=[
                DiagnosticStep(
                    step=1,
                    sequence_name="Read VIN",
                    ecu="ACU",
                    request="22 F1 90",
                    delay_ms=None,
                    repeat=1,
                    expected_response="62 F1 90",
                ),
                DiagnosticStep(
                    step=2,
                    sequence_name="Read DTC",
                    ecu="BCM",
                    request="19 02 09",
                    delay_ms=500,
                    repeat=1,
                    expected_response="59 02",
                ),
                DiagnosticStep(
                    step=3,
                    sequence_name="Extended Session",
                    ecu="BMS",
                    request="10 03",
                    delay_ms=None,
                    repeat=1,
                    expected_response="50 03",
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
