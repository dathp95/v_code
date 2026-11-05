import os
import time
import unittest
from threading import Event
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QThread, QTimer
from gui.themes.theme import ThemeType
from gui.themes.theme_manager import ThemeManager
from services.can import CANChannelInfo, CANDeviceInfo, VectorDriverUnavailableError, CANConnectionSnapshot, CANConnectionState as State
from gui.workers.can_connection_worker import CANConnectionTask

from core.diagnostic_sequence import DiagnosticStep, DiagnosticTestCase

from gui.tabs.can_interface_tab import CANInterfaceTab
from gui.widgets.diagnostic import (
    DiagnosticSequenceList,
    DiagnosticSequenceTable,
)


class FakeCANService:

    def __init__(self):
        self.config = None
        self.connected = False
        self.refresh_count = 0
        self.connect_error = None
        self.devices = (CANDeviceInfo("VN1630A", 123456, 57, 0, (
            CANChannelInfo(0, 4, "CAN 1", True, 0), CANChannelInfo(1, 9, "CAN 2", False, 1),
        )),)
        self.discovery_error = None
        self.gate = None
        self.discovery_threads = []
        self.state = State.DISCONNECTED
        self.trusted_bench = None

    def fn_revoke_trusted_bench(self):
        self.trusted_bench = None

    @property
    def snapshot(self):
        return CANConnectionSnapshot(self.state, self.config if self.connected else None)

    def fn_connect(self, config):
        if self.connect_error is not None:
            self.state = State.ERROR
            raise self.connect_error
        self.config = config
        self.connected = True
        self.state = State.CONNECTED

    def fn_disconnect(self):
        self.connected = False
        self.state = State.DISCONNECTED

    def fn_is_connected(self):
        return self.connected

    def fn_refresh(self):
        self.refresh_count += 1
        self.discovery_threads.append(QThread.currentThread())
        if self.gate is not None:
            if not self.gate.wait(5):
                raise RuntimeError("test did not release discovery")
        if self.discovery_error is not None:
            raise self.discovery_error
        return self.devices


class CANInterfaceTabTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def refresh(self, tab):
        tab.refresh_can_setup()
        self.wait_for_refresh(tab)

    def tearDown(self):
        for task in self.application.findChildren(CANConnectionTask):
            task.shutdown()
        self.application.processEvents()

    def connect(self, tab):
        tab.connect_can()
        self.wait_for_connection(tab)

    def wait_for_connection(self, tab):
        deadline = time.monotonic() + 5
        while tab._connection_task.running and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.001)
        self.assertFalse(tab._connection_task.running)

    def wait_for_refresh(self, tab):
        deadline = time.monotonic() + 10
        while tab._discovery_task.running and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.001)
        self.assertFalse(tab._discovery_task.running)
        self.application.processEvents()

    def test_initial_values_and_button_states(self):
        tab = CANInterfaceTab(service=FakeCANService())
        self.addCleanup(tab.deleteLater)

        self.assertEqual(tab.cmb_vendor.currentText(), "Vector")
        self.assertEqual(tab.cmb_device.count(), 0)
        self.assertEqual(tab.cmb_channel.count(), 0)
        self.assertEqual(tab.cmb_baudrate.currentData(), 500000)
        self.assertEqual(tab.lbl_status.text(), "Disconnected")
        self.assertTrue(tab.btn_connect.isEnabled())  # Connect looks for adapters when none is listed.
        self.assertFalse(tab.btn_disconnect.isEnabled())
        self.assertTrue(tab.cmb_channel.isHidden() and tab.lbl_channel.isHidden())

    def test_action_buttons_and_status_are_in_the_same_row(self):
        tab = CANInterfaceTab(service=FakeCANService())
        self.addCleanup(tab.deleteLater)

        self.assertIs(tab.action_layout.itemAt(0).widget(), tab.btn_connect)
        self.assertIs(tab.action_layout.itemAt(1).widget(), tab.btn_disconnect)
        self.assertIs(tab.action_layout.itemAt(2).widget(), tab.lbl_status)
        self.assertGreaterEqual(
            tab.lbl_status.minimumHeight(),
            tab.btn_connect.minimumHeight(),
        )

    def test_real_service_starts_without_loading_python_can_and_reports_missing_dependency(self):
        with patch("services.can.vector_backend.import_module", side_effect=ImportError("missing")) as load, patch(
            "gui.controllers.can_connection_controller.QMessageBox.warning"
        ) as warning:
            tab = CANInterfaceTab()
            self.addCleanup(tab.deleteLater)
            load.assert_not_called()
            self.refresh(tab)
        warning.assert_called_once()
        self.assertEqual(tab.lbl_status.toolTip(), "python-can is not installed.")
        self.assertEqual(tab.cmb_device.count(), 0)

    def test_diagnostic_sequence_list_and_table_editor_are_available(self):
        tab = CANInterfaceTab(service=FakeCANService())
        self.addCleanup(tab.deleteLater)

        self.assertIsInstance(tab.sequence_list, DiagnosticSequenceList)
        self.assertIsInstance(tab.sequence_table, DiagnosticSequenceTable)

    def test_sequence_selected_loads_center_table(self):
        tab = CANInterfaceTab(service=FakeCANService())
        self.addCleanup(tab.deleteLater)
        test_case = DiagnosticTestCase(
            schema_version=1,
            name="READ VIN",
            description="",
            enabled=True,
            steps=[
                DiagnosticStep(
                    step=1,
                    sequence_name="Read VIN",
                    ecu="ACU",
                    request="22 F1 90",
                )
            ],
        )

        tab._on_sequence_selected(test_case)

        self.assertEqual(tab.sequence_table.table.rowCount(), 1)
        self.assertEqual(
            tab.sequence_table.table.item(
                0,
                tab.sequence_table.COL_REQUEST,
            ).text(),
            "22 F1 90",
        )

    def test_connect_uses_selected_channel_and_bitrate(self):
        service = FakeCANService()
        tab = CANInterfaceTab(service=service)
        self.addCleanup(tab.deleteLater)

        self.refresh(tab)
        tab.cmb_channel.setCurrentIndex(1)
        tab.cmb_baudrate.setCurrentIndex(3)
        self.connect(tab)

        self.assertEqual(service.config.interface, "vector")
        self.assertEqual(service.config.channel, 1)
        self.assertEqual(service.config.bitrate, 1000000)
        self.assertEqual(service.config.serial, 123456)
        self.assertEqual(service.config.channel_index, 9)
        self.assertEqual(tab.lbl_status.text(), "Connected")
        self.assertFalse(tab.btn_connect.isEnabled())
        self.assertTrue(tab.btn_disconnect.isEnabled())

    def test_connect_error_updates_status_without_crash(self):
        service = FakeCANService()
        service.connect_error = RuntimeError("Invalid Vector CAN channel.")
        tab = CANInterfaceTab(service=service)
        self.addCleanup(tab.deleteLater)

        self.refresh(tab)
        with patch("gui.controllers.can_connection_controller.QMessageBox.warning"):
            self.connect(tab)

        self.assertEqual(tab.lbl_status.text(), "Error")
        self.assertIn("Invalid Vector CAN channel", tab.lbl_status.toolTip())
        self.assertTrue(tab.btn_connect.isEnabled())
        self.assertFalse(tab.btn_disconnect.isEnabled())

    def test_disconnect_returns_to_disconnected_state(self):
        service = FakeCANService()
        tab = CANInterfaceTab(service=service)
        self.addCleanup(tab.deleteLater)

        self.refresh(tab)
        self.connect(tab)
        tab.disconnect_can()
        self.wait_for_connection(tab)

        self.assertFalse(service.connected)
        self.assertEqual(tab.lbl_status.text(), "Disconnected")
        self.assertTrue(tab.btn_connect.isEnabled())
        self.assertFalse(tab.btn_disconnect.isEnabled())

    def test_refresh_does_not_fake_hardware_enumeration(self):
        service = FakeCANService()
        tab = CANInterfaceTab(service=service)
        self.addCleanup(tab.deleteLater)

        self.refresh(tab)

        self.assertEqual(service.refresh_count, 1)
        self.assertEqual(tab.cmb_channel.count(), 2)
        self.assertEqual(tab.lbl_status.text(), "Disconnected")

    def test_no_hardware_clears_stale_selection_and_disables_connect(self):
        service = FakeCANService()
        tab = CANInterfaceTab(service)
        self.addCleanup(tab.deleteLater)
        self.refresh(tab)
        service.devices = ()
        self.refresh(tab)
        self.assertEqual(tab.cmb_device.count(), 0)
        self.assertEqual(tab.cmb_channel.count(), 0)
        self.assertTrue(tab.cmb_channel.isHidden() and tab.lbl_channel.isHidden())
        self.assertTrue(tab.btn_connect.isEnabled())
        self.assertIn("No Vector CAN device detected", tab.lbl_status.toolTip())

    def test_device_selection_and_refresh_preserve_correct_channel_identity(self):
        service = FakeCANService()
        first = service.devices[0]
        second = CANDeviceInfo("VN1630A", 123456, 57, 1, (CANChannelInfo(2, 20, "CAN 3", False, 2),))
        service.devices = (first, second)
        tab = CANInterfaceTab(service)
        self.addCleanup(tab.deleteLater)
        self.refresh(tab)
        self.assertNotEqual(tab.cmb_device.itemText(0), tab.cmb_device.itemText(1))
        tab.cmb_device.setCurrentIndex(1)
        self.assertEqual(tab.cmb_channel.count(), 1)
        self.assertEqual(tab.cmb_channel.currentData().channel_index, 20)
        service.devices = (second, first)
        self.refresh(tab)
        self.assertEqual(tab.cmb_device.currentData().identity, second.identity)
        self.assertEqual(tab.cmb_channel.currentData().channel_index, 20)
        self.connect(tab)
        self.assertEqual((service.config.channel, service.config.channel_index, service.config.serial), (2, 20, 123456))

    def test_no_channels_or_unmapped_channel_never_connects(self):
        service = FakeCANService()
        tab = CANInterfaceTab(service)
        self.addCleanup(tab.deleteLater)
        for channels in ((), (CANChannelInfo(0, None, "CAN 1", False),)):
            service.devices = (CANDeviceInfo("Vector Device", None, None, None, channels),)
            self.refresh(tab)
            tab.connect_can()  # Without a connectable channel Connect only runs discovery again.
            self.wait_for_refresh(tab)
            self.assertIsNone(service.config)

    def test_refresh_preserves_local_channel_and_uses_updated_global_index(self):
        service = FakeCANService()
        tab = CANInterfaceTab(service)
        self.addCleanup(tab.deleteLater)
        self.refresh(tab)
        tab.cmb_channel.setCurrentIndex(1)
        tab.cmb_baudrate.setCurrentIndex(0)
        service.devices = (CANDeviceInfo("VN1630A", 123456, 57, 0, (
            CANChannelInfo(1, 23, "CAN 2", False, 1), CANChannelInfo(0, 22, "CAN 1", True, 0),
        )),)
        self.refresh(tab)
        self.assertEqual(tab.cmb_channel.currentData().hw_channel, 1)
        self.assertEqual(tab.cmb_channel.currentData().channel_index, 23)
        self.assertEqual(tab.cmb_baudrate.currentData(), 125000)
        self.connect(tab)
        self.assertEqual((service.config.channel, service.config.channel_index), (1, 23))

    def test_removed_selected_device_does_not_keep_stale_channels(self):
        service = FakeCANService()
        first = service.devices[0]
        service.devices += (CANDeviceInfo("Vector Device", 200, 57, 1, (CANChannelInfo(0, 30, "CAN 1", False, 0),)),)
        tab = CANInterfaceTab(service)
        self.addCleanup(tab.deleteLater)
        self.refresh(tab)
        tab.cmb_device.setCurrentIndex(1)
        service.devices = (first,)
        self.refresh(tab)
        self.assertEqual(tab.cmb_device.currentData().serial, 123456)
        self.assertEqual(tab.cmb_channel.currentData().channel_index, 4)

    def test_driver_error_clears_old_choices_and_shows_distinct_message(self):
        service = FakeCANService()
        tab = CANInterfaceTab(service)
        self.addCleanup(tab.deleteLater)
        self.refresh(tab)
        service.discovery_error = VectorDriverUnavailableError("Vector XL Driver is unavailable.")
        with patch("gui.controllers.can_connection_controller.QMessageBox.warning") as warning:
            self.refresh(tab)
        warning.assert_called_once()
        self.assertEqual(tab.cmb_device.count(), 0)
        self.assertIn("Vector XL Driver", tab.lbl_status.toolTip())
        self.assertTrue(tab.cmb_channel.isHidden())

    def test_refresh_is_async_duplicate_guard_and_never_disconnects(self):
        service = FakeCANService()
        service.gate = Event()
        tab = CANInterfaceTab(service)
        self.addCleanup(tab.deleteLater)
        tab.refresh_can_setup()
        try:
            self.assertFalse(tab.btn_connect.isEnabled())
            tab.refresh_can_setup()
            alive = []
            QTimer.singleShot(0, lambda: alive.append(True))
            self.application.processEvents()
            self.assertEqual(alive, [True])
        finally:
            service.gate.set()
            self.wait_for_refresh(tab)
        self.assertEqual(service.refresh_count, 1)
        self.assertNotEqual(service.discovery_threads[0], self.application.thread())
        self.connect(tab)
        config = service.config
        tab.refresh_can_setup()
        self.assertEqual(service.refresh_count, 1)
        self.assertTrue(service.connected)
        self.assertIs(service.config, config)

    def test_theme_switch_and_discovery_completion_preserve_layout(self):
        tab = CANInterfaceTab(FakeCANService())
        self.addCleanup(tab.deleteLater)
        threads = []
        tab.cmb_device.currentIndexChanged.connect(lambda: threads.append(QThread.currentThread()))
        self.refresh(tab)
        self.assertTrue(all(thread == self.application.thread() for thread in threads))
        selection = tab.cmb_channel.currentData()
        self.addCleanup(ThemeManager.fn_set_theme, ThemeManager.fn_theme())
        for theme in (ThemeType.DARK, ThemeType.LIGHT):
            ThemeManager.fn_set_theme(theme)
            tab.fn_refresh_theme()
            self.assertEqual(tab.cmb_channel.currentData(), selection)
            self.assertIs(tab.action_layout.itemAt(0).widget(), tab.btn_connect)

    def test_closing_tab_ignores_late_results_without_destroying_active_thread(self):
        service = FakeCANService()
        service.gate = Event()
        tab = CANInterfaceTab(service)
        self.addCleanup(tab.deleteLater)
        tab.refresh_can_setup()
        tab.close()
        service.gate.set()
        self.wait_for_refresh(tab)
        self.assertEqual(tab.cmb_device.count(), 0)


if __name__ == "__main__":
    unittest.main()
