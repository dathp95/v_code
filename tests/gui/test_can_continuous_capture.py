import time
import unittest
from pathlib import Path
import tempfile
import can
from PySide6.QtCore import QTimer
from unittest.mock import patch

from tests.gui import test_can_diagnostic_execution as fixtures


class ContinuousCaptureTests(unittest.TestCase):
    setUpClass=classmethod(fixtures.CanDiagnosticExecutionTests.setUpClass.__func__)
    setUp=fixtures.CanDiagnosticExecutionTests.setUp
    wait=fixtures.CanDiagnosticExecutionTests.wait
    click=fixtures.CanDiagnosticExecutionTests.click
    outcome=fixtures.CanDiagnosticExecutionTests.outcome

    def test_idle_then_vin_then_idle_single_owner(self):
        self.bus.rx('01 01',0x760)
        self.bus.rx('01 01',0x760)
        self.wait(lambda:self.tab.monitor_panel.frames>=2)
        self.assertEqual(self.bus.sent,[])
        self.click();self.wait(lambda:self.outcome()=='Passed')
        before=self.tab.monitor_panel.frames
        self.bus.rx('01 02',0x760)
        self.wait(lambda:self.tab.monitor_panel.frames>before)
        self.assertEqual(len(set(self.bus.threads)),1)
        self.tab.disconnect_can();self.wait(lambda:not self.tab._connection_task.running)

    def recording(self):
        directory=tempfile.TemporaryDirectory(dir=Path.cwd());self.addCleanup(directory.cleanup)
        self.addCleanup(self.tab._connection_task.shutdown)
        path=Path(directory.name)/'real-service-fake-bus.blf'
        self.tab._connection_task.start_recording(path)
        self.wait(lambda:self.tab._connection_task.recorder.snapshot.state=='RECORDING')
        return path

    def test_blf_idle_vin_echo_filter_clear_and_disconnect_round_trip(self):
        path=self.recording();task=self.tab._connection_task
        self.bus.rx('01 01',0x760);self.bus.rx('01 01',0x760)
        self.wait(lambda:task.recorder.snapshot.written>=2)
        self.tab.monitor_panel.edit_can_id.setText('760')
        self.click();self.wait(lambda:self.outcome()=='Passed')
        tx=self.bus.sent[0]
        self.bus.queue.append(can.Message(timestamp=time.time(),arbitration_id=tx.arbitration_id,
            data=tx.data,is_extended_id=False,is_rx=False,channel=0))
        self.bus.rx('01 02',0x760)
        self.wait(lambda:task.recorder.snapshot.written>=9 and task.recorder.snapshot.echoes==1)
        self.tab.monitor_panel.clear_display()
        self.tab.disconnect_can();self.wait(lambda:not task.running)
        snapshot=task.recorder.snapshot
        self.assertTrue(snapshot.complete,snapshot)
        with can.BLFReader(path) as reader: messages=list(reader)
        self.assertEqual(len(messages),9)
        self.assertEqual([m.arbitration_id for m in messages[:2]],[0x760]*2)
        diagnostic=[m for m in messages if m.arbitration_id in (0x681,0x601)]
        self.assertEqual([m.is_rx for m in diagnostic],[False,True,False,True,True])
        self.assertEqual([bytes(m.data) for m in diagnostic],[bytes.fromhex(s) for s in (
            '03 22 F1 90 00 00 00 00','10 14 62 F1 90 4D 47 55','30 00 00 00 00 00 00 00',
            '21 56 35 4A 54 4C 58 54','22 4A 39 39 39 37 34 31')])
        self.assertTrue(all(m.channel==0 for m in messages))
        self.assertEqual([m.timestamp for m in messages],sorted(m.timestamp for m in messages))

    def test_shutdown_finalizes_writer_and_idle_unplug_is_incomplete(self):
        path=self.recording();task=self.tab._connection_task
        self.bus.rx('01 02',0x760);self.wait(lambda:task.recorder.snapshot.written>=1)
        self.bus.mode='recv_error'
        self.wait(lambda:not task.monitoring and not task.recorder.snapshot.busy)
        self.assertFalse(task.recorder.snapshot.complete)
        self.assertIn('capture stopped unexpectedly',task.recorder.snapshot.error)
        self.assertTrue(self.service.snapshot.rediscovery_required)
        task.shutdown()
        self.assertFalse(task.alive)
        with can.BLFReader(path) as reader: self.assertEqual(len(list(reader)),1)

    def test_unplugging_the_adapter_after_start_stops_the_recording_by_itself(self):
        directory = tempfile.TemporaryDirectory(dir=Path.cwd()); self.addCleanup(directory.cleanup)
        self.addCleanup(self.tab._connection_task.shutdown)
        path = Path(directory.name) / 'unplugged.blf'
        controller = self.tab.recording_controller; panel = self.tab.monitor_panel; task = self.tab._connection_task
        controller.refresh()
        with patch.object(controller, 'destination', return_value=(path, False)):
            panel.btn_start.click()  # START, and STOP is never pressed.
        self.wait(lambda: task.recorder.snapshot.state == 'RECORDING')
        self.bus.rx('01 02', 0x760); self.wait(lambda: task.recorder.snapshot.written >= 1)
        self.bus.mode = 'recv_error'  # USB-CAN pulled out.
        self.wait(lambda: task.recorder.snapshot.state != 'RECORDING' and not task.recorder.snapshot.busy)
        controller.refresh()
        self.assertFalse(task.monitoring)
        self.assertFalse(panel.btn_stop.isEnabled())  # Nothing left to stop.
        self.assertFalse(panel.btn_start.isEnabled())  # No adapter: START waits for a new connection.
        self.assertIn('capture stopped unexpectedly', panel.feedback.text())
        self.assertTrue(self.service.snapshot.rediscovery_required)
        self.assertEqual(self.bus.close_count, 1)
        with can.BLFReader(path) as reader:  # The file was closed properly and keeps what was captured.
            self.assertEqual(len(list(reader)), 1)

    def test_shutdown_while_recording_and_busy_uds(self):
        path=self.recording();task=self.tab._connection_task
        self.bus.mode='pending';self.click();self.wait(lambda:len(self.bus.sent)>0)
        task.shutdown()
        self.assertFalse(task.alive)
        self.assertTrue(task.recorder.snapshot.complete,task.recorder.snapshot)
        self.assertEqual(self.bus.close_count,1)
        with can.BLFReader(path) as reader: self.assertGreaterEqual(len(list(reader)),1)

    def test_ui_queue_overflow_does_not_drop_recording(self):
        path=self.recording();task=self.tab._connection_task
        self.tab.resize(1366,768);self.tab.show();self.app.processEvents()
        started=time.monotonic();ticks=[]
        heartbeat=QTimer();heartbeat.setInterval(10);heartbeat.timeout.connect(lambda:ticks.append(time.monotonic()))
        heartbeat.start();self.addCleanup(heartbeat.stop)
        for _ in range(5000): self.bus.rx('01 01',0x760)
        self.wait(lambda:task.recorder.snapshot.written==5000)
        elapsed=time.monotonic()-started
        heartbeat.stop()
        gaps=[b-a for a,b in zip([started]+ticks,ticks+[time.monotonic()])]
        self.assertLess(max(gaps),1.0)
        task._drain_frames()
        self.assertLessEqual(len(self.tab.monitor_panel._buffer),2000)
        self.assertGreater(self.tab.monitor_panel.dropped,0)
        task.stop_recording();self.wait(lambda:not task.recorder.snapshot.busy)
        self.assertTrue(task.recorder.snapshot.complete,task.recorder.snapshot)
        with can.BLFReader(path) as reader: self.assertEqual(len(list(reader)),5000)
        print(f'M04B fake capture: 5000 frames; {elapsed:.3f}s; max GUI heartbeat gap {max(gaps):.3f}s; writer dropped {task.recorder.snapshot.dropped}')

    def test_existing_buttons_start_stop_cancel_csv_and_theme(self):
        from gui.themes.theme_manager import ThemeManager
        from gui.themes.theme import ThemeType
        directory=tempfile.TemporaryDirectory(dir=Path.cwd());self.addCleanup(directory.cleanup)
        self.addCleanup(self.tab._connection_task.shutdown)
        path=Path(directory.name)/'button.blf';controller=self.tab.recording_controller
        panel=self.tab.monitor_panel;task=self.tab._connection_task
        controller.refresh();self.assertTrue(panel.btn_start.isEnabled());self.assertFalse(panel.btn_stop.isEnabled())
        with patch.object(controller,'destination',return_value=(None,False)): panel.btn_start.click()
        self.assertFalse(task.recorder.snapshot.busy)
        with patch.object(controller,'destination',return_value=(path,False)): panel.btn_start.click()
        self.wait(lambda:task.recorder.snapshot.state=='RECORDING')
        controller.refresh();self.assertTrue(panel.btn_stop.isEnabled());self.assertFalse(panel.btn_start.isEnabled())
        self.bus.rx('01 01',0x760);self.wait(lambda:panel.frames>=1)
        self.addCleanup(ThemeManager.fn_set_theme,ThemeManager.fn_theme())
        for theme in (ThemeType.LIGHT,ThemeType.DARK):
            ThemeManager.fn_set_theme(theme);self.tab.fn_refresh_theme();controller.refresh()
            self.tab.resize(1366,768);self.tab.show();self.app.processEvents()
            self.assertEqual(panel.retained_frames()[0].can_id,0x760)
        panel.btn_stop.click();self.wait(lambda:not task.recorder.snapshot.busy)
        controller.refresh();self.assertTrue(task.recorder.snapshot.complete)
        csv_path=path.with_suffix('.csv');panel.edit_can_id.setText('760')
        with patch.object(controller,'destination',return_value=(csv_path,False)): panel.btn_export.click()
        self.assertTrue(csv_path.read_bytes().startswith(b'\xef\xbb\xbf'))
        self.assertIn('1 retained frames',panel.feedback.text())

    def test_stale_response_and_malformed_acquisition_cannot_fake_success(self):
        self.recording();task=self.tab._connection_task
        self.bus.mode='silent';self.click();self.wait(lambda:len(self.bus.sent)>0)
        self.bus.queue.append(can.Message(timestamp=time.time()-1,arbitration_id=0x601,
            data=bytes.fromhex('03 62 F1 90 00 00 00 00'),is_extended_id=False))
        self.wait(lambda:task.recorder.snapshot.written>=2)
        self.assertNotEqual(self.outcome(),'Passed')
        self.bus.queue.append(can.Message(timestamp=time.time(),arbitration_id=0x760,dlc=1,data=b'12',is_extended_id=False))
        self.wait(lambda:task.recorder.snapshot.state=='INCOMPLETE')
        self.assertFalse(task.recorder.snapshot.complete)

    def test_fault_marks_recorder_before_native_close(self):
        self.recording();task=self.tab._connection_task
        original=self.bus.shutdown
        seen=[]
        def shutdown():
            task.recorder.stop();task.recorder.wait(3)
            seen.append(task.recorder.snapshot.complete)
            original()
        self.bus.shutdown=shutdown
        self.bus.mode='recv_error'
        self.wait(lambda:bool(seen))
        self.assertEqual(seen,[False])

    def test_stale_start_rejected_by_owner_and_immediate_stop_is_ordered(self):
        directory=tempfile.TemporaryDirectory(dir=Path.cwd());self.addCleanup(directory.cleanup)
        task=self.tab._connection_task;self.addCleanup(task.shutdown)
        path=Path(directory.name)/'queued.blf';replies=[]
        task.recording_start_finished.connect(replies.append)
        task._recording_start.emit(path,False,'disconnected-session')
        self.wait(lambda:bool(replies))
        self.assertIsInstance(replies[0],str)
        self.assertFalse(path.exists())
        task.start_recording(path);task.stop_recording()
        self.wait(lambda:path.exists() and not task.recorder.snapshot.busy)
        self.assertTrue(task.recorder.snapshot.complete,task.recorder.snapshot)
