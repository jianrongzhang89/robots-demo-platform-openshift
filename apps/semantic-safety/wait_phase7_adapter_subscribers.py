"""Wait until the production adapter's camera subscriptions are in its ROS graph."""
import json
import os
from pathlib import Path
import time

import rclpy
from rclpy.node import Node


TOPICS = (
    "/camera/color/image_compressed",
    "/camera/depth/image_compressed",
    "/camera/color/camera_info",
    "/camera/capture_trace",
    "/camera/compression_trace",
)
ADAPTER_NODE = "sam3_semantic_inference"


def main():
    timeout_s = float(os.environ.get("PHASE7_SUBSCRIBER_DISCOVERY_TIMEOUT", "120"))
    ready_path = Path("/phase7-shared/adapter-subscribers-ready")
    failed_path = Path("/phase7-shared/adapter-subscribers-failed")
    rclpy.init()
    node = Node("phase7_adapter_subscription_readiness")
    deadline = time.monotonic() + timeout_s
    try:
        while time.monotonic() < deadline:
            visible = {
                topic: node.get_subscriptions_info_by_topic(topic)
                for topic in TOPICS
            }
            counts = {topic: len(endpoints) for topic, endpoints in visible.items()}
            adapter_topics = {
                topic: [endpoint for endpoint in endpoints
                        if endpoint.node_name == ADAPTER_NODE]
                for topic, endpoints in visible.items()
            }
            if all(adapter_topics[topic] for topic in TOPICS):
                ready_path.write_text(json.dumps({"counts": counts}))
                print(json.dumps({
                    "event": "phase7_adapter_subscribers_ready",
                    "counts": counts,
                    "adapter_node": ADAPTER_NODE,
                }, sort_keys=True), flush=True)
                return
            rclpy.spin_once(node, timeout_sec=0.25)
        failed_path.write_text(json.dumps({"counts": counts}))
        raise RuntimeError(f"adapter camera subscriptions were not all discovered: {counts}")
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
