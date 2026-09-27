#!/usr/bin/env bash
set -euo pipefail
# Run only inside the disposable Ubuntu container.
if [[ ! -f /run/.containerenv && ! -f /.dockerenv ]]; then
  printf '%s\n' 'Run this check inside a disposable container only.' >&2
  exit 1
fi
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y /release/transferpc_1.0-1_amd64.deb
dpkg-query -W transferpc
test -f /usr/share/applications/transferpc.desktop
test -f /opt/transferpc/licenses/Qt/LGPL-3.0-only.txt
set +e
QT_QPA_PLATFORM=offscreen timeout 3 transferpc
startup_status=$?
set -e
test "$startup_status" -eq 124
apt-get remove -y transferpc
test ! -e /opt/transferpc/transferpc
printf '%s\n' 'DEB installation, startup and removal passed in the Ubuntu container.'
