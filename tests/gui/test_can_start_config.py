import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from gui.tabs.can_interface_tab import CANInterfaceTab
from gui.workers.can_connection_worker import CANConnectionTask
from repositories.load_config_start_store import LoadConfigStartStore
from services.can import CANChannelInfo, CANDeviceInfo
from tests.gui.test_can_interface_tab import FakeCANService


class CanStartConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        for task in self.app.findChildren(CANConnectionTask):
            task.shutdown()
        self.app.processEvents()

    def store(self):
        directory = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(directory.cleanup)
        return LoadConfigStartStore(Path(directory.name) / 'load_config_start.json')

    def wait(self, running):
        deadline = time.monotonic() + 8
        while running() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.001)
        self.assertFalse(running())
        self.app.processEvents()

    def tab(self, service, store):
        tab = CANInterfaceTab(service=service, start_store=store)
        self.addCleanup(tab.deleteLater)
        return tab

    def discover(self, tab):
        tab.refresh_can_setup()
        self.wait(lambda: tab._discovery_task.running)

    def connect(self, tab):
        tab.connect_can()
        self.wait(lambda: tab._connection_task.running)

    def test_nothing_is_saved_until_a_connection_succeeds(self):
        store = self.store()
        tab = self.tab(FakeCANService(), store)
        self.discover(tab)
        tab.cmb_channel.setCurrentIndex(1)
        self.assertFalse(store.path.exists())  # Picking a channel is not enough.

    def test_successful_connect_saves_the_channel_and_the_next_start_selects_it(self):
        store = self.store()
        first = self.tab(FakeCANService(), store)
        self.discover(first)
        first.cmb_channel.setCurrentIndex(1)  # CAN 2
        self.connect(first)
        saved = store.get_tab('can_interface')
        self.assertEqual((saved['channel'], saved['channel_name']), (1, 'CAN 2'))
        # A fresh start (new tab, same file): after discovery the saved channel is selected again.
        second = self.tab(FakeCANService(), store)
        self.assertEqual(second.cmb_channel.count(), 0)
        self.discover(second)
        self.assertEqual(second.cmb_channel.currentData().channel, 1)
        self.assertEqual(second.cmb_channel.currentText(), 'CAN 2')

    def test_failed_connect_saves_nothing(self):
        store = self.store()
        service = FakeCANService()
        service.connect_error = RuntimeError('adapter busy')
        tab = self.tab(service, store)
        self.discover(tab)
        tab.cmb_channel.setCurrentIndex(1)
        with patch('gui.controllers.can_connection_controller.QMessageBox.warning'), \
                patch('gui.controllers.can_connection_controller.QMessageBox.critical'):
            self.connect(tab)
        self.assertFalse(store.path.exists())

    def test_a_later_connect_updates_the_remembered_channel(self):
        store = self.store()
        tab = self.tab(FakeCANService(), store)
        self.discover(tab)
        self.connect(tab)  # CAN 1
        self.assertEqual(store.get_tab('can_interface')['channel'], 0)
        tab.disconnect_can()
        self.wait(lambda: tab._connection_task.running)
        tab.cmb_channel.setCurrentIndex(1)
        self.connect(tab)
        self.assertEqual(store.get_tab('can_interface')['channel'], 1)

    def test_saved_channel_of_another_device_or_a_missing_channel_falls_back_to_the_first(self):
        store = self.store()
        store.set_tab_values('can_interface', device=['hardware', 999, 1, 7], channel=5, channel_name='CAN 6')
        tab = self.tab(FakeCANService(), store)
        self.discover(tab)
        self.assertEqual(tab.cmb_channel.currentIndex(), 0)
        store.set_tab_values('can_interface', device=None, channel=7)
        other = self.tab(FakeCANService(), store)
        self.discover(other)
        self.assertEqual(other.cmb_channel.currentIndex(), 0)

    def test_saved_channel_is_picked_on_the_right_device_when_two_adapters_are_present(self):
        service = FakeCANService()
        first = service.devices[0]
        second = CANDeviceInfo('VN1630A', 123456, 57, 1, (CANChannelInfo(0, 20, 'CAN 1', False, 0),
                                                          CANChannelInfo(1, 21, 'CAN 2', False, 1)))
        service.devices = (first, second)
        store = self.store()
        tab = self.tab(service, store)
        self.discover(tab)
        tab.cmb_device.setCurrentIndex(1)
        tab.cmb_channel.setCurrentIndex(1)
        self.connect(tab)
        restarted_service = FakeCANService()
        restarted_service.devices = (first, second)
        restarted = self.tab(restarted_service, store)
        self.discover(restarted)
        self.assertEqual(restarted.cmb_device.currentData().identity, second.identity)
        self.assertEqual(restarted.cmb_channel.currentData().channel_index, 21)

    def test_corrupt_start_file_does_not_stop_the_tab(self):
        store = self.store()
        store.path.write_text('{bad', encoding='utf-8')
        tab = self.tab(FakeCANService(), store)
        self.discover(tab)
        self.assertEqual(tab.cmb_channel.currentIndex(), 0)

    def test_unwritable_start_file_does_not_break_the_connection(self):
        store = self.store()
        tab = self.tab(FakeCANService(), store)
        self.discover(tab)
        with patch('repositories.load_config_start_store.os.replace', side_effect=OSError('read only')):
            self.connect(tab)
        self.assertEqual(tab.lbl_status.text(), 'Connected')


if __name__ == '__main__':
    unittest.main()
