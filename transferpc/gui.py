"""Qt desktop interface. All transfers run on a worker thread."""
from __future__ import annotations

import os
import threading
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal, QSize, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QProgressBar, QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from .engine import Progress, TransferCancelled, TransferConflict, TransferEngine, TransferError, build_plan
from .locations import available_locations


def format_size(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{amount:.0f} B" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return "0 B"


def format_time(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


class DropArea(QFrame):
    dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("dropArea")
        self.setAcceptDrops(True)
        self.setMinimumHeight(90)
        layout = QVBoxLayout(self)
        title = QLabel("Drop files and folders here")
        title.setAlignment(Qt.AlignCenter)
        title.setObjectName("dropTitle")
        hint = QLabel("Or use Add files / Add folder below")
        hint.setAlignment(Qt.AlignCenter)
        hint.setObjectName("muted")
        layout.addWidget(title)
        layout.addWidget(hint)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() and all(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        self.dropped.emit([Path(url.toLocalFile()) for url in event.mimeData().urls()])
        event.acceptProposedAction()


class TransferWorker(QThread):
    progress_changed = Signal(object)
    succeeded = Signal()
    failed = Signal(str)
    cancelled = Signal(str)

    def __init__(self, sources: list[Path], destination: Path, move: bool,
                 overwrite: bool = False) -> None:
        super().__init__()
        self.sources = sources
        self.destination = destination
        self.move = move
        self.overwrite = overwrite
        self.cancel_event = threading.Event()

    def run(self) -> None:
        try:
            TransferEngine(self.progress_changed.emit, self.cancel_event).run(
                self.sources, self.destination, self.move, self.overwrite)
        except TransferCancelled as exc:
            self.cancelled.emit(str(exc))
        except (TransferError, OSError) as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"Unexpected transfer error ({type(exc).__name__}): {exc}")
        else:
            self.succeeded.emit()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TransferPC · v1.0")
        self.setWindowIcon(QIcon(str(Path(__file__).parent.parent / "assets" / "transferpc.svg")))
        self.resize(760, 780)
        self.setMinimumSize(590, 750)
        self._normal_height = 780
        self.worker: TransferWorker | None = None
        self.queue: list[Path] = []
        self.edit_controls: list[QPushButton] = []
        self._terminal_state = False
        self._build_ui()
        self.refresh_locations()
        self.refresh_feedback.clear()
        self.source_combo.currentIndexChanged.connect(self._source_selection_changed)
        self.destination_combo.currentIndexChanged.connect(self._destination_selection_changed)
        self.operation.currentIndexChanged.connect(self._new_job_if_finished)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(24, 16, 24, 16)
        outer.setSpacing(10)

        header = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QIcon(str(Path(__file__).parent.parent / "assets" / "transferpc.svg")).pixmap(40, 40))
        heading = QVBoxLayout()
        title = QLabel("TransferPC")
        title.setObjectName("title")
        subtitle = QLabel("Verified local file transfers")
        subtitle.setObjectName("muted")
        heading.addWidget(title)
        heading.addWidget(subtitle)
        header.addWidget(logo)
        header.addLayout(heading)
        header.addStretch()
        self.refresh_feedback = QLabel("")
        self.refresh_feedback.setObjectName("refreshFeedback")
        self.refresh_feedback.setAccessibleName("Location refresh status")
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self.refresh_feedback.clear)
        header.addWidget(self.refresh_feedback)
        self.refresh_button = QPushButton()
        self.refresh_button.setObjectName("refreshButton")
        self.refresh_button.setIcon(QIcon(str(Path(__file__).parent.parent / "assets" / "refresh-arrow.svg")))
        self.refresh_button.setIconSize(QSize(19, 19))
        self.refresh_button.setFixedSize(38, 38)
        self.refresh_button.setToolTip("Refresh locations")
        self.refresh_button.setAccessibleName("Refresh locations")
        self.refresh_button.clicked.connect(self.refresh_locations)
        self.edit_controls.append(self.refresh_button)
        header.addWidget(self.refresh_button)
        outer.addLayout(header)

        self.bulk_mode = QCheckBox("Transfer entire folder")
        self.bulk_mode.setObjectName("bulkMode")
        self.bulk_mode.setToolTip("Copy or move the contents of one source folder")
        self.bulk_mode.toggled.connect(self._mode_changed)
        outer.addWidget(self.bulk_mode)

        self.source_group = QWidget()
        self.source_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        source_layout = QVBoxLayout(self.source_group)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.setSpacing(5)
        source_layout.addWidget(QLabel("Source folder"))
        source_row = QHBoxLayout()
        self.source_combo = QComboBox()
        self.source_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        source_row.addWidget(self.source_combo, 1)
        source_browse = QPushButton("Browse")
        source_browse.clicked.connect(lambda: self.browse(self.source_combo))
        self.edit_controls.append(source_browse)
        source_row.addWidget(source_browse)
        source_layout.addLayout(source_row)
        self.source_group.setVisible(False)
        outer.addWidget(self.source_group)

        destination_label = QLabel("Destination")
        outer.addWidget(destination_label)
        destination_row = QHBoxLayout()
        self.destination_combo = QComboBox()
        self.destination_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        destination_row.addWidget(self.destination_combo, 1)
        destination_browse = QPushButton("Browse")
        destination_browse.clicked.connect(lambda: self.browse(self.destination_combo))
        self.edit_controls.append(destination_browse)
        destination_row.addWidget(destination_browse)
        outer.addLayout(destination_row)

        operation_row = QHBoxLayout()
        operation_row.addWidget(QLabel("Operation"))
        self.operation = QComboBox()
        self.operation.addItems(["Copy", "Move"])
        self.operation.setFixedWidth(125)
        self.operation.setMinimumHeight(36)
        operation_row.addWidget(self.operation)
        operation_row.addStretch()
        outer.addLayout(operation_row)

        self.normal_group = QWidget()
        normal_layout = QVBoxLayout(self.normal_group)
        normal_layout.setContentsMargins(0, 0, 0, 0)
        normal_layout.setSpacing(8)
        self.drop = DropArea()
        self.drop.dropped.connect(self.add_paths)
        normal_layout.addWidget(self.drop)
        queue_header = QHBoxLayout()
        queue_header.addWidget(QLabel("Selected items · sources"))
        queue_header.addStretch()
        add_files = QPushButton("Add files")
        add_files.clicked.connect(self.add_files)
        self.edit_controls.append(add_files)
        queue_header.addWidget(add_files)
        add_folder = QPushButton("Add folder")
        add_folder.clicked.connect(self.add_folder)
        self.edit_controls.append(add_folder)
        queue_header.addWidget(add_folder)
        remove = QPushButton("Remove selected")
        remove.clicked.connect(self.remove_selected)
        self.edit_controls.append(remove)
        queue_header.addWidget(remove)
        normal_layout.addLayout(queue_header)
        self.queue_list = QListWidget()
        self.queue_list.setMinimumHeight(80)
        normal_layout.addWidget(self.queue_list, 1)
        outer.addWidget(self.normal_group, 1)
        self.bulk_spacer = QWidget()
        self.bulk_spacer.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.bulk_spacer.setVisible(False)
        outer.addWidget(self.bulk_spacer, 1)

        panel = QFrame()
        panel.setObjectName("progressPanel")
        panel.setMinimumHeight(155)
        progress_layout = QVBoxLayout(panel)
        progress_layout.setSpacing(8)
        self.phase = QLabel("Ready to transfer")
        self.phase.setObjectName("sectionTitle")
        self.current = QLabel("No transfer in progress")
        self.current.setObjectName("muted")
        self.current.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setFormat("%p%")
        self.bar.setToolTip("Overall progress: copying, checksum verification and finalization")
        self.bytes_label = QLabel("Transferred: 0 B / 0 B")
        self.remaining = QLabel("Remaining: 0 B")
        self.speed = QLabel("Speed: —")
        self.elapsed = QLabel("Elapsed: 00:00:00")
        self.eta = QLabel("Copy ETA: —")
        self.files = QLabel("Files: 0 / 0")
        progress_layout.addWidget(self.phase)
        progress_layout.addWidget(self.current)
        progress_layout.addWidget(self.bar)
        stats = QGridLayout()
        for index, widget in enumerate((self.bytes_label, self.remaining, self.speed,
                                         self.elapsed, self.eta, self.files)):
            stats.addWidget(widget, index // 2, index % 2)
        progress_layout.addLayout(stats)
        outer.addWidget(panel)

        actions = QHBoxLayout()
        self.status = QLabel("Add files or a folder, then choose a destination.")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        actions.addWidget(self.status, 1)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_transfer)
        self.start_button = QPushButton("Start transfer")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self.start_transfer)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.start_button)
        outer.addLayout(actions)
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #ffffff; color: #202b3a; font: 13px 'Sans Serif'; }
            QLabel#title { font-size: 22px; font-weight: 700; color: #102d55; }
            QLabel#sectionTitle { font-size: 15px; font-weight: 600; }
            QLabel#dropTitle { font-size: 16px; font-weight: 600; color: #2059a2; }
            QLabel#muted { color: #627184; }
            QComboBox, QListWidget { border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px; background: white; }
            QPushButton { border: 1px solid #b9c8db; border-radius: 6px; min-height: 20px; min-width: 86px; padding: 8px 12px; background: #f7faff; font-weight: 600; }
            QPushButton:hover { background: #e8f1ff; border-color: #83a9dc; }
            QPushButton:pressed { background: #cfdef3; border-color: #4d82c9; }
            QPushButton:focus { border: 2px solid #1768d1; }
            QPushButton:disabled { color: #9aa6b5; background: #f3f5f7; border-color: #d9e0e8; }
            QPushButton#primary { background: #1768d1; color: white; border-color: #1768d1; font-weight: 600; min-width: 110px; }
            QPushButton#primary:hover { background: #1257b3; }
            QPushButton#primary:pressed { background: #0c438e; }
            QPushButton#primary:disabled { background: #9bbce7; color: white; }
            QPushButton#refreshButton { min-width: 0; padding: 7px; }
            QLabel#refreshFeedback { color: #177245; padding-right: 8px; }
            QFrame#dropArea { border: 2px dashed #87afe2; border-radius: 9px; background: #f7fbff; }
            QFrame#dropArea QLabel { background: transparent; }
            QFrame#progressPanel { background: transparent; border: 0; border-top: 1px solid #e1e8f0; padding-top: 8px; }
            QFrame#progressPanel QLabel { background: transparent; }
            QProgressBar { border: 1px solid #cbd5e1; border-radius: 5px; text-align: center; background: white; height: 17px; }
            QProgressBar::chunk { background: #1768d1; border-radius: 4px; }
        """)

    def _reset_result(self) -> None:
        if not self._terminal_state:
            return
        self._terminal_state = False
        self.phase.setText("Ready to transfer")
        self.current.setText("No transfer in progress")
        self.bar.setValue(0)
        self.bytes_label.setText("Transferred: 0 B / 0 B")
        self.remaining.setText("Remaining: 0 B")
        self.speed.setText("Speed: —")
        self.elapsed.setText("Elapsed: 00:00:00")
        self.eta.setText("Copy ETA: —")
        self.files.setText("Files: 0 / 0")
        self.status.setStyleSheet("")
        self.status.setText("Ready to transfer.")

    def _new_job_if_finished(self, *_args) -> None:
        if not (self.worker and self.worker.isRunning()):
            self._reset_result()

    def _source_selection_changed(self, *_args) -> None:
        if self.bulk_mode.isChecked():
            self._new_job_if_finished()
            self._update_ready_status()

    def _destination_selection_changed(self, *_args) -> None:
        self._new_job_if_finished()
        self._update_ready_status()

    def _update_ready_status(self) -> None:
        if self._terminal_state or (self.worker and self.worker.isRunning()):
            return
        if self.bulk_mode.isChecked():
            ready = self.source_combo.currentData() and self.destination_combo.currentData()
            self.status.setText("Ready to transfer the source folder's contents." if ready else
                                "Choose a source folder and destination.")
        else:
            self.status.setText(f"{len(self.queue)} item(s) selected." if self.queue else
                                "Add files or a folder, then choose a destination.")

    def _mode_changed(self, bulk: bool) -> None:
        if bulk:
            self._normal_height = self.height()
            self.setMinimumHeight(570)
            self.resize(self.width(), 600)
        else:
            self.setMinimumHeight(750)
            self.resize(self.width(), max(self._normal_height, 750))
        self.source_group.setVisible(bulk)
        self.normal_group.setVisible(not bulk)
        self.bulk_spacer.setVisible(bulk)
        self._new_job_if_finished()
        self._update_ready_status()

    def refresh_locations(self) -> None:
        locations = available_locations()
        previous_source = self.source_combo.currentData()
        previous_destination = self.destination_combo.currentData()
        for combo in (self.source_combo, self.destination_combo):
            previous = combo.currentData()
            # A disconnected volume can leave its mount directory behind.
            # Preserve only directories the user explicitly browsed to.
            was_custom = combo.currentText().startswith("Custom — ")
            custom = previous if was_custom and previous and Path(previous).is_dir() else None
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Choose source folder…" if combo is self.source_combo else "Choose destination…", None)
            for label, path in locations:
                combo.addItem(f"{label} — {path}", path)
            if custom and combo.findData(custom) < 0:
                combo.addItem(f"Custom — {custom}", custom)
            index = combo.findData(previous) if previous else -1
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.blockSignals(False)
        if (previous_source != self.source_combo.currentData() or
                previous_destination != self.destination_combo.currentData()):
            self._new_job_if_finished()
            self._update_ready_status()
        if hasattr(self, "refresh_feedback"):
            self.refresh_feedback.setText("Updated")
            self._refresh_timer.start(1800)

    def browse(self, combo: QComboBox) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Choose a directory", str(combo.currentData() or Path.home()))
        if chosen:
            path = Path(chosen).resolve()
            index = combo.findData(path)
            if index < 0:
                combo.addItem(f"Custom — {path}", path)
                index = combo.count() - 1
            combo.setCurrentIndex(index)
            self._new_job_if_finished()

    def add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose files", str(Path.home()))
        self.add_paths([Path(path) for path in paths])

    def add_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose a folder", str(Path.home()))
        if path:
            self.add_paths([Path(path)])

    def add_paths(self, paths: list[Path]) -> None:
        if self.worker and self.worker.isRunning():
            return
        if self.bulk_mode.isChecked():
            return
        for path in paths:
            path = Path(os.path.abspath(path))
            if not path.exists():
                self.status.setText(f"Source is unavailable: {path}")
                continue
            if path.is_symlink():
                self.status.setText(f"Symbolic links are not supported: {path.name}")
                continue
            try:
                path = path.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                self.status.setText(f"Cannot read source: {exc}")
                continue
            if path in self.queue:
                continue
            if any(path.is_relative_to(item) or item.is_relative_to(path) for item in self.queue):
                self.status.setText(f"Item overlaps an item already queued: {path.name}")
                continue
            self._reset_result()
            self.queue.append(path)
            item = QListWidgetItem(f"{path.name}\n{path}")
            item.setData(Qt.UserRole, str(path))
            item.setToolTip(str(path))
            self.queue_list.addItem(item)
            self.status.setText(f"{len(self.queue)} item(s) selected.")

    def remove_selected(self) -> None:
        for item in self.queue_list.selectedItems():
            self._reset_result()
            self.queue.remove(Path(item.data(Qt.UserRole)))
            self.queue_list.takeItem(self.queue_list.row(item))
        self.status.setText(f"{len(self.queue)} item(s) selected.")

    def start_transfer(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        destination = self.destination_combo.currentData()
        overwrite = False
        try:
            if destination is None:
                raise TransferError("Select a destination directory.")
            if self.bulk_mode.isChecked():
                source = self.source_combo.currentData()
                if source is None:
                    raise TransferError("Select a source folder.")
                source = Path(source)
                if source.is_symlink() or not source.is_dir():
                    raise TransferError("Source folder is unavailable or is a symbolic link.")
                source = source.resolve(strict=True)
                destination_resolved = Path(destination).resolve(strict=True)
                if destination_resolved == source or destination_resolved.is_relative_to(source):
                    raise TransferError("Destination cannot be inside the source folder.")
                sources = sorted(source.iterdir())
                if not sources:
                    raise TransferError("The source folder has no items to transfer.")
            else:
                sources = list(self.queue)
            try:
                build_plan(sources, destination)
            except TransferConflict as conflict:
                names = "\n".join(conflict.names[:10])
                if len(conflict.names) > 10:
                    names += f"\n…and {len(conflict.names) - 10} more file(s)"
                answer = QMessageBox.question(
                    self, "Overwrite existing files?",
                    f"These destination files already exist:\n\n{names}\n\n"
                    "Do you want to overwrite them? Matching names and sizes do not "
                    "guarantee identical contents. The previous files are kept until "
                    "the new copies pass verification.",
                    QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
                if answer != QMessageBox.Yes:
                    return
                overwrite = True
                build_plan(sources, destination, overwrite=True)
        except (TransferError, OSError) as exc:
            QMessageBox.warning(self, "Cannot start transfer", str(exc))
            return
        self.worker = TransferWorker(sources, destination,
                                     self.operation.currentText() == "Move", overwrite)
        self.worker.progress_changed.connect(self.on_progress)
        self.worker.succeeded.connect(self.on_success)
        self.worker.failed.connect(self.on_failure)
        self.worker.cancelled.connect(self.on_cancelled)
        self.worker.finished.connect(self.on_finished)
        self.status.setStyleSheet("")
        self.status.setText("Transferring and verifying items…")
        self.bar.setValue(0)
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.source_combo.setEnabled(False)
        self.bulk_mode.setEnabled(False)
        self.destination_combo.setEnabled(False)
        self.operation.setEnabled(False)
        self.drop.setAcceptDrops(False)
        for control in self.edit_controls:
            control.setEnabled(False)
        self.phase.setText(f"{self.operation.currentText()} in progress")
        self.worker.start()

    def on_progress(self, progress: Progress) -> None:
        percent = progress.work_done * 100 // progress.work_total if progress.work_total else 0
        # Count real copy, verification and filesystem work. Only the worker's
        # success signal may display 100%, after temporary staging is removed.
        self.bar.setValue(min(percent, 99))
        stage = {
            "Preparing": "Preparing…",
            "Copying": "Transferring…",
            "Verifying": "Verifying…",
            "Verified": "Verifying…",
            "Publishing": "Verifying…",
            "Verifying destination": "Verifying destination…",
            "Removing verified sources": "Finishing move…",
            "Finalizing": "Finalizing…",
            "Complete": "Finalizing…",
        }.get(progress.phase, progress.phase)
        self.phase.setText(stage)
        self.current.setText(progress.current_file or progress.phase)
        self.bytes_label.setText(f"Transferred: {format_size(progress.transferred)} / {format_size(progress.total)}")
        remaining = max(0, progress.total - progress.transferred)
        self.remaining.setText(f"Remaining: {format_size(remaining)}")
        self.speed.setText(f"Speed: {format_size(int(progress.speed))}/s" if progress.speed else "Speed: —")
        self.elapsed.setText(f"Elapsed: {format_time(progress.elapsed)}")
        self.eta.setText(f"Copy ETA: {format_time(remaining / progress.speed)}" if progress.speed and remaining else "Copy ETA: —")
        self.files.setText(f"Files: {progress.completed_files} / {progress.total_files}")

    def on_success(self) -> None:
        self._terminal_state = True
        self.bar.setValue(100)
        self.phase.setText("Transfer verified")
        self.status.setStyleSheet("color: #177245;")
        self.status.setText("All items transferred and verified successfully.")
        QMessageBox.information(self, "Transfer complete", "All items transferred and verified successfully.")
        self.queue.clear()
        self.queue_list.clear()

    def on_failure(self, message: str) -> None:
        self._terminal_state = True
        self.phase.setText("Transfer failed")
        self.status.setStyleSheet("color: #b42318;")
        self.status.setText(message)
        QMessageBox.critical(self, "Transfer failed", message)

    def on_cancelled(self, message: str) -> None:
        self._terminal_state = True
        self.phase.setText("Transfer cancelled")
        self.status.setText(message)

    def on_finished(self) -> None:
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.source_combo.setEnabled(True)
        self.bulk_mode.setEnabled(True)
        self.destination_combo.setEnabled(True)
        self.operation.setEnabled(True)
        self.drop.setAcceptDrops(True)
        for control in self.edit_controls:
            control.setEnabled(True)

    def cancel_transfer(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancel_event.set()
            self.cancel_button.setEnabled(False)
            self.status.setText("Cancelling safely…")

    def closeEvent(self, event) -> None:
        if self.worker and self.worker.isRunning():
            self.cancel_transfer()
            event.ignore()
            QMessageBox.information(self, "Transfer in progress", "The transfer is stopping safely. Close the window after it finishes.")
            return
        event.accept()
