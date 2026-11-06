from pathlib import Path
from datetime import datetime
from config.paths import LOG_ANALYZER_REPORT_DIR
from gui.widgets.controls.save_dialog import ask_save_path

# Lazy import in fn_export

import re

class ReportService:

    def __init__(self):

        pass

    # ==========================================
    # Public
    # ==========================================

    def fn_export(
            self,
            parent,
            pipeline_result,
            vehicle_name: str = "",
        ):
        output_file = self.fn_choose_output_file(
            parent,
            vehicle_name=vehicle_name,
        )

        if output_file is None:
            return None

        from core.report_export import export_workbook
        success = export_workbook(
            summary=pipeline_result["summary"],
            ecu_reports=pipeline_result["ecu_reports"],
            transactions=pipeline_result["transactions"],
            output_file=output_file,
        )

        if not success:
            return None

        return output_file
    
    
    def fn_choose_output_file(
            self,
            parent,
            vehicle_name: str = "",
        ):
        report_folder = self.fn_get_report_folder()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        safe_vehicle = re.sub(
            r'[<>:"/\\|?*\x00-\x1f]',
            "_",
            vehicle_name.strip(),
        ).strip(" .")

        if safe_vehicle:
            default_name = (
                f"EEIV_LogAnalyzer_Report_{safe_vehicle}_{timestamp}.xlsx"
            )
        else:
            default_name = f"EEIV_LogAnalyzer_Report_{timestamp}.xlsx"

        default_path = report_folder / default_name

        output_file = ask_save_path(
            parent,
            "Save Excel Report",
            default_path,
            "Excel Files (*.xlsx)",
        )

        if not output_file:
            return None

        if not output_file.lower().endswith(".xlsx"):
            output_file += ".xlsx"

        return output_file
    

    def fn_get_report_folder(self):

        today = datetime.now().strftime(

            "%d-%m-%Y"

        )

        report_folder = (LOG_ANALYZER_REPORT_DIR / today)

        report_folder.mkdir(

            parents=True,

            exist_ok=True

        )

        return report_folder