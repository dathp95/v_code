from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QWidget,
    QComboBox,
    QSizePolicy,
)
from gui.widgets.controls.primary_button import PrimaryButton
from gui.widgets.controls.primary_combobox import PrimaryComboBox
from gui.widgets.controls.primary_label import PrimaryLabel
from gui.themes.styles.controls.scrollbar_style import fn_apply_scrollbar_style

CONTROL_HEIGHT = 30
CONTROL_BAR_HEIGHT = 40


class CanConnectionPanel(QWidget):
    CONTROLS = (
        "lbl_vendor",
        "lbl_device",
        "lbl_channel",
        "lbl_baudrate",
        "cmb_vendor",
        "cmb_device",
        "cmb_channel",
        "cmb_baudrate",
        "btn_connect",
        "btn_disconnect",
        "lbl_status",
        "action_layout",
        "cmb_bench_policy",
    )

    def __init__(self):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setFixedHeight(CONTROL_BAR_HEIGHT)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(4, 2, 4, 2)
        main_layout.setSpacing(6)
        main_layout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        # 1. Toggle button for collapsible details (<< / >>)
        self.btn_toggle_details = PrimaryButton("<<", width=30, height=CONTROL_HEIGHT)
        self.btn_toggle_details.setToolTip("Show/hide connection details (Device, Baudrate)")
        self.btn_toggle_details.clicked.connect(self._toggle_details)
        main_layout.addWidget(self.btn_toggle_details)

        # 2. Hidden-by-default details panel (Device, Baudrate only - Vendor & Bench Policy removed from visible UI)
        self.details_widget = QWidget()
        details_layout = QHBoxLayout(self.details_widget)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(6)

        # Keep internal dummy attributes for backward compatibility
        self.lbl_vendor = PrimaryLabel("Vendor")
        self.cmb_vendor = PrimaryComboBox(minimum_height=CONTROL_HEIGHT)
        self.cmb_vendor.addItem("Vector", "vector")

        self.cmb_bench_policy = PrimaryComboBox(minimum_height=CONTROL_HEIGHT)
        self.cmb_bench_policy.addItem("Authorize bench", "manual-automotive-bench")

        self.lbl_device = PrimaryLabel("Device")
        self.cmb_device = PrimaryComboBox(minimum_height=CONTROL_HEIGHT)
        self.cmb_device.setMinimumContentsLength(8)
        self.cmb_device.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_device.setMaxVisibleItems(10)
        details_layout.addWidget(self.lbl_device)
        details_layout.addWidget(self.cmb_device)

        self.lbl_baudrate = PrimaryLabel("Baudrate")
        self.cmb_baudrate = PrimaryComboBox(minimum_height=CONTROL_HEIGHT)
        for bitrate in (125000, 250000, 500000, 1000000):
            self.cmb_baudrate.addItem(f"{bitrate // 1000} kbit/s", bitrate)
        self.cmb_baudrate.setCurrentIndex(2)
        details_layout.addWidget(self.lbl_baudrate)
        details_layout.addWidget(self.cmb_baudrate)

        self.details_widget.hide()
        main_layout.addWidget(self.details_widget)

        # 3. Channel selector: shown by the controller only while an adapter has reported channels
        self.lbl_channel = PrimaryLabel("Channel")
        self.cmb_channel = PrimaryComboBox(minimum_height=CONTROL_HEIGHT)
        self.cmb_channel.setMinimumContentsLength(6)
        self.cmb_channel.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_channel.setMaxVisibleItems(10)
        main_layout.addWidget(self.lbl_channel)
        main_layout.addWidget(self.cmb_channel)

        # 4. Action layout: [btn_connect/btn_disconnect, status]
        self.btn_connect = PrimaryButton("Connect", width=80, height=CONTROL_HEIGHT)
        self.btn_disconnect = PrimaryButton("Disconnect", width=80, height=CONTROL_HEIGHT)
        self.btn_disconnect.hide()

        self.lbl_status = QLabel("Disconnected")
        self.lbl_status.setMinimumHeight(CONTROL_HEIGHT)
        self.lbl_status.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.lbl_status.setStyleSheet("font-weight: bold; color: #94a3b8;")

        self.lbl_status_dot = QLabel("●")
        self.lbl_status_dot.setFixedSize(14, CONTROL_HEIGHT)
        self.lbl_status_dot.setAlignment(Qt.AlignCenter)
        self.lbl_status_dot.setStyleSheet("color: #94a3b8; font-size: 14px;")

        self.action_layout = QHBoxLayout()
        self.action_layout.setContentsMargins(0, 0, 0, 0)
        self.action_layout.setSpacing(6)
        self.action_layout.addWidget(self.btn_connect)
        self.action_layout.addWidget(self.btn_disconnect)
        self.action_layout.addWidget(self.lbl_status)
        self.action_layout.addWidget(self.lbl_status_dot)

        main_layout.addLayout(self.action_layout)

        self.title = PrimaryLabel("Connection")
        self.fn_refresh_theme()

    def _toggle_details(self):
        is_hidden = self.details_widget.isHidden()
        self.details_widget.setVisible(is_hidden)
        self.btn_toggle_details.setText(">>" if is_hidden else "<<")

    def fn_refresh_theme(self):
        if hasattr(self, "title") and hasattr(self.title, "fn_refresh_theme"):
            self.title.fn_refresh_theme()
        for name in self.CONTROLS:
            if hasattr(self, name):
                widget = getattr(self, name)
                if hasattr(widget, "fn_refresh_theme"):
                    widget.fn_refresh_theme()
                if isinstance(widget, PrimaryComboBox):
                    fn_apply_scrollbar_style(widget.view())
