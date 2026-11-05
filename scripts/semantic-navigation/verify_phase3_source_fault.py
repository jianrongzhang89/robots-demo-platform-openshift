#!/usr/bin/env python3
"""Observe a controlled source outage/reset; never injects faults itself.

After audit_ready, externally pause the private world or its compressor for
eight seconds, with guaranteed restoration. For reset mode, reset only the
private world after audit_ready. All accepted results must retain capture age.
"""
import argparse
import json
import time
from collections import OrderedDict

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from sensor_msgs.msg import CompressedImage


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fault", required=True, choices=("compressor_delay", "world_pause", "world_reset"))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    rclpy.init()
    node = Node("phase3_source_fault_audit", enable_rosout=False)
    statuses, results = [], []
    source_traces, delayed_inputs = OrderedDict(), []
    def source(msg):
        trace = json.loads(msg.data)
        source_traces[trace["stamp_ns"]] = trace
        if len(source_traces) > 256:
            source_traces.popitem(last=False)
    def rgb(msg):
        key = msg.header.stamp.sec * 10**9 + msg.header.stamp.nanosec
        trace = source_traces.get(key)
        if trace:
            age = (time.time_ns()-trace["capture_wall_ns"])/1e6
            if age > 500:
                delayed_inputs.append({"stamp_ns": key, "source_epoch": trace["source_epoch"],
                                       "receiver_capture_age_ms": age})
    def status(msg):
        row = json.loads(msg.data)
        row["observer_wall_ns"] = time.time_ns()
        statuses.append(row)
    def timing(msg):
        row = json.loads(msg.data)
        row["observer_wall_ns"] = time.time_ns()
        results.append(row)
    node.create_subscription(String, "/robot_1/semantic/status", status, 20)
    node.create_subscription(String, "/robot_1/semantic/timing", timing, 20)
    node.create_subscription(String, "/robot_1/camera/capture_trace", source, 20)
    node.create_subscription(CompressedImage, "/robot_1/camera/color/image_compressed", rgb, 20)
    def wait(predicate, seconds=45):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            rclpy.spin_once(node, timeout_sec=.05)
            if predicate():
                return
        raise AssertionError("fault/recovery observation timed out")
    try:
        wait(lambda: statuses and statuses[-1]["ready"])
        initial = statuses[-1]
        results.clear()
        statuses.clear()
        print(json.dumps({"event": "audit_ready", "fault": args.fault,
                          "source_epoch": initial["source_epoch"]}), flush=True)
        if args.fault == "world_reset":
            wait(lambda: statuses and statuses[-1]["source_epoch"] != initial["source_epoch"])
            reset_status = statuses[-1]
            reset_wall = reset_status["observer_wall_ns"]
            wait(lambda: statuses[-1]["ready"] and statuses[-1]["last_result"]["source_epoch"] == reset_status["source_epoch"])
            recovered = statuses[-1]
            assert recovered["stream_epoch"] != initial["stream_epoch"]
            until = time.monotonic() + 5
            wait(lambda: time.monotonic() >= until)
            after = [r for r in results if r["result_wall_ns"] >= reset_wall]
            assert after and all(r["source_epoch"] != initial["source_epoch"] for r in after)
            assert recovered["last_result"]["capture"]["stamp_ns"] < initial["last_result"]["capture"]["stamp_ns"]
            summary = {"reset_status": reset_status, "post_reset_outputs": len(after)}
        else:
            wait(lambda: statuses and not statuses[-1]["ready"])
            failure = statuses[-1]
            assert failure["reason"]
            failure_age_ms = (failure["observer_wall_ns"]-failure["last_result"]["capture_wall_ns"])/1e6
            # 500 ms capture deadline + 50 ms status period + observer allowance.
            assert failure_age_ms <= 600, failure_age_ms
            count = len(results)
            until = time.monotonic() + 3
            wait(lambda: time.monotonic() >= until)
            assert not statuses[-1]["ready"] and len(results) == count
            assert statuses[-1]["last_result"] == failure["last_result"]
            print(json.dumps({"event": "outage_verified", "fault": args.fault}), flush=True)
            wait(lambda: statuses[-1]["ready"] and statuses[-1]["last_result"] != failure["last_result"])
            recovered = statuses[-1]
            until = time.monotonic() + 5
            wait(lambda: time.monotonic() >= until)
            summary = {"failure_status": failure, "quiescent_observation_s": 3,
                "outputs_during_quiescence": 0, "heartbeat_unchanged": True,
                "not_ready_capture_age_ms": failure_age_ms}
        assert results
        assert all(0 <= row["capture_age_upper_ms"] <= 500 for row in results), "invalid capture wall age"
        assert all(0 <= row["simulation_age_ms"] <= 500 for row in results), "invalid simulation age"
        if args.fault == "compressor_delay":
            assert delayed_inputs, "test did not deliver an expired source capture"
            emitted = {(r["source_epoch"], r["capture"]["stamp_ns"]) for r in results}
            assert not any((r["source_epoch"], r["stamp_ns"]) in emitted for r in delayed_inputs)
        report = {"kind": args.fault, "passed": True, "initial_status": initial,
                  "recovered_status": recovered, "results": results, "statuses": statuses,
                  "delayed_inputs_rejected": delayed_inputs, **summary}
        with open(args.output, "x") as handle:
            json.dump(report, handle, sort_keys=True)
        compact = {key: value for key, value in report.items()
                   if key not in ("results", "statuses", "delayed_inputs_rejected")}
        compact["delayed_inputs_rejected_count"] = len(delayed_inputs)
        print(json.dumps(compact, sort_keys=True), flush=True)
    except Exception as error:
        with open(args.output, "x") as handle:
            json.dump({"kind": args.fault, "passed": False, "error": repr(error),
                       "statuses": statuses, "results": results,
                       "delayed_inputs_rejected": delayed_inputs}, handle, sort_keys=True)
        raise
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
