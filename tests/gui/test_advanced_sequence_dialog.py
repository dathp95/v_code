import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from core.advanced_sequence import AdvancedRow, render_advanced_steps
from gui.controllers.can_workspace_controller import CanWorkspaceController
from gui.dialogs.advanced_sequence_dialog import AdvancedSequenceDialog
from gui.widgets.can_interface.diagnostic_table_panel import CanDiagnosticTablePanel
from gui.widgets.can_interface.sequence_sidebar import CanSequenceSidebar
from models.ecu import ECU
from models.vehicle import Vehicle
from repositories.can_interface_ui_store import CanInterfaceUiStore
from repositories.can_sequence_repository import CanSequenceRepository

SIX = ['BCM', 'BMS', '3N1', 'ACU', 'BPM', 'EPS']


def vehicle_service():
    vehicles = {'VF5NP': Vehicle('VF5NP', ecus=[ECU(name, str(0x681 + i), str(0x601 + i)) for i, name in enumerate(SIX)]),
                'VF3': Vehicle('VF3', ecus=[ECU('MHU', '6A0', '620'), ECU('MHU', '6A1', '621'), ECU('BCM', '681', '601')])}
    return SimpleNamespace(list_vehicles=lambda: list(vehicles), load_vehicle=lambda name: vehicles[name])


class AdvancedSequenceDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make(self, vehicle='VF5NP'):
        dialog = AdvancedSequenceDialog(vehicle_service=vehicle_service(), vehicle=vehicle)
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        return dialog

    def type_row(self, dialog, row, name, payload, delay='100', repeat='1', expected='', comment=''):
        for column, text in ((dialog.COL_NAME, name), (dialog.COL_REQUEST, payload), (dialog.COL_DELAY, delay),
                             (dialog.COL_REPEAT, repeat), (dialog.COL_EXPECTED, expected), (dialog.COL_COMMENT, comment)):
            dialog.table.item(row, column).setText(text)

    def ticked(self, dialog):
        return [dialog.ecu_list.item(i).text() for i in range(dialog.ecu_list.count())
                if dialog.ecu_list.item(i).checkState() == Qt.Checked]

    def test_vehicle_combo_lists_vehicles_and_the_ecu_list_follows_it_all_ticked(self):
        dialog = self.make('VF5NP')
        self.assertEqual([dialog.vehicle_combo.itemText(i) for i in range(dialog.vehicle_combo.count())], ['VF5NP', 'VF3'])
        self.assertEqual(dialog.vehicle_combo.currentText(), 'VF5NP')
        self.assertEqual(self.ticked(dialog), SIX)  # Every ECU of the Vehicle is ticked by default.
        self.assertEqual(dialog.chk_all.checkState(), Qt.Checked)
        dialog.vehicle_combo.setCurrentIndex(dialog.vehicle_combo.findText('VF3'))
        self.assertEqual(self.ticked(dialog), ['BCM'])  # Repeated ECU names are ambiguous and left out.
        self.assertEqual(dialog.chk_all.checkState(), Qt.Checked)

    def test_select_all_follows_and_drives_the_ecu_ticks(self):
        dialog = self.make()
        dialog.ecu_list.item(1).setCheckState(Qt.Unchecked)
        self.assertEqual(self.ticked(dialog), [n for n in SIX if n != 'BMS'])
        self.assertNotEqual(dialog.chk_all.checkState(), Qt.Checked)
        dialog.chk_all.click()  # Not all ticked: tick everything.
        self.assertEqual(self.ticked(dialog), SIX)
        dialog.chk_all.click()  # All ticked: clear everything.
        self.assertEqual(self.ticked(dialog), [])
        self.assertFalse(dialog.btn_apply.isEnabled())

    def test_table_has_the_sequence_columns_with_ecu_receive_results_and_step_read_only(self):
        dialog = self.make()
        headers = [dialog.table.horizontalHeaderItem(i).text() for i in range(dialog.table.columnCount())]
        self.assertEqual(headers, ['Step', 'Test sequence name', 'ECU', 'Payload (HEX)', 'Delay (ms)', 'Repeat',
                                   'Expected Response (HEX)', 'Receive Message (HEX)', 'Results', 'Comment'])
        dialog.btn_add_row.click()
        for row in range(2):
            self.assertEqual(dialog.table.item(row, dialog.COL_STEP).text(), str(row + 1))
            for column in (dialog.COL_STEP, dialog.COL_ECU, dialog.COL_RECEIVE, dialog.COL_RESULT):
                self.assertFalse(dialog.table.item(row, column).flags() & Qt.ItemIsEditable, (row, column))
            for column in (dialog.COL_NAME, dialog.COL_REQUEST, dialog.COL_DELAY, dialog.COL_REPEAT,
                           dialog.COL_EXPECTED, dialog.COL_COMMENT):
                self.assertTrue(dialog.table.item(row, column).flags() & Qt.ItemIsEditable, (row, column))
            self.assertEqual(dialog.table.item(row, dialog.COL_DELAY).text(), '100')
            self.assertEqual(dialog.table.item(row, dialog.COL_REPEAT).text(), '1')

    def test_rows_can_be_added_and_deleted_and_steps_stay_numbered(self):
        dialog = self.make()
        for _ in range(3):
            dialog.btn_add_row.click()
        self.assertEqual(dialog.table.rowCount(), 4)
        dialog.table.selectRow(1)
        dialog.btn_delete_row.click()
        self.assertEqual([dialog.table.item(r, dialog.COL_STEP).text() for r in range(3)], ['1', '2', '3'])

    def test_apply_needs_a_name_a_typed_row_and_an_ecu_and_renders_every_ecu_in_turn(self):
        dialog = self.make()
        self.assertFalse(dialog.btn_apply.isEnabled())
        dialog.name_edit.setText('Both rows')
        self.assertFalse(dialog.btn_apply.isEnabled())  # Nothing typed in the table yet.
        dialog.btn_add_row.click()
        self.type_row(dialog, 0, 'Check Ignition ON', '22 F1 23', expected='62 F1 23', comment='0x00=OFF')
        self.type_row(dialog, 1, 'Status of Actual Gear', '22 01 44', expected='62 01 44')
        self.assertTrue(dialog.btn_apply.isEnabled())
        self.assertIn('12', dialog.lbl_summary.text())  # 2 rows x 6 ECUs
        dialog.ecu_list.item(5).setCheckState(Qt.Unchecked)
        self.assertIn('10', dialog.lbl_summary.text())
        dialog.btn_apply.click()
        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual((dialog.name, dialog.vehicle), ('Both rows', 'VF5NP'))
        self.assertEqual([(s.step, s.ecu, s.sequence_name) for s in dialog.steps][:4],
                         [(1, 'BCM', 'Check Ignition ON'), (2, 'BCM', 'Status of Actual Gear'),
                          (3, 'BMS', 'Check Ignition ON'), (4, 'BMS', 'Status of Actual Gear')])
        self.assertEqual(len(dialog.steps), 10)
        self.assertEqual({s.ecu for s in dialog.steps}, set(SIX[:5]))
        self.assertEqual(dialog.steps[0].comment, '0x00=OFF')

    # --- HEX cells are formatted and checked like the main table ---------------------
    def editor_for(self, dialog, row, column):
        from PySide6.QtWidgets import QStyleOptionViewItem
        delegate = dialog.table.itemDelegateForColumn(column)
        editor = delegate.createEditor(dialog.table.viewport(), QStyleOptionViewItem(), dialog.table.model().index(row, column))
        self.addCleanup(editor.deleteLater)
        editor.show()
        return delegate, editor

    def test_payload_and_expected_editors_group_hex_while_typing_and_warn_on_half_bytes(self):
        from PySide6.QtTest import QTest
        from gui.widgets.can_interface.diagnostic_table_panel import HexItemDelegate
        dialog = self.make()
        for column in (dialog.COL_REQUEST, dialog.COL_EXPECTED):
            self.assertIsInstance(dialog.table.itemDelegateForColumn(column), HexItemDelegate)
            delegate, editor = self.editor_for(dialog, 0, column)
            QTest.keyClicks(editor, '1003')
            self.assertEqual(editor.text(), '10 03')  # 1003 -> 10 03 as you type.
            self.assertNotIn('Warning', editor.toolTip())
            editor.clear()
            QTest.keyClicks(editor, '100')
            self.assertEqual(editor.text(), '10 0')
            self.assertIn('Warning', editor.toolTip())  # A half byte is flagged.
            delegate.setModelData(editor, dialog.table.model(), dialog.table.model().index(0, column))

    def test_cells_are_normalised_and_flagged_after_the_edit(self):
        from PySide6.QtGui import QColor
        from gui.themes.theme_manager import ThemeManager
        dialog = self.make()
        warning = QColor(ThemeManager.fn_colors().WARNING)
        for column in (dialog.COL_REQUEST, dialog.COL_EXPECTED):
            item = dialog.table.item(0, column)
            item.setText('1003')
            self.assertEqual(item.text(), '10 03')
            self.assertEqual(item.toolTip(), '')
            self.assertNotEqual(item.foreground().color(), warning)
            item.setText('10 0')
            self.assertEqual(item.text(), '10 0')  # Kept as typed, but flagged.
            self.assertTrue(item.toolTip().startswith('Warning'))
            self.assertEqual(item.foreground().color(), warning)
            item.setText('zz')
            self.assertTrue(item.toolTip().startswith('Warning'))
            item.setText('')
            self.assertEqual(item.toolTip(), '')
        dialog.name_edit.setText('x')
        dialog.table.item(0, dialog.COL_REQUEST).setText('1003')
        dialog.table.item(0, dialog.COL_EXPECTED).setText('5003')
        dialog.btn_apply.click()
        self.assertEqual((dialog.steps[0].request, dialog.steps[0].expected_response), ('10 03', '50 03'))

    # --- size ------------------------------------------------------------------------
    def test_dialog_is_wide_enough_to_show_every_column_through_comment(self):
        from PySide6.QtGui import QGuiApplication
        dialog = self.make()
        columns = sum(dialog.table.columnWidth(c) for c in range(dialog.table.columnCount()))
        self.assertGreaterEqual(dialog.preferred_width(), columns + dialog.ecu_list.width())
        available = QGuiApplication.primaryScreen().availableGeometry().width()
        self.assertEqual(dialog.width(), min(dialog.preferred_width(), int(available * 0.95)))
        self.assertGreaterEqual(dialog.table.columnWidth(dialog.COL_COMMENT), 200)

    # --- Apply explains itself ---------------------------------------------------------
    def test_apply_tooltip_says_what_is_missing(self):
        dialog = self.make()
        self.assertFalse(dialog.btn_apply.isEnabled())
        self.assertEqual(dialog.btn_apply.toolTip(), 'Require sequence name')
        dialog.name_edit.setText('   ')
        self.assertEqual(dialog.btn_apply.toolTip(), 'Require sequence name')  # Blanks are not a name.
        dialog.name_edit.setText('VIP 2')
        self.assertEqual(dialog.btn_apply.toolTip(), 'Require at least one row with content')
        self.type_row(dialog, 0, 'a', '10 03')
        self.assertTrue(dialog.btn_apply.isEnabled())
        self.assertEqual(dialog.btn_apply.toolTip(), '')
        dialog.chk_all.click()
        self.assertEqual(dialog.btn_apply.toolTip(), 'Require at least one ECU')
        dialog.chk_all.click()
        dialog.name_edit.clear()
        self.assertEqual(dialog.btn_apply.toolTip(), 'Require sequence name')

    def test_cancel_leaves_nothing_behind(self):
        dialog = self.make()
        dialog.btn_cancel.click()
        self.assertEqual(dialog.result(), QDialog.Rejected)
        self.assertEqual(tuple(getattr(dialog, 'steps', ())), ())

    def test_sidebar_menu_has_add_sequence_advance_right_after_add_sequence(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            sidebar = CanSequenceSidebar(CanSequenceRepository(root), CanInterfaceUiStore(root / 'ui'))
            self.addCleanup(sidebar.deleteLater)
            menu = sidebar.build_sequence_context_menu('')
            self.addCleanup(menu.deleteLater)
            texts = [a.text() for a in menu.actions() if not a.isSeparator()]
            self.assertEqual(texts[:3], ['+ Add sequence', '+ Add sequence advance', 'Rename'])
            requested = []
            sidebar.add_advanced_requested.connect(lambda: requested.append(True))
            next(a for a in menu.actions() if a.text() == '+ Add sequence advance').trigger()
            self.assertEqual(requested, [True])

    def session(self, root):
        repo = CanSequenceRepository(root)
        store = CanInterfaceUiStore(root / 'prefs')
        sidebar = CanSequenceSidebar(repo, store)
        vehicle = Vehicle('BENCH', ecus=[ECU('BCM', '681', '601'), ECU('EPS', '682', '602')])
        panel = CanDiagnosticTablePanel(vehicle_service=SimpleNamespace(list_vehicles=lambda: ['BENCH'], load_vehicle=lambda _: vehicle))
        controller = CanWorkspaceController(sidebar, panel, repo, store)
        for obj in (controller, panel, sidebar):
            self.addCleanup(obj.deleteLater)
        return controller, panel, sidebar

    def fake_dialog(self, name, steps, vehicle='BENCH', accepted=True):
        class Fake:
            def __init__(self, *args, **kwargs):
                self.name, self.vehicle, self.steps = name, vehicle, steps

            def exec(self):
                return QDialog.Accepted if accepted else QDialog.Rejected
        return Fake

    def test_controller_creates_the_sequence_selects_the_vehicle_and_fills_the_rendered_steps(self):
        rows = [AdvancedRow('Read VIN', '22 F1 90', '100', '1', '62 F1 90', ''), AdvancedRow('Gear', '22 01 44', '100', '1', '', '')]
        steps = render_advanced_steps(rows, ['BCM', 'EPS'])
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            controller, panel, sidebar = self.session(root)
            with patch('gui.controllers.can_workspace_controller.AdvancedSequenceDialog', self.fake_dialog('Advanced one', steps)):
                self.assertTrue(controller.add_sequence_advanced())
            case = panel.fn_current_sequence()
            self.assertEqual(case.name, 'Advanced one')
            self.assertEqual([(s.ecu, s.sequence_name) for s in case.steps],
                             [('BCM', 'Read VIN'), ('BCM', 'Gear'), ('EPS', 'Read VIN'), ('EPS', 'Gear')])
            self.assertEqual(panel.fn_current_vehicle(), 'BENCH')
            self.assertTrue((root / 'Advanced one.json').is_file())  # Created like "Add sequence" does.
            self.assertTrue(panel.fn_is_dirty())  # The rendered steps are saved with Save, as for an import.
            self.assertEqual(panel.table.cellWidget(2, panel.COL_ECU).currentText(), 'EPS')

    def test_controller_does_nothing_when_the_dialog_is_cancelled_or_the_name_is_taken(self):
        steps = render_advanced_steps([AdvancedRow('x', '10 03', '100', '1', '', '')], ['BCM'])
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            controller, panel, sidebar = self.session(root)
            with patch('gui.controllers.can_workspace_controller.AdvancedSequenceDialog',
                       self.fake_dialog('Nope', steps, accepted=False)):
                self.assertFalse(controller.add_sequence_advanced())
            self.assertIsNone(panel.fn_current_sequence())
            self.assertFalse((root / 'Nope.json').exists())
            controller.add_sequence('Taken')
            with patch('gui.controllers.can_workspace_controller.AdvancedSequenceDialog', self.fake_dialog('Taken', steps)):
                self.assertFalse(controller.add_sequence_advanced())
            self.assertEqual(panel.fn_current_sequence().steps, [])  # The existing sequence is untouched.


if __name__ == '__main__':
    unittest.main()
