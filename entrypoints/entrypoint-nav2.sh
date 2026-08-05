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

# ── Switch to Regulated Pure Pursuit (RPP) controller.
# DWB's multi-critic trajectory sampling creates local scoring minima in the
# tb3_sandbox pillar grid where ALL sampled trajectories score comparably,
# resulting in zero velocity output. RPP avoids this entirely: it computes a
# single "carrot" lookahead point on the global path and drives toward it,
# producing forward velocity unconditionally as long as the path is clear.
fp = cs.setdefault('FollowPath', {})
fp['plugin'] = 'nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController'
fp['desired_linear_vel'] = 0.22         # m/s — slightly below max for stability
fp['lookahead_dist'] = 0.6             # m — longer carrot: less curvature near pillars
fp['min_lookahead_dist'] = 0.3         # m
fp['max_lookahead_dist'] = 0.9         # m
fp['lookahead_time'] = 1.5             # s — time-based lookahead fallback
fp['rotate_to_heading_angular_vel'] = 0.8   # rad/s — heading correction rate
fp['transform_tolerance'] = 0.2
fp['use_velocity_scaled_lookahead_dist'] = False  # fixed lookahead in tight gaps
fp['min_approach_linear_velocity'] = 0.05   # m/s — don't slow to zero near goal
fp['approach_velocity_scaling_dist'] = 1.0  # m — start slowing 1m from goal
fp['use_collision_detection'] = False
# Collision detection disabled: RPP's forward-check uses local costmap (0.10m
# inflation), flagging the robot footprint (r=0.22m) as colliding with pillar
# inflation zones even though the global path is physically navigable (pillar
# gaps are 0.80m, robot width is 0.44m). The global planner with 0.15m
# inflation already ensures paths avoid physical pillars — RPP just follows.
fp['use_regulated_linear_velocity_scaling'] = True   # slow near obstacles
fp['use_fixed_curvature_lookahead'] = False
fp['regulated_linear_scaling_min_radius'] = 0.9  # m
fp['regulated_linear_scaling_min_speed'] = 0.25  # keep moving even when scaling
fp['use_rotate_to_heading'] = False     # no in-place rotation; continuous steering
fp['allow_reversing'] = False           # forward only
fp['max_angular_accel'] = 3.2          # rad/s²
fp['max_robot_pose_search_dist'] = 10.0  # m — wide search for closest path point
# Accept any final yaw — RMF sends nav_graph waypoint orientations which
# may differ from robot's current heading by up to pi radians
cs.setdefault('general_goal_checker', {})['yaw_goal_tolerance'] = 3.14159

# ── collision_monitor: disable to prevent laser scan from slowing the robot
# near pillars. The collision_monitor interprets the pillar's laser returns as
# a collision hazard and reduces cmd_vel to near-zero ("approach" mode) even
# though the physical gap (0.80m) is larger than the robot (0.44m wide).
# RPP's use_collision_detection=False already handles this at the planner level;
# the collision_monitor node causes double-suppression of velocity.
cmon = p.setdefault('collision_monitor', {}).setdefault('ros__parameters', {})
cmon['enabled'] = False

# ── Global planner: switch NavFn from Dijkstra to A*.
# Dijkstra hugs obstacle walls and produces paths with sharp turns near pillars.
# A* with a straight-line heuristic finds shorter, smoother paths that require
# less curvature — critical for RPP tracking through the pillar grid.
pserver = p.setdefault('planner_server', {}).setdefault('ros__parameters', {})
pserver.setdefault('GridBased', {})['use_astar'] = True
pserver.setdefault('GridBased', {})['allow_unknown'] = True
pserver.setdefault('GridBased', {})['tolerance'] = 0.5  # accept path ending within 0.5m of goal

