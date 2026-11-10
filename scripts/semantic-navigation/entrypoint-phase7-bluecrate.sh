#!/usr/bin/env bash
set -Eeuo pipefail

original=/entrypoint-semantic-navigation-phase1.sh
patched=/tmp/entrypoint-phase7-bluecrate.sh
python3 - "$original" "$patched" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1]).read_text()
marker = 'export GZ_SIM_RESOURCE_PATH='
if source.count(marker) != 1:
    raise SystemExit("unexpected simulator entrypoint; refusing to patch")
inject = (
    'case "${SEMANTIC_PHASE7_BLUE_CRATE:-present}" in\n'
    '  present) scene_mode= ;;\n'
    '  absent) scene_mode=--metadata-only ;;\n'
    '  *) echo "SEMANTIC_PHASE7_BLUE_CRATE must be present or absent" >&2; exit 2 ;;\n'
    'esac\n'
    'python3 /opt/phase7-capture/patch_phase7_blue_crate.py "${WORLD}" '
    '--metadata /phase7-data/blue-crate-geometry.json ${scene_mode}\n'
)
Path(sys.argv[2]).write_text(source.replace(marker, inject + marker))
PY

exec /bin/bash "$patched"
