"""Import of UDS display names (a JSON file, or pasted rules) from any tab's Setting menu."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

from core.config_loader import import_display_name_rules, import_display_names
from core.uds_lookup import reload_display_names
from gui.dialogs.import_display_names_dialog import ImportDisplayNamesDialog

SUCCESS_NOTICE_MS = 1500
SUCCESS_NOTICE_WITH_HINT_MS = 3000  # Long enough to read the extra line.


class DisplayNamesImportController:
    def __init__(self, parent, hint=None):
        self.parent = parent
        # Optional callable returning an extra line for the success notice (e.g. "press Refresh ...").
        self._hint = hint

    def import_file(self):
        """Import File Display Names: choose a *.json file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self.parent,
            "Import Display Names",
            "",
            "JSON Files (*.json)",
        )
        if not file_path:
            return
        try:
            import_display_names(file_path)
            reload_display_names()
        except (FileNotFoundError, ValueError, OSError) as error:
            QMessageBox.warning(self.parent, "Import Display Names", str(error))
            return
        self._show_auto_close_info("Import Display Names", "Display names imported successfully.")

    def import_rules(self):
        """Import Rules Display Names: paste "request|name" rules in a dialog."""
        dialog = ImportDisplayNamesDialog(self.parent)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            import_display_name_rules(dialog.fn_rules())
            reload_display_names()
        except (ValueError, OSError) as error:
            QMessageBox.warning(self.parent, "Import Display Name Rules", str(error))
            return
        self._show_auto_close_info("Import Display Name Rules", "Display-name rules imported successfully.")

    def _show_auto_close_info(self, title, message):
        message_box = QMessageBox(self.parent)
        message_box.setIcon(QMessageBox.Information)
        message_box.setWindowTitle(title)
        hint = self._hint() if self._hint is not None else ""
        message_box.setText(f"{message}\n{hint}" if hint else message)
        message_box.setStandardButtons(QMessageBox.NoButton)
        QTimer.singleShot(SUCCESS_NOTICE_WITH_HINT_MS if hint else SUCCESS_NOTICE_MS, message_box.accept)
        message_box.exec()
