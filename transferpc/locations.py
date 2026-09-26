"""Live local directory and mounted volume discovery."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtCore import QStorageInfo


def _xdg_directory(kind: QStandardPaths.StandardLocation) -> Path | None:
    value = QStandardPaths.writableLocation(kind)
    path = Path(value).expanduser() if value else None
    return path if path and path.is_dir() else None


def available_locations() -> list[tuple[str, Path]]:
    locations: list[tuple[str, Path]] = []
    seen: set[Path] = set()

    def add(label: str, path: Path | None) -> None:
        if path is None:
            return
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            return
        if resolved.is_dir() and resolved not in seen and os.access(resolved, os.R_OK):
            seen.add(resolved)
            locations.append((label, resolved))

    add("Home", Path.home())
    for label, kind in (
        ("Downloads", QStandardPaths.DownloadLocation),
        ("Documents", QStandardPaths.DocumentsLocation),
        ("Pictures", QStandardPaths.PicturesLocation),
        ("Videos", QStandardPaths.MoviesLocation),
    ):
        add(label, _xdg_directory(kind))
    for volume in QStorageInfo.mountedVolumes():
        if not volume.isValid() or not volume.isReady():
            continue
        root = Path(volume.rootPath())
        if root != Path("/") and any(part.startswith(".") for part in root.parts[1:]):
            continue
        if root == Path("/tmp") or root.is_relative_to(Path("/tmp")):
            continue
        if root.is_relative_to(Path("/proc")) or root.is_relative_to(Path("/sys")) or root.is_relative_to(Path("/dev")):
            continue
        if root.is_relative_to(Path("/run")) and not root.is_relative_to(Path("/run/media")):
            continue
        if root != Path("/") and QStorageInfo(str(root.parent)).device() == volume.device():
            continue
        label = volume.displayName() or root.name or "Root filesystem"
        add(f"{label} ({root})", root)
    return locations
