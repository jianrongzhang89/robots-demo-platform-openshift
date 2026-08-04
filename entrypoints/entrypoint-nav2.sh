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

echo "[nav2-pod/${ROBOT_NAME}] Starting robot_state_publisher (URDF-based static TF publisher)..."
URDF=$(cat /usr/lib64/ros-jazzy/share/nav2_minimal_tb3_sim/urdf/turtlebot3_waffle.urdf)
ros2 run robot_state_publisher robot_state_publisher \
  --ros-args -p robot_description:="${URDF}" &
RSP_PID=$!

echo "[nav2-pod/${ROBOT_NAME}] Starting nav2 RMF relay (pub/sub bridge for navigate_to_pose)..."
python3 /nav2_relay.py &
NAV_RELAY_PID=$!

echo "[nav2-pod/${ROBOT_NAME}] Clock delivered directly via bridge (robot_N/clock -> /clock, same as main branch)."
CLOCK_ROS_RELAY_PID=""
TF_HEARTBEAT_PID=""

echo "[nav2-pod/${ROBOT_NAME}] Launching Nav2 bringup (no ROS namespace — isolation via Zenoh)..."
# Patch nav2_params.yaml with MPPI tuning for the tb3_sandbox pillar grid.
NAV2_PARAMS="${BRINGUP_DIR}/params/nav2_params.yaml"
CUSTOM_PARAMS="/tmp/nav2_params_${ROBOT_NAME}.yaml"
if [ -f "${NAV2_PARAMS}" ]; then
  python3 -c "
import yaml, sys
with open('${NAV2_PARAMS}') as f:
    p = yaml.safe_load(f) or {}
cs = p.setdefault('controller_server', {}).setdefault('ros__parameters', {})

# ── MPPI tuning for tb3_sandbox (tight pillar corridors, RTF=0.5) ──────────
fp = cs.setdefault('FollowPath', {})
# allow_reversing=True so MPPI can compute valid paths through tight pillar grid.
# PreferForwardCritic (weight=5.0 below) discourages backward motion instead.
fp['allow_reversing'] = True
fp['time_steps'] = 15              # short horizon: better for tight spaces (default 56)
fp['batch_size'] = 2000            # more trajectories for complex environments (default 1000)
fp['temperature'] = 0.3            # default 0.3 — keep moderate exploration
fp['gamma'] = 0.015                # default 0.015
fp['vx_max'] = 0.26                # match sandbox speed limit
fp['vx_min'] = 0.0                 # no reverse
fp['wz_max'] = 1.5                 # allow faster turning in narrow passages (default 1.9)
fp['prune_distance'] = 0.8         # shorter look-back for plan pruning (default 1.7)
fp['model_dt'] = 0.05              # simulation timestep (default 0.05)

# Critic weights tuned for the pillar maze:
# - Higher PathFollow: stay closer to the global plan (avoids getting stuck)
# - Lower Obstacles: allow passing closer to pillars when plan requires it
# - Enable PathAlign for direction following
fp.setdefault('PathFollowCritic', {}).update({
    'enabled': True, 'cost_weight': 5.0, 'cost_power': 1  # default 2.0
})
fp.setdefault('PathAlignCritic', {}).update({
    'enabled': True, 'cost_weight': 14.0,  # default 14.0 — keep
    'trajectory_point_step': 4, 'threshold_to_consider': 0.4
})
fp.setdefault('ObstaclesCritic', {}).update({
    'enabled': True, 'cost_weight': 1.5,   # reduce from default 2.0
    'inflation_layer_name': 'InflationLayer'
})
fp.setdefault('CostCritic', {}).update({
    'enabled': True, 'cost_weight': 3.81,  # default 3.81 — keep
    'cost_power': 1, 'collision_cost': 1e4, 'critical_cost': 300.0
})
fp.setdefault('GoalCritic', {}).update({
    'enabled': True, 'cost_weight': 5.0, 'threshold_to_consider': 1.0
})
fp.setdefault('GoalAngleCritic', {}).update({
    'enabled': True, 'cost_weight': 3.0, 'threshold_to_consider': 0.4
})
fp.setdefault('PreferForwardCritic', {}).update({
    'enabled': True, 'cost_weight': 5.0   # stronger forward preference
})

