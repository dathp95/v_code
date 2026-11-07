from PySide6.QtCore import QObject, Signal, Slot
from pathlib import Path

from core.asc_reader import get_log_channel_id_counts, get_log_channels
from core.log_parsers.diagnostics import ParserDiagnostics


class LogChannelWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    diagnostics_ready = Signal(object)
    # {channel: {can_id: frames}} of a log with several channels (None otherwise): lets the tab pick the
    # diagnostic channel by itself once it knows the vehicle.
    channel_ids_ready = Signal(object)

    def __init__(
            self,
            log_file: str,
        ):
        super().__init__()
        self._log_file = log_file

    @Slot()
    def run(self):
        counts = None
        try:
            if Path(self._log_file).suffix.lower() == ".txt":
                diagnostics = ParserDiagnostics()
                channels = get_log_channels(self._log_file, diagnostics=diagnostics)
                self.diagnostics_ready.emit(diagnostics)
                if len(channels) > 1:
                    counts = self._txt_channel_id_counts()
            else:
                counts = get_log_channel_id_counts(self._log_file)
                channels = sorted(counts)
        except Exception as exc:
            self.failed.emit(str(exc))
            return

        self.channel_ids_ready.emit(counts if counts and len(counts) > 1 else None)
        self.finished.emit(channels)

    def _txt_channel_id_counts(self):
        try:
            return get_log_channel_id_counts(self._log_file)
        except Exception:
            return None  # Only the automatic choice is lost; the channels themselves were read fine.
