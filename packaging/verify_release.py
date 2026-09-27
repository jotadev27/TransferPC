"""Inspect release payloads, metadata and embedded Python code, then smoke-test."""
from __future__ import annotations

import hashlib
import io
import marshal
import os
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import types
import zipfile
from pathlib import Path

from audit_public import check_data
from PyInstaller.archive.readers import CArchiveReader

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "installer"


def inspect_code(code: types.CodeType) -> None:
    check_data(code.co_filename.encode())
    for constant in code.co_consts:
        if isinstance(constant, types.CodeType):
            inspect_code(constant)
        elif isinstance(constant, str):
            check_data(constant.encode())
        elif isinstance(constant, bytes):
            check_data(constant)


def inspect_executable(path: Path) -> None:
    archive = CArchiveReader(str(path))
    for name, entry in archive.toc.items():
        check_data(name.encode())
        kind = entry[-1]
        if kind == "s":
            inspect_code(marshal.loads(archive.extract(name)))
        elif kind == "z":
            modules = archive.open_embedded_archive(name)
            for module in modules.toc:
                value = modules.extract(module)
                if isinstance(value, types.CodeType):
                    inspect_code(value)


def inspect_cpio(data: bytes, destination: Path) -> None:
    cursor = 0
    files = 0
    while cursor + 110 <= len(data):
        header = data[cursor:cursor + 110]
        if header[:6] not in (b"070701", b"070702"):
            raise ValueError("Unexpected RPM payload format")
        size = int(header[54:62], 16)
        mode = int(header[14:22], 16)
        namesize = int(header[94:102], 16)
        name = data[cursor + 110:cursor + 110 + namesize - 1].decode()
        cursor = (cursor + 110 + namesize + 3) & ~3
        if name == "TRAILER!!!":
            break
        if name.startswith("/") or ".." in Path(name).parts:
            raise ValueError("Unsafe RPM path")
        check_data(name.encode())
        check_data(data[cursor:cursor + size])
        target = destination / name
        if stat.S_ISDIR(mode):
            target.mkdir(parents=True, exist_ok=True)
        elif stat.S_ISREG(mode):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data[cursor:cursor + size])
            target.chmod(mode & 0o777)
        else:
            raise ValueError("Unexpected special file in RPM payload")
        cursor = (cursor + size + 3) & ~3
        files += 1
    if not files:
        raise ValueError("Empty RPM payload")


