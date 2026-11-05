#!/usr/bin/env python3
"""Read-only receiver-side RGB-D stream check for phase 1."""

from __future__ import annotations

import json
import time
from collections import deque

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CameraInfo, CompressedImage
from tf2_ros import Buffer, TransformException, TransformListener


def stamp_ns(header) -> int:
    return header.stamp.sec * 1_000_000_000 + header.stamp.nanosec


class CameraStreamProbe(Node):
    def __init__(self, duration: float):
        # The hotel simulation publishes robot-scoped TF topics. Apply the
        # same remaps to TransformListener's /tf subscriptions on this pod.
        super().__init__(
            "semantic_camera_stream_probe",
            cli_args=["-r", "/tf:=/robot_1/tf", "-r", "/tf_static:=/robot_1/tf_static"],
        )
        self.duration = duration
        self.started = time.monotonic()
        self.images: deque[CompressedImage] = deque(maxlen=20)
        self.depths: deque[CompressedImage] = deque(maxlen=20)
        self.infos: deque[CameraInfo] = deque(maxlen=20)
        self.valid_pairs: list[tuple[int, int]] = []
        self.bad_frames = 0
        self.tf_ok = 0
        self.tf_missing = 0
        self.depth_valid_fractions: list[float] = []
        self.reconstructed_points: list[int] = []
        self.encoded_bytes = {"rgb": 0, "depth": 0}
        self.frames = {"rgb_compressed": 0, "depth_compressed": 0, "info": 0}
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.create_subscription(CompressedImage, "/robot_1/camera/color/image_compressed", self.rgb_cb, qos_profile_sensor_data)
        self.create_subscription(CompressedImage, "/robot_1/camera/depth/image_compressed", self.depth_cb, qos_profile_sensor_data)
        self.create_subscription(CameraInfo, "/robot_1/camera/color/camera_info", self.info_cb, qos_profile_sensor_data)
        self.timer = self.create_timer(1.0, self.tick)

    def rgb_cb(self, msg: CompressedImage):
        self.frames["rgb_compressed"] += 1
        self.encoded_bytes["rgb"] += len(msg.data)
        self.images.append(msg)
        self.match()

    def depth_cb(self, msg: CompressedImage):
        self.frames["depth_compressed"] += 1
        self.encoded_bytes["depth"] += len(msg.data)
        self.depths.append(msg)
        self.match()

    def info_cb(self, msg: CameraInfo):
        self.frames["info"] += 1
        self.infos.append(msg)

    def match(self):
        if not (self.images and self.depths and self.infos):
            return
        rgb = self.images[-1]
        rgb_stamp = stamp_ns(rgb.header)
        depth = min(self.depths, key=lambda msg: abs(stamp_ns(msg.header) - rgb_stamp))
        delta_depth = abs(stamp_ns(depth.header) - rgb_stamp)
        info = min(self.infos, key=lambda msg: abs(stamp_ns(msg.header) - rgb_stamp))
        delta_info = abs(stamp_ns(info.header) - rgb_stamp)
        if delta_depth > 30_000_000 or delta_info > 100_000_000:
            return
        if self.valid_pairs and self.valid_pairs[-1][0] == rgb_stamp:
            return
        rgb_array = cv2.imdecode(np.frombuffer(rgb.data, dtype=np.uint8), cv2.IMREAD_COLOR)
        depth_mm = cv2.imdecode(np.frombuffer(depth.data, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        fields_ok = (rgb_array is not None and depth_mm is not None and
                     rgb_array.shape == (480, 640, 3) and
                     depth_mm.shape == (480, 640) and depth_mm.dtype == np.uint16 and
                     rgb.header.frame_id == depth.header.frame_id == info.header.frame_id and
                     info.width == 640 and info.height == 480 and
                     info.k[0] > 0 and info.k[4] > 0)
        if not fields_ok:
            self.bad_frames += 1
            return
        valid = depth_mm > 0
        self.depth_valid_fractions.append(float(valid.mean()))
        # Reconstruct an organized XYZ cloud from the pixel-aligned depth and
        # CameraInfo. Geometry remains local to the receiver; no large raw
        # PointCloud2 is sent through Zenoh.
        v, u = np.indices(depth_mm.shape, dtype=np.float32)
        z = depth_mm.astype(np.float32) / 1000.0
        x = (u - float(info.k[2])) * z / float(info.k[0])
        y = (v - float(info.k[5])) * z / float(info.k[4])
        xyz = np.stack((x, y, z), axis=-1)
        self.reconstructed_points.append(int(np.isfinite(xyz[valid]).all(axis=1).sum()))
        self.valid_pairs.append((rgb_stamp, time.monotonic_ns()))
        try:
            self.tf_buffer.lookup_transform(
                "base_link", rgb.header.frame_id,
                rclpy.time.Time.from_msg(rgb.header.stamp),
            )
            self.tf_ok += 1
        except TransformException:
            self.tf_missing += 1

    def tick(self):
        elapsed = time.monotonic() - self.started
        if int(elapsed) % 10 == 0:
            self.get_logger().info(json.dumps({
                "elapsed_wall_s": round(elapsed, 1),
                "received": self.frames,
                "synchronized_rgb_depth_and_camera_info": len(self.valid_pairs),
                "mean_depth_valid_fraction": None if not self.depth_valid_fractions else float(np.mean(self.depth_valid_fractions)),
                "mean_reconstructed_finite_points": None if not self.reconstructed_points else float(np.mean(self.reconstructed_points)),
                "encoded_bytes_per_second": {key: round(value / max(elapsed, 1e-9), 1) for key, value in self.encoded_bytes.items()},
                "invalid_layout_or_frame": self.bad_frames,
                "tf_lookup_ok": self.tf_ok,
                "tf_lookup_missing": self.tf_missing,
                "camera_info": None if not self.infos else {
                    "width": self.infos[-1].width,
                    "height": self.infos[-1].height,
                    "frame_id": self.infos[-1].header.frame_id,
                    "k": list(self.infos[-1].k),
                },
            }))
        if elapsed >= self.duration:
            deltas = [
                (self.valid_pairs[i][0] - self.valid_pairs[i - 1][0]) / 1e9
                for i in range(1, len(self.valid_pairs))
            ]
            total_elapsed = max(elapsed, 1e-9)
            summary = {
                "duration_wall_s": round(elapsed, 3),
                "received": self.frames,
                "synchronized_rgb_depth_and_camera_info": len(self.valid_pairs),
                "synchronized_pairs_per_wall_second": round(len(self.valid_pairs) / total_elapsed, 3),
                "mean_depth_valid_fraction": None if not self.depth_valid_fractions else float(np.mean(self.depth_valid_fractions)),
                "mean_reconstructed_finite_points": None if not self.reconstructed_points else float(np.mean(self.reconstructed_points)),
                "encoded_bytes_per_second": {key: round(value / total_elapsed, 1) for key, value in self.encoded_bytes.items()},
                "invalid_layout_or_frame": self.bad_frames,
                "tf_lookup_ok": self.tf_ok,
                "tf_lookup_missing": self.tf_missing,
                "capture_interval_p95_s": None if not deltas else sorted(deltas)[int(0.95 * (len(deltas) - 1))],
                "camera_info": None if not self.infos else {
                    "width": self.infos[-1].width,
                    "height": self.infos[-1].height,
                    "frame_id": self.infos[-1].header.frame_id,
                    "k": list(self.infos[-1].k),
                },
            }
            self.get_logger().info("PHASE1_SUMMARY " + json.dumps(summary))
            rclpy.shutdown()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=600)
    args = parser.parse_args()
    rclpy.init()
    node = CameraStreamProbe(args.duration)
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()


if __name__ == "__main__":
    main()
