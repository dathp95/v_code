import os
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication

from core.diagnostic_sequence import DiagnosticStep, DiagnosticTestCase
from gui.themes.colors import DARK_COLORS, LIGHT_COLORS
from gui.themes.theme import ThemeType
from gui.themes.theme_manager import ThemeManager
from gui.widgets.can_interface.diagnostic_table_panel import CanDiagnosticTablePanel
from gui.widgets.can_interface.sequence_sidebar import CanSequenceSidebar
from models.ecu import ECU
from models.vehicle import Vehicle
from repositories.can_interface_ui_store import CanInterfaceUiStore
from repositories.can_sequence_repository import CanSequenceRepository

TOKENS = ('SEQUENCE_SELECTED_BG', 'SEQUENCE_SELECTED_TEXT', 'TABLE_ROW_SELECTED_BG', 'TABLE_ROW_SELECTED_TEXT')


class SelectionColorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def themes(self):
        self.addCleanup(ThemeManager.fn_set_theme, ThemeManager.fn_theme())
        return (ThemeType.LIGHT, ThemeType.DARK)

    def test_selection_colors_are_named_in_the_theme_and_match_quick_access_pressed(self):
        for colors in (LIGHT_COLORS, DARK_COLORS):
            for token in TOKENS:
                self.assertTrue(hasattr(colors, token), token)
            # Same tint as the pressed Quick Access button, in both lists and in the table.
            self.assertEqual(colors.SEQUENCE_SELECTED_BG, colors.QUICK_ACCESS_PRESSED)
            self.assertEqual(colors.TABLE_ROW_SELECTED_BG, colors.QUICK_ACCESS_PRESSED)
            self.assertNotEqual(colors.TABLE_ROW_SELECTED_BG, colors.PRIMARY)
            self.assertNotEqual(colors.TABLE_ROW_SELECTED_TEXT, colors.TABLE_ROW_SELECTED_BG)

    def make_panel(self):
        vehicle = Vehicle('V', ecus=[ECU('BCM', '681', '601')])
        panel = CanDiagnosticTablePanel(vehicle_service=SimpleNamespace(list_vehicles=lambda: ['V'], load_vehicle=lambda _: vehicle))
        self.addCleanup(panel.deleteLater)
        panel.resize(1300, 400)
        panel.show()
        panel.fn_load_sequence(DiagnosticTestCase(1, 'T', '', True, [DiagnosticStep(i, '', 'BCM', '22 F1 90') for i in (1, 2, 3)]))
        panel.vehicle_selector.fn_set_vehicle('V')
        self.app.processEvents()
        return panel

    def pixel(self, panel, row, column):
        table = panel.table
        image = table.viewport().grab().toImage()
        return image.pixelColor(table.columnViewportPosition(column) + 3, table.rowViewportPosition(row) + 3).name().lower()

    def test_selected_table_row_uses_the_themed_selection_color(self):
        panel = self.make_panel()
        for theme in self.themes():
            ThemeManager.fn_set_theme(theme)
            panel.fn_refresh_theme()
            colors = ThemeManager.fn_colors()
            panel.table.selectRow(1)
            self.app.processEvents()
            self.assertEqual(self.pixel(panel, 1, panel.COL_STEP), colors.TABLE_ROW_SELECTED_BG.lower())
            self.assertNotEqual(self.pixel(panel, 0, panel.COL_STEP), colors.TABLE_ROW_SELECTED_BG.lower())
            cell = panel.table.cellWidget(1, panel.COL_RECEIVE)  # The Receive cell follows the same colors.
            self.assertIn(colors.TABLE_ROW_SELECTED_BG, cell.styleSheet())
            self.assertIn(colors.TABLE_ROW_SELECTED_TEXT, cell.styleSheet())
            self.assertNotIn(colors.PRIMARY, panel.table.styleSheet().split('QTableWidget::item:selected')[-1].split('}')[0])

    def test_negative_response_stays_red_on_a_selected_row(self):
        panel = self.make_panel()
        panel.set_step_result(panel.step_ids[1], '7F 22 31', 'Failed')
        panel.table.selectRow(1)
        sheet = panel.table.cellWidget(1, panel.COL_RECEIVE).styleSheet()
        self.assertIn(ThemeManager.fn_colors().NEGATIVE_RESPONSE_TEXT, sheet)
        self.assertIn('font-weight: bold', sheet)

    def test_selected_sequence_in_the_list_uses_the_themed_selection_color(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            repo = CanSequenceRepository(root)
            sidebar = CanSequenceSidebar(repo, CanInterfaceUiStore(root / 'ui'))
            self.addCleanup(sidebar.deleteLater)
            for theme in self.themes():
                ThemeManager.fn_set_theme(theme)
                sidebar.fn_refresh_theme()
                colors = ThemeManager.fn_colors()
                blocks = re.findall(r'QListWidget::item:selected\s*\{([^}]*)\}', sidebar.list_sequences.styleSheet())
                self.assertTrue(blocks)
                last = blocks[-1]  # The rule that wins.
                self.assertIn(colors.SEQUENCE_SELECTED_BG, last)
                self.assertIn(colors.SEQUENCE_SELECTED_TEXT, last)
                self.assertNotIn(colors.PRIMARY, last)


if __name__ == '__main__':
    unittest.main()
