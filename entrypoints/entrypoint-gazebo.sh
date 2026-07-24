#!/usr/bin/env bash
set -eo pipefail

# Gazebo simulation pod entrypoint — multi-robot distributed deployment.
# Spawns N robots from the ROBOTS env var, runs ros_gz_bridge per robot,
# and serves the Gazebo GUI over noVNC.
#
# ROBOTS format: space-separated "name:x:y:yaw:r,g,b" tuples, e.g.:
#   ROBOTS="robot_1:-2.0:-0.5:0.0:0,0,1 robot_2:2.0:0.5:3.14159:1,0,0"
# The r,g,b color (0-1 range) is applied to all robot visuals via a patched SDF xacro.
# Omit color or use "1,1,1" for the default white.

export HOME="/tmp/ros-home"
mkdir -p "${HOME}" "${HOME}/.ros" "${HOME}/.gazebo" "${HOME}/.config" "${HOME}/.gz/sim/8"
export ROS_HOME="${HOME}/.ros"
export ROS_LOG_DIR="${HOME}/.ros/log"

if [ -f /etc/gz/sim/8/server.config ]; then
  cp /etc/gz/sim/8/server.config "${HOME}/.gz/sim/8/server.config"
fi

ROS_PREFIX="${ROS_PREFIX:-/opt/ros/${ROS_DISTRO}}"

