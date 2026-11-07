import logging

from PySide6.QtCore import QObject, QSignalBlocker

from PySide6.QtWidgets import QApplication, QMessageBox

from gui.themes.theme_manager import ThemeManager

from gui.workers.can_discovery_worker import CANDiscoveryTask

from gui.workers.can_connection_worker import CANConnectionOperation as Operation, CANConnectionTask

from services.can import CANChannelInfo, CANConfig, CANDeviceInfo, CANNoChannelsError, CANService, CANValidationError

from services.can import CANConnectionState as State

from core.bench_authorization import BenchAuthorizationContext

from repositories.load_config_start_store import LoadConfigStartStore

LOG = logging.getLogger(__name__)

START_CONFIG_TAB = "can_interface"


def _as_tuple(value):

    """JSON turns the device identity tuple into nested lists; turn it back."""

    return tuple(_as_tuple(item) for item in value) if isinstance(value, list) else value

class CanConnectionController(QObject):

    def __init__(self, service, view, parent=None, start_store=None):

        super().__init__(parent)

        self._start_store = start_store if start_store is not None else LoadConfigStartStore()

        self._service = service

        self.view = view

        for name in view.CONTROLS:

            setattr(self, name, getattr(view, name))

        self._status_state = "Disconnected"

        self._status_message = ""

        self._refreshing = False

        self._closing = False

        # Adapter and channel of the last successful connection (load_config_start.json): the first discovery of

        # a new run selects them again, falling back to the first entry when they are not present.

        saved = self._start_store.get_tab(START_CONFIG_TAB)

        self._previous_device = _as_tuple(saved["device"]) if isinstance(saved.get("device"), list) else None

        self._previous_channel = saved["channel"] if type(saved.get("channel")) is int else None

        self._auto_discovered = False

        app = QApplication.instance()

        self._discovery_task = CANDiscoveryTask(self._service, app)

        self._discovery_task.completed.connect(self._discovery_completed)

        self._discovery_task.failed.connect(self._discovery_failed)

        self.destroyed.connect(self._discovery_task.dispose)

        app.aboutToQuit.connect(self._discovery_task.shutdown)

        self._connection_task = CANConnectionTask(self._service, app)

        self._connection_task.completed.connect(self._connection_completed)

        self._connection_task.failed.connect(self._connection_failed)

        self._connection_task.connection_fault.connect(self._transport_fault)

        self.destroyed.connect(self._connection_task.dispose)

        app.aboutToQuit.connect(self._connection_task.shutdown)

        self._connect_signals()

        self._set_status("Disconnected")

    def _connect_signals(self):

        self.btn_connect.clicked.connect(self.connect_can)

        self.btn_disconnect.clicked.connect(self.disconnect_can)

        self.cmb_device.currentIndexChanged.connect(self._populate_device_channels)

        self.cmb_channel.currentIndexChanged.connect(self._update_button_states)

    def discover_on_first_show(self):

        # There is no Refresh button: adapters are looked up once when the tab first appears,
        # and again whenever Connect is pressed without a usable channel.

        if not self._auto_discovered:

            self._auto_discovered = True

            self.refresh_can_setup()

    def refresh_can_setup(self):

        if self._closing or self._refreshing or self._connection_task.running or self._service.snapshot.state not in (State.DISCONNECTED, State.ERROR):

            return

        device = self.cmb_device.currentData()

        channel = self.cmb_channel.currentData()

        if isinstance(device, CANDeviceInfo):

            self._previous_device = device.identity

        if isinstance(channel, CANChannelInfo):

            self._previous_channel = channel.identity

        self._refreshing = True

        self._set_status("Discovering", "Searching for Vector CAN devices.")

        self._discovery_task.start()

    def _discovery_completed(self, devices):

        if self._closing:

            return

        self._refreshing = False

        # External connections must never be replaced by a late discovery result.

        if self._service.fn_is_connected():

            self._set_status("Connected")

            return

        with QSignalBlocker(self.cmb_device):

            self.cmb_device.clear()

            selected = 0

            for index, device in enumerate(devices):

                parts = [device.name]

                if device.serial is not None:

                    parts.append(f"SN {device.serial}")

                if device.hw_index is not None:

                    parts.append(f"HW {device.hw_type}:{device.hw_index}" if device.hw_type is not None else f"HW index {device.hw_index}")

                if device.hw_type is None or device.hw_index is None:

                    global_index = device.channels[0].channel_index if device.channels else None

                    parts.append(f"Index {global_index}" if global_index is not None else f"Discovery {index + 1}")

                self.cmb_device.addItem(" - ".join(parts), device)

                if device.identity == self._previous_device:

                    selected = index

            self.cmb_device.setCurrentIndex(selected if devices else -1)

        self._populate_device_channels()

        if not devices:

            self._set_status("No devices", "No Vector CAN device detected.")

    def _populate_device_channels(self):

        device = self.cmb_device.currentData()

        with QSignalBlocker(self.cmb_channel):

            self.cmb_channel.clear()

            selected = 0

            if isinstance(device, CANDeviceInfo):

                for index, channel in enumerate(device.channels):

                    self.cmb_channel.addItem(channel.name, channel)

                    if device.identity == self._previous_device and channel.identity == self._previous_channel:

                        selected = index

                self.cmb_channel.setCurrentIndex(selected if device.channels else -1)

        self._update_button_states()

        if (not self._refreshing and not self._connection_task.running and isinstance(device, CANDeviceInfo)

                and self._service.snapshot.state in (State.DISCONNECTED, State.ERROR)):

            if not device.channels:

                self._set_status("No CAN channel", "The detected Vector device has no available CAN channel.")

            else:

                self._set_status("Disconnected", "" if self._has_selection() else "The selected channel has no unambiguous global channel index.")

    def _discovery_failed(self, error):

        if self._closing:

            return

        self._refreshing = False

        if self._service.fn_is_connected():

            self._set_status("Connected")

            return

        self.cmb_device.clear()

        self.cmb_channel.clear()

        snapshot = self._service.snapshot

        state = (State.RECOVERY_REQUIRED.value if snapshot.state == State.RECOVERY_REQUIRED

                 else "No CAN channel" if isinstance(error, CANNoChannelsError) else "Error")

        message = snapshot.error if snapshot.state == State.RECOVERY_REQUIRED else str(error)

        self._set_status(state, message)

        self._show_error(message)

    def connect_can(self):

        if (self._closing or self._refreshing or self._connection_task.running

                or self._service.snapshot.state not in (State.DISCONNECTED, State.ERROR)):

            return

        if self._service.snapshot.rediscovery_required or not self._has_selection():

            # Nothing valid to connect to yet: look for adapters, then let the user pick a channel.

            self.refresh_can_setup()

            return

        try:

            config = self._read_config()

            self._set_status("Connecting")

            self._connection_task.start(Operation.CONNECT, config)

            self._update_button_states()

        except Exception as error:

            self._set_status("Error", str(error))

            self._show_error(str(error))

            return

    def disconnect_can(self):

        if (self._closing or self._refreshing or self._connection_task.running

                or self._service.snapshot.state != State.CONNECTED):

            return

        self._set_status("Disconnecting")

        self._connection_task.start(Operation.DISCONNECT)

        self._update_button_states()

    def _connection_completed(self, operation, snapshot):

        if self._closing:

            return

        config = snapshot.config

        if operation == Operation.DISCONNECT:

            self.cmb_bench_policy.setCurrentIndex(0)

        details = (f"Vector SN {config.serial}, HW {config.hw_type}:{config.hw_index}, CAN {config.channel + 1}, global index {config.channel_index}, "

                   f"{config.bitrate} bit/s") if config else ""

        if config and config.bench_context:

            authorized = self._service.trusted_bench is not None

            details += (f'; bench context: {config.bench_context.context_id}; '

                        f'authorization: {"active" if authorized else "unavailable"}; only 10 01, 10 03, 14 FF FF FF')

        self._set_status(snapshot.state.value, details)

        if operation == Operation.CONNECT and snapshot.state == State.CONNECTED:

            self._remember_channel()

    def _remember_channel(self):

        """Keep the adapter and channel of a successful connection for the next start of the app."""

        device = self.cmb_device.currentData()

        channel = self.cmb_channel.currentData()

        if not (isinstance(device, CANDeviceInfo) and isinstance(channel, CANChannelInfo)):

            return

        try:

            self._start_store.set_tab_values(START_CONFIG_TAB, device=device.identity,
                                             channel=channel.identity, channel_name=channel.name)

        except (OSError, TypeError, ValueError):

            LOG.exception("Cannot save the CAN start-up configuration")

    def _connection_failed(self, operation, error):

        if self._closing:

            return

        snapshot = self._service.snapshot

        if snapshot.state != State.CONNECTED: self.cmb_bench_policy.setCurrentIndex(0)

        self._set_status(snapshot.state.value, str(error))

        self._show_error(str(error))

    def _transport_fault(self,snapshot):

        if not self._closing:

            self.cmb_bench_policy.setCurrentIndex(0)

            self._set_status(snapshot.state.value,snapshot.error)

    def _read_config(self):

        if not self._has_selection():

            raise CANValidationError("Select a detected Vector CAN channel before connecting.")

        device = self.cmb_device.currentData()

        channel = self.cmb_channel.currentData()

        vendor = self.cmb_vendor.currentData() if hasattr(self, 'cmb_vendor') and self.cmb_vendor.currentData() else 'vector'

        return CANConfig(

            interface=vendor,

            channel=channel.channel,

            bitrate=int(self.cmb_baudrate.currentData()),

            serial=device.serial,

            channel_index=channel.channel_index,

            hw_type=device.hw_type,

            hw_index=device.hw_index,

            hw_channel=channel.hw_channel,

            bench_context=BenchAuthorizationContext('manual-automotive-bench', authorized=True),

        )

    def _has_selection(self):

        device = self.cmb_device.currentData()

        channel = self.cmb_channel.currentData()

        return (isinstance(device, CANDeviceInfo) and isinstance(channel, CANChannelInfo)

                and channel in device.channels and channel.can_connect

                and (device.serial is not None or (device.hw_type is not None and device.hw_index is not None)))

    def _set_status(self, state, message=""):

        self._status_state = state

        self._status_message = message

        self.lbl_status.setText(state)

        self.lbl_status.setToolTip(message)

        self._update_button_states()

        self._refresh_status_theme()

    def _update_button_states(self):

        snapshot = self._service.snapshot

        idle = snapshot.state in (State.DISCONNECTED, State.ERROR)

        busy = self._connection_task.running or self._refreshing or self._closing

        self.btn_connect.setEnabled(idle and not busy)

        self.btn_disconnect.setEnabled(snapshot.state == State.CONNECTED and not busy)

        for combo in (self.cmb_vendor, self.cmb_device, self.cmb_channel, self.cmb_baudrate, self.cmb_bench_policy):

            if hasattr(combo, 'setEnabled'):

                combo.setEnabled(idle and not busy)

        has_channels = self.cmb_channel.count() > 0

        self.lbl_channel.setVisible(has_channels)

        self.cmb_channel.setVisible(has_channels)

        if snapshot.state == State.CONNECTED:

            self.btn_connect.hide()

            self.btn_disconnect.show()

        else:

            self.btn_connect.show()

            self.btn_disconnect.hide()

    def close(self):

        if not self._closing:

            self._closing = True

            self._discovery_task.dispose()

            self._connection_task.dispose()

    def _show_error(self, message):

        QMessageBox.warning(self.view, "CAN Interface", message)

    def fn_refresh_theme(self):

        self._refresh_status_theme()

    def _refresh_status_theme(self):

        colors = ThemeManager.fn_colors()

        muted = colors.TEXT if ThemeManager.fn_is_dark() else colors.SECONDARY_TEXT

        state_colors = {

            "Disconnected": muted,

            "Connecting": colors.WARNING,

            "Disconnecting": colors.WARNING,

            "Recovery required": colors.DANGER,

            "Connected": colors.SUCCESS,

            "Error": colors.DANGER,

            "Discovering": colors.WARNING,

            "No devices": muted,

            "No CAN channel": colors.WARNING,

        }

        color = state_colors.get(self._status_state, colors.TEXT)

        self.lbl_status.setStyleSheet(

            f"""

            QLabel {{

                color: {color};

                font-weight: bold;

            }}

            """

        )

        if hasattr(self.view, "lbl_status_dot"):

            self.view.lbl_status_dot.setStyleSheet(f"color: {color}; font-size: 14px;")

