import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repositories.load_config_start_store import LoadConfigStartStore


class LoadConfigStartStoreTests(unittest.TestCase):
    def make(self):
        directory = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(directory.cleanup)
        return LoadConfigStartStore(Path(directory.name) / 'load_config_start.json')

    def test_default_file_lives_in_config_and_is_not_created_until_something_is_saved(self):
        from config.paths import LOAD_CONFIG_START_FILE
        self.assertEqual((LOAD_CONFIG_START_FILE.parent.name, LOAD_CONFIG_START_FILE.name),
                         ('config', 'load_config_start.json'))
        self.assertEqual(LoadConfigStartStore().path.name, 'vcode_tests_load_config_start.json')  # Redirected by tests/__init__.
        store = self.make()
        self.assertEqual(store.get_tab('can_interface'), {})
        self.assertFalse(store.path.exists())

    def test_values_are_saved_per_tab_and_merged(self):
        store = self.make()
        store.set_tab_values('can_interface', channel=1, device=['hardware', 5, 57, 0])
        store.set_tab_values('can_interface', channel=2)  # Updates one key, keeps the others.
        store.set_tab_values('log_analyzer', vehicle='VF5NP')
        self.assertEqual(store.get_tab('can_interface'), {'channel': 2, 'device': ['hardware', 5, 57, 0]})
        self.assertEqual(store.get_tab('log_analyzer'), {'vehicle': 'VF5NP'})
        on_disk = json.loads(store.path.read_text(encoding='utf-8'))
        self.assertEqual(on_disk['version'], 1)
        self.assertEqual(set(on_disk['tabs']), {'can_interface', 'log_analyzer'})

    def test_returned_values_are_copies(self):
        store = self.make()
        store.set_tab_values('can_interface', device=['a'])
        store.get_tab('can_interface')['device'].append('b')
        self.assertEqual(store.get_tab('can_interface'), {'device': ['a']})

    def test_missing_corrupt_or_wrong_shape_files_fall_back_to_empty(self):
        store = self.make()
        for text in ('{bad', '[]', '{"version": 2, "tabs": {"can_interface": {"channel": 1}}}',
                     '{"version": 1, "tabs": []}', '{"version": 1, "tabs": {"can_interface": 5}}'):
            store.path.write_text(text, encoding='utf-8')
            self.assertEqual(store.get_tab('can_interface'), {}, text)
        store.set_tab_values('can_interface', channel=1)  # A broken file is simply replaced.
        self.assertEqual(store.get_tab('can_interface'), {'channel': 1})

    def test_unserializable_values_are_rejected_without_touching_the_file(self):
        store = self.make()
        store.set_tab_values('can_interface', channel=1)
        before = store.path.read_bytes()
        with self.assertRaises(TypeError):
            store.set_tab_values('can_interface', channel=object())
        self.assertEqual(store.path.read_bytes(), before)
        self.assertEqual(list(store.path.parent.glob('*.tmp')), [])

    def test_write_failure_is_atomic_and_leaves_no_temporary_file(self):
        store = self.make()
        store.set_tab_values('can_interface', channel=1)
        before = store.path.read_bytes()
        with patch('repositories.load_config_start_store.os.replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                store.set_tab_values('can_interface', channel=2)
        self.assertEqual(store.path.read_bytes(), before)
        self.assertEqual(list(store.path.parent.glob('*.tmp')), [])


if __name__ == '__main__':
    unittest.main()
