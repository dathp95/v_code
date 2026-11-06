from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QListWidget, QListWidgetItem, QPlainTextEdit, QTableWidgetItem,
    QVBoxLayout,
)

from core.advanced_sequence import AdvancedRow, render_advanced_steps
from core.sequence_exchange import parse_sequence_text
from gui.themes.styles.controls.scrollbar_style import fn_apply_scrollbar_style
from gui.themes.theme_manager import ThemeManager
from gui.widgets.can_interface.diagnostic_table_panel import HexItemDelegate, validate_and_format_hex
from gui.widgets.controls.cancel_button import CancelButton
from gui.widgets.controls.primary_button import PrimaryButton
from gui.widgets.controls.primary_checkbox import PrimaryCheckBox
from gui.widgets.controls.primary_combobox import PrimaryComboBox
from gui.widgets.controls.primary_label import PrimaryLabel
from gui.widgets.controls.primary_lineedit import PrimaryLineEdit
from gui.widgets.controls.primary_table import PrimaryTable
from gui.widgets.controls.secondary_button import SecondaryButton

COLUMNS = ("Step", "Test sequence name", "ECU", "Payload (HEX)", "Delay (ms)", "Repeat",
           "Expected Response (HEX)", "Receive Message (HEX)", "Results", "Comment")
NOTHING = "—"

IMPORT_MODE = "Import Sequence"
DEFAULT_MODE = "Default"

COLUMN_WIDTHS = (46, 170, 80, 130, 80, 64, 170, 150, 80, 220)
LIST_WIDTH = 200
FRAME_ALLOWANCE = 90  # Margins, spacing and the table frame / scroll bar around the columns.


