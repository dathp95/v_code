from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDoubleSpinBox

from gui.themes.styles.controls.spinbox_style import fn_spinbox_style


class PrimaryIntegerSpinBox(QDoubleSpinBox):
    """Whole-number spin box with the same look as the Q current "Wake duration (s)" field.

    Built like that field (a QDoubleSpinBox styled with fn_spinbox_style, centered text), only with no
    decimals, and value() always returns an int so models never receive floats.
    """

    def __init__(self, width: int = 110, height: int = 36, parent=None):
        super().__init__(parent)

        self.setDecimals(0)
        self.setFixedWidth(width)
        self.setMinimumHeight(height)
        self.lineEdit().setAlignment(Qt.AlignCenter)

        self.fn_refresh_theme()

    def value(self) -> int:
        return int(round(super().value()))

    def fn_refresh_theme(self):
        self.setStyleSheet(fn_spinbox_style())
