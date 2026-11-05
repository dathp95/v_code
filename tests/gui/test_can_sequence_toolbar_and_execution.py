import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from openpyxl import load_workbook

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QHBoxLayout

from core.diagnostic_sequence import DiagnosticStep, DiagnosticTestCase
from gui.widgets.can_interface.diagnostic_table_panel import CanDiagnosticTablePanel
from gui.widgets.controls.primary_button import PrimaryButton
from models.ecu import ECU
from models.vehicle import Vehicle


class FakeVehicleService:
    def __init__(self, vehicles=None):
        self._vehicles = vehicles or {"VF5NP": [ECU("BCM", request_id="0x700", response_id="0x708")]}

    def list_vehicles(self):
        return list(self._vehicles.keys())

    def load_vehicle(self, name):
        ecus = self._vehicles.get(name, [])
        return Vehicle(name, ecus=ecus)


class CanSequenceToolbarAndExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.service = FakeVehicleService()
        self.panel = CanDiagnosticTablePanel(vehicle_service=self.service)
        self.addCleanup(self.panel.deleteLater)

        self.steps = [
            DiagnosticStep(
                step=1,
                sequence_name="Step 1 Read VIN",
                ecu="BCM",
                request="22 F1 90",
                delay_ms=50,
                repeat=1,
                expected_response="62 F1 90",
                comment="Comment 1",
            ),
            DiagnosticStep(
                step=2,
                sequence_name="Step 2 Session",
                ecu="BCM",
                request="10 03",
                delay_ms=50,
                repeat=1,
                expected_response="50 03",
                comment="Comment 2",
            ),
            DiagnosticStep(
                step=3,
                sequence_name="Step 3 Reset",
                ecu="BCM",
                request="11 01",
                delay_ms=50,
                repeat=1,
                expected_response="51 01",
                comment="Comment 3",
            ),
        ]
        self.test_case = DiagnosticTestCase(
            schema_version=1,
            name="300.BMS&S",
            description="Battery sequence",
            enabled=True,
            steps=self.steps,
        )
        self.panel.fn_load_sequence(self.test_case)
        self.panel.vehicle_selector.fn_set_vehicle("VF5NP")

    def test_toolbar_layout_and_button_texts(self):
        """Test layout: RUN, EXPORT, STOP first, then Vehicle, +Add Row, Delete, Setting."""
        # Title must be hidden / not added to toolbar
        self.assertTrue(self.panel.title.isHidden())

        # Check button texts
        self.assertEqual(self.panel.btn_add.text(), "+Add Row")
        self.assertEqual(self.panel.btn_delete.text(), "Delete")
        self.assertEqual(self.panel.btn_settings.text(), "Setting")
        self.assertEqual(self.panel.btn_run.text(), "RUN")
        self.assertEqual(self.panel.btn_export.text(), "EXPORT")
        self.assertEqual(self.panel.btn_stop.text(), "STOP")

        # Check RUN, EXPORT, STOP are PrimaryButton instances and visible
        self.assertIsInstance(self.panel.btn_run, PrimaryButton)
        self.assertIsInstance(self.panel.btn_export, PrimaryButton)
        self.assertIsInstance(self.panel.btn_stop, PrimaryButton)
        self.assertFalse(self.panel.btn_run.isHidden())
        self.assertFalse(self.panel.btn_export.isHidden())
        self.assertFalse(self.panel.btn_stop.isHidden())

        # Inspect toolbar layout items
        toolbar = self.panel.layout().itemAt(0)
        self.assertIsInstance(toolbar, QHBoxLayout)

        # Left items, in the table's left margin: RUN | EXPORT | STOP, then Vehicle, +Add Row, Delete, Setting.
        self.assertIs(toolbar.itemAt(0).widget(), self.panel.btn_run)
        self.assertIs(toolbar.itemAt(1).widget(), self.panel.btn_export)
        self.assertIs(toolbar.itemAt(2).widget(), self.panel.btn_stop)
        self.assertIsNone(toolbar.itemAt(3).widget())  # Fixed gap after the three action buttons.
        self.assertIs(toolbar.itemAt(4).widget(), self.panel.vehicle_selector)
        self.assertIs(toolbar.itemAt(5).widget(), self.panel.btn_add)
        self.assertIs(toolbar.itemAt(6).widget(), self.panel.btn_delete)
        self.assertIs(toolbar.itemAt(7).widget(), self.panel.btn_settings)

    def test_run_and_stop_button_signals(self):
        """Test that clicking RUN and STOP emits the proper panel signals."""
        run_events = []
        stop_events = []

        self.panel.sequence_run_requested.connect(lambda: run_events.append(True))
        self.panel.sequence_stop_requested.connect(lambda: stop_events.append(True))

        self.panel.btn_run.setEnabled(True)
        self.panel.btn_run.click()
        self.assertEqual(len(run_events), 1)

        self.panel.btn_stop.setEnabled(True)
        self.panel.btn_stop.click()
        self.assertEqual(len(stop_events), 1)

    def test_sequence_running_state_toggles_buttons(self):
        """Test that set_sequence_running toggles btn_run and btn_stop enabled state."""
        self.panel.set_send_available(True)
        self.assertTrue(self.panel.btn_run.isEnabled())
        self.assertFalse(self.panel.btn_stop.isEnabled())

        self.panel.set_sequence_running(True)
        self.assertFalse(self.panel.btn_run.isEnabled())
        self.assertTrue(self.panel.btn_stop.isEnabled())

        self.panel.set_sequence_running(False)
        self.assertTrue(self.panel.btn_run.isEnabled())
        self.assertFalse(self.panel.btn_stop.isEnabled())

    def test_export_excel_functionality(self):
        """Test that EXPORT button writes valid Excel file with sequence and runtime data."""
        # Set some runtime results
        key1 = self.panel.step_ids[0]
        key2 = self.panel.step_ids[1]
        self.panel.set_step_result(key1, "62 F1 90 01 02", "Passed", "RT 0.05s")
        self.panel.set_step_result(key2, "7F 10 12", "Failed", "NRC 0x12")

        with tempfile.TemporaryDirectory() as tmpdir:
            target_path = Path(tmpdir) / "exported_seq.xlsx"

            with patch("PySide6.QtWidgets.QFileDialog.getSaveFileName", return_value=(str(target_path), "Excel Files (*.xlsx)")), \
                 patch("PySide6.QtWidgets.QMessageBox.information") as mock_info:
                self.panel.export_excel()

                self.assertTrue(target_path.exists())
                mock_info.assert_called_once()

            wb = load_workbook(target_path)
            ws = wb.active

            self.assertEqual(ws["A1"].value, "Generated by V-CODE EEIV Diagnostic")
            self.assertEqual(ws.cell(row=2, column=1).value, "Step")
            self.assertEqual(ws.cell(row=2, column=4).value, "Payload (HEX)")
            self.assertEqual(ws.cell(row=2, column=9).value, "Results")

            # Row 3 (Step 1)
            self.assertEqual(ws.cell(row=3, column=1).value, 1)
            self.assertEqual(ws.cell(row=3, column=4).value, "22 F1 90")
            self.assertEqual(ws.cell(row=3, column=8).value, "62 F1 90 01 02")
            self.assertEqual(ws.cell(row=3, column=9).value, "Passed")

            # Row 4 (Step 2)
            self.assertEqual(ws.cell(row=4, column=1).value, 2)
            self.assertEqual(ws.cell(row=4, column=4).value, "10 03")
            self.assertEqual(ws.cell(row=4, column=8).value, "7F 10 12")
            self.assertEqual(ws.cell(row=4, column=9).value, "Failed")


if __name__ == "__main__":
    unittest.main()
