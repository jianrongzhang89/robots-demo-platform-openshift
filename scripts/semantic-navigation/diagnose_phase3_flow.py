#!/usr/bin/env python3
"""Read-only 30-second camera/inference flow smoke check; not a Phase 3 gate."""
import json
import time

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CameraInfo, CompressedImage, Image, PointCloud2
from std_msgs.msg import Bool, String


def main():
    rclpy.init()
    node = Node("semantic_phase3_flow_audit", enable_rosout=False)
    counts = dict(rgb=0, depth=0, info=0, mask=0, cloud=0, matched=0,
                  ready_true=0, ready_false=0, bad_layout=0)
    pending = {"mask": {}, "cloud": {}}
    details = {"last_status": None, "last_pair": None}

    def camera(kind):
        def receive(msg):
            counts[kind] += 1
        return receive

    def output(kind):
        def receive(msg):
            counts[kind] += 1
            key = (msg.header.stamp.sec, msg.header.stamp.nanosec, msg.header.frame_id)
            if kind == "mask":
                valid = (msg.encoding == "mono8" and (msg.width, msg.height) == (640, 480)
                         and len(msg.data) == 640 * 480 and set(msg.data) <= {0, 2})
                description = {"pixels": sum(bool(value) for value in msg.data)}
            else:
                valid = (msg.point_step == 12 and (msg.width, msg.height) == (640, 480)
                         and len(msg.data) == msg.width * msg.height * 12)
                description = {"points": msg.width * msg.height}
            if not valid:
                counts["bad_layout"] += 1
                return
            other = "cloud" if kind == "mask" else "mask"
            if key in pending[other]:
                counts["matched"] += 1
                details["last_pair"] = {"header": key, **description, **pending[other].pop(key)}
            else:
                pending[kind][key] = description
                if len(pending[kind]) > 128:
                    pending[kind].pop(next(iter(pending[kind])))
        return receive

    def ready(msg):
        counts["ready_true" if msg.data else "ready_false"] += 1

    def status(msg):
        details["last_status"] = json.loads(msg.data)

    for kind, msg_type, topic in [
        ("rgb", CompressedImage, "color/image_compressed"),
        ("depth", CompressedImage, "depth/image_compressed"),
        ("info", CameraInfo, "color/camera_info"),
    ]:
        node.create_subscription(msg_type, "/robot_1/camera/" + topic, camera(kind), 20)
    node.create_subscription(Image, "/robot_1/semantic/mask", output("mask"), 20)
    node.create_subscription(PointCloud2, "/robot_1/semantic/points", output("cloud"), 20)
    node.create_subscription(Bool, "/robot_1/semantic/ready", ready, 20)
    node.create_subscription(String, "/robot_1/semantic/status", status, 20)
    started = time.monotonic()
    while time.monotonic() - started < 30:
        rclpy.spin_once(node, timeout_sec=0.1)
    print(json.dumps({"duration_s": time.monotonic() - started, "counts": counts,
                      "pending": {key: len(value) for key, value in pending.items()},
                      **details}), flush=True)
    node.destroy_node()
    rclpy.shutdown()
    if not all(counts[key] > 0 for key in ("rgb", "depth", "info", "matched", "ready_true")):
        raise SystemExit(1)
    if counts["bad_layout"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
