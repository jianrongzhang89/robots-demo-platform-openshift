#!/usr/bin/env python3
"""SAM3 RGB-D inference node; publishes diagnostic outputs only."""

from __future__ import annotations

import json
import hashlib
import os
import threading
import time
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import numpy as np
import rclpy
from PIL import Image as PILImage
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from rclpy._rclpy_pybind11 import RCLError
from rclpy.clock import Clock, ClockType
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CameraInfo, CompressedImage, Image, PointCloud2, PointField
from std_msgs.msg import Bool, String
from rosgraph_msgs.msg import Clock as ClockMessage
from backend_factory import create_backend
from http_backend import IdentityMismatch
from rcl_interfaces.msg import SetParametersResult
from inference_contract import POLICY, VERSIONS, ResultGuard, make_request, dimensions
from capture_timing import validate_capture_trace, capture_deadline, capture_age_upper_ms, simulation_capture_age_ms

from sam3_runtime_core import (
    pop_synchronized_triplet,
    stamp_ns,
    work_wait_expired,
)


@dataclass(frozen=True)
class FrameBundle:
    rgb: CompressedImage
    depth: CompressedImage
    info: CameraInfo
    received_monotonic: float
    sequence: int
    epoch: str


class Sam3Runtime(Node):
    def __init__(self):
        super().__init__("sam3_semantic_inference")
        self.declare_parameter("checkpoint", "/models/sam3.pt")
        self.declare_parameter("backend", os.getenv("SEMANTIC_BACKEND", "local"))
        self.declare_parameter("robot_id", "robot_1")
        self.declare_parameter("stream_id", "camera/color")
        self.declare_parameter("input_prefix", "/robot_1/camera")
        self.declare_parameter("output_prefix", "/robot_1/semantic")
        for name, env in (("endpoint", "SEMANTIC_ENDPOINT"), ("tls_ca", "SEMANTIC_TLS_CA"),
                          ("tls_cert", "SEMANTIC_TLS_CERT"), ("tls_key", "SEMANTIC_TLS_KEY"),
                          ("deployment_identity", "SEMANTIC_DEPLOYMENT_IDENTITY")):
            self.declare_parameter(name, os.getenv(env, ""))
        self.backend_kind = str(self.get_parameter("backend").value)
        if self.backend_kind not in ("local", "http"):
            raise ValueError("backend must be local or http")
        self.robot_id = str(self.get_parameter("robot_id").value)
        self.stream_id = str(self.get_parameter("stream_id").value)
        self.input_prefix = str(self.get_parameter("input_prefix").value).rstrip("/")
        self.output_prefix = str(self.get_parameter("output_prefix").value).rstrip("/")
        if any(not 0 < len(v) <= 256 for v in (self.robot_id, self.stream_id)):
            raise ValueError("explicit bounded robot and stream identity required")
        if any(not v.startswith("/") or len(v) > 256 for v in (self.input_prefix, self.output_prefix)):
            raise ValueError("absolute bounded input/output topic prefixes required")
        self.declare_parameter("prompt", os.getenv("SAM3_PROMPT", "red mat"))
        self.declare_parameter("confidence_threshold", 0.5)
        self.declare_parameter("sync_tolerance_ms", 30.0)
        self.declare_parameter("input_queue_size", 20)
        self.declare_parameter("work_queue_size", 1)
        self.declare_parameter("stale_after_ms", 500.0)
        self.declare_parameter("max_cloud_points", 20000)
        self.declare_parameter("model_revision", "3c879f39826c281e95690f02c7821c4de09afae7")
        self.checkpoint = str(self.get_parameter("checkpoint").value)
        self.prompt = str(self.get_parameter("prompt").value)
        self.threshold = float(self.get_parameter("confidence_threshold").value)
        self.tolerance_ns = int(float(self.get_parameter("sync_tolerance_ms").value) * 1e6)
        self.input_depth = int(self.get_parameter("input_queue_size").value)
        self.work_depth = int(self.get_parameter("work_queue_size").value)
        self.max_work_wait_ms = float(os.getenv("SEMANTIC_MAX_WORK_WAIT_MS", "0"))
        work_wait_expired(0, 0, self.max_work_wait_ms)  # validate before model load
        self.stale_after_s = float(self.get_parameter("stale_after_ms").value) / 1000.0
        self.max_cloud_points = int(self.get_parameter("max_cloud_points").value)
        self.model_revision = str(self.get_parameter("model_revision").value)
        if (min(self.input_depth, self.work_depth, self.max_cloud_points) < 1 or
                self.input_depth > 20 or self.work_depth != 1):
            raise ValueError("queue sizes and max_cloud_points must be positive")
        if not 0 < self.stale_after_s <= 5 or not 0 <= self.threshold <= 1 or self.tolerance_ns < 0:
            raise ValueError("invalid deadline, confidence or sync tolerance")
        if self.model_revision != VERSIONS["model"]:
            raise ValueError("model revision differs from pinned backend")
        self.epoch = str(uuid.uuid4())
        self.guard = ResultGuard(self.epoch)
        self.last_input_stamp = {}
        self.last_result = None
        self.fault_path = os.getenv("PHASE3_DIAGNOSTIC_FAULT_FILE")
        self.require_trace = os.getenv("SEMANTIC_REQUIRE_CAPTURE_TRACE") == "1"
        self.clock_uncertainty_ms = float(os.getenv("SEMANTIC_CLOCK_UNCERTAINTY_MS", "2"))
        self.capture_traces, self.compression_traces = OrderedDict(), OrderedDict()
        self.input_receipts = {name: OrderedDict() for name in ("rgb", "depth", "info")}
        self.source_epoch = None
        self.latest_source_wall_ns = -1
        self.capture_after_wall_ns = 0
        self.sim_clock_ns = None
        self.sim_clock_received = None
        self.trace_errors = 0

        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=self.input_depth,
            reliability=ReliabilityPolicy.RELIABLE,
        )
        self.rgb_queue = deque(maxlen=self.input_depth)
        self.depth_queue = deque(maxlen=self.input_depth)
        self.info_queue = deque(maxlen=self.input_depth)
        self.work_queue: deque[FrameBundle] = deque(maxlen=self.work_depth)
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.discarded = {"rgb": 0, "depth": 0, "info": 0}
        self.input_drops = 0
        self.work_drops = 0
        self.work_wait_drops = 0
        self.paired = 0
        self.emitted = 0
        self.valid_result_wall: float | None = None
        self.valid_result_deadline: float | None = None
        self.last_error: str | None = None
        self.ready = False
        self.model_loaded = False
        self.backend = None
        self.status_file = os.getenv("SEMANTIC_STATUS_FILE")

        self.mask_pub = self.create_publisher(Image, self.output_prefix + "/mask", 10)
        self.cloud_pub = self.create_publisher(
            PointCloud2, self.output_prefix + "/points", 10
        )
        self.status_pub = self.create_publisher(
            String, self.output_prefix + "/status", 10
        )
        self.ready_pub = self.create_publisher(
            Bool, self.output_prefix + "/ready", 1
        )
        self.timing_pub = self.create_publisher(String, self.output_prefix + "/timing", 20)
        self.label_pub = self.create_publisher(String, self.output_prefix + "/label_info",
            QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                       durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.label_pub.publish(String(data=json.dumps({
            "policy": POLICY, "generation": 1,
            "labels": {"0": "unobserved", "1": "traversable", "2": "avoid_target"},
            "active_labels": [0, 2], "prompt": self.prompt,
        }, sort_keys=True)))
        self.create_subscription(
            CompressedImage, self.input_prefix + "/color/image_compressed",
            self.on_rgb, qos,
        )
        self.create_subscription(
            CompressedImage, self.input_prefix + "/depth/image_compressed",
            self.on_depth, qos,
        )
        self.create_subscription(
            CameraInfo, self.input_prefix + "/color/camera_info", self.on_info, qos
        )
        self.create_subscription(String, self.input_prefix + "/capture_trace", self.on_capture_trace, 20)
        self.create_subscription(String, self.input_prefix + "/compression_trace", self.on_compression_trace, 20)
        self.create_subscription(ClockMessage, "/clock", self.on_clock,
                                 QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT))
        self.create_timer(0.05, self.publish_status, clock=Clock(clock_type=ClockType.STEADY_TIME))
        self.add_on_set_parameters_callback(lambda params: SetParametersResult(
            successful=not any(p.name != "use_sim_time" for p in params),
            reason="adapter configuration is pinned; explicit restart required"))
        self.worker = threading.Thread(target=self.inference_loop, daemon=True)
        self.worker.start()

    @staticmethod
    def decode_rgb(message: CompressedImage) -> PILImage.Image:
        with PILImage.open(BytesIO(bytes(message.data))) as image:
            dimensions(image.width, image.height)
            return image.convert("RGB")

    @staticmethod
    def decode_depth(message: CompressedImage) -> np.ndarray:
        with PILImage.open(BytesIO(bytes(message.data))) as image:
            dimensions(image.width, image.height)
            depth = np.asarray(image)
        if depth.ndim != 2 or depth.dtype not in (np.uint16, np.int32):
            raise ValueError(f"expected single-channel uint16 PNG depth, got {depth.dtype}/{depth.shape}")
        if np.any(depth < 0) or np.any(depth > 65535):
            raise ValueError("depth outside uint16 range")
        return depth.astype(np.uint16, copy=False)

    def on_rgb(self, message: CompressedImage):
        self.enqueue("rgb", message)

    def on_depth(self, message: CompressedImage):
        self.enqueue("depth", message)

    def on_info(self, message: CameraInfo):
        self.enqueue("info", message)

    @staticmethod
    def cache(target, key, value):
        target[key] = value
        if len(target) > 128:
            target.popitem(last=False)

    def on_clock(self, message):
        with self.lock:
            current = message.clock.sec * 10**9 + message.clock.nanosec
            if self.sim_clock_ns is not None and current < self.sim_clock_ns:
                # Clock may reset BEFORE a new camera trace/header arrives.
                # Invalidate in-flight inference at this earliest observable event.
                self.epoch = str(uuid.uuid4())
                self.guard.reset(self.epoch, 1)
                for queue in (self.rgb_queue, self.depth_queue, self.info_queue, self.work_queue):
                    queue.clear()
                self.last_input_stamp.clear()
                self.capture_traces.clear()
                self.compression_traces.clear()
                self.ready = False
                self.last_error = "simulation_clock_rollback"
                # Also reject newly delivered pre-reset captures, even if their
                # simulation stamp happens to overlap the restarted timeline.
                self.capture_after_wall_ns = time.time_ns() + int(self.clock_uncertainty_ms * 1e6)
            self.sim_clock_ns = current
            self.sim_clock_received = time.monotonic()

    def on_capture_trace(self, message):
        try:
            if len(message.data) > 4096:
                raise ValueError("capture trace exceeds size bound")
            trace = validate_capture_trace(json.loads(message.data))
            with self.lock:
                if self.source_epoch != trace["source_epoch"]:
                    if trace["capture_wall_ns"] <= self.latest_source_wall_ns:
                        raise ValueError("delayed old source epoch")
                    if self.source_epoch is not None:
                        self.epoch = str(uuid.uuid4())
                        self.guard.reset(self.epoch, 1)
                        for queue in (self.rgb_queue, self.depth_queue, self.info_queue, self.work_queue):
                            queue.clear()
                        self.capture_traces.clear()
                        self.compression_traces.clear()
                        self.last_input_stamp.clear()
                        self.ready = False
                        self.last_error = "source_epoch_changed"
                    self.source_epoch = trace["source_epoch"]
                self.latest_source_wall_ns = max(self.latest_source_wall_ns, trace["capture_wall_ns"])
                self.cache(self.capture_traces, trace["stamp_ns"], trace)
        except Exception as error:
            self.trace_errors += 1
            self.last_error = f"capture_trace: {error}"
            self.ready = False

    def on_compression_trace(self, message):
        try:
            if len(message.data) > 4096:
                raise ValueError("compression trace exceeds size bound")
            trace = json.loads(message.data)
            if trace["schema"] != "semantic-compression/v1":
                raise ValueError("unsupported compression trace")
            with self.lock:
                self.cache(self.compression_traces, trace["stamp_ns"], trace)
        except Exception as error:
            self.trace_errors += 1
            self.last_error = f"compression_trace: {error}"
            self.ready = False

    def capture_context(self, bundle):
        if not self.require_trace:
            return None, None, bundle.received_monotonic + self.stale_after_s
        key = stamp_ns(bundle.rgb)
        until = bundle.received_monotonic + self.stale_after_s
        while not self.stop_event.is_set() and time.monotonic() < until:
            with self.lock:
                trace = self.capture_traces.get(key)
                compression = self.compression_traces.get(key)
                if trace and compression and self.sim_clock_received is not None:
                    if trace["capture_wall_ns"] < self.capture_after_wall_ns:
                        raise TimeoutError("capture predates observed simulation reset")
                    if trace["source_epoch"] != self.source_epoch or bundle.epoch != self.epoch:
                        raise ValueError("capture context invalidated by source reset")
                    if time.monotonic() - self.sim_clock_received > self.stale_after_s:
                        raise TimeoutError("simulation clock unavailable/stale")
                    if abs(self.sim_clock_ns - key) > self.stale_after_s * 1e9:
                        raise TimeoutError("capture differs from current simulation clock")
                    deadline = capture_deadline(trace, time.time_ns(), time.monotonic(),
                                                self.stale_after_s, self.clock_uncertainty_ms)
                    return trace, compression, deadline
            self.stop_event.wait(.005)
        raise TimeoutError("capture trace/calibration timing missing")

    def enqueue(self, name: str, message):
        if (len(message.header.frame_id) > 256 or
                (name in ("rgb", "depth") and len(message.data) > 8 * 1024 * 1024)):
            with self.lock:
                self.input_drops += 1
                self.ready = False
                self.last_error = "input_exceeds_bound"
            return
        with self.lock:
            capture_stamp = stamp_ns(message)
            self.cache(self.input_receipts[name], capture_stamp, time.time_ns())
            previous = self.last_input_stamp.get(name)
            if previous is not None and capture_stamp < previous:
                # A rollback invalidates retained work. Ordinary delayed packets may
                # cause a conservative reset; they can never resurrect old results.
                self.epoch = str(uuid.uuid4())
                self.guard.reset(self.epoch, 1)
                for queue in (self.rgb_queue, self.depth_queue, self.info_queue, self.work_queue):
                    queue.clear()
                self.last_input_stamp.clear()
                self.ready = False
                self.last_error = "capture_clock_rollback"
            if previous == capture_stamp:
                self.input_drops += 1
                return
            self.last_input_stamp[name] = capture_stamp
            target = {"rgb": self.rgb_queue, "depth": self.depth_queue,
                      "info": self.info_queue}[name]
            if len(target) == target.maxlen:
                self.input_drops += 1
            target.append(message)
            while True:
                triplet, dropped = pop_synchronized_triplet(
                    self.rgb_queue, self.depth_queue, self.info_queue,
                    self.tolerance_ns,
                )
                for key, value in dropped.items():
                    self.discarded[key] += value
                if triplet is None:
                    break
                self.paired += 1
                bundle = FrameBundle(*triplet, time.monotonic(), self.paired, self.epoch)
                if len(self.work_queue) == self.work_queue.maxlen:
                    self.work_queue.popleft()
                    self.work_drops += 1
                self.work_queue.append(bundle)

    def inference_loop(self):
        try:
            self.backend = create_backend(self.backend_kind, checkpoint=self.checkpoint,
                prompt=self.prompt, threshold=self.threshold,
                endpoint=str(self.get_parameter("endpoint").value),
                ca=str(self.get_parameter("tls_ca").value),
                cert=str(self.get_parameter("tls_cert").value),
                key=str(self.get_parameter("tls_key").value),
                identity=str(self.get_parameter("deployment_identity").value))
            while self.backend_kind == "http" and not self.stop_event.is_set():
                try:
                    self.backend.initialize()
                    break
                except IdentityMismatch:
                    raise
                except Exception as error:
                    self.last_error = f"backend_initialization: {type(error).__name__}"
                    self.stop_event.wait(1)
            if self.stop_event.is_set():
                return
            self.model_loaded = True
            self.last_error = None
            self.get_logger().info("Backend initialized; awaiting fresh RGB-D result")
        except Exception as error:
            self.last_error = f"model_initialization: {type(error).__name__}: {error}"
            self.get_logger().error(self.last_error)
            return

        while rclpy.ok() and not self.stop_event.is_set():
            with self.lock:
                bundle = self.work_queue.popleft() if self.work_queue else None
            if bundle is None:
                self.stop_event.wait(0.01)
                continue
            if work_wait_expired(bundle.received_monotonic, time.monotonic(), self.max_work_wait_ms):
                # Deliberate admission skip, not an inference success or heartbeat.
                # Existing capture-based deadline/watchdog remains authoritative.
                self.work_wait_drops += 1
                continue
            started = time.monotonic()
            request = None
            try:
                trace, compression, deadline = self.capture_context(bundle)
                decode_started = time.monotonic()
                rgb = self.decode_rgb(bundle.rgb)
                depth = self.decode_depth(bundle.depth)
                if rgb.size != (depth.shape[1], depth.shape[0]):
                    raise ValueError("RGB/depth dimensions differ")
                if bundle.info.width != rgb.width or bundle.info.height != rgb.height:
                    raise ValueError("CameraInfo dimensions differ from image")
                if any(msg.header.frame_id != bundle.rgb.header.frame_id for msg in (bundle.depth, bundle.info)):
                    raise ValueError("RGB/depth/calibration optical frames differ")
                request = make_request(rgb, sequence=bundle.sequence, epoch=bundle.epoch,
                    generation=1, stamp=stamp_ns(bundle.rgb), frame=bundle.rgb.header.frame_id,
                    prompt=self.prompt, threshold=self.threshold,
                    budget_ms=(deadline - time.monotonic()) * 1000,
                    robot=self.robot_id, stream=self.stream_id)
                submitted_bundle = bundle
                with self.lock:
                    self.guard.register(request, deadline, deadline, bundle)
                # Explicitly opt-in diagnostic-only hook; never enabled by default.
                if self.fault_path and os.path.isfile(self.fault_path):
                    with open(self.fault_path) as handle:
                        fault = json.load(handle)
                    if fault.get("mode") == "exception":
                        raise RuntimeError("diagnostic injected inference exception")
                    if fault.get("mode") == "delay":
                        self.stop_event.wait(min(5.0, max(0.0, float(fault.get("seconds", 1)))))
                backend_started = time.monotonic()
                response = self.backend.predict(request)
                backend_finished = time.monotonic()
                with self.lock:
                    mask, scores, bundle = self.guard.accept(response)
                    if (bundle is not submitted_bundle or bundle.depth is None or not len(bundle.depth.data)):
                        raise ValueError("retained depth bundle lost or replaced")
                mask_msg = Image()
                mask_msg.header = bundle.rgb.header
                mask_msg.height, mask_msg.width = mask.shape
                mask_msg.encoding = "mono8"
                mask_msg.is_bigendian = 0
                mask_msg.step = mask.shape[1]
                mask_msg.data = mask.tobytes()
                cloud_msg = self.make_mask_cloud(
                    mask, depth, bundle.info, bundle.rgb.header
                )
                with self.lock:
                    if self.stop_event.is_set() or bundle.epoch != self.epoch or time.monotonic() >= deadline:
                        raise TimeoutError("result invalidated before publication")
                    if trace:
                        if self.sim_clock_received is None or time.monotonic()-self.sim_clock_received > self.stale_after_s:
                            raise TimeoutError("simulation clock expired before publication")
                        simulation_age = simulation_capture_age_ms(self.sim_clock_ns, stamp_ns(bundle.rgb), self.stale_after_s*1000)
                    self.mask_pub.publish(mask_msg)
                    self.cloud_pub.publish(cloud_msg)
                    finished = time.monotonic()
                    processing_age_ms = (finished - bundle.received_monotonic) * 1000.0
                    self.emitted += 1
                    self.valid_result_wall = finished
                    self.valid_result_deadline = deadline
                    self.last_error = None
                    self.ready = True
                    self.last_result = {"identity": request["identity"], "capture": request["capture"],
                        "result_wall_ns": time.time_ns(), "receiver_processing_age_ms": processing_age_ms}
                    if trace:
                        self.last_result.update(capture_wall_ns=trace["capture_wall_ns"],
                            source_epoch=trace["source_epoch"], source_sequence=trace["sequence"],
                            capture_age_upper_ms=capture_age_upper_ms(trace, self.last_result["result_wall_ns"], self.clock_uncertainty_ms),
                            simulation_age_ms=simulation_age)
                        timing = {**self.last_result, "source": trace, "compression": compression,
                            "mask_sha256": hashlib.sha256(bytes(mask_msg.data)).hexdigest(),
                            "cloud_sha256": hashlib.sha256(bytes(cloud_msg.data)).hexdigest(),
                            "clock_uncertainty_ms": self.clock_uncertainty_ms,
                            "receiver_rgb_wall_ns": self.input_receipts["rgb"].get(stamp_ns(bundle.rgb)),
                            "receiver_depth_wall_ns": self.input_receipts["depth"].get(stamp_ns(bundle.depth)),
                            "receiver_info_wall_ns": self.input_receipts["info"].get(stamp_ns(bundle.info)),
                            "backend_ms": (backend_finished - backend_started) * 1000,
                            "work_wait_ms": (started - bundle.received_monotonic) * 1000,
                            "decode_request_ms": (backend_started - decode_started) * 1000,
                            "normalization_cloud_publish_ms": (finished - backend_finished) * 1000}
                        self.timing_pub.publish(String(data=json.dumps(timing, sort_keys=True)))
                self.get_logger().info(json.dumps({
                    "event": "valid_result", "capture_stamp_ns": stamp_ns(bundle.rgb),
                    "receiver_processing_age_ms": round(processing_age_ms, 2),
                    "inference_ms": round((finished - started) * 1000.0, 2),
                    "mask_pixels": int(np.count_nonzero(mask)),
                    "scores": scores.tolist(), "paired": self.paired,
                    "emitted": self.emitted, "work_drops": self.work_drops,
                }, sort_keys=True))
            except Exception as error:
                with self.lock:
                    if request is not None:
                        self.guard.cancel(request["identity"]["request_id"])
                    self.ready = False
                    self.last_error = f"inference: {type(error).__name__}: {error}"
                self.get_logger().error(self.last_error)

    def make_mask_cloud(self, mask: np.ndarray, depth: np.ndarray,
                        info: CameraInfo, header) -> PointCloud2:
        # Organized pixel-aligned cloud: never compact/stride masked points.
        rows, cols = np.indices(depth.shape)
        z = depth.astype(np.float32) * 0.001
        z[(depth == 0) | (z < 0.15) | (z > 5.0)] = np.nan
        fx, fy, cx, cy = (float(info.k[0]), float(info.k[4]),
                          float(info.k[2]), float(info.k[5]))
        if not np.isfinite([fx, fy, cx, cy]).all() or fx <= 0.0 or fy <= 0.0:
            raise ValueError("CameraInfo intrinsics are invalid")
        x = (cols.astype(np.float32) - cx) * z / fx
        y = (rows.astype(np.float32) - cy) * z / fy
        points = np.stack((x, y, z), axis=-1).astype("<f4", copy=False)
        cloud = PointCloud2()
        cloud.header = header
        cloud.height, cloud.width = depth.shape
        cloud.fields = [
            PointField(name="x", offset=0, datatype=PointField.FLOAT32, count=1),
            PointField(name="y", offset=4, datatype=PointField.FLOAT32, count=1),
            PointField(name="z", offset=8, datatype=PointField.FLOAT32, count=1),
        ]
        cloud.is_bigendian = False
        cloud.point_step = 12
        cloud.row_step = cloud.point_step * cloud.width
        cloud.is_dense = False
        cloud.data = points.tobytes()
        return cloud

    def publish_status(self):
        with self.lock:
            self._publish_status_locked()

    def _publish_status_locked(self):
        # Publishing a late-but-valid result must NOT restart its freshness TTL.
        # This monotonic deadline was derived from source capture, not receipt.
        if self.valid_result_deadline is None or time.monotonic() >= self.valid_result_deadline:
            self.ready = False
        self.ready_pub.publish(Bool(data=self.ready))
        queued = len(self.work_queue)
        waiting = {"rgb": len(self.rgb_queue), "depth": len(self.depth_queue),
                   "camera_info": len(self.info_queue)}
        status = {
            "status_wall_ns": time.time_ns(),
            "ready": self.ready,
            "state": "ready" if self.ready else (
                "loading" if not self.model_loaded and self.last_error is None
                else "not_ready"
            ),
            "reason": self.last_error or (
                "model_loading" if not self.model_loaded else
                "awaiting_first_valid_result" if self.valid_result_wall is None else
                "stale_input_or_result" if not self.ready else None
            ),
            "backend": self.backend_kind,
            "backend_in_flight": getattr(self.backend, "in_flight", None),
            "deployment_identity": getattr(self.backend, "loaded_identity", None),
            "robot_id": self.robot_id, "stream_id": self.stream_id,
            "output_prefix": self.output_prefix,
            "model": "facebook/sam3-original",
            "model_revision": self.model_revision,
            "versions": VERSIONS,
            "policy": POLICY,
            "policy_generation": 1,
            "stream_epoch": self.epoch,
            "source_epoch": self.source_epoch,
            "capture_trace_required": self.require_trace,
            "clock_uncertainty_ms": self.clock_uncertainty_ms,
            "trace_errors": self.trace_errors,
            "last_result": self.last_result,
            "prompt": self.prompt,
            "confidence_threshold": self.threshold,
            "paired_triplets": self.paired,
            "emitted_results": self.emitted,
            "timestamp_discards": self.discarded,
            "input_queue_drops": self.input_drops,
            "work_queue_drops": self.work_drops,
            "work_wait_drops": self.work_wait_drops,
            "max_work_wait_ms": self.max_work_wait_ms,
            "work_queue_depth": queued,
            "input_queue_depths": waiting,
            "last_valid_result_age_ms": (
                None if self.valid_result_wall is None else
                round((time.monotonic() - self.valid_result_wall) * 1000.0, 2)
            ),
        }
        self.status_pub.publish(String(data=json.dumps(status, sort_keys=True)))
        if self.status_file:
            temporary = Path(self.status_file + ".tmp")
            temporary.write_text(json.dumps(status, sort_keys=True))
            temporary.replace(self.status_file)

    def destroy_node(self):
        self.stop_event.set()
        if self.backend is not None and hasattr(self.backend, "close"):
            self.backend.close()
        if self.worker.is_alive():
            self.worker.join(timeout=2.0)
        super().destroy_node()


def main():
    rclpy.init()
    node = Sam3Runtime()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    except RCLError:
        # SIGTERM can invalidate the context while the executor builds a wait
        # set, before it raises ExternalShutdownException. Never hide live errors.
        if rclpy.ok():
            raise
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
