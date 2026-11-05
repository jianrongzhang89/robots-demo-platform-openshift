#!/usr/bin/env python3
"""Read-only organized-cloud/label/soak auditor. No navigation publishers.

Receipt age is NOT capture age: source camera rendering/compression/transport
precede this observer and require separate instrumentation for the full gate.
Run in the inference container with ROS sourced. JSON result goes to stdout.
"""
import argparse
import json
import time
from collections import OrderedDict

import numpy as np
import psutil
import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CompressedImage, Image, PointCloud2
from std_msgs.msg import Bool, String


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=600)
    parser.add_argument("--wait-ready", type=float, default=180)
    args = parser.parse_args()
    rclpy.init()
    node = Node("semantic_phase3_runtime_audit", enable_rosout=False)
    state = {"status": None, "labels": None, "ready": False}
    counts = dict(mask=0, cloud=0, matched=0, invalid=0, duplicates=0,
                  out_of_order=0, ready_false=0, ready_true=0, source_rgb=0)
    pending = {"mask": OrderedDict(), "cloud": OrderedDict()}
    source = OrderedDict()
    seen = {"mask": set(), "cloud": set()}
    last_stamp = {"mask": -1, "cloud": -1}
    receipt_ages, processing_ages, resources, transitions = [], [], [], []
    active = False
    last_result_id = None
    startup_states = []

    def key(msg):
        return (msg.header.stamp.sec * 10**9 + msg.header.stamp.nanosec, msg.header.frame_id)

    def bounded(target, key_, value, limit=128):
        target[key_] = value
        if len(target) > limit:
            target.popitem(last=False)

    def rgb(msg):
        if active:
            counts["source_rgb"] += 1
            bounded(source, key(msg), time.monotonic())

    def output(kind):
        def receive(msg):
            if not active:
                return
            counts[kind] += 1
            header = key(msg)
            if header in seen[kind]:
                counts["duplicates"] += 1
            seen[kind].add(header)
            if header[0] <= last_stamp[kind]:
                counts["out_of_order"] += 1
            last_stamp[kind] = header[0]
            valid = (msg.width, msg.height) == (640, 480) and header[1] == "camera_color_optical_frame"
            if kind == "mask":
                labels = np.frombuffer(msg.data, dtype=np.uint8)
                valid = valid and msg.encoding == "mono8" and msg.step == 640
                valid = valid and len(labels) == 640 * 480 and np.isin(labels, [0, 2]).all()
                if header in source:
                    receipt_ages.append((time.monotonic() - source[header]) * 1000)
            else:
                valid = valid and msg.point_step == 12 and msg.row_step == 640 * 12
                valid = valid and len(msg.data) == 640 * 480 * 12 and not msg.is_bigendian
                valid = valid and [(f.name, f.offset, f.datatype, f.count) for f in msg.fields] == [
                    ("x", 0, 7, 1), ("y", 4, 7, 1), ("z", 8, 7, 1)]
                if valid:
                    points = np.frombuffer(msg.data, dtype="<f4").reshape(-1, 3)
                    valid_rows = np.isfinite(points).all(axis=1)
                    invalid_rows = np.isnan(points).all(axis=1)
                    valid = bool(np.all(valid_rows | invalid_rows))
                    valid = valid and bool(np.all((points[valid_rows, 2] >= .15) & (points[valid_rows, 2] <= 5)))
            if not valid:
                counts["invalid"] += 1
                return
            other = "cloud" if kind == "mask" else "mask"
            if header in pending[other]:
                pending[other].pop(header)
                counts["matched"] += 1
            else:
                bounded(pending[kind], header, True)
        return receive

    def ready(msg):
        if active:
            counts["ready_true" if msg.data else "ready_false"] += 1
            if msg.data != state["ready"]:
                transitions.append({"at_s": time.monotonic() - started, "ready": msg.data})
        state["ready"] = msg.data

    def status(msg):
        nonlocal last_result_id
        state["status"] = json.loads(msg.data)
        if not active:
            summary = {key: state["status"].get(key) for key in ("state", "ready", "reason", "stream_epoch")}
            if not startup_states or summary != startup_states[-1]:
                startup_states.append(summary)
        last = state["status"].get("last_result")
        if active and last and last["identity"]["request_id"] != last_result_id:
            processing_ages.append(last["receiver_processing_age_ms"])
            last_result_id = last["identity"]["request_id"]

    node.create_subscription(CompressedImage, "/robot_1/camera/color/image_compressed", rgb, 20)
    node.create_subscription(Image, "/robot_1/semantic/mask", output("mask"), 20)
    node.create_subscription(PointCloud2, "/robot_1/semantic/points", output("cloud"), 20)
    node.create_subscription(Bool, "/robot_1/semantic/ready", ready, 20)
    node.create_subscription(String, "/robot_1/semantic/status", status, 20)
    node.create_subscription(String, "/robot_1/semantic/label_info",
        lambda msg: state.update(labels=json.loads(msg.data)),
        QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL))
    wait_start = time.monotonic()
    while not (state["ready"] and state["labels"] and state["status"] and state["status"]["ready"]):
        rclpy.spin_once(node, timeout_sec=.1)
        if time.monotonic() - wait_start > args.wait_ready:
            print(json.dumps({"error": "ready/labels wait expired", "state": state}))
            raise SystemExit(1)
    initial = state["status"]
    started = time.monotonic()
    active = True
    next_sample = started
    while time.monotonic() - started < args.duration:
        rclpy.spin_once(node, timeout_sec=.1)
        now = time.monotonic()
        if now >= next_sample:
            memory = psutil.Process(1).memory_info().rss
            resources.append({"at_s": round(now - started, 2), "runtime_rss_bytes": memory,
                "mask_count": counts["mask"], "status": state["status"]})
            next_sample = now + 10
    elapsed = time.monotonic() - started
    def percentiles(values):
        return None if not values else {"samples": len(values), "p50": float(np.percentile(values, 50)),
            "p95": float(np.percentile(values, 95)), "max": float(max(values))}
    result = {"duration_s": elapsed, "counts": counts, "outputs_per_s": counts["mask"] / elapsed,
        "matched_percent": 100 * counts["matched"] / max(1, counts["mask"]),
        "pending": {key: len(value) for key, value in pending.items()},
        "observer_rgb_receipt_to_mask_ms_NOT_capture_age": percentiles(receipt_ages),
        "sampled_receiver_processing_ms_NOT_capture_age": percentiles(processing_ages),
        "full_capture_to_result_age": "NOT_MEASURED", "resources": resources,
        "initial_status": initial, "final_state": state, "transitions": transitions}
    result["startup_states"] = startup_states
    print(json.dumps(result, sort_keys=True), flush=True)
    node.destroy_node()
    rclpy.shutdown()
    if counts["invalid"] or counts["duplicates"] or counts["out_of_order"] or not counts["matched"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
