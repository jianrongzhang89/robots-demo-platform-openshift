#!/bin/sh
#
# Entrypoint for RMF pod in Multi-Level Nav2 + Free Fleet architecture
#
# Runs RMF fleet management with multi-level support:
#   - RMF Traffic Schedule
#   - RMF Task Dispatcher
#   - Building Map Server (multi-level topology)
#   - Lift Supervisor (coordinates lift requests)
#   - Free Fleet Server (coordinates Nav2 robots)
#   - (Optional) rmf-web API server + dashboard
#
# Nav2 robots run in separate pods with Free Fleet Clients.
# Communication via Zenoh federation.
#

set -e

export HOME="/tmp/ros-home"
mkdir -p "${HOME}" "${HOME}/.ros" "${HOME}/.config"
export ROS_HOME="${HOME}/.ros"
export ROS_LOG_DIR="${HOME}/.ros/log"

# Source ROS2 environment
. /opt/ros/jazzy/setup.sh

# Source Free Fleet if installed
if [ -f /opt/free_fleet_ws/install/setup.sh ]; then
  . /opt/free_fleet_ws/install/setup.sh
fi

if [ -f /opt/rmf_demos_ws/install/setup.sh ]; then
  . /opt/rmf_demos_ws/install/setup.sh
fi

# ROS configuration
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-55}"  # Separate from Nav2/Gazebo domain 0
export PYTHONFAULTHANDLER=1

# Enable debug logging for RMF bidding investigation
export RCUTILS_CONSOLE_OUTPUT_FORMAT="[{severity} {time}] [{name}]: {message}"
export RCUTILS_LOGGING_USE_STDOUT=1
export RCUTILS_LOGGING_BUFFERED_STREAM=1

# Service ports
API_PORT="${API_PORT:-8000}"
DASHBOARD_PORT="${DASHBOARD_PORT:-3000}"
# Disable web server requirement for Free Fleet - not compatible with Jazzy
SERVER_URI="${SERVER_URI:-}"

# Building and navigation configuration
BUILDING_CONFIG="${BUILDING_CONFIG:-/opt/hotel_config/hotel.building.yaml}"
NAV_GRAPH="${NAV_GRAPH:-/opt/rmf_config/hotel_nav_graph_enhanced.yaml}"

# Zenoh configuration for Free Fleet
ZENOH_CONFIG="${ZENOH_CONFIG:-/opt/free_fleet_zenoh_config/free-fleet-client.json5}"

echo "=================================================="
echo "RMF Pod - Multi-Level Free Fleet Architecture"
echo "=================================================="
echo ""
echo "Configuration:"
echo "  DDS Domain: ${ROS_DOMAIN_ID}"
echo "  RMW: ${RMW_IMPLEMENTATION}"
echo "  API Port: ${API_PORT}"
echo "  Dashboard Port: ${DASHBOARD_PORT}"
echo "  Building Config: ${BUILDING_CONFIG}"
echo "  Nav Graph: ${NAV_GRAPH}"
echo "  Zenoh Config: ${ZENOH_CONFIG}"
echo ""

# --- Publish 'map' TF root frame ---
echo "Publishing map TF frame..."
ros2 run tf2_ros static_transform_publisher \
    --x 0 --y 0 --z 0 --roll 0 --pitch 0 --yaw 0 \
    --frame-id map --child-frame-id rmf_building \
    --ros-args -p use_sim_time:=true &
TF_PID=$!

# --- Launch AMCL Pose to TF Republisher (optional) ---
if [ -f /opt/free_fleet_scripts/amcl_pose_to_tf.py ]; then
  echo "Launching AMCL Pose to TF republisher..."
  python3 /opt/free_fleet_scripts/amcl_pose_to_tf.py &
  TF_REPUB_PID=$!
else
  echo "AMCL Pose to TF republisher not found (optional component)"
  TF_REPUB_PID=""
fi

