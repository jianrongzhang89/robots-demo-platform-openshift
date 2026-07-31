#!/usr/bin/env python3
"""
Nav2 RMF relay — navigation + monotonic clock relay combined.

1. Navigation relay: subscribes to /rmf_navigate_cmd (std_msgs/String:
   "GOAL_ID X Y YAW" or "GOAL_ID CANCEL"), calls the local /navigate_to_pose
   action, and publishes the result to /rmf_navigate_result.

2. Clock relay: subscribes to /clock_mono (the monotonic sim clock delivered
   by the bridge from robot_N/clock_mono), filters backwards timestamps, and
   republishes to /clock. This prevents tf2 "jump back in time" buffer clears
   that prevent Nav2 lifecycle activation.
"""
import math
import threading
import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.action import ActionClient
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from std_msgs.msg import String
from rosgraph_msgs.msg import Clock
from nav2_msgs.action import NavigateToPose
from geometry_msgs.msg import PoseStamped


class NavRelay(Node):
    def __init__(self):
        super().__init__(
            "nav2_rmf_relay",
            parameter_overrides=[Parameter("use_sim_time", value=True)],
        )
        nav_qos = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
        )
        self._pub = self.create_publisher(String, "/rmf_navigate_result", nav_qos)
        self._sub = self.create_subscription(
            String, "/rmf_navigate_cmd", self._on_cmd, nav_qos
        )
        self._nav = ActionClient(self, NavigateToPose, "/navigate_to_pose")
        self._lock = threading.Lock()
        self._active_goal_handle = None
        self._active_goal_id = None


        # Monotonic clock relay: /clock_bridge (from clock-bridge sidecar) -> /clock
        # The clock-bridge sidecar (namespace /clock_relay) delivers the monotonic
        # filtered clock from Zenoh clock_relay/clock_bridge -> local /clock_bridge.
        # This relay re-publishes it as /clock (what Nav2 nodes subscribe to).
        # No loop: nav2_relay publishes to /clock but subscribes to /clock_bridge.
        clock_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
        )
        self._clock_pub = self.create_publisher(Clock, "/clock", clock_qos)
        self._clock_sub = self.create_subscription(
            Clock, "/clock_bridge", self._on_clock_bridge, clock_qos
        )

        self.get_logger().info("[nav_relay] Ready on /rmf_navigate_cmd + /clock_bridge->clock")

    def _on_clock_bridge(self, msg: Clock) -> None:
        self._clock_pub.publish(msg)

    def _on_cmd(self, msg: String) -> None:
        parts = msg.data.strip().split()
        if len(parts) < 2:
            self.get_logger().warn(f"[nav_relay] Bad cmd: {msg.data!r}")
            return

        goal_id = parts[0]

        if parts[1] == "CANCEL":
            self._cancel(goal_id)
            return

        if len(parts) != 4:
            self.get_logger().warn(f"[nav_relay] Expected 'GOAL_ID X Y YAW', got: {msg.data!r}")
            return

        try:
            x, y, yaw = float(parts[1]), float(parts[2]), float(parts[3])
        except ValueError:
            self.get_logger().warn(f"[nav_relay] Bad pose values: {msg.data!r}")
            return

        self.get_logger().info(
            f"[nav_relay] goal {goal_id}: navigate to ({x:.3f}, {y:.3f}, {yaw:.3f})"
        )

        # Cancel any ongoing goal
        with self._lock:
            if self._active_goal_handle is not None:
                try:
                    self._active_goal_handle.cancel_goal_async()
                except Exception:
                    pass
            self._active_goal_handle = None
            self._active_goal_id = goal_id

        if not self._nav.wait_for_server(timeout_sec=5.0):
            self.get_logger().error("[nav_relay] navigate_to_pose server not available")
            self._publish_result(goal_id, False)
            return

        goal = NavigateToPose.Goal()
        goal.pose = PoseStamped()
        goal.pose.header.frame_id = "map"
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.pose.position.x = x
        goal.pose.pose.position.y = y
        goal.pose.pose.orientation.z = math.sin(yaw / 2.0)
        goal.pose.pose.orientation.w = math.cos(yaw / 2.0)

        send_future = self._nav.send_goal_async(goal)
        send_future.add_done_callback(
            lambda f: self._on_goal_response(f, goal_id)
        )

    def _on_goal_response(self, future, goal_id: str) -> None:
        handle = future.result()
        if not handle.accepted:
            self.get_logger().warn(f"[nav_relay] goal {goal_id} rejected by Nav2")
            # Brief backoff before reporting failure: when bt_navigator is briefly
            # inactive (e.g., recovering from a TF clear), rapid-fire rejections
            # storm the action server and prevent it from stabilizing.
            # A 3-second delay lets bt_navigator recover before the adapter replans.
            def delayed_fail():
                import time
                time.sleep(3.0)
                with self._lock:
                    if self._active_goal_id == goal_id:
                        self._publish_result(goal_id, False)
            import threading
            threading.Thread(target=delayed_fail, daemon=True).start()
            return

        with self._lock:
            if self._active_goal_id != goal_id:
                # A newer goal was issued — cancel this one
                try:
                    handle.cancel_goal()
                except Exception:
                    pass
                return
            self._active_goal_handle = handle

        result_future = handle.get_result_async()
        result_future.add_done_callback(
            lambda f: self._on_result(f, goal_id)
        )

    def _on_result(self, future, goal_id: str) -> None:
        with self._lock:
            if self._active_goal_id != goal_id:
                return  # superseded
        try:
            result = future.result()
            # GoalStatus: 4 = SUCCEEDED
            success = result.status == 4
        except Exception as e:
            self.get_logger().error(f"[nav_relay] result error for {goal_id}: {e}")
            success = False

        self._publish_result(goal_id, success)

    def _publish_result(self, goal_id: str, success: bool) -> None:
        msg = String()
        msg.data = f"{goal_id} {'OK' if success else 'FAILED'}"
        self._pub.publish(msg)
        self.get_logger().info(f"[nav_relay] result: {msg.data}")

    def _cancel(self, goal_id: str) -> None:
        with self._lock:
            if self._active_goal_id == goal_id and self._active_goal_handle is not None:
                try:
                    self._active_goal_handle.cancel_goal_async()
                except Exception:
                    pass
                self._active_goal_handle = None
                self._active_goal_id = None
        self.get_logger().info(f"[nav_relay] goal {goal_id} canceled")


def main():
    rclpy.init()
    node = NavRelay()
    rclpy.spin(node)


if __name__ == "__main__":
    main()
