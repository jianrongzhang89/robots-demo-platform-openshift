#!/usr/bin/env bash
set -eo pipefail

# Open-RMF Hotel World demo — single-pod entrypoint.
#
# Runs the FULL upstream hotel demo in one container on a single localhost DDS
# domain (no Zenoh, no separate Nav2 pods):
#   Gazebo (slotcar robots + lift/door plugins), RMF building map server,
#   door + lift supervisors, traffic schedule, task dispatcher, and 3
#   full_control fleet adapters (TinyRobot, cleanerBotA, DeliveryRobot).
#
# The Gazebo GUI (and RViz) render into an Xvfb virtual display exposed to the
# browser over noVNC — same visualization scaffold as entrypoint-gazebo.sh.
#
# Tunables (env):
#   HOTEL_LAUNCH_PKG   launch package               (default: rmf_demos_gz)
#   HOTEL_LAUNCH_FILE  launch file                  (default: hotel.launch.xml)
#   HOTEL_LAUNCH_ARGS  extra "key:=value" launch args passed verbatim
#   DISPLAY_NUM        Xvfb display number          (default: 99)
#   RESOLUTION         Xvfb resolution              (default: 1600x900x24)

export HOME="/tmp/ros-home"
mkdir -p "${HOME}" "${HOME}/.ros" "${HOME}/.config" "${HOME}/.gz"
export ROS_HOME="${HOME}/.ros"
export ROS_LOG_DIR="${HOME}/.ros/log"

# Auto-detect ROS distro (use env var if set, otherwise find available distro)
if [ -z "${ROS_DISTRO}" ]; then
  for distro in lyrical jazzy humble; do
    if [ -f "/opt/ros/${distro}/setup.bash" ]; then
      export ROS_DISTRO="${distro}"
      break
    fi
  done
fi
echo "[hotel-pod] Detected ROS distro: ${ROS_DISTRO}"
source /opt/ros/${ROS_DISTRO}/setup.bash
# Overlay A: rmf_ros2 (source-built librmf_fleet_adapter.so matching ROS2 API)
if [ -f /opt/rmf_ros2_ws/install/setup.bash ]; then
  source /opt/rmf_ros2_ws/install/setup.bash
fi
# Overlay B: rmf_demos (hotel world, launch files, building map)
if [ -f /opt/rmf_demos_ws/install/setup.bash ]; then
  source /opt/rmf_demos_ws/install/setup.bash
fi

export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export PYTHONFAULTHANDLER=1   # print Python stack on SIGSEGV
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"

# GPU rendering required for gpu_lidar sensor
# NOTE: Requires OpenShift nodes with GPU support
# export LIBGL_ALWAYS_SOFTWARE=1
# export GALLIUM_DRIVER=llvmpipe

# Force Qt6 to use the X11 (xcb) platform plugin on Ubuntu 24.04.
# Without this, Qt6 tries Wayland first; with no Wayland compositor in the
# container, it falls back to offscreen/EGL rendering that never composites
# into the X framebuffer, leaving the noVNC display black.
export QT_QPA_PLATFORM=xcb
export QT_X11_NO_MITSHM=1

# Gazebo model search path. simulation.launch.xml appends the hotel/models dir
# (hotel_L1/L2/L3) automatically. We add:
#   /opt/gz-models      — Open-RMF/ wrapper for Fuel-style model://Open-RMF/X URIs
#   rmf_demos_assets    — robot SDFs (TinyRobot, CleanerBotA, DeliveryRobot)
export GZ_SIM_RESOURCE_PATH="/opt/gz-models:/opt/rmf_demos_ws/install/share/rmf_demos_assets/models"

WEB_PORT="${WEB_PORT:-8080}"
VNC_PORT="${VNC_PORT:-5900}"
NOVNC_PORT="${NOVNC_PORT:-6080}"
API_PORT="${API_PORT:-8000}"
DASHBOARD_PORT="${DASHBOARD_PORT:-3000}"
DISPLAY_NUM="${DISPLAY_NUM:-99}"
RESOLUTION="${RESOLUTION:-1600x900x24}"
HOTEL_LAUNCH_PKG="${HOTEL_LAUNCH_PKG:-rmf_demos_gz}"
HOTEL_LAUNCH_FILE="${HOTEL_LAUNCH_FILE:-hotel.launch.xml}"
HOTEL_LAUNCH_ARGS="${HOTEL_LAUNCH_ARGS:-}"

