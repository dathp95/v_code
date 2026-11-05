import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from core.diagnostic_sequence import DiagnosticStep, DiagnosticTestCase
from core.sequence_exchange import HEADERS, parse_sequence_text, export_sequence_text
from gui.controllers.can_workspace_controller import CanWorkspaceController
from gui.dialogs.sequence_exchange_dialog import SequenceExchangeDialog
from gui.widgets.can_interface.sequence_sidebar import CanSequenceSidebar
from gui.widgets.can_interface.diagnostic_table_panel import CanDiagnosticTablePanel
from repositories.can_sequence_repository import CanSequenceRepository
from repositories.can_interface_ui_store import CanInterfaceUiStore
from models.vehicle import Vehicle
from models.ecu import ECU


class SequenceEditor64Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        temp=tempfile.TemporaryDirectory(dir=Path.cwd());self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.repo=CanSequenceRepository(self.root/'seq')
        for name in ('one','two'):
            self.repo.fn_save_sequence(DiagnosticTestCase(1,name,'',True,[DiagnosticStep(1,name,'BCM','22 F1 90')]),self.repo.root/f'{name}.json')
        self.store=CanInterfaceUiStore(self.root/'prefs')
        self.sidebar=CanSequenceSidebar(self.repo,self.store)
        service=SimpleNamespace(list_vehicles=lambda:['BENCH'],load_vehicle=lambda _:Vehicle('BENCH',ecus=[ECU('BCM','681','601'),ECU('EPS','682','602')]))
        self.panel=CanDiagnosticTablePanel(vehicle_service=service)
        self.controller=CanWorkspaceController(self.sidebar,self.panel,self.repo,self.store)
        for widget in (self.controller,self.panel,self.sidebar): self.addCleanup(widget.deleteLater)

    def open(self):
        self.assertTrue(self.controller.open_source(self.repo.root/'one.json'))
        self.panel.vehicle_selector.fn_set_vehicle('BENCH')

    def test_fixed_two_row_footer_long_list_error_overflow_and_theme(self):
        from gui.themes.theme_manager import ThemeManager
        from gui.themes.theme import ThemeType
        self.addCleanup(ThemeManager.fn_set_theme,ThemeManager.fn_theme())
        for index in range(60):
            self.repo.fn_save_sequence(DiagnosticTestCase(1,f'Case {index}','',True,[]),self.repo.root/f'case{index}.json')
        (self.repo.root/'broken.json').write_text('{bad')
        self.sidebar.fn_refresh_sequences();self.sidebar.resize(310,520);self.sidebar.show();self.app.processEvents()
        self.assertEqual([button.text() for button in self.sidebar.footer_buttons],['+ Add','Import SEQ','Export SEQ','Save','Save Order'])
        self.assertTrue(self.sidebar.sequence_errors)
        self.sidebar._set_errors(['Very long error '+str(i)+'x'*1000 for i in range(80)])
        for theme in (ThemeType.LIGHT,ThemeType.DARK):
            ThemeManager.fn_set_theme(theme);self.sidebar.fn_refresh_theme();self.app.processEvents()
            before=self.sidebar.footer.geometry()
            bar=self.sidebar.list_sequences.verticalScrollBar();self.assertGreater(bar.maximum(),0);bar.setValue(bar.maximum())
            self.app.processEvents()
            self.assertEqual(before,self.sidebar.footer.geometry())
            for button in self.sidebar.footer_buttons:
                self.assertTrue(self.sidebar.footer.isAncestorOf(button))
                self.assertTrue(button.isVisible())
            self.assertLessEqual(self.sidebar.footer.geometry().bottom(),self.sidebar.height())
            self.assertEqual(self.sidebar.list_sequences.horizontalScrollBar().maximum(),0)

    def test_new_draft_save_clears_stars_but_not_pending_order(self):
        self.assertTrue(self.controller.add_sequence('New'))
        self.assertFalse((self.repo.root/'New.json').exists())
        self.panel.fn_add_step_after_selected()
        combo=self.panel.table.cellWidget(0,self.panel.COL_ECU)
        self.panel.vehicle_selector.fn_set_vehicle('BENCH')
        combo=self.panel.table.cellWidget(0,self.panel.COL_ECU);combo.setCurrentIndex(combo.findText('BCM'))
        key=self.panel.step_ids[0]
        self.panel.table.item(0,self.panel.COL_REQUEST).setText('22 F1 90')
        self.panel.table.item(0,self.panel.COL_SEQUENCE_NAME).setText('Editable sequence name')
        self.panel.set_step_result(key,'62 F1 90','Passed')
        self.assertIn('*',self.panel.title.text())
        self.assertTrue(self.sidebar.list_sequences.currentItem().text().endswith(' *'))
        self.assertTrue(self.sidebar.btn_save.isEnabled());self.assertTrue(self.panel.btn_export.isHidden())
        with patch.object(self.repo,'fn_save_sequence',side_effect=OSError('write failed')):
            self.assertIsNone(self.controller.save_sequence(self.repo.root/'New.json'))
        self.assertTrue(self.panel.fn_is_dirty())
        self.assertTrue(self.sidebar.list_sequences.currentItem().text().endswith(' *'))
        self.sidebar.reorder(tuple(reversed(self.sidebar.source_ids())))
        self.assertTrue(self.sidebar.btn_save_order.isEnabled())
        self.assertEqual(self.controller.save_sequence(self.repo.root/'New.json'),self.repo.root/'New.json')
        self.assertFalse(self.sidebar.btn_save.isEnabled());self.assertTrue(self.sidebar.btn_save_order.isEnabled())
        self.assertNotIn('*',self.panel.title.text())
        self.assertEqual(self.panel.step_ids,[key]);self.assertEqual(self.panel._runtime[key][1],'Passed')
        self.assertEqual(self.store.load().order,())
        self.sidebar._save_order()
        self.panel.table.item(0,self.panel.COL_COMMENT).setText('still unsaved')
        self.sidebar.reorder(tuple(reversed(self.sidebar.source_ids())))
        self.sidebar._save_order()
        self.assertTrue(self.panel.fn_is_dirty())
        self.assertTrue(self.sidebar.list_sequences.currentItem().text().endswith(' *'))

    def test_unknown_ecu_empty_reversible_display_save_normalizes_and_no_send(self):
        self.open();original=DiagnosticTestCase(1,'bad','',True,[DiagnosticStep(1,'bad','unknown<>','22 F1 90')])
        self.panel.fn_load_sequence(original);key=self.panel.step_ids[0]
        self.assertEqual(self.panel.table.cellWidget(0,self.panel.COL_ECU).currentText(),'')
        self.assertEqual(self.panel.fn_current_sequence(),original)
        sent=[];self.panel.row_send_requested.connect(sent.append);self.panel._request_step(key)
        self.assertEqual(sent,[])
        self.assertFalse(self.panel.table.cellWidget(0,self.panel.COL_SEND).isEnabled())
        self.panel.fn_set_vehicle(None)
        self.assertEqual(self.panel.table.cellWidget(0,self.panel.COL_ECU).currentText(),'unknown<>')
        self.panel.vehicle_selector.fn_set_vehicle('BENCH')
        self.panel._mark_dirty();self.controller.save_sequence(self.repo.root/'one.json')
        self.assertEqual(self.repo.fn_load_sequence(self.repo.root/'one.json').steps[0].ecu,'')
        self.assertTrue(any('unknown<>' in note for note in self.panel.import_diagnostics))

    def test_import_preview_atomic_append_results_ignored_export_copy_cancel(self):
        self.open();key=self.panel.step_ids[0];self.panel.set_step_result(key,'62 F1 90','Passed')
        step=DiagnosticStep(1,'unsaved','EPS','10 01',comment='quoted\tcomment\nnext')
        text=export_sequence_text([step],['Passed'])
        dialog=SequenceExchangeDialog(ecu_names={'BCM','EPS'});self.addCleanup(dialog.deleteLater)
        dialog.editor.setPlainText(text)
        self.assertTrue(dialog.btn_apply.isEnabled())  # Append below the cursor is the default mode; no preview step.
        before=self.panel.fn_current_sequence()
        dialog.editor.setPlainText(text+'"unterminated\tquote');dialog.btn_apply.click()  # Unreadable input is refused.
        self.assertIsNone(dialog.parsed);self.assertEqual(self.panel.fn_current_sequence(),before)
        imported=parse_sequence_text(text,ecu_names={'BCM','EPS'});self.panel.apply_import(imported,'append')
        self.assertEqual(self.panel.step_ids[0],key);self.assertEqual(self.panel._runtime[key][1],'Passed')
        self.assertNotIn(self.panel.step_ids[1],self.panel._runtime)
        exported=self.panel.exchange_text();self.assertEqual(exported.splitlines()[0],'\t'.join(HEADERS))
        self.assertEqual(parse_sequence_text(exported).steps[1].comment,step.comment)
        QApplication.clipboard().setText('unchanged')
        export=SequenceExchangeDialog(text=exported);self.addCleanup(export.deleteLater)
        export.reject();self.assertEqual(QApplication.clipboard().text(),'unchanged')
        export.btn_apply.click();self.assertEqual(QApplication.clipboard().text(),exported)

    def test_duplicate_display_names_and_cancelled_dirty_switch(self):
        for name in ('one','two'):
            self.repo.fn_save_sequence(DiagnosticTestCase(1,'Same','',True,[DiagnosticStep(1,'same','BCM','22 F1 90')]),self.repo.root/f'{name}.json')
        self.sidebar.fn_refresh_sequences();self.open()
        self.panel.table.item(0,self.panel.COL_COMMENT).setText('dirty')
        before=self.panel.fn_current_sequence();ids=tuple(self.panel.step_ids)
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Cancel):
            self.assertFalse(self.controller.open_source(self.repo.root/'two.json'))
            self.assertFalse(self.controller.add_sequence('another'))
        self.assertEqual(self.panel.fn_current_sequence(),before);self.assertEqual(tuple(self.panel.step_ids),ids)
        self.assertEqual(sum(self.sidebar.list_sequences.item(i).text().endswith(' *') for i in range(2)),1)

    def test_clearing_ecu_selector_cannot_send_previous_hidden_target(self):
        self.open()
        combo=self.panel.table.cellWidget(0,self.panel.COL_ECU)
        combo.setCurrentIndex(0)
        self.assertEqual(self.panel.fn_current_sequence().steps[0].ecu,'')
        self.assertFalse(self.panel.table.cellWidget(0,self.panel.COL_SEND).isEnabled())
        sent=[];self.panel.row_send_requested.connect(sent.append)
        self.panel._request_step(self.panel.step_ids[0]);self.assertEqual(sent,[])

    def test_saving_new_document_without_drag_does_not_dirty_save_order(self):
        self.assertTrue(self.controller.add_sequence('A first'))
        self.controller.save_sequence(self.repo.root/'A first.json')
        self.assertFalse(self.sidebar.btn_save_order.isEnabled())

    def test_save_as_keeps_original_file_identity_in_pending_order(self):
        self.open();self.controller.open_source(self.repo.root/'two.json')
        original=str((self.repo.root/'two.json').resolve())
        order=tuple(reversed(self.sidebar.source_ids()));self.sidebar.reorder(order)
        self.controller.save_sequence(self.repo.root/'copy.json')
        ids=self.sidebar.source_ids()
        self.assertEqual(tuple(value for value in ids if value in order),order)
        self.assertIn(original,ids)

    def test_no_vehicle_preserves_ecu_text_but_disables_send(self):
        self.open();self.panel.fn_set_vehicle(None)
        self.assertEqual(self.panel.table.cellWidget(0,self.panel.COL_ECU).currentText(),'BCM')
        self.assertFalse(self.panel.table.cellWidget(0,self.panel.COL_SEND).isEnabled())
        sent=[];self.panel.row_send_requested.connect(sent.append)
        self.panel._request_step(self.panel.step_ids[0]);self.assertEqual(sent,[])

    def test_dragged_draft_position_survives_save_and_requires_explicit_order_save(self):
        self.controller.add_sequence('zznew')
        draft=self.controller.document_id
        self.sidebar.reorder((draft,*self.sidebar.persistent_ids()))
        self.controller.save_sequence(self.repo.root/'zznew.json')
        self.assertEqual(self.sidebar.source_ids()[0],str((self.repo.root/'zznew.json').resolve()))
        self.assertTrue(self.sidebar.btn_save_order.isEnabled())
        self.assertEqual(self.store.load().order,())

    def test_discard_checked_draft_updates_count_and_checked_signal(self):
        self.controller.add_sequence('draft')
        self.sidebar.list_sequences.currentItem().setCheckState(Qt.Checked)
        signals=[];self.sidebar.checked_sequences_changed.connect(signals.append)
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Discard):
            self.controller.add_sequence('next')
        self.assertEqual(self.sidebar.checked_ids(),())
        self.assertEqual(self.sidebar.lbl_selected.text(),'0 selected')
        self.assertEqual(signals[-1],())
