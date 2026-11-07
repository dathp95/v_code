import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QMenu

from gui.controllers.display_names_import_controller import DisplayNamesImportController
from gui.tabs.log_analyzer_tab import LogAnalyzerTab
from gui.themes.theme import ThemeType
from gui.themes.theme_manager import ThemeManager
from gui.widgets.controls.secondary_button import SecondaryButton

MODULE = 'gui.controllers.display_names_import_controller'


class LogAnalyzerSettingMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tab(self):
        tab = LogAnalyzerTab()
        self.addCleanup(tab.deleteLater)
        return tab

    # --- layout ----------------------------------------------------------------------
    def test_setting_button_sits_right_of_browse_with_the_same_size_and_row(self):
        tab = self.tab()
        tab.resize(1200, 800)
        tab.show()
        self.app.processEvents()
        selector = tab.log_selector
        browse, setting = selector.browse_button, selector.settings_button
        self.assertIsInstance(setting, SecondaryButton)
        self.assertEqual(setting.text(), 'Setting')
        self.assertEqual(setting.size(), browse.size())  # Same width and height as Browse.
        self.assertGreater(setting.mapTo(tab, setting.rect().topLeft()).x(), browse.mapTo(tab, browse.rect().topLeft()).x())
        self.assertEqual(setting.mapTo(tab, setting.rect().center()).y(), browse.mapTo(tab, browse.rect().center()).y())

    def test_menu_has_the_two_display_name_actions_in_order(self):
        selector = self.tab().log_selector
        self.assertEqual([a.text() for a in selector.settings_menu.actions()],
                         ['Import Rules Display Names', 'Import File Display Names'])

    def test_clicking_setting_drops_the_menu_down_from_the_button(self):
        tab = self.tab()
        tab.show()
        self.app.processEvents()
        selector = tab.log_selector
        with patch.object(QMenu, 'popup') as popup:
            selector.settings_button.click()
        popup.assert_called_once()
        position = popup.call_args.args[0]
        corner = selector.settings_button.mapToGlobal(selector.settings_button.rect().bottomLeft())
        self.assertEqual(position.x(), corner.x())
        self.assertLessEqual(abs(position.y() - (corner.y() + 1)), 1)  # Directly under the button.

    def test_menu_is_themed_in_light_and_dark(self):
        tab = self.tab()
        self.addCleanup(ThemeManager.fn_set_theme, ThemeManager.fn_theme())
        for theme in (ThemeType.LIGHT, ThemeType.DARK):
            ThemeManager.fn_set_theme(theme)
            tab.fn_refresh_theme()
            self.assertIn(ThemeManager.fn_colors().TEXT, tab.log_selector.settings_menu.styleSheet())

    # --- actions ---------------------------------------------------------------------
    def test_actions_run_the_file_and_rules_imports(self):
        tab = self.tab()
        rules, file_action = tab.log_selector.settings_menu.actions()
        with patch.object(DisplayNamesImportController, 'import_rules') as import_rules, \
                patch.object(DisplayNamesImportController, 'import_file') as import_file:
            # The tab bound the methods at start-up, so go through a fresh controller to check the wiring.
            tab.log_selector.settings_menu.clear()
            tab.log_selector.add_setting_action('Import Rules Display Names', tab.display_names_import.import_rules)
            tab.log_selector.add_setting_action('Import File Display Names', tab.display_names_import.import_file)
            rules, file_action = tab.log_selector.settings_menu.actions()
            rules.trigger()
            import_rules.assert_called_once_with()
            import_file.assert_not_called()
            file_action.trigger()
            import_file.assert_called_once_with()

    def test_the_real_wiring_reaches_the_controller(self):
        tab = self.tab()
        with patch(MODULE + '.QFileDialog.getOpenFileName', return_value=('', '')) as chooser:
            tab.log_selector.settings_menu.actions()[1].trigger()
        chooser.assert_called_once()
        with patch(MODULE + '.ImportDisplayNamesDialog') as dialog:
            dialog.return_value.exec.return_value = 0
            tab.log_selector.settings_menu.actions()[0].trigger()
        dialog.assert_called_once()

    def test_setting_button_is_disabled_together_with_the_log_selector_while_busy(self):
        tab = self.tab()
        tab.log_selector.setEnabled(False)
        self.assertFalse(tab.log_selector.settings_button.isEnabled())
        tab.log_selector.setEnabled(True)
        self.assertTrue(tab.log_selector.settings_button.isEnabled())


