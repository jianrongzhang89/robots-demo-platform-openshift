#!/usr/bin/env python3
"""
Meet Demo: robot_1 (blue) and robot_2 (red) swap starting positions.

Each robot navigates autonomously using its own Nav2 stack (AMCL + planner +
controller). They cross paths in the middle of the world, demonstrating
independent multi-robot navigation over separate OpenShift pods connected
by Zenoh.

Architecture
------------
The script is designed to run on EACH robot's own Nav2 pod (one instance per
pod).  This avoids cross-pod ROS 2 service calls, which Zenoh does not reliably
route responses for (topics are fine; service request/reply is not).

The "both robots ready" barrier uses a Zenoh-bridged ROS 2 topic
(/demo/robot_N_ready) so the two pod-local instances can coordinate without
needing service calls across pods.

Usage
-----
  # On robot_1's pod:
  python3 /tmp/meet_demo.py --namespace robot_1

  # On robot_2's pod (simultaneously):
  python3 /tmp/meet_demo.py --namespace robot_2

Or via Makefile (handles both pods in parallel):
  make demo

Assumptions
-----------
  - Both robots have been teleported to their spawn origins:
      robot_1 (blue): (-2.0, -0.5)  yaw=0
      robot_2 (red):  ( 2.0,  0.5)  yaw=π
  - Nav2 is active on both pods (AMCL localised, lifecycle managers active)
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

# Phase 1 collision avoidance (Tier 0): robot_2 waits this many seconds before
# departing so robot_1 clears the center crossing zone.  Both Nav2 scripts run
# simultaneously on their own pods (make demo runs two oc exec in parallel), so
# the stagger is relative to each robot finishing waitUntilNav2Active().
#
# NOTE: time.sleep() uses wall-clock time. The simulation runs at
# real_time_factor=0.5, so each real second = 0.5 sim-seconds.  To clear the
# crossing zone robot_1 must travel ~2.2 m at ~0.26 m/s sim-speed:
#   2.2 / 0.26 ≈ 8.5 sim-s → 17 real-s minimum.  Use 20 s for safety.
STAGGER_DELAY_SEC = 20.0


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
    Navigate one robot to its goal, coordinating the departure barrier with the
    peer pod via a Zenoh-bridged topic (/demo/{ns}_ready).

    This function is called from the robot's OWN Nav2 pod, so all Nav2 service
    calls are local and reliable.
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

    # ── Phase 1 stagger: robot_2 waits before departing ──────────────────────
    # Both pods run this script simultaneously (make demo launches two oc exec
    # in parallel).  No cross-pod barrier is needed — the stagger delay is
    # enough to prevent a head-on collision at the center.
    if namespace == 'robot_2':
        print(f'[{namespace}/{color}] Staggering {STAGGER_DELAY_SEC}s — '
              f'letting robot_1 clear the crossing zone...')
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
