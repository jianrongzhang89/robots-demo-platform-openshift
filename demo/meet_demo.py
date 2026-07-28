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

Collision avoidance strategy
-----------------------------
Tier 0 — departure stagger (only approach used here):

  robot_2 waits STAGGER_DELAY_SEC real-seconds before departing.
  With real_time_factor=0.5, 1 real-s = 0.5 sim-s.

  The stagger must be long enough for robot_1 to complete most of its
  path before robot_2 starts, so they are never heading toward each other
  in the shared corridor at the same time.

  Observed traversal time for a 4.8 m path: ~80–90 real-s.
  Safe stagger = traversal_time × 0.6 ≈ 50 real-s.

  A proximity-based yield (cancelling robot_2's goal and waiting) was
  attempted but made things worse: stopping robot_2 mid-corridor creates
  a static LiDAR obstacle that robot_1 cannot plan around, causing both
  robots to fail.  Without inter-robot costmap sharing, reliably yielding
  one robot for the other requires Phase 2 of the collision-avoidance
  proposal (pose-coordinator node with Nav2 pause/resume).

Usage
-----
  make demo                          # handles both pods in parallel
  # or manually on each pod:
  python3 /tmp/meet_demo.py --namespace robot_1   # on robot_1's pod
  python3 /tmp/meet_demo.py --namespace robot_2   # on robot_2's pod
"""

import argparse
import math
import sys
import time

import rclpy
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
from nav2_simple_commander.robot_navigator import BasicNavigator, TaskResult


# ── Robot configuration ───────────────────────────────────────────────────────

ROBOTS = {
    'robot_1': {
        'color':  'blue',
        'spawn':  (-2.0, -0.5, 0.0),
        'goal':   ( 2.0,  0.5, math.pi),
    },
    'robot_2': {
        'color':  'red',
        'spawn':  ( 2.0,  0.5, math.pi),
        'goal':   (-2.0, -0.5, 0.0),
    },
}

# Tier 0: departure stagger (real-time seconds).
#
# Rationale (real_time_factor=0.5, path ~4.8 m, observed speed ~0.06 m/s real):
#   Traversal time ≈ 80 real-s.  To prevent crossing, robot_2 must not depart
#   until robot_1 is past the midpoint of the shared corridor:
#     safe stagger = traversal_time × 0.6 ≈ 50 real-s
#
# A shorter stagger (e.g. 20 s) lets both robots enter the shared corridor
# simultaneously; they meet head-on, neither can see the other in its costmap
# (no inter-robot costmap sharing is configured), and they push each other.
STAGGER_DELAY_SEC = 50.0


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
        PoseWithCovarianceStamped, f'/{namespace}/initialpose', 1
    )
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


# ── Single-robot distributed mode ─────────────────────────────────────────────

def run_single_robot(namespace):
    """
    Navigate one robot to its goal.
    Runs on the robot's OWN Nav2 pod so all Nav2 calls are local.
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

    print(f'[{namespace}/{color}] Waiting for Nav2 to become active...')
    nav.waitUntilNav2Active(localizer='amcl')
    print(f'[{namespace}/{color}] Nav2 active.')

    print(f'[{namespace}/{color}] Setting initial pose ({sx:.1f}, {sy:.1f})...')
    set_initial_pose(nav, namespace, sx, sy, syaw)
    time.sleep(1.0)

    # ── Tier 0: departure stagger ─────────────────────────────────────────────
    if namespace == 'robot_2':
        print(f'[{namespace}/{color}] Staggering {STAGGER_DELAY_SEC}s — '
              f'letting robot_1 clear the corridor...')
        time.sleep(STAGGER_DELAY_SEC)

    # ── Navigate ──────────────────────────────────────────────────────────────
    goal = make_pose_stamped(nav, gx, gy, gyaw)
    print(f'[{namespace}/{color}] Navigating to ({gx:.1f}, {gy:.1f}) ...')
    nav.goToPose(goal)

    while not nav.isTaskComplete():
        fb = nav.getFeedback()
        if fb:
            dist = getattr(fb, 'distance_remaining', '?')
            print(f'[{namespace}/{color}]   {dist:.2f} m remaining')
        time.sleep(2.0)

    result = nav.getResult()
    label = 'SUCCEEDED ✓' if result == TaskResult.SUCCEEDED else f'FAILED ({result})'
    print(f'[{namespace}/{color}] Navigation {label}')

    nav.destroy_node()
    rclpy.shutdown()
    return result == TaskResult.SUCCEEDED


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
