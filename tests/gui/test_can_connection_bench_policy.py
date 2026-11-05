import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QMessageBox
from core.diagnostic_request import DiagnosticSettings
from core.diagnostic_sequence import DiagnosticStep,DiagnosticTestCase
from services.can import CANConfig
from gui.workers.can_connection_worker import CANConnectionOperation
from tests.gui import test_can_diagnostic_execution as fixtures

class ConnectionBenchPolicyGuiTests(unittest.TestCase):
    setUpClass=classmethod(fixtures.CanDiagnosticExecutionTests.setUpClass.__func__)
    setUp=fixtures.CanDiagnosticExecutionTests.setUp
    wait=fixtures.CanDiagnosticExecutionTests.wait
    click=fixtures.CanDiagnosticExecutionTests.click
    outcome=fixtures.CanDiagnosticExecutionTests.outcome

    def authorize_connection(self):
        from core.bench_authorization import BenchAuthorizationContext
        task=self.tab._connection_task
        self.tab.disconnect_can();self.wait(lambda:not task.running)
        self.tab.session_panel.connection.cmb_bench_policy.setCurrentIndex(1)
        task.start(CANConnectionOperation.CONNECT,CANConfig('vector',0,500000,
            bench_context=BenchAuthorizationContext('manual-automotive-bench',authorized=True)))
        self.wait(lambda:not task.running)
        self.assertIsNotNone(self.service.trusted_bench)
        self.tab.diagnostic_controller.settings=DiagnosticSettings(p2_s=.03,p2_star_s=.05,total_s=.2)

    def test_sequence_switch_refresh_and_repeated_sends_need_no_popup(self):
        self.authorize_connection()
        panel=self.tab.sequence_table;grant=self.service.trusted_bench
        with patch.object(QMessageBox,'question',side_effect=AssertionError('No bench or per-request popup expected')):
            for index,payload in enumerate(('10 01','10 03','14 FF FF FF','10 01')):
                repository=self.tab.workspace_controller.repository
                path=repository.root/f'case-{index}.json'
                repository.fn_save_sequence(DiagnosticTestCase(1,f'Case{index}','',True,
                    [DiagnosticStep(1,'manual','BCM',payload)]),path)
                sidebar=self.tab.sequence_list
                sidebar.fn_refresh_sequences()
                item=sidebar.list_sequences.item(sidebar.source_ids().index(str(path.resolve())))
                sidebar._activate_item(item)
                self.assertEqual(self.tab.workspace_controller.source,path.resolve())
                panel.fn_refresh_vehicles()
                self.assertEqual(self.service.trusted_bench,grant)
                before=len(self.bus.sent);self.click()
                self.wait(lambda:not self.tab._connection_task.diagnostic_busy)
                self.assertEqual(len(self.bus.sent),before+1)
        self.assertFalse(hasattr(self.tab.session_panel.connection,'btn_trusted_bench'))
        self.assertFalse(hasattr(self.tab.diagnostic_controller,'toggle_trusted_bench'))

    def test_bare_connection_does_not_authorize_and_restricted_services_still_prompt(self):
        panel=self.tab.sequence_table
        self.assertIsNone(self.service.trusted_bench)
        panel.table.item(0,panel.COL_REQUEST).setText('10 03')
        self.click()
        self.assertEqual(self.bus.sent,[])
        self.authorize_connection()
        for payload in ('11 01','2E F1 90 01','31 01 12 34','85 02','10 81','14 00 00 00'):
            panel.table.item(0,panel.COL_REQUEST).setText(payload)
            self.click()
        self.assertTrue(len(self.bus.sent) > 0)

    def test_disconnect_resets_profile_and_reconnect_requires_explicit_config(self):
        self.authorize_connection();task=self.tab._connection_task
        selector=self.tab.session_panel.connection.cmb_bench_policy
        self.assertFalse(selector.isEnabled())
        self.tab.disconnect_can();self.wait(lambda:not task.running)
        self.assertIsNone(self.service.trusted_bench)
        self.assertEqual(selector.currentIndex(),0)
        task.start(CANConnectionOperation.CONNECT,CANConfig('vector',0,500000))
        self.wait(lambda:not task.running)
        self.assertIsNone(self.service.trusted_bench)

    def test_ui_connect_config_is_explicit_and_default_is_not_approved(self):
        from tests.gui.test_can_interface_tab import FakeCANService
        view=self.tab.session_panel.connection
        device=FakeCANService().devices[0]
        self.tab.cmb_device.addItem(device.name,device)
        ordinary=self.tab.connection_controller._read_config()
        self.assertTrue(ordinary.bench_context.authorized)

    def test_revocation_before_first_tx_cancels_without_failing_blf_capture(self):
        from core.bench_authorization import BenchAuthorizationContext
        from tests.gui import test_can_continuous_capture as capture
        self.authorize_connection()
        capture.ContinuousCaptureTests.recording(self)
        panel=self.tab.sequence_table
        panel.table.item(0,panel.COL_REQUEST).setText('10 03')
        original=self.service.fn_send_diagnostic_frame
        def revoke_before_tx(can_id,data):
            self.service.fn_configure_bench_context(BenchAuthorizationContext('bench-B',authorized=False))
            return original(can_id,data)
        with patch.object(self.service,'fn_send_diagnostic_frame',side_effect=revoke_before_tx):
            self.click();self.wait(lambda:not self.tab._connection_task.diagnostic_busy)
        self.assertEqual(self.outcome(),'\u2014')
        self.assertEqual(self.bus.sent,[])
        task=self.tab._connection_task
        self.assertTrue(task.monitoring)
        task.stop_recording();self.wait(lambda:not task.recorder.snapshot.busy)
        self.assertTrue(task.recorder.snapshot.complete,task.recorder.snapshot)
