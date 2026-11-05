#!/usr/bin/env python3
"""Compare native vs ROS raw input on identical captures in the isolated pod.

Starts a temporary ROS-input compressor with ALL output topics remapped; leaves
the native compressor running. Never changes the simulator or navigation.
"""
import hashlib
import json
import os
import subprocess
import time
from collections import OrderedDict

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage


def main():
    if os.getenv("GZ_PARTITION") != "semantic_phase3_inference":
        raise RuntimeError("test restricted to the private Phase 3 partition")
    rclpy.init()
    node = Node("native_codec_equivalence", enable_rosout=False)
    pending = {(transport, kind): OrderedDict()
               for transport in ("gz", "ros") for kind in ("rgb", "depth")}
    matches = {"rgb": [], "depth": []}
    def receive(transport, kind):
        def callback(msg):
            stamp = msg.header.stamp.sec * 10**9 + msg.header.stamp.nanosec
            value = {"stamp_ns": stamp, "frame": msg.header.frame_id, "format": msg.format,
                     "bytes": len(msg.data), "sha256": hashlib.sha256(bytes(msg.data)).hexdigest()}
            target = pending[(transport, kind)]
            target[stamp] = value
            if len(target) > 100:
                target.popitem(last=False)
            other = pending[("ros" if transport == "gz" else "gz", kind)].get(stamp)
            if other is not None and len(matches[kind]) < 10:
                assert value == other, (value, other)
                matches[kind].append(value)
        return callback
    for kind, suffix in (("rgb", "color"), ("depth", "depth")):
        node.create_subscription(CompressedImage, f"/robot_1/camera/{suffix}/image_compressed", receive("gz", kind), 20)
        node.create_subscription(CompressedImage, f"/phase3_comparison/{kind}", receive("ros", kind), 20)
    command = ["python3", "/opt/semantic-navigation/camera_compressor.py", "--ros-args",
               "-r", "__node:=phase3_ros_mirror",
               "-r", "/robot_1/camera/color/image_compressed:=/phase3_comparison/rgb",
               "-r", "/robot_1/camera/depth/image_compressed:=/phase3_comparison/depth",
               "-r", "/robot_1/camera/compression_trace:=/phase3_comparison/trace"]
    child = subprocess.Popen(command, env={**os.environ, "SEMANTIC_RAW_INPUT": "ros"},
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        until = time.monotonic() + 90
        while not all(len(values) == 10 for values in matches.values()):
            assert child.poll() is None, "mirror exited"
            assert time.monotonic() < until, "not enough exact-stamp matches"
            rclpy.spin_once(node, timeout_sec=.05)
        print(json.dumps({"kind": "native_ros_codec_equivalence", "passed": True,
                          "matches": matches}, sort_keys=True), flush=True)
    finally:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
