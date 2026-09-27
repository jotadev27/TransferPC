"""Build Linux RPM and bundled portable releases using explicit payloads."""
from __future__ import annotations

import hashlib
import argparse
import os
import platform
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging"))
from audit_public import check_data

VERSION = "1.0"
RELEASE_NOTES = """# TransferPC v1.0

Verified local file transfers for Linux.

## Highlights
- Copy or move files and folders with drag and drop and whole-folder mode.
- Overall progress includes copying, both checksum passes and finalization.
- SHA-256 verification before and after publication; Move removes only verified sources.
- Existing regular files prompt Yes or Cancel, with Cancel selected by default.
- Previous destination files are restored if verification fails or cancellation occurs before source removal.
- Queue removal works after transfer errors, with multiple selection support.
- Local operation: no uploads, analytics, remote access service or automatic updater.
- English interface and documentation. TransferPC source is licensed under MIT.

## Downloads
- transferpc-1.0-1.fc44.noarch.rpm: Fedora 44 installer using distribution dependencies.
- transferpc_1.0-1_amd64.deb: Ubuntu 22.04+ installer with bundled Python and Qt.
- transferpc-1.0-1-x86_64.pkg.tar.zst: Manjaro/Arch installer with bundled Python and Qt.
- transferpc-1.0-linux-x86_64-portable.tar.gz: bundled Python and Qt; extract and run ./transferpc from the TransferPC-1.0 folder.
- SHA256SUMS: verify downloads with sha256sum -c SHA256SUMS.

## Compatibility and limitations
The bundled packages and portable target Linux x86_64 with glibc 2.35 or newer and a compatible desktop session. The portable is built on Ubuntu 22.04. Ubuntu container and Fedora startup checks are automated; the pacman package is checked in an Arch container. A Manjaro desktop has not been tested. For older systems or other architectures, use the source installation with Python 3.10+ and PySide6 6.6+.
Existing folders, symbolic links and special files cannot be overwritten. Keep sources unchanged during a transfer. Wait for Transfer verified and 100% before disconnecting storage. Errors after publication can leave destination items; inspect both locations before retrying. If rollback fails, the previous file's backup path is reported and retained. Cancellation cannot interrupt source removal once final Move cleanup starts.
Integrity verification does not scan files for malware. A public repository does not grant access to the maintainer's computer; future code and dependency changes still require review.

Bundled dependency licenses are included in the portable. See the repository README, SECURITY.md and THIRD_PARTY_NOTICES.md for details.
"""
OUTPUT = ROOT / "installer"
BUILD = ROOT / "build"
SOURCE = BUILD / "portable-source"


def run(*arguments: str) -> None:
    subprocess.run(arguments, cwd=ROOT, check=True)


def stage_portable() -> None:
    if SOURCE.exists():
        shutil.rmtree(SOURCE)
    for relative in (
        *(Path("transferpc") / name for name in
          ("__init__.py", "__main__.py", "engine.py", "gui.py", "locations.py")),
        Path("assets/transferpc.svg"), Path("assets/refresh-arrow.svg"),
    ):
        target = SOURCE / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        data = (ROOT / relative).read_bytes()
        check_data(data)
        target.write_bytes(data)
    shutil.copyfile(ROOT / "packaging/fedora/launch.py", SOURCE / "launch.py")


def copy_notices(bundle: Path) -> None:
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copyfile(ROOT / name, bundle / name)
    licenses = bundle / "licenses"
    licenses.mkdir(exist_ok=True)
    # Include the installed distribution's notices for every bundled library.
    if shutil.which("rpm") and Path("/etc/fedora-release").exists():
        copy_rpm_notices(bundle, licenses)
    else:
        shutil.copytree("/usr/share/common-licenses", licenses / "common", dirs_exist_ok=True)
        shutil.copytree(BUILD / "qt-license-texts", licenses / "Qt", dirs_exist_ok=True)
        # Debian's copyright files include notices for distribution libraries.
        for path in Path("/usr/share/doc").glob("*/copyright"):
            destination = licenses / "distribution" / path.parent.name / "copyright"
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
    import importlib.metadata
    distributions = ["pyinstaller", "altgraph", "pyinstaller-hooks-contrib"]
    if not Path("/etc/fedora-release").exists():
        distributions += ["PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6"]
    for distribution in distributions:
        package = importlib.metadata.distribution(distribution)
        for file in package.files or []:
            if ("license" in str(file).lower() or "copying" in file.name.lower()) and ".." not in file.parts:
                path = Path(package.locate_file(file))
                if path.is_file():
                    destination = licenses / distribution / Path(str(file))
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, destination)
    (bundle / "RUN.txt").write_text(
        "TransferPC v1.0 — Linux x86_64 portable\n\n"
        "Extract the complete folder, then run ./transferpc.\n"
        "Keep _internal/ beside the executable. No app installation, root\n"
        "privileges, external Python or external PySide6 are required.\n"
        "Built on Ubuntu 22.04: requires Linux x86_64, glibc 2.35 or newer,\n"
        "OpenGL/EGL desktop libraries and a working desktop session.\n"
        "Targets Ubuntu 22.04+, modern Fedora and Manjaro/Arch.\n"
        "Shared LGPL libraries can be replaced inside _internal/.\n"
        "See LICENSE, THIRD_PARTY_NOTICES.md and licenses/ for notices.\n",
        encoding="utf-8")