for d in /usr/lib64/ros-jazzy/opt/*/lib64; do
  [ -d "$d" ] && export LD_LIBRARY_PATH="${d}:${LD_LIBRARY_PATH:-}"
done

source "${ROS_PREFIX}/setup.bash"

set -u

export TURTLEBOT3_MODEL="${TURTLEBOT3_MODEL:-waffle}"
export GZ_SIM_RESOURCE_PATH="${ROS_PREFIX}/share:${ROS_PREFIX}/share/nav2_minimal_tb3_sim/models:${GZ_SIM_RESOURCE_PATH:-}"

if nvidia-smi &>/dev/null; then
  echo "[gazebo-pod] NVIDIA GPU detected, configuring GPU rendering..."
  export __NV_PRIME_RENDER_OFFLOAD=1
  export __GLX_VENDOR_LIBRARY_NAME=nvidia
  GPU_AVAILABLE=true
else
  echo "[gazebo-pod] No GPU detected, using software rendering..."
  export LIBGL_ALWAYS_SOFTWARE=1
  export GALLIUM_DRIVER=llvmpipe
  GPU_AVAILABLE=false
fi

WEB_PORT="${WEB_PORT:-8080}"
VNC_PORT="${VNC_PORT:-5900}"
NOVNC_PORT="${NOVNC_PORT:-6080}"
WORLD_NAME="${WORLD_NAME:-tb3_sandbox}"
DISPLAY_NUM="${DISPLAY_NUM:-99}"
RESOLUTION="${RESOLUTION:-1280x720x24}"

# Space-separated "name:x:y:yaw:r,g,b" robot definitions
ROBOTS="${ROBOTS:-robot_1:-2.0:-0.5:0.0:1,1,1}"

export DISPLAY=":${DISPLAY_NUM}"

# --- 1. Virtual framebuffer ---
if [ "${GPU_AVAILABLE}" = "true" ]; then
  export __EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json
fi
echo "[gazebo-pod] Starting Xvfb on display ${DISPLAY} at ${RESOLUTION}..."
Xvfb "${DISPLAY}" -screen 0 "${RESOLUTION}" +extension GLX +render -noreset &
XVFB_PID=$!
unset __EGL_VENDOR_LIBRARY_FILENAMES
sleep 2

# --- 2. Window manager ---
echo "[gazebo-pod] Starting openbox window manager..."
openbox &

# --- 3. VNC server ---
echo "[gazebo-pod] Starting x11vnc on port ${VNC_PORT}..."
x11vnc -display "${DISPLAY}" -rfbport "${VNC_PORT}" -shared -forever -nopw -noxdamage -noscr &

# --- 4. noVNC web proxy ---
echo "[gazebo-pod] Starting noVNC on port ${NOVNC_PORT}..."
websockify --web /usr/share/novnc "${NOVNC_PORT}" "localhost:${VNC_PORT}" &

# --- 5. Web landing page ---
echo "[gazebo-pod] Starting web landing page on port ${WEB_PORT}..."
python3 -m http.server "${WEB_PORT}" --directory /opt/ros2-demo/www &

# --- 6. Process world xacro and start Gazebo server ---
WORLD_SDF="/tmp/ros-home/world.sdf"

echo "[gazebo-pod] Processing world xacro..."
xacro -o "${WORLD_SDF}" "headless:=True" \
  "/opt/ros2-demo/worlds/tb3_sandbox.sdf.xacro"

echo "[gazebo-pod] Starting Gazebo server..."
gz sim -r -s "${WORLD_SDF}" &
GZ_SERVER_PID=$!

# --- 7. Wait for Gazebo to be ready ---
echo "[gazebo-pod] Waiting for Gazebo server to start..."
for i in $(seq 1 60); do
  if gz topic -l 2>/dev/null | grep -q "/world/${WORLD_NAME}/"; then
    echo "[gazebo-pod] Gazebo server detected after $((i * 2))s"
    break
  fi
  sleep 2
done

# --- 8. Spawn all robots ---
SIM_DIR="${ROS_PREFIX}/share/nav2_minimal_tb3_sim"
URDF_FILE="${SIM_DIR}/urdf/turtlebot3_waffle.urdf"
BASE_SDF="${SIM_DIR}/urdf/gz_waffle.sdf.xacro"

echo "[gazebo-pod] Spawning robots: ${ROBOTS}"
SPAWN_PIDS=()
for spec in ${ROBOTS}; do
  IFS=: read -r rname rx ry ryaw rcolor <<< "${spec}"
  rcolor="${rcolor:-1,1,1}"
  # Convert comma-separated r,g,b to space-separated for SDF diffuse tag
  diffuse="$(echo "${rcolor}" | tr ',' ' ')"

  # Generate a color-patched SDF xacro for this robot
  PATCHED_SDF="/tmp/${rname}_waffle.sdf.xacro"
  python3 -c "
content = open('${BASE_SDF}').read()
content = content.replace('<diffuse>1 1 1</diffuse>', '<diffuse>${diffuse}</diffuse>')
open('${PATCHED_SDF}', 'w').write(content)
"
  echo "[gazebo-pod] Spawning ${rname} at (${rx}, ${ry}, yaw=${ryaw}) color=(${diffuse})..."
  ros2 launch nav2_minimal_tb3_sim spawn_tb3.launch.py \
    use_sim_time:=True \
    namespace:="${rname}" \
    robot_name:="${rname}" \
    x_pose:="${rx}" \
    y_pose:="${ry}" \
    z_pose:=0.01 \
    robot_sdf:="${PATCHED_SDF}" &
  SPAWN_PIDS+=($!)

  # robot_state_publisher per robot — remap /tf to /robot_N/tf so the Gazebo
  # zenoh bridge routes it as "robot_N/tf" in Zenoh (what the Nav2 bridge and
  # free_fleet_adapter subscribe to under the robot namespace).
  ros2 run robot_state_publisher robot_state_publisher \
    --ros-args \
    --remap __ns:=/"${rname}" \
    --remap /tf:=/"${rname}"/tf \
    --remap /tf_static:=/"${rname}"/tf_static \
    -p use_sim_time:=true \
    -p "robot_description:=$(cat "${URDF_FILE}")" &
done

# --- 9. Launch Gazebo GUI client for visualization ---
echo "[gazebo-pod] Waiting before launching Gazebo GUI..."
for i in $(seq 1 30); do
  if gz topic -l 2>/dev/null | grep -q "/world/${WORLD_NAME}/"; then
    gz sim -g &
    GZ_GUI_PID=$!
    echo "[gazebo-pod] Gazebo GUI launched."
    break
  fi
  sleep 2
done

# --- 10. Per-robot clock relay ---
# The Gazebo zenoh bridge routes /clock as bare Zenoh "clock".
# Each Nav2 pod's bridge (namespace=/robot_N) expects "robot_N/clock".
# Relay re-publishes /clock as /robot_N/clock so Nav2 use_sim_time works.
echo "[gazebo-pod] Starting per-robot clock relays..."
CLOCK_RELAY_SCRIPT="$(cat <<'PYEOF'
import sys, rclpy
from rclpy.node import Node
from rosgraph_msgs.msg import Clock
robot = sys.argv[1]
rclpy.init()
n = Node('clock_relay_' + robot.replace('_',''))
pub = n.create_publisher(Clock, '/' + robot + '/clock', 10)
n.create_subscription(Clock, '/clock', pub.publish, 10)
rclpy.spin(n)
PYEOF
)"
for spec in ${ROBOTS}; do
  IFS=: read -r rname rx ry ryaw rcolor <<< "${spec}"
  python3 -c "${CLOCK_RELAY_SCRIPT}" "${rname}" &
  echo "[gazebo-pod] Clock relay started for ${rname}"
done

echo "[gazebo-pod] All ${#SPAWN_PIDS[@]} robot(s) spawned. Simulation ready."

term_handler() {
  echo "[gazebo-pod] Shutting down..."
  kill "${GZ_GUI_PID:-}" "${SPAWN_PIDS[@]:-}" "${GZ_SERVER_PID}" "${XVFB_PID}" 2>/dev/null || true
  pkill -P $$ 2>/dev/null || true
  wait "${GZ_SERVER_PID}" 2>/dev/null || true
}

trap term_handler SIGTERM SIGINT

wait "${GZ_SERVER_PID}"
