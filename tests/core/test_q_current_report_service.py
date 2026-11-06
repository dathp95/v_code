import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.services.q_current_report_service import (
    QCurrentReportService,
    sanitize_dataset_name,
)


class QCurrentReportServiceTests(unittest.TestCase):

    def test_sanitizes_dataset_names_for_windows_safe_report_files(self):
        self.assertEqual(sanitize_dataset_name("VF8_Sleep_Current.db"), "VF8_Sleep_Current")
        self.assertEqual(sanitize_dataset_name("VF6_Test.db"), "VF6_Test")
        self.assertEqual(sanitize_dataset_name("VF8 / Sleep:Test.db"), "VF8_Sleep_Test")
        self.assertEqual(sanitize_dataset_name(""), "Dataset")

    def test_default_report_path_uses_date_folder_and_timestamped_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = QCurrentReportService(
                report_root=Path(tmpdir),
                now_provider=lambda: datetime(2026, 9, 29, 8, 7, 6),
            )

            output_path = service.fn_default_report_path("VF8_Sleep_Current.db")

            self.assertEqual(output_path.parent, Path(tmpdir) / "29-09-2026")
            self.assertEqual(
                output_path.name,
                "QCurrent_VF8_Sleep_Current_Report_20260929_080706.xlsx",
            )
            self.assertTrue(output_path.parent.exists())

    def test_choose_output_file_appends_xlsx_and_cancel_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            selected = str(Path(tmpdir) / "custom_report")
            service = QCurrentReportService(
                report_root=Path(tmpdir),
                now_provider=lambda: datetime(2026, 9, 29, 8, 7, 6),
            )
            with patch(
                "core.services.q_current_report_service.ask_save_path",
                return_value=selected,
            ):
                output_path = service.fn_choose_output_file(None, "VF6_Test.db")
            self.assertEqual(output_path, Path(selected).with_suffix(".xlsx"))

            with patch(
                "core.services.q_current_report_service.ask_save_path",
                return_value="",
            ):
                self.assertIsNone(service.fn_choose_output_file(None, "VF6_Test.db"))

    def test_export_returns_none_on_cancel_and_raises_on_permission_error(self):
        calls = []
        service = QCurrentReportService(exporter=lambda *_args: calls.append("export") or True)
        with patch.object(service, "fn_choose_output_file", return_value=None):
            self.assertIsNone(service.fn_export(None, SimpleNamespace(dataset_name="VF6_Test")))
        self.assertEqual(calls, [])

        failing_service = QCurrentReportService(exporter=lambda *_args: False)
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "report.xlsx"
            with patch.object(failing_service, "fn_choose_output_file", return_value=target):
                with self.assertRaises(PermissionError):
                    failing_service.fn_export(None, SimpleNamespace(dataset_name="VF6_Test"))


if __name__ == "__main__":
    unittest.main()