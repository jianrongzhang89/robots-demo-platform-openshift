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

# Localization mode: slam_toolbox (default) or amcl
# amcl requires LOCALIZATION_MAP env var pointing to a nav2 map YAML file.
LOCALIZATION_MODE="${LOCALIZATION_MODE:-slam_toolbox}"
LOCALIZATION_MAP="${LOCALIZATION_MAP:-/opt/ros/jazzy/share/nav2_bringup/maps/tb3_sandbox.yaml}"

BRINGUP_DIR="${ROS_PREFIX}/share/nav2_bringup"

echo "[nav2-pod/${ROBOT_NAME}] Starting robot_state_publisher (global TF frames — not namespaced)..."
URDF=$(cat /usr/lib64/ros-jazzy/share/nav2_minimal_tb3_sim/urdf/turtlebot3_waffle.urdf)
ros2 run robot_state_publisher robot_state_publisher \
  --ros-args -p robot_description:="${URDF}" &
RSP_PID=$!

echo "[nav2-pod/${ROBOT_NAME}] Starting nav2 RMF relay (pub/sub bridge for navigate_to_pose)..."
# Watchdog loop: restart relay if it exits unexpectedly.
(while true; do
  python3 /nav2_relay.py 2>&1
  echo "[nav2-pod/${ROBOT_NAME}] nav2_relay.py exited (exit=$?), restarting in 3s..."
  sleep 3
done) &
NAV_RELAY_PID=$!

echo "[nav2-pod/${ROBOT_NAME}] Clock delivered directly via bridge (robot_N/clock -> /clock, same as main branch)."
CLOCK_ROS_RELAY_PID=""
TF_HEARTBEAT_PID=""

echo "[nav2-pod/${ROBOT_NAME}] Launching Nav2 bringup (no ROS namespace — isolation via Zenoh)..."
# Patch nav2_params.yaml: start from our custom config (which has correct base
# settings) rather than the stock nav2_bringup params (whose structure varies
# across Nav2 versions). Use Python to substitute ${ROBOT_NAME} and apply
# runtime overrides (RPP plugin, costmap tuning, bond_timeout, etc.).
NAV2_PARAMS="${BRINGUP_DIR}/params/nav2_params.yaml"  # stock nav2_bringup params (un-namespaced frames)
CUSTOM_PARAMS="/tmp/nav2_params_${ROBOT_NAME}.yaml"
if [ -f "${NAV2_PARAMS}" ]; then
  echo "[nav2-pod/${ROBOT_NAME}] Patching nav2 params from ${NAV2_PARAMS}..."
  python3 2>/tmp/py_err_${ROBOT_NAME}.log -c "
import yaml, sys, os
with open('${NAV2_PARAMS}') as f:
    p = yaml.safe_load(f) or {}
cs = p.setdefault('controller_server', {}).setdefault('ros__parameters', {})

# ── Switch to Regulated Pure Pursuit (RPP) controller.
# DWB's multi-critic trajectory sampling creates local scoring minima in the
# tb3_sandbox pillar grid where ALL sampled trajectories score comparably,
# resulting in zero velocity output. RPP avoids this entirely: it computes a
# single carrot lookahead point on the global path and drives toward it,
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
# Collision detection disabled: the spawn→s_in diagonal path passes through
# the pillar grid where RPP's forward check fires on inflated pillar cells.
# With slam_toolbox localization (<=0.012m drift), the VoxelLayer CORRECTLY
# marks robot_2 as an obstacle when robots approach — visible in noVNC.
# RMF negotiation fires via ETA drift (fleet_states position lag causes the
# scheduler to detect trajectory overlap) rather than via RPP slowdown.
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
# a collision hazard and reduces cmd_vel to near-zero (approach mode) even
# though the physical gap (0.80m) is larger than the robot (0.44m wide).
# RPP's use_collision_detection=False already handles this at the planner level;
# the collision_monitor node causes double-suppression of velocity.
cmon = p.setdefault('collision_monitor', {}).setdefault('ros__parameters', {})
cmon['enabled'] = True
# collision_monitor re-enabled. With slam_toolbox accuracy the corridor walls
# no longer cause false positives. Reduce time_before_collision to 0.5s
# (was 1.2s default) so the approach polygon fires on the other robot at
# close range without triggering on walls that are further away.
cmon.setdefault('FootprintApproach', {})['enabled'] = True
cmon.setdefault('FootprintApproach', {})['time_before_collision'] = 0.5

