import os
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QMessageBox
from core.diagnostic_request import DiagnosticSettings
from core.diagnostic_sequence import DiagnosticStep, DiagnosticTestCase
from tests.gui import test_can_diagnostic_execution as fixtures


class SecuritySeedGuiTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.CanDiagnosticExecutionTests.setUpClass.__func__)
    setUp = fixtures.CanDiagnosticExecutionTests.setUp
    wait = fixtures.CanDiagnosticExecutionTests.wait
    click = fixtures.CanDiagnosticExecutionTests.click
    outcome = fixtures.CanDiagnosticExecutionTests.outcome

    def configure(self, text='27 01'):
        panel = self.tab.sequence_table
        panel.table.item(0,panel.COL_REQUEST).setText(text)
        panel.table.item(0,panel.COL_EXPECTED).setText('67 01')
        return panel

    def test_exact_seed_ui_guard_whitespace_invalid_hex_unresolved_and_disconnected(self):
        panel = self.configure(' \t27\u00a001\n')
        button = panel.table.cellWidget(0,panel.COL_SEND)
        self.assertTrue(button.isEnabled())
        sent = []
        panel.row_send_requested.connect(sent.append)
        for text in ('27 02','27 09','27 01 00','27 0a','27 81','27','270','27 0G','0x27 01',''):
            panel.table.item(0,panel.COL_REQUEST).setText(text)
            self.assertFalse(panel.table.cellWidget(0,panel.COL_SEND).isEnabled(),text)
            panel._request_step(panel.step_ids[0])
        self.assertEqual(sent,[])
        panel.fn_load_sequence(DiagnosticTestCase(1,'Seed','',True,[DiagnosticStep(1,'Seed','MISSING','27 01')]))
        self.assertFalse(panel.table.cellWidget(0,panel.COL_SEND).isEnabled())
        panel._request_step(panel.step_ids[0]);self.assertEqual(sent,[])
        panel.fn_load_sequence(DiagnosticTestCase(1,'Seed','',True,[DiagnosticStep(1,'Seed','BCM','27 01')]))
        self.assertTrue(panel.table.cellWidget(0,panel.COL_SEND).isEnabled())
        self.tab.disconnect_can();self.wait(lambda:not self.tab._connection_task.running)
        self.assertFalse(panel.table.cellWidget(0,panel.COL_SEND).isEnabled())
        self.assertEqual(self.bus.sent,[])

    def test_seed_row_without_verified_provider_sends_nothing(self):
        # Every 27 01/03/05/07 row is an Auto workflow now; on a physical adapter it needs a verified provider.
        panel = self.configure()
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes) as confirm:
            self.click()
            self.wait(lambda:self.outcome()=='Failed')
        confirm.assert_not_called()
        self.assertEqual(self.bus.sent,[])
        self.assertIn('Physical Auto',panel.notice.text())


if __name__ == '__main__':
    unittest.main()
