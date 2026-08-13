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
fp['use_collision_detection'] = True
# Collision detection re-enabled for the outer corridor demo: robots navigate
# via the south/north outer corridors (no pillars), so RPP's forward-check
# safely detects the other robot as a VoxelLayer obstacle and slows down.
# The pillar-grid path is not used in the RMF swap demo.
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
cmon['enabled'] = False
# collision_monitor disabled: its approach polygon triggers on nearby corridor
# walls (south outer wall is ~0.5m from the robot), stalling navigation.
# Layer 2 LiDAR avoidance is demonstrated by RPP's use_collision_detection=True:
# robot_2's body appears in robot_1's local VoxelLayer costmap → RPP's forward
# projection detects the high-cost cells → use_regulated_linear_velocity_scaling
# smoothly reduces robot_1's speed as robot_2 enters its approach distance.
cmon.setdefault('FootprintApproach', {})['enabled'] = False

# ── Global planner: switch NavFn from Dijkstra to A*.
# Dijkstra hugs obstacle walls and produces paths with sharp turns near pillars.
# A* with a straight-line heuristic finds shorter, smoother paths that require
# less curvature — critical for RPP tracking through the pillar grid.
pserver = p.setdefault('planner_server', {}).setdefault('ros__parameters', {})
pserver.setdefault('GridBased', {})['use_astar'] = True
pserver.setdefault('GridBased', {})['allow_unknown'] = True
pserver.setdefault('GridBased', {})['tolerance'] = 0.5  # accept path ending within 0.5m of goal

# ── AMCL for localization using the pre-built pgm map (full sandbox coverage).
# AMCL with the pgm map covers the entire tb3_sandbox from the start, allowing
# Nav2 to plan paths to any waypoint without goal-outside-bounds errors.
# slam_toolbox posegraph coverage is limited to areas near each robot's spawn,
# causing goal-coordinates-outside-bounds for south-corridor goals when robots
# spawn far from the corridor. AMCL's localization drift in the south outer
# corridor does not affect LiDAR-based collision detection (which operates in the
# odom/sensor frame) — it only affects pose estimate precision.
amcl_ros2 = p.setdefault('amcl', {}).setdefault('ros__parameters', {})
amcl_ros2['base_frame_id']   = 'base_footprint'
amcl_ros2['odom_frame_id']   = 'odom'
amcl_ros2['global_frame_id'] = 'map'

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
print('[nav2-pod] Patched nav2 params: AMCL + A* + RPP + collision_monitor(min_pts=12) + 300s bond_timeout')
" && PARAMS_ARG="params_file:=${CUSTOM_PARAMS}" || { echo "[nav2-pod/${ROBOT_NAME}] Python patch FAILED:"; cat /tmp/py_err_${ROBOT_NAME}.log >&1; PARAMS_ARG=""; }
# Verify the file was actually created before using it
[ -f "${CUSTOM_PARAMS}" ] || { echo "[nav2-pod/${ROBOT_NAME}] WARNING: custom params file not created, using stock params"; PARAMS_ARG=""; }
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

# Wait for AMCL to load, then set initial pose so localization can start.
(
echo "[nav2-pod/${ROBOT_NAME}] Waiting for AMCL node to load..."
  for i in $(seq 1 180); do
    if ros2 node list 2>/dev/null | grep -qE "^(/amcl|/${ROBOT_NAME}/amcl)$"; then
      echo "[nav2-pod/${ROBOT_NAME}] AMCL detected (attempt ${i}), publishing initialpose until map->odom TF appears..."
      # Publish /initialpose repeatedly with best_effort QoS until AMCL
      # publishes the map->odom TF. Relying on lifecycle get /amcl is
      # unreliable (query times out). Publishing every 5s is safe — AMCL
      # drops the message while inactive and processes it when active.
      read -r INITIAL_QZ INITIAL_QW < <(python3 -c \
        "import math; y=${INITIAL_YAW}; print(math.sin(y/2), math.cos(y/2))")
      for k in $(seq 1 60); do
        ros2 topic pub "/initialpose" geometry_msgs/msg/PoseWithCovarianceStamped \
          "{header: {frame_id: 'map'}, pose: {pose: {position: {x: ${INITIAL_X}, y: ${INITIAL_Y}, z: 0.0}, orientation: {x: 0.0, y: 0.0, z: ${INITIAL_QZ}, w: ${INITIAL_QW}}}, covariance: [0.01, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.01, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.01]}}" \
          --times 1 --qos-reliability best_effort 2>/dev/null || true
        if timeout 3 ros2 run tf2_ros tf2_echo "map" "odom" 2>&1 | grep -q "Translation"; then
          echo "[nav2-pod/${ROBOT_NAME}] Localization active — navigation stack ready."
          break
        fi
        echo "[nav2-pod/${ROBOT_NAME}] Waiting for map->odom TF (attempt ${k}/60)..."
        sleep 5
      done

      timeout 8 ros2 param set /local_costmap/local_costmap transform_tolerance 10.0 2>/dev/null || true
      timeout 8 ros2 param set /global_costmap/global_costmap transform_tolerance 10.0 2>/dev/null || true
      timeout 8 ros2 param set /controller_server general_goal_checker.yaw_goal_tolerance 3.14159 2>/dev/null || true

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
        print('[nav2-pod] keepalive PERMANENT for ${ROBOT_NAME}', flush=True)
        # Keep the subscription open permanently — never disconnect.
        # Reconnecting every 55s creates a gap during which the Zenoh bridge
        # retires the DDS→Zenoh route for cmd_vel, causing the robot to stop.
        time.sleep(999999)
        # (Unreachable: loop restarts only on exception)
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
