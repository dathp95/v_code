import unittest
from dataclasses import replace
from types import SimpleNamespace

from core.diagnostic_request import DiagnosticResult, DiagnosticOutcome as Outcome
from tests.services.test_security_seed_request import seed_request
from tests.services import test_security_access82 as owner_fixtures


class AutoSecurityCoordinatorTests(unittest.TestCase):
    def flow(self):
        from services.can.auto_security_access import AutoSecurityAccessL1
        return AutoSecurityAccessL1(replace(seed_request(), expected=b'\x67\x02'))

    def test_matches_depends_on_seed_payload_only_not_expected(self):
        from services.can.auto_security_access import AutoSecurityAccessL1
        for expected in (b'', b'\x67\x01', b'\x67\x02', b'\x50\x03'):
            self.assertTrue(AutoSecurityAccessL1.matches(replace(seed_request(), expected=expected)))
        flow = AutoSecurityAccessL1(replace(seed_request(), expected=b''))
        self.assertEqual(flow.expected_unlock, b'\x67\x02')
        for payload in (b'\x27\x02', b'\x27\x01\x00', b'\x22\xf1\x90', b'\x27\x09'):
            self.assertFalse(AutoSecurityAccessL1.matches(SimpleNamespace(uds_payload=payload)))

    def test_seed_subrequest_has_its_own_identity_and_expectation(self):
        flow = self.flow()
        self.assertNotEqual(flow.seed_request.transaction_id, flow.logical_request.transaction_id)
        self.assertEqual(flow.seed_request.expected, b'\x67\x01')
        self.assertEqual(flow.logical_request.expected, b'\x67\x02')
        result = DiagnosticResult(flow.seed_request, Outcome.PASSED, b'\x67\x01'+bytes(range(16)))
        self.assertTrue(flow.accept_seed(result))
        self.assertIsNone(flow.result)
        self.assertFalse(flow.accept_seed(result))  # Duplicate callback cannot advance twice.
        self.assertNotIn('00 01 02', repr(flow.trace))

    def test_zero_seed_is_not_a_fabricated_key_acknowledgement(self):
        flow = self.flow()
        self.assertFalse(flow.accept_seed(DiagnosticResult(flow.seed_request, Outcome.PASSED, b'\x67\x01'+bytes(16))))
        self.assertEqual(flow.result.outcome, Outcome.NOT_EVALUATED)
        self.assertEqual(flow.result.response, b'\x67\x01')
        self.assertIn('Already unlocked', flow.result.detail)

    def test_wrong_seed_lengths_echoes_and_failures_never_advance(self):
        for payload in (b'\x67\x01', b'\x67\x03'+bytes(16), b'\x67\x01'+bytes(15), b'\x67\x01'+bytes(17)):
            flow = self.flow()
            self.assertFalse(flow.accept_seed(DiagnosticResult(flow.seed_request, Outcome.PASSED, payload)))
            self.assertEqual(flow.result.outcome, Outcome.ERROR)
        flow = self.flow()
        flow.accept_seed(DiagnosticResult(flow.seed_request, Outcome.FAILED, b'\x7f\x27\x35', nrc=0x35))
        self.assertEqual(flow.result.outcome, Outcome.FAILED)
        self.assertEqual(flow.result.response, b'\x7f\x27\x35')

    def test_key_positive_requires_both_exact_ack_and_current_submission(self):
        from core.security_submission import SubmissionAuthority
        from services.can.hmac_sha1_provider import ProviderVerificationGate
        from threading import Event
        for payload, accepted in ((b'\x67\x02\x00', True), (b'\x67\x02', False), (b'\x67\x02', True)):
            flow = self.flow()
            flow.accept_seed(DiagnosticResult(flow.seed_request, Outcome.PASSED, b'\x67\x01'+bytes(range(16))))
            gate = ProviderVerificationGate(simulator=True)
            material = gate.provider('BENCH', 'BCM').calculate(bytes(range(16)), source_transaction=flow.seed_request.transaction_id)
            authority = SubmissionAuthority(gate.validate, clock=lambda: 1.)
            key = authority.issue(flow.seed_request, material, connection_id='c', epoch=1,
                                  authorization_id='a', deadline=2., cancel=Event())
            flow.key_ready(key)
            flow.accept_key(DiagnosticResult(key, Outcome.PASSED, payload), accepted=accepted)
            self.assertEqual(flow.result.outcome == Outcome.PASSED, payload == b'\x67\x02' and accepted)
            self.assertEqual(len(flow.trace), 2)


class AutoSecurityOwnerTests(unittest.TestCase):
    setUp = owner_fixtures.SecurityOwnerFlowTests.setUp
    transact = owner_fixtures.SecurityOwnerFlowTests.transact
    prepare = owner_fixtures.SecurityOwnerFlowTests.prepare

    def logical(self):
        return replace(seed_request(settings=self.settings), expected=b'\x67\x02')

    def test_preflight_reservation_and_no_interleaved_request(self):
        with self.assertRaises(ValueError): self.service.begin_auto_security(self.logical())
        self.assertEqual(self.backend.requests, [])
        self.prepare()
        flow = self.service.begin_auto_security(self.logical())
        with self.assertRaises(ValueError): self.service.fn_begin_diagnostic(seed_request())
        self.assertTrue(self.service.is_auto_request(flow.seed_request))
        self.service.end_auto_security(flow)
        self.assertFalse(self.service.is_auto_request(flow.seed_request))

    def test_physical_backend_rejects_even_with_simulator_provider(self):
        self.prepare()
        original = self.service._backend
        class PhysicalProxy:
            def fn_is_connected(self): return True
            capture_session_id = original.capture_session_id
        self.service._backend = PhysicalProxy()
        try:
            with self.assertRaises(ValueError): self.service.begin_auto_security(self.logical())
        finally:
            self.service._backend = original

    def test_provider_changed_before_seed_owner_admission_is_rejected(self):
        from services.can.hmac_sha1_provider import ProviderVerificationGate
        self.prepare()
        flow = self.service.begin_auto_security(self.logical())
        self.service.security_gate = ProviderVerificationGate(simulator=True)
        with self.assertRaises(ValueError): self.service.fn_begin_diagnostic(flow.seed_request)
        self.service.end_auto_security(flow)

    def test_cleanup_releases_owner_even_after_workflow_authority_expires(self):
        self.prepare()
        flow = self.service.begin_auto_security(self.logical())
        self.service.fn_begin_diagnostic(flow.seed_request)
        flow.deadline = 0
        self.service.fn_end_diagnostic(flow.seed_request.transaction_id)
        self.assertIsNone(self.service._diagnostic_request)
        self.assertFalse(self.service._operation_lock.locked())
        self.service.end_auto_security(flow)


if __name__ == '__main__':
    unittest.main()