# --- Publish Namespaced Map Frames for Free Fleet (optional) ---
if [ -f /opt/free_fleet_scripts/publish_namespaced_map_frames.py ]; then
  echo "Publishing namespaced map frames (tinyBot_X/map → map)..."
  python3 /opt/free_fleet_scripts/publish_namespaced_map_frames.py &
  NAMESPACED_MAP_PID=$!
else
  echo "Namespaced map frames publisher not found (optional component)"
  NAMESPACED_MAP_PID=""
fi

# --- Launch RMF Traffic Schedule ---
echo "Launching RMF traffic schedule..."
ros2 run rmf_traffic_ros2 rmf_traffic_schedule \
  --ros-args -p use_sim_time:=true &
TRAFFIC_PID=$!

sleep 3

# --- Launch Building Map Server ---
echo "Launching Building Map Server for multi-level coordination..."
BUILDING_CONFIG="${BUILDING_CONFIG:-/opt/hotel_config/hotel.building.yaml}"
if [ -f "${BUILDING_CONFIG}" ]; then
  ros2 run rmf_building_map_tools building_map_server \
    "${BUILDING_CONFIG}" \
    --ros-args -p use_sim_time:=true &
  BUILDING_MAP_PID=$!
  echo "  ✅ Building map loaded from: ${BUILDING_CONFIG}"
else
  echo "  ⚠️  Building config not found: ${BUILDING_CONFIG}"
  BUILDING_MAP_PID=""
fi

# --- Launch Lift Supervisor ---
# Coordinates lift requests between RMF and Gazebo lift plugins
echo "Launching lift supervisor for multi-level coordination..."
ros2 run rmf_lift_ros2 rmf_lift_supervisor \
  --ros-args -p use_sim_time:=true &
LIFT_SUPERVISOR_PID=$!
echo "  ✅ Lift supervisor running (PID ${LIFT_SUPERVISOR_PID})"

sleep 2

# --- Launch RMF Task Dispatcher ---
echo "Launching RMF task dispatcher..."
# Use ROS parameters (not command-line args) to match rmf_demos official launch
# Critical parameters from rmf_demos/launch/common.launch.xml:
#   - bidding_time_window: Time window for bidding process (default: 2.0)
#   - use_unique_hex_string_with_task_id: Append unique hex to task IDs (default: true)
#   - server_uri: API server URI (default: "")
echo "  Dispatcher configuration:"
echo "    - bidding_time_window: 2.0 seconds"
echo "    - use_unique_hex_string_with_task_id: true"
echo "    - server_uri: ${SERVER_URI:-}"
ros2 run rmf_task_ros2 rmf_task_dispatcher \
  --ros-args \
  -p use_sim_time:=true \
  -p bidding_time_window:=2.0 \
  -p use_unique_hex_string_with_task_id:=true \
  -p server_uri:="${SERVER_URI:-}" \
  --log-level rmf_task_ros2:=DEBUG &
DISPATCHER_PID=$!

sleep 3

# --- Launch Free Fleet Adapter ---
echo "Launching Free Fleet Adapter for tinyRobot fleet..."
NAV_GRAPH="${NAV_GRAPH:-/opt/rmf_config/hotel_nav_graph_enhanced.yaml}"
if [ -f "${NAV_GRAPH}" ]; then
  # Build fleet adapter command with consistent parameters
  FLEET_CMD="ros2 run free_fleet_adapter fleet_adapter.py"
  FLEET_CMD="${FLEET_CMD} -c /opt/free_fleet_config/tinybot_fleet_config.yaml"
  FLEET_CMD="${FLEET_CMD} -n ${NAV_GRAPH}"
  FLEET_CMD="${FLEET_CMD} -sim"

  # Add server_uri if provided (matches rmf_demos fleet_adapter configuration)
  if [ -n "${SERVER_URI}" ]; then
    FLEET_CMD="${FLEET_CMD} -s ${SERVER_URI}"
    echo "  Server URI: ${SERVER_URI}"
  fi

  # Add Zenoh config if available
  if [ -f "${ZENOH_CONFIG}" ]; then
    FLEET_CMD="${FLEET_CMD} --zenoh-config ${ZENOH_CONFIG}"
    echo "  Zenoh config: ${ZENOH_CONFIG}"
  fi

  # Add ROS args
  FLEET_CMD="${FLEET_CMD} --ros-args -p use_sim_time:=true --log-level rmf_fleet_adapter:=INFO"

  echo "  Launching fleet adapter..."
  eval ${FLEET_CMD} &
  FREE_FLEET_PID=$!
  echo "  ✅ Free Fleet adapter running (PID ${FREE_FLEET_PID})"
  echo "  📍 Nav graph: ${NAV_GRAPH}"
