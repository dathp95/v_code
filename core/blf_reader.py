"""Direct BLF input; no conversion, temporary files, or writes to the source.

Timestamp/channel compatibility follows python-can 4.6.1 ASCWriter:
https://python-can.readthedocs.io/en/v4.6.1/_modules/can/io/asc.html
"""

import logging
import os
import struct
import zlib
from pathlib import Path

import can
from can.io.blf import BLFParseError, FILE_HEADER_STRUCT


LOGGER = logging.getLogger(__name__)


def _fn_raw_blf_channel_to_logical_channel(value):
    if value is None:
        return None
    try:
        channel = int(value) + 1
    except (TypeError, ValueError):
        return None
    return channel if channel > 0 else None


def _iter_blf_messages(blf_file):
    path = Path(blf_file)
    try:
        # Own the handle even if BLFReader construction fails on a bad header.
        with path.open("rb") as source:
            actual_size = os.fstat(source.fileno()).st_size
            header = FILE_HEADER_STRUCT.unpack(source.read(FILE_HEADER_STRUCT.size))
            if (header[0] != b"LOGG" or not FILE_HEADER_STRUCT.size <= header[1] <= actual_size
                    or header[10] > actual_size):
                raise ValueError("Invalid header or incomplete file.")
            source.seek(0)
            with can.BLFReader(source) as reader:
                yield from reader
                # 4.6.1 buffers partial objects across containers but silently
                # ignores a leftover object at EOF. Only zero padding is valid.
                if reader._tail.rstrip(b"\x00"):
                    raise ValueError("Incomplete final BLF object.")
    except OSError as error:
        raise OSError(error.errno, f"Unable to read BLF log: {error.strerror}", str(path)) from error
    except (BLFParseError, struct.error, zlib.error, ValueError) as error:
        raise ValueError(f"Invalid or truncated BLF log: {error}") from error


def get_blf_channel_id_counts(blf_file):
    """{logical channel: {CAN ID: classic data frames}}; a channel with no usable frame maps to {}."""
    counts = {}
    for message in _iter_blf_messages(blf_file):
        channel = _fn_raw_blf_channel_to_logical_channel(message.channel)
        if channel is None:
            continue
        ids = counts.setdefault(channel, {})
        if message.is_fd or message.is_remote_frame or message.is_error_frame:
            continue
        ids[message.arbitration_id] = ids.get(message.arbitration_id, 0) + 1
    return counts


def get_blf_channels(blf_file):
    channels = set()
    for message in _iter_blf_messages(blf_file):
        channel = _fn_raw_blf_channel_to_logical_channel(message.channel)
        if channel is not None:
            channels.add(channel)
    return sorted(channels)


def load_blf(blf_file, channel=None):
    """Return classic CAN data frames in the load_asc message schema.

    Like the legacy ASC conversion, timestamps are relative to the first BLF
    message (before channel/type filtering) and rounded to microseconds.
    Selected normalized messages are retained; raw BLF bytes are not buffered.
    """
    messages = []
    origin = None
    skipped = 0
    for message in _iter_blf_messages(blf_file):
        if origin is None:
            origin = message.timestamp or 0.0
        logical_channel = _fn_raw_blf_channel_to_logical_channel(message.channel)
        if channel is not None and logical_channel != channel:
            continue
        if (message.is_fd or message.is_remote_frame or message.is_error_frame
                or logical_channel is None or not 0 <= message.dlc <= 8
                or len(message.data) != message.dlc):
            skipped += 1
            continue
        timestamp = message.timestamp
        if timestamp >= origin:
            timestamp -= origin
        messages.append({
            "timestamp": float(f"{timestamp:.6f}"),
            "channel": logical_channel,
            "can_id": message.arbitration_id,
            "dlc": message.dlc,
            "data": list(message.data),
        })
    if skipped:
        LOGGER.warning("BLF reader skipped %d unsupported/invalid frames (FD, RTR, error or invalid data/channel).", skipped)
    if channel is not None and not messages:
        raise ValueError("Selected Diagnostic Channel was not found in the log or has no supported classic CAN data frames.")
    return messages
