"""Count Phase 7 camera messages at one side of the isolated ROS bridge."""
import json
import os
import time
import threading

import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CameraInfo, CompressedImage
from std_msgs.msg import String


def main():
    side = os.environ.get("PHASE7_STREAM_PROBE_SIDE", "unknown")
    prefix = os.environ.get("PHASE7_STREAM_PROBE_PREFIX", "/camera")
    duration = float(os.environ.get("PHASE7_STREAM_PROBE_SECONDS", "20"))
    topics = {
        "rgb": (prefix + "/color/image_compressed", CompressedImage),
        "depth": (prefix + "/depth/image_compressed", CompressedImage),
        "camera_info": (prefix + "/color/camera_info", CameraInfo),
        "capture_trace": (prefix + "/capture_trace", String),
        "compression_trace": (prefix + "/compression_trace", String),
    }
    counts = {name: 0 for name in topics}
    lock = threading.Lock()

    rclpy.init()
    node = rclpy.create_node("phase7_ros_stream_probe_" + side.replace("-", "_"))
    subscriptions = []
    for name, (topic, message_type) in topics.items():
        def callback(_message, stream_name=name):
            with lock:
                counts[stream_name] += 1
        subscriptions.append(node.create_subscription(
            message_type, topic, callback, qos_profile_sensor_data))

    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    thread = threading.Thread(target=executor.spin, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))
        with lock:
            result = dict(counts)
        print(json.dumps({
            "event": "phase7_ros_stream_probe",
            "side": side,
            "ros_domain_id": os.environ.get("ROS_DOMAIN_ID"),
            "prefix": prefix,
            "duration_seconds": duration,
            "counts": result,
            "passed": all(value > 0 for value in result.values()),
        }, sort_keys=True), flush=True)
    finally:
        executor.shutdown(timeout_sec=2.0)
        thread.join(timeout=2.0)
        for subscription in subscriptions:
            node.destroy_subscription(subscription)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
