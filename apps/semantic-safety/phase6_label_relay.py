"""Relay the SAM3 label_info metadata from the isolated camera/semantic
domain (88) onto the safety domain (85) for the Phase 6 costmap layers.

Why this exists (Phase 6 pilot 1, October 2026): the label_info
transient-local latch crosses a single zenoh-bridge subscriber reliably (the
Phase 5 series shape, 88-bridge alone, 10/10), but a SECOND bridge
subscribing the same transient-local key from the same router loses the
latch — reproducible with read-only diagnostic pods regardless of startup
order. The Phase 6 fixture pod needs both bridges (88 for the observation
worker, 85 for the costmaps), so label_info is kept EXCLUSIVE to the
88-bridge and this relay republishes the identical message on domain 85
with the same reliable/transient-local QoS the layers subscribe with. The
message is relayed verbatim; nothing is parsed, restamped or synthesized,
and the layer still validates the full policy/generation/labels content.
"""
import argparse
import json
import os
from pathlib import Path
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

SOURCE_DOMAIN = "88"
TARGET_DOMAIN = "85"


def main():
    if not os.getenv("GZ_PARTITION", "").startswith("phase5-watchdog-"):
        raise RuntimeError("private fixture partition required")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shared-dir", required=True,
                        help="emptyDir shared with the fixture: the relay reports its state here")
    args = parser.parse_args()
    shared = Path(args.shared_dir)
    shared.mkdir(exist_ok=True)
    status_path = shared / "label-relay.json"

    def write_status(payload):
        temporary = Path(str(status_path) + ".tmp")
        temporary.write_text(json.dumps(payload))
        temporary.replace(status_path)

    os.environ["ROS_DOMAIN_ID"] = SOURCE_DOMAIN
    source_context = rclpy.Context()
    rclpy.init(context=source_context)
    source_node = Node("phase6_label_relay_source", context=source_context)
    print(json.dumps({"event": "relay_started", "source_domain": SOURCE_DOMAIN,
                      "target_domain": TARGET_DOMAIN}), flush=True)

    os.environ["ROS_DOMAIN_ID"] = TARGET_DOMAIN
    target_context = rclpy.Context()
    rclpy.init(context=target_context)
    target_node = Node("phase6_label_relay_target", context=target_context)

    qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                     durability=DurabilityPolicy.TRANSIENT_LOCAL)
    publisher = target_node.create_publisher(String, "/robot_1/semantic/label_info", qos)
    state = {"received": 0, "published": 0, "first_wall_ns": None}

    def on_labels(message):
        # Verbatim relay: same payload, same reliable/transient-local contract.
        state["received"] += 1
        publisher.publish(message)
        state["published"] += 1
        if state["first_wall_ns"] is None:
            state["first_wall_ns"] = time.time_ns()
        write_status({**state, "wall_ns": time.time_ns()})

    source_node.create_subscription(String, "/robot_1/semantic/label_info",
                                    on_labels, qos)

    from rclpy.executors import SingleThreadedExecutor
    source_executor = SingleThreadedExecutor(context=source_context)
    source_executor.add_node(source_node)
    target_executor = SingleThreadedExecutor(context=target_context)
    target_executor.add_node(target_node)
    write_status({**state, "wall_ns": time.time_ns()})
    try:
        while rclpy.ok(context=source_context):
            source_executor.spin_once(timeout_sec=0.05)
            target_executor.spin_once(timeout_sec=0.05)
    finally:
        write_status({**state, "wall_ns": time.time_ns(), "stopped": True})
        source_node.destroy_node()
        target_node.destroy_node()
        source_executor.shutdown()
        target_executor.shutdown()
        rclpy.shutdown(context=target_context)
        rclpy.shutdown(context=source_context)


if __name__ == "__main__":
    main()
