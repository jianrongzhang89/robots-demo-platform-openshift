#!/usr/bin/env python3
"""Read-only raw RGB-D timestamp and callback-order diagnostic."""

from __future__ import annotations

import argparse
import json
import time
from collections import deque

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image


def stamp_ns(message: Image) -> int:
    return message.header.stamp.sec * 1_000_000_000 + message.header.stamp.nanosec


def percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(int(fraction * (len(ordered) - 1)), len(ordered) - 1)]


class PairingDiagnostic(Node):
    def __init__(self, duration: float, tolerance_ms: float, queue_size: int):
        super().__init__("semantic_rgbd_pairing_diagnostic")
        self.duration = duration
        self.tolerance_ns = int(tolerance_ms * 1_000_000)
        self.queue_capacities = sorted({queue_size, max(queue_size, 100)})
        self.started = time.monotonic()
        self.events: list[tuple[int, str, int]] = []
        self.last_stamp = {"rgb": None, "depth": None}
        self.inversions = {"rgb": 0, "depth": 0}
        self.online = {
            capacity: {
                "queues": {
                    "rgb": deque(maxlen=capacity),
                    "depth": deque(maxlen=capacity),
                },
                "pairs": 0,
                "discards": {"rgb": 0, "depth": 0},
                "evictions": {"rgb": 0, "depth": 0},
            }
            for capacity in self.queue_capacities
        }
        qos = QoSProfile(depth=20, reliability=ReliabilityPolicy.RELIABLE)
        self.create_subscription(
            Image, "/robot_1/camera/color/image_raw",
            lambda msg: self.callback("rgb", msg), qos)
        self.create_subscription(
            Image, "/robot_1/camera/depth/image_raw",
            lambda msg: self.callback("depth", msg), qos)
        self.timer = self.create_timer(1.0, self.check_done)

    def callback(self, stream: str, message: Image) -> None:
        stamp = stamp_ns(message)
        prior = self.last_stamp[stream]
        if prior is not None and stamp < prior:
            self.inversions[stream] += 1
        self.last_stamp[stream] = stamp
        self.events.append((time.monotonic_ns(), stream, stamp))

        for state in self.online.values():
            queues = state["queues"]
            queue = queues[stream]
            if len(queue) == queue.maxlen:
                state["evictions"][stream] += 1
            queue.append(stamp)
            rgb, depth = queues["rgb"], queues["depth"]
            while rgb and depth:
                delta = rgb[0] - depth[0]
                if abs(delta) <= self.tolerance_ns:
                    rgb.popleft()
                    depth.popleft()
                    state["pairs"] += 1
                elif delta < 0:
                    rgb.popleft()
                    state["discards"]["rgb"] += 1
                else:
                    depth.popleft()
                    state["discards"]["depth"] += 1

    def check_done(self) -> None:
        if time.monotonic() - self.started < self.duration:
            return
        rgb_stamps = [stamp for _, stream, stamp in self.events if stream == "rgb"]
        depth_stamps = [stamp for _, stream, stamp in self.events if stream == "depth"]
        i = j = offline_pairs = 0
        skews = []
        while i < len(rgb_stamps) and j < len(depth_stamps):
            delta = rgb_stamps[i] - depth_stamps[j]
            if abs(delta) <= self.tolerance_ns:
                skews.append(abs(delta))
                offline_pairs += 1
                i += 1
                j += 1
            elif delta < 0:
                i += 1
            else:
                j += 1
        online_summary = {
            str(capacity): {
                "pairs": state["pairs"],
                "timestamp_discards": state["discards"],
                "queue_evictions": state["evictions"],
                "queued_at_end": {
                    key: len(queue) for key, queue in state["queues"].items()
                },
            }
            for capacity, state in self.online.items()
        }
        summary = {
            "duration_wall_s": round(time.monotonic() - self.started, 3),
            "callbacks": {"rgb": len(rgb_stamps), "depth": len(depth_stamps)},
            "source_stamp_inversions": self.inversions,
            "tolerance_ms": self.tolerance_ns / 1_000_000,
            "online_by_queue_capacity": online_summary,
            "offline_timestamp_order_pairs": offline_pairs,
            "offline_pairs_skew_ms": {
                "p50": None if not skews else percentile(skews, 0.50) / 1_000_000,
                "p95": None if not skews else percentile(skews, 0.95) / 1_000_000,
                "max": None if not skews else max(skews) / 1_000_000,
            },
            "offline_unmatched_by_stream": {
                "rgb": len(rgb_stamps) - offline_pairs,
                "depth": len(depth_stamps) - offline_pairs,
            },
        }
        self.get_logger().info("RGBD_PAIRING_DIAGNOSTIC " + json.dumps(summary, sort_keys=True))
        rclpy.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=120)
    parser.add_argument("--tolerance-ms", type=float, default=30)
    parser.add_argument("--queue-size", type=int, default=10)
    args = parser.parse_args()
    if args.duration <= 0 or args.tolerance_ms < 0 or args.queue_size < 1:
        parser.error("duration and queue size must be positive; tolerance cannot be negative")
    rclpy.init()
    node = PairingDiagnostic(args.duration, args.tolerance_ms, args.queue_size)
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()


if __name__ == "__main__":
    main()
