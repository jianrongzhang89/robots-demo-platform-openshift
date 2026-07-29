#!/usr/bin/env python3
"""
Meet Demo: robot_1 (blue) and robot_2 (red) swap starting positions.

Each robot navigates autonomously using its own Nav2 stack (AMCL + planner +
controller). They cross paths in the middle of the world, demonstrating
independent multi-robot navigation over separate OpenShift pods connected
by Zenoh.

Architecture
------------
The script runs on EACH robot's own Nav2 pod (one instance per pod).
This avoids cross-pod ROS 2 service calls, which Zenoh does not reliably
route responses for (topics are fine; service request/reply is not).

Collision avoidance — Phase 2
------------------------------
The demo/coordinator.py process runs on the Gazebo pod and publishes two
coordination signals as regular pub/sub topics (bridged transparently by
Zenoh):

  /demo/robot2_gate  (Bool, TRANSIENT_LOCAL)
      Closed (False) initially.  The coordinator opens it when robot_1
      has advanced past DEPARTURE_THRESHOLD_M along its path, ensuring
      robot_2 never enters the shared corridor while robot_1 is still in
      it.  This replaces the former fixed stagger delay.

  /demo/robot2_yield (Bool)
      The coordinator publishes True when the inter-robot distance drops
      below YIELD_TRIGGER_M.  robot_2 briefly cancels its goal and waits
      for the signal to clear before resuming — at most MAX_YIELDS times.

robot_1 has priority: it never pauses or yields.

Usage (via Makefile — launches coordinator + both nav scripts in parallel):
    make demo

Or manually:
    # Gazebo pod:
    python3 /tmp/coordinator.py
    # robot_1 pod:
    python3 /tmp/meet_demo.py --namespace robot_1
    # robot_2 pod:
    python3 /tmp/meet_demo.py --namespace robot_2
"""

import argparse
import math
import sys
import time

import rclpy
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
from nav2_simple_commander.robot_navigator import BasicNavigator, TaskResult
from rclpy.qos import QoSProfile
from rclpy.task import Future as RclpyFuture


# ── Robot configuration ───────────────────────────────────────────────────────

ROBOTS = {
    'robot_1': {
        'color':     'blue',
        'spawn':     (-2.0, -0.5, 0.0),
        # Waypoint (0.5, 0.1) lies on the diagonal between the two spawns.
        # Forces robot_1 through the shared corridor so it meets robot_2.
        # Without this waypoint DWB may choose a different route and they
        # never encounter each other.
        'waypoints': [(0.5, 0.1, math.pi)],
        'goal':      ( 2.0,  0.5, math.pi),
    },
    'robot_2': {
        'color':  'red',
        'spawn':  ( 2.0,  0.5, math.pi),
        # Same shared-corridor waypoint — robot_2 moves left into the
        # corridor first, heading directly toward robot_1.
        'waypoints': [(0.5, 0.1, math.pi)],
        'goal':      (-2.0, -0.5, 0.0),
    },
}

# Phase 2 coordinator parameters (robot_2 only).
# robot_2 subscribes to /robot_1/amcl_pose and departs once robot_1 has
# advanced DEPARTURE_THRESHOLD_M metres along its spawn→goal path.
# This avoids head-on encounters in the shared corridor.
# (DEPARTURE_THRESHOLD_M removed — replaced by a fixed 5 s stagger)

# Proximity yield — robot_2 pauses when robots are this close.
# Primary check uses /robot_1/amcl_pose + /robot_2/amcl_pose directly
# (Zenoh pub/sub, always reliable).  Coordinator /demo/robot2_yield is
# an optional cross-pod supplement.
YIELD_TRIGGER_M = 2.0    # metres — yield when robots are closer than this
MAX_YIELDS      = 1      # maximum yield pauses (1 is enough; more causes compounding costmap issues)
YIELD_PAUSE_SEC = 15.0   # real-s per pause  (7.5 sim-s at real_time_factor=0.5)



# ── Helpers ───────────────────────────────────────────────────────────────────

def yaw_to_quat(yaw):
    return 0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0)


