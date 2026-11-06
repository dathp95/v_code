from PySide6.QtWidgets import QMessageBox

from core.services.report_service import ReportService
from gui.widgets.controls.export_toast import show_export_toast


class ReportController:

    def __init__(self):

        self.report_service = ReportService()

    # ==========================================
    # Public
    # ==========================================

    def fn_export(
            self,
            parent,
            pipeline_result,
            vehicle_name: str = "",
        ):
        if pipeline_result is None:
            QMessageBox.warning(
                parent,
                "Export",
                "Please run analysis before exporting.",
            )
            return

        try:
            output_file = self.report_service.fn_export(
                parent=parent,
                pipeline_result=pipeline_result,
                vehicle_name=vehicle_name,
            )

            if output_file is None:
                return

            show_export_toast(parent, output_file, title="Excel report saved")

        except Exception as error:
            QMessageBox.critical(
                parent,
                "Export Error",
                str(error),
            )