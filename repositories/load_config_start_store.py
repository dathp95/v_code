"""Values each tab restores when the app starts (config/load_config_start.json).

One small JSON file shared by every tab:

    {"version": 1, "tabs": {"can_interface": {"channel": 1, ...}, "<another tab>": {...}}}

A tab asks for its own section with get_tab() and updates a few keys with set_tab_values(); the other keys
and the other tabs are left alone. A missing, damaged or foreign file simply reads as "nothing saved".
Sequence data, vehicles and other real content never belong here, only start-up preferences.
"""
import copy
import json
import os
import tempfile
from pathlib import Path

from config.paths import LOAD_CONFIG_START_FILE

VERSION = 1


class LoadConfigStartStore:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else LOAD_CONFIG_START_FILE

    def _read(self):
        """All tabs' sections; {} when the file is missing, unreadable or not in the expected shape."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            return {}
        if not isinstance(data, dict) or data.get("version") != VERSION or not isinstance(data.get("tabs"), dict):
            return {}
        return {name: values for name, values in data["tabs"].items()
                if isinstance(name, str) and isinstance(values, dict)}

    def get_tab(self, tab):
        """A copy of the saved values of one tab ({} when it has none)."""
        return copy.deepcopy(self._read().get(tab, {}))

    def set_tab_values(self, tab, **values):
        """Merge values into one tab's section and write the file atomically (JSON-serializable values only)."""
        tabs = self._read()
        tabs[tab] = {**tabs.get(tab, {}), **values}
        text = json.dumps(dict(version=VERSION, tabs=tabs), indent=4, ensure_ascii=False) + "\n"  # TypeError first.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=self.path.name, suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(text)
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
