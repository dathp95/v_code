import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFocusEvent
from PySide6.QtWidgets import (
    QApplication,
    QDoubleSpinBox,
    QGroupBox,
    QLineEdit,
    QMessageBox,
    QSplitter,
)

from core.q_current_config import QCurrentConfig, save_q_current_config
from core.sleep_current_database import database_path_for_source, import_dataset
from gui.tabs.q_current_tab import (
    CHART_SCROLL_SCALE,
    PLACEHOLDER_VALUE,
    QCurrentTab,
    calculate_elapsed_seconds,
)
from gui.themes.theme import ThemeType
from gui.themes.theme_manager import ThemeManager
from gui.widgets.controls.primary_button import PrimaryButton
from gui.widgets.controls.primary_combobox import PrimaryComboBox
from gui.widgets.controls.quick_access_button import QuickAccessButton


class QCurrentTabTests(unittest.TestCase):

    def _wait_for_idle(self, tab):
        deadline = time.monotonic() + 10
        while tab._operation_running and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.001)
        self.assertFalse(tab._operation_running, "Q Current worker did not finish")

    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def tearDown(self):
        ThemeManager.fn_set_theme(ThemeType.LIGHT)

    def _create_tab(self, tmpdir: str):
        database_dir = Path(tmpdir) / "config" / "database_qcurrent"
        config_file = Path(tmpdir) / "config" / "q_current_config.json"
        tab = QCurrentTab(database_dir=database_dir, config_file=config_file)
        self.addCleanup(tab.deleteLater)
        return tab, database_dir


    def _legend_labels(self, tab):
        return [item.legend_text for item in tab.legend_items]

    def _sample(self, time, current_ma):
        return type("Sample", (), {"time": str(time), "current_mA": current_ma})()

    def _use_manual_end_mode(self, tab):
        tab.sampling_duration_checkbox.setChecked(False)
        if not tab.current_samples:
            return
        try:
            elapsed_seconds = calculate_elapsed_seconds(tab.current_samples)
        except ValueError:
            return
        if not elapsed_seconds:
            return
        end_time_s = float(max(elapsed_seconds))
        tab.analysis_end_time_edit.setMaximum(
            max(tab.analysis_end_time_edit.maximum(), end_time_s)
        )
        tab.analysis_end_time_edit.setValue(end_time_s)

    def test_analysis_settings_header_has_two_rows_and_file_controls(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)

            self.assertIsInstance(tab.settings_group, QGroupBox)
            self.assertEqual(tab.settings_group.title(), "Analysis Settings")
            self.assertEqual(tab.settings_layout.rowCount(), 3)
            self.assertIsInstance(tab.source_file_edit, QLineEdit)
            self.assertEqual(tab.source_file_edit.objectName(), "source_file_edit")
            self.assertTrue(tab.source_file_edit.isReadOnly())
            self.assertEqual(
                tab.source_file_edit.placeholderText(),
                "Select current data file (*.csv, *.xlsx)",
            )
            self.assertEqual(tab.browse_button.objectName(), "browse_button")
            self.assertEqual(tab.browse_button.text(), "Browse")
            self.assertIsInstance(tab.dataset_combo, PrimaryComboBox)
            self.assertEqual(tab.dataset_combo.objectName(), "dataset_combo")
            self.assertGreaterEqual(tab.dataset_combo.minimumWidth(), 220)
            self.assertEqual(tab.dataset_combo.count(), 0)
            self.assertEqual(tab.import_button.objectName(), "import_button")
            self.assertEqual(tab.import_button.text(), "Import")
            self.assertTrue(tab.import_button.isEnabled())
            self.assertEqual(tab.current_limit_label.text(), "Sleep limit (mA)")
            self.assertIsInstance(tab.current_limit_edit, QDoubleSpinBox)
            self.assertEqual(tab.current_limit_edit.objectName(), "current_limit_edit")
            self.assertEqual(tab.current_limit_edit.minimum(), 0.0)
            self.assertEqual(tab.current_limit_edit.decimals(), 1)
            self.assertEqual(tab.current_limit_edit.value(), 30.0)
            self.assertEqual(tab.current_limit_edit.text(), "30.0")
            self.assertEqual(tab.wake_limit_label.text(), "Wake Up limit (mA)")
            self.assertIsInstance(tab.wake_limit_edit, QDoubleSpinBox)
            self.assertEqual(tab.wake_limit_edit.objectName(), "wake_limit_edit")
            self.assertEqual(tab.wake_limit_edit.minimum(), 0.0)
            self.assertEqual(tab.wake_limit_edit.decimals(), 1)
            self.assertEqual(tab.wake_limit_edit.value(), 300.0)
            self.assertEqual(tab.wake_limit_edit.text(), "300.0")
            self.assertEqual(tab.wake_duration_label.text(), "Wake duration (s)")
            self.assertIsInstance(tab.wake_duration_edit, QDoubleSpinBox)
            self.assertEqual(tab.wake_duration_edit.objectName(), "wake_duration_edit")
            self.assertEqual(tab.wake_duration_edit.minimum(), 0.1)
            self.assertEqual(tab.wake_duration_edit.maximum(), 3600.0)
            self.assertEqual(tab.wake_duration_edit.singleStep(), 0.5)
            self.assertEqual(tab.wake_duration_edit.decimals(), 1)
            self.assertEqual(tab.wake_duration_edit.value(), 2.0)
            self.assertEqual(tab.wake_duration_edit.text(), "2.0")
            self.assertEqual(tab.sampling_duration_checkbox.text(), "Sampling Duration (min)")
            self.assertTrue(tab.sampling_duration_checkbox.isChecked())
            self.assertIsInstance(tab.sampling_duration_edit, QDoubleSpinBox)
            self.assertEqual(tab.sampling_duration_edit.objectName(), "sampling_duration_edit")
            self.assertEqual(tab.sampling_duration_edit.decimals(), 0)
            self.assertEqual(tab.sampling_duration_edit.minimum(), 5.0)
            self.assertEqual(tab.sampling_duration_edit.maximum(), 1440.0)
            self.assertEqual(tab.sampling_duration_edit.singleStep(), 5.0)
            self.assertEqual(tab.sampling_duration_edit.value(), 60.0)
            self.assertTrue(tab.sampling_duration_edit.isEnabled())
            self.assertEqual(tab.save_config_button.objectName(), "save_config_button")
            self.assertEqual(tab.save_config_button.text(), "SAVE CONFIG")
            self.assertIsInstance(tab.save_config_button, PrimaryButton)
            self.assertFalse(hasattr(tab, "sleep_duration_edit"))
            self.assertFalse(hasattr(tab, "sleep_duration_label"))
            self.assertEqual(tab.analysis_progress_bar.text(), "NOT RUN")
            self.assertEqual(tab.analysis_range_label.text(), "Analysis Range:")
            self.assertEqual(tab.analysis_start_time_label.text(), "Start Time (s)")
            self.assertEqual(tab.analysis_start_time_edit.objectName(), "analysis_start_time_edit")
            self.assertEqual(tab.analysis_start_time_edit.value(), 0.0)
            self.assertFalse(tab.analysis_start_time_edit.isEnabled())
            self.assertEqual(tab.analysis_end_time_label.text(), "End Time (s)")
            self.assertEqual(tab.analysis_end_time_edit.objectName(), "analysis_end_time_edit")
            self.assertEqual(tab.analysis_end_time_edit.value(), 0.0)
            self.assertFalse(tab.analysis_end_time_edit.isEnabled())


    def test_saved_q_current_config_loads_on_new_tab_startup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            database_dir = Path(tmpdir) / "config" / "database_qcurrent"
            config_file = Path(tmpdir) / "config" / "q_current_config.json"
            save_q_current_config(
                QCurrentConfig(
                    standard_current_ma=25.0,
                    wake_up_limit_ma=250.0,
                    wake_duration_s=3.0,
                    sampling_duration_enabled=False,
                    sampling_duration_min=75.0,
                ),
                config_file,
            )

            tab = QCurrentTab(database_dir=database_dir, config_file=config_file)
            self.addCleanup(tab.deleteLater)

            self.assertEqual(tab.current_limit_edit.value(), 25.0)
            self.assertEqual(tab.wake_limit_edit.value(), 250.0)
            self.assertEqual(tab.wake_duration_edit.value(), 3.0)
            self.assertFalse(tab.sampling_duration_checkbox.isChecked())
            self.assertEqual(tab.sampling_duration_edit.value(), 75.0)
            self.assertFalse(tab.sampling_duration_edit.isEnabled())
            self.assertFalse(tab.analysis_end_time_edit.isEnabled())

    def test_sampling_duration_config_saves_and_loads_on_fresh_tab(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            database_dir = Path(tmpdir) / "config" / "database_qcurrent"
            config_file = Path(tmpdir) / "config" / "q_current_config.json"
            tab = QCurrentTab(database_dir=database_dir, config_file=config_file)
            self.addCleanup(tab.deleteLater)

            tab.sampling_duration_checkbox.setChecked(True)
            tab.sampling_duration_edit.setValue(120.0)

            with patch.object(QMessageBox, "information") as information, patch.object(
                QMessageBox,
                "critical",
            ) as critical:
                self.assertTrue(tab.save_current_config())

            information.assert_called_once()
            critical.assert_not_called()
            restarted_tab = QCurrentTab(database_dir=database_dir, config_file=config_file)
            self.addCleanup(restarted_tab.deleteLater)
            self.assertTrue(restarted_tab.sampling_duration_checkbox.isChecked())
            self.assertEqual(restarted_tab.sampling_duration_edit.value(), 120.0)

    def test_sampling_duration_mode_recalculates_end_time_and_switches_manual_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, 1.0),
                self._sample(7200.0, 2.0),
            ])

            self.assertTrue(tab.sampling_duration_checkbox.isChecked())
            self.assertTrue(tab.sampling_duration_edit.isEnabled())
            self.assertFalse(tab.analysis_end_time_edit.isEnabled())
            self.assertEqual(tab.analysis_start_time_edit.value(), 0.0)
            self.assertEqual(tab.analysis_end_time_edit.value(), 3600.0)

            tab.analysis_start_time_edit.setValue(600.0)
            self.assertEqual(tab.analysis_end_time_edit.value(), 4200.0)
            tab.sampling_duration_edit.setValue(90.0)
            self.assertEqual(tab.analysis_end_time_edit.value(), 6000.0)
            self.assertEqual(tab._effective_analysis_end_time_s(), 6000.0)

            tab.sampling_duration_checkbox.setChecked(False)
            self.assertFalse(tab.sampling_duration_edit.isEnabled())
            self.assertTrue(tab.analysis_end_time_edit.isEnabled())
            tab.analysis_end_time_edit.setValue(3000.0)
            self.assertEqual(tab._effective_analysis_end_time_s(), 3000.0)

            tab.sampling_duration_checkbox.setChecked(True)
            self.assertTrue(tab.sampling_duration_edit.isEnabled())
            self.assertFalse(tab.analysis_end_time_edit.isEnabled())
            self.assertEqual(tab.sampling_duration_edit.value(), 90.0)
            self.assertEqual(tab.analysis_end_time_edit.value(), 6000.0)

    def test_sampling_duration_mode_rejects_insufficient_data_without_analysis(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, 10.0),
                self._sample(1800.0, 20.0),
                self._sample(3600.0, 30.0),
            ])
            tab.sampling_duration_checkbox.setChecked(True)
            tab.sampling_duration_edit.setValue(60.0)
            tab.analysis_start_time_edit.setValue(1800.0)

            with patch("gui.tabs.q_current_tab.QMessageBox.warning") as warning_box:
                tab.btn_run.click()
                self._wait_for_idle(tab)

            warning_box.assert_called_once()
            self.assertIn("Insufficient data for the selected sampling duration", warning_box.call_args.args[2])
            self.assertIsNone(tab.current_analysis_result)
            self.assertEqual(tab.analysis_progress_bar.text(), "ANALYSIS ERROR")

    def test_manual_end_mode_filters_analysis_and_qmenu_end_is_mode_aware(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, 10.0),
                self._sample(1800.0, 20.0),
                self._sample(3600.0, 30.0),
                self._sample(7200.0, 40.0),
            ])
            tab.wake_limit_edit.setValue(1000.0)
            review_menu, review_actions = tab._create_review_context_menu()
            self.assertFalse(review_actions["set_end_time"].isEnabled())
            chart_menu, chart_actions = tab._create_chart_context_menu("pin")
            self.assertFalse(chart_actions["set_end_time"].isEnabled())

            tab.sampling_duration_checkbox.setChecked(False)
            review_menu, review_actions = tab._create_review_context_menu()
            self.assertTrue(review_actions["set_end_time"].isEnabled())
            chart_menu, chart_actions = tab._create_chart_context_menu("pin")
            self.assertTrue(chart_actions["set_end_time"].isEnabled())
            self.assertTrue(tab.set_analysis_start_from_review_row(1))
            self.assertTrue(tab.set_analysis_end_from_chart_sample(2))
            self.assertEqual(tab.analysis_start_time_edit.value(), 1800.0)
            self.assertEqual(tab.analysis_end_time_edit.value(), 3600.0)

            tab.btn_run.click()
            self._wait_for_idle(tab)

            self.assertEqual(tab.current_analysis_result.total_samples, 2)
            self.assertEqual(tab.current_analysis_result.start_time_s, 1800.0)
            self.assertEqual(tab.current_analysis_result.end_time_s, 3600.0)
            self.assertFalse(tab.current_analysis_settings.sampling_duration_enabled)

    def test_clear_preserves_sampling_duration_project_config_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab.sampling_duration_checkbox.setChecked(True)
            tab.sampling_duration_edit.setValue(90.0)
            tab._load_samples_into_workspace([
                self._sample(0.0, 1.0),
                self._sample(7200.0, 2.0),
            ])
            tab.analysis_start_time_edit.setValue(600.0)

            tab.btn_clear.click()

            self.assertTrue(tab.sampling_duration_checkbox.isChecked())
            self.assertEqual(tab.sampling_duration_edit.value(), 90.0)
            self.assertEqual(tab.analysis_start_time_edit.value(), 0.0)
            self.assertEqual(tab.analysis_end_time_edit.value(), 0.0)
            self.assertFalse(tab.analysis_start_time_edit.isEnabled())
            self.assertFalse(tab.analysis_end_time_edit.isEnabled())

    def test_unsaved_q_current_config_changes_do_not_survive_restart(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            database_dir = Path(tmpdir) / "config" / "database_qcurrent"
            config_file = Path(tmpdir) / "config" / "q_current_config.json"
            save_q_current_config(
                QCurrentConfig(30.0, 300.0, 2.0),
                config_file,
            )
            first_tab = QCurrentTab(database_dir=database_dir, config_file=config_file)
            self.addCleanup(first_tab.deleteLater)
            first_tab.current_limit_edit.setValue(25.0)
            first_tab.wake_limit_edit.setValue(250.0)
            first_tab.wake_duration_edit.setValue(3.0)

            second_tab = QCurrentTab(database_dir=database_dir, config_file=config_file)
            self.addCleanup(second_tab.deleteLater)

            self.assertEqual(second_tab.current_limit_edit.value(), 30.0)
            self.assertEqual(second_tab.wake_limit_edit.value(), 300.0)
            self.assertEqual(second_tab.wake_duration_edit.value(), 2.0)

    def test_save_config_writes_global_config_without_running_analysis(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            config_file = Path(tmpdir) / "config" / "q_current_config.json"
            tab.current_limit_edit.setValue(25.0)
            tab.wake_limit_edit.setValue(250.0)
            tab.wake_duration_edit.setValue(3.0)

            with patch("gui.tabs.q_current_tab.analyze_q_current") as analyze, patch.object(
                QMessageBox,
                "information",
            ) as information, patch.object(
                QMessageBox,
                "critical",
            ) as critical:
                tab.save_config_button.click()

            analyze.assert_not_called()
            information.assert_called_once()
            critical.assert_not_called()
            self.assertTrue(config_file.exists())
            restarted_tab = QCurrentTab(
                database_dir=Path(tmpdir) / "config" / "database_qcurrent",
                config_file=config_file,
            )
            self.addCleanup(restarted_tab.deleteLater)
            self.assertEqual(restarted_tab.current_limit_edit.value(), 25.0)
            self.assertEqual(restarted_tab.wake_limit_edit.value(), 250.0)
            self.assertEqual(restarted_tab.wake_duration_edit.value(), 3.0)
            self.assertEqual(tab.analysis_progress_bar.text(), "NOT RUN")
            self.assertFalse(tab._chart_ready)

    def test_save_config_error_does_not_report_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab.current_limit_edit.setValue(300.0)
            tab.wake_limit_edit.setValue(30.0)

            with patch.object(QMessageBox, "information") as information, patch.object(
                QMessageBox,
                "critical",
            ) as critical:
                tab.save_config_button.click()

            information.assert_not_called()
            critical.assert_called_once()
            self.assertFalse((Path(tmpdir) / "config" / "q_current_config.json").exists())

    def test_clear_and_dataset_changes_do_not_reset_q_current_config_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab.current_limit_edit.setValue(25.0)
            tab.wake_limit_edit.setValue(250.0)
            tab.wake_duration_edit.setValue(3.0)
            tab._load_samples_into_workspace([self._sample(0.0, 10.0)])

            tab.btn_clear.click()
            tab.dataset_combo.addItem("A")
            tab.dataset_combo.addItem("B")
            tab.dataset_combo.setCurrentText("B")
            tab._load_samples_into_workspace([self._sample(1.0, 20.0)])

            self.assertEqual(tab.current_limit_edit.value(), 25.0)
            self.assertEqual(tab.wake_limit_edit.value(), 250.0)
            self.assertEqual(tab.wake_duration_edit.value(), 3.0)

    def test_export_uses_run_snapshot_not_saved_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "config" / "q_current_config.json"
            save_q_current_config(QCurrentConfig(30.0, 300.0, 2.0), config_file)
            tab = QCurrentTab(
                database_dir=Path(tmpdir) / "config" / "database_qcurrent",
                config_file=config_file,
            )
            self.addCleanup(tab.deleteLater)
            tab._load_samples_into_workspace([
                self._sample(0.0, 10.0),
                self._sample(1.0, 20.0),
            ])
            tab.current_limit_edit.setValue(25.0)
            tab.wake_limit_edit.setValue(250.0)
            tab.wake_duration_edit.setValue(3.0)
            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)

            with patch.object(
                tab.q_current_report_service,
                "fn_export",
                return_value=None,
            ) as export_report:
                tab.btn_export.click()

            report_data = export_report.call_args.args[1]
            self.assertEqual(report_data.settings.standard_current_ma, 25.0)
            self.assertEqual(report_data.settings.wake_up_limit_ma, 250.0)
            self.assertEqual(report_data.settings.wake_duration_s, 3.0)
            restarted_tab = QCurrentTab(
                database_dir=Path(tmpdir) / "config" / "database_qcurrent",
                config_file=config_file,
            )
            self.addCleanup(restarted_tab.deleteLater)
            self.assertEqual(restarted_tab.current_limit_edit.value(), 30.0)
            self.assertEqual(restarted_tab.wake_limit_edit.value(), 300.0)
            self.assertEqual(restarted_tab.wake_duration_edit.value(), 2.0)
    def test_q_current_action_buttons_start_disabled_until_data_loads(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)

            self.assertTrue(tab.browse_button.isEnabled())
            self.assertTrue(tab.import_button.isEnabled())
            self.assertFalse(tab.btn_run.isEnabled())
            self.assertFalse(tab.btn_copy_data_review.isEnabled())
            self.assertFalse(tab.btn_export.isEnabled())
            self.assertFalse(tab.btn_pin.isEnabled())
            self.assertFalse(tab.btn_capture_chart.isEnabled())
            self.assertFalse(tab.btn_invert_y_axis.isEnabled())
            self.assertFalse(tab.btn_fit_all.isEnabled())
            self.assertFalse(tab.btn_copy_summary.isEnabled())
            self.assertFalse(tab.btn_clear.isEnabled())
            self.assertFalse(hasattr(tab, "btn_copy_chart"))
            self.assertTrue(tab.current_plot.isHidden())
            self.assertFalse(tab.chart_placeholder.isHidden())
            self.assertEqual(tab.wake_up_regions, [])
            self.assertEqual(tab.chart_time_seconds.tolist(), [])
            self.assertEqual(tab.chart_current_ma.tolist(), [])
            self.assertFalse(tab.hover_marker.isVisible())
            self.assertFalse(tab.hover_label.isVisible())
            self.assertIsNotNone(tab.upper_sleep_limit_line)
            self.assertIsNotNone(tab.lower_sleep_limit_line)
            self.assertTrue(tab.chart_scrollbar.isHidden())

    def test_startup_keeps_dataset_combo_empty_until_user_opens_dropdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            database_dir = Path(tmpdir) / "database_qcurrent"
            database_file = database_dir / "sample.db"
            source_file = Path(tmpdir) / "sample.csv"
            source_file.write_text("Trigger time,No1 Average Ch1\n0,0.001\n", encoding="utf-8")
            import_dataset(
                "sample",
                source_file,
                [("0", 0.001, 1.0)],
                database_file,
            )

            tab = QCurrentTab(database_dir=database_dir)
            self.addCleanup(tab.deleteLater)

            self.assertEqual(tab.dataset_combo.count(), 0)

            tab.dataset_combo.showPopup()
            tab.dataset_combo.hidePopup()

            self.assertEqual(tab.dataset_combo.count(), 1)
            self.assertEqual(tab.dataset_combo.itemText(0), "sample")
            self.assertEqual(tab.dataset_combo.itemData(0), str(database_file.resolve()))

    def test_browse_cancel_keeps_existing_path_and_does_not_import(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab.source_file_edit.setText("C:/already/selected.csv")
            tab.source_file_edit.setToolTip("C:/already/selected.csv")

            with patch(
                "gui.tabs.q_current_tab.QFileDialog.getOpenFileName",
                return_value=("", ""),
            ), patch.object(tab, "import_current_file") as import_current_file:
                tab.browse_current_file()

            self.assertEqual(tab.source_file_edit.text(), "C:/already/selected.csv")
            self.assertEqual(tab.source_file_edit.toolTip(), "C:/already/selected.csv")
            self.assertEqual(tab.dataset_combo.count(), 0)
            import_current_file.assert_not_called()

    def test_browse_selects_absolute_file_path_enables_import_and_does_not_add_combo_item(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            source_file = Path(tmpdir) / "sample.csv"
            source_file.write_text("Trigger time,No1 Average Ch1\n0,0.001\n", encoding="utf-8")

            with patch(
                "gui.tabs.q_current_tab.QFileDialog.getOpenFileName",
                return_value=(str(source_file), "CSV Files (*.csv)"),
            ):
                tab.browse_current_file()

            self.assertEqual(tab.source_file_edit.text(), str(source_file.resolve()))
            self.assertEqual(tab.source_file_edit.toolTip(), str(source_file.resolve()))
            self.assertTrue(tab.import_button.isEnabled())
            self.assertEqual(tab.dataset_combo.count(), 0)

    def test_import_button_imports_selected_file_refreshes_combo_and_updates_header_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, database_dir = self._create_tab(tmpdir)
            existing_source = Path(tmpdir) / "VF6_Test.csv"
            existing_source.write_text("Trigger time,No1 Average Ch1\n0,0.001\n", encoding="utf-8")
            existing_database = database_path_for_source(existing_source, database_dir)
            import_dataset(
                "VF6_Test",
                existing_source,
                [("0", 0.001, 1.0)],
                existing_database,
            )
            tab._refresh_dataset_combo()
            self.assertEqual(tab.dataset_combo.currentText(), "VF6_Test")

            source_file = Path(tmpdir) / "sample.csv"
            source_file.write_text("Trigger time,No1 Average Ch7\n0,-1.2E-03\n", encoding="utf-8")
            tab.set_source_file(source_file)

            with patch("gui.tabs.q_current_tab.QMessageBox.information") as info_box:
                tab.import_current_file()
                self._wait_for_idle(tab)

            self.assertEqual(tab.analysis_progress_bar.text(), "IMPORTED")
            self.assertEqual(tab.current_import.row_count, 1)
            expected_database = database_path_for_source(source_file, database_dir)
            self.assertEqual(tab.current_database_path, expected_database)
            self.assertEqual(tab.dataset_combo.count(), 2)
            self.assertEqual(
                {tab.dataset_combo.itemText(index) for index in range(tab.dataset_combo.count())},
                {"VF6_Test", "sample"},
            )
            self.assertEqual(tab.dataset_combo.currentText(), "sample")
            self.assertEqual(tab.dataset_combo.currentData(), str(expected_database.resolve()))
            self.assertEqual(tab.source_file_edit.text(), "")
            self.assertEqual(tab.source_file_edit.toolTip(), "")
            self.assertTrue(tab.import_button.isEnabled())
            self.assertEqual(len(tab.current_samples), 1)
            self.assertTrue(tab.btn_run.isEnabled())
            self.assertTrue(tab.btn_copy_data_review.isEnabled())
            self.assertTrue(tab.btn_clear.isEnabled())
            self.assertFalse(tab.btn_export.isEnabled())
            self.assertFalse(tab.btn_pin.isEnabled())
            self.assertFalse(tab.btn_capture_chart.isEnabled())
            self.assertFalse(tab.btn_invert_y_axis.isEnabled())
            self.assertFalse(tab.btn_fit_all.isEnabled())
            self.assertFalse(tab.btn_copy_summary.isEnabled())
            self.assertIsNone(tab.current_curve.getData()[0])
            self.assertTrue(expected_database.exists())
            info_box.assert_called_once()

    def test_import_button_loads_selected_dataset_into_data_review(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, database_dir = self._create_tab(tmpdir)
            source_file = Path(tmpdir) / "sample.csv"
            source_file.write_text("Trigger time,No1 Average Ch1\n0,0.001\n", encoding="utf-8")
            database_file = database_path_for_source(source_file, database_dir)
            import_dataset(
                "sample",
                source_file,
                [
                    ("26-09-11 11:41:29.036", -0.0169, -16.9),
                    ("26-09-11 11:41:30.079", -0.0173, -17.3),
                    ("26-09-11 11:41:31.101", -0.0158, -15.8),
                ],
                database_file,
            )
            tab._refresh_dataset_combo(selected_db_path=database_file)
            self.assertEqual(tab.source_file_edit.text(), "")

            with patch("gui.tabs.q_current_tab.QMessageBox.warning") as warning_box:
                tab.import_current_file()
                self._wait_for_idle(tab)

            self.assertEqual(tab.current_database_path, database_file.resolve())
            self.assertEqual(len(tab.current_samples), 3)
            self.assertEqual(tab.review_table.model().rowCount(), 3)
            self.assertEqual(tab.review_table.model().columnCount(), 3)
            self.assertEqual(
                [tab.review_table.model().headerData(index, Qt.Horizontal) for index in range(3)],
                ["No.", "Time", "Current (mA)"],
            )
            self.assertEqual(tab.review_table.model().index(0, 0).data(), "1")
            self.assertEqual(tab.review_table.model().index(0, 1).data(), "26-09-11 11:41:29.036")
            self.assertEqual(tab.review_table.model().index(0, 2).data(), "-16.90")
            self.assertEqual(tab.review_table.model().index(2, 0).data(), "3")
            self.assertEqual(tab.review_table.model().index(2, 2).data(), "-15.80")
            self.assertTrue(tab.import_button.isEnabled())
            self.assertTrue(tab.btn_run.isEnabled())
            self.assertTrue(tab.btn_copy_data_review.isEnabled())
            self.assertTrue(tab.btn_clear.isEnabled())
            self.assertFalse(tab.btn_export.isEnabled())
            self.assertFalse(tab.btn_pin.isEnabled())
            self.assertFalse(tab.btn_capture_chart.isEnabled())
            self.assertFalse(tab.btn_invert_y_axis.isEnabled())
            self.assertFalse(tab.btn_fit_all.isEnabled())
            self.assertFalse(tab.btn_copy_summary.isEnabled())
            warning_box.assert_not_called()

    def test_review_table_selection_clears_when_focus_leaves(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._populate_review_table([
                type("Sample", (), {"time": "26-09-11 11:41:29.036", "current_mA": -16.9})(),
            ])

            tab.review_table.selectRow(0)
            self.assertTrue(tab.review_table.selectionModel().selectedIndexes())

            tab.review_table.focusOutEvent(QFocusEvent(QEvent.FocusOut))

            self.assertFalse(tab.review_table.selectionModel().selectedIndexes())
            self.assertEqual(tab.review_table.currentIndex().row(), -1)

    def test_loading_selected_dataset_resets_review_scrollbar_to_top(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, database_dir = self._create_tab(tmpdir)
            first_source = Path(tmpdir) / "first.csv"
            second_source = Path(tmpdir) / "second.csv"
            first_source.write_text("Trigger time,No1 Average Ch1\n0,0.001\n", encoding="utf-8")
            second_source.write_text("Trigger time,No1 Average Ch1\n0,0.002\n", encoding="utf-8")
            first_database = database_path_for_source(first_source, database_dir)
            second_database = database_path_for_source(second_source, database_dir)
            import_dataset(
                "first",
                first_source,
                [(str(index), 0.001, 1.0) for index in range(30)],
                first_database,
            )
            import_dataset(
                "second",
                second_source,
                [(str(index), 0.002, 2.0) for index in range(30)],
                second_database,
            )
            tab._refresh_dataset_combo(selected_db_path=first_database)
            tab.import_current_file()
            self._wait_for_idle(tab)
            scrollbar = tab.review_table.verticalScrollBar()
            scrollbar.setRange(0, 100)
            scrollbar.setValue(80)
            tab.dataset_combo.setCurrentIndex(
                tab.dataset_combo.findData(str(second_database.resolve()))
            )

            tab.import_current_file()
            self._wait_for_idle(tab)

            self.assertEqual(tab.current_database_path, second_database.resolve())
            self.assertEqual(scrollbar.value(), scrollbar.minimum())

    def test_copy_data_review_and_summary_buttons_copy_table_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._populate_review_table([
                type("Sample", (), {"time": "26-09-11 11:41:29.036", "current_mA": -16.9})(),
                type("Sample", (), {"time": "26-09-11 11:41:30.079", "current_mA": -17.3})(),
            ])
            tab.summary_widget.summary_values["result_status"].setText("PASSED")
            tab.summary_widget.summary_values["average_sleep_current_ma"].setText("17.10 mA")
            tab.summary_widget.summary_values["total_samples"].setText("2")

            tab.copy_data_review()

            self.assertEqual(
                QApplication.clipboard().text(),
                "No.\tTime\tCurrent (mA)\n"
                "1\t26-09-11 11:41:29.036\t-16.90\n"
                "2\t26-09-11 11:41:30.079\t-17.30",
            )

            tab.copy_summary()

            self.assertEqual(
                QApplication.clipboard().text(),
                "SUMMARY\n"
                "\n"
                "RESULT: PASSED\n"
                "\n"
                "CURRENT STATISTICS\n"
                "Average Sleep Current: 17.10 mA\n"
                "Minimum Sleep Current: N/A\n"
                "Maximum Sleep Current: N/A\n"
                "\n"
                "WAKE-UP STATISTICS\n"
                "Wake-up Events: N/A\n"
                "Total Wake-up Duration: N/A\n"
                "Average Wake-up Duration: N/A\n"
                "Maximum Wake-up Duration: N/A\n"
                "Average Wake-up Interval: N/A\n"
                "Minimum Wake-up Interval: N/A\n"
                "Maximum Wake-up Interval: N/A\n"
                "Longest Continuous Sleep: N/A\n"
                "\n"
                "TEST INFORMATION\n"
                "Start Time: N/A\n"
                "End Time: N/A\n"
                "Duration: N/A\n"
                "Total Samples: 2\n"
                "Sample Interval: N/A",
            )


    def test_calculate_elapsed_seconds_uses_real_timestamp_differences(self):
        samples = [
            type("Sample", (), {"time": "26-09-11 11:41:29.036"})(),
            type("Sample", (), {"time": "26-09-11 11:41:30.079"})(),
            type("Sample", (), {"time": "26-09-11 11:41:31.150"})(),
        ]

        elapsed_seconds = calculate_elapsed_seconds(samples)

        self.assertEqual(elapsed_seconds, [0.0, 1.043, 2.114])

    def test_run_draws_current_chart_thresholds_and_enables_chart_actions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, database_dir = self._create_tab(tmpdir)
            source_file = Path(tmpdir) / "sample.csv"
            source_file.write_text("Trigger time,No1 Average Ch1\n0,0.001\n", encoding="utf-8")
            database_file = database_path_for_source(source_file, database_dir)
            import_dataset(
                "sample",
                source_file,
                [
                    ("26-09-11 11:41:29.036", -0.0169, -16.9),
                    ("26-09-11 11:41:30.079", -0.0173, -17.3),
                    ("26-09-11 11:41:31.150", -0.0181, -18.1),
                ],
                database_file,
            )
            tab._refresh_dataset_combo(selected_db_path=database_file)
            tab.import_current_file()
            self._wait_for_idle(tab)

            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)

            current_x, current_y = tab.current_curve.getData()
            self.assertEqual([round(value, 3) for value in current_x.tolist()], [0.0, 1.043, 2.114])
            self.assertEqual([round(value, 2) for value in current_y.tolist()], [-16.9, -17.3, -18.1])
            self.assertEqual(tab.upper_sleep_limit_line.value(), tab.current_limit_edit.value())
            self.assertEqual(tab.lower_sleep_limit_line.value(), -tab.current_limit_edit.value())
            self.assertFalse(tab.upper_sleep_limit_line.movable)
            self.assertFalse(tab.lower_sleep_limit_line.movable)
            self.assertEqual(tab.wake_up_regions, [])
            self.assertEqual(self._legend_labels(tab), [
                "Current",
                "Sleep threshold",
                "Wake-up",
            ])
            self.assertIsNone(tab.current_plot.getPlotItem().legend)
            self.assertTrue(tab.btn_export.isEnabled())
            self.assertFalse(tab.btn_pin.isEnabled())
            self.assertTrue(tab.btn_capture_chart.isEnabled())
            self.assertTrue(tab.btn_invert_y_axis.isEnabled())
            self.assertTrue(tab.btn_fit_all.isEnabled())
            self.assertTrue(tab.btn_copy_summary.isEnabled())
            self.assertFalse(tab.current_plot.isHidden())
            self.assertTrue(tab.chart_placeholder.isHidden())
            self.assertTrue(tab.chart_scrollbar.isHidden())
            self.assertEqual(tab.analysis_progress_bar.text(), "PASSED")
            self.assertEqual(tab.chart_time_seconds.tolist(), [0.0, 1.043, 2.114])
            self.assertEqual(tab.chart_current_ma.tolist(), [-16.9, -17.3, -18.1])
            bottom_axis = tab.current_plot.getPlotItem().getAxis("bottom")
            left_axis = tab.current_plot.getPlotItem().getAxis("left")
            self.assertEqual(bottom_axis.labelText, "Time (s)")
            self.assertEqual(left_axis.labelText, "Current (mA)")
            self.assertFalse(getattr(bottom_axis, "autoSIPrefix", True))
            self.assertFalse(getattr(left_axis, "autoSIPrefix", True))

    def test_export_button_exports_completed_analysis_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab.dataset_combo.addItem("VF8_Sleep_Current")
            tab.dataset_combo.setCurrentText("VF8_Sleep_Current")
            tab._load_samples_into_workspace([
                self._sample(0.0, 10.0),
                self._sample(1.0, -20.0),
            ])
            tab.current_limit_edit.setValue(30.0)
            tab.wake_limit_edit.setValue(300.0)
            tab.wake_duration_edit.setValue(2.0)
            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)

            output_file = Path(tmpdir) / "report.xlsx"
            with patch.object(
                tab.q_current_report_service,
                "fn_export",
                return_value=output_file,
            ) as export_report, patch(
                "gui.tabs.q_current_tab.show_export_toast",
            ) as information, patch.object(
                QMessageBox,
                "critical",
            ) as critical:
                tab.btn_export.click()

            export_report.assert_called_once()
            report_data = export_report.call_args.args[1]
            self.assertEqual(report_data.dataset_name, "VF8_Sleep_Current")
            self.assertEqual(len(report_data.samples), 2)
            self.assertEqual(report_data.analysis_result.result_status, "PASSED")
            self.assertEqual(report_data.settings.standard_current_ma, 30.0)
            self.assertEqual(report_data.settings.wake_up_limit_ma, 300.0)
            self.assertEqual(report_data.settings.wake_duration_s, 2.0)
            self.assertIsInstance(report_data.chart_png, bytes)
            self.assertGreater(len(report_data.chart_png), 0)
            information.assert_called_once()
            critical.assert_not_called()

    def test_export_cancel_does_not_show_message(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([self._sample(0.0, 10.0)])
            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)

            with patch.object(
                tab.q_current_report_service,
                "fn_export",
                return_value=None,
            ) as export_report, patch(
                "gui.tabs.q_current_tab.show_export_toast",
            ) as information, patch.object(
                QMessageBox,
                "critical",
            ) as critical:
                tab.btn_export.click()

            export_report.assert_called_once()
            information.assert_not_called()
            critical.assert_not_called()

    def test_export_error_shows_critical_message(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([self._sample(0.0, 10.0)])
            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)

            with patch.object(
                tab.q_current_report_service,
                "fn_export",
                side_effect=PermissionError("locked"),
            ), patch(
                "gui.tabs.q_current_tab.show_export_toast",
            ) as information, patch.object(
                QMessageBox,
                "critical",
            ) as critical:
                tab.btn_export.click()

            information.assert_not_called()
            critical.assert_called_once()
    def test_run_populates_summary_status_and_resets_on_clear(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, 10.0),
                self._sample(1.0, -20.0),
            ])

            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)

            self.assertEqual(tab.summary_widget.summary_values["result_status"].text(), "PASSED")
            self.assertEqual(tab.analysis_progress_bar.text(), "PASSED")
            self.assertEqual(tab.summary_widget.summary_values["average_sleep_current_ma"].text(), "15.00 mA")
            self.assertIn(ThemeManager.fn_colors().SUCCESS, tab.summary_widget.summary_values["result_status"].styleSheet())
            self.assertIn(ThemeManager.fn_colors().SUCCESS, tab.analysis_progress_bar.styleSheet())
            self.assertIn("font-weight: 700", tab.analysis_progress_bar.styleSheet())

            tab.btn_clear.click()

            self.assertEqual(tab.summary_widget.summary_values["result_status"].text(), PLACEHOLDER_VALUE)
            self.assertEqual(tab.analysis_progress_bar.text(), "NOT RUN")
            self.assertNotIn(ThemeManager.fn_colors().DANGER, tab.analysis_progress_bar.styleSheet())
            self.assertNotIn("font-weight: 700", tab.analysis_progress_bar.styleSheet())
            self.assertFalse(tab.btn_copy_summary.isEnabled())

    def test_run_marks_summary_failed_with_danger_theme(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, 40.0),
                self._sample(1.0, -50.0),
            ])

            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)
            ThemeManager.fn_set_theme(ThemeType.DARK)
            tab.fn_refresh_theme()

            self.assertEqual(tab.summary_widget.summary_values["result_status"].text(), "FAILED")
            self.assertEqual(tab.analysis_progress_bar.text(), "FAILED")
            self.assertIn(ThemeManager.fn_colors().DANGER, tab.summary_widget.summary_values["result_status"].styleSheet())
            self.assertIn(ThemeManager.fn_colors().DANGER, tab.analysis_progress_bar.styleSheet())
            self.assertIn("font-weight: 700", tab.analysis_progress_bar.styleSheet())

    def test_summary_uses_database_time_only_and_preserves_elapsed_duration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample("2026-09-29 23:58:00", 10.0),
                self._sample("2026-09-30 00:10:00", -20.0),
            ])

            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)

            self.assertEqual(tab.summary_widget.summary_values["source_start_time"].text(), "23:58:00")
            self.assertEqual(tab.summary_widget.summary_values["source_end_time"].text(), "00:10:00")
            self.assertEqual(tab.summary_widget.summary_values["duration_s"].text(), "12 min 0.000 s")
            copied_text = tab.summary_widget.to_text()
            self.assertIn("Start Time: 23:58:00", copied_text)
            self.assertIn("End Time: 00:10:00", copied_text)
            self.assertNotIn("2026-09-29", copied_text)
            self.assertNotIn("0.000 s", copied_text.split("TEST INFORMATION", 1)[1].split("Duration", 1)[0])

    def test_analysis_result_style_resets_after_import_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, 10.0),
                self._sample(1.0, 20.0),
            ])
            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)
            self.assertEqual(tab.analysis_progress_bar.text(), "PASSED")
            self.assertIn(ThemeManager.fn_colors().SUCCESS, tab.analysis_progress_bar.styleSheet())

            tab._set_analysis_result("IMPORTED")

            self.assertEqual(tab.analysis_progress_bar.text(), "IMPORTED")
            self.assertNotIn(ThemeManager.fn_colors().SUCCESS, tab.analysis_progress_bar.styleSheet())
            self.assertNotIn("font-weight: 700", tab.analysis_progress_bar.styleSheet())

    def test_long_time_range_uses_horizontal_chart_scrollbar(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, database_dir = self._create_tab(tmpdir)
            source_file = Path(tmpdir) / "long_sample.csv"
            source_file.write_text("Trigger time,No1 Average Ch1\n0,0.001\n", encoding="utf-8")
            database_file = database_path_for_source(source_file, database_dir)
            import_dataset(
                "long_sample",
                source_file,
                [(str(seconds), 0.001, float(index)) for index, seconds in enumerate((0, 200, 400, 600, 800))],
                database_file,
            )
            tab._refresh_dataset_combo(selected_db_path=database_file)
            tab.import_current_file()
            self._wait_for_idle(tab)

            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)

            self.assertFalse(tab.chart_scrollbar.isHidden())
            self.assertGreater(tab.chart_scrollbar.maximum(), 0)
            tab.chart_scrollbar.setValue(tab.chart_scrollbar.maximum())

            start_range, end_range = tab.current_plot.getPlotItem().viewRange()[0]
            self.assertAlmostEqual(start_range, 400.0, places=3)
            self.assertAlmostEqual(end_range, 800.0, places=3)

    def test_run_highlights_wake_up_regions_and_keeps_signed_current_curve(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab.wake_limit_edit.setValue(300.0)
            tab.wake_duration_edit.setValue(2.0)
            tab._load_samples_into_workspace([
                self._sample(0.0, 10.0),
                self._sample(1.0, -40.0),
                self._sample(2.0, -50.0),
                self._sample(3.5, -60.0),
                self._sample(5.0, 20.0),
                self._sample(6.0, 350.0),
                self._sample(6.5, 360.0),
            ])

            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)

            current_x, current_y = tab.current_curve.getData()
            self.assertEqual(current_x.tolist(), [0.0, 1.0, 2.0, 3.5, 5.0, 6.0, 6.5])
            self.assertEqual(current_y.tolist(), [10.0, -40.0, -50.0, -60.0, 20.0, 350.0, 360.0])
            self.assertEqual(len(tab.wake_up_regions), 1)
            self.assertEqual(tab.wake_up_regions[0].getRegion(), (1.0, 3.5))
            self.assertEqual(tab.summary_widget.summary_values["average_sleep_current_ma"].text(), "36.00 mA")
            self.assertEqual(tab.wake_up_regions[0].zValue(), -10)
            self.assertFalse(tab.wake_up_regions[0].movable)

            ThemeManager.fn_set_theme(ThemeType.DARK)
            tab.fn_refresh_theme()

            self.assertEqual(len(tab.wake_up_regions), 1)
            self.assertEqual(tab.wake_up_regions[0].getRegion(), (1.0, 3.5))
            self.assertEqual(tab.summary_widget.summary_values["average_sleep_current_ma"].text(), "36.00 mA")
            themed_x, themed_y = tab.current_curve.getData()
            self.assertEqual(themed_x.tolist(), current_x.tolist())
            self.assertEqual(themed_y.tolist(), current_y.tolist())

    def test_analysis_range_initializes_from_dataset_and_filters_run_inputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, 10.0),
                self._sample(1.0, 20.0),
                self._sample(2.0, 100.0),
                self._sample(3.0, 120.0),
            ])
            tab.sampling_duration_checkbox.setChecked(False)
            tab.wake_limit_edit.setValue(1000.0)

            self.assertTrue(tab.analysis_start_time_edit.isEnabled())
            self.assertTrue(tab.analysis_end_time_edit.isEnabled())
            self.assertEqual(tab.analysis_start_time_edit.value(), 0.0)
            self.assertEqual(tab.analysis_end_time_edit.value(), 3.0)
            self.assertEqual(tab.review_table.model().rowCount(), 4)

            tab.analysis_start_time_edit.setValue(2.0)
            tab.analysis_end_time_edit.setValue(3.0)
            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)

            self.assertEqual(tab.current_curve.getData()[0].tolist(), [0.0, 1.0, 2.0, 3.0])
            self.assertEqual(tab.chart_time_seconds.tolist(), [0.0, 1.0, 2.0, 3.0])
            self.assertEqual(tab.current_analysis_result.total_samples, 2)
            self.assertEqual(tab.current_analysis_result.start_time_s, 2.0)
            self.assertEqual(tab.current_analysis_result.end_time_s, 3.0)
            self.assertEqual(tab.current_analysis_result.duration_s, 1.0)
            self.assertEqual(tab.current_analysis_result.average_sleep_current_ma, 110.0)
            self.assertEqual(tab.current_analysis_settings.analysis_start_time_s, 2.0)
            self.assertEqual(tab.current_analysis_settings.analysis_end_time_s, 3.0)

    def test_analysis_range_includes_boundaries_and_handles_irregular_samples(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, 10.0),
                self._sample(0.7, 20.0),
                self._sample(2.4, 30.0),
                self._sample(5.8, 40.0),
            ])
            tab.sampling_duration_checkbox.setChecked(False)
            tab.wake_limit_edit.setValue(1000.0)
            tab.analysis_start_time_edit.setValue(0.7)
            tab.analysis_end_time_edit.setValue(2.4)

            tab.btn_run.click()
            self._wait_for_idle(tab)

            self.assertEqual(tab.current_analysis_result.total_samples, 2)
            self.assertEqual(tab.current_analysis_result.start_time_s, 0.7)
            self.assertEqual(tab.current_analysis_result.end_time_s, 2.4)
            self.assertEqual(tab.current_analysis_result.average_sleep_current_ma, 25.0)

    def test_invalid_or_empty_analysis_range_warns_without_running(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, 10.0),
                self._sample(100.0, 20.0),
                self._sample(200.0, 30.0),
            ])
            tab.sampling_duration_checkbox.setChecked(False)
            tab.analysis_start_time_edit.setValue(100.0)
            tab.analysis_end_time_edit.setValue(0.0)
            with patch("gui.tabs.q_current_tab.QMessageBox.warning") as warning_box:
                tab.btn_run.click()
                self._wait_for_idle(tab)
            warning_box.assert_called_once()
            self.assertIn("Start Time must be less than End Time", warning_box.call_args.args[2])
            self.assertIsNone(tab.current_analysis_result)
            self.assertEqual(tab.analysis_progress_bar.text(), "ANALYSIS ERROR")

            tab.analysis_start_time_edit.setValue(20.0)
            tab.analysis_end_time_edit.setValue(30.0)
            with patch("gui.tabs.q_current_tab.QMessageBox.warning") as warning_box:
                tab.btn_run.click()
                self._wait_for_idle(tab)
            warning_box.assert_called_once()
            self.assertIn("No samples exist inside", warning_box.call_args.args[2])
            self.assertIsNone(tab.current_analysis_result)

    def test_analysis_range_can_be_set_from_review_rows_without_touching_cursors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, 10.0),
                self._sample(42.5, 182.3),
                self._sample(48.2, 179.8),
            ])
            tab.sampling_duration_checkbox.setChecked(False)

            self.assertTrue(tab.set_analysis_start_from_review_row(1))
            self.assertEqual(tab.analysis_start_time_edit.value(), 42.5)
            self.assertIsNone(tab.cursor_a_index)
            self.assertTrue(tab.set_analysis_end_from_review_row(2))
            self.assertEqual(tab.analysis_end_time_edit.value(), 48.2)
            self.assertIsNone(tab.cursor_b_index)

            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)
            tab.set_cursor_a(0)
            tab.set_cursor_b(2)
            self.assertEqual(tab.analysis_start_time_edit.value(), 42.5)
            self.assertEqual(tab.analysis_end_time_edit.value(), 48.2)

            tab.analysis_start_time_edit.setValue(43.0)
            tab.analysis_end_time_edit.setValue(47.0)
            self.assertEqual(tab.analysis_start_time_edit.value(), 43.0)
            self.assertEqual(tab.analysis_end_time_edit.value(), 47.0)
            self.assertEqual(tab.cursor_a_index, 0)
            self.assertEqual(tab.cursor_b_index, 2)
            self.assertEqual(tab.cursor_a_value_label.text(), "A: 0.000 s | 10.00 mA")
            self.assertEqual(tab.cursor_b_value_label.text(), "B: 48.200 s | 179.80 mA")
            self.assertEqual(tab.analysis_progress_bar.text(), "NOT RUN")

    def test_analysis_range_resets_for_new_dataset_and_clear(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, 1.0),
                self._sample(100.0, 2.0),
            ])
            tab.sampling_duration_checkbox.setChecked(False)
            tab.analysis_start_time_edit.setValue(20.0)
            tab.analysis_end_time_edit.setValue(80.0)

            tab._load_samples_into_workspace([
                self._sample(0.0, 1.0),
                self._sample(500.0, 2.0),
            ])
            self.assertEqual(tab.analysis_start_time_edit.value(), 0.0)
            self.assertEqual(tab.analysis_end_time_edit.value(), 500.0)
            self.assertTrue(tab.analysis_start_time_edit.isEnabled())
            self.assertTrue(tab.analysis_end_time_edit.isEnabled())

            tab.btn_clear.click()
            self.assertEqual(tab.analysis_start_time_edit.value(), 0.0)
            self.assertEqual(tab.analysis_end_time_edit.value(), 0.0)
            self.assertFalse(tab.analysis_start_time_edit.isEnabled())
            self.assertFalse(tab.analysis_end_time_edit.isEnabled())
            self.assertIsNone(tab.cursor_a_index)
            self.assertIsNone(tab.cursor_b_index)

    def test_sleep_limit_change_updates_existing_lines_and_marks_not_run(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, 1.0),
                self._sample(1.0, -2.0),
            ])
            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)
            upper_line = tab.upper_sleep_limit_line
            lower_line = tab.lower_sleep_limit_line

            tab.current_limit_edit.setValue(45.0)

            self.assertIs(tab.upper_sleep_limit_line, upper_line)
            self.assertIs(tab.lower_sleep_limit_line, lower_line)
            self.assertEqual(tab.upper_sleep_limit_line.value(), 45.0)
            self.assertEqual(tab.lower_sleep_limit_line.value(), -45.0)
            self.assertEqual(tab.analysis_progress_bar.text(), "NOT RUN")

    def test_review_row_click_does_nothing_before_chart_run(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, 10.0),
                self._sample(1.0, 20.0),
            ])

            tab.review_table.clicked.emit(tab.review_table.model().index(1, 2))

            self.assertFalse(tab.hover_marker.isVisible())
            self.assertFalse(tab.hover_label.isVisible())
            self.assertFalse(tab._chart_ready)
            self.assertEqual(tab.analysis_progress_bar.text(), "NOT RUN")

    def test_review_row_click_highlights_same_sample_from_any_column(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, 10.0),
                self._sample(1.0, -28.46),
                self._sample(2.0, 12.0),
            ])
            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)

            tab.review_table.clicked.emit(tab.review_table.model().index(1, 1))
            first_marker_x, first_marker_y = tab.hover_marker.getData()
            tab.review_table.clicked.emit(tab.review_table.model().index(1, 2))
            second_marker_x, second_marker_y = tab.hover_marker.getData()

            self.assertEqual(first_marker_x.tolist(), [1.0])
            self.assertEqual(first_marker_y.tolist(), [-28.46])
            self.assertEqual(second_marker_x.tolist(), [1.0])
            self.assertEqual(second_marker_y.tolist(), [-28.46])
            hover_html = tab.hover_label.toHtml().replace("\xa0", " ")
            self.assertIn("Time: 1.000 s", hover_html)
            self.assertIn("Current: -28.46 mA", hover_html)
            self.assertTrue(tab.hover_marker.isVisible())
            self.assertTrue(tab.hover_label.isVisible())

    def test_review_row_click_uses_same_window_as_scrollbar_navigation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, 1.0),
                self._sample(200.0, 2.0),
                self._sample(600.0, 3.0),
                self._sample(1000.0, 4.0),
            ])
            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)
            scroll_value = int(round((600.0 - tab._chart_visible_span / 2.0) * CHART_SCROLL_SCALE))
            tab.chart_scrollbar.setValue(scroll_value)
            scrollbar_range = tab.current_plot.getPlotItem().viewRange()[0]
            tab._set_chart_x_range(0.0, 20.0, padding=0)

            tab.review_table.clicked.emit(tab.review_table.model().index(2, 2))

            row_range = tab.current_plot.getPlotItem().viewRange()[0]
            self.assertAlmostEqual(row_range[0], scrollbar_range[0], places=3)
            self.assertAlmostEqual(row_range[1], scrollbar_range[1], places=3)
            self.assertAlmostEqual(row_range[1] - row_range[0], tab._chart_visible_span, places=3)
            self.assertEqual(tab.chart_scrollbar.value(), scroll_value)
            marker_x, marker_y = tab.hover_marker.getData()
            self.assertEqual(marker_x.tolist(), [600.0])
            self.assertEqual(marker_y.tolist(), [3.0])

    def test_review_row_click_clamps_to_dataset_start_and_end_with_scrollbar_window(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, 1.0),
                self._sample(200.0, 2.0),
                self._sample(600.0, 3.0),
                self._sample(1000.0, 4.0),
            ])
            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)

            tab.review_table.clicked.emit(tab.review_table.model().index(0, 1))
            start_range = tab.current_plot.getPlotItem().viewRange()[0]
            self.assertAlmostEqual(start_range[0], 0.0, places=3)
            self.assertAlmostEqual(start_range[1], tab._chart_visible_span, places=3)
            self.assertEqual(tab.chart_scrollbar.value(), tab.chart_scrollbar.minimum())

            tab.review_table.clicked.emit(tab.review_table.model().index(3, 1))
            end_range = tab.current_plot.getPlotItem().viewRange()[0]
            self.assertAlmostEqual(end_range[1], 1000.0, places=3)
            self.assertAlmostEqual(end_range[1] - end_range[0], tab._chart_visible_span, places=3)
            self.assertEqual(tab.chart_scrollbar.value(), tab.chart_scrollbar.maximum())

    def test_review_row_click_short_dataset_shows_full_dataset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, 1.0),
                self._sample(100.0, 2.0),
                self._sample(200.0, 3.0),
            ])
            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)

            tab.review_table.clicked.emit(tab.review_table.model().index(1, 0))

            x_range = tab.current_plot.getPlotItem().viewRange()[0]
            self.assertAlmostEqual(x_range[0], 0.0, places=3)
            self.assertAlmostEqual(x_range[1], 200.0, places=3)
            self.assertTrue(tab.chart_scrollbar.isHidden())

    def test_review_row_click_preserves_user_zoom_width_for_repeated_selection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, 1.0),
                self._sample(200.0, 2.0),
                self._sample(600.0, 3.0),
                self._sample(1000.0, 4.0),
            ])
            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)
            tab.current_plot.setXRange(100.0, 200.0, padding=0)
            self.assertTrue(tab._chart_user_zoomed)

            tab.review_table.clicked.emit(tab.review_table.model().index(2, 0))
            first_range = tab.current_plot.getPlotItem().viewRange()[0]
            self.assertAlmostEqual(first_range[0], 550.0, places=3)
            self.assertAlmostEqual(first_range[1], 650.0, places=3)
            self.assertAlmostEqual(first_range[1] - first_range[0], 100.0, places=3)

            tab.review_table.clicked.emit(tab.review_table.model().index(3, 0))
            second_range = tab.current_plot.getPlotItem().viewRange()[0]
            self.assertAlmostEqual(second_range[0], 900.0, places=3)
            self.assertAlmostEqual(second_range[1], 1000.0, places=3)
            self.assertAlmostEqual(second_range[1] - second_range[0], 100.0, places=3)
            self.assertEqual(tab.chart_scrollbar.value(), tab.chart_scrollbar.maximum())

    def test_scrollbar_preserves_user_zoom_width_after_manual_zoom(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, 1.0),
                self._sample(200.0, 2.0),
                self._sample(600.0, 3.0),
                self._sample(1000.0, 4.0),
            ])
            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)
            tab.current_plot.setXRange(100.0, 200.0, padding=0)
            self.assertTrue(tab._chart_user_zoomed)

            tab.chart_scrollbar.setValue(400 * CHART_SCROLL_SCALE)

            x_range = tab.current_plot.getPlotItem().viewRange()[0]
            self.assertAlmostEqual(x_range[0], 400.0, places=3)
            self.assertAlmostEqual(x_range[1], 500.0, places=3)
            self.assertAlmostEqual(x_range[1] - x_range[0], 100.0, places=3)

    def test_fit_all_resets_user_zoom_for_review_row_navigation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, 1.0),
                self._sample(200.0, 2.0),
                self._sample(600.0, 3.0),
                self._sample(1000.0, 4.0),
            ])
            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)
            tab.current_plot.setXRange(100.0, 200.0, padding=0)
            self.assertTrue(tab._chart_user_zoomed)

            tab.btn_fit_all.click()
            self.assertFalse(tab._chart_user_zoomed)
            tab.review_table.clicked.emit(tab.review_table.model().index(2, 0))

            x_range = tab.current_plot.getPlotItem().viewRange()[0]
            self.assertAlmostEqual(x_range[0], 400.0, places=3)
            self.assertAlmostEqual(x_range[1], 800.0, places=3)
            self.assertAlmostEqual(x_range[1] - x_range[0], tab._chart_visible_span, places=3)

    def test_pin_button_pins_selected_review_sample_without_changing_zoom(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, 10.0),
                self._sample(100.0, -20.0),
                self._sample(300.0, 35.5),
            ])
            self.assertFalse(tab.btn_pin.isEnabled())

            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)
            self.assertFalse(tab.btn_pin.isEnabled())
            tab.current_plot.setXRange(80.0, 140.0, padding=0)
            self.assertTrue(tab._chart_user_zoomed)

            tab.review_table.clicked.emit(tab.review_table.model().index(1, 0))
            x_range_before_pin = tab.current_plot.getPlotItem().viewRange()[0]
            y_range_before_pin = tab.current_plot.getPlotItem().viewRange()[1]
            self.assertEqual(tab._selected_review_chart_index, 1)
            self.assertTrue(tab.btn_pin.isEnabled())
            self.assertEqual(tab.chart_pins, [])

            tab.btn_pin.click()

            self.assertEqual([pin.sample_index for pin in tab.chart_pins], [1])
            pin_html = tab.chart_pins[0].label.toHtml().replace("\xa0", " ")
            self.assertIn("Time: 100.000 s", pin_html)
            self.assertIn("Current: -20.00 mA", pin_html)
            self.assertEqual(tab.current_plot.getPlotItem().viewRange()[0], x_range_before_pin)
            self.assertEqual(tab.current_plot.getPlotItem().viewRange()[1], y_range_before_pin)

            tab.btn_pin.click()
            self.assertEqual([pin.sample_index for pin in tab.chart_pins], [1])

            tab.review_table.clicked.emit(tab.review_table.model().index(2, 0))
            self.assertEqual(tab._selected_review_chart_index, 2)
            tab.btn_pin.click()
            self.assertEqual([pin.sample_index for pin in tab.chart_pins], [1, 2])

            tab._load_samples_into_workspace([
                self._sample(0.0, 1.0),
                self._sample(1.0, 2.0),
            ])
            self.assertIsNone(tab._selected_review_chart_index)
            self.assertFalse(tab.btn_pin.isEnabled())

    def test_review_row_click_preserves_inverted_y_and_pins(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, -25.0),
                self._sample(100.0, 10.0),
                self._sample(200.0, 80.0),
            ])
            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)
            tab.pin_chart_sample(0)
            tab.btn_invert_y_axis.click()
            tab.current_plot.setXRange(40.0, 60.0, padding=0)

            tab.review_table.clicked.emit(tab.review_table.model().index(2, 0))

            self.assertTrue(tab._y_axis_inverted)
            self.assertTrue(tab.current_plot.getPlotItem().getViewBox().yInverted())
            self.assertEqual([pin.sample_index for pin in tab.chart_pins], [0])
            self.assertEqual(len(tab.chart_pins), 1)
            marker_x, marker_y = tab.hover_marker.getData()
            self.assertEqual(marker_x.tolist(), [200.0])
            self.assertEqual(marker_y.tolist(), [80.0])
    def test_hover_uses_nearest_sample_without_changing_current_sign(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, 10.0),
                self._sample(1.5, -28.46),
                self._sample(3.0, 12.0),
            ])
            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)

            nearest = tab.find_nearest_sample(1.6)
            self.assertEqual(nearest, (1.5, -28.46))

            tab.update_hover_items(*nearest)

            marker_x, marker_y = tab.hover_marker.getData()
            self.assertEqual(marker_x.tolist(), [1.5])
            self.assertEqual(marker_y.tolist(), [-28.46])
            self.assertTrue(tab.hover_marker.isVisible())
            self.assertFalse(hasattr(tab, "chart_coordinate_label"))
            hover_html = tab.hover_label.toHtml().replace("\xa0", " ")
            self.assertIn("Time: 1.500 s", hover_html)
            self.assertIn("Current: -28.46 mA", hover_html)

    def test_chart_uses_custom_pin_context_menu_without_default_pyqtgraph_menu(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            view_box = tab.current_plot.getPlotItem().getViewBox()

            self.assertFalse(view_box.menuEnabled())
            self.assertEqual(tab._chart_context_action_at_scene_position(None), (None, None))

    def test_context_menus_use_shared_style_and_range_actions_do_not_touch_cursors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, 10.0),
                self._sample(10.5, 20.0),
                self._sample(20.75, 30.0),
            ])
            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)
            tab.set_cursor_a(0)
            tab.set_cursor_b(2)
            cursor_a_before = tab.cursor_a_index
            cursor_b_before = tab.cursor_b_index

            with patch("gui.tabs.q_current_tab.fn_apply_menu_style") as apply_style:
                review_menu, review_actions = tab._create_review_context_menu()
            apply_style.assert_called_once_with(review_menu)
            self.assertEqual(
                [action.text() for action in review_menu.actions()],
                ["Set Start Time", "Set End Time"],
            )
            self.assertIn("set_start_time", review_actions)
            self.assertIn("set_end_time", review_actions)

            self.assertTrue(tab.set_analysis_start_from_review_row(1))
            self.assertTrue(tab.set_analysis_end_from_review_row(2))
            self.assertEqual(tab.analysis_start_time_edit.value(), 10.5)
            self.assertEqual(tab.analysis_end_time_edit.value(), 20.75)
            self.assertEqual(tab.cursor_a_index, cursor_a_before)
            self.assertEqual(tab.cursor_b_index, cursor_b_before)

            with patch("gui.tabs.q_current_tab.fn_apply_menu_style") as apply_style:
                chart_menu, chart_actions = tab._create_chart_context_menu("pin")
            apply_style.assert_called_once_with(chart_menu)
            self.assertIn("set_start_time", chart_actions)
            self.assertIn("set_end_time", chart_actions)

            tab._apply_chart_context_menu_selection(
                chart_actions["set_start_time"],
                chart_actions,
                "pin",
                1,
            )
            tab._apply_chart_context_menu_selection(
                chart_actions["set_end_time"],
                chart_actions,
                "pin",
                2,
            )
            self.assertEqual(tab.analysis_start_time_edit.value(), 10.5)
            self.assertEqual(tab.analysis_end_time_edit.value(), 20.75)
            self.assertEqual(tab.cursor_a_index, cursor_a_before)
            self.assertEqual(tab.cursor_b_index, cursor_b_before)
            self.assertEqual(tab.chart_pins, [])

    def test_chart_ab_cursors_measure_real_elapsed_time_and_signed_current(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, 20.0),
                self._sample(0.4, 182.30),
                self._sample(1.6, 10.0),
                self._sample(6.1, 179.80),
            ])
            self.assertEqual(tab.cursor_a_value_label.text(), "A: — | —")
            self.assertEqual(tab.cursor_b_value_label.text(), "B: — | —")
            self.assertEqual(tab.cursor_delta_time_label.text(), "Δt: —")
            self.assertEqual(tab.cursor_delta_current_label.text(), "ΔI: —")

            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)
            scene_pos = tab._scene_position_for_chart_sample(1)
            action, payload = tab._chart_context_action_at_scene_position(scene_pos)
            self.assertEqual(action, "pin")
            self.assertEqual(payload, 1)
            menu, actions = tab._create_chart_context_menu(action)
            self.assertEqual(
                [item.text() for item in menu.actions() if not item.isSeparator()],
                ["Pin", "Set Start Time", "Set End Time", "Set Cursor A", "Set Cursor B"],
            )

            tab.set_cursor_a(1)
            self.assertEqual(tab.cursor_a_index, 1)
            self.assertEqual(tab.cursor_a_value_label.text(), "A: 0.400 s | 182.30 mA")
            self.assertEqual(tab.cursor_b_value_label.text(), "B: — | —")
            self.assertEqual(tab.cursor_delta_time_label.text(), "Δt: —")
            self.assertEqual(tab.cursor_delta_current_label.text(), "ΔI: —")
            self.assertTrue(tab.cursor_a_marker.isVisible())
            self.assertTrue(tab.cursor_a_line.isVisible())
            self.assertTrue(tab.cursor_a_label.isVisible())

            tab.set_cursor_b(3)
            self.assertEqual(tab.cursor_b_index, 3)
            self.assertEqual(tab.cursor_b_value_label.text(), "B: 6.100 s | 179.80 mA")
            self.assertEqual(tab.cursor_delta_time_label.text(), "Δt: 5.700 s")
            self.assertEqual(tab.cursor_delta_current_label.text(), "ΔI: -2.50 mA")
            self.assertTrue(tab.cursor_b_marker.isVisible())
            self.assertTrue(tab.cursor_b_line.isVisible())
            self.assertTrue(tab.cursor_b_label.isVisible())

            tab.set_cursor_a(0)
            self.assertEqual(tab.cursor_a_index, 0)
            self.assertEqual(tab.cursor_a_value_label.text(), "A: 0.000 s | 20.00 mA")
            self.assertEqual(tab.cursor_delta_time_label.text(), "Δt: 6.100 s")
            self.assertEqual(tab.cursor_delta_current_label.text(), "ΔI: +159.80 mA")

            tab.current_plot.setXRange(1.0, 2.0, padding=0)
            x_range_before_pin_clear = tab.current_plot.getPlotItem().viewRange()[0]
            tab.pin_chart_sample(2)
            self.assertEqual(len(tab.chart_pins), 1)
            tab.clear_chart_pins()
            self.assertEqual(tab.chart_pins, [])
            self.assertEqual(tab.cursor_a_index, 0)
            self.assertEqual(tab.cursor_b_index, 3)
            self.assertEqual(tab.cursor_delta_current_label.text(), "ΔI: +159.80 mA")
            self.assertEqual(tab.current_plot.getPlotItem().viewRange()[0], x_range_before_pin_clear)

            tab.clear_ab_cursors()
            self.assertIsNone(tab.cursor_a_index)
            self.assertIsNone(tab.cursor_b_index)
            self.assertEqual(tab.cursor_a_value_label.text(), "A: — | —")
            self.assertEqual(tab.cursor_b_value_label.text(), "B: — | —")
            self.assertEqual(tab.cursor_delta_time_label.text(), "Δt: —")
            self.assertEqual(tab.cursor_delta_current_label.text(), "ΔI: —")
            self.assertFalse(tab.cursor_a_marker.isVisible())
            self.assertFalse(tab.cursor_b_marker.isVisible())

    def test_chart_pin_context_adds_multiple_pins_prevents_duplicates_and_deletes_one(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, 10.0),
                self._sample(1.5, -28.46),
                self._sample(3.0, 12.0),
            ])
            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)

            first_scene_pos = tab._scene_position_for_chart_sample(1)
            action, payload = tab._chart_context_action_at_scene_position(first_scene_pos)
            self.assertEqual(action, "pin")
            self.assertEqual(payload, 1)
            menu, actions = tab._create_chart_context_menu(action)
            self.assertEqual(
                [item.text() for item in menu.actions() if not item.isSeparator()],
                ["Pin", "Set Start Time", "Set End Time", "Set Cursor A", "Set Cursor B"],
            )
            self.assertIsNone(actions["clear_all_pins"])

            self.assertTrue(tab.pin_chart_sample(payload))
            self.assertEqual(len(tab.chart_pins), 1)
            self.assertEqual(tab.chart_pins[0].sample_index, 1)
            self.assertEqual(tab.chart_pins[0].time_s, 1.5)
            self.assertEqual(tab.chart_pins[0].current_ma, -28.46)
            pin_html = tab.chart_pins[0].label.toHtml().replace("\xa0", " ")
            self.assertIn("Time: 1.500 s", pin_html)
            self.assertIn("Current: -28.46 mA", pin_html)

            action, payload = tab._chart_context_action_at_scene_position(first_scene_pos)
            self.assertEqual(action, "delete")
            self.assertIs(payload, tab.chart_pins[0])
            menu, actions = tab._create_chart_context_menu(action)
            self.assertEqual(
                ["---" if item.isSeparator() else item.text() for item in menu.actions()],
                [
                    "Delete Pin",
                    "---",
                    "Set Start Time",
                    "Set End Time",
                    "Set Cursor A",
                    "Set Cursor B",
                    "---",
                    "Clear All Pins",
                ],
            )
            self.assertIsNotNone(actions["clear_all_pins"])
            self.assertFalse(tab.pin_chart_sample(1))
            self.assertEqual(len(tab.chart_pins), 1)

            normal_scene_pos = tab._scene_position_for_chart_sample(0)
            action, normal_payload = tab._chart_context_action_at_scene_position(normal_scene_pos)
            self.assertEqual(action, "pin")
            self.assertEqual(normal_payload, 0)
            menu, actions = tab._create_chart_context_menu(action)
            self.assertEqual(
                ["---" if item.isSeparator() else item.text() for item in menu.actions()],
                [
                    "Pin",
                    "---",
                    "Set Start Time",
                    "Set End Time",
                    "Set Cursor A",
                    "Set Cursor B",
                    "---",
                    "Clear All Pins",
                ],
            )
            self.assertIsNotNone(actions["clear_all_pins"])

            self.assertTrue(tab.pin_chart_sample(2))
            self.assertEqual(len(tab.chart_pins), 2)
            tab.hide_hover_items()
            self.assertEqual(len(tab.chart_pins), 2)

            tab.delete_chart_pin(payload)

            self.assertEqual(len(tab.chart_pins), 1)
            self.assertEqual(tab.chart_pins[0].sample_index, 2)
            self.assertEqual(tab.chart_current_ma.tolist(), [10.0, -28.46, 12.0])
            self.assertEqual(
                [sample.current_mA for sample in tab.current_samples],
                [10.0, -28.46, 12.0],
            )

    def test_chart_pins_survive_view_actions_and_clear_with_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, -25.0),
                self._sample(100.0, 10.0),
                self._sample(200.0, 80.0),
            ])
            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)
            tab.pin_chart_sample(0)
            tab.pin_chart_sample(2)

            tab.btn_invert_y_axis.click()
            tab.current_plot.setXRange(40.0, 60.0, padding=0)
            tab.btn_fit_all.click()

            self.assertEqual([pin.sample_index for pin in tab.chart_pins], [0, 2])
            self.assertTrue(tab.current_plot.getPlotItem().getViewBox().yInverted())
            first_pin_html = tab.chart_pins[0].label.toHtml().replace("\xa0", " ")
            self.assertIn("Current: -25.00 mA", first_pin_html)

            menu, actions = tab._create_chart_context_menu("pin")
            tab._apply_chart_context_menu_selection(
                actions["clear_all_pins"],
                actions,
                "pin",
                1,
            )
            self.assertEqual(tab.chart_pins, [])
            self.assertFalse(tab.current_plot.isHidden())
            self.assertEqual(tab.chart_time_seconds.tolist(), [0.0, 100.0, 200.0])
            self.assertEqual(tab.chart_current_ma.tolist(), [-25.0, 10.0, 80.0])
            tab.update_hover_items(100.0, 10.0)
            self.assertTrue(tab.hover_label.isVisible())
            tab.btn_fit_all.click()
            tab.btn_invert_y_axis.click()
            self.assertFalse(tab.current_plot.getPlotItem().getViewBox().yInverted())
            self.assertTrue(tab.capture_current_chart())
            self.assertTrue(tab.pin_chart_sample(1))
            self.assertEqual([pin.sample_index for pin in tab.chart_pins], [1])

            tab._load_samples_into_workspace([
                self._sample(0.0, 1.0),
                self._sample(1.0, 2.0),
            ])
            self.assertEqual(tab.chart_pins, [])

            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)
            tab.pin_chart_sample(1)
            self.assertEqual(len(tab.chart_pins), 1)
            tab.btn_clear.click()
            self.assertEqual(tab.chart_pins, [])

    def test_chart_pin_theme_refresh_updates_existing_pin_label(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, 1.0),
                self._sample(1.0, 2.0),
            ])
            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)
            tab.pin_chart_sample(1)
            light_html = tab.chart_pins[0].label.toHtml()

            ThemeManager.fn_set_theme(ThemeType.DARK)
            tab.fn_refresh_theme()
            dark_html = tab.chart_pins[0].label.toHtml()

            self.assertNotEqual(light_html, dark_html)
            self.assertIn(ThemeManager.fn_colors().TEXT.lower(), dark_html.lower())

    def test_invert_y_axis_toggles_viewbox_without_changing_chart_data_or_hover(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, -25.30),
                self._sample(1.0, 42.0),
            ])
            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)
            view_box = tab.current_plot.getPlotItem().getViewBox()
            x_range_before = tab.current_plot.getPlotItem().viewRange()[0]
            current_x, current_y = tab.current_curve.getData()

            tab.btn_invert_y_axis.click()

            self.assertTrue(tab._y_axis_inverted)
            self.assertTrue(view_box.yInverted())
            self.assertEqual(tab.current_curve.getData()[0].tolist(), current_x.tolist())
            self.assertEqual(tab.current_curve.getData()[1].tolist(), current_y.tolist())
            self.assertEqual(tab.chart_current_ma.tolist(), [-25.30, 42.0])
            self.assertEqual(tab.current_samples[0].current_mA, -25.30)
            self.assertEqual(tab.current_plot.getPlotItem().viewRange()[0], x_range_before)

            tab.update_hover_items(0.0, -25.30)
            hover_html = tab.hover_label.toHtml().replace("\xa0", " ")
            self.assertIn("Current: -25.30 mA", hover_html)

            tab.btn_invert_y_axis.click()

            self.assertFalse(tab._y_axis_inverted)
            self.assertFalse(view_box.yInverted())
            self.assertEqual(tab.chart_current_ma.tolist(), [-25.30, 42.0])

    def test_fit_all_restores_full_chart_view_without_resetting_inverted_y(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, -25.0),
                self._sample(100.0, 10.0),
                self._sample(200.0, 80.0),
            ])
            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)
            tab.btn_invert_y_axis.click()
            tab.current_plot.setXRange(40.0, 60.0, padding=0)
            tab.current_plot.setYRange(-5.0, 5.0, padding=0)

            tab.btn_fit_all.click()

            x_range, y_range = tab.current_plot.getPlotItem().viewRange()
            self.assertLessEqual(x_range[0], 0.0)
            self.assertGreaterEqual(x_range[1], 200.0)
            self.assertLessEqual(y_range[0], -25.0)
            self.assertGreaterEqual(y_range[1], 80.0)
            self.assertTrue(tab._y_axis_inverted)
            self.assertTrue(tab.current_plot.getPlotItem().getViewBox().yInverted())
            self.assertEqual(tab.chart_time_seconds.tolist(), [0.0, 100.0, 200.0])
            self.assertEqual(tab.chart_current_ma.tolist(), [-25.0, 10.0, 80.0])

    def test_clear_and_new_dataset_reset_y_axis_orientation_and_disable_chart_actions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, 1.0),
                self._sample(1.0, 2.0),
            ])
            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)
            tab.btn_invert_y_axis.click()
            self.assertTrue(tab.current_plot.getPlotItem().getViewBox().yInverted())

            tab._load_samples_into_workspace([
                self._sample(0.0, -3.0),
                self._sample(1.0, -4.0),
            ])

            self.assertFalse(tab._y_axis_inverted)
            self.assertFalse(tab.current_plot.getPlotItem().getViewBox().yInverted())
            self.assertFalse(tab.btn_invert_y_axis.isEnabled())
            self.assertFalse(tab.btn_fit_all.isEnabled())
            self.assertFalse(tab.btn_pin.isEnabled())
            self.assertFalse(tab.btn_capture_chart.isEnabled())

            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)
            tab.btn_invert_y_axis.click()
            tab.btn_clear.click()

            self.assertFalse(tab._y_axis_inverted)
            self.assertFalse(tab.current_plot.getPlotItem().getViewBox().yInverted())
            self.assertFalse(tab.btn_invert_y_axis.isEnabled())
            self.assertFalse(tab.btn_fit_all.isEnabled())
            self.assertFalse(tab.btn_pin.isEnabled())
            self.assertFalse(tab.btn_capture_chart.isEnabled())

    def test_capture_buttons_copy_current_chart_pixmap_to_clipboard(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, 1.0),
                self._sample(1.0, -2.0),
            ])
            self.assertFalse(tab.capture_current_chart())

            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)
            tab.btn_invert_y_axis.click()

            self.assertTrue(tab.capture_current_chart())
            first_pixmap = QApplication.clipboard().pixmap()
            self.assertFalse(first_pixmap.isNull())

            QApplication.clipboard().clear()
            tab.btn_capture_chart.click()
            capture_pixmap = QApplication.clipboard().pixmap()
            self.assertFalse(capture_pixmap.isNull())

            QApplication.clipboard().clear()
            self.assertTrue(tab.current_plot.getPlotItem().getViewBox().yInverted())
            self.assertEqual(tab.chart_current_ma.tolist(), [1.0, -2.0])


    def test_analysis_range_markers_exist_and_start_hidden(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)

            self.assertIsNotNone(tab.analysis_start_line)
            self.assertIsNotNone(tab.analysis_end_line)
            self.assertIsNotNone(tab.analysis_start_label)
            self.assertIsNotNone(tab.analysis_end_label)
            self.assertFalse(tab.analysis_start_line.isVisible())
            self.assertFalse(tab.analysis_end_line.isVisible())
            self.assertFalse(tab.analysis_start_label.isVisible())
            self.assertFalse(tab.analysis_end_label.isVisible())

    def test_analysis_range_markers_follow_duration_mode_and_label_nearest_samples(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample("2026-09-11 14:10:36.025", 10.0),
                self._sample("2026-09-11 14:30:36.125", -18.42),
                self._sample("2026-09-11 15:30:36.025", 21.75),
                self._sample("2026-09-11 16:10:36.025", 5.0),
            ])
            tab.analysis_start_time_edit.setValue(1200.0)
            tab.sampling_duration_edit.setValue(60.0)

            tab.btn_run.click()
            self._wait_for_idle(tab)

            self.assertTrue(tab.analysis_start_line.isVisible())
            self.assertTrue(tab.analysis_end_line.isVisible())
            self.assertAlmostEqual(tab.analysis_start_line.value(), 1200.0, places=3)
            self.assertAlmostEqual(tab.analysis_end_line.value(), 4800.0, places=3)
            self.assertEqual(tab.chart_time_seconds.tolist(), [0.0, 1200.1, 4800.0, 7200.0])
            start_html = tab.analysis_start_label.toHtml().replace("\xa0", " ")
            end_html = tab.analysis_end_label.toHtml().replace("\xa0", " ")
            self.assertIn("START", start_html)
            self.assertIn("1200.00 s", start_html)
            self.assertIn("14:30:36.125", start_html)
            self.assertIn("-18.42 mA", start_html)
            self.assertIn("END", end_html)
            self.assertIn("4800.00 s", end_html)
            self.assertIn("15:30:36.025", end_html)
            self.assertIn("21.75 mA", end_html)

            tab.sampling_duration_edit.setValue(90.0)

            self.assertAlmostEqual(tab.analysis_end_line.value(), 6600.0, places=3)
            self.assertTrue(tab.analysis_start_label.isVisible())
            self.assertTrue(tab.analysis_end_label.isVisible())
            self.assertEqual(tab.analysis_progress_bar.text(), "NOT RUN")

    def test_analysis_range_markers_follow_manual_end_and_out_of_range_duration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, 10.0),
                self._sample(1800.0, -20.0),
                self._sample(3600.0, 30.0),
            ])
            tab.sampling_duration_checkbox.setChecked(False)
            tab.analysis_start_time_edit.setValue(1200.0)
            tab.analysis_end_time_edit.setValue(3500.0)
            tab.btn_run.click()
            self._wait_for_idle(tab)

            self.assertAlmostEqual(tab.analysis_start_line.value(), 1200.0, places=3)
            self.assertAlmostEqual(tab.analysis_end_line.value(), 3500.0, places=3)

            tab.sampling_duration_checkbox.setChecked(True)
            tab.analysis_start_time_edit.setValue(1800.0)
            tab.sampling_duration_edit.setValue(60.0)

            self.assertAlmostEqual(tab.analysis_start_line.value(), 1800.0, places=3)
            self.assertAlmostEqual(tab.analysis_end_line.value(), 5400.0, places=3)
            end_html = tab.analysis_end_label.toHtml().replace("\xa0", " ")
            self.assertIn("END", end_html)
            self.assertIn("5400.00 s", end_html)
            self.assertIn("Out of data range", end_html)
            self.assertNotIn("30.00 mA", end_html)

    def test_analysis_range_markers_are_independent_from_pins_cursors_and_clear(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)
            tab._load_samples_into_workspace([
                self._sample(0.0, -25.0),
                self._sample(1200.0, -18.42),
                self._sample(4800.0, 21.75),
                self._sample(7200.0, 8.0),
            ])
            tab.analysis_start_time_edit.setValue(1200.0)
            tab.sampling_duration_edit.setValue(60.0)
            tab.btn_run.click()
            self._wait_for_idle(tab)
            start_line = tab.analysis_start_line
            end_line = tab.analysis_end_line
            start_label = tab.analysis_start_label
            end_label = tab.analysis_end_label
            tab.pin_chart_sample(1)
            tab.set_cursor_a(0)
            tab.set_cursor_b(2)

            tab.analysis_start_time_edit.setValue(1800.0)
            tab.sampling_duration_edit.setValue(30.0)

            self.assertEqual([pin.sample_index for pin in tab.chart_pins], [1])
            self.assertEqual(tab.cursor_a_index, 0)
            self.assertEqual(tab.cursor_b_index, 2)
            self.assertAlmostEqual(tab.analysis_start_line.value(), 1800.0, places=3)
            self.assertAlmostEqual(tab.analysis_end_line.value(), 3600.0, places=3)

            tab.clear_chart_pins()

            self.assertEqual(tab.chart_pins, [])
            self.assertTrue(tab.analysis_start_line.isVisible())
            self.assertTrue(tab.analysis_end_line.isVisible())

            tab.btn_clear.click()

            self.assertIs(tab.analysis_start_line, start_line)
            self.assertIs(tab.analysis_end_line, end_line)
            self.assertIs(tab.analysis_start_label, start_label)
            self.assertIs(tab.analysis_end_label, end_label)
            self.assertFalse(tab.analysis_start_line.isVisible())
            self.assertFalse(tab.analysis_end_line.isVisible())
            self.assertFalse(tab.analysis_start_label.isVisible())
            self.assertFalse(tab.analysis_end_label.isVisible())

    def test_run_again_refreshes_chart_without_duplicate_items_and_updates_thresholds(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, database_dir = self._create_tab(tmpdir)
            source_file = Path(tmpdir) / "sample.csv"
            source_file.write_text("Trigger time,No1 Average Ch1\n0,0.001\n", encoding="utf-8")
            database_file = database_path_for_source(source_file, database_dir)
            import_dataset(
                "sample",
                source_file,
                [("0", 0.001, 1.0), ("1.5", 0.002, 2.0)],
                database_file,
            )
            tab._refresh_dataset_combo(selected_db_path=database_file)
            tab.import_current_file()
            self._wait_for_idle(tab)

            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)
            current_curve = tab.current_curve
            upper_line = tab.upper_sleep_limit_line
            lower_line = tab.lower_sleep_limit_line
            hover_marker = tab.hover_marker
            tab.current_limit_edit.setValue(45.0)
            tab.wake_limit_edit.setValue(350.0)
            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)

            self.assertIs(tab.current_curve, current_curve)
            self.assertIs(tab.upper_sleep_limit_line, upper_line)
            self.assertIs(tab.lower_sleep_limit_line, lower_line)
            self.assertIs(tab.hover_marker, hover_marker)
            self.assertEqual(len(self._legend_labels(tab)), 3)
            self.assertEqual(tab.upper_sleep_limit_line.value(), 45.0)
            self.assertEqual(tab.lower_sleep_limit_line.value(), -45.0)
            current_x, current_y = tab.current_curve.getData()
            self.assertEqual(current_x.tolist(), [0.0, 1.5])
            self.assertEqual(current_y.tolist(), [1.0, 2.0])

    def test_clear_resets_workspace_without_deleting_database_or_combo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, database_dir = self._create_tab(tmpdir)
            source_file = Path(tmpdir) / "sample.csv"
            source_file.write_text("Trigger time,No1 Average Ch1\n0,0.001\n", encoding="utf-8")
            database_file = database_path_for_source(source_file, database_dir)
            import_dataset(
                "sample",
                source_file,
                [("0", 0.001, 1.0), ("1", 0.002, 2.0)],
                database_file,
            )
            tab._refresh_dataset_combo(selected_db_path=database_file)
            tab.import_current_file()
            self._wait_for_idle(tab)
            self._use_manual_end_mode(tab)
            tab.btn_run.click()
            self._wait_for_idle(tab)

            tab.btn_clear.click()

            self.assertTrue(database_file.exists())
            self.assertEqual(tab.dataset_combo.count(), 1)
            self.assertEqual(tab.current_samples, [])
            self.assertEqual(tab.review_table.model().rowCount(), 0)
            self.assertIsNone(tab.current_curve.getData()[0])
            self.assertEqual(tab.analysis_progress_bar.text(), "NOT RUN")
            self.assertFalse(tab.btn_run.isEnabled())
            self.assertFalse(tab.btn_copy_data_review.isEnabled())
            self.assertFalse(tab.btn_export.isEnabled())
            self.assertFalse(tab.btn_pin.isEnabled())
            self.assertFalse(tab.btn_capture_chart.isEnabled())
            self.assertFalse(tab.btn_invert_y_axis.isEnabled())
            self.assertFalse(tab.btn_fit_all.isEnabled())
            self.assertFalse(tab.btn_copy_summary.isEnabled())
            self.assertFalse(tab.btn_clear.isEnabled())
            self.assertFalse(hasattr(tab, "btn_copy_chart"))
            self.assertTrue(tab.current_plot.isHidden())
            self.assertFalse(tab.chart_placeholder.isHidden())
            self.assertEqual(tab.wake_up_regions, [])
            self.assertEqual(tab.chart_time_seconds.tolist(), [])
            self.assertEqual(tab.chart_current_ma.tolist(), [])
            self.assertFalse(tab.hover_marker.isVisible())
            self.assertFalse(tab.hover_label.isVisible())
            self.assertIsNotNone(tab.upper_sleep_limit_line)
            self.assertIsNotNone(tab.lower_sleep_limit_line)

    def test_import_failure_keeps_source_combo_selection_and_import_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, database_dir = self._create_tab(tmpdir)
            existing_source = Path(tmpdir) / "VF6_Test.csv"
            existing_source.write_text("Trigger time,No1 Average Ch1\n0,0.001\n", encoding="utf-8")
            existing_database = database_path_for_source(existing_source, database_dir)
            import_dataset(
                "VF6_Test",
                existing_source,
                [("0", 0.001, 1.0)],
                existing_database,
            )
            tab._refresh_dataset_combo()
            selected_dataset = tab.dataset_combo.currentData()

            bad_source = Path(tmpdir) / "bad.txt"
            bad_source.write_text("not,current,data\n", encoding="utf-8")
            tab.set_source_file(bad_source)

            with patch("gui.tabs.q_current_tab.QMessageBox.warning") as warning_box:
                tab.import_current_file()
                self._wait_for_idle(tab)

            self.assertEqual(tab.analysis_progress_bar.text(), "IMPORT FAILED")
            self.assertEqual(tab.source_file_edit.text(), str(bad_source.resolve()))
            self.assertEqual(tab.source_file_edit.toolTip(), str(bad_source.resolve()))
            self.assertEqual(tab.dataset_combo.count(), 1)
            self.assertEqual(tab.dataset_combo.currentData(), selected_dataset)
            self.assertTrue(tab.import_button.isEnabled())
            warning_box.assert_called_once()

    def test_duplicate_import_no_cancel_keeps_existing_dataset_unchanged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, database_dir = self._create_tab(tmpdir)
            source_file = Path(tmpdir) / "sample.csv"
            source_file.write_text("Trigger time,No1 Average Ch1\n0,0.001\n", encoding="utf-8")
            database_file = database_path_for_source(source_file, database_dir)
            first = import_dataset("sample", source_file, [("0", 0.001, 1.0)], database_file)
            tab._refresh_dataset_combo()
            source_file.write_text("Trigger time,No1 Average Ch1\n1,0.009\n", encoding="utf-8")
            tab.set_source_file(source_file)

            with patch(
                "gui.tabs.q_current_tab.QMessageBox.question",
                return_value=QMessageBox.No,
            ), patch("gui.tabs.q_current_tab.QMessageBox.information") as info_box:
                tab.import_current_file()
                self._wait_for_idle(tab)

            tab._refresh_dataset_combo()
            self.assertEqual(tab.dataset_combo.count(), 1)
            self.assertEqual(tab.dataset_combo.itemData(0), str(database_file.resolve()))
            self.assertEqual(tab.analysis_progress_bar.text(), "NOT RUN")
            info_box.assert_not_called()

    def test_duplicate_import_yes_replaces_dataset_and_selects_it(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, database_dir = self._create_tab(tmpdir)
            source_file = Path(tmpdir) / "sample.csv"
            source_file.write_text("Trigger time,No1 Average Ch1\n0,0.001\n", encoding="utf-8")
            database_file = database_path_for_source(source_file, database_dir)
            first = import_dataset("sample", source_file, [("0", 0.001, 1.0)], database_file)
            source_file.write_text("Trigger time,No1 Average Ch2\n1,0.009\n2,0.010\n", encoding="utf-8")
            tab.set_source_file(source_file)

            with patch(
                "gui.tabs.q_current_tab.QMessageBox.question",
                return_value=QMessageBox.Yes,
            ), patch("gui.tabs.q_current_tab.QMessageBox.information"):
                tab.import_current_file()
                self._wait_for_idle(tab)

            self.assertEqual(tab.dataset_combo.count(), 1)
            self.assertEqual(tab.dataset_combo.currentData(), str(database_file.resolve()))
            self.assertEqual(tab.current_import.dataset.id, first.dataset.id)
            self.assertEqual(
                [(sample.time, sample.current_mA) for sample in tab.current_samples],
                [("1", 9.0), ("2", 10.0)],
            )

    def test_q_current_tab_keeps_non_settings_layout_regions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)

            self.assertIsInstance(tab.main_splitter, QSplitter)
            self.assertEqual(tab.main_splitter.orientation(), Qt.Horizontal)
            self.assertFalse(hasattr(tab, "information_group"))
            self.assertIs(tab.main_splitter.widget(0), tab.review_group)
            self.assertIs(tab.main_splitter.widget(1), tab.chart_group)
            self.assertIs(tab.main_splitter.widget(2), tab.right_panel)
            self.assertEqual(tab.chart_placeholder.text(), PLACEHOLDER_VALUE)
            self.assertEqual(tab.review_table.model().rowCount(), 0)
            self.assertEqual(tab.review_table.model().columnCount(), 3)
            self.assertEqual(tab.review_table.model().headerData(0, Qt.Horizontal), "No.")
            self.assertEqual(tab.review_table.model().headerData(1, Qt.Horizontal), "Time")
            self.assertEqual(tab.review_table.model().headerData(2, Qt.Horizontal), "Current (mA)")
            self.assertIs(tab.summary_group, tab.summary_widget)
            self.assertIn("result_status", tab.summary_widget.summary_values)
            self.assertIn("average_sleep_current_ma", tab.summary_widget.summary_values)
            self.assertIn("wake_up_event_count", tab.summary_widget.summary_values)
            self.assertIn("longest_continuous_sleep_s", tab.summary_widget.summary_values)
            self.assertIn("total_samples", tab.summary_widget.summary_values)
            self.assertIn("source_start_time", tab.summary_widget.summary_values)
            self.assertIn("source_end_time", tab.summary_widget.summary_values)

    def test_q_current_tab_uses_existing_controls_and_theme_refresh(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tab, _database_dir = self._create_tab(tmpdir)

            buttons = [
                tab.btn_run,
                tab.btn_export,
                tab.btn_copy_data_review,
                tab.btn_copy_summary,
                tab.btn_clear,
            ]
            self.assertTrue(all(isinstance(button, PrimaryButton) for button in buttons))
            self.assertEqual([button.text() for button in buttons], [
                "RUN",
                "EXPORT",
                "COPY Data Review",
                "COPY Summary",
                "CLEAR",
            ])
            chart_buttons = [
                tab.btn_pin,
                tab.btn_invert_y_axis,
                tab.btn_fit_all,
                tab.btn_capture_chart,
            ]
            self.assertTrue(all(isinstance(button, QuickAccessButton) for button in chart_buttons))
            self.assertEqual([button.text() for button in chart_buttons], [
                "Pin",
                "Invert Y Axis",
                "Fit All",
                "Capture",
            ])
            self.assertLess(
                tab.chart_toolbar_layout.indexOf(tab.btn_pin),
                tab.chart_toolbar_layout.indexOf(tab.btn_invert_y_axis),
            )
            self.assertLess(
                tab.chart_toolbar_layout.indexOf(tab.btn_invert_y_axis),
                tab.chart_toolbar_layout.indexOf(tab.btn_fit_all),
            )
            self.assertLess(
                tab.chart_toolbar_layout.indexOf(tab.btn_fit_all),
                tab.chart_toolbar_layout.indexOf(tab.btn_capture_chart),
            )
            self.assertEqual(tab.legend_layout.indexOf(tab.btn_pin), -1)
            self.assertEqual(self._legend_labels(tab), [
                "Current",
                "Sleep threshold",
                "Wake-up",
            ])
            self.assertEqual(tab.cursor_a_value_label.text(), "A: — | —")
            self.assertEqual(tab.cursor_b_value_label.text(), "B: — | —")
            self.assertEqual(tab.cursor_delta_time_label.text(), "Δt: —")
            self.assertEqual(tab.cursor_delta_current_label.text(), "ΔI: —")
            self.assertTrue(tab.dataset_combo.view().verticalScrollBar().styleSheet())
            self.assertTrue(tab.chart_scrollbar.styleSheet())

            light_style = tab.chart_placeholder.styleSheet()
            light_quick_access_style = tab.btn_fit_all.styleSheet()
            ThemeManager.fn_set_theme(ThemeType.DARK)
            tab.fn_refresh_theme()
            dark_style = tab.chart_placeholder.styleSheet()
            dark_quick_access_style = tab.btn_fit_all.styleSheet()

            self.assertNotEqual(light_style, dark_style)
            self.assertNotEqual(light_quick_access_style, dark_quick_access_style)
            self.assertIn(ThemeManager.fn_colors().TEXT, dark_style)
            self.assertTrue(tab.current_limit_edit.styleSheet())
            self.assertEqual(
                tab.current_limit_edit.styleSheet(),
                tab.wake_limit_edit.styleSheet(),
            )
            self.assertEqual(
                tab.current_limit_edit.styleSheet(),
                tab.wake_duration_edit.styleSheet(),
            )
            self.assertEqual(
                tab.current_limit_edit.styleSheet(),
                tab.sampling_duration_edit.styleSheet(),
            )
            self.assertEqual(
                tab.current_limit_edit.styleSheet(),
                tab.analysis_start_time_edit.styleSheet(),
            )
            self.assertEqual(
                tab.current_limit_edit.styleSheet(),
                tab.analysis_end_time_edit.styleSheet(),
            )


if __name__ == "__main__":
    unittest.main()
