#!/usr/bin/env python3
"""Capture a stopped RGB-D pair from the Phase 7 compressed ROS camera stream."""

from __future__ import annotations

import argparse
import json
import math
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np
try:
    import rclpy
    from nav_msgs.msg import Odometry
    from rclpy.node import Node
    from rclpy.qos import DurabilityPolicy, QoSProfile, qos_profile_sensor_data
    from sensor_msgs.msg import CameraInfo, CompressedImage
    from tf2_msgs.msg import TFMessage
except ImportError:
    rclpy = None
    Node = object
    Odometry = CameraInfo = CompressedImage = TFMessage = None
    DurabilityPolicy = QoSProfile = qos_profile_sensor_data = None


def stamp_ns(msg) -> int:
    return msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec


def decode_color(message: CompressedImage) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(message.data, np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("compressed color frame did not decode as 3-channel image")
    return image


def decode_depth(message: CompressedImage) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(message.data, np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None or image.ndim != 2 or image.dtype != np.uint16:
        raise ValueError("compressed depth frame did not decode as uint16 millimeters")
    return image


class Capture(Node):
    def __init__(self, args):
        if rclpy is None:
            raise RuntimeError("ROS 2 Python packages are required for capture")
        super().__init__("phase7_compressed_capture")
        self.args = args
        self.deadline = time.monotonic() + args.timeout
        self.max_skew_ns = int(args.max_metadata_skew_ms * 1_000_000)
        self.colors = deque(maxlen=10)
        self.depths = deque(maxlen=10)
        self.infos = deque(maxlen=30)
        self.odom = deque(maxlen=80)
        self.static_transforms = []
        self.rows = []
        args.output.mkdir(parents=True, exist_ok=True)
        self.create_subscription(CompressedImage,
            "/robot_1/camera/color/image_compressed", self.on_color, qos_profile_sensor_data)
        self.create_subscription(CompressedImage,
            "/robot_1/camera/depth/image_compressed", self.on_depth, qos_profile_sensor_data)
        self.create_subscription(CameraInfo,
            "/robot_1/camera/color/camera_info", self.on_info, qos_profile_sensor_data)
        self.create_subscription(Odometry,
            "/robot_1/odom", self.on_odom, qos_profile_sensor_data)
        static_qos = QoSProfile(depth=10, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(TFMessage,
            "/robot_1/tf_static", self.on_static_tf, static_qos)

    def on_color(self, message):
        self.colors.append(message)
        self.save_pairs()

    def on_depth(self, message):
        self.depths.append(message)
        self.save_pairs()

    def on_info(self, message):
        self.infos.append(message)
        self.save_pairs()

    def on_odom(self, message):
        self.odom.append(message)
        self.save_pairs()

    def on_static_tf(self, message):
        self.static_transforms = [{
            "parent_frame": item.header.frame_id,
            "child_frame": item.child_frame_id,
            "translation": {"x": item.transform.translation.x,
                            "y": item.transform.translation.y,
                            "z": item.transform.translation.z},
            "rotation_xyzw": {"x": item.transform.rotation.x,
                              "y": item.transform.rotation.y,
                              "z": item.transform.rotation.z,
                              "w": item.transform.rotation.w},
        } for item in message.transforms]
        self.save_pairs()

    def save_pairs(self):
        if not self.colors or not self.depths or len(self.rows) >= self.args.count:
            return
        color = self.colors[-1]
        color_stamp = stamp_ns(color)
        depth = min(self.depths, key=lambda item: abs(stamp_ns(item) - color_stamp))
        depth_skew = abs(stamp_ns(depth) - color_stamp)
        if depth_skew > 30_000_000 or not self.infos or not self.odom or not self.static_transforms:
            return
        info = min(self.infos, key=lambda item: abs(stamp_ns(item) - color_stamp))
        odom = min(self.odom, key=lambda item: abs(stamp_ns(item) - color_stamp))
        info_skew, odom_skew = abs(stamp_ns(info) - color_stamp), abs(stamp_ns(odom) - color_stamp)
        if max(info_skew, odom_skew) > self.max_skew_ns:
            return
        if self.args.world_from_base_link is None:
            raise ValueError("capture-time Gazebo world pose is required")
        speed = math.hypot(odom.twist.twist.linear.x, odom.twist.twist.linear.y)
        angular_speed = abs(odom.twist.twist.angular.z)
        if not self.args.allow_motion and (speed > self.args.max_linear_speed or
                                           angular_speed > self.args.max_angular_speed):
            return
        if self.rows and self.rows[-1]["rgb_stamp_ns"] == color_stamp:
            return
        color_image, depth_mm = decode_color(color), decode_depth(depth)
        if color_image.shape[:2] != depth_mm.shape:
            raise ValueError("compressed RGB and depth dimensions differ")
        index = len(self.rows)
        rgb_path = self.args.output / f"{self.args.label}-{index:04d}.jpg"
        depth_path = self.args.output / f"{self.args.label}-{index:04d}-depth.png"
        if not cv2.imwrite(str(rgb_path), color_image, [cv2.IMWRITE_JPEG_QUALITY, 98]):
            raise RuntimeError(f"failed to save {rgb_path}")
        if not cv2.imwrite(str(depth_path), depth_mm):
            raise RuntimeError(f"failed to save {depth_path}")
        self.rows.append({
            "index": index, "label": self.args.label,
            "rgb": rgb_path.name, "depth": depth_path.name,
            "rgb_stamp_ns": color_stamp, "depth_stamp_ns": stamp_ns(depth),
            "skew_ms": depth_skew / 1_000_000,
            "width": color_image.shape[1], "height": color_image.shape[0],
            "frame_id": color.header.frame_id, "depth_frame_id": depth.header.frame_id,
            "depth_encoding": "16UC1", "camera_info_stamp_ns": stamp_ns(info),
            "camera_info_skew_ms": info_skew / 1_000_000,
            "camera_info": {"frame_id": info.header.frame_id, "width": info.width,
                "height": info.height, "distortion_model": info.distortion_model,
                "d": list(info.d), "k": list(info.k), "r": list(info.r), "p": list(info.p)},
            "odometry_stamp_ns": stamp_ns(odom), "odometry_skew_ms": odom_skew / 1_000_000,
            "odometry": {"frame_id": odom.header.frame_id,
                "child_frame_id": odom.child_frame_id,
                "position": {"x": odom.pose.pose.position.x,
                             "y": odom.pose.pose.position.y,
                             "z": odom.pose.pose.position.z},
                "orientation_xyzw": {"x": odom.pose.pose.orientation.x,
                    "y": odom.pose.pose.orientation.y, "z": odom.pose.pose.orientation.z,
                    "w": odom.pose.pose.orientation.w},
                "linear_velocity_x_mps": odom.twist.twist.linear.x,
                "angular_velocity_z_radps": odom.twist.twist.angular.z},
            "world_from_base_link": self.args.world_from_base_link,
            "world_to_odom_anchor": self.args.world_to_odom_anchor,
            "static_transforms": self.static_transforms,
            "capture_stream": "phase7-compressed-rgbd",
        })
        (self.args.output / "manifest.json").write_text(json.dumps(self.rows, indent=2) + "\n")
        self.get_logger().info(f"saved synchronized pair {len(self.rows)}/{self.args.count}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--label", required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--max-metadata-skew-ms", type=float, default=100.0)
    parser.add_argument("--world-from-base-link", type=float, nargs=7, required=True)
    parser.add_argument("--world-to-odom-anchor", type=float, nargs=7)
    parser.add_argument("--allow-motion", action="store_true")
    parser.add_argument("--max-linear-speed", type=float, default=0.01)
    parser.add_argument("--max-angular-speed", type=float, default=0.01)
    args = parser.parse_args()
    if rclpy is None:
        parser.error("ROS 2 Python packages are required for capture")
    if args.count < 1 or args.timeout <= 0 or args.max_metadata_skew_ms < 0:
        parser.error("count and timeout must be positive; metadata skew must be nonnegative")
    rclpy.init()
    node = Capture(args)
    try:
        end = time.monotonic() + args.timeout
        while len(node.rows) < args.count and time.monotonic() < end and rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.05)
        if len(node.rows) != args.count:
            raise TimeoutError(f"saved {len(node.rows)}/{args.count} synchronized pairs")
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
