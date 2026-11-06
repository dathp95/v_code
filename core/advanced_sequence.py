"""Pure rendering for "Add sequence advance": a template of rows repeated for every chosen ECU."""
from dataclasses import dataclass

from core.diagnostic_sequence import DiagnosticStep
from core.sequence_exchange import _hex_or_as_typed, _whole_number


@dataclass(frozen=True)
class AdvancedRow:
    """One template row as typed in the dialog (everything is the raw cell text)."""

    sequence_name: str = ""
    request: str = ""
    delay: str = "100"
    repeat: str = "1"
    expected_response: str = ""
    comment: str = ""

    @property
    def is_blank(self):
        # Delay and Repeat always hold a default, so only what the user really typed counts.
        return not any(text.strip() for text in (self.sequence_name, self.request, self.expected_response, self.comment))


def render_advanced_steps(rows, ecu_names):
    """Every ECU in turn gets the whole template: ECU1 rows, then ECU2 rows... Steps are numbered 1..N.

    Cell text is treated like an imported sequence: HEX is normalised when it can be and kept as typed
    otherwise, an unusable Delay becomes the default (None) and an unusable Repeat becomes 1.
    """

    template = [row for row in rows if not row.is_blank]
    steps = []
    ignored = []
    for ecu in ecu_names:
        for row in template:
            request = _hex_or_as_typed(row.request, "Payload", 0, ignored, allow_empty=True)
            expected = _hex_or_as_typed(row.expected_response, "Expected Response", 0, ignored, allow_empty=True)
            delay = _whole_number(row.delay, 0) if row.delay.strip() else None
            repeat = _whole_number(row.repeat, 1) if row.repeat.strip() else 1
            steps.append(DiagnosticStep(len(steps) + 1, row.sequence_name.strip(), ecu, request, delay,
                                        repeat if repeat is not None else 1, expected, comment=row.comment))
    return tuple(steps)
