"""Test package. Keeps tests away from the user's real start-up preferences."""
import tempfile
import unittest
from pathlib import Path

from repositories import load_config_start_store

# Tabs created without an explicit store would otherwise write config/load_config_start.json during tests.
# They use a scratch file that every test starts without, so no test inherits another one's remembered values.
_SCRATCH = Path(tempfile.gettempdir()) / "vcode_tests_load_config_start.json"
load_config_start_store.LOAD_CONFIG_START_FILE = _SCRATCH
_original_run = unittest.TestCase.run


def _run_with_clean_start_config(self, *args, **kwargs):
    _SCRATCH.unlink(missing_ok=True)
    return _original_run(self, *args, **kwargs)


unittest.TestCase.run = _run_with_clean_start_config
