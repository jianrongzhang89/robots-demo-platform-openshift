"""Standalone observation-only SAM3 monitor for the private guarded fixture.

Runs as a separate process so the multi-megabyte semantic point clouds are
deserialized and projected OUTSIDE the fixture's single-threaded safety
pump, and on their OWN private ROS domain so they never load the safety
domain's clock/TF/command traffic (series 2 trial 2: clouds on the safety
domain delayed the frame bridge's TF past the controller's transform waits
and the chain correctly stopped command_expired). This worker reads TF from
the safety domain and every camera/semantic stream from the isolated
camera/semantic domain through two rclpy contexts, hash-matches each timing
record to its mask and cloud, projects the avoid_target points through
capture-time TF, and reports only small aggregated state through files. It
moves no robot, commands nothing, and changes no deadline.
"""
import argparse
import hashlib
import json
import os
import time
from collections import deque
from pathlib import Path

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.time import Time
from sensor_msgs.msg import Image, PointCloud2
from std_msgs.msg import Bool, String
from tf2_ros import Buffer, TransformListener

from sam3_observation import (decode_mask, decode_points_xyz,
                               parse_mat_ground_truth, points_in_rectangle,
                               transform_points)
from semantic_fault_probe import (observe_result_for_streak,
                                   result_streak_seconds)

SAFETY_DOMAIN = "85"
SEMANTIC_DOMAIN = "88"


def write_json(path, payload):
    temporary = Path(str(path) + ".tmp")
    temporary.write_text(json.dumps(payload))
    temporary.replace(path)