def make_pose_stamped(nav, x, y, yaw, frame='map'):
    p = PoseStamped()
    p.header.frame_id = frame
    p.header.stamp = nav.get_clock().now().to_msg()
    p.pose.position.x = float(x)
    p.pose.position.y = float(y)
    _, _, qz, qw = yaw_to_quat(yaw)
    p.pose.orientation.z = qz
    p.pose.orientation.w = qw
    return p


def set_initial_pose(nav, namespace, x, y, yaw):
    """Publish initialpose so AMCL can localise from a known position."""
    pub = nav.create_publisher(
        PoseWithCovarianceStamped, f'/{namespace}/initialpose', 1)
    msg = PoseWithCovarianceStamped()
    msg.header.frame_id = 'map'
    msg.header.stamp = nav.get_clock().now().to_msg()
    msg.pose.pose.position.x = float(x)
    msg.pose.pose.position.y = float(y)
    _, _, qz, qw = yaw_to_quat(yaw)
    msg.pose.pose.orientation.z = qz
    msg.pose.pose.orientation.w = qw
    msg.pose.covariance[0]  = 0.25
    msg.pose.covariance[7]  = 0.25
    msg.pose.covariance[35] = 0.07
    for _ in range(5):
        pub.publish(msg)
        time.sleep(0.3)


def spin_sec(nav, duration: float):
    """Spin nav node for *duration* seconds to process subscription callbacks."""
    deadline = time.time() + duration
    while time.time() < deadline:
        remaining = deadline - time.time()
        rclpy.spin_until_future_complete(
            nav, RclpyFuture(), timeout_sec=min(0.1, remaining))


# ── Single-robot navigation ───────────────────────────────────────────────────

