#!/usr/bin/env bash
set -Eeuo pipefail

original=/entrypoint-semantic-navigation-phase1.sh
patched=/tmp/entrypoint-semantic-navigation-phase7.sh

python3 - "$original" "$patched" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1]).read_text()
camera_marker = 'export GZ_SIM_RESOURCE_PATH='
urdf_source = 'robot_description:="$(< /opt/ros2-demo/robot/turtlebot3_waffle.urdf)"'
plugin_path = 'export GZ_SIM_SYSTEM_PLUGIN_PATH="/opt/ros/jazzy/opt/gz_sim_vendor/lib/gz-sim-8/plugins:${GZ_SIM_SYSTEM_PLUGIN_PATH:-}"'
if (source.count(camera_marker) != 1 or source.count(urdf_source) != 1 or
        source.count(plugin_path) != 1):
    raise SystemExit('unexpected simulator entrypoint; refusing to patch')

prepare = '''python3 - <<'PHASE7_ASSETS'
from pathlib import Path
from prepare_assets import prepare

world = Path("/tmp/semantic-navigation/hotel.world")
urdf = Path("/opt/ros2-demo/robot/turtlebot3_waffle.urdf")
patched_world, patched_urdf = prepare(world.read_text(), urdf.read_text())
world.write_text(patched_world)
Path("/tmp/semantic-navigation/robot.urdf").write_text(patched_urdf)
PHASE7_ASSETS
'''
source = source.replace(camera_marker, prepare + camera_marker)
source = source.replace(urdf_source,
    'robot_description:="$(< /tmp/semantic-navigation/robot.urdf)"')
source = source.replace(plugin_path,
    'export GZ_SIM_SYSTEM_PLUGIN_PATH="/opt/ros/jazzy/opt/gz_sim_vendor/lib/gz-sim-8/plugins:/opt/phase7-native/lib:${GZ_SIM_SYSTEM_PLUGIN_PATH:-}"')
Path(sys.argv[2]).write_text(source)
PY

exec /bin/bash "$patched"