def smoke_test(command: list[str]) -> None:
    environment = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    environment.pop("PYTHONPATH", None)
    # Run outside the checkout: a missing asset or source dependency must fail.
    with tempfile.TemporaryDirectory(prefix="transferpc-smoke-") as temporary:
        process = subprocess.Popen(command, cwd=temporary, env=environment,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.terminate()
            _, stderr = process.communicate(timeout=5)
            if b"Traceback" in stderr or b"Failed to execute" in stderr:
                raise RuntimeError("Release startup failed")
        else:
            _, stderr = process.communicate()
            raise RuntimeError(f"Release exited during startup: {process.returncode}; {stderr.decode(errors='replace')}")


def main() -> None:
    for line in (OUTPUT / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        path = OUTPUT / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Release checksum mismatch")
    rpm, = OUTPUT.glob("transferpc-1.0-*.rpm")
    metadata = subprocess.check_output(["rpm", "-qp", "--qf",
        "%{VERSION}\n%{LICENSE}\n%{PACKAGER}\n%{BUILDHOST}\n", str(rpm)])
    if metadata != b"1.0\nMIT\nTransferPC\nlocalhost\n":
        raise ValueError("Unexpected RPM identity or version")
    check_data(subprocess.check_output(["rpm", "-qp", "--xml", str(rpm)]))
    with tempfile.TemporaryDirectory(prefix="transferpc-rpm-") as temporary:
        extracted = Path(temporary)
        inspect_cpio(subprocess.check_output(["rpm2cpio", str(rpm)]), extracted)
        smoke_test([sys.executable, str(extracted / "usr/libexec/transferpc/launch.py")])
    portable = OUTPUT / "transferpc-1.0-linux-x86_64-portable.tar.gz"
    with tarfile.open(portable) as archive:
        for item in archive:
            if item.name.startswith("/") or ".." in Path(item.name).parts:
                raise ValueError("Unsafe portable path")
            if (item.uid, item.gid, item.uname, item.gname) != (0, 0, "root", "root"):
                raise ValueError("Portable contains local ownership metadata")
            check_data(item.name.encode())
            if item.isfile():
                data = archive.extractfile(item).read()
                check_data(data)
                if item.name.endswith("base_library.zip"):
                    with zipfile.ZipFile(io.BytesIO(data)) as library:
                        for member in library.namelist():
                            if member.endswith(".pyc"):
                                inspect_code(marshal.loads(library.read(member)[16:]))
        with tempfile.TemporaryDirectory(prefix="transferpc-release-") as temporary:
            archive.extractall(temporary, filter="data")
            executable = Path(temporary) / "TransferPC-1.0/transferpc"
            inspect_executable(executable)
            smoke_test([str(executable)])
            for binary in executable.parent.rglob("*"):
                if not binary.is_file() or binary.is_symlink():
                    continue
                with binary.open("rb") as stream:
                    if stream.read(4) != b"\x7fELF":
                        continue
                symbols = subprocess.check_output(["readelf", "--version-info", str(binary)])
                versions = [tuple(map(int, version.split(b".")))
                            for version in re.findall(rb"GLIBC_([0-9]+\.[0-9]+)", symbols)]
                if versions and max(versions) > (2, 35):
                    raise ValueError(f"Portable needs a newer glibc: {binary.name}")
    deb = OUTPUT / "transferpc_1.0-1_amd64.deb"
    members = subprocess.check_output(["ar", "t", str(deb)]).decode().splitlines()
    if members != ["debian-binary", "control.tar.gz", "data.tar.gz"]:
        raise ValueError("Unexpected Debian package members")
    control = subprocess.check_output(["ar", "p", str(deb), "control.tar.gz"])
    with tarfile.open(fileobj=io.BytesIO(control)) as archive:
        metadata = archive.extractfile("control").read()
        if b"Version: 1.0-1\n" not in metadata or b"Architecture: amd64\n" not in metadata:
            raise ValueError("Unexpected Debian package metadata")
        check_data(metadata)
    data = subprocess.check_output(["ar", "p", str(deb), "data.tar.gz"])
    verify_native_tar(data, compressed=True)
    arch = OUTPUT / "transferpc-1.0-1-x86_64.pkg.tar.zst"
    data = subprocess.check_output(["zstd", "-q", "-d", "-c", str(arch)])
    verify_native_tar(data, compressed=False)
    notes = (OUTPUT / "TransferPC-v1.0-release.txt").read_bytes()
    check_data(notes)
    if b"v1.0" not in notes or b"1.0.0" in notes:
        raise ValueError("Unexpected release-note version")
    print("Release audit passed: checksums, RPM/DEB/pacman payloads, metadata, ownership, embedded code, glibc 2.35 baseline and standalone startup.")


def verify_native_tar(data: bytes, compressed: bool) -> None:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz" if compressed else "r:") as archive:
        for item in archive:
            if item.name.startswith("/") or ".." in Path(item.name).parts:
                raise ValueError("Unsafe native package path")
            if (item.uid, item.gid, item.uname, item.gname) != (0, 0, "root", "root"):
                raise ValueError("Native package contains local ownership")
            check_data(item.name.encode())
            if item.isfile():
                contents = archive.extractfile(item).read()
                check_data(contents)
                if item.name == ".PKGINFO":
                    for field in (b"pkgver = 1.0-1\n", b"arch = x86_64\n", b"xdata = pkgtype=pkg\n"):
                        if field not in contents:
                            raise ValueError("Unexpected pacman metadata")
        with tempfile.TemporaryDirectory(prefix="transferpc-native-") as temporary:
            archive.extractall(temporary, filter="data")
            root = Path(temporary)
            inspect_executable(root / "opt/transferpc/transferpc")
            smoke_test([str(root / "opt/transferpc/transferpc")])


if __name__ == "__main__":
    main()