# ── Progress checker: lenient for slow RTF=0.5 sim ──────────────────────────
pc = cs.setdefault('progress_checker', {})
pc['plugin'] = 'nav2_controller::SimpleProgressChecker'
pc['required_movement_radius'] = 0.05  # 5 cm minimum movement
pc['movement_time_allowance'] = 60.0   # 60 sim-s = 120 wall-s allowance

# ── Costmap tuning: reduce inflation so robots can pass through pillar gaps ─
# Default inflation_radius=0.55m blocks the ~0.5m gaps between pillars.
# Reduce to 0.20m so there is free space between pillars for the MPPI.
# The nav2_params.yaml has double nesting: local_costmap.local_costmap.ros__parameters
for top_key in ['local_costmap', 'global_costmap']:
    inner_key = top_key  # e.g. 'local_costmap'
    cmap_params = p.setdefault(top_key, {}).setdefault(inner_key, {}).setdefault('ros__parameters', {})
    cmap_params.setdefault('inflation_layer', {})['inflation_radius'] = 0.20
    cmap_params.setdefault('inflation_layer', {})['cost_scaling_factor'] = 5.0

with open('${CUSTOM_PARAMS}', 'w') as f:
    yaml.dump(p, f, default_flow_style=False)
print('[nav2-pod] Patched nav2 params: MPPI tuned for tb3_sandbox pillars')
" 2>/dev/null && PARAMS_ARG="params_file:=${CUSTOM_PARAMS}" || PARAMS_ARG=""
else
  PARAMS_ARG=""
fi

ros2 launch nav2_bringup bringup_launch.py \
  use_sim_time:=True \
  autostart:=True \
  use_composition:=False \
  map:="${BRINGUP_DIR}/maps/tb3_sandbox.yaml" \
  ${PARAMS_ARG} &
NAV2_PID=$!

