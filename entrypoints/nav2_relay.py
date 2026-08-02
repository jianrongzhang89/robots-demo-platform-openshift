#!/usr/bin/env python3
"""
Nav2 RMF relay — navigation + monotonic clock relay combined.

1. Navigation relay: subscribes to /rmf_navigate_cmd (std_msgs/String:
   "GOAL_ID X Y YAW" or "GOAL_ID CANCEL"). Uses a simple proportional
   controller to drive the robot directly toward each waypoint, bypassing
   Nav2's MPPI controller which consistently drives the robot backward (west)
   in the tb3_sandbox environment.

2. Clock relay: subscribes to /clock_bridge and republishes as /clock so
   Nav2 nodes receive the sim clock.
"""
import math
import threading
import time
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from std_msgs.msg import String
from rosgraph_msgs.msg import Clock
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
import os

# P controller parameters
GOAL_TOLERANCE = 0.35  # m — stop when within this distance of goal
ALIGN_THRESHOLD = 0.5  # rad — drive forward only when roughly facing goal
LINEAR_KP  = 0.4       # forward speed gain
ANGULAR_KP = 1.2       # turning gain
MAX_LINEAR  = 0.20     # m/s max forward speed
MAX_ANGULAR = 0.6      # rad/s max turn speed
CONTROL_HZ  = 10       # control loop Hz


class NavRelay(Node):
    def __init__(self):
        super().__init__("nav2_rmf_relay")

        nav_qos = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
        )
        self._result_pub = self.create_publisher(String, "/rmf_navigate_result", nav_qos)
        self._cmd_sub = self.create_subscription(
            String, "/rmf_navigate_cmd", self._on_cmd,
            QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT,
                       history=HistoryPolicy.KEEP_LAST)
        )
        self._cmd_vel_pub = self.create_publisher(Twist, "/cmd_vel", 10)

        self._lock = threading.Lock()
        self._active_goal_id = None

        # Position: initial spawn (from env vars) + odom delta
        self._initial_x   = float(os.environ.get("INITIAL_X",   "-2.0"))
        self._initial_y   = float(os.environ.get("INITIAL_Y",   "-0.5"))
        self._initial_yaw = float(os.environ.get("INITIAL_YAW", "0.0"))
        self._pose_lock = threading.Lock()
        self._odom_x   = 0.0
        self._odom_y   = 0.0
        self._odom_yaw = self._initial_yaw

        self._odom_sub = self.create_subscription(
            Odometry, "/odom",
            self._on_odom,
            QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT,
                       history=HistoryPolicy.KEEP_LAST)
        )

        # Clock relay: /clock_bridge -> /clock
        clock_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
        )
        self._clock_pub = self.create_publisher(Clock, "/clock", clock_qos)
        self._clock_sub = self.create_subscription(
            Clock, "/clock_bridge", self._on_clock_bridge, clock_qos
        )

        self.get_logger().info(
            f"[nav_relay] Ready. Initial pos: ({self._initial_x}, {self._initial_y})"
        )

    # ── callbacks ─────────────────────────────────────────────────────────────

    def _on_clock_bridge(self, msg: Clock) -> None:
        self._clock_pub.publish(msg)

    def _on_odom(self, msg: Odometry) -> None:
        q = msg.pose.pose.orientation
        yaw = math.atan2(2*(q.w*q.z + q.x*q.y), 1 - 2*(q.y**2 + q.z**2))
        with self._pose_lock:
            self._odom_x   = msg.pose.pose.position.x
            self._odom_y   = msg.pose.pose.position.y
            self._odom_yaw = yaw

    def _get_pose(self):
        with self._pose_lock:
            return (self._initial_x + self._odom_x,
                    self._initial_y + self._odom_y,
                    self._odom_yaw)

    def _on_cmd(self, msg: String) -> None:
        parts = msg.data.strip().split()
        if len(parts) < 2:
            return
        goal_id = parts[0]

        if parts[1] == "CANCEL":
            with self._lock:
                if self._active_goal_id == goal_id:
                    self._active_goal_id = None
            self._cmd_vel_pub.publish(Twist())
            self.get_logger().info(f"[nav_relay] goal {goal_id} canceled")
            return

        if len(parts) != 4:
            return
        try:
            x, y = float(parts[1]), float(parts[2])
        except ValueError:
            return

        with self._lock:
            if self._active_goal_id == goal_id:
                return  # duplicate from retry — already running
            self._active_goal_id = goal_id

        self.get_logger().info(
            f"[nav_relay] goal {goal_id}: navigate to ({x:.3f}, {y:.3f})"
        )

        t = threading.Thread(
            target=self._control_loop, args=(goal_id, x, y), daemon=True
        )
        t.start()

    # ── control loop ──────────────────────────────────────────────────────────

    def _control_loop(self, goal_id: str, goal_x: float, goal_y: float) -> None:
        period = 1.0 / CONTROL_HZ
        time.sleep(0.2)  # let any previous loop stop

        while True:
            with self._lock:
                if self._active_goal_id != goal_id:
                    self._cmd_vel_pub.publish(Twist())
                    return

            cur_x, cur_y, cur_yaw = self._get_pose()

            dx  = goal_x - cur_x
            dy  = goal_y - cur_y
            dist = math.sqrt(dx*dx + dy*dy)

            if dist < GOAL_TOLERANCE:
                self._cmd_vel_pub.publish(Twist())
                self.get_logger().info(
                    f"[nav_relay] goal {goal_id}: REACHED ({dist:.2f}m)"
                )
                with self._lock:
                    if self._active_goal_id == goal_id:
                        self._active_goal_id = None
                self._publish_result(goal_id, True)
                return

            desired_yaw = math.atan2(dy, dx)
            yaw_err = desired_yaw - cur_yaw
            while yaw_err >  math.pi: yaw_err -= 2*math.pi
            while yaw_err < -math.pi: yaw_err += 2*math.pi

            twist = Twist()
            twist.angular.z = max(-MAX_ANGULAR, min(MAX_ANGULAR, ANGULAR_KP * yaw_err))
            if abs(yaw_err) < ALIGN_THRESHOLD:
                twist.linear.x = max(0.0, min(MAX_LINEAR, LINEAR_KP * dist))
            self._cmd_vel_pub.publish(twist)
            time.sleep(period)

    def _publish_result(self, goal_id: str, success: bool) -> None:
        msg = String()
        msg.data = f"{goal_id} {'OK' if success else 'FAILED'}"
        self._result_pub.publish(msg)
        self.get_logger().info(f"[nav_relay] result: {msg.data}")


def main():
    rclpy.init()
    node = NavRelay()
    rclpy.spin(node)


if __name__ == "__main__":
    main()