def copy_rpm_notices(bundle: Path, licenses: Path) -> None:
    owners = {"python3-libs", "python3-pyside6", "python3-shiboken6"}
    search = (Path("/usr/lib64"), Path("/usr/lib"))
    for binary in (bundle / "_internal").rglob("*"):
        if not binary.is_file() or ".so" not in binary.name:
            continue
        candidates = [directory / binary.name for directory in search]
        candidates += list(Path("/usr/lib64/qt6").rglob(binary.name))
        for candidate in candidates:
            if candidate.is_file():
                owner = subprocess.run(["rpm", "-qf", "--qf", "%{NAME}", str(candidate)],
                                       capture_output=True, text=True)
                if owner.returncode == 0:
                    owners.add(owner.stdout)
                    break
    for owner in sorted(owners):
        files = subprocess.check_output(["rpm", "-ql", owner], text=True).splitlines()
        for name in files:
            path = Path(name)
            if path.is_file() and ("/licenses/" in name or path.name.lower().startswith(("license", "copying"))):
                destination = licenses / owner / path.relative_to("/usr")
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)


def archive_portable(bundle: Path) -> Path:
    output = OUTPUT / f"transferpc-{VERSION}-linux-x86_64-portable.tar.gz"
    with tarfile.open(output, "w:gz", format=tarfile.PAX_FORMAT) as archive:
        for path in (bundle, *sorted(bundle.rglob("*"))):
            info = archive.gettarinfo(str(path), arcname=str(path.relative_to(bundle.parent)))
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            info.mtime = 0
            if info.isfile():
                with path.open("rb") as reader:
                    archive.addfile(info, reader)
            else:
                archive.addfile(info)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portable-only", action="store_true",
                        help="Build the portable and Ubuntu/Manjaro packages in the Ubuntu container")
    arguments = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise SystemExit("This release builder targets Linux x86_64.")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("PYINSTALLER_CONFIG_DIR", str(BUILD / "pyinstaller-cache"))
    OUTPUT.mkdir(exist_ok=True)
    if not arguments.portable_only:
        run(sys.executable, "packaging/fedora/build_rpm.py")
        run("bash", "packaging/portable/build_container.sh")
        return
    if platform.libc_ver()[1] != "2.35":
        raise SystemExit("Build the compatible portable in the Ubuntu 22.04 container (glibc 2.35).")
    stage_portable()
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--distpath", str(BUILD / "portable"), "--workpath", str(BUILD / "pyinstaller"),
        "packaging/portable/transferpc.spec")
    bundle = BUILD / "portable" / f"TransferPC-{VERSION}"
    copy_notices(bundle)
    # Bytecode filenames are normalized by PyInstaller; scan all emitted bytes.
    for path in bundle.rglob("*"):
        if path.is_file():
            check_data(path.read_bytes())
    portable = archive_portable(bundle)
    from build_native import build_packages
    native = build_packages(bundle)
    artifacts = [*sorted(OUTPUT.glob(f"transferpc-{VERSION}-*.rpm")), portable, *native]
    sums = [f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in artifacts]
    (OUTPUT / "SHA256SUMS").write_text("".join(sums), encoding="utf-8")
    (OUTPUT / "TransferPC-v1.0-release.txt").write_text(RELEASE_NOTES, encoding="utf-8")
    for artifact in artifacts:
        print(artifact.name)


if __name__ == "__main__":
    main()
