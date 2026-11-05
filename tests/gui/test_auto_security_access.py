import unittest
from unittest.mock import patch
from threading import get_ident
import time
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox
from core.diagnostic_request import DiagnosticOutcome as Outcome, DiagnosticSettings
from tests.gui import test_security_access82 as fixtures

class AutoSecurityGuiTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.SecurityAccess82GuiTests.setUpClass.__func__)
    def setUp(self):
        fixtures.SecurityAccess82GuiTests.setUp(self)
        self.tab.diagnostic_controller.settings = DiagnosticSettings(p2_s=.15, p2_star_s=.3, total_s=.7)
    wait = fixtures.SecurityAccess82GuiTests.wait
    outcome = fixtures.SecurityAccess82GuiTests.outcome

    def extended(self):
        self.panel.table.selectRow(0)
        self.panel.table.cellWidget(0, self.panel.COL_SEND).click()
        self.wait(lambda: self.outcome(0) == 'Passed')

    def auto(self):
        self.panel.table.item(1, self.panel.COL_EXPECTED).setText('67 02')
        self.panel.table.selectRow(1)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.No) as question:
            self.panel.table.cellWidget(1, self.panel.COL_SEND).click()
            self.wait(lambda: self.outcome(1) not in ('Running', '—'))
            question.assert_not_called()

    def test_one_click_two_transactions_final_row_pass_and_safe_comment(self):
        self.extended()
        self.auto()
        self.assertEqual(self.outcome(1), 'Passed')
        self.assertEqual(self.panel.table.item(1, self.panel.COL_RECEIVE).text(), '67 02')
        self.assertEqual(self.panel.table.item(1, self.panel.COL_COMMENT).text(), '')
        self.assertIn('Security Unlocked', self.panel.table.item(1, self.panel.COL_RESULT).toolTip())
        flow = self.tab.diagnostic_controller.auto_security.last_flow
        self.assertEqual(len(flow.trace), 2)
        self.assertNotEqual(flow.trace[0].transaction_id, flow.trace[1].transaction_id)
        self.assertEqual([p[:2] for p in self.backend.requests], [b'\x10\x03', b'\x27\x01', b'\x27\x02'])
        self.assertEqual(self.panel.sequence_for_save().steps[1].comment, '')
        self.assertEqual(len(set(self.backend.threads)), 1)
        self.assertNotEqual(self.backend.threads[0], get_ident())

    def autosec_log(self):
        with self.assertLogs('vcode.autosec', level='DEBUG') as captured:
            self.extended()
            self.auto()
        return chr(10).join(captured.output)

    def test_trace_logs_each_phase_without_seed_or_key_bytes(self):
        text = self.autosec_log()
        for event in ('AUTO start', 'AUTO seed result', 'AUTO key calculated',
                      'AUTO key sent', 'AUTO key result', 'finished | outcome=Passed'):
            self.assertIn(event, text)
        self.assertIn('seed_len=16', text)
        self.assertIn('since_seed=', text)
        self.assertNotIn('00 01 02 03', text)
        self.assertNotIn('000102', text)

    def test_trace_names_the_nrc_when_key_is_rejected(self):
        self.backend.key_response = bytes((0x7f, 0x27, 0x35))
        text = self.autosec_log()
        self.assertIn('nrc=0x35 invalidKey', text)
        self.assertIn('AUTO key result', text)

    def test_trace_logs_reason_when_workflow_aborts(self):
        self.backend.seed = bytes(16)
        text = self.autosec_log()
        self.assertIn('zero_seed=True', text)

    def test_preflight_no_extended_or_provider_sends_nothing(self):
        self.auto()
        self.assertEqual(self.outcome(1), 'Failed')
        self.assertEqual(self.backend.requests, [])

    def test_zero_seed_not_evaluated_never_fabricates_6702(self):
        self.extended(); self.backend.seed = bytes(16)
        self.auto()
        self.assertEqual(self.outcome(1), 'Passed')
        self.assertNotEqual(self.panel.table.item(1, self.panel.COL_RECEIVE).text(), '67 02')
        self.assertEqual(len(self.backend.requests), 2)

    def test_invalid_key_fails_without_retry(self):
        self.extended(); self.backend.key_response = b'\x7f\x27\x35'
        self.auto()
        self.assertEqual(self.outcome(1), 'Failed')
        self.assertEqual(self.panel.table.item(1, self.panel.COL_RECEIVE).text(), '7F 27 35')
        self.assertEqual(sum(p[:2] == b'\x27\x02' for p in self.backend.requests), 1)

    def test_all_terminal_key_nrcs_are_final_no_retry(self):
        self.extended()
        for nrc in (0x24, 0x33, 0x35, 0x36, 0x37):
            with self.subTest(nrc=nrc):
                self.backend.key_response = bytes((0x7f, 0x27, nrc))
                before = len(self.backend.requests)
                self.auto()
                self.assertEqual(self.outcome(1), 'Failed')
                self.assertEqual(len(self.backend.requests)-before, 2)
                self.assertIn(f'{nrc:02X}', self.panel.table.item(1, self.panel.COL_RECEIVE).text())

    def test_pending_positive_and_pending_timeout_do_not_duplicate_tx(self):
        self.extended(); self.backend.pending_delay = .08
        self.auto(); self.assertEqual(self.outcome(1), 'Passed')
        self.backend.pending_delay = 0
        self.backend.key_response = b'\x7f\x27\x78'
        self.auto(); self.assertEqual(self.outcome(1), 'Timeout')
        self.assertEqual(sum(p[:2] == b'\x27\x02' for p in self.backend.requests), 2)

    def test_malformed_key_positive_and_wrong_rx_never_pass(self):
        self.extended(); self.backend.key_response = b'\x67\x02\x00'
        self.auto(); self.assertEqual(self.outcome(1), 'Timeout')
        self.backend.response_can_id = 0x602
        self.auto(); self.assertEqual(self.outcome(1), 'Timeout')

    def test_seed_bad_length_or_terminal_nrc_never_sends_key(self):
        self.extended(); self.backend.seed = bytes(range(15))
        self.auto(); self.assertEqual(self.outcome(1), 'Failed')
        original = self.backend._response
        def response(payload):
            original(b'\x7f\x27\x36' if payload and payload[:2] == b'\x67\x01' else payload)
        self.backend._response = response
        self.auto(); self.assertEqual(self.outcome(1), 'Failed')
        self.assertFalse(any(p[:2] == b'\x27\x02' for p in self.backend.requests))

    def test_missing_provider_and_revoked_bench_block_before_seed(self):
        from services.can.hmac_sha1_provider import ProviderVerificationGate
        self.extended(); self.service.security_gate = ProviderVerificationGate()
        self.auto(); self.assertEqual(self.outcome(1), 'Failed')
        self.service.security_gate = ProviderVerificationGate(simulator=True)
        self.service.fn_revoke_trusted_bench()
        self.auto(); self.assertEqual(self.outcome(1), 'Failed')
        self.assertEqual(len(self.backend.requests), 1)

    def test_double_click_and_other_row_cannot_interleave_calculation(self):
        self.extended()
        provider = self.service.security_provider('BENCH', 'BCM'); original = provider.calculate
        threads = []
        def slow(*args, **kwargs):
            threads.append(get_ident()); time.sleep(.08)
            return original(*args, **kwargs)
        self.panel.table.item(1, self.panel.COL_EXPECTED).setText('67 02')
        self.panel.table.item(1, self.panel.COL_COMMENT).setText('Operator note')
        self.panel.table.selectRow(1)
        states, model_comments = [], []
        with patch.object(provider, 'calculate', side_effect=slow):
            button = self.panel.table.cellWidget(1, self.panel.COL_SEND)
            button.click(); button.click()
            QTimer.singleShot(15, lambda: states.append(self.outcome(1)))
            QTimer.singleShot(15, lambda: model_comments.append(self.panel.sequence_for_save().steps[1].comment))
            QTimer.singleShot(15, lambda: self.tab.diagnostic_controller.send_row(self.panel.step_ids[0]))
            self.wait(lambda: self.outcome(1) == 'Passed')
        self.assertEqual(len(self.backend.requests), 3)
        self.assertNotEqual(threads, [get_ident()])
        self.assertEqual(states, ['\u2014'])
        self.assertEqual(model_comments, ['Operator note'])
        repository = self.tab.workspace_controller.repository
        path = repository.root / 'auto-save.json'
        repository.fn_save_sequence(self.panel.sequence_for_save(), path)
        saved = repository.fn_load_sequence(path)
        self.assertEqual(saved.steps[1].comment, 'Operator note')
        self.assertEqual((saved.steps[1].request, saved.steps[1].expected_response), ('27 01', '67 02'))

    def test_unseen_seed_consecutive_frame_after_cancel_stays_private(self):
        self.extended(); captured = []
        self.tab._connection_task._worker.session.capture_sink = captured.append
        original = self.backend._response
        def first_frame_only(payload):
            original(payload)
            if payload and payload[:2] == b'\x67\x01':
                self.backend._outgoing = b''
        self.backend._response = first_frame_only
        self.panel.table.item(1, self.panel.COL_EXPECTED).setText('67 02')
        self.panel.table.selectRow(1)
        self.panel.table.cellWidget(1, self.panel.COL_SEND).click()
        self.wait(lambda: any(f.direction == 'TX' and f.data[:1] == b'\x30' for f in self.backend.frames))
        self.tab.diagnostic_controller.auto_security.cancel()
        self.wait(lambda: not self.tab._connection_task.diagnostic_busy)
        self.backend._enqueue(b'\x21'+b'\xaa'*7)
        self.wait(lambda: not self.backend._rx)
        self.assertTrue(any(f.data[:1] == b'\x21' for f in captured))

    def test_edit_cancels_late_calculation_without_key(self):
        self.extended()
        provider = self.service.security_provider('BENCH', 'BCM'); original = provider.calculate
        def slow(*args, **kwargs):
            time.sleep(.08); return original(*args, **kwargs)
        self.panel.table.item(1, self.panel.COL_EXPECTED).setText('67 02')
        self.panel.table.selectRow(1)
        with patch.object(provider, 'calculate', side_effect=slow):
            self.panel.table.cellWidget(1, self.panel.COL_SEND).click()
            QTimer.singleShot(20, lambda: self.panel.table.item(0, self.panel.COL_COMMENT).setText('Edited'))
            self.wait(lambda: not self.tab.diagnostic_controller.auto_security.busy)
        self.assertEqual(self.tab.diagnostic_controller.auto_security.last_flow.result.outcome, Outcome.CANCELLED)
        self.assertFalse(any(p[:2] == b'\x27\x02' for p in self.backend.requests))

    def test_provider_exception_never_leaks_and_owner_reservation_releases(self):
        self.extended()
        provider = self.service.security_provider('BENCH', 'BCM')
        with patch.object(provider, 'calculate', side_effect=TimeoutError('PRIVATE_SECRET')):
            self.auto(); self.assertEqual(self.outcome(1), 'Failed')
        self.assertNotIn('PRIVATE_SECRET', self.panel.notice.text())
        self.assertIsNone(self.service._auto_context)
        self.auto(); self.assertEqual(self.outcome(1), 'Passed')

    def test_provider_change_during_calculation_prevents_key(self):
        from services.can.hmac_sha1_provider import ProviderVerificationGate
        self.extended()
        provider = self.service.security_provider('BENCH', 'BCM'); original = provider.calculate
        def slow(*args, **kwargs):
            time.sleep(.08); return original(*args, **kwargs)
        self.panel.table.item(1, self.panel.COL_EXPECTED).setText('67 02')
        self.panel.table.selectRow(1)
        with patch.object(provider, 'calculate', side_effect=slow):
            self.panel.table.cellWidget(1, self.panel.COL_SEND).click()
            QTimer.singleShot(15, lambda: setattr(self.service, 'security_gate', ProviderVerificationGate(simulator=True)))
            self.wait(lambda: not self.tab.diagnostic_controller.auto_security.busy)
        self.assertEqual(self.outcome(1), 'Failed')
        self.assertEqual(len(self.backend.requests), 2)

    def test_disconnect_during_calculation_cancels_without_key(self):
        self.extended()
        provider = self.service.security_provider('BENCH', 'BCM'); original = provider.calculate
        def slow(*args, **kwargs):
            time.sleep(.08); return original(*args, **kwargs)
        self.panel.table.item(1, self.panel.COL_EXPECTED).setText('67 02')
        self.panel.table.selectRow(1)
        with patch.object(provider, 'calculate', side_effect=slow):
            self.panel.table.cellWidget(1, self.panel.COL_SEND).click()
            QTimer.singleShot(20, self.tab.disconnect_can)
            self.wait(lambda: not self.tab.diagnostic_controller.auto_security.busy)
        self.assertNotEqual(self.outcome(1), 'Passed')
        self.assertFalse(any(p[:2] == b'\x27\x02' for p in self.backend.requests))

    def test_workflow_deadline_cancels_late_provider_and_releases_transport(self):
        self.extended()
        provider = self.service.security_provider('BENCH', 'BCM'); original = provider.calculate
        def slow(*args, **kwargs):
            time.sleep(.08); return original(*args, **kwargs)
        self.panel.table.item(1, self.panel.COL_EXPECTED).setText('67 02')
        self.panel.table.selectRow(1)
        def expire():
            adapter = self.tab.diagnostic_controller.auto_security
            if adapter.flow is not None:
                adapter.flow.deadline = 0
                adapter.check_timeout()
        with patch.object(provider, 'calculate', side_effect=slow):
            self.panel.table.cellWidget(1, self.panel.COL_SEND).click()
            QTimer.singleShot(20, expire)
            self.wait(lambda: not self.tab.diagnostic_controller.auto_security.busy)
        self.assertEqual(self.outcome(1), 'Timeout')
        self.assertFalse(self.service._operation_lock.locked())
        self.assertEqual(len(self.backend.requests), 2)

    def test_rejected_key_dispatch_does_not_send_and_consumes_capability(self):
        self.extended()
        task = self.tab._connection_task; original = task.submit_diagnostic
        def submit(request):
            return False if request.uds_payload[:2] == b'\x27\x02' else original(request)
        with patch.object(task, 'submit_diagnostic', side_effect=submit):
            self.auto()
        self.assertEqual(self.outcome(1), 'Failed')
        self.assertEqual(len(self.backend.requests), 2)
        self.assertIsNone(self.service._auto_context)

    def test_changed_canonical_ids_during_calculation_never_send_key(self):
        self.extended()
        provider = self.service.security_provider('BENCH', 'BCM'); original = provider.calculate
        def slow(*args, **kwargs):
            time.sleep(.08); return original(*args, **kwargs)
        self.panel.table.item(1, self.panel.COL_EXPECTED).setText('67 02')
        self.panel.table.selectRow(1)
        with patch.object(provider, 'calculate', side_effect=slow):
            self.panel.table.cellWidget(1, self.panel.COL_SEND).click()
            QTimer.singleShot(20, lambda: setattr(self.panel._vehicle_service.load_vehicle('BENCH').ecus[0], 'request_id', '682'))
            self.wait(lambda: not self.tab.diagnostic_controller.auto_security.busy)
        self.assertNotEqual(self.outcome(1), 'Passed')
        self.assertEqual(len(self.backend.requests), 2)

    def test_seed_request_auto_unlocks_whatever_expected_says(self):
        self.extended()
        for expected in ('', '67 01', '67 03', '50 03'):
            with self.subTest(expected=expected):
                before = len(self.backend.requests)
                self.panel.table.item(1, self.panel.COL_EXPECTED).setText(expected)
                self.panel.table.selectRow(1)
                with patch.object(QMessageBox, 'question', return_value=QMessageBox.No) as question:
                    self.panel.table.cellWidget(1, self.panel.COL_SEND).click()
                    self.wait(lambda: self.outcome(1) not in ('Running', '—'))
                    question.assert_not_called()
                self.assertEqual(self.outcome(1), 'Passed')
                self.assertEqual(self.panel.table.item(1, self.panel.COL_RECEIVE).text(), '67 02')
                self.assertEqual([p[:2] for p in self.backend.requests[before:]], [b'\x27\x01', b'\x27\x02'])
                self.assertEqual(self.panel.sequence_for_save().steps[1].expected_response, expected)

    def test_sequence_run_unlocks_seed_rows_with_blank_expected(self):
        from core.diagnostic_sequence import DiagnosticStep, DiagnosticTestCase
        self.tab._on_sequence_selected(DiagnosticTestCase(1, 'seq', '', True, [
            DiagnosticStep(1, 'Session', 'BCM', '10 03', expected_response='50 03'),
            DiagnosticStep(2, '', 'BCM', '27 01'),
            DiagnosticStep(3, '', 'BCM', '27 03')]))
        self.panel.vehicle_selector.fn_set_vehicle('BENCH')
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.No) as question:
            self.panel.btn_run.click()
            self.wait(lambda: not self.tab.diagnostic_controller._sequence_running
                      and self.outcome(2) not in ('Running', '—'))
            question.assert_not_called()
        self.assertEqual([self.outcome(row) for row in range(3)], ['Passed', 'Passed', 'Passed'])
        self.assertEqual([self.panel.table.item(row, self.panel.COL_RECEIVE).text() for row in (1, 2)],
                         ['67 02', '67 04'])
        self.assertEqual([p[:2] for p in self.backend.requests],
                         [b'\x10\x03', b'\x27\x01', b'\x27\x02', b'\x27\x03', b'\x27\x04'])

    def test_generated_key_frames_reach_monitor_and_recording_sink(self):
        captured = []
        self.tab._connection_task._worker.session.capture_sink = captured.append
        self.extended()
        self.auto()
        self.assertEqual(self.outcome(1), 'Passed')
        self.wait(lambda: any(f.data[1:3] == b'g' for f in self.tab.monitor_panel._buffer))
        for frames in (captured, self.tab.monitor_panel._buffer):
            self.assertTrue(any(f.direction == 'TX' and f.data[0] >> 4 in (1, 2) for f in frames))

    def test_sequence_with_io_control_2f_rows_runs_and_passes(self):
        from core.diagnostic_sequence import DiagnosticStep, DiagnosticTestCase
        self.tab._on_sequence_selected(DiagnosticTestCase(1, 'IO', '', True, [
            DiagnosticStep(1, 'Session', 'BCM', '10 03', expected_response='50 03'),
            DiagnosticStep(2, 'Screen', 'BCM', '2F F0 AC 03 00', expected_response='6F F0 AC 03 00'),
            DiagnosticStep(3, '', 'BCM', '2F F0 AC 03 01', expected_response='6F F0 AC 03 01')]))
        self.panel.vehicle_selector.fn_set_vehicle('BENCH')
        self.panel.btn_run.click()
        self.wait(lambda: not self.tab.diagnostic_controller._sequence_running
                  and self.outcome(2) not in ('Running', '\u2014'))
        self.assertEqual([self.outcome(row) for row in range(3)], ['Passed', 'Passed', 'Passed'])
        self.assertEqual([self.panel.table.item(row, self.panel.COL_RECEIVE).text() for row in (1, 2)],
                         ['6F F0 AC 03 00', '6F F0 AC 03 01'])

    def io_sequence(self):
        from core.diagnostic_sequence import DiagnosticStep, DiagnosticTestCase
        self.tab._on_sequence_selected(DiagnosticTestCase(1, 'IO', '', True, [
            DiagnosticStep(1, 'Session', 'BCM', '10 03', expected_response='50 03'),
            DiagnosticStep(2, '', 'BCM', '2F F0 AC 03 00', expected_response='6F F0 AC 03 00'),
            DiagnosticStep(3, '', 'BCM', '2F F0 AC 03 01', expected_response='6F F0 AC 03 01')]))
        self.panel.vehicle_selector.fn_set_vehicle('BENCH')

    def test_run_executes_only_the_checked_rows(self):
        from PySide6.QtCore import Qt
        self.io_sequence()
        self.assertEqual(self.panel.checked_step_ids(), tuple(self.panel.step_ids))  # All rows by default.
        self.panel.table.item(1, self.panel.COL_CHECK).setCheckState(Qt.Unchecked)
        self.panel.btn_run.click()
        self.wait(lambda: not self.tab.diagnostic_controller._sequence_running
                  and self.outcome(2) not in ('Running', '\u2014'))
        self.assertEqual([self.outcome(row) for row in range(3)], ['Passed', '\u2014', 'Passed'])
        self.assertFalse(self.panel.fn_is_dirty())  # Running a sequence and receiving data never enables Save.
        self.assertEqual([p[:3] for p in self.backend.requests], [b'\x10\x03', b'\x2f\xf0\xac'])
        self.assertEqual(self.backend.requests[1], bytes.fromhex('2F F0 AC 03 01'))

    def test_run_with_nothing_checked_sends_nothing_and_says_why(self):
        from PySide6.QtCore import Qt
        self.io_sequence()
        for row in range(3):
            self.panel.table.item(row, self.panel.COL_CHECK).setCheckState(Qt.Unchecked)
        self.panel.btn_run.click()
        self.assertFalse(self.tab.diagnostic_controller._sequence_running)
        self.assertEqual(self.backend.requests, [])
        self.assertIn('Select at least one', self.panel.notice.text())

    def test_stale_6702_queued_before_workflow_cannot_prove_unlock(self):
        self.extended()
        self.backend._response(b'\x67\x02')
        self.backend.key_response = None
        self.auto()
        self.assertEqual(self.outcome(1), 'Timeout')

    def test_duplicate_result_and_raw_seed_key_never_reach_generic_capture(self):
        self.extended(); captured = []
        self.tab._connection_task._worker.session.capture_sink = captured.append
        self.auto()
        self.wait(lambda: any(f.data[1:3] == b'\x67\x02' for f in self.tab.monitor_panel._buffer))
        for frames in (captured, self.tab.monitor_panel._buffer):
            self.assertTrue(any(f.data[0] >> 4 in (1, 2) for f in frames))
        flow = self.tab.diagnostic_controller.auto_security.last_flow
        from core.diagnostic_request import DiagnosticResult
        self.tab.diagnostic_controller._result(DiagnosticResult(flow.seed_request, Outcome.PASSED, b'\x67\x01'+bytes(16)))
        self.assertEqual(self.outcome(1), 'Passed')
        self.assertEqual(len(self.backend.requests), 3)

class PhysicalAutoGateGuiTests(unittest.TestCase):
    from tests.gui import test_can_diagnostic_execution as fixtures
    setUpClass = classmethod(fixtures.CanDiagnosticExecutionTests.setUpClass.__func__)
    setUp = fixtures.CanDiagnosticExecutionTests.setUp
    wait = fixtures.CanDiagnosticExecutionTests.wait

    def test_mock_provider_cannot_auto_send_on_vector_adapter(self):
        from services.can.hmac_sha1_provider import ProviderVerificationGate
        self.service.security_gate = ProviderVerificationGate(simulator=True)
        self.assertIsNotNone(self.service.security_provider('BENCH', 'BCM'))
        panel = self.tab.sequence_table
        panel.table.item(0, panel.COL_REQUEST).setText('27 01')
        panel.table.item(0, panel.COL_EXPECTED).setText('67 02')
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.No) as question:
            panel.table.cellWidget(0, panel.COL_SEND).click()
            question.assert_not_called()
        self.assertEqual(self.bus.sent, [])
        self.assertEqual(panel.table.item(0, panel.COL_RESULT).text(), 'Failed')
        self.assertIn('Physical Auto L1 blocked', panel.notice.text())