# Wait for AMCL to load, then set initial pose so localization can start.
# Nav2 bringup with namespace may register the node as /amcl (short) or
# /${ROBOT_NAME}/amcl (full) depending on the version — check both.
(
  echo "[nav2-pod/${ROBOT_NAME}] Waiting for AMCL node to load..."
  for i in $(seq 1 180); do
    if ros2 node list 2>/dev/null | grep -qE "^(/amcl|/${ROBOT_NAME}/amcl)$"; then
      echo "[nav2-pod/${ROBOT_NAME}] AMCL node detected (attempt ${i}), waiting for activation..."
      # Wait 45s: AMCL needs time to configure+activate its lifecycle, during which
      # the TF buffer may clear several times due to sim-clock jumps after Gazebo
      # restarts. 45s covers the typical worst-case activation window.
      sleep 45
      # Increase transform_tolerance on AMCL and costmaps.
      # Zenoh bridges the sim clock at ~1350 Hz; occasional out-of-order delivery
      # causes tf2 "jump back in time" buffer clears. High transform_tolerance lets
      # costmaps survive the brief gaps and attempt activation successfully.
      timeout 8 ros2 param set /amcl transform_tolerance 10.0 2>/dev/null || true
      timeout 8 ros2 param set /local_costmap/local_costmap transform_tolerance 10.0 2>/dev/null || true
      timeout 8 ros2 param set /global_costmap/global_costmap transform_tolerance 10.0 2>/dev/null || true
      # Large yaw tolerance: RMF waypoint approach requires a specific final yaw
      # (~π rad), but the traffic manager verifies orientation separately.
      # Setting yaw_goal_tolerance=π lets Nav2 declare the waypoint reached on
      # position alone without requiring a long in-place rotation.
      timeout 8 ros2 param set /controller_server general_goal_checker.yaw_goal_tolerance 3.14159 2>/dev/null || true

      echo "[nav2-pod/${ROBOT_NAME}] Publishing initial pose at (${INITIAL_X}, ${INITIAL_Y}, yaw=${INITIAL_YAW})..."
      # Compute quaternion from yaw: qz=sin(yaw/2), qw=cos(yaw/2) (qx=qy=0 for planar)
      read -r INITIAL_QZ INITIAL_QW < <(python3 -c \
        "import math; y=${INITIAL_YAW}; print(math.sin(y/2), math.cos(y/2))")
      # Publish initial pose — use --times 10 instead of --once so the message
      # is sent even if AMCL's /initialpose subscriber isn't ready yet. AMCL
      # will receive one of the 10 publications once it activates.
      ros2 topic pub "/initialpose" geometry_msgs/msg/PoseWithCovarianceStamped \
        "{header: {frame_id: 'map'}, pose: {pose: {position: {x: ${INITIAL_X}, y: ${INITIAL_Y}, z: 0.0}, orientation: {x: 0.0, y: 0.0, z: ${INITIAL_QZ}, w: ${INITIAL_QW}}}, covariance: [0.01, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.01, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.01]}}" \
        --times 10 2>/dev/null || true

      echo "[nav2-pod/${ROBOT_NAME}] Waiting for AMCL to publish map->odom transform..."
      for j in $(seq 1 60); do
        if timeout 5 ros2 run tf2_ros tf2_echo "map" "odom" 2>&1 | grep -q "Translation"; then
          echo "[nav2-pod/${ROBOT_NAME}] Localization active — navigation stack ready."
          break
        fi
        sleep 2
      done

      # Monitor navigation lifecycle and retry if activation failed.
      # Uses action server availability (more reliable than lifecycle get which times out).
      # Continuous watchdog: re-activates navigation whenever bt_navigator goes inactive.
      # Uses navigate_to_pose action server availability — more reliable than lifecycle get
      # which times out and incorrectly shows nodes as inactive even when they're active.
      # TF instability from clock jumps can cause controller_server to fail internally,
      # which the lifecycle manager then propagates to deactivate bt_navigator.
      # cmd_vel keepalive is embedded in nav2_relay.py as a daemon thread
      # (more reliable than a separate shell background process).
      echo "[nav2-pod/${ROBOT_NAME}] cmd_vel keepalive: running inside nav2_relay.py"
      KEEPALIVE_PID=""

      echo "[nav2-pod/${ROBOT_NAME}] Starting navigation watchdog (continuous monitoring)..."
      while true; do
        sleep 10

        # Keepalive is embedded in nav2_relay.py (daemon thread) — no restart needed.
        # Check bt_navigator lifecycle — call RESUME if INACTIVE
        BT_STATE=$(timeout 3 ros2 lifecycle get /bt_navigator 2>/dev/null | grep -oE "[a-z]+ \[[0-9]+\]" | head -1)
        if echo "${BT_STATE}" | grep -q "active"; then
          : # Nav2 active — no action needed
        else
          echo "[nav2-pod/${ROBOT_NAME}] bt_navigator not active (${BT_STATE}), calling RESUME..."
          timeout 90 ros2 service call /lifecycle_manager_navigation/manage_nodes \
            nav2_msgs/srv/ManageLifecycleNodes "{command: 2}" 2>/dev/null || true
        fi
      done
      break
    fi
    sleep 5
  done
) &

echo "[nav2-pod/${ROBOT_NAME}] Nav2 pod started."

term_handler() {
  echo "[nav2-pod/${ROBOT_NAME}] Shutting down..."
  kill "${NAV2_PID}" "${TF_HEARTBEAT_PID:-}" "${NAV_RELAY_PID:-}" "${CLOCK_ROS_RELAY_PID:-}" "${RSP_PID:-}" "${KEEPALIVE_PID:-}" 2>/dev/null || true
  pkill -P $$ 2>/dev/null || true
  wait "${NAV2_PID}" 2>/dev/null || true
}

trap term_handler SIGTERM SIGINT

wait "${NAV2_PID}"
