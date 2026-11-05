from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtWidgets import QHeaderView, QStyle, QStyleOptionButton


class CheckAllHeader(QHeaderView):
    """Horizontal header whose first section is a working "select all" check box."""

    CHECK_COLUMN = 0

    toggle_requested = Signal(bool)  # True: select every row, False: clear every row.

    def __init__(self, orientation=Qt.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self._state = Qt.Unchecked
        self.setSectionsClickable(True)

    def check_state(self):
        return self._state

    def set_check_state(self, state):
        if state != self._state:
            self._state = state
            self.updateSection(self.CHECK_COLUMN)

    def paintSection(self, painter, rect, logical_index):
        super().paintSection(painter, rect, logical_index)
        if logical_index != self.CHECK_COLUMN:
            return
        style = self.style()
        width = style.pixelMetric(QStyle.PM_IndicatorWidth)
        height = style.pixelMetric(QStyle.PM_IndicatorHeight)
        option = QStyleOptionButton()
        option.rect = QRect(rect.x() + (rect.width() - width) // 2,
                            rect.y() + (rect.height() - height) // 2, width, height)
        option.state = QStyle.State_Enabled | (QStyle.State_Active if self.isActiveWindow() else QStyle.State_None)
        option.state |= {Qt.Checked: QStyle.State_On,
                         Qt.PartiallyChecked: QStyle.State_NoChange}.get(self._state, QStyle.State_Off)
        style.drawPrimitive(QStyle.PE_IndicatorCheckBox, option, painter, self)

    def mousePressEvent(self, event):
        if self.logicalIndexAt(event.position().toPoint()) == self.CHECK_COLUMN:
            # A partial selection is completed first; only a full one is cleared.
            self.toggle_requested.emit(self._state != Qt.Checked)
            event.accept()
            return
        super().mousePressEvent(event)
