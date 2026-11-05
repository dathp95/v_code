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

    def make_panel(self, count=3):
        from gui.widgets.can_interface.diagnostic_table_panel import CanDiagnosticTablePanel
        service = SimpleNamespace(list_vehicles=lambda: ['BENCH'], load_vehicle=lambda _: Vehicle('BENCH', ecus=[ECU('TEST')]))
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
            self.assertEqual(panel.table.item(0,panel.COL_RESULT).foreground().color().name(),ThemeManager.fn_colors().SUCCESS.lower())
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