def run_single_robot(namespace: str) -> bool:
    """
    Navigate one robot to its goal.

    For robot_2: subscribe to coordinator signals, wait for the departure
    gate, and yield briefly if the yield signal fires during navigation.

    All Nav2 calls (goToPose, cancelTask) are local to this pod.
    """
    cfg   = ROBOTS[namespace]
    color = cfg['color']
    sx, sy, syaw = cfg['spawn']
    gx, gy, gyaw = cfg['goal']

    rclpy.init()

    nav = BasicNavigator(
        node_name=f'{namespace}_demo_nav',
        namespace=namespace,
    )

    # ── Phase 2 coordinator subscriptions (robot_2 only) ─────────────────────
    robot1_pos   = [None]    # robot_1's latest amcl_pose position

    own_pos = [None]   # robot_2's own latest amcl_pose position

    if namespace == 'robot_2':
        be_qos = QoSProfile(depth=10)

        # /robot_2/amcl_pose — local AMCL; used for direct proximity yield.
        nav.create_subscription(
            PoseWithCovarianceStamped,
            '/robot_2/amcl_pose',
            lambda m: own_pos.__setitem__(0, m.pose.pose.position),
            be_qos)

        # /robot_1/amcl_pose — Zenoh-bridged; used for direct proximity yield.
        nav.create_subscription(
            PoseWithCovarianceStamped,
            '/robot_1/amcl_pose',
            lambda m: robot1_pos.__setitem__(0, m.pose.pose.position),
            be_qos)


    # ── Nav2 startup ──────────────────────────────────────────────────────────
    print(f'[{namespace}/{color}] Waiting for Nav2 to become active...')
    nav.waitUntilNav2Active(localizer='amcl')
    print(f'[{namespace}/{color}] Nav2 active.')

    print(f'[{namespace}/{color}] Setting initial pose ({sx:.1f}, {sy:.1f})...')
    set_initial_pose(nav, namespace, sx, sy, syaw)
    time.sleep(1.0)

    # ── Departure stagger (robot_2 only) ─────────────────────────────────────
    # Fixed 5 s stagger so robot_2 departs shortly after robot_1.
    # Both robots now share the same waypoint (0.5, 0.1), so they enter the
    # shared corridor from opposite ends and are guaranteed to meet.
    # The AMCL-tracking gate was removed: it waited up to 60 s for the stale
    # previous-run AMCL pose to reset, making robot_2 start far too late.
    if namespace == 'robot_2':
        stagger = 5.0
        print(f'[{namespace}/{color}] Staggering {stagger}s — '
              f'letting robot_1 enter the corridor first...')
        time.sleep(stagger)

    # ── Navigate through waypoints then final goal ────────────────────────────
    # Build the ordered target list: optional waypoints first, then final goal.
    targets = [(wx, wy, wyaw) for wx, wy, wyaw in cfg.get('waypoints', [])]
    targets.append((gx, gy, gyaw))

    yield_count = 0
    final_result = TaskResult.FAILED

    for t_idx, (tx, ty, tyaw) in enumerate(targets):
        is_final = (t_idx == len(targets) - 1)
        tag = f'goal ({tx:.1f},{ty:.1f})' if is_final else f'waypoint {t_idx+1} ({tx:.1f},{ty:.1f})'
        print(f'[{namespace}/{color}] Navigating to {tag} ...')

        current_target = make_pose_stamped(nav, tx, ty, tyaw)
        nav.goToPose(current_target)

        while not nav.isTaskComplete():

            # Phase 2: robot_2 yields when robots are too close.
            # Primary: direct distance from own+peer amcl_pose (Zenoh pub/sub,
            #   always reliable cross-pod — no service call needed).
            # Fallback: coordinator /demo/robot2_yield topic (may not arrive
            #   cross-pod from the Gazebo container).
            _too_close = (
                robot1_pos[0] is not None
                and own_pos[0] is not None
                and math.hypot(robot1_pos[0].x - own_pos[0].x,
                               robot1_pos[0].y - own_pos[0].y) < YIELD_TRIGGER_M
            )
            if (namespace == 'robot_2'
                    and _too_close
                    and yield_count < MAX_YIELDS):
                yield_count += 1
                print(f'[{namespace}/{color}] Yield #{yield_count}/{MAX_YIELDS} — '
                      f'proximity signal, pausing {YIELD_PAUSE_SEC}s...')
                nav.cancelTask()

                while not nav.isTaskComplete():
                    time.sleep(0.1)

                # Spin while paused so yield_now updates
                spin_sec(nav, YIELD_PAUSE_SEC)

                # Clear the local costmap so robot_2 does not re-plan around
                # stale "robot_1 was here" obstacle cells left by the pause.
                # This is a LOCAL service call on robot_2's own pod — reliable.
                try:
                    nav.clearLocalCostmap()
                except Exception:
                    pass

                print(f'[{namespace}/{color}] Resuming toward {tag}.')
                # Re-issue the CURRENT target (waypoint or goal), not always goal
                current_target = make_pose_stamped(nav, tx, ty, tyaw)
                nav.goToPose(current_target)
                continue

            fb = nav.getFeedback()
            if fb:
                dist = getattr(fb, 'distance_remaining', '?')
                print(f'[{namespace}/{color}]   {dist:.2f} m remaining')
            time.sleep(2.0)

        seg_result = nav.getResult()
        if is_final:
            final_result = seg_result
        elif seg_result != TaskResult.SUCCEEDED:
            print(f'[{namespace}/{color}] {tag} FAILED — continuing to next target.')

    label = 'SUCCEEDED ✓' if final_result == TaskResult.SUCCEEDED else f'FAILED ({final_result})'
    print(f'[{namespace}/{color}] Navigation {label}')

    nav.destroy_node()
    rclpy.shutdown()
    return final_result == TaskResult.SUCCEEDED


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Meet demo — two robots swap positions')
    parser.add_argument(
        '--namespace', '-n',
        choices=['robot_1', 'robot_2'],
        required=True,
        help='Namespace of the robot this instance controls (run one per pod)',
    )
    args = parser.parse_args()

    print('=' * 60)
    print(f' Meet Demo — {args.namespace} ({ROBOTS[args.namespace]["color"]})')
    print(f'   spawn: {ROBOTS[args.namespace]["spawn"][:2]}')
    print(f'   goal:  {ROBOTS[args.namespace]["goal"][:2]}')
    print('=' * 60)

    success = run_single_robot(args.namespace)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
