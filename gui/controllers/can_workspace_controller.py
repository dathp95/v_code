from pathlib import Path
import re
import os
from dataclasses import replace
from uuid import uuid4
from dataclasses import replace

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QFileDialog, QMessageBox, QInputDialog, QDialog
from core.diagnostic_sequence import DiagnosticTestCase
from core.vehicle_dll_paths import safe_component
from gui.dialogs.sequence_exchange_dialog import SequenceExchangeDialog
from services.can.diag_batch_converter import (
    convert_diag_folder,
)

class CanWorkspaceController(QObject):
    """Sequence document actions and view preferences; no ECU or transport store."""
    def __init__(self, sidebar, panel, repository, store, parent=None):
        super().__init__(parent)
        self.sidebar, self.panel, self.repository, self.store = sidebar, panel, repository, store
        self.source = None
        self.document_id = None
        # Unsaved sequence content, held only in RAM.
        # Key: absolute JSON/DIAG source path.
        # Value: DiagnosticTestCase.
        self._session_drafts = {}

        # Paths that have unsaved modifications.
        self._session_dirty = set()

        # Runtime results (Receive Message / Results) of sequences not on screen.
        # Key: absolute source path. Value: panel.runtime_snapshot().
        self._session_runtime = {}
        sidebar.load_diag_requested.connect(self.browse_source)

        sidebar.sequence_open_requested.connect(self.open_source)
        panel.load_requested.connect(self.browse_source)
        panel.save_requested.connect(self.save_sequence)
        panel.sequence_modified.connect(self._modified)
        panel.vehicle_changed.connect(self._vehicle_changed)
        panel.document_changed.connect(self._sync_actions)
        sidebar.add_requested.connect(self.add_sequence)
        sidebar.import_requested.connect(self.import_sequence)
        sidebar.import_folder_requested.connect(
            self.import_diag_folder
        )
        sidebar.export_requested.connect(self.export_sequence)
        sidebar.rename_requested.connect(
            self.rename_sequence
        )

        sidebar.delete_requested.connect(
            self.delete_sequence
        )

        sidebar.clone_requested.connect(
            self.clone_sequence
        )
        sidebar.save_requested.connect(lambda: self.save_sequence())
        self._sync_actions()

    
    def _case_for_source(self, source_id):
        """
        Return the newest model:
        unsaved RAM draft takes priority over disk.
        """
        path = Path(source_id).resolve()
        key = str(path)

        if key == self.document_id:
            self._remember_current_sequence()

        case = self._session_drafts.get(key)

        if case is None:
            case = self.repository.fn_load_sequence(path)

        return case


    def _validate_new_sequence_path(self, name, old_path=None):
        name = name.strip()
        safe_component(name)

        root = self.repository.root.resolve()
        target = root / f"{name}.json"

        for path in root.glob("*.json"):
            if (
                path.name.casefold() == target.name.casefold()
                and (
                    old_path is None
                    or path.resolve() != old_path.resolve()
                )
            ):
                raise FileExistsError(
                    "A sequence with this filename already exists."
                )

        return target.resolve()


    def _update_saved_path_references(self, old_id, new_id):
        """
        Move UI preferences after a rename.
        The JSON source itself is handled separately.
        """
        state = self.store.load()

        order = tuple(
            new_id if value == old_id else value
            for value in state.order
        )

        sources = tuple(
            new_id if value == old_id else value
            for value in state.sources
        )

        vehicles = dict(state.vehicles)

        if old_id in vehicles:
            vehicles[new_id] = vehicles.pop(old_id)

        selected = (
            new_id
            if state.selected_id == old_id
            else state.selected_id
        )

        updated = replace(
            state,
            order=tuple(dict.fromkeys(order)),
            sources=tuple(dict.fromkeys(sources)),
            vehicles=vehicles,
            selected_id=selected,
        )

        self.store._save(updated)

    
    def rename_sequence(self, source_id):
        if not source_id:
            return False

        source = Path(source_id).resolve()

        if source.suffix.lower() != ".json":
            self.panel.show_notice(
                "Only native JSON sequences can be renamed."
            )
            return False

        if not source.is_file():
            self.panel.show_notice(
                "Sequence file does not exist."
            )
            return False

        try:
            case = self._case_for_source(str(source))
        except (OSError, ValueError) as error:
            self.panel.show_notice(str(error))
            return False

        new_name, ok = QInputDialog.getText(
            self.panel,
            "Rename Sequence",
            "New sequence name:",
            text=case.name,
        )

        if not ok:
            return False

        new_name = new_name.strip()

        try:
            destination = self._validate_new_sequence_path(
                new_name,
                old_path=source,
            )

            if destination == source and new_name == case.name:
                return True

            updated_case = replace(case, name=new_name)

            # Handle a display-name-only change without moving.
            if destination == source:
                self.repository.fn_save_sequence(
                    updated_case, source
                )
            else:
                # Reserve a new filename; do not overwrite
                # an existing document.
                with destination.open("x", encoding="utf-8"):
                    pass

                try:
                    self.repository.fn_save_sequence(
                        updated_case, destination
                    )
                except Exception:
                    destination.unlink(missing_ok=True)
                    raise

                # Remove the old path only after the new JSON
                # has been successfully written.
                try:
                    source.unlink()
                except OSError:
                    destination.unlink(missing_ok=True)
                    raise

            old_id = str(source)
            new_id = str(destination)

            self._update_saved_path_references(
                old_id, new_id
            )

            was_dirty = old_id in self._session_dirty

            self._session_drafts.pop(old_id, None)
            self._session_dirty.discard(old_id)
            self.sidebar._dirty_ids.discard(old_id)
            runtime = self._session_runtime.pop(old_id, None)
            if runtime is not None:
                self._session_runtime[new_id] = runtime

            if self.document_id == old_id:
                self.source = destination
                self.document_id = new_id

                self.panel._test_case = updated_case
                self.panel.mark_saved()

            self.sidebar.fn_refresh_sequences()
            self.sidebar.mark_opened(
                self.document_id or "",
                persist=False,
            )

            self._sync_actions()
            self.panel.show_notice(
                f"Renamed to {new_name}."
            )

            return True

        except (OSError, ValueError) as error:
            self.panel.show_notice(
                f"Cannot rename sequence: {error}"
            )
            return False



    
    def delete_sequence(self, source_id):
        if not source_id:
            return False

        source = Path(source_id).resolve()

        if source.suffix.lower() != ".json":
            self.panel.show_notice(
                "Only JSON sequences can be deleted."
            )
            return False

        answer = QMessageBox.question(
            self.panel,
            "Delete Sequence",
            f"Permanently delete '{source.stem}'?\n"
            "This action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if answer != QMessageBox.Yes:
            return False

        try:
            source.unlink()
        except OSError as error:
            self.panel.show_notice(
                f"Cannot delete sequence: {error}"
            )
            return False

        old_id = str(source)

        self._session_drafts.pop(old_id, None)
        self._session_dirty.discard(old_id)
        self._session_runtime.pop(old_id, None)
        self.sidebar._dirty_ids.discard(old_id)

        state = self.store.load()

        vehicles = dict(state.vehicles)
        vehicles.pop(old_id, None)

        updated = replace(
            state,
            order=tuple(
                x for x in state.order if x != old_id
            ),
            sources=tuple(
                x for x in state.sources if x != old_id
            ),
            vehicles=vehicles,
            selected_id=(
                ""
                if state.selected_id == old_id
                else state.selected_id
            ),
        )

        try:
            self.store._save(updated)
        except OSError as error:
            self.panel.show_notice(
                f"Sequence deleted, but UI preferences "
                f"could not be updated: {error}"
            )

        if self.document_id == old_id:
            self.source = None
            self.document_id = None
            self.panel.fn_load_sequence(None)

        self.sidebar.fn_refresh_sequences()
        self.sidebar.mark_opened(
            self.document_id or "",
            persist=False,
        )

        self._sync_actions()
        self.panel.show_notice("Sequence deleted.")

        return True

    
    def clone_sequence(self, source_id):
        if not source_id:
            return False

        source = Path(source_id).resolve()

        if source.suffix.lower() != ".json":
            self.panel.show_notice(
                "Only JSON sequences can be cloned."
            )
            return False

        try:
            case = self._case_for_source(str(source))

            root = self.repository.root.resolve()
            base_name = f"{source.stem}_copy"

            index = 1

            while True:
                name = (
                    base_name
                    if index == 1
                    else f"{base_name}_{index}"
                )

                destination = root / f"{name}.json"

                if not any(
                    path.name.casefold()
                    == destination.name.casefold()
                    for path in root.glob("*.json")
                ):
                    break

                index += 1

            cloned_case = replace(
                case,
                name=name,
            )

            # Create exclusively to avoid replacing
            # a file already existing on disk.
            with destination.open("x", encoding="utf-8"):
                pass

            try:
                self.repository.fn_save_sequence(
                    cloned_case,
                    destination,
                )
            except Exception:
                destination.unlink(missing_ok=True)
                raise

            # Refresh without changing the current document.
            self.sidebar.fn_refresh_sequences()

            self.sidebar.mark_opened(
                self.document_id or "",
                persist=False,
            )

            self.panel.show_notice(
                f"Cloned: {destination.name}"
            )

            return True

        except (OSError, ValueError) as error:
            self.panel.show_notice(
                f"Cannot clone sequence: {error}"
            )
            return False



    def _modified(self, case):
        if self.document_id is None:
            return

        # Save the edited model in memory only.
        self._session_drafts[self.document_id] = case
        self._session_dirty.add(self.document_id)

        # Update the document title.
        self.panel.title.setText(f"{case.name} *")

        # Update the corresponding sidebar item.
        self.sidebar.update_document_model(
            self.document_id,
            case,
        )

        self.sidebar.set_document_dirty(
            self.document_id,
            True,
        )

        self._sync_actions()

    def _remember_current_sequence(self):
        """Keep the active edited sequence in RAM."""

        if self.document_id is None:
            return

        if not self.panel.fn_is_dirty():
            return

        case = self.panel.fn_current_sequence()

        if case is None:
            return

        self._session_drafts[self.document_id] = case
        self._session_dirty.add(self.document_id)

    def _sync_actions(self):
        case = self.panel.fn_current_sequence()
        self.sidebar.set_document_actions(case is not None,
            self.panel.fn_is_dirty() or self.source is None or self.source.suffix.lower() == '.diag')

    def _release_current(self):
        if self.document_id in self.sidebar._drafts:
            self.sidebar.remove_draft(self.document_id)
        elif self.document_id:
            self.sidebar.set_document_dirty(self.document_id, False)

    def add_sequence(self, name=None):

        if name is None:
            name, ok = QInputDialog.getText(
                self.panel,
                "New Sequence",
                "Sequence name:",
            )

            if not ok:
                return False

        name = name.strip()

        try:
            safe_component(name)

            # Reject duplicate display names.
            existing_names = set()

            for source_path in self.repository.fn_list_sequences():
                try:
                    existing = self.repository.fn_load_sequence(
                        source_path
                    )
                    existing_names.add(existing.name.casefold())
                except (OSError, ValueError):
                    continue

            if name.casefold() in existing_names:
                raise ValueError(
                    f"Sequence '{name}' already exists."
                )

            destination = (
                self.repository.root / f"{name}.json"
            ).resolve()

            if destination.exists():
                raise FileExistsError(
                    f"File already exists: {destination.name}"
                )

            # Create an empty valid sequence.
            case = DiagnosticTestCase(
                schema_version=1,
                name=name,
                description="",
                enabled=True,
                steps=[],
            )

            # Create the JSON file immediately.
            self.repository.fn_save_sequence(
                case,
                destination,
            )

        except (OSError, ValueError) as error:
            self.panel.show_notice(
                f"Cannot create sequence: {error}"
            )
            return False

        # Remember any unsaved edits in the previous sequence.
        self._remember_current_sequence()

        # Switch to the newly created file.
        self.source = None
        self.document_id = None

        return self.open_source(
            str(destination),
            force=True,
        )
    
    def import_diag_folder(self):
        """Import a folder of .diag files into V-CODE JSON library."""

        folder = QFileDialog.getExistingDirectory(
            self.panel,
            "Select folder containing DIAG files",
            "",
            QFileDialog.ShowDirsOnly,
        )

        if not folder:
            return

        try:
            result = convert_diag_folder(
                folder,
                self.repository,
            )

        except (OSError, ValueError) as error:
            QMessageBox.warning(
                self.panel,
                "Import Folder Failed",
                str(error),
            )
            return

        # Refresh only the sidebar.
        # Do not reload the current document:
        # it may contain unsaved in-memory edits.
        self.sidebar.fn_refresh_sequences()

        summary = (
            f"Imported: {len(result.imported)}\n"
            f"Skipped: {len(result.skipped)}\n"
            f"Failed: {len(result.failed)}"
        )

        dialog = QMessageBox(self.panel)
        dialog.setWindowTitle("DIAG Folder Import")
        dialog.setIcon(
            QMessageBox.Warning
            if result.failed
            else QMessageBox.Information
        )
        dialog.setText(summary)

        if result.failed:
            details = "\n".join(
                f"{name}: {message}"
                for name, message in result.failed
            )
            dialog.setDetailedText(details)

        dialog.setStandardButtons(QMessageBox.Ok)
        dialog.exec()


    def import_sequence(self):
        names = {ecu.name for ecu in self.panel._available_ecus if self.panel._resolved_ecu(ecu.name)} if self.panel._current_vehicle is not None else None
        dialog = SequenceExchangeDialog(self.panel, ecu_names=names)
        if dialog.exec() != QDialog.Accepted:
            return False
        if self.panel.fn_current_sequence() is None and not self.add_sequence():
            return False
        self.panel.apply_import(dialog.parsed, dialog.mode)
        return True

    def export_sequence(self):
        if self.panel.fn_current_sequence() is None:
            return False
        SequenceExchangeDialog(self.panel, text=self.panel.exchange_text()).exec()
        return True

    def _allow_replace(self):
        if not self.panel.fn_is_dirty():
            return True

        answer = QMessageBox.question(
            self.panel,
            "Unsaved sequence",
            "Save changes before opening another sequence?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )

        if answer == QMessageBox.Cancel:
            return False

        if answer == QMessageBox.Discard:
            return True

        if answer == QMessageBox.Save:
            result = self.save_sequence()

            if result is None:
                QMessageBox.warning(
                    self.panel,
                    "Save Failed",
                    "The sequence could not be saved. "
                    "Your changes have been kept."
                )
                return False

            return True

        return False
    def browse_source(self):
        path, _ = QFileDialog.getOpenFileName(self.panel, "Load Diagnostic Sequence", "", "Sequences (*.diag *.json)")
        if path:
            self.open_source(path, force=True)

    def open_source(
            self,
            source_id,
            *,
            persist=True,
            force=False,
        ):
        try:
            path = Path(source_id).resolve()
            target_id = str(path)

            if self.source == path and not force:
                return True

            # Prefer the unsaved in-memory version.
            if target_id in self._session_drafts:
                case = self._session_drafts[target_id]
            else:
                case = self.repository.fn_load_sequence(path)

        except (OSError, ValueError) as error:
            self.panel.show_notice(
                f"Cannot open sequence: {error}"
            )
            self.sidebar.mark_opened(
                self.document_id or "",
                persist=False,
            )
            return False

        # Preserve the active unsaved document and its runtime results.
        self._remember_current_sequence()
        if self.document_id is not None:
            self._session_runtime[self.document_id] = self.panel.runtime_snapshot()

        # Switching is unconditional, with no Save dialog.
        self.source = path
        self.document_id = target_id

        self.panel.fn_load_sequence(case)

        # fn_load_sequence() resets the dirty flag.
        dirty = target_id in self._session_dirty

        self.panel._is_dirty = dirty

        self.panel.title.setText(
            case.name + (" *" if dirty else "")
        )

        chosen = self.store.load().vehicles.get(
            target_id,
            "",
        )

        self.panel.fn_refresh_vehicles(chosen)

        # After the Vehicle refresh, which clears results; restores only unchanged rows.
        self.panel.restore_runtime_snapshot(
            self._session_runtime.pop(target_id, None)
        )

        if hasattr(self.repository, "register_source"):
            self.repository.register_source(path)

        self.sidebar.fn_refresh_sequences()

        self.sidebar.mark_opened(
            target_id,
            persist=persist,
        )

        # Restore the dirty indicator.
        self.sidebar.set_document_dirty(
            target_id,
            dirty,
        )

        if case.steps:
            self.panel._select_row(0)

        self._sync_actions()

        return True

    def restore(self):
        selected = self.store.load().selected_id
        if selected:
            self.open_source(selected, persist=False)

    def save_sequence(self, path=None, *, overwrite=False):
        case = self.panel.fn_current_sequence()
        if case is None:
            self.panel.show_notice("No diagnostic sequence to save.")
            return None
        if path is None:

            if self.source is not None:
                suffix = self.source.suffix.lower()

                if suffix == ".json":
                    # Update existing JSON directly.
                    path = self.source

                elif suffix == ".diag":

                    target = (
                        self.repository.root
                        / f"{self.source.stem}.json"
                    )

                    # This source is read-only.
                    # Create a new native JSON only if necessary.
                    if target.exists():
                        index = 1

                        while True:
                            candidate = (
                                self.repository.root
                                / f"{self.source.stem}_{index}.json"
                            )

                            if not candidate.exists():
                                target = candidate
                                break

                            index += 1

                    path = target

                    # The selected target was checked as unused.
                    # Repository saving still validates the destination.
                    overwrite = False

                else:
                    self.panel.show_notice(
                        "Unsupported sequence format."
                    )
                    return None

            else:
                # First Save for a new sequence.
                name = re.sub(
                    r'[<>:"/\\|?*]',
                    '_',
                    case.name
                ) or "sequence"

                path, _ = QFileDialog.getSaveFileName(
                    self.panel,
                    "Save New Sequence",
                    str(self.repository.root / f"{name}.json"),
                    "V-CODE Sequence (*.json)"
                )

                if not path:
                    return None

                overwrite = True
        destination = Path(path).resolve()
        try:
            case = self.panel.sequence_for_save()
            if destination.suffix.lower() != '.json':
                raise ValueError("Save As must use .json; .diag sources are never overwritten.")
            if destination.exists() and destination != self.source and not overwrite:
                raise FileExistsError("Destination already exists. Choose a different file or confirm overwrite in Save As.")
            result = self.repository.fn_save_sequence(case, destination)
           
            if not destination.is_file():
                raise OSError(
                    f"Sequence file was not created: {destination}"
                )
        except (OSError, ValueError) as error:
            self.panel.show_notice(f"Cannot save sequence: {error}")
            return None
        
        self.source = destination

        old_id = self.document_id
        self.document_id = str(destination)

        # The file write has succeeded.
        # Remove the corresponding unsaved RAM draft.
        self._session_drafts.pop(old_id, None)
        self._session_dirty.discard(old_id)

        # Also clear any entry using the destination identity.
        self._session_drafts.pop(self.document_id, None)
        self._session_dirty.discard(self.document_id)

        self.sidebar.replace_draft_id(old_id, self.document_id)
        
        
        self.panel._test_case = case
        self.panel._step_signatures = self.panel._runtime_signatures()
        self.panel._refresh_ecu_combos()
        self.panel._selection_changed()
        self.panel.mark_saved()
        if hasattr(self.repository, 'register_source'):
            self.repository.register_source(destination)
        self.sidebar.fn_refresh_sequences()
        self.sidebar.mark_opened(str(destination))
        self.sidebar.set_document_dirty(self.document_id, False)
        self._sync_actions()
        self._vehicle_changed(self.panel.fn_current_vehicle())
        self.panel.show_notice(
            "Sequence saved successfully."
        )
        return result

    def _vehicle_changed(self, name):
        if self.source is not None:
            try:
                self.store.save_vehicle(str(self.source), name)
            except OSError as error:
                self.panel.show_notice(f"Cannot save Vehicle view preference: {error}")

    def refresh_vehicles(self, changed_name=""):
        self.panel.fn_refresh_vehicles(preserve_unchanged=True)
