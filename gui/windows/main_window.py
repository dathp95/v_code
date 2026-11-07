from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QMainWindow,
    QTabWidget,
)
from PySide6.QtGui import QKeySequence, QShortcut

from core.feature_access import (
    Feature,
    is_feature_enabled,
    load_deactivated_features,
)
from gui.tabs.can_interface_tab import CANInterfaceTab
from gui.tabs.coding_value_tab import CodingValueTab
from gui.tabs.crc_converter_tab import CRCConverterTab
from gui.tabs.license_support_tab import LicenseSupportTab
from gui.tabs.log_analyzer_tab import LogAnalyzerTab
from gui.tabs.q_current_tab import QCurrentTab
from gui.tabs.vehicle_manager_tab import VehicleManagerTab
from gui.themes.icon_manager import IconManager
from gui.themes.styles.containers.window_style import fn_window_style
from config.paths import RELEASE_FEATURES_FILE, SHORTCUTS_FILE
from license.manager import LicenseStatus
from shortcuts.shortcut_manager import load_shortcuts


class MainWindow(QMainWindow):

    def __init__(self, license_status=None, progress_callback=None):
        super().__init__()
        self._progress_callback = progress_callback
        from gui.widgets.controls.save_dialog import prefetch_quick_access
        prefetch_quick_access()
        self._report_progress(25, "Initializing core window...")

        self.license_status = license_status
        self._deactivated_features = load_deactivated_features(
            RELEASE_FEATURES_FILE
        )

        self.setWindowTitle("V-CODE v3.0.6 | AES EEIV by DAT TRAN")
        self.setWindowIcon(
            IconManager.app()
        )
        self.resize(1200, 800)

        self.setup_ui()
        self._setup_shortcuts()
        self._report_progress(82, "Applying visual themes...")
        self.fn_refresh_theme()
        self._report_progress(96, "Finalizing workspace...")

    def _report_progress(self, percent: int, message: str = "") -> None:
        if callable(self._progress_callback):
            try:
                self._progress_callback(percent, message)
            except Exception:
                pass

    def _setup_shortcuts(self):
        actions = {
            "open_log": lambda: self.log_analyzer_tab.log_selector.browse_file(),
            "export_report": lambda: self.log_analyzer_tab.fn_export_clicked(),
            "search": lambda: self.log_analyzer_tab.filter_box.set_focus(),
            "clear": lambda: self.log_analyzer_tab.fn_clear_clicked(),
            "analyze": lambda: self.log_analyzer_tab.fn_run_clicked(),
            "add_quick_access": lambda: self.log_analyzer_tab.left_panel.quick_access.fn_add_filter(),
            "vehicle_selector": lambda: self.log_analyzer_tab.vehicle_selector.cmb_vehicle.setFocus(),
            "toggle_theme": lambda: self.vehicle_manager_tab.theme_switch.switch_dark.click(),
            "copy_asc": lambda: self.log_analyzer_tab.fn_copy_clicked(),
            "clone_quick_access": lambda: self.log_analyzer_tab.left_panel.quick_access.fn_clone_selected(),
        }
        self._shortcuts = []
        for item in load_shortcuts(SHORTCUTS_FILE):
            sequence = item.get("key")
            action = actions.get(item.get("action"))
            if not sequence or action is None:
                continue
            shortcut = QShortcut(QKeySequence(sequence), self)
            if item.get("action") == "toggle_theme":
                shortcut.activated.connect(action)
            else:
                shortcut.activated.connect(
                    lambda action=action: self._run_log_analyzer_shortcut(action)
                )
            self._shortcuts.append(shortcut)

    def _run_log_analyzer_shortcut(self, action):
        if self.tabs.currentWidget() != self.log_analyzer_tab:
            return

        action()

    def setup_ui(self):
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self._report_progress(30, "Loading Log Analyzer...")
        self.log_analyzer_tab = LogAnalyzerTab()
        self._report_progress(45, "Loading Coding Value...")
        self.coding_value_tab = CodingValueTab()
        self._report_progress(58, "Loading CRC Converter...")
        self.crc_converter_tab = CRCConverterTab()
        self._report_progress(64, "Loading CAN Interface...")
        self.can_interface_tab = CANInterfaceTab()
        self._report_progress(70, "Loading Q Current...")
        self.q_current_tab = QCurrentTab()
        self._report_progress(74, "Loading Vehicle Manager...")
        self.vehicle_manager_tab = VehicleManagerTab()
        self._report_progress(78, "Loading License & Support...")
        self.license_support_tab = LicenseSupportTab()

        self._feature_tabs = (
            (
                self.log_analyzer_tab,
                "Log Analyzer",
                Feature.LOG_ANALYZER,
            ),
            (
                self.coding_value_tab,
                "Coding value",
                Feature.CODING_VALUE,
            ),
            (
                self.crc_converter_tab,
                "CRC_Converter",
                Feature.CRC_CONVERTER,
            ),
            (
                self.can_interface_tab,
                "CAN Interface",
                Feature.CAN_INTERFACE,
            ),
            (
                self.q_current_tab,
                "Q current",
                Feature.Q_CURRENT,
            ),
            (
                self.vehicle_manager_tab,
                "Vehicle Manager",
                Feature.VEHICLE_MANAGER,
            ),
            (
                self.license_support_tab,
                "License & Support",
                Feature.LICENSE_SUPPORT,
            ),
        )

        for tab, label, feature in self._feature_tabs:

            if feature in self._deactivated_features:
                continue

            self.tabs.addTab(
                tab,
                label,
            )

        # Place CAN Connection widget on the right side of the tabbar
        if hasattr(self, "can_interface_tab") and hasattr(self.can_interface_tab, "session_panel"):
            conn_panel = self.can_interface_tab.session_panel.connection
            self.tabs.setCornerWidget(conn_panel, Qt.TopRightCorner)
            self.tabs.currentChanged.connect(self._on_tab_changed_update_corner)
            self._on_tab_changed_update_corner(self.tabs.currentIndex())

        self._apply_feature_access()
        self.license_support_tab.activationSucceeded.connect(
            self._on_license_activated
        )

        self.vehicle_manager_tab.vehicle_data_changed.connect(
            lambda _vehicle_name: self.log_analyzer_tab.fn_refresh_vehicles()
        )

        self.crc_converter_tab.crc_transfer_requested.connect(
            self.coding_value_tab.fn_set_crc_value
        )

    def _on_tab_changed_update_corner(self, index):
        if hasattr(self, "can_interface_tab") and hasattr(self.can_interface_tab, "session_panel"):
            is_can = self.tabs.currentWidget() == self.can_interface_tab
            self.can_interface_tab.session_panel.connection.setVisible(is_can)

    def _apply_feature_access(self):
        license_is_valid = self._license_is_valid()

        for tab, _label, feature in self._feature_tabs:
            tab_index = self.tabs.indexOf(tab)
            if tab_index < 0:
                continue

            self.tabs.setTabEnabled(
                tab_index,
                is_feature_enabled(
                    feature,
                    license_is_valid=license_is_valid,
                    deactivated_features=self._deactivated_features,
                ),
            )

        self._select_first_enabled_tab()

    def _select_first_enabled_tab(self):
        for index in range(self.tabs.count()):
            if self.tabs.isTabEnabled(index):
                self.tabs.setCurrentIndex(index)
                return

    def _license_is_valid(self):
        if self.license_status is None:
            return False

        return bool(self.license_status.is_valid)

    def _on_license_activated(self, license_model):
        self.license_status = LicenseStatus.valid(license_model)
        self._apply_feature_access()

        expire_text = license_model.expire_date.astimezone().strftime(
            "%d/%m/%Y %H:%M:%S"
        )
        self.setWindowTitle(
            f"V-CODE v3.0.6 | AES EEIV by DAT TRAN | Valid until {expire_text}"
        )

    def fn_refresh_theme(self):
        self.setStyleSheet(
            fn_window_style()
        )

        self.log_analyzer_tab.fn_refresh_theme()

        self.coding_value_tab.fn_refresh_theme()

        if hasattr(
            self.crc_converter_tab,
            "fn_refresh_theme",
        ):
            self.crc_converter_tab.fn_refresh_theme()

        if hasattr(
            self.can_interface_tab,
            "fn_refresh_theme",
        ):
            self.can_interface_tab.fn_refresh_theme()

        if hasattr(
            self.q_current_tab,
            "fn_refresh_theme",
        ):
            self.q_current_tab.fn_refresh_theme()

        if hasattr(
            self.vehicle_manager_tab,
            "fn_refresh_theme",
        ):
            self.vehicle_manager_tab.fn_refresh_theme()

        if hasattr(
            self.license_support_tab,
            "fn_refresh_theme",
        ):
            self.license_support_tab.fn_refresh_theme()