# ── BT XML: use single-plan-then-follow (no 1 Hz replanning).
# navigate_to_pose_w_replanning_and_recovery replans every sim-second;
# this resets the velocity_smoother's ramp-up window, capping effective speed
# at a tiny fraction of max_vel_x. The w_recovery variant computes path once
# and follows it — sufficient for obstacle-free outer corridors at y=±1.8.
bt_nav = p.setdefault('bt_navigator', {}).setdefault('ros__parameters', {})
share = '/usr/lib64/ros-jazzy/share/nav2_bt_navigator/behavior_trees'
bt_nav['default_nav_to_pose_bt_xml'] = f'{share}/navigate_w_replanning_only_if_path_becomes_invalid.xml'
# Use the same BT for navigate_through_poses to avoid dependency on behavior_server
# (navigate_through_poses_w_replanning_and_recovery.xml requires spin action server
# from behavior_server, which may not be ready when bt_navigator activates).
bt_nav['default_nav_through_poses_bt_xml'] = f'{share}/navigate_w_replanning_only_if_path_becomes_invalid.xml'

# ── Progress checker: lenient for slow RTF=0.5 sim ──────────────────────────
pc = cs.setdefault('progress_checker', {})
pc['plugin'] = 'nav2_controller::SimpleProgressChecker'
pc['required_movement_radius'] = 0.05  # 5 cm minimum movement
pc['movement_time_allowance'] = 300.0  # 300 sim-s = 600 wall-s; generous for slow RTF

# ── Costmap tuning: reduce inflation so robots can pass through pillar gaps ─
# Default inflation_radius=0.55m blocks the ~0.5m gaps between pillars.
# Reduce to 0.20m so there is free space between pillars for the MPPI.
# The nav2_params.yaml has double nesting: local_costmap.local_costmap.ros__parameters
for top_key in ['local_costmap', 'global_costmap']:
    inner_key = top_key  # e.g. 'local_costmap'
    cmap_params = p.setdefault(top_key, {}).setdefault(inner_key, {}).setdefault('ros__parameters', {})
    # Inflation strategy for RPP:
    # Global at 0.15m: paths route robot center ≥ 0.30m from pillar center,
    #   giving footprint (r=0.22m) 0.08m clearance from pillar surface.
    # robot_radius=0 on global costmap: lets NavFn plan FROM positions where the
    #   physical footprint enters the inflation zone (near pillars). Without this
    #   ComputePathToPose immediately ABORTs when the start pose is in high-cost
    #   area — the robot can still physically navigate through because RPP with
    #   use_collision_detection=False follows the global path without re-checking.
    # Local at 0.10m: RPP reads local costmap for its path tracking.
    inflation = 0.15 if top_key == 'global_costmap' else 0.10
    cmap_params.setdefault('inflation_layer', {})['inflation_radius'] = inflation
    if top_key == 'global_costmap':
        cmap_params['robot_radius'] = 0.0  # point robot for global planning
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
      # External Zenoh keepalive process (MUST be separate — zenoh+rclpy share
      # the same Python process causes segfaults in CycloneDDS).
      # Reconnects every 55 s to create fresh Zenoh subscriber events, which
      # forces the nav bridge to recreate the DDS→Zenoh route after retirements.
      python3 -c "
import zenoh, time, sys, signal
signal.signal(signal.SIGTERM, lambda s, f: None)
signal.signal(signal.SIGINT, lambda s, f: None)
while True:
    try:
        conf = zenoh.Config()
        conf.insert_json5('connect/endpoints', '[\"tcp/zenoh-router:7447\"]')
        conf.insert_json5('mode', '\"client\"')
        conf.insert_json5('scouting/multicast/enabled', 'false')
        z = zenoh.open(conf)
        sub = z.declare_subscriber('${ROBOT_NAME}/cmd_vel', lambda s: None)
        print('[nav2-pod] keepalive active for ${ROBOT_NAME}', flush=True)
        time.sleep(55)
        try: sub.undeclare(); z.close()
        except: pass
    except BaseException as e:
        time.sleep(5)
" &
      KEEPALIVE_PID=$!

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
