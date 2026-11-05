#!/usr/bin/env python3
"""Pair Gazebo RGB-D frames and encode them for the cross-pod Zenoh link."""

from __future__ import annotations

import cv2
import numpy as np
import rclpy
import os
import json
import time
import threading
from collections import OrderedDict, deque
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from rclpy.qos import QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CompressedImage, Image
from std_msgs.msg import String

from rgbd_pairing import drain_synchronized_pairs
from camera_qos import subscription_history_depth


def image_array(msg: Image) -> np.ndarray:
    if msg.encoding in ("rgb8", "bgr8", "R8G8B8", "B8G8R8"):
        channels = 3
        dtype = np.dtype("u1")
    elif msg.encoding in ("32FC1", "32FC"):
        channels = 1
        dtype = np.dtype(">f4" if msg.is_bigendian else "<f4")
    elif msg.encoding in ("16UC1", "mono16"):
        channels = 1
        dtype = np.dtype(">u2" if msg.is_bigendian else "<u2")
    else:
        raise ValueError(f"unsupported camera encoding {msg.encoding!r}")
    row_elements = msg.step // dtype.itemsize
    raw = np.frombuffer(msg.data, dtype=dtype).reshape(msg.height, row_elements)
    raw = raw[:, : msg.width * channels]
    if channels == 1:
        return raw.reshape(msg.height, msg.width)
    return raw.reshape(msg.height, msg.width, channels)