export DISPLAY=":${DISPLAY_NUM}"

# --- 1. Display server (Xorg + dummy driver) ---
# Xvfb uses direct DRI rendering that bypasses the X framebuffer, so OpenGL
# content (RViz2, Gazebo) is invisible to x11vnc/VNC. Xorg with the dummy
# video driver uses a shared-memory framebuffer that OpenGL properly composites
# into, making it visible over VNC.
echo "[hotel-pod] Starting Xorg (dummy driver) on display ${DISPLAY}..."
Xorg "${DISPLAY}" -config /etc/X11/xorg-dummy.conf \
    -nolisten tcp -logfile /tmp/Xorg.${DISPLAY_NUM}.log &
XVFB_PID=$!
sleep 2

# --- 2. Window manager ---
echo "[hotel-pod] Starting openbox window manager..."
openbox &

# --- 3. VNC server ---
echo "[hotel-pod] Starting x11vnc on port ${VNC_PORT}..."
x11vnc -display "${DISPLAY}" -rfbport "${VNC_PORT}" -shared -forever -nopw -noxdamage -noscr &

# --- 4. noVNC web proxy ---
echo "[hotel-pod] Starting noVNC on port ${NOVNC_PORT}..."
websockify --web /usr/share/novnc "${NOVNC_PORT}" "localhost:${VNC_PORT}" &

# --- 5. Web landing page ---
echo "[hotel-pod] Starting web landing page on port ${WEB_PORT}..."
python3 -m http.server "${WEB_PORT}" --directory /opt/ros2-demo/www &

# --- 6. Optional rmf-web API server + dashboard ---
if python3 -c "import api_server" 2>/dev/null; then
  echo "[hotel-pod] Starting rmf-web API server on port ${API_PORT}..."
  ( cd /opt/rmf-web/packages/api-server && python3 -m api_server ) &
  API_PID=$!
  echo "[hotel-pod] Serving fleet dashboard on port ${DASHBOARD_PORT}..."
  ( cd /opt/rmf-dashboard && python3 -m http.server "${DASHBOARD_PORT}" 2>/dev/null ) &
  DASHBOARD_PID=$!
else
  echo "[hotel-pod] rmf-web api_server not available — skipping dashboard (Gazebo GUI over noVNC remains)."
  API_PID=""
  DASHBOARD_PID=""
fi

# --- 6b. Puppet controller: drives robots via fleet_manager HTTP when
#         librmf_fleet_adapter EasyFullControl C++ crashes on task execution.
#         Monitors /dispatch_states, sends navigate() to fleet_manager REST API. ---
python3 /entrypoints/rmf_puppet_controller.py &

# --- 6d. Publish the 'map' TF root frame ---
# The RMF visualization topics (fleet_markers, floorplan, building_systems_markers)
# all publish with frame_id='map'. Without a 'map' TF frame in the TF tree,
# RViz2 cannot resolve the coordinate frame and shows empty panels.
# This static_transform_publisher makes 'map' a root anchor frame.
ros2 run tf2_ros static_transform_publisher \
    --x 0 --y 0 --z 0 --roll 0 --pitch 0 --yaw 0 \
    --frame-id map --child-frame-id rmf_building \
    --ros-args -p use_sim_time:=true &

# --- 6e. Fix Gazebo GUI RCL context crash ---
# Remove problematic GUI plugins that try to access ROS2 before context is initialized.
# The toggle_floors and toggle_charging plugins cause "failed to create guard condition"
# RCL errors when Gazebo GUI loads. Copy world file to /tmp, patch it, and point
# GZ_SIM_RESOURCE_PATH to the patched version.
echo "[hotel-pod] Patching hotel.world to fix GUI plugin RCL crash..."
HOTEL_WORLD_SRC=$(find /opt/rmf_demos_ws -name "hotel.world" -type f | head -1)
if [ -n "${HOTEL_WORLD_SRC}" ] && [ -f "${HOTEL_WORLD_SRC}" ]; then
  # Copy to writable location
  mkdir -p /tmp/hotel_world_patched/maps/hotel
  HOTEL_WORLD="/tmp/hotel_world_patched/maps/hotel/hotel.world"
  cp "${HOTEL_WORLD_SRC}" "${HOTEL_WORLD}"
  echo "[hotel-pod] Copied world file to ${HOTEL_WORLD}"

  # Use Python for reliable multi-line XML patching
  python3 - "${HOTEL_WORLD}" <<'PATCHEOF'
