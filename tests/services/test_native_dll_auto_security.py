import time
import unittest
from dataclasses import replace

from core.bench_authorization import BenchAuthorizationContext
from core.diagnostic_request import (
    DiagnosticRequest,
    DiagnosticResult,
    DiagnosticValidationError,
    DiagnosticSettings,
    DiagnosticOutcome,
)
from services.can import CANService, CANConfig
from services.can.simulated_backend import SimulatedCANBackend
from services.can.diagnostic_client import DiagnosticClient
from services.can.security_access_session import SecurityAccessState


class NativeDllAutoSecurityTests(unittest.TestCase):
    def setUp(self):
        self.backend = SimulatedCANBackend()
        self.service = CANService(self.backend)
        self.service.fn_connect(
            CANConfig('vector', 0, 500000, bench_context=BenchAuthorizationContext('sim-bench', True))
        )
        self.addCleanup(self.service.fn_disconnect)
        self.settings = DiagnosticSettings(p2_s=1.0, p2_star_s=2.0, total_s=5.0)

    def transact(self, request):
        self.service.fn_begin_diagnostic(request)
        try:
            client = DiagnosticClient(request, self.service.fn_send_diagnostic_frame)
            while client.result is None:
                client.poll()
                frame = self.service.fn_receive_diagnostic_frame()
                if frame is not None:
                    client.feed(frame)
                time.sleep(0.001)
            self.service.fn_diagnostic_completed(client.result)
            return client.result
        finally:
            self.service.fn_end_diagnostic(request.transaction_id)

    def test_auto_security_l1_end_to_end_with_bcm_dll(self):
        # 1. Extended session 10 03 -> 50 03
        ext_req = DiagnosticRequest(
            transaction_id='tx_ext',
            step_id='step_1',
            generation=1,
            vehicle_name='VF5NP',
            ecu_name='BCM',
            tx_id=0x681,
            rx_id=0x601,
            uds_payload=b'\x10\x03',
            expected=b'\x50\x03',
            settings=self.settings,
            confirmed=True,
        )
        ext_res = self.transact(ext_req)
        self.assertEqual(ext_res.outcome, DiagnosticOutcome.PASSED)

        # Vector 0 offline seed & expected key for BCM subfunction 1
        seed_bytes = bytes.fromhex('adbeb3dd50ef2e87052cdce050f651b2')
        expected_key = bytes.fromhex('c141495385515aa08a006885b67815ac')
        self.backend.seed = seed_bytes
        self.backend.expected_key = expected_key

        # 2. Logical request 27 01 -> expected 67 02
        logical_req = DiagnosticRequest(
            transaction_id='tx_l1',
            step_id='step_2',
            generation=1,
            vehicle_name='VF5NP',
            ecu_name='BCM',
            tx_id=0x681,
            rx_id=0x601,
            uds_payload=b'\x27\x01',
            expected=b'\x67\x02',
            settings=self.settings,
            confirmed=True,
        )

        flow = self.service.begin_auto_security(logical_req)
        self.assertEqual(flow.subfunction, 1)
        self.assertEqual(flow.key_subfunction, 2)
        self.assertEqual(flow.expected_unlock, b'\x67\x02')

        # Transact seed request
        seed_res = self.transact(flow.seed_request)
        advance = flow.accept_seed(seed_res)
        self.assertTrue(advance)
        self.assertEqual(flow.phase, 'Seed received')

        # Calculate key with real DLL provider
        provider, gate = self.service.auto_provider(flow)
        flow.calculating()
        key_material = provider.calculate(seed_bytes, source_transaction=flow.seed_request.transaction_id)
        self.assertEqual(key_material.key, expected_key)
        self.assertTrue(key_material.verified_real)

        # Prepare key submission
        from services.can.security_access_session import SecurityAccessSession
        session = SecurityAccessSession()
        session.start(flow.seed_request, self.service.capture_session_id, 1)
        session.receive(seed_res, self.service.capture_session_id, 1)
        session.calculate_verified(provider, gate)
        key_req = self.service.prepare_auto_submission(flow, session, 1)
        flow.key_ready(key_req)

        # Transact key request
        key_res = self.transact(key_req)
        accepted = session.finish_submission(key_res)
        self.assertTrue(accepted)
        success = flow.accept_key(key_res, accepted=accepted)
        self.assertTrue(success)
        self.assertEqual(flow.result.outcome, DiagnosticOutcome.PASSED)
        self.assertEqual(flow.result.response, b'\x67\x02')
        self.assertEqual(session.state, SecurityAccessState.UNLOCKED)
        self.service.end_auto_security(flow)

    def test_auto_security_l2_end_to_end_with_bcm_dll(self):
        # 1. Extended session 10 03 -> 50 03
        ext_req = DiagnosticRequest(
            transaction_id='tx_ext2',
            step_id='step_1',
            generation=1,
            vehicle_name='VF5NP',
            ecu_name='BCM',
            tx_id=0x681,
            rx_id=0x601,
            uds_payload=b'\x10\x03',
            expected=b'\x50\x03',
            settings=self.settings,
            confirmed=True,
        )
        ext_res = self.transact(ext_req)
        self.assertEqual(ext_res.outcome, DiagnosticOutcome.PASSED)

        # Vector offline seed & expected key for BCM subfunction 3 (Level 2)
        seed_bytes = bytes.fromhex('0d84466fdfd1a53c4c3f6f606661c113')
        expected_key = bytes.fromhex('4a04f887df23553b9e2a53a6d74e43a5')
        self.backend.seed = seed_bytes
        self.backend.expected_key = expected_key

        # 2. Logical request 27 03 -> expected 67 04
        logical_req = DiagnosticRequest(
            transaction_id='tx_l2',
            step_id='step_3',
            generation=1,
            vehicle_name='VF5NP',
            ecu_name='BCM',
            tx_id=0x681,
            rx_id=0x601,
            uds_payload=b'\x27\x03',
            expected=b'\x67\x04',
            settings=self.settings,
            confirmed=True,
        )

        flow = self.service.begin_auto_security(logical_req)
        self.assertEqual(flow.subfunction, 3)
        self.assertEqual(flow.key_subfunction, 4)
        self.assertEqual(flow.expected_unlock, b'\x67\x04')

        # Transact seed request
        seed_res = self.transact(flow.seed_request)
        advance = flow.accept_seed(seed_res)
        self.assertTrue(advance)
        self.assertEqual(flow.phase, 'Seed received')

        # Calculate key with real DLL provider (subfunction=3)
        provider, gate = self.service.auto_provider(flow)
        flow.calculating()
        key_material = provider.calculate(seed_bytes, source_transaction=flow.seed_request.transaction_id)
        self.assertEqual(key_material.key, expected_key)
        self.assertTrue(key_material.verified_real)

        # Prepare key submission 27 04
        from services.can.security_access_session import SecurityAccessSession
        session = SecurityAccessSession()
        session.start(flow.seed_request, self.service.capture_session_id, 1)
        session.receive(seed_res, self.service.capture_session_id, 1)
        session.calculate_verified(provider, gate)
        key_req = self.service.prepare_auto_submission(flow, session, 1)
        self.assertEqual(key_req.uds_payload[:2], b'\x27\x04')
        self.assertEqual(key_req.expected, b'\x67\x04')
        flow.key_ready(key_req)

        # Transact key request
        key_res = self.transact(key_req)
        accepted = session.finish_submission(key_res)
        self.assertTrue(accepted)
        success = flow.accept_key(key_res, accepted=accepted)
        self.assertTrue(success)
        self.assertEqual(flow.result.outcome, DiagnosticOutcome.PASSED)
        self.assertEqual(flow.result.response, b'\x67\x04')
        self.assertEqual(session.state, SecurityAccessState.UNLOCKED)
        self.service.end_auto_security(flow)

    def test_physical_backend_permitted_when_real_dll_present(self):
        # Set up extended session
        ext_req = DiagnosticRequest(
            transaction_id='tx_ext_phys',
            step_id='step_1',
            generation=1,
            vehicle_name='VF5NP',
            ecu_name='BCM',
            tx_id=0x681,
            rx_id=0x601,
            uds_payload=b'\x10\x03',
            expected=b'\x50\x03',
            settings=self.settings,
            confirmed=True,
        )
        self.transact(ext_req)

        # Mock a physical backend (non-simulator)
        original_backend = self.service._backend
        class PhysicalBackendStub:
            def fn_is_connected(self): return True
            capture_session_id = original_backend.capture_session_id

        self.service._backend = PhysicalBackendStub()
        try:
            logical_req = DiagnosticRequest(
                transaction_id='tx_phys',
                step_id='step_2',
                generation=1,
                vehicle_name='VF5NP',
                ecu_name='BCM',
                tx_id=0x681,
                rx_id=0x601,
                uds_payload=b'\x27\x01',
                expected=b'\x67\x02',
                settings=self.settings,
                confirmed=True,
            )
            # Must succeed and not raise 'Physical Auto L1 blocked' because BCM has real DLL
            flow = self.service.begin_auto_security(logical_req)
            self.assertIsNotNone(flow)
            self.service.end_auto_security(flow)
        finally:
            self.service._backend = original_backend
    def test_auto_security_generic_ecu_and_subfunction_5(self):
        # Test BMS ECU with subfunction 5 (Level 3)
        provider = self.service.security_provider('VF5NP', 'BMS', subfunction=5)
        self.assertIsNotNone(provider)
        self.assertTrue(getattr(provider._proof, 'verified_real', False))
        seed_bytes = bytes.fromhex('0102030405060708090a0b0c0d0e0f10')
        key_material = provider.calculate(seed_bytes, source_transaction='tx_bms_calc')
        self.assertEqual(len(key_material.key), 16)
        self.assertTrue(key_material.verified_real)

        # Test EPS ECU with subfunction 1 (Level 1)
        eps_provider = self.service.security_provider('VF5NP', 'EPS', subfunction=1)
        self.assertIsNotNone(eps_provider)
        self.assertTrue(getattr(eps_provider._proof, 'verified_real', False))
        eps_key = eps_provider.calculate(seed_bytes, source_transaction='tx_eps_calc')
        self.assertEqual(len(eps_key.key), 16)
        self.assertTrue(eps_key.verified_real)

        # Test MHU ECU with subfunction 1 and subfunction 3
        mhu_provider_1 = self.service.security_provider('VF5NP', 'MHU', subfunction=1)
        self.assertIsNotNone(mhu_provider_1)
        self.assertTrue(getattr(mhu_provider_1._proof, 'verified_real', False))
        mhu_key_1 = mhu_provider_1.calculate(seed_bytes, source_transaction='tx_mhu_calc1')
        self.assertEqual(len(mhu_key_1.key), 16)
        self.assertTrue(mhu_key_1.verified_real)

        mhu_provider_3 = self.service.security_provider('VF5NP', 'MHU', subfunction=3)
        self.assertIsNotNone(mhu_provider_3)
        self.assertTrue(getattr(mhu_provider_3._proof, 'verified_real', False))
        mhu_key_3 = mhu_provider_3.calculate(seed_bytes, source_transaction='tx_mhu_calc3')
        self.assertEqual(len(mhu_key_3.key), 16)
        self.assertTrue(mhu_key_3.verified_real)

        # Provider cache distinction: subfunction 1 provider is NOT reused for subfunction 3
        self.assertNotEqual(mhu_provider_1._subfunction, mhu_provider_3._subfunction)
        self.assertNotEqual(mhu_provider_1._proof.fingerprint, mhu_provider_3._proof.fingerprint)

    def test_auto_security_all_four_levels_activation_rules(self):
        from services.can.auto_security_access import AutoSecurityAccessL1

        # Level 1: 27 01 -> always auto (expected is ignored); unlock response 67 02
        req_l1 = DiagnosticRequest('t', 's', 1, 'VF5NP', 'BCM', 0x681, 0x601, b'\x27\x01', b'\x67\x02', settings=self.settings)
        self.assertTrue(AutoSecurityAccessL1.matches(req_l1))
        self.assertTrue(AutoSecurityAccessL1.matches(replace(req_l1, expected=b'\x67\x01')))
        self.assertTrue(AutoSecurityAccessL1.matches(replace(req_l1, expected=b'')))

        # Level 2: 27 03 -> always auto (expected is ignored); unlock response 67 04
        req_l2 = DiagnosticRequest('t', 's', 1, 'VF5NP', 'BCM', 0x681, 0x601, b'\x27\x03', b'\x67\x04', settings=self.settings)
        self.assertTrue(AutoSecurityAccessL1.matches(req_l2))
        self.assertTrue(AutoSecurityAccessL1.matches(replace(req_l2, expected=b'\x67\x03')))
        self.assertTrue(AutoSecurityAccessL1.matches(replace(req_l2, expected=b'')))

        # Level 3: 27 05 -> always auto (expected is ignored); unlock response 67 06
        req_l3 = DiagnosticRequest('t', 's', 1, 'VF5NP', 'BCM', 0x681, 0x601, b'\x27\x05', b'\x67\x06', settings=self.settings)
        self.assertTrue(AutoSecurityAccessL1.matches(req_l3))
        self.assertTrue(AutoSecurityAccessL1.matches(replace(req_l3, expected=b'\x67\x05')))
        self.assertTrue(AutoSecurityAccessL1.matches(replace(req_l3, expected=b'')))

        # Level 4: 27 07 -> always auto (expected is ignored); unlock response 67 08
        req_l4 = DiagnosticRequest('t', 's', 1, 'VF5NP', 'BCM', 0x681, 0x601, b'\x27\x07', b'\x67\x08', settings=self.settings)
        self.assertTrue(AutoSecurityAccessL1.matches(req_l4))
        self.assertTrue(AutoSecurityAccessL1.matches(replace(req_l4, expected=b'\x67\x07')))
        self.assertTrue(AutoSecurityAccessL1.matches(replace(req_l4, expected=b'')))

        # Unsupported subfunction 0x09: blocked by diagnostic request policy
        with self.assertRaises(DiagnosticValidationError):
            DiagnosticRequest('t', 's', 1, 'VF5NP', 'BCM', 0x681, 0x601, b'\x27\x09', b'\x67\x0A', settings=self.settings)

    def test_auto_security_l3_end_to_end_flow(self):
        # 1. Extended session 10 03 -> 50 03
        ext_req = DiagnosticRequest('tx_ext3', 'step_1', 1, 'VF5NP', 'BCM', 0x681, 0x601, b'\x10\x03', b'\x50\x03', settings=self.settings, confirmed=True)
        self.assertEqual(self.transact(ext_req).outcome, DiagnosticOutcome.PASSED)

        seed_bytes = bytes.fromhex('0102030405060708090a0b0c0d0e0f10')
        self.backend.seed = seed_bytes

        # Logical request 27 05 -> expected 67 06
        logical_req = DiagnosticRequest('tx_l3', 'step_5', 1, 'VF5NP', 'BCM', 0x681, 0x601, b'\x27\x05', b'\x67\x06', settings=self.settings, confirmed=True)
        flow = self.service.begin_auto_security(logical_req)
        self.assertEqual(flow.subfunction, 5)
        self.assertEqual(flow.key_subfunction, 6)
        self.assertEqual(flow.expected_unlock, b'\x67\x06')
        self.assertEqual(flow.level_name, 'Level 3')

        seed_res = self.transact(flow.seed_request)
        self.assertTrue(flow.accept_seed(seed_res))

        provider, gate = self.service.auto_provider(flow)
        flow.calculating()
        key_material = provider.calculate(seed_bytes, source_transaction=flow.seed_request.transaction_id)
        self.assertEqual(len(key_material.key), 16)
        self.backend.expected_key = key_material.key

        from services.can.security_access_session import SecurityAccessSession
        session = SecurityAccessSession()
        session.start(flow.seed_request, self.service.capture_session_id, 1)
        session.receive(seed_res, self.service.capture_session_id, 1)
        session.calculate_verified(provider, gate)
        key_req = self.service.prepare_auto_submission(flow, session, 1)
        self.assertEqual(key_req.uds_payload[:2], b'\x27\x06')
        self.assertEqual(key_req.expected, b'\x67\x06')
        flow.key_ready(key_req)

        key_res = self.transact(key_req)
        accepted = session.finish_submission(key_res)
        self.assertTrue(accepted)
        self.assertTrue(flow.accept_key(key_res, accepted=accepted))
        self.assertEqual(flow.result.outcome, DiagnosticOutcome.PASSED)
        self.assertEqual(flow.result.response, b'\x67\x06')
        self.assertIn('Level 3', flow.result.detail)
        self.service.end_auto_security(flow)

    def test_auto_security_negative_response_stops_workflow(self):
        ext_req = DiagnosticRequest('tx_ext_nrc', 'step_1', 1, 'VF5NP', 'BCM', 0x681, 0x601, b'\x10\x03', b'\x50\x03', settings=self.settings, confirmed=True)
        self.assertEqual(self.transact(ext_req).outcome, DiagnosticOutcome.PASSED)

        logical_req = DiagnosticRequest('tx_l1_nrc', 'step_2', 1, 'VF5NP', 'BCM', 0x681, 0x601, b'\x27\x01', b'\x67\x02', settings=self.settings, confirmed=True)
        flow = self.service.begin_auto_security(logical_req)

        # ECU responds with NRC 0x35 (Invalid Key / Attempts Exceeded)
        nrc_result = DiagnosticResult(flow.seed_request, DiagnosticOutcome.FAILED, b'\x7F\x27\x35', nrc=0x35, detail='NRC 0x35')
        advance = flow.accept_seed(nrc_result)
        self.assertFalse(advance)
        self.assertEqual(flow.phase, 'Finished')
        self.assertEqual(flow.result.outcome, DiagnosticOutcome.FAILED)
        self.assertEqual(flow.result.response, b'\x7F\x27\x35')
        self.service.end_auto_security(flow)

