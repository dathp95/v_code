import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import can
from PySide6.QtWidgets import QApplication

from gui.tabs.log_analyzer_tab import LogAnalyzerTab
from gui.workers.log_channel_worker import LogChannelWorker
from models.ecu import ECU
from models.vehicle import Vehicle


def line(channel, can_id, data='03 22 F1 90 00 00 00 00', time=0.001):
    return f'{time} {channel} {can_id} Rx d 8 {data}\n'


def vehicle(name='V', request='682', response='602'):
    return Vehicle(name=name, ecus=[ECU(name='ECU', request_id=request, response_id=response)])


class AutoDiagnosticChannelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.tab = LogAnalyzerTab()
        self.info = patch('gui.tabs.log_analyzer_tab.QMessageBox.information').start()
        self.warning = patch('gui.tabs.log_analyzer_tab.QMessageBox.warning').start()
        self.addCleanup(patch.stopall)
        self.addCleanup(self.tab.deleteLater)

    # --- helpers ---------------------------------------------------------------------
    def wait_for(self, predicate):
        deadline = time.monotonic() + 8
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertTrue(predicate(), 'Qt background worker did not finish')

    def write(self, name='log.asc', *, diag_channel=3, extra_channels=(2, 4)):
        """Channels 2 and 4 carry body traffic, `diag_channel` carries the diagnostic request/response."""
        text = ''.join(line(channel, '123') * 50 for channel in extra_channels)
        text += line(diag_channel, '682') * 5 + line(diag_channel, '602', '03 62 F1 90 00 00 00 00') * 5
        path = self.root / name
        path.write_text(text, encoding='utf-8')
        return path

    def load(self, path):
        self.tab.log_selector.set_path(str(path))
        self.tab.fn_log_file_changed(str(path))
        self.wait_for(lambda: self.tab._log_channel_thread is None)

    def use_vehicle(self, vehicle_):
        self.tab._current_vehicle = vehicle_

    def selector(self):
        return self.tab.channel_selector

    def run_enabled(self):
        return self.tab.right_panel.action_panel.btn_run.isEnabled()

    # --- the automatic choice --------------------------------------------------------
    def test_with_a_vehicle_the_diagnostic_channel_is_chosen_without_asking(self):
        self.use_vehicle(vehicle())
        self.load(self.write())
        self.assertEqual(self.selector().fn_channel(), 3)
        self.assertEqual(self.selector().cmb_channel.currentText(), 'Channel 3 (auto)')
        self.assertTrue(self.selector().fn_is_auto_selected())
        self.assertIn('automatically', self.selector().cmb_channel.toolTip())
        self.assertEqual([self.selector().cmb_channel.itemText(i) for i in range(3)],
                         ['Channel 2', 'Channel 3 (auto)', 'Channel 4'])
        self.assertTrue(self.run_enabled())  # Nothing left for the user to pick.

    def test_the_channel_is_not_the_busiest_one_and_not_a_fixed_number(self):
        for diag in (2, 4):
            with self.subTest(diag=diag):
                self.use_vehicle(vehicle())
                self.load(self.write(f'log{diag}.asc', diag_channel=diag, extra_channels=tuple({2, 3, 4} - {diag})))
                self.assertEqual(self.selector().fn_channel(), diag)

    def test_loaded_message_mentions_the_detected_channel(self):
        self.use_vehicle(vehicle())
        self.load(self.write())
        message = self.info.call_args.args[2]
        self.assertIn('Detected 3 CAN channels', message)
        self.assertIn('Channel 3', message)
        self.assertIn('automatically', message)

    def test_vehicle_chosen_after_the_log_triggers_the_detection(self):
        self.load(self.write())
        self.assertIsNone(self.selector().fn_channel())  # No vehicle yet: nothing to compare with.
        self.assertFalse(self.run_enabled())
        with patch.object(self.tab.vehicle_service, 'load_vehicle', return_value=vehicle()):
            self.tab.fn_vehicle_changed('V')
        self.assertEqual(self.selector().fn_channel(), 3)
        self.assertTrue(self.selector().fn_is_auto_selected())

    def test_changing_vehicle_re_detects_while_the_user_has_not_chosen(self):
        self.use_vehicle(vehicle())
        path = self.write(extra_channels=())
        with path.open('a', encoding='utf-8') as log:
            log.write(line(2, '700') * 5 + line(2, '708') * 5)
            log.write(line(4, '123') * 5)
        self.load(path)
        self.assertEqual(self.selector().fn_channel(), 3)
        with patch.object(self.tab.vehicle_service, 'load_vehicle', return_value=vehicle('W', '700', '708')):
            self.tab.fn_vehicle_changed('W')
        self.assertEqual(self.selector().fn_channel(), 2)
        with patch.object(self.tab.vehicle_service, 'load_vehicle', return_value=vehicle('X', '111', '112')):
            self.tab.fn_vehicle_changed('X')  # Matches nothing: back to asking.
        self.assertIsNone(self.selector().fn_channel())
        self.assertFalse(self.selector().fn_is_auto_selected())
        self.assertFalse(self.run_enabled())

    def test_a_channel_picked_by_the_user_is_never_overridden(self):
        self.use_vehicle(vehicle())
        self.load(self.write())
        index = self.selector().cmb_channel.findData(4)
        self.selector().cmb_channel.setCurrentIndex(index)
        self.selector().cmb_channel.activated.emit(index)  # What a click on the list item does.
        self.assertEqual(self.selector().fn_channel(), 4)
        self.assertFalse(self.selector().fn_is_auto_selected())
        with patch.object(self.tab.vehicle_service, 'load_vehicle', return_value=vehicle()):
            self.tab.fn_vehicle_changed('V')
        self.assertEqual(self.selector().fn_channel(), 4)

    def test_opening_another_log_starts_fresh(self):
        self.use_vehicle(vehicle())
        self.load(self.write())
        index = self.selector().cmb_channel.findData(2)
        self.selector().cmb_channel.setCurrentIndex(index)
        self.selector().cmb_channel.activated.emit(index)
        self.load(self.write('second.asc', diag_channel=4, extra_channels=(2, 3)))
        self.assertEqual(self.selector().fn_channel(), 4)  # Manual choice of the previous log does not carry over.
        self.assertTrue(self.selector().fn_is_auto_selected())

    # --- when it cannot decide -------------------------------------------------------
    def test_no_channel_with_vehicle_ids_leaves_the_choice_to_the_user(self):
        self.use_vehicle(vehicle('Other', '111', '112'))
        self.load(self.write())
        self.assertIsNone(self.selector().fn_channel())
        self.assertEqual(self.selector().cmb_channel.currentIndex(), -1)
        self.assertTrue(self.selector().cmb_channel.isEnabled())  # Still pickable by hand.
        self.assertFalse(self.run_enabled())
        self.assertNotIn('automatically', self.info.call_args.args[2])

    def test_identical_diagnostic_traffic_on_two_channels_is_not_guessed(self):
        self.use_vehicle(vehicle())
        path = self.root / 'mirror.asc'
        path.write_text(line(2, '682') * 5 + line(2, '602') * 5 + line(3, '682') * 5 + line(3, '602') * 5
                        + line(4, '123') * 9, encoding='utf-8')
        self.load(path)
        self.assertIsNone(self.selector().fn_channel())

    def test_single_channel_log_is_unchanged(self):
        self.use_vehicle(vehicle())
        path = self.root / 'one.asc'
        path.write_text(line(2, '682') * 3, encoding='utf-8')
        self.load(path)
        self.assertEqual(self.selector().fn_channel(), 2)
        self.assertEqual(self.selector().cmb_channel.currentText(), 'Channel 2')  # Not "(auto)": nothing was detected.
        self.assertFalse(self.selector().cmb_channel.isEnabled())

    def test_vehicle_without_ecu_ids_is_harmless(self):
        self.use_vehicle(Vehicle(name='Empty', ecus=[]))
        self.load(self.write())
        self.assertIsNone(self.selector().fn_channel())
        self.use_vehicle(object())
        self.assertFalse(self.tab._auto_select_diagnostic_channel())

    # --- other formats and the worker ------------------------------------------------
    def test_blf_log_with_several_channels(self):
        self.use_vehicle(vehicle())
        path = self.root / 'log.blf'
        with can.BLFWriter(path) as writer:
            stamp = 1000
            for channel, can_id, count in ((1, 0x123, 40), (2, 0x682, 5), (2, 0x602, 5), (3, 0x7FF, 3)):
                for _ in range(count):
                    stamp += 0.001
                    writer.on_message_received(can.Message(timestamp=stamp, arbitration_id=can_id, channel=channel,
                                                           is_extended_id=False, data=bytes(8)))
        self.load(path)
        self.assertEqual(self.selector().fn_channel(), 3)  # Raw BLF channel 2 is logical channel 3.
        self.assertTrue(self.selector().fn_is_auto_selected())

    def test_worker_reports_channel_id_counts_only_for_multi_channel_logs(self):
        multi = self.write()
        single = self.root / 'one.asc'
        single.write_text(line(2, '682') * 3, encoding='utf-8')
        for path, expected_ids in ((multi, True), (single, False)):
            with self.subTest(path=path.name):
                worker = LogChannelWorker(str(path))
                counts, channels = [], []
                worker.channel_ids_ready.connect(counts.append)
                worker.finished.connect(channels.append)
                worker.run()
                self.assertEqual(len(counts), 1)
                self.assertEqual(counts[0] is not None, expected_ids)
                self.assertEqual(channels[0], [2, 3, 4] if expected_ids else [2])

    def test_unreadable_log_still_fails_with_a_message(self):
        path = self.root / 'bad.blf'
        path.write_bytes(b'not a BLF file')
        worker = LogChannelWorker(str(path))
        failures, ids = [], []
        worker.failed.connect(failures.append)
        worker.channel_ids_ready.connect(ids.append)
        worker.run()
        self.assertEqual(len(failures), 1)
        self.assertEqual(ids, [])


if __name__ == '__main__':
    unittest.main()
