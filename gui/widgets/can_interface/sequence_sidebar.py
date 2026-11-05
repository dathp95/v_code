from pathlib import Path
from html import escape

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem, QStyle, QStyleOptionViewItem, QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy

from gui.widgets.diagnostic.diagnostic_sequence_list import DiagnosticSequenceList
from gui.widgets.controls.primary_label import PrimaryLabel
from gui.widgets.controls.primary_lineedit import PrimaryLineEdit
from gui.widgets.controls.secondary_button import SecondaryButton
from gui.widgets.controls.primary_button import PrimaryButton
from gui.themes.styles.controls.scrollbar_style import fn_apply_scrollbar_style
from gui.themes.theme_manager import ThemeManager
from repositories.can_interface_ui_store import CanInterfaceUiStore
from gui.widgets.can_interface.panel_theme import apply_panel_theme

from PySide6.QtWidgets import QMenu

class _SequenceList(QListWidget):
    checkbox_click = False

    def mousePressEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        self.checkbox_click = False
        if item is not None:
            option = QStyleOptionViewItem()
            self.initViewItemOption(option)
            option.rect = self.visualItemRect(item)
            option.features |= QStyleOptionViewItem.HasCheckIndicator
            rectangle = self.style().subElementRect(QStyle.SE_ItemViewItemCheckIndicator, option, self)
            self.checkbox_click = rectangle.contains(event.position().toPoint())
        super().mousePressEvent(event)