class DisplayNamesImportControllerTests(unittest.TestCase):
    """The import behaviour that used to live in Vehicle Manager, unchanged."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def controller(self):
        from PySide6.QtWidgets import QWidget
        parent = QWidget()
        self.addCleanup(parent.deleteLater)
        return DisplayNamesImportController(parent)

    def test_import_file_uses_selected_json_file(self):
        controller = self.controller()
        with patch(MODULE + '.QFileDialog.getOpenFileName', return_value=('C:/display_names.json', 'JSON Files (*.json)')), \
                patch(MODULE + '.import_display_names') as import_file, \
                patch(MODULE + '.reload_display_names') as reload_names, \
                patch.object(controller, '_show_auto_close_info') as success:
            controller.import_file()
        import_file.assert_called_once_with('C:/display_names.json')
        reload_names.assert_called_once_with()
        success.assert_called_once()

    def test_import_file_cancel_does_nothing_and_errors_are_reported(self):
        controller = self.controller()
        with patch(MODULE + '.QFileDialog.getOpenFileName', return_value=('', '')), \
                patch(MODULE + '.import_display_names') as import_file:
            controller.import_file()
        import_file.assert_not_called()
        with patch(MODULE + '.QFileDialog.getOpenFileName', return_value=('bad.json', '')), \
                patch(MODULE + '.import_display_names', side_effect=ValueError('Broken file')), \
                patch(MODULE + '.reload_display_names') as reload_names, \
                patch(MODULE + '.QMessageBox.warning') as warning, \
                patch.object(controller, '_show_auto_close_info') as success:
            controller.import_file()
        warning.assert_called_once()
        self.assertIn('Broken file', warning.call_args.args[2])
        reload_names.assert_not_called()
        success.assert_not_called()

    def test_import_rules_uses_dialog_rules(self):
        controller = self.controller()
        with patch(MODULE + '.ImportDisplayNamesDialog') as dialog, \
                patch(MODULE + '.import_display_name_rules') as import_rules, \
                patch(MODULE + '.reload_display_names') as reload_names, \
                patch.object(controller, '_show_auto_close_info') as success:
            dialog.return_value.exec.return_value = 1
            dialog.return_value.fn_rules.return_value = '22 F1 20|Global Time'
            controller.import_rules()
        import_rules.assert_called_once_with('22 F1 20|Global Time')
        reload_names.assert_called_once_with()
        success.assert_called_once()

    def test_import_rules_cancel_and_invalid_rules(self):
        controller = self.controller()
        with patch(MODULE + '.ImportDisplayNamesDialog') as dialog, \
                patch(MODULE + '.import_display_name_rules') as import_rules:
            dialog.return_value.exec.return_value = 0
            controller.import_rules()
        import_rules.assert_not_called()
        with patch(MODULE + '.ImportDisplayNamesDialog') as dialog, \
                patch(MODULE + '.import_display_name_rules', side_effect=ValueError('Bad rule')), \
                patch(MODULE + '.reload_display_names') as reload_names, \
                patch(MODULE + '.QMessageBox.warning') as warning:
            dialog.return_value.exec.return_value = 1
            dialog.return_value.fn_rules.return_value = '22 F1 GG|Broken'
            controller.import_rules()
        warning.assert_called_once()
        reload_names.assert_not_called()


if __name__ == '__main__':
    unittest.main()
