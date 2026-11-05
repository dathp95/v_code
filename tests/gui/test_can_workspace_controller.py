import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication, QMessageBox
from gui.controllers.can_workspace_controller import CanWorkspaceController
from gui.widgets.can_interface.sequence_sidebar import CanSequenceSidebar
from gui.widgets.can_interface.diagnostic_table_panel import CanDiagnosticTablePanel
from repositories.can_interface_ui_store import CanInterfaceUiStore
from repositories.can_sequence_repository import CanSequenceRepository
from models.vehicle import Vehicle
from models.ecu import ECU


class CanWorkspaceControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_import_save_as_order_and_vehicle_preferences_do_not_cross(self):
        fixtures=Path(__file__).parents[1]/'fixtures'/'can_interface'
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root=Path(directory)
            source=root/'source.diag'
            source.write_bytes((fixtures/'0002.READ VIN(1).diag').read_bytes())
            original=source.read_bytes()
            repo=CanSequenceRepository(root)
            store=CanInterfaceUiStore(root/'prefs.ui')
            sidebar=CanSequenceSidebar(repo,store)
            panel=CanDiagnosticTablePanel(vehicle_service=SimpleNamespace(list_vehicles=lambda:['BENCH'],load_vehicle=lambda _: Vehicle('BENCH',ecus=[ECU('TEST_ECU_01')])))
            controller=CanWorkspaceController(sidebar,panel,repo,store)
            self.addCleanup(controller.deleteLater)
            self.addCleanup(panel.deleteLater)
            self.addCleanup(sidebar.deleteLater)
            self.assertTrue(controller.open_source(str(source)))
            panel.vehicle_selector.fn_set_vehicle('BENCH')
            panel.table.item(0,panel.COL_COMMENT).setText('native comment')
            self.assertIsNone(controller.save_sequence(source))
            target=root/'converted.json'
            self.assertEqual(controller.save_sequence(target),target)
            self.assertEqual(source.read_bytes(),original)
            self.assertEqual(repo.fn_load_sequence(target).steps[0].comment,'native comment')
            sidebar.reorder(tuple(reversed(sidebar.source_ids())))
            self.assertTrue(sidebar.btn_save_order.isEnabled())
            panel.table.item(0,panel.COL_COMMENT).setText('second edit')
            controller.save_sequence()
            self.assertTrue(sidebar.btn_save_order.isEnabled())
            self.assertEqual(store.load().order,())
            self.assertEqual(store.load().vehicles[str(target)],'BENCH')
            self.assertNotIn('IDReq',target.read_text(encoding='utf-8'))

    def test_invalid_preferences_and_invalid_source_do_not_crash(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            store=CanInterfaceUiStore(Path(directory)/'prefs')
            store.path.write_text('{bad',encoding='utf-8')
            self.assertEqual(store.load().selected_id,'')
            repo=CanSequenceRepository(directory,sources=('not-a-sequence.invalid',))
            sidebar=CanSequenceSidebar(repo,store)
            panel=CanDiagnosticTablePanel(vehicle_service=SimpleNamespace(list_vehicles=lambda:[]))
            controller=CanWorkspaceController(sidebar,panel,repo,store)
            self.addCleanup(controller.deleteLater)
            self.addCleanup(panel.deleteLater)
            self.addCleanup(sidebar.deleteLater)
            self.assertFalse(controller.open_source(Path(directory)/'missing.diag'))
            self.assertIn('missing.diag',panel.notice.text())

    def test_switching_sequences_away_and_back_keeps_runtime_results(self):
        fixtures=Path(__file__).parents[1]/'fixtures'/'can_interface'
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            repo=CanSequenceRepository(directory)
            store=CanInterfaceUiStore(Path(directory)/'prefs')
            sidebar=CanSequenceSidebar(repo,store)
            panel=CanDiagnosticTablePanel(vehicle_service=SimpleNamespace(list_vehicles=lambda:[]))
            controller=CanWorkspaceController(sidebar,panel,repo,store)
            for obj in (controller,panel,sidebar): self.addCleanup(obj.deleteLater)
            first=fixtures/'0001.READ&CDS(1).diag'
            second=fixtures/'0002.READ VIN(1).diag'
            self.assertTrue(controller.open_source(first))
            for row,key in enumerate(panel.step_ids):
                panel.set_step_result(key,f'62 F1 90 {row:02X}','Passed',f'RT {row}')
            expected=[panel._runtime[key] for key in panel.step_ids]
            self.assertTrue(controller.open_source(second))
            self.assertEqual(panel._runtime,{})
            self.assertTrue(controller.open_source(first))
            self.assertEqual([panel._runtime.get(key) for key in panel.step_ids],expected)
            self.assertEqual(panel.table.item(0,panel.COL_RESULT).text(),'Passed')
            self.assertEqual(panel.table.cellWidget(0,panel.COL_RECEIVE).text(),'62 F1 90 00')

    def test_opening_a_sequence_remaps_ecus_but_never_marks_it_modified(self):
        import json
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root=Path(directory)
            step={'step':1,'sequence_name':'Read VIN','ecu':'WRONG_NAME','request':' 22 F1 90','delay_ms':100,'repeat':1,
                  'expected_response':'62 F1 90','match':'prefix','comment':'',
                  'source_request_id':0x681,'source_response_id':0x601}
            source=root/'seq.json'
            source.write_text(json.dumps({'schema_version':1,'name':'seq','description':'','enabled':True,
                'execution':{'loop':1,'command_delay_ms':100},'steps':[step]}),encoding='utf-8')
            repo=CanSequenceRepository(root)
            store=CanInterfaceUiStore(root/'prefs')
            sidebar=CanSequenceSidebar(repo,store)
            panel=CanDiagnosticTablePanel(vehicle_service=SimpleNamespace(list_vehicles=lambda:['BENCH'],
                load_vehicle=lambda _:Vehicle('BENCH',ecus=[ECU('BCM','681','601')])))
            controller=CanWorkspaceController(sidebar,panel,repo,store)
            for obj in (controller,panel,sidebar): self.addCleanup(obj.deleteLater)
            self.assertTrue(controller.open_source(str(source)))
            self.assertEqual(panel.fn_current_sequence().steps[0].ecu,'WRONG_NAME')  # No Vehicle: nothing to resolve.
            self.assertFalse(panel.fn_is_dirty())
            panel.vehicle_selector.fn_set_vehicle('BENCH')
            self.assertEqual(panel.fn_current_sequence().steps[0].ecu,'BCM')  # Addressing still maps to the ECU name.
            self.assertFalse(panel.fn_is_dirty())
            self.assertEqual(controller._session_dirty,set())
            self.assertFalse(sidebar.btn_save.isEnabled())
            self.assertFalse(panel.title.text().endswith('*'))
            panel.set_step_result(panel.step_ids[0],'62 F1 90 41','Passed')  # A result is not an edit either.
            self.assertFalse(panel.fn_is_dirty())
            self.assertFalse(sidebar.btn_save.isEnabled())
            panel.table.item(0,panel.COL_COMMENT).setText('real edit')
            self.assertTrue(panel.fn_is_dirty())
            self.assertTrue(sidebar.btn_save.isEnabled())

    def test_unsaved_switch_can_be_cancelled(self):
        fixtures=Path(__file__).parents[1]/'fixtures'/'can_interface'
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            repo=CanSequenceRepository(directory)
            store=CanInterfaceUiStore(Path(directory)/'prefs')
            sidebar=CanSequenceSidebar(repo,store)
            panel=CanDiagnosticTablePanel(vehicle_service=SimpleNamespace(list_vehicles=lambda:[]))
            controller=CanWorkspaceController(sidebar,panel,repo,store)
            for obj in (controller,panel,sidebar): self.addCleanup(obj.deleteLater)
            first=fixtures/'0001.READ&CDS(1).diag'
            controller.open_source(first)
            panel.table.item(0,panel.COL_COMMENT).setText('unsaved')
            with patch.object(QMessageBox,'question',return_value=QMessageBox.Cancel):
                self.assertFalse(controller.open_source(fixtures/'0002.READ VIN(1).diag'))
            self.assertEqual(controller.source,first.resolve())
            self.assertEqual(panel.fn_current_sequence().steps[0].comment,'unsaved')

    def test_sidebar_cancel_keeps_unsaved_document_active_without_selected_signal(self):
        fixtures = Path(__file__).parents[1] / 'fixtures' / 'can_interface'
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            repo = CanSequenceRepository(directory)
            store = CanInterfaceUiStore(Path(directory) / 'prefs')
            sidebar = CanSequenceSidebar(repo, store)
            panel = CanDiagnosticTablePanel(vehicle_service=SimpleNamespace(list_vehicles=lambda: []))
            controller = CanWorkspaceController(sidebar, panel, repo, store)
            for obj in (controller, panel, sidebar): self.addCleanup(obj.deleteLater)
            first = (fixtures / '0001.READ&CDS(1).diag').resolve()
            second = (fixtures / '0002.READ VIN(1).diag').resolve()
            repo.register_source(second)
            self.assertTrue(controller.open_source(first))
            panel.table.item(0, panel.COL_COMMENT).setText('keep this unsaved edit')
            previous_document = panel.fn_current_sequence()
            previous_ids = tuple(panel.step_ids)
            selected = []
            sidebar.sequence_selected.connect(selected.append)
            index = sidebar.source_ids().index(str(second))
            sidebar.list_sequences.setCurrentRow(index)
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.Cancel) as prompt:
                sidebar._activate_item(sidebar.list_sequences.item(index))
            prompt.assert_called_once()
            self.assertEqual(selected, [])
            self.assertEqual(controller.source, first)
            self.assertEqual(sidebar._active_source, str(first))
            self.assertEqual(sidebar.list_sequences.currentItem().data(sidebar.ITEM_PATH_ROLE), str(first))
            self.assertEqual(store.load().selected_id, str(first))
            self.assertEqual(panel.fn_current_sequence(), previous_document)
            self.assertEqual(tuple(panel.step_ids), previous_ids)
            self.assertTrue(panel.fn_is_dirty())

    def test_external_inventory_and_active_source_restore_without_saving_order(self):
        fixtures=Path(__file__).parents[1]/'fixtures'/'can_interface'
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            store=CanInterfaceUiStore(Path(directory)/'prefs')
            first=(fixtures/'0001.READ&CDS(1).diag').resolve()
            second=(fixtures/'0002.READ VIN(1).diag').resolve()
            store.save_selection(str(first))
            store.save_selection(str(second))
            state=store.load()
            self.assertEqual(state.order,())
            repo=CanSequenceRepository(Path(directory)/'empty',sources=state.sources)
            self.assertEqual(set(repo.fn_list_sequences()),{first,second})
            sidebar=CanSequenceSidebar(repo,store)
            panel=CanDiagnosticTablePanel(vehicle_service=SimpleNamespace(list_vehicles=lambda:[]))
            controller=CanWorkspaceController(sidebar,panel,repo,store)
            for obj in (controller,panel,sidebar): self.addCleanup(obj.deleteLater)
            controller.restore()
            self.assertEqual(controller.source,second)
            self.assertEqual(len(panel.fn_current_sequence().steps),16)

    def test_preference_write_failure_is_atomic_and_removes_temporary(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            store=CanInterfaceUiStore(Path(directory)/'prefs')
            store.save_order(('first','second'))
            original=store.path.read_bytes()
            with patch('repositories.can_interface_ui_store.os.replace',side_effect=OSError('disk full')):
                with self.assertRaises(OSError): store.save_order(('second','first'))
            self.assertEqual(store.path.read_bytes(),original)
            self.assertEqual(list(Path(directory).glob('*.tmp')),[])
