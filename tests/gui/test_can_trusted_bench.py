import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QMessageBox
from core.diagnostic_request import DiagnosticSettings
from services.can import CANConfig
from gui.workers.can_connection_worker import CANConnectionOperation
from tests.gui import test_can_diagnostic_execution as fixtures
from core.diagnostic_sequence import DiagnosticStep,DiagnosticTestCase
from models.ecu import ECU
from tests.gui import test_can_connection_bench_policy as policy
from core.bench_authorization import BenchAuthorizationContext

class TrustedBenchGuiTests(unittest.TestCase):
    setUpClass=classmethod(fixtures.CanDiagnosticExecutionTests.setUpClass.__func__)
    setUp=fixtures.CanDiagnosticExecutionTests.setUp
    wait=fixtures.CanDiagnosticExecutionTests.wait
    click=fixtures.CanDiagnosticExecutionTests.click
    outcome=fixtures.CanDiagnosticExecutionTests.outcome
    enable=policy.ConnectionBenchPolicyGuiTests.authorize_connection

    def test_explicit_opt_in_skips_only_three_exact_requests_and_reconnect_resets(self):
        panel=self.tab.sequence_table
        self.assertIsNone(self.service.trusted_bench)
        with patch.object(QMessageBox,'question',side_effect=AssertionError('No connection authorization popup')):
            self.enable()
        self.tab.diagnostic_controller.settings=DiagnosticSettings(p2_s=.03,p2_star_s=.05,total_s=.2)
        for payload in ('10 01','10 03','14 FF FF FF'):
            panel.table.item(0,panel.COL_REQUEST).setText(payload)
            before=len(self.bus.sent)
            with patch.object(QMessageBox,'question',side_effect=AssertionError('Unexpected per-request popup')):
                self.click();self.wait(lambda:not self.tab._connection_task.diagnostic_busy)
            self.assertEqual(len(self.bus.sent),before+1)
        self.tab.disconnect_can();self.wait(lambda:not self.tab._connection_task.running)
        self.assertIsNone(self.service.trusted_bench)
        self.assertEqual(self.tab.session_panel.connection.cmb_bench_policy.currentIndex(),0)
        self.tab._connection_task.start(CANConnectionOperation.CONNECT,CANConfig('vector',0,500000))
        self.wait(lambda:not self.tab._connection_task.running)
        panel.table.item(0,panel.COL_REQUEST).setText('10 03')
        before=len(self.bus.sent)
        self.click()
        self.wait(lambda:not self.tab._connection_task.diagnostic_busy)
        self.assertEqual(len(self.bus.sent),before + 1)

    def test_other_services_still_prompt_and_vehicle_refresh_preserves_connection_grant(self):
        panel=self.tab.sequence_table
        self.enable()
        for payload in ('11 01','2E F1 90 01','31 01 12 34','85 02','14 00 00 00','10 81'):
            panel.table.item(0,panel.COL_REQUEST).setText(payload)
            self.click()
            self.wait(lambda:not self.tab._connection_task.diagnostic_busy)
        self.assertTrue(len(self.bus.sent) > 0)
        panel.fn_refresh_vehicles()
        self.assertIsNotNone(self.service.trusted_bench)

    def test_explicit_context_change_revokes_and_metadata_edit_cancels_running_result(self):
        panel=self.tab.sequence_table
        self.enable()
        self.service.fn_configure_bench_context(BenchAuthorizationContext('another-bench',authorized=True))
        self.assertIsNone(self.service.trusted_bench)
        self.bus.mode='pending';self.click();self.wait(lambda:bool(self.bus.sent))
        panel.table.item(0,panel.COL_COMMENT).setText('metadata edit during pending')
        self.wait(lambda:not self.tab._connection_task.diagnostic_busy)
        self.assertEqual(self.outcome(),'\u2014')
        self.assertNotEqual(self.outcome(),'Passed')

    def test_four_actual_fake_bus_results_survive_fifth_ecu_edit(self):
        panel=self.tab.sequence_table
        panel._current_vehicle.ecus.append(ECU('EPS','682','602'))
        panel.fn_refresh_vehicles()
        self.tab._on_sequence_selected(DiagnosticTestCase(1,'Five steps','',True,
            [DiagnosticStep(i,'Five steps','BCM','22 F1 90',expected_response='62 F1 90') for i in range(1,6)]))
        ids=tuple(panel.step_ids)
        for row in range(4):
            panel.table.cellWidget(row,panel.COL_SEND).click()
            self.wait(lambda r=row:panel.table.item(r,panel.COL_RESULT).text()=='Passed')
        previous=dict(panel._runtime)
        combo=panel.table.cellWidget(4,panel.COL_ECU)
        combo.setCurrentIndex(combo.findText('EPS'))
        self.assertEqual(panel._runtime,previous)
        self.assertEqual(tuple(panel.step_ids),ids)
        self.assertEqual(len(self.bus.sent),8)  # Four SF requests and four FC frames.

    def test_trust_revocation_and_theme_do_not_grant_extra_permissions(self):
        from gui.themes.theme_manager import ThemeManager
        from gui.themes.theme import ThemeType
        self.enable()
        grant=self.service.trusted_bench
        self.addCleanup(ThemeManager.fn_set_theme,ThemeManager.fn_theme())
        for theme in (ThemeType.LIGHT,ThemeType.DARK):
            ThemeManager.fn_set_theme(theme);self.tab.fn_refresh_theme()
            self.assertEqual(self.service.trusted_bench,grant)
        self.service.fn_configure_bench_context(None)
        self.assertIsNone(self.service.trusted_bench)
