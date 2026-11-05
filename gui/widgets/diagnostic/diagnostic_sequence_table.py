from __future__ import annotations

import re
from dataclasses import replace

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.diagnostic_sequence import (
    DiagnosticExecutionSettings,
    DiagnosticStep,
    DiagnosticTestCase,
)
from gui.themes.styles.controls.scrollbar_style import fn_apply_scrollbar_style
from gui.widgets.controls.primary_button import PrimaryButton
from gui.widgets.controls.secondary_button import SecondaryButton

from gui.widgets.controls.primary_combobox import PrimaryComboBox
from gui.widgets.controls.primary_label import PrimaryLabel
from gui.widgets.controls.primary_integer_spinbox import PrimaryIntegerSpinBox
from gui.widgets.controls.primary_table import PrimaryTable
from gui.widgets.vehicle_manager.vehicle_selector import VehicleSelectorWidget
from services.vehicle_service import VehicleService



_HEX_BYTE_PATTERN = re.compile(r"^[0-9A-Fa-f]{2}$")


class DiagnosticSequenceTable(QWidget):

    sequence_modified = Signal(object)

    ROW_HEIGHT = 40

    COL_STEP = 0
    COL_SEQUENCE_NAME = 1
    COL_ECU = 2
    COL_REQUEST = 3
    COL_DELAY = 4
    COL_REPEAT = 5
    COL_EXPECTED = 6
    COL_RECEIVE = 7
    COL_RESULT = 8

    HEADERS = (
        "Step",
        "Test Sequence Name",
        "ECU",
        "TX Message",
        "DL (ms)",
        "Loop",
        "EX Message",
        "RX Message",
        "Result",
    )

    def __init__(self, parent=None, vehicle_service=None):
        super().__init__(parent)

        self._test_case: DiagnosticTestCase | None = None
        self._vehicle_service = vehicle_service or VehicleService()
        self._current_vehicle_name = ""
        self._current_vehicle = None
        self._available_ecus = []
        self._is_populating = False
        self._is_dirty = False

        self._setup_ui()
        self._connect_signals()
        self.fn_refresh_vehicles()
        self.fn_load_sequence(None)
        self.fn_refresh_theme()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.execution_layout = QHBoxLayout()
        self.execution_layout.setContentsMargins(0, 0, 0, 0)
        self.execution_layout.setSpacing(8)

        self.vehicle_selector = VehicleSelectorWidget(
            orientation="horizontal"
        )

        self.lbl_loop = PrimaryLabel("Loop")
        self.spn_loop = PrimaryIntegerSpinBox()
        self.spn_loop.setRange(1, 9999)
        self.spn_loop.setSingleStep(1)
        self.spn_loop.setValue(1)

        self.lbl_command_delay = PrimaryLabel("DELAY")
        self.spn_command_delay = PrimaryIntegerSpinBox()
        self.spn_command_delay.setRange(0, 60000)
        self.spn_command_delay.setSingleStep(100)
        self.spn_command_delay.setValue(100)
        self.lbl_ms = PrimaryLabel("ms")

        self.btn_import_delay = SecondaryButton("Import", width=90)
        self.btn_add = SecondaryButton("+ Add", width=90)
        self.btn_export = PrimaryButton("EXPORT", width=100)
        self.btn_stop = PrimaryButton("STOP", width=100)
        self.btn_run = PrimaryButton("RUN", width=120)

        self.execution_layout.addWidget(
            self.vehicle_selector,
            0,
            Qt.AlignVCenter,
        )
        self.execution_layout.addWidget(self.btn_add)
        self.execution_layout.addSpacing(12)
        self.execution_layout.addWidget(self.lbl_loop)
        self.execution_layout.addWidget(self.spn_loop)
        self.execution_layout.addSpacing(12)
        self.execution_layout.addWidget(self.lbl_command_delay)
        self.execution_layout.addWidget(self.spn_command_delay)
        self.execution_layout.addWidget(self.lbl_ms)
        self.execution_layout.addWidget(self.btn_import_delay)
        self.execution_layout.addStretch(1)
        self.execution_layout.addWidget(self.btn_export)
        self.execution_layout.addWidget(self.btn_stop)
        self.execution_layout.addWidget(self.btn_run)

        self.table = PrimaryTable()
        self.table.setColumnCount(len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setSortingEnabled(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.verticalHeader().setDefaultSectionSize(self.ROW_HEIGHT)
        self.table.fn_enable_one_click_edit()
        self.table.installEventFilter(self)
        self.table.horizontalHeader().setStretchLastSection(True)
        self._configure_columns()

        layout.addLayout(self.execution_layout)
        layout.addWidget(self.table, 1)

    def _connect_signals(self):
        self.vehicle_selector.vehicle_changed.connect(
            self._on_vehicle_changed
        )
        self.spn_loop.valueChanged.connect(self._on_loop_changed)
        self.spn_command_delay.valueChanged.connect(
            self._on_command_delay_changed
        )
        self.btn_add.clicked.connect(
            self.fn_add_step_after_selected
        )
        self.btn_import_delay.clicked.connect(
            self.fn_import_execution_values_to_rows
        )
        self.table.itemChanged.connect(self._on_item_changed)

    def fn_refresh_vehicles(self, selected_vehicle_name: str = ""):
        if not selected_vehicle_name:
            selected_vehicle_name = self._current_vehicle_name

        try:
            vehicles = self._vehicle_service.list_vehicles()
        except Exception:
            vehicles = []

        if selected_vehicle_name and selected_vehicle_name not in vehicles:
            selected_vehicle_name = ""

        self.vehicle_selector.fn_set_vehicles(
            vehicles,
            selected_vehicle=selected_vehicle_name,
            allow_empty_selection=not bool(vehicles),
        )
        self._load_vehicle_by_name(self.vehicle_selector.fn_vehicle())
        self._refresh_ecu_combos()

    def fn_current_vehicle(self) -> str:
        return self._current_vehicle_name

    def fn_set_vehicle(self, vehicle):
        self._current_vehicle = vehicle
        self._current_vehicle_name = vehicle.name if vehicle else ""
        self._available_ecus = list(vehicle.ecus) if vehicle else []
        self._sync_vehicle_selector()
        self._refresh_ecu_combos()

    def fn_load_sequence(self, test_case):
        self._is_populating = True
        self._test_case = test_case
        self._is_dirty = False
        self.table.clearContents()
        self.table.setRowCount(0)

        if test_case is None:
            self._set_execution_values(
                loop=1,
                command_delay_ms=100,
            )
            self._is_populating = False
            return

        self._set_execution_values(
            loop=test_case.execution.loop,
            command_delay_ms=test_case.execution.command_delay_ms,
        )

        self._reload_steps_into_table()
        self._is_populating = False

    def fn_current_sequence(self):
        return self._test_case

    def fn_is_dirty(self):
        return self._is_dirty

    def fn_add_step(self):
        self.fn_add_step_after_selected()

    def fn_add_step_after_selected(self):
        self._ensure_test_case()
        insert_index = self._selected_insert_index()
        steps = list(self._test_case.steps)
        inherited = self._inherited_values_for_insert(insert_index, steps)
        steps.insert(
            insert_index,
            DiagnosticStep(
                step=insert_index + 1,
                sequence_name="",
                ecu=inherited["ecu"],
                request="",
                delay_ms=inherited["delay_ms"],
                repeat=inherited["repeat"],
                expected_response="",
                match="prefix",
                comment="",
            ),
        )
        self._replace_steps(steps)
        self._reload_steps_into_table()
        self._select_row(insert_index)
        self._mark_dirty()

    def fn_import_command_delay_to_rows(self):
        self.fn_import_execution_values_to_rows()

    def fn_import_execution_values_to_rows(self):
        if self._test_case is None or not self._test_case.steps:
            return

        selected_rows = self._selected_rows()
        target_rows = selected_rows or list(range(len(self._test_case.steps)))
        command_delay_ms = self.spn_command_delay.value()
        loop = self.spn_loop.value()
        steps = list(self._test_case.steps)

        for row in target_rows:
            steps[row] = replace(
                steps[row],
                delay_ms=command_delay_ms,
                repeat=loop,
            )

        self._replace_steps(steps)
        self._reload_steps_into_table()
        for row in target_rows:
            self.table.selectRow(row)
        self._mark_dirty()

    def fn_remove_selected_step(self):
        if self._test_case is None or not self._test_case.steps:
            return

        selected_rows = self._selected_rows()
        if not selected_rows:
            return

        remaining_steps = [
            step
            for row, step in enumerate(self._test_case.steps)
            if row not in selected_rows
        ]
        next_row = min(selected_rows[0], len(remaining_steps) - 1)

        self._replace_steps(remaining_steps)
        self._reload_steps_into_table()
        self._select_row(next_row)
        self._mark_dirty()

    def fn_move_step_up(self):
        return None

    def fn_move_step_down(self):
        return None

    def _ensure_test_case(self):
        if self._test_case is not None:
            return

        self._test_case = DiagnosticTestCase(
            schema_version=1,
            name="Untitled Diagnostic Sequence",
            description="",
            enabled=True,
            execution=DiagnosticExecutionSettings(),
            steps=[],
        )

    def _set_execution_values(self, loop, command_delay_ms):
        self.spn_loop.blockSignals(True)
        self.spn_command_delay.blockSignals(True)
        self.spn_loop.setValue(loop)
        self.spn_command_delay.setValue(command_delay_ms)
        self.spn_command_delay.blockSignals(False)
        self.spn_loop.blockSignals(False)

    def _reload_steps_into_table(self):
        self._is_populating = True
        self.table.clearContents()
        self.table.setRowCount(len(self._test_case.steps))
        for row, step in enumerate(self._test_case.steps):
            self._populate_step_row(row, step)
        self._is_populating = False

    def _populate_step_row(self, row, step):
        self._set_item(row, self.COL_STEP, step.step, editable=True)
        self._set_item(row, self.COL_SEQUENCE_NAME, step.sequence_name, editable=True)
        self._set_ecu_combo(row, step.ecu)
        self._set_item(row, self.COL_REQUEST, step.request, editable=True)
        self._set_item(row, self.COL_DELAY, self._format_optional_int(step.delay_ms), editable=True)
        self._set_item(row, self.COL_REPEAT, step.repeat, editable=True)
        self._set_item(row, self.COL_EXPECTED, step.expected_response, editable=True)
        self._set_item(row, self.COL_RECEIVE, "", editable=False)
        self._set_item(row, self.COL_RESULT, "", editable=False)

    def _set_item(self, row, column, value, editable):
        alignment = Qt.AlignCenter if column in (
            self.COL_STEP,
            self.COL_DELAY,
            self.COL_REPEAT,
            self.COL_RESULT,
        ) else Qt.AlignLeft | Qt.AlignVCenter
        item = self.table.fn_create_item(value, row, alignment=alignment)
        if not editable:
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, column, item)

    def _set_ecu_combo(self, row, ecu):
        combo = PrimaryComboBox(minimum_height=28)
        combo.blockSignals(True)

        selected_index = -1
        for index, vehicle_ecu in enumerate(self._available_ecus):
            combo.addItem(vehicle_ecu.name, vehicle_ecu)
            if vehicle_ecu.name == ecu:
                selected_index = index

        combo.setCurrentIndex(selected_index)
        combo.blockSignals(False)
        combo.currentTextChanged.connect(
            lambda value, current_row=row: self._on_ecu_changed(current_row, value)
        )
        combo.fn_refresh_theme()
        fn_apply_scrollbar_style(combo.view())
        self.table.setCellWidget(row, self.COL_ECU, combo)

    def _on_vehicle_changed(self, vehicle_name):
        self._load_vehicle_by_name(vehicle_name)
        self._refresh_ecu_combos()

    def _load_vehicle_by_name(self, vehicle_name):
        self._current_vehicle_name = vehicle_name or ""
        self._current_vehicle = None
        self._available_ecus = []

        if not self._current_vehicle_name:
            return

        try:
            vehicle = self._vehicle_service.load_vehicle(
                self._current_vehicle_name
            )
        except Exception:
            return

        self._current_vehicle = vehicle
        self._available_ecus = list(vehicle.ecus)

    def _sync_vehicle_selector(self):
        combo = self.vehicle_selector.cmb_vehicle
        combo.blockSignals(True)
        if self._current_vehicle_name:
            index = combo.findText(self._current_vehicle_name)
            if index >= 0:
                combo.setCurrentIndex(index)
            else:
                combo.setCurrentIndex(-1)
        else:
            combo.setCurrentIndex(-1)
        combo.blockSignals(False)

    def _refresh_ecu_combos(self):
        if self._test_case is None:
            return

        was_populating = self._is_populating
        self._is_populating = True
        for row, step in enumerate(self._test_case.steps):
            self._set_ecu_combo(row, step.ecu)
        self._is_populating = was_populating

    def _on_loop_changed(self, value):
        value = int(value)
        if self._is_populating:
            return
        if self._test_case is None or self._test_case.execution.loop == value:
            return

        execution = replace(self._test_case.execution, loop=value)
        self._replace_test_case(execution=execution)
        self._mark_dirty()

    def _on_command_delay_changed(self, value):
        value = int(value)
        if self._is_populating:
            return
        if (
            self._test_case is None
            or self._test_case.execution.command_delay_ms == value
        ):
            return

        execution = replace(
            self._test_case.execution,
            command_delay_ms=value,
        )
        self._replace_test_case(execution=execution)
        self._mark_dirty()

    def _on_item_changed(self, item):
        if self._is_populating or self._test_case is None:
            return

        row = item.row()
        column = item.column()
        if row >= len(self._test_case.steps):
            return

        step = self._test_case.steps[row]
        updated_step = self._updated_step_from_item(step, column, item.text())
        if updated_step is None:
            self._restore_step_row(row, step)
            return
        if updated_step == step:
            return

        steps = list(self._test_case.steps)
        steps[row] = updated_step
        self._replace_steps(steps)
        self._restore_step_row(row, self._test_case.steps[row])
        self._mark_dirty()

    def _on_ecu_changed(self, row, value):
        if self._is_populating or self._test_case is None:
            return
        if row >= len(self._test_case.steps):
            return
        if not value:
            return

        step = self._test_case.steps[row]
        if step.ecu == value:
            return
        steps = list(self._test_case.steps)
        steps[row] = replace(step, ecu=value)
        self._replace_steps(steps)
        self._mark_dirty()

    def _updated_step_from_item(self, step, column, text):
        if column == self.COL_STEP:
            value = self._validated_int(text, minimum=1)
            return replace(step, step=value) if value is not None else None
        if column == self.COL_SEQUENCE_NAME:
            return replace(step, sequence_name=text.strip())
        if column == self.COL_REQUEST:
            value = self._normalize_hex(text, allow_empty=True)
            return replace(step, request=value) if value is not None else None
        if column == self.COL_DELAY:
            value = self._validated_optional_int(text, minimum=0)
            return replace(step, delay_ms=value) if value is not False else None
        if column == self.COL_REPEAT:
            value = self._validated_int(text, minimum=1)
            return replace(step, repeat=value) if value is not None else None
        if column == self.COL_EXPECTED:
            value = self._normalize_hex(text, allow_empty=True)
            return replace(step, expected_response=value) if value is not None else None
        return step

    def _restore_step_row(self, row, step):
        self._is_populating = True
        self._populate_step_row(row, step)
        self._is_populating = False

    def _replace_test_case(self, **changes):
        if self._test_case is not None:
            self._test_case = replace(self._test_case, **changes)

    def _replace_steps(self, steps):
        reindexed_steps = [
            replace(step, step=index)
            for index, step in enumerate(steps, start=1)
        ]
        self._replace_test_case(steps=reindexed_steps)

    def _selected_rows(self):
        return sorted({
            index.row()
            for index in self.table.selectedIndexes()
        })

    def _selected_insert_index(self):
        selected_rows = self._selected_rows()
        if selected_rows:
            return selected_rows[-1] + 1
        return len(self._test_case.steps)

    @staticmethod
    def _inherited_values_for_insert(insert_index, steps):
        if insert_index <= 0 or not steps:
            return {
                "ecu": "",
                "delay_ms": 100,
                "repeat": 1,
            }
        previous_step = steps[insert_index - 1]
        return {
            "ecu": previous_step.ecu,
            "delay_ms": previous_step.delay_ms,
            "repeat": previous_step.repeat,
        }

    def eventFilter(self, watched, event):
        if (
            watched is self.table
            and event.type() == QEvent.KeyPress
            and event.key() == Qt.Key_Delete
        ):
            self.fn_remove_selected_step()
            return True
        return super().eventFilter(watched, event)

    def _select_row(self, row):
        self.table.clearSelection()
        if 0 <= row < self.table.rowCount():
            self.table.selectRow(row)
            self.table.setCurrentCell(row, self.COL_STEP)
            item = self.table.item(row, self.COL_STEP)
            if item is not None:
                self.table.scrollToItem(item)

    def _mark_dirty(self):
        self._is_dirty = True
        self.sequence_modified.emit(self._test_case)

    @staticmethod
    def _format_optional_int(value):
        return "" if value is None else str(value)

    @staticmethod
    def _validated_int(text, minimum=None, maximum=None):
        try:
            value = int(str(text).strip())
        except (TypeError, ValueError):
            return None
        if minimum is not None and value < minimum:
            return None
        if maximum is not None and value > maximum:
            return None
        return value

    @staticmethod
    def _validated_optional_int(text, minimum=None):
        text = str(text).strip()
        if text == "":
            return None
        value = DiagnosticSequenceTable._validated_int(text, minimum=minimum)
        if value is None:
            return False
        return value

    @staticmethod
    def _normalize_hex(text, allow_empty=False):
        text = str(text).strip()
        if not text:
            return "" if allow_empty else None
        tokens = text.split()
        if any(not _HEX_BYTE_PATTERN.fullmatch(token) for token in tokens):
            return None
        return " ".join(token.upper() for token in tokens)

    def _configure_columns(self):
        widths = {
            self.COL_STEP: 56,
            self.COL_SEQUENCE_NAME: 190,
            self.COL_ECU: 110,
            self.COL_REQUEST: 150,
            self.COL_DELAY: 76,
            self.COL_REPEAT: 64,
            self.COL_EXPECTED: 160,
            self.COL_RECEIVE: 150,
            self.COL_RESULT: 90,
        }
        header = self.table.horizontalHeader()
        for column, width in widths.items():
            self.table.setColumnWidth(column, width)
            header.setSectionResizeMode(column, QHeaderView.Interactive)
        header.setSectionResizeMode(self.COL_RESULT, QHeaderView.Stretch)
        self.table.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Expanding,
        )
        self.table.verticalHeader().setDefaultSectionSize(40)

    def fn_refresh_theme(self):
        self.vehicle_selector.fn_refresh_theme()
        for label in (
            self.lbl_loop,
            self.lbl_command_delay,
            self.lbl_ms,
        ):
            label.fn_refresh_theme()
        self.spn_loop.fn_refresh_theme()
        self.spn_command_delay.fn_refresh_theme()
        self.btn_import_delay.fn_refresh_theme()
        self.btn_add.fn_refresh_theme()
        self.btn_export.fn_refresh_theme()
        self.btn_stop.fn_refresh_theme()
        self.btn_run.fn_refresh_theme()
        self.table.fn_refresh_theme()
        for row in range(self.table.rowCount()):
            combo = self.table.cellWidget(row, self.COL_ECU)
            if hasattr(combo, "fn_refresh_theme"):
                combo.fn_refresh_theme()
