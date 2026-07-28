#!/usr/bin/env python3
"""
Phase 2 coordinator for the multi-robot meet demo.

Monitors both robots' AMCL poses (cross-pod via Zenoh pub/sub topics) and
publishes two coordination signals that robot_2's demo script subscribes to:

  /demo/robot2_gate  (std_msgs/Bool, TRANSIENT_LOCAL)
      False initially.  Set to True when robot_1 has advanced far enough
      along its path that robot_2 can safely depart without entering the
      shared corridor while robot_1 is still in it (adaptive stagger).

  /demo/robot2_yield (std_msgs/Bool)
      False initially.  Set to True when the inter-robot distance drops
      below YIELD_TRIGGER_M; back to False when it rises above RESUME_M.

Design notes
------------
- Only pub/sub topics are used — no cross-pod service or action calls
  (those do not work through Zenoh because the reply cannot be routed).
- All Nav2 action calls (cancelTask / goToPose) happen on robot_2's OWN
  pod via its local demo script (meet_demo.py --namespace robot_2).
- TRANSIENT_LOCAL QoS on gate_pub ensures robot_2 receives the current
  gate state even if it subscribes after the coordinator started.

Run from the Gazebo pod:
    python3 /tmp/coordinator.py
"""

import math
import sys

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile
from geometry_msgs.msg import PoseWithCovarianceStamped
from std_msgs.msg import Bool


# ── Tuning ────────────────────────────────────────────────────────────────────

# Path from robot_1's spawn toward its goal.
# robot_1: (-2, -0.5) → (2, 0.5),  direction vector = (4, 1) / ||(4,1)||
_PATH_LEN = math.hypot(4.0, 1.0)   # ≈ 4.123 m (straight-line)
ROBOT1_SPAWN_X   = -2.0
ROBOT1_SPAWN_Y   = -0.5
ROBOT1_PATH_UX   = 4.0 / _PATH_LEN   # unit direction x
ROBOT1_PATH_UY   = 1.0 / _PATH_LEN   # unit direction y

# robot_2 gate opens when robot_1 is this many metres along its path.
# Observed full traversal ≈ 4.8 m (DWB routes around obstacles).
# 3.5 m = ~73% of path: robot_1 is past the main crossing zone.
DEPARTURE_THRESHOLD_M = 3.5

# Yield / resume thresholds (map-frame Euclidean metres)
YIELD_TRIGGER_M  = 2.0   # yield earlier — before they're deep in each other's LiDAR
RESUME_TRIGGER_M = 3.0


# ── Coordinator node ──────────────────────────────────────────────────────────

class Coordinator(Node):

    def __init__(self):
        super().__init__('demo_coordinator')

        self._r1_pos   = None   # robot_1 PosePosition
        self._r2_pos   = None   # robot_2 PosePosition
        self._gate_open = False
        self._yielding  = False

        # Use BEST_EFFORT VOLATILE for cross-pod delivery via Zenoh.
        # TRANSIENT_LOCAL is NOT reliably delivered cross-pod: the Zenoh bridge
        # creates a VOLATILE local DDS publisher, so late subscribers miss the
        # cached message (same issue seen with /robot_N/tf_static).
        # With VOLATILE, the 0.5 s timer re-publishes the current state
        # continuously so robot_2 receives it within one spin cycle.
        be_qos = QoSProfile(depth=10)

        self.create_subscription(
            PoseWithCovarianceStamped,
            '/robot_1/amcl_pose', self._r1_cb, be_qos)
        self.create_subscription(
            PoseWithCovarianceStamped,
            '/robot_2/amcl_pose', self._r2_cb, be_qos)

        self._gate_pub  = self.create_publisher(Bool, '/demo/robot2_gate',  be_qos)
        self._yield_pub = self.create_publisher(Bool, '/demo/robot2_yield', be_qos)

        # Publish initial closed state so robot_2 receives it on subscribe
        self._gate_pub.publish(Bool(data=False))
        self._yield_pub.publish(Bool(data=False))

        self.create_timer(0.5, self._update)
        self.get_logger().info(
            f'Coordinator ready.  '
            f'Gate opens when robot_1 progress ≥ {DEPARTURE_THRESHOLD_M} m.  '
            f'Yield triggers at {YIELD_TRIGGER_M} m, '
            f'resumes at {RESUME_TRIGGER_M} m.')

    # ── Subscription callbacks ────────────────────────────────────────────────

    def _r1_cb(self, msg: PoseWithCovarianceStamped):
        self._r1_pos = msg.pose.pose.position

    def _r2_cb(self, msg: PoseWithCovarianceStamped):
        self._r2_pos = msg.pose.pose.position

    # ── Control loop ──────────────────────────────────────────────────────────

    def _robot1_progress(self) -> float:
        """Metres of robot_1 progress along its spawn→goal path."""
        if self._r1_pos is None:
            return 0.0
        dx = self._r1_pos.x - ROBOT1_SPAWN_X
        dy = self._r1_pos.y - ROBOT1_SPAWN_Y
        return dx * ROBOT1_PATH_UX + dy * ROBOT1_PATH_UY

    def _update(self):
        progress = self._robot1_progress()

        # ── Departure gate ────────────────────────────────────────────────────
        if not self._gate_open and progress >= DEPARTURE_THRESHOLD_M:
            self._gate_open = True
            self.get_logger().info(
                f'[GATE OPEN] robot_1 at {progress:.2f} m — robot_2 may depart')
        # Re-publish on every tick so cross-pod VOLATILE subscribers receive it
        self._gate_pub.publish(Bool(data=self._gate_open))

        # ── Yield / resume signal ─────────────────────────────────────────────
        if self._r1_pos is not None and self._r2_pos is not None:
            dist = math.hypot(
                self._r1_pos.x - self._r2_pos.x,
                self._r1_pos.y - self._r2_pos.y,
            )

            if not self._yielding and dist < YIELD_TRIGGER_M:
                self._yielding = True
                self._yield_pub.publish(Bool(data=True))
                self.get_logger().info(
                    f'[YIELD] robots at {dist:.2f} m — signalling robot_2 to pause')

            elif self._yielding and dist > RESUME_TRIGGER_M:
                self._yielding = False
                self._yield_pub.publish(Bool(data=False))
                self.get_logger().info(
                    f'[RESUME] separation {dist:.2f} m — signalling robot_2 to continue')

            self.get_logger().info(
                f'r1_prog={progress:.2f} m  dist={dist:.2f} m  '
                f'gate={"OPEN" if self._gate_open else "closed"}  '
                f'yield={self._yielding}')
        else:
            self.get_logger().info(
                f'r1_prog={progress:.2f} m  gate={"OPEN" if self._gate_open else "closed"}'
                f'  (waiting for amcl_pose...)')


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    rclpy.init()
    node = Coordinator()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
