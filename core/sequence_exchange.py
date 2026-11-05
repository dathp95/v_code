"""Pure clipboard exchange; imported Results never become diagnostic runtime state.

Importing is lenient: missing or odd content (blank names, short rows, bad numbers, incomplete HEX)
is kept or defaulted with a warning, so anything the app exported can be pasted back. Only input
that cannot be read at all is refused.
"""
import csv
from dataclasses import dataclass
import io

from core.diagnostic_sequence import DiagnosticStep
from repositories.diagnostic_sequence_repository import DiagnosticSequenceRepository as Native

HEADERS = ('Step', 'Test sequence name', 'ECU', 'Payload(HEX)', 'Delay(ms)', 'Repeat',
           'Expected Response (HEX)', 'Results', 'Comment')
MAX_TEXT = 2 * 1024 * 1024
MAX_ROWS = 2000


@dataclass(frozen=True)
class SequenceImport:
    steps: tuple[DiagnosticStep, ...]
    diagnostics: tuple[str, ...]


def export_sequence_text(steps, results=()):
    output = io.StringIO(newline='')
    writer = csv.writer(output, delimiter='\t', lineterminator='\n')
    writer.writerow(HEADERS)
    results = tuple(results)
    for index, step in enumerate(steps):
        writer.writerow((step.step, step.sequence_name, step.ecu, step.request,
                         '' if step.delay_ms is None else step.delay_ms, step.repeat,
                         step.expected_response, results[index] if index < len(results) else '', step.comment))
    return output.getvalue()


def _whole_number(text, minimum):
    try:
        value = int(str(text).strip())
    except ValueError:
        return None
    return value if value >= minimum else None


def _hex_or_as_typed(text, label, source_row, diagnostics, *, allow_empty):
    try:
        return Native._normalize_hex(text, label, allow_empty=allow_empty)
    except (ValueError, TypeError):
        compact = ''.join(text.split())
        if compact and len(compact) % 2 == 0 and all(char in '0123456789abcdefABCDEF' for char in compact):
            return ' '.join(compact[index:index + 2].upper() for index in range(0, len(compact), 2))  # "22f190"
        diagnostics.append(f'Row {source_row}: {label} {text.strip()!r} is not valid HEX; kept as typed.')
        return text.strip()


def parse_sequence_text(text, *, ecu_names=None):
    if not isinstance(text, str) or len(text) > MAX_TEXT:
        raise ValueError('Input exceeds the 2,097,152-character clipboard limit.')
    body = text.lstrip('\ufeff')
    reader = csv.reader(io.StringIO(body, newline=''), delimiter='\t' if '\t' in body else ',', strict=True)
    steps, diagnostics, seen, first = [], [], set(), True
    while True:
        source_row = reader.line_num + 1
        try:
            row = next(reader)
        except StopIteration:
            break
        except csv.Error:
            raise ValueError(f'Row {source_row}: invalid quoted TSV/CSV.') from None
        if first:
            first = False
            if row and row[0].strip().lower() == 'step':  # The header row is optional.
                continue
        if not any(cell.strip() for cell in row):
            continue
        if len(row) != len(HEADERS):
            diagnostics.append(f'Row {source_row}: expected {len(HEADERS)} cells, got {len(row)}; '
                               + ('missing cells left blank.' if len(row) < len(HEADERS) else 'extra cells ignored.'))
        cells = [*row[:len(HEADERS)], *([''] * (len(HEADERS) - len(row)))]
        number = _whole_number(cells[0], 1)
        if number is None or number in seen:
            if cells[0].strip():
                diagnostics.append(f'Row {source_row}: step {cells[0].strip()!r} is not a unique positive number; '
                                   f'using position {len(steps) + 1}.')
            number = len(steps) + 1
        ecu = cells[2].strip()
        request = _hex_or_as_typed(cells[3], 'Payload', source_row, diagnostics, allow_empty=True)
        expected = _hex_or_as_typed(cells[6], 'Expected Response', source_row, diagnostics, allow_empty=True)
        delay = _whole_number(cells[4], 0) if cells[4].strip() else None
        if cells[4].strip() and delay is None:
            diagnostics.append(f'Row {source_row}: delay {cells[4].strip()!r} is not valid; default used.')
        repeat = _whole_number(cells[5], 1) if cells[5].strip() else 1
        if repeat is None:
            diagnostics.append(f'Row {source_row}: repeat {cells[5].strip()!r} is not valid; 1 used.')
            repeat = 1
        seen.add(number)
        steps.append(DiagnosticStep(number, cells[1].strip(), ecu, request, delay, repeat, expected, comment=cells[8]))
        if len(steps) > MAX_ROWS:
            raise ValueError(f'Row {source_row}: at most {MAX_ROWS} rows may be imported.')
        if ecu_names is not None and (not ecu or ecu not in ecu_names):
            diagnostics.append(f'Row {source_row}: unresolved ECU {ecu!r}; selector will be empty.')
        if cells[7].strip() not in ('', '\u2014'):
            diagnostics.append(f'Row {source_row}: imported Results ignored; actual transport execution is required.')
    if not steps:
        raise ValueError('Row 2: no diagnostic rows to import.')
    return SequenceImport(tuple(steps), tuple(diagnostics))
