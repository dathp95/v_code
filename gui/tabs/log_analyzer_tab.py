import logging
from PySide6.QtCore import Qt, QThread

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QMessageBox,
    QGridLayout,

)

from gui.controllers.analysis_controller import AnalysisController
from gui.controllers.clipboard_controller import ClipboardController
from gui.controllers.report_controller import ReportController
from core.transaction_formatter import fn_build_transaction_rows
from gui.themes.styles.controls.scrollbar_style import fn_apply_scrollbar_style
from gui.widgets.log_analyzer.filter_box import FilterBox
from gui.widgets.log_analyzer.left_panel import LeftPanel
from gui.widgets.log_analyzer.channel_selector import DiagnosticChannelSelectorWidget
from gui.widgets.log_analyzer.path_selector import PathSelectorWidget
from gui.widgets.log_analyzer.result_table import ResultTable
from gui.widgets.log_analyzer.right_panel import RightPanel
from gui.widgets.vehicle_manager.vehicle_selector import VehicleSelectorWidget
from gui.workers.analysis_worker import AnalysisWorker
from gui.workers.log_channel_worker import LogChannelWorker
from core.diagnostic_channel import detect_diagnostic_channel
from services.vehicle_service import VehicleService
from repositories.load_config_start_store import LoadConfigStartStore
from gui.controllers.display_names_import_controller import DisplayNamesImportController


LOG = logging.getLogger(__name__)

START_CONFIG_TAB = "log_analyzer"


