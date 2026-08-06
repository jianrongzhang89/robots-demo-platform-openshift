#!/usr/bin/env python3
"""
Nav2 RMF relay — Architecture A (RMF as orchestrator, Nav2 map-aware planning).

1. Navigation relay: subscribes to /rmf_navigate_cmd (std_msgs/String:
   "GOAL_ID X Y YAW" or "GOAL_ID CANCEL"). Forwards each goal to Nav2's
   navigate_to_pose action server which plans a map-aware, obstacle-avoiding
   path using the tb3_sandbox.pgm costmap and the DWB controller.

2. Clock relay: subscribes to /clock_bridge and republishes as /clock with
   a monotonic filter that drops backward timestamps, preventing TF2 buffer
   clears that would break planner/BT pose lookups.

Three improvements retained from the debugging session:

  a) CANCEL-ignore: RMF always follows CANCEL with NAVIGATE for the same
     destination. Ignoring CANCEL keeps the running Nav2 goal alive so the
     DWB controller is not restarted (restarting resets its state and may
     trigger the RotateToGoal spin-up again).

  b) _finish race fix: when same-destination transfers update self._rmf_id
     (A → A′), the old _on_result(A) check "self._rmf_id == A" fails and the
     handle stays set indefinitely. Fix: always clear state, publish using the
     CURRENT rmf_id (self._rmf_id or the callback's rmf_id).

  c) Monotonic clock filter: drops sim-clock messages that go backward,
     preventing the TF2 buffer from being cleared mid-navigation.

IMPORTANT: zenoh-python must NOT be imported in this process. The external
keepalive in entrypoint-nav2.sh subscribes to robot_N/cmd_vel via a separate
Python process to maintain the DDS→Zenoh cmd_vel route without causing the
rclpy+zenoh segfault.
"""
import math
import os
import threading
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from std_msgs.msg import String
from rosgraph_msgs.msg import Clock
from geometry_msgs.msg import PoseStamped, Twist
from nav2_msgs.action import NavigateToPose

DEST_TOL = 0.15          # m — same-destination transfer radius
SERVER_TIMEOUT = 15.0    # s — wait for action server at startup
FAIL_COOLDOWN = 5.0      # s — pause after rapid-abort to let bt_navigator recover

