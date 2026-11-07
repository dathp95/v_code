import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import asc_reader
from core.asc_reader import load_asc, parse_asc_line

GOOD = "{t} {ch} {cid} Rx d 8 03 22 F1 90 00 00 00 00\n"
LINES = [
    "date Sat Nov 7 10:00:00 2026\n",                      # Header line.
    "base hex  timestamps absolute\n",
    GOOD.format(t="0.001", ch=2, cid="123"),
    GOOD.format(t="0.002", ch=3, cid="681"),
    "0.003 3 601 Rx d 8 06 62 F1 90 4D 47 55 00\n",
    "0.004 3 601 Rx d 8 ZZ 62 F1 90 4D 47 55 00\n",         # Bad hex on the diagnostic channel: skipped.
    "0.005 2 123 Rx d 8 ZZ 22 33 44 55 66 77 88\n",         # Bad hex on another channel: skipped either way.
    "0.006 x 681 Rx d 8 03 22 F1 90 00 00 00 00\n",         # Channel is not a number: skipped.
    "0.007 3 681 Rx d 8 03 22\n",                           # Too short: skipped.
    "0.008 3 GGG Rx d 8 03 22 F1 90 00 00 00 00\n",         # Bad CAN ID: skipped.
    "0.009 4 7FF Tx d 8 11 22 33 44 55 66 77 88\n",
    "0.010 3 681 Rx d 4 02 10 03 00 FF FF FF FF\n",         # DLC 4: only four data bytes are read.
    "\n",
]


class LoadAscChannelFilterTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "log.asc"
        self.path.write_text("".join(LINES), encoding="utf-8")

    def test_selected_channel_returns_exactly_the_valid_lines_of_that_channel(self):
        messages = load_asc(self.path, channel=3)
        self.assertEqual([m["timestamp"] for m in messages], [0.002, 0.003, 0.010])
        self.assertTrue(all(m["channel"] == 3 for m in messages))
        self.assertEqual(messages[2]["data"], [0x02, 0x10, 0x03, 0x00])

    def test_result_equals_filtering_the_whole_log(self):
        everything = load_asc(self.path)
        for channel in (2, 3, 4):
            with self.subTest(channel=channel):
                self.assertEqual(load_asc(self.path, channel=channel),
                                 [m for m in everything if m["channel"] == channel])

    def test_messages_are_the_same_as_parse_asc_line_gives(self):
        expected = [m for m in (parse_asc_line(line) for line in LINES) if m is not None]
        self.assertEqual(load_asc(self.path), expected)

    def test_lines_of_other_channels_are_not_fully_parsed(self):
        built = []
        original = asc_reader._message_from_parts

        def counting(parts):
            built.append(parts[1])
            return original(parts)

        with patch.object(asc_reader, "_message_from_parts", side_effect=counting):
            load_asc(self.path, channel=3)
        self.assertEqual(set(built), {"3"})  # Only channel 3 lines went through the expensive part.

    def test_channel_with_only_unusable_lines_is_reported_as_missing(self):
        path = self.path.with_name("only_bad.asc")
        path.write_text("0.001 5 681 Rx d 8 ZZ 22 F1 90 00 00 00 00\n0.002 2 123 Rx d 8 11 22 33 44 55 66 77 88\n",
                        encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Selected Diagnostic Channel"):
            load_asc(path, channel=5)
        self.assertEqual(len(load_asc(path, channel=2)), 1)

    def test_channel_not_in_the_log_is_reported_as_missing(self):
        with self.assertRaisesRegex(ValueError, "Selected Diagnostic Channel"):
            load_asc(self.path, channel=9)

    def test_short_or_empty_lines_still_parse_to_none(self):
        self.assertIsNone(parse_asc_line(""))
        self.assertIsNone(parse_asc_line("0.001 3 681 Rx d 8 03 22"))
        self.assertEqual(parse_asc_line(GOOD.format(t="0.5", ch=3, cid="681"))["can_id"], 0x681)


if __name__ == "__main__":
    unittest.main()
