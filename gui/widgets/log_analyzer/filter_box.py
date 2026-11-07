from PySide6.QtWidgets import (
    QWidget,
    QLabel,
    QVBoxLayout,
    QHBoxLayout
)

from PySide6.QtCore import QEvent, Qt, QTimer, Signal

from gui.widgets.controls.primary_button import PrimaryButton
from gui.widgets.controls.primary_lineedit import PrimaryLineEdit
from gui.widgets.log_analyzer.layout_constants import FORM_ACTION_BUTTON_WIDTH
from gui.utils.payload_format import delete_payload_character_at_cursor
from gui.utils.payload_format import format_payload_input_with_cursor


class FilterBox(QWidget):

    # Filtering a large result table takes seconds, so typing is applied once the user pauses.
    DEBOUNCE_MS = 250

    filter_changed = Signal(str)
    refresh_clicked = Signal()

    def __init__(
            self,
            title = "",
        ):
        super().__init__()
        self.label_title = QLabel(title)
        self.edit_filter= PrimaryLineEdit(
                placeholder="Search ECU, NAME DIDS, Request, Response..."
                )
        self.btn_refresh = PrimaryButton(
            "Refresh"
        )
        self.btn_refresh.setFixedWidth(FORM_ACTION_BUTTON_WIDTH)
        self.btn_refresh.setEnabled(False)

        # Typing is debounced; clear()/set_text()/setText() and Enter apply at once.
        self._typing = False
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(self.DEBOUNCE_MS)
        self._debounce_timer.timeout.connect(self._emit_pending_filter)

        self._setup_ui()
        self._connect_signals()
        self.edit_filter.installEventFilter(self)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)

        filter_box_layout = QHBoxLayout()

        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(6)

        filter_box_layout.setContentsMargins(0, 0, 0, 0)
        filter_box_layout.setSpacing(8)

        # filter_box_layout.addWidget(self.label_title)
        filter_box_layout.addWidget(
            self.edit_filter,
            1,
        )
        filter_box_layout.addWidget(
            self.btn_refresh
        )

        main_layout.addLayout(filter_box_layout)

    def _connect_signals(self):
        self.edit_filter.textEdited.connect(self._on_user_edit)
        self.edit_filter.textEdited.connect(self._format_payload)
        self.edit_filter.textChanged.connect(self._on_text_changed)
        self.edit_filter.returnPressed.connect(self.fn_flush_filter)
        self.btn_refresh.clicked.connect(
            self.refresh_clicked.emit
        )

    def _on_user_edit(self, _value):
        """Qt emits textEdited right before textChanged for the user's own typing, never for setText()."""
        self._typing = True
        QTimer.singleShot(0, self._end_typing)  # The matching textChanged arrives before this runs.

    def _end_typing(self):
        self._typing = False

    def _on_text_changed(self, text):
        typing, self._typing = self._typing, False
        if typing:
            self._debounce_timer.start()  # Restart the wait on every keystroke.
            return
        self._debounce_timer.stop()  # A programmatic change replaces whatever typing was pending.
        self.filter_changed.emit(text)

    def _emit_pending_filter(self):
        self.filter_changed.emit(self.edit_filter.text())

    def fn_flush_filter(self):
        """Apply a pending typed filter right now (Enter)."""
        if self._debounce_timer.isActive():
            self._debounce_timer.stop()
            self._emit_pending_filter()

    def _format_payload(self, value):
        formatted, cursor = format_payload_input_with_cursor(
            value,
            self.edit_filter.cursorPosition(),
        )
        if formatted != value:
            self.edit_filter.blockSignals(True)
            self.edit_filter.setText(formatted)
            self.edit_filter.setCursorPosition(cursor)
            self.edit_filter.blockSignals(False)

    def eventFilter(self, watched, event):
        if (
                watched is self.edit_filter
                and event.type() == QEvent.KeyPress
                and event.key() == Qt.Key_Delete
                and not self.edit_filter.hasSelectedText()
            ):
            formatted, cursor = delete_payload_character_at_cursor(
                self.edit_filter.text(),
                self.edit_filter.cursorPosition(),
            )
            if formatted != self.edit_filter.text():
                self.edit_filter.blockSignals(True)
                self.edit_filter.setText(formatted)
                self.edit_filter.setCursorPosition(cursor)
                self.edit_filter.blockSignals(False)
                self._debounce_timer.start()
                return True

        return False
        

    # ==========================
    # Public API
    # ==========================        

    def text(self):
        return self.edit_filter.text()
    
    def clear(self):
        self.edit_filter.clear()
    
    def set_text(self, text: str):

        self.edit_filter.setText(text)


    def set_placeholder(self, text: str):

        self.edit_filter.setPlaceholderText(text)


    def set_focus(self):

        self.edit_filter.setFocus()

    def fn_set_refresh_enabled(
        self,
        enabled: bool,
    ) -> None:
        self.btn_refresh.setEnabled(enabled)

    
    def fn_refresh_theme(self):

        self.edit_filter.fn_refresh_theme()
        self.btn_refresh.fn_refresh_theme()
