"""Excel export of CAN Interface sequences: day folder, file naming, one sheet per sequence, done popup."""
from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from config.paths import CAN_INTERFACE_LOG_DIR
from core.services.diagnostic_sequence_report_service import DiagnosticSequenceReportService
from gui.widgets.can_interface.diagnostic_table_panel import result_label
from gui.widgets.controls.export_toast import show_export_toast
from gui.widgets.controls.save_dialog import SAVE_DIALOG_SIZE, ask_save_path, configure_save_dialog  # noqa: F401


def sheet_for_case(case, runtime_rows=()):
    """(sheet name, rows) of a sequence that is not on screen, with its remembered results.

    runtime_rows is the second item of CanDiagnosticTablePanel.runtime_snapshot(): one
    (signature, (payload, outcome, detail) or None, auto comment) entry per step.
    """
    rows = list(runtime_rows)
    data = []
    for index, step in enumerate(case.steps):
        remembered = rows[index][1] if index < len(rows) and rows[index] is not None else None
        payload, outcome, _detail = remembered if remembered else ("", "", "")
        data.append({
            "step": index + 1,
            "sequence_name": step.sequence_name,
            "ecu": step.ecu,
            "request": step.request,
            "delay_ms": 100 if step.delay_ms is None else step.delay_ms,
            "repeat": step.repeat if step.repeat is not None else 1,
            "expected": step.expected_response,
            "receive": payload,
            "result": result_label(outcome),
            "comment": step.comment,
        })
    return case.name, data


def export_sheets_excel(parent, sheets, vehicle_name="", *, report_dir=None):
    """Ask where to save, write one sheet per sequence, then show the OPEN FOLDER / OPEN FILE popup.

    One sequence keeps its name and vehicle in the file name; two or more use only the timestamp.
    Returns the saved path, or None when cancelled or failed.
    """
    service = DiagnosticSequenceReportService(report_dir if report_dir is not None else CAN_INTERFACE_LOG_DIR)
    folder = service.fn_get_report_folder()  # CAN_Interface_Logs/<dd-mm-yyyy>
    single = len(sheets) == 1
    filename = service.fn_default_output_filename(sheets[0][0] if single else "", vehicle_name if single else "")
    output_file = ask_save_path(parent, "Save Excel Report", folder / filename, "Excel Files (*.xlsx)")
    if not output_file:
        return None
    if not str(output_file).lower().endswith(".xlsx"):
        output_file = str(output_file) + ".xlsx"
    try:
        saved = service.export_sequences(sheets, output_file)
    except PermissionError:
        QMessageBox.warning(parent, "Export Error",
                            "Cannot save Excel report. Please close the Excel file and try again.")
        return None
    except Exception as error:
        QMessageBox.critical(parent, "Export Error", str(error))
        return None
    show_export_toast(parent, Path(saved), title="Excel report saved")
    return Path(saved)
