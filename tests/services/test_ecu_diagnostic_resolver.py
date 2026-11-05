import unittest
from types import SimpleNamespace
from models.ecu import ECU
from models.vehicle import Vehicle
from core.diagnostic_sequence import DiagnosticStep


class EcuDiagnosticResolverTests(unittest.TestCase):
    def resolve(self, ecus=None, step=None, name='BENCH'):
        from services.can.ecu_diagnostic_resolver import resolve_request
        service=SimpleNamespace(load_vehicle=lambda _: Vehicle('BENCH',ecus=ecus if ecus is not None else [ECU('BCM','681','0x601')]))
        return resolve_request(service,name,step or DiagnosticStep(1,'VIN','BCM','22 F1 90',expected_response='62 F1 90'),'row-id',7)

    def test_hex_ids_and_frozen_payload(self):
        result=self.resolve()
        self.assertEqual((result.tx_id,result.rx_id),(0x681,0x601))
        self.assertEqual(result.uds_payload,b'\x22\xf1\x90')
        self.assertEqual(result.generation,7)
        self.assertEqual(result.expected,b'\x62\xf1\x90')

    def test_missing_ambiguous_invalid_ids_and_extended_rejected(self):
        from core.diagnostic_request import DiagnosticValidationError
        for ecus in ([],[ECU('BCM'),ECU('BCM')],[ECU('BCM','','601')],[ECU('BCM','681','681')],
                     [ECU('BCM','1800','601')],[ECU('BCM','681','601'),ECU('OTHER','682','601')]):
            with self.assertRaises(DiagnosticValidationError): self.resolve(ecus)
        with self.assertRaises(DiagnosticValidationError): self.resolve(name='')

    def test_security_invalid_payload_and_undefined_wildcard_rejected(self):
        from core.diagnostic_request import DiagnosticValidationError
        for payload in ('27 02','27 03','27 01 00','','zz','34 00','10 02','10 82'):
            with self.assertRaises(DiagnosticValidationError): self.resolve(step=DiagnosticStep(1,'TEST','BCM',payload))
        with self.assertRaises(DiagnosticValidationError):
            self.resolve(step=DiagnosticStep(1,'TEST','BCM','22 F1 90',match='wildcard'))

    def test_io_control_2f_is_state_changing_and_responses_correlate_by_did(self):
        from core.diagnostic_request import validate_send_policy, response_belongs_to_request, DiagnosticValidationError
        from dataclasses import replace
        step=DiagnosticStep(1,'Screen','BCM','2F F0 AC 03 00',expected_response='6F F0 AC 03 00')
        request=self.resolve(step=step)
        self.assertEqual(request.uds_payload,b'\x2f\xf0\xac\x03\x00')
        self.assertTrue(request.requires_confirmation)
        with self.assertRaises(DiagnosticValidationError): validate_send_policy(request)
        validate_send_policy(replace(request,confirmed=True))
        for payload in (b'\x6f\xf0\xac\x03\x00', b'\x6f\xf0\xac', b'\x7f\x2f\x31', b'\x7f\x2f\x78'):
            self.assertTrue(response_belongs_to_request(request,payload),payload.hex())
        for payload in (b'\x6f\xf0\xad\x03\x00', b'\x6f', b'\x7f\x2e\x31', b'\x62\xf0\xac'):
            self.assertFalse(response_belongs_to_request(request,payload),payload.hex())

    def test_every_shipped_sequence_step_builds_a_valid_request(self):
        import json
        from pathlib import Path
        from core.diagnostic_request import DiagnosticRequest, DiagnosticSettings, DiagnosticValidationError
        from core.diagnostic_sequence import DiagnosticStep
        failures=[]
        for path in sorted(Path('config/diagnostic_sequences').glob('*.json')):
            for item in json.loads(path.read_text(encoding='utf-8')).get('steps',[]):
                text=item.get('request','').strip()
                if not text: continue  # Blank placeholder rows are not requests.
                step=DiagnosticStep(item['step'],'','BCM',text,expected_response=item.get('expected_response',''),
                                    match=item.get('match','prefix'))
                try:
                    DiagnosticRequest('t','s',0,'V','BCM',0x681,0x601,bytes.fromhex(step.request.replace(' ','')),
                                      bytes.fromhex(step.expected_response.replace(' ','')),step.match,
                                      settings=DiagnosticSettings(),confirmed=True)
                except (ValueError,DiagnosticValidationError) as error:
                    failures.append((path.name,item['step'],text,str(error)))
        self.assertEqual(failures,[])

    def test_state_changing_requires_separate_confirmation(self):
        from core.diagnostic_request import validate_send_policy, DiagnosticValidationError
        from dataclasses import replace
        request=self.resolve(step=DiagnosticStep(1,'WRITE','BCM','2E F1 90 01'))
        self.assertTrue(request.requires_confirmation)
        with self.assertRaises(DiagnosticValidationError): validate_send_policy(request)
        validate_send_policy(replace(request,confirmed=True))
        session=self.resolve(step=DiagnosticStep(1,'SESSION','BCM','10 03'))
        with self.assertRaises(DiagnosticValidationError): validate_send_policy(session)
