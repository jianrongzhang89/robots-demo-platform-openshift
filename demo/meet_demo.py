#!/usr/bin/env python3
"""
Meet Demo: robot_1 (blue) and robot_2 (red) swap starting positions.

Each robot navigates autonomously using its own Nav2 stack (AMCL + planner +
controller). They cross paths in the middle of the world, demonstrating
independent multi-robot navigation over separate OpenShift pods connected
by Zenoh.

Assumptions:
  - Both robots have been teleported to their spawn origins:
      robot_1 (blue): (-2.0, -0.5)  yaw=0
      robot_2 (red):  ( 2.0,  0.5)  yaw=π
  - Nav2 is active and AMCL is localised on both pods
  - Run from any pod that has ros-jazzy + nav2_simple_commander installed

Usage (from your workstation):
  GZPOD=$(oc get pod -n ros2-multi-robot -l app=gazebo-sim \
           -o jsonpath='{.items[0].metadata.name}')
  oc cp demo/meet_demo.py ros2-multi-robot/${GZPOD}:/tmp/meet_demo.py -c gazebo
  oc exec -n ros2-multi-robot ${GZPOD} -c gazebo -- python3 /tmp/meet_demo.py

Or use: make demo
"""

import math
import sys
import threading
import time

import rclpy
from rclpy.executors import SingleThreadedExecutor
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
from nav2_simple_commander.robot_navigator import BasicNavigator, TaskResult


# ── Robot configuration ───────────────────────────────────────────────────────

ROBOTS = {
    'robot_1': {
        'color':     'blue',
        'spawn':     (-2.0, -0.5, 0.0),        # x, y, yaw (radians)
        'goal':      ( 2.0,  0.5, math.pi),    # swap with robot_2's spawn
    },
    'robot_2': {
        'color':     'red',
        'spawn':     ( 2.0,  0.5, math.pi),
        'goal':      (-2.0, -0.5, 0.0),        # swap with robot_1's spawn
    },
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def yaw_to_quat(yaw):
    """Convert a yaw angle (rad) to a quaternion (x, y, z, w)."""
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
    """Publish an initial pose to AMCL so it can localise from a known position."""
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
    # Covariance: σ²(x)=0.25, σ²(y)=0.25, σ²(yaw)=0.07
    msg.pose.covariance[0]  = 0.25
    msg.pose.covariance[7]  = 0.25
    msg.pose.covariance[35] = 0.07
    for _ in range(5):          # publish a few times so AMCL doesn't miss it
        pub.publish(msg)
        time.sleep(0.3)


# ── Per-robot navigation thread ───────────────────────────────────────────────

def navigate_robot(namespace, cfg, results, idx, ready_event):
    """
    Run inside a Python thread: wait for Nav2, send initial pose, navigate to goal.
    Each thread owns its own rclpy executor and BasicNavigator node.
    """
    color = cfg['color']
    sx, sy, syaw = cfg['spawn']
    gx, gy, gyaw = cfg['goal']

    # Create a dedicated executor so this thread can spin its navigator node
    # independently of the other thread.
    executor = SingleThreadedExecutor()
    nav = BasicNavigator(
        node_name=f'{namespace}_demo_nav',
        namespace=namespace,
    )
    executor.add_node(nav)

    def spin_background():
        """Keep the executor spinning so action callbacks are processed."""
        while rclpy.ok():
            executor.spin_once(timeout_sec=0.05)

    spin_thread = threading.Thread(target=spin_background, daemon=True)
    spin_thread.start()

    try:
        print(f'[{namespace}/{color}] Waiting for Nav2 to become active...')
        nav.waitUntilNav2Active(localizer='amcl')
        print(f'[{namespace}/{color}] Nav2 active.')

        # Re-publish the initial pose so AMCL is confident about location
        print(f'[{namespace}/{color}] Setting initial pose ({sx:.1f}, {sy:.1f})...')
        set_initial_pose(nav, namespace, sx, sy, syaw)
        time.sleep(1.0)

        # Signal that this robot is ready; wait for the other one too
        ready_event.set()
        ready_event.wait()      # both robots ready → start together

        # Send navigation goal
        goal = make_pose_stamped(nav, gx, gy, gyaw)
        print(f'[{namespace}/{color}] Navigating to ({gx:.1f}, {gy:.1f}) ...')
        nav.goToPose(goal)

        # Poll until done
        while not nav.isTaskComplete():
            fb = nav.getFeedback()
            if fb:
                dist = getattr(fb, 'distance_remaining', '?')
                print(f'[{namespace}/{color}]   {dist:.2f} m remaining')
            time.sleep(2.0)

        result = nav.getResult()
        results[idx] = result
        label = 'SUCCEEDED ✓' if result == TaskResult.SUCCEEDED else f'FAILED ({result})'
        print(f'[{namespace}/{color}] Navigation {label}')

    except Exception as exc:
        print(f'[{namespace}/{color}] ERROR: {exc}', file=sys.stderr)
        results[idx] = None
    finally:
        nav.destroy_node()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    rclpy.init()

    results = [None, None]
    # Use a threading.Event to synchronise departure: both robots start moving
    # at the same moment once both Nav2 stacks report active.
    ready = threading.Barrier(2)    # replaced by pair of events below

    # Two events — one per robot — act as a bilateral barrier
    ev1 = threading.Event()
    ev2 = threading.Event()

    # Pair them: each robot sets its own event and waits on both
    class BothReady:
        def __init__(self, mine, other):
            self.mine, self.other = mine, other
        def set(self):   self.mine.set()
        def wait(self):  self.other.wait()

    ready1 = BothReady(ev1, ev2)
    ready2 = BothReady(ev2, ev1)

    items  = list(ROBOTS.items())
    t1 = threading.Thread(
        target=navigate_robot,
        args=(items[0][0], items[0][1], results, 0, ready1),
        daemon=True,
    )
    t2 = threading.Thread(
        target=navigate_robot,
        args=(items[1][0], items[1][1], results, 1, ready2),
        daemon=True,
    )

    print('=' * 60)
    print(' Meet Demo — robots swap positions (cross paths)')
    print('   robot_1 (blue): (-2, -0.5) → (2,  0.5)')
    print('   robot_2 (red):  ( 2,  0.5) → (-2, -0.5)')
    print('=' * 60)

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    print()
    print('=' * 60)
    print(' Results')
    print('=' * 60)
    for (ns, cfg), result in zip(ROBOTS.items(), results):
        status = 'SUCCEEDED ✓' if result == TaskResult.SUCCEEDED else 'FAILED ✗'
        print(f'  {ns} ({cfg["color"]}): {status}')

    rclpy.shutdown()
    return 0 if all(r == TaskResult.SUCCEEDED for r in results) else 1


if __name__ == '__main__':
    sys.exit(main())
