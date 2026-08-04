#!/usr/bin/env python3
"""
Nav2 RMF relay — Architecture A (RMF as orchestrator, Nav2 map-aware planning).

1. Navigation relay: subscribes to /rmf_navigate_cmd (std_msgs/String:
   "GOAL_ID X Y YAW" or "GOAL_ID CANCEL"). Forwards each goal to Nav2's
   navigate_to_pose action server which plans a map-aware, obstacle-avoiding
   path using the tb3_sandbox.pgm costmap and the MPPI controller.

2. Clock relay: subscribes to /clock_bridge and republishes as /clock so
   Nav2 nodes receive the sim clock.

Design: a single "active Nav2 mission" tracks (dest_x, dest_y, rmf_goal_id).
When the RMF adapter sends a new goal_id for the SAME destination, only the
rmf_goal_id is updated — the running Nav2 goal is kept alive.  A genuinely
new destination cancels the current Nav2 goal and starts a fresh one.

IMPORTANT: the Zenoh cmd_vel keepalive runs as a SEPARATE Python process in
entrypoint-nav2.sh.  It cannot run in this process because zenoh-python +
rclpy (CycloneDDS) in the same Python process causes segfaults.
"""
import math
import threading
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from std_msgs.msg import String
from rosgraph_msgs.msg import Clock
from geometry_msgs.msg import PoseStamped, Twist
from nav2_msgs.action import NavigateToPose

DEST_TOL = 0.15          # m — destinations within this radius are "the same"
SERVER_TIMEOUT = 15.0    # s — wait for action server


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

        self._nav_client = ActionClient(self, NavigateToPose, "navigate_to_pose")

        # DDS /cmd_vel publisher: publishes zero-velocity heartbeat so the nav
        # bridge always sees a DDS publisher and maintains the DDS→Zenoh route.
        self._cmd_vel_pub = self.create_publisher(Twist, "/cmd_vel", 10)
        self.create_timer(5.0, lambda: self._cmd_vel_pub.publish(Twist()))

        # Mission state — guarded by _lock
        self._lock = threading.Lock()
        self._rmf_id: str | None = None
        self._dest: tuple[float, float] | None = None
        self._handle = None

        # Clock relay: /clock_bridge -> /clock
        clock_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT,
                                history=HistoryPolicy.KEEP_LAST)
        self._clock_pub = self.create_publisher(Clock, "/clock", clock_qos)
        self._clock_sub = self.create_subscription(
            Clock, "/clock_bridge", self._on_clock_bridge, clock_qos
        )

        self.get_logger().info("[nav_relay] Ready (Nav2 action-client mode).")

    def _on_clock_bridge(self, msg: Clock) -> None:
        self._clock_pub.publish(msg)

    def _on_cmd(self, msg: String) -> None:
        parts = msg.data.strip().split()
        if len(parts) < 2:
            return
        rmf_id = parts[0]

        if parts[1] == "CANCEL":
            with self._lock:
                if self._rmf_id == rmf_id:
                    handle = self._handle
                    self._rmf_id = None
                    self._dest = None
                    self._handle = None
                else:
                    handle = None
            if handle is not None:
                try:
                    handle.cancel_goal_async()
                except Exception:
                    pass
            self.get_logger().info(f"[nav_relay] goal {rmf_id} canceled")
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
                return  # exact duplicate retry

            same = False
            if self._dest is not None and self._handle is not None:
                dx, dy = self._dest[0] - x, self._dest[1] - y
                same = (dx*dx + dy*dy) < DEST_TOL * DEST_TOL

            if same:
                self.get_logger().info(
                    f"[nav_relay] {rmf_id}: same dest ({x:.2f},{y:.2f}), "
                    f"transferring from {self._rmf_id}"
                )
                self._rmf_id = rmf_id
                return

            old_handle = self._handle
            self._rmf_id = rmf_id
            self._dest = new_dest
            self._handle = None

        if old_handle is not None:
            try:
                old_handle.cancel_goal_async()
            except Exception:
                pass

        self.get_logger().info(
            f"[nav_relay] {rmf_id}: navigate_to_pose ({x:.2f},{y:.2f}) yaw={yaw:.2f}"
        )
        threading.Thread(
            target=self._run_goal, args=(rmf_id, x, y, yaw), daemon=True
        ).start()

    def _run_goal(self, rmf_id: str, x: float, y: float, yaw: float) -> None:
        if not self._nav_client.wait_for_server(timeout_sec=SERVER_TIMEOUT):
            self.get_logger().warn("[nav_relay] navigate_to_pose server not available")
            self._finish(rmf_id, False)
            return

        with self._lock:
            if self._rmf_id != rmf_id:
                return

        goal = NavigateToPose.Goal()
        goal.pose = PoseStamped()
        goal.pose.header.frame_id = "map"
        goal.pose.header.stamp.sec = 0  # use latest available transform
        goal.pose.pose.position.x = x
        goal.pose.pose.position.y = y
        goal.pose.pose.orientation.z = math.sin(yaw / 2.0)
        goal.pose.pose.orientation.w = math.cos(yaw / 2.0)

        dest = (x, y)
        send_future = self._nav_client.send_goal_async(goal)
        send_future.add_done_callback(lambda f: self._on_accepted(f, rmf_id, dest))

    def _on_accepted(self, future, rmf_id: str, dest: tuple) -> None:
        handle = future.result()
        if not handle.accepted:
            self.get_logger().warn(f"[nav_relay] {rmf_id} rejected by Nav2")
            self._finish(rmf_id, False)
            return

        with self._lock:
            dest_still_current = (self._dest == dest)
            if dest_still_current:
                self._handle = handle
            else:
                try:
                    handle.cancel_goal_async()
                except Exception:
                    pass
                return

        handle.get_result_async().add_done_callback(
            lambda f: self._on_result(f, rmf_id)
        )

    def _on_result(self, future, rmf_id: str) -> None:
        from action_msgs.msg import GoalStatus
        status = future.result().status
        success = (status == GoalStatus.STATUS_SUCCEEDED)
        self.get_logger().info(
            f"[nav_relay] {rmf_id}: {'SUCCEEDED' if success else 'FAILED'} (status={status})"
        )
        self._finish(rmf_id, success)

    def _finish(self, rmf_id: str, success: bool) -> None:
        with self._lock:
            if self._rmf_id == rmf_id:
                self._rmf_id = None
                self._dest = None
                self._handle = None
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