import re, sys
world_file = sys.argv[1]
with open(world_file, "r") as f:
    content = f.read()

# Remove toggle_charging plugin (single line)
content = re.sub(
    r'<plugin filename="toggle_charging"[^/]*/?>',
    '<!-- DISABLED: RCL crash fix - <plugin filename="toggle_charging" .../> -->',
    content
)

# Remove toggle_floors plugin (multi-line block)
content = re.sub(
    r'<plugin name="toggle_floors".*?</plugin>',
    '<!-- DISABLED: RCL crash fix\n      <plugin name="toggle_floors">...</plugin>\n      -->',
    content,
    flags=re.DOTALL
)

with open(world_file, "w") as f:
    f.write(content)
print(f"[patch] Disabled toggle_charging and toggle_floors plugins in {world_file}")
PATCHEOF
  echo "[hotel-pod] GUI plugins patched successfully"
  # Prepend patched world directory to GZ_SIM_RESOURCE_PATH so Gazebo finds it first
  export GZ_SIM_RESOURCE_PATH="/tmp/hotel_world_patched:${GZ_SIM_RESOURCE_PATH}"
  echo "[hotel-pod] Updated GZ_SIM_RESOURCE_PATH to use patched world"
else
  echo "[hotel-pod] WARNING: hotel.world not found, GUI may crash"
fi

# --- 7. Launch the full hotel demo ---
echo "[hotel-pod] Launching Open-RMF hotel demo:"
echo "            ros2 launch ${HOTEL_LAUNCH_PKG} ${HOTEL_LAUNCH_FILE} ${HOTEL_LAUNCH_ARGS}"
# shellcheck disable=SC2086
ros2 launch "${HOTEL_LAUNCH_PKG}" "${HOTEL_LAUNCH_FILE}" ${HOTEL_LAUNCH_ARGS} &
LAUNCH_PID=$!

# --- 7b. TurtleBot3 robot pre-spawned in world file ---
# NOTE: Robot is pre-spawned in hotel.world at build time
# Using Bullet physics engine (DART 6.13.2 has continuous joint DOF=0 bug, TPE has no joint support)
if [ "${SPAWN_TURTLEBOT3:-false}" = "true" ]; then
  echo "[hotel-pod] TurtleBot3 robot_1 pre-spawned in world file at (10, 30)"
  echo "[hotel-pod] Bullet-Featherstone physics + continuous wheel joints enabled"
else
  echo "[hotel-pod] TurtleBot3 spawning disabled (using slotcar robots from launch file)"
fi

echo ""
echo "=================================================="
echo " Open-RMF Hotel World running (single pod)"
echo "  DDS domain : ${ROS_DOMAIN_ID} (localhost only)"
echo "  noVNC      : port ${NOVNC_PORT}"
echo "  Dashboard  : port ${DASHBOARD_PORT} (if enabled)"
echo ""
echo " Dispatch a multi-level patrol (L1 -> L3 via lift):"
echo "   ros2 run rmf_demos_tasks dispatch_patrol \\"
echo "     -p L3_room1 L3_room1 -n 1 --use_sim_time"
echo "=================================================="

term_handler() {
  echo "[hotel-pod] Shutting down..."
  kill "${LAUNCH_PID:-}" "${API_PID:-}" "${DASHBOARD_PID:-}" "${XVFB_PID:-}" 2>/dev/null || true
  pkill -P $$ 2>/dev/null || true
  wait "${LAUNCH_PID}" 2>/dev/null || true
}
trap term_handler SIGTERM SIGINT

wait "${LAUNCH_PID}"
