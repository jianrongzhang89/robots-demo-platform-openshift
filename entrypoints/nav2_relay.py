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

  a) Timed CANCEL (2s): RMF responsive_wait sends CANCEL to stop a robot
     during negotiation. A 2s window separates this from same-dest CANCEL+
     NAVIGATE transfers. If NAVIGATE arrives within 2s, suppress cancel;
     otherwise execute it so the robot actually stops (enables negotiation).

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

DEST_TOL = 0.15           # m — same-destination transfer radius
SERVER_TIMEOUT = 15.0     # s — wait for action server at startup
FAIL_COOLDOWN = 5.0       # s — pause after rapid-abort to let bt_navigator recover
RECENT_OK_WINDOW = 10.0   # s — ignore retries of recently-completed destinations
RECENT_SENT_WINDOW = 25.0  # s — ignore retries of same dest within 25s of sending

# slam_toolbox localization: map frame = posegraph frame (origin = robot spawn).
# Goals from RMF are in world frame; Nav2 needs map frame = world - spawn offset.
import os as _os
_MAP_OFFSET_X = float(_os.environ.get("INITIAL_X", "0.0"))
_MAP_OFFSET_Y = float(_os.environ.get("INITIAL_Y", "0.0"))

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
        # Thread generation counter: incremented each time a new _run_goal thread
        # is spawned. Each thread captures its generation at spawn time and exits
        # if the generation has advanced (a newer thread superseded it).
        self._thread_gen: int = 0
        # Recently completed destination: when the fleet adapter's periodic dispatch
        # tick re-sends a goal to a waypoint the robot just finished navigating to,
        # the relay would preempt the NEXT leg with a spurious retry. Tracking the
        # last completed dest and immediately reporting success for retries prevents
        # this leg-1/leg-2 preemption race that appears at the start of each patrol.
        self._last_ok_dest: tuple[float, float] | None = None
        self._last_ok_time: float = 0.0
        # Recently SENT destination: set when _run_goal calls send_goal_async. Used
        # in _on_cmd to block fleet-adapter retries of the same destination within
        # RECENT_SENT_WINDOW seconds. Unlike _last_ok_dest (which requires actual
        # completion), this fires as soon as the goal is sent — covering the timing
        # window between goal-send and goal-completion where _last_ok_dest isn't set.
        # Window must be long enough to cover the fleet adapter's retry interval
        # (~0.8s) but shorter than the n_out→robot_1_home retry gap (~20s).
        self._last_sent_dest: tuple[float, float] | None = None
        self._last_sent_time: float = 0.0
        # Single-execution guard: prevents two zombie-fix threads from both sending
        # goals to bt_navigator simultaneously. When a thread is running _run_goal,
        # _run_active is True. New threads spawned during this window exit immediately.
        # Cleared when the thread exits (success, failure, or superseded).
        self._run_active: bool = False

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

        # Timed CANCEL: wait 2s before cancelling the active Nav2 goal.
        # RMF responsive_wait (negotiation yield) sends CANCEL without a
        # follow-up NAVIGATE — robot must actually stop for negotiation to work.
        # Same-dest transfers also send CANCEL then immediately send NAVIGATE.
        # A 2s window distinguishes: if NAVIGATE arrives in 2s, suppress cancel
        # (same-dest transfer); otherwise execute cancel (negotiation yield).
        if parts[1] == "CANCEL":
            cancel_rmf_id = rmf_id
            def _deferred_cancel():
                import time as _tc
                _tc.sleep(2.0)
                with self._lock:
                    if self._rmf_id != cancel_rmf_id:
                        self.get_logger().info(
                            f"[nav_relay] {cancel_rmf_id}: CANCEL suppressed "
                            f"(new goal arrived within 2s)")
                        return
                    old_handle = self._handle
                    self._rmf_id = None
                    self._dest = None
                    self._handle = None
                if old_handle is not None:
                    try:
                        old_handle.cancel_goal_async()
                    except Exception:
                        pass
                self.get_logger().info(
                    f"[nav_relay] {cancel_rmf_id}: CANCEL executed "
                    f"(RMF negotiation yield — no NAVIGATE in 2s)")
            threading.Thread(target=_deferred_cancel, daemon=True).start()
            return

        if len(parts) != 4:
            return
        try:
            x, y, yaw = float(parts[1]), float(parts[2]), float(parts[3])
        except ValueError:
            return

        new_dest = (x, y)

        import time as _time_cmd
        with self._lock:
            if self._rmf_id == rmf_id:
                return  # exact duplicate retry

            now_cmd = _time_cmd.monotonic()
            # Skip retries of recently completed destinations (RECENT_OK_WINDOW = 10s):
            # the free_fleet_adapter's execute loop re-sends the goal after completion,
            # and _on_result may not have fired yet. Immediately report OK.
            if self._last_ok_dest is not None:
                elapsed_ok = now_cmd - self._last_ok_time
                if elapsed_ok < RECENT_OK_WINDOW:
                    ox, oy = self._last_ok_dest
                    if (ox - x) ** 2 + (oy - y) ** 2 < DEST_TOL * DEST_TOL:
                        self.get_logger().info(
                            f"[nav_relay] {rmf_id}: retry of recently reached ({x:.2f},{y:.2f})"
                            f" — reporting OK immediately"
                        )
                        import threading as _thr
                        _dest = new_dest
                        _thr.Thread(target=lambda: self._finish(rmf_id, True, completed_dest=_dest),
                                    daemon=True).start()
                        return

            # Skip retries of recently SENT destinations (RECENT_SENT_WINDOW = 5s):
            # covers the gap between send_goal_async and _on_result where _last_ok_dest
            # isn't set. A retry arriving within 5s of sending the same goal is
            # the fleet adapter's execute loop re-publishing before the result arrives.
            # 5s is long enough to cover 0.8s retry intervals but short enough that
            # n_out retries (arriving every 20s) are NOT blocked.
            if self._last_sent_dest is not None:
                elapsed_sent = now_cmd - self._last_sent_time
                if elapsed_sent < RECENT_SENT_WINDOW:
                    sx, sy = self._last_sent_dest
                    if (sx - x) ** 2 + (sy - y) ** 2 < DEST_TOL * DEST_TOL:
                        # Only skip if this dest is NOT the current active goal.
                        # If the current active goal IS this dest, the same-dest check
                        # below handles it (no preemption). Reporting "OK immediately"
                        # for retries of the CURRENT active goal would prematurely
                        # call execution.finished(), advancing the patrol to the next
                        # waypoint before the robot reaches the current one.
                        currently_active = (
                            self._dest is not None and
                            (self._dest[0] - x) ** 2 + (self._dest[1] - y) ** 2 < DEST_TOL * DEST_TOL
                        )
                        if not currently_active:
                            self.get_logger().info(
                                f"[nav_relay] {rmf_id}: retry of recently sent ({x:.2f},{y:.2f})"
                                f" ({elapsed_sent:.1f}s ago, prev step) — reporting OK immediately"
                            )
                            import threading as _thr
                            _dest = new_dest
                            _thr.Thread(target=lambda: self._finish(rmf_id, True, completed_dest=_dest),
                                        daemon=True).start()
                            return

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
                if self._handle is not None:
                    # Active Nav2 goal already running — just update rmf_id tracking.
                    return
                # No active handle: the previous _run_goal thread may have returned
                # after its rmf_id was superseded by this same-dest transfer. Without
                # spawning a new thread, the relay gets stuck — it holds the destination
                # but never sends navigate_to_pose to bt_navigator.
                # Spawn a new thread with the updated rmf_id.
                self._thread_gen += 1
                my_gen = self._thread_gen
                # dest and yaw unchanged; x,y are already equal within DEST_TOL
            else:
                old_handle = self._handle
                old_dest = self._dest  # save before overwriting
                self._rmf_id = rmf_id
                self._dest = new_dest
                self._handle = None
                self._thread_gen += 1
                my_gen = self._thread_gen

        if not same and old_handle is not None:
            try:
                from action_msgs.msg import GoalStatus as _GS
                if old_handle.status == _GS.STATUS_SUCCEEDED:
                    # bt_navigator already completed this goal before the cancel arrived.
                    # Record the completed destination NOW (synchronously) so that the
                    # fleet adapter's periodic retry of this rmf_id is skipped. Without
                    # this check, cancel_goal_async() would cause _on_result to see
                    # STATUS_CANCELED instead of STATUS_SUCCEEDED, preventing
                    # _last_ok_dest from being set and allowing the retry to preempt
                    # the next navigation leg.
                    if old_dest is not None:
                        with self._lock:
                            self._last_ok_dest = old_dest
                            self._last_ok_time = _time_cmd.monotonic()
                        self.get_logger().info(
                            f"[nav_relay] preempted already-succeeded goal "
                            f"({old_dest[0]:.2f},{old_dest[1]:.2f}) → recorded as last_ok_dest"
                        )
                else:
                    old_handle.cancel_goal_async()
            except Exception:
                pass

        self.get_logger().info(
            f"[nav_relay] {rmf_id}: navigate_to_pose ({x:.2f},{y:.2f}) yaw={yaw:.2f}"
        )
        # Set _last_sent_dest HERE (before the thread starts) so that subsequent
        # _on_cmd calls see it immediately. Setting it in _run_goal (a background
        # thread) is too late — the thread may be in cooldown or waiting for the
        # server when the next NAVIGATE arrives, causing spurious zombie-fix triggers
        # that preempt the goal before it's even accepted by bt_navigator.
        with self._lock:
            self._last_sent_dest = (x, y)
            self._last_sent_time = _time_cmd.monotonic()
        threading.Thread(
            target=self._run_goal, args=(rmf_id, x, y, yaw, my_gen), daemon=True
        ).start()

    # ── Nav2 goal lifecycle ──────────────────────────────────────────────────

    def _run_goal(self, rmf_id: str, x: float, y: float, yaw: float,
                  my_gen: int = 0) -> None:
        # Single-execution guard: exit immediately if another thread is already
        # running _run_goal. This prevents zombie-fix threads from racing to
        # send_goal_async simultaneously, which would preempt a running goal.
        with self._lock:
            if self._run_active:
                return
            self._run_active = True
        try:
            self._run_goal_inner(rmf_id, x, y, yaw, my_gen)
        finally:
            with self._lock:
                self._run_active = False

    def _run_goal_inner(self, rmf_id: str, x: float, y: float, yaw: float,
                        my_gen: int) -> None:
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
                if self._rmf_id != rmf_id or self._thread_gen != my_gen:
                    return  # superseded during cooldown

        if not self._nav_client.wait_for_server(timeout_sec=SERVER_TIMEOUT):
            self.get_logger().warn("[nav_relay] navigate_to_pose server not available")
            self._finish(rmf_id, False)
            return

        with self._lock:
            if self._rmf_id != rmf_id or self._thread_gen != my_gen:
                return  # superseded before we started

        # Convert world-frame goal to slam_toolbox map frame.
        map_x = x - _MAP_OFFSET_X
        map_y = y - _MAP_OFFSET_Y

        goal = NavigateToPose.Goal()
        goal.pose = PoseStamped()
        goal.pose.header.frame_id = "map"
        goal.pose.header.stamp.sec = 0  # use latest available transform
        goal.pose.pose.position.x = map_x
        goal.pose.pose.position.y = map_y
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
            lambda f: self._on_result(f, rmf_id, handle, dest)
        )

    def _on_result(self, future, rmf_id: str, handle, dest: tuple) -> None:
        from action_msgs.msg import GoalStatus
        status = future.result().status
        success = (status == GoalStatus.STATUS_SUCCEEDED)
        self.get_logger().info(
            f"[nav_relay] {rmf_id}: {'SUCCEEDED' if success else 'FAILED'} "
            f"(status={status})"
        )

        with self._lock:
            if self._handle is handle:
                report_id = self._rmf_id if self._rmf_id is not None else rmf_id
                completed_dest = self._dest
                # On FAILED: keep _dest so retries are seen as currently_active
                # and RECENT_SENT_WINDOW does not fire fake-OK for the same dest.
                # On SUCCESS: clear state so the next goal can be tracked.
                self._rmf_id = None
                self._handle = None
                if success:
                    self._dest = None
            else:
                # Stale result from a superseded goal (e.g., the patrol leg-N goal
                # completes after leg N+1 has already started). Do NOT clear state.
                # Still record the completed dest so _on_cmd can skip spurious retries
                # of this goal's destination within the RECENT_OK_WINDOW.
                report_id = rmf_id
                completed_dest = dest  # dest from when this handle was accepted

        self._finish(report_id, success, completed_dest=completed_dest if success else None)

    def _finish(self, rmf_id: str, success: bool,
                completed_dest: "tuple[float,float] | None" = None) -> None:
        import time as _time
        now = _time.monotonic()
        if not success:
            self._last_fail_time = now
        elif completed_dest is not None:
            with self._lock:
                self._last_ok_dest = completed_dest
                self._last_ok_time = now
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
