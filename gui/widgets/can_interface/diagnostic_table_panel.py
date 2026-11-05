import re

from dataclasses import replace

from uuid import uuid4

from core.diagnostic_request import SECURITY_SEED_REQUESTS

from html import escape

from PySide6.QtCore import QItemSelectionModel, Qt, QSignalBlocker, Signal

from PySide6.QtGui import QColor, QFont, QFontDatabase, QKeySequence, QShortcut

from PySide6.QtWidgets import (

    QApplication, QHBoxLayout, QHeaderView, QSizePolicy, QWidget,

    QLineEdit, QStyledItemDelegate, QTableWidget

)
from gui.themes.theme_manager import ThemeManager

from gui.themes.styles.controls.scrollbar_style import fn_apply_scrollbar_style

from gui.widgets.controls.action_button import ActionButton

from gui.widgets.controls.primary_combobox import PrimaryComboBox

from gui.widgets.controls.primary_label import PrimaryLabel

from gui.widgets.diagnostic.diagnostic_sequence_table import DiagnosticSequenceTable

from gui.widgets.can_interface.check_all_header import CheckAllHeader
from gui.widgets.can_interface.panel_theme import apply_panel_theme

from services.can.diag_ecu_mapper import find_ecu_by_can_ids

from gui.themes.styles.controls.lineedit_style import fn_lineedit_style
from gui.themes.styles.controls.table_style import fn_table_style

# Same face and size as the ECU column and the table text (see fn_table_style).
HEX_FONT_SIZE = 10

HEX_FONT_FAMILY = "Segoe UI"


def fn_hex_font():
    return QFont(HEX_FONT_FAMILY, HEX_FONT_SIZE)


_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


def format_hex_while_typing(text, cursor):
    """Group typed HEX digits in pairs ('22f190' -> '22 F1 90').

    Returns (text, cursor) or None when the text is not plain HEX (left untouched so the
    existing invalid-HEX warning still shows).
    """

    if any(not (char in _HEX_DIGITS or char.isspace()) for char in text):
        return None

    digits_before = sum(char in _HEX_DIGITS for char in text[:cursor])

    digits = "".join(char for char in text if char in _HEX_DIGITS).upper()

    formatted = " ".join(digits[i:i + 2] for i in range(0, len(digits), 2))

    position = 0 if digits_before == 0 else (digits_before - 1) + (digits_before - 1) // 2 + 1

    return formatted, position


def validate_and_format_hex(raw_text: str):

    """

    Validates and formats hex strings for Payload and Expected Response.

    Returns: (is_valid: bool, formatted_text: str, warning_message: str)

    """

    text = str(raw_text or "").strip()

    if not text:

        return True, "", ""

    clean_hex = set("0123456789abcdefABCDEF")
    if any(not (c in clean_hex or c.isspace()) for c in text):
        return False, str(raw_text), "Chứa ký tự không phải HEX"

    tokens = text.split()

    if not tokens:

        return True, "", ""

    bytes_list = []

    for token in tokens:

        if len(token) == 1:

            return False, str(raw_text), "Byte chưa đủ 2 ký tự"

        if len(token) % 2 != 0:

            if len(tokens) == 1:

                return False, str(raw_text), "Số ký tự HEX lẻ"

            return False, str(raw_text), "Byte không đúng định dạng"

        for i in range(0, len(token), 2):

            bytes_list.append(token[i:i+2].upper())

    return True, " ".join(bytes_list), ""


class HexItemDelegate(QStyledItemDelegate):
    """HEX editor for compact diagnostic table cells."""

    LIVE_FORMAT = True

    def _live_format(self, editor):
        result = format_hex_while_typing(editor.text(), editor.cursorPosition())

        if result is None or result[0] == editor.text():
            return

        text, position = result

        editor.setText(text)

        editor.setCursorPosition(position)

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setObjectName("diagnosticHexEditor")

        editor.setFont(fn_hex_font())

        editor.setAlignment(
            Qt.AlignLeft | Qt.AlignVCenter
        )

        editor.textChanged.connect(
            lambda text: self._on_text_changed(editor, text)
        )

        if self.LIVE_FORMAT:
            editor.textEdited.connect(lambda _text: self._live_format(editor))

        self._on_text_changed(editor, "")
        
        return editor

    def _apply_editor_style(self, editor, invalid=False):
        colors = ThemeManager.fn_colors()

        state = (ThemeManager.fn_theme(), bool(invalid))
        if getattr(editor, "_hex_style_state", None) == state:
            return

        border_color = (
            colors.WARNING if invalid else colors.PRIMARY
        )
        text_color = (
            colors.WARNING if invalid else colors.TEXT
        )

        selected_text = (
            colors.WINDOW
            if ThemeManager.fn_is_dark()
            else colors.TEXT_INVERT
        )

        mono_font = QFontDatabase.systemFont(
            QFontDatabase.FixedFont
        ).family()

        style = fn_lineedit_style() + f"""
        QLineEdit#diagnosticHexEditor,
        QLineEdit#diagnosticHexEditor:focus {{
            background-color: {colors.WINDOW};
            color: {text_color};

            border: 1px solid {border_color};
            border-radius: 2px;

            padding: 0px 4px;

            font-family: "{mono_font}";

            selection-background-color: {colors.PRIMARY};
            selection-color: {selected_text};
        }}
        """

        editor.setStyleSheet(style)
        editor._hex_style_state = state

    def _on_text_changed(self, editor, text):
        is_valid, _, warning = validate_and_format_hex(text)

        colors = ThemeManager.fn_colors()

        text_color = (
            colors.TEXT if is_valid else colors.WARNING
        )

        border_color = (
            colors.BORDER if is_valid else colors.WARNING
        )

        style = fn_lineedit_style() + f"""
            QLineEdit#diagnosticHexEditor,
            QLineEdit#diagnosticHexEditor:focus {{
                background-color: {colors.WINDOW};
                color: {text_color};
                border: 1px solid {border_color};
                border-radius: 0px;
                padding: 0px;

                font-family: "{HEX_FONT_FAMILY}";
                font-size: {HEX_FONT_SIZE}pt;
            }}
        """

        editor.setStyleSheet(style)
        editor.setToolTip(
            f"Warning: {warning}" if not is_valid else ""
        )

    def setModelData(self, editor, model, index):
        raw_text = editor.text()
        is_valid, formatted, _ = validate_and_format_hex(
            raw_text
        )

        new_text = (
            formatted if is_valid and formatted else raw_text
        )

        model.setData(index, new_text, Qt.EditRole)



