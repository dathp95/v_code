import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QHeaderView, QMenu

from gui.themes.styles.controls.menu_style import fn_apply_menu_style
from gui.themes.theme import ThemeType
from gui.themes.theme_manager import ThemeManager
from gui.widgets.log_analyzer.result_table import ResultTable


class ResultTableQuickFilterTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def _table_with_rows(self):
        table = ResultTable()
        self.addCleanup(table.deleteLater)
        rows = [
            {
                "ECU": "MHU",
                "Time": "42.500",
                "Activity": "Read DID",
                "Request": "22 F1 90",
                "Response": "62 F1 90 56 49 4E",
                "RT (ms)": "12.50",
                "Status": "Positive",
            },
            {
                "ECU": "VCU",
                "Time": "125.320",
                "Activity": "Read VIN",
                "Request": "22 F1 91",
                "Response": "7F 22 31",
                "RT (ms)": "18.50",
                "Status": "Negative",
            },
        ]
        table.set_data(rows)
        table.resize(900, 300)
        table.show()
        self.application.processEvents()
        return table, rows

    def _row_position(self, table, row):
        item = table.item(row, table._fn_column_index("ECU"))
        return table.visualItemRect(item).center()

    def test_pending_status_search_and_response_filter_do_not_use_nrc78_as_final(self):
        from core.build_transactions import build_transactions_v4
        from core.transaction_formatter import fn_build_transaction_rows
        from tests.core.test_transaction_matching import msg

        transactions = build_transactions_v4([msg(1, 0x682, "31 01 02 06")], [],
            [msg(1.1, 0x602, "7F 31 78")], {"A": {"request": 0x682, "response": 0x602}}, 1)
        table = ResultTable()
        self.addCleanup(table.deleteLater)
        table.set_data(fn_build_transaction_rows(transactions))
        self.assertEqual(table.fn_row_data(0)["Status"], "PENDING_TIMEOUT")
        self.assertEqual(table.fn_row_data(0)["Response"], "")
        table.fn_search("PENDING_TIMEOUT")
        self.assertFalse(table.isRowHidden(0))
        table.fn_apply_quick_filter({"filters": {"response": "7F 31 78"}})
        self.assertTrue(table.isRowHidden(0))
        table.fn_apply_quick_filter({"filters": {"request": "31 01 02 06"}})
        self.assertFalse(table.isRowHidden(0))

    def test_activity_and_response_stretch_while_status_keeps_its_width(self):
        table = ResultTable()
        self.addCleanup(table.deleteLater)

        header = table.horizontalHeader()
        for name in ("Activity", "Response"):
            self.assertEqual(header.sectionResizeMode(table._fn_column_index(name)), QHeaderView.Stretch, name)
        for name in ("ECU", "Time", "Request", "RT (ms)", "Status"):
            self.assertEqual(header.sectionResizeMode(table._fn_column_index(name)), QHeaderView.Interactive, name)

    def test_header_sorting_is_disabled_without_changing_resize_mode(self):
        table = ResultTable()
        self.addCleanup(table.deleteLater)

        table.set_data([
            {
                "ECU": "ZCU",
                "Time": "2.000",
                "Activity": "Second",
                "Request": "22 F1 91",
                "Response": "62 F1 91",
                "RT (ms)": "20",
                "Status": "OK",
            },
            {
                "ECU": "ACU",
                "Time": "1.000",
                "Activity": "First",
                "Request": "22 F1 90",
                "Response": "62 F1 90",
                "RT (ms)": "10",
                "Status": "OK",
            },
        ])

        header = table.horizontalHeader()
        ecu_column = table._fn_column_index("ECU")
        before = [table.item(row, ecu_column).text() for row in range(table.rowCount())]

        header.sectionClicked.emit(ecu_column)
        after = [table.item(row, ecu_column).text() for row in range(table.rowCount())]

        self.assertFalse(table.isSortingEnabled())
        self.assertFalse(header.isSortIndicatorShown())
        self.assertEqual(after, before)
        self.assertEqual(
            header.sectionResizeMode(ecu_column),
            QHeaderView.Interactive,
        )

    def test_row_data_returns_displayed_selected_row_values(self):
        table = ResultTable()
        self.addCleanup(table.deleteLater)

        row_data = {
            "ECU": "VCU",
            "Time": "125.320",
            "Activity": "Read VIN",
            "Request": "22 F1 90",
            "Response": "62 F1 90",
            "RT (ms)": "15.20",
            "Status": "Positive",
        }
        table.set_data([row_data])

        self.assertEqual(table.fn_row_data(0), row_data)
        self.assertEqual(table.fn_row_data(-1), {})

    def test_context_menu_does_not_open_for_empty_table_space(self):
        table = ResultTable()
        self.addCleanup(table.deleteLater)

        with patch.object(table, "_fn_exec_context_menu") as exec_menu:
            table._fn_show_context_menu(QPoint(5, 5))

        exec_menu.assert_not_called()

    def test_context_menu_selects_right_clicked_row_and_emits_transaction(self):
        table, rows = self._table_with_rows()
        selected_rows = []
        table.transaction_selected.connect(selected_rows.append)

        with patch.object(table, "_fn_exec_context_menu", return_value=None) as exec_menu:
            table._fn_show_context_menu(self._row_position(table, 1))

        exec_menu.assert_called_once()
        self.assertEqual(table.currentRow(), 1)
        self.assertEqual(selected_rows, [rows[1]])

    def test_context_menu_uses_themed_menu_style_without_changing_actions(self):
        table, _ = self._table_with_rows()
        captured = []

        def capture_menu(menu, pos):
            captured.append(menu)
            return None

        with patch.object(table, "_fn_exec_context_menu", side_effect=capture_menu):
            table._fn_show_context_menu(self._row_position(table, 0))

        menu = captured[0]
        self.assertIn("QMenu::item:selected", menu.styleSheet())
        self.assertIn("QMenu::separator", menu.styleSheet())
        self.assertEqual(
            [action.text() for action in menu.actions()],
            [
                "Copy Request",
                "Copy Response",
                "Copy Transaction",
                "",
                "Create Quick Filter",
            ],
        )
        self.assertTrue(menu.actions()[3].isSeparator())

    def test_menu_style_uses_current_theme_colors(self):
        menu = QMenu()
        self.addCleanup(menu.deleteLater)
        self.addCleanup(ThemeManager.fn_set_theme, ThemeType.LIGHT)

        ThemeManager.fn_set_theme(ThemeType.DARK)
        colors = ThemeManager.fn_colors()

        fn_apply_menu_style(menu)

        style = menu.styleSheet()
        self.assertIn(f"background-color: {colors.WINDOW};", style)
        self.assertIn(f"color: {colors.TEXT};", style)
        self.assertIn(f"background-color: {colors.PRIMARY};", style)
        self.assertIn(f"color: {colors.WINDOW};", style)
        self.assertIn(f"color: {colors.BUTTON_DISABLED_TEXT};", style)

    def test_copy_request_response_and_transaction_use_displayed_values(self):
        table, rows = self._table_with_rows()
        clipboard = QApplication.clipboard()

        table._fn_copy_request(rows[0])
        self.assertEqual(clipboard.text(), "22 F1 90")

        table._fn_copy_response(rows[0])
        self.assertEqual(clipboard.text(), "62 F1 90 56 49 4E")

        table._fn_copy_transaction(rows[0])
        self.assertEqual(
            clipboard.text(),
            "ECU: MHU\n"
            "Time: 42.500\n"
            "Activity: Read DID\n"
            "Request: 22 F1 90\n"
            "Response: 62 F1 90 56 49 4E\n"
            "RT (ms): 12.50\n"
            "Status: Positive",
        )

    def test_copy_handles_missing_values_safely(self):
        table = ResultTable()
        self.addCleanup(table.deleteLater)
        clipboard = QApplication.clipboard()

        table._fn_copy_request({"Request": None})
        self.assertEqual(clipboard.text(), "")

        table._fn_copy_response({})
        self.assertEqual(clipboard.text(), "")

    def test_create_quick_filter_action_emits_row_data(self):
        table, rows = self._table_with_rows()
        emitted = []
        table.create_quick_filter_requested.connect(emitted.append)

        def choose_create_filter(menu, pos):
            return menu.actions()[4]

        with patch.object(table, "_fn_exec_context_menu", side_effect=choose_create_filter):
            table._fn_show_context_menu(self._row_position(table, 0))

        self.assertEqual(emitted, [rows[0]])

    def test_apply_quick_filter_clears_previous_row_selection(self):
        table = ResultTable()
        self.addCleanup(table.deleteLater)

        table.set_data([
            {
                "ECU": "ECU1",
                "Time": "0.001",
                "Activity": "Diag",
                "Request": "22 F1 90",
                "Response": "62 F1 90",
                "RT (ms)": "10",
                "Status": "OK",
            },
            {
                "ECU": "ECU2",
                "Time": "0.002",
                "Activity": "Diag",
                "Request": "22 F1 91",
                "Response": "62 F1 91",
                "RT (ms)": "11",
                "Status": "OK",
            },
        ])

        filter_2 = {
            "filters": {
                "ecu": "ECU2",
                "request": "",
                "response": "",
            }
        }
        filter_1 = {
            "filters": {
                "ecu": "ECU1",
                "request": "",
                "response": "",
            }
        }

        table.fn_apply_quick_filter(filter_2)
        table.selectRow(1)
        self.assertEqual(table.currentRow(), 1)
        self.assertTrue(table.selectionModel().selectedRows())

        table.fn_apply_quick_filter(filter_1)
        self.assertEqual(table.currentRow(), -1)
        self.assertFalse(table.selectionModel().selectedRows())

        table.fn_apply_quick_filter(filter_2)
        self.assertEqual(table.currentRow(), -1)
        self.assertFalse(table.selectionModel().selectedRows())

    def test_reset_view_restores_rows_colors_selection_and_scroll(self):
        table = ResultTable()
        self.addCleanup(table.deleteLater)
        rows = []
        for index in range(30):
            rows.append({
                "ECU": "ECU1" if index == 0 else "ECU2",
                "Time": f"{index}.000",
                "Activity": "Diag",
                "Request": "22 F1 90" if index == 0 else "22 F1 91",
                "Response": "62 F1 90" if index == 0 else "7F 22 31",
                "RT (ms)": "10",
                "Status": "OK",
            })
        table.set_data(rows)
        table.resize(500, 180)
        table.show()
        self.application.processEvents()

        table.fn_apply_quick_filter({
            "filters": {
                "ecu": "ECU1",
                "request": "22 F1 90",
                "response": "62 F1 90",
            }
        })
        table.selectRow(0)
        table.setCurrentCell(0, 0)
        table.verticalScrollBar().setValue(table.verticalScrollBar().maximum())
        table.horizontalScrollBar().setValue(table.horizontalScrollBar().maximum())

        self.assertTrue(table.isRowHidden(1))

        table.fn_reset_view()

        self.assertTrue(all(
            not table.isRowHidden(row)
            for row in range(table.rowCount())
        ))
        self.assertEqual(table.currentRow(), -1)
        self.assertFalse(table.selectionModel().selectedRows())
        self.assertEqual(
            table.verticalScrollBar().value(),
            table.verticalScrollBar().minimum(),
        )
        self.assertEqual(
            table.horizontalScrollBar().value(),
            table.horizontalScrollBar().minimum(),
        )

        colors = ThemeManager.fn_colors()
        self.assertEqual(
            table.item(0, 0).background().color().name().lower(),
            colors.TABLE_ROW.lower(),
        )
        self.assertEqual(
            table.item(1, 0).background().color().name().lower(),
            colors.TABLE_ROW_ALT.lower(),
        )


if __name__ == "__main__":
    unittest.main()
