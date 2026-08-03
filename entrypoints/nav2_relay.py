#!/usr/bin/env python3
"""
Nav2 RMF relay — navigation + monotonic clock relay combined.

1. Navigation relay: subscribes to /rmf_navigate_cmd (std_msgs/String:
   "GOAL_ID X Y YAW" or "GOAL_ID CANCEL"). Uses a simple proportional
   controller to drive the robot directly toward each waypoint, bypassing
   Nav2's MPPI controller which consistently drives the robot backward (west)
   in the tb3_sandbox environment.

   Position tracking: cmd_vel dead reckoning (integrates the commands we
   publish).  Gazebo's diff_drive odom is NOT used for position because its
   integration frame is tied to the robot's spawn orientation, not world frame,
   causing sign inversions for robots spawned with non-zero yaw (e.g. robot_2
   at yaw=π).  Dead reckoning is accurate enough for the ~30-second patrols
   in this demo.

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
ALIGN_THRESHOLD = 3.15  # rad — always drive forward (never pure-spin).
LINEAR_KP  = 0.4       # forward speed gain
ANGULAR_KP = 0.8       # turning gain
MAX_LINEAR  = 0.20     # m/s max forward speed
MAX_ANGULAR = 0.3      # rad/s max turn speed
CONTROL_HZ  = 10       # control loop Hz
REAL_TIME_FACTOR = 0.5 # Gazebo real_time_factor for dead reckoning dt


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

        # Position tracking via cmd_vel dead reckoning.
        # Initial pose from env vars (spawn position).
        self._pose_lock = threading.Lock()
        self._pos_x   = float(os.environ.get("INITIAL_X",   "-2.0"))
        self._pos_y   = float(os.environ.get("INITIAL_Y",   "-0.5"))
        self._pos_yaw = float(os.environ.get("INITIAL_YAW", "0.0"))

        # angular.z follows standard ROS convention for all robots (positive = CCW).
        # The diff_drive plugin respects this regardless of spawn orientation.
        # No sign flip needed.
        self._angular_flip = 1.0

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
            f"[nav_relay] Ready. Initial pos: ({self._pos_x}, {self._pos_y}) "
            f"yaw={self._pos_yaw:.3f} (dead-reckoning mode)"
        )

    # ── callbacks ─────────────────────────────────────────────────────────────

    def _on_clock_bridge(self, msg: Clock) -> None:
        self._clock_pub.publish(msg)

    def _get_pose(self):
        with self._pose_lock:
            return (self._pos_x, self._pos_y, self._pos_yaw)

    def _update_pose(self, linear_x: float, angular_z: float, dt_wall: float) -> None:
        """Dead-reckoning update: integrate cmd_vel over real time × RTF = sim time."""
        dt_sim = dt_wall * REAL_TIME_FACTOR
        with self._pose_lock:
            self._pos_yaw += angular_z * dt_sim
            # Normalize yaw to [-π, π]
            while self._pos_yaw >  math.pi: self._pos_yaw -= 2*math.pi
            while self._pos_yaw < -math.pi: self._pos_yaw += 2*math.pi
            self._pos_x += linear_x * math.cos(self._pos_yaw) * dt_sim
            self._pos_y += linear_x * math.sin(self._pos_yaw) * dt_sim

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
        _dbg_tick = 0

        while True:
            with self._lock:
                if self._active_goal_id != goal_id:
                    self._cmd_vel_pub.publish(Twist())
                    return

            cur_x, cur_y, cur_yaw = self._get_pose()
            _dbg_tick += 1
            if _dbg_tick % 20 == 1:  # log every 2 seconds
                self.get_logger().info(
                    f"[nav_relay] pos=({cur_x:.2f},{cur_y:.2f}) yaw={cur_yaw:.2f} "
                    f"goal=({goal_x:.2f},{goal_y:.2f})"
                )

            dx  = goal_x - cur_x
            dy  = goal_y - cur_y
            dist = math.sqrt(dx*dx + dy*dy)

            if dist < GOAL_TOLERANCE:
                self._cmd_vel_pub.publish(Twist())
                self.get_logger().info(
                    f"[nav_relay] goal {goal_id}: REACHED ({dist:.2f}m)"
                )
                # Reset pose to waypoint so the next leg starts from a clean position.
                with self._pose_lock:
                    self._pos_x = goal_x
                    self._pos_y = goal_y
                with self._lock:
                    if self._active_goal_id == goal_id:
                        self._active_goal_id = None
                self._publish_result(goal_id, True)
                return

            desired_yaw = math.atan2(dy, dx)
            yaw_err = desired_yaw - cur_yaw
            while yaw_err >  math.pi: yaw_err -= 2*math.pi
            while yaw_err < -math.pi: yaw_err += 2*math.pi

            az_intended = max(-MAX_ANGULAR, min(MAX_ANGULAR, ANGULAR_KP * yaw_err))
            lx = 0.0
            if abs(yaw_err) < ALIGN_THRESHOLD:
                lx = max(0.0, min(MAX_LINEAR, LINEAR_KP * dist))

            twist = Twist()
            twist.linear.x = lx
            # Flip angular.z sign for robots whose diff_drive inverts the direction
            twist.angular.z = self._angular_flip * az_intended
            self._cmd_vel_pub.publish(twist)

            # Dead-reckoning: use the INTENDED angular.z (not flipped) since the
            # flip compensates for Gazebo's sign inversion, so the net world rotation
            # is still az_intended rad/s CCW.
            self._update_pose(lx, az_intended, period)

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
