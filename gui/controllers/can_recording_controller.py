"""GUI dialogs/status only; native CAN and BLF file owners stay outside widgets."""
from datetime import datetime
from pathlib import Path
import re

from PySide6.QtCore import QObject,QTimer
from PySide6.QtWidgets import QFileDialog,QMessageBox
from config.paths import CAN_INTERFACE_LOG_DIR
from services.can import CANConnectionState
from services.can.can_csv_export import export_retained_csv


def suggested_name(vehicle,suffix):
    safe=re.sub(r'[^\w.-]+','_',vehicle or 'capture').strip(' ._')[:64] or 'capture'
    return f'V_CODE_CAN_{safe}_{datetime.now():%Y%m%d_%H%M%S_%f}.{suffix}'


class CanRecordingController(QObject):
    def __init__(self,panel,task,service,vehicle_name,parent=None):
        super().__init__(parent)
        self.panel,self.task,self.service,self.vehicle_name=panel,task,service,vehicle_name
        panel.btn_start.clicked.connect(self.start_recording)
        panel.btn_stop.clicked.connect(self.stop_recording)
        panel.btn_export.clicked.connect(self.export_csv)
        self.timer=QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        task.monitoring_changed.connect(self.refresh)
        task.started.connect(self.refresh)
        task.completed.connect(self.refresh)
        task.failed.connect(self.refresh)
        task.connection_fault.connect(self.refresh)
        task.recording_start_finished.connect(self._started)
        self.refresh()

    def refresh(self,*_):
        connected=(self.service.snapshot.state==CANConnectionState.CONNECTED
                   and self.task.monitoring and not self.task.running)
        self.panel.set_recording_snapshot(self.task.recorder.snapshot,connected)
        if self.task.recording_start_pending: self.panel.btn_start.setEnabled(False)

    def _started(self,error):
        if error: self.panel.show_export_notice(f'BLF not started: {error}')
        self.refresh()

    def destination(self,suffix):
        CAN_INTERFACE_LOG_DIR.mkdir(parents=True,exist_ok=True)
        filename,_=QFileDialog.getSaveFileName(self.panel,f'Export {suffix.upper()}',
            str(CAN_INTERFACE_LOG_DIR/suggested_name(self.vehicle_name(),suffix)),
            f'{suffix.upper()} (*.{suffix})',options=QFileDialog.DontConfirmOverwrite)
        if not filename: return None,False
        path=Path(filename)
        if path.suffix.lower()!=f'.{suffix}': path=path.with_suffix(f'.{suffix}')
        overwrite=path.exists()
        if overwrite and QMessageBox.question(self.panel,'Replace existing file?',
                f'Replace {path.name}?',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:
            return None,False
        return path,overwrite

    def stop_recording(self):
        if self.task.recorder.snapshot.state=='RECORDING': self.task.stop_recording()
        self.refresh()

    def start_recording(self):
        snapshot=self.task.recorder.snapshot
        if snapshot.state=='RECORDING' or snapshot.busy: return
        try:
            path,overwrite=self.destination('blf')
            if path is not None: self.task.start_recording(path,overwrite=overwrite)
        except (OSError,ValueError,RuntimeError) as error:
            self.panel.show_export_notice(f'BLF not started: {error}')
        self.refresh()

    def export_csv(self):
        frames=self.panel.retained_frames(filtered=True)
        if not frames:
            self.panel.show_export_notice('No retained frames match the current filters.');return
        try:
            path,overwrite=self.destination('csv')
            if path is None: return
            count=export_retained_csv(path,frames,overwrite=overwrite)
            self.panel.show_export_notice(f'Exported {count} retained frames. CSV is not a complete bus log.')
        except (OSError,ValueError) as error:
            self.panel.show_export_notice(f'CSV export failed: {error}')

    def close(self):
        self.timer.stop()