else
  echo "  ❌ ERROR: Nav graph not found: ${NAV_GRAPH}"
  exit 1
fi

sleep 3

# --- Nav2 Puppet Controller ---
# DISABLED: Free Fleet adapter handles Nav2 control directly
# The puppet controller was a workaround that's no longer needed
echo "Nav2 Puppet Controller disabled (Free Fleet handles Nav2 control)"
PUPPET_PID=""

sleep 2

# --- rmf-web API server (optional) ---
# DISABLED: rmf-web has Tortoise ORM incompatibility causing pod crashes
# The multi-level demo doesn't need the web interface
echo "rmf-web dashboard disabled (not required for this demo)"
API_PID=""
DASHBOARD_PID=""

echo ""
echo "===================================================================="
echo "🏨 RMF MULTI-LEVEL NAVIGATION - READY"
echo "===================================================================="
echo ""
echo "✅ Core RMF Components:"
echo "  📡 RMF Traffic Schedule: PID ${TRAFFIC_PID}"
if [ -n "${BUILDING_MAP_PID}" ]; then
echo "  🏢 Building Map Server: PID ${BUILDING_MAP_PID}"
fi
if [ -n "${LIFT_SUPERVISOR_PID}" ]; then
echo "  🛗 Lift Supervisor: PID ${LIFT_SUPERVISOR_PID}"
fi
echo "  📋 RMF Task Dispatcher: PID ${DISPATCHER_PID}"
echo ""
echo "✅ Fleet Control:"
echo "  🤖 Free Fleet Adapter: PID ${FREE_FLEET_PID}"
echo "  📍 TF Publisher (map→rmf_building): PID ${TF_PID}"
echo ""
echo "✅ Navigation Infrastructure:"
echo "  🗺️  Nav Graph: ${NAV_GRAPH}"
echo "  🏗️  Building: ${BUILDING_CONFIG}"
echo ""
echo "🚀 Fleet: tinyRobot (4 robots with Nav2)"
echo "📍 Levels: L1 (Lobby), L2, L3"
echo "🛗 Lifts: Lift1, Lift2 (RMF coordinated)"
echo "🔗 Federation: Zenoh bridge (Domain 55 ↔ Domain 0)"
echo "===================================================================="

# Cleanup handler
term_handler() {
  echo ""
  echo "[RMF] Shutting down multi-level navigation system..."
  kill "${TRAFFIC_PID:-}" "${BUILDING_MAP_PID:-}" "${LIFT_SUPERVISOR_PID:-}" \
       "${DISPATCHER_PID:-}" "${FREE_FLEET_PID:-}" "${PUPPET_PID:-}" \
       "${TF_PID:-}" "${TF_REPUB_PID:-}" "${NAMESPACED_MAP_PID:-}" \
       "${API_PID:-}" "${DASHBOARD_PID:-}" 2>/dev/null || true
  pkill -P $$ 2>/dev/null || true
  wait 2>/dev/null || true
  echo "[RMF] Shutdown complete"
}
trap term_handler TERM INT

# Wait for main processes (keep container running)
while true; do
  if ! kill -0 "${TRAFFIC_PID}" 2>/dev/null; then
    echo "ERROR: RMF Traffic Schedule exited!"
    exit 1
  fi
  if ! kill -0 "${DISPATCHER_PID}" 2>/dev/null; then
    echo "ERROR: RMF Task Dispatcher exited!"
    exit 1
  fi
  sleep 10
done