# ── Global planner: switch NavFn from Dijkstra to A*.
# Dijkstra hugs obstacle walls and produces paths with sharp turns near pillars.
# A* with a straight-line heuristic finds shorter, smoother paths that require
# less curvature — critical for RPP tracking through the pillar grid.
pserver = p.setdefault('planner_server', {}).setdefault('ros__parameters', {})
pserver.setdefault('GridBased', {})['use_astar'] = True
pserver.setdefault('GridBased', {})['allow_unknown'] = True
pserver.setdefault('GridBased', {})['tolerance'] = 0.5  # accept path ending within 0.5m of goal

# ── Localization: AMCL (default) or slam_toolbox mapping (SLAM_BUILD_MODE=1).
# SLAM_BUILD_MODE=1 is used when rebuilding posegraphs: robots explore the
# sandbox in mapping mode so slam_toolbox records the full layout. Once the
# exploration is complete and posegraphs are serialized, the image is rebuilt
# with localization mode using the new full-coverage posegraphs.
import os as _os
_slam_mode = _os.environ.get('SLAM_BUILD_MODE', '0')
if _slam_mode == '1':
    # SLAM MAPPING mode: build new posegraph from scratch (SLAM_BUILD_MODE=1 image).
    slam = p.setdefault('slam_toolbox', {}).setdefault('ros__parameters', {})
    slam['use_sim_time']             = True
    slam['odom_frame']               = 'odom'
    slam['map_frame']                = 'map'
    slam['base_frame']               = 'base_footprint'
    slam['scan_topic']               = '/scan'
    slam['debug_logging']            = False
    slam['throttle_scans']           = 1
    slam['transform_publish_period'] = 0.02
    slam['map_update_interval']      = 5.0
    slam['resolution']               = 0.05
    slam['max_laser_range']          = 3.5
    slam['minimum_time_interval']    = 0.5
    slam['transform_timeout']        = 0.2
    slam['tf_buffer_duration']       = 30.0
    slam['stack_size_to_use']        = 40000000
    slam['enable_interactive_mode']  = False
    slam['mode']                     = 'mapping'
    slam['do_loop_closing']          = True
    slam['loop_search_maximum_distance'] = 4.0
    slam['link_scan_maximum_distance'] = 1.5
    print('[nav2-pod] SLAM BUILD MODE: mapping (building new posegraph)')
else:
    # slam_toolbox in localization mode (non-lifecycle localization_slam_toolbox_node).
    # Provides accurate scan-matching TF in the south outer corridor.
    # The node is started as a standalone process (not through the lifecycle manager)
    # to bypass the lifecycle activate timeout during posegraph deserialization.
    # The global_costmap uses /map from slam_toolbox (posegraph-based occupancy grid).
    # Nav2 goals subtract spawn offset: map = world - (INITIAL_X, INITIAL_Y).
    print('[nav2-pod] SLAM LOCALIZATION MODE: localization_slam_toolbox_node (non-lifecycle)')

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
        # Use actual robot radius (0.22m) so NavFn routes around pillar grid.
        # Pillar gap 0.8m - 2x(0.15m pillar inflation + 0.22m robot) = -0.14m:
        # negative effective gap means NavFn correctly finds outer corridor routes.
        cmap_params['robot_radius'] = 0.22
    cmap_params.setdefault('inflation_layer', {})['cost_scaling_factor'] = 5.0
    # transform_timeout: how long global/local costmap activation waits for TF.
    # Default (0.1s) is too short for AMCL mode — AMCL must receive initial pose
    # and publish map→odom before the costmap can activate. 60s covers AMCL startup.
    cmap_params['transform_timeout'] = 60.0
    # Allow 30 s for map→odom TF during activation. The default (0.3 s) is too
    # short: AMCL may not have published map→odom by the time the lifecycle
    # manager activates planner_server, causing the global_costmap to abort.
    cmap_params['transform_tolerance'] = 30.0

