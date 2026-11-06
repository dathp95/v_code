import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QWidget


class ExportPopupSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_log_analyzer_export_shows_the_open_folder_open_file_popup(self):
        from gui.controllers.report_controller import ReportController
        parent = QWidget()
        self.addCleanup(parent.deleteLater)
        controller = ReportController()
        saved = Path('C:/x/day/report.xlsx')
        with patch.object(controller.report_service, 'fn_export', return_value=saved), \
                patch('gui.controllers.report_controller.show_export_toast') as toast, \
                patch('gui.controllers.report_controller.QMessageBox.information') as box:
            controller.fn_export(parent, SimpleNamespace(), 'VF5NP')
        toast.assert_called_once()
        self.assertEqual(toast.call_args.args[:2], (parent, saved))
        box.assert_not_called()

    def test_cancelled_log_analyzer_export_shows_nothing(self):
        from gui.controllers.report_controller import ReportController
        parent = QWidget()
        self.addCleanup(parent.deleteLater)
        controller = ReportController()
        with patch.object(controller.report_service, 'fn_export', return_value=None), \
                patch('gui.controllers.report_controller.show_export_toast') as toast:
            controller.fn_export(parent, SimpleNamespace(), '')
        toast.assert_not_called()

    def test_csv_export_of_the_can_monitor_shows_the_popup(self):
        import tempfile
        from gui.controllers.can_recording_controller import CanRecordingController
        from core.can_interface_view import CanFrameView
        from gui.widgets.can_interface.can_monitor_panel import CanMonitorPanel
        panel = CanMonitorPanel()
        self.addCleanup(panel.deleteLater)
        panel.append_frame_batch([CanFrameView(1.0, 'RX', 0x601, 1, b'\x01')])
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            target = Path(directory) / 'frames.csv'
            controller = SimpleNamespace(panel=panel, destination=lambda suffix: (target, False))
            with patch('gui.controllers.can_recording_controller.show_export_toast') as toast:
                CanRecordingController.export_csv(controller)
            self.assertTrue(target.exists())
        toast.assert_called_once()
        self.assertEqual(toast.call_args.args[:2], (panel, target))


if __name__ == '__main__':
    unittest.main()
