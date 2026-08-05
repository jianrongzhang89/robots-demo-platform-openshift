#!/usr/bin/env python3
"""
Nav2 RMF relay — Architecture A (RMF as orchestrator).

1. Navigation relay: subscribes to /rmf_navigate_cmd (std_msgs/String:
   "GOAL_ID X Y YAW" or "GOAL_ID CANCEL"). Uses an AMCL-feedback
   P-controller to navigate to each waypoint. This approach is more
   reliable than the Nav2 ActionClient in the distributed cross-pod setup,
   where DWB generates zero velocity due to planner timeouts and TF clock
   extrapolation errors.

2. Clock relay: subscribes to /clock_bridge and republishes as /clock with
   a monotonic filter to prevent TF2 buffer clears from backward clock jumps.

Architecture A is preserved: RMF dispatches tasks → free_fleet_adapter →
Zenoh → THIS relay → cmd_vel → Gazebo. The relay publishes
/rmf_navigate_result so RMF knows when each waypoint is reached.
"""
import math
import threading
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from std_msgs.msg import String
from rosgraph_msgs.msg import Clock
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry

# P-controller gains
KP_LIN = 0.3          # linear velocity gain
KP_ANG = 1.2          # angular velocity gain
MAX_LIN = 0.26        # m/s
MAX_ANG = 1.0         # rad/s
GOAL_TOL_M = 0.25     # m — same as Nav2 xy_goal_tolerance
CTRL_HZ = 20          # control loop frequency

DEST_TOL = 0.15       # m — same-destination transfer radius