# The Results column only ever shows Passed, Failed or Timeout; everything else is "no result".
# A positive response with no expected value counts as Passed, any error as Failed.
NO_RESULT = "\u2014"

RESULT_LABELS = {
    "Passed": "Passed",
    "Not Evaluated": "Passed",
    "Failed": "Failed",
    "Error": "Failed",
    "Timeout": "Timeout",
}


def result_label(outcome):
    return RESULT_LABELS.get(outcome, NO_RESULT)


def is_negative_response(text):
    tokens = str(text or "").split()

    return bool(tokens) and tokens[0].upper() == "7F"


class ResultDelegate(QStyledItemDelegate):
    """Fills a Passed / Failed / Timeout cell with its theme color, even in a selected row."""

    def paint(self, painter, option, index):
        label = index.data(Qt.DisplayRole)

        colors = ThemeManager.fn_colors()

        background = {
            "Passed": colors.RESULT_PASSED_BG,
            "Failed": colors.RESULT_FAILED_BG,
            "Timeout": colors.RESULT_TIMEOUT_BG,
        }.get(label)

        if background is None:
            super().paint(painter, option, index)

            return

        painter.save()

        painter.fillRect(option.rect, QColor(background))

        painter.setFont(option.font)

        painter.setPen(QColor(colors.RESULT_TEXT))

        painter.drawText(option.rect, Qt.AlignCenter, label)

        painter.restore()


class TextItemDelegate(HexItemDelegate):
    """Free-text editor with the same boxed look as the HEX editors."""

    LIVE_FORMAT = False

    def _on_text_changed(self, editor, text):
        # Plain text is never an invalid HEX string.
        super()._on_text_changed(editor, "")

    def setModelData(self, editor, model, index):
        QStyledItemDelegate.setModelData(self, editor, model, index)


class ReadOnlyHexCell(QLineEdit):
    """Read-only HEX cell using the existing V-CODE theme.

    At rest it blends into the row; once clicked it selects all of its text and takes the same
    boxed look as the Payload / Expected Response editors, so the text can be copied.
    A negative response (7F ...) is drawn in the theme's red, bold.
    """

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)

        self.setObjectName("receiveMessageCell")
        self.setReadOnly(True)
        self.setFrame(False)
        self.setFont(fn_hex_font())

        self.setAlignment(
            Qt.AlignLeft | Qt.AlignVCenter
        )

        self.setCursorPosition(0)

        self._style_signature = None
        self._selected = False
        self._row = 0
        self._focused = False
        self._select_all_on_click = True
        self.fn_refresh_theme()

    def set_payload(self, text):
        if text != self.text():
            self.setText(text)

        # Long data always shows its beginning, never its tail.
        self.setCursorPosition(0)

        self.fn_refresh_theme()

    def fn_refresh_theme(self, selected=None, row=None):
        if selected is not None:
            self._selected = bool(selected)

        if row is not None:
            self._row = row

        selected, row = self._selected, self._row

        negative = is_negative_response(self.text())

        signature = (
            ThemeManager.fn_theme(),
            selected,
            row % 2,
            self._focused,
            negative,
        )

        if signature == self._style_signature:
            return

        colors = ThemeManager.fn_colors()

        # Match the selected-row colors of V-CODE.
        selected_text = (
            colors.WINDOW
            if ThemeManager.fn_is_dark()
            else colors.TEXT_INVERT
        )

        if self._focused:
            # Same look as the HEX / name editors.
            background = colors.WINDOW
            foreground = colors.TEXT
            border = f"1px solid {colors.PRIMARY}"
            radius = "2px"
            selection_bg = colors.PRIMARY
            selection_fg = selected_text
        else:
            background = (
                colors.PRIMARY
                if selected
                else (
                    colors.TABLE_ROW
                    if row % 2 == 0
                    else colors.TABLE_ROW_ALT
                )
            )

            foreground = (
                selected_text if selected else colors.TEXT
            )

            border = "none"
            radius = "0px"

            # Make text selection visible even when the row is selected.
            selection_bg = (
                colors.TABLE_HEADER if selected else colors.PRIMARY
            )

            selection_fg = (
                colors.TEXT if selected else selected_text
            )

        weight = ""

        if negative:
            weight = "font-weight: bold;"

            # Red on the blue selected row would be unreadable: keep the row's own text color there.
            if self._focused or not selected:
                foreground = colors.NEGATIVE_RESPONSE_TEXT

        self.setStyleSheet(
            fn_lineedit_style()
            + f"""
            QLineEdit#receiveMessageCell,
            QLineEdit#receiveMessageCell:focus {{
                background-color: {background};
                color: {foreground};
                border: {border};
                border-radius: {radius};
                padding: 0px 4px;
                selection-background-color: {selection_bg};
                selection-color: {selection_fg};
                font-family: "{HEX_FONT_FAMILY}";
                font-size: {HEX_FONT_SIZE}pt;
                {weight}
            }}
            """
        )

        self._style_signature = signature

    def focusInEvent(self, event):
        super().focusInEvent(event)

        self._focused = True
        self.fn_refresh_theme()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)

        self._focused = False
        self._select_all_on_click = True
        self.deselect()
        self.setCursorPosition(0)
        self.fn_refresh_theme()

    def mousePressEvent(self, event):
        if self._select_all_on_click:
            # First click behaves like clicking a Payload cell: focus it and select everything.
            self._select_all_on_click = False
            self.setFocus(Qt.MouseFocusReason)
            self.selectAll()
            event.accept()
        else:
            super().mousePressEvent(event)

        table = self.parent()

        while table is not None and not isinstance(
            table, QTableWidget
        ):
            table = table.parent()

        if table is None:
            return

        point = table.viewport().mapFrom(
            self, event.position().toPoint()
        )

        index = table.indexAt(point)

        if index.isValid():
            table.selectRow(index.row())


class _RowButton(ActionButton):

    def __init__(self):

        super().__init__(">", width=32, height=28)

        self.setToolTip("Send one manual UDS request on the connected channel.")

        self.setAccessibleName("Send this one diagnostic step")

    def fn_refresh_theme(self):

        super().fn_refresh_theme()

        self.setStyleSheet(self.styleSheet() + "QPushButton { padding: 0px; }")

