#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
export XDG_CACHE_HOME=/tmp/transferpc-build-cache
export QT_QPA_PLATFORM=offscreen
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$XDG_CACHE_HOME"
apt-get update
apt-get install -y --no-install-recommends python3 python3-venv libpython3.10 binutils \
  zstd rpm libglib2.0-0 libgl1 libegl1 libdbus-1-3 libxkbcommon0 libxcb-cursor0 \
  libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 \
  libxcb-xinerama0 libxcb-xkb1 libxkbcommon-x11-0 libfontconfig1
python3 -m venv /tmp/transferpc-venv
/tmp/transferpc-venv/bin/python -m pip install --no-cache-dir \
  'PyInstaller==6.22.3' 'PySide6==6.11.2'
/tmp/transferpc-venv/bin/python -m unittest discover -s tests -q
/tmp/transferpc-venv/bin/python packaging/build_release.py --portable-only
/tmp/transferpc-venv/bin/python packaging/verify_release.py
apt-get install -y /project/installer/transferpc_1.0-1_amd64.deb
test -f /usr/share/applications/transferpc.desktop
set +e
QT_QPA_PLATFORM=offscreen timeout 3 transferpc
startup_status=$?
set -e
test "$startup_status" -eq 124
apt-get remove -y transferpc
test ! -e /opt/transferpc/transferpc
printf '%s\n' 'DEB installation, startup and removal passed in the Ubuntu container.'