class NavRelay(Node):
    def __init__(self):
        super().__init__("nav2_rmf_relay")

        nav_qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE,
                              history=HistoryPolicy.KEEP_LAST)
        self._result_pub = self.create_publisher(String, "/rmf_navigate_result", nav_qos)
        self._cmd_sub = self.create_subscription(
            String, "/rmf_navigate_cmd", self._on_cmd,
            QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT,
                       history=HistoryPolicy.KEEP_LAST),
        )

        # cmd_vel publisher — P-controller output
        self._cmd_vel_pub = self.create_publisher(Twist, "/cmd_vel", 10)

        # Heartbeat: keep zenoh-bridge DDS→Zenoh route for cmd_vel alive
        self.create_timer(5.0, lambda: self._cmd_vel_pub.publish(Twist()))

        # AMCL pose subscriber for position feedback
        amcl_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT,
                               history=HistoryPolicy.KEEP_LAST)
        self._odom_sub = self.create_subscription(
            Odometry, "/odom", self._on_odom, amcl_qos
        )

        # Pose state (from /odom)
        self._pose_lock = threading.Lock()
        self._x: float = 0.0
        self._y: float = 0.0
        self._yaw: float = 0.0
        self._have_pose: bool = False

        # Mission state
        self._lock = threading.Lock()
        self._rmf_id: str | None = None
        self._dest: tuple[float, float] | None = None
        self._active: bool = False

        # Control loop timer
        self.create_timer(1.0 / CTRL_HZ, self._ctrl_tick)

        # Clock relay: /clock_bridge -> /clock (monotonic filter)
        self._last_clock_ns: int = 0
        clock_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT,
                                history=HistoryPolicy.KEEP_LAST)
        self._clock_pub = self.create_publisher(Clock, "/clock", clock_qos)
        self._clock_sub = self.create_subscription(
            Clock, "/clock_bridge", self._on_clock_bridge, clock_qos
        )

        self.get_logger().info("[nav_relay] Ready (P-controller mode).")

    # ── Clock relay ─────────────────────────────────────────────────────────

    def _on_clock_bridge(self, msg: Clock) -> None:
        ns = msg.clock.sec * 1_000_000_000 + msg.clock.nanosec
        if ns < self._last_clock_ns:
            return  # drop backward jump to prevent TF2 buffer clears
        self._last_clock_ns = ns
        self._clock_pub.publish(msg)

    # ── Odometry ─────────────────────────────────────────────────────────────

    def _on_odom(self, msg: Odometry) -> None:
        q = msg.pose.pose.orientation
        siny = 2.0 * (q.w * q.z + q.x * q.y)
        cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        with self._pose_lock:
            self._x = msg.pose.pose.position.x
            self._y = msg.pose.pose.position.y
            self._yaw = math.atan2(siny, cosy)
            self._have_pose = True

    # ── Command handler ──────────────────────────────────────────────────────

    def _on_cmd(self, msg: String) -> None:
        parts = msg.data.strip().split()
        if len(parts) < 2:
            return
        rmf_id = parts[0]

        # CANCEL ignored: RMF always follows CANCEL with a new NAVIGATE.
        # The subsequent NAVIGATE triggers same-destination transfer or
        # a fresh goal, keeping navigation uninterrupted.
        if parts[1] == "CANCEL":
            self.get_logger().info(f"[nav_relay] goal {rmf_id} CANCEL ignored (await NAVIGATE)")
            return

        if len(parts) != 4:
            return
        try:
            x, y, yaw = float(parts[1]), float(parts[2]), float(parts[3])
        except ValueError:
            return

        new_dest = (x, y)

        with self._lock:
            if self._rmf_id == rmf_id:
                return  # exact duplicate

            same = False
            if self._dest is not None and self._active:
                dx, dy = self._dest[0] - x, self._dest[1] - y
                same = (dx*dx + dy*dy) < DEST_TOL * DEST_TOL

            if same:
                self.get_logger().info(
                    f"[nav_relay] {rmf_id}: same dest ({x:.2f},{y:.2f}), "
                    f"transferring from {self._rmf_id}"
                )
                self._rmf_id = rmf_id
                return

            self._rmf_id = rmf_id
            self._dest = new_dest
            self._active = True

        self.get_logger().info(f"[nav_relay] {rmf_id}: navigate ({x:.2f},{y:.2f})")

    # ── P-controller loop ─────────────────────────────────────────────────────

    def _ctrl_tick(self) -> None:
        with self._lock:
            if not self._active:
                return
            rmf_id = self._rmf_id
            dest = self._dest

        if dest is None or rmf_id is None:
            return

        with self._pose_lock:
            if not self._have_pose:
                return
            cx, cy, cyaw = self._x, self._y, self._yaw

        gx, gy = dest
        dx, dy = gx - cx, gy - cy
        dist = math.hypot(dx, dy)

        if dist < GOAL_TOL_M:
            # Goal reached
            self._cmd_vel_pub.publish(Twist())  # stop
            with self._lock:
                if self._rmf_id == rmf_id:
                    self._active = False
                    self._rmf_id = None
                    self._dest = None
            self.get_logger().info(f"[nav_relay] {rmf_id}: REACHED ({gx:.2f},{gy:.2f})")
            self._publish_result(rmf_id, True)
            return

        # P-controller
        angle_to_goal = math.atan2(dy, dx)
        angle_err = angle_to_goal - cyaw
        # Normalize to [-pi, pi]
        while angle_err > math.pi:
            angle_err -= 2 * math.pi
        while angle_err < -math.pi:
            angle_err += 2 * math.pi

        v_lin = min(KP_LIN * dist, MAX_LIN)
        v_ang = max(-MAX_ANG, min(KP_ANG * angle_err, MAX_ANG))

        # Slow down when heading is badly wrong (> 60°)
        if abs(angle_err) > math.pi / 3:
            v_lin *= 0.3

        twist = Twist()
        twist.linear.x = v_lin
        twist.angular.z = v_ang
        self._cmd_vel_pub.publish(twist)

    def _publish_result(self, rmf_id: str, success: bool) -> None:
        msg = String()
        msg.data = f"{rmf_id} {'OK' if success else 'FAILED'}"
        self._result_pub.publish(msg)
        self.get_logger().info(f"[nav_relay] result: {msg.data}")


def main():
    rclpy.init()
    node = NavRelay()
    rclpy.spin(node)


if __name__ == "__main__":
    main()
