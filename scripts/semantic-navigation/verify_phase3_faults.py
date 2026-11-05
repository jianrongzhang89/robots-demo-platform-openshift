#!/usr/bin/env python3
"""Exercise the opt-in inference exception/delay hook, never navigation."""
import json
import os
import time
from pathlib import Path

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from sensor_msgs.msg import Image


def main():
    path = Path(os.environ["PHASE3_DIAGNOSTIC_FAULT_FILE"])
    if path.exists():
        raise RuntimeError("fault file already exists; refusing to overwrite")
    rclpy.init()
    node = Node("semantic_phase3_fault_audit", enable_rosout=False)
    state = {"status": None, "masks": 0}
    node.create_subscription(String, "/robot_1/semantic/status",
        lambda msg: state.update(status=json.loads(msg.data)), 20)
    node.create_subscription(Image, "/robot_1/semantic/mask",
        lambda msg: state.update(masks=state["masks"] + 1), 20)
    def wait(predicate, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=.05)
            if predicate():
                return
        raise AssertionError(f"wait expired: {state}")
    def spin(seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=.05)
    results = []
    try:
        wait(lambda: state["status"] and state["status"]["ready"])
        for mode in ("exception", "delay"):
            with path.open("x") as handle:
                json.dump({"mode": mode, "seconds": 1.0}, handle)
            # Allow one already-in-flight result and status propagation to settle.
            spin(1.5)
            wait(lambda: not state["status"]["ready"])
            before = state["status"]["last_result"]
            masks_before = state["masks"]
            spin(3)
            assert not state["status"]["ready"], state
            assert state["status"]["reason"], state
            assert state["masks"] == masks_before, state
            assert state["status"]["last_result"] == before, state
            failure_state = state["status"]
            path.unlink()
            wait(lambda: state["status"]["ready"] and state["status"]["last_result"] != before)
            results.append({"fault": mode, "quiescent_observation_s": 3,
                "masks_during_failure": 0, "heartbeat_unchanged": True,
                "failure_status": failure_state, "recovered_status": state["status"]})
    finally:
        path.unlink(missing_ok=True)
        node.destroy_node()
        rclpy.shutdown()
    print(json.dumps({"kind": "live_fault_tests", "results": results}), flush=True)


if __name__ == "__main__":
    main()
