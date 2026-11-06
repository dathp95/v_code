import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from core.diagnostic_sequence import DiagnosticStep, DiagnosticTestCase
from gui.controllers.can_workspace_controller import CanWorkspaceController
from gui.widgets.can_interface.diagnostic_table_panel import CanDiagnosticTablePanel
from gui.widgets.can_interface.sequence_sidebar import CanSequenceSidebar
from repositories.can_interface_ui_store import CanInterfaceUiStore
from repositories.can_sequence_repository import CanSequenceRepository


def case(name, rows=1):
    return DiagnosticTestCase(1, name, '', True, [
        DiagnosticStep(i + 1, f'step {i + 1}', 'BCM', '10 03', 100, 1, '50 03') for i in range(rows)])


class SequenceOrderAndProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make(self, names, saved_order=None, selected=None, rows=1):
        directory = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(directory.cleanup)
        root = Path(directory.name) / 'sequences'
        repo = CanSequenceRepository(root)
        for name in names:
            repo.fn_save_sequence(case(name, rows), repo.root / f'{name}.json')
        store = CanInterfaceUiStore(Path(directory.name) / 'prefs')
        resolve = lambda n: str((repo.root / f'{n}.json').resolve())
        if saved_order is not None:
            store.save_order(tuple(resolve(n) for n in saved_order))
        if selected is not None:
            store.save_selection(resolve(selected))
        sidebar = CanSequenceSidebar(repo, store)
        panel = CanDiagnosticTablePanel(vehicle_service=SimpleNamespace(list_vehicles=lambda: []))
        controller = CanWorkspaceController(sidebar, panel, repo, store)
        for obj in (controller, panel, sidebar):
            self.addCleanup(obj.deleteLater)
        return SimpleNamespace(repo=repo, store=store, sidebar=sidebar, panel=panel, controller=controller,
                               resolve=resolve, root=repo.root)

    def names(self, env):
        return [Path(i).stem for i in env.sidebar.source_ids()]

    # --- startup -------------------------------------------------------------------
    def test_restore_opens_the_first_sequence_with_the_list_scrolled_to_the_top(self):
        names = [f'{9600 + i}.seq{i}' for i in range(40)]
        env = self.make(names, selected=names[-1])
        env.sidebar.resize(300, 300)
        env.sidebar.show()
        env.sidebar.list_sequences.verticalScrollBar().setValue(10 ** 6)
        env.controller.restore()
        self.app.processEvents()
        first = env.sidebar.source_ids()[0]
        self.assertEqual(str(env.controller.source), first)
        self.assertEqual(env.sidebar.list_sequences.currentItem().data(env.sidebar.ITEM_PATH_ROLE), first)
        self.assertEqual(env.sidebar.list_sequences.verticalScrollBar().value(), 0)

    def test_restore_with_no_sequences_does_nothing(self):
        env = self.make([])
        env.controller.restore()
        self.assertIsNone(env.controller.source)

    # --- clone ---------------------------------------------------------------------
    def test_clone_sits_right_below_its_source_and_the_position_is_saved(self):
        env = self.make(['9601.a', '9602.b', '9603.c'])
        self.assertTrue(env.controller.clone_sequence(env.resolve('9601.a')))
        self.assertEqual(self.names(env), ['9601.a', '9601.a_copy', '9602.b', '9603.c'])
        saved = [Path(i).stem for i in env.store.load().order]
        self.assertEqual(saved, ['9601.a', '9601.a_copy', '9602.b', '9603.c'])
        self.assertFalse(env.sidebar.btn_save_order.isEnabled())
        self.assertNotIn('**', ''.join(env.sidebar.list_sequences.item(i).text() for i in range(4)))

    def test_clone_keeps_a_custom_order_and_does_not_save_other_pending_moves(self):
        env = self.make(['9601.a', '9602.b', '9603.c'], saved_order=['9603.c', '9601.a', '9602.b'])
        env.sidebar.reorder(tuple(env.resolve(n) for n in ('9602.b', '9603.c', '9601.a')))  # Unsaved drag.
        self.assertTrue(env.controller.clone_sequence(env.resolve('9601.a')))
        self.assertEqual(self.names(env), ['9602.b', '9603.c', '9601.a', '9601.a_copy'])
        self.assertEqual([Path(i).stem for i in env.store.load().order],
                         ['9603.c', '9601.a', '9601.a_copy', '9602.b'])
        self.assertTrue(env.sidebar.btn_save_order.isEnabled())  # The drag is still pending.

    # --- add sequence ordering -----------------------------------------------------
    def test_new_sequences_are_placed_by_number_first_then_alphabet(self):
        names = ['9601.a', '9700.b', 'test 1', 'test 3']
        env = self.make(names, saved_order=names)
        for new in ('01 a1', 'test 2', '9650.z', 'test 9'):
            self.assertTrue(env.controller.add_sequence(new))
        self.assertEqual(self.names(env),
                         ['01 a1', '9601.a', '9650.z', '9700.b', 'test 1', 'test 2', 'test 3', 'test 9'])
        self.assertFalse(env.sidebar.btn_save_order.isEnabled())

    def test_without_a_saved_order_the_list_is_sorted_the_same_way(self):
        env = self.make(['test 2', '10.x', '9.y', 'alpha'])
        self.assertEqual(self.names(env), ['9.y', '10.x', 'alpha', 'test 2'])

    # --- progress bar --------------------------------------------------------------
    def test_progress_bar_follows_checked_rows_with_a_result(self):
        env = self.make(['9601.a'], rows=200)
        env.controller.restore()
        sidebar, panel = env.sidebar, env.panel
        self.assertEqual((sidebar.progress.value(), sidebar.progress.maximum()), (0, 200))
        self.assertEqual(sidebar.progress.format(), '0 / 200')
        for key in panel.step_ids[:50]:
            panel.set_step_result(key, '50 03', 'Passed')
        self.assertEqual(sidebar.progress.value(), 50)
        self.assertIn('50 / 200', sidebar.progress.format())
        self.assertIn('25%', sidebar.progress.format())
        panel.set_step_result(panel.step_ids[50], '', 'Running')  # Running is not done yet.
        self.assertEqual(sidebar.progress.value(), 50)
        panel.set_step_result(panel.step_ids[50], '', 'Timeout')
        self.assertEqual(sidebar.progress.value(), 51)
        panel.set_step_result(panel.step_ids[-1], '50 03', 'Failed')
        self.assertEqual(sidebar.progress.value(), 52)

    def test_progress_bar_resets_when_sequences_are_switched_and_is_themed(self):
        from gui.themes.theme import ThemeType
        from gui.themes.theme_manager import ThemeManager
        env = self.make(['9601.a', '9602.b'], rows=3)
        env.controller.restore()
        for key in env.panel.step_ids:
            env.panel.set_step_result(key, '50 03', 'Passed')
        self.assertEqual(env.sidebar.progress.value(), 3)
        env.controller.open_source(env.resolve('9602.b'))
        self.assertEqual((env.sidebar.progress.value(), env.sidebar.progress.maximum()), (0, 3))
        self.addCleanup(ThemeManager.fn_set_theme, ThemeManager.fn_theme())
        for theme in (ThemeType.LIGHT, ThemeType.DARK):
            ThemeManager.fn_set_theme(theme)
            env.sidebar.fn_refresh_theme()
            colors = ThemeManager.fn_colors()
            sheet = env.sidebar.progress.styleSheet()
            for token in (colors.PROGRESS_TRACK, colors.PROGRESS_CHUNK, colors.PROGRESS_TEXT):
                self.assertIn(token, sheet)

    def test_progress_bar_sits_under_the_list(self):
        env = self.make(['9601.a'])
        env.sidebar.resize(300, 500)
        env.sidebar.show()
        self.app.processEvents()
        list_bottom = env.sidebar.list_sequences.geometry().bottom()
        self.assertGreater(env.sidebar.progress.geometry().top(), list_bottom)
        self.assertLess(env.sidebar.progress.geometry().bottom(), env.sidebar.footer.geometry().top())


if __name__ == '__main__':
    unittest.main()
