from dataclasses import replace
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QMessageBox
from core.diagnostic_sequence import DiagnosticTestCase, DiagnosticStep
from core.diagnostic_request import DiagnosticOutcome as Outcome, DiagnosticResult
from services.can.security_access_session import SecurityAccessState as State
from tests.gui import test_can_diagnostic_execution as fixtures
from services.can.ecu_diagnostic_resolver import resolve_request


class SecurityAccessGuiTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.CanDiagnosticExecutionTests.setUpClass.__func__)
    setUp = fixtures.CanDiagnosticExecutionTests.setUp
    wait = fixtures.CanDiagnosticExecutionTests.wait
    click = fixtures.CanDiagnosticExecutionTests.click
    outcome = fixtures.CanDiagnosticExecutionTests.outcome

    def receive_seed(self):
        # A row send of 27 01 is an Auto workflow that never leaves a seed at rest, so the stored-seed
        # lifecycle is exercised by handing the session a seed response directly.
        panel = self.tab.sequence_table
        controller = self.tab.diagnostic_controller
        panel.table.item(0,panel.COL_REQUEST).setText('27 01')
        key = panel.step_ids[0]
        request = replace(resolve_request(panel._vehicle_service, panel.fn_current_vehicle(), panel.step_for_id(key),
                                          key, controller.generation, controller.settings), confirmed=True)
        identity, epoch = controller._connection_identity(), controller._session_epoch
        controller.security_session.start(request, identity, epoch)
        controller._seed_request = request
        controller.security_session.receive(
            DiagnosticResult(request, Outcome.PASSED, b'\x67\x01\xAA\xBB'), identity, epoch)
        controller._refresh_security_status()
        return panel

    def test_seed_lifecycle_status_theme_and_manual_key_remains_disabled(self):
        panel=self.receive_seed()
        controller=self.tab.diagnostic_controller
        self.assertEqual(controller.security_session.state,State.SEED_RECEIVED)
        self.assertTrue(controller.security_session.has_seed)
        label=self.tab.session_panel.current_test_case.security_status
        self.assertIn('Seed received',label.text())
        self.assertNotIn('AA BB',label.text())
        self.assertIn('27 02 disabled',label.text())
        from gui.themes.theme_manager import ThemeManager
        from gui.themes.theme import ThemeType
        self.addCleanup(ThemeManager.fn_set_theme,ThemeManager.fn_theme())
        for theme in (ThemeType.DARK,ThemeType.LIGHT):
            ThemeManager.fn_set_theme(theme);self.tab.fn_refresh_theme()
            self.assertIn('Seed received',label.text())
        self.assertEqual(len(self.bus.sent),0)
        panel.table.item(0,panel.COL_REQUEST).setText('27 02 11 22')
        self.assertFalse(panel.table.cellWidget(0,panel.COL_SEND).isEnabled())
        panel._request_step(panel.step_ids[0])
        self.assertEqual(len(self.bus.sent),0)
        self.assertFalse(controller.security_session.has_seed)

    def test_disconnect_and_document_switch_clear_seed(self):
        panel=self.receive_seed()
        panel.fn_load_sequence(DiagnosticTestCase(1,'Other','',True,[DiagnosticStep(1,'Other','BCM','22 F1 90')]))
        self.assertFalse(self.tab.diagnostic_controller.security_session.has_seed)
        self.receive_seed()
        self.tab.disconnect_can();self.wait(lambda:not self.tab._connection_task.running)
        self.assertFalse(self.tab.diagnostic_controller.security_session.has_seed)

    def test_connection_start_immediately_invalidates_material(self):
        self.receive_seed()
        self.tab.diagnostic_controller._connection_started()
        self.assertFalse(self.tab.diagnostic_controller.security_session.has_seed)

    def test_sending_another_ecu_without_row_selection_invalidates_material(self):
        from models.ecu import ECU
        panel=self.tab.sequence_table
        vehicle=panel._vehicle_service.load_vehicle('BENCH')
        vehicle.ecus.append(ECU('EPS','682','602'))
        panel.fn_set_vehicle(vehicle)
        panel.fn_load_sequence(DiagnosticTestCase(1,'Mixed','',True,[
            DiagnosticStep(1,'Seed','BCM','27 01',expected_response='67 01'),
            DiagnosticStep(2,'EPS','EPS','22 F1 90',expected_response='62 F1 90')]))
        self.receive_seed()
        panel.table.cellWidget(1,panel.COL_SEND).click()
        self.wait(lambda:len(self.bus.sent)==1)
        self.assertFalse(self.tab.diagnostic_controller.security_session.has_seed)

    def test_stored_seed_expires_without_user_action(self):
        controller=self.tab.diagnostic_controller
        now=[10.0]
        controller.security_session._clock=lambda:now[0]
        self.receive_seed();now[0]+=31
        self.wait(lambda:controller.security_session.state==State.FAILED)
        self.assertFalse(controller.security_session.has_seed)

    def test_inflight_cancel_and_session_control_do_not_retain_seed(self):
        panel=self.receive_seed()
        panel.table.item(0,panel.COL_REQUEST).setText('10 03')
        self.bus.mode='silent'
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes): self.click()
        self.wait(lambda:len(self.bus.sent)==1)
        self.assertFalse(self.tab.diagnostic_controller.security_session.has_seed)
        panel.table.item(0,panel.COL_REQUEST).setText('27 01')
        self.wait(lambda:not self.tab._connection_task.diagnostic_busy)
        self.bus.rx('04 67 01 AA BB 00 00 00')
        self.wait(lambda:not self.bus.queue)
        self.assertFalse(self.tab.diagnostic_controller.security_session.has_seed)
