#!/bin/sh
#
# Entrypoint for Gazebo Harmonic with Multi-Level Hotel World (2.5D)
# Launches hotel_multilevel_2d.sdf world
#

set -e

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

export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
export RCUTILS_CONSOLE_OUTPUT_FORMAT="[{severity} {time}] [{name}]: {message}"
export RCUTILS_LOGGING_USE_STDOUT=1
export RCUTILS_LOGGING_BUFFERED_STREAM=1

# Gazebo environment
export GZ_SIM_RESOURCE_PATH="/usr/lib64/ros-jazzy/share/nav2_minimal_tb3_sim/models:/opt/ros2-demo/gz_models:/opt/ros2-demo/worlds"
export GZ_SIM_SYSTEM_PLUGIN_PATH="/usr/lib64/ros-jazzy/opt/gz_sim_vendor/lib64/gz-sim-8/plugins"

# Select world file
WORLD_FILE="${WORLD_FILE:-/opt/ros2-demo/worlds/hotel_multilevel_2d.sdf}"

echo "=================================================="
echo "Multi-Level Hotel World - Gazebo Harmonic"
echo "=================================================="
echo ""
echo "Configuration:"
echo "  World: ${WORLD_FILE}"
echo "  Domain ID: ${ROS_DOMAIN_ID}"
echo "  RMW: ${RMW_IMPLEMENTATION}"
echo ""
echo "Layout: 2.5D (3 floors arranged horizontally)"
echo "  L1 (Lobby):  X=[5, 45]   Y=[10, 50]"
echo "  L2 (Rooms):  X=[65, 105] Y=[10, 50]"
echo "  L3 (Suites): X=[125, 165] Y=[10, 50]"
echo "=================================================="
echo ""

# Start Xvfb
Xvfb :99 -screen 0 1024x768x24 &
XVFB_PID=$!
export DISPLAY=:99

# Start VNC server
x11vnc -display :99 -forever -shared -rfbport 5900 &
VNC_PID=$!

# Start noVNC
/usr/bin/websockify --web=/usr/share/novnc/ 6080 localhost:5900 &
NOVNC_PID=$!

# Start window manager
openbox &
WM_PID=$!

sleep 2

# Launch Gazebo with ROS bridge
echo "Launching Gazebo Harmonic..."
gz sim "${WORLD_FILE}" -r -v 4 &
GZ_PID=$!

# Wait for Gazebo to be ready
echo "Waiting for Gazebo to be ready..."
for i in $(seq 1 60); do
  if gz topic -l 2>/dev/null | grep -q "/world/hotel_multilevel/"; then
    echo "Gazebo ready after $((i * 2))s"
    break
  fi
  sleep 2
done

# Spawn robots from ROBOTS environment variable
ROBOTS="${ROBOTS:-robot-1:20:30:0:0,0,1 robot-2:10:30:0:1,0,0}"
SIM_DIR="${ROS_PREFIX}/share/nav2_minimal_tb3_sim"
URDF_FILE="${SIM_DIR}/urdf/turtlebot3_waffle.urdf"
BASE_SDF="${SIM_DIR}/urdf/gz_waffle.sdf.xacro"

echo "Spawning robots: ${ROBOTS}"
for spec in ${ROBOTS}; do
  IFS=: read -r rname rx ry ryaw rcolor <<< "${spec}"
  rcolor="${rcolor:-1,1,1}"
  diffuse="$(echo "${rcolor}" | tr ',' ' ')"

  # Generate color-patched SDF for this robot
  PATCHED_SDF="/tmp/${rname}_waffle.sdf.xacro"
  python3 -c "
content = open('${BASE_SDF}').read()
content = content.replace('<diffuse>1 1 1</diffuse>', '<diffuse>${diffuse}</diffuse>')
open('${PATCHED_SDF}', 'w').write(content)
"
  echo "  Spawning ${rname} at (${rx}, ${ry}, yaw=${ryaw})..."
  ros2 launch nav2_minimal_tb3_sim spawn_tb3.launch.py \
    use_sim_time:=True \
    namespace:="${rname}" \
    robot_name:="${rname}" \
    x_pose:="${rx}" \
    y_pose:="${ry}" \
    z_pose:=0.01 \
    yaw_pose:="${ryaw}" \
    robot_sdf:="${PATCHED_SDF}" &

  # Robot state publisher per robot
  ros2 run robot_state_publisher robot_state_publisher \
    --ros-args \
    --remap __ns:=/"${rname}" \
    --remap /tf:=/"${rname}"/tf \
    --remap /tf_static:=/"${rname}"/tf_static \
    -p use_sim_time:=true \
    -p "robot_description:=$(cat "${URDF_FILE}")" &
done

sleep 3

# Launch ROS-Gazebo bridges (one per robot)
echo "Launching ROS-Gazebo bridges..."

for spec in ${ROBOTS}; do
  IFS=: read -r ROBOT_NAME rx ry ryaw rcolor <<< "${spec}"

  echo "  Bridging ${ROBOT_NAME}..."

  ros2 run ros_gz_bridge parameter_bridge \
    /world/hotel_multilevel/model/${ROBOT_NAME}/cmd_vel@geometry_msgs/msg/Twist@gz.msgs.Twist \
    /world/hotel_multilevel/model/${ROBOT_NAME}/odometry@nav_msgs/msg/Odometry@gz.msgs.Odometry \
    /world/hotel_multilevel/model/${ROBOT_NAME}/scan@sensor_msgs/msg/LaserScan@gz.msgs.LaserScan \
    /world/hotel_multilevel/model/${ROBOT_NAME}/tf@tf2_msgs/msg/TFMessage@gz.msgs.Pose_V \
    /clock@rosgraph_msgs/msg/Clock@gz.msgs.Clock \
    --ros-args -p use_sim_time:=true -r __ns:=/${ROBOT_NAME} &
done

echo ""
echo "✅ Gazebo multi-level world ready"
echo "   VNC: http://localhost:6080"
echo ""

# Cleanup handler
term_handler() {
  echo ""
  echo "[Gazebo] Shutting down..."
  kill "${GZ_PID}" "${XVFB_PID}" "${VNC_PID}" "${NOVNC_PID}" "${WM_PID}" 2>/dev/null || true
  for i in $(seq 1 $ROBOT_COUNT); do
    BRIDGE_PID_VAR="BRIDGE_${i}_PID"
    kill $(eval echo \$${BRIDGE_PID_VAR}) 2>/dev/null || true
  done
  pkill -P $$ 2>/dev/null || true
  wait 2>/dev/null || true
  echo "[Gazebo] Shutdown complete"
}
trap term_handler TERM INT

# Wait for Gazebo
while true; do
  if ! kill -0 "${GZ_PID}" 2>/dev/null; then
    echo "ERROR: Gazebo exited!"
    exit 1
  fi
  sleep 10
done
