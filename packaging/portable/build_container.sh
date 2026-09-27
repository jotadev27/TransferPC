#!/usr/bin/env bash
set -euo pipefail
project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
mkdir -p "$project_root/build" "$project_root/installer"
mkdir -p "$project_root/build/qt-license-texts"
for license_name in LGPL-3.0-only.txt GPL-3.0-only.txt BSD-3-Clause.txt Apache-2.0.txt Qt-GPL-exception-1.0.txt; do
  cp "/usr/share/licenses/python3-pyside6/$license_name" "$project_root/build/qt-license-texts/$license_name"
done
podman run --rm --security-opt label=disable \
  -v "$project_root:/project:ro" \
  -v "$project_root/build:/project/build:rw" \
  -v "$project_root/installer:/project/installer:rw" \
  -w /project docker.io/library/ubuntu:22.04 \
  bash /project/packaging/portable/container_build.sh
