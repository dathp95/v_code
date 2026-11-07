from PySide6.QtCore import QPoint, Signal

from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QHBoxLayout,
    QMenu,
    QVBoxLayout,
    QWidget,
)

from gui.themes.styles.controls.menu_style import fn_apply_menu_style
from gui.widgets.controls.primary_button import PrimaryButton
from gui.widgets.controls.secondary_button import SecondaryButton
from gui.widgets.controls.primary_lineedit import PrimaryLineEdit
from gui.widgets.log_analyzer.layout_constants import FORM_ACTION_BUTTON_WIDTH


class PathSelectorWidget(QWidget):

    path_changed = Signal(str)

    def __init__(self, title, file_filter, *, settings=False):
        super().__init__()

        self.file_filter = file_filter
        self.label = QLabel(title)
        self.edit_path = PrimaryLineEdit(
            placeholder="Please click Browse button to select file *.blf, *.asc, *.txt",
        )
        self.browse_button = PrimaryButton("Browse")
        self.browse_button.setFixedWidth(FORM_ACTION_BUTTON_WIDTH)

        # Optional "Setting" button next to Browse (same size); its actions drop down from it.
        self.settings_button = None
        self.settings_menu = None
        if settings:
            self.settings_button = SecondaryButton(
                "Setting",
                width=FORM_ACTION_BUTTON_WIDTH,
                height=self.browse_button.minimumHeight(),
            )
            self.settings_button.setFixedWidth(FORM_ACTION_BUTTON_WIDTH)
            self.settings_menu = QMenu(self)

        self.set_ui()
        self.connect_signals()

    def set_ui(self):
        main_layout = QVBoxLayout(self)
        file_layout = QHBoxLayout()

        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(6)

        file_layout.setContentsMargins(0, 0, 0, 0)
        file_layout.setSpacing(8)

        file_layout.addWidget(
            self.edit_path,
            1,
        )
        file_layout.addWidget(self.browse_button)
        if self.settings_button is not None:
            file_layout.addWidget(self.settings_button)

        main_layout.addWidget(self.label)
        main_layout.addLayout(file_layout)


    def connect_signals(self):
        self.browse_button.clicked.connect(self.browse_file)
        if self.settings_button is not None:
            self.settings_button.clicked.connect(self.show_settings_menu)

    def add_setting_action(self, text, callback):
        """Add an entry to the Setting drop-down menu."""
        action = self.settings_menu.addAction(text)
        action.triggered.connect(lambda _checked=False: callback())
        return action

    def show_settings_menu(self):
        fn_apply_menu_style(self.settings_menu)
        self.settings_menu.popup(
            self.settings_button.mapToGlobal(QPoint(0, self.settings_button.height()))
        )

    def browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.label.text(),
            "",
            self.file_filter,
        )

        if file_path:
            self.edit_path.setText(file_path)
            self.path_changed.emit(file_path)

    def path(self):
        return self.edit_path.text()

    def set_path(self, value):
        self.edit_path.setText(value)

    def fn_refresh_theme(self):
        self.edit_path.fn_refresh_theme()
        self.browse_button.fn_refresh_theme()
        if self.settings_button is not None:
            self.settings_button.fn_refresh_theme()
            fn_apply_menu_style(self.settings_menu)
