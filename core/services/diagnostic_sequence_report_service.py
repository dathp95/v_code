from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from config.paths import LOG_ANALYZER_REPORT_DIR
from core.excel_styles import (
    CENTER_ALIGNMENT,
    FAIL_FILL,
    HEADER_ALIGNMENT,
    HEADER_FILL,
    HEADER_FONT,
    LEFT_ALIGNMENT,
    PASS_FILL,
    THIN_BORDER,
)

SEQUENCE_REPORT_HEADERS = [
    "Step",
    "Test sequence name",
    "ECU",
    "Payload (HEX)",
    "Delay (ms)",
    "Repeat",
    "Expected Response (HEX)",
    "Receive Message (HEX)",
    "Results",
    "Comment",
]


# Fixed layout (characters): long HEX / text columns wrap inside their cell instead of widening the sheet.
COLUMN_WIDTHS = {
    "Step": 7,
    "Test sequence name": 34,
    "ECU": 10,
    "Payload (HEX)": 42,
    "Delay (ms)": 11,
    "Repeat": 9,
    "Expected Response (HEX)": 42,
    "Receive Message (HEX)": 42,
    "Results": 12,
    "Comment": 40,
}
WRAPPED_HEADERS = frozenset({
    "Test sequence name", "Payload (HEX)", "Expected Response (HEX)", "Receive Message (HEX)", "Comment",
})
LINE_HEIGHT = 15.0
MAX_ROW_HEIGHT = 409.0  # Excel limit.

# Same colors as the Results cell in the app: (fill, text).
RESULT_COLORS = {
    "Passed": ("2E8B57", "FFFFFF"),
    "Failed": ("C0392B", "FFFFFF"),
    "Error": ("C0392B", "FFFFFF"),
    "Timeout": ("E67E22", "FFFFFF"),
}


def _wrapped_lines(text, width):
    """Rough number of lines a wrapped cell needs (breaks at spaces like Excel does)."""
    usable = max(int(width) - 2, 1)
    lines = 0
    for paragraph in str(text if text is not None else "").split("\n"):
        current = 0
        lines += 1
        for word in paragraph.split(" "):
            needed = len(word) + (1 if current else 0)
            if current and current + needed > usable:
                lines += 1
                current = len(word)
            else:
                current += needed
            while current > usable:  # A single word longer than the cell is cut by Excel.
                lines += 1
                current -= usable
    return lines


class DiagnosticSequenceReportService:
    def __init__(self, report_dir: Path | None = None):
        self.report_dir = Path(report_dir) if report_dir is not None else LOG_ANALYZER_REPORT_DIR

    def fn_get_report_folder(self) -> Path:
        today = datetime.now().strftime("%d-%m-%Y")
        folder = self.report_dir / today
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def fn_default_output_filename(
        self,
        sequence_name: str = "",
        vehicle_name: str = "",
    ) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_seq = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(sequence_name or "").strip()).strip(" .")
        safe_veh = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(vehicle_name or "").strip()).strip(" .")

        parts = ["EEIV_Sequence_Report"]
        if safe_seq:
            parts.append(safe_seq)
        if safe_veh:
            parts.append(safe_veh)
        parts.append(timestamp)

        return f"{'_'.join(parts)}.xlsx"

    def export_sequence(
        self,
        sequence_name: str,
        vehicle_name: str,
        steps_data: Sequence[dict[str, Any]],
        output_file: str | Path,
    ) -> Path:
        return self.export_sequences([(sequence_name, steps_data)], output_file)

    def export_sequences(
        self,
        sheets: Sequence[tuple[str, Sequence[dict[str, Any]]]],
        output_file: str | Path,
    ) -> Path:
        """One worksheet per (sequence name, step rows) pair, in the given order."""
        if not sheets:
            raise ValueError("No sequence data to export.")
        wb = Workbook()
        used_titles: set[str] = set()
        for index, (sequence_name, steps_data) in enumerate(sheets):
            ws = wb.active if index == 0 else wb.create_sheet()
            ws.title = self._unique_sheet_title(sequence_name, used_titles)
            self._fill_sheet(ws, steps_data)
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        wb.save(output_path)
        return output_path

    @staticmethod
    def _unique_sheet_title(sequence_name: str, used: set[str]) -> str:
        raw_title = str(sequence_name or "Sequence").strip()
        base = re.sub(r"[\\/*?:\[\]]", "_", raw_title)[:31] or "Sequence"
        title, number = base, 1
        while title.casefold() in used:
            number += 1
            suffix = f" ({number})"
            title = base[:31 - len(suffix)] + suffix
        used.add(title.casefold())
        return title

    def _fill_sheet(self, ws, steps_data: Sequence[dict[str, Any]]) -> None:
        # Row 1: Banner Header
        num_cols = len(SEQUENCE_REPORT_HEADERS)
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=num_cols)
        banner_cell = ws["A1"]
        banner_cell.value = "Generated by V-CODE EEIV Diagnostic"
        banner_cell.alignment = HEADER_ALIGNMENT
        banner_cell.font = Font(name="Segoe UI", size=12, bold=True, color="1F4E78")

        # Row 2: Table Headers
        for col_idx, header in enumerate(SEQUENCE_REPORT_HEADERS, 1):
            cell = ws.cell(row=2, column=col_idx, value=header)
            cell.font = HEADER_FONT
            cell.fill = HEADER_FILL
            cell.alignment = HEADER_ALIGNMENT
            cell.border = THIN_BORDER

        # Rows 3+: Sequence Steps Data
        for row_idx, step_data in enumerate(steps_data, 3):
            row_values = [
                step_data.get("step", row_idx - 2),
                step_data.get("sequence_name", ""),
                step_data.get("ecu", ""),
                step_data.get("request", ""),
                step_data.get("delay_ms", ""),
                step_data.get("repeat", ""),
                step_data.get("expected", ""),
                step_data.get("receive", ""),
                step_data.get("result", ""),
                step_data.get("comment", ""),
            ]
            outcome = str(step_data.get("result", "")).strip()
            lines = 1

            for col_idx, val in enumerate(row_values, 1):
                cell = ws.cell(row=row_idx, column=col_idx, value=val)
                cell.border = THIN_BORDER
                header = SEQUENCE_REPORT_HEADERS[col_idx - 1]

                if header in ("Step", "Delay (ms)", "Repeat", "ECU", "Results"):
                    cell.alignment = CENTER_ALIGNMENT
                elif header in WRAPPED_HEADERS:
                    cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
                    lines = max(lines, _wrapped_lines(val, COLUMN_WIDTHS[header]))
                else:
                    cell.alignment = LEFT_ALIGNMENT

                if header == "Results" and outcome in RESULT_COLORS:
                    fill, text = RESULT_COLORS[outcome]
                    cell.fill = PatternFill("solid", fgColor=fill)
                    cell.font = Font(bold=True, color=text)

            ws.row_dimensions[row_idx].height = min(max(lines, 1) * LINE_HEIGHT + 3, MAX_ROW_HEIGHT)

        ws.freeze_panes = "A3"
        if ws.max_column > 0 and ws.max_row >= 2:
            ws.auto_filter.ref = f"A2:{get_column_letter(ws.max_column)}{ws.max_row}"

        for col_idx, header in enumerate(SEQUENCE_REPORT_HEADERS, 1):
            ws.column_dimensions[get_column_letter(col_idx)].width = COLUMN_WIDTHS[header]
