# Build from the explicit, sanitized payload prepared by build_release.py.
from pathlib import Path

root = Path(SPECPATH).resolve().parents[1]
source = root / "build" / "portable-source"
a = Analysis(
    [str(source / "launch.py")],
    pathex=[str(source)],
    binaries=[],
    datas=[(str(source / "assets"), "assets")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "unittest", "PySide6.QtNetwork",
              "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtWebEngineCore",
              "PySide6.QtWebEngineWidgets", "PySide6.QtSql"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="transferpc",
          debug=False, bootloader_ignore_signals=False, strip=False,
          upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="TransferPC-1.0")
