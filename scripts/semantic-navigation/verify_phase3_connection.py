#!/usr/bin/env python3
"""Observe an externally interrupted private router; never changes networking.

Wait for audit_ready, remove only semantic-phase3-router, wait for outage_verified,
restore that pod, then retain the final JSON result. A missing router is a test
fault, not authorization to touch canonical routers or robot networking.
"""
import json
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from sensor_msgs.msg import Image


def main():
    rclpy.init()
    node = Node("semantic_phase3_connection_audit", enable_rosout=False)
    state = {"status": None, "masks": 0}
    node.create_subscription(String, "/robot_1/semantic/status",
        lambda msg: state.update(status=json.loads(msg.data)), 20)
    node.create_subscription(Image, "/robot_1/semantic/mask",
        lambda msg: state.update(masks=state["masks"] + 1), 20)
    def wait(predicate, timeout=120):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=.05)
            if predicate():
                return
        raise AssertionError(f"wait expired: {state}")
    try:
        wait(lambda: state["status"] and state["status"]["ready"])
        before = state["status"]
        print(json.dumps({"event": "audit_ready", "status": before}), flush=True)
        wait(lambda: not state["status"]["ready"])
        deadline = time.monotonic() + 1.5
        wait(lambda: time.monotonic() >= deadline)
        failure = state["status"]
        masks_before = state["masks"]
        deadline = time.monotonic() + 3
        wait(lambda: time.monotonic() >= deadline)
        assert not state["status"]["ready"] and state["status"]["reason"]
        assert state["masks"] == masks_before
        assert state["status"]["last_result"] == failure["last_result"]
        print(json.dumps({"event": "outage_verified", "status": state["status"]}), flush=True)
        wait(lambda: state["status"]["ready"] and state["status"]["last_result"] != failure["last_result"])
        print(json.dumps({"kind": "router_disconnection", "quiescent_observation_s": 3,
            "masks_during_outage": 0, "heartbeat_unchanged": True,
            "initial_status": before, "failure_status": failure,
            "recovered_status": state["status"]}), flush=True)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
