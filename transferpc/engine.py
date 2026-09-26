"""Verified, staged filesystem transfers."""
from __future__ import annotations

import ctypes
import errno
import hashlib
import os
import shutil
import stat
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

CHUNK_SIZE = 4 * 1024 * 1024
_AT_FDCWD = -100
_RENAME_NOREPLACE = 1


class TransferError(Exception):
    pass


class TransferCancelled(TransferError):
    pass


@dataclass(frozen=True)
class Progress:
    transferred: int
    total: int
    completed_files: int
    total_files: int
    current_file: str
    elapsed: float
    speed: float
    phase: str
    work_done: int = 0
    work_total: int = 0


@dataclass(frozen=True)
class FileEntry:
    source: Path
    relative: Path
    size: int
    device: int
    inode: int
    mtime_ns: int


@dataclass(frozen=True)
class Plan:
    sources: tuple[Path, ...]
    destination: Path
    files: tuple[FileEntry, ...]
    directories: tuple[Path, ...]
    directory_ids: tuple[tuple[Path, int, int], ...]
    total_bytes: int


def _walk_error(exc: OSError) -> None:
    raise TransferError(f"Cannot scan source folder: {exc}") from exc


def _regular_info(path: Path) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        raise TransferError(f"Cannot read {path}: {exc.strerror or exc}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise TransferError(f"Unsupported file type or symbolic link: {path}")
    return info


def _directory_info(path: Path) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        raise TransferError(f"Cannot read source folder {path}: {exc.strerror or exc}") from exc
    if not stat.S_ISDIR(info.st_mode):
        raise TransferError(f"Unsupported folder entry or symbolic link: {path}")
    return info


def build_plan(sources: list[Path], destination: Path) -> Plan:
    """Snapshot the queue and reject unsafe or conflicting paths."""
    if not sources:
        raise TransferError("Add at least one file or folder first.")
    try:
        dest = destination.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise TransferError(f"Destination is unavailable: {exc}") from exc
    if not dest.is_dir():
        raise TransferError("Destination must be a directory.")
    unique: list[Path] = []
    files: list[FileEntry] = []
    directories: list[Path] = []
    directory_ids: list[tuple[Path, int, int]] = []
    for item in sources:
        source = Path(os.path.abspath(item))
        try:
            info = source.lstat()
        except OSError as exc:
            raise TransferError(f"Source is unavailable: {source}: {exc.strerror or exc}") from exc
        if stat.S_ISLNK(info.st_mode):
            raise TransferError(f"Symbolic links are not supported: {source}")
        try:
            source = source.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise TransferError(f"Cannot resolve source path: {source}: {exc}") from exc
        if source in unique:
            continue
        if any(source.name == previous.name for previous in unique):
            raise TransferError(f"Queued items have the same name: {source.name}")
        if any(source.is_relative_to(parent) or parent.is_relative_to(source) for parent in unique):
            raise TransferError(f"Queued items overlap: {source}")
        if dest == source or (stat.S_ISDIR(info.st_mode) and dest.is_relative_to(source)):
            raise TransferError("Destination cannot be inside a source folder.")
        if source.parent == dest or (dest / source.name).exists() or (dest / source.name).is_symlink():
            raise TransferError(f"An item already exists at the destination: {source.name}")
        unique.append(source)
        if stat.S_ISREG(info.st_mode):
            files.append(FileEntry(source, Path(source.name), info.st_size, info.st_dev, info.st_ino, info.st_mtime_ns))
        elif stat.S_ISDIR(info.st_mode):
            for root, dirs, names in os.walk(source, followlinks=False, onerror=_walk_error):
                root_path = Path(root)
                root_info = _directory_info(root_path)
                directories.append(Path(source.name) / root_path.relative_to(source))
                directory_ids.append((root_path, root_info.st_dev, root_info.st_ino))
                for dirname in dirs:
                    child = root_path / dirname
                    _directory_info(child)
                for name in names:
                    child = root_path / name
                    child_info = _regular_info(child)
                    relative = Path(source.name) / child.relative_to(source)
                    files.append(FileEntry(child, relative, child_info.st_size, child_info.st_dev, child_info.st_ino, child_info.st_mtime_ns))
        else:
            raise TransferError(f"Unsupported source type: {source}")
    try:
        free = shutil.disk_usage(dest).free
    except OSError as exc:
        raise TransferError(f"Cannot determine destination space: {exc}") from exc
    total = sum(entry.size for entry in files)
    if total > free:
        raise TransferError(f"Insufficient destination space: need {total:,} bytes; available {free:,} bytes.")
    return Plan(tuple(unique), dest, tuple(files), tuple(directories), tuple(directory_ids), total)


def _validate_sources(plan: Plan) -> None:
    expected_files = {entry.source for entry in plan.files}
    expected_dirs = {path for path, _, _ in plan.directory_ids}
    for entry in plan.files:
        current = _regular_info(entry.source)
        if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (entry.device, entry.inode, entry.size, entry.mtime_ns):
            raise TransferError(f"Source changed during transfer: {entry.source}")
    for path, device, inode in plan.directory_ids:
        try:
            current = path.lstat()
        except OSError as exc:
            raise TransferError(f"Source folder is unavailable: {path}: {exc}") from exc
        if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (device, inode):
            raise TransferError(f"Source folder changed during transfer: {path}")
    for source in plan.sources:
        if source in expected_dirs:
            actual_dirs: set[Path] = set()
            actual_files: set[Path] = set()
            for root, dirs, names in os.walk(source, followlinks=False, onerror=_walk_error):
                actual_dirs.add(Path(root))
                actual_dirs.update(Path(root) / name for name in dirs)
                actual_files.update(Path(root) / name for name in names)
            if actual_dirs != {path for path in expected_dirs if path == source or path.is_relative_to(source)} or actual_files != {path for path in expected_files if path.is_relative_to(source)}:
                raise TransferError(f"Source folder contents changed during transfer: {source}")


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish(source: Path, target: Path) -> None:
    # Linux renameat2 prevents a concurrent process from replacing an existing item.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.renameat2(_AT_FDCWD, os.fsencode(source), _AT_FDCWD, os.fsencode(target), _RENAME_NOREPLACE) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(target))


class TransferEngine:
    def __init__(self, progress: Callable[[Progress], None] | None = None,
                 cancel: threading.Event | None = None) -> None:
        self.progress = progress or (lambda _: None)
        self.cancel = cancel or threading.Event()

    def _check_cancel(self) -> None:
        if self.cancel.is_set():
            raise TransferCancelled("Transfer cancelled. Source files were kept.")

    def run(self, sources: list[Path], destination: Path, move: bool = False) -> None:
        plan = build_plan(sources, destination)
        self._check_cancel()
        stage = plan.destination / f".transferpc-{uuid.uuid4().hex}"
        copied = completed = 0
        # Count the copy and both checksum passes, plus filesystem operations.
        # Small operation units also give empty files/folders meaningful progress.
        work_done = 0
        work_total = (3 * plan.total_bytes + 3 * len(plan.directories)
                      + len(plan.files) + len(plan.sources) + 4)
        if move:
            work_total += len(plan.files) + len(plan.directories) + 1
        started = time.monotonic()
        published: list[Path] = []
        hashes: dict[Path, bytes] = {}
        last_copy_time = started
        last_copy_bytes = 0
        copy_speed = 0.0

        def update(current: str, phase: str) -> None:
            nonlocal last_copy_time, last_copy_bytes, copy_speed
            now = time.monotonic()
            elapsed = now - started
            if phase == "Copying" and copied > last_copy_bytes:
                interval = max(now - last_copy_time, 0.001)
                instantaneous = (copied - last_copy_bytes) / interval
                copy_speed = instantaneous if copy_speed == 0 else 0.65 * copy_speed + 0.35 * instantaneous
                last_copy_time = now
                last_copy_bytes = copied
            self.progress(Progress(copied, plan.total_bytes, completed, len(plan.files),
                                   current, elapsed, copy_speed if phase == "Copying" else 0,
                                   phase, work_done, work_total))

        try:
            stage.mkdir(mode=0o700)
            update("", "Preparing")
            for directory in plan.directories:
                self._check_cancel()
                (stage / directory).mkdir(parents=True, exist_ok=True)
                work_done += 1
                update(str(directory), "Preparing")
            for entry in plan.files:
                self._check_cancel()
                target = stage / entry.relative
                target.parent.mkdir(parents=True, exist_ok=True)
                source_hash = hashlib.sha256()
                try:
                    with entry.source.open("rb", buffering=0) as reader, target.open("xb", buffering=0) as writer:
                        current = os.fstat(reader.fileno())
                        if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (entry.device, entry.inode, entry.size, entry.mtime_ns):
                            raise TransferError(f"Source changed before copying: {entry.source}")
                        while True:
                            self._check_cancel()
                            chunk = reader.read(CHUNK_SIZE)
                            if not chunk:
                                break
                            source_hash.update(chunk)
                            view = memoryview(chunk)
                            while view:
                                self._check_cancel()
                                written = writer.write(view)
                                if not written:
                                    raise OSError(errno.EIO, "Write returned no data")
                                view = view[written:]
                                copied += written
                                work_done += written
                                update(str(entry.relative), "Copying")
                        os.fsync(writer.fileno())
                        current = os.fstat(reader.fileno())
                        if (current.st_size, current.st_mtime_ns) != (entry.size, entry.mtime_ns):
                            raise TransferError(f"Source changed while copying: {entry.source}")
                    self._check_cancel()
                    update(str(entry.relative), "Verifying")
                    if target.stat().st_size != entry.size:
                        raise TransferError(f"Size verification failed: {entry.relative}")
                    target_hash = hashlib.sha256()
                    with target.open("rb", buffering=0) as reader:
                        while True:
                            self._check_cancel()
                            chunk = reader.read(CHUNK_SIZE)
                            if not chunk:
                                break
                            target_hash.update(chunk)
                            work_done += len(chunk)
                            update(str(entry.relative), "Verifying")
                    if source_hash.digest() != target_hash.digest():
                        raise TransferError(f"Checksum verification failed: {entry.relative}")
                    hashes[entry.relative] = source_hash.digest()
                    completed += 1
                    work_done += 1
                    update(str(entry.relative), "Verified")
                except OSError as exc:
                    raise TransferError(f"Failed to transfer {entry.source}: {exc.strerror or exc}") from exc
            self._check_cancel()
            _validate_sources(plan)
            work_done += 1
            for directory in reversed(plan.directories):
                _fsync_dir(stage / directory)
                work_done += 1
                update(str(directory), "Publishing")
            _fsync_dir(stage)
            work_done += 1
            self._check_cancel()
            update("", "Publishing")
            for source in plan.sources:
                self._check_cancel()
                target = plan.destination / source.name
                _publish(stage / source.name, target)
                published.append(source)
                work_done += 1
                update(source.name, "Publishing")
            _fsync_dir(plan.destination)
            work_done += 1
            update("", "Verifying destination")
            for directory in plan.directories:
                self._check_cancel()
                target = plan.destination / directory
                if not stat.S_ISDIR(target.lstat().st_mode):
                    raise TransferError(f"Destination folder verification failed: {directory}")
                work_done += 1
                update(str(directory), "Verifying destination")
            verified_bytes = 0
            for entry in plan.files:
                self._check_cancel()
                target = plan.destination / entry.relative
                info = _regular_info(target)
                if info.st_size != entry.size:
                    raise TransferError(f"Destination size verification failed: {entry.relative}")
                digest = hashlib.sha256()
                with target.open("rb", buffering=0) as reader:
                    while True:
                        self._check_cancel()
                        chunk = reader.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        digest.update(chunk)
                        work_done += len(chunk)
                        update(str(entry.relative), "Verifying destination")
                if digest.digest() != hashes[entry.relative]:
                    raise TransferError(f"Destination checksum verification failed: {entry.relative}")
                verified_bytes += info.st_size
            if verified_bytes != plan.total_bytes:
                raise TransferError("Destination byte count verification failed.")
            if move:
                self._check_cancel()
                # Once published, cancellation cannot interrupt source removal halfway through.
                update("", "Removing verified sources")
                _validate_sources(plan)
                work_done += 1
                for entry in plan.files:
                    entry.source.unlink()
                    work_done += 1
                    update(str(entry.relative), "Removing verified sources")
                for directory in sorted((path for path, _, _ in plan.directory_ids),
                                        key=lambda path: len(path.parts), reverse=True):
                    directory.rmdir()
                    work_done += 1
                    update(directory.name, "Removing verified sources")
            update("", "Finalizing")
        except TransferCancelled as exc:
            if published:
                raise TransferCancelled(f"{exc} Some destination items may remain.") from exc
            raise
        except TransferError as exc:
            if published:
                raise TransferError(f"{exc} Some destination items may remain; inspect both locations before retrying.") from exc
            raise
        except OSError as exc:
            suffix = " Some destination items may remain; inspect both locations before retrying." if published else ""
            raise TransferError(f"Transfer failed: {exc.strerror or exc}.{suffix}") from exc
        finally:
            if stage.exists():
                try:
                    shutil.rmtree(stage)
                except OSError as exc:
                    raise TransferError(f"Could not remove temporary transfer data at {stage}: {exc}") from exc
        work_done += 1
        update("", "Complete")
