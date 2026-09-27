"""Wrap the compatible portable payload in Debian and pacman packages."""
from __future__ import annotations

import shutil
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build/native"
OUTPUT = ROOT / "installer"


def archive_tree(source: Path, output: Path, compressed: bool = True) -> None:
    # dpkg on Ubuntu 22.04 accepts GNU long-name records, but not PAX records.
    with tarfile.open(output, "w:gz" if compressed else "w", format=tarfile.GNU_FORMAT) as archive:
        for path in sorted(source.rglob("*")):
            info = archive.gettarinfo(str(path), arcname=str(path.relative_to(source)))
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            info.mtime = 0
            if info.isfile():
                with path.open("rb") as stream:
                    archive.addfile(info, stream)
            else:
                archive.addfile(info)


def build_packages(bundle: Path) -> list[Path]:
    if BUILD.exists():
        shutil.rmtree(BUILD)
    payload = BUILD / "payload"
    shutil.copytree(bundle, payload / "opt/transferpc", symlinks=True)
    launcher = payload / "usr/bin/transferpc"
    launcher.parent.mkdir(parents=True)
    launcher.write_text('#!/bin/sh\nexec /opt/transferpc/transferpc "$@"\n')
    launcher.chmod(0o755)
    desktop = payload / "usr/share/applications/transferpc.desktop"
    desktop.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "packaging/fedora/transferpc.desktop", desktop)
    icon = payload / "usr/share/icons/hicolor/scalable/apps/transferpc.svg"
    icon.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "assets/transferpc.svg", icon)
    license_path = payload / "usr/share/licenses/transferpc/LICENSE"
    license_path.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "LICENSE", license_path)
    size = sum(path.stat().st_size for path in payload.rglob("*") if path.is_file())
    control = BUILD / "control"
    control.mkdir()
    (control / "control").write_text(
        "Package: transferpc\nVersion: 1.0-1\nSection: utils\nPriority: optional\n"
        "Architecture: amd64\nMaintainer: TransferPC <transferpc@users.noreply.github.com>\n"
        f"Installed-Size: {(size + 1023) // 1024}\n"
        "Depends: libc6 (>= 2.35), libgl1, libegl1\n"
        "Homepage: https://github.com/jotadev27/TransferPC\n"
        "Description: Verified local file transfers for Linux\n"
        " Copy or move files with checksum verification and safe overwrite confirmation.\n")
    (BUILD / "debian-binary").write_bytes(b"2.0\n")
    archive_tree(control, BUILD / "control.tar.gz")
    archive_tree(payload, BUILD / "data.tar.gz")
    deb = OUTPUT / "transferpc_1.0-1_amd64.deb"
    if deb.exists():
        deb.unlink()
    subprocess.run(["ar", "crD", str(deb), "debian-binary", "control.tar.gz", "data.tar.gz"],
                   cwd=BUILD, check=True)
    (payload / ".PKGINFO").write_text(
        "pkgname = transferpc\npkgbase = transferpc\nxdata = pkgtype=pkg\npkgver = 1.0-1\n"
        "pkgdesc = Verified local file transfers for Linux\n"
        "url = https://github.com/jotadev27/TransferPC\n"
        "builddate = 1790380800\npackager = TransferPC\n"
        f"size = {size}\narch = x86_64\nlicense = MIT\nlicense = LGPL-3.0-only\nlicense = PSF-2.0\n"
        "depend = glibc>=2.35\ndepend = libglvnd\n")
    arch_tar = BUILD / "transferpc.tar"
    archive_tree(payload, arch_tar, compressed=False)
    arch = OUTPUT / "transferpc-1.0-1-x86_64.pkg.tar.zst"
    subprocess.run(["zstd", "-q", "-f", "-T0", str(arch_tar), "-o", str(arch)], check=True)
    return [deb, arch]
