"""Render documentation screenshots using entirely fictional local paths."""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from transferpc.engine import Progress
from transferpc.gui import MainWindow


def main() -> None:
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    window = MainWindow()
    for combo, label, path in (
        (window.source_combo, "Example source", Path("/mnt/source")),
        (window.destination_combo, "Example backup", Path("/mnt/backup")),
    ):
        combo.clear()
        combo.addItem(f"{label} — {path}", path)
    # No real personal files, locations or volume labels are used.
    from PySide6.QtWidgets import QListWidgetItem
    window.queue_list.addItem(QListWidgetItem("Project archive.zip\n/mnt/source/Project archive.zip"))
    window.status.setText("Transferring and verifying items…")
    window.start_button.setEnabled(False)
    window.cancel_button.setEnabled(True)
    for control in window.edit_controls:
        control.setEnabled(False)
    total = 512 * 1024 * 1024
    window.on_progress(Progress(total, total, 1, 1, "Project archive.zip", 18, 0,
                                "Verifying destination", total * 5 // 2, total * 3 + 6))
    window.show()
    app.processEvents()
    output = Path(__file__).resolve().parents[1] / "assets/screenshots"
    output.mkdir(parents=True, exist_ok=True)
    if not window.grab().save(str(output / "transferpc.png")):
        raise RuntimeError("Could not render normal-mode screenshot")
    window.bulk_mode.setChecked(True)
    window.start_button.setEnabled(True)
    window.cancel_button.setEnabled(False)
    for control in window.edit_controls:
        control.setEnabled(True)
    window.phase.setText("Ready to transfer")
    window.current.setText("No transfer in progress")
    window.bar.setValue(0)
    window.bytes_label.setText("Transferred: 0 B / 0 B")
    window.remaining.setText("Remaining: 0 B")
    window.elapsed.setText("Elapsed: 00:00:00")
    window.files.setText("Files: 0 / 0")
    app.processEvents()
    if not window.grab().save(str(output / "transferpc-bulk.png")):
        raise RuntimeError("Could not render bulk-mode screenshot")
    window.close()


if __name__ == "__main__":
    main()
