"""Build the allowlisted Fedora RPM payload and package it with rpmbuild."""
from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION = "1.0"
TOPDIR = ROOT / "build" / "rpm"
STAGING = TOPDIR / "SOURCES" / f"transferpc-{VERSION}"
DIST = ROOT / "installer"
FORBIDDEN = (Path.home().name.encode(), b"/home/", b".venv", b"__pycache__")


def render_icons() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    app = QGuiApplication.instance() or QGuiApplication([])
    renderer = QSvgRenderer(str(ROOT / "assets" / "transferpc.svg"))
    if not renderer.isValid():
        raise RuntimeError("Application icon SVG could not be rendered")
    for size in (32, 48, 64, 128, 256):
        image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        output = STAGING / "assets" / "icons" / f"{size}x{size}" / "transferpc.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        if not image.save(str(output)):
            raise RuntimeError(f"Could not render {size}px icon")
    del app


def stage_sources() -> None:
    if STAGING.exists():
        shutil.rmtree(STAGING)
    for relative in (
        *(Path("transferpc") / name for name in ("__init__.py", "__main__.py", "engine.py", "gui.py", "locations.py")),
        Path("assets/transferpc.svg"),
        Path("assets/refresh-arrow.svg"),
        Path("packaging/fedora/launch.py"),
        Path("packaging/fedora/transferpc"),
        Path("packaging/fedora/transferpc.desktop"),
        Path("LICENSE"),
        Path("THIRD_PARTY_NOTICES.md"),
    ):
        source = ROOT / relative
        target = STAGING / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    render_icons()
    for file in STAGING.rglob("*"):
        if file.is_file():
            data = file.read_bytes()
            for forbidden in FORBIDDEN:
                if forbidden in data:
                    raise RuntimeError(f"Private or development data found in package input: {file.name}")


def make_tarball() -> Path:
    tarball = TOPDIR / "SOURCES" / f"transferpc-{VERSION}.tar.gz"
    with tarfile.open(tarball, "w:gz", format=tarfile.PAX_FORMAT) as archive:
        for file in sorted(STAGING.rglob("*")):
            info = archive.gettarinfo(str(file), arcname=str(file.relative_to(STAGING.parent)))
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            info.mtime = 0
            if file.is_file():
                with file.open("rb") as reader:
                    archive.addfile(info, reader)
            else:
                archive.addfile(info)
    return tarball


def main() -> None:
    for subdir in ("SOURCES", "BUILD", "BUILDROOT", "RPMS", "SRPMS", "SPECS"):
        (TOPDIR / subdir).mkdir(parents=True, exist_ok=True)
    stage_sources()
    make_tarball()
    subprocess.run(["desktop-file-validate", str(STAGING / "packaging/fedora/transferpc.desktop")], check=True)
    subprocess.run([
        "rpmbuild", "-bb", str(ROOT / "packaging/fedora/transferpc.spec"),
        "--define", f"_topdir {TOPDIR}",
        "--define", "_tmppath /tmp",
        "--define", "_buildhost localhost",
        "--define", "_packager TransferPC",
    ], check=True)
    packages = list((TOPDIR / "RPMS").rglob("transferpc-1.0-*.rpm"))
    if len(packages) != 1:
        raise RuntimeError(f"Expected one RPM, found {len(packages)}")
    DIST.mkdir(exist_ok=True)
    output = DIST / packages[0].name
    shutil.copy2(packages[0], output)
    print(output)


if __name__ == "__main__":
    main()
