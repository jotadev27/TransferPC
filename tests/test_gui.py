from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from transferpc.gui import MainWindow
from transferpc.engine import Progress
from transferpc.locations import available_locations


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_locations_exist(self):
        locations = available_locations()
        self.assertTrue(locations)
        self.assertTrue(all(path.is_dir() for _, path in locations))

    def test_drag_drop_and_move_through_window(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            item = source / "dragged file.txt"
            item.write_text("verified", encoding="utf-8")
            window = MainWindow()
            for combo, path in ((window.source_combo, source), (window.destination_combo, destination)):
                combo.clear()
                combo.addItem(str(path), path)
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(item))])
            enter = QDragEnterEvent(window.drop.rect().center(), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
            window.drop.dragEnterEvent(enter)
            self.assertTrue(enter.isAccepted())
            drop = QDropEvent(QPointF(window.drop.rect().center()), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
            window.drop.dropEvent(drop)
            self.assertEqual(window.queue, [item])
            window.add_paths([item])
            self.assertEqual(len(window.queue), 1)
            window.queue_list.setCurrentRow(0)
            window.remove_selected()
            self.assertFalse(window.queue)
            window.add_paths([item])
            window.operation.setCurrentText("Move")
            window.show()
            self.app.processEvents()
            with patch.object(QMessageBox, "information"):
                window.start_transfer()
                deadline = time.monotonic() + 5
                while window.worker and window.worker.isRunning() and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(0.01)
                self.app.processEvents()
            self.assertEqual((destination / item.name).read_text(encoding="utf-8"), "verified")
            self.assertFalse(item.exists())
            self.assertEqual(window.phase.text(), "Transfer verified")
            self.assertEqual(window.bar.value(), 100)
            window.close()


    def _wait_for_worker(self, window):
        deadline = time.monotonic() + 5
        while window.worker and window.worker.isRunning() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.app.processEvents()
        self.assertFalse(window.worker.isRunning())

    def test_normal_copy_without_source_then_new_job_resets_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "elsewhere"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            first = source / "first.txt"
            first.write_text("copy", encoding="utf-8")
            second = source / "second.txt"
            second.write_text("next", encoding="utf-8")
            window = MainWindow()
            window.destination_combo.clear()
            window.destination_combo.addItem("Destination", destination)
            self.assertFalse(window.source_group.isVisibleTo(window))
            window.add_paths([first])
            self.assertEqual(window.queue, [first])
            self.assertIn(str(first), window.queue_list.item(0).text())
            window.show()
            with patch.object(QMessageBox, "information"):
                window.start_transfer()
                self._wait_for_worker(window)
            self.assertEqual((destination / first.name).read_text(), "copy")
            self.assertTrue(first.exists())
            self.assertEqual(window.bar.value(), 100)
            self.assertEqual(window.phase.text(), "Transfer verified")
            window.add_paths([second])
            self.assertEqual(window.bar.value(), 0)
            self.assertEqual(window.phase.text(), "Ready to transfer")
            self.assertEqual(window.bytes_label.text(), "Transferred: 0 B / 0 B")
            self.assertEqual(window.files.text(), "Files: 0 / 0")
            self.assertEqual(window.elapsed.text(), "Elapsed: 00:00:00")
            self.assertEqual(window.status.text(), "1 item(s) selected.")
            window.close()

    def test_overwrite_dialog_cancel_and_yes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            item = source / "same.txt"
            item.write_bytes(b"new")
            target = destination / item.name
            target.write_bytes(b"old")
            window = MainWindow()
            window.destination_combo.addItem("Destination", destination)
            window.destination_combo.setCurrentIndex(window.destination_combo.findData(destination))
            window.add_paths([item])
            with patch.object(QMessageBox, "question", return_value=QMessageBox.Cancel) as prompt:
                window.start_transfer()
            self.assertIsNone(window.worker)
            self.assertEqual(target.read_bytes(), b"old")
            self.assertEqual(prompt.call_args.args[-1], QMessageBox.Cancel)
            with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes), \
                 patch.object(QMessageBox, "information"):
                window.start_transfer()
                self._wait_for_worker(window)
            self.assertEqual(target.read_bytes(), b"new")
            self.assertEqual(window.bar.value(), 100)
            window.close()

    def test_remove_selected_after_failure_resets_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            item = Path(temporary) / "file.txt"
            item.write_text("data")
            window = MainWindow()
            window.add_paths([item])
            self.assertEqual(len(window.queue_list.selectedItems()), 1)
            with patch.object(QMessageBox, "critical"):
                window.on_failure("Transfer failed")
            window.queue_list.clearSelection()
            remove = next(control for control in window.edit_controls if control.text() == "Remove selected")
            remove.click()
            self.assertFalse(window.queue)
            self.assertEqual(window.queue_list.count(), 0)
            self.assertEqual(window.phase.text(), "Ready to transfer")
            self.assertEqual(window.bar.value(), 0)
            self.assertIn("Add files", window.status.text())
            self.assertTrue(item.exists())
            window.close()

    def test_remove_multiple_items_and_explain_missing_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            items = [Path(temporary) / name for name in ("first", "second")]
            for item in items:
                item.touch()
            window = MainWindow()
            window.add_paths(items)
            self.assertEqual(len(window.queue_list.selectedItems()), 2)
            window.queue_list.clearSelection()
            window.remove_selected()
            self.assertEqual(window.queue, items)
            self.assertIn("Select items", window.status.text())
            for index in range(window.queue_list.count()):
                window.queue_list.item(index).setSelected(True)
            window.remove_selected()
            self.assertFalse(window.queue)
            self.assertTrue(all(item.exists() for item in items))
            window.close()

    def test_bulk_copy_contents_without_selected_items(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "destination"
            (source / "nested").mkdir(parents=True)
            destination.mkdir()
            (source / "nested" / "file.txt").write_text("bulk", encoding="utf-8")
            (source / "empty").mkdir()
            window = MainWindow()
            window.bulk_mode.setChecked(True)
            window.source_combo.clear()
            window.source_combo.addItem("Source", source)
            window.destination_combo.clear()
            window.destination_combo.addItem("Destination", destination)
            self.assertEqual(window.status.text(), "Ready to transfer the source folder's contents.")
            self.assertFalse(window.queue)
            window.show()
            self.assertTrue(window.source_group.isVisibleTo(window))
            self.assertFalse(window.normal_group.isVisibleTo(window))
            with patch.object(QMessageBox, "information"):
                window.start_transfer()
                self._wait_for_worker(window)
            self.assertEqual((destination / "nested/file.txt").read_text(), "bulk")
            self.assertTrue((destination / "empty").is_dir())
            self.assertTrue((source / "nested/file.txt").exists())
            self.assertEqual(window.bar.value(), 100)
            another_source = root / "another"
            another_source.mkdir()
            window.source_combo.addItem("Another", another_source)
            window.source_combo.setCurrentIndex(window.source_combo.findData(another_source))
            self.assertEqual(window.bar.value(), 0)
            self.assertEqual(window.phase.text(), "Ready to transfer")
            window.close()

    def test_bulk_move_removes_only_verified_source_contents(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            (source / "file.txt").write_text("moved", encoding="utf-8")
            window = MainWindow()
            window.bulk_mode.setChecked(True)
            window.source_combo.clear()
            window.source_combo.addItem("Source", source)
            window.destination_combo.clear()
            window.destination_combo.addItem("Destination", destination)
            window.operation.setCurrentText("Move")
            window.show()
            with patch.object(QMessageBox, "information"):
                window.start_transfer()
                self._wait_for_worker(window)
            self.assertEqual((destination / "file.txt").read_text(), "moved")
            self.assertFalse((source / "file.txt").exists())
            self.assertTrue(source.is_dir())
            self.assertEqual(window.bar.value(), 100)
            window.close()

    def test_verification_never_displays_one_hundred_percent(self):
        window = MainWindow()
        for phase in ("Copying", "Verifying", "Publishing", "Verifying destination", "Removing verified sources", "Complete"):
            window.on_progress(Progress(100, 100, 1, 1, "file.txt", 1.0, 0.0, phase, 310, 310))
            self.assertLess(window.bar.value(), 100, phase)
        with patch.object(QMessageBox, "information"):
            window.on_success()
        self.assertEqual(window.bar.value(), 100)
        window.close()

    def test_bar_advances_while_all_bytes_are_already_copied(self):
        window = MainWindow()
        for work_done, phase in ((100, "Copying"), (150, "Verifying"),
                                 (200, "Verified"), (250, "Verifying destination")):
            window.on_progress(Progress(100, 100, 1, 1, "file.txt", 1.0, 0.0,
                                        phase, work_done, 310))
            self.assertEqual(window.bar.value(), work_done * 100 // 310)
        self.assertEqual(window.bytes_label.text(), "Transferred: 100 B / 100 B")
        self.assertEqual(window.eta.text(), "Copy ETA: —")
        window.close()

    def test_refresh_requeries_locations_and_preserves_valid_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first"
            second = root / "usb"
            first.mkdir()
            second.mkdir()
            window = MainWindow()
            with patch("transferpc.gui.available_locations", side_effect=[[("First", first)], [("First", first), ("USB", second)]]) as discover:
                window.refresh_button.click()
                window.destination_combo.setCurrentIndex(window.destination_combo.findData(first))
                self.assertEqual(window.destination_combo.currentData(), first)
                window.refresh_button.click()
                self.assertEqual(window.destination_combo.currentData(), first)
            self.assertEqual(discover.call_count, 2)
            self.assertGreaterEqual(window.destination_combo.findData(second), 0)
            self.assertEqual(window.refresh_button.toolTip(), "Refresh locations")
            self.assertEqual(window.refresh_feedback.text(), "Updated")
            self.assertFalse(window.refresh_button.icon().pixmap(19, 19).isNull())
            window.close()

    def test_refresh_drops_missing_detected_mount_but_keeps_custom_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mount = root / "mount"
            custom = root / "custom"
            mount.mkdir()
            custom.mkdir()
            window = MainWindow()
            with patch("transferpc.gui.available_locations", side_effect=[[("Drive", mount)], []]):
                window.refresh_button.click()
                window.destination_combo.setCurrentIndex(window.destination_combo.findData(mount))
                self.assertEqual(window.destination_combo.currentData(), mount)
                window.refresh_button.click()
            self.assertIsNone(window.destination_combo.currentData())
            window.destination_combo.addItem(f"Custom — {custom}", custom)
            window.destination_combo.setCurrentIndex(window.destination_combo.findData(custom))
            with patch("transferpc.gui.available_locations", return_value=[]):
                window.refresh_button.click()
            self.assertEqual(window.destination_combo.currentData(), custom)
            window.close()


if __name__ == "__main__":
    unittest.main()
