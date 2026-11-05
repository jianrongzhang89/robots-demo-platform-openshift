#!/usr/bin/env python3
"""Read-only source-side trace correlation; does not subscribe to raw images."""
import json
import time
import numpy as np
import rclpy
from rclpy.node import Node
from std_msgs.msg import String


def main():
    rclpy.init()
    node = Node("phase3_source_timing_audit", enable_rosout=False)
    source, compression = {}, {}
    def callback(target):
        def receive(message):
            row = json.loads(message.data)
            target[row["stamp_ns"]] = row
        return receive
    node.create_subscription(String, "/robot_1/camera/capture_trace", callback(source), 20)
    node.create_subscription(String, "/robot_1/camera/compression_trace", callback(compression), 20)
    started = time.monotonic()
    while time.monotonic() - started < 60:
        rclpy.spin_once(node, timeout_sec=.1)
    pairs = [(source[key], compression[key]) for key in sorted(source.keys() & compression.keys())]
    def summary(values):
        return {"p50": float(np.percentile(values,50)), "p95": float(np.percentile(values,95)),
                "max": max(values), "count": len(values)}
    rows = []
    for capture, compressed in pairs:
        rows.append({"stamp_ns": capture["stamp_ns"],
            "render_ms": capture["render_duration_ns"]/1e6,
            "source_to_raw_rgb_ms": (compressed["rgb_received_wall_ns"]-capture["source_publish_wall_ns"])/1e6,
            "source_to_raw_depth_ms": (compressed["depth_received_wall_ns"]-capture["source_publish_wall_ns"])/1e6,
            "raw_pair_wait_ms": (compressed["compression_start_wall_ns"]-min(compressed["rgb_received_wall_ns"],compressed["depth_received_wall_ns"]))/1e6,
            "compression_ms": (compressed["compression_end_wall_ns"]-compressed["compression_start_wall_ns"])/1e6,
            "capture_to_compressed_ms": (compressed["compression_end_wall_ns"]-capture["capture_wall_ns"])/1e6})
    assert rows, "no matching trace records"
    result = {"kind": "source_timing", "duration_s": time.monotonic()-started,
        "source_records":len(source), "compression_records":len(compression), "matched":len(rows),
        "stages_ms": {key:summary([row[key] for row in rows]) for key in rows[0] if key!="stamp_ns"},
        "slowest": sorted(rows,key=lambda row:row["capture_to_compressed_ms"], reverse=True)[:10]}
    print(json.dumps(result,sort_keys=True), flush=True)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
