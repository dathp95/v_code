"""Display preferences only. Sequence definitions and ECU data are never stored here."""
import json
import os
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path

from config.paths import CONFIG_DIR


@dataclass(frozen=True)
class CanInterfaceUiState:
    order: tuple[str, ...] = ()
    selected_id: str = ""
    vehicles: dict[str, str] = field(default_factory=dict)
    sources: tuple[str, ...] = ()
    # Settings strip (Loop / Delay used by Import), remembered between runs. The ECU box follows the cursor row.
    import_settings: dict = field(default_factory=dict)


def _valid_import_settings(value):
    """Keep only well-formed entries; anything else silently falls back to the defaults."""
    if not isinstance(value, dict):
        return {}
    cleaned = {}
    loop, delay_ms = value.get("loop"), value.get("delay_ms")
    if type(loop) is int and 1 <= loop <= 9999:
        cleaned["loop"] = loop
    if type(delay_ms) is int and 0 <= delay_ms <= 60000:
        cleaned["delay_ms"] = delay_ms
    return cleaned


class CanInterfaceUiStore:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else CONFIG_DIR / "can_interface_ui.json"

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("version") != 1:
                return CanInterfaceUiState()
            order, selected, vehicles = data.get("order", []), data.get("selected_id", ""), data.get("vehicles", {})
            sources = data.get("sources", [])
            if (not isinstance(order, list) or any(not isinstance(x, str) for x in order)
                    or not isinstance(sources, list) or any(not isinstance(x, str) for x in sources)
                    or not isinstance(selected, str) or not isinstance(vehicles, dict)
                    or any(not isinstance(k, str) or not isinstance(v, str) for k, v in vehicles.items())):
                return CanInterfaceUiState()
            return CanInterfaceUiState(tuple(dict.fromkeys(order)), selected, vehicles, tuple(dict.fromkeys(sources)),
                                       _valid_import_settings(data.get("import_settings")))
        except (OSError, UnicodeError, ValueError):
            return CanInterfaceUiState()

    def _save(self, state):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=self.path.name, suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(dict(version=1, order=state.order, selected_id=state.selected_id, vehicles=state.vehicles, sources=state.sources,
                               import_settings=state.import_settings),
                          stream, indent=4, ensure_ascii=False)
                stream.write("\n")
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def save_order(self, ids):
        self._save(replace(self.load(), order=tuple(ids)))

    def save_selection(self, source_id):
        # Load the SAVED order; never persist a pending visual reorder here.
        state = self.load()
        sources = tuple(dict.fromkeys((*state.sources, source_id))) if source_id else state.sources
        self._save(replace(state, selected_id=source_id, sources=sources))

    def save_import_settings(self, loop, delay_ms):
        self._save(replace(self.load(), import_settings=_valid_import_settings(dict(loop=loop, delay_ms=delay_ms))))

    def save_vehicle(self, source_id, vehicle_name):
        state = self.load()
        vehicles = dict(state.vehicles)
        vehicles[source_id] = vehicle_name
        self._save(replace(state, vehicles=vehicles))
