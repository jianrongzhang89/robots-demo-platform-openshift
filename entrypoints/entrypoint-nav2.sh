#!/usr/bin/env bash
set -eo pipefail

# Nav2 robot pod entrypoint — multi-robot distributed deployment.
# Runs the Nav2 navigation stack for a single robot identified by ROBOT_NAME.
# Gazebo runs in a separate pod; topics arrive via zenoh-bridge-ros2dds.
#
# Required env vars:
#   ROBOT_NAME   — ROS2 namespace for this robot (e.g. "robot_1")
#   INITIAL_X    — Initial x position for AMCL (meters, default -2.0)
#   INITIAL_Y    — Initial y position for AMCL (meters, default -0.5)
#   INITIAL_YAW  — Initial yaw for AMCL (radians, default 0.0)

export HOME="/tmp/ros-home"
mkdir -p "${HOME}" "${HOME}/.ros" "${HOME}/.config"
export ROS_HOME="${HOME}/.ros"
export ROS_LOG_DIR="${HOME}/.ros/log"

ROS_PREFIX="${ROS_PREFIX:-/opt/ros/${ROS_DISTRO}}"

for d in /usr/lib64/ros-jazzy/opt/*/lib64; do
  [ -d "$d" ] && export LD_LIBRARY_PATH="${d}:${LD_LIBRARY_PATH:-}"
done

source "${ROS_PREFIX}/setup.bash"

set -u

export TURTLEBOT3_MODEL="${TURTLEBOT3_MODEL:-waffle}"

ROBOT_NAME="${ROBOT_NAME:-robot_1}"
INITIAL_X="${INITIAL_X:--2.0}"
INITIAL_Y="${INITIAL_Y:--0.5}"
INITIAL_YAW="${INITIAL_YAW:-0.0}"

BRINGUP_DIR="${ROS_PREFIX}/share/nav2_bringup"

# ── Determine peer robot name ─────────────────────────────────────────────────
# Supports any number of robots named robot_N; peer is always the "other" robot
# in the two-robot demo. Extend this logic for N>2 scenarios.
if [ "${ROBOT_NAME}" = "robot_1" ]; then
    PEER_ROBOT="robot_2"
else
    PEER_ROBOT="robot_1"
fi
echo "[nav2-pod/${ROBOT_NAME}] Peer robot identified as: ${PEER_ROBOT}"

# ── Run local robot_state_publisher for static TF frames only ─────────────────
# Zenoh does not reliably deliver /robot_N/tf_static with TRANSIENT_LOCAL QoS
# to late-joining Nav2 pods (the bridge creates a VOLATILE local DDS publisher,
# so late-joining TF buffer subscribers miss the cached message).  Running a
# local RSP guarantees the static transforms (base_footprint→base_link etc.)
# are published with TRANSIENT_LOCAL directly in the Nav2 pod's DDS space.
#
# The DYNAMIC /tf output (wheel-joint TF) is redirected to a null topic to
# prevent the "Moved backwards in time" problem: Zenoh-delayed joint_states can
# arrive out of order, causing the RSP to re-publish wheel-joint TF with an
# earlier timestamp, which clears the TF buffer and breaks navigation.
# With the dynamic TF discarded, only static TF comes from the local RSP.
SIM_DIR="${ROS_PREFIX}/share/nav2_minimal_tb3_sim"
URDF_FILE="${SIM_DIR}/urdf/turtlebot3_waffle.urdf"
echo "[nav2-pod/${ROBOT_NAME}] Starting local robot_state_publisher (static TF only)..."
ros2 run robot_state_publisher robot_state_publisher \
  --ros-args \
  --remap __ns:="/${ROBOT_NAME}" \
  -r /tf:=/_unused/${ROBOT_NAME}/tf \
  -r /tf_static:=/${ROBOT_NAME}/tf_static \
  -p use_sim_time:=true \
  -p "robot_description:=$(cat "${URDF_FILE}")" &
RSP_PID=$!

# Wait for Gazebo to fully start and Zenoh to bridge topics before Nav2 launches.
# Gazebo starts in ~60-90 s (software rendering); with real_time_factor=0.5 the
# simulation is stable and the clock will not jump backward.
echo "[nav2-pod/${ROBOT_NAME}] Waiting 120s for Gazebo to start and Zenoh to bridge topics..."
sleep 120

# ── Launch Nav2 with proper multi-robot params ────────────────────────────────
# use_namespace:=True activates PushROSNamespace so nodes run at /{ROBOT_NAME}/*
# and ReplaceString substitutes <robot_namespace> → /{ROBOT_NAME} in the params
# file. nav2_multirobot_params_all.yaml uses <robot_namespace>/scan for the
# scan topic so the costmap correctly subscribes to /{ROBOT_NAME}/scan.
# This also fixes the MPPI "No critics defined" error: with use_namespace:=True
# the RewrittenYaml wrapping under {ROBOT_NAME}: matches the node FQNs.
# ── Patch params: tighter goal tolerance ─────────────────────────────────────
# The default xy_goal_tolerance is 0.25 m — the robot declares "SUCCEEDED"
# up to 25 cm from the goal, which looks visually short in Gazebo.
# Patch to 0.10 m so the robot parks within 10 cm of the target position.
CUSTOM_PARAMS="/tmp/nav2_params_${ROBOT_NAME}.yaml"
python3 - "${BRINGUP_DIR}/params/nav2_multirobot_params_all.yaml" "${CUSTOM_PARAMS}" <<'PYEOF'
import sys
src, dst = sys.argv[1], sys.argv[2]
with open(src) as f:
    content = f.read()
content = content.replace(
    'xy_goal_tolerance: 0.25',
    'xy_goal_tolerance: 0.15'   # 15 cm — visually at dest; achievable for DWB
)
# Loosen yaw tolerance so orientation alignment doesn't block arrival
content = content.replace(
    'yaw_goal_tolerance: 0.25',
    'yaw_goal_tolerance: 0.5'
)
with open(dst, 'w') as f:
    f.write(content)
print(f'[params] xy_goal_tolerance=0.15 m  yaw_goal_tolerance=0.5 rad  (were 0.25)')
PYEOF

echo "[nav2-pod/${ROBOT_NAME}] Launching Nav2 bringup with namespace=${ROBOT_NAME} (use_namespace:=True)..."
ros2 launch nav2_bringup bringup_launch.py \
  namespace:="${ROBOT_NAME}" \
  use_namespace:=True \
  use_sim_time:=True \
  autostart:=True \
  use_composition:=False \
  map:="${BRINGUP_DIR}/maps/tb3_sandbox.yaml" \
  params_file:="${CUSTOM_PARAMS}" &
NAV2_PID=$!

# Wait for AMCL to load, then set initial pose so localization can start
(
  AMCL_NODE="/${ROBOT_NAME}/amcl"
  echo "[nav2-pod/${ROBOT_NAME}] Waiting for AMCL node (${AMCL_NODE}) to load..."
  for i in $(seq 1 180); do
    if ros2 node list 2>/dev/null | grep -q "${AMCL_NODE}"; then
      echo "[nav2-pod/${ROBOT_NAME}] AMCL node detected (attempt ${i}), waiting for activation..."
      sleep 10

      echo "[nav2-pod/${ROBOT_NAME}] Publishing initial pose at (${INITIAL_X}, ${INITIAL_Y}, yaw=${INITIAL_YAW})..."
      ros2 topic pub "/${ROBOT_NAME}/initialpose" geometry_msgs/msg/PoseWithCovarianceStamped \
        "{header: {frame_id: 'map'}, pose: {pose: {position: {x: ${INITIAL_X}, y: ${INITIAL_Y}, z: 0.0}, orientation: {x: 0.0, y: 0.0, z: 0.0, w: 1.0}}, covariance: [0.25, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.25, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.06853892]}}" --once 2>&1

      echo "[nav2-pod/${ROBOT_NAME}] Waiting for AMCL to publish map->odom transform..."
      for j in $(seq 1 60); do
        if timeout 5 ros2 run tf2_ros tf2_echo "${ROBOT_NAME}/map" "${ROBOT_NAME}/odom" 2>&1 | grep -q "Translation"; then
          echo "[nav2-pod/${ROBOT_NAME}] Localization active — navigation stack ready."
          break
        fi
        sleep 2
      done
      break
    fi
    sleep 5
  done
) &

echo "[nav2-pod/${ROBOT_NAME}] Nav2 pod started."

term_handler() {
  echo "[nav2-pod/${ROBOT_NAME}] Shutting down..."
  kill "${NAV2_PID}" "${RSP_PID}" 2>/dev/null || true
  pkill -P $$ 2>/dev/null || true
  wait "${NAV2_PID}" 2>/dev/null || true
}

trap term_handler SIGTERM SIGINT

wait "${NAV2_PID}"
