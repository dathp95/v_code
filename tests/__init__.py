"""Test package. Keeps tests away from the user's real start-up preferences."""
import tempfile
from pathlib import Path

from repositories import load_config_start_store

# Tabs created without an explicit store would otherwise write config/load_config_start.json during tests.
load_config_start_store.LOAD_CONFIG_START_FILE = Path(tempfile.gettempdir()) / "vcode_tests_load_config_start.json"
