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
from std_msgs.msg import Bool


# ── Robot configuration ───────────────────────────────────────────────────────

ROBOTS = {
    'robot_1': {
        'color': 'blue',
        'spawn': (-2.0, -0.5, 0.0),
        'goal':  ( 2.0,  0.5, math.pi),
    },
    'robot_2': {
        'color': 'red',
        'spawn': ( 2.0,  0.5, math.pi),
        'goal':  (-2.0, -0.5, 0.0),
    },
}

# Phase 2 coordinator parameters (robot_2 only).
# robot_2 subscribes to /robot_1/amcl_pose and departs once robot_1 has
# advanced DEPARTURE_THRESHOLD_M metres along its spawn→goal path.
# This avoids head-on encounters in the shared corridor.
DEPARTURE_THRESHOLD_M = 3.5   # metres along robot_1's path before robot_2 may depart

# At most MAX_YIELDS brief pauses during the traversal (yield signal from
# coordinator). The pause is intentionally short: stopping robot_2 longer
# turns it into a static LiDAR obstacle that disrupts robot_1's costmap.
MAX_YIELDS      = 2
YIELD_PAUSE_SEC = 15.0   # real-s  (7.5 sim-s at real_time_factor=0.5)

# Gate phase timeouts.
GATE_TIMEOUT_SEC = 120.0   # max time to wait for robot_1 to advance


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
    yield_now    = [False]   # yield signal from coordinator (optional)
    robot1_pos   = [None]    # robot_1's latest amcl_pose position

    if namespace == 'robot_2':
        be_qos = QoSProfile(depth=10)

        # /robot_1/amcl_pose is published by robot_1's AMCL and bridged
        # reliably via Zenoh to robot_2's pod (confirmed: regular pub/sub topic,
        # no cross-pod service call needed).  robot_2 uses this to compute
        # robot_1's path progress directly — no dependency on the coordinator's
        # gate signal, which cannot be delivered cross-pod from the Gazebo container.
        nav.create_subscription(
            PoseWithCovarianceStamped,
            '/robot_1/amcl_pose',
            lambda m: robot1_pos.__setitem__(0, m.pose.pose.position),
            be_qos)

        # Optional: yield signal from coordinator (best-effort).
        nav.create_subscription(
            Bool, '/demo/robot2_yield',
            lambda m: yield_now.__setitem__(0, m.data),
            be_qos)

    # ── Nav2 startup ──────────────────────────────────────────────────────────
    print(f'[{namespace}/{color}] Waiting for Nav2 to become active...')
    nav.waitUntilNav2Active(localizer='amcl')
    print(f'[{namespace}/{color}] Nav2 active.')

    print(f'[{namespace}/{color}] Setting initial pose ({sx:.1f}, {sy:.1f})...')
    set_initial_pose(nav, namespace, sx, sy, syaw)
    time.sleep(1.0)

    # ── Phase 2 departure gate (robot_2 only) ─────────────────────────────────
    # robot_2 subscribes to /robot_1/amcl_pose directly (Zenoh pub/sub, always
    # works cross-pod) and computes robot_1's progress along its path.
    # Departure is allowed once robot_1 has passed DEPARTURE_THRESHOLD_M — well
    # past the corridor midpoint — so the two robots never enter the shared
    # corridor simultaneously heading toward each other.
    #
    # Path from robot_1's spawn (-2,-0.5) toward goal (2,0.5):
    #   direction = (4, 1), length ≈ 4.12 m  (DWB routes ~4.8 m with obstacles)
    _PATH_LEN  = math.hypot(4.0, 1.0)
    _PATH_UX   = 4.0 / _PATH_LEN
    _PATH_UY   = 1.0 / _PATH_LEN

    def _robot1_progress():
        p = robot1_pos[0]
        if p is None:
            return 0.0
        return (p.x - (-2.0)) * _PATH_UX + (p.y - (-0.5)) * _PATH_UY

    if namespace == 'robot_2':
        print(f'[{namespace}/{color}] Waiting for robot_1 AMCL to reinitialise '
              f'and then reach {DEPARTURE_THRESHOLD_M:.1f} m along its path...')

        # Phase A: wait for robot_1's AMCL to show it near its spawn.
        # After `make reset` the previous run's AMCL pose is stale (robot_1 at
        # goal ≈ 4 m progress).  We must see progress < 0.5 m before tracking,
        # otherwise robot_2 would depart immediately on a stale reading.
        REINIT_TIMEOUT = 60.0
        reinit_deadline = time.time() + REINIT_TIMEOUT
        saw_spawn = False
        while time.time() < reinit_deadline:
            spin_sec(nav, 1.0)
            if robot1_pos[0] is not None and _robot1_progress() < 0.5:
                saw_spawn = True
                print(f'[{namespace}/{color}] robot_1 AMCL at spawn '
                      f'({_robot1_progress():.2f} m) — now tracking progress.')
                break

        if not saw_spawn:
            # AMCL never reset (previous run pose stuck) → fixed fallback
            fallback = 50.0
            print(f'[{namespace}/{color}] AMCL reinit timeout — '
                  f'fallback stagger {fallback}s.')
            time.sleep(fallback)
        else:
            # Phase B: wait for robot_1 to advance past the threshold.
            gate_deadline = time.time() + GATE_TIMEOUT_SEC
            while time.time() < gate_deadline:
                spin_sec(nav, 1.0)
                prog = _robot1_progress()
                if prog >= DEPARTURE_THRESHOLD_M:
                    print(f'[{namespace}/{color}] '
                          f'robot_1 at {prog:.2f} m — departing.')
                    break
                if robot1_pos[0] is not None:
                    print(f'[{namespace}/{color}]   robot_1 at {prog:.2f} m / '
                          f'{DEPARTURE_THRESHOLD_M:.1f} m needed...')
            else:
                fallback = 50.0
                print(f'[{namespace}/{color}] Gate timeout — fallback stagger '
                      f'{fallback}s.')
                time.sleep(fallback)

    # ── Navigate ──────────────────────────────────────────────────────────────
    goal = make_pose_stamped(nav, gx, gy, gyaw)
    print(f'[{namespace}/{color}] Navigating to ({gx:.1f}, {gy:.1f}) ...')
    nav.goToPose(goal)

    yield_count = 0

    while not nav.isTaskComplete():

        # Phase 2: robot_2 yields briefly when coordinator signals proximity
        if (namespace == 'robot_2'
                and yield_now[0]
                and yield_count < MAX_YIELDS):
            yield_count += 1
            print(f'[{namespace}/{color}] Yield #{yield_count}/{MAX_YIELDS} — '
                  f'coordinator signalled proximity, pausing {YIELD_PAUSE_SEC}s...')
            nav.cancelTask()

            # Wait for task to drain cleanly
            while not nav.isTaskComplete():
                time.sleep(0.1)

            # Spin while paused so yield_now stays current
            spin_sec(nav, YIELD_PAUSE_SEC)

            print(f'[{namespace}/{color}] Resuming navigation.')
            goal = make_pose_stamped(nav, gx, gy, gyaw)
            nav.goToPose(goal)
            continue

        fb = nav.getFeedback()
        if fb:
            dist = getattr(fb, 'distance_remaining', '?')
            print(f'[{namespace}/{color}]   {dist:.2f} m remaining')
        time.sleep(2.0)

    result = nav.getResult()
    label  = 'SUCCEEDED ✓' if result == TaskResult.SUCCEEDED else f'FAILED ({result})'
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
