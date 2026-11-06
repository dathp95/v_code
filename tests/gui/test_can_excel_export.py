import os
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from openpyxl import load_workbook
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid

from core.diagnostic_sequence import DiagnosticStep, DiagnosticTestCase
from core.services.diagnostic_sequence_report_service import DiagnosticSequenceReportService
from gui.controllers.can_workspace_controller import CanWorkspaceController
from gui.widgets.can_interface.diagnostic_table_panel import NO_RESULT, CanDiagnosticTablePanel
from gui.widgets.can_interface.sequence_sidebar import CanSequenceSidebar
from gui.widgets.controls import export_toast
from gui.widgets.controls.export_toast import ExportToast, show_export_toast
from repositories.can_interface_ui_store import CanInterfaceUiStore
from repositories.can_sequence_repository import CanSequenceRepository

DIALOG = 'gui.widgets.can_interface.excel_export.ask_save_path'
TOAST = 'gui.widgets.can_interface.excel_export.show_export_toast'


def case(name, rows=2):
    return DiagnosticTestCase(1, name, '', True, [
        DiagnosticStep(i + 1, f'step {i + 1}', 'BCM', f'22 F1 {i:02X}', 100, 1, f'62 F1 {i:02X}') for i in range(rows)])


class ExcelExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make(self, names):
        directory = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(directory.cleanup)
        repo = CanSequenceRepository(Path(directory.name) / 'sequences')
        for name in names:
            repo.fn_save_sequence(case(name), repo.root / f'{name}.json')
        store = CanInterfaceUiStore(Path(directory.name) / 'prefs')
        sidebar = CanSequenceSidebar(repo, store)
        panel = CanDiagnosticTablePanel(vehicle_service=SimpleNamespace(list_vehicles=lambda: []))
        controller = CanWorkspaceController(sidebar, panel, repo, store)
        for obj in (controller, panel, sidebar):
            self.addCleanup(obj.deleteLater)
        return SimpleNamespace(root=Path(directory.name), repo=repo, sidebar=sidebar, panel=panel,
                               controller=controller, resolve=lambda n: str((repo.root / f'{n}.json').resolve()))

    def tick(self, env, *names):
        wanted = {env.resolve(n) for n in names}
        for i in range(env.sidebar.list_sequences.count()):
            item = env.sidebar.list_sequences.item(i)
            item.setCheckState(Qt.Checked if item.data(env.sidebar.ITEM_PATH_ROLE) in wanted else Qt.Unchecked)

    def export(self, env, report_dir):
        """Run EXPORT accepting the suggested path; returns (suggested path, toast mock)."""
        suggested = []

        def accept(parent, caption, path, filters):
            suggested.append(Path(path))
            return str(path)

        with patch(DIALOG, side_effect=accept), patch(TOAST) as toast, \
                patch('gui.widgets.can_interface.excel_export.CAN_INTERFACE_LOG_DIR', report_dir):
            env.panel.export_excel()
        return (suggested[0] if suggested else None), toast

    # --- folder and file name ------------------------------------------------------
    def test_single_sequence_goes_to_a_day_folder_and_keeps_name_and_vehicle_in_the_file_name(self):
        env = self.make(['0001.READ&CDS'])
        env.controller.restore()
        logs = env.root / 'CAN_Interface_Logs'
        suggested, toast = self.export(env, logs)
        self.assertEqual(suggested.parent.parent, logs)
        self.assertRegex(suggested.parent.name, r'^\d{2}-\d{2}-\d{4}$')
        self.assertTrue(suggested.parent.is_dir())
        self.assertRegex(suggested.name, r'^EEIV_Sequence_Report_0001\.READ&CDS_\d{8}_\d{6}\.xlsx$')
        self.assertTrue(suggested.exists())
        toast.assert_called_once()
        self.assertEqual(toast.call_args.args[1], suggested)

    def test_two_or_more_sequences_use_only_the_timestamp_in_the_file_name(self):
        env = self.make(['9601.a', '9602.b', '9603.c'])
        env.controller.restore()
        self.tick(env, '9601.a', '9603.c')
        suggested, _ = self.export(env, env.root / 'logs')
        self.assertRegex(suggested.name, r'^EEIV_Sequence_Report_\d{8}_\d{6}\.xlsx$')

    # --- sheets --------------------------------------------------------------------
    def test_each_ticked_sequence_becomes_one_sheet_with_its_remembered_results(self):
        env = self.make(['9601.a', '9602.b', '9603.c'])
        env.controller.restore()  # 9601.a is open.
        env.panel.set_step_result(env.panel.step_ids[0], '62 F1 00 11', 'Passed')
        env.controller.open_source(env.resolve('9602.b'))
        env.panel.set_step_result(env.panel.step_ids[1], '7F 22 31', 'Failed')
        env.controller.open_source(env.resolve('9603.c'))  # 9601.a and 9602.b are now in the background.
        self.tick(env, '9601.a', '9602.b')
        suggested, _ = self.export(env, env.root / 'logs')
        book = load_workbook(suggested)
        self.assertEqual(book.sheetnames, ['9601.a', '9602.b'])
        first, second = book['9601.a'], book['9602.b']
        self.assertEqual((first['D3'].value, first['H3'].value, first['I3'].value), ('22 F1 00', '62 F1 00 11', 'Passed'))
        self.assertEqual(first['I4'].value, NO_RESULT)  # Not run: same marker as the table.
        self.assertEqual((second['H4'].value, second['I4'].value), ('7F 22 31', 'Failed'))

    def test_open_sequence_is_exported_live_with_unsaved_edits_when_ticked(self):
        env = self.make(['9601.a', '9602.b'])
        env.controller.restore()
        env.panel.table.item(0, env.panel.COL_COMMENT).setText('edited, not saved')
        self.tick(env, '9601.a')
        suggested, _ = self.export(env, env.root / 'logs')
        self.assertEqual(load_workbook(suggested)['9601.a']['J3'].value, 'edited, not saved')

    def test_blank_test_sequence_names_stay_blank_and_never_borrow_the_sequence_name(self):
        env = self.make(['9601.a', '9602.b'])
        env.controller.restore()  # 9601.a open (live path); 9602.b in the background (stored path).
        for row in range(env.panel.table.rowCount()):
            self.assertEqual(env.panel.table.item(row, env.panel.COL_SEQUENCE_NAME).text(), 'step %d' % (row + 1))
            env.panel.table.item(row, env.panel.COL_SEQUENCE_NAME).setText('')
        self.tick(env, '9601.a', '9602.b')
        suggested, _ = self.export(env, env.root / 'logs')
        book = load_workbook(suggested)
        live, background = book['9601.a'], book['9602.b']
        self.assertEqual([live['B3'].value, live['B4'].value], [None, None])
        self.assertEqual([background['B3'].value, background['B4'].value], ['step 1', 'step 2'])

    def test_background_sequence_without_step_names_leaves_the_column_empty(self):
        from gui.widgets.can_interface.excel_export import sheet_for_case
        blank = DiagnosticTestCase(1, 'My Sequence', '', True, [DiagnosticStep(1, '', 'BCM', '10 03')])
        name, rows = sheet_for_case(blank)
        self.assertEqual((name, rows[0]['sequence_name']), ('My Sequence', ''))

    def test_nothing_ticked_exports_the_open_sequence_only(self):
        env = self.make(['9601.a', '9602.b'])
        env.controller.restore()
        self.tick(env)
        suggested, _ = self.export(env, env.root / 'logs')
        self.assertEqual(load_workbook(suggested).sheetnames, ['9601.a'])

    def test_cancelled_dialog_writes_nothing_and_shows_no_popup(self):
        env = self.make(['9601.a'])
        env.controller.restore()
        with patch(DIALOG, return_value=''), patch(TOAST) as toast, \
                patch('gui.widgets.can_interface.excel_export.CAN_INTERFACE_LOG_DIR', env.root / 'logs'):
            env.panel.export_excel()
        toast.assert_not_called()
        self.assertEqual(list((env.root / 'logs').rglob('*.xlsx')), [])

    def test_service_gives_every_sheet_a_unique_valid_title(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            rows = [{'step': 1}]
            path = DiagnosticSequenceReportService(directory).export_sequences(
                [('Same', rows), ('same', rows), ('a/b:c*' + 'x' * 40, rows)], Path(directory) / 'x.xlsx')
            names = load_workbook(path).sheetnames
        self.assertEqual(names[:2], ['Same', 'same (2)'])
        self.assertTrue(all(len(n) <= 31 and not re.search(r'[\\/*?:\[\]]', n) for n in names))
        self.assertEqual(len(set(n.casefold() for n in names)), 3)

    # --- Save dialog -----------------------------------------------------------------
    def test_save_dialog_is_small_and_centered_on_the_screen(self):
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QFileDialog
        from gui.widgets.can_interface.excel_export import SAVE_DIALOG_SIZE, configure_save_dialog
        dialog = QFileDialog()
        self.addCleanup(dialog.deleteLater)
        dialog.resize(5000, 4000)  # What a remembered full-screen size would be.
        configure_save_dialog(dialog)
        area = QGuiApplication.primaryScreen().availableGeometry()
        self.assertLessEqual(dialog.width(), min(SAVE_DIALOG_SIZE[0], area.width()))
        self.assertLessEqual(dialog.height(), min(SAVE_DIALOG_SIZE[1], area.height()))
        center = dialog.frameGeometry().center()
        self.assertLessEqual(abs(center.x() - area.center().x()), 2)
        self.assertLessEqual(abs(center.y() - area.center().y()), 2)

    # --- Excel layout ----------------------------------------------------------------
    def test_sheet_has_fixed_widths_wrapped_long_columns_and_app_result_colors(self):
        from core.services.diagnostic_sequence_report_service import COLUMN_WIDTHS, SEQUENCE_REPORT_HEADERS
        long_hex = ' '.join(['00'] * 400)
        rows = [{'step': i + 1, 'sequence_name': 'name', 'ecu': 'BCM', 'request': long_hex, 'delay_ms': 100,
                 'repeat': 1, 'expected': long_hex, 'receive': long_hex, 'result': result, 'comment': long_hex}
                for i, result in enumerate(('Passed', 'Failed', 'Timeout', '\u2014'))]
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            path = DiagnosticSequenceReportService(directory).export_sequences([('S', rows)], Path(directory) / 'x.xlsx')
            sheet = load_workbook(path)['S']
        for index, header in enumerate(SEQUENCE_REPORT_HEADERS, 1):
            self.assertEqual(sheet.column_dimensions[chr(64 + index)].width, COLUMN_WIDTHS[header])
        self.assertLessEqual(sum(COLUMN_WIDTHS.values()), 260)
        for column in 'DGHJ':  # Payload, Expected, Receive, Comment.
            self.assertTrue(sheet[f'{column}3'].alignment.wrap_text)
        self.assertGreater(sheet.row_dimensions[3].height, 100)
        self.assertLessEqual(sheet.row_dimensions[3].height, 409)
        colors = {sheet[f'I{r}'].value: sheet[f'I{r}'].fill.fgColor.rgb[-6:] for r in (3, 4, 5)}
        self.assertEqual(colors, {'Passed': '2E8B57', 'Failed': 'C0392B', 'Timeout': 'E67E22'})
        self.assertEqual(sheet['I3'].font.color.rgb[-6:], 'FFFFFF')
        self.assertTrue(sheet['I3'].font.bold)
        self.assertNotEqual(sheet['I6'].fill.fill_type, 'solid')  # No result: no color.

    # --- popup ---------------------------------------------------------------------
    def window(self):
        window = QWidget()
        window.resize(800, 600)
        window.show()
        self.addCleanup(window.deleteLater)
        self.app.processEvents()
        return window

    def test_popup_has_three_buttons_in_the_bottom_right_corner(self):
        window = self.window()
        toast = show_export_toast(window, Path('C:/x/report.xlsx'))
        self.app.processEvents()
        self.assertEqual([toast.btn_open_folder.text(), toast.btn_open_file.text(), toast.btn_cancel.text()],
                         ['OPEN FOLDER', 'OPEN FILE', 'CANCEL'])
        self.assertIn('report.xlsx', toast.lbl_file.text())
        self.assertLessEqual(toast.geometry().right(), window.width())
        self.assertGreater(toast.geometry().left(), window.width() // 2)
        self.assertGreater(toast.geometry().top(), window.height() // 2)
        window.resize(1000, 700)
        self.app.processEvents()
        self.assertGreater(toast.geometry().left(), 500)  # Follows the window corner.
        toast.dismiss()

    def test_popup_closes_itself_after_the_timeout_and_the_default_is_five_seconds(self):
        self.assertEqual(export_toast.EXPORT_TOAST_TIMEOUT_MS, 5000)
        window = self.window()
        toast = show_export_toast(window, Path('C:/x/report.xlsx'), timeout_ms=30)
        self.assertTrue(toast.isVisible())
        QTest.qWait(150)
        self.assertFalse(isValid(toast) and toast.isVisible())

    def test_popup_buttons_open_the_folder_or_the_file_and_cancel_just_closes(self):
        window = self.window()
        path = Path('C:/x/day/report.xlsx')
        with patch.object(export_toast, 'open_location') as opener:
            toast = show_export_toast(window, path)
            toast.btn_open_folder.click()
            opener.assert_called_once_with(path.parent)
            self.assertFalse(toast.isVisible())
            opener.reset_mock()
            toast = show_export_toast(window, path)
            toast.btn_open_file.click()
            opener.assert_called_once_with(path)
            opener.reset_mock()
            toast = show_export_toast(window, path)
            toast.btn_cancel.click()
            opener.assert_not_called()
            self.assertFalse(toast.isVisible())

    def test_a_new_popup_replaces_the_previous_one(self):
        window = self.window()
        first = show_export_toast(window, Path('C:/x/a.xlsx'))
        second = show_export_toast(window, Path('C:/x/b.xlsx'))
        self.app.processEvents()
        self.assertFalse(first.isVisible())
        self.assertTrue(second.isVisible())
        second.dismiss()


if __name__ == '__main__':
    unittest.main()
