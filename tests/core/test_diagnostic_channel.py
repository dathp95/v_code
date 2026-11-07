import tempfile
import unittest
from pathlib import Path

import can

from core.asc_reader import get_log_channel_id_counts, get_log_channels
from core.diagnostic_channel import detect_diagnostic_channel, diagnostic_frame_counts
from models.ecu import ECU
from models.vehicle import Vehicle


def asc_line(channel, can_id, time=0.001, data="03 22 F1 90 00 00 00 00"):
    return f"{time} {channel} {can_id} Rx d 8 {data}\n"


def vehicle(*pairs):
    return Vehicle(name="V", ecus=[ECU(name=f"ECU{i}", request_id=req, response_id=resp)
                                   for i, (req, resp) in enumerate(pairs)])


class ChannelIdCountsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_asc_counts_frames_per_channel_and_can_id(self):
        path = self.root / "log.asc"
        path.write_text(asc_line(2, "123") * 3 + asc_line(3, "681") * 2 + asc_line(3, "601") + asc_line(4, "7FF"),
                        encoding="utf-8")
        counts = get_log_channel_id_counts(path)
        self.assertEqual(counts, {2: {0x123: 3}, 3: {0x681: 2, 0x601: 1}, 4: {0x7FF: 1}})
        self.assertEqual(sorted(counts), get_log_channels(path))

    def test_blf_counts_use_the_same_logical_channels_as_get_log_channels(self):
        path = self.root / "log.blf"
        with can.BLFWriter(path) as writer:
            for index, (channel, can_id) in enumerate([(0, 0x123), (1, 0x681), (1, 0x601), (1, 0x681), (2, 0x7FF)]):
                writer.on_message_received(can.Message(timestamp=1000 + index, arbitration_id=can_id, channel=channel,
                                                       is_extended_id=False, data=bytes(8)))
        counts = get_log_channel_id_counts(path)
        self.assertEqual(counts, {1: {0x123: 1}, 2: {0x681: 2, 0x601: 1}, 3: {0x7FF: 1}})
        self.assertEqual(sorted(counts), get_log_channels(path))

    def test_a_channel_with_only_unusable_frames_is_still_listed(self):
        path = self.root / "log.blf"
        with can.BLFWriter(path) as writer:
            writer.on_message_received(can.Message(timestamp=1000, arbitration_id=0x123, channel=0,
                                                   is_extended_id=False, data=bytes(8)))
            writer.on_message_received(can.Message(timestamp=1001, arbitration_id=0x124, channel=1,
                                                   is_extended_id=False, is_remote_frame=True, dlc=8))
        counts = get_log_channel_id_counts(path)
        self.assertEqual(sorted(counts), get_log_channels(path))
        self.assertEqual(counts[2], {})

    def test_unsupported_format_is_rejected(self):
        with self.assertRaises(ValueError):
            get_log_channel_id_counts(self.root / "log.xyz")


class DetectDiagnosticChannelTests(unittest.TestCase):
    COUNTS = {
        2: {0x123: 5000, 0x3AB: 900},                 # Body traffic, no diagnostics.
        3: {0x682: 40, 0x602: 38, 0x123: 10},         # Request / response of ECU 682 / 602.
        4: {0x7FF: 3},
    }

    def test_picks_the_channel_carrying_the_vehicle_diagnostic_ids_not_the_busiest_one(self):
        self.assertEqual(detect_diagnostic_channel(self.COUNTS, vehicle(("682", "602"))), 3)

    def test_ids_may_be_written_with_prefix_or_any_case(self):
        self.assertEqual(detect_diagnostic_channel(self.COUNTS, vehicle(("0x682", "0X602"))), 3)

    def test_any_ecu_of_the_vehicle_counts(self):
        self.assertEqual(detect_diagnostic_channel(self.COUNTS, vehicle(("111", "112"), ("682", "602"))), 3)
        self.assertEqual(diagnostic_frame_counts(self.COUNTS, vehicle(("682", "602"))), {2: 0, 3: 78, 4: 0})

    def test_no_match_gives_none(self):
        self.assertIsNone(detect_diagnostic_channel(self.COUNTS, vehicle(("111", "112"))))

    def test_a_tie_is_not_guessed(self):
        counts = {2: {0x682: 10, 0x602: 10}, 3: {0x682: 10, 0x602: 10}}
        self.assertIsNone(detect_diagnostic_channel(counts, vehicle(("682", "602"))))

    def test_clear_winner_over_a_little_mirrored_traffic(self):
        counts = {2: {0x682: 2}, 3: {0x682: 40, 0x602: 38}}
        self.assertEqual(detect_diagnostic_channel(counts, vehicle(("682", "602"))), 3)

    def test_missing_or_unusable_inputs_give_none(self):
        self.assertIsNone(detect_diagnostic_channel(None, vehicle(("682", "602"))))
        self.assertIsNone(detect_diagnostic_channel({}, vehicle(("682", "602"))))
        self.assertIsNone(detect_diagnostic_channel(self.COUNTS, None))
        self.assertIsNone(detect_diagnostic_channel(self.COUNTS, object()))
        self.assertIsNone(detect_diagnostic_channel(self.COUNTS, vehicle(("", ""), ("zz", "yy"))))
        self.assertIsNone(detect_diagnostic_channel(self.COUNTS, Vehicle(name="Empty", ecus=[])))


if __name__ == "__main__":
    unittest.main()
