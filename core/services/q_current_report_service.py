from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from gui.widgets.controls.save_dialog import ask_save_path

from config.paths import Q_CURRENT_REPORT_DIR
from core.q_current_report_export import QCurrentReportData, export_q_current_report


_INVALID_FILENAME_CHARS = '<>:"/\\|?*'


class QCurrentReportService:
    def __init__(
        self,
        report_root: str | Path | None = None,
        exporter=export_q_current_report,
        now_provider=datetime.now,
    ):
        self.report_root = Path(report_root) if report_root is not None else Q_CURRENT_REPORT_DIR
        self._exporter = exporter
        self._now_provider = now_provider

    def fn_get_report_folder(self) -> Path:
        today = self._now_provider().strftime("%d-%m-%Y")
        report_folder = self.report_root / today
        report_folder.mkdir(parents=True, exist_ok=True)
        return report_folder

    def fn_default_report_path(self, dataset_name: str) -> Path:
        now = self._now_provider()
        safe_dataset_name = sanitize_dataset_name(dataset_name)
        report_folder = self.fn_get_report_folder()
        filename = f"QCurrent_{safe_dataset_name}_Report_{now.strftime('%Y%m%d_%H%M%S')}.xlsx"
        return report_folder / filename

    def fn_choose_output_file(self, parent, dataset_name: str) -> Path | None:
        default_path = self.fn_default_report_path(dataset_name)
        output_file = ask_save_path(
            parent,
            "Save Q Current Report",
            default_path,
            "Excel Files (*.xlsx)",
        )
        if not output_file:
            return None
        selected_path = Path(output_file)
        if selected_path.suffix.lower() != ".xlsx":
            selected_path = selected_path.with_suffix(".xlsx")
        return selected_path

    def fn_export(self, parent, report_data: QCurrentReportData) -> Path | None:
        output_file = self.fn_choose_output_file(parent, report_data.dataset_name)
        if output_file is None:
            return None
        output_file.parent.mkdir(parents=True, exist_ok=True)
        success = self._exporter(report_data, output_file)
        if not success:
            raise PermissionError(f"Cannot write Q Current report: {output_file}")
        return output_file


def sanitize_dataset_name(dataset_name: str) -> str:
    text = str(dataset_name or "").strip()
    if text.lower().endswith(".db"):
        text = text[:-3]
    for character in _INVALID_FILENAME_CHARS:
        text = text.replace(character, "_")
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"_+", "_", text)
    text = text.strip(" _." )
    return text or "Dataset"