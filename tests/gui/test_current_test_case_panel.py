import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QScrollArea

from core.diagnostic_sequence import DiagnosticStep, DiagnosticTestCase
from gui.tabs.can_interface_tab import CANInterfaceTab
from gui.themes.theme import ThemeType
from gui.themes.theme_manager import ThemeManager
from gui.widgets.can_interface.current_test_case_panel import CurrentTestCasePanel
from models.ecu import ECU
from models.vehicle import Vehicle
from repositories.can_interface_ui_store import CanInterfaceUiStore
from tests.gui.test_can_interface_tab import FakeCANService

ORDER = ['Step', 'Result', 'Name', 'ECU', 'Payload', 'Delay', 'Repeat', 'Expected', 'Receive', 'Bytes', 'Comment']
LABELS = ['Step', 'Result', 'Name', 'ECU', 'Payload (HEX)', 'Delay (ms)', 'Repeat (times)',
          'Expected Response (HEX)', 'Receive Message (HEX)', 'Number Byte', 'Comment']


class CurrentTestCasePanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make(self, height=420):
        panel = CurrentTestCasePanel()
        self.addCleanup(panel.deleteLater)
        panel.resize(420, height)
        panel.show()
        return panel

    def step(self, **overrides):
        values = dict(step=15, sequence_name='ODO', ecu='AVAS', request='22 F1 08', delay_ms=100, repeat=1,
                      expected_response='', comment='check mileage')
        values.update(overrides)
        return DiagnosticStep(**values)

    def test_theme_has_result_text_colors(self):
        from dataclasses import fields
        from gui.themes.colors import DARK_COLORS, LIGHT_COLORS, ThemeColors
        names = {field.name for field in fields(ThemeColors)}
        tokens = ('RESULT_PASSED_TEXT', 'RESULT_FAILED_TEXT', 'RESULT_TIMEOUT_TEXT')
        self.assertTrue(set(tokens) <= names)
        for colors in (LIGHT_COLORS, DARK_COLORS):
            self.assertEqual(len({getattr(colors, token) for token in tokens}), 3)

    def test_fields_are_listed_top_to_bottom_in_the_requested_order(self):
        panel = self.make()
        panel.display_step(self.step(), 15)
        self.app.processEvents()
        self.assertEqual(list(panel.values), ORDER)
        self.assertEqual([panel.labels[key].text() for key in ORDER], LABELS)
        tops = [panel.labels[key].mapTo(panel, panel.labels[key].rect().topLeft()).y() for key in ORDER]
        self.assertEqual(tops, sorted(set(tops)))  # One field per line, strictly top to bottom.

    def test_values_come_from_the_selected_row(self):
        panel = self.make()
        panel.display_step(self.step(), 15, result='Passed', receive='62 F1 08 41 42',
                           ecu_address=('0x6CC', '0x64C'))
        text = {key: panel.values[key].text() for key in ORDER}
        self.assertEqual(text, dict(Step='15 / 15', Result='PASSED', Name='ODO', ECU='AVAS - Req 0x6CC - Resp 0x64C',
                                    Payload='22 F1 08', Delay='100', Repeat='1', Expected='—',
                                    Receive='62 F1 08 41 42', Bytes='5', Comment='check mileage'))
        panel.display_step(self.step(sequence_name='', comment='', expected_response='62 F1 08'), 3)
        self.assertEqual((panel.values['Name'].text(), panel.values['Comment'].text()), ('—', '—'))
        self.assertEqual((panel.values['Result'].text(), panel.values['Receive'].text()), ('—', '—'))
        self.assertEqual(panel.values['Bytes'].text(), '—')  # No data, no count.
        self.assertEqual((panel.values['ECU'].text(), panel.values['Expected'].text()), ('AVAS', '62 F1 08'))
        panel.display_step(self.step(), 3, receive='62 F1 08 00 25 4A 39 39 39 37 34 31 06 0D 0D 02 11')
        self.assertEqual(panel.values['Bytes'].text(), '17')

    def test_result_is_bold_and_colored_green_red_or_orange(self):
        panel = self.make()
        for theme in (ThemeType.LIGHT, ThemeType.DARK):
            self.addCleanup(ThemeManager.fn_set_theme, ThemeManager.fn_theme())
            ThemeManager.fn_set_theme(theme)
            panel.fn_refresh_theme()
            colors = ThemeManager.fn_colors()
            for outcome, label, color in (('Passed', 'PASSED', colors.RESULT_PASSED_TEXT),
                                          ('Failed', 'FAILED', colors.RESULT_FAILED_TEXT),
                                          ('Timeout', 'TIMEOUT', colors.RESULT_TIMEOUT_TEXT)):
                panel.display_step(self.step(), 15, result=outcome)
                value = panel.values['Result']
                self.assertEqual(value.text(), label)
                self.assertIn(color, value.styleSheet())
                self.assertIn('font-weight: bold', value.styleSheet())
            panel.display_step(self.step(), 15, result='')
            self.assertNotIn('font-weight: bold', panel.values['Result'].styleSheet())

    def test_long_content_scrolls_vertically_inside_the_panel(self):
        panel = self.make(height=220)
        panel.display_step(self.step(comment='long comment ' * 200), 15, receive=' '.join(['62'] * 400))
        self.app.processEvents()
        self.assertIsInstance(panel.scroll, QScrollArea)
        self.assertTrue(panel.scroll.widgetResizable())
        self.assertEqual(panel.scroll.horizontalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)
        self.assertGreater(panel.scroll.verticalScrollBar().maximum(), 0)
        self.assertEqual(panel.scroll.horizontalScrollBar().maximum(), 0)  # Text wraps, it never runs off the side.
        self.assertTrue(panel.values['Comment'].wordWrap() and panel.values['Receive'].wordWrap())

    def test_dll_line_is_not_shown_and_empty_state_is_explained(self):
        panel = self.make()
        self.assertTrue(panel.dll_status.isHidden())
        panel.dll_status.setText('DLL configured (x86); ready via 32-bit helper.')  # The controller may still set it.
        self.assertTrue(panel.dll_status.isHidden())
        self.assertTrue(panel.security_status.isHidden())  # No "Idle" / "Cancelled" line either...
        panel.security_status.setText('Seed received')  # ...though the session still keeps its text there.
        self.assertTrue(panel.security_status.isHidden())
        panel.display_step(None)
        self.assertTrue(panel.scroll.isHidden())
        self.assertFalse(panel.empty.isHidden())
        self.assertEqual(panel.values['Step'].text(), '—')

    def make_tab(self, directory):
        vehicle = Vehicle('BENCH', ecus=[ECU('BCM', '681', '601')])
        service = SimpleNamespace(list_vehicles=lambda: ['BENCH'], load_vehicle=lambda _: vehicle)
        tab = CANInterfaceTab(FakeCANService(), vehicle_service=service, ui_store=CanInterfaceUiStore(Path(directory) / 'ui'))
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        tab._on_sequence_selected(DiagnosticTestCase(1, 'Bench', '', True, [
            DiagnosticStep(1, 'Start session', 'BCM', '10 03', 100, 1, '50 03', comment='first'),
            DiagnosticStep(2, 'Read VIN', 'BCM', '22 F1 90', 100, 2, '62 F1 90')]))
        tab.sequence_table.vehicle_selector.fn_set_vehicle('BENCH')
        return tab

    def test_panel_shows_the_same_result_as_the_table_for_every_raw_outcome(self):
        # The table folds raw outcomes into Passed / Failed / Timeout; the panel must agree with it.
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            tab = self.make_tab(directory)
            table = tab.sequence_table
            panel = tab.session_panel.current_test_case
            table.table.selectRow(0)
            for outcome, expected in (('Passed', 'PASSED'), ('Not Evaluated', 'PASSED'), ('Failed', 'FAILED'),
                                      ('Error', 'FAILED'), ('Timeout', 'TIMEOUT'), ('Running', '—'), ('Cancelled', '—')):
                table.set_step_result(table.step_ids[0], '62 F1 90 41', outcome)
                self.assertEqual(table.table.item(0, table.COL_RESULT).text().upper().replace('\u2014', '—'),
                                 expected if expected != '—' else '—', outcome)
                self.assertEqual(panel.values['Result'].text(), expected, outcome)
            self.assertEqual(panel.values['Bytes'].text(), '4')

    def test_title_shows_the_name_of_the_selected_sequence(self):
        panel = self.make()
        self.assertEqual(panel.title.text(), 'Select a sequence')
        panel.set_sequence_name('0001.READ&CDS')
        self.assertEqual((panel.title.text(), panel.title.toolTip()), ('0001.READ&CDS', '0001.READ&CDS'))
        panel.set_sequence_name('')
        self.assertEqual(panel.title.text(), 'Select a sequence')

    def test_title_follows_the_open_sequence_and_its_rename(self):
        from dataclasses import replace
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            tab = self.make_tab(directory)
            panel = tab.session_panel.current_test_case
            self.assertEqual(panel.title.text(), 'Bench')  # No row is selected, yet the sequence is known.
            tab._on_sequence_selected(DiagnosticTestCase(1, 'Other sequence', '', True,
                                                         [DiagnosticStep(1, 'x', 'BCM', '10 03')]))
            self.assertEqual(panel.title.text(), 'Other sequence')
            table = tab.sequence_table
            table._test_case = replace(table._test_case, name='Renamed')
            table.mark_saved()
            self.assertEqual(panel.title.text(), 'Renamed')
            tab._on_sequence_selected(None)
            self.assertEqual(panel.title.text(), 'Select a sequence')

    def test_panel_follows_the_selected_row_its_result_and_its_comment_live(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            tab = self.make_tab(directory)
            table = tab.sequence_table
            panel = tab.session_panel.current_test_case
            table.table.selectRow(0)
            self.assertEqual(panel.values['ECU'].text(), 'BCM - Req 0x681 - Resp 0x601')
            self.assertEqual((panel.values['Name'].text(), panel.values['Comment'].text()), ('Start session', 'first'))
            self.assertEqual((panel.values['Result'].text(), panel.values['Receive'].text()), ('—', '—'))
            table.set_step_result(table.step_ids[0], '50 03 00 32', 'Passed')  # A result arrives while selected...
            self.assertEqual((panel.values['Result'].text(), panel.values['Receive'].text()), ('PASSED', '50 03 00 32'))
            table.table.selectRow(1)  # ...another row has none yet...
            self.assertEqual((panel.values['Result'].text(), panel.values['Name'].text()), ('—', 'Read VIN'))
            table.set_step_result(table.step_ids[1], '', 'Timeout')
            self.assertEqual((panel.values['Result'].text(), panel.values['Receive'].text()), ('TIMEOUT', '—'))
            table.table.item(1, table.COL_COMMENT).setText('typed')
            self.assertEqual(panel.values['Comment'].text(), 'typed')
            table.reset_runtime_results()
            self.assertEqual(panel.values['Result'].text(), '—')


if __name__ == '__main__':
    unittest.main()
