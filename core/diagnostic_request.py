from dataclasses import dataclass, field
from enum import Enum
from math import isfinite


class DiagnosticValidationError(ValueError):
    pass


class DiagnosticCancelled(RuntimeError):
    """Cooperative cancellation shared by admission/TX policy and transport."""
    pass


class DiagnosticOutcome(Enum):
    PASSED = 'Passed'
    FAILED = 'Failed'
    TIMEOUT = 'Timeout'
    ERROR = 'Error'
    NOT_EVALUATED = 'Not Evaluated'
    CANCELLED = 'Cancelled'


SAFE_SERVICES = frozenset((0x19, 0x22, 0x3E))
# 0x2F (InputOutputControlByIdentifier) drives actuators/outputs, so it is state-changing like 0x2E/0x31.
CONFIRM_SERVICES = frozenset((0x10, 0x11, 0x14, 0x2E, 0x2F, 0x31, 0x85))
TRUSTED_BENCH_PAYLOADS = frozenset((b'\x10\x01', b'\x10\x03', b'\x14\xff\xff\xff'))
SECURITY_LEVELS = {
    0x01: {"level": 1, "send_key": 0x02},
    0x03: {"level": 2, "send_key": 0x04},
    0x05: {"level": 3, "send_key": 0x06},
    0x07: {"level": 4, "send_key": 0x08},
}

SECURITY_SEED_REQUESTS = frozenset(bytes([0x27, sf]) for sf in SECURITY_LEVELS)


def is_security_seed_payload(payload: bytes) -> bool:
    return (
        isinstance(payload, bytes)
        and len(payload) == 2
        and payload[0] == 0x27
        and payload[1] in SECURITY_LEVELS
    )


@dataclass(frozen=True)
class DiagnosticSettings:
    p2_s: float = 1.0
    p2_star_s: float = 5.0
    total_s: float = 30.0
    fc_timeout_s: float = 1.0
    cf_timeout_s: float = 1.0
    padding: int | None = 0
    block_size: int = 0
    stmin: int = 0
    max_payload: int = 4095

    def __post_init__(self):
        for value in (self.p2_s, self.p2_star_s, self.total_s, self.fc_timeout_s, self.cf_timeout_s):
            if isinstance(value, bool) or not isinstance(value, (int,float)) or not isfinite(value) or value <= 0:
                raise DiagnosticValidationError('Diagnostic timeouts must be finite and positive.')
        if not self.p2_s <= self.p2_star_s <= self.total_s <= 120:
            raise DiagnosticValidationError('Require P2 <= P2* <= total <= 120 seconds.')
        for value, maximum in ((self.block_size,255),(self.stmin,127),(self.max_payload,4095)):
            if isinstance(value,bool) or not isinstance(value,int) or not 0 <= value <= maximum:
                raise DiagnosticValidationError('Invalid ISO-TP settings.')
        if self.max_payload < 8 or (self.padding is not None and (isinstance(self.padding,bool) or not isinstance(self.padding,int) or not 0 <= self.padding <= 255)):
            raise DiagnosticValidationError('Invalid ISO-TP padding/payload limit.')


