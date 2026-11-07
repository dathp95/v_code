
from PySide6.QtCore import Qt, Signal

from PySide6.QtWidgets import (
    QApplication,
    QHeaderView,
    QMenu,
    QTableWidget,
    QTableWidgetItem,
)
from PySide6.QtGui import QColor

from gui.themes.theme_manager import ThemeManager
from gui.themes.styles.controls.menu_style import fn_apply_menu_style
from gui.widgets.controls.primary_table import PrimaryTable
from gui.utils.payload_format import format_payload_input
from core.transaction_formatter import TRANSACTION_COLUMNS


class ResultTable(PrimaryTable):
    create_quick_filter_requested = Signal(dict)
    transaction_selected = Signal(dict)

    TRANSACTION_FIELDS = list(TRANSACTION_COLUMNS)

    FIXED_COLUMN_WIDTHS = {
        "ECU": 64,
        "Time": 80,
        "Request": 110,
        "RT (ms)": 64,
        "Status": 84,
    }
    STRETCH_FIELDS = ("Activity", "Response")
    MIN_SECTION_WIDTH = 60

    def __init__(self):
        super().__init__()

        self._setup_ui()

        self._fn_setup_column_width()

        self.fn_refresh_theme()

    def _setup_ui(self):
        self.setColumnCount(
            len(self.TRANSACTION_FIELDS)
        )
        self.setHorizontalHeaderLabels(
            self.TRANSACTION_FIELDS
        )
        self.setSortingEnabled(False)

        header = self.horizontalHeader()
        header.setSortIndicatorShown(False)
        header.setSectionsClickable(False)

        header.setSectionResizeMode(
            QHeaderView.Interactive
        )

        header.setStretchLastSection(False)

        # Short columns keep a fixed width (still resizable by hand); the two long text columns share what
        # is left, so ECU ... Status all fit a ~700 px table (1366 px screen) without a horizontal scroll bar.
        header.setMinimumSectionSize(self.MIN_SECTION_WIDTH)

        for field in self.STRETCH_FIELDS:
            header.setSectionResizeMode(
                self._fn_column_index(field),
                QHeaderView.Stretch,
            )

        self.setContextMenuPolicy(
            Qt.CustomContextMenu
        )
        self.customContextMenuRequested.connect(
            self._fn_show_context_menu
        )

    def clear_data(self):
        self.setRowCount(0)

    def fn_reset_view(self) -> None:
        self._refresh_row_colors()

        for row in range(self.rowCount()):
            self.setRowHidden(
                row,
                False,
            )

        self.clearSelection()
        self.setCurrentCell(-1, -1)
        self._fn_reset_scroll_position()
    


    def set_data(self, data):

        self.setSortingEnabled(False)

        self.clear_data()     

        self.setRowCount(len(data))

        for row, item in enumerate(data):

            for column, field in enumerate(self.TRANSACTION_FIELDS):
                value = item.get(field, "")
                self.setItem(row, column, self.fn_create_item("" if value is None else value, row))

   
    
    def _fn_setup_column_width(self):
        """
        Set the widths of the fixed columns; Activity and Response stretch (see _setup_ui).
        """

        for field, width in self.FIXED_COLUMN_WIDTHS.items():
            self.setColumnWidth(
                self._fn_column_index(field),
                width
            )

    def fn_search(
            self,
            keyword: str = "",
        ):
        """
        Filter table rows by keyword.

        Search is:
        - Case-insensitive.
        - Ignores leading/trailing spaces.
        - Normalizes multiple spaces into one.
        """

        # ------------------------------------------
        # Normalize user input
        # ------------------------------------------

        # Global search replaces Quick Filter highlighting.
        self._refresh_row_colors()

        keyword = format_payload_input(keyword.strip())
        keyword = " ".join(keyword.split()).lower()

        # Empty keyword -> show all rows
        if not keyword:

            for row in range(self.rowCount()):

                self.setRowHidden(
                    row,
                    False
                )
            self._fn_reset_scroll_position()

            return

        # ------------------------------------------
        # Search every cell
        # ------------------------------------------

        for row in range(self.rowCount()):

            matched = False

            for column in range(self.columnCount()):

                item = self.item(row, column)

                if item is None:
                    continue

                cell_text = " ".join(
                    item.text().strip().split()
                ).lower()

                if keyword in cell_text:

                    matched = True
                    break

            self.setRowHidden(
                row,
                not matched
            )
       
        # Reset table view to the beginning after search
        self._fn_reset_scroll_position()

    def _fn_reset_scroll_position(self):
        self.verticalScrollBar().setValue(
            self.verticalScrollBar().minimum()
        )

        self.horizontalScrollBar().setValue(
            self.horizontalScrollBar().minimum()
        )
  
    def fn_row_data(
            self,
            row: int,
        ) -> dict:
        """Return displayed table values for a row."""

        if row < 0 or row >= self.rowCount():
            return {}

        data = {}

        for column in range(self.columnCount()):
            header_item = self.horizontalHeaderItem(column)

            if header_item is None:
                continue

            item = self.item(row, column)
            data[header_item.text()] = "" if item is None else item.text()

        return data

    def fn_visible_rows(self) -> list[dict]:
        """Return all non-hidden rows in displayed order, ignoring selection."""
        return [self.fn_row_data(row) for row in range(self.rowCount())
                if not self.isRowHidden(row)]

    def _fn_show_context_menu(
            self,
            pos,
        ):
        item = self.itemAt(pos)

        if item is None:
            return

        row = item.row()
        row_data = self.fn_row_data(row)

        if not row_data:
            return

        self.selectRow(row)
        self.setCurrentCell(row, item.column())
        self.transaction_selected.emit(row_data)

        menu = QMenu(self)
        fn_apply_menu_style(menu)
        action_copy_request = menu.addAction("Copy Request")
        action_copy_response = menu.addAction("Copy Response")
        action_copy_transaction = menu.addAction("Copy Transaction")
        menu.addSeparator()
        action_create_quick_filter = menu.addAction("Create Quick Filter")

        action = self._fn_exec_context_menu(menu, pos)

        if action == action_copy_request:
            self._fn_copy_request(row_data)
        elif action == action_copy_response:
            self._fn_copy_response(row_data)
        elif action == action_copy_transaction:
            self._fn_copy_transaction(row_data)
        elif action == action_create_quick_filter:
            self.create_quick_filter_requested.emit(row_data)

    def _fn_exec_context_menu(
            self,
            menu: QMenu,
            pos,
        ):
        return menu.exec(
            self.viewport().mapToGlobal(pos)
        )

    def _fn_copy_request(
            self,
            row_data: dict,
        ):
        self._fn_copy_text(
            self._fn_text_value(row_data.get("Request", ""))
        )

    def _fn_copy_response(
            self,
            row_data: dict,
        ):
        self._fn_copy_text(
            self._fn_text_value(row_data.get("Response", ""))
        )

    def _fn_copy_transaction(
            self,
            row_data: dict,
        ):
        self._fn_copy_text(
            self._fn_transaction_text(row_data)
        )

    def _fn_transaction_text(
            self,
            row_data: dict,
        ) -> str:
        return "\n".join(
            f"{field}: {self._fn_text_value(row_data.get(field, ''))}"
            for field in self.TRANSACTION_FIELDS
        )

    @staticmethod
    def _fn_copy_text(text) -> None:
        QApplication.clipboard().setText(
            ResultTable._fn_text_value(text)
        )

    @staticmethod
    def _fn_text_value(value) -> str:
        if value is None:
            return ""

        return str(value)

  
    def _fn_column_index(
            self,
            header: str,
        ) -> int:
        """
        Return the column index by header text.

        Raises
        ------
        ValueError
            If the header does not exist.
        """

        for column in range(self.columnCount()):

            item = self.horizontalHeaderItem(column)

            if item is None:

                continue

            if item.text().strip().lower() == header.lower():

                return column

        raise ValueError(

            f"Column '{header}' not found."

        )
    
    def fn_apply_quick_filter(
            self,
            filter_data: dict,
        ):
        """
        Apply one quick filter.

        Empty filter fields are ignored.
        All non-empty fields must match (AND logic).
        """

        filters = filter_data.get(
            "filters",
            {}
        )

        ecu = filters.get("ecu", "").strip().upper()

        request = format_payload_input(
            filters.get("request", "").strip()
        )
        response = format_payload_input(
            filters.get("response", "").strip()
        )

        ecu_col = self._fn_column_index("ECU")

        request_col = self._fn_column_index("Request")
        response_col = self._fn_column_index("Response")

        colors = ThemeManager.fn_colors()

        self._refresh_row_colors()

        for row in range(self.rowCount()):

            matched = True

            # --------------------------
            # ECU
            # --------------------------

            if ecu:

                item = self.item(
                    row,
                    ecu_col
                )

                cell = ""

                if item is not None:

                    cell = item.text().strip().upper()

                matched &= ecu in cell

            # --------------------------
            # Request
            # --------------------------

            if request:

                item = self.item(
                    row,
                    request_col
                )

                cell = ""

                if item is not None:

                    cell = " ".join(
                        item.text().strip().split()
                    ).upper()

                matched &= cell == request

            if response:
                item = self.item(row, response_col)
                cell = "" if item is None else " ".join(
                    item.text().strip().split()
                ).upper()
                if not request:
                    matched &= cell == response

                if request:
                    if cell == response:
                        background = colors.QUICK_FILTER_MATCH
                    elif not cell:
                        background = colors.QUICK_FILTER_NO_RESPONSE
                    else:
                        background = colors.QUICK_FILTER_NOT_MATCH
                else:
                    background = None

                for column in range(self.columnCount()):
                    cell_item = self.item(row, column)
                    if cell_item is not None:
                        if background is None:
                            cell_item.setBackground(QColor(
                                colors.TABLE_ROW if row % 2 == 0 else colors.TABLE_ROW_ALT
                            ))
                        else:
                            cell_item.setBackground(QColor(background))

            self.setRowHidden(

                row,

                not matched

            )
    
        self.clearSelection()
        self.setCurrentCell(-1, -1)
    
    def fn_refresh_theme(self):

        super().fn_refresh_theme()
