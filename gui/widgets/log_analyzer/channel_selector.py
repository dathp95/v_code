from PySide6.QtCore import Signal, Qt   
from PySide6.QtWidgets import QVBoxLayout, QWidget

from gui.widgets.controls.primary_combobox import PrimaryComboBox
from gui.widgets.controls.primary_label import PrimaryLabel


class DiagnosticChannelSelectorWidget(QWidget):
    channel_changed = Signal(object)

    def __init__(self):
        super().__init__()
        self._setup_ui()
        self._connect_signals()
        self.fn_clear()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.lbl_channel = PrimaryLabel("Diagnostic Channel")
        self.cmb_channel = PrimaryComboBox()
        self.cmb_channel.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.cmb_channel.setAutoFillBackground(False)

        layout.addWidget(self.lbl_channel)
        layout.addWidget(self.cmb_channel)

    def _connect_signals(self):
        self.cmb_channel.currentIndexChanged.connect(
            self._fn_emit_channel_changed
        )

    def _fn_emit_channel_changed(self):
        self.channel_changed.emit(
            self.fn_channel()
        )

    def _fn_set_single_item(
            self,
            text: str,
            data=None,
            enabled: bool = False,
        ):
        self.cmb_channel.blockSignals(True)
        self.cmb_channel.clear()
        self.cmb_channel.setPlaceholderText("")
        self.cmb_channel.addItem(text, data)
        self.cmb_channel.setCurrentIndex(0)
        self.cmb_channel.setEnabled(enabled)
        self.cmb_channel.blockSignals(False)

    def fn_clear(self):
        self._fn_set_single_item(
            "No log selected",
            None,
            False,
        )

    def fn_set_channels(self, channels):
        normalized_channels = sorted({
            int(channel)
            for channel in channels
            if channel is not None
        })

        if not normalized_channels:
            self._fn_set_single_item(
                "No CAN channel detected",
                None,
                False,
            )
            return

        if len(normalized_channels) == 1:
            channel = normalized_channels[0]
            self._fn_set_single_item(
                f"Channel {channel}",
                channel,
                False,
            )
            return

        self.cmb_channel.blockSignals(True)
        self.cmb_channel.clear()
        self.cmb_channel.setPlaceholderText("Select channel...")

        for channel in normalized_channels:
            self.cmb_channel.addItem(
                f"Channel {channel}",
                channel,
            )

        self.cmb_channel.setCurrentIndex(-1)
        self.cmb_channel.setEnabled(True)
        self.cmb_channel.blockSignals(False)

    def fn_channel(self):
        return self.cmb_channel.currentData()

    def _reset_auto_marks(self):
        for index in range(self.cmb_channel.count()):
            self.cmb_channel.setItemText(index, f"Channel {self.cmb_channel.itemData(index)}")
        self.cmb_channel.setToolTip("")

    def fn_select_channel(self, channel, *, auto=False):
        """Select a listed channel (emits channel_changed); auto=True marks it as found by the tool."""
        index = self.cmb_channel.findData(channel)
        if index < 0:
            return False
        self._reset_auto_marks()
        if auto:
            self.cmb_channel.setItemText(index, f"Channel {channel} (auto)")
            self.cmb_channel.setToolTip("Detected automatically: this channel carries the vehicle's diagnostic request/response IDs.")
        self.cmb_channel.setCurrentIndex(index)
        return True

    def fn_clear_selection(self):
        """Back to "Select channel..." (several channels listed, none chosen)."""
        self._reset_auto_marks()
        self.cmb_channel.setCurrentIndex(-1)

    def fn_is_auto_selected(self):
        index = self.cmb_channel.currentIndex()
        return index >= 0 and self.cmb_channel.itemText(index).endswith("(auto)")

    def fn_refresh_theme(self):
        self.lbl_channel.fn_refresh_theme()
        self.cmb_channel.fn_refresh_theme()
