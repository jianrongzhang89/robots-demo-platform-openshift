#!/usr/bin/env python3
"""Capture-origin timing observer. Runs beside inference; never commands motion."""
import argparse
import json
import os
import hashlib
from pathlib import Path
import time
from collections import OrderedDict

import numpy as np
import psutil
import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image, PointCloud2
from std_msgs.msg import String


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=60)
    parser.add_argument("--output", help="Write the complete evidence to a NEW file")
    parser.add_argument("--progress", action="store_true", help="Print one summary per minute")
    args = parser.parse_args()
    if not 1 <= args.duration <= 600:
        parser.error("duration must be within 1..600 seconds")
    rclpy.init()
    node = Node("phase3_capture_timing_audit", enable_rosout=False)
    state = {"status": None, "labels": None}
    rows, transitions, resources = [], [], []
    captures, compression = OrderedDict(), OrderedDict()
    counts = dict(mask=0, cloud=0, paired=0, invalid=0, source=0, compression=0)
    pairs = {"mask": set(), "cloud": set()}
    pair_receipts = {}
    arrival_receipts = {"mask": {}, "cloud": {}}
    last_ready = None
    active = False
    started = time.monotonic()
    def status(msg):
        nonlocal last_ready
        state["status"] = json.loads(msg.data)
        if active and state["status"]["ready"] != last_ready:
            transitions.append({"at_s": time.monotonic() - started,
                "ready": state["status"]["ready"], "reason": state["status"]["reason"]})
            last_ready = state["status"]["ready"]
    def timing(msg):
        if active:
            row = json.loads(msg.data)
            row["observer_wall_ns"] = time.time_ns()
            rows.append(row)
    def trace(kind):
        def receive(msg):
            if active:
                row = json.loads(msg.data)
                row["observer_wall_ns"] = time.time_ns()
                target = captures if kind == "source" else compression
                key = (row.get("source_epoch", ""), row["stamp_ns"])
                target[key] = row
                counts[kind] += 1
        return receive
    def output(kind):
        def receive(msg):
            if not active:
                return
            arrived_wall_ns = time.time_ns()
            counts[kind] += 1
            key = (msg.header.stamp.sec * 10**9 + msg.header.stamp.nanosec, msg.header.frame_id)
            arrival_receipts[kind][key] = arrived_wall_ns
            valid = (msg.width, msg.height) == (640, 480) and key[1] == "camera_color_optical_frame"
            if kind == "mask":
                valid = valid and msg.encoding == "mono8" and msg.step == 640 and not msg.is_bigendian and len(msg.data) == 640*480
                valid = valid and np.isin(np.frombuffer(msg.data, dtype=np.uint8), [0, 2]).all()
            else:
                valid = valid and msg.point_step == 12 and msg.row_step == 640*12 and len(msg.data) == 640*480*12
                valid = valid and not msg.is_bigendian and not msg.is_dense
                valid = valid and [(f.name, f.offset, f.datatype, f.count) for f in msg.fields] == [("x", 0, 7, 1), ("y", 4, 7, 1), ("z", 8, 7, 1)]
                if valid:
                    points = np.frombuffer(msg.data, dtype="<f4").reshape(-1, 3)
                    finite = np.isfinite(points).all(axis=1)
                    valid = bool(np.all(finite | np.isnan(points).all(axis=1)))
                    valid = valid and bool(np.all((points[finite, 2] >= .15) & (points[finite, 2] <= 5)))
            if not valid:
                counts["invalid"] += 1
                return
            other = "cloud" if kind == "mask" else "mask"
            if key in pairs[other]:
                pairs[other].remove(key)
                counts["paired"] += 1
                pair_receipts[key] = time.time_ns()
            else:
                pairs[kind].add(key)
        return receive
    node.create_subscription(String, "/robot_1/semantic/status", status, 20)
    node.create_subscription(String, "/robot_1/semantic/label_info",
        lambda msg: state.update(labels=json.loads(msg.data)),
        QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                   durability=DurabilityPolicy.TRANSIENT_LOCAL))
    node.create_subscription(String, "/robot_1/semantic/timing", timing, 20)
    node.create_subscription(String, "/robot_1/camera/capture_trace", trace("source"), 20)
    node.create_subscription(String, "/robot_1/camera/compression_trace", trace("compression"), 20)
    node.create_subscription(Image, "/robot_1/semantic/mask", output("mask"), 20)
    node.create_subscription(PointCloud2, "/robot_1/semantic/points", output("cloud"), 20)
    wait_start = time.monotonic()
    while not (state["status"] and state["status"]["ready"] and state["labels"]):
        rclpy.spin_once(node, timeout_sec=.1)
        if time.monotonic() - wait_start > 180:
            print(json.dumps({"error": "no ready state", **state}))
            raise SystemExit(1)
    initial = state["status"]
    assert state["labels"]["policy"] == "avoid-target/v1"
    assert state["labels"]["generation"] == 1
    assert state["labels"]["labels"] == {"0": "unobserved", "1": "traversable", "2": "avoid_target"}
    assert state["labels"]["active_labels"] == [0, 2]
    started = time.monotonic()
    started_wall_ns = time.time_ns()
    next_sample = started
    next_progress = started + 60
    active = True
    while time.monotonic() - started < args.duration:
        rclpy.spin_once(node, timeout_sec=.05)
        if time.monotonic() >= next_sample:
            resources.append({"at_s": time.monotonic()-started,
                "rss_bytes": psutil.Process(1).memory_info().rss, "status": state["status"]})
            next_sample += 10
        if args.progress and time.monotonic() >= next_progress:
            ages_so_far = [row["capture_age_upper_ms"] for row in rows]
            print(json.dumps({"event": "progress", "elapsed_s": time.monotonic()-started,
                "counts": counts, "capture_p95_ms": float(np.percentile(ages_so_far, 95)) if ages_so_far else None,
                "ready": state["status"]["ready"]}), flush=True)
            next_progress += 60
    elapsed = time.monotonic()-started
    def stats(values):
        if not values:
            return None
        return {"count": len(values), "p50": float(np.percentile(values,50)),
                "p95": float(np.percentile(values,95)), "max": float(max(values))}
    ages = [row["capture_age_upper_ms"] for row in rows]
    observer_pair_ages = []
    observer_arrival_ages = []
    for row in rows:
        received = pair_receipts.get((row["capture"]["stamp_ns"], row["capture"]["frame_id"]))
        if received is not None:
            row["observer_pair_wall_ns"] = received
            observer_pair_ages.append((received-row["capture_wall_ns"])/1e6+row["clock_uncertainty_ms"])
            key = (row["capture"]["stamp_ns"], row["capture"]["frame_id"])
            arrival = max(values[key] for values in arrival_receipts.values())
            row["observer_pair_arrival_wall_ns"] = arrival
            observer_arrival_ages.append((arrival-row["capture_wall_ns"])/1e6+row["clock_uncertainty_ms"])
    identities = [row["identity"]["request_id"] for row in rows]
    identity_errors = len(identities) - len(set(identities))
    order_errors = sum(right["capture"]["stamp_ns"] <= left["capture"]["stamp_ns"]
                       for left, right in zip(rows, rows[1:])
                       if left["source_epoch"] == right["source_epoch"])
    age_errors = sum(not 0 <= row["capture_age_upper_ms"] <= 500 or
                     not 0 <= row["simulation_age_ms"] <= 500 for row in rows)
    def stage(fn):
        return stats([fn(row) for row in rows])
    gaps = [(right["result_wall_ns"]-left["result_wall_ns"])/1e6
            for left, right in zip(rows, rows[1:])]
    source_rows = list(captures.values())
    source_rtf = None
    if len(source_rows) > 1 and source_rows[0]["source_epoch"] == source_rows[-1]["source_epoch"]:
        source_rtf = (source_rows[-1]["stamp_ns"]-source_rows[0]["stamp_ns"]) / (source_rows[-1]["capture_wall_ns"]-source_rows[0]["capture_wall_ns"])
    report = {"kind": "capture_origin_timing", "duration_s": elapsed,
        "receiver_cyclonedds_uri": os.getenv("CYCLONEDDS_URI"),
        "started_wall_ns": started_wall_ns, "finished_wall_ns": time.time_ns(),
        "counts": counts, "timed_outputs": len(rows), "outputs_per_s": counts["mask"]/elapsed,
        "identity_errors": identity_errors, "age_errors": age_errors,
        "order_errors": order_errors, "label_metadata": state["labels"],
        "capture_age_upper_ms": stats(ages), "simulation_age_ms": stage(lambda r:r["simulation_age_ms"]),
        "observer_pair_capture_age_upper_ms": stats(observer_pair_ages),
        "observer_pair_arrival_capture_age_upper_ms": stats(observer_arrival_ages),
        "outputs_within_250ms_per_s": sum(x<=250 for x in ages)/elapsed,
        "outputs_within_500ms_per_s": sum(x<=500 for x in ages)/elapsed,
        "publication_gap_ms": stats(gaps), "gaps_over_500ms": sum(x>500 for x in gaps),
        "source_simulation_wall_ratio": source_rtf,
        "stages_ms": {
            "render": stage(lambda r:r["source"]["render_duration_ns"]/1e6),
            "source_publish_to_raw_rgb": stage(lambda r:(r["compression"]["rgb_received_wall_ns"]-r["source"]["source_publish_wall_ns"])/1e6),
            "raw_pair_wait": stage(lambda r:(r["compression"]["compression_start_wall_ns"]-min(r["compression"]["rgb_received_wall_ns"],r["compression"]["depth_received_wall_ns"]))/1e6),
            "compression": stage(lambda r:(r["compression"]["compression_end_wall_ns"]-r["compression"]["compression_start_wall_ns"])/1e6),
            "compressed_to_receiver_rgb": stage(lambda r:(r["receiver_rgb_wall_ns"]-r["compression"]["compression_end_wall_ns"])/1e6),
            "backend": stage(lambda r:r["backend_ms"]),
            "work_wait": stage(lambda r:r.get("work_wait_ms", 0)),
            "normalized_cloud_publish": stage(lambda r:r["normalization_cloud_publish_ms"]),
            "receiver_rgb_to_result": stage(lambda r:(r["result_wall_ns"]-r["receiver_rgb_wall_ns"])/1e6)},
        "initial_status": initial, "final_status": state["status"],
        "transitions": transitions, "resources": resources, "results": rows,
        "source_traces": list(captures.values()), "compression_traces": list(compression.values())}
    if (report["receiver_cyclonedds_uri"] or "").startswith("file://"):
        report["receiver_cyclonedds_sha256"] = hashlib.sha256(Path(report["receiver_cyclonedds_uri"][7:]).read_bytes()).hexdigest()
    if args.output:
        with open(args.output, "x") as handle:
            json.dump(report, handle, sort_keys=True)
        summary = {key: value for key, value in report.items()
                   if key not in ("results", "source_traces", "compression_traces", "resources")}
        summary["evidence_file"] = args.output
        summary["rss_first_last_bytes"] = [resources[0]["rss_bytes"], resources[-1]["rss_bytes"]]
        print(json.dumps(summary, sort_keys=True), flush=True)
    else:
        print(json.dumps(report, sort_keys=True), flush=True)
    node.destroy_node()
    rclpy.shutdown()
    if not rows or counts["invalid"] or identity_errors or age_errors or order_errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
