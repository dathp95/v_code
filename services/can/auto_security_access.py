"""Composite SecurityAccess workflow for Level 1, 2, 3, and 4. No I/O or Qt ownership."""
from dataclasses import dataclass, replace
from uuid import uuid4
import time

from core.diagnostic_request import SECURITY_LEVELS, DiagnosticOutcome as Outcome, is_security_seed_payload
from core.security_submission import is_key_submission


@dataclass(frozen=True)
class AutoSecurityResult:
    outcome: Outcome
    response: bytes
    detail: str


@dataclass(frozen=True)
class AutoPhysicalRecord:
    transaction_id: str
    phase: str
    outcome: Outcome
    elapsed_s: float
    nrc: int | None


class AutoSecurityAccessL1:
    """Composite protocol state for automated UDS SecurityAccess (L1..L4)."""
    def __init__(self, logical_request, *, clock=time.monotonic):
        if not self.matches(logical_request):
            raise ValueError('Auto SecurityAccess requires a valid request (27 01, 27 03, 27 05 or 27 07).')
        self.logical_request = logical_request
        self.subfunction = logical_request.uds_payload[1]
        cfg = SECURITY_LEVELS[self.subfunction]
        self.key_subfunction = cfg["send_key"]
        self.level_number = cfg["level"]
        self.level_name = f'Level {self.level_number}'
        self.expected_seed = bytes([0x67, self.subfunction])
        self.expected_unlock = bytes([0x67, self.key_subfunction])
        self.workflow_id = uuid4().hex
        self._clock = clock
        self.deadline = clock() + logical_request.settings.total_s
        self.seed_request = replace(logical_request, transaction_id=uuid4().hex,
                                    expected=self.expected_seed, match='prefix', confirmed=True)
        self.key_request = None
        self.phase = 'Requesting seed'
        self.result = None
        self.trace = []

    @staticmethod
    def matches(request):
        """Every seed request (27 01/03/05/07) is an Auto workflow; the Expected Response column is ignored."""
        return is_security_seed_payload(getattr(request, 'uds_payload', None))

    @property
    def expired(self):
        return self._clock() >= self.deadline

    def _record(self, result):
        self.trace.append(AutoPhysicalRecord(result.request.transaction_id, self.phase,
            result.outcome, result.elapsed_s, result.nrc))

    def finish(self, outcome, response=b'', detail=''):
        if self.result is None:
            self.result = AutoSecurityResult(outcome, response, detail)
            self.phase = 'Finished'

    def accept_seed(self, result):
        if self.result is not None or self.phase != 'Requesting seed' or result.request is not self.seed_request:
            return False
        self._record(result)
        if result.outcome not in (Outcome.PASSED, Outcome.NOT_EVALUATED):
            self.finish(result.outcome, self._safe_response(result), 'Seed request: ' + result.detail)
            return False
        payload = result.response_payload
        if not isinstance(payload, bytes) or len(payload) != 18 or payload[:2] != self.expected_seed:
            self.finish(Outcome.ERROR, detail=f"Seed response must be {self.expected_seed.hex(' ').upper()} plus 16 bytes.")
            return False
        if not any(payload[2:]):
            self.finish(Outcome.NOT_EVALUATED, self.expected_seed,
                f"Already unlocked (zero seed); no key sent and no {self.expected_unlock.hex(' ').upper()} received.")
            return False
        self.phase = 'Seed received'
        return True

    def calculating(self):
        if self.phase != 'Seed received' or self.result is not None:
            raise ValueError('No accepted seed for Auto SecurityAccess calculation.')
        self.phase = 'Calculating key'

    def key_ready(self, request):
        if (self.result is not None or self.phase not in ('Seed received', 'Calculating key')
                or not is_key_submission(request)
                or (request.vehicle_name, request.ecu_name, request.tx_id, request.rx_id,
                    request.step_id, request.generation) !=
                   (self.seed_request.vehicle_name, self.seed_request.ecu_name,
                    self.seed_request.tx_id, self.seed_request.rx_id,
                    self.seed_request.step_id, self.seed_request.generation)):
            raise ValueError('Generated key does not belong to the Auto SecurityAccess workflow.')
        self.key_request = request
        self.phase = 'Waiting for ECU'

    def accept_key(self, result, *, accepted):
        if self.result is not None or self.phase != 'Waiting for ECU' or result.request is not self.key_request:
            return False
        self._record(result)
        success = accepted is True and result.outcome == Outcome.PASSED and result.response_payload == self.expected_unlock
        outcome = Outcome.PASSED if success else Outcome.ERROR if result.outcome == Outcome.PASSED else result.outcome
        detail = f'Security Unlocked ({self.level_name})' if success else 'Key request: ' + result.detail
        self.finish(outcome, self.expected_unlock if success else self._safe_response(result), detail)
        return success

    @staticmethod
    def _safe_response(result):
        payload = result.response_payload
        return payload if isinstance(payload, bytes) and len(payload) == 3 and payload[:2] == b'\x7f\x27' else b''


AutoSecurityAccessFlow = AutoSecurityAccessL1
