"""Shared Save dialog for every Export button: modest fixed size, centered on the screen.

It is Qt's own dialog (the native Windows one reopens at its last, often full-screen, size), so its left
sidebar is rebuilt here to keep what people expect: the folder being used, recently used folders, the
Windows Quick access folders, the usual user folders and the drives.
"""
import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QDir, QSettings, QStandardPaths, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QFileDialog

SAVE_DIALOG_SIZE = (860, 520)
RECENT_FOLDER_LIMIT = 5
QUICK_ACCESS_LIMIT = 12
QUICK_ACCESS_TIMEOUT_S = 3

# Folders of the Windows "Quick access" node (pinned + frequent), listed through the shell.
_QUICK_ACCESS_SCRIPT = (
    "$ErrorActionPreference='Stop';"
    "(New-Object -ComObject Shell.Application).Namespace('shell:::{679f85cb-0220-4080-b29b-5540cc05aab6}')"
    ".Items() | Where-Object { $_.IsFolder } | ForEach-Object { $_.Path }"
)
_quick_access_cache = None


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


def _settings():
    return QSettings(QSettings.IniFormat, QSettings.UserScope, "V-CODE", "save_dialog")


def recent_folders():
    """Folders the user saved into recently, newest first (only those that still exist)."""
    value = _settings().value("recent_folders", [])
    if isinstance(value, str):
        value = [value]
    return [folder for folder in (value or []) if Path(folder).is_dir()][:RECENT_FOLDER_LIMIT]


def remember_folder(folder):
    folder = str(Path(folder))
    others = [item for item in recent_folders() if Path(item) != Path(folder)]
    _settings().setValue("recent_folders", [folder] + others[:RECENT_FOLDER_LIMIT - 1])


def windows_quick_access_folders():
    """Pinned / frequent folders of Windows Explorer's Quick access; [] elsewhere or when the shell is unavailable."""
    global _quick_access_cache
    if _quick_access_cache is not None:
        return _quick_access_cache
    folders = []
    if sys.platform == "win32":
        try:
            done = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", _QUICK_ACCESS_SCRIPT],
                capture_output=True, text=True, timeout=QUICK_ACCESS_TIMEOUT_S, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if done.returncode == 0:
                folders = [line.strip() for line in done.stdout.splitlines() if Path(line.strip()).is_dir()]
        except (OSError, subprocess.SubprocessError):
            folders = []
    _quick_access_cache = folders[:QUICK_ACCESS_LIMIT]
    return _quick_access_cache


def prefetch_quick_access():
    """Read the Quick access list in the background so the first Save dialog opens without waiting for it."""
    if _quick_access_cache is None and sys.platform == "win32":
        threading.Thread(target=windows_quick_access_folders, name="quick-access-prefetch", daemon=True).start()


def sidebar_folders(current_folder):
    """Ordered, de-duplicated, existing folders for the dialog sidebar."""
    standard = [QStandardPaths.writableLocation(location) for location in (
        QStandardPaths.DesktopLocation, QStandardPaths.DocumentsLocation,
        QStandardPaths.DownloadLocation, QStandardPaths.PicturesLocation)]
    drives = [info.absoluteFilePath() for info in QDir.drives()]
    result, seen = [], set()
    for folder in [str(current_folder), *recent_folders(), *windows_quick_access_folders(), *standard, *drives]:
        key = str(Path(folder)).casefold() if folder else ""
        if key and key not in seen and Path(folder).is_dir():
            seen.add(key)
            result.append(str(Path(folder)))
    return result


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
    dialog.setSidebarUrls([QUrl.fromLocalFile(folder) for folder in sidebar_folders(path.parent)])
    dialog.setHistory(recent_folders())
    dialog.selectFile(path.name)
    configure_save_dialog(dialog, parent)
    if dialog.exec() != QDialog.Accepted or not dialog.selectedFiles():
        return ""
    chosen = dialog.selectedFiles()[0]
    remember_folder(Path(chosen).parent)
    return chosen
