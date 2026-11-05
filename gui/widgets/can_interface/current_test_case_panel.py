from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from gui.themes.styles.controls.label_style import fn_label_style
from gui.themes.styles.controls.scrollbar_style import fn_apply_scrollbar_style
from gui.themes.theme_manager import ThemeManager
from gui.widgets.controls.action_button import ActionButton
from gui.widgets.controls.primary_label import PrimaryLabel

# (key, caption), top to bottom.
FIELDS = (
    ("Step", "Step"),
    ("Result", "Result"),
    ("Name", "Name"),
    ("ECU", "ECU"),
    ("Payload", "Payload (HEX)"),
    ("Delay", "Delay (ms)"),
    ("Repeat", "Repeat (times)"),
    ("Expected", "Expected Response (HEX)"),
    ("Receive", "Receive Message (HEX)"),
    ("Bytes", "Number Byte"),
    ("Comment", "Comment"),
)

# Result text color tokens in the theme (colors.py).
RESULT_TEXT_TOKENS = {
    "Passed": "RESULT_PASSED_TEXT",
    "Failed": "RESULT_FAILED_TEXT",
    "Timeout": "RESULT_TIMEOUT_TEXT",
}

NOTHING = "—"

NO_SEQUENCE = "Select a sequence"


class CurrentTestCasePanel(QWidget):
    """Details of the selected row, one field per line; the list scrolls when it is too long."""

    def __init__(self):
        super().__init__()
        self._result = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.title = PrimaryLabel(NO_SEQUENCE)
        self.title.setTextFormat(Qt.PlainText)
        self.title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.empty = PrimaryLabel("Select a diagnostic row.")
        layout.addWidget(self.title)
        layout.addWidget(self.empty)

        self.fields = QWidget()
        grid = QGridLayout(self.fields)
        grid.setContentsMargins(0, 0, 8, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        self.labels, self.values = {}, {}
        for row, (key, caption) in enumerate(FIELDS):
            label = PrimaryLabel(caption)
            value = PrimaryLabel(NOTHING)
            value.setTextFormat(Qt.PlainText)
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
            value.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            value.setMinimumWidth(40)
            grid.addWidget(label, row, 0, Qt.AlignTop)
            grid.addWidget(value, row, 1)
            self.labels[key], self.values[key] = label, value
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(len(FIELDS), 1)

        self.scroll = QScrollArea()
        self.scroll.setWidget(self.fields)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.scroll.viewport().setAutoFillBackground(False)
        self.fields.setAutoFillBackground(False)
        layout.addWidget(self.scroll, 1)

        # Kept for the DLL controller (it still writes its status here) but no longer shown.
        self.dll_status = PrimaryLabel("DLL: select a diagnostic row and Vehicle.")
        self.dll_status.setTextFormat(Qt.PlainText)
        self.dll_status.setWordWrap(True)
        self.dll_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.dll_status.setVisible(False)
        layout.addWidget(self.dll_status)

        self.security_status = PrimaryLabel('Idle; 27 02 disabled: DLL ABI/offline verification pending.')
        self.security_status.setTextFormat(Qt.PlainText)
        self.security_status.setWordWrap(True)
        self.security_status.setAccessibleName('SecurityAccess session status')
        self.security_status.setVisible(False)
        layout.addWidget(self.security_status)
        self.key_result = PrimaryLabel('27 02: —')
        self.key_result.setTextFormat(Qt.PlainText)
        self.key_result.setWordWrap(True)
        self.key_result.setAccessibleName('SecurityAccess key submission result')
        self.key_result.setVisible(False)
        layout.addWidget(self.key_result)
        self.btn_unlock_l1 = ActionButton('Unlock L1', width=110, height=30)
        self.btn_unlock_l1.setAccessibleName('Calculate and submit SecurityAccess Level 1 key')
        self.btn_unlock_l1.setEnabled(False)
        self.btn_unlock_l1.setToolTip('Request a seed with 27 01 first; a verified provider is required.')
        self.btn_unlock_l1.setVisible(False)
        layout.addWidget(self.btn_unlock_l1, 0, Qt.AlignLeft)
        fn_apply_scrollbar_style(self.scroll)
        self.display_step()

    def set_sequence_name(self, name):
        """The heading is the name of the sequence being edited."""
        self.title.setText(name or NO_SEQUENCE)
        self.title.setToolTip(name or "")

    def display_step(self, step=None, total=0, *, result="", receive="", ecu_address=()):
        """Show one row. `result` is the raw outcome ("" = none yet), `ecu_address` is (request, response)."""
        self.empty.setVisible(step is None)
        self.scroll.setVisible(step is not None)
        if step is None:
            for value in self.values.values():
                value.setText(NOTHING)
            self._set_result("")
            return
        ecu = " - ".join((step.ecu, *(f"{name} {address}" for name, address in zip(("Req", "Resp"), ecu_address))))
        shown = dict(
            Step=f"{step.step} / {total}",
            Name=step.sequence_name,
            ECU=ecu,
            Payload=step.request,
            Delay="" if step.delay_ms is None else str(step.delay_ms),
            Repeat=str(step.repeat),
            Expected=step.expected_response,
            Receive=receive,
            Bytes=str(len(receive.split())) if receive.split() else "",
            Comment=step.comment,
        )
        for key, text in shown.items():
            self.values[key].setText(text or NOTHING)
            self.values[key].setToolTip(escape(text) if text else "")
        self._set_result(result)

    def _set_result(self, outcome):
        self._result = outcome if outcome in RESULT_TEXT_TOKENS else ""
        self.values["Result"].setText(self._result.upper() or NOTHING)
        self._style_result()

    def _style_result(self):
        value = self.values["Result"]
        style = fn_label_style()
        token = RESULT_TEXT_TOKENS.get(self._result)
        if token:
            style += f"QLabel {{ color: {getattr(ThemeManager.fn_colors(), token)}; font-weight: bold; }}"
        value.setStyleSheet(style)

    def fn_refresh_theme(self):
        self.title.fn_refresh_theme()
        self.empty.fn_refresh_theme()
        self.dll_status.fn_refresh_theme()
        self.security_status.fn_refresh_theme()
        self.key_result.fn_refresh_theme()
        self.btn_unlock_l1.fn_refresh_theme()
        fn_apply_scrollbar_style(self.scroll)
        for widget in (*self.labels.values(), *self.values.values()):
            widget.fn_refresh_theme()
        self._style_result()
