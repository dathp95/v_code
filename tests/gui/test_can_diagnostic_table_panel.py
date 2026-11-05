import os
import unittest
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QFocusEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem
from core.diagnostic_sequence import DiagnosticStep, DiagnosticTestCase
from models.vehicle import Vehicle
from models.ecu import ECU


class CanDiagnosticTableUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_panel(self, count=3, ecus=None):
        from gui.widgets.can_interface.diagnostic_table_panel import CanDiagnosticTablePanel
        vehicle_ecus = ecus if ecus is not None else [ECU('TEST')]
        service = SimpleNamespace(list_vehicles=lambda: ['BENCH'], load_vehicle=lambda _: Vehicle('BENCH', ecus=vehicle_ecus))
        panel = CanDiagnosticTablePanel(vehicle_service=service)
        self.addCleanup(panel.deleteLater)
        panel.resize(1500, 500)
        panel.show()
        panel.fn_load_sequence(DiagnosticTestCase(1, 'TEST', '', True,
            [DiagnosticStep(i, '', 'TEST', '22 F1 90', expected_response='62 F1 90') for i in range(1, count + 1)]))
        self.app.processEvents()
        return panel

    def click_header_checkbox(self, panel):
        header = panel.table.horizontalHeader()
        x = header.sectionViewportPosition(panel.COL_CHECK) + header.sectionSize(panel.COL_CHECK) // 2
        QTest.mouseClick(header.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(x, header.height() // 2))
        self.app.processEvents()

    def editor_for(self, panel, column):
        delegate = panel.table.itemDelegateForColumn(column)
        editor = delegate.createEditor(panel.table.viewport(), QStyleOptionViewItem(), panel.table.model().index(0, column))
        self.addCleanup(editor.deleteLater)
        editor.show()
        return editor

    # --- toolbar ---------------------------------------------------------
    def test_run_export_stop_lead_the_toolbar_aligned_with_the_table(self):
        panel = self.make_panel()
        for button in (panel.btn_run, panel.btn_export, panel.btn_stop):
            self.assertEqual((button.minimumWidth(), button.maximumWidth()), (120, 120))
        left = lambda widget: widget.mapTo(panel, QPoint(0, 0)).x()
        self.assertEqual(left(panel.btn_run), left(panel.table))
        self.assertLess(left(panel.btn_run), left(panel.btn_export))
        self.assertLess(left(panel.btn_export), left(panel.btn_stop))
        self.assertLess(left(panel.btn_stop), left(panel.vehicle_selector))
        self.assertLess(left(panel.vehicle_selector), left(panel.btn_add))

    # --- select all ------------------------------------------------------
    def test_all_rows_are_selected_by_default_and_header_checkbox_toggles_them(self):
        panel = self.make_panel()
        header = panel.table.horizontalHeader()
        self.assertEqual(panel.table.horizontalHeaderItem(panel.COL_CHECK).text(), '')
        self.assertEqual(panel.checked_step_ids(), tuple(panel.step_ids))
        self.assertEqual(header.check_state(), Qt.Checked)
        signals = []
        panel.selected_rows_changed.connect(signals.append)
        self.click_header_checkbox(panel)
        self.assertEqual(panel.checked_step_ids(), ())
        self.assertEqual(header.check_state(), Qt.Unchecked)
        self.assertTrue(all(panel.table.item(r, panel.COL_CHECK).checkState() == Qt.Unchecked for r in range(3)))
        self.click_header_checkbox(panel)
        self.assertEqual(panel.checked_step_ids(), tuple(panel.step_ids))
        self.assertTrue(all(panel.table.item(r, panel.COL_CHECK).checkState() == Qt.Checked for r in range(3)))
        self.assertEqual(signals, [(), tuple(panel.step_ids)])

    def test_header_checkbox_is_partial_for_mixed_rows_and_follows_add_and_remove(self):
        panel = self.make_panel()
        header = panel.table.horizontalHeader()
        panel.table.item(1, panel.COL_CHECK).setCheckState(Qt.Unchecked)
        self.assertEqual(header.check_state(), Qt.PartiallyChecked)
        self.click_header_checkbox(panel)  # Mixed -> select everything.
        self.assertEqual(header.check_state(), Qt.Checked)
        panel.table.item(0, panel.COL_CHECK).setCheckState(Qt.Unchecked)
        panel.table.selectRow(0)
        panel.fn_add_step_after_selected()
        new_id = panel.step_ids[1]
        self.assertIn(new_id, panel.checked_step_ids())
        self.assertEqual(header.check_state(), Qt.PartiallyChecked)
        panel.table.selectRow(0)
        panel.fn_remove_selected_step()
        self.assertEqual(header.check_state(), Qt.Checked)

    # --- live HEX formatting ---------------------------------------------
    def test_typing_hex_is_grouped_in_pairs_while_typing(self):
        panel = self.make_panel()
        for column in (panel.COL_REQUEST, panel.COL_EXPECTED):
            editor = self.editor_for(panel, column)
            QTest.keyClicks(editor, '22f190')
            self.assertEqual(editor.text(), '22 F1 90')
            self.assertEqual(editor.cursorPosition(), len('22 F1 90'))
            editor.clear()
            QTest.keyClicks(editor, '22F')
            self.assertEqual(editor.text(), '22 F')

    def test_live_hex_grouping_keeps_cursor_and_leaves_invalid_text_alone(self):
        panel = self.make_panel()
        editor = self.editor_for(panel, panel.COL_REQUEST)
        QTest.keyClicks(editor, '22F190')
        editor.setCursorPosition(2)
        QTest.keyClicks(editor, 'a')
        self.assertEqual(editor.text(), '22 AF 19 0')
        self.assertEqual(editor.cursorPosition(), 4)
        editor.clear()
        QTest.keyClicks(editor, 'zz')
        self.assertEqual(editor.text(), 'zz')
        self.assertIn('HEX', editor.toolTip())

    # --- Receive Message ---------------------------------------------------
    def test_receive_message_is_left_aligned_and_shows_the_start_of_long_data(self):
        from gui.widgets.can_interface.diagnostic_table_panel import ReadOnlyHexCell
        panel = self.make_panel(1)
        long_payload = ' '.join(f'{i:02X}' for i in range(40))
        panel.set_step_result(panel.step_ids[0], long_payload, 'Passed')
        cell = panel.table.cellWidget(0, panel.COL_RECEIVE)
        self.assertIsInstance(cell, ReadOnlyHexCell)
        self.assertEqual(cell.cursorPosition(), 0)
        self.assertTrue(cell.alignment() & Qt.AlignLeft)
        panel.set_step_result(panel.step_ids[0], '62 F1 90 ' + long_payload, 'Passed')
        self.assertEqual(cell.cursorPosition(), 0)

    def test_clicked_receive_message_gets_the_same_editor_look_as_expected_response(self):
        panel = self.make_panel(1)
        panel.set_step_result(panel.step_ids[0], '62 F1 90', 'Passed')
        cell = panel.table.cellWidget(0, panel.COL_RECEIVE)
        resting = cell.styleSheet()
        cell.focusInEvent(QFocusEvent(QEvent.FocusIn))
        focused = cell.styleSheet()
        self.assertNotEqual(resting, focused)
        self.assertIn('border: 1px solid', focused)
        cell.focusOutEvent(QFocusEvent(QEvent.FocusOut))
        self.assertEqual(cell.styleSheet(), resting)

    def test_sequence_name_uses_the_same_editor_style_as_expected_response(self):
        panel = self.make_panel(1)
        name = self.editor_for(panel, panel.COL_SEQUENCE_NAME)
        expected = self.editor_for(panel, panel.COL_EXPECTED)
        self.assertEqual(name.objectName(), expected.objectName())
        name.setText('Start Diagnostic Session')  # Free text is never flagged as invalid HEX.
        self.assertEqual(name.toolTip(), '')
        self.assertEqual(name.text(), 'Start Diagnostic Session')

    # --- toolbar height and the row send buttons -------------------------------
    def test_toolbar_controls_are_taller(self):
        panel = self.make_panel(1)
        self.app.processEvents()
        for widget in (panel.btn_run, panel.btn_export, panel.btn_stop, panel.btn_add, panel.btn_delete,
                       panel.btn_settings, panel.vehicle_selector.cmb_vehicle):
            self.assertGreaterEqual(widget.height(), 40, widget.objectName() or type(widget).__name__)
        self.assertEqual((panel.btn_run.width(), panel.btn_export.width(), panel.btn_stop.width()), (120, 120, 120))

    def send_button_gaps(self, panel, row):
        """Pixels of cell background around the drawn send button: (left, right, top, bottom)."""
        self.app.processEvents()
        table = panel.table
        image = table.viewport().grab().toImage()
        x0 = table.columnViewportPosition(panel.COL_SEND)
        y0 = table.rowViewportPosition(row)
        width, height = table.columnWidth(panel.COL_SEND), table.rowHeight(row)
        background = image.pixelColor(x0, y0 + height // 2).name()
        # The last pixel column / row of a cell is the grid line, not cell background.
        across = [image.pixelColor(x0 + dx, y0 + height // 2).name() != background for dx in range(width - 1)]
        down = [image.pixelColor(x0 + width // 2, y0 + dy).name() != background for dy in range(height - 1)]
        return (across.index(True), across[::-1].index(True), down.index(True), down[::-1].index(True))

    def test_send_button_is_centered_in_its_cell(self):
        panel = self.cursor_panel(['BCM', 'BMS'])
        for row in (0, 1):
            left, right, top, bottom = self.send_button_gaps(panel, row)
            self.assertLessEqual(abs(left - right), 1, (row, left, right))
            self.assertLessEqual(abs(top - bottom), 1, (row, top, bottom))
            self.assertGreaterEqual(min(left, right, top, bottom), 3)  # A real margin on every side.
        self.assertGreaterEqual(panel.table.columnWidth(panel.COL_SEND), 44)

    def test_a_running_request_does_not_make_every_send_button_flash(self):
        from PySide6.QtCore import QEvent, QObject

        class Counter(QObject):
            count = 0

            def eventFilter(self, watched, event):
                if event.type() == QEvent.EnabledChange:
                    Counter.count += 1
                return False

        panel = self.cursor_panel(['BCM', 'BMS', 'SS'])
        buttons = [panel.table.cellWidget(row, panel.COL_SEND) for row in range(3)]
        counter = Counter()
        self.addCleanup(counter.deleteLater)
        for button in buttons:
            button.installEventFilter(counter)
        sent = []
        panel.row_send_requested.connect(sent.append)
        panel.set_request_busy(True)
        self.assertTrue(all(button.isEnabled() for button in buttons))
        buttons[1].click()  # A click while busy is refused, with an explanation...
        self.assertEqual(sent, [])
        self.assertIn('already running', panel.notice.text())
        panel.set_request_busy(False)
        buttons[1].click()  # ...and works again afterwards.
        self.assertEqual(sent, [panel.step_ids[1]])
        self.assertEqual(Counter.count, 0)  # No button changed state, so none repainted.

    # --- Settings: ECU + Import --------------------------------------------
    def select_rows(self, panel, rows):
        from PySide6.QtCore import QItemSelectionModel
        panel.table.clearSelection()
        for row in rows:
            panel.table.selectionModel().select(
                panel.table.model().index(row, panel.COL_STEP),
                QItemSelectionModel.Select | QItemSelectionModel.Rows)
        self.app.processEvents()

    VEHICLE_ECUS = (('BCM', '681', '601'), ('BMS', '682', '602'), ('SS', '683', '603'))

    def cursor_panel(self, row_ecus, select_vehicle=True):
        """A panel whose rows carry the given ECU names (all checked), on a Vehicle with BCM, BMS and SS."""
        from gui.widgets.can_interface.diagnostic_table_panel import CanDiagnosticTablePanel
        vehicle = Vehicle('BENCH', ecus=[ECU(*values) for values in self.VEHICLE_ECUS])
        panel = CanDiagnosticTablePanel(vehicle_service=SimpleNamespace(list_vehicles=lambda: ['BENCH'], load_vehicle=lambda _: vehicle))
        self.addCleanup(panel.deleteLater)
        panel.resize(1500, 500)
        panel.show()
        panel.fn_load_sequence(DiagnosticTestCase(1, 'TEST', '', True,
            [DiagnosticStep(i, '', ecu, '22 F1 90') for i, ecu in enumerate(row_ecus, 1)]))
        if select_vehicle:
            panel.vehicle_selector.fn_set_vehicle('BENCH')
        self.app.processEvents()
        return panel

    def rows(self, panel):
        return [(s.ecu, s.repeat, s.delay_ms) for s in panel.fn_current_sequence().steps]

    def combo_items(self, panel):
        return [panel.cmb_import_ecu.itemText(i) for i in range(panel.cmb_import_ecu.count())]

    def test_import_ecu_combo_and_button_need_a_vehicle_then_list_its_ecus(self):
        panel = self.cursor_panel(['BCM', 'BMS'], select_vehicle=False)
        combo = panel.cmb_import_ecu
        self.assertFalse(combo.isEnabled())  # No Vehicle yet: a hint, never an empty list.
        self.assertFalse(panel.btn_import_delay.isEnabled())
        self.assertEqual(self.combo_items(panel), ['Select Vehicle first'])
        panel.vehicle_selector.fn_set_vehicle('BENCH')
        self.assertTrue(combo.isEnabled())
        self.assertTrue(panel.btn_import_delay.isEnabled())
        self.assertEqual(self.combo_items(panel), ['', 'BCM', 'BMS', 'SS'])  # The blank entry means: keep every ECU.
        panel.fn_set_vehicle(None)
        self.assertFalse(combo.isEnabled())
        self.assertFalse(panel.btn_import_delay.isEnabled())
        self.assertEqual(combo.currentText(), 'Select Vehicle first')

    def test_import_row_is_loop_delay_ecu_then_import_then_undo(self):
        panel = self.make_panel(1)
        layout = panel.execution_layout
        widgets = [layout.itemAt(i).widget() for i in range(layout.count())]
        wanted = (panel.lbl_ms, panel.lbl_import_ecu, panel.cmb_import_ecu, panel.btn_import_delay, panel.btn_import_undo)
        self.assertEqual([w for w in widgets if w in wanted], list(wanted))
        self.assertEqual(panel.btn_import_undo.text(), 'Undo')
        self.assertFalse(panel.btn_import_undo.isEnabled())  # Nothing to undo yet.

    # --- the ECU box mirrors the row under the cursor ------------------------
    def test_ecu_combo_shows_the_ecu_of_the_row_under_the_cursor(self):
        panel = self.cursor_panel(['BCM', 'BMS', 'SS', 'GHOST'])
        combo = panel.cmb_import_ecu
        for row, expected in ((2, 'SS'), (0, 'BCM'), (1, 'BMS')):
            panel.table.selectRow(row)
            self.assertEqual(combo.currentText(), expected, row)
        panel.table.selectRow(3)  # The row's ECU is not an ECU of the Vehicle: the blank entry is selected.
        self.assertEqual((combo.currentIndex(), combo.currentText()), (0, ''))
        panel.table.selectRow(0)
        panel.table.cellWidget(0, panel.COL_ECU).setCurrentIndex(panel.table.cellWidget(0, panel.COL_ECU).findText('SS'))
        self.assertEqual(combo.currentText(), 'SS')  # Follows an ECU edit of that same row.

    def test_import_writes_loop_delay_and_the_cursor_rows_ecu_into_every_checked_row(self):
        panel = self.cursor_panel(['BCM', 'BMS', 'SS'])
        ids = tuple(panel.step_ids)
        panel.spn_loop.setValue(5)
        panel.spn_command_delay.setValue(1500)
        panel.table.selectRow(0)
        self.assertEqual(panel.cmb_import_ecu.currentText(), 'BCM')  # The cursor row's ECU is the default.
        panel._is_dirty = False
        panel.btn_import_delay.click()
        # Rows 1, 2 and 3 are all checked: they all end up with the same ECU, Loop and Delay.
        self.assertEqual(self.rows(panel), [('BCM', 5, 1500)] * 3)
        self.assertEqual(tuple(panel.step_ids), ids)
        self.assertEqual(panel.checked_step_ids(), ids)  # Ticks survive the import.
        self.assertEqual(panel.table.currentRow(), 0)
        self.assertEqual(panel.cmb_import_ecu.currentText(), 'BCM')
        self.assertTrue(panel.fn_is_dirty())

    def test_import_leaves_unchecked_rows_and_their_results_alone(self):
        panel = self.cursor_panel(['BCM', 'BMS', 'SS'])
        ids = tuple(panel.step_ids)
        panel.set_step_result(ids[1], '62 F1 90', 'Passed')
        panel.spn_loop.setValue(4)
        panel.spn_command_delay.setValue(500)
        panel.table.item(1, panel.COL_CHECK).setCheckState(Qt.Unchecked)
        panel.table.selectRow(2)
        self.assertEqual(panel.cmb_import_ecu.currentText(), 'SS')
        panel.btn_import_delay.click()
        self.assertEqual(self.rows(panel), [('SS', 4, 500), ('BMS', 1, 100), ('SS', 4, 500)])
        self.assertEqual(panel.checked_step_ids(), (ids[0], ids[2]))
        self.assertIn(ids[1], panel._runtime)

    def test_import_writes_a_deliberately_chosen_ecu_into_every_checked_row(self):
        panel = self.cursor_panel(['BCM', 'BMS', 'SS'])
        panel.spn_loop.setValue(2)
        panel.table.selectRow(1)
        panel.cmb_import_ecu.setCurrentIndex(panel.cmb_import_ecu.findText('SS'))
        panel.btn_import_delay.click()
        self.assertEqual(self.rows(panel), [('SS', 2, 100)] * 3)

    def test_blank_ecu_entry_imports_loop_and_delay_while_keeping_every_ecu(self):
        panel = self.cursor_panel(['BCM', 'BMS', 'SS'])
        panel.spn_loop.setValue(3)
        panel.spn_command_delay.setValue(700)
        panel.table.selectRow(1)
        self.assertEqual(panel.cmb_import_ecu.currentText(), 'BMS')
        panel.cmb_import_ecu.setCurrentIndex(0)  # The user picks the blank entry.
        panel.btn_import_delay.click()
        self.assertEqual(self.rows(panel), [('BCM', 3, 700), ('BMS', 3, 700), ('SS', 3, 700)])
        panel.btn_import_undo.click()
        self.assertEqual(self.rows(panel), [('BCM', 1, 100), ('BMS', 1, 100), ('SS', 1, 100)])

    def test_import_into_nothing_checked_changes_nothing_even_with_a_cursor_row(self):
        panel = self.cursor_panel(['BCM', 'BMS', 'SS'])
        panel.spn_loop.setValue(5)
        panel.set_all_checked(False)
        panel.table.selectRow(1)
        panel._is_dirty = False
        panel.btn_import_delay.click()
        self.assertEqual(self.rows(panel), [('BCM', 1, 100), ('BMS', 1, 100), ('SS', 1, 100)])
        self.assertFalse(panel.fn_is_dirty())
        self.assertIn('Check', panel.notice.text())

    def test_import_never_writes_an_ecu_when_the_cursor_row_has_none_selected_in_the_box(self):
        panel = self.cursor_panel(['BCM', 'GHOST'])
        panel.spn_loop.setValue(3)
        panel.table.item(0, panel.COL_CHECK).setCheckState(Qt.Unchecked)
        panel.table.selectRow(1)
        self.assertEqual(panel.cmb_import_ecu.currentText(), '')
        panel.btn_import_delay.click()
        self.assertEqual(self.rows(panel), [('BCM', 1, 100), ('GHOST', 3, 100)])

    def test_import_with_nothing_checked_or_selected_changes_nothing_and_says_so(self):
        panel = self.cursor_panel(['BCM', 'BMS'])
        panel.spn_loop.setValue(5)
        panel.set_all_checked(False)
        panel.table.clearSelection()
        panel.table.setCurrentCell(-1, -1)
        panel._is_dirty = False
        panel.btn_import_delay.click()
        self.assertEqual(self.rows(panel), [('BCM', 1, 100), ('BMS', 1, 100)])
        self.assertFalse(panel.fn_is_dirty())
        self.assertFalse(panel.btn_import_undo.isEnabled())
        self.assertIn('Check', panel.notice.text())

    # --- Undo -------------------------------------------------------------
    def test_undo_restores_the_state_before_each_import_step_by_step(self):
        panel = self.cursor_panel(['BCM', 'BMS', 'SS'])
        original = self.rows(panel)
        panel.spn_loop.setValue(3)
        panel.spn_command_delay.setValue(250)
        panel.table.selectRow(0)
        panel.cmb_import_ecu.setCurrentIndex(panel.cmb_import_ecu.findText('SS'))
        panel.btn_import_delay.click()
        first = self.rows(panel)
        self.assertNotEqual(first, original)
        self.assertTrue(panel.btn_import_undo.isEnabled())
        panel.spn_loop.setValue(7)
        panel.spn_command_delay.setValue(900)
        panel.table.selectRow(2)
        panel.cmb_import_ecu.setCurrentIndex(panel.cmb_import_ecu.findText('BCM'))
        panel.btn_import_delay.click()
        second = self.rows(panel)
        panel.btn_import_undo.click()
        self.assertEqual(self.rows(panel), first)
        self.assertTrue(panel.btn_import_undo.isEnabled())
        panel.btn_import_undo.click()
        self.assertEqual(self.rows(panel), original)
        self.assertFalse(panel.btn_import_undo.isEnabled())
        self.assertNotEqual(second, original)

    def test_undo_restores_only_what_import_changed_and_keeps_other_edits(self):
        panel = self.cursor_panel(['BCM', 'BMS'])
        ids = tuple(panel.step_ids)
        panel.spn_loop.setValue(4)
        panel.table.selectRow(0)
        panel.cmb_import_ecu.setCurrentIndex(panel.cmb_import_ecu.findText('SS'))
        panel.btn_import_delay.click()
        panel.table.item(0, panel.COL_COMMENT).setText('typed after import')
        panel.table.item(1, panel.COL_REQUEST).setText('10 03')
        panel.btn_import_undo.click()
        steps = panel.fn_current_sequence().steps
        self.assertEqual([(s.ecu, s.repeat) for s in steps], [('BCM', 1), ('BMS', 1)])
        self.assertEqual((steps[0].comment, steps[1].request), ('typed after import', '10 03'))
        self.assertEqual(tuple(panel.step_ids), ids)
        self.assertTrue(panel.fn_is_dirty())

    def test_undo_survives_removed_rows_and_is_cleared_by_loading_a_sequence(self):
        panel = self.cursor_panel(['BCM', 'BMS', 'SS'])
        panel.spn_loop.setValue(4)
        panel.btn_import_delay.click()
        panel.table.selectRow(0)
        panel.fn_remove_selected_step()
        panel.btn_import_undo.click()  # The removed row is skipped; the others are restored.
        self.assertEqual(self.rows(panel), [('BMS', 1, 100), ('SS', 1, 100)])
        self.assertFalse(panel.btn_import_undo.isEnabled())
        panel.btn_import_delay.click()
        self.assertTrue(panel.btn_import_undo.isEnabled())
        panel.fn_load_sequence(DiagnosticTestCase(1, 'OTHER', '', True, [DiagnosticStep(1, '', 'TEST', '22 F1 90')]))
        self.assertFalse(panel.btn_import_undo.isEnabled())

    # --- Import SEQ: where the rows go ---------------------------------------
    def imported(self, *names):
        from core.sequence_exchange import export_sequence_text, parse_sequence_text
        steps = [DiagnosticStep(i, name, 'SS', '22 F1 90') for i, name in enumerate(names, 1)]
        return parse_sequence_text(export_sequence_text(steps))

    def names(self, panel):
        return [s.sequence_name for s in panel.fn_current_sequence().steps]

    def test_append_goes_below_the_cursor_row_by_default(self):
        panel = self.cursor_panel(['BCM', 'BMS', 'SS'])
        for index, name in enumerate(('a', 'b', 'c')):
            panel.table.item(index, panel.COL_SEQUENCE_NAME).setText(name)
        ids = tuple(panel.step_ids)
        panel.set_step_result(ids[2], '62 F1 90', 'Passed')
        panel.table.selectRow(1)
        panel.apply_import(self.imported('x', 'y'), 'below')
        self.assertEqual(self.names(panel), ['a', 'b', 'x', 'y', 'c'])
        self.assertEqual([s.step for s in panel.fn_current_sequence().steps], [1, 2, 3, 4, 5])
        self.assertEqual((panel.step_ids[0], panel.step_ids[1], panel.step_ids[4]), (ids[0], ids[1], ids[2]))
        self.assertIn(ids[2], panel._runtime)  # Existing rows keep their results...
        self.assertEqual(set(panel.checked_step_ids()), set(panel.step_ids))  # ...and new rows are ticked.
        self.assertEqual(panel._selected_rows(), [2, 3])  # The imported rows are highlighted.
        self.assertTrue(panel.fn_is_dirty())

    def test_append_above_inserts_before_the_cursor_row(self):
        panel = self.cursor_panel(['BCM', 'BMS', 'SS'])
        for index, name in enumerate(('a', 'b', 'c')):
            panel.table.item(index, panel.COL_SEQUENCE_NAME).setText(name)
        panel.table.selectRow(1)
        panel.apply_import(self.imported('x', 'y'), 'above')
        self.assertEqual(self.names(panel), ['a', 'x', 'y', 'b', 'c'])

    def test_append_without_a_cursor_row_goes_to_the_end_or_the_start(self):
        for mode, expected in (('below', ['a', 'b', 'x']), ('above', ['x', 'a', 'b']), ('append', ['a', 'b', 'x'])):
            panel = self.cursor_panel(['BCM', 'BMS'])
            panel.table.item(0, panel.COL_SEQUENCE_NAME).setText('a')
            panel.table.item(1, panel.COL_SEQUENCE_NAME).setText('b')
            panel.table.clearSelection()
            panel.table.setCurrentCell(-1, -1)
            panel.apply_import(self.imported('x'), mode)
            self.assertEqual(self.names(panel), expected, mode)

    def test_replace_still_replaces_everything(self):
        panel = self.cursor_panel(['BCM', 'BMS'])
        panel.apply_import(self.imported('only'), 'replace')
        self.assertEqual(self.names(panel), ['only'])
        with self.assertRaises(ValueError):
            panel.apply_import(self.imported('x'), 'sideways')

    def test_the_apps_own_export_can_be_pasted_back_even_with_blank_names(self):
        from core.sequence_exchange import parse_sequence_text
        panel = self.cursor_panel(['BCM', 'BMS', 'SS'])  # Every sequence name is blank.
        panel.table.selectRow(0)
        panel.apply_import(parse_sequence_text(panel.exchange_text()), 'below')
        self.assertEqual([s.ecu for s in panel.fn_current_sequence().steps], ['BCM', 'BCM', 'BMS', 'SS', 'BMS', 'SS'])

    def test_import_dialog_has_no_preview_and_apply_reads_the_text_directly(self):
        from PySide6.QtWidgets import QDialog
        from gui.dialogs.sequence_exchange_dialog import SequenceExchangeDialog
        from core.sequence_exchange import export_sequence_text
        dialog = SequenceExchangeDialog(ecu_names={'BCM'})
        self.addCleanup(dialog.deleteLater)
        self.assertFalse(hasattr(dialog, 'btn_preview') or hasattr(dialog, 'preview'))
        items = [dialog.mode_combo.itemText(i) for i in range(dialog.mode_combo.count())]
        self.assertEqual(items, ['Append below cursor', 'Append above cursor', 'Replace'])
        self.assertEqual(dialog.mode_combo.currentIndex(), 0)
        self.assertFalse(dialog.btn_apply.isEnabled())  # Nothing pasted yet.
        dialog.editor.setPlainText(export_sequence_text([DiagnosticStep(1, '', 'BCM', '22 F1 90', None, 1)])
                                   + 'garbage')  # Blank name, odd trailing row: still importable.
        self.assertTrue(dialog.btn_apply.isEnabled())
        for index, mode in enumerate(('below', 'above', 'replace')):
            dialog.mode_combo.setCurrentIndex(index)
            dialog.btn_apply.click()  # One click parses and accepts.
            self.assertEqual((dialog.mode, dialog.result()), (mode, QDialog.Accepted))
            self.assertEqual(len(dialog.parsed.steps), 2)
        dialog.editor.setPlainText('   \n')
        self.assertFalse(dialog.btn_apply.isEnabled())

    def test_import_dialog_stays_open_and_explains_unreadable_text(self):
        from PySide6.QtWidgets import QDialog
        from gui.dialogs.sequence_exchange_dialog import SequenceExchangeDialog
        dialog = SequenceExchangeDialog(ecu_names=None)
        self.addCleanup(dialog.deleteLater)
        dialog.editor.setPlainText('1\t"unterminated\tBCM\n')
        self.assertTrue(dialog.btn_apply.isEnabled())
        dialog.btn_apply.click()
        self.assertIsNone(dialog.parsed)
        self.assertNotEqual(dialog.result(), QDialog.Accepted)
        self.assertIn('Row 1', dialog.status.text())
        dialog.editor.setPlainText('1\tname\tBCM\t22 F1 90\n')  # Typing again clears the old message.
        self.assertEqual(dialog.status.text(), '')

    # --- Filter: text box + result combo ----------------------------------------
    def filter_panel(self):
        """Four rows with distinct content in every field."""
        panel = self.cursor_panel(['BCM', 'BMS', 'SS', 'BCM'])
        values = [('Read VIN', 'battery low', '22 F1 90', 100, 1), ('Start', 'check cell', '10 03', 250, 2),
                  ('ODO', 'mileage', '22 F1 21', 100, 1), ('Reset', '', '11 01', 500, 3)]
        steps = [DiagnosticStep(i, name, ecu, request, delay, repeat, comment=comment)
                 for i, ((name, comment, request, delay, repeat), ecu)
                 in enumerate(zip(values, ['BCM', 'BMS', 'SS', 'BCM']), 1)]
        panel.fn_load_sequence(DiagnosticTestCase(1, 'T', '', True, steps))
        self.app.processEvents()
        return panel

    def visible(self, panel):
        return [row for row in range(panel.table.rowCount()) if not panel.table.isRowHidden(row)]

    def test_filter_box_and_result_combo_sit_after_setting_in_the_toolbar(self):
        panel = self.make_panel(1)
        self.app.processEvents()
        toolbar = panel.layout().itemAt(0)
        widgets = [toolbar.itemAt(i).widget() for i in range(toolbar.count())]
        order = [w for w in widgets if w in (panel.btn_delete, panel.btn_settings, panel.edt_filter, panel.cmb_result_filter)]
        self.assertEqual(order, [panel.btn_delete, panel.btn_settings, panel.edt_filter, panel.cmb_result_filter])
        for widget in (panel.edt_filter, panel.cmb_result_filter):
            self.assertGreaterEqual(widget.height(), 40)
        self.assertEqual([panel.cmb_result_filter.itemText(i) for i in range(4)], ['All results', 'Passed', 'Failed', 'Timeout'])
        self.assertTrue(panel.edt_filter.placeholderText())

    def test_typing_in_the_filter_keeps_rows_matching_any_field(self):
        panel = self.filter_panel()
        panel.set_step_result(panel.step_ids[2], '62 F1 21 41 42', 'Passed')
        ids = tuple(panel.step_ids)
        for text, expected in (('bms', [1]),            # ECU
                               ('read vin', [0]),       # name, any case
                               ('MILEAGE', [2]),        # comment
                               ('f190', [0]),           # HEX without spaces matches "22 F1 90"
                               ('22 f1', [0, 2]),       # payload
                               ('500', [3]),            # delay
                               ('4142', [2]),           # received data
                               ('passed', [2]),         # result
                               ('nothing like this', []),
                               ('  ', [0, 1, 2, 3]),
                               ('', [0, 1, 2, 3])):
            panel.edt_filter.setText(text)
            self.assertEqual(self.visible(panel), expected, text)
        self.assertEqual(tuple(panel.step_ids), ids)  # Filtering never touches the data.
        self.assertFalse(panel.fn_is_dirty())

    def test_result_combo_is_inactive_until_a_result_exists_then_filters_by_it(self):
        panel = self.filter_panel()
        combo = panel.cmb_result_filter
        self.assertFalse(combo.isEnabled())
        panel.set_step_result(panel.step_ids[0], '', 'Running')  # Not a result yet.
        self.assertFalse(combo.isEnabled())
        panel.set_step_result(panel.step_ids[0], '62 F1 90', 'Passed')
        panel.set_step_result(panel.step_ids[1], '7F 10 22', 'Error')       # shown as Failed
        panel.set_step_result(panel.step_ids[2], '', 'Timeout')
        panel.set_step_result(panel.step_ids[3], '62 11', 'Not Evaluated')  # shown as Passed
        self.assertTrue(combo.isEnabled())
        for label, expected in (('Passed', [0, 3]), ('Failed', [1]), ('Timeout', [2]), ('All results', [0, 1, 2, 3])):
            combo.setCurrentIndex(combo.findText(label))
            self.assertEqual(self.visible(panel), expected, label)
        combo.setCurrentIndex(combo.findText('Passed'))
        panel.edt_filter.setText('bcm')  # Both filters must hold.
        self.assertEqual(self.visible(panel), [0, 3])
        panel.edt_filter.setText('read')
        self.assertEqual(self.visible(panel), [0])
        panel.reset_runtime_results()  # No results any more: combo off and back on "All results".
        self.assertFalse(combo.isEnabled())
        self.assertEqual(combo.currentIndex(), 0)
        self.assertEqual(self.visible(panel), [0])  # The text filter still applies.

    def test_restored_results_re_enable_the_result_combo(self):
        panel = self.filter_panel()
        panel.set_step_result(panel.step_ids[0], '62 F1 90', 'Failed')
        snapshot = panel.runtime_snapshot()
        panel.fn_load_sequence(panel.fn_current_sequence())  # A fresh load has no results...
        self.assertFalse(panel.cmb_result_filter.isEnabled())
        panel.restore_runtime_snapshot(snapshot)  # ...until the earlier ones are put back.
        self.assertTrue(panel.cmb_result_filter.isEnabled())
        panel.cmb_result_filter.setCurrentIndex(panel.cmb_result_filter.findText('Failed'))
        self.assertEqual(self.visible(panel), [0])

    def test_filter_survives_the_table_being_rebuilt_but_never_hides_a_row_being_edited(self):
        panel = self.filter_panel()
        panel.edt_filter.setText('bcm')
        self.assertEqual(self.visible(panel), [0, 3])
        panel.table.item(0, panel.COL_COMMENT).setText('typed: no longer matches')
        panel.table.item(0, panel.COL_SEQUENCE_NAME).setText('zzz')
        self.assertEqual(self.visible(panel), [0, 3])  # Still on screen while you edit it.
        panel.spn_loop.setValue(2)
        panel.table.selectRow(0)
        panel.cmb_import_ecu.setCurrentIndex(0)  # Blank entry: keep every ECU.
        panel.btn_import_delay.click()  # Rebuilds every row...
        self.assertEqual(self.visible(panel), [0, 3])  # ...and the filter is applied again.
        panel.edt_filter.setText('')
        self.assertEqual(self.visible(panel), [0, 1, 2, 3])

    # --- right-click menu on the table -------------------------------------------
    MENU = ['COPY', 'SAVE', 'UNDO', 'DEL', '-', 'CLEAR', 'RUN', '-', 'Insert row down', 'Insert row up', '-',
            'Import sequence', 'Export sequence']

    def menu_actions(self, menu):
        return {action.text(): action for action in menu.actions() if not action.isSeparator()}

    def test_context_menu_has_the_requested_entries_and_separators(self):
        panel = self.cursor_panel(['BCM', 'BMS'])
        menu = panel.build_context_menu(0, panel.COL_REQUEST)
        self.addCleanup(menu.deleteLater)
        self.assertEqual(['-' if action.isSeparator() else action.text() for action in menu.actions()], self.MENU)
        self.assertEqual(panel.table.contextMenuPolicy(), Qt.CustomContextMenu)
        self.assertEqual(panel.table.cellWidget(0, panel.COL_RECEIVE).contextMenuPolicy(), Qt.NoContextMenu)

    def test_right_click_on_cell_widgets_reaches_the_tables_menu(self):
        from PySide6.QtGui import QContextMenuEvent
        panel = self.cursor_panel(['BCM', 'BMS', 'SS'])
        panel.set_step_result(panel.step_ids[1], '62 F1 90 41', 'Passed')
        panel.table.customContextMenuRequested.disconnect(panel._show_context_menu)  # Never open a real menu here.
        asked = []
        panel.table.customContextMenuRequested.connect(
            lambda position: asked.append(panel.table.indexAt(position).row()))
        for row, column in ((1, panel.COL_RECEIVE), (2, panel.COL_ECU), (0, panel.COL_SEND)):
            widget = panel.table.cellWidget(row, column)
            position = widget.rect().center()
            QApplication.sendEvent(widget, QContextMenuEvent(QContextMenuEvent.Mouse, position, widget.mapToGlobal(position)))
            self.assertEqual(asked[-1:], [row], (row, column))
        self.assertEqual(len(asked), 3)

    def test_copy_puts_the_value_of_the_clicked_cell_on_the_clipboard(self):
        panel = self.cursor_panel(['BCM', 'BMS'])
        panel.set_step_result(panel.step_ids[1], '62 F1 90 41', 'Passed')
        panel.table.item(0, panel.COL_COMMENT).setText('my note')
        clipboard = QApplication.clipboard()
        for row, column, expected in ((1, panel.COL_ECU, 'BMS'), (0, panel.COL_REQUEST, '22 F1 90'),
                                      (1, panel.COL_RECEIVE, '62 F1 90 41'), (0, panel.COL_COMMENT, 'my note'),
                                      (1, panel.COL_STEP, '2'), (1, panel.COL_RESULT, 'Passed')):
            clipboard.setText('before')
            action = self.menu_actions(panel.build_context_menu(row, column))['COPY']
            self.assertTrue(action.isEnabled(), (row, column))
            action.trigger()
            self.assertEqual(clipboard.text(), expected, (row, column))
        for row, column in ((0, panel.COL_RECEIVE), (0, panel.COL_SEND), (0, panel.COL_SEQUENCE_NAME)):
            self.assertFalse(self.menu_actions(panel.build_context_menu(row, column))['COPY'].isEnabled(), (row, column))

    def test_right_click_selects_the_row_unless_it_is_already_part_of_the_selection(self):
        panel = self.cursor_panel(['BCM', 'BMS', 'SS'])
        self.select_rows(panel, [0, 2])
        panel.build_context_menu(2, panel.COL_REQUEST)  # Inside the selection: keep it all.
        self.assertEqual(panel._selected_rows(), [0, 2])
        self.assertEqual(panel.table.currentRow(), 2)
        panel.build_context_menu(1, panel.COL_REQUEST)  # Outside: just that row.
        self.assertEqual(panel._selected_rows(), [1])

    def test_del_removes_the_selected_rows_and_clear_wipes_receive_and_results(self):
        panel = self.cursor_panel(['BCM', 'BMS', 'SS'])
        ids = tuple(panel.step_ids)
        self.select_rows(panel, [0, 2])
        self.menu_actions(panel.build_context_menu(0, panel.COL_REQUEST))['DEL'].trigger()
        self.assertEqual(tuple(panel.step_ids), (ids[1],))
        panel.set_step_result(ids[1], '62 F1 90', 'Passed')
        clear = self.menu_actions(panel.build_context_menu(0, panel.COL_REQUEST))['CLEAR']
        self.assertTrue(clear.isEnabled())
        clear.trigger()
        self.assertEqual(panel._runtime, {})
        self.assertEqual((panel.table.item(0, panel.COL_RECEIVE).text(), panel.table.item(0, panel.COL_RESULT).text()),
                         ('\u2014', '\u2014'))
        self.assertFalse(self.menu_actions(panel.build_context_menu(0, panel.COL_REQUEST))['CLEAR'].isEnabled())

    def test_run_and_save_do_what_their_buttons_do(self):
        panel = self.cursor_panel(['BCM', 'BMS'])
        events = []
        panel.sequence_run_requested.connect(lambda: events.append('run'))
        panel.save_requested.connect(lambda: events.append('save'))
        actions = self.menu_actions(panel.build_context_menu(0, panel.COL_REQUEST))
        self.assertEqual(actions['RUN'].isEnabled(), panel.btn_run.isEnabled())
        panel.btn_run.setEnabled(True)
        panel.set_save_available(False)
        actions = self.menu_actions(panel.build_context_menu(0, panel.COL_REQUEST))
        self.assertTrue(actions['RUN'].isEnabled())
        self.assertFalse(actions['SAVE'].isEnabled())  # Same as the Save button: nothing to save.
        panel.set_save_available(True)
        actions = self.menu_actions(panel.build_context_menu(0, panel.COL_REQUEST))
        actions['RUN'].trigger()
        actions['SAVE'].trigger()
        self.assertEqual(events, ['run', 'save'])
        panel.btn_run.setEnabled(False)
        self.assertFalse(self.menu_actions(panel.build_context_menu(0, panel.COL_REQUEST))['RUN'].isEnabled())

    def test_insert_row_down_and_up_work_relative_to_the_clicked_row(self):
        panel = self.cursor_panel(['BCM', 'BMS', 'SS'])
        for index, name in enumerate(('a', 'b', 'c')):
            panel.table.item(index, panel.COL_SEQUENCE_NAME).setText(name)
        ids = tuple(panel.step_ids)
        panel._is_dirty = False
        self.menu_actions(panel.build_context_menu(1, panel.COL_REQUEST))['Insert row down'].trigger()
        self.assertEqual(self.names(panel), ['a', 'b', '', 'c'])
        self.assertEqual([panel.step_ids[i] for i in (0, 1, 3)], [ids[0], ids[1], ids[2]])
        self.assertIn(panel.step_ids[2], panel.checked_step_ids())  # Like +Add Row: new rows are ticked...
        self.assertEqual(panel.fn_current_sequence().steps[2].ecu, 'BMS')  # ...and inherit from the row above.
        self.assertTrue(panel.fn_is_dirty())
        self.menu_actions(panel.build_context_menu(0, panel.COL_REQUEST))['Insert row up'].trigger()
        self.assertEqual(self.names(panel), ['', 'a', 'b', '', 'c'])
        self.assertEqual([s.step for s in panel.fn_current_sequence().steps], [1, 2, 3, 4, 5])
        self.assertEqual(len(panel.step_ids), 5)
        self.assertEqual(panel.table.rowCount(), 5)

    def test_insert_without_a_clicked_row_goes_to_the_end_or_the_start(self):
        panel = self.cursor_panel(['BCM', 'BMS'])
        panel.table.item(0, panel.COL_SEQUENCE_NAME).setText('a')
        panel.table.item(1, panel.COL_SEQUENCE_NAME).setText('b')
        self.menu_actions(panel.build_context_menu(-1, -1))['Insert row down'].trigger()
        self.assertEqual(self.names(panel), ['a', 'b', ''])
        self.menu_actions(panel.build_context_menu(-1, -1))['Insert row up'].trigger()
        self.assertEqual(self.names(panel), ['', 'a', 'b', ''])

    def test_import_and_export_sequence_reuse_the_existing_actions(self):
        from unittest.mock import MagicMock, patch
        from gui.controllers.can_workspace_controller import CanWorkspaceController
        panel = self.cursor_panel(['BCM'])
        events = []
        panel.import_sequence_requested.connect(lambda: events.append('import'))
        panel.export_sequence_requested.connect(lambda: events.append('export'))
        actions = self.menu_actions(panel.build_context_menu(0, panel.COL_REQUEST))
        self.assertTrue(actions['Import sequence'].isEnabled() and actions['Export sequence'].isEnabled())
        actions['Import sequence'].trigger()
        actions['Export sequence'].trigger()
        self.assertEqual(events, ['import', 'export'])
        # In the real tab they land on the very handlers the sidebar buttons use.
        import tempfile
        from pathlib import Path
        from gui.tabs.can_interface_tab import CANInterfaceTab
        from repositories.can_interface_ui_store import CanInterfaceUiStore
        from tests.gui.test_can_interface_tab import FakeCANService
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory, \
                patch.object(CanWorkspaceController, 'import_sequence', MagicMock()) as imp, \
                patch.object(CanWorkspaceController, 'export_sequence', MagicMock()) as exp, \
                patch.object(CanWorkspaceController, 'save_sequence', MagicMock()) as sav:
            tab = CANInterfaceTab(FakeCANService(), ui_store=CanInterfaceUiStore(Path(directory) / 'ui'))
            self.addCleanup(tab.deleteLater)
            self.addCleanup(tab.close)
            tab.sequence_table.import_sequence_requested.emit()
            tab.sequence_table.export_sequence_requested.emit()
            tab.sequence_table.save_requested.emit()
            imp.assert_called_once()
            exp.assert_called_once()
            sav.assert_called()

    def test_save_entry_follows_the_sidebar_save_button_state(self):
        import tempfile
        from pathlib import Path
        from gui.tabs.can_interface_tab import CANInterfaceTab
        from repositories.can_interface_ui_store import CanInterfaceUiStore
        from tests.gui.test_can_interface_tab import FakeCANService
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            tab = CANInterfaceTab(FakeCANService(), ui_store=CanInterfaceUiStore(Path(directory) / 'ui'))
            self.addCleanup(tab.deleteLater)
            self.addCleanup(tab.close)
            table = tab.sequence_table
            tab._on_sequence_selected(DiagnosticTestCase(1, 'T', '', True, [DiagnosticStep(1, '', 'BCM', '22 F1 90')]))
            tab.workspace_controller._sync_actions()
            self.assertEqual(self.menu_actions(table.build_context_menu(0, table.COL_REQUEST))['SAVE'].isEnabled(),
                             tab.sequence_list.btn_save.isEnabled())

    # --- UNDO in the right-click menu: step back through changes to the table ------
    def undo(self, panel):
        action = self.menu_actions(panel.build_context_menu(0, panel.COL_REQUEST))['UNDO']
        self.assertTrue(action.isEnabled())
        action.trigger()

    def undo_enabled(self, panel):
        return self.menu_actions(panel.build_context_menu(0, panel.COL_REQUEST))['UNDO'].isEnabled()

    def snapshot(self, panel):
        return ([(s.sequence_name, s.ecu, s.request, s.delay_ms, s.repeat, s.comment) for s in panel.fn_current_sequence().steps],
                tuple(panel.step_ids), panel.checked_step_ids())

    def test_undo_walks_back_through_every_kind_of_change_in_order(self):
        panel = self.cursor_panel(['BCM', 'BMS', 'SS'])
        self.assertFalse(self.undo_enabled(panel))  # Nothing has changed yet.
        states = [self.snapshot(panel)]
        panel.table.item(0, panel.COL_COMMENT).setText('typed')                       # edit a cell
        states.append(self.snapshot(panel))
        panel.table.cellWidget(1, panel.COL_ECU).setCurrentIndex(panel.table.cellWidget(1, panel.COL_ECU).findText('SS'))
        states.append(self.snapshot(panel))                                           # change an ECU
        panel.table.selectRow(0)
        panel.fn_insert_row(0, above=False)                                           # insert a row
        states.append(self.snapshot(panel))
        panel.table.selectRow(1)
        panel.fn_remove_selected_step()                                               # delete a row
        states.append(self.snapshot(panel))
        panel.table.item(0, panel.COL_CHECK).setCheckState(Qt.Unchecked)             # a tick is not a document change
        self.assertEqual(self.snapshot(panel)[:2], states[-1][:2])
        for expected in reversed(states[:-1]):
            self.undo(panel)
            self.assertEqual(self.snapshot(panel)[:2], expected[:2])
        self.assertFalse(self.undo_enabled(panel))
        self.assertEqual(panel.table.rowCount(), 3)

    def test_undo_brings_back_deleted_rows_with_their_ids_ticks_and_results(self):
        panel = self.cursor_panel(['BCM', 'BMS', 'SS'])
        ids = tuple(panel.step_ids)
        panel.set_step_result(ids[1], '62 F1 90', 'Passed')
        panel.table.item(1, panel.COL_CHECK).setCheckState(Qt.Unchecked)
        panel.table.selectRow(1)
        panel.fn_remove_selected_step()
        self.assertEqual(tuple(panel.step_ids), (ids[0], ids[2]))
        self.undo(panel)
        self.assertEqual(tuple(panel.step_ids), ids)
        self.assertEqual(panel._runtime[ids[1]][1], 'Passed')
        self.assertEqual(panel.table.item(1, panel.COL_RESULT).text(), 'Passed')
        self.assertNotIn(ids[1], panel.checked_step_ids())  # Its tick comes back as it was.
        self.assertEqual(panel.table.rowCount(), 3)

    def test_undo_of_an_edit_keeps_results_of_other_rows(self):
        panel = self.cursor_panel(['BCM', 'BMS'])
        ids = tuple(panel.step_ids)
        panel.set_step_result(ids[0], '62 F1 90', 'Passed')
        panel.set_step_result(ids[1], '62 F1 90', 'Failed')
        panel.table.item(0, panel.COL_REQUEST).setText('22 F1 91')  # Invalidates only row 1's result.
        self.assertNotIn(ids[0], panel._runtime)
        self.undo(panel)
        self.assertEqual(panel.table.item(0, panel.COL_REQUEST).text(), '22 F1 90')
        self.assertEqual(panel._runtime[ids[0]][1], 'Passed')  # The result valid for that payload is back.
        self.assertEqual(panel._runtime[ids[1]][1], 'Failed')

    def test_undo_does_not_record_itself_and_loading_a_sequence_clears_the_history(self):
        panel = self.cursor_panel(['BCM', 'BMS'])
        panel.table.item(0, panel.COL_COMMENT).setText('one')
        panel.table.item(0, panel.COL_COMMENT).setText('two')
        self.undo(panel)
        self.undo(panel)
        self.assertFalse(self.undo_enabled(panel))  # Two changes, two undos, nothing left.
        panel.table.item(0, panel.COL_COMMENT).setText('again')
        self.assertTrue(self.undo_enabled(panel))
        panel.fn_load_sequence(DiagnosticTestCase(1, 'OTHER', '', True, [DiagnosticStep(1, '', 'BCM', '22 F1 90')]))
        self.assertFalse(self.undo_enabled(panel))

    def test_undo_back_to_the_saved_state_clears_the_modified_mark(self):
        panel = self.cursor_panel(['BCM', 'BMS'])
        panel._is_dirty = False
        reverted, modified = [], []
        panel.reverted_to_saved.connect(lambda: reverted.append(True))
        panel.sequence_modified.connect(modified.append)
        panel.table.item(0, panel.COL_COMMENT).setText('one')
        panel.table.item(0, panel.COL_COMMENT).setText('two')
        self.assertTrue(panel.fn_is_dirty())
        self.undo(panel)
        self.assertTrue(panel.fn_is_dirty())  # Still different from what was loaded.
        self.assertEqual(reverted, [])
        self.undo(panel)
        self.assertFalse(panel.fn_is_dirty())  # Back to the loaded (saved) content.
        self.assertEqual(reverted, [True])

    def test_undo_across_a_save_makes_the_document_modified_again(self):
        panel = self.cursor_panel(['BCM', 'BMS'])
        panel._is_dirty = False
        panel.table.item(0, panel.COL_COMMENT).setText('before save')
        panel.mark_saved()  # What the workspace does after writing the file.
        panel.table.item(0, panel.COL_COMMENT).setText('after save')
        self.undo(panel)
        self.assertEqual(panel.table.item(0, panel.COL_COMMENT).text(), 'before save')
        self.assertFalse(panel.fn_is_dirty())  # Equal to the saved file.
        self.undo(panel)
        self.assertEqual(panel.table.item(0, panel.COL_COMMENT).text(), '')
        self.assertTrue(panel.fn_is_dirty())  # Older than the saved file.

    def test_undo_in_the_tab_updates_the_save_button_and_title(self):
        import tempfile
        from pathlib import Path
        from gui.tabs.can_interface_tab import CANInterfaceTab
        from repositories.can_interface_ui_store import CanInterfaceUiStore
        from tests.gui.test_can_interface_tab import FakeCANService
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            tab = CANInterfaceTab(FakeCANService(), ui_store=CanInterfaceUiStore(Path(directory) / 'ui'))
            self.addCleanup(tab.deleteLater)
            self.addCleanup(tab.close)
            table = tab.sequence_table
            source = Path(directory) / 'seq.json'
            tab.workspace_controller.repository.fn_save_sequence(
                DiagnosticTestCase(1, 'seq', '', True, [DiagnosticStep(1, 'row', 'BCM', '22 F1 90')]), source)
            tab.workspace_controller.open_source(str(source))
            self.assertFalse(table.fn_is_dirty())
            table.table.item(0, table.COL_COMMENT).setText('edited')
            self.assertTrue(tab.sequence_list.btn_save.isEnabled())
            self.undo(table)
            self.assertFalse(table.fn_is_dirty())
            self.assertFalse(tab.sequence_list.btn_save.isEnabled())
            self.assertFalse(table.title.text().endswith('*'))
            self.assertFalse(tab.workspace_controller._session_dirty)

    # --- Loop / Delay are a remembered preference, not sequence data ----------
    def test_settings_strip_values_never_touch_the_sequence_and_are_announced(self):
        panel = self.cursor_panel(['BCM', 'BMS'])
        announced = []
        panel.import_settings_changed.connect(lambda *values: announced.append(values))
        before = panel.fn_current_sequence().execution
        panel._is_dirty = False
        panel.spn_loop.setValue(6)
        panel.spn_command_delay.setValue(800)
        panel.cmb_import_ecu.setCurrentIndex(1)  # The ECU follows the cursor row: it is never remembered.
        self.assertEqual(announced, [(6, 100), (6, 800)])
        self.assertEqual(panel.fn_current_sequence().execution, before)
        self.assertFalse(panel.fn_is_dirty())  # Adjusting the strip never enables Save.
        panel.fn_load_sequence(DiagnosticTestCase(1, 'OTHER', '', True, [DiagnosticStep(1, '', 'BCM', '22 F1 90')]))
        panel.fn_load_sequence(None)
        self.assertEqual((panel.spn_loop.value(), panel.spn_command_delay.value()), (6, 800))

    def test_apply_import_settings_restores_loop_and_delay_silently(self):
        panel = self.make_panel(1)
        announced = []
        panel.import_settings_changed.connect(lambda *values: announced.append(values))
        panel.apply_import_settings(loop=6, delay_ms=800)
        self.assertEqual((panel.spn_loop.value(), panel.spn_command_delay.value()), (6, 800))
        self.assertEqual(announced, [])  # Restoring is not a user change, so nothing is re-saved.
        panel.apply_import_settings(delay_ms=300)
        self.assertEqual((panel.spn_loop.value(), panel.spn_command_delay.value()), (6, 300))

    # --- Results column ----------------------------------------------------
    def test_theme_owns_the_result_and_negative_response_colors(self):
        from dataclasses import fields
        from gui.themes.colors import DARK_COLORS, LIGHT_COLORS, ThemeColors
        names = {field.name for field in fields(ThemeColors)}
        tokens = {'RESULT_PASSED_BG', 'RESULT_FAILED_BG', 'RESULT_TIMEOUT_BG', 'RESULT_TEXT', 'NEGATIVE_RESPONSE_TEXT'}
        self.assertTrue(tokens <= names)
        for colors in (LIGHT_COLORS, DARK_COLORS):
            self.assertEqual(colors.RESULT_TEXT.upper(), '#FFFFFF')
            self.assertEqual(len({colors.RESULT_PASSED_BG, colors.RESULT_FAILED_BG, colors.RESULT_TIMEOUT_BG}), 3)

    def test_results_show_only_passed_failed_or_timeout(self):
        panel = self.make_panel(8)
        cases = [('Passed', 'Passed'), ('Not Evaluated', 'Passed'), ('Failed', 'Failed'), ('Error', 'Failed'),
                 ('Timeout', 'Timeout'), ('Running', '\u2014'), ('Pending', '\u2014'), ('Cancelled', '\u2014')]
        for row, (outcome, _label) in enumerate(cases):
            panel.set_step_result(panel.step_ids[row], '62 F1 90', outcome, f'detail {outcome}')
        for row, (outcome, label) in enumerate(cases):
            self.assertEqual(panel.table.item(row, panel.COL_RESULT).text(), label, outcome)
            self.assertEqual(panel._runtime[panel.step_ids[row]][1], outcome)  # The raw outcome is kept.
            self.assertEqual(panel.table.item(row, panel.COL_RESULT).toolTip(), f'detail {outcome}')

    def result_pixel(self, panel, row):
        self.app.processEvents()
        table = panel.table
        x = table.columnViewportPosition(panel.COL_RESULT) + 3
        y = table.rowViewportPosition(row) + table.rowHeight(row) // 2
        return table.viewport().grab().toImage().pixelColor(x, y).name().lower()

    def test_result_cells_are_filled_from_theme_colors_even_when_the_row_is_selected(self):
        from gui.themes.theme import ThemeType
        from gui.themes.theme_manager import ThemeManager
        panel = self.make_panel(4)
        for row, outcome in enumerate(('Passed', 'Failed', 'Timeout')):
            panel.set_step_result(panel.step_ids[row], '62 F1 90', outcome)
        self.addCleanup(ThemeManager.fn_set_theme, ThemeManager.fn_theme())
        for theme in (ThemeType.LIGHT, ThemeType.DARK):
            ThemeManager.fn_set_theme(theme)
            panel.fn_refresh_theme()
            colors = ThemeManager.fn_colors()
            panel.table.clearSelection()
            self.assertEqual(self.result_pixel(panel, 0), colors.RESULT_PASSED_BG.lower())
            self.assertEqual(self.result_pixel(panel, 1), colors.RESULT_FAILED_BG.lower())
            self.assertEqual(self.result_pixel(panel, 2), colors.RESULT_TIMEOUT_BG.lower())
            self.assertNotIn(self.result_pixel(panel, 3), (colors.RESULT_PASSED_BG.lower(), colors.RESULT_FAILED_BG.lower(),
                                                          colors.RESULT_TIMEOUT_BG.lower()))
            panel.table.selectRow(1)
            self.assertEqual(self.result_pixel(panel, 1), colors.RESULT_FAILED_BG.lower())

    # --- Receive Message ---------------------------------------------------
    def test_negative_response_is_red_and_bold_and_positive_is_not(self):
        from gui.themes.theme_manager import ThemeManager
        panel = self.make_panel(3)
        panel.set_step_result(panel.step_ids[0], '7F 22 31', 'Failed')
        panel.set_step_result(panel.step_ids[1], '62 F1 90 7F', 'Passed')
        negative = panel.table.cellWidget(0, panel.COL_RECEIVE).styleSheet()
        positive = panel.table.cellWidget(1, panel.COL_RECEIVE).styleSheet()
        self.assertIn(ThemeManager.fn_colors().NEGATIVE_RESPONSE_TEXT, negative)
        self.assertIn('font-weight: bold', negative)
        self.assertNotIn('font-weight: bold', positive)
        self.assertNotIn(ThemeManager.fn_colors().NEGATIVE_RESPONSE_TEXT, positive)
        panel.set_step_result(panel.step_ids[0], '62 F1 90', 'Passed')  # The look follows the new content.
        self.assertNotIn('font-weight: bold', panel.table.cellWidget(0, panel.COL_RECEIVE).styleSheet())

    def test_clicking_receive_message_selects_all_text_like_the_payload_cell(self):
        panel = self.make_panel(2)
        panel.set_step_result(panel.step_ids[1], '62 F1 90 41 42 43', 'Passed')
        cell = panel.table.cellWidget(1, panel.COL_RECEIVE)
        QTest.mouseClick(cell, Qt.LeftButton, Qt.NoModifier, QPoint(5, cell.height() // 2))
        self.assertEqual(cell.selectedText(), '62 F1 90 41 42 43')
        self.assertEqual(panel.table.currentRow(), 1)
        self.assertEqual(panel.selected_step_id(), panel.step_ids[1])

    # --- fonts -----------------------------------------------------------
    def test_table_text_uses_the_same_font_as_the_ecu_column(self):
        from gui.widgets.can_interface.diagnostic_table_panel import fn_hex_font
        panel = self.make_panel(1)
        font = fn_hex_font()
        self.assertEqual((font.family(), font.pointSize(), font.bold()), ('Segoe UI', 10, False))
        cell = panel.table.cellWidget(0, panel.COL_RECEIVE)
        self.assertIn('Segoe UI', cell.styleSheet())
        self.assertNotIn('bold', cell.styleSheet())
        editor = self.editor_for(panel, panel.COL_REQUEST)
        self.assertNotIn('bold', editor.styleSheet())
        self.assertEqual(panel.table.item(0, panel.COL_REQUEST).font().family(), 'Segoe UI')
        self.assertFalse(panel.table.item(0, panel.COL_REQUEST).font().bold())


class CanDiagnosticTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_panel(self):
        from gui.widgets.can_interface.diagnostic_table_panel import CanDiagnosticTablePanel
        service = SimpleNamespace(list_vehicles=lambda: ['BENCH'], load_vehicle=lambda _: Vehicle('BENCH', ecus=[ECU('TEST')]))
        panel = CanDiagnosticTablePanel(vehicle_service=service)
        self.addCleanup(panel.deleteLater)
        panel.fn_load_sequence(DiagnosticTestCase(1, 'TEST', '', True, [DiagnosticStep(1,'TEST','TEST','22 F1 90')]))
        return panel

    def test_exact_columns_stable_actions_and_independent_checks(self):
        panel = self.make_panel()
        panel.vehicle_selector.fn_set_vehicle('BENCH')
        self.assertEqual(panel.HEADERS, ('','Step','Test sequence name','ECU','Payload (HEX)','>','Delay (ms)','Repeat',
                         'Expected Response (HEX)','Receive Message (HEX)','Results','Comment'))
        self.assertFalse(panel.table.isSortingEnabled())
        original = panel.step_ids[0]
        actions = []
        panel.row_send_requested.connect(actions.append)
        panel.table.cellWidget(0, panel.COL_SEND).click()
        self.assertEqual(actions, [original])
        self.assertEqual(panel.checked_step_ids(), (original,))  # Every row is selected by default.
        panel.table.item(0,panel.COL_CHECK).setCheckState(Qt.Checked)
        panel.fn_add_step_after_selected()
        panel.table.selectRow(0)
        panel.fn_remove_selected_step()
        survivor = panel.step_ids[0]
        panel.table.cellWidget(0, panel.COL_SEND).click()
        self.assertEqual(actions[-1], survivor)
        self.assertNotEqual(original, survivor)
        self.assertEqual(panel.table.item(0, panel.COL_RECEIVE).text(), '—')
        self.assertEqual(panel.table.item(0, panel.COL_RESULT).text(), '—')

    def test_validation_comment_and_runtime_separation(self):
        panel = self.make_panel()
        panel.table.item(0,panel.COL_REQUEST).setText('zz')
        self.assertEqual(panel.fn_current_sequence().steps[0].request, '22 F1 90')
        self.assertIn('Invalid', panel.notice.text())
        for column, value in ((panel.COL_DELAY,'-1'), (panel.COL_REPEAT,'0')):
            panel.table.item(0,column).setText(value)
        self.assertEqual(panel.fn_current_sequence().steps[0].delay_ms, 100)
        self.assertEqual(panel.fn_current_sequence().steps[0].repeat, 1)
        panel.table.item(0,panel.COL_COMMENT).setText('Bench only')
        self.assertEqual(panel.fn_current_sequence().steps[0].comment, 'Bench only')
        panel.set_step_result(panel.step_ids[0], '62 F1 90', 'Not Evaluated')
        self.assertEqual(panel.table.item(0,panel.COL_RECEIVE).text(), '62 F1 90')
        self.assertFalse(hasattr(panel.fn_current_sequence().steps[0], 'received_payload'))
        panel.reset_runtime_results()
        self.assertEqual(panel.table.item(0,panel.COL_RESULT).text(),'—')

    def test_vehicle_is_explicit_and_missing_ecu_is_preserved(self):
        panel = self.make_panel()
        self.assertEqual(panel.fn_current_vehicle(), '')
        self.assertIn('Select Vehicle', panel.table.cellWidget(0,panel.COL_ECU).toolTip())
        panel.vehicle_selector.fn_set_vehicle('BENCH')
        self.assertEqual(panel.table.cellWidget(0,panel.COL_ECU).currentData().name,'TEST')
        panel.fn_set_vehicle(Vehicle('OTHER', ecus=[ECU('OTHER')]))
        self.assertEqual(panel.fn_current_sequence().steps[0].ecu,'TEST')
        self.assertIn('missing',panel.table.cellWidget(0,panel.COL_ECU).toolTip())

    def test_theme_refresh_keeps_runtime_and_definition_edit_invalidates_it(self):
        from gui.themes.theme_manager import ThemeManager
        from gui.themes.theme import ThemeType
        panel=self.make_panel()
        key=panel.step_ids[0]
        panel.set_step_result(key,'62 F1 90','Passed','Injected QA result, not transport execution')
        self.addCleanup(ThemeManager.fn_set_theme,ThemeManager.fn_theme())
        for theme in (ThemeType.DARK,ThemeType.LIGHT):
            ThemeManager.fn_set_theme(theme)
            panel.fn_refresh_theme()
            self.assertEqual(panel.table.item(0,panel.COL_RESULT).text(),'Passed')
            self.assertFalse(panel.fn_is_dirty())
        panel.table.item(0,panel.COL_COMMENT).setText('changed')
        self.assertEqual(panel.table.item(0,panel.COL_RESULT).text(),'Passed')
        panel.table.item(0,panel.COL_REQUEST).setText('22 F1 91')
        self.assertEqual(panel.table.item(0,panel.COL_RESULT).text(),'—')

    def test_added_row_hidden_sequence_name_remains_native_saveable(self):
        import tempfile
        from pathlib import Path
        from repositories.diagnostic_sequence_repository import DiagnosticSequenceRepository
        panel=self.make_panel()
        panel.vehicle_selector.fn_set_vehicle('BENCH')
        panel.fn_add_step_after_selected()
        panel.table.item(1,panel.COL_REQUEST).setText('10 03')
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            path=Path(directory)/'sequence.json'
            DiagnosticSequenceRepository(directory).fn_save_sequence(panel.fn_current_sequence(),path)
            self.assertEqual(DiagnosticSequenceRepository(directory).fn_load_sequence(path).steps[1].sequence_name,'TEST')