@dataclass(frozen=True)
class DiagnosticRequest:
    transaction_id: str
    step_id: str
    generation: int
    vehicle_name: str
    ecu_name: str
    tx_id: int
    rx_id: int
    uds_payload: bytes
    expected: bytes = b''
    match: str = 'prefix'
    settings: DiagnosticSettings = field(default_factory=DiagnosticSettings)
    confirmed: bool = False
    extended: bool = False
    bench_authorization_id: str = ''

    def __post_init__(self):
        if not all(isinstance(x,str) and x for x in (self.transaction_id,self.step_id,self.vehicle_name,self.ecu_name)):
            raise DiagnosticValidationError('Missing diagnostic request identity.')
        if isinstance(self.generation,bool) or not isinstance(self.generation,int) or self.generation < 0:
            raise DiagnosticValidationError('Invalid document generation.')
        if self.extended or any(isinstance(x,bool) or not isinstance(x,int) or not 0 <= x <= 0x7FF for x in (self.tx_id,self.rx_id)):
            raise DiagnosticValidationError('M04 supports normal physical 11-bit addressing only.')
        if self.tx_id == self.rx_id or self.tx_id == 0x7DF:
            raise DiagnosticValidationError('Use distinct physical ECU request/response CAN IDs.')
        if not isinstance(self.settings,DiagnosticSettings):
            raise DiagnosticValidationError('Invalid diagnostic settings.')
        if not isinstance(self.uds_payload,bytes) or not 1 <= len(self.uds_payload) <= self.settings.max_payload:
            raise DiagnosticValidationError('Invalid UDS payload length.')
        sid = self.uds_payload[0]
        if sid == 0x27:
            if not is_security_seed_payload(self.uds_payload):
                from core.security_submission import validate_generated_constructor
                validate_generated_constructor(self)
        elif sid not in SAFE_SERVICES | CONFIRM_SERVICES or (sid == 0x10 and len(self.uds_payload)>1 and self.uds_payload[1]&0x7F == 2):
            raise DiagnosticValidationError('This service/programming operation is not enabled in M04.')
        if self.match not in ('prefix','exact'):
            raise DiagnosticValidationError('Wildcard matching is undefined and not enabled; choose prefix or exact.')
        if not isinstance(self.expected,bytes) or len(self.expected) > self.settings.max_payload:
            raise DiagnosticValidationError('Invalid expected response.')
        if not isinstance(self.confirmed,bool):
            raise DiagnosticValidationError('Invalid confirmation value.')
        if not isinstance(self.bench_authorization_id,str) or (self.bench_authorization_id and
                (not self.confirmed or self.uds_payload not in TRUSTED_BENCH_PAYLOADS)):
            raise DiagnosticValidationError('Payload is not covered by connection bench authorization.')

    @property
    def requires_confirmation(self):
        return self.uds_payload[0] in CONFIRM_SERVICES or is_security_seed_payload(self.uds_payload) or self.uds_payload in SECURITY_SEED_REQUESTS


def validate_send_policy(request):
    if not isinstance(request,DiagnosticRequest):
        raise DiagnosticValidationError('Invalid diagnostic request.')
    DiagnosticRequest.__post_init__(request)
    if request.requires_confirmation and not request.confirmed:
        raise DiagnosticValidationError('Manual confirmation is required for this state-changing service.')


@dataclass(frozen=True)
class TrustedBenchAuthorization:
    """In-memory grant for one connection generation and configured bench context."""
    authorization_id: str
    connection_id: str
    context_id: str

    def permits(self, request, connection_id):
        return connection_id == self.connection_id and request.uds_payload in TRUSTED_BENCH_PAYLOADS


def response_belongs_to_request(request, payload):
    """Protocol correlation, independent of the user's expected-response rule.

    SF/FF callers supply the available UDS prefix; required echo fields fit in
    the first Classical CAN FF. Additional DIDs/data remain expectation checks.
    """
    sent=request.uds_payload
    if not payload: return False
    if payload[0] == 0x7F:
        return len(payload)>=2 and payload[1] == sent[0]
    if payload[0] != sent[0]+0x40: return False
    if sent[0] == 0x27 and len(sent) >= 2 and sent[1] % 2 == 0:
        from core.security_submission import is_key_submission
        return is_key_submission(request) and payload == bytes([0x67, sent[1]])
    if sent[0] == 0x27 and (not is_security_seed_payload(sent) or len(payload) < 3):
        return False  # 67 xx alone is not a successful seed response.
    echo_length={0x10:1,0x11:1,0x19:1,0x22:2,0x27:1,0x2E:2,0x2F:2,0x31:3,0x3E:1,0x85:1}.get(sent[0],0)
    if len(sent)<1+echo_length or len(payload)<1+echo_length: return False
    echo=bytearray(sent[1:1+echo_length])
    if sent[0] in (0x10,0x11,0x19,0x31,0x3E,0x85) and echo: echo[0]&=0x7F
    return payload[1:1+echo_length] == bytes(echo)


@dataclass(frozen=True)
class DiagnosticResult:
    request: DiagnosticRequest
    outcome: DiagnosticOutcome
    response_payload: bytes | None = None
    detail: str = ''
    elapsed_s: float = 0.0
    nrc: int | None = None
    pending_times: tuple[float, ...] = ()
    pending_count: int = 0
