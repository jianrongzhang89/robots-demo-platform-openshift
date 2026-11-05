#!/usr/bin/env python3
"""Record one exact-stamp compressed RGB-D pair for transport equivalence."""
import hashlib
import json
import time
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage

rclpy.init()
node = Node("phase3_camera_fingerprint", enable_rosout=False)
frames = {"rgb": {}, "depth": {}}
def callback(kind):
    def receive(message):
        stamp = message.header.stamp.sec * 10**9 + message.header.stamp.nanosec
        frames[kind][stamp] = {"stamp_ns": stamp, "frame_id": message.header.frame_id,
            "format": message.format, "bytes": len(message.data),
            "sha256": hashlib.sha256(bytes(message.data)).hexdigest()}
        if len(frames[kind]) > 20:
            frames[kind].pop(next(iter(frames[kind])))
    return receive
for kind, topic in [("rgb", "color"), ("depth", "depth")]:
    node.create_subscription(CompressedImage, f"/robot_1/camera/{topic}/image_compressed", callback(kind), 20)
started = time.monotonic()
while time.monotonic() - started < 15:
    rclpy.spin_once(node, timeout_sec=.1)
    shared = frames["rgb"].keys() & frames["depth"].keys()
    if shared:
        stamp = max(shared)
        print(json.dumps({kind: frames[kind][stamp] for kind in frames}), flush=True)
        break
else:
    raise RuntimeError("no exact-stamp RGB-D pair")
node.destroy_node()
rclpy.shutdown()
