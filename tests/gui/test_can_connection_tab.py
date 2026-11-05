import os
import subprocess
import sys
import time
import unittest
from threading import Event
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from gui.tabs.can_interface_tab import CANInterfaceTab
from gui.themes.theme import ThemeType
from gui.themes.theme_manager import ThemeManager
from services.can import CANService, CANConnectionError, CANConnectionState as State, VectorDriverUnavailableError
from tests.services.test_can_service import FakeCANBackend
from tests.gui.test_can_interface_tab import FakeCANService


class CANConnectionAutoDiscoveryTests(unittest.TestCase):
    """No Refresh button: the tab discovers adapters itself; Connect never invents a channel."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.backend = FakeCANBackend()
        self.backend.fn_receive_frame = lambda: None
        self.adapter = FakeCANService().devices
        self.service = CANService(self.backend)
        self.tab = CANInterfaceTab(self.service)
        self.addCleanup(self.tab.deleteLater)
        self.addCleanup(self.tab._connection_task.shutdown)
        self.addCleanup(self.tab.close)

    def wait(self, predicate):
        deadline = time.monotonic() + 5
        while predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.001)
        self.assertFalse(predicate())

    def test_there_is_no_refresh_button_and_the_bar_is_taller(self):
        self.assertFalse(hasattr(self.tab, 'btn_refresh'))
        self.assertIs(self.tab.action_layout.itemAt(0).widget(), self.tab.btn_connect)
        panel = self.tab.session_panel.connection
        self.assertGreaterEqual(panel.height(), 40)
        for widget in (panel.cmb_channel, panel.btn_connect, panel.cmb_device, panel.cmb_baudrate):
            self.assertGreaterEqual(widget.minimumHeight(), 30)

    def test_first_show_discovers_once_and_empty_channel_is_hidden(self):
        self.tab.show()
        self.wait(lambda: self.tab._discovery_task.running)
        self.assertEqual(self.backend.refresh_count, 1)
        self.assertEqual(self.tab.cmb_channel.count(), 0)
        self.assertTrue(self.tab.cmb_channel.isHidden() and self.tab.lbl_channel.isHidden())
        self.assertEqual(self.tab.lbl_status.text(), "No devices")
        self.tab.hide()
        self.tab.show()
        self.app.processEvents()
        self.assertEqual(self.backend.refresh_count, 1)

    def test_adapter_present_at_show_lists_channels_and_connect_goes_straight_through(self):
        self.backend.devices = self.adapter
        self.tab.show()
        self.wait(lambda: self.tab._discovery_task.running)
        self.assertEqual([self.tab.cmb_channel.itemText(i) for i in range(self.tab.cmb_channel.count())], ["CAN 1", "CAN 2"])
        self.assertFalse(self.tab.cmb_channel.isHidden())
        self.assertTrue(self.tab.btn_connect.isEnabled())
        self.tab.cmb_channel.setCurrentIndex(1)
        self.tab.btn_connect.click()
        self.wait(lambda: self.tab._connection_task.running)
        self.assertEqual(self.backend.opened_config.channel_index, 9)
        self.assertEqual(self.backend.refresh_count, 1)

    def test_connect_with_no_channels_only_discovers_then_waits_for_user_choice(self):
        self.tab.show()
        self.wait(lambda: self.tab._discovery_task.running)
        self.backend.devices = self.adapter  # adapter plugged in after launch
        self.assertTrue(self.tab.btn_connect.isEnabled())
        self.tab.btn_connect.click()
        self.wait(lambda: self.tab._discovery_task.running)
        self.assertEqual(self.backend.refresh_count, 2)
        self.assertIsNone(self.backend.opened_config)
        self.assertFalse(self.tab.cmb_channel.isHidden())
        self.tab.btn_connect.click()
        self.wait(lambda: self.tab._connection_task.running)
        self.assertIsNotNone(self.backend.opened_config)
        self.assertEqual(self.service.snapshot.state, State.CONNECTED)


class CANConnectionTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.backend = FakeCANBackend()
        # Connection-only tests have no traffic but must satisfy continuous RX.
        self.backend.fn_receive_frame = lambda: None
        self.backend.devices = FakeCANService().devices
        self.service = CANService(self.backend)
        self.tab = CANInterfaceTab(self.service)
        self.addCleanup(self.tab.deleteLater)
        self.addCleanup(self.tab._connection_task.shutdown)
        self.addCleanup(self.tab.close)
        self.tab.refresh_can_setup()
        self.wait(lambda: self.tab._discovery_task.running)

    def wait(self, predicate):
        deadline = time.monotonic() + 5
        while predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.001)
        self.assertFalse(predicate())

    def connect(self):
        self.tab.connect_can()
        self.wait(lambda: self.tab._connection_task.running)

    def test_connect_with_rediscovery_pending_runs_discovery_instead_of_connecting(self):
        def unplugged(config):
            raise CANConnectionError("Selected hardware is unavailable.", rediscovery_required=True)

        original = self.backend.fn_open
        self.backend.fn_open = unplugged
        with patch("gui.controllers.can_connection_controller.QMessageBox.warning"):
            self.connect()
        self.assertTrue(self.service.snapshot.rediscovery_required)
        self.backend.fn_open = original
        self.assertTrue(self.tab.btn_connect.isEnabled())
        count = self.backend.refresh_count
        self.tab.btn_connect.click()
        self.wait(lambda: self.tab._discovery_task.running)
        self.assertEqual(self.backend.refresh_count, count + 1)
        self.assertIsNone(self.backend.opened_config)
        self.assertFalse(self.service.snapshot.rediscovery_required)
        self.assertNotEqual(self.service.snapshot.state, State.CONNECTED)

    def test_slow_connect_and_disconnect_freeze_config_and_keep_ui_responsive(self):
        entered, release = Event(), Event()
        original = self.backend.fn_open

        def slow(config):
            entered.set()
            release.wait(3)
            original(config)

        self.backend.fn_open = slow
        self.tab.cmb_channel.setCurrentIndex(1)
        self.tab.connect_can()
        try:
            self.assertTrue(entered.wait(2))
            self.assertEqual(self.service.snapshot.state, State.CONNECTING)
            self.assertEqual(self.tab.lbl_status.text(), "Connecting")
            self.assertTrue(all(not button.isEnabled() for button in (self.tab.btn_connect, self.tab.btn_disconnect)))
            self.assertFalse(self.tab.cmb_channel.isEnabled())
            heartbeat = []
            QTimer.singleShot(0, lambda: heartbeat.append(True))
            self.app.processEvents()
            self.assertEqual(heartbeat, [True])
            # Even a programmatic selection change cannot mutate frozen config.
            self.tab.cmb_channel.setCurrentIndex(0)
            self.tab.connect_can()
            self.tab.disconnect_can()
            self.tab.refresh_can_setup()
            self.assertEqual(self.backend.refresh_count, 1)
        finally:
            release.set()
            self.wait(lambda: self.tab._connection_task.running)
        self.assertEqual(self.backend.opened_config.channel_index, 9)
        self.assertIn("global index 9", self.tab.lbl_status.toolTip())

        entered.clear()
        release.clear()
        original_close = self.backend.fn_close

        def slow_close():
            entered.set()
            release.wait(3)
            original_close()

        self.backend.fn_close = slow_close
        self.tab.disconnect_can()
        try:
            self.assertTrue(entered.wait(2))
            self.assertEqual(self.service.snapshot.state, State.DISCONNECTING)
            self.assertEqual(self.tab.lbl_status.text(), "Disconnecting")
            self.assertFalse(self.tab.btn_connect.isEnabled())
            self.assertFalse(self.tab.btn_disconnect.isEnabled())
            self.tab.connect_can()
            self.tab.disconnect_can()
            self.tab.refresh_can_setup()
            self.assertEqual(self.backend.refresh_count, 1)
            heartbeat.clear()
            QTimer.singleShot(0, lambda: heartbeat.append(True))
            self.app.processEvents()
            self.assertEqual(heartbeat, [True])
        finally:
            release.set()
            self.wait(lambda: self.tab._connection_task.running)
        self.assertEqual(self.backend.close_count, 1)
        self.assertEqual(self.service.snapshot.state, State.DISCONNECTED)
        self.assertTrue(self.tab.btn_connect.isEnabled())

    def test_unplug_error_requires_refresh_before_retry(self):
        original = self.backend.fn_open

        def unplugged(config):
            raise CANConnectionError("Selected hardware is unavailable.", rediscovery_required=True)

        self.backend.fn_open = unplugged
        with patch("gui.controllers.can_connection_controller.QMessageBox.warning") as warning:
            self.connect()
        warning.assert_called_once()
        self.assertEqual(self.service.snapshot.state, State.ERROR)
        self.assertTrue(self.tab.btn_connect.isEnabled())
        self.backend.fn_open = original
        self.tab.btn_connect.click()  # Rediscovery is pending: Connect looks for adapters again.
        self.wait(lambda: self.tab._discovery_task.running)
        self.assertIsNone(self.backend.opened_config)
        self.connect()
        self.assertEqual(self.service.snapshot.state, State.CONNECTED)

    def test_cleanup_failure_disables_unsafe_controls_and_survives_theme(self):
        self.connect()

        def fail():
            raise RuntimeError("native close failed")

        self.backend.fn_close = fail
        with patch("gui.controllers.can_connection_controller.QMessageBox.warning"):
            self.tab.disconnect_can()
            self.wait(lambda: self.tab._connection_task.running)
        self.assertEqual(self.service.snapshot.state, State.RECOVERY_REQUIRED)
        self.assertEqual(self.tab.lbl_status.text(), "Recovery required")
        self.addCleanup(ThemeManager.fn_set_theme, ThemeManager.fn_theme())
        for theme in (ThemeType.LIGHT, ThemeType.DARK):
            ThemeManager.fn_set_theme(theme)
            self.tab.fn_refresh_theme()
            self.assertFalse(self.tab.btn_connect.isEnabled())
            self.assertFalse(self.tab.btn_disconnect.isEnabled())
            self.assertFalse(self.tab.cmb_channel.isEnabled())

    def test_discovery_cleanup_failure_shows_recovery_message(self):
        self.backend.recovery_required = True
        self.backend.fn_refresh = Mock(side_effect=VectorDriverUnavailableError("Vector XL Driver is unavailable."))
        with patch("gui.controllers.can_connection_controller.QMessageBox.warning") as warning:
            self.tab.refresh_can_setup()
            self.wait(lambda: self.tab._discovery_task.running)
        self.assertEqual(self.tab.lbl_status.text(), "Recovery required")
        self.assertIn("cleanup", self.tab.lbl_status.toolTip())
        self.assertIn("Restart", warning.call_args.args[2])
        self.assertFalse(self.tab.btn_connect.isEnabled())

    def test_close_during_connect_ignores_late_result_and_cleans_bus(self):
        entered, release = Event(), Event()
        original = self.backend.fn_open

        def slow(config):
            entered.set()
            release.wait(3)
            original(config)

        self.backend.fn_open = slow
        self.tab.connect_can()
        try:
            self.assertTrue(entered.wait(2))
            self.tab.close()
        finally:
            release.set()
            self.wait(lambda: self.tab._connection_task.alive)
        self.assertEqual(self.service.snapshot.state, State.DISCONNECTED)
        self.assertNotEqual(self.tab.lbl_status.text(), "Connected")
        self.assertEqual(self.backend.close_count, 1)

    def test_application_quit_during_native_open_is_safe(self):
        script = '''
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from threading import Event, Timer
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from gui.workers.can_connection_worker import CANConnectionTask, CANConnectionOperation
from services.can import CANService, CANConfig, CANConnectionState
from tests.services.test_can_service import FakeCANBackend
app = QApplication([])
backend = FakeCANBackend()
entered, release = Event(), Event()
original = backend.fn_open
def slow(config):
    entered.set()
    release.wait(3)
    original(config)
backend.fn_open = slow
service = CANService(backend)
task = CANConnectionTask(service, app)
app.aboutToQuit.connect(task.shutdown)
task.start(CANConnectionOperation.CONNECT, CANConfig('vector', 0, 500000))
assert entered.wait(2)
timer = Timer(0.05, release.set)
timer.start()
QTimer.singleShot(0, app.quit)
app.exec()
timer.join()
assert not task.alive
assert service.snapshot.state == CANConnectionState.DISCONNECTED
assert backend.close_count == 1
print('shutdown-clean')
'''
        result = subprocess.run([sys.executable, "-X", "faulthandler", "-c", script], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("shutdown-clean", result.stdout)

