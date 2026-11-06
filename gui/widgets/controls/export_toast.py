"""Reusable "file saved" popup for every Export button: OPEN FOLDER | OPEN FILE | CANCEL.

It floats at the bottom-right corner of the window that owns the exporting widget and closes itself after
EXPORT_TOAST_TIMEOUT_MS if the user does nothing.  Use show_export_toast(widget, path) from any tab.
"""
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout

from gui.themes.theme_manager import ThemeManager
from gui.widgets.controls.action_button import ActionButton
from gui.widgets.controls.primary_label import PrimaryLabel

EXPORT_TOAST_TIMEOUT_MS = 5000
EXPORT_TOAST_MARGIN = 16


def open_location(path):
    """Open a file or folder with the operating system's default handler."""
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class ExportToast(QFrame):
    def __init__(self, window, path, *, title="Export completed", timeout_ms=EXPORT_TOAST_TIMEOUT_MS):
        super().__init__(window)
        self.path = Path(path)
        self._window = window
        self.setObjectName("exportToast")
        self.setAttribute(Qt.WA_StyledBackground, True)

        self.lbl_title = PrimaryLabel(title)
        self.lbl_file = PrimaryLabel(self.path.name)
        self.lbl_file.setToolTip(str(self.path))
        self.btn_open_folder = ActionButton("OPEN FOLDER", width=110, height=30)
        self.btn_open_file = ActionButton("OPEN FILE", width=90, height=30, variant="primary")
        self.btn_cancel = ActionButton("CANCEL", width=80, height=30)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        for button in (self.btn_open_folder, self.btn_open_file, self.btn_cancel):
            buttons.addWidget(button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)
        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_file)
        layout.addLayout(buttons)

        self.btn_open_folder.clicked.connect(lambda: self._open(self.path.parent))
        self.btn_open_file.clicked.connect(lambda: self._open(self.path))
        self.btn_cancel.clicked.connect(self.dismiss)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(int(timeout_ms))
        self._timer.timeout.connect(self.dismiss)

        window.installEventFilter(self)
        self.fn_refresh_theme()
        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()
        self._timer.start()

    def _open(self, target):
        open_location(target)
        self.dismiss()

    def dismiss(self):
        self._timer.stop()
        self._window.removeEventFilter(self)
        self.hide()
        self.deleteLater()

    def reposition(self):
        self.move(max(self._window.width() - self.width() - EXPORT_TOAST_MARGIN, 0),
                  max(self._window.height() - self.height() - EXPORT_TOAST_MARGIN, 0))

    def eventFilter(self, watched: QObject, event):
        if watched is self._window and event.type() == QEvent.Resize:
            self.reposition()
        return False

    def fn_refresh_theme(self):
        colors = ThemeManager.fn_colors()
        self.setStyleSheet(
            f"QFrame#exportToast {{ background: {colors.WINDOW}; border: 1px solid {colors.BORDER};"
            f" border-radius: 8px; }}")
        for widget in (self.lbl_title, self.lbl_file, self.btn_open_folder, self.btn_open_file, self.btn_cancel):
            widget.fn_refresh_theme()
        self.lbl_title.setStyleSheet(f"color: {colors.TEXT}; font-weight: 700; background: transparent;")
        self.lbl_file.setStyleSheet(f"color: {colors.TEXT}; background: transparent;")


def show_export_toast(widget, path, *, title="Export completed", timeout_ms=EXPORT_TOAST_TIMEOUT_MS):
    """Show the popup in the bottom-right corner of widget's window, replacing any earlier one."""
    window = widget.window()
    previous = getattr(window, "_export_toast", None)
    if previous is not None:
        try:
            previous.dismiss()
        except RuntimeError:  # Already deleted by Qt.
            pass
    toast = ExportToast(window, path, title=title, timeout_ms=timeout_ms)
    window._export_toast = toast
    return toast