# ── Lifecycle manager: extend bond_timeout so planner_server can wait ────────
# planner_server's global_costmap blocks during activation waiting for the /map
# topic from AMCL. If lifecycle_manager_localization hasn't yet activated AMCL,
# the static_layer has no map and the costmap reports a TF lookup failure after
# the bond_timeout expires (default 4s). Setting 300s gives AMCL enough time
# to fully activate and publish /map before planner_server gives up.
for lm_name in ['lifecycle_manager_navigation', 'lifecycle_manager_localization']:
    lm = p.setdefault(lm_name, {}).setdefault('ros__parameters', {})
    lm['bond_timeout'] = 300.0

with open('${CUSTOM_PARAMS}', 'w') as f:
    yaml.dump(p, f, default_flow_style=False)
_build = _os.environ.get('SLAM_BUILD_MODE', '0')
mode_label = 'SLAM-MAPPING' if _build == '1' else 'AMCL'
print(f'[nav2-pod] Patched nav2 params: {mode_label} + A* + RPP + 300s bond_timeout')
" && PARAMS_ARG="params_file:=${CUSTOM_PARAMS}" || { echo "[nav2-pod/${ROBOT_NAME}] Python patch FAILED:"; cat /tmp/py_err_${ROBOT_NAME}.log >&1; PARAMS_ARG=""; }
# Verify the file was actually created before using it
[ -f "${CUSTOM_PARAMS}" ] || { echo "[nav2-pod/${ROBOT_NAME}] WARNING: custom params file not created, using stock params"; PARAMS_ARG=""; }
else
  PARAMS_ARG=""
fi

if [ "${SLAM_BUILD_MODE:-0}" = "1" ]; then
  # Mapping mode: slam_toolbox builds posegraph (SLAM_BUILD_MODE=1 image only)
  ros2 launch nav2_bringup bringup_launch.py \
    use_sim_time:=True \
    autostart:=True \
    use_composition:=False \
    slam:=True \
    ${PARAMS_ARG} &
  NAV2_PID=$!
elif [ "${LOCALIZATION_MODE}" = "amcl" ]; then
  # AMCL localization mode: uses a pre-built occupancy grid map (.pgm + .yaml).
  # Works with any world that has a map in nav2_bringup (tb3_sandbox, turtlebot3_world, etc.)
  # or a custom map mounted via ConfigMap. No posegraph generation required.
  echo "[nav2-pod/${ROBOT_NAME}] AMCL LOCALIZATION MODE: map=${LOCALIZATION_MAP}"
  ros2 launch nav2_bringup bringup_launch.py \
    use_sim_time:=True \
    autostart:=True \
    use_composition:=False \
    map:="${LOCALIZATION_MAP}" \
    ${PARAMS_ARG} &
  NAV2_PID=$!
  echo "[nav2-pod/${ROBOT_NAME}] Nav2 (AMCL) starting, waiting 3s for AMCL to subscribe to /initialpose..."
  sleep 3
  ros2 topic pub /initialpose geometry_msgs/msg/PoseWithCovarianceStamped \
    "{header: {frame_id: 'map'}, pose: {pose: {position: {x: ${INITIAL_X}, y: ${INITIAL_Y}}, \
    orientation: {w: 1.0}}, covariance: [0.25,0,0,0,0,0, 0,0.25,0,0,0,0, 0,0,0,0,0,0, \
    0,0,0,0,0,0, 0,0,0,0,0,0, 0,0,0,0,0,0.07]}}" \
    --times 5 2>/dev/null || true
  echo "[nav2-pod/${ROBOT_NAME}] AMCL initial pose published."
