from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import partial
from pathlib import Path
from time import perf_counter

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSignalBlocker, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QLabel,
    QMessageBox,
    QScrollBar,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
    QHeaderView,
    QMenu,
)

from core.q_current_analysis import analyze_q_current, parse_q_current_timestamp
from core.q_current_loading import (
    QCurrentWorkspaceData, calculate_elapsed_seconds, prepare_workspace_data, timed_call,
)
from core.q_current_config import QCurrentConfig, load_q_current_config, save_q_current_config
from core.q_current_report_export import QCurrentReportData, QCurrentReportSettings
from core.services.q_current_report_service import QCurrentReportService
from gui.widgets.controls.export_toast import show_export_toast
from core.sleep_current_database import (
    database_path_for_source,
    default_dataset_name,
    ensure_database_directory,
    get_primary_dataset,
    get_samples,
    import_dataset,
    list_datasets,
    normalize_current_data,
)
from gui.themes.styles.containers.groupbox_style import fn_groupbox_style
from gui.themes.styles.controls.scrollbar_style import (
    fn_apply_scrollbar_style,
    fn_scrollbar_style,
)
from gui.themes.styles.controls.menu_style import fn_apply_menu_style
from gui.themes.styles.controls.spinbox_style import fn_spinbox_style
from gui.themes.theme_manager import ThemeManager
from gui.widgets.controls.primary_button import PrimaryButton
from gui.widgets.controls.primary_checkbox import PrimaryCheckBox
from gui.widgets.controls.primary_combobox import PrimaryComboBox
from gui.widgets.controls.primary_label import PrimaryLabel
from gui.widgets.controls.primary_lineedit import PrimaryLineEdit
from gui.widgets.controls.quick_access_button import QuickAccessButton
from gui.widgets.q_current.summary_widget import QCurrentSummaryWidget
from gui.widgets.q_current.analysis_progress import QCurrentProgressBar
from gui.widgets.q_current.review_table import QCurrentReviewModel, QCurrentReviewTable
from gui.workers.q_current_worker import QCurrentTaskRunner


PLACEHOLDER_VALUE = "\u2014"
SOURCE_FILE_PLACEHOLDER = "Select current data file (*.csv, *.xlsx)"
SUPPORTED_SOURCE_EXTENSIONS = {".csv", ".xlsx"}
SOURCE_FILE_FILTER = (
    "Supported Files (*.csv *.xlsx);;"
    "CSV Files (*.csv);;"
    "Excel Files (*.xlsx)"
)
CHART_SCROLL_VISIBLE_SECONDS = 400.0
CHART_SCROLL_SCALE = 1000
PIN_HIT_RADIUS_PX = 12.0
SAMPLE_HIT_RADIUS_PX = 18.0


def parse_timestamp(value):
    return parse_q_current_timestamp(value)


@dataclass
class ChartPin:
    sample_index: int
    time_s: float
    current_ma: float
    marker: pg.ScatterPlotItem
    label: pg.TextItem


