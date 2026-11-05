#!/usr/bin/env python3
"""Save synchronized robot RGB-D camera pairs and capture metadata."""

from __future__ import annotations

import argparse
import json
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, qos_profile_sensor_data
from nav_msgs.msg import Odometry
from sensor_msgs.msg import CameraInfo, Image
from tf2_msgs.msg import TFMessage


def stamp_ns(msg: Image) -> int:
    return msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec


class Capture(Node):
    def __init__(self, output: Path, count: int, label: str, timeout: float,
                 max_metadata_skew_ms: float, world_anchor: list[float] | None,
                 world_from_base_link: list[float] | None,
                 require_stopped: bool, max_linear_speed: float,
                 max_angular_speed: float):
        super().__init__("semantic_phase2_capture")
        self.output = output
        self.count = count
        self.label = label
        self.deadline = time.monotonic() + timeout
        self.max_metadata_skew_ns = int(max_metadata_skew_ms * 1_000_000)
        self.world_anchor = world_anchor
        self.world_from_base_link = world_from_base_link
        self.require_stopped = require_stopped
        self.max_linear_speed = max_linear_speed
        self.max_angular_speed = max_angular_speed
        self.colors: deque[Image] = deque(maxlen=5)
        self.depths: deque[Image] = deque(maxlen=5)
        self.camera_infos: deque[CameraInfo] = deque(maxlen=20)
        self.odometry: deque[Odometry] = deque(maxlen=50)
        self.static_transforms: list[dict] = []
        self.rows = []
        output.mkdir(parents=True, exist_ok=True)
        self.create_subscription(Image, "/robot_1/camera/color/image_raw",
                                 self.color_cb, qos_profile_sensor_data)
        self.create_subscription(Image, "/robot_1/camera/depth/image_raw",
                                 self.depth_cb, qos_profile_sensor_data)
        self.create_subscription(CameraInfo, "/robot_1/camera/color/camera_info",
                                 self.camera_info_cb, qos_profile_sensor_data)
        self.create_subscription(Odometry, "/robot_1/odom",
                                 self.odometry_cb, qos_profile_sensor_data)
        static_tf_qos = QoSProfile(depth=10, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(TFMessage, "/robot_1/tf_static",
                                 self.static_tf_cb, static_tf_qos)
        self.create_timer(0.2, self.check_deadline)

    def color_cb(self, msg: Image):
        self.colors.append(msg)
        self.save_pairs()

    def depth_cb(self, msg: Image):
        self.depths.append(msg)
        self.save_pairs()

    def camera_info_cb(self, msg: CameraInfo):
        self.camera_infos.append(msg)
        self.save_pairs()

    def odometry_cb(self, msg: Odometry):
        self.odometry.append(msg)
        self.save_pairs()

    def static_tf_cb(self, msg: TFMessage):
        self.static_transforms = [
            {
                "parent_frame": item.header.frame_id,
                "child_frame": item.child_frame_id,
                "translation": {
                    "x": item.transform.translation.x,
                    "y": item.transform.translation.y,
                    "z": item.transform.translation.z,
                },
                "rotation_xyzw": {
                    "x": item.transform.rotation.x,
                    "y": item.transform.rotation.y,
                    "z": item.transform.rotation.z,
                    "w": item.transform.rotation.w,
                },
            }
            for item in msg.transforms
        ]
        self.save_pairs()

    def check_deadline(self):
        if time.monotonic() > self.deadline:
            diagnostics = {
                "saved": len(self.rows), "requested": self.count,
                "buffered_color": len(self.colors), "buffered_depth": len(self.depths),
                "buffered_camera_info": len(self.camera_infos),
                "buffered_odometry": len(self.odometry),
                "static_transform_count": len(self.static_transforms),
            }
            if self.colors and self.depths:
                color = self.colors[-1]
                depth = min(self.depths, key=lambda item: abs(stamp_ns(item) - stamp_ns(color)))
                diagnostics["latest_rgb_depth_skew_ms"] = abs(
                    stamp_ns(depth) - stamp_ns(color)
                ) / 1_000_000
                if self.camera_infos:
                    info = min(self.camera_infos,
                               key=lambda item: abs(stamp_ns(item) - stamp_ns(color)))
                    diagnostics["latest_camera_info_skew_ms"] = abs(
                        stamp_ns(info) - stamp_ns(color)
                    ) / 1_000_000
                if self.odometry:
                    odom = min(self.odometry,
                               key=lambda item: abs(stamp_ns(item) - stamp_ns(color)))
                    diagnostics["latest_odometry_skew_ms"] = abs(
                        stamp_ns(odom) - stamp_ns(color)
                    ) / 1_000_000
            self.get_logger().error(f"capture timeout: {json.dumps(diagnostics)}")
            rclpy.shutdown()

    def save_pairs(self):
        if not self.colors or not self.depths or len(self.rows) >= self.count:
            return
        color = self.colors[-1]
        depth = min(self.depths, key=lambda item: abs(stamp_ns(item) - stamp_ns(color)))
        if abs(stamp_ns(depth) - stamp_ns(color)) > 30_000_000:
            return
        if not self.camera_infos or not self.odometry or not self.static_transforms:
            return
        camera_info = min(self.camera_infos,
                          key=lambda item: abs(stamp_ns(item) - stamp_ns(color)))
        odometry = min(self.odometry,
                       key=lambda item: abs(stamp_ns(item) - stamp_ns(color)))
        camera_info_skew = abs(stamp_ns(camera_info) - stamp_ns(color))
        odometry_skew = abs(stamp_ns(odometry) - stamp_ns(color))
        if max(camera_info_skew, odometry_skew) > self.max_metadata_skew_ns:
            return
        if self.require_stopped and (
            abs(odometry.twist.twist.linear.x) > self.max_linear_speed
            or abs(odometry.twist.twist.angular.z) > self.max_angular_speed
        ):
            return
        if self.rows and self.rows[-1]["rgb_stamp_ns"] == stamp_ns(color):
            return
        rgb = np.frombuffer(color.data, dtype=np.uint8).reshape(color.height, color.step)
        rgb = rgb[:, : color.width * 3].reshape(color.height, color.width, 3)
        if color.encoding in ("rgb8", "R8G8B8"):
            rgb = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        if depth.encoding in ("32FC1", "32FC"):
            depth_dtype = np.dtype(">f4" if depth.is_bigendian else "<f4")
        elif depth.encoding in ("16UC1", "mono16"):
            depth_dtype = np.dtype(">u2" if depth.is_bigendian else "<u2")
        else:
            raise ValueError(f"unsupported depth encoding {depth.encoding!r}")
        raw_depth = np.frombuffer(depth.data, dtype=depth_dtype).reshape(
            depth.height, depth.step // depth_dtype.itemsize
        )[:, : depth.width]
        if depth.encoding in ("32FC1", "32FC"):
            valid = np.isfinite(raw_depth) & (raw_depth >= 0.15) & (raw_depth <= 5.0)
            depth_mm = np.zeros(raw_depth.shape, dtype=np.uint16)
            depth_mm[valid] = np.rint(raw_depth[valid] * 1000.0).astype(np.uint16)
        else:
            depth_mm = raw_depth.astype(np.uint16, copy=False)
        index = len(self.rows)
        rgb_path = self.output / f"{self.label}-{index:04d}.jpg"
        depth_path = self.output / f"{self.label}-{index:04d}-depth.png"
        if not cv2.imwrite(str(rgb_path), rgb, [cv2.IMWRITE_JPEG_QUALITY, 98]):
            raise RuntimeError(f"failed to save {rgb_path}")
        if not cv2.imwrite(str(depth_path), depth_mm):
            raise RuntimeError(f"failed to save {depth_path}")
        self.rows.append({
            "index": index, "label": self.label,
            "rgb": rgb_path.name, "depth": depth_path.name,
            "rgb_stamp_ns": stamp_ns(color), "depth_stamp_ns": stamp_ns(depth),
            "skew_ms": abs(stamp_ns(depth) - stamp_ns(color)) / 1_000_000,
            "width": color.width, "height": color.height,
            "frame_id": color.header.frame_id,
            "depth_frame_id": depth.header.frame_id,
            "depth_encoding": depth.encoding,
            "camera_info_stamp_ns": stamp_ns(camera_info),
            "camera_info_skew_ms": camera_info_skew / 1_000_000,
            "camera_info": {
                "frame_id": camera_info.header.frame_id,
                "width": camera_info.width,
                "height": camera_info.height,
                "distortion_model": camera_info.distortion_model,
                "d": list(camera_info.d),
                "k": list(camera_info.k),
                "r": list(camera_info.r),
                "p": list(camera_info.p),
            },
            "odometry_stamp_ns": stamp_ns(odometry),
            "odometry_skew_ms": odometry_skew / 1_000_000,
            "odometry": {
                "frame_id": odometry.header.frame_id,
                "child_frame_id": odometry.child_frame_id,
                "position": {
                    "x": odometry.pose.pose.position.x,
                    "y": odometry.pose.pose.position.y,
                    "z": odometry.pose.pose.position.z,
                },
                "orientation_xyzw": {
                    "x": odometry.pose.pose.orientation.x,
                    "y": odometry.pose.pose.orientation.y,
                    "z": odometry.pose.pose.orientation.z,
                    "w": odometry.pose.pose.orientation.w,
                },
                "linear_velocity_x_mps": odometry.twist.twist.linear.x,
                "angular_velocity_z_radps": odometry.twist.twist.angular.z,
            },
            "world_to_odom_anchor": self.world_anchor,
            "world_from_base_link": self.world_from_base_link,
            "static_transforms": self.static_transforms,
        })
        (self.output / "manifest.json").write_text(json.dumps(self.rows, indent=2) + "\n")
        self.get_logger().info(f"saved synchronized pair {len(self.rows)}/{self.count}")
        if len(self.rows) >= self.count:
            rclpy.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--label", required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--max-metadata-skew-ms", type=float, default=100.0)
    parser.add_argument(
        "--world-to-odom-anchor", type=float, nargs=7,
        metavar=("X", "Y", "Z", "QX", "QY", "QZ", "QW"),
        help="world-frame pose of odom origin (translation and quaternion xyzw)",
    )
    parser.add_argument("--allow-motion", action="store_true",
                        help="capture moving samples (not suitable for Phase 2 scoring)")
    parser.add_argument("--max-linear-speed", type=float, default=0.01)
    parser.add_argument("--max-angular-speed", type=float, default=0.01)
    parser.add_argument(
        "--world-from-base-link", type=float, nargs=7,
        metavar=("X", "Y", "Z", "QX", "QY", "QZ", "QW"),
        help="capture-time Gazebo world pose of robot_1/base_link",
    )
    args = parser.parse_args()
    if args.max_metadata_skew_ms < 0:
        parser.error("--max-metadata-skew-ms must be non-negative")
    if args.max_linear_speed < 0 or args.max_angular_speed < 0:
        parser.error("stop speed limits must be non-negative")
    rclpy.init()
    node = Capture(args.output, args.count, args.label, args.timeout,
                   args.max_metadata_skew_ms, args.world_to_odom_anchor,
                   args.world_from_base_link, not args.allow_motion,
                   args.max_linear_speed, args.max_angular_speed)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0 if len(node.rows) == args.count else 1


if __name__ == "__main__":
    raise SystemExit(main())
