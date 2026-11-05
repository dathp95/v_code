import os
import unittest
from dataclasses import replace
from types import SimpleNamespace
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from core.diagnostic_sequence import DiagnosticStep,DiagnosticTestCase
from models.vehicle import Vehicle
from models.ecu import ECU
from gui.widgets.can_interface.diagnostic_table_panel import CanDiagnosticTablePanel


class StepRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        service=SimpleNamespace(list_vehicles=lambda:['BENCH','OTHER'],
            load_vehicle=lambda name:Vehicle(name,ecus=[ECU('BCM','681','601'),ECU('EPS','682','602')]))
        self.panel=CanDiagnosticTablePanel(vehicle_service=service)
        self.addCleanup(self.panel.deleteLater)
        self.case=DiagnosticTestCase(1,'VIN','',True,[DiagnosticStep(i,'VIN','BCM','22 F1 90',expected_response='62 F1 90') for i in range(1,6)])
        self.panel.fn_load_sequence(self.case)
        self.panel.vehicle_selector.fn_set_vehicle('BENCH')
        for i,key in enumerate(self.panel.step_ids): self.panel.set_step_result(key,f'62 F1 90 {i:02X}','Passed',f'RT {i}')
        self.original=dict(self.panel._runtime)
        self.ids=tuple(self.panel.step_ids)

    def test_steps_1_to_4_survive_step_5_bcm_to_eps_without_rebuilding(self):
        p=self.panel
        cells=[p.table.item(i,p.COL_RECEIVE) for i in range(4)]
        combo=p.table.cellWidget(4,p.COL_ECU)
        combo.setCurrentIndex(combo.findText('EPS'))
        self.assertEqual(tuple(p.step_ids),self.ids)
        for i,key in enumerate(self.ids[:4]):
            self.assertEqual(p._runtime[key],self.original[key])
            self.assertEqual(p.table.item(i,p.COL_RESULT).text(),'Passed')
            self.assertIs(p.table.item(i,p.COL_RECEIVE),cells[i])
        self.assertNotIn(self.ids[4],p._runtime)

    def test_comment_delay_repeat_keep_all_results(self):
        p=self.panel
        for column,value in ((p.COL_COMMENT,'note'),(p.COL_DELAY,'250'),(p.COL_REPEAT,'3'),
                             (p.COL_SEQUENCE_NAME,'Renamed diagnostic step')):
            p.table.item(0,column).setText(value)
            self.assertEqual(p._runtime,self.original)

    def test_committing_reformatted_hex_editor_keeps_results(self):
        # Sequence JSON often stores HEX non-canonically (e.g. ' 22 F1 90');
        # a one-click editor commit reformats it without changing the bytes.
        p=self.panel
        steps=[replace(step,request=' 22f190',expected_response='62f190 ') for step in self.case.steps]
        p.fn_load_sequence(replace(self.case,steps=steps))
        ids=tuple(p.step_ids)
        for key in ids: p.set_step_result(key,'62 F1 90 00','Passed')
        modified=[]
        p.sequence_modified.connect(modified.append)
        p.table.item(1,p.COL_REQUEST).setText('22 F1 90')
        p.table.item(1,p.COL_EXPECTED).setText('62 F1 90')
        self.assertEqual(set(p._runtime),set(ids))
        self.assertEqual(p.table.item(1,p.COL_RESULT).text(),'Passed')
        self.assertEqual(p.table.cellWidget(1,p.COL_RECEIVE).text(),'62 F1 90 00')
        self.assertEqual(modified,[])
        self.assertFalse(p.fn_is_dirty())

    def test_runtime_snapshot_restores_only_matching_rows_and_transport(self):
        p=self.panel
        snapshot=p.runtime_snapshot()
        steps=list(self.case.steps);steps[1]=replace(steps[1],request='22 F1 91')
        p.fn_load_sequence(replace(self.case,steps=steps))
        self.assertEqual(p._runtime,{})
        p.restore_runtime_snapshot(snapshot)
        restored=[p._runtime.get(key) for key in p.step_ids]
        self.assertIsNone(restored[1])
        for row in (0,2,3,4):
            self.assertEqual(restored[row],self.original[self.ids[row]])
            self.assertEqual(p.table.item(row,p.COL_RESULT).text(),'Passed')
            self.assertEqual(p.table.cellWidget(row,p.COL_RECEIVE).text(),f'62 F1 90 {row:02X}')
        p.fn_load_sequence(self.case)
        p.vehicle_selector.fn_set_vehicle('OTHER')
        p.restore_runtime_snapshot(snapshot)
        self.assertEqual(p._runtime,{})
        p.restore_runtime_snapshot(None)

    def test_running_step_is_not_kept_in_snapshot(self):
        p=self.panel
        p.set_step_running(self.ids[0])
        snapshot=p.runtime_snapshot()
        p.fn_load_sequence(self.case)
        p.restore_runtime_snapshot(snapshot)
        self.assertIsNone(p._runtime.get(p.step_ids[0]))
        self.assertEqual(p._runtime.get(p.step_ids[1]),self.original[self.ids[1]])

    def test_payload_expected_and_match_invalidate_only_changed_step(self):
        p=self.panel
        for column,value in ((p.COL_REQUEST,'22 F1 91'),(p.COL_EXPECTED,'62 F1 91')):
            p.set_step_result(self.ids[0],'62 F1 90 00','Passed')
            p.table.item(0,column).setText(value)
            self.assertNotIn(self.ids[0],p._runtime)
            for key in self.ids[1:]: self.assertEqual(p._runtime[key],self.original[key])
        p.set_step_result(self.ids[0],'62 F1 91 00','Passed')
        steps=list(p.fn_current_sequence().steps);steps[0]=replace(steps[0],match='exact')
        p._replace_steps(steps);p._mark_dirty()
        self.assertNotIn(self.ids[0],p._runtime)
        self.assertEqual(tuple(p.step_ids),self.ids)

    def test_add_delete_preserve_surviving_results_and_sequence_load_resets(self):
        p=self.panel
        p.table.selectRow(2);p.fn_remove_selected_step()
        expected={key:value for key,value in self.original.items() if key!=self.ids[2]}
        self.assertEqual(p._runtime,expected)
        p.fn_add_step_after_selected()
        self.assertEqual(p._runtime,expected)
        p.fn_load_sequence(self.case)
        self.assertEqual(p._runtime,{})
        self.assertTrue(set(self.ids).isdisjoint(p.step_ids))

    def test_vehicle_switch_configuration_refresh_and_direct_set_clear_results(self):
        p=self.panel
        p.vehicle_selector.fn_set_vehicle('OTHER')
        self.assertEqual(p._runtime,{})
        p.set_step_result(self.ids[0],'62 F1 90','Passed')
        p.fn_refresh_vehicles()
        self.assertEqual(p._runtime,{})
        p.set_step_result(self.ids[0],'62 F1 90','Passed')
        p.fn_set_vehicle(Vehicle('NEW'))
        self.assertEqual(p._runtime,{})