class CameraCompressor(Node):
    def __init__(self):
        super().__init__("semantic_camera_compressor")
        self.rgb_pub = self.create_publisher(
            CompressedImage, "/robot_1/camera/color/image_compressed", 10)
        self.depth_pub = self.create_publisher(
            CompressedImage, "/robot_1/camera/depth/image_compressed", 10)
        self.trace_enabled = os.getenv("SEMANTIC_COMPRESSION_TRACE") == "1"
        self.raw_transport = os.getenv("SEMANTIC_RAW_INPUT", "ros")
        if self.raw_transport not in ("ros", "gz"):
            raise ValueError("SEMANTIC_RAW_INPUT must explicitly select ros or gz")
        self.trace_pub = self.create_publisher(String, "/robot_1/camera/compression_trace", 20)
        self.receipts = {"rgb": OrderedDict(), "depth": OrderedDict()}
        self.rgb_queue: deque[Image] = deque(maxlen=10)
        self.depth_queue: deque[Image] = deque(maxlen=10)
        self.input_frames = {"rgb": 0, "depth": 0}
        self.skew_checks = 0
        self.skew_discards = 0
        self.max_skew_ms = 0.0
        self.queue_evictions = {"rgb": 0, "depth": 0}
        self.timestamp_discards = {"rgb": 0, "depth": 0}
        self.queue_high_water = {"rgb": 0, "depth": 0}
        self.frames = 0
        self.last_batch_max_skew_ms: float | None = None
        self.fault_path = os.getenv("PHASE3_CAMERA_FAULT_FILE")
        self.last_fault_token = None
        subscription_depth = subscription_history_depth(
            os.environ.get("SEMANTIC_CAMERA_SUBSCRIPTION_DEPTH")
        )
        camera_qos = QoSProfile(
            depth=subscription_depth, reliability=ReliabilityPolicy.RELIABLE
        )
        if self.raw_transport == "ros":
            self.create_subscription(
                Image, "/robot_1/camera/color/image_raw", self.rgb_cb, camera_qos)
            self.create_subscription(
                Image, "/robot_1/camera/depth/image_raw", self.depth_cb, camera_qos)
        else:
            if not os.getenv("GZ_PARTITION"):
                raise ValueError("native Gazebo input requires an explicit GZ_PARTITION")
            from gz.transport13 import Node as GzNode
            from gz.msgs10.image_pb2 import Image as GzImage
            self.gz_lock = threading.Lock()
            self.gz_node = GzNode()
            self.gz_node.subscribe(GzImage, "/robot_1/camera/image", lambda msg: self.gz_receive("rgb", msg))
            self.gz_node.subscribe(GzImage, "/robot_1/camera/depth_image", lambda msg: self.gz_receive("depth", msg))
        self.get_logger().info(
            f"raw subscription QoS: reliable, history depth={subscription_depth}"
        )
        self.get_logger().info(f"explicit raw camera transport: {self.raw_transport}")
        self.create_timer(10.0, self.report_status)

    def gz_receive(self, kind, message):
        # Gazebo callbacks may run concurrently. Keep the existing pairer and
        # encoder single-owner, just as with rclpy's single-threaded executor.
        with self.gz_lock:
            try:
                msg = Image()
                msg.header.stamp.sec = message.header.stamp.sec
                msg.header.stamp.nanosec = message.header.stamp.nsec
                frames = [entry.value[0] for entry in message.header.data
                          if entry.key == "frame_id" and entry.value]
                if len(frames) != 1 or not frames[0]:
                    raise ValueError("Gazebo image lacks an unambiguous optical frame")
                msg.header.frame_id = frames[0]
                msg.width, msg.height, msg.step = message.width, message.height, message.step
                fmt = message.DESCRIPTOR.fields_by_name["pixel_format_type"].enum_type.values_by_number[message.pixel_format_type].name
                msg.encoding = {"RGB_INT8": "rgb8", "BGR_INT8": "bgr8", "R_FLOAT32": "32FC1"}[fmt]
                msg.is_bigendian = False  # pinned x86_64 Gazebo source
                msg.data = message.data
                (self.rgb_cb if kind == "rgb" else self.depth_cb)(msg)
            except Exception as error:
                self.get_logger().error(f"dropping invalid native Gazebo image: {error}")

    def report_status(self):
        self.get_logger().info(
            f"status inputs={self.input_frames} paired={self.frames} "
            f"skew_checks={self.skew_checks} skew_discards={self.skew_discards} "
            f"max_skew_ms={self.max_skew_ms} "
            f"last_batch_max_skew_ms={self.last_batch_max_skew_ms} "
            f"queue_evictions={self.queue_evictions} "
            f"timestamp_discards={self.timestamp_discards} "
            f"queue_high_water={self.queue_high_water} "
            f"queued_rgb={len(self.rgb_queue)} queued_depth={len(self.depth_queue)}")

    @staticmethod
    def stamp_ns(msg: Image) -> int:
        return msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec

    def rgb_cb(self, msg: Image):
        self.record_receipt("rgb", msg)
        self.input_frames["rgb"] += 1
        if len(self.rgb_queue) == self.rgb_queue.maxlen:
            self.queue_evictions["rgb"] += 1
        self.rgb_queue.append(msg)
        self.queue_high_water["rgb"] = max(
            self.queue_high_water["rgb"], len(self.rgb_queue))
        self.match_and_encode()

    def depth_cb(self, msg: Image):
        self.record_receipt("depth", msg)
        self.input_frames["depth"] += 1
        if len(self.depth_queue) == self.depth_queue.maxlen:
            self.queue_evictions["depth"] += 1
        self.depth_queue.append(msg)
        self.queue_high_water["depth"] = max(
            self.queue_high_water["depth"], len(self.depth_queue))
        self.match_and_encode()

    def record_receipt(self, kind, msg):
        if self.trace_enabled:
            self.receipts[kind][self.stamp_ns(msg)] = time.time_ns()
            if len(self.receipts[kind]) > 20:
                self.receipts[kind].popitem(last=False)

    def match_and_encode(self):
        if not self.rgb_queue or not self.depth_queue:
            return
        pairs, discarded, checks, batch_max_skew_ns = drain_synchronized_pairs(
            self.rgb_queue, self.depth_queue, self.stamp_ns, 30_000_000
        )
        self.skew_checks += checks
        self.skew_discards += sum(discarded.values())
        self.timestamp_discards["rgb"] += discarded["rgb"]
        self.timestamp_discards["depth"] += discarded["depth"]
        if checks:
            batch_max_skew_ms = batch_max_skew_ns / 1_000_000.0
            self.last_batch_max_skew_ms = batch_max_skew_ms
            self.max_skew_ms = max(self.max_skew_ms, batch_max_skew_ms)
        for rgb_msg, depth_msg in pairs:
            self.encode_pair(rgb_msg, depth_msg)

    def encode_pair(self, rgb_msg: Image, depth_msg: Image):
        try:
            # Explicit private-stack diagnostic hook. No default fault behavior.
            if self.fault_path and os.path.isfile(self.fault_path):
                with open(self.fault_path) as handle:
                    fault = json.load(handle)
                token = fault.get("token")
                if fault.get("mode") == "delay" and token and token != self.last_fault_token:
                    self.last_fault_token = token
                    self.get_logger().warning("diagnostic camera delivery delay started")
                    time.sleep(min(10.0, max(0.0, float(fault.get("seconds", 8)))))
                    self.get_logger().warning("diagnostic camera delivery delay finished")
            compression_start_ns = time.time_ns()
            rgb = image_array(rgb_msg)
            if rgb_msg.encoding in ("rgb8", "R8G8B8"):
                rgb = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            ok, encoded_rgb = cv2.imencode(
                ".jpg", rgb, [cv2.IMWRITE_JPEG_QUALITY, 90])
            if not ok:
                raise ValueError("JPEG encoding failed")

            depth = image_array(depth_msg)
            if depth_msg.encoding in ("32FC1", "32FC"):
                valid = np.isfinite(depth) & (depth >= 0.15) & (depth <= 5.0)
                depth_mm = np.zeros(depth.shape, dtype=np.uint16)
                depth_mm[valid] = np.rint(depth[valid] * 1000.0).astype(np.uint16)
            else:
                depth_mm = depth.astype(np.uint16, copy=False)
            ok, encoded_depth = cv2.imencode(".png", depth_mm)
            if not ok:
                raise ValueError("PNG depth encoding failed")

            rgb_out = CompressedImage()
            rgb_out.header = rgb_msg.header
            rgb_out.format = "jpeg"
            rgb_out.data = encoded_rgb.tobytes()
            depth_out = CompressedImage()
            depth_out.header = depth_msg.header
            depth_out.format = "16UC1; png; units=mm"
            depth_out.data = encoded_depth.tobytes()
            if self.trace_enabled:
                self.trace_pub.publish(String(data=json.dumps({
                    "schema": "semantic-compression/v1", "stamp_ns": self.stamp_ns(rgb_msg),
                    "input_transport": self.raw_transport,
                    "depth_stamp_ns": self.stamp_ns(depth_msg),
                    "rgb_received_wall_ns": self.receipts["rgb"].pop(self.stamp_ns(rgb_msg), None),
                    "depth_received_wall_ns": self.receipts["depth"].pop(self.stamp_ns(depth_msg), None),
                    "compression_start_wall_ns": compression_start_ns,
                    "compression_end_wall_ns": time.time_ns(),
                }, sort_keys=True)))
            self.rgb_pub.publish(rgb_out)
            self.depth_pub.publish(depth_out)
            self.frames += 1
            if self.frames % 50 == 0:
                self.get_logger().info(
                    f"paired={self.frames} inputs={self.input_frames} "
                    f"rgb_jpeg={len(rgb_out.data)}B "
                    f"depth_png={len(depth_out.data)}B")
        except Exception as error:  # keep the camera bridge alive on a bad frame
            self.get_logger().error(f"dropping invalid RGB-D pair: {error}")


def main():
    rclpy.init()
    node = CameraCompressor()
    node.get_logger().info("RGB-D compressor started; waiting for raw color and depth samples")
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
