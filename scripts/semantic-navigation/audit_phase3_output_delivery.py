#!/usr/bin/env python3
"""Thin mask/cloud receiver with per-process UDP counters; no validation loops."""
import argparse
import json
import os
from pathlib import Path
import time

import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image, PointCloud2
from std_msgs.msg import String


def snapshot():
    fds = {}
    for entry in Path("/proc/self/fd").iterdir():
        try:
            target = os.readlink(entry)
        except OSError:
            continue
        if target.startswith("socket:["):
            fds[target[8:-1]] = entry.name
    sockets = []
    for line in Path("/proc/net/udp").read_text().splitlines()[1:]:
        fields = line.split()
        if fields[9] in fds:
            sockets.append({"inode": fields[9], "port": int(fields[1].split(":")[1],16),
                            "drops": int(fields[-1])})
    udp = [line.split()[1:] for line in Path("/proc/net/snmp").read_text().splitlines() if line.startswith("Udp:")]
    return {"wall_ns": time.time_ns(), "pid": os.getpid(), "sockets": sockets,
            "pod_udp": dict(zip(udp[0], map(int,udp[1])))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=30)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    assert 1 <= args.duration <= 600
    rclpy.init()
    node = Node("phase3_thin_delivery_audit", enable_rosout=False)
    timing, received = {}, {"mask": {}, "cloud": {}}
    def result(msg):
        row = json.loads(msg.data)
        timing[row["capture"]["stamp_ns"]] = row
    def output(kind):
        def callback(msg):
            received[kind][msg.header.stamp.sec*10**9+msg.header.stamp.nanosec] = time.time_ns()
        return callback
    node.create_subscription(String, "/robot_1/semantic/timing", result, 20)
    node.create_subscription(Image, "/robot_1/semantic/mask", output("mask"), 20)
    node.create_subscription(PointCloud2, "/robot_1/semantic/points", output("cloud"), 20)
    until = time.monotonic()+30
    while len(received["cloud"]) < 3:
        assert time.monotonic() < until, "no live output"
        rclpy.spin_once(node, timeout_sec=.05)
    timing.clear()
    for values in received.values():
        values.clear()
    before = snapshot()
    started = time.monotonic()
    while time.monotonic()-started < args.duration:
        rclpy.spin_once(node, timeout_sec=.05)
    after = snapshot()
    rows = []
    for stamp, row in timing.items():
        if all(stamp in values for values in received.values()):
            rows.append({"stamp_ns": stamp, "publish_capture_age_upper_ms": row["capture_age_upper_ms"],
                **{f"{kind}_capture_age_upper_ms": (values[stamp]-row["capture_wall_ns"])/1e6+row["clock_uncertainty_ms"]
                   for kind, values in received.items()}})
    def stats(name):
        values = [row[name] for row in rows]
        return {"count": len(values), "p50": float(np.percentile(values,50)),
                "p95": float(np.percentile(values,95)), "max": max(values)}
    report = {"kind": "thin_output_delivery", "duration_s": time.monotonic()-started,
              "counts": {kind: len(values) for kind,values in received.items()}, "paired": len(rows),
              "before": before, "after": after,
              "ages_ms": {name: stats(name) for name in ("publish_capture_age_upper_ms", "mask_capture_age_upper_ms", "cloud_capture_age_upper_ms")},
              "slowest": sorted(rows, key=lambda r:r["cloud_capture_age_upper_ms"])[-10:]}
    with open(args.output,"x") as handle:
        json.dump(report,handle,sort_keys=True)
    print(json.dumps(report,sort_keys=True),flush=True)
    node.destroy_node()
    rclpy.try_shutdown()


if __name__ == "__main__":
    main()
