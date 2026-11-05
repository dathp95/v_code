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
        self.assertEqual(self.combo_items(panel), ['BCM', 'BMS', 'SS'])  # No "keep" entry.
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
        panel.table.selectRow(3)  # The row's ECU is not an ECU of the Vehicle: nothing is selected.
        self.assertEqual(combo.currentIndex(), -1)
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
        self.assertEqual(panel.cmb_import_ecu.currentIndex(), -1)
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
