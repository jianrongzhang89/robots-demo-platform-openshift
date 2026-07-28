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

# ── Tune stuck-recovery parameters ───────────────────────────────────────────
# With real_time_factor=0.5 the stock defaults are far too slow for a demo:
#   movement_time_allowance=10 sim-s  → 20 real-s before stuck is detected
#   BackUp speed=0.025 m/s           → 12 real-s to back off 0.15 m
# We patch the installed params file and recovery BT XML at startup so no
# image rebuild is needed when tuning these values.

CUSTOM_PARAMS="/tmp/nav2_params_${ROBOT_NAME}.yaml"
CUSTOM_BT_DIR="/tmp/nav2_bt"
CUSTOM_BT_XML="${CUSTOM_BT_DIR}/fast_recovery.xml"
mkdir -p "${CUSTOM_BT_DIR}"

# 1. Patch the BT XML: faster BackUp (0.15 m/s over 0.30 m = 4 real-s vs 12).
#    Use Python for robust XML attribute editing.
DEFAULT_BT="${ROS_PREFIX}/share/nav2_bt_navigator/behavior_trees/navigate_to_pose_w_replanning_and_recovery.xml"
python3 - "${DEFAULT_BT}" "${CUSTOM_BT_XML}" <<'PYEOF'
import sys
import xml.etree.ElementTree as ET

src, dst = sys.argv[1], sys.argv[2]
ET.register_namespace('', '')
tree = ET.parse(src)
for node in tree.iter('BackUp'):
    node.set('backup_dist', '0.30')   # was 0.15 m
    node.set('backup_speed', '0.15')  # was 0.025 m/s — 6× faster
with open(dst, 'wb') as f:
    tree.write(f, encoding='utf-8', xml_declaration=True)
print(f'[tune] BackUp: dist=0.30 m  speed=0.15 m/s  (written to {dst})')
PYEOF

# 2. Patch the params file: faster stuck detection + point to custom BT XML.
#    Text substitution preserves the original YAML format exactly (avoids the
#    yaml.dump re-serialisation issue that broke param loading earlier).
python3 - "${BRINGUP_DIR}/params/nav2_multirobot_params_all.yaml" \
           "${CUSTOM_PARAMS}" "${CUSTOM_BT_XML}" <<'PYEOF'
import sys, re

src, dst, bt_xml = sys.argv[1], sys.argv[2], sys.argv[3]
with open(src) as f:
    content = f.read()

# Reduce stuck-detection window: 10 sim-s → 3 sim-s (= 6 real-s at ×0.5).
content = content.replace(
    'movement_time_allowance: 10.0',
    'movement_time_allowance: 3.0'
)

# Point bt_navigator to the faster-recovery BT XML.
# Use the 'navigators:' key as anchor — it is unique to the bt_navigator
# section, so this replacement cannot accidentally hit waypoint_follower
# (which also has action_server_result_timeout: 900.0).
content = content.replace(
    '    navigators: ["navigate_to_pose", "navigate_through_poses"]',
    f'    default_nav_to_pose_bt_xml: "{bt_xml}"\n'
    '    navigators: ["navigate_to_pose", "navigate_through_poses"]'
)

with open(dst, 'w') as f:
    f.write(content)
print(f'[tune] movement_time_allowance: 3.0 sim-s  BT XML: {bt_xml}')
print(f'[tune] Custom params written to {dst}')
PYEOF

# ── Launch Nav2 with proper multi-robot params ────────────────────────────────
# use_namespace:=True activates PushROSNamespace so nodes run at /{ROBOT_NAME}/*
# and ReplaceString substitutes <robot_namespace> → /{ROBOT_NAME} in the params
# file. nav2_multirobot_params_all.yaml uses <robot_namespace>/scan for the
# scan topic so the costmap correctly subscribes to /{ROBOT_NAME}/scan.
# This also fixes the MPPI "No critics defined" error: with use_namespace:=True
# the RewrittenYaml wrapping under {ROBOT_NAME}: matches the node FQNs.
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
