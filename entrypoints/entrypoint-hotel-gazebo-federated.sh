#!/usr/bin/env bash
set -eo pipefail

# Open-RMF Hotel World — Federated Gazebo pod entrypoint.
#
# Runs ONLY the Gazebo simulation with slotcar robots, building, doors, and lifts.
# RMF fleet adapters and task dispatch run in a separate rmf-core pod.
# Communication via Zenoh federation.

export HOME="/tmp/ros-home"
mkdir -p "${HOME}" "${HOME}/.ros" "${HOME}/.config" "${HOME}/.gz"
export ROS_HOME="${HOME}/.ros"
export ROS_LOG_DIR="${HOME}/.ros/log"

source /opt/ros/jazzy/setup.bash
# Overlay A: rmf_ros2 (for building map server and lift/door plugins)
if [ -f /opt/rmf_ros2_ws/install/setup.bash ]; then
  source /opt/rmf_ros2_ws/install/setup.bash
fi
# Overlay B: rmf_demos (hotel world, building map)
if [ -f /opt/rmf_demos_ws/install/setup.bash ]; then
  source /opt/rmf_demos_ws/install/setup.bash
fi

export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export PYTHONFAULTHANDLER=1
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"

# CPU software rendering
export LIBGL_ALWAYS_SOFTWARE=1
export GALLIUM_DRIVER=llvmpipe

# Qt6 X11 platform
export QT_QPA_PLATFORM=xcb
export QT_X11_NO_MITSHM=1

# Gazebo model search path
export GZ_SIM_RESOURCE_PATH="/opt/gz-models:/opt/rmf_demos_ws/install/share/rmf_demos_assets/models"

WEB_PORT="${WEB_PORT:-8080}"
VNC_PORT="${VNC_PORT:-5900}"
NOVNC_PORT="${NOVNC_PORT:-6080}"
DISPLAY_NUM="${DISPLAY_NUM:-99}"
RESOLUTION="${RESOLUTION:-1600x900x24}"

export DISPLAY=":${DISPLAY_NUM}"

# --- 1. Display server ---
echo "[hotel-gazebo] Starting Xorg (dummy driver) on display ${DISPLAY}..."
Xorg "${DISPLAY}" -config /etc/X11/xorg-dummy.conf \
    -nolisten tcp -logfile /tmp/Xorg.${DISPLAY_NUM}.log &
XVFB_PID=$!
sleep 2

# --- 2. Window manager ---
echo "[hotel-gazebo] Starting openbox window manager..."
openbox &

# --- 3. VNC server ---
echo "[hotel-gazebo] Starting x11vnc on port ${VNC_PORT}..."
x11vnc -display "${DISPLAY}" -rfbport "${VNC_PORT}" -shared -forever -nopw -noxdamage -noscr &

# --- 4. noVNC web proxy ---
echo "[hotel-gazebo] Starting noVNC on port ${NOVNC_PORT}..."
websockify --web /usr/share/novnc "${NOVNC_PORT}" "localhost:${VNC_PORT}" &

# --- 5. Web landing page ---
echo "[hotel-gazebo] Starting web landing page on port ${WEB_PORT}..."
python3 -m http.server "${WEB_PORT}" --directory /opt/ros2-demo/www &

# --- 6. Launch Gazebo simulation only ---
# We launch ONLY the simulation components:
#   - Gazebo with hotel world
#   - Slotcar robots
#   - Building (doors, lifts)
#   - Building map server (for visualization)
#   - Door/lift supervisor plugins (they run in Gazebo)
#
# We do NOT launch:
#   - Fleet adapters (run in rmf-core pod)
#   - Traffic schedule (run in rmf-core pod)
#   - Task dispatcher (run in rmf-core pod)

echo "[hotel-gazebo] Launching hotel simulation (Gazebo + building map server)..."

# Start building map server (publishes /map for visualization)
ros2 run rmf_building_map_tools building_map_server \
  /opt/rmf_demos_ws/install/share/rmf_demos_maps/maps/hotel/hotel.building.yaml \
  --ros-args -p use_sim_time:=true &

# Start Gazebo with hotel world
# The hotel world SDF includes:
#   - Building structure (3 levels)
#   - Slotcar robots (deliveryBot_1, tinyBot_1, cleanerBotA_1, cleanerBotA_2)
#   - Door and lift plugins
ros2 launch rmf_demos_gz simulation.launch.xml \
  world_name:=hotel \
  headless:=False \
  use_sim_time:=True &
LAUNCH_PID=$!

echo ""
echo "=================================================="
echo " Hotel Gazebo (Federated) Running"
echo "  Gazebo simulation + slotcar robots"
echo "  DDS domain : ${ROS_DOMAIN_ID}"
echo "  noVNC      : port ${NOVNC_PORT}"
echo ""
echo " RMF fleet adapters run in separate rmf-core pod"
echo " Connected via Zenoh federation"
echo "=================================================="

term_handler() {
  echo "[hotel-gazebo] Shutting down..."
  kill "${LAUNCH_PID:-}" "${XVFB_PID:-}" 2>/dev/null || true
  pkill -P $$ 2>/dev/null || true
  wait "${LAUNCH_PID}" 2>/dev/null || true
}
trap term_handler SIGTERM SIGINT

wait "${LAUNCH_PID}"