class AdvancedSequenceDialog(QDialog):
    """Type a template once, tick the ECUs of a Vehicle: Apply renders the template for every ticked ECU."""

    (COL_STEP, COL_NAME, COL_ECU, COL_REQUEST, COL_DELAY, COL_REPEAT,
     COL_EXPECTED, COL_RECEIVE, COL_RESULT, COL_COMMENT) = range(10)

    # Filled in by the program, never typed: ECU is rendered per ticked ECU, Receive/Results come from a run.
    READ_ONLY = (COL_STEP, COL_ECU, COL_RECEIVE, COL_RESULT)

    def __init__(self, parent=None, *, vehicle_service, vehicle=""):
        super().__init__(parent)
        self._service = vehicle_service
        self.name = ""
        self.vehicle = ""
        self.steps = ()
        self.setWindowTitle("Add Sequence Advance")

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.lbl_name = PrimaryLabel("Sequence name")
        self.name_edit = PrimaryLineEdit("Name of the new sequence")
        self.name_edit.setMinimumHeight(34)
        self.lbl_vehicle = PrimaryLabel("Vehicle")
        self.vehicle_combo = PrimaryComboBox(minimum_height=34)
        self.vehicle_combo.setMinimumWidth(160)
        for widget in (self.lbl_name, self.name_edit, self.lbl_vehicle, self.vehicle_combo):
            top.addWidget(widget, 1 if widget is self.name_edit else 0)
        layout.addLayout(top)

        body = QHBoxLayout()
        side = QVBoxLayout()
        self.lbl_ecus = PrimaryLabel("ECUs of the Vehicle")
        self.chk_all = PrimaryCheckBox("Select all")
        self.chk_all.setChecked(True)
        self.ecu_list = QListWidget()
        self.ecu_list.setFixedWidth(LIST_WIDTH)
        self.ecu_list.setSelectionMode(QAbstractItemView.NoSelection)
        side.addWidget(self.lbl_ecus)
        side.addWidget(self.chk_all)
        side.addWidget(self.ecu_list, 1)
        body.addLayout(side)

        main = QVBoxLayout()
        self.paste_edit = QPlainTextEdit()
        self.paste_edit.setPlaceholderText("Paste a sequence copied with Export SEQ here. Its ECU column is ignored: "
                                           "the ECUs ticked on the left are used instead.")
        self.paste_edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.paste_edit.setMaximumHeight(120)
        self.paste_edit.setVisible(False)
        self.lbl_import_status = PrimaryLabel("")
        self.lbl_import_status.setTextFormat(Qt.PlainText)
        self.lbl_import_status.setVisible(False)
        main.addWidget(self.paste_edit)
        main.addWidget(self.lbl_import_status)
        self.table = PrimaryTable()
        self.table.setSortingEnabled(False)
        self.table.setColumnCount(len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.fn_enable_one_click_edit()
        for column, width in enumerate(COLUMN_WIDTHS):
            self.table.setColumnWidth(column, width)
        # Payload and Expected group HEX while typing and warn on incomplete bytes, like the main table.
        self.hex_delegate = HexItemDelegate(self.table)
        self.table.setItemDelegateForColumn(self.COL_REQUEST, self.hex_delegate)
        self.table.setItemDelegateForColumn(self.COL_EXPECTED, self.hex_delegate)
        main.addWidget(self.table, 1)
        rows = QHBoxLayout()
        self.mode_combo = PrimaryComboBox(minimum_height=32)
        self.mode_combo.addItems((IMPORT_MODE, DEFAULT_MODE))
        self.mode_combo.setCurrentIndex(self.mode_combo.findText(DEFAULT_MODE))
        self.mode_combo.setMinimumWidth(150)
        self.btn_add_row = SecondaryButton("+ Add row", width=100, height=32)
        self.btn_delete_row = SecondaryButton("Delete row", width=100, height=32)
        rows.addWidget(self.mode_combo)
        rows.addWidget(self.btn_add_row)
        rows.addWidget(self.btn_delete_row)
        rows.addStretch()
        main.addLayout(rows)
        body.addLayout(main, 1)
        layout.addLayout(body, 1)

        bottom = QHBoxLayout()
        self.lbl_summary = PrimaryLabel("")
        self.lbl_summary.setTextFormat(Qt.PlainText)
        self.btn_cancel = CancelButton("Cancel", width=90, height=32)
        self.btn_apply = PrimaryButton("Apply", width=90, height=32)
        bottom.addWidget(self.lbl_summary, 1)
        bottom.addWidget(self.btn_cancel)
        bottom.addWidget(self.btn_apply)
        layout.addLayout(bottom)

        names = self._vehicle_names()
        self.vehicle_combo.addItems(names)
        self.vehicle_combo.setCurrentIndex(max(self.vehicle_combo.findText(vehicle), 0) if names else -1)
        self._fill_ecus()
        self._add_row()

        self.vehicle_combo.currentIndexChanged.connect(self._fill_ecus)
        self.ecu_list.itemChanged.connect(self._ecu_ticked)
        self.chk_all.clicked.connect(self._select_all_clicked)
        self.name_edit.textChanged.connect(self._refresh_state)
        self.table.itemChanged.connect(self._cell_changed)
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        self.paste_edit.textChanged.connect(self._paste_changed)
        self.btn_add_row.clicked.connect(self._add_row)
        self.btn_delete_row.clicked.connect(self._delete_rows)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_apply.clicked.connect(self._apply)
        self.fn_refresh_theme()
        self._refresh_state()
        # Wide enough to read every column through Comment (as far as the screen allows).
        screen = QGuiApplication.primaryScreen()
        available = screen.availableGeometry().width() if screen is not None else self.preferred_width()
        self.resize(min(self.preferred_width(), int(available * 0.95)), 620)

    def preferred_width(self):
        return sum(COLUMN_WIDTHS) + LIST_WIDTH + FRAME_ALLOWANCE

    # --- Vehicle / ECUs --------------------------------------------------------
    def _vehicle_names(self):
        try:
            return list(self._service.list_vehicles())
        except Exception:
            return []

    def _ecu_names(self, vehicle_name):
        if not vehicle_name:
            return []
        try:
            names = [ecu.name for ecu in self._service.load_vehicle(vehicle_name).ecus if ecu.name and ecu.name.strip()]
        except Exception:
            return []
        return [name for name in names if names.count(name) == 1]  # An ambiguous name could not be resolved later.

    def _fill_ecus(self, *_):
        self.ecu_list.blockSignals(True)
        self.ecu_list.clear()
        for name in self._ecu_names(self.vehicle_combo.currentText()):
            item = QListWidgetItem(name)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)  # All ECUs are ticked by default.
            self.ecu_list.addItem(item)
        self.ecu_list.blockSignals(False)
        self._sync_select_all()
        self._refresh_state()

    def selected_ecus(self):
        return [self.ecu_list.item(i).text() for i in range(self.ecu_list.count())
                if self.ecu_list.item(i).checkState() == Qt.Checked]

    def _sync_select_all(self):
        self.chk_all.blockSignals(True)
        self.chk_all.setChecked(self.ecu_list.count() > 0 and len(self.selected_ecus()) == self.ecu_list.count())
        self.chk_all.blockSignals(False)

    def _ecu_ticked(self, _item):
        self._sync_select_all()
        self._refresh_state()

    def _select_all_clicked(self, _checked):
        # Everything ticked -> the click clears it; anything else (including a partial selection) ticks all.
        tick_all = len(self.selected_ecus()) != self.ecu_list.count()
        self.ecu_list.blockSignals(True)
        for index in range(self.ecu_list.count()):
            self.ecu_list.item(index).setCheckState(Qt.Checked if tick_all else Qt.Unchecked)
        self.ecu_list.blockSignals(False)
        self._sync_select_all()
        self._refresh_state()

    # --- template table ----------------------------------------------------------
    def _add_row(self, *_, values=None):
        row = self.table.rowCount()
        blocked = self.table.blockSignals(True)
        self.table.insertRow(row)
        defaults = {self.COL_ECU: "(per ECU)", self.COL_DELAY: "100", self.COL_REPEAT: "1",
                    self.COL_RECEIVE: NOTHING, self.COL_RESULT: NOTHING}
        if values is not None:
            defaults.update(values)
        for column in range(len(COLUMNS)):
            item = QTableWidgetItem(defaults.get(column, ""))
            item.setTextAlignment(Qt.AlignCenter if column in (self.COL_STEP, self.COL_DELAY, self.COL_REPEAT,
                                                              self.COL_RESULT) else Qt.AlignLeft | Qt.AlignVCenter)
            if column in self.READ_ONLY:
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(row, column, item)
        self.table.blockSignals(blocked)
        self._renumber()
        self._style_read_only()
        self._refresh_state()

    def _mode_changed(self, *_):
        importing = self.mode_combo.currentText() == IMPORT_MODE
        self.paste_edit.setVisible(importing)
        self.lbl_import_status.setVisible(importing and bool(self.lbl_import_status.text()))
        if importing:
            self._paste_changed()

    def _paste_changed(self):
        """Import Sequence mode: replace the template with the pasted sequence (its ECU column is ignored)."""
        text = self.paste_edit.toPlainText()
        if self.mode_combo.currentText() != IMPORT_MODE or not text.strip():
            self.lbl_import_status.clear()
            self.lbl_import_status.setVisible(False)
            return
        try:
            imported = parse_sequence_text(text)
        except ValueError as error:
            self.lbl_import_status.setText(str(error))  # The table keeps what it had.
            self.lbl_import_status.setToolTip("")
        else:
            self._load_rows(imported.steps)
            self.lbl_import_status.setText(
                f"{len(imported.steps)} row(s) loaded from the pasted sequence; its ECU column is ignored.")
            self.lbl_import_status.setToolTip("\n".join(imported.diagnostics))
        self.lbl_import_status.setVisible(True)

    def _load_rows(self, steps):
        blocked = self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.table.blockSignals(blocked)
        for step in steps:
            self._add_row(values={
                self.COL_NAME: step.sequence_name, self.COL_REQUEST: step.request,
                self.COL_DELAY: "" if step.delay_ms is None else str(step.delay_ms),
                self.COL_REPEAT: str(step.repeat), self.COL_EXPECTED: step.expected_response,
                self.COL_COMMENT: step.comment})

    def _delete_rows(self):
        for row in sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(row)
        self._renumber()
        self._refresh_state()

    def _cell_changed(self, item):
        if item.column() in (self.COL_REQUEST, self.COL_EXPECTED):
            self._format_hex_cell(item)
        self._refresh_state()

    def _format_hex_cell(self, item):
        """Group valid HEX ("1003" -> "10 03"); flag anything else (kept as typed, e.g. "10 0")."""
        valid, formatted, warning = validate_and_format_hex(item.text())
        blocked = self.table.blockSignals(True)
        if valid and formatted != item.text():
            item.setText(formatted)
        colors = ThemeManager.fn_colors()
        item.setForeground(QColor(colors.TEXT if valid else colors.WARNING))
        item.setToolTip("" if valid else f"Warning: {warning}")
        self.table.blockSignals(blocked)

    def _renumber(self):
        blocked = self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            self.table.item(row, self.COL_STEP).setText(str(row + 1))
        self.table.blockSignals(blocked)

    def template_rows(self):
        def text(row, column):
            item = self.table.item(row, column)
            return item.text() if item is not None else ""

        return [AdvancedRow(text(row, self.COL_NAME), text(row, self.COL_REQUEST), text(row, self.COL_DELAY),
                            text(row, self.COL_REPEAT), text(row, self.COL_EXPECTED), text(row, self.COL_COMMENT))
                for row in range(self.table.rowCount())]

    # --- state and result ----------------------------------------------------------
    def _refresh_state(self, *_):
        typed = sum(1 for row in self.template_rows() if not row.is_blank)
        ecus = len(self.selected_ecus())
        self.lbl_summary.setText(f"{typed} row(s) x {ecus} ECU(s) = {typed * ecus} step(s)")
        missing = ("Require sequence name" if not self.name_edit.text().strip()
                   else "Require at least one row with content" if typed == 0
                   else "Require at least one ECU" if ecus == 0 else "")
        self.btn_apply.setEnabled(not missing)
        self.btn_apply.setToolTip(missing)

    def _apply(self):
        self.name = self.name_edit.text().strip()
        self.vehicle = self.vehicle_combo.currentText()
        self.steps = render_advanced_steps(self.template_rows(), self.selected_ecus())
        self.accept()

    # --- theme ---------------------------------------------------------------------
    def _style_read_only(self):
        colors = ThemeManager.fn_colors()
        for row in range(self.table.rowCount()):
            for column in (self.COL_REQUEST, self.COL_EXPECTED):
                item = self.table.item(row, column)
                if item is not None:
                    self._format_hex_cell(item)
        for row in range(self.table.rowCount()):
            for column in self.READ_ONLY:
                item = self.table.item(row, column)
                if item is not None:
                    item.setBackground(QColor(colors.PANEL))
                    item.setForeground(QColor(colors.BUTTON_DISABLED_TEXT))

    def fn_refresh_theme(self):
        colors = ThemeManager.fn_colors()
        self.setStyleSheet(f"QDialog {{ background: {colors.WINDOW}; color: {colors.TEXT}; }}")
        self.ecu_list.setStyleSheet(
            f"QListWidget {{ background: {colors.WINDOW}; color: {colors.TEXT}; border: 1px solid {colors.BORDER}; "
            f"border-radius: 6px; padding: 4px; }} QListWidget::item {{ padding: 5px; }}")
        fn_apply_scrollbar_style(self.ecu_list)
        fn_apply_scrollbar_style(self.table)
        self.table.fn_refresh_theme()
        self._style_read_only()
        self.paste_edit.setStyleSheet(
            f"QPlainTextEdit {{ background: {colors.WINDOW}; color: {colors.TEXT}; border: 1px solid {colors.BORDER}; "
            f"border-radius: 6px; padding: 6px; font-family: Consolas; }}")
        fn_apply_scrollbar_style(self.paste_edit)
        for widget in (self.lbl_name, self.name_edit, self.lbl_vehicle, self.vehicle_combo, self.lbl_ecus,
                       self.chk_all, self.lbl_summary, self.lbl_import_status, self.mode_combo, self.btn_add_row,
                       self.btn_delete_row, self.btn_cancel, self.btn_apply):
            widget.fn_refresh_theme()
