"""Shared Save dialog for every Export button: modest fixed size, centered on the screen."""
from pathlib import Path

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QFileDialog

SAVE_DIALOG_SIZE = (860, 520)


def configure_save_dialog(dialog, parent=None):
    """Fixed, modest size, centered on the screen the window is on (not the remembered full-screen size)."""
    width, height = SAVE_DIALOG_SIZE
    dialog.resize(width, height)
    screen = parent.screen() if parent is not None else QGuiApplication.primaryScreen()
    if screen is not None:
        area = screen.availableGeometry()
        width, height = min(width, area.width()), min(height, area.height())
        dialog.resize(width, height)
        dialog.move(area.x() + (area.width() - width) // 2, area.y() + (area.height() - height) // 2)


def ask_save_path(parent, caption, path, name_filter, *, default_suffix="xlsx", confirm_overwrite=True):
    """Ask where to save; returns the chosen path or "" when cancelled.

    confirm_overwrite=False leaves the "file exists" question to the caller.
    """
    path = Path(path)
    dialog = QFileDialog(parent, caption, str(path.parent), name_filter)
    dialog.setAcceptMode(QFileDialog.AcceptSave)
    dialog.setFileMode(QFileDialog.AnyFile)
    dialog.setOption(QFileDialog.DontUseNativeDialog, True)  # The native one reopens at its last (huge) size.
    dialog.setOption(QFileDialog.DontConfirmOverwrite, not confirm_overwrite)
    if default_suffix:
        dialog.setDefaultSuffix(default_suffix)
    dialog.selectFile(path.name)
    configure_save_dialog(dialog, parent)
    if dialog.exec() != QDialog.Accepted or not dialog.selectedFiles():
        return ""
    return dialog.selectedFiles()[0]