def main():
    if not os.getenv("GZ_PARTITION", "").startswith("phase5-watchdog-"):
        raise RuntimeError("private fixture partition required")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shared-dir", required=True,
                        help="emptyDir shared with the fixture container: the fixture writes the mat ground truth here, the worker writes its aggregated state")
    args = parser.parse_args()
    shared = Path(args.shared_dir)
    ground_truth_file = shared / "ground-truth.json"
    deadline = time.monotonic() + 180
    while not ground_truth_file.is_file():
        if time.monotonic() > deadline:
            raise RuntimeError("mat ground truth never appeared in the shared directory")
        time.sleep(.2)
    rectangle = json.loads(ground_truth_file.read_text())["mat"]
    # The target-absent negative case writes mat:null: the worker records
    # empty results without projection (no ground truth to register against).
    if rectangle is None:
        rectangle = {"xmin": 0.0, "xmax": 0.0, "ymin": 0.0, "ymax": 0.0,
                     "_absent": True}
    state = {"masks": deque(maxlen=10), "clouds": deque(maxlen=10), "results": [],
             "ages": [], "stamps": [], "labels": None, "ready": False,
             "isolation": None, "last_isolation": 0.0, "pending": deque(),
             "camera": {"count": 0, "stamp_ns": 0, "rollback": False,
                        "input_transport": None},
             # Armed-semantic lease evidence for the guarded supervisor: the
             # camera capture traces (render-time camera heartbeat), the
             # SAM3 timing records (semantic result freshness, measured by
             # capture age) and the SAM3 status heartbeat. Each entry is
             # {epoch, sequence, wall_ns, ros_ns} or None while absent.
             "leases": {"camera": None, "semantic": None, "inference_heartbeat": None},
             "clock_ros_ns": 0}
    worker_epoch = f"semantic-worker-{time.time_ns()}"
    heartbeat_sequence = 0

    # Safety-domain context: TF only, exactly as qualified. The domain is
    # forced here regardless of the launch environment.
    os.environ["ROS_DOMAIN_ID"] = SAFETY_DOMAIN
    safety_context = rclpy.Context()
    rclpy.init(context=safety_context)
    tf_node = Node("phase5_sam3_tf_observer", context=safety_context)
    tf = Buffer()
    listener = TransformListener(tf, tf_node)  # kept alive for the buffer

    # Isolated camera/semantic-domain context: every bulk stream lives here.
    os.environ["ROS_DOMAIN_ID"] = SEMANTIC_DOMAIN
    semantic_context = rclpy.Context()
    rclpy.init(context=semantic_context)
    node = Node("phase5_sam3_observer", context=semantic_context)

    def resolve(record, received):
        """Try to resolve one timing record against retained payloads.

        The small timing record can overtake its multi-megabyte cloud through
        the cross-node transport, so resolution is retried from the spin
        loop until the payloads arrive or the record expires.
        """
        mask_row = next((m for h, m, _ in state["masks"] if h == record.get("mask_sha256")), None)
        cloud_row = next((c for h, c, _ in state["clouds"] if h == record.get("cloud_sha256")), None)
        if mask_row is None or cloud_row is None:
            return False
        capture = Time(nanoseconds=int(mask_row.header.stamp.sec) * 1_000_000_000
                       + mask_row.header.stamp.nanosec)
        # The capture stamp routinely leads the newest AMCL map->odom edge by
        # up to one scan interval; check availability BEFORE the expensive
        # decodes and retry from the pending loop.
        if not tf.can_transform("map", "camera_color_optical_frame", capture):
            return False
        try:
            mask = decode_mask(mask_row.data, mask_row.width, mask_row.height)
            offsets = tuple(next(f.offset for f in cloud_row.fields if f.name == axis)
                            for axis in ("x", "y", "z"))
            xyz = decode_points_xyz(cloud_row.data, cloud_row.width, cloud_row.height,
                                    cloud_row.point_step, offsets)
            transform = tf.lookup_transform("map", "camera_color_optical_frame", capture).transform
            pts_map = transform_points(xyz[mask == 2],
                (transform.translation.x, transform.translation.y, transform.translation.z),
                (transform.rotation.x, transform.rotation.y, transform.rotation.z,
                 transform.rotation.w))
            count, fraction = points_in_rectangle(pts_map, rectangle)
            state["results"].append({"selected": count, "inside_fraction": fraction,
                                     "matched": True, "receipt_wall_ns": received,
                                     "capture_stamp_ns": record.get("capture", {}).get("stamp_ns")})
        except Exception as error:  # evidence row, never a crash
            state["results"].append({"selected": 0, "inside_fraction": 0.0, "moving": False,
                                     "matched": False, "reason": "projection_error:" + str(error),
                                     "receipt_wall_ns": received})
        return True

    def resolve_pending():
        remaining = deque()
        for record, received in state["pending"]:
            if resolve(record, received):
                continue
            if time.time_ns() - received > 2_000_000_000:
                state["results"].append({"selected": 0, "inside_fraction": 0.0, "moving": False,
                                         "matched": False, "reason": "unmatched_payload",
                                         "receipt_wall_ns": received})
                continue
            remaining.append((record, received))
        state["pending"] = remaining

    def on_mask(message):
        state["masks"].append((hashlib.sha256(bytes(message.data)).hexdigest(),
                               message, time.time_ns()))

    def on_cloud(message):
        state["clouds"].append((hashlib.sha256(bytes(message.data)).hexdigest(),
                                message, time.time_ns()))

    def on_timing(message):
        record = json.loads(message.data)
        now = time.time_ns()
        state["ages"].append((now - record["capture_wall_ns"]) / 1e6)
        state["stamps"].append(record.get("capture", {}).get("stamp_ns"))
        observe_result_for_streak(state, now, record.get("capture_wall_ns", now))
        # Semantic lease evidence: capture age is the freshness authority.
        source = record.get("source") or {}
        state["leases"]["semantic"] = {
            "epoch": source.get("source_epoch") or worker_epoch,
            "sequence": len(state["stamps"]),
            "wall_ns": record.get("capture_wall_ns", now),
            "ros_ns": record.get("capture", {}).get("stamp_ns", 0)}
        if not resolve(record, now):
            state["pending"].append((record, now))

    def on_labels(message):
        state["labels"] = json.loads(message.data)

    def on_ready(message):
        state["ready"] = bool(message.data)

    def on_compression_trace(message):
        row = json.loads(message.data)
        camera = state["camera"]
        camera["rollback"] = bool(camera["rollback"]
                                  or (camera["stamp_ns"] and row.get("stamp_ns", 0) < camera["stamp_ns"]))
        camera["count"] += 1
        camera["stamp_ns"] = row.get("stamp_ns") or camera["stamp_ns"]
        camera["input_transport"] = row.get("input_transport")

    def on_capture_trace(message):
        # Camera lease evidence from the render-time capture trace.
        row = json.loads(message.data)
        if row.get("schema") != "semantic-capture/v1":
            return
        state["leases"]["camera"] = {
            "epoch": row.get("source_epoch") or worker_epoch,
            "sequence": row.get("sequence", state["camera"]["count"]),
            "wall_ns": row.get("capture_wall_ns", time.time_ns()),
            "ros_ns": row.get("stamp_ns", 0)}

    def on_status(message):
        # Inference heartbeat: the process's 20 Hz status; its ros field is
        # the worker's /clock copy on this isolated domain.
        nonlocal heartbeat_sequence
        heartbeat_sequence += 1
        state["leases"]["inference_heartbeat"] = {
            "epoch": worker_epoch,
            "sequence": heartbeat_sequence,
            "wall_ns": time.time_ns(),
            "ros_ns": state["clock_ros_ns"]}

    def on_clock(message):
        state["clock_ros_ns"] = (message.clock.sec * 1_000_000_000
                                 + message.clock.nanosec)

    node.create_subscription(Image, "/robot_1/semantic/mask", on_mask, 10)
    node.create_subscription(PointCloud2, "/robot_1/semantic/points", on_cloud, 10)
    node.create_subscription(String, "/robot_1/semantic/timing", on_timing, 20)
    node.create_subscription(Bool, "/robot_1/semantic/ready", on_ready, 10)
    node.create_subscription(String, "/robot_1/semantic/label_info", on_labels,
        QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                   durability=DurabilityPolicy.TRANSIENT_LOCAL))
    node.create_subscription(String, "/robot_1/camera/compression_trace", on_compression_trace, 20)
    node.create_subscription(String, "/robot_1/camera/capture_trace", on_capture_trace, 20)
    node.create_subscription(String, "/robot_1/semantic/status", on_status, 20)
    from rosgraph_msgs.msg import Clock as ClockMessage
    node.create_subscription(ClockMessage, "/clock", on_clock, 10)

    # Explicit per-context executors: the global rclpy executor is bound to
    # the default context and cannot service either custom context.
    from rclpy.executors import SingleThreadedExecutor
    safety_executor = SingleThreadedExecutor(context=safety_context)
    safety_executor.add_node(tf_node)
    semantic_executor = SingleThreadedExecutor(context=semantic_context)
    semantic_executor.add_node(node)

    def isolation():
        semantic_topics = sorted(t for t, _ in node.get_topic_names_and_types()
                                 if "/semantic/" in t)
        subscribers = {sub.node_name for topic in semantic_topics
                       for sub in node.get_subscriptions_info_by_topic(topic)}
        return {"semantic_topics": semantic_topics,
                "subscribing_nodes": sorted(subscribers),
                "costmap_subscriptions": sorted(n for n in subscribers if "costmap" in n)}

    status_path, observation_path = shared / "status.json", shared / "observation.json"

    def status_payload():
        return {"ready": state["ready"], "labels": state["labels"],
                "results": len(state["results"]),
                "last_result_receipt_wall_ns": (state["results"][-1]["receipt_wall_ns"]
                                                if state["results"] else None),
                "camera": dict(state["camera"]),
                "leases": {key: dict(value) if value else None
                           for key, value in state["leases"].items()},
                "isolation": state["isolation"],
                "result_streak_s": result_streak_seconds(state, time.time_ns()),
                "written_wall_ns": time.time_ns()}

    def observation_payload():
        return {"ground_truth_mat": rectangle, "results": state["results"],
                "ages_ms": state["ages"], "capture_stamps_ns": state["stamps"],
                "labels": state["labels"], "camera": dict(state["camera"]),
                "leases": {key: dict(value) if value else None
                           for key, value in state["leases"].items()},
                "isolation": state["isolation"],
                "result_streak_s": result_streak_seconds(state, time.time_ns())}

    last_write = 0.0
    try:
        while rclpy.ok(context=safety_context):
            safety_executor.spin_once(timeout_sec=0.02)
            semantic_executor.spin_once(timeout_sec=0.03)
            resolve_pending()
            now = time.monotonic()
            if now - state["last_isolation"] > 2.0:
                state["isolation"] = isolation()
                state["last_isolation"] = now
            if now - last_write > 0.2 or state["results"]:
                write_json(status_path, status_payload())
                write_json(observation_path, observation_payload())
                last_write = now
    finally:
        write_json(status_path, {**status_payload(), "stopped": True})
        write_json(observation_path, observation_payload())
        node.destroy_node()
        tf_node.destroy_node()
        safety_executor.shutdown()
        semantic_executor.shutdown()
        rclpy.shutdown(context=semantic_context)
        rclpy.shutdown(context=safety_context)


if __name__ == "__main__":
    main()