class QCurrentDatasetComboBox(PrimaryComboBox):

    def __init__(self, refresh_callback, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._refresh_callback = refresh_callback
        self._refresh_popup_scrollbar()

    def showPopup(self):
        self._refresh_callback()
        self._refresh_popup_scrollbar()
        super().showPopup()

    def fn_refresh_theme(self):
        super().fn_refresh_theme()
        self._refresh_popup_scrollbar()

    def _refresh_popup_scrollbar(self):
        fn_apply_scrollbar_style(self.view())


class QCurrentTab(QWidget):

    def __init__(
        self,
        database_dir: str | Path | None = None,
        config_file: str | Path | None = None,
    ):
        super().__init__()

        self._theme_widgets = []
        self._database_dir = database_dir
        self._config_file = config_file
        self._operation_running = False
        self._task_runner = QCurrentTaskRunner(QApplication.instance())
        self._task_runner.finished.connect(self._task_finished)
        self._task_runner.failed.connect(self._task_failed)
        QApplication.instance().aboutToQuit.connect(self._task_runner.wait)
        self.destroyed.connect(self._task_runner.wait)
        self.destroyed.connect(self._task_runner.deleteLater)
        self.q_current_config = load_q_current_config(config_file)
        self.current_import = None
        self.current_samples = []
        self._workspace_data = None
        self.last_loading_timings = {}
        self.current_database_path = None
        self.current_analysis_result = None
        self.current_analysis_settings = None
        self.q_current_report_service = QCurrentReportService()
        self._chart_ready = False
        self.current_curve = None
        self.upper_sleep_limit_line = None
        self.lower_sleep_limit_line = None
        self.hover_marker = None
        self.hover_label = None
        self.analysis_start_line = None
        self.analysis_end_line = None
        self.analysis_start_label = None
        self.analysis_end_label = None
        self.wake_up_regions = []
        self.chart_pins = []
        self.cursor_a_index = None
        self.cursor_b_index = None
        self.cursor_a_line = None
        self.cursor_b_line = None
        self.cursor_a_marker = None
        self.cursor_b_marker = None
        self.cursor_a_label = None
        self.cursor_b_label = None
        self.chart_time_seconds = np.array([], dtype=float)
        self.chart_current_ma = np.array([], dtype=float)
        self.chart_source_times = np.array([], dtype=object)
        self._chart_user_zoomed = False
        self._hover_sample = None
        self._y_axis_inverted = False
        self._chart_scrollbar_updating = False
        self._chart_xrange_updating = False
        self._chart_user_zoomed = False
        self._selected_review_chart_index = None
        self._chart_x_min = 0.0
        self._chart_x_max = 0.0
        self._chart_visible_span = CHART_SCROLL_VISIBLE_SECONDS
        self._setup_ui()
        self._initialize_database()
        self._connect_signals()
        self.fn_refresh_theme()
        self._update_action_states()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        # Top: Analysis Settings + Actions
        self.settings_group = self._create_settings_group()
        self.actions_group = self._create_actions_group()

        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(12)

        top_layout.addWidget(self.settings_group, 9)
        top_layout.addWidget(self.actions_group, 2)

        main_layout.addLayout(top_layout)

        # Bottom: Data Review + Chart + Summary
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)

        self.review_group = self._create_review_group()
        self.chart_group = self._create_chart_group()
        self.right_panel = self._create_right_panel()

        self.main_splitter.addWidget(self.review_group)
        self.main_splitter.addWidget(self.chart_group)
        self.main_splitter.addWidget(self.right_panel)
        self.main_splitter.setSizes([260, 720, 220])
       

        main_layout.addWidget(self.main_splitter, 1)

   

    def _initialize_database(self):
        ensure_database_directory(self._database_dir)

    def _connect_signals(self):
        self.browse_button.clicked.connect(self.browse_current_file)
        self.import_button.clicked.connect(self.import_current_file)
        self.btn_run.clicked.connect(self.run_current_analysis)
        self.btn_export.clicked.connect(self.export_q_current_report)
        self.btn_clear.clicked.connect(self.clear_current_workspace)
        self.save_config_button.clicked.connect(self.save_current_config)
        self.btn_capture_chart.clicked.connect(self.capture_current_chart)
        self.btn_pin.clicked.connect(self.pin_selected_review_sample)
        self.btn_invert_y_axis.clicked.connect(self.toggle_y_axis_inversion)
        self.btn_fit_all.clicked.connect(self._fit_all_current_chart)
        self.current_plot.customContextMenuRequested.connect(
            self.show_chart_context_menu
        )
        self.review_table.customContextMenuRequested.connect(
            self.show_review_context_menu
        )
        self.btn_copy_data_review.clicked.connect(self.copy_data_review)
        self.btn_copy_summary.clicked.connect(self.copy_summary)
        self.chart_scrollbar.valueChanged.connect(
            self._on_chart_scrollbar_changed
        )
        self.review_table.clicked.connect(
            lambda index: self._on_review_row_selected(index.row(), index.column())
        )
        self.current_plot.getPlotItem().getViewBox().sigXRangeChanged.connect(
            self._on_chart_x_range_changed
        )
        self.current_limit_edit.valueChanged.connect(
            self.update_sleep_limit_lines
        )
        self.wake_limit_edit.valueChanged.connect(self._mark_analysis_not_run)
        self.wake_duration_edit.valueChanged.connect(self._mark_analysis_not_run)
        self.sampling_duration_checkbox.toggled.connect(
            self._on_sampling_duration_toggled
        )
        self.sampling_duration_edit.valueChanged.connect(
            self._on_sampling_duration_changed
        )
        self.analysis_start_time_edit.valueChanged.connect(
            self._on_analysis_start_time_changed
        )
        self.analysis_end_time_edit.valueChanged.connect(
            self._on_analysis_end_time_changed
        )

        self.dataset_combo.currentIndexChanged.connect(
            self._on_dataset_changed
        )
    
   
    
    def _create_dataset_widgets(self):
        self.source_file_edit = PrimaryLineEdit(
            placeholder=SOURCE_FILE_PLACEHOLDER,
        )
        self.source_file_edit.setObjectName("source_file_edit")
        self.source_file_edit.setReadOnly(True)
        self.source_file_edit.setToolTip("")

        self.browse_button = PrimaryButton(
            "Browse",
            width=90,
            height=36,
        )
        self.browse_button.setObjectName("browse_button")

        self.dataset_combo = QCurrentDatasetComboBox(
            self._refresh_dataset_combo
        )
        self.dataset_combo.setPlaceholderText("")
        self.dataset_combo.setCurrentIndex(-1)
        self.dataset_combo.setObjectName("dataset_combo")
        self.dataset_combo.setMinimumWidth(220)
        self.dataset_combo.setFixedHeight(36)

        self.import_button = PrimaryButton(
            "Import",
            width=90,
            height=36,
        )
        self.import_button.setObjectName("import_button")
        self.import_button.setEnabled(True)

    def _create_settings_group(self):
        group = QGroupBox("Analysis Settings")

        self._create_settings_widgets()

        self.settings_layout = QHBoxLayout(group)
        self.settings_layout.setContentsMargins(12, 16, 12, 12)
        self.settings_layout.setSpacing(36)

        self.config_widget = self._create_config_layout()
        self.dataset_widget = self._create_dataset_layout()

        self.settings_layout.addWidget(self.config_widget, 1)
        self.settings_layout.addWidget(self.dataset_widget, 2)

        return group
    
    def _create_settings_widgets(self):
        self._create_dataset_widgets()
        self._create_config_widgets()
        self._create_analysis_widgets()
    
    def _create_config_layout(self):
        widget = QWidget()

        layout = QGridLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(8)

        # Row 0: Sleep limit | Sampling Duration
        layout.addWidget(self.current_limit_label, 0, 0)
        layout.addWidget(self.current_limit_edit, 0, 1)

        layout.addWidget(self.sampling_duration_checkbox, 0, 2)
        layout.addWidget(self.sampling_duration_edit, 0, 3)

        # Row 1: Wake-up limit | Wake duration
        layout.addWidget(self.wake_limit_label, 1, 0)
        layout.addWidget(self.wake_limit_edit, 1, 1)

        layout.addWidget(self.wake_duration_label, 1, 2)
        layout.addWidget(self.wake_duration_edit, 1, 3)

        # Row 2: Save Config
        layout.addWidget(
            self.save_config_button,
            2, 0, 1, 4,
            Qt.AlignLeft,
        )
        

        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 0)
        layout.setColumnStretch(2, 1)
        layout.setColumnStretch(3, 0)

        return widget
    
    def _create_dataset_layout(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Row 0: Select file and import
        file_layout = QHBoxLayout()
        file_layout.setSpacing(8)

        file_layout.addWidget(self.source_file_edit, 1)
        file_layout.addWidget(self.browse_button)
        file_layout.addWidget(self.dataset_combo)
        file_layout.addWidget(self.import_button)

        layout.addLayout(file_layout)

        # Row 1: Analysis time range
        time_layout = QHBoxLayout()
        time_layout.setSpacing(8)

        time_layout.addWidget(self.analysis_start_time_label)
        time_layout.addWidget(self.analysis_start_time_edit)
        time_layout.addSpacing(12)
        time_layout.addWidget(self.analysis_end_time_label)
        time_layout.addWidget(self.analysis_end_time_edit)
        time_layout.addStretch()

        layout.addLayout(time_layout)

        # Row 2: Analysis result
        result_layout = QHBoxLayout()
        result_layout.setSpacing(8)

        result_layout.addWidget(self.analysis_result_label)
        result_layout.addWidget(self.analysis_progress_bar)
        result_layout.addStretch()

        layout.addLayout(result_layout)
        layout.addStretch()

        return widget
    
    def _create_config_widgets(self):
        # Sleep limit
        self.current_limit_label = PrimaryLabel("Sleep limit (mA)")

        self.current_limit_edit = QDoubleSpinBox()
        self.current_limit_edit.setObjectName("current_limit_edit")
        self.current_limit_edit.setDecimals(1)
        self.current_limit_edit.setMinimum(0.0)
        self.current_limit_edit.setMaximum(1000000.0)
        self.current_limit_edit.setSingleStep(0.5)
        self.current_limit_edit.setValue(
            self.q_current_config.standard_current_ma
        )
        self.current_limit_edit.setFixedWidth(110)
        self.current_limit_edit.setMinimumHeight(36)
        self.current_limit_edit.lineEdit().setAlignment(Qt.AlignCenter)

        # Wake-up limit
        self.wake_limit_label = PrimaryLabel("Wake Up limit (mA)")

        self.wake_limit_edit = QDoubleSpinBox()
        self.wake_limit_edit.setObjectName("wake_limit_edit")
        self.wake_limit_edit.setDecimals(1)
        self.wake_limit_edit.setMinimum(0.0)
        self.wake_limit_edit.setMaximum(1000000.0)
        self.wake_limit_edit.setSingleStep(0.5)
        self.wake_limit_edit.setValue(
            self.q_current_config.wake_up_limit_ma
        )
        self.wake_limit_edit.setFixedWidth(110)
        self.wake_limit_edit.setMinimumHeight(36)
        self.wake_limit_edit.lineEdit().setAlignment(Qt.AlignCenter)

        # Wake duration
        self.wake_duration_label = PrimaryLabel("Wake duration (s)")

        self.wake_duration_edit = QDoubleSpinBox()
        self.wake_duration_edit.setObjectName("wake_duration_edit")
        self.wake_duration_edit.setDecimals(1)
        self.wake_duration_edit.setMinimum(0.1)
        self.wake_duration_edit.setMaximum(1000000.0)
        self.wake_duration_edit.setSingleStep(0.5)
        self.wake_duration_edit.setValue(
            self.q_current_config.wake_duration_s
        )
        self.wake_duration_edit.setFixedWidth(110)
        self.wake_duration_edit.setMinimumHeight(36)
        self.wake_duration_edit.lineEdit().setAlignment(Qt.AlignCenter)

        # Sampling duration
        self.sampling_duration_checkbox = PrimaryCheckBox(
            "Sampling Duration (min)"
        )
        self.sampling_duration_checkbox.setObjectName(
            "sampling_duration_checkbox"
        )
        self.sampling_duration_checkbox.setChecked(
            self.q_current_config.sampling_duration_enabled
        )

        self.sampling_duration_edit = QDoubleSpinBox()
        self.sampling_duration_edit.setObjectName(
            "sampling_duration_edit"
        )
        self.sampling_duration_edit.setDecimals(0)
        self.sampling_duration_edit.setMinimum(5.0)
        self.sampling_duration_edit.setMaximum(1000000.0)
        self.sampling_duration_edit.setSingleStep(5.0)
        self.sampling_duration_edit.setValue(
            self.q_current_config.sampling_duration_min
        )
        self.sampling_duration_edit.setFixedWidth(110)
        self.sampling_duration_edit.setMinimumHeight(36)
        self.sampling_duration_edit.setEnabled(
            self.q_current_config.sampling_duration_enabled
        )
        self.sampling_duration_edit.lineEdit().setAlignment(
            Qt.AlignCenter
        )

        # Save Config
        self.save_config_button = PrimaryButton(
            "SAVE CONFIG",
            width=120,
            height=36,
        )
        self.save_config_button.setObjectName("save_config_button")
    
    def _create_analysis_widgets(self):
        # Analysis result
        self.analysis_result_label = PrimaryLabel(
            "STATUS:       "
        )

        self.analysis_progress_bar = QCurrentProgressBar()
        self._set_analysis_result("NOT RUN")

        # Analysis start time
        self.analysis_start_time_label = PrimaryLabel(
            "Start time (s)"
        )
        self.analysis_start_time_edit = (
            self._create_analysis_range_spinbox(
                "analysis_start_time_edit"
            )
        )

        # Analysis end time
        self.analysis_end_time_label = PrimaryLabel(
            "End time (s)"
        )
        self.analysis_end_time_edit = (
            self._create_analysis_range_spinbox(
                "analysis_end_time_edit"
            )
        )
    
    def _on_dataset_changed(self, index):
        if index < 0:
            return

        if not self.dataset_combo.currentData():
            return

        self.load_selected_dataset()

    def _create_analysis_range_spinbox(self, object_name):
        spinbox = QDoubleSpinBox()
        spinbox.setObjectName(object_name)
        spinbox.setDecimals(2)
        spinbox.setMinimum(0.0)
        spinbox.setMaximum(0.0)
        spinbox.setSingleStep(0.1)
        spinbox.setValue(0.0)
        spinbox.setFixedWidth(110)
        spinbox.setMinimumHeight(36)
        spinbox.setEnabled(False)
        spinbox.lineEdit().setAlignment(Qt.AlignCenter)
        return spinbox

    def _create_chart_group(self):
        group = QGroupBox("Current Chart")
        self.chart_layout = QVBoxLayout(group)
        self.chart_layout.setContentsMargins(12, 16, 12, 12)
        self.chart_layout.setSpacing(8)

        self.chart_header_layout = QGridLayout()
        self.chart_header_layout.setContentsMargins(0, 0, 0, 0)
        self.chart_header_layout.setHorizontalSpacing(16)
        self.chart_header_layout.setVerticalSpacing(4)

        self.chart_toolbar_layout = QHBoxLayout()
        self.chart_toolbar_layout.setContentsMargins(0, 0, 0, 0)
        self.chart_toolbar_layout.setSpacing(8)
        self.btn_pin = QuickAccessButton(
            "Pin",
            width=70,
            height=30,
        )
        self.btn_pin.setObjectName("btn_pin")
        self.btn_invert_y_axis = QuickAccessButton(
            "Invert Y Axis",
            width=120,
            height=30,
        )
        self.btn_invert_y_axis.setObjectName("btn_invert_y_axis")
        self.btn_fit_all = QuickAccessButton(
            "Fit All",
            width=80,
            height=30,
        )
        self.btn_fit_all.setObjectName("btn_fit_all")
        self.btn_capture_chart = QuickAccessButton(
            "Capture",
            width=90,
            height=30,
        )
        self.btn_capture_chart.setObjectName("btn_capture_chart")
        self.chart_toolbar_layout.addWidget(self.btn_pin)
        self.chart_toolbar_layout.addWidget(self.btn_invert_y_axis)
        self.chart_toolbar_layout.addWidget(self.btn_fit_all)
        self.chart_toolbar_layout.addWidget(self.btn_capture_chart)
        self.chart_toolbar_layout.addStretch(1)

        self.legend_layout = QHBoxLayout()
        self.legend_layout.setContentsMargins(0, 0, 0, 0)
        self.legend_layout.setSpacing(18)
        self.legend_items = self._create_chart_legend_items()
        for legend_item in self.legend_items:
            self.legend_layout.addWidget(legend_item)
        self.legend_layout.addStretch(1)

        self.cursor_values_layout = QHBoxLayout()
        self.cursor_values_layout.setContentsMargins(0, 0, 0, 0)
        self.cursor_values_layout.setSpacing(18)
        self.cursor_a_value_label = PrimaryLabel("A: — | —")
        self.cursor_b_value_label = PrimaryLabel("B: — | —")
        self.cursor_values_layout.addWidget(self.cursor_a_value_label)
        self.cursor_values_layout.addWidget(self.cursor_b_value_label)
        self.cursor_values_layout.addStretch(1)
        self._theme_widgets.extend([
            self.cursor_a_value_label,
            self.cursor_b_value_label,
        ])

        self.cursor_delta_layout = QHBoxLayout()
        self.cursor_delta_layout.setContentsMargins(0, 0, 0, 0)
        self.cursor_delta_layout.setSpacing(12)
        self.cursor_delta_time_label = PrimaryLabel("Δt: —")
        self.cursor_delta_current_label = PrimaryLabel("ΔI: —")
        self.cursor_delta_layout.addWidget(self.cursor_delta_time_label)
        self.cursor_delta_layout.addWidget(self.cursor_delta_current_label)
        self.cursor_delta_layout.addStretch(1)
        self._theme_widgets.extend([
            self.cursor_delta_time_label,
            self.cursor_delta_current_label,
        ])

        self.chart_header_layout.addLayout(self.chart_toolbar_layout, 0, 0)
        self.chart_header_layout.addLayout(self.legend_layout, 0, 2)
        self.chart_header_layout.addLayout(self.cursor_values_layout, 1, 0)
        self.chart_header_layout.addLayout(self.cursor_delta_layout, 1, 2)
        self.chart_header_layout.setColumnStretch(0, 0)
        self.chart_header_layout.setColumnStretch(1, 1)
        self.chart_header_layout.setColumnStretch(2, 0)

        self.chart_content_layout = QVBoxLayout()
        self.chart_content_layout.setContentsMargins(0, 0, 0, 0)
        self.chart_placeholder = self._create_placeholder_panel()
        self.current_plot = self._create_current_plot()
        self.current_plot.hide()
        self.chart_content_layout.addWidget(self.chart_placeholder, 1)
        self.chart_content_layout.addWidget(self.current_plot, 1)

        self.chart_scrollbar = QScrollBar(Qt.Horizontal)
        self.chart_scrollbar.setObjectName("chart_scrollbar")
        self.chart_scrollbar.setSingleStep(CHART_SCROLL_SCALE)
        self.chart_scrollbar.setPageStep(
            int(CHART_SCROLL_VISIBLE_SECONDS * CHART_SCROLL_SCALE)
        )
        self.chart_scrollbar.hide()
        self.chart_content_layout.addWidget(self.chart_scrollbar)

        self.chart_layout.addLayout(self.chart_header_layout)
        self.chart_layout.addLayout(self.chart_content_layout, 1)
        return group

    def _create_chart_legend_items(self):
        return [
            self._create_legend_item(
                "Current",
                "line-solid",
                "Gia tri dong dien thuc te",
            ),
            self._create_legend_item(
                "Sleep threshold",
                "line-dashed",
                "Nguong dong ngu do nguoi dung cai dat",
            ),
            self._create_legend_item(
                "Wake-up",
                "dot",
                "Nguong tham chieu wake-up",
            ),
        ]

    def _create_legend_item(self, text, marker_type, tooltip):
        item = QWidget()
        item.setToolTip(tooltip)
        layout = QHBoxLayout(item)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        marker = QLabel()
        marker.setObjectName(f"legend_marker_{marker_type}")
        marker.setFixedSize(34, 14)
        marker.setToolTip(tooltip)
        label = PrimaryLabel(text)
        label.setToolTip(tooltip)
        layout.addWidget(marker)
        layout.addWidget(label)
        item.marker = marker
        item.label = label
        item.marker_type = marker_type
        item.legend_text = text
        self._theme_widgets.append(label)
        return item

    def _create_current_plot(self):
        plot = pg.PlotWidget()
        plot.setBackground(None)
        plot.setLabel("bottom", "Time (s)")
        plot.setLabel("left", "Current (mA)")
        plot_item = plot.getPlotItem()
        # Hide PyQtGraph built-in auto-range button.
        plot_item.hideButtons()
        plot_item.getAxis("bottom").enableAutoSIPrefix(False)
        plot_item.getAxis("left").enableAutoSIPrefix(False)
        plot.showGrid(x=True, y=True, alpha=0.25)
        plot.setMouseEnabled(x=True, y=True)
        plot.setMenuEnabled(False)
        plot.setContextMenuPolicy(Qt.CustomContextMenu)

        colors = self._chart_colors()
        self.upper_sleep_limit_line = pg.InfiniteLine(
            pos=abs(self.current_limit_edit.value()),
            angle=0,
            movable=False,
            pen=pg.mkPen(colors["sleep"], width=1.5, style=Qt.DashLine),
        )
        self.lower_sleep_limit_line = pg.InfiniteLine(
            pos=-abs(self.current_limit_edit.value()),
            angle=0,
            movable=False,
            pen=pg.mkPen(colors["sleep"], width=1.5, style=Qt.DashLine),
        )
        self.upper_sleep_limit_line.setZValue(5)
        self.lower_sleep_limit_line.setZValue(5)
        plot.addItem(self.upper_sleep_limit_line)
        plot.addItem(self.lower_sleep_limit_line)

        self.current_curve = plot.plot(
            [],
            [],
            pen=pg.mkPen(colors["current"], width=2),
        )
        self.current_curve.setZValue(20)
        self.current_curve.setClipToView(True)
        self.current_curve.setDownsampling(auto=True, method="peak")

        self.hover_marker = pg.ScatterPlotItem(
            [],
            [],
            symbol="s",
            size=8,
            brush=pg.mkBrush(colors["hover_marker"]),
            pen=pg.mkPen(colors["hover_marker_border"], width=1),
        )
        self.hover_marker.setZValue(30)
        self.hover_marker.hide()
        plot.addItem(self.hover_marker)

        self.hover_label = pg.TextItem(anchor=(0, 1))
        self.hover_label.setZValue(40)
        self.hover_label.hide()
        plot.addItem(self.hover_label)

        self._create_analysis_range_graphics(plot)
        self._create_cursor_graphics(plot, "a")
        self._create_cursor_graphics(plot, "b")

        self._mouse_move_proxy = pg.SignalProxy(
            plot.scene().sigMouseMoved,
            rateLimit=60,
            slot=self._update_hover_coordinates,
        )
        plot_item.vb.sigRangeChanged.connect(self.position_chart_pin_labels)
        plot_item.vb.sigRangeChanged.connect(self.position_analysis_range_labels)
        return plot

    def _create_review_group(self):
        group = QGroupBox("Data Review")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(12, 16, 12, 12)
        self.review_table = self._create_review_table()
        layout.addWidget(self.review_table, 1)
        return group

    
    def _create_actions_group(self):
        panel = QWidget()
        panel.setObjectName("q_current_actions_panel")

        panel.setMinimumWidth(240)
        panel.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Preferred,
        )

        layout = QGridLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(18)
        layout.setVerticalSpacing(6)

        self.btn_run = PrimaryButton("RUN")
        self.btn_copy_data_review = PrimaryButton("COPY Data Review")
        self.btn_copy_summary = PrimaryButton("COPY Summary")
        self.btn_export = PrimaryButton("EXPORT")
        self.btn_clear = PrimaryButton("CLEAR")

        buttons = (
            self.btn_run,
            self.btn_copy_data_review,
            self.btn_copy_summary,
            self.btn_export,
            self.btn_clear,
        )

        for button in buttons:
            button.setSizePolicy(
                QSizePolicy.Expanding,
                QSizePolicy.Fixed,
            )
            button.setFixedHeight(42)

        # Row 0: RUN full width
        layout.addWidget(self.btn_run, 0, 0, 1, 2)

        # Row 1: Copy buttons
        layout.addWidget(self.btn_copy_data_review, 1, 0)
        layout.addWidget(self.btn_copy_summary, 1, 1)

        # Row 2: Export and Clear
        layout.addWidget(self.btn_export, 2, 0)
        layout.addWidget(self.btn_clear, 2, 1)

        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)

        return panel
   
   
    def _create_right_panel(self):
        panel = QWidget()
        panel.setMinimumWidth(200)
        panel.setMaximumWidth(360)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.summary_widget = QCurrentSummaryWidget()
        self.summary_group = self.summary_widget

        layout.addWidget(self.summary_widget, 1)

        return panel
    
    
    def _create_placeholder_panel(self):
        label = QLabel(PLACEHOLDER_VALUE)
        label.setFrameShape(QFrame.StyledPanel)
        label.setAlignment(Qt.AlignCenter)
        label.setMinimumHeight(120)
        self._theme_widgets.append(label)
        return label

    def _create_review_table(self):
        table = QCurrentReviewTable()
        table.setObjectName("review_table")
        table.setModel(QCurrentReviewModel(table))
        table.setSortingEnabled(False)
        table.setContextMenuPolicy(Qt.CustomContextMenu)

        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        return table

    def browse_current_file(self):
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Select Current Data File",
            "",
            SOURCE_FILE_FILTER,
        )
        if not file_path:
            return

        self.set_source_file(file_path)

    def set_source_file(self, file_path: str | Path):
        if self._operation_running:
            return
        path = Path(file_path).expanduser().resolve()
        path_text = str(path)
        self.source_file_edit.setText(path_text)
        self.source_file_edit.setToolTip(path_text)
        self.import_button.setEnabled(True)

    def _set_analysis_result(self, text):
        self.analysis_progress_bar.set_status(text)

    def _refresh_analysis_result_style(self):
        self.analysis_progress_bar.fn_refresh_theme()

    def clear_source_file_selection(self):
        self.source_file_edit.clear()
        self.source_file_edit.setToolTip("")
        self.import_button.setEnabled(True)

    def _set_task_busy(self, busy):
        self._operation_running = busy
        for control in (
            self.browse_button, self.import_button, self.dataset_combo,
            self.current_limit_edit, self.wake_limit_edit, self.wake_duration_edit,
            self.sampling_duration_checkbox, self.sampling_duration_edit,
            self.analysis_start_time_edit, self.analysis_end_time_edit,
            self.save_config_button,
        ):
            control.setEnabled(not busy)
        for group in (self.actions_group, self.chart_group, self.review_group):
            group.setEnabled(not busy)
        if not busy:
            self._apply_sampling_duration_mode(mark_not_run=False)
        self._update_action_states()

    def _begin_operation(self, state):
        if state == "IMPORTING":
            self.last_loading_timings = {}
        self._task_error_state = "IMPORT FAILED" if state == "IMPORTING" else "ANALYSIS ERROR"
        self._task_error_title = "Q current Import" if state == "IMPORTING" else "Q current Chart"
        self._set_task_busy(True)
        self._set_analysis_result(state)

    def _start_task(self, operation, on_success):
        self._task_success = on_success
        self._task_runner.start(operation)

    def _task_finished(self, result):
        callback = self._task_success
        self._task_success = None
        try:
            callback(result)
        except Exception as error:
            self._task_failed(str(error))
        finally:
            if not self._task_runner.running:
                self._set_task_busy(False)

    def _task_failed(self, message):
        self._task_success = None
        self._set_analysis_result(self._task_error_state)
        self._set_task_busy(False)
        QMessageBox.warning(self, self._task_error_title, message)

    def import_current_file(self):
        if self._operation_running:
            return
        source_text = self.source_file_edit.text().strip()
        if not source_text:
            self.load_selected_dataset()
            return

        previous_state = self.analysis_progress_bar.state
        self._begin_operation("IMPORTING")
        try:
            source_path = Path(source_text).expanduser().resolve()
            dataset_name = default_dataset_name(source_path)
            database_path = database_path_for_source(source_path, self._database_dir)
        except Exception as error:
            self._task_failed(str(error))
            return

        self._start_task(
            partial(timed_call, self.last_loading_timings, "file_parse_s", normalize_current_data, source_path),
            partial(self._confirm_current_import, source_path, dataset_name, database_path, previous_state),
        )

    def _confirm_current_import(self, source_path, dataset_name, database_path, previous_state, normalized):
        if database_path.exists():
            response = QMessageBox.question(
                self,
                "Replace Dataset",
                (
                    f"Database '{database_path.name}' already exists.\n"
                    "Replace it with the selected file?"
                ),
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                QMessageBox.No,
            )
            if response != QMessageBox.Yes:
                self._set_analysis_result(previous_state)
                return

        timings = self.last_loading_timings
        database_dir = self._database_dir

        def import_and_load():
            result = timed_call(timings, "sqlite_write_s", import_dataset,
                dataset_name,
                source_path,
                normalized.rows,
                database_path,
                detected_channel=normalized.detected_channel,
            )
            path = result.dataset.database_path or database_path
            samples = timed_call(timings, "sqlite_read_s", get_samples, result.dataset.id, path)
            prepared = timed_call(timings, "prepare_s", prepare_workspace_data, samples)
            datasets = timed_call(timings, "catalog_s", list_datasets, database_dir)
            return result, path, prepared, datasets

        self._start_task(import_and_load, self._current_import_finished)

    def _current_import_finished(self, imported):
        result, database_path, prepared, datasets = imported
        self.current_import = result
        self.current_database_path = database_path
        self._load_samples_into_workspace(prepared)
        self._refresh_dataset_combo(selected_db_path=self.current_database_path, datasets=datasets)
        self.clear_source_file_selection()
        self._set_analysis_result("IMPORTED")
        QMessageBox.information(
            self,
            "Q current Import",
            (
                f"Imported {result.row_count} rows.\n"
                f"Dataset: {result.dataset.name}\n"
                f"Channel: {result.dataset.detected_channel}\n"
                f"Database: {self.current_database_path}"
            ),
        )

    def load_selected_dataset(self):
        if self._operation_running:
            return
        database_value = self.dataset_combo.currentData()
        if not database_value:
            QMessageBox.warning(
                self,
                "Q current Import",
                "Select an imported Q current dataset.",
            )
            return

        self._begin_operation("IMPORTING")
        timings = self.last_loading_timings

        def load_dataset():
            database_path = Path(database_value).expanduser().resolve()
            dataset = timed_call(timings, "sqlite_metadata_s", get_primary_dataset, database_path)
            if dataset is None:
                raise ValueError(f"Q current database is not valid: {database_path}")
            path = dataset.database_path or database_path
            samples = timed_call(timings, "sqlite_read_s", get_samples, dataset.id, path)
            prepared = timed_call(timings, "prepare_s", prepare_workspace_data, samples)
            return path, prepared

        self._start_task(load_dataset, self._current_dataset_loaded)

    def _current_dataset_loaded(self, loaded):
        database_path, prepared = loaded
        self.current_import = None
        self.current_database_path = database_path
        self._load_samples_into_workspace(prepared)
        self._set_analysis_result("IMPORTED")
        self.import_button.setEnabled(True)

    def _load_samples_into_workspace(self, samples):
        started = perf_counter()
        prepared = samples if isinstance(samples, QCurrentWorkspaceData) else prepare_workspace_data(samples)
        self._workspace_data = prepared
        self.current_samples = prepared.samples
        self.current_analysis_result = None
        self.current_analysis_settings = None
        self._selected_review_chart_index = None
        self._chart_ready = False
        self._clear_current_chart()
        self.summary_widget.clear_result()

        # Reset Analysis Range from the previous dataset.
        self._reset_analysis_range_controls()

        self._populate_review_table(self.current_samples)
        self._initialize_analysis_range_from_samples()
        self._update_action_states()
        self.last_loading_timings["workspace_gui_s"] = perf_counter() - started

    def _get_elapsed_seconds(self):
        prepared = self._workspace_data
        if prepared is not None and prepared.samples is self.current_samples:
            if prepared.timestamp_error is not None:
                raise ValueError(prepared.timestamp_error)
            return prepared.elapsed_seconds
        return calculate_elapsed_seconds(self.current_samples)

    def _update_action_states(self):
        has_data = bool(self.current_samples)
        has_chart = self._chart_ready
        has_analysis = self.current_analysis_result is not None
        self.btn_run.setEnabled(has_data)
        self.btn_copy_data_review.setEnabled(has_data)
        self.btn_clear.setEnabled(has_data)
        self.btn_export.setEnabled(has_analysis)
        can_pin = has_chart and self._selected_review_chart_index is not None
        self.btn_pin.setEnabled(can_pin)
        self.btn_capture_chart.setEnabled(has_chart)
        self.btn_invert_y_axis.setEnabled(has_chart)
        self.btn_fit_all.setEnabled(has_chart)
        self.btn_copy_summary.setEnabled(has_analysis)

    def run_current_analysis(self):
        if self._operation_running:
            return
        if not self.current_samples:
            self._update_action_states()
            return
        self._selected_review_chart_index = None
        self._begin_operation("ANALYZING")
        try:
            elapsed_seconds, current_values = self._build_chart_data()
            (
                analysis_elapsed_seconds,
                analysis_current_values,
                analysis_source_times,
            ) = self._build_analysis_data(elapsed_seconds, current_values)
            operation = partial(
                analyze_q_current,
                analysis_elapsed_seconds,
                analysis_current_values,
                self.current_limit_edit.value(),
                self.wake_limit_edit.value(),
                self.wake_duration_edit.value(),
                source_times=analysis_source_times,
            )
            settings = QCurrentReportSettings(
                standard_current_ma=self.current_limit_edit.value(),
                wake_up_limit_ma=self.wake_limit_edit.value(),
                wake_duration_s=self.wake_duration_edit.value(),
                analysis_start_time_s=self.analysis_start_time_edit.value(),
                analysis_end_time_s=self._effective_analysis_end_time_s(),
                sampling_duration_enabled=self.sampling_duration_checkbox.isChecked(),
                sampling_duration_min=self.sampling_duration_edit.value(),
            )
        except Exception as error:
            self._task_failed(str(error))
            return

        self._start_task(operation, partial(self._current_analysis_finished, elapsed_seconds, current_values, settings))

    def _current_analysis_finished(self, elapsed_seconds, current_values, settings, analysis_result):
        self._update_current_chart(
            elapsed_seconds,
            current_values,
            analysis_result.wake_up_intervals,
        )
        self.summary_widget.set_result(
            analysis_result,
            dataset_samples=len(self.current_samples),
        )
        self.current_analysis_result = analysis_result
        self.current_analysis_settings = settings
        self._chart_ready = True
        self._set_analysis_result(analysis_result.result_status)
        self._update_action_states()

    def clear_current_workspace(self):
        if self._operation_running:
            return
        self.current_import = None
        self.current_database_path = None
        self.current_samples = []
        self._workspace_data = None
        self.current_analysis_result = None
        self.current_analysis_settings = None
        self._selected_review_chart_index = None
        self._chart_ready = False
        self.review_table.model().set_samples([])
        self._clear_current_chart()
        self._reset_analysis_range_controls()
        self.summary_widget.clear_result()
        self._set_analysis_result("NOT RUN")
        self._update_action_states()

    def _build_chart_data(self):
        elapsed_seconds = self._get_elapsed_seconds()
        if not elapsed_seconds:
            raise ValueError("Q current data contains no valid timestamps.")
        current_values = [float(sample.current_mA) for sample in self.current_samples]
        if len(elapsed_seconds) != len(current_values):
            raise ValueError("Q current chart data is not aligned.")
        return elapsed_seconds, current_values

    def _build_analysis_data(self, elapsed_seconds, current_values):
        start_time_s = float(self.analysis_start_time_edit.value())
        end_time_s = float(self._effective_analysis_end_time_s())
        available_end_time_s = float(max(elapsed_seconds))
        if (
            start_time_s > end_time_s
            or (len(elapsed_seconds) > 1 and start_time_s >= end_time_s)
        ):
            raise ValueError("Start Time must be less than End Time.")
        if end_time_s > available_end_time_s:
            if self.sampling_duration_checkbox.isChecked():
                raise ValueError(
                    "Insufficient data for the selected sampling duration.\n\n"
                    f"Start Time: {start_time_s:.2f} s\n"
                    f"Sampling Duration: {self.sampling_duration_edit.value():.0f} min\n"
                    f"Required End Time: {end_time_s:.2f} s\n"
                    f"Available End Time: {available_end_time_s:.2f} s"
                )
            raise ValueError("End Time must be inside the available dataset range.")

        filtered_elapsed_seconds = []
        filtered_current_values = []
        filtered_source_times = []
        for elapsed_s, current_ma, sample in zip(
            elapsed_seconds,
            current_values,
            self.current_samples,
        ):
            elapsed_s = float(elapsed_s)
            if start_time_s <= elapsed_s <= end_time_s:
                filtered_elapsed_seconds.append(elapsed_s)
                filtered_current_values.append(float(current_ma))
                filtered_source_times.append(sample.time)

        if not filtered_elapsed_seconds:
            raise ValueError("No samples exist inside the selected analysis range.")
        return filtered_elapsed_seconds, filtered_current_values, filtered_source_times

    def _reset_analysis_range_controls(self):
        if not hasattr(self, "analysis_start_time_edit"):
            return
        for spinbox in (
            self.analysis_start_time_edit,
            self.analysis_end_time_edit,
        ):
            blocker = QSignalBlocker(spinbox)
            spinbox.setMaximum(0.0)
            spinbox.setValue(0.0)
            spinbox.setEnabled(False)
            del blocker

    def _initialize_analysis_range_from_samples(self):
        prepared = self._workspace_data
        if prepared is None or prepared.time_bounds is None:
            self._reset_analysis_range_controls()
            return
        start_time_s, end_time_s = prepared.time_bounds
        calculated_end_time_s = start_time_s + self.sampling_duration_edit.value() * 60.0
        maximum_time_s = max(end_time_s, calculated_end_time_s, 0.0)
        for spinbox in (self.analysis_start_time_edit, self.analysis_end_time_edit):
            blocker = QSignalBlocker(spinbox)
            spinbox.setMaximum(maximum_time_s)
            del blocker
        start_blocker = QSignalBlocker(self.analysis_start_time_edit)
        self.analysis_start_time_edit.setValue(start_time_s)
        self.analysis_start_time_edit.setEnabled(True)
        del start_blocker
        end_blocker = QSignalBlocker(self.analysis_end_time_edit)
        self.analysis_end_time_edit.setValue(end_time_s)
        del end_blocker
        self._apply_sampling_duration_mode(mark_not_run=False)

    def _effective_analysis_end_time_s(self):
        if self.sampling_duration_checkbox.isChecked():
            return (
                self.analysis_start_time_edit.value()
                + self.sampling_duration_edit.value() * 60.0
            )
        return self.analysis_end_time_edit.value()

    def _update_calculated_end_time(self):
        if not self.sampling_duration_checkbox.isChecked():
            return
        end_time_s = self._effective_analysis_end_time_s()
        blocker = QSignalBlocker(self.analysis_end_time_edit)
        self.analysis_end_time_edit.setMaximum(
            max(self.analysis_end_time_edit.maximum(), end_time_s)
        )
        self.analysis_end_time_edit.setValue(end_time_s)
        del blocker

    def _apply_sampling_duration_mode(self, mark_not_run=True):
        checked = self.sampling_duration_checkbox.isChecked()
        has_data = bool(self.current_samples)
        self.sampling_duration_edit.setEnabled(checked)
        self.analysis_start_time_edit.setEnabled(has_data)
        self.analysis_end_time_edit.setEnabled(has_data and not checked)
        if checked and has_data:
            self._update_calculated_end_time()
        elif has_data:
            self._clamp_manual_end_time_to_dataset()
        self._update_analysis_range_markers()
        if mark_not_run:
            self._mark_analysis_not_run()


    def _clamp_manual_end_time_to_dataset(self):
        prepared = self._workspace_data
        if prepared is None or prepared.time_bounds is None:
            return
        available_end_time_s = prepared.time_bounds[1]
        if self.analysis_end_time_edit.value() <= available_end_time_s:
            return
        blocker = QSignalBlocker(self.analysis_end_time_edit)
        self.analysis_end_time_edit.setMaximum(
            max(self.analysis_end_time_edit.maximum(), available_end_time_s)
        )
        self.analysis_end_time_edit.setValue(available_end_time_s)
        del blocker

    def _on_sampling_duration_toggled(self, _checked):
        self._apply_sampling_duration_mode(mark_not_run=True)

    def _on_sampling_duration_changed(self, _value):
        if self.sampling_duration_checkbox.isChecked() and self.current_samples:
            self._update_calculated_end_time()
        self._update_analysis_range_markers()
        self._mark_analysis_not_run()

    def _on_analysis_start_time_changed(self, _value):
        if self.sampling_duration_checkbox.isChecked() and self.current_samples:
            self._update_calculated_end_time()
        self._update_analysis_range_markers()
        self._mark_analysis_not_run()

    def _on_analysis_end_time_changed(self, _value):
        self._update_analysis_range_markers()
        self._mark_analysis_not_run()

    def _update_current_chart(self, elapsed_seconds, current_values, wake_up_intervals):
        self.clear_chart_pins()
        time_array = np.asarray(elapsed_seconds, dtype=float)
        current_array = np.asarray(current_values, dtype=float)
        if time_array.size != current_array.size:
            raise ValueError("Q current chart data is not aligned.")
        source_times = np.asarray(
            [sample.time for sample in self.current_samples],
            dtype=object,
        )
        if source_times.size != time_array.size:
            raise ValueError("Q current chart source data is not aligned.")
        order = np.argsort(time_array)
        time_array = time_array[order]
        current_array = current_array[order]
        source_times = source_times[order]
        self.chart_time_seconds = time_array
        self.chart_current_ma = current_array
        self.chart_source_times = source_times

        x_min = float(time_array[0])
        x_max = float(time_array[-1]) if time_array.size > 1 else x_min + 1.0
        self.current_curve.setData(time_array, current_array)
        self.update_sleep_limit_lines(
            self.current_limit_edit.value(),
            mark_not_run=False,
        )
        self.update_wake_up_regions(wake_up_intervals)
        self.hide_hover_items()
        self._update_chart_scrollbar(x_min, x_max)
        self._fit_all_current_chart()
        self._update_analysis_range_markers()

        self.chart_placeholder.hide()
        self.current_plot.show()

    def _fit_all_current_chart(self):
        if self.chart_time_seconds.size == 0:
            return

        x_min = float(self.chart_time_seconds[0])
        x_max = float(self.chart_time_seconds[-1])

        if x_max <= x_min:
            x_max = x_min + 1.0

        self._chart_user_zoomed = False
        self._chart_visible_span = self._chart_scroll_window_seconds()
        self._sync_chart_scrollbar_to_range(self._chart_x_min, self._chart_visible_span)
        self._set_chart_x_range(
            x_min,
            x_max,
            padding=0.02,
        )

        y_min = float(np.min(self.chart_current_ma))
        y_max = float(np.max(self.chart_current_ma))
        if y_max <= y_min:
            y_min -= 1.0
            y_max += 1.0
        self.current_plot.setYRange(y_min, y_max, padding=0.08)
        self.position_chart_pin_labels()
        self.position_analysis_range_labels()

    def _on_review_row_selected(self, row, _column):
        if not self._chart_ready or self.chart_time_seconds.size == 0:
            return
        if not self.current_samples:
            return
        if row < 0 or row >= len(self.current_samples):
            return
        try:
            elapsed_seconds = self._get_elapsed_seconds()
        except ValueError:
            return
        if row >= len(elapsed_seconds):
            return

        target_time_s = float(elapsed_seconds[row])
        chart_index = self.find_nearest_sample_index(target_time_s)
        if chart_index is None:
            return

        self._selected_review_chart_index = chart_index
        time_s = float(self.chart_time_seconds[chart_index])
        current_ma = float(self.chart_current_ma[chart_index])
        self._navigate_chart_to_time(time_s)
        self.update_hover_items(time_s, current_ma)
        self._update_action_states()

    def pin_selected_review_sample(self):
        if not self._chart_ready:
            return False
        sample_index = self._selected_review_chart_index
        if sample_index is None:
            return False
        return self.pin_chart_sample(sample_index)

    def show_review_context_menu(self, position):
        row = self.review_table.rowAt(position.y())
        if row < 0 or row >= len(self.current_samples):
            return
        self.review_table.setCurrentIndex(self.review_table.model().index(row, 0))
        self.review_table.selectRow(row)
        menu, actions = self._create_review_context_menu()
        set_start_action = actions["set_start_time"]
        set_end_action = actions["set_end_time"]
        selected_action = menu.exec(
            self.review_table.viewport().mapToGlobal(position)
        )
        if selected_action is set_start_action:
            self.set_analysis_start_from_review_row(row)
        elif selected_action is set_end_action:
            self.set_analysis_end_from_review_row(row)

    def _create_review_context_menu(self):
        menu = QMenu(self.review_table)
        fn_apply_menu_style(menu)
        actions = {
            "set_start_time": menu.addAction("Set Start Time"),
            "set_end_time": menu.addAction("Set End Time"),
        }
        actions["set_end_time"].setEnabled(
            not self.sampling_duration_checkbox.isChecked()
        )
        return menu, actions

    def set_analysis_start_from_review_row(self, row):
        return self._set_analysis_range_from_review_row(
            row,
            self.analysis_start_time_edit,
        )

    def set_analysis_end_from_review_row(self, row):
        if self.sampling_duration_checkbox.isChecked():
            return False
        return self._set_analysis_range_from_review_row(
            row,
            self.analysis_end_time_edit,
        )

    def _set_analysis_range_from_review_row(self, row, spinbox):
        if row < 0 or row >= len(self.current_samples):
            return False
        try:
            elapsed_seconds = self._get_elapsed_seconds()
        except ValueError:
            return False
        if row >= len(elapsed_seconds):
            return False
        spinbox.setValue(float(elapsed_seconds[row]))
        return True

    def _navigate_chart_to_time(self, time_s):
        if self.chart_time_seconds.size == 0:
            return

        data_min = float(self.chart_time_seconds[0])
        data_max = float(self.chart_time_seconds[-1])
        total_span = data_max - data_min
        if total_span <= 0.0:
            return

        window_seconds = self._active_chart_window_seconds()
        if window_seconds >= total_span:
            new_x_min = data_min
            new_x_max = data_max
        else:
            half_window = window_seconds / 2.0
            new_x_min = float(time_s) - half_window
            new_x_max = float(time_s) + half_window
            if new_x_min < data_min:
                new_x_min = data_min
                new_x_max = data_min + window_seconds
            if new_x_max > data_max:
                new_x_max = data_max
                new_x_min = data_max - window_seconds

        self._sync_chart_scrollbar_to_range(new_x_min, window_seconds)
        self._set_chart_x_range(new_x_min, new_x_max, padding=0)
        self.position_chart_pin_labels()
        self.position_analysis_range_labels()

    def _set_chart_x_range(self, x_min, x_max, padding=0):
        self._chart_xrange_updating = True
        try:
            self.current_plot.setXRange(x_min, x_max, padding=padding)
        finally:
            self._chart_xrange_updating = False

    def _chart_scroll_window_seconds(self):
        total_span = max(0.0, self._chart_x_max - self._chart_x_min)
        return min(
            CHART_SCROLL_VISIBLE_SECONDS,
            total_span if total_span > 0.0 else CHART_SCROLL_VISIBLE_SECONDS,
        )

    def _active_chart_window_seconds(self):
        total_span = max(0.0, self._chart_x_max - self._chart_x_min)
        if total_span <= 0.0:
            return CHART_SCROLL_VISIBLE_SECONDS
        if self._chart_user_zoomed:
            x_range, _y_range = self.current_plot.getPlotItem().viewRange()
            current_width = max(float(x_range[1]) - float(x_range[0]), 1e-9)
            return min(current_width, total_span)
        return self._chart_scroll_window_seconds()

    def _sync_chart_scrollbar_to_range(self, x_min, window_seconds):
        total_span = max(0.0, self._chart_x_max - self._chart_x_min)
        window_seconds = min(max(float(window_seconds), 0.0), total_span)
        max_scroll = max(
            0,
            int(round((total_span - window_seconds) * CHART_SCROLL_SCALE)),
        )
        scroll_value = int(round((float(x_min) - self._chart_x_min) * CHART_SCROLL_SCALE))
        scroll_value = max(0, min(max_scroll, scroll_value))

        self._chart_scrollbar_updating = True
        self.chart_scrollbar.setRange(0, max_scroll)
        self.chart_scrollbar.setPageStep(
            max(1, int(round(window_seconds * CHART_SCROLL_SCALE)))
        )
        self.chart_scrollbar.setSingleStep(CHART_SCROLL_SCALE)
        self.chart_scrollbar.setValue(scroll_value)
        self.chart_scrollbar.setVisible(max_scroll > 0)
        self._chart_scrollbar_updating = False

    def _update_chart_scrollbar(self, x_min, x_max):
        self._chart_x_min = float(x_min)
        self._chart_x_max = float(x_max)
        self._chart_user_zoomed = False
        self._chart_visible_span = self._chart_scroll_window_seconds()
        self._sync_chart_scrollbar_to_range(self._chart_x_min, self._chart_visible_span)
        self._apply_chart_scrollbar_range()

    def _on_chart_x_range_changed(self, *_args):
        if self._chart_xrange_updating or not self._chart_ready:
            return
        if self.chart_time_seconds.size == 0:
            return
        x_range, _y_range = self.current_plot.getPlotItem().viewRange()
        current_width = float(x_range[1]) - float(x_range[0])
        total_span = max(0.0, self._chart_x_max - self._chart_x_min)
        if current_width <= 0.0 or total_span <= 0.0:
            return
        self._chart_user_zoomed = True
        self._sync_chart_scrollbar_to_range(float(x_range[0]), min(current_width, total_span))
        self.position_chart_pin_labels()
        self.position_analysis_range_labels()
    def _on_chart_scrollbar_changed(self, _value=None):
        if self._chart_scrollbar_updating or not self._chart_ready:
            return
        self._apply_chart_scrollbar_range()

    def _apply_chart_scrollbar_range(self):
        total_span = max(0.0, self._chart_x_max - self._chart_x_min)
        if total_span <= 0.0:
            self._set_chart_x_range(
                self._chart_x_min,
                self._chart_x_min + 1.0,
                padding=0.02,
            )
            self.position_chart_pin_labels()
            return

        window_seconds = self._active_chart_window_seconds()
        if self.chart_scrollbar.maximum() <= 0 or window_seconds >= total_span:
            self._set_chart_x_range(
                self._chart_x_min,
                self._chart_x_max,
                padding=0.02,
            )
            self.position_chart_pin_labels()
            self.position_analysis_range_labels()
            return

        start = (
            self._chart_x_min
            + self.chart_scrollbar.value() / CHART_SCROLL_SCALE
        )
        end = start + window_seconds
        if end > self._chart_x_max:
            end = self._chart_x_max
            start = end - window_seconds
        if start < self._chart_x_min:
            start = self._chart_x_min
            end = min(start + window_seconds, self._chart_x_max)
        self._set_chart_x_range(start, end, padding=0)
        self.position_chart_pin_labels()
        self.position_analysis_range_labels()
    def toggle_y_axis_inversion(self):
        self._y_axis_inverted = not self._y_axis_inverted
        self._apply_y_axis_orientation()

    def reset_y_axis_orientation(self):
        self._y_axis_inverted = False
        if hasattr(self, "current_plot"):
            self._apply_y_axis_orientation()

    def _apply_y_axis_orientation(self):
        view_box = self.current_plot.getPlotItem().getViewBox()
        view_box.invertY(self._y_axis_inverted)
        self.position_chart_pin_labels()
        self.position_analysis_range_labels()

    def save_current_config(self):
        config = QCurrentConfig(
            standard_current_ma=self.current_limit_edit.value(),
            wake_up_limit_ma=self.wake_limit_edit.value(),
            wake_duration_s=self.wake_duration_edit.value(),
            sampling_duration_enabled=self.sampling_duration_checkbox.isChecked(),
            sampling_duration_min=self.sampling_duration_edit.value(),
        )
        try:
            save_q_current_config(config, self._config_file)
        except Exception as error:
            QMessageBox.critical(self, "Save Config Error", str(error))
            return False
        self.q_current_config = config
        QMessageBox.information(
            self,
            "Save Config",
            "Q Current configuration saved successfully.",
        )
        return True
    def capture_current_chart(self):
        if not self._chart_ready:
            return False
        pixmap = self.current_plot.grab()
        if pixmap.isNull():
            return False
        QApplication.clipboard().setPixmap(pixmap)
        return True

    def export_q_current_report(self):
        if self.current_analysis_result is None or self.current_analysis_settings is None:
            return None
        report_data = QCurrentReportData(
            dataset_name=self.dataset_combo.currentText(),
            samples=list(self.current_samples),
            analysis_result=self.current_analysis_result,
            settings=self.current_analysis_settings,
            chart_png=self._grab_current_chart_png(),
        )
        try:
            output_file = self.q_current_report_service.fn_export(self, report_data)
        except Exception as error:
            QMessageBox.critical(self, "Export Error", str(error))
            return None
        if output_file is not None:
            show_export_toast(self, output_file, title="Excel report saved")
        return output_file

    def _grab_current_chart_png(self):
        if not self._chart_ready:
            return None
        pixmap = self.current_plot.grab()
        if pixmap.isNull():
            return None
        byte_array = QByteArray()
        buffer = QBuffer(byte_array)
        if not buffer.open(QIODevice.WriteOnly):
            return None
        if not pixmap.save(buffer, "PNG"):
            buffer.close()
            return None
        buffer.close()
        return bytes(byte_array)

    def update_sleep_limit_lines(self, limit_ma, mark_not_run=True):
        if self.upper_sleep_limit_line is None or self.lower_sleep_limit_line is None:
            return
        limit_ma = abs(float(limit_ma))
        self.upper_sleep_limit_line.setValue(limit_ma)
        self.lower_sleep_limit_line.setValue(-limit_ma)
        self._update_sleep_legend_tooltip(limit_ma)
        if mark_not_run:
            self._mark_analysis_not_run()

    def _update_sleep_legend_tooltip(self, limit_ma):
        tooltip = f"Sleep band: -{limit_ma:.1f} mA to +{limit_ma:.1f} mA"
        for item in getattr(self, "legend_items", []):
            if item.legend_text == "Sleep threshold":
                item.setToolTip(tooltip)
                item.marker.setToolTip(tooltip)
                item.label.setToolTip(tooltip)
                break

    def _mark_analysis_not_run(self, *_args):
        if self._operation_running:
            return
        self.current_analysis_result = None
        self.current_analysis_settings = None
        if hasattr(self, "analysis_progress_bar"):
            self._set_analysis_result("NOT RUN")
        if hasattr(self, "summary_widget"):
            self.summary_widget.clear_result()
        if hasattr(self, "btn_export"):
            self._update_action_states()

    def create_wake_up_region(self, start_s, end_s):
        region = pg.LinearRegionItem(
            values=(float(start_s), float(end_s)),
            orientation="vertical",
            movable=False,
            brush=self._transparent_brush(
                self._chart_colors()["wake_fill"],
                70,
            ),
        )
        region.setZValue(-10)
        for line in getattr(region, "lines", []):
            line.setPen(pg.mkPen(None))
            line.setHoverPen(pg.mkPen(None))
            line.setMovable(False)
        return region

    def update_wake_up_regions(self, intervals):
        self.clear_wake_up_regions()
        for interval in intervals:
            region = self.create_wake_up_region(
                interval.start_s,
                interval.end_s,
            )
            self.wake_up_regions.append(region)
            self.current_plot.addItem(region)

    def clear_wake_up_regions(self):
        if not hasattr(self, "current_plot"):
            return
        for region in self.wake_up_regions:
            self.current_plot.removeItem(region)
        self.wake_up_regions = []

    def find_nearest_sample(self, mouse_time_s):
        nearest_index = self.find_nearest_sample_index(mouse_time_s)
        if nearest_index is None:
            return None
        return (
            float(self.chart_time_seconds[nearest_index]),
            float(self.chart_current_ma[nearest_index]),
        )

    def show_chart_context_menu(self, widget_position):
        scene_position = self.current_plot.mapToScene(widget_position)
        action_type, payload = self._chart_context_action_at_scene_position(
            scene_position
        )
        if action_type is None:
            return

        menu, actions = self._create_chart_context_menu(action_type)
        selected_action = menu.exec(self.current_plot.mapToGlobal(widget_position))
        self._apply_chart_context_menu_selection(
            selected_action,
            actions,
            action_type,
            payload,
        )

    def _create_chart_context_menu(self, action_type):
        menu = QMenu(self.current_plot)
        fn_apply_menu_style(menu)
        actions = {
            "primary": None,
            "set_start_time": None,
            "set_end_time": None,
            "set_cursor_a": None,
            "set_cursor_b": None,
            "clear_cursor_a": None,
            "clear_cursor_b": None,
            "clear_ab": None,
            "clear_all_pins": None,
        }
        if action_type == "delete":
            actions["primary"] = menu.addAction("Delete Pin")
        else:
            actions["primary"] = menu.addAction("Pin")
        menu.addSeparator()
        actions["set_start_time"] = menu.addAction("Set Start Time")
        actions["set_end_time"] = menu.addAction("Set End Time")
        actions["set_end_time"].setEnabled(
            not self.sampling_duration_checkbox.isChecked()
        )
        actions["set_cursor_a"] = menu.addAction("Set Cursor A")
        actions["set_cursor_b"] = menu.addAction("Set Cursor B")

        has_cursor_clear = self.cursor_a_index is not None or self.cursor_b_index is not None
        if has_cursor_clear:
            menu.addSeparator()
            if self.cursor_a_index is not None:
                actions["clear_cursor_a"] = menu.addAction("Clear Cursor A")
            if self.cursor_b_index is not None:
                actions["clear_cursor_b"] = menu.addAction("Clear Cursor B")
            actions["clear_ab"] = menu.addAction("Clear A/B")

        if self.chart_pins:
            menu.addSeparator()
            actions["clear_all_pins"] = menu.addAction("Clear All Pins")
        return menu, actions

    def _apply_chart_context_menu_selection(
        self,
        selected_action,
        actions,
        action_type,
        payload,
    ):
        if selected_action is None:
            return
        if selected_action is actions.get("clear_all_pins"):
            self.clear_chart_pins()
            return
        if selected_action is actions.get("clear_cursor_a"):
            self.clear_cursor_a()
            return
        if selected_action is actions.get("clear_cursor_b"):
            self.clear_cursor_b()
            return
        if selected_action is actions.get("clear_ab"):
            self.clear_ab_cursors()
            return

        sample_index = self._context_sample_index(action_type, payload)
        if selected_action is actions.get("set_start_time"):
            self.set_analysis_start_from_chart_sample(sample_index)
            return
        if selected_action is actions.get("set_end_time"):
            self.set_analysis_end_from_chart_sample(sample_index)
            return
        if selected_action is actions.get("set_cursor_a"):
            self.set_cursor_a(sample_index)
            return
        if selected_action is actions.get("set_cursor_b"):
            self.set_cursor_b(sample_index)
            return
        if selected_action is not actions.get("primary"):
            return
        if action_type == "delete":
            self.delete_chart_pin(payload)
        elif action_type == "pin":
            self.pin_chart_sample(payload)

    def _context_sample_index(self, action_type, payload):
        if action_type == "delete" and payload is not None:
            return payload.sample_index
        return payload

    def set_analysis_start_from_chart_sample(self, sample_index):
        return self._set_analysis_range_from_chart_sample(
            sample_index,
            self.analysis_start_time_edit,
        )

    def set_analysis_end_from_chart_sample(self, sample_index):
        if self.sampling_duration_checkbox.isChecked():
            return False
        return self._set_analysis_range_from_chart_sample(
            sample_index,
            self.analysis_end_time_edit,
        )

    def _set_analysis_range_from_chart_sample(self, sample_index, spinbox):
        if sample_index is None:
            return False
        sample_index = int(sample_index)
        if self.chart_time_seconds.size > 0:
            if sample_index < 0 or sample_index >= self.chart_time_seconds.size:
                return False
            spinbox.setValue(float(self.chart_time_seconds[sample_index]))
            return True
        try:
            elapsed_seconds = self._get_elapsed_seconds()
        except ValueError:
            return False
        if sample_index < 0 or sample_index >= len(elapsed_seconds):
            return False
        spinbox.setValue(float(elapsed_seconds[sample_index]))
        return True

    def _chart_context_action_at_scene_position(self, scene_position):
        if (
            scene_position is None
            or not self._chart_ready
            or self.chart_time_seconds.size == 0
        ):
            return None, None

        plot_item = self.current_plot.getPlotItem()
        if not plot_item.sceneBoundingRect().contains(scene_position):
            return None, None

        pin = self._chart_pin_at_scene_position(scene_position)
        if pin is not None:
            return "delete", pin

        sample_index = self._chart_sample_at_scene_position(scene_position)
        if sample_index is None:
            return None, None

        pin = self._pin_for_sample_index(sample_index)
        if pin is not None:
            return "delete", pin
        return "pin", sample_index

    def _chart_pin_at_scene_position(self, scene_position):
        closest_pin = None
        closest_distance = PIN_HIT_RADIUS_PX
        for pin in self.chart_pins:
            pin_scene_position = self._scene_position_for_chart_value(
                pin.time_s,
                pin.current_ma,
            )
            distance = self._scene_distance(scene_position, pin_scene_position)
            if distance <= closest_distance:
                closest_pin = pin
                closest_distance = distance
        return closest_pin

    def _chart_sample_at_scene_position(self, scene_position):
        point = self.current_plot.getPlotItem().vb.mapSceneToView(scene_position)
        sample_index = self.find_nearest_sample_index(point.x())
        if sample_index is None:
            return None
        sample_scene_position = self._scene_position_for_chart_sample(sample_index)
        distance = self._scene_distance(scene_position, sample_scene_position)
        if distance > SAMPLE_HIT_RADIUS_PX:
            return None
        return sample_index

    def _scene_position_for_chart_sample(self, sample_index):
        return self._scene_position_for_chart_value(
            float(self.chart_time_seconds[sample_index]),
            float(self.chart_current_ma[sample_index]),
        )

    def _scene_position_for_chart_value(self, time_s, current_ma):
        view_box = self.current_plot.getPlotItem().getViewBox()
        return view_box.mapViewToScene(pg.Point(float(time_s), float(current_ma)))

    @staticmethod
    def _scene_distance(first_position, second_position):
        dx = first_position.x() - second_position.x()
        dy = first_position.y() - second_position.y()
        return (dx * dx + dy * dy) ** 0.5


    def _create_analysis_range_graphics(self, plot):
        colors = self._chart_colors()
        marker_specs = (
            ("start", "analysis_start"),
            ("end", "analysis_end"),
        )
        for marker_name, color_key in marker_specs:
            line = pg.InfiniteLine(
                pos=0.0,
                angle=90,
                movable=False,
                pen=pg.mkPen(colors[color_key], width=1.4, style=Qt.DashLine),
            )
            line.setZValue(23)
            line.hide()
            label = pg.TextItem(anchor=(0, 0))
            label.setZValue(43)
            label.hide()
            plot.addItem(line)
            plot.addItem(label)
            setattr(self, f"analysis_{marker_name}_line", line)
            setattr(self, f"analysis_{marker_name}_label", label)

    def hide_analysis_range_markers(self):
        for item in (
            self.analysis_start_line,
            self.analysis_end_line,
            self.analysis_start_label,
            self.analysis_end_label,
        ):
            if item is not None:
                item.hide()

    def _update_analysis_range_markers(self):
        if (
            self.analysis_start_line is None
            or self.analysis_end_line is None
            or self.analysis_start_label is None
            or self.analysis_end_label is None
        ):
            return
        if self.chart_time_seconds.size == 0 or self.chart_current_ma.size == 0:
            self.hide_analysis_range_markers()
            return

        start_time_s = float(self.analysis_start_time_edit.value())
        end_time_s = float(self._effective_analysis_end_time_s())
        self._update_analysis_marker(
            self.analysis_start_line,
            self.analysis_start_label,
            "START",
            start_time_s,
        )
        self._update_analysis_marker(
            self.analysis_end_line,
            self.analysis_end_label,
            "END",
            end_time_s,
        )
        self.position_analysis_range_labels()

    def _update_analysis_marker(self, line, label, title, boundary_time_s):
        line.setValue(float(boundary_time_s))
        line.show()
        label.setHtml(self._analysis_marker_label_html(title, boundary_time_s))
        label.show()

    def _analysis_marker_label_html(self, title, boundary_time_s):
        colors = self._chart_colors()
        body_lines = [title, f"{float(boundary_time_s):.2f} s"]
        sample_index = self._analysis_marker_sample_index(boundary_time_s)
        if sample_index is None:
            body_lines.append("Out of data range")
        else:
            source_time = self._source_time_for_chart_index(sample_index)
            body_lines.append(self._format_source_time_for_marker(source_time))
            body_lines.append(f"{float(self.chart_current_ma[sample_index]):.2f} mA")
        body = "<br/>".join(body_lines)
        return (
            f"<div style='background-color: {colors['analysis_label_background']}; "
            f"color: {colors['analysis_label_text']}; padding: 4px; "
            "white-space: nowrap; font-size: 9pt;'>"
            f"{body}"
            "</div>"
        )

    def _analysis_marker_sample_index(self, boundary_time_s):
        if self.chart_time_seconds.size == 0:
            return None
        data_min = float(self.chart_time_seconds[0])
        data_max = float(self.chart_time_seconds[-1])
        boundary_time_s = float(boundary_time_s)
        if boundary_time_s < data_min or boundary_time_s > data_max:
            return None
        return self.find_nearest_sample_index(boundary_time_s)

    def _source_time_for_chart_index(self, sample_index):
        if 0 <= sample_index < self.chart_source_times.size:
            return self.chart_source_times[sample_index]
        if 0 <= sample_index < len(self.current_samples):
            return self.current_samples[sample_index].time
        return ""

    def _format_source_time_for_marker(self, source_time):
        source_text = str(source_time)
        try:
            parsed_time = parse_timestamp(source_time)
        except (TypeError, ValueError):
            return source_text
        if isinstance(parsed_time, datetime):
            return parsed_time.strftime("%H:%M:%S.%f").rstrip("0").rstrip(".")
        return source_text

    def position_analysis_range_labels(self, *_args):
        if (
            self.analysis_start_label is None
            or self.analysis_end_label is None
            or not hasattr(self, "current_plot")
        ):
            return
        self._position_analysis_range_label(
            self.analysis_start_label,
            self.analysis_start_line,
            prefer_right=True,
        )
        self._position_analysis_range_label(
            self.analysis_end_label,
            self.analysis_end_line,
            prefer_right=False,
        )

    def _position_analysis_range_label(self, label, line, prefer_right):
        if label is None or line is None or not label.isVisible():
            return

        x_range, y_range = self.current_plot.getPlotItem().viewRange()

        x_span = max(float(x_range[1]) - float(x_range[0]), 1e-9)

        y_min = float(min(y_range))
        y_max = float(max(y_range))
        y_span = max(y_max - y_min, 1e-9)

        x_padding = x_span * 0.015

        # Keep label visually at the TOP of the chart,
        # regardless of Y-axis inversion.
        if self._y_axis_inverted:
            y_top = y_min + y_span * 0.03
        else:
            y_top = y_max - y_span * 0.03
        
        anchor_y = 0

        line_x = float(line.value())

        if prefer_right:
            anchor_x = 0
            label_x = line_x + x_padding

            if label_x > float(x_range[1]) - x_padding:
                anchor_x = 1
                label_x = line_x - x_padding
        else:
            anchor_x = 1
            label_x = line_x - x_padding

            if label_x < float(x_range[0]) + x_padding:
                anchor_x = 0
                label_x = line_x + x_padding

        label.setAnchor((anchor_x, 0))
        label.setPos(label_x, y_top)

    def _refresh_analysis_range_theme(self):
        if self.analysis_start_line is None or self.analysis_end_line is None:
            return
        colors = self._chart_colors()
        self.analysis_start_line.setPen(
            pg.mkPen(colors["analysis_start"], width=1.4, style=Qt.DashLine)
        )
        self.analysis_end_line.setPen(
            pg.mkPen(colors["analysis_end"], width=1.4, style=Qt.DashLine)
        )
        if self.analysis_start_label is not None and self.analysis_start_label.isVisible():
            self.analysis_start_label.setHtml(
                self._analysis_marker_label_html(
                    "START",
                    float(self.analysis_start_line.value()),
                )
            )
        if self.analysis_end_label is not None and self.analysis_end_label.isVisible():
            self.analysis_end_label.setHtml(
                self._analysis_marker_label_html(
                    "END",
                    float(self.analysis_end_line.value()),
                )
            )
        self.position_analysis_range_labels()

    def pin_chart_sample(self, sample_index):
        if sample_index is None:
            return False
        sample_index = int(sample_index)
        if sample_index < 0 or sample_index >= self.chart_time_seconds.size:
            return False
        if self._pin_for_sample_index(sample_index) is not None:
            return False

        time_s = float(self.chart_time_seconds[sample_index])
        current_ma = float(self.chart_current_ma[sample_index])
        colors = self._chart_colors()
        marker = pg.ScatterPlotItem(
            [time_s],
            [current_ma],
            symbol="o",
            size=10,
            brush=pg.mkBrush(colors["pin_marker"]),
            pen=pg.mkPen(colors["pin_marker_border"], width=1.5),
        )
        marker.setZValue(35)
        label = pg.TextItem(anchor=(0, 1))
        label.setZValue(45)
        label.setHtml(self._pin_label_html(time_s, current_ma))
        pin = ChartPin(
            sample_index=sample_index,
            time_s=time_s,
            current_ma=current_ma,
            marker=marker,
            label=label,
        )
        self.current_plot.addItem(marker)
        self.current_plot.addItem(label)
        self.chart_pins.append(pin)
        self.position_chart_pin_label(pin)
        return True

    def _create_cursor_graphics(self, plot, cursor_name):
        colors = self._chart_colors()
        color_key = f"cursor_{cursor_name}"
        line = pg.InfiniteLine(
            pos=0.0,
            angle=90,
            movable=False,
            pen=pg.mkPen(colors[color_key], width=1.5),
        )
        line.setZValue(24)
        line.hide()
        marker = pg.ScatterPlotItem(
            [],
            [],
            symbol="o",
            size=10,
            brush=pg.mkBrush(colors[color_key]),
            pen=pg.mkPen(colors["cursor_marker_border"], width=1.2),
        )
        marker.setZValue(34)
        marker.hide()
        label = pg.TextItem(anchor=(0.5, 1.0))
        label.setZValue(44)
        label.setHtml(self._cursor_label_html(cursor_name.upper(), color_key))
        label.hide()
        plot.addItem(line)
        plot.addItem(marker)
        plot.addItem(label)
        setattr(self, f"cursor_{cursor_name}_line", line)
        setattr(self, f"cursor_{cursor_name}_marker", marker)
        setattr(self, f"cursor_{cursor_name}_label", label)

    def _valid_cursor_index(self, sample_index):
        if sample_index is None:
            return None
        sample_index = int(sample_index)
        if sample_index < 0 or sample_index >= self.chart_time_seconds.size:
            return None
        return sample_index

    def set_cursor_a(self, sample_index):
        sample_index = self._valid_cursor_index(sample_index)
        if sample_index is None:
            return False
        self.cursor_a_index = sample_index
        self._update_cursor_graphics("a")
        self._update_cursor_measurement()
        return True

    def set_cursor_b(self, sample_index):
        sample_index = self._valid_cursor_index(sample_index)
        if sample_index is None:
            return False
        self.cursor_b_index = sample_index
        self._update_cursor_graphics("b")
        self._update_cursor_measurement()
        return True

    def clear_cursor_a(self):
        self.cursor_a_index = None
        self._hide_cursor_graphics("a")
        self._update_cursor_measurement()

    def clear_cursor_b(self):
        self.cursor_b_index = None
        self._hide_cursor_graphics("b")
        self._update_cursor_measurement()

    def clear_ab_cursors(self):
        self.cursor_a_index = None
        self.cursor_b_index = None
        self._hide_cursor_graphics("a")
        self._hide_cursor_graphics("b")
        self._update_cursor_measurement()

    def _cursor_items(self, cursor_name):
        return (
            getattr(self, f"cursor_{cursor_name}_line", None),
            getattr(self, f"cursor_{cursor_name}_marker", None),
            getattr(self, f"cursor_{cursor_name}_label", None),
        )

    def _hide_cursor_graphics(self, cursor_name):
        for item in self._cursor_items(cursor_name):
            if item is not None:
                item.hide()

    def _update_cursor_graphics(self, cursor_name):
        index = self.cursor_a_index if cursor_name == "a" else self.cursor_b_index
        index = self._valid_cursor_index(index)
        if index is None:
            self._hide_cursor_graphics(cursor_name)
            return
        time_s = float(self.chart_time_seconds[index])
        current_ma = float(self.chart_current_ma[index])
        line, marker, label = self._cursor_items(cursor_name)
        if line is None or marker is None or label is None:
            return
        line.setPos(time_s)
        line.show()
        marker.setData([time_s], [current_ma])
        marker.show()
        label.setHtml(self._cursor_label_html(cursor_name.upper(), f"cursor_{cursor_name}"))
        label.setPos(time_s, current_ma)
        label.show()

    def _update_cursor_measurement(self):
        def cursor_text(name, index):
            if index is None or self._valid_cursor_index(index) is None:
                return f"{name}: — | —"
            time_s = float(self.chart_time_seconds[index])
            current_ma = float(self.chart_current_ma[index])
            return f"{name}: {time_s:.3f} s | {current_ma:.2f} mA"

        self.cursor_a_value_label.setText(cursor_text("A", self.cursor_a_index))
        self.cursor_b_value_label.setText(cursor_text("B", self.cursor_b_index))
        if (
            self._valid_cursor_index(self.cursor_a_index) is None
            or self._valid_cursor_index(self.cursor_b_index) is None
        ):
            self.cursor_delta_time_label.setText("Δt: —")
            self.cursor_delta_current_label.setText("ΔI: —")
            return
        time_a = float(self.chart_time_seconds[self.cursor_a_index])
        time_b = float(self.chart_time_seconds[self.cursor_b_index])
        current_a = float(self.chart_current_ma[self.cursor_a_index])
        current_b = float(self.chart_current_ma[self.cursor_b_index])
        self.cursor_delta_time_label.setText(f"Δt: {abs(time_b - time_a):.3f} s")
        self.cursor_delta_current_label.setText(f"ΔI: {current_b - current_a:+.2f} mA")

    def _cursor_label_html(self, text, color_key):
        colors = self._chart_colors()
        return (
            f"<div style='color: {colors[color_key]}; font-weight: bold; "
            "white-space: nowrap;'>"
            f"{text}"
            "</div>"
        )

    def delete_chart_pin(self, pin):
        if pin not in self.chart_pins:
            return False
        self.current_plot.removeItem(pin.marker)
        self.current_plot.removeItem(pin.label)
        self.chart_pins.remove(pin)
        return True

    def clear_chart_pins(self):
        if not hasattr(self, "current_plot"):
            self.chart_pins = []
            return
        for pin in list(self.chart_pins):
            self.current_plot.removeItem(pin.marker)
            self.current_plot.removeItem(pin.label)
        self.chart_pins = []

    def _pin_for_sample_index(self, sample_index):
        for pin in self.chart_pins:
            if pin.sample_index == sample_index:
                return pin
        return None

    def position_chart_pin_labels(self, *_args):
        for pin in self.chart_pins:
            self.position_chart_pin_label(pin)

    def position_chart_pin_label(self, pin):
        x_range, y_range = self.current_plot.getPlotItem().viewRange()
        x_mid = (x_range[0] + x_range[1]) / 2.0
        y_mid = (y_range[0] + y_range[1]) / 2.0
        anchor_x = 0 if pin.time_s <= x_mid else 1
        anchor_y = 1 if pin.current_ma >= y_mid else 0
        x_offset = (0.02 if anchor_x == 0 else -0.02) * (x_range[1] - x_range[0])
        y_offset = (0.04 if anchor_y == 0 else -0.04) * (y_range[1] - y_range[0])
        pin.label.setAnchor((anchor_x, anchor_y))
        pin.label.setPos(pin.time_s + x_offset, pin.current_ma + y_offset)

    def _pin_label_html(self, time_s, current_ma):
        colors = self._chart_colors()
        return (
            f"<div style='background-color: {colors['pin_label_background']}; "
            f"color: {colors['pin_label_text']}; padding: 4px; "
            "white-space: nowrap;'>"
            f"Time: {time_s:.3f} s<br/>"
            f"Current: {current_ma:.2f} mA"
            "</div>"
        )

    def _refresh_chart_pin_theme(self):
        colors = self._chart_colors()
        for pin in self.chart_pins:
            pin.marker.setBrush(pg.mkBrush(colors["pin_marker"]))
            pin.marker.setPen(pg.mkPen(colors["pin_marker_border"], width=1.5))
            pin.label.setHtml(self._pin_label_html(pin.time_s, pin.current_ma))
            self.position_chart_pin_label(pin)

    def find_nearest_sample_index(self, mouse_time_s):
        if self.chart_time_seconds.size == 0:
            return None
        index = int(np.searchsorted(self.chart_time_seconds, mouse_time_s))
        candidates = []
        if index < self.chart_time_seconds.size:
            candidates.append(index)
        if index > 0:
            candidates.append(index - 1)
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda candidate: abs(
                self.chart_time_seconds[candidate] - mouse_time_s
            ),
        )

    def update_hover_items(self, time_s, current_ma):
        self._hover_sample = (float(time_s), float(current_ma))
        self.hover_marker.setData([time_s], [current_ma])
        self.hover_marker.show()
        self.hover_label.setHtml(self._hover_label_html(time_s, current_ma))
        self.position_hover_label(time_s, current_ma)
        self.hover_label.show()
     
    def position_hover_label(self, time_s, current_ma):
        x_range, y_range = self.current_plot.getPlotItem().viewRange()
        x_mid = (x_range[0] + x_range[1]) / 2.0
        y_mid = (y_range[0] + y_range[1]) / 2.0
        anchor_x = 1 if time_s >= x_mid else 0
        anchor_y = 0 if current_ma >= y_mid else 1
        x_offset = (-0.02 if anchor_x else 0.02) * (x_range[1] - x_range[0])
        y_offset = (-0.04 if anchor_y == 0 else 0.04) * (y_range[1] - y_range[0])
        self.hover_label.setAnchor((anchor_x, anchor_y))
        self.hover_label.setPos(time_s + x_offset, current_ma + y_offset)

    def hide_hover_items(self):
        if self.hover_marker is not None:
            self.hover_marker.hide()
        if self.hover_label is not None:
            self.hover_label.hide()
        self._hover_sample = None
        
    def _hover_label_html(self, time_s, current_ma):
        colors = self._chart_colors()
        return (
            f"<div style='background-color: {colors['hover_label_background']}; "
            f"color: {colors['hover_label_text']}; padding: 4px; "
            "white-space: nowrap;'>"
            f"Time: {time_s:.3f} s<br/>"
            f"Current: {current_ma:.2f} mA"
            "</div>"
        )

    def _clear_current_chart(self):
        if not hasattr(self, "current_plot"):
            return
        self.current_curve.setData([], [])
        self.reset_y_axis_orientation()
        self.clear_chart_pins()
        self.clear_ab_cursors()
        self.clear_wake_up_regions()
        self.hide_analysis_range_markers()
        self.chart_time_seconds = np.array([], dtype=float)
        self.chart_current_ma = np.array([], dtype=float)
        self.chart_source_times = np.array([], dtype=object)
        self._selected_review_chart_index = None
        self._chart_user_zoomed = False
        self.hide_hover_items()
        self._chart_scrollbar_updating = True
        self.chart_scrollbar.setValue(self.chart_scrollbar.minimum())
        self.chart_scrollbar.hide()
        self._chart_scrollbar_updating = False
        self.current_plot.getPlotItem().enableAutoRange()
        self.current_plot.hide()
        self.chart_placeholder.show()

    def _update_hover_coordinates(self, event):
        if not self._chart_ready or self.chart_time_seconds.size == 0:
            self.hide_hover_items()
            return
        position = event[0]
        plot_item = self.current_plot.getPlotItem()
        if not plot_item.sceneBoundingRect().contains(position):
            self.hide_hover_items()
            return
        point = plot_item.vb.mapSceneToView(position)
        nearest_sample = self.find_nearest_sample(point.x())
        if nearest_sample is None:
            self.hide_hover_items()
            return
        self.update_hover_items(*nearest_sample)

    def _chart_colors(self):
        colors = ThemeManager.fn_colors()
        return {
            "current": colors.PRIMARY,
            "sleep": colors.WARNING,
            "wake": colors.WARNING,
            "wake_fill": colors.WARNING,
            "hover_marker": "#E8F531",
            "hover_marker_border": colors.TEXT,
            "hover_label_background": colors.WINDOW,
            "hover_label_text": colors.TEXT,
            "pin_marker": colors.SUCCESS,
            "pin_marker_border": colors.TEXT,
            "pin_label_background": colors.WINDOW,
            "pin_label_text": colors.TEXT,
            "cursor_a": colors.PRIMARY,
            "cursor_b": colors.DANGER,
            "cursor_marker_border": colors.TEXT,
            "analysis_start": colors.SUCCESS,
            "analysis_end": colors.DANGER,
            "analysis_label_background": colors.WINDOW,
            "analysis_label_text": colors.TEXT,
            "background": colors.WINDOW,
            "grid": colors.TABLE_GRID,
            "axis": colors.TEXT,
        }

    def _refresh_chart_theme(self):
        if not hasattr(self, "current_plot"):
            return
        chart_colors = self._chart_colors()
        self.current_plot.setBackground(chart_colors["background"])
        plot_item = self.current_plot.getPlotItem()
        plot_item.getAxis("bottom").setPen(chart_colors["axis"])
        plot_item.getAxis("bottom").setTextPen(chart_colors["axis"])
        plot_item.getAxis("left").setPen(chart_colors["axis"])
        plot_item.getAxis("left").setTextPen(chart_colors["axis"])
        self.chart_scrollbar.setStyleSheet(fn_scrollbar_style())
        self.current_curve.setPen(pg.mkPen(chart_colors["current"], width=2))
        sleep_pen = pg.mkPen(
            chart_colors["sleep"],
            width=1.5,
            style=Qt.DashLine,
        )
        self.upper_sleep_limit_line.setPen(sleep_pen)
        self.lower_sleep_limit_line.setPen(sleep_pen)
        wake_brush = self._transparent_brush(chart_colors["wake_fill"], 70)
        for region in self.wake_up_regions:
            region.setBrush(wake_brush)
            for line in getattr(region, "lines", []):
                line.setPen(pg.mkPen(None))
                line.setHoverPen(pg.mkPen(None))
        self.hover_marker.setBrush(pg.mkBrush(chart_colors["hover_marker"]))
        self.hover_marker.setPen(
            pg.mkPen(chart_colors["hover_marker_border"], width=1)
        )
        self._refresh_visible_hover_label()
        self._refresh_chart_pin_theme()
        self._refresh_cursor_theme()
        self._refresh_analysis_range_theme()
        self._refresh_legend_theme()

    def _transparent_brush(self, color_value, alpha):
        color = QColor(color_value)
        color.setAlpha(alpha)
        return pg.mkBrush(color)

    def _refresh_visible_hover_label(self):
        if self.hover_label is None or not self.hover_label.isVisible():
            return
        if self._hover_sample is not None:
            self.hover_label.setHtml(self._hover_label_html(*self._hover_sample))

    def _refresh_cursor_theme(self):
        if self.cursor_a_line is None or self.cursor_b_line is None:
            return
        colors = self._chart_colors()
        for cursor_name in ("a", "b"):
            line, marker, label = self._cursor_items(cursor_name)
            color_key = f"cursor_{cursor_name}"
            if line is not None:
                line.setPen(pg.mkPen(colors[color_key], width=1.5))
            if marker is not None:
                marker.setBrush(pg.mkBrush(colors[color_key]))
                marker.setPen(pg.mkPen(colors["cursor_marker_border"], width=1.2))
            if label is not None:
                label.setHtml(self._cursor_label_html(cursor_name.upper(), color_key))
        self._update_cursor_graphics("a")
        self._update_cursor_graphics("b")

    def _refresh_legend_theme(self):
        if not hasattr(self, "legend_items"):
            return
        chart_colors = self._chart_colors()
        marker_styles = {
            "line-solid": (
                f"border-top: 3px solid {chart_colors['current']};"
                "background: transparent;"
            ),
            "line-dashed": (
                f"border-top: 3px dashed {chart_colors['sleep']};"
                "background: transparent;"
            ),
            "dot": (
                f"background: {chart_colors['wake']};"
                "border-radius: 6px;"
                "max-width: 12px; min-width: 12px;"
                "max-height: 12px; min-height: 12px;"
            ),
        }
        for item in self.legend_items:
            item.marker.setStyleSheet(marker_styles[item.marker_type])
        

    def _populate_review_table(self, samples):
        started = perf_counter()
        self.review_table.setSortingEnabled(False)
        self.review_table.model().set_samples(samples)

        self.review_table.scrollToTop()
        self.review_table.verticalScrollBar().setValue(
            self.review_table.verticalScrollBar().minimum()
        )
        self.review_table.horizontalScrollBar().setValue(
            self.review_table.horizontalScrollBar().minimum()
        )
        self.last_loading_timings["table_bind_s"] = perf_counter() - started

    def copy_data_review(self):
        QApplication.clipboard().setText(self._review_table_to_text())

    def copy_summary(self):
        QApplication.clipboard().setText(self.summary_widget.to_text())

    def _review_table_to_text(self):
        model = self.review_table.model()
        rows = ["\t".join(model.HEADERS)]
        for row, sample in enumerate(model.samples):
            timestamp = str(sample.time).replace("\t", " ").replace("\r", " ").replace("\n", " ")
            rows.append(f"{row + 1}\t{timestamp}\t{sample.current_mA:.2f}")
        return "\n".join(rows)

    def _summary_to_text(self):
        return self.summary_widget.to_text()

    def _refresh_dataset_combo(
            self,
            selected_db_path: Path | str | None = None,
            datasets=None,
        ):
        selected_path = selected_db_path

        if selected_path is None:
            selected_path = self.dataset_combo.currentData()

        if selected_path is not None:
            selected_path = str(
                Path(selected_path).expanduser().resolve()
            )

        with QSignalBlocker(self.dataset_combo):
            self.dataset_combo.clear()

            for dataset in (list_datasets(self._database_dir) if datasets is None else datasets):
                if dataset.database_path is None:
                    continue

                db_path = dataset.database_path.resolve()

                self.dataset_combo.addItem(
                    db_path.stem,
                    str(db_path),
                )

            # Default: no selection
            selected_index = -1

            if selected_path is not None:
                selected_index = self.dataset_combo.findData(
                    selected_path
                )

            self.dataset_combo.setCurrentIndex(selected_index)

    @staticmethod
    def _is_valid_source_file(path: Path) -> bool:
        return (
            path.exists()
            and path.is_file()
            and path.suffix.lower() in SUPPORTED_SOURCE_EXTENSIONS
        )

    def fn_refresh_theme(self):
        group_style = fn_groupbox_style()
        for group in (
            self.settings_group,
            self.chart_group,
            self.review_group,
            self.summary_group,
        ):
            group.setStyleSheet(group_style)

        for widget in (
            self.source_file_edit,
            self.dataset_combo,
            self.review_table,
            self.browse_button,
            self.import_button,
            self.save_config_button,
            self.sampling_duration_checkbox,
            self.btn_run,
            self.btn_export,
            self.btn_pin,
            self.btn_invert_y_axis,
            self.btn_fit_all,
            self.btn_capture_chart,
            self.btn_copy_data_review,
            self.btn_copy_summary,
            self.btn_clear,
        ):
            widget.fn_refresh_theme()

        spinbox_style = fn_spinbox_style()
        for spinbox in (
            self.current_limit_edit,
            self.wake_limit_edit,
            self.wake_duration_edit,
            self.sampling_duration_edit,
            self.analysis_start_time_edit,
            self.analysis_end_time_edit,
        ):
            spinbox.setStyleSheet(spinbox_style)

        for label in self.findChildren(PrimaryLabel):
            label.fn_refresh_theme()

        self.summary_widget.fn_refresh_theme()
        self._refresh_analysis_result_style()
        self._refresh_chart_theme()

        colors = ThemeManager.fn_colors()
        value_style = f"""
            QLabel {{
                color: {colors.TEXT};
                background: transparent;
                font-size: 10pt;
            }}
        """
        placeholder_style = f"""
            QLabel {{
                color: {colors.TEXT};
                background: {colors.WINDOW};
                border: 1px solid {colors.BORDER};
                border-radius: 6px;
                font-size: 18pt;
                font-weight: 600;
            }}
        """
        for label in self._theme_widgets:
            if label is self.chart_placeholder:
                label.setStyleSheet(placeholder_style)
            else:
                label.setStyleSheet(value_style)