class CanSequenceSidebar(DiagnosticSequenceList):
    sequence_open_requested = Signal(str)
    checked_sequences_changed = Signal(tuple)
    order_save_requested = Signal(tuple)
    add_requested = Signal()
    import_requested = Signal()
    import_folder_requested = Signal()
    export_requested = Signal()
    save_requested = Signal()

    rename_requested = Signal(str)
    delete_requested = Signal(str)
    clone_requested = Signal(str)
    load_diag_requested = Signal()

    def __init__(self, repository=None, store=None):
        self.store = store if store is not None else CanInterfaceUiStore()
        self._saved_order = ()
        self._active_source = self.store.load().selected_id
        self._drafts = {}
        self._dirty_ids = set()
        self._draft_order_baseline = ()
        self._draft_order_dirty = False
        super().__init__(repository)

    def _setup_ui(self):
        super()._setup_ui()
        self.setMinimumWidth(280)
        self.title = PrimaryLabel("Test Sequence")
        self.edit_search = PrimaryLineEdit("Search...")
        self.layout().insertWidget(0, self.title)
        self.layout().insertWidget(1, self.edit_search)
        old = self.list_sequences
        self.list_sequences = _SequenceList()
        self.list_sequences.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list_sequences.setDragDropMode(QAbstractItemView.InternalMove)
        self.list_sequences.setDefaultDropAction(Qt.MoveAction)
        self.list_sequences.setDropIndicatorShown(True)
        self.list_sequences.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list_sequences.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_sequences.setTextElideMode(Qt.ElideRight)
        self.layout().replaceWidget(old, self.list_sequences)
        old.hide()
        old.deleteLater()
        self.layout().setStretchFactor(self.list_sequences, 1)
        self.lbl_selected = PrimaryLabel("0 selected")
        self.btn_save_order = PrimaryButton("Save Order", height=30, width=90)
        self.layout().addWidget(self.lbl_selected)
        self.feedback = PrimaryLabel("")
        self.lbl_error.setTextFormat(Qt.PlainText)
        self.feedback.setTextFormat(Qt.PlainText)
        self.layout().addWidget(self.feedback)
        for label in (self.lbl_empty, self.lbl_error, self.lbl_selected, self.feedback):
            label.setMaximumHeight(22)
            label.setWordWrap(False)
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.footer = QWidget(self)
        footer_layout = QVBoxLayout(self.footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(6)
        self.footer.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.btn_add = SecondaryButton('+ Add', width=52, height=30)
        self.btn_import = SecondaryButton('Import SEQ', width=84, height=30)
        self.btn_import_folder = SecondaryButton("Import Folder", width=100, height=30,)
        self.btn_export = SecondaryButton('Export SEQ', width=84, height=30)
        self.btn_save = PrimaryButton('Save', width=70, height=30)

        # Only Save and Save Order remain visible.
        self.footer_buttons = (
            self.btn_save,
            self.btn_save_order,
        )

        row = QHBoxLayout()
        row.setSpacing(6)

        for button in self.footer_buttons:
            button.setSizePolicy(
                QSizePolicy.Expanding,
                QSizePolicy.Fixed,
            )
            row.addWidget(button, 1)

        footer_layout.addLayout(row)

        self.layout().addWidget(self.footer)
        self.btn_save.setEnabled(False)
        self.btn_export.setEnabled(False)
        for button, signal in ((self.btn_add,self.add_requested), (self.btn_import,self.import_requested),
                               (self.btn_export,self.export_requested), (self.btn_save,self.save_requested)):
            button.clicked.connect(signal)
        self.edit_search.textChanged.connect(self._filter)
        self.list_sequences.model().rowsMoved.connect(self._order_changed)
        self.list_sequences.itemActivated.connect(self._activate_item)
        self.list_sequences.setContextMenuPolicy(
            Qt.CustomContextMenu
        )

        self.list_sequences.customContextMenuRequested.connect(
            self._show_sequence_context_menu
        )

        # Hide the old action buttons without disconnecting
        # the existing logic.

        self.btn_save_order.clicked.connect(self._save_order)
        self.btn_import_folder.clicked.connect(
            self.import_folder_requested.emit
        )
        self._feedback_timer = QTimer(self)
        self._feedback_timer.setSingleShot(True)
        self._feedback_timer.timeout.connect(self.feedback.clear)

    def source_ids(self):
        return tuple(self.list_sequences.item(i).data(self.ITEM_PATH_ROLE) for i in range(self.list_sequences.count()))

    def checked_ids(self):
        return tuple(self._selected_paths())

    def _refresh_sequence_labels(self):
        """
        Prefix '**' for sequences whose position changed.

        Suffix '*' for unsaved sequence content.
        """
        current = self.source_ids()

        saved = tuple(
            source_id
            for source_id in self._saved_order
            if source_id in current
        )

        # Include sequences not present in the saved order.
        baseline = saved + tuple(
            source_id
            for source_id in current
            if source_id not in saved
        )

        updating = self._is_updating
        self._is_updating = True

        try:
            for index, source_id in enumerate(current):
                item = self.list_sequences.item(index)

                base_name = item.data(
                    Qt.UserRole + 2
                )

                order_changed = (
                    index < len(baseline)
                    and baseline[index] != source_id
                )

                content_changed = (
                    source_id in self._dirty_ids
                )

                prefix = "** " if order_changed else ""
                suffix = " *" if content_changed else ""

                item.setText(
                    f"{prefix}{base_name}{suffix}"
                )

        finally:
            self._is_updating = updating

    def fn_refresh_sequences(self):
        current = self.source_ids()
        pending = current if self.order_is_dirty() else ()
        checked = set(self.checked_ids())
        scroll = self.list_sequences.verticalScrollBar().value()
        super().fn_refresh_sequences()
        for source_id, case in self._drafts.items():
            item = self._draft_item(source_id, case)
            if source_id in checked:
                item.setCheckState(Qt.Checked)
            self.list_sequences.addItem(item)
        ids = self.source_ids()
        saved = self.store.load().order
        persistent = self.persistent_ids()
        self._saved_order = tuple(x for x in saved if x in persistent) + tuple(x for x in persistent if x not in saved)
        order = tuple(x for x in pending if x in ids) + tuple(x for x in ids if x not in pending) if pending else (*self._saved_order,*self._drafts)
        self._apply_order(order)
        self._filter(self.edit_search.text())
        self._order_changed()
        self.mark_opened(self._active_source, persist=False)
        self.list_sequences.verticalScrollBar().setValue(scroll)

        # Restore dirty markers for every unsaved sequence.
        self._refresh_sequence_labels()     
        self._emit_selection_changed()

    def _create_sequence_item(self, path, test_case):
        item = super()._create_sequence_item(str(Path(path).resolve()), test_case)
        item.setData(Qt.UserRole + 2, item.text())
        return item

    def persistent_ids(self):
        return tuple(value for value in self.source_ids() if value not in self._drafts)

    def _draft_item(self, source_id, case):
        item = QListWidgetItem(case.name)
        item.setData(self.ITEM_PATH_ROLE, source_id)
        item.setData(self.ITEM_MODEL_ROLE, case)
        item.setData(Qt.UserRole + 2, case.name)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Unchecked)
        return item

    def add_draft(self, source_id, case):
        self._drafts[source_id] = case
        self.list_sequences.addItem(self._draft_item(source_id, case))
        self._draft_order_baseline = self.source_ids()
        self._draft_order_dirty = False
        self._refresh_empty_state()
        self.mark_opened(source_id, persist=False)
        self._sync_select_all_state()
        self._emit_selection_changed()

    def remove_draft(self, source_id):
        self._drafts.pop(source_id, None)
        self._dirty_ids.discard(source_id)
        for index, value in enumerate(self.source_ids()):
            if value == source_id:
                self.list_sequences.takeItem(index)
                break
        self._sync_select_all_state()
        self._emit_selection_changed()
        self._refresh_empty_state()
        self._order_changed()

    def replace_draft_id(self, old, new):
        was_draft = old in self._drafts
        order_was_dirty = self.order_is_dirty()
        self._drafts.pop(old, None)
        self._dirty_ids.discard(old)
        if not was_draft:
            return  # Save As retains the original file-backed identity and its order.
        for index, value in enumerate(self.source_ids()):
            if value == old:
                self.list_sequences.item(index).setData(self.ITEM_PATH_ROLE,new)
                break
        if not order_was_dirty:
            self._saved_order = self.persistent_ids()

    def set_document_dirty(self, source_id, dirty):
        if dirty:
            self._dirty_ids.add(source_id)
        else:
            self._dirty_ids.discard(source_id)

        self._refresh_sequence_labels()

    def update_document_model(self, source_id, case):
        if source_id in self._drafts:
            self._drafts[source_id] = case
        updating = self._is_updating
        self._is_updating = True
        try:
            for index, value in enumerate(self.source_ids()):
                if value == source_id:
                    self.list_sequences.item(index).setData(self.ITEM_MODEL_ROLE, case)
                    break
        finally:
            self._is_updating = updating

    def set_document_actions(self, exists, save_enabled):
        self.btn_save.setEnabled(bool(exists and save_enabled))
        self.btn_export.setEnabled(bool(exists))

    def _set_errors(self, errors):
        self.sequence_errors = tuple(errors)
        self.lbl_error.setText(f'{len(errors)} sequence error(s); hover for details.' if errors else '')
        self.lbl_error.setToolTip(escape('\n'.join(errors)))
        self.lbl_error.setVisible(bool(errors))

    
    def _show_sequence_context_menu(self, position):
        item = self.list_sequences.itemAt(position)

        # Snapshot the source ID before running any action.
        # Refreshing the sidebar can destroy QListWidgetItem.
        source_id = (
            item.data(self.ITEM_PATH_ROLE)
            if item is not None
            else ""
        )

        is_sequence = bool(source_id)

        menu = QMenu(self.list_sequences)
        menu.setObjectName("testSequenceContextMenu")

        colors = ThemeManager.fn_colors()

        menu.setStyleSheet(f"""
            QMenu#testSequenceContextMenu {{
                background-color: {colors.PANEL};
                color: {colors.TEXT};
                border: 1px solid {colors.BORDER};
                padding: 5px;
            }}

            QMenu#testSequenceContextMenu::item {{
                padding: 7px 34px 7px 14px;
                margin: 2px 3px;
                border-radius: 5px;
            }}

            QMenu#testSequenceContextMenu::item:selected {{
                background-color: {colors.QUICK_ACCESS_HOVER};
                color: {colors.QUICK_ACCESS_TEXT};
            }}

            QMenu#testSequenceContextMenu::item:pressed {{
                background-color: {colors.QUICK_ACCESS_PRESSED};
            }}

            QMenu#testSequenceContextMenu::item:disabled {{
                color: {colors.BUTTON_DISABLED_TEXT};
            }}

            QMenu#testSequenceContextMenu::separator {{
                height: 1px;
                background: {colors.BORDER};
                margin: 6px 8px;
            }}
        """)

        def add_action(text, callback, enabled=True):
            action = menu.addAction(text)
            action.setEnabled(enabled)
            action.triggered.connect(
                lambda checked=False: callback()
            )
            return action

        add_action(
            "+ Add sequence",
            self.add_requested.emit,
        )

        add_action(
            "Rename",
            lambda: self.rename_requested.emit(source_id),
            is_sequence,
        )

        add_action(
            "Delete",
            lambda: self.delete_requested.emit(source_id),
            is_sequence,
        )

        add_action(
            "Clone",
            lambda: self.clone_requested.emit(source_id),
            is_sequence,
        )

        menu.addSeparator()

        add_action(
            "Import sequence",
            self.import_requested.emit,
        )

        add_action(
            "Export sequence",
            lambda: self._export_context_sequence(source_id),
            is_sequence,
        )

        add_action(
            "Import DIAG Folder",
            self.import_folder_requested.emit,
        )

        add_action(
            "Load .diag file",
            self.load_diag_requested.emit,
        )

        menu.addSeparator()

        add_action(
            "Save",
            lambda: self._save_context_sequence(source_id),
            is_sequence and source_id == self._active_source
            and source_id in self._dirty_ids,
        )

        add_action(
            "Save Order",
            self._save_order,
            self.order_is_dirty(),
        )

        menu.exec(
            self.list_sequences.viewport().mapToGlobal(
                position
            )
        )


    def _export_context_sequence(self, source_id):
        if not source_id:
            return

        # Existing export operates on the currently opened sequence.
        if source_id != self._active_source:
            self.sequence_open_requested.emit(source_id)

        if self._active_source == source_id:
            self.export_requested.emit()


    def _save_context_sequence(self, source_id):
        if (
            source_id
            and source_id == self._active_source
            and source_id in self._dirty_ids
        ):
            self.save_requested.emit()


    @staticmethod
    def _display_name(path, test_case):
        if test_case.name == Path(path).stem:
            return test_case.name
        return DiagnosticSequenceList._display_name(path, test_case)

    def _apply_order(self, ids):
        self._is_updating = True
        items = {self.list_sequences.item(i).data(self.ITEM_PATH_ROLE): self.list_sequences.item(i)
                 for i in range(self.list_sequences.count())}
        for position, source_id in enumerate(ids):
            item = items[source_id]
            self.list_sequences.takeItem(self.list_sequences.row(item))
            self.list_sequences.insertItem(position, item)
        self._is_updating = False

    def reorder(self, ids):
        ids = tuple(ids)
        if self.edit_search.text() or len(ids) != len(self.source_ids()) or set(ids) != set(self.source_ids()):
            return False
        self._apply_order(ids)
        self.mark_opened(self._active_source, persist=False)
        self._order_changed()
        return True

    def _order_changed(self, *_):
        if not self._is_updating:
            current = self.source_ids()
            common = set(current) & set(self._draft_order_baseline)
            self._draft_order_dirty = any(
                set(current[:current.index(key)]) & common !=
                set(self._draft_order_baseline[:self._draft_order_baseline.index(key)]) & common
                for key in self._drafts if key in common)
            dirty = self.order_is_dirty()
            self.btn_save_order.setEnabled(dirty)
            self.btn_save_order.setText("Save Order *" if dirty else "Save Order")
            self._refresh_sequence_labels()

    def _save_order(self):
        if self._draft_order_dirty:
            text = 'Save the new sequence before saving its position.'
            self.feedback.setText(text)
            self.feedback.setToolTip(text)
            return
        ids = self.persistent_ids()
        self.order_save_requested.emit(ids)
        try:
            self.store.save_order(ids)
        except OSError as error:
            self.feedback.setText(f"Cannot save order: {error}")
            return
        self._saved_order = ids
        self._order_changed()
        self._refresh_sequence_labels()
        self.feedback.setText("Order saved.")
        self._feedback_timer.start(1800)

    def order_is_dirty(self):
        return self._draft_order_dirty or self.persistent_ids() != self._saved_order

    def mark_opened(self, source_id, *, persist=True):
        self._active_source = source_id
        for index, item_id in enumerate(self.source_ids()):
            if item_id == source_id:
                self.list_sequences.setCurrentRow(index)
                break
        else:
            self.list_sequences.setCurrentRow(-1)
            self.list_sequences.clearSelection()
        if persist and source_id not in self._drafts:
            try:
                self.store.save_selection(source_id)
            except OSError as error:
                self.feedback.setText(f"Cannot save selection: {error}")

    def _on_item_clicked(self, item):
        if self.list_sequences.checkbox_click:
            return
        self._activate_item(item)

    def _activate_item(self, item):
        source_id = item.data(self.ITEM_PATH_ROLE)
        test_case = item.data(self.ITEM_MODEL_ROLE)
        # Opening can synchronously rebuild the list and delete this item.
        self.sequence_open_requested.emit(source_id)
        # The controller owns activation; Cancel must not notify a stale selection.
        if self._active_source == source_id:
            self.sequence_selected.emit(test_case)

    def _visible_items(self):
        return [self.list_sequences.item(i) for i in range(self.list_sequences.count())
                if not self.list_sequences.item(i).isHidden()]

    def _filter(self, text):
        for index in range(self.list_sequences.count()):
            item = self.list_sequences.item(index)
            base_name = item.data(Qt.UserRole + 2) or ""
            item.setHidden(
                text.casefold() not in base_name.casefold()
            )
        self.list_sequences.setDragEnabled(not bool(text))
        self.list_sequences.setAcceptDrops(not bool(text))
        self._sync_select_all_state()

    def _on_select_all_toggled(self, checked):
        if self._is_updating:
            return
        self._is_updating = True
        for item in self._visible_items():
            item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self._is_updating = False
        self._sync_select_all_state()
        self._emit_selection_changed()

    def fn_clear_selection(self):
        self._on_select_all_toggled(False)

    def _sync_select_all_state(self):
        items = self._visible_items()
        self.chk_select_all.blockSignals(True)
        self.chk_select_all.setChecked(bool(items) and all(x.checkState() == Qt.Checked for x in items))
        self.chk_select_all.setText("Select All (visible)")
        self.chk_select_all.setEnabled(bool(items))
        self.chk_select_all.blockSignals(False)

    def _emit_selection_changed(self):
        super()._emit_selection_changed()
        ids = self.checked_ids()
        self.lbl_selected.setText(f"{len(ids)} selected")
        self.checked_sequences_changed.emit(ids)

    def fn_refresh_theme(self):
        scroll = self.list_sequences.verticalScrollBar().value()
        apply_panel_theme(self, "canSequenceSidebar")
        super().fn_refresh_theme()
        for widget in (self.title, self.edit_search, self.lbl_selected, *self.footer_buttons, self.feedback):
            widget.fn_refresh_theme()
        colors = ThemeManager.fn_colors()
        self.list_sequences.setStyleSheet(self.list_sequences.styleSheet() +
            f"QListWidget::drop-indicator {{ background: {colors.PRIMARY}; height: 2px; }}"
            f"QListWidget::item:selected {{ background: {colors.SEQUENCE_SELECTED_BG}; color: {colors.SEQUENCE_SELECTED_TEXT}; }}")
        fn_apply_scrollbar_style(self.list_sequences)
        self.list_sequences.verticalScrollBar().setValue(scroll)
