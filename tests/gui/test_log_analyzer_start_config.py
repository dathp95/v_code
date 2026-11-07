import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication

from gui.tabs.log_analyzer_tab import LogAnalyzerTab
from repositories.load_config_start_store import LoadConfigStartStore


class FakeVehicleService:
    """Stands in for the vehicles stored in config/vehicles."""
    names = ['VF3', 'VF5NP', 'VF6', 'VF7']

    def list_vehicles(self):
        return list(self.names)

    def load_vehicle(self, name):
        if name not in self.names:
            raise FileNotFoundError(name)
        return SimpleNamespace(name=name, ecus=[])


class LogAnalyzerStartConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        FakeVehicleService.names = ['VF3', 'VF5NP', 'VF6', 'VF7']
        patcher = patch('gui.tabs.log_analyzer_tab.VehicleService', FakeVehicleService)
        patcher.start()
        self.addCleanup(patcher.stop)

    def store(self):
        directory = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(directory.cleanup)
        return LoadConfigStartStore(Path(directory.name) / 'load_config_start.json')

    def tab(self, store):
        tab = LogAnalyzerTab(start_store=store)
        self.addCleanup(tab.deleteLater)
        return tab

    def pick(self, tab, name):
        tab.vehicle_selector.cmb_vehicle.setCurrentIndex(tab.vehicle_selector.cmb_vehicle.findText(name))

    def saved(self, store):
        return store.get_tab('log_analyzer').get('vehicle')

    def test_first_run_has_no_vehicle_and_writes_nothing(self):
        store = self.store()
        tab = self.tab(store)
        self.assertEqual(tab.vehicle_selector.fn_vehicle(), '')
        self.assertIsNone(tab._current_vehicle)
        self.assertFalse(store.path.exists())

    def test_choosing_a_vehicle_saves_it_and_the_next_start_selects_and_loads_it(self):
        store = self.store()
        first = self.tab(store)
        self.pick(first, 'VF6')
        self.assertEqual(self.saved(store), 'VF6')
        second = self.tab(store)  # The app is opened again.
        self.assertEqual(second.vehicle_selector.fn_vehicle(), 'VF6')
        self.assertEqual(second._current_vehicle.name, 'VF6')  # Loaded, not just shown.

    def test_the_latest_choice_wins_across_several_runs(self):
        store = self.store()
        tab = self.tab(store)
        for name in ('VF7', 'VF3', 'VF5NP'):
            self.pick(tab, name)
        self.assertEqual(self.saved(store), 'VF5NP')
        self.assertEqual(self.tab(store).vehicle_selector.fn_vehicle(), 'VF5NP')

    def test_a_vehicle_that_no_longer_exists_falls_back_to_no_selection(self):
        store = self.store()
        self.pick(self.tab(store), 'VF7')
        FakeVehicleService.names = ['VF3', 'VF5NP']  # VF7 was deleted in Vehicle Manager.
        tab = self.tab(store)
        self.assertEqual(tab.vehicle_selector.fn_vehicle(), '')
        self.assertIsNone(tab._current_vehicle)
        self.assertEqual(self.saved(store), 'VF7')  # Not forgotten: it may come back (e.g. re-imported).
        FakeVehicleService.names = ['VF3', 'VF5NP', 'VF7']
        self.assertEqual(self.tab(store).vehicle_selector.fn_vehicle(), 'VF7')

    def test_no_vehicles_at_all_starts_empty(self):
        store = self.store()
        store.set_tab_values('log_analyzer', vehicle='VF6')
        FakeVehicleService.names = []
        tab = self.tab(store)
        self.assertEqual(tab.vehicle_selector.fn_vehicle(), '')
        self.assertIsNone(tab._current_vehicle)

    def test_refreshing_the_list_keeps_the_selection_and_does_not_rewrite_the_file(self):
        store = self.store()
        tab = self.tab(store)
        self.pick(tab, 'VF5NP')
        before = store.path.read_bytes()
        with patch.object(LoadConfigStartStore, 'set_tab_values') as write:
            tab.fn_refresh_vehicles()
            write.assert_not_called()
        self.assertEqual(tab.vehicle_selector.fn_vehicle(), 'VF5NP')
        self.assertEqual(store.path.read_bytes(), before)

    def test_renamed_vehicle_is_remembered_under_its_new_name(self):
        store = self.store()
        tab = self.tab(store)
        self.pick(tab, 'VF6')
        FakeVehicleService.names = ['VF3', 'VF5NP', 'VF6-NEW', 'VF7']
        tab.fn_refresh_vehicles('VF6-NEW')  # What Vehicle Manager does after a rename.
        self.assertEqual(self.saved(store), 'VF6-NEW')

    def test_other_start_values_of_the_tab_and_other_tabs_are_kept(self):
        store = self.store()
        store.set_tab_values('can_interface', channel=1)
        store.set_tab_values('log_analyzer', something_else=True)
        self.pick(self.tab(store), 'VF3')
        self.assertEqual(store.get_tab('can_interface'), {'channel': 1})
        self.assertEqual(store.get_tab('log_analyzer'), {'something_else': True, 'vehicle': 'VF3'})

    def test_corrupt_wrong_type_or_unwritable_start_file_never_breaks_the_tab(self):
        store = self.store()
        store.path.write_text('{bad', encoding='utf-8')
        self.assertEqual(self.tab(store).vehicle_selector.fn_vehicle(), '')
        store.path.write_text('{"version": 1, "tabs": {"log_analyzer": {"vehicle": 5}}}', encoding='utf-8')
        self.assertEqual(self.tab(store).vehicle_selector.fn_vehicle(), '')
        tab = self.tab(self.store())
        with patch('repositories.load_config_start_store.os.replace', side_effect=OSError('read only')):
            self.pick(tab, 'VF3')
        self.assertEqual(tab._current_vehicle.name, 'VF3')  # The selection still works.

    def test_restored_vehicle_enables_analysis_like_a_manual_choice(self):
        store = self.store()
        self.pick(self.tab(store), 'VF5NP')
        tab = self.tab(store)
        self.assertEqual(tab._current_vehicle.name, 'VF5NP')
        with patch.object(tab, '_update_analyze_state') as update:
            tab.fn_vehicle_changed('VF3')
            update.assert_called()


if __name__ == '__main__':
    unittest.main()
