"""Wait until every source camera publisher is visible before bridge startup."""
import json
import os
from pathlib import Path
import time

import rclpy
from rclpy.node import Node


TOPICS = (
    "/robot_1/camera/color/image_compressed",
    "/robot_1/camera/depth/image_compressed",
    "/robot_1/camera/color/camera_info",
    "/robot_1/camera/capture_trace",
    "/robot_1/camera/compression_trace",
)
EXPECTED_NODES = {
    "/robot_1/camera/color/image_compressed": "semantic_camera_compressor",
    "/robot_1/camera/depth/image_compressed": "semantic_camera_compressor",
    "/robot_1/camera/color/camera_info": "semantic_camera_bridge",
    "/robot_1/camera/capture_trace": "semantic_camera_bridge",
    "/robot_1/camera/compression_trace": "semantic_camera_compressor",
}


def main():
    timeout_s = float(os.environ.get("PHASE7_PUBLISHER_DISCOVERY_TIMEOUT", "120"))
    ready_path = Path("/phase7-shared/camera-publishers-ready")
    failed_path = Path("/phase7-shared/camera-publishers-failed")
    rclpy.init()
    node = Node("phase7_camera_publisher_readiness")
    deadline = time.monotonic() + timeout_s
    try:
        while time.monotonic() < deadline:
            visible = {
                topic: node.get_publishers_info_by_topic(topic)
                for topic in TOPICS
            }
            counts = {topic: len(endpoints) for topic, endpoints in visible.items()}
            if all(any(endpoint.node_name == EXPECTED_NODES[topic]
                       for endpoint in visible[topic])
                   for topic in TOPICS):
                qos = {
                    topic: sorted({str(endpoint.qos_profile.reliability)
                                  for endpoint in endpoints})
                    for topic, endpoints in visible.items()
                }
                ready_path.write_text(json.dumps({"counts": counts, "qos": qos}))
                print(json.dumps({
                    "event": "phase7_camera_publishers_ready",
                    "counts": counts,
                    "qos": qos,
                }, sort_keys=True), flush=True)
                return
            rclpy.spin_once(node, timeout_sec=0.25)
        failed_path.write_text(json.dumps({"counts": counts}))
        raise RuntimeError(f"camera publishers were not all discovered: {counts}")
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