class LogAnalyzerTab(QWidget):

    def __init__(self, start_store=None):
        super().__init__()

        # Values restored at start-up (config/load_config_start.json): the last chosen vehicle.
        self._start_store = start_store if start_store is not None else LoadConfigStartStore()

        # Runtime data
        self._current_vehicle = None
        self._analysis_running = False
        self._analysis_thread = None
        self._analysis_worker = None
        self._log_loading = False
        self._log_channel_thread = None
        self._log_channel_worker = None
        # {channel: {can_id: frames}} of a multi-channel log: the diagnostic channel is picked from it.
        self._log_channel_ids = None
        self._channel_chosen_manually = False
        self._parser_diagnostics = None

        # Controllers
        self._create_controllers()

        # Build UI
        self.setup_ui()

        # Connect signals
        self._connect_signals()

        # Initial UI state
        self.right_panel.action_panel.fn_set_startup_state()
        self.left_panel.fn_disable_quick_access()
        self._load_vehicles()

        self.fn_refresh_theme()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)

        # ==========================================================
        # Vehicle selector
        # ==========================================================
        self.vehicle_selector = VehicleSelectorWidget()
        

        # ==========================================================
        # Diagnostic Channel selector
        # ==========================================================
        self.channel_selector = DiagnosticChannelSelectorWidget()

        left_input_layout = QHBoxLayout()
        left_input_layout.setContentsMargins(0, 0, 0, 0)
        left_input_layout.setSpacing(8)

        left_input_layout.addWidget(
            self.vehicle_selector,
            1,
        )

        left_input_layout.addWidget(
            self.channel_selector,
            1,
        )

        # ==========================================================
        # Main layout
        # ==========================================================
        main_layout.setSpacing(8)

        
        

        # ==========================================================
        # Log selector
        # ==========================================================
        self.log_selector = PathSelectorWidget(
            "Log File: Ensure the correct Diagnostic Channel is selected",
            "Log Files (*.blf *.asc *.txt)",
            settings=True,
        )

        # Keep Vehicle / Log File labels at the same height
        input_label_height = max(
            self.vehicle_selector.lbl_vehicle.sizeHint().height(),
            self.channel_selector.lbl_channel.sizeHint().height(),
            self.log_selector.label.sizeHint().height(),
        )

        self.vehicle_selector.lbl_vehicle.setFixedHeight(
            input_label_height
        )

        self.channel_selector.lbl_channel.setFixedHeight(
            input_label_height
        )

        self.log_selector.label.setFixedHeight(
            input_label_height
        )

        # ==========================================================
        # Main widgets
        # ==========================================================
        self.filter_box = FilterBox()

        self.left_panel = LeftPanel()
        self.tbl_result = ResultTable()
        self.right_panel = RightPanel()

        # Quick Filter search is created inside QuickAccessWidget
        # but displayed in the main grid.
        self.quick_filter_search = (
            self.left_panel.quick_access.edit_search
        )

        # ==========================================================
        # Top input layout
        # ==========================================================
       

        # ==========================================================
        # Search + Content Grid
        #
        # Column 0 = Quick Filter
        # Column 1 = Result Table
        # Column 2 = Right Panel
        #
        # Using the SAME grid guarantees vertical alignment.
        # ==========================================================
        content_grid = QGridLayout()

        content_grid.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        content_grid.setHorizontalSpacing(8)
        content_grid.setVerticalSpacing(8)

        # ----------------------------------------------------------
        # Column ratio
        # Left : Table : Right
        #   5  :  18   :   4
        # ----------------------------------------------------------
        content_grid.setColumnStretch(0, 6)
        content_grid.setColumnStretch(1, 16)
        content_grid.setColumnStretch(2, 5)

        # ==========================================================
        # Row 0 - Search
        # ==========================================================
        content_grid.addLayout(
            left_input_layout,
            0,
            0,
        )
        
        content_grid.addWidget(
            self.log_selector,
            0,
            1,
        )
        content_grid.addWidget(
            self.quick_filter_search,
            1,
            0,
        )

        content_grid.addWidget(
            self.filter_box,
            1,
            1,
        )

        # Column 2 intentionally empty.
        # This keeps Search ECU aligned exactly with Result Table.

        # ==========================================================
        # Row 1 - Main content
        # ==========================================================
        content_grid.addWidget(
            self.left_panel,
            2,
            0,
        )

        content_grid.addWidget(
            self.tbl_result,
            2,
            1,
        )

        content_grid.addWidget(
            self.right_panel,
            0,
            2,
            3,
            1,
        )

        # Search row only uses required height.
        # Main content consumes remaining vertical space.
        content_grid.setRowStretch(0, 0)
        content_grid.setRowStretch(1, 0)
        content_grid.setRowStretch(2, 1)

        # ==========================================================
        # Add everything to main layout
        # ==========================================================
        

        main_layout.addLayout(
            content_grid,
            1,
        )

    def _create_controllers(self):
        self.analysis_controller = AnalysisController()
        self.export_controller = ReportController()
        self.clipboard_controller = ClipboardController()
        self.vehicle_service = VehicleService()
        self.display_names_import = DisplayNamesImportController(self)

    def _connect_signals(self):
        self.vehicle_selector.vehicle_changed.connect(
            self.fn_vehicle_changed
        )

        self.log_selector.add_setting_action(
            "Import Rules Display Names",
            self.display_names_import.import_rules,
        )
        self.log_selector.add_setting_action(
            "Import File Display Names",
            self.display_names_import.import_file,
        )

        self.log_selector.path_changed.connect(
            self.fn_log_file_changed
        )

        self.channel_selector.channel_changed.connect(
            self._fn_channel_changed
        )
        # "activated" fires only for the user's own choice, never for the automatic one.
        self.channel_selector.cmb_channel.activated.connect(
            self._fn_channel_chosen_by_user
        )

        self.filter_box.filter_changed.connect(
            self.fn_filter_transactions
        )

        self.filter_box.refresh_clicked.connect(
            self.fn_refresh_table
        )

        self.right_panel.action_panel.analyze_clicked.connect(
            self.fn_run_clicked
        )

        self.right_panel.action_panel.export_clicked.connect(
            self.fn_export_clicked
        )

        self.right_panel.action_panel.copy_clicked.connect(
            self.fn_copy_clicked
        )

        self.right_panel.action_panel.clear_clicked.connect(
            self.fn_clear_clicked
        )

        self.left_panel.quick_filter_selected.connect(
            self.fn_quick_filter
        )

        self.left_panel.quick_filter_cleared.connect(
            self.right_panel.action_panel.fn_clear_quick_filter_info
        )

        self.tbl_result.cellClicked.connect(
            self._fn_result_row_selected
        )

        self.tbl_result.transaction_selected.connect(
            self.right_panel.action_panel.fn_set_transaction_info
        )

        self.tbl_result.create_quick_filter_requested.connect(
            self._fn_create_quick_filter_from_transaction
        )

    def _load_vehicles(self):
        # Select the vehicle used in the last session; no selection if it no longer exists.
        saved = self._start_store.get_tab(START_CONFIG_TAB).get("vehicle")
        self.fn_refresh_vehicles(saved if isinstance(saved, str) else "")

    def _remember_vehicle(self, vehicle_name: str) -> None:
        try:
            if self._start_store.get_tab(START_CONFIG_TAB).get("vehicle") != vehicle_name:
                self._start_store.set_tab_values(START_CONFIG_TAB, vehicle=vehicle_name)
        except (OSError, TypeError, ValueError):
            LOG.exception("Cannot save the Log Analyzer start-up configuration")

    def fn_refresh_vehicles(
        self,
        selected_vehicle_name: str = "",
    ) -> None:

        vehicles = self.vehicle_service.list_vehicles()

        if not selected_vehicle_name and self._current_vehicle is not None:

            selected_vehicle_name = self._current_vehicle.name

        if (
            selected_vehicle_name
            and selected_vehicle_name not in vehicles
        ):

            selected_vehicle_name = ""

        self.vehicle_selector.fn_set_vehicles(
            vehicles,
            selected_vehicle=selected_vehicle_name,
            allow_empty_selection=True,
        )

        if selected_vehicle_name:

            self.fn_vehicle_changed(
                selected_vehicle_name
            )

            return

        self._current_vehicle = None

        self._update_analyze_state()

    def fn_vehicle_changed(
        self,
        vehicle_name: str,
    ):

        self._invalidate_analysis_result()

        if not vehicle_name:
            self._current_vehicle = None
            self._update_analyze_state()
            return

        self._current_vehicle = self.vehicle_service.load_vehicle(
            vehicle_name
        )

        self._remember_vehicle(vehicle_name)

        self._auto_select_diagnostic_channel()

        self._update_analyze_state()

    def _fn_channel_chosen_by_user(self, _index=None) -> None:
        self._channel_chosen_manually = True

    def _fn_log_channel_ids_ready(self, counts) -> None:
        self._log_channel_ids = counts

    def _auto_select_diagnostic_channel(self) -> bool:
        """Pick the channel that carries the selected vehicle's diagnostic IDs (log with several channels).

        Runs when the log is loaded and whenever the vehicle changes, until the user picks a channel
        themselves. No match, or an ambiguous one, leaves the choice to the user.
        """
        selector = self.channel_selector
        if (
            self._channel_chosen_manually
            or self._log_channel_ids is None
            or selector.cmb_channel.count() < 2
        ):
            return False

        channel = detect_diagnostic_channel(
            self._log_channel_ids,
            self._current_vehicle,
        )

        if channel is None:
            if selector.fn_is_auto_selected():
                selector.fn_clear_selection()
            return False

        if selector.fn_channel() == channel and selector.fn_is_auto_selected():
            return True

        return selector.fn_select_channel(channel, auto=True)

    def _fn_channel_changed(
        self,
        channel,
    ):
        self._invalidate_analysis_result()
        self._update_analyze_state()

    def _invalidate_analysis_result(self) -> None:
        self.analysis_controller.pipeline_result = None
        self.filter_box.fn_set_refresh_enabled(False)
        if self._parser_diagnostics is not None:
            self._parser_diagnostics.pipeline_frames = 0
        self._fn_refresh_parser_diagnostics()

    def _fn_parser_diagnostics_ready(self, diagnostics) -> None:
        self._parser_diagnostics = diagnostics
        self._fn_refresh_parser_diagnostics()

    def _fn_refresh_parser_diagnostics(self) -> None:
        if self._parser_diagnostics is not None:
            self._parser_diagnostics.selected_channel = self.channel_selector.fn_channel()
        self.right_panel.action_panel.fn_set_parser_diagnostics(self._parser_diagnostics)

    def fn_log_file_changed(
        self,
        file_path: str,
        ):
        # Reset selected Quick Filter
        self.left_panel.quick_access.fn_clear_active_selection()

         # Clear Quick Filter information panel
        self.right_panel.action_panel.fn_clear_quick_filter_info()

        self._parser_diagnostics = None
        self._log_channel_ids = None
        self._channel_chosen_manually = False
        self._invalidate_analysis_result()
        self.channel_selector.fn_clear()
        self.right_panel.action_panel.fn_set_analysis_ready()

        if not file_path:
            self._update_analyze_state()
            return

        self._start_log_channel_discovery(
            file_path
        )

    def _start_log_channel_discovery(
        self,
        file_path: str,
    ) -> None:
        self._log_loading = True
        self._fn_set_log_loading_inputs_enabled(False)
        self.right_panel.action_panel.fn_set_log_loading()
        self._fn_start_log_channel_thread(file_path)

    def _fn_start_log_channel_thread(
        self,
        file_path: str,
    ) -> None:
        self._log_channel_thread = QThread(self)
        self._log_channel_worker = LogChannelWorker(file_path)
        self._log_channel_worker.moveToThread(
            self._log_channel_thread
        )
        self._log_channel_worker.diagnostics_ready.connect(self._fn_parser_diagnostics_ready)
        self._log_channel_worker.channel_ids_ready.connect(self._fn_log_channel_ids_ready)

        self._log_channel_thread.started.connect(
            self._log_channel_worker.run
        )
        self._log_channel_worker.finished.connect(
            self._fn_log_channels_loaded
        )
        self._log_channel_worker.failed.connect(
            self._fn_log_channels_failed
        )
        self._log_channel_worker.finished.connect(
            self._log_channel_thread.quit
        )
        self._log_channel_worker.failed.connect(
            self._log_channel_thread.quit
        )
        self._log_channel_thread.finished.connect(
            self._log_channel_worker.deleteLater
        )
        self._log_channel_thread.finished.connect(
            self._log_channel_thread.deleteLater
        )
        self._log_channel_thread.finished.connect(
            self._fn_log_channel_thread_finished
        )

        self._log_channel_thread.start()

    def _fn_log_channels_loaded(
        self,
        channels,
    ) -> None:
        valid_channels = sorted({
            int(channel)
            for channel in channels
            if channel is not None
        })

        if not valid_channels:
            self._fn_log_channels_failed(
                "No CAN channel detected in the selected log."
            )
            return

        self._log_loading = False
        self.channel_selector.fn_set_channels(valid_channels)
        self._auto_select_diagnostic_channel()
        self._fn_refresh_parser_diagnostics()
        self._fn_set_log_loading_inputs_enabled(True)
        self.right_panel.action_panel.fn_set_log_loaded()
        self._update_analyze_state()

        channel_count = len(valid_channels)
        plural = "s" if channel_count != 1 else ""

        if self._parser_diagnostics is not None and self._parser_diagnostics.has_warnings:
            return

        message = (
            "Log file loaded successfully.\n"
            f"Detected {channel_count} CAN channel{plural}."
        )

        if self.channel_selector.fn_is_auto_selected():
            message += (
                "\nDiagnostic channel detected automatically: "
                f"Channel {self.channel_selector.fn_channel()}."
            )

        QMessageBox.information(
            self,
            "Log File Loaded",
            message,
        )

    def _fn_log_channels_failed(
        self,
        message: str,
    ) -> None:
        self._log_loading = False
        self._parser_diagnostics = None
        self._invalidate_analysis_result()
        self.channel_selector.fn_set_channels([])
        self._fn_set_log_loading_inputs_enabled(True)
        self.right_panel.action_panel.fn_set_log_load_failed()
        self._update_analyze_state()

        QMessageBox.warning(
            self,
            "Log File",
            message,
        )

    def _fn_log_channel_thread_finished(self) -> None:
        self._log_channel_thread = None
        self._log_channel_worker = None

    def _update_analyze_state(self):
        if self._log_loading:
            self.right_panel.action_panel.fn_set_log_loading()
            return

        if self._analysis_running:
            self.right_panel.action_panel.fn_set_analysis_started()
            return

        if (
            self.log_selector.path()
            and self._current_vehicle is not None
            and self.channel_selector.fn_channel() is not None
        ):
            self.right_panel.action_panel.fn_set_file_loaded_state()
            return

        self.right_panel.action_panel.fn_set_startup_state()

    def _fn_set_analysis_inputs_enabled(
        self,
        enabled: bool,
    ):
        self.vehicle_selector.setEnabled(enabled)
        self.channel_selector.setEnabled(enabled)
        self.log_selector.setEnabled(enabled)

    def _fn_set_log_loading_inputs_enabled(
        self,
        enabled: bool,
    ) -> None:
        self.vehicle_selector.setEnabled(enabled)
        self.channel_selector.setEnabled(enabled)
        self.log_selector.setEnabled(enabled)
        self.filter_box.setEnabled(enabled)
        self.left_panel.setEnabled(enabled)
        self.tbl_result.setEnabled(enabled)

    def fn_run_clicked(self):
        if self._analysis_running or self._log_loading:
            return

        log_file = self.log_selector.path()
        vehicle = self._current_vehicle
        channel = self.channel_selector.fn_channel()

        self._invalidate_analysis_result()
        self._analysis_running = True
        self._fn_set_analysis_inputs_enabled(False)
        self.right_panel.action_panel.fn_set_analysis_started()
        self._fn_start_analysis_thread(
            log_file,
            vehicle,
            channel,
        )

    def _fn_start_analysis_thread(
        self,
        log_file: str,
        vehicle,
        channel,
    ):
        self._analysis_thread = QThread(self)
        self._analysis_worker = AnalysisWorker(
            controller=self.analysis_controller,
            log_file=log_file,
            vehicle=vehicle,
            channel=channel,
        )
        self._analysis_worker.moveToThread(
            self._analysis_thread
        )

        self._analysis_thread.started.connect(
            self._analysis_worker.run
        )
        self._analysis_worker.status_changed.connect(
            self.right_panel.action_panel.fn_set_analysis_status
        )
        self._analysis_worker.finished.connect(
            self._fn_analysis_finished
        )
        self._analysis_worker.failed.connect(
            self._fn_analysis_failed
        )
        self._analysis_worker.finished.connect(
            self._analysis_thread.quit
        )
        self._analysis_worker.failed.connect(
            self._analysis_thread.quit
        )
        self._analysis_thread.finished.connect(
            self._analysis_worker.deleteLater
        )
        self._analysis_thread.finished.connect(
            self._analysis_thread.deleteLater
        )
        self._analysis_thread.finished.connect(
            self._fn_analysis_thread_finished
        )

        self._analysis_thread.start()

    def _fn_analysis_finished(
        self,
        result,
    ):
        self._analysis_running = False
        self._fn_set_analysis_inputs_enabled(True)
        self._parser_diagnostics = result.get("parser_diagnostics")
        self._fn_refresh_parser_diagnostics()

        rows = fn_build_transaction_rows(
            result["transactions"]
        )

        self.tbl_result.set_data(rows)
        self.filter_box.fn_set_refresh_enabled(True)
        self.tbl_result.clearSelection()
        self.tbl_result.setCurrentCell(-1, -1)
        self.right_panel.action_panel.fn_clear_transaction_info()

        self.right_panel.action_panel.fn_set_analysis_completed()
        self.right_panel.action_panel.fn_set_analyzed_state(has_data=bool(rows))
        self.left_panel.fn_enable_quick_access()

    def _fn_analysis_failed(
        self,
        message: str,
    ):
        self._analysis_running = False
        self._fn_set_analysis_inputs_enabled(True)
        self._update_analyze_state()
        self.right_panel.action_panel.fn_set_analysis_failed(message)
        self.filter_box.fn_set_refresh_enabled(False)

        QMessageBox.warning(
            self,
            "Analyze",
            message,
        )

    def _fn_analysis_thread_finished(self):
        self._analysis_thread = None
        self._analysis_worker = None

    def fn_export_clicked(self):
        vehicle_name = (
            self._current_vehicle.name
            if self._current_vehicle is not None
            else ""
        )

        self.export_controller.fn_export(
            parent=self,
            pipeline_result=self.analysis_controller.pipeline_result,
            vehicle_name=vehicle_name,
        )

    def fn_copy_clicked(self):
        self.clipboard_controller.fn_copy(
            parent=self,
            rows=self.tbl_result.fn_visible_rows(),
        )

    def fn_clear_clicked(self) -> None:
        """Clear current table data and reset analysis UI state."""

        self.tbl_result.clear_data()
        self.filter_box.clear()
        self._invalidate_analysis_result()
        self.right_panel.action_panel.fn_clear_detail_panels()
        self.left_panel.fn_disable_quick_access()
        self.right_panel.action_panel.fn_set_analysis_ready()
        self._update_analyze_state()

    def fn_filter_transactions(self, keyword=None):
        self.tbl_result.fn_search(keyword)

    def fn_refresh_table(self):
        self.filter_box.clear()
        self.tbl_result.fn_reset_view()
        self.right_panel.action_panel.fn_clear_quick_filter_info()
        self.right_panel.action_panel.fn_clear_transaction_info()
        self.left_panel.quick_access.fn_clear_active_selection()

    def fn_quick_filter(self, filter_data: dict):
        # Reset previous transaction details
        self.right_panel.action_panel.fn_clear_transaction_info()

        # Display selected Quick Filter information
        self.right_panel.action_panel.fn_set_quick_filter_info(filter_data)

        # Apply selected filter to ResultTable
        self.tbl_result.fn_apply_quick_filter(filter_data)

    def _fn_result_row_selected(
        self,
        row: int,
        column: int,
    ):
        self.right_panel.action_panel.fn_set_transaction_info(
            self.tbl_result.fn_row_data(row)
        )

    def _fn_create_quick_filter_from_transaction(
        self,
        row_data: dict,
    ):
        self.left_panel.quick_access.fn_create_from_transaction(
            row_data
        )

    def fn_refresh_theme(self):
        self.vehicle_selector.fn_refresh_theme()
        self.channel_selector.fn_refresh_theme()
        self.log_selector.fn_refresh_theme()
        self.right_panel.fn_refresh_theme()
        self.left_panel.fn_refresh_theme()
        self.filter_box.fn_refresh_theme()
        self.tbl_result.fn_refresh_theme()
