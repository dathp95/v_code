import os
import unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from gui.widgets.can_interface.can_monitor_panel import CanMonitorPanel


class CanMonitorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])

    def test_empty_honest_shell_and_bounded_filtered_display(self):
        from core.can_interface_view import CanFrameView
        monitor=CanMonitorPanel(capacity=2)
        self.addCleanup(monitor.deleteLater)
        self.assertEqual(monitor.table.model().rowCount(),0)
        self.assertFalse(monitor.btn_export.isEnabled())
        self.assertFalse(monitor.btn_start.isEnabled())
        self.assertFalse(monitor.btn_stop.isEnabled())
        self.assertFalse(hasattr(monitor,'status'))
        monitor.append_frame_batch([CanFrameView(1.0,'TX',0x123,1,b'\x01'), CanFrameView(2.0,'RX',0x456,1,b'\x02'),CanFrameView(3.0,'RX',0x123,1,b'\x03')])
        self.assertEqual((monitor.frames,monitor.displayed,monitor.dropped),(3,2,1))
        monitor.edit_can_id.setText('123')
        self.assertEqual(monitor.table.model().rowCount(),1)
        self.assertEqual(monitor.table.model().index(0,4).data(),'03')
        monitor.cmb_direction.setCurrentText('TX')
        self.assertEqual(monitor.displayed,0)
        monitor.edit_can_id.setText('invalid')
        self.assertEqual(monitor.displayed,0)
        monitor.clear_display()
        self.assertEqual((monitor.frames,monitor.displayed,monitor.dropped),(0,0,0))


    def frames(self):
        from core.can_interface_view import CanFrameView
        return [CanFrameView(1.0,'TX',0x688,8,bytes.fromhex('0322F10800000000')),
                CanFrameView(2.0,'RX',0x608,8,bytes.fromhex('037F2231AAAAAAAA')),
                CanFrameView(3.0,'TX',0x681,8,bytes.fromhex('0322F10800000000'))]

    def test_filter_matches_can_id_or_data_hex(self):
        monitor=CanMonitorPanel()
        self.addCleanup(monitor.deleteLater)
        monitor.append_frame_batch(self.frames())
        for text,expected in (('688',1),('0x688',1),('7f 22',1),('7F22',1),('aaaa',1),('0322',2),('22 f1 08',2),('ZZ',0),('',3)):
            monitor.edit_can_id.setText(text)
            self.assertEqual(monitor.displayed,expected,text)
            self.assertEqual(len(monitor.retained_frames(filtered=True)),expected,text)
        self.assertEqual(monitor.feedback.text(),'')

    def test_view_follows_new_frames_unless_the_user_scrolled_up(self):
        from core.can_interface_view import CanFrameView
        monitor=CanMonitorPanel()
        self.addCleanup(monitor.deleteLater)
        monitor.resize(500,300);monitor.show();self.app.processEvents()
        bar=monitor.table.verticalScrollBar()
        monitor.append_frame_batch([CanFrameView(i/10,'RX',0x601,1,b'') for i in range(100)])
        self.app.processEvents()
        self.assertGreater(bar.maximum(),0)
        self.assertEqual(bar.value(),bar.maximum())
        monitor.append_frame_batch([CanFrameView(20+i/10,'RX',0x601,1,b'') for i in range(20)])
        self.app.processEvents()
        self.assertEqual(bar.value(),bar.maximum())
        bar.setValue(0)
        monitor.append_frame_batch([CanFrameView(30.0,'RX',0x601,1,b'')])
        self.app.processEvents()
        self.assertEqual(bar.value(),0)

    def test_toolbar_layout_buttons_and_no_status_text(self):
        monitor=CanMonitorPanel()
        self.addCleanup(monitor.deleteLater)
        monitor.fn_refresh_theme();monitor.resize(700,300);monitor.show();self.app.processEvents()
        buttons=(monitor.btn_start,monitor.btn_stop,monitor.btn_clear,monitor.btn_export,monitor.btn_logs)
        self.assertEqual([b.text() for b in buttons],['START','STOP','Clear','Export CSV','Open Logs'])
        xs=[b.mapTo(monitor,b.rect().topLeft()).x() for b in buttons]
        self.assertEqual(xs,sorted(xs))
        self.assertIn('background-color: #D13438',monitor.btn_stop.styleSheet())
        self.assertIn('color: #FFFFFF',monitor.btn_stop.styleSheet())
        self.assertIn('#0078D4',monitor.btn_start.styleSheet())
        monitor.set_monitoring_state('Monitoring')
        self.assertFalse(hasattr(monitor,'status'))

    def test_blf_and_csv_dialogs_start_in_the_day_folder(self):
        import tempfile
        from datetime import datetime
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from gui.controllers import can_recording_controller as module
        controller = SimpleNamespace(panel=None, vehicle_name=lambda: 'VF5NP')
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            logs = Path(directory) / 'CAN_Interface_Logs'
            seen = []
            with patch.object(module, 'CAN_INTERFACE_LOG_DIR', logs),                     patch.object(module, 'ask_save_path', side_effect=lambda *a, **k: (seen.append(str(a[2])) or '')):
                for suffix in ('blf', 'csv'):
                    self.assertEqual(module.CanRecordingController.destination(controller, suffix), (None, False))
            today = datetime.now().strftime('%d-%m-%Y')
            self.assertTrue((logs / today).is_dir())
            for path, suffix in zip(seen, ('blf', 'csv')):
                self.assertEqual(Path(path).parent, logs / today)
                self.assertTrue(path.endswith('.' + suffix))
