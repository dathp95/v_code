from PySide6.QtCore import Qt, QTimer, Signal

from PySide6.QtWidgets import (
    QGroupBox,
    QDialog,
    QInputDialog,
    QFileDialog,
    QMessageBox,
    QScrollArea,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
)

from copy import deepcopy

from gui.dialogs.import_ecu_dialog import ImportECUDialog
from gui.dialogs.export_vehicle_dialog import ExportVehicleDialog
from gui.dialogs.shortcuts_dialog import ShortcutsDialog
from gui.controllers.vehicle_controller import VehicleController
from gui.controllers.ecu_draft_controller import EcuDraftController
from repositories.vehicle_dll_storage import ResourceCleanupError
from gui.themes.theme_manager import ThemeManager
from gui.themes.styles.containers.groupbox_style import fn_groupbox_style
from gui.themes.styles.controls.scrollbar_style import (
    fn_apply_scrollbar_style,
)
from models.ecu import ECU
from models.vehicle import Vehicle
from gui.widgets.controls.primary_button import PrimaryButton
from gui.widgets.controls.secondary_button import SecondaryButton
from gui.widgets.controls.theme_switch import ThemeSwitch

from gui.widgets.vehicle_manager.vehicle_selector import (
    VehicleSelectorWidget,
)

from gui.widgets.vehicle_manager.ecu_list import (
    ECUList,
)


from gui.widgets.vehicle_manager.ecu_info import (
    ECUInfoWidget,
)

from gui.widgets.vehicle_manager.ecu_resource import (
    ECUResourceWidget,
)
from gui.widgets.controls.primary_label import (
    PrimaryLabel,
)