NAV_ACTION = "navigate_to_pose"


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

        self._nav_client = ActionClient(self, NavigateToPose, NAV_ACTION)

        # Zero-velocity heartbeat keeps the nav-bridge DDS→Zenoh cmd_vel route
        # alive so the bridge doesn't retire it between goals.
        self._cmd_vel_pub = self.create_publisher(Twist, "/cmd_vel", 10)
        self.create_timer(5.0, lambda: self._cmd_vel_pub.publish(Twist()))

        # Mission state — guarded by _lock
        self._lock = threading.Lock()
        self._rmf_id: str | None = None
        self._dest: tuple[float, float] | None = None
        self._handle = None
        self._last_fail_time: float = 0.0  # timestamp of last FAILED result

        # Clock relay: /clock_bridge → /clock (monotonic filter)
        self._last_clock_ns: int = 0
        clock_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT,
                                history=HistoryPolicy.KEEP_LAST)
        self._clock_pub = self.create_publisher(Clock, "/clock", clock_qos)
        self._clock_sub = self.create_subscription(
            Clock, "/clock_bridge", self._on_clock_bridge, clock_qos
        )

        self.get_logger().info("[nav_relay] Ready (Nav2 ActionClient mode).")

    # ── Clock relay ──────────────────────────────────────────────────────────

    def _on_clock_bridge(self, msg: Clock) -> None:
        ns = msg.clock.sec * 1_000_000_000 + msg.clock.nanosec
        if ns < self._last_clock_ns:
            return  # drop backward jump — prevents TF2 buffer clears
        self._last_clock_ns = ns
        self._clock_pub.publish(msg)

    # ── Command handler ──────────────────────────────────────────────────────

    def _on_cmd(self, msg: String) -> None:
        parts = msg.data.strip().split()
        if len(parts) < 2:
            return
        rmf_id = parts[0]

        # CANCEL-ignore: RMF always follows CANCEL with NAVIGATE for the same
        # destination. Ignoring keeps the running DWB controller alive so it
        # is not forced to restart (which would re-trigger RotateToGoal).
        if parts[1] == "CANCEL":
            self.get_logger().info(
                f"[nav_relay] goal {rmf_id} CANCEL ignored (await NAVIGATE)")
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

            # Check _dest alone (not _handle): _handle is None between
            # send_goal_async() and _on_accepted() — a window >0.8s over Zenoh.
            # If _handle is required, every 0.8s retry starts a NEW Nav2 goal,
            # causing a preemption cascade that prevents the controller from running.
            same = False
            if self._dest is not None:
                dx, dy = self._dest[0] - x, self._dest[1] - y
                same = (dx * dx + dy * dy) < DEST_TOL * DEST_TOL

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

    # ── Nav2 goal lifecycle ──────────────────────────────────────────────────

    def _run_goal(self, rmf_id: str, x: float, y: float, yaw: float) -> None:
        # If the previous goal failed very recently (rapid-abort loop from
        # bt_navigator crash/restart), pause to allow the lifecycle to recover.
        import time as _time
        with self._lock:
            elapsed = _time.monotonic() - self._last_fail_time
        if elapsed < FAIL_COOLDOWN:
            remaining = FAIL_COOLDOWN - elapsed
            self.get_logger().info(
                f"[nav_relay] {rmf_id}: cooldown {remaining:.1f}s after rapid abort"
            )
            _time.sleep(remaining)
            with self._lock:
                if self._rmf_id != rmf_id:
                    return  # superseded during cooldown

        if not self._nav_client.wait_for_server(timeout_sec=SERVER_TIMEOUT):
            self.get_logger().warn("[nav_relay] navigate_to_pose server not available")
            self._finish(rmf_id, False)
            return

        with self._lock:
            if self._rmf_id != rmf_id:
                return  # superseded before we started

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
        send_future.add_done_callback(
            lambda f: self._on_accepted(f, rmf_id, dest)
        )

    def _on_accepted(self, future, rmf_id: str, dest: tuple) -> None:
        handle = future.result()
        if not handle.accepted:
            self.get_logger().warn(f"[nav_relay] {rmf_id} rejected by Nav2")
            self._finish(rmf_id, False)
            return

        with self._lock:
            if self._dest == dest:
                self._handle = handle
            else:
                # Superseded by a different destination while we were waiting
                try:
                    handle.cancel_goal_async()
                except Exception:
                    pass
                return

        handle.get_result_async().add_done_callback(
            lambda f: self._on_result(f, rmf_id, handle)
        )

    def _on_result(self, future, rmf_id: str, handle) -> None:
        from action_msgs.msg import GoalStatus
        status = future.result().status
        success = (status == GoalStatus.STATUS_SUCCEEDED)
        self.get_logger().info(
            f"[nav_relay] {rmf_id}: {'SUCCEEDED' if success else 'FAILED'} "
            f"(status={status})"
        )

        with self._lock:
            if self._handle is handle:
                # This result is for our CURRENT active Nav2 goal — clear state.
                # Use the most-recently-transferred rmf_id so RMF gets the result
                # for the goal it is currently tracking (after same-dest transfers
                # A → A′ → A″, _rmf_id is A″ even though the handle belongs to A).
                report_id = self._rmf_id if self._rmf_id is not None else rmf_id
                self._rmf_id = None
                self._dest = None
                self._handle = None
            else:
                # Stale result from a superseded goal (e.g., an old preempted goal
                # whose cancel/abort arrives after we started a new goal).
                # Do NOT clear state — the new goal is still running.
                report_id = rmf_id

        self._finish(report_id, success)

    def _finish(self, rmf_id: str, success: bool) -> None:
        import time as _time
        if not success:
            self._last_fail_time = _time.monotonic()
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
