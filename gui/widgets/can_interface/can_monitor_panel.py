from collections import deque
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget, QSizePolicy
from core.can_interface_view import CanFrameView
from gui.widgets.controls.action_button import ActionButton
from gui.widgets.controls.primary_combobox import PrimaryComboBox
from gui.widgets.controls.primary_lineedit import PrimaryLineEdit
from gui.widgets.controls.primary_label import PrimaryLabel
from gui.widgets.can_interface.can_monitor_model import CanMonitorTable
from gui.widgets.can_interface.panel_theme import apply_panel_theme


class CanMonitorPanel(QWidget):
    def __init__(self, capacity=2000):
        super().__init__()
        if isinstance(capacity, bool) or not isinstance(capacity, int) or not 1 <= capacity <= 10000:
            raise ValueError("Monitor display capacity must be in range 1..10000.")
        self._buffer = deque(maxlen=capacity)
        self._monitoring_state='Not monitoring'
        self._recording_error=''
        self._export_notice=''
        self._filter_error=''
        self.frames = self.displayed = self.dropped = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        header = QHBoxLayout()
        self.title = PrimaryLabel("CAN Monitor")
        self.title.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred)
        self.title.setMinimumWidth(80)
        self.btn_start = ActionButton("START", width=70, height=30, variant="primary")
        self.btn_stop = ActionButton("STOP", width=70, height=30, variant="stop")
        self.btn_clear = ActionButton("Clear", width=55, height=30)
        self.btn_export = ActionButton("Export CSV", width=85, height=30)
        self.btn_logs = ActionButton("Open Logs", width=85, height=30)
        self.btn_export.setEnabled(False)
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.btn_export.setToolTip("Export retained frames matching the view filters, not a complete raw log.")
        self.btn_start.setToolTip("Connect a CAN channel to record raw traffic (BLF) independently of this view.")
        self.btn_stop.setToolTip("Stop the BLF recording.")
        self.btn_logs.setToolTip("Open diagnostic anomalies and application logs folder.")
        header.addWidget(self.title, 1)
        for button in (self.btn_start, self.btn_stop, self.btn_clear, self.btn_export, self.btn_logs):
            header.addWidget(button)
        filters = QHBoxLayout()
        self.edit_can_id = PrimaryLineEdit("Filter by CAN ID or Data (HEX)")
        self.cmb_direction = PrimaryComboBox(minimum_height=30)
        self.cmb_direction.addItems(("All", "TX", "RX"))
        filters.addWidget(self.edit_can_id, 1)
        filters.addWidget(self.cmb_direction)
        self.table = CanMonitorTable()
        for column, width in enumerate((85, 45, 85, 45, 180)): self.table.setColumnWidth(column, width)
        self.feedback = PrimaryLabel("")
        self.feedback.setWordWrap(True)
        self.feedback.hide()
        self.counters = PrimaryLabel("")
        layout.addLayout(header)
        layout.addLayout(filters)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.feedback)
        layout.addWidget(self.counters)
        self.btn_clear.clicked.connect(self.clear_display)
        self.btn_logs.clicked.connect(self._open_logs)
        self.edit_can_id.textChanged.connect(self._render)
        self.cmb_direction.currentTextChanged.connect(self._render)
        self._render()

    def append_frame_batch(self, frames, *, dropped=0):
        if QThread.currentThread() != self.thread():
            raise RuntimeError("Monitor view updates must run on the GUI thread.")
        try:
            self.dropped+=dropped
            for frame in frames:
                if not isinstance(frame, CanFrameView):
                    raise TypeError("Expected CanFrameView presentation data.")
                if len(self._buffer) == self._buffer.maxlen:
                    self.dropped += 1
                self._buffer.append(frame)
                self.frames += 1
        finally:
            self._render()

    def clear_display(self):
        self._buffer.clear()
        self.frames = self.displayed = self.dropped = 0
        self._render()

    def set_monitoring_state(self, state):
        if state not in ('Not monitoring','Captured during request','Capture stopped','Monitoring','Stopped'):
            raise NotImplementedError("Continuous monitoring is not implemented.")
        self._monitoring_state=state

    def set_recording_snapshot(self,snapshot,connected):
        state=snapshot.state
        self._recording_error=snapshot.error
        self.btn_start.setEnabled(state!='RECORDING' and connected and not snapshot.busy)
        self.btn_stop.setEnabled(state=='RECORDING')
        detail=(f'{snapshot.path}\nState: {state}; captured: {snapshot.captured}; written: {snapshot.written}; '
                f'dropped/rejected: {snapshot.dropped}; paired echoes: {snapshot.echoes}; '
                f'adjusted timestamps: {snapshot.adjusted_timestamps}; fallback: {snapshot.fallback_timestamps}; '
                f'finalized: {snapshot.finalized}\n{snapshot.error}')
        self.btn_stop.setToolTip(detail if state=='RECORDING' else 'Stop the BLF recording.')
        self._feedback()

    def show_export_notice(self,text):
        self._export_notice=text
        self._feedback()

    def _feedback(self):
        text='\n'.join(value for value in (self._filter_error,self._recording_error,self._export_notice) if value)
        self.feedback.setText(text)
        self.feedback.setVisible(bool(text))

    def _matcher(self):
        """Match a typed HEX fragment against the CAN ID (exact) or anywhere in the data bytes."""
        text=self.edit_can_id.text().strip().upper()
        text=text[2:] if text.startswith('0X') else text
        compact=''.join(text.split())
        if not compact: return None
        try: can_id=int(compact,16)
        except ValueError: can_id=None
        if can_id is not None and not 0<=can_id<=0x1FFFFFFF: can_id=None
        direction=self.cmb_direction.currentText()
        return lambda frame:((can_id is not None and frame.can_id==can_id) or compact in frame.data.hex().upper())

    def _visible_frames(self):
        matches=self._matcher()
        direction=self.cmb_direction.currentText()
        return [frame for frame in self._buffer if (matches is None or matches(frame))
                and (direction=='All' or frame.direction==direction)]

    def retained_frames(self,filtered=False):
        return tuple(self._visible_frames() if filtered else self._buffer)

    def set_logging_state(self, state, path=None):
        if state != "Stopped" or path is not None:
            raise NotImplementedError("BLF logging is unavailable in M03.")

    def _render(self, *_):
        frames = self._visible_frames()
        self._filter_error=''
        self._feedback()
        bar = self.table.verticalScrollBar()
        follow = bar.value() >= bar.maximum() - 2  # Stay put when the user scrolled up to read.
        self.table.model().set_frames(frames)
        if follow:
            self.table.scrollToBottom()
        self.displayed = len(frames)
        self.btn_export.setEnabled(bool(self._buffer))
        self.counters.setText(f"Frames: {self.frames}    Displayed: {self.displayed}    Dropped: {self.dropped}")

    def _open_logs(self):
        from services.logging_service import open_logs_folder
        open_logs_folder()

    def fn_refresh_theme(self):
        apply_panel_theme(self, "canMonitorPanel")
        self.title.fn_refresh_theme()
        self.table.fn_refresh_theme()
        for widget in (self.btn_start, self.btn_stop, self.btn_clear, self.btn_export, self.btn_logs, self.edit_can_id, self.cmb_direction, self.feedback, self.counters):
            widget.fn_refresh_theme()
        from gui.themes.styles.controls.scrollbar_style import fn_apply_scrollbar_style
        fn_apply_scrollbar_style(self.cmb_direction.view())
