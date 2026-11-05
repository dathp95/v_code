import tempfile
from pathlib import Path
from threading import get_ident
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox
from core.bench_authorization import BenchAuthorizationContext
from core.diagnostic_sequence import DiagnosticStep,DiagnosticTestCase
from gui.tabs.can_interface_tab import CANInterfaceTab
from gui.workers.can_connection_worker import CANConnectionOperation
from repositories.can_interface_ui_store import CanInterfaceUiStore
from repositories.can_sequence_repository import CanSequenceRepository
from models.ecu import ECU
from models.vehicle import Vehicle
from services.can import CANService,CANConfig
from services.can.simulated_backend import SimulatedCANBackend
from services.can.security_access_session import SecurityAccessState as State
from tests.gui import test_can_diagnostic_execution as fixtures


class SecurityAccess82GuiTests(unittest.TestCase):
    setUpClass=classmethod(fixtures.CanDiagnosticExecutionTests.setUpClass.__func__)
    wait=fixtures.CanDiagnosticExecutionTests.wait

    def setUp(self):
        directory=tempfile.TemporaryDirectory(dir=Path.cwd());self.addCleanup(directory.cleanup)
        root=Path(directory.name)
        self.backend=SimulatedCANBackend()
        self.service=CANService(self.backend)
        vehicle=Vehicle('BENCH',ecus=[ECU('BCM','681','601')])
        self.tab=CANInterfaceTab(self.service,vehicle_service=SimpleNamespace(list_vehicles=lambda:['BENCH'],load_vehicle=lambda _:vehicle),
            sequence_repository=CanSequenceRepository(root/'seq'),ui_store=CanInterfaceUiStore(root/'prefs'))
        self.addCleanup(self.tab.deleteLater);self.addCleanup(self.tab._connection_task.shutdown);self.addCleanup(self.tab.close)
        self.tab._on_sequence_selected(DiagnosticTestCase(1,'L1 simulator','',True,[
            DiagnosticStep(1,'Session','BCM','10 03',expected_response='50 03'),
            DiagnosticStep(2,'Seed','BCM','27 01',expected_response='67 01')]))
        self.panel=self.tab.sequence_table
        self.panel.vehicle_selector.fn_set_vehicle('BENCH')
        config=CANConfig('vector',0,500000,bench_context=BenchAuthorizationContext('simulator-bench',True))
        self.tab._connection_task.start(CANConnectionOperation.CONNECT,config)
        self.wait(lambda:not self.tab._connection_task.running)

    def outcome(self,row): return self.panel.table.item(row,self.panel.COL_RESULT).text()