else
  # Localization mode: start localization_slam_toolbox_node as a standalone
  # non-lifecycle process BEFORE nav2 navigation stack.
  #
  # ROOT CAUSE OF LOCALIZATION DRIFT (research finding):
  # Default loop_search_maximum_distance=4.0m allows loop closure to find
  # posegraph candidates anywhere in the 4m tb3_sandbox. Symmetric corridor
  # walls make the spawn scan ambiguously similar to other corridor positions
  # (e.g., map(3.63,-1.49)), causing non-deterministic convergence to wrong
  # locations. Restricting to 1.0m eliminates all wrong candidates — they are
  # all >1.5m away from spawn.
  #
  # Fix: set loop_search_maximum_distance=1.0 + verify TF is near (0,0) after
  # initialization, retrying slam_toolbox startup if drift > 0.3m.
  read -r SLAM_QZ SLAM_QW < <(python3 -c \
    "import math; y=${INITIAL_YAW}; print(math.sin(y/2), math.cos(y/2))")

  # Inner function: attempt one slam_toolbox init cycle.
  # Returns 0 (success) if TF converges to within 0.3m of origin, else 1.
  _slam_init_one() {
    local attempt=$1
    echo "[nav2-pod/${ROBOT_NAME}] slam_toolbox init attempt ${attempt}..."
    # Kill previous instance if retrying
    [ -n "${SLAM_LOC_PID:-}" ] && kill "${SLAM_LOC_PID}" 2>/dev/null; sleep 2

    ros2 run slam_toolbox localization_slam_toolbox_node \
      --ros-args \
      -p use_sim_time:=true \
      -p odom_frame:=odom \
      -p map_frame:=map \
      -p base_frame:=base_footprint \
      -p scan_topic:=/scan \
      -p enable_interactive_mode:=false \
      -p tf_buffer_duration:=30.0 \
      -p transform_publish_period:=0.02 \
      -p loop_search_maximum_distance:=1.0 \
      -p link_scan_maximum_distance:=1.5 \
      -p correlation_search_space_dimension:=0.5 \
      -p minimum_time_interval:=0.5 &
    SLAM_LOC_PID=$!
    echo "[nav2-pod/${ROBOT_NAME}] localization_slam_toolbox_node started (PID ${SLAM_LOC_PID})"

    sleep 5
    timeout 15 ros2 lifecycle set /slam_toolbox configure 2>/dev/null || true
    sleep 3
    timeout 15 ros2 lifecycle set /slam_toolbox activate 2>/dev/null || true
    sleep 3

    echo "[nav2-pod/${ROBOT_NAME}] Loading posegraph /opt/ros2-demo/slam_maps/${ROBOT_NAME}_slam..."
    timeout 120 ros2 service call /slam_toolbox/deserialize_map \
      slam_toolbox/srv/DeserializePoseGraph \
      "{filename: '/opt/ros2-demo/slam_maps/${ROBOT_NAME}_slam', match_type: 1, \
       pose: {x: 0.0, y: 0.0, theta: ${INITIAL_YAW}}}" 2>/dev/null || true

    # Publish /initialpose at map(0,0) = posegraph origin = robot spawn.
    timeout 30 ros2 topic pub "/initialpose" geometry_msgs/msg/PoseWithCovarianceStamped \
      "{header: {frame_id: 'map'}, pose: {pose: {position: {x: 0.0, y: 0.0, z: 0.0}, \
      orientation: {x: 0.0, y: 0.0, z: ${SLAM_QZ}, w: ${SLAM_QW}}}, \
      covariance: [0.01,0,0,0,0,0, 0,0.01,0,0,0,0, 0,0,0,0,0,0, 0,0,0,0,0,0, \
      0,0,0,0,0,0, 0,0,0,0,0,0.01]}}" \
      --times 5 2>/dev/null || true

    # Wait for TF and verify it is CORRECT (translation < 0.3m).
    # This catches the case where loop closure still finds a wrong candidate.
    echo "[nav2-pod/${ROBOT_NAME}] Waiting for slam_toolbox map→odom TF and verifying correctness..."
    for k in $(seq 1 40); do
      TF_OUT=$(timeout 5 ros2 run tf2_ros tf2_echo "map" "odom" 2>&1 | grep "Translation" | head -1)
      if [ -n "${TF_OUT}" ]; then
        TF_DIST=$(echo "${TF_OUT}" | python3 -c "
import sys, re, math
m = re.search(r'\[([^,]+),\s*([^,]+)', sys.stdin.read())
x, y = (float(m.group(1)), float(m.group(2))) if m else (99, 99)
print(f'{math.sqrt(x**2+y**2):.3f}|{x:.3f}|{y:.3f}')
" 2>/dev/null || echo "99|99|99")
        DIST=$(echo "${TF_DIST}" | cut -d'|' -f1)
        TX=$(echo "${TF_DIST}" | cut -d'|' -f2)
        TY=$(echo "${TF_DIST}" | cut -d'|' -f3)
        echo "[nav2-pod/${ROBOT_NAME}] TF = (${TX}, ${TY}), dist from origin = ${DIST}m"
        if python3 -c "import sys; exit(0 if float('${DIST}') < 0.30 else 1)" 2>/dev/null; then
          echo "[nav2-pod/${ROBOT_NAME}] TF CORRECT (< 0.3m). Navigation stack can start."
          return 0
        else
          echo "[nav2-pod/${ROBOT_NAME}] TF WRONG (${DIST}m) — slam_toolbox drifted. Will retry."
          return 1
        fi
      fi
      if [ $((k % 5)) -eq 0 ]; then
        ros2 topic pub "/initialpose" geometry_msgs/msg/PoseWithCovarianceStamped \
          "{header: {frame_id: 'map'}, pose: {pose: {position: {x: 0.0, y: 0.0, z: 0.0}, \
          orientation: {x: 0.0, y: 0.0, z: ${SLAM_QZ}, w: ${SLAM_QW}}}, \
          covariance: [0.01,0,0,0,0,0, 0,0.01,0,0,0,0, 0,0,0,0,0,0, 0,0,0,0,0,0, \
          0,0,0,0,0,0, 0,0,0,0,0,0.01]}}" \
          --times 3 2>/dev/null || true
      fi
      echo "[nav2-pod/${ROBOT_NAME}] TF not yet available (${k}/40)..."
      sleep 3
    done
    echo "[nav2-pod/${ROBOT_NAME}] TF never appeared — retrying."
    return 1
  }

  # Retry up to 3 times until TF converges correctly to spawn position.
  SLAM_INIT_OK=0
  for attempt in 1 2 3; do
    if _slam_init_one "${attempt}"; then
      SLAM_INIT_OK=1
      break
    fi
    echo "[nav2-pod/${ROBOT_NAME}] Attempt ${attempt} failed. Retrying in 3s..."
    sleep 3
  done
  [ "${SLAM_INIT_OK}" = "0" ] && \
    echo "[nav2-pod/${ROBOT_NAME}] WARNING: slam_toolbox failed all 3 attempts — proceeding."

  # Start Nav2 navigation only (slam_toolbox provides TF and /map).
  ros2 launch nav2_bringup navigation_launch.py \
    use_sim_time:=True \
    autostart:=True \
    use_composition:=False \
    ${PARAMS_ARG} &
  NAV2_PID=$!
fi
NAV2_PID=$!

# odom→base_footprint TF broadcaster
# The ros_gz_bridge in Gazebo publishes the DiffDrive odom TF to /robot_N/tf,
# but a QoS mismatch between the ros_gz_bridge DDS publisher and the Zenoh
# bridge DDS subscriber prevents it from reaching this pod. Without this TF,
# AMCL cannot publish map→odom and the global_costmap activation times out.
# This broadcaster derives the same TF from /odom (which flows correctly via
# Zenoh) and runs in a restart loop to survive any crashes.
cat > /tmp/odom_tf_broadcaster.py << 'ODOM_TF_EOF'
import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from geometry_msgs.msg import TransformStamped
from tf2_ros import TransformBroadcaster

class OdomTfBroadcaster(Node):
    def __init__(self):
        super().__init__('odom_tf_broadcaster')
        self.tf_broadcaster = TransformBroadcaster(self)
        self.create_subscription(Odometry, '/odom', self.odom_cb, 10)
        self.get_logger().info('odom->base_footprint TF broadcaster started')

    def odom_cb(self, msg):
        t = TransformStamped()
        t.header.stamp = msg.header.stamp
        t.header.frame_id = 'odom'
        t.child_frame_id = 'base_footprint'
        t.transform.translation.x = msg.pose.pose.position.x
        t.transform.translation.y = msg.pose.pose.position.y
        t.transform.translation.z = msg.pose.pose.position.z
        t.transform.rotation = msg.pose.pose.orientation
        self.tf_broadcaster.sendTransform(t)

rclpy.init(args=['--ros-args', '-p', 'use_sim_time:=true'])
rclpy.spin(OdomTfBroadcaster())
ODOM_TF_EOF
while true; do python3 /tmp/odom_tf_broadcaster.py 2>/dev/null || true; sleep 2; done &
echo "[nav2-pod/${ROBOT_NAME}] odom->base_footprint TF broadcaster started"

# Costmap clearing service — subscribes to Zenoh robot_N/clear_costmaps and
# calls /global_costmap/clear_entirely_global_costmap and the local equivalent.
# Stale obstacle cells accumulate in the costmap during Phase 1+2 navigation of
# the collision-avoidance demo, blocking Phase 3 planning.  Clearing on demand
# ensures Nav2 has a fresh costmap for Phase 3.
cat > /tmp/costmap_clear.py << 'COSTMAP_EOF'
import rclpy, zenoh, time, os, signal, threading
from rclpy.node import Node
from std_srvs.srv import Empty

ROBOT = os.environ.get('ROBOT_NAME', 'robot_1')
KEY = f'{ROBOT}/clear_costmaps'

class CostmapClearer(Node):
    def __init__(self):
        super().__init__('costmap_clearer')
        self._gcli = self.create_client(Empty, '/global_costmap/clear_entirely_global_costmap')
        self._lcli = self.create_client(Empty, '/local_costmap/clear_entirely_local_costmap')
        self.get_logger().info(f'Costmap clearer ready, listening on Zenoh {KEY}')

    def clear(self):
        for cli, name in [(self._gcli, 'global'), (self._lcli, 'local')]:
            if cli.wait_for_service(timeout_sec=2.0):
                cli.call_async(Empty.Request())
                self.get_logger().info(f'{name} costmap cleared')

signal.signal(signal.SIGTERM, lambda s, f: None)
signal.signal(signal.SIGINT,  lambda s, f: None)
while True:
    try:
        rclpy.init(args=['--ros-args', '-p', 'use_sim_time:=true'])
        node = CostmapClearer()
        conf = zenoh.Config()
        conf.insert_json5('connect/endpoints', f'[\"tcp/zenoh-router:7447\"]')
        conf.insert_json5('mode', '"client"')
        conf.insert_json5('scouting/multicast/enabled', 'false')
        z = zenoh.open(conf)
        def on_signal(sample):
            threading.Thread(target=lambda: (node.clear(), rclpy.spin_once(node, timeout_sec=0.1)), daemon=True).start()
        sub = z.declare_subscriber(KEY, on_signal)
        rclpy.spin(node)
    except BaseException:
        time.sleep(3)
COSTMAP_EOF
while true; do python3 /tmp/costmap_clear.py 2>/dev/null || true; sleep 2; done &
echo "[nav2-pod/${ROBOT_NAME}] costmap clearing service started"

# slam_toolbox → amcl_pose relay.
# slam_toolbox publishes /pose (PoseWithCovarianceStamped) in its own MAP frame
# (origin = robot spawn = world INITIAL_X, INITIAL_Y).  The free_fleet adapter
# subscribes to robot_N/amcl_pose via Zenoh and expects world-frame coordinates.
# This relay converts map frame to world frame by adding the spawn offset.
cat > /tmp/slam_amcl_relay.py << 'SLAM_RELAY_EOF'
import rclpy, os, time
from rclpy.node import Node
from geometry_msgs.msg import PoseWithCovarianceStamped

SPAWN_X = float(os.environ.get('INITIAL_X', '0.0'))
SPAWN_Y = float(os.environ.get('INITIAL_Y', '0.0'))

class SlamAmclRelay(Node):
    def __init__(self):
        super().__init__('slam_amcl_relay')
        self._pub = self.create_publisher(
            PoseWithCovarianceStamped, '/amcl_pose', 10)
        self.create_subscription(
            PoseWithCovarianceStamped, '/pose', self._cb, 10)
        self.get_logger().info(
            f'slam→amcl relay: adding spawn offset ({SPAWN_X},{SPAWN_Y})')

    def _cb(self, msg):
        out = PoseWithCovarianceStamped()
        out.header = msg.header
        out.header.frame_id = 'map'
        out.pose = msg.pose
        # Convert slam_toolbox map frame → world frame:
        # world = map_pos + spawn_offset
        # (slam_toolbox map origin = spawn = world INITIAL_X/Y)
        out.pose.pose.position.x = msg.pose.pose.position.x + SPAWN_X
        out.pose.pose.position.y = msg.pose.pose.position.y + SPAWN_Y
        self._pub.publish(out)

while True:
    try:
        rclpy.init(args=['--ros-args', '-p', 'use_sim_time:=true'])
        rclpy.spin(SlamAmclRelay())
    except BaseException:
        time.sleep(2)
SLAM_RELAY_EOF
while true; do python3 /tmp/slam_amcl_relay.py 2>/dev/null || true; sleep 2; done &
echo "[nav2-pod/${ROBOT_NAME}] slam→amcl_pose relay started (adds spawn offset to map-frame pose)"

# cmd_vel Zenoh publisher — bypasses zenoh-bridge-ros2dds for cmd_vel.
# The bridge's cmd_vel Publisher route gets garbage-collected at ~82 s
# (Zenoh broker idle-subscriber timer), stopping velocity commands from
# reaching Gazebo. This process maintains a persistent Zenoh publisher for
# robot_N/cmd_vel and forwards every DDS /cmd_vel message directly, so the
# Gazebo bridge's Route Subscriber (Zenoh:robot_N/cmd_vel→DDS:/robot_N/cmd_vel)
# stays alive and cmd_vel flows continuously regardless of Zenoh bridge GC.
cat > /tmp/cmdvel_zenoh_pub.py << 'CMDVEL_EOF'
import rclpy, zenoh, time, threading, os, signal
from rclpy.node import Node
from geometry_msgs.msg import Twist
from rclpy.serialization import serialize_message

ROBOT = os.environ.get('ROBOT_NAME', 'robot_1')
KEY = f'{ROBOT}/cmd_vel'

class CmdVelZenohPub(Node):
    def __init__(self, pub):
        super().__init__('cmdvel_zenoh_pub')
        self._pub = pub
        self.create_subscription(Twist, '/cmd_vel', self._cb, 10)
        self.get_logger().info(f'cmd_vel Zenoh publisher started → {KEY}')

    def _cb(self, msg):
        try:
            self._pub.put(serialize_message(msg))
        except Exception:
            pass

signal.signal(signal.SIGTERM, lambda s, f: None)
signal.signal(signal.SIGINT,  lambda s, f: None)
while True:
    try:
        conf = zenoh.Config()
        conf.insert_json5('connect/endpoints', '["tcp/zenoh-router:7447"]')
        conf.insert_json5('mode', '"client"')
        conf.insert_json5('scouting/multicast/enabled', 'false')
        z = zenoh.open(conf)
        pub = z.declare_publisher(KEY)
        rclpy.init(args=['--ros-args', '-p', 'use_sim_time:=true'])
        node = CmdVelZenohPub(pub)
        rclpy.spin(node)
    except BaseException:
        time.sleep(3)
CMDVEL_EOF
while true; do python3 /tmp/cmdvel_zenoh_pub.py 2>/dev/null || true; sleep 2; done &
echo "[nav2-pod/${ROBOT_NAME}] cmd_vel Zenoh publisher started"

# Wait for localization node (AMCL or slam_toolbox) to publish map→odom TF.
(
if [ "${SLAM_BUILD_MODE:-0}" = "1" ]; then
  # ── MAPPING mode ──────────────────────────────────────────────────────────
  # slam_toolbox builds map from scan as robot explores. TF published automatically.
  echo "[nav2-pod/${ROBOT_NAME}] SLAM mapping mode: waiting for slam_toolbox..."
  for i in $(seq 1 180); do
    if ros2 node list 2>/dev/null | grep -qE "^(/slam_toolbox|/${ROBOT_NAME}/slam_toolbox)$"; then
      echo "[nav2-pod/${ROBOT_NAME}] slam_toolbox ready (attempt ${i}) — drive robot to explore."
      break
    fi
    sleep 5
  done
else
  # ── slam_toolbox localization mode (non-lifecycle) ───────────────────────
  # localization_slam_toolbox_node and navigation_launch.py were started before
  # this subshell. The TF is already published (from the pre-launch sequence).
  # Wait for bt_navigator to activate, then set additional params.
  echo "[nav2-pod/${ROBOT_NAME}] Waiting for bt_navigator to activate (slam_toolbox localization)..."
  for k in $(seq 1 60); do
    BT=$(timeout 5 ros2 lifecycle get /bt_navigator 2>/dev/null | grep -oE "[a-z]+ \[[0-9]+\]" | head -1)
    if echo "${BT}" | grep -q "active"; then
      echo "[nav2-pod/${ROBOT_NAME}] bt_navigator active — navigation stack ready."
      break
    fi
    echo "[nav2-pod/${ROBOT_NAME}] bt_navigator: ${BT} (${k}/60)..."
    sleep 5
  done

  timeout 8 ros2 param set /local_costmap/local_costmap transform_tolerance 10.0 2>/dev/null || true
  timeout 8 ros2 param set /global_costmap/global_costmap transform_tolerance 10.0 2>/dev/null || true
  timeout 8 ros2 param set /controller_server general_goal_checker.yaw_goal_tolerance 3.14159 2>/dev/null || true

  # Zenoh keepalive — prevents cmd_vel route from being garbage-collected (~82s idle).
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
        print('[nav2-pod] keepalive PERMANENT for ${ROBOT_NAME}', flush=True)
        time.sleep(999999)
    except BaseException:
        time.sleep(5)
" &
  KEEPALIVE_PID=$!

  # Navigation watchdog — calls RESUME when bt_navigator goes inactive.
  echo "[nav2-pod/${ROBOT_NAME}] Starting navigation watchdog..."
  while true; do
    sleep 10
    BT_STATE=$(timeout 3 ros2 lifecycle get /bt_navigator 2>/dev/null | grep -oE "[a-z]+ \[[0-9]+\]" | head -1)
    if ! echo "${BT_STATE}" | grep -q "active"; then
      echo "[nav2-pod/${ROBOT_NAME}] bt_navigator not active (${BT_STATE}), calling RESUME..."
      timeout 90 ros2 service call /lifecycle_manager_navigation/manage_nodes \
        nav2_msgs/srv/ManageLifecycleNodes "{command: 2}" 2>/dev/null || true
    fi
  done
fi
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