class CanDiagnosticTablePanel(DiagnosticSequenceTable):

    row_selected = Signal(str)

    row_send_requested = Signal(str)

    selected_rows_changed = Signal(tuple)

    save_requested = Signal()

    load_requested = Signal()

    vehicle_changed = Signal(str)

    document_changed=Signal()

    vehicle_configuration_changed=Signal()

    vehicle_resources_changed=Signal()

    sequence_run_requested = Signal()

    sequence_stop_requested = Signal()

    COL_CHECK, COL_STEP, COL_SEQUENCE_NAME, COL_ECU, COL_REQUEST, COL_SEND, COL_DELAY, COL_REPEAT, COL_EXPECTED, COL_RECEIVE, COL_RESULT, COL_COMMENT = range(12)

    HEADERS = ("", "Step", "Test sequence name", "ECU", "Payload (HEX)", ">", "Delay (ms)", "Repeat",

               "Expected Response (HEX)", "Receive Message (HEX)", "Results", "Comment")

    OUTCOMES = frozenset(("Pending", "Running", "Passed", "Failed", "Timeout", "Error", "Not Evaluated", "Cancelled"))

    TRANSIENT_OUTCOMES = frozenset(("Pending", "Running"))

    def __init__(self, parent=None, vehicle_service=None):

        self.step_ids = []

        self._checked = set()

        self._runtime = {}

        self._auto_comments = {}

        self._step_signatures = {}

        self._request_busy=False

        self._send_available=True  # Standalone view can still emit typed action intent.

        self._sequence_running = False

        self.import_diagnostics = ()

        super().__init__(parent, vehicle_service)

    def _setup_ui(self):

        super()._setup_ui()

        layout = self.layout()

        layout.setContentsMargins(8, 8, 8, 8)

        layout.removeItem(self.execution_layout)

        self.execution_settings = QWidget()

        self.execution_settings.setLayout(self.execution_layout)

        self.execution_settings.hide()

        # ECU written into the selected rows by Import; listed from the selected Vehicle.
        self.lbl_import_ecu = PrimaryLabel("ECU")

        self.cmb_import_ecu = PrimaryComboBox(minimum_height=36)

        self.cmb_import_ecu.setMinimumWidth(160)

        import_index = self.execution_layout.indexOf(self.btn_import_delay)

        self.execution_layout.insertSpacing(import_index, 12)

        self.execution_layout.insertWidget(import_index + 1, self.lbl_import_ecu)

        self.execution_layout.insertWidget(import_index + 2, self.cmb_import_ecu)

        self._refresh_import_ecu_combo()

        self.title = PrimaryLabel("Select a sequence")

        self.title.setTextFormat(Qt.PlainText)

        self.title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        self.title.setMinimumWidth(60)

        self.title.hide()

        self.notice = PrimaryLabel("")

        self.notice.setTextFormat(Qt.PlainText)

        self.notice.setWordWrap(True)

        self.notice.setMaximumHeight(40)

        self.notice.hide()

        self.btn_delete = ActionButton("Delete", width=62, height=30)

        self.btn_load = ActionButton("Load .diag", width=85, height=30)

        self.btn_load.hide()

        self.btn_settings = ActionButton("Setting", width=72, height=30)

        self.btn_settings.setCheckable(True)

        self.btn_settings.toggled.connect(self.execution_settings.setVisible)

        self.btn_add.setText("+Add Row")
        self.btn_add.setMinimumSize(85, 30)
        self.btn_add.setMaximumHeight(30)

        self.btn_run.setText("RUN")
        self.btn_run.setFixedSize(120, 30)
        self.btn_run.setMaximumHeight(30)
        self.btn_run.setEnabled(False)
        self.btn_run.setToolTip("Run the checked steps from top to bottom.")
        self.btn_run.show()

        self.btn_export.setText("EXPORT")
        self.btn_export.setFixedSize(120, 30)
        self.btn_export.setMaximumHeight(30)
        self.btn_export.setEnabled(True)
        self.btn_export.setToolTip("Export diagnostic sequence to Excel report (.xlsx)")
        self.btn_export.show()

        self.btn_stop.setText("STOP")
        self.btn_stop.setFixedSize(120, 30)
        self.btn_stop.setMaximumHeight(30)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setToolTip("Stop sequence execution.")
        self.btn_stop.show()

        self.vehicle_selector.setMaximumWidth(210)

        self.vehicle_selector.cmb_vehicle.setMinimumContentsLength(6)

        self.vehicle_selector.cmb_vehicle.setPlaceholderText("Select Vehicle")

        toolbar = QHBoxLayout()

        toolbar.setSpacing(6)

        # Căn trái, cùng lề với bảng: RUN | EXPORT | STOP (120px) | Vehicle | +Add Row | Delete | Setting
        toolbar.addWidget(self.btn_run)

        toolbar.addWidget(self.btn_export)

        toolbar.addWidget(self.btn_stop)

        toolbar.addSpacing(12)

        toolbar.addWidget(self.vehicle_selector)

        toolbar.addWidget(self.btn_add)

        toolbar.addWidget(self.btn_delete)

        toolbar.addWidget(self.btn_settings)

        toolbar.addStretch(1)

        # The first header section is a working "select all" check box.
        header = CheckAllHeader(Qt.Horizontal, self.table)

        self.table.setHorizontalHeader(header)

        header.setStretchLastSection(True)

        header.toggle_requested.connect(self.set_all_checked)

        self._configure_columns()

        self.table.horizontalHeaderItem(self.COL_CHECK).setToolTip("Select / deselect all steps to run")

        layout.insertLayout(0, toolbar)

        layout.insertWidget(1, self.execution_settings)

        layout.addWidget(self.notice)

        self.btn_delete.clicked.connect(self.fn_remove_selected_step)

        self.btn_load.clicked.connect(self.load_requested)

        self.btn_export.clicked.connect(self.export_excel)

        self.btn_run.clicked.connect(self.sequence_run_requested)

        self.btn_stop.clicked.connect(self.sequence_stop_requested)

        self.table.currentCellChanged.connect(self._selection_changed)
        self.table.itemSelectionChanged.connect(
            self._refresh_receive_selection_colors
        )

        self._copy_shortcut = QShortcut(QKeySequence.Copy, self.table)

        self._copy_shortcut.setContext(Qt.WidgetWithChildrenShortcut)

        self._copy_shortcut.activated.connect(self.copy_current_cell)

        self.hex_delegate = HexItemDelegate(self.table)

        self.receive_delegate = ReceiveMessageDelegate(self.table)

        self.table.setItemDelegateForColumn(
            self.COL_RECEIVE,
            self.receive_delegate
        )

        self.text_delegate = TextItemDelegate(self.table)

        self.table.setItemDelegateForColumn(self.COL_SEQUENCE_NAME, self.text_delegate)

        self.result_delegate = ResultDelegate(self.table)

        self.table.setItemDelegateForColumn(self.COL_RESULT, self.result_delegate)

        self.table.setItemDelegateForColumn(self.COL_REQUEST, self.hex_delegate)

        self.table.setItemDelegateForColumn(self.COL_EXPECTED, self.hex_delegate)

    def _configure_columns(self):

        for column, width in enumerate((34, 50, 160, 110, 165, 36, 85, 65, 185, 185, 100, 160)):

            self.table.setColumnWidth(column, width)

            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.Interactive)

        self.table.setMinimumHeight(120)

    def fn_load_sequence(self, test_case):

        self._auto_comments.clear()

        self.step_ids = [uuid4().hex for _ in test_case.steps] if test_case else []

        # Every row is selected to run by default.
        self._checked = set(self.step_ids)

        self._runtime.clear()

        self.import_diagnostics = ()

        super().fn_load_sequence(test_case)

        self._refresh_check_all()

        self._step_signatures = self._runtime_signatures()

        self.title.setText(test_case.name if test_case else "Select a sequence")

        self.title.setToolTip(self.title.text())

        self.notice.clear()

        self.notice.hide()

        self._selection_changed()

        self._update_run_button_state()

        self._update_run_button_state()

        self.document_changed.emit()

    def mark_saved(self):

        self._is_dirty = False

        self.title.setText(self._test_case.name if self._test_case else "Select a sequence")

    def fn_add_step_after_selected(self):

        self._ensure_test_case()

        new_id = uuid4().hex

        self.step_ids.insert(self._selected_insert_index(), new_id)

        self._checked.add(new_id)

        super().fn_add_step_after_selected()

        self._refresh_check_all()

        self._update_run_button_state()

    def _replace_steps(self, steps):

        # Preserve user-entered values, including empty names.

        super()._replace_steps(steps)

    def fn_remove_selected_step(self):

        removed = set(self._selected_rows())

        ids = [key for index, key in enumerate(self.step_ids) if index not in removed]

        self._checked.intersection_update(ids)

        self._runtime = {key: value for key, value in self._runtime.items() if key in ids}

        self._auto_comments = {key: value for key, value in self._auto_comments.items() if key in ids}

        self.step_ids = ids

        super().fn_remove_selected_step()

        self.selected_rows_changed.emit(self.checked_step_ids())

        self._refresh_check_all()

        self._selection_changed()

        self._update_run_button_state()

    def _populate_step_row(self, row, step):

        step_id = self.step_ids[row]

        self._set_item(row, self.COL_CHECK, "", editable=False)

        check = self.table.item(row, self.COL_CHECK)

        check.setFlags(check.flags() | Qt.ItemIsUserCheckable)

        check.setCheckState(Qt.Checked if step_id in self._checked else Qt.Unchecked)

        self._set_item(row, self.COL_STEP, step.step, editable=False)

        self._set_item(row, self.COL_SEQUENCE_NAME, step.sequence_name, editable=True)

        self._set_ecu_combo(row, step.ecu)

        for column, value in ((self.COL_REQUEST, step.request), (self.COL_DELAY, self._format_optional_int(step.delay_ms)),

                              (self.COL_REPEAT, step.repeat), (self.COL_EXPECTED, step.expected_response),

                              (self.COL_COMMENT, step.comment)):

            self._set_item(row, column, value, editable=True)

        button = _RowButton()

        button.clicked.connect(lambda checked=False, key=step_id: self._request_step(key))

        self.table.setCellWidget(row, self.COL_SEND, button)

        cell = self.table.cellWidget(row, self.COL_RECEIVE)

        if not isinstance(cell, ReadOnlyHexCell):

            self.table.setCellWidget(row, self.COL_RECEIVE, ReadOnlyHexCell("—", self.table))

        self._set_button_state(row)

        self._render_runtime(row)

    def _set_item(self, row, column, value, editable):

        super()._set_item(row, column, value, editable)

        item = self.table.item(row, column)

        if item is None:

            return

        item.setToolTip(escape(str(value)))

       
        if column in (
            self.COL_REQUEST,
            self.COL_EXPECTED,
            self.COL_RECEIVE
        ):
            item.setFont(fn_hex_font())

            item.setTextAlignment(
                Qt.AlignLeft | Qt.AlignVCenter
            )

        if column in (self.COL_REQUEST, self.COL_EXPECTED):

            is_valid, formatted, warning = validate_and_format_hex(value)

            colors = ThemeManager.fn_colors()

            if not is_valid:

                item.setForeground(QColor(colors.WARNING))

                item.setToolTip(f"Warning: {warning}")

            else:

                item.setForeground(QColor(colors.TEXT))

    def _updated_step_from_item(self, step, column, text):

        if column == self.COL_SEQUENCE_NAME:

            return replace(

                step,

                sequence_name=text

            )

        if column == self.COL_COMMENT:

            return replace(step, comment=text)

        if column in (self.COL_REQUEST, self.COL_EXPECTED):

            field = "request" if column == self.COL_REQUEST else "expected_response"

            is_valid, formatted, _ = validate_and_format_hex(text)

            new_text = formatted if is_valid and formatted else text

            # Closing the one-click editor reformats stored HEX (e.g. ' 22f190' -> '22 F1 90').
            # Same bytes is not an edit: keep the step so runtime results survive.
            if self._canonical_hex(new_text) == self._canonical_hex(getattr(step, field)):

                return step

            return replace(step, **{field: new_text})

        return super()._updated_step_from_item(

            step, column, text

        )

    def _on_item_changed(self, item):
        if self._is_populating:
            return
        try:
            row = item.row()
            col = item.column()
        except RuntimeError:
            return
        if col == self.COL_CHECK and row < len(self.step_ids):
            key = self.step_ids[row]
            if item.checkState() == Qt.Checked:
                self._checked.add(key)
            else:
                self._checked.discard(key)
            self.selected_rows_changed.emit(self.checked_step_ids())
            self._refresh_check_all()
            return
        super()._on_item_changed(item)
        if row < len(self.step_ids):
            self._set_button_state(row)

    def _mark_dirty(self):

        current = self._runtime_signatures()

        for key in self._step_signatures.keys() | current.keys():

            if self._step_signatures.get(key) != current.get(key):

                self.invalidate_step_result(key)

        self._step_signatures = current

        super()._mark_dirty()

    @staticmethod
    def _canonical_hex(value):

        is_valid, formatted, _ = validate_and_format_hex(value)

        return formatted if is_valid else str(value or "")

    def _runtime_signatures(self):

        return {key: (step.ecu, step.request, step.expected_response, step.match)

                for key, step in zip(self.step_ids, self._test_case.steps if self._test_case else ())}

    def runtime_snapshot(self):

        """Per-row results for restoring after the sequence is reloaded (step ids are regenerated)."""

        signatures = self._runtime_signatures()

        rows = []

        for key in self.step_ids:

            result = self._runtime.get(key)

            if result is not None and result[1] in self.TRANSIENT_OUTCOMES:

                result = None

            rows.append((signatures.get(key), result, self._auto_comments.get(key)))

        return self._transport_configuration(), tuple(rows)

    def restore_runtime_snapshot(self, snapshot):

        """Restore rows whose step and Vehicle/ECU addressing are unchanged; others stay empty."""

        if not snapshot or snapshot[0] != self._transport_configuration():

            return

        signatures = self._runtime_signatures()

        with QSignalBlocker(self.table):

            for row, (key, (signature, result, auto_comment)) in enumerate(zip(self.step_ids, snapshot[1])):

                if result is None or signature != signatures.get(key):

                    continue

                self._runtime[key] = result

                if auto_comment is not None:

                    self._auto_comments[key] = auto_comment

                self._render_runtime(row)

    def invalidate_step_result(self, key):

        self._auto_comments.pop(key, None)

        self._runtime.pop(key, None)

        if key in self.step_ids:

            row = self.step_ids.index(key)

            with QSignalBlocker(self.table):

                self._render_runtime(row)

                self._set_button_state(row)

    def _request_step(self, key):

        if key in self.step_ids:

            row=self.step_ids.index(key)

            step=self._test_case.steps[row]

            req_valid, req_fmt, req_warn = validate_and_format_hex(step.request)

            if not req_valid or not step.request.strip():

                self.show_notice(f"Cannot send: {req_warn or 'Invalid or empty HEX payload.'}"); return

            exp_valid, exp_fmt, exp_warn = validate_and_format_hex(step.expected_response)

            if not exp_valid and step.expected_response.strip():

                self.show_notice(f"Cannot send: {exp_warn}"); return

            payload = self._request_payload(step.request)

            if payload is None:

                self.show_notice('Invalid or empty HEX payload.'); return

            if payload[0] == 0x27 and payload not in SECURITY_SEED_REQUESTS:

                self.show_notice('Security Access permits only exact 27 01 requestSeed; key submission is not enabled.'); return

            if not self._resolved_ecu(step.ecu):

                self.show_notice('Select Vehicle and a configured ECU before sending.'); return

            if not self._request_busy and self._send_available: self.row_send_requested.emit(key)

    def set_request_busy(self,busy):

        self._request_busy=bool(busy)

        for row in range(self.table.rowCount()): self._set_button_state(row)

    def set_send_available(self,available):

        self._send_available=bool(available)

        for row in range(self.table.rowCount()): self._set_button_state(row)

        self._update_run_button_state()

    def is_sequence_running(self) -> bool:

        return getattr(self, "_sequence_running", False)

    def set_sequence_running(self, running: bool):

        self._sequence_running = bool(running)

        self.btn_run.setEnabled(not running and self._send_available and len(self.step_ids) > 0)

        self.btn_stop.setEnabled(running)

    def _update_run_button_state(self):

        if not getattr(self, "_sequence_running", False):

            self.btn_run.setEnabled(self._send_available and len(self.step_ids) > 0)

            self.btn_stop.setEnabled(False)

    def _set_button_state(self, row):

        button = self.table.cellWidget(row, self.COL_SEND)

        if button is None or self._test_case is None or row >= len(self._test_case.steps):

            return

        step = self._test_case.steps[row]

        req_valid, req_fmt, req_warn = validate_and_format_hex(step.request)

        exp_valid, exp_fmt, exp_warn = validate_and_format_hex(step.expected_response)

        payload = self._request_payload(step.request)

        payload_valid = req_valid and payload is not None and bool(step.request.strip())

        security = (

            payload_valid

            and payload[0] == 0x27 and payload not in SECURITY_SEED_REQUESTS

        )

        target_valid = self._resolved_ecu(step.ecu)

        exp_has_error = (not exp_valid) and bool(step.expected_response.strip())

        enabled = (

            self._send_available

            and not self._request_busy

            and not security

            and target_valid

            and payload_valid

            and not exp_has_error

        )

        button.setEnabled(enabled)

        if not req_valid:

            tooltip = f"Warning: {req_warn}"

        elif exp_has_error:

            tooltip = f"Warning: {exp_warn}"

        elif not payload_valid:

            tooltip = "Invalid or empty HEX payload."

        elif security:

            tooltip = "Only exact 27 01 requestSeed is enabled; key submission is disabled."

        elif not target_valid:

            tooltip = "Select a configured ECU."

        elif self._request_busy:

            tooltip = "A diagnostic request is running."

        elif not self._send_available:

            tooltip = "Connect Vector first."

        elif payload in SECURITY_SEED_REQUESTS:

            tooltip = ("Auto SecurityAccess L1: two UDS transactions; final ECU 67 02 required."

                       if self._request_payload(step.expected_response) == b'\x67\x02' else

                       "Request seed manually with 27 01; no key submission or ECU unlock.")

        else:

            tooltip = "Send one manual UDS request."

        button.setToolTip(tooltip)

    def show_notice(self, text):

        self.notice.setText(text)

        self.notice.setToolTip(escape(text))

        self.notice.setVisible(bool(text))

    def _refresh_check_all(self):

        selected = sum(key in self._checked for key in self.step_ids)

        self.table.horizontalHeader().set_check_state(
            Qt.Unchecked if not selected
            else Qt.Checked if selected == len(self.step_ids)
            else Qt.PartiallyChecked
        )

    def set_all_checked(self, checked):

        self._checked = set(self.step_ids) if checked else set()

        state = Qt.Checked if checked else Qt.Unchecked

        self._is_populating = True

        try:

            for row in range(self.table.rowCount()):

                item = self.table.item(row, self.COL_CHECK)

                if item is not None:

                    item.setCheckState(state)

        finally:

            self._is_populating = False

        self._refresh_check_all()

        self.selected_rows_changed.emit(self.checked_step_ids())

    def checked_step_ids(self):

        return tuple(key for key in self.step_ids if key in self._checked)

    def selected_step_id(self):

        row = self.table.currentRow()

        return self.step_ids[row] if 0 <= row < len(self.step_ids) else ""

    def _selection_changed(self, *_):

        self.row_selected.emit(self.selected_step_id())

    def step_for_id(self, key):

        if key not in self.step_ids:

            return None

        return self._test_case.steps[self.step_ids.index(key)]

    def set_step_running(self, key):

        self.set_step_result(key, "", "Running")

    def set_auto_step_result(self, key, received_payload, outcome, detail):

        """Runtime-only annotation; never mutate the editable sequence model."""

        self._auto_comments[key] = detail

        return self.set_step_result(key, received_payload, outcome, detail)

    def set_step_result(self, key, received_payload, outcome, detail=""):

        if key not in self.step_ids:

            return False

        payload = self._normalize_hex(received_payload, allow_empty=True)

        if payload is None or outcome not in self.OUTCOMES:

            raise ValueError("Invalid runtime result")

        self._runtime[key] = (payload, outcome, detail)

        with QSignalBlocker(self.table):

            self._render_runtime(self.step_ids.index(key))

        return True

    def _render_runtime(self, row):

        payload, outcome, detail = self._runtime.get(self.step_ids[row], ("—", "—", ""))

        self._set_item(row, self.COL_RECEIVE, payload, editable=False)

        label = result_label(outcome)

        self._set_item(row, self.COL_RESULT, label, editable=False)

        self.table.item(row, self.COL_RESULT).setToolTip(detail or label)

        # Update ReadOnlyHexCell widget in COL_RECEIVE

        cell = self.table.cellWidget(row, self.COL_RECEIVE)

        if not isinstance(cell, ReadOnlyHexCell):

            cell = ReadOnlyHexCell(payload, self.table)

            self.table.setCellWidget(row, self.COL_RECEIVE, cell)

        else:
            cell.set_payload(payload)

        # Task 5: Comment is 100% user-managed: never overwrite with auto_comments

        selection_model = self.table.selectionModel()
        model = self.table.model()

        if selection_model is None:
            return

        index = model.index(row, self.COL_RECEIVE)
        is_selected = selection_model.isSelected(index)

        cell.fn_refresh_theme(
            selected=is_selected,
            row=row,
        )


        step = self._test_case.steps[row]

        self._set_item(row, self.COL_COMMENT, step.comment, editable=True)

    def reset_runtime_results(self):

        self._auto_comments.clear()

        self._runtime.clear()

        with QSignalBlocker(self.table):

            for row in range(self.table.rowCount()):

                self._render_runtime(row)

    def copy_current_cell(self):
        focus = QApplication.focusWidget()
        if isinstance(focus, QLineEdit) and focus.hasSelectedText():
            QApplication.clipboard().setText(focus.selectedText())
            return
        for r in range(self.table.rowCount()):
            cell = self.table.cellWidget(r, self.COL_RECEIVE)
            if isinstance(cell, QLineEdit) and cell.hasSelectedText():
                QApplication.clipboard().setText(cell.selectedText())
                return
        item = self.table.currentItem()
        if item is not None:
            QApplication.clipboard().setText(item.text())

    def _transport_configuration(self):

        if self._current_vehicle is None:

            return None

        return (self._current_vehicle_name, tuple(sorted(

            (ecu.name, ecu.request_id, ecu.response_id) for ecu in self._available_ecus)))

    
    def _refresh_receive_selection_colors(self):
        selection_model = self.table.selectionModel()
        model = self.table.model()

        if selection_model is None:
            return

        for row in range(self.table.rowCount()):
            cell = self.table.cellWidget(
                row, self.COL_RECEIVE
            )

            if not isinstance(cell, ReadOnlyHexCell):
                continue

            index = model.index(row, self.COL_RECEIVE)
            is_selected = selection_model.isSelected(index)

            cell.fn_refresh_theme(
                selected=is_selected,
                row=row,
            )

    
    def fn_refresh_vehicles(self, selected_vehicle_name="", *, preserve_unchanged=False):

        previous = self._transport_configuration()

        chosen = selected_vehicle_name or self._current_vehicle_name

        try:

            names = self._vehicle_service.list_vehicles()

        except Exception as error:

            names = []

            self.show_notice(f"Cannot load vehicles: {error}")

        self.vehicle_selector.fn_set_vehicles(names, chosen if chosen in names else "", allow_empty_selection=True)

        self._load_vehicle_by_name(self.vehicle_selector.fn_vehicle())

        self._apply_diag_ecu_mapping()

        self._refresh_ecu_combos()

        if preserve_unchanged and previous is not None and previous == self._transport_configuration():

            self.vehicle_resources_changed.emit()

        else:

            self.reset_runtime_results()

            self.vehicle_configuration_changed.emit()

    def _on_vehicle_changed(self, vehicle_name):

        self.reset_runtime_results()

        # Load newly selected Vehicle and its ECU definitions.

        super()._on_vehicle_changed(vehicle_name)

        # Map imported .diag addressing to V-CODE ECU names.

        self._apply_diag_ecu_mapping()

        if vehicle_name and self._current_vehicle is None:

            self.show_notice(

                f"Cannot load Vehicle '{vehicle_name}'."

            )

        self.vehicle_changed.emit(vehicle_name)

        self.vehicle_configuration_changed.emit()

    def fn_set_vehicle(self, vehicle):

        self.reset_runtime_results()

        super().fn_set_vehicle(vehicle)

        self._apply_diag_ecu_mapping()

        self.vehicle_configuration_changed.emit()

    def _set_ecu_combo(self, row, ecu):

        combo = PrimaryComboBox(minimum_height=28)

        # Populate only valid, uniquely named ECU definitions.

        valid_ecus = [

            item

            for item in self._available_ecus

            if self._resolved_ecu(item.name)

        ]

        for item in valid_ecus:

            combo.addItem(item.name, item)

        # No empty item at index 0.

        # -1 means no ECU has been selected.

        selected_index = combo.findText(ecu) if ecu else -1

        if selected_index >= 0:

            combo.setCurrentIndex(selected_index)

        else:

            combo.setCurrentIndex(-1)

        # Show empty editor text when no ECU is selected,

        # without creating a selectable blank option.

        combo.setPlaceholderText("")

        if self._current_vehicle is None:

            tooltip = "Select a Vehicle first."

        elif not ecu:

            tooltip = "Select an ECU."

        elif selected_index < 0:

            tooltip = (

                f"ECU '{ecu}' is not configured "

                "in the selected Vehicle."

            )

        else:

            tooltip = ecu

        combo.setToolTip(escape(tooltip))

        key = self.step_ids[row]

        combo.currentIndexChanged.connect(

            lambda index, target=key, control=combo:

                self._ecu_changed(target, control)

        )

        fn_apply_scrollbar_style(combo.view())

        self.table.setCellWidget(

            row,

            self.COL_ECU,

            combo,

        )

    def _resolved_ecu(self, name):

        return bool(name and name.strip() and self._current_vehicle is not None

                    and sum(ecu.name == name for ecu in self._available_ecus) == 1)

    def unresolved_ecus(self):

        if self._current_vehicle is None or self._test_case is None:

            return ()

        return tuple((row + 1, step.ecu) for row, step in enumerate(self._test_case.steps)

                     if not self._resolved_ecu(step.ecu))

    def _refresh_import_ecu_combo(self):

        combo = self.cmb_import_ecu

        previous = combo.currentData()

        names = [

            ecu.name

            for ecu in self._available_ecus

            if self._current_vehicle is not None and self._resolved_ecu(ecu.name)

        ]

        with QSignalBlocker(combo):

            combo.clear()

            for name in names:

                combo.addItem(name, name)

            if names:

                combo.setCurrentIndex(max(combo.findData(previous), 0))

            else:

                # Without a Vehicle (or ECUs) there is nothing to import: say why, never show an empty list.

                combo.addItem("Select Vehicle first" if self._current_vehicle is None else "No ECU available", None)

        combo.setEnabled(bool(names))

        self.btn_import_delay.setEnabled(bool(names))

        fn_apply_scrollbar_style(combo.view())

    def fn_import_execution_values_to_rows(self):

        """Write Loop, Delay and ECU into every checked row (the row under the cursor is irrelevant)."""

        if self._test_case is None or not self._test_case.steps:

            return

        rows = [row for row, key in enumerate(self.step_ids) if key in self._checked]

        if not rows:

            self.show_notice("Check the rows to import into first.")

            return

        changes = {"delay_ms": self.spn_command_delay.value(), "repeat": self.spn_loop.value()}

        ecu = self.cmb_import_ecu.currentData()

        if ecu:

            changes["ecu"] = ecu

        cursor_rows = self._selected_rows()

        steps = list(self._test_case.steps)

        for row in rows:

            steps[row] = replace(steps[row], **changes)

        self._replace_steps(steps)

        self._reload_steps_into_table()

        # Reloading rebuilds the table: put the cursor selection back where it was.

        selection = self.table.selectionModel()

        for row in cursor_rows:

            selection.select(
                self.table.model().index(row, self.COL_STEP),
                QItemSelectionModel.Select | QItemSelectionModel.Rows,
            )

        self._mark_dirty()

    def _refresh_ecu_combos(self):

        self._refresh_import_ecu_combo()

        super()._refresh_ecu_combos()

        for row in range(self.table.rowCount()):

            self._set_button_state(row)

        # Empty ECU is a valid draft state.

        # Only show a warning for nonempty unresolved ECU names.

        unknown = tuple(

            (row, name)

            for row, name in self.unresolved_ecus()

            if str(name or "").strip()

        )

        if unknown:

            details = "\n".join(

                f"Row {row}: {name}"

                for row, name in unknown

            )

            self.show_notice(

                f"{len(unknown)} unresolved ECU(s)."

            )

            self.notice.setToolTip(details)

        else:

            # Clear only an ECU warning previously set by this method.

            if self.notice.text().endswith("unresolved ECU(s)."):

                self.show_notice("")

    def sequence_for_save(self):

        """

        Save editor content as-is.

        Empty ECU, incomplete HEX and empty sequence names

        are allowed in saved drafts.

        ECU resolution and HEX validation are required

        before sending diagnostic requests.

        """

        return self._test_case

    def exchange_text(self):

        from core.sequence_exchange import export_sequence_text

        case = self.sequence_for_save()

        return export_sequence_text(case.steps if case else (),

                                    [RESULT_LABELS.get(self._runtime.get(key, ('', '', ''))[1], '') for key in self.step_ids])

    def export_excel(self):
        from core.services.diagnostic_sequence_report_service import DiagnosticSequenceReportService
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        if not self._test_case or not self.step_ids:
            QMessageBox.warning(self, "Export", "No sequence data to export.")
            return

        service = DiagnosticSequenceReportService()
        report_folder = service.fn_get_report_folder()
        seq_name = self._test_case.name if self._test_case else "Sequence"
        vehicle_name = self.fn_current_vehicle()
        default_filename = service.fn_default_output_filename(seq_name, vehicle_name)
        default_path = report_folder / default_filename

        output_file, _ = QFileDialog.getSaveFileName(
            self,
            "Save Excel Report",
            str(default_path),
            "Excel Files (*.xlsx)",
        )
        if not output_file:
            return

        if not str(output_file).lower().endswith(".xlsx"):
            output_file = str(output_file) + ".xlsx"

        steps_data = []
        for row, step_id in enumerate(self.step_ids):
            step = self._test_case.steps[row] if self._test_case and row < len(self._test_case.steps) else None
            runtime_payload, outcome, detail = self._runtime.get(step_id, ("—", "—", ""))

            comment = step.comment if step else ""
            comment_item = self.table.item(row, self.COL_COMMENT)
            if comment_item is not None:
                comment = comment_item.text()

            seq_item = self.table.item(row, self.COL_SEQUENCE_NAME)
            step_seq_name = seq_item.text() if seq_item is not None and seq_item.text().strip() else (step.sequence_name if step else seq_name)

            ecu_cell = self.table.cellWidget(row, self.COL_ECU)
            ecu_text = ecu_cell.currentText() if ecu_cell is not None else (step.ecu if step else "")

            delay_val = 100
            delay_item = self.table.item(row, self.COL_DELAY)
            if delay_item is not None and delay_item.text().strip().isdigit():
                delay_val = int(delay_item.text().strip())
            elif step and step.delay_ms is not None:
                delay_val = step.delay_ms

            repeat_val = 1
            repeat_item = self.table.item(row, self.COL_REPEAT)
            if repeat_item is not None and repeat_item.text().strip().isdigit():
                repeat_val = int(repeat_item.text().strip())
            elif step and step.repeat is not None:
                repeat_val = step.repeat

            req_val = step.request if step else ""
            req_item = self.table.item(row, self.COL_REQUEST)
            if req_item is not None:
                req_val = req_item.text()

            exp_val = step.expected_response if step else ""
            exp_item = self.table.item(row, self.COL_EXPECTED)
            if exp_item is not None:
                exp_val = exp_item.text()

            steps_data.append({
                "step": row + 1,
                "sequence_name": step_seq_name,
                "ecu": ecu_text,
                "request": req_val,
                "delay_ms": delay_val,
                "repeat": repeat_val,
                "expected": exp_val,
                "receive": runtime_payload,
                "result": result_label(outcome),
                "comment": comment,
            })

        try:
            saved_path = service.export_sequence(
                sequence_name=seq_name,
                vehicle_name=vehicle_name,
                steps_data=steps_data,
                output_file=output_file,
            )
            QMessageBox.information(
                self,
                "Export",
                f"Excel report saved:\n\n{saved_path}",
            )
        except PermissionError:
            QMessageBox.warning(
                self,
                "Export Error",
                "Cannot save Excel report. Please close the Excel file and try again.",
            )
        except Exception as error:
            QMessageBox.critical(
                self,
                "Export Error",
                str(error),
            )

    def apply_import(self, imported, mode):

        if mode not in ('append', 'replace') or self._test_case is None:

            raise ValueError('Select an active document and explicit Append or Replace mode.')

        if mode == 'replace':

            self.fn_load_sequence(replace(self._test_case, steps=list(imported.steps)))

        else:

            self.step_ids.extend(uuid4().hex for _ in imported.steps)

            self._replace_steps([*self._test_case.steps, *imported.steps])

            self._reload_steps_into_table()

        self.import_diagnostics = imported.diagnostics

        self._mark_dirty()

        self._refresh_ecu_combos()

        if imported.diagnostics:

            self.show_notice('\n'.join(imported.diagnostics))

    def _ecu_changed(self, key, combo):

        value = combo.currentData()

        if key not in self.step_ids or self._is_populating:

            return

        row = self.step_ids.index(key)

        name = value.name if value is not None else ''

        step = self._test_case.steps[row]

        if step.ecu != name:

            steps = list(self._test_case.steps)

            steps[row] = replace(step, ecu=name)

            self._replace_steps(steps)

            self._mark_dirty()

    def _apply_diag_ecu_mapping(self):

        """

        Remap steps imported from .diag using the

        currently selected Vehicle.

        Do not alter steps without original CAN IDs.

        """

        if self._test_case is None or self._current_vehicle is None:

            # Without a Vehicle there is nothing to resolve against: keep the saved ECU names.

            return False

        changed = False

        steps = list(self._test_case.steps)

        for index, step in enumerate(steps):

            # Native manually created steps remain untouched.

            if (

                step.source_request_id is None

                or step.source_response_id is None

            ):

                continue

            mapped_name = find_ecu_by_can_ids(

                self._current_vehicle,

                step.source_request_id,

                step.source_response_id,

            )

            # No match or ambiguous match -> empty ECU.

            if step.ecu != mapped_name:

                steps[index] = replace(

                    step,

                    ecu=mapped_name,

                )

                changed = True

        if not changed:

            return False

        # Update the document model.

        self._replace_steps(steps)

        # Update ECU comboboxes without triggering user edits.

        self._refresh_ecu_combos()

        # Addressing -> ECU name is derived from the selected Vehicle, not a user edit:
        # refresh the dependent views but leave the document unmodified (no "*", no Save).

        self._step_signatures = self._runtime_signatures()

        self.document_changed.emit()

        self._selection_changed()

        return True

    @staticmethod

    def _is_valid_request_hex(value):

        text = str(value or "").strip()

        if not text:

            return False

        tokens = text.split()

        return all(

            re.fullmatch(r"[0-9A-Fa-f]{2}", token)

            for token in tokens

        )

    @classmethod
    def _request_payload(cls, value):
        tokens = str(value or "").split()
        if not tokens or not all(len(t) == 2 and set(t) <= set("0123456789abcdefABCDEF") for t in tokens):
            return None
        try:
            return bytes.fromhex(" ".join(tokens))
        except ValueError:
            return None

    
    def fn_refresh_theme(self):
        apply_panel_theme(self, "canDiagnosticTablePanel")

        with QSignalBlocker(self.table):
            super().fn_refresh_theme()

            self.lbl_import_ecu.fn_refresh_theme()

            self.cmb_import_ecu.fn_refresh_theme()

            fn_apply_scrollbar_style(self.cmb_import_ecu.view())

            colors = ThemeManager.fn_colors()

            # Match the foreground of selected table rows.
            selected_text = (
                colors.WINDOW
                if ThemeManager.fn_is_dark()
                else colors.TEXT_INVERT
            )

            # Reuse the existing V-CODE table style.
            # Only override selection foreground locally.
            self.table.setStyleSheet(
                fn_table_style()
                + f"""
                QTableWidget::item:selected {{
                    background-color: {colors.PRIMARY};
                    color: {selected_text};
                }}
                """
            )

            for widget in (
                self.title,
                self.notice,
                self.btn_add,
                self.btn_delete,
                self.btn_load,
                self.btn_settings,
                self.btn_run,
                self.btn_export,
                self.btn_stop,
            ):
                widget.fn_refresh_theme()

            for row in range(self.table.rowCount()):
                send_button = self.table.cellWidget(
                    row, self.COL_SEND
                )

                if send_button is not None:
                    send_button.fn_refresh_theme()

                ecu_combo = self.table.cellWidget(
                    row, self.COL_ECU
                )

                if ecu_combo is not None:
                    fn_apply_scrollbar_style(
                        ecu_combo.view()
                    )

                self._render_runtime(row)

        self._refresh_receive_selection_colors()


class ReceiveMessageDelegate(QStyledItemDelegate):
    """Keep model data but do not paint duplicate text."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.text = ""