class VehicleManagerTab(QWidget):

    vehicle_data_changed = Signal(str)

    def __init__(self):

        super().__init__()
        self._current_vehicle_name = ""

        self._current_vehicle = None

        self._current_ecu = None

        self._create_controller()

        self._setup_ui()
        self.ecu_drafts = EcuDraftController(self)

        self._connect_signals()

        self._load_data()

    # ==========================================
    # Private
    # ==========================================

    def _create_controller(self):

        self._controller = VehicleController()

    def _setup_ui(self):

        main_layout = QVBoxLayout(self)

        main_layout.setContentsMargins(
            16,
            16,
            16,
            16,
        )

        main_layout.setSpacing(12)

        self.vehicle_selector = VehicleSelectorWidget()

        self.btn_create_vehicle = SecondaryButton(
            "+ Vehicle",
            width=120,
        )

        self.btn_delete_vehicle = SecondaryButton(
            "Delete Vehicle",
            width=120,
        )

        self.btn_delete_vehicle.setEnabled(False)

        self.btn_export_vehicle = SecondaryButton(
            "Export Vehicle",
            width=120,
        )

        self.btn_export_vehicle.setEnabled(False)

        self.btn_import_ecus = SecondaryButton(
            "Import Vehicle",
            width=120,
        )
        self.btn_import_ecus.setEnabled(False)

        vehicle_widget = QWidget()

        vehicle_layout = QHBoxLayout(vehicle_widget)

        vehicle_layout.setContentsMargins(0, 0, 0, 0)

        vehicle_layout.setSpacing(12)

        vehicle_layout.addWidget(
            self.vehicle_selector,
            1,
            Qt.AlignTop,
        )
        vehicle_action_widget = QWidget()

        vehicle_action_layout = QVBoxLayout(vehicle_action_widget)

        vehicle_action_layout.setContentsMargins(0, 0, 0, 0)

        vehicle_action_layout.setSpacing(6)

        # Giữ cùng chiều cao với Label bên trái
        vehicle_action_layout.addWidget(
            PrimaryLabel("Actions")
        )

        vehicle_button_layout = QHBoxLayout()

        vehicle_button_layout.setContentsMargins(0, 0, 0, 0)

        vehicle_button_layout.setSpacing(8)

        vehicle_button_layout.addWidget(
            self.btn_create_vehicle
        )

        vehicle_button_layout.addWidget(
            self.btn_delete_vehicle
        )

        vehicle_button_layout.addWidget(
            self.btn_export_vehicle
        )

        vehicle_button_layout.addWidget(
            self.btn_import_ecus
        )

        vehicle_button_layout.addStretch()

        vehicle_action_layout.addLayout(
            vehicle_button_layout
        )

        vehicle_layout.addWidget(
            vehicle_action_widget,
            0,
        )
     

        self.vehicle_panel = self._create_panel(
            "Vehicle Package",
            vehicle_widget,
        )

        main_layout.addWidget(
            self.vehicle_panel
        )

        content_layout = QHBoxLayout()

        content_layout.setSpacing(30)

        self.ecu_list = ECUList()

        self.ecu_info = ECUInfoWidget()

        self.ecu_resource = ECUResourceWidget()

        self.btn_save = PrimaryButton(
            "Save",
            width=120,
        )

        self.btn_save.setEnabled(False)

        self.btn_add_ecu = SecondaryButton(
            "+ ECU",
            width=120,
        )

        self.btn_add_ecu.setEnabled(False)

        self.btn_delete_ecu = SecondaryButton(
            "Delete ECU",
            width=120,
        )

        self.btn_delete_ecu.setEnabled(False)       

       

        self.btn_shortcuts = SecondaryButton(
            "Keyboard Shortcuts",
            width=180,
        )
        self.btn_shortcuts.setVisible(False)

        self.theme_switch = ThemeSwitch()

        ecu_list_widget = QWidget()

        ecu_list_layout = QVBoxLayout(ecu_list_widget)

        ecu_list_layout.setContentsMargins(0, 0, 0, 0)

        ecu_list_layout.setSpacing(8)

        ecu_list_layout.addWidget(
            self.ecu_list
        )

        ecu_list_action_layout = QHBoxLayout()

        ecu_list_action_layout.setContentsMargins(0, 0, 0, 0)

        ecu_list_action_layout.setSpacing(8)

        ecu_list_action_layout.addWidget(
            self.btn_add_ecu
        )

        ecu_list_action_layout.addWidget(
            self.btn_delete_ecu
        )

        ecu_list_layout.addLayout(
            ecu_list_action_layout
        )

        self.ecu_list_panel = self._create_panel(
            "ECU List",
            ecu_list_widget,
        )

        self.ecu_info_panel = self._create_panel(
            "Basic Information",
            self.ecu_info,
        )

        self.ecu_resource_panel = self._create_panel(
            "Resources",
            self.ecu_resource,
        )

        detail_widget = QWidget()

        detail_layout = QVBoxLayout(detail_widget)

        detail_layout.setContentsMargins(0, 0, 0, 0)

        detail_layout.setSpacing(12)

        detail_content_layout = QHBoxLayout()

        detail_content_layout.setContentsMargins(0, 0, 0, 0)

        detail_content_layout.setSpacing(12)

        detail_content_layout.addWidget(
            self.ecu_info_panel,
            1,
        )

        detail_content_layout.addWidget(
            self.ecu_resource_panel,
            2,
        )

        detail_layout.addLayout(
            detail_content_layout
        )

        action_layout = QHBoxLayout()

        action_layout.setContentsMargins(0, 0, 0, 0)


        action_layout.addWidget(
            self.btn_shortcuts
        )

        action_layout.addStretch()

        action_layout.addWidget(
            self.btn_save
        )

        detail_layout.addLayout(
            action_layout
        )

        detail_layout.addStretch()

        bottom_layout = QHBoxLayout()

        bottom_layout.setContentsMargins(0, 0, 0, 0)

        # bottom_layout.addWidget(
        #     self.theme_switch
        # )

        bottom_layout.addStretch()

        detail_layout.addLayout(
            bottom_layout
        )

        self.detail_scroll_area = QScrollArea()

        self.detail_scroll_area.setWidgetResizable(True)

        self.detail_scroll_area.setFrameShape(
            QScrollArea.NoFrame
        )

        self.detail_scroll_area.setWidget(
            detail_widget
        )

        fn_apply_scrollbar_style(
            self.detail_scroll_area
        )

        content_layout.addWidget(
            self.ecu_list_panel,
            1,
        )

        content_layout.addWidget(
            self.detail_scroll_area,
            4,
        )

        main_layout.addLayout(
            content_layout
        )

    def _create_panel(
            self,
            title: str,
            widget: QWidget,
        ) -> QGroupBox:

        panel = QGroupBox(title)

        layout = QVBoxLayout(panel)

        layout.setContentsMargins(
            12,
            14,
            12,
            12,
        )

        layout.setSpacing(8)

        layout.addWidget(widget)

        return panel

    def _connect_signals(self):

        self.vehicle_selector.vehicle_changed.connect(

            self._on_vehicle_changed

        )

        self.btn_create_vehicle.clicked.connect(

            self._on_create_vehicle_clicked

        )

        self.btn_delete_vehicle.clicked.connect(

            self._on_delete_vehicle_clicked

        )

        self.btn_export_vehicle.clicked.connect(

            self._on_export_vehicle_clicked

        )
        

        self.ecu_list.ecu_selected.connect(

            self._on_ecu_selected

        )

        self.btn_add_ecu.clicked.connect(

            self._on_add_ecu_clicked

        )

        self.btn_delete_ecu.clicked.connect(

            self._on_delete_ecu_clicked

        )

        self.btn_import_ecus.clicked.connect(

            self._on_import_ecus_clicked

        )

        self.btn_shortcuts.clicked.connect(
            self._on_shortcuts_clicked
        )

        self.btn_save.clicked.connect(

            self._on_save_clicked

        )

        self.theme_switch.theme_changed.connect(
            self.fn_change_theme
        )

    def _load_data(self):        

        vehicles = self._controller.list_vehicles()

        self.vehicle_selector.fn_set_vehicles(
            vehicles,
            allow_empty_selection=True,
        )

        self._clear_vehicle_state()

    def _on_vehicle_changed(
            self,
            vehicle_name: str,
        ):
        self.ecu_drafts.leave()

        if not vehicle_name:

            self._clear_vehicle_state()

            return

        self._current_vehicle = self._controller.load_vehicle(
            vehicle_name
        )

        self._current_vehicle_name = vehicle_name

        self.btn_add_ecu.setEnabled(True)

        self.btn_delete_vehicle.setEnabled(True)

        self.btn_export_vehicle.setEnabled(True)

        self.btn_import_ecus.setEnabled(True)

        ecu_names = [

            ecu.name

            for ecu in self._current_vehicle.ecus

        ]

        self.ecu_info.fn_clear()

        self.ecu_resource.fn_clear()

        self._current_ecu = None

        self.btn_save.setEnabled(False)

        self.btn_delete_ecu.setEnabled(False)

        self.ecu_list.fn_set_ecus(
            ecu_names
        )

        if ecu_names:

            self._on_ecu_selected(
                ecu_names[0]
            )

    # ==========================================
    # Public
    # ==========================================

    def _clear_vehicle_state(self):
        self.ecu_drafts.leave()

        self._current_vehicle_name = ""

        self._current_vehicle = None

        self._current_ecu = None

        self.ecu_info.fn_clear()

        self.ecu_resource.fn_clear()

        self.ecu_list.fn_set_ecus([])

        self.btn_add_ecu.setEnabled(False)

        self.btn_import_ecus.setEnabled(False)

        self.btn_delete_vehicle.setEnabled(False)

        self.btn_export_vehicle.setEnabled(False)

        self.btn_save.setEnabled(False)

        self.btn_delete_ecu.setEnabled(False)

    def _refresh_vehicle_list(
        self,
        selected_vehicle_name: str = "",
    ):

        vehicles = self._controller.list_vehicles()

        self.vehicle_selector.fn_set_vehicles(
            vehicles,
            selected_vehicle=selected_vehicle_name,
        )

        if not vehicles:

            self._clear_vehicle_state()

            return

        if selected_vehicle_name not in vehicles:

            selected_vehicle_name = vehicles[0]

        self._on_vehicle_changed(
            selected_vehicle_name
        )

    def _on_create_vehicle_clicked(self):

        vehicle_name, accepted = QInputDialog.getText(
            self,
            "Create Vehicle",
            "Vehicle name:",
        )

        if not accepted:

            return

        vehicle_name = vehicle_name.strip()

        if not vehicle_name:

            QMessageBox.warning(
                self,
                "Create Vehicle",
                "Vehicle name cannot be empty.",
            )

            return

        try:

            self._controller.create_vehicle(
                Vehicle(
                    name=vehicle_name,
                )
            )

        except (ValueError, FileExistsError) as error:

            QMessageBox.warning(
                self,
                "Create Vehicle",
                str(error),
            )

            return

        self._refresh_vehicle_list(
            selected_vehicle_name=vehicle_name
        )

        self._notify_vehicle_data_changed()

    def _on_delete_vehicle_clicked(self):

        if not self._current_vehicle_name:

            return

        vehicle_name = self._current_vehicle_name

        answer = QMessageBox.question(
            self,
            "Delete Vehicle",
            f"Delete vehicle package '{vehicle_name}' and its unsaved ECU drafts?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if answer != QMessageBox.Yes:

            return

        try:

            self._controller.delete_vehicle(
                vehicle_name
            )

        except (OSError, ValueError) as error:

            QMessageBox.warning(
                self,
                "Delete Vehicle",
                str(error),
            )

            return

        self.ecu_drafts.deleted_vehicle(vehicle_name)
        self._refresh_vehicle_list()

        self._notify_vehicle_data_changed()



    def _on_export_vehicle_clicked(self):

        if not self._current_vehicle_name:

            return

        try:

            ecu_text = self._controller.export_vehicle_ecu_list(
                self._current_vehicle_name
            )

        except (FileNotFoundError, ValueError) as error:

            QMessageBox.warning(
                self,
                "Export Vehicle",
                str(error),
            )

            return

        dialog = ExportVehicleDialog(
            self._current_vehicle_name,
            ecu_text,
            self,
        )

        dialog.exec()

    def _on_ecu_selected(
            self,
            ecu_name: str,
        ):

        if self._current_vehicle is None:

            return

        for ecu in self._current_vehicle.ecus:

            if ecu.name == ecu_name:

                self._current_ecu = ecu

                self.ecu_drafts.activate(self._current_vehicle_name, ecu)

                self.btn_save.setEnabled(True)

                self.btn_delete_ecu.setEnabled(True)

                break

    def _on_add_ecu_clicked(self):

        if not self._current_vehicle_name:

            return

        ecu_name, accepted = QInputDialog.getText(
            self,
            "Add ECU",
            "ECU name:",
        )

        if not accepted:

            return

        ecu_name = ecu_name.strip()

        if not ecu_name:

            QMessageBox.warning(
                self,
                "Add ECU",
                "ECU name cannot be empty.",
            )

            return

        ecu = ECU(
            name=ecu_name,
        )

        try:

            self._controller.add_ecu(
                self._current_vehicle_name,
                ecu,
            )

        except ValueError as error:

            QMessageBox.warning(
                self,
                "Add ECU",
                str(error),
            )

            return

        self._reload_current_vehicle(
            selected_ecu_name=ecu_name
        )

        self._notify_vehicle_data_changed()

    def _on_delete_ecu_clicked(self):

        if (
            self._current_vehicle is None
            or self._current_ecu is None
        ):

            return

        ecu_name = self._current_ecu.name

        answer = QMessageBox.question(
            self,
            "Delete ECU",
            f"Delete ECU '{ecu_name}' and its unsaved draft?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if answer != QMessageBox.Yes:

            return

        try:
            self._controller.delete_ecu(self._current_vehicle_name, ecu_name)
        except (ValueError, OSError) as error:
            if isinstance(error, ResourceCleanupError):
                self.ecu_drafts.saved(self._current_vehicle_name, ecu_name)
                self._reload_current_vehicle(selected_ecu_name='')
                self._notify_vehicle_data_changed()
            QMessageBox.warning(self, 'Delete ECU', str(error))
            return

        self.ecu_drafts.saved(self._current_vehicle_name, ecu_name)
        next_ecu_name = ""

        remaining_ecus = [
            ecu
            for ecu in self._current_vehicle.ecus
            if ecu.name != ecu_name
        ]

        if remaining_ecus:

            next_ecu_name = remaining_ecus[0].name

        self.ecu_info.fn_clear()

        self.ecu_resource.fn_clear()

        self._current_ecu = None

        self.btn_save.setEnabled(False)

        self.btn_delete_ecu.setEnabled(False)

        self._reload_current_vehicle(
            selected_ecu_name=next_ecu_name
        )

        self._notify_vehicle_data_changed()

    def _on_import_ecus_clicked(self):

        if not self._current_vehicle_name:

            return

        dialog = ImportECUDialog(self)

        if dialog.exec() != QDialog.Accepted:

            return

        try:

            ecus = dialog.fn_ecus()

            self._validate_import_ecus(ecus)

            for ecu in ecus:

                self._controller.add_ecu(
                    self._current_vehicle_name,
                    ecu,
                )

        except ValueError as error:

            QMessageBox.warning(
                self,
                "Import ECU List",
                str(error),
            )

            return

        selected_ecu_name = (
            ecus[0].name
            if ecus
            else ""
        )

        self._reload_current_vehicle(
            selected_ecu_name=selected_ecu_name
        )

        self._notify_vehicle_data_changed()

    def _on_shortcuts_clicked(self):
        dialog = ShortcutsDialog(self)
        dialog.exec()

    def _validate_import_ecus(
        self,
        ecus: list[ECU],
    ) -> None:

        if self._current_vehicle is None:

            raise ValueError(
                "Please select a vehicle before importing ECUs."
            )

        existing_names = {
            ecu.name.lower()
            for ecu in self._current_vehicle.ecus
        }

        existing_requests = {
            self._normalize_can_id(ecu.request_id): ecu.name
            for ecu in self._current_vehicle.ecus
            if self._normalize_can_id(ecu.request_id)
        }

        existing_responses = {
            self._normalize_can_id(ecu.response_id): ecu.name
            for ecu in self._current_vehicle.ecus
            if self._normalize_can_id(ecu.response_id)
        }

        imported_requests = {}

        imported_responses = {}

        for ecu in ecus:

            if ecu.name.lower() in existing_names:

                raise ValueError(
                    f"ECU '{ecu.name}' already exists."
                )

            request_id = self._normalize_can_id(
                ecu.request_id
            )

            response_id = self._normalize_can_id(
                ecu.response_id
            )

            if request_id in existing_requests:

                raise ValueError(
                    f"Request ID '{ecu.request_id}' already exists in ECU '{existing_requests[request_id]}'."
                )

            if response_id in existing_responses:

                raise ValueError(
                    f"Response ID '{ecu.response_id}' already exists in ECU '{existing_responses[response_id]}'."
                )

            if request_id in imported_requests:

                raise ValueError(
                    f"Duplicate Request ID '{ecu.request_id}' in pasted list."
                )

            if response_id in imported_responses:

                raise ValueError(
                    f"Duplicate Response ID '{ecu.response_id}' in pasted list."
                )

            if request_id:

                imported_requests[request_id] = ecu.name

            if response_id:

                imported_responses[response_id] = ecu.name

    @staticmethod
    def _normalize_can_id(
        value: str,
    ) -> str:

        value = (value or "").strip().lower()

        if value.startswith("0x"):

            value = value[2:]

        return value

    def _reload_current_vehicle(
        self,
        selected_ecu_name: str = "",
    ) -> None:

        if not self._current_vehicle_name:

            return

        self._current_vehicle = self._controller.load_vehicle(
            self._current_vehicle_name
        )

        self._refresh_ecu_list(
            selected_ecu_name=selected_ecu_name
        )

    def _refresh_ecu_list(
        self,
        selected_ecu_name: str = "",
    ):

        if self._current_vehicle is None:

            return

        ecu_names = [
            ecu.name
            for ecu in self._current_vehicle.ecus
        ]

        self.ecu_list.fn_set_ecus(
            ecu_names
        )
        self.ecu_drafts.apply_markers()

        if selected_ecu_name:

            self.ecu_list.fn_select_ecu(
                selected_ecu_name
            )

            self._on_ecu_selected(
                selected_ecu_name
            )

    def _on_save_clicked(self):

        if self._current_ecu is None:

            return

        draft_ecu = deepcopy(
            self._current_ecu
        )

        old_ecu_name = self._current_ecu.name

        self.ecu_info.fn_get_ecu(

            draft_ecu

        )

        try:
            draft_ecu = self.ecu_resource.fn_get_ecu(draft_ecu)
        except ValueError:
            # Resource widget already presents a non-modal validation message.
            return

        if draft_ecu.name.lower() != old_ecu_name.lower():

            for ecu in self._current_vehicle.ecus:

                if ecu.name.lower() == draft_ecu.name.lower():

                    QMessageBox.warning(
                        self,
                        "Save ECU",
                        f"ECU '{draft_ecu.name}' already exists.",
                    )

                    return

        try:

            source = self.ecu_resource.fn_dll_import_source()
            options = {'dll_source': source} if source is not None else {}
            renamed_atomically = self._controller.save_ecu(
                self._current_vehicle_name,
                draft_ecu,
                existing_ecu_name=old_ecu_name,
                **options,
            )

            if draft_ecu.name != old_ecu_name and renamed_atomically is not True:

                self._controller.delete_ecu(
                    self._current_vehicle_name,
                    old_ecu_name,
                )

        except (OSError, ValueError) as error:
            if isinstance(error, ResourceCleanupError):
                self.ecu_drafts.saved(self._current_vehicle_name, old_ecu_name)
                self._reload_current_vehicle(selected_ecu_name=draft_ecu.name)
                self._notify_vehicle_data_changed()
            QMessageBox.warning(self, "Save ECU", str(error))
            return

        self.ecu_drafts.saved(self._current_vehicle_name, old_ecu_name)
        self._reload_current_vehicle(selected_ecu_name=draft_ecu.name)

        self._show_auto_close_info(
            "Save ECU",
            "Saved successfully.",
        )

        self._notify_vehicle_data_changed()

    def _notify_vehicle_data_changed(self) -> None:

        self.vehicle_data_changed.emit(
            self._current_vehicle_name
        )

    def _show_auto_close_info(
        self,
        title: str,
        message: str,
    ) -> None:

        message_box = QMessageBox(self)

        message_box.setIcon(QMessageBox.Information)

        message_box.setWindowTitle(title)

        message_box.setText(message)

        message_box.setStandardButtons(QMessageBox.NoButton)

        QTimer.singleShot(
            1500,
            message_box.accept,
        )

        message_box.exec()

    def fn_change_theme(self, theme):
        ThemeManager.fn_set_theme(theme)

        window = self.window()

        if (
            window is not self
            and hasattr(window, "fn_refresh_theme")
        ):
            window.fn_refresh_theme()
            return

        self.fn_refresh_theme()

    def fn_refresh_theme(self):

        self.setStyleSheet("")

        for panel in (
            self.vehicle_panel,
            self.ecu_list_panel,
            self.ecu_info_panel,
            self.ecu_resource_panel,
        ):

            panel.setStyleSheet(
                fn_groupbox_style()
            )

        fn_apply_scrollbar_style(
            self.detail_scroll_area
        )

        self.vehicle_selector.fn_refresh_theme()

        self.ecu_list.fn_refresh_theme()

        self.ecu_info.fn_refresh_theme()

        self.ecu_resource.fn_refresh_theme()

        self.btn_save.fn_refresh_theme()

        self.btn_create_vehicle.fn_refresh_theme()

        self.btn_delete_vehicle.fn_refresh_theme()

        self.btn_export_vehicle.fn_refresh_theme()

        self.btn_add_ecu.fn_refresh_theme()

        self.btn_delete_ecu.fn_refresh_theme()

        self.btn_import_ecus.fn_refresh_theme()

        self.btn_shortcuts.fn_refresh_theme()



        self.theme_switch.fn_refresh_theme()
