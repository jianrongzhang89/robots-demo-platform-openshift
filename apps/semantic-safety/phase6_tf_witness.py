"""Capture-time TF witness for the Phase 6 arm trials (user-approved October 28, 2026).

Why this exists (pair-1-off-gcfix / pair-1-off-tfprobe): at mat-close the
fixture process saturates (~95% CPU, its busy pump) and its own /tf reader
delivery queues to ~180 ms, so capture-time map->lidar_frame lookups can
no longer resolve within the ~100 ms simulation scan window and the 500 ms
tf lease correctly stops the robot (`tf_stale`) — while an identical idle
process in the same pod receives the same /tf stream in ~1.4 ms. This
witness is that idle process, promoted to the supervisor's tf evidence
source: it subscribes the SAME /robot_1/scan_fixed stream and /tf, keeps
its own tf2 buffer, and resolves the capture-time transform for each scan
stamp with the same semantics as the fixture's own lookup (exact
capture-time, no latest-TF substitution, no extrapolation). It publishes
only a small status record through the shared emptyDir.

Fail-closed contract (mirrors the qualified UDP companion path):
- The witness grants NO authority. It only records that the capture-time
  transform for a scan stamp resolved, when, and with which sequence
  number; the gate keeps its unchanged 500 ms capture-age freshness and
  the fixture renews the tf lease through the same evidence() path with
  its own clock bound and monotonicity checks.
- A stale, missing or regressing witness record simply renews nothing:
  the tf lease starves exactly as before. Witness loss can never create
  optimistic authority or resume motion.
- The witness dies with the pod (sidecar) and holds no latched state
  across trials.
"""
import json
import os
import time
from pathlib import Path

import rclpy
from rclpy.clock import Clock, ClockType
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan
from tf2_ros import Buffer, TransformListener
from rclpy.time import Time

SCHEMA = "phase6-tf-witness/v1"
STALENESS_HEARTBEAT_S = 0.2
RETRY_PERIOD_S = 0.005


def main():
    if os.getenv("ROS_DOMAIN_ID") != "85":
        raise RuntimeError("private safety domain 85 required")
    if not os.getenv("GZ_PARTITION", "").startswith("phase5-watchdog-"):
        raise RuntimeError("private fixture partition required")
    shared = Path(os.getenv("PHASE6_TF_WITNESS_DIR", "/tmp/phase5-sam3-shared"))
    shared.mkdir(exist_ok=True)
    status_path = shared / "tf-witness.json"

    def write_status(payload):
        temporary = Path(str(status_path) + ".tmp")
        temporary.write_text(json.dumps(payload))
        temporary.replace(status_path)

    rclpy.init()
    node = Node("phase6_tf_witness")
    buffer = Buffer()
    TransformListener(buffer, node)
    state = {"latest_stamp": None, "frame": None, "scans": 0,
             "seq": 0, "qualified_stamp": None, "qualified_wall_ns": None,
             "fault": None, "last_write": 0.0, "last_error": None}

    def on_scan(message):
        state["scans"] += 1
        stamp = message.header.stamp.sec * 1_000_000_000 + message.header.stamp.nanosec
        frame = message.header.frame_id
        if state["latest_stamp"] is None or stamp > state["latest_stamp"]:
            state["latest_stamp"] = stamp
            state["frame"] = frame

    node.create_subscription(LaserScan, "/robot_1/scan_fixed", on_scan,
                             qos_profile_sensor_data)

    def attempt():
        # Wall-clock timer (steady): a paused simulation stops producing
        # scans and the last qualified stamp ages out at the gate, exactly
        # like the fixture's own lookup path.
        stamp, frame = state["latest_stamp"], state["frame"]
        if stamp is not None and frame and stamp != state["qualified_stamp"]:
            try:
                if buffer.can_transform("map", frame, Time(nanoseconds=stamp)):
                    state["seq"] += 1
                    state["qualified_stamp"] = stamp
                    state["qualified_wall_ns"] = time.time_ns()
                    state["last_error"] = None
                else:
                    state["last_error"] = "not_resolvable_yet"
            except Exception as error:  # diagnostics only; never fatal
                state["last_error"] = str(error)[:120]
        now = time.monotonic()
        if (state["seq"] and (now - state["last_write"]) >= 0.02) or \
                (now - state["last_write"]) >= STALENESS_HEARTBEAT_S:
            state["last_write"] = now
            write_status({"schema": SCHEMA, "seq": state["seq"],
                          "scan_stamp_ns": state["qualified_stamp"],
                          "frame": state["frame"],
                          "qualified_wall_ns": state["qualified_wall_ns"],
                          "scans_seen": state["scans"],
                          "last_error": state["last_error"],
                          "written_wall_ns": time.time_ns()})

    node.create_timer(RETRY_PERIOD_S, attempt, clock=Clock(clock_type=ClockType.STEADY_TIME))
    write_status({"schema": SCHEMA, "seq": 0, "scan_stamp_ns": None,
                  "written_wall_ns": time.time_ns()})
    print(json.dumps({"event": "tf_witness_started", "pid": os.getpid()}), flush=True)
    try:
        rclpy.spin(node)
    except rclpy.executors.ExternalShutdownException:
        # SIGTERM during pod teardown shuts the context from the signal
        # handler and raises here; this is normal teardown, not a failure.
        # An uncaught escape exits 1 and fails the whole pod
        # (paired-series-4/8/11: the fixture had completed with all checks
        # passing, but the sidecar's non-zero exit flipped the pod to
        # Failed during the evidence-retrieval window).
        pass
    finally:
        node.destroy_node()
        # The context may already be down (signal handler); never fail the
        # process during cleanup.
        try:
            rclpy.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
