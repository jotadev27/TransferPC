from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from transferpc.engine import TransferCancelled, TransferEngine, TransferError, build_plan


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source = root / "source"
        self.destination = root / "destination"
        self.source.mkdir()
        self.destination.mkdir()

    def assert_no_stage(self):
        self.assertFalse(list(self.destination.glob(".transferpc-*")))

    def test_small_multiple_unicode_and_space(self):
        first = self.source / "a file.txt"
        second = self.source / "données.txt"
        first.write_bytes(b"hello")
        second.write_bytes(b"\x00" * 123)
        events = []
        TransferEngine(events.append).run([first, second], self.destination)
        self.assertEqual((self.destination / first.name).read_bytes(), first.read_bytes())
        self.assertEqual((self.destination / second.name).read_bytes(), second.read_bytes())
        self.assertEqual(events[-1].transferred, 128)
        self.assertEqual(events[-1].completed_files, 2)
        self.assert_no_stage()

    def test_large_file_progress_and_hash(self):
        item = self.source / "large.bin"
        data = os.urandom(9 * 1024 * 1024)
        item.write_bytes(data)
        events = []
        TransferEngine(events.append).run([item], self.destination)
        self.assertEqual((self.destination / item.name).read_bytes(), data)
        self.assertTrue(any(0 < event.transferred < len(data) for event in events))

    def test_nested_and_empty_directory(self):
        folder = self.source / "folder"
        (folder / "nested" / "empty").mkdir(parents=True)
        (folder / "nested" / "file").write_bytes(b"content")
        TransferEngine().run([folder], self.destination)
        self.assertTrue((self.destination / "folder/nested/empty").is_dir())
        self.assertEqual((self.destination / "folder/nested/file").read_bytes(), b"content")

    def test_move_after_verification(self):
        item = self.source / "move.txt"
        item.write_bytes(b"move me")
        TransferEngine().run([item], self.destination, move=True)
        self.assertFalse(item.exists())
        self.assertEqual((self.destination / item.name).read_bytes(), b"move me")

    def test_move_nested_folder(self):
        folder = self.source / "folder"
        (folder / "nested" / "empty").mkdir(parents=True)
        (folder / "nested" / "file").write_bytes(b"verified")
        TransferEngine().run([folder], self.destination, move=True)
        self.assertFalse(folder.exists())
        self.assertEqual((self.destination / "folder/nested/file").read_bytes(), b"verified")

    def test_existing_destination_is_rejected(self):
        item = self.source / "same"
        item.write_bytes(b"new")
        (self.destination / "same").write_bytes(b"old")
        with self.assertRaisesRegex(TransferError, "already exists"):
            TransferEngine().run([item], self.destination)
        self.assertEqual((self.destination / "same").read_bytes(), b"old")
        self.assert_no_stage()

    def test_missing_source_and_destination(self):
        with self.assertRaisesRegex(TransferError, "Source is unavailable"):
            build_plan([self.source / "missing"], self.destination)
        item = self.source / "file"
        item.write_bytes(b"x")
        with self.assertRaisesRegex(TransferError, "Destination is unavailable"):
            build_plan([item], self.destination / "missing")

    def test_insufficient_space(self):
        item = self.source / "file"
        item.write_bytes(b"some bytes")
        usage = os.statvfs(self.destination)
        with patch("transferpc.engine.shutil.disk_usage") as disk_usage:
            disk_usage.return_value.free = 1
            with self.assertRaisesRegex(TransferError, "Insufficient"):
                build_plan([item], self.destination)
        self.assertTrue(usage.f_bavail >= 0)

    def test_cancel_keeps_source_and_removes_stage(self):
        item = self.source / "file"
        item.write_bytes(os.urandom(5 * 1024 * 1024))
        event = threading.Event()
        def progress(state):
            if state.transferred:
                event.set()
        with self.assertRaises(TransferCancelled):
            TransferEngine(progress, event).run([item], self.destination, move=True)
        self.assertTrue(item.exists())
        self.assertFalse((self.destination / item.name).exists())
        self.assert_no_stage()

    def test_cancel_during_destination_verification_keeps_move_source(self):
        item = self.source / "file"
        item.write_bytes(b"verified first")
        event = threading.Event()
        def progress(state):
            if state.phase == "Verifying destination":
                event.set()
        with self.assertRaisesRegex(TransferCancelled, "destination items may remain"):
            TransferEngine(progress, event).run([item], self.destination, move=True)
        self.assertEqual(item.read_bytes(), b"verified first")
        self.assertTrue((self.destination / item.name).exists())

    def test_corruption_preserves_move_source(self):
        item = self.source / "file"
        item.write_bytes(b"original")
        corrupted = False
        def progress(state):
            nonlocal corrupted
            if state.phase == "Verifying" and not corrupted:
                stage = next(self.destination.glob(".transferpc-*"))
                (stage / item.name).write_bytes(b"corrupt!")
                corrupted = True
        with self.assertRaisesRegex(TransferError, "Checksum verification failed"):
            TransferEngine(progress).run([item], self.destination, move=True)
        self.assertEqual(item.read_bytes(), b"original")
        self.assertFalse((self.destination / item.name).exists())
        self.assert_no_stage()

    def test_published_corruption_preserves_move_source(self):
        item = self.source / "file"
        item.write_bytes(b"original")
        def progress(state):
            if state.phase == "Verifying destination":
                (self.destination / item.name).write_bytes(b"corrupt!")
        with self.assertRaisesRegex(TransferError, "Destination checksum verification failed"):
            TransferEngine(progress).run([item], self.destination, move=True)
        self.assertEqual(item.read_bytes(), b"original")
        self.assert_no_stage()

    def test_destination_disappears_during_transfer(self):
        item = self.source / "file"
        item.write_bytes(b"original")
        def progress(state):
            if state.phase == "Verified":
                import shutil
                shutil.rmtree(self.destination)
        with self.assertRaises(TransferError):
            TransferEngine(progress).run([item], self.destination, move=True)
        self.assertEqual(item.read_bytes(), b"original")

    def test_folder_changes_during_transfer(self):
        folder = self.source / "folder"
        folder.mkdir()
        (folder / "file").write_bytes(b"data")
        def progress(state):
            if state.phase == "Verified":
                (folder / "new file").write_bytes(b"new")
        with self.assertRaisesRegex(TransferError, "contents changed"):
            TransferEngine(progress).run([folder], self.destination, move=True)
        self.assertTrue((folder / "file").exists())
        self.assertFalse((self.destination / "folder").exists())

    def test_empty_folder_disappears_during_transfer(self):
        folder = self.source / "empty"
        folder.mkdir()
        def progress(state):
            if state.phase == "Preparing":
                folder.rmdir()
        with self.assertRaisesRegex(TransferError, "Source folder is unavailable"):
            TransferEngine(progress).run([folder], self.destination, move=True)
        self.assertFalse((self.destination / "empty").exists())

    def test_permission_error_is_reported(self):
        item = self.source / "file"
        item.write_bytes(b"original")
        original_open = Path.open
        def denied(path, *args, **kwargs):
            if path == item:
                raise PermissionError("permission denied")
            return original_open(path, *args, **kwargs)
        with patch.object(Path, "open", denied):
            with self.assertRaisesRegex(TransferError, "permission denied"):
                TransferEngine().run([item], self.destination)
        self.assert_no_stage()

    def test_short_writes_are_retried(self):
        item = self.source / "file"
        item.write_bytes(os.urandom(100_000))
        original_open = Path.open
        class ShortWriter:
            def __init__(self, stream):
                self.stream = stream
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return self.stream.__exit__(*args)
            def write(self, data):
                return self.stream.write(data[:max(1, len(data) // 2)])
            def fileno(self):
                return self.stream.fileno()
        def short_open(path, *args, **kwargs):
            stream = original_open(path, *args, **kwargs)
            return ShortWriter(stream) if args and args[0] == "xb" else stream
        with patch.object(Path, "open", short_open):
            TransferEngine().run([item], self.destination)
        self.assertEqual((self.destination / item.name).read_bytes(), item.read_bytes())
        self.assert_no_stage()

    def test_source_disappears_before_copy(self):
        item = self.source / "file"
        item.write_bytes(b"data")
        def progress(state):
            if state.phase == "Preparing":
                item.unlink()
        with self.assertRaises(TransferError):
            TransferEngine(progress).run([item], self.destination)
        self.assert_no_stage()

    def test_symlink_and_destination_inside_source_rejected(self):
        folder = self.source / "folder"
        folder.mkdir()
        (folder / "link").symlink_to(self.source)
        with self.assertRaisesRegex(TransferError, "symbolic link"):
            build_plan([folder], self.destination)
        (folder / "link").unlink()
        with self.assertRaisesRegex(TransferError, "inside a source"):
            build_plan([folder], folder)


if __name__ == "__main__":
    unittest.main()
