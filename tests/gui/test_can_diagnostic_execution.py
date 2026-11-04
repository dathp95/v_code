import os
import sys
import time
import tempfile
import unittest
from collections import deque
from pathlib import Path
from threading import get_ident
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import can
from PySide6.QtWidgets import QApplication,QMessageBox
from PySide6.QtCore import QTimer
from gui.tabs.can_interface_tab import CANInterfaceTab
from gui.workers.can_connection_worker import CANConnectionOperation
from services.can import CANConfig,CANService,VectorBackend,CANConnectionState
from core.diagnostic_sequence import DiagnosticStep,DiagnosticTestCase
from core.diagnostic_request import DiagnosticSettings
from models.vehicle import Vehicle
from models.ecu import ECU
from repositories.can_interface_ui_store import CanInterfaceUiStore
from repositories.can_sequence_repository import CanSequenceRepository
from tests.services.test_isotp_transport import VIN


class BenchBus:
    def __init__(self,mode='vin'):
        self.mode=mode;self.queue=deque();self.sent=[];self.threads=[];self.closed=False;self.close_count=0

    def rx(self,text,can_id=0x601):
        data=bytes.fromhex(text)
        self.queue.append(can.Message(timestamp=time.time(),arbitration_id=can_id,is_extended_id=False,
                                      data=data,is_rx=True,channel=0))

    def send(self,msg,timeout):
        self.threads.append(get_ident())
        if self.mode == 'send_error': raise can.CanOperationError('hardware removed',error_code=129)
        self.sent.append(msg)
        if bytes(msg.data[:4]) == bytes.fromhex('03 22 F1 90'):
            if self.mode == 'vin':
                self.rx('01 AA 00 00 00 00 00 00',0x123)
                self.rx('10 14 62 F1 90 4D 47 55')
            elif self.mode == 'pending': self.rx('03 7F 22 78 00 00 00 00')
            elif self.mode == 'negative': self.rx('03 7F 22 31 00 00 00 00')
        elif msg.data[0] == 0x30 and self.mode == 'vin':
            self.rx('21 56 35 4A 54 4C 58 54');self.rx('22 4A 39 39 39 37 34 31')

    def recv(self,timeout):
        self.threads.append(get_ident())
        if self.mode == 'recv_error': raise can.CanOperationError('hardware removed',error_code=129)
        if self.mode == 'flood':
            return can.Message(timestamp=time.time(),arbitration_id=0x123,data=[1,2],is_extended_id=False)
        return self.queue.popleft() if self.queue else None

    def shutdown(self):
        self.threads.append(get_ident());self.close_count+=1;self.closed=True
        if self.mode == 'cleanup_error': raise can.CanOperationError('Cannot confirm shutdown')


class CanDiagnosticExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        directory=tempfile.TemporaryDirectory(dir=Path.cwd());self.addCleanup(directory.cleanup)
        root=Path(directory.name)
        self.bus=BenchBus()
        backend=VectorBackend(can_module=SimpleNamespace(Bus=lambda **kwargs:self.bus,Message=can.Message))
        self.service=CANService(backend)
        vehicle=Vehicle('BENCH',ecus=[ECU('BCM','681','601',resources={'dll':'UNUSED_NEVER_LOAD.dll'})])
        self.tab=CANInterfaceTab(self.service,vehicle_service=SimpleNamespace(list_vehicles=lambda:['BENCH'],load_vehicle=lambda _:vehicle),
                                 sequence_repository=CanSequenceRepository(root/'seq'),ui_store=CanInterfaceUiStore(root/'prefs'))
        self.addCleanup(self.tab.deleteLater);self.addCleanup(self.tab._connection_task.shutdown);self.addCleanup(self.tab.close)
        self.tab._on_sequence_selected(DiagnosticTestCase(1,'VIN','',True,[DiagnosticStep(1,'VIN','BCM','22 F1 90',repeat=5,expected_response='62 F1 90')]))
        self.tab.sequence_table.vehicle_selector.fn_set_vehicle('BENCH')
        self.tab._connection_task.start(CANConnectionOperation.CONNECT,CANConfig('vector',0,500000))
        self.wait(lambda:not self.tab._connection_task.running)

    def wait(self,predicate):
        deadline=time.monotonic()+5
        while not predicate() and time.monotonic()<deadline:
            self.app.processEvents();time.sleep(.002)
        self.assertTrue(predicate(),'Qt diagnostic task did not reach expected state')

    def click(self):
        self.tab.sequence_table.table.cellWidget(0,self.tab.sequence_table.COL_SEND).click()

    def outcome(self):
        return self.tab.sequence_table.table.item(0,self.tab.sequence_table.COL_RESULT).text()

    def test_real_pipeline_fake_bus_vin_one_request_monitor_and_theme(self):
        self.click();self.click()
        self.wait(lambda:self.outcome()=='Passed')
        panel=self.tab.sequence_table
        self.assertEqual(panel.table.item(0,panel.COL_RECEIVE).text(),VIN.hex(' ').upper())
        self.assertEqual([bytes(msg.data) for msg in self.bus.sent],[bytes.fromhex('03 22 F1 90 00 00 00 00'),bytes.fromhex('30 00 00 00 00 00 00 00')])
        self.assertEqual(panel.checked_step_ids(),())
        self.wait(lambda:self.tab.monitor_panel.frames>=6)
        self.assertTrue(any(frame.can_id==0x123 for frame in self.tab.monitor_panel._buffer))
        tx=[frame for frame in self.tab.monitor_panel._buffer if frame.direction=='TX']
        self.assertTrue(all(frame.tx_origin=='driver_accepted' for frame in tx))
        self.assertEqual(len(set(self.bus.threads)),1)
        self.assertNotEqual(self.bus.threads[0],get_ident())
        from gui.themes.theme_manager import ThemeManager
        from gui.themes.theme import ThemeType
        self.addCleanup(ThemeManager.fn_set_theme,ThemeManager.fn_theme())
        for theme in (ThemeType.DARK,ThemeType.LIGHT):
            ThemeManager.fn_set_theme(theme);self.tab.fn_refresh_theme();self.assertEqual(self.outcome(),'Passed')
        self.assertTrue(panel.btn_run.isEnabled())
        self.assertEqual(panel.btn_run.text(), 'RUN')
        self.assertEqual(panel.btn_export.text(), 'EXPORT')
        self.assertEqual(panel.btn_stop.text(), 'STOP')
        self.assertFalse(panel.btn_stop.isEnabled())
        self.tab.recording_controller.refresh()
        self.assertTrue(self.tab.monitor_panel.btn_blf.isEnabled())
        self.assertTrue(self.tab.monitor_panel.btn_export.isEnabled())

    def test_unsupported_security_and_unconfirmed_write_never_send(self):
        panel=self.tab.sequence_table
        for payload in ('27 02','27 09','27 01 00'):
            panel.table.item(0,panel.COL_REQUEST).setText(payload)
            panel.row_send_requested.emit(panel.step_ids[0])
            self.assertIn('Security Access',panel.notice.text())
        panel.table.item(0,panel.COL_REQUEST).setText('2E F1 90 01')
        with patch.object(QMessageBox,'question',return_value=QMessageBox.No):
            panel.row_send_requested.emit(panel.step_ids[0])
        self.assertEqual(self.bus.sent,[])

    def test_disconnect_and_edit_cancel_pending_without_stale_result(self):
        self.bus.mode='pending';self.click()
        self.wait(lambda:len(self.bus.sent)>0)
        heartbeat=[];QTimer.singleShot(0,lambda:heartbeat.append(True));self.app.processEvents();self.assertTrue(heartbeat)
        self.tab.sequence_table.table.item(0,self.tab.sequence_table.COL_REQUEST).setText('22 F1 91')
        self.wait(lambda:not self.tab._connection_task.diagnostic_busy)
        self.assertNotEqual(self.outcome(),'Passed')
        self.tab.disconnect_can();self.wait(lambda:not self.tab._connection_task.running)
        self.assertEqual(self.service.snapshot.state,CANConnectionState.DISCONNECTED)
        self.assertEqual(self.bus.close_count,1)

    def test_native_io_error_cleans_and_blocks_further_use(self):
        self.bus.mode='send_error';self.click()
        self.wait(lambda:self.outcome()=='Error')
        self.assertEqual(self.service.snapshot.state,CANConnectionState.DISCONNECTED)
        self.assertTrue(self.service.snapshot.rediscovery_required)
        self.assertEqual(self.bus.close_count,1)

    def test_receive_error_before_tx_and_uncertain_cleanup(self):
        self.bus.mode='recv_error';self.click()
        self.wait(lambda:self.outcome()=='Error')
        self.assertEqual(self.bus.sent,[])
        self.assertTrue(self.service.snapshot.rediscovery_required)
        self.assertEqual(self.bus.close_count,1)

    def test_timeout_retry_and_terminal_negative(self):
        self.tab.diagnostic_controller.settings=DiagnosticSettings(p2_s=.03,p2_star_s=.05,total_s=.2)
        self.bus.mode='silent';self.click()
        self.wait(lambda:self.outcome()=='Timeout')
        self.assertEqual(self.service.snapshot.state,CANConnectionState.CONNECTED)
        self.bus.mode='negative';self.click()
        self.wait(lambda:self.outcome()=='Failed')
        panel=self.tab.sequence_table
        self.assertEqual(panel.table.item(0,panel.COL_RECEIVE).text(),'7F 22 31')
        self.assertEqual(len(self.bus.sent),2)

    def test_disconnect_pending_and_shutdown_busy_close_once(self):
        self.bus.mode='pending';self.click()
        self.wait(lambda:len(self.bus.sent)>0)
        self.tab.disconnect_can()
        self.wait(lambda:not self.tab._connection_task.running)
        self.assertEqual(self.outcome(),'Cancelled')
        self.assertEqual(self.bus.close_count,1)
        self.tab._connection_task.shutdown()
        self.assertFalse(self.tab._connection_task.alive)
        self.assertEqual(self.bus.close_count,1)

    def test_document_reload_discards_result_and_close_cancels(self):
        self.bus.mode='pending';self.click();self.wait(lambda:len(self.bus.sent)>0)
        self.tab._on_sequence_selected(DiagnosticTestCase(2,'OTHER','',True,[DiagnosticStep(1,'OTHER','BCM','22 F1 91')]))
        self.wait(lambda:not self.tab._connection_task.diagnostic_busy)
        self.assertEqual(self.tab.sequence_table._runtime,{})
        self.click();self.wait(lambda:len(self.bus.sent)>1)
        self.tab.close();self.tab._connection_task.shutdown()
        self.assertFalse(self.tab._connection_task.alive)
        self.assertEqual(self.bus.close_count,1)

    def test_flood_queue_bounded_and_disconnect_responsive(self):
        from core.can_interface_view import CanFrameView
        task=self.tab._connection_task
        task._record_frames([CanFrameView(0,'RX',0x123,1,b'\x01')]*6000)
        self.assertEqual(len(task._frames),4096)
        self.assertEqual(task._frame_drops,1904)
        task._drain_frames()
        self.assertEqual(len(task._frames),3072)
        self.assertGreaterEqual(self.tab.monitor_panel.dropped,1904)
        self.bus.mode='flood';self.click()
        self.wait(lambda:len(self.bus.threads)>3)
        started=time.monotonic();self.tab.disconnect_can()
        self.wait(lambda:not task.running)
        self.assertLess(time.monotonic()-started,1.0)
        self.assertEqual(self.bus.sent,[])
        self.assertLessEqual(len(self.tab.monitor_panel._buffer),2000)

    def test_confirmation_yes_sends_one_write_and_security_denial_is_terminal(self):
        panel=self.tab.sequence_table
        panel.table.item(0,panel.COL_REQUEST).setText('2E F1 90 01')
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes): self.click()
        self.wait(lambda:len(self.bus.sent)>0)
        self.bus.rx('03 7F 2E 33 00 00 00 00')
        self.wait(lambda:self.outcome()=='Failed')
        self.assertEqual(panel.table.item(0,panel.COL_RECEIVE).text(),'7F 2E 33')
        self.assertEqual(len(self.bus.sent),1)

    def test_run_button_executes_sequence_top_to_bottom(self):
        panel = self.tab.sequence_table
        test_case = DiagnosticTestCase(
            1, "MULTI", "", True, [
                DiagnosticStep(1, "S1", "BCM", "22 F1 90", delay_ms=50, expected_response="62 F1 90"),
                DiagnosticStep(2, "S2", "BCM", "22 F1 90", delay_ms=50, expected_response="62 F1 90"),
            ]
        )
        self.tab._on_sequence_selected(test_case)
        panel.vehicle_selector.fn_set_vehicle("BENCH")

        self.assertTrue(panel.btn_run.isEnabled())
        self.assertFalse(panel.btn_stop.isEnabled())

        panel.btn_run.click()

        # While running, btn_run is disabled, btn_stop is enabled
        self.wait(lambda: not self.tab.diagnostic_controller._sequence_running)

        self.assertEqual(panel.table.item(0, panel.COL_RESULT).text(), "Passed")
        self.assertEqual(panel.table.item(1, panel.COL_RESULT).text(), "Passed")
        self.assertTrue(panel.btn_run.isEnabled())
        self.assertFalse(panel.btn_stop.isEnabled())

    def test_stop_button_halts_running_sequence(self):
        panel = self.tab.sequence_table
        test_case = DiagnosticTestCase(
            1, "MULTI_STOP", "", True, [
                DiagnosticStep(1, "S1", "BCM", "22 F1 90", delay_ms=500, expected_response="62 F1 90"),
                DiagnosticStep(2, "S2", "BCM", "22 F1 90", delay_ms=500, expected_response="62 F1 90"),
                DiagnosticStep(3, "S3", "BCM", "22 F1 90", delay_ms=500, expected_response="62 F1 90"),
            ]
        )
        self.tab._on_sequence_selected(test_case)
        panel.vehicle_selector.fn_set_vehicle("BENCH")

        panel.btn_run.click()
        self.assertTrue(self.tab.diagnostic_controller._sequence_running)

        # Stop while running
        panel.btn_stop.click()

        self.assertFalse(self.tab.diagnostic_controller._sequence_running)
        self.assertFalse(panel.btn_stop.isEnabled())
        self.assertTrue(panel.btn_run.isEnabled())
        # Step 3 should not have run
        self.assertEqual(panel.table.item(2, panel.COL_RESULT).text(), "—")


if __name__ == '__main__':
    unittest.main()
