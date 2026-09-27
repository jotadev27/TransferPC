#!/usr/bin/env bash
set -euo pipefail
# Run only inside the disposable Arch container, not on the maintainer's host.
if [[ ! -f /run/.containerenv && ! -f /.dockerenv ]]; then
  printf '%s\n' 'Run this check inside a disposable container only.' >&2
  exit 1
fi
pacman -Syu --noconfirm
pacman -U --noconfirm /release/transferpc-1.0-1-x86_64.pkg.tar.zst
pacman -Q transferpc
test -f /usr/share/applications/transferpc.desktop
test -f /opt/transferpc/licenses/Qt/LGPL-3.0-only.txt
set +e
QT_QPA_PLATFORM=offscreen timeout 3 transferpc
startup_status=$?
set -e
test "$startup_status" -eq 124
pacman -R --noconfirm transferpc
test ! -e /opt/transferpc/transferpc
printf '%s\n' 'Pacman installation, startup and removal passed in the Arch container.'
