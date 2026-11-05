#!/usr/bin/env python3
"""Phase 5 sensor-only bridge: preserve stamps, one odom TF authority, no map TF.

Publishes neither commands nor synthetic fresh poses. Clock rollback latches
until process restart (the coordinator must stop and clear consumers first).
"""
import copy
import json
import math
import os
import time

import rclpy
from rclpy.clock import Clock, ClockType
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from geometry_msgs.msg import TransformStamped
from nav_msgs.msg import Odometry
from rosgraph_msgs.msg import Clock as ClockMessage
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String
from tf2_ros import TransformBroadcaster


def stamp_ns(stamp):
    return stamp.sec * 1_000_000_000 + stamp.nanosec


class FrameBridge(Node):
    def __init__(self):
        super().__init__("phase5_frame_bridge")
        if not self.has_parameter("use_sim_time"):
            self.declare_parameter("use_sim_time", True)
        else:
            self.set_parameters([rclpy.parameter.Parameter("use_sim_time", rclpy.Parameter.Type.BOOL, True)])
        self.clock_ns = None
        self.clock_progress = None
        self.last = {"odom": -1, "scan": -1}
        self.receipts = {"odom": None, "scan": None}
        self.deadlines = {"odom": None, "scan": None}
        self.tf_producer_trace = os.getenv("PHASE5_TF_PRODUCER_TRACE") == "1"
        self.tf_trace_count = 0
        self.previous_odom_receive_ns = None
        self.previous_odom_stamp_ns = None
        self.fault = None
        self.tf = TransformBroadcaster(self)
        self.scan_pub = self.create_publisher(LaserScan, "/robot_1/scan_fixed", qos_profile_sensor_data)
        self.status = self.create_publisher(String, "/robot_1/phase5/frames", 10)
        self.create_subscription(ClockMessage, "/clock", self.on_clock, qos_profile_sensor_data)
        self.create_subscription(Odometry, "/robot_1/odom", self.on_odom, qos_profile_sensor_data)
        self.create_subscription(LaserScan, "/robot_1/scan", self.on_scan, qos_profile_sensor_data)
        self.create_timer(.05, self.report, clock=Clock(clock_type=ClockType.STEADY_TIME))

    def on_clock(self, message):
        value = stamp_ns(message.clock)
        if self.clock_ns is not None and value < self.clock_ns:
            self.fault = "simulation_clock_rollback_restart_required"
        if self.clock_ns is None or value > self.clock_ns:
            self.clock_progress = time.monotonic()
        self.clock_ns = value

    def eligible(self, kind, header):
        value = stamp_ns(header.stamp)
        if (self.fault or self.clock_ns is None or self.clock_progress is None
                or time.monotonic()-self.clock_progress >= .5
                or not 0 <= self.clock_ns-value < 500_000_000 or value <= self.last[kind]):
            return False
        self.last[kind] = value
        self.receipts[kind] = time.monotonic()
        self.deadlines[kind] = self.receipts[kind] + .5 - (self.clock_ns-value)/1e9
        return True

    def on_odom(self, message):
        receive_monotonic_ns = time.monotonic_ns()
        receive_wall_ns = time.time_ns()
        if message.header.frame_id != "odom" or message.child_frame_id != "base_footprint":
            self.fault = "unexpected_odometry_frames"
            return
        p, q = message.pose.pose.position, message.pose.pose.orientation
        if (not all(math.isfinite(x) for x in (p.x,p.y,p.z,q.x,q.y,q.z,q.w))
                or abs(q.x*q.x+q.y*q.y+q.z*q.z+q.w*q.w-1) > .01):
            self.fault = "invalid_odometry_pose"
            return
        if not self.eligible("odom", message.header):
            return
        transform = TransformStamped()
        transform.header = copy.deepcopy(message.header)
        transform.child_frame_id = message.child_frame_id
        transform.transform.translation.x = p.x
        transform.transform.translation.y = p.y
        transform.transform.translation.z = p.z
        transform.transform.rotation = copy.deepcopy(q)
        send_start_ns = time.monotonic_ns()
        self.tf.sendTransform(transform)
        send_end_ns = time.monotonic_ns()
        if self.tf_producer_trace and self.tf_trace_count < 20000:
            message_stamp_ns = stamp_ns(message.header.stamp)
            previous_receive_gap_ns = (None if self.previous_odom_receive_ns is None else
                                       receive_monotonic_ns-self.previous_odom_receive_ns)
            previous_stamp_delta_ns = (None if self.previous_odom_stamp_ns is None else
                                       message_stamp_ns-self.previous_odom_stamp_ns)
            row = {
                "kind": "odom_tf_publish",
                "stamp_ns": message_stamp_ns,
                "clock_ns_at_callback": self.clock_ns,
                "clock_minus_odom_ns": None if self.clock_ns is None else self.clock_ns-message_stamp_ns,
                "receive_monotonic_ns": receive_monotonic_ns,
                "receive_wall_ns": receive_wall_ns,
                "previous_receive_gap_ns": previous_receive_gap_ns,
                "previous_stamp_delta_ns": previous_stamp_delta_ns,
                "tf_send_start_ns": send_start_ns,
                "tf_send_end_ns": send_end_ns,
                "tf_send_duration_ns": send_end_ns-send_start_ns,
                "tf_send_wall_ns": time.time_ns(),
            }
            print("FRAME_DIAG "+json.dumps(row,separators=(",",":")),flush=True)
            self.tf_trace_count += 1
        self.previous_odom_receive_ns = receive_monotonic_ns
        self.previous_odom_stamp_ns = stamp_ns(message.header.stamp)

    def on_scan(self, message):
        receive_monotonic_ns = time.monotonic_ns()
        receive_wall_ns = time.time_ns()
        if message.header.frame_id not in ("lidar_frame", "robot_1/base_scan/lidar"):
            self.fault = "unexpected_lidar_frame"
            if self.tf_producer_trace:
                print("SCAN_DIAG "+json.dumps({"stamp_ns":stamp_ns(message.header.stamp),
                    "receive_monotonic_ns":receive_monotonic_ns,"receive_wall_ns":receive_wall_ns,
                    "accepted":False,"reason":self.fault},separators=(",",":")),flush=True)
            return
        if not self.eligible("scan", message.header):
            if self.tf_producer_trace:
                print("SCAN_DIAG "+json.dumps({"stamp_ns":stamp_ns(message.header.stamp),
                    "receive_monotonic_ns":receive_monotonic_ns,"receive_wall_ns":receive_wall_ns,
                    "accepted":False,"reason":self.fault or "scan_not_fresh_or_monotonic"},
                    separators=(",",":")),flush=True)
            return
        result = copy.deepcopy(message)
        result.header.frame_id = "lidar_frame"
        publish_start_ns = time.monotonic_ns()
        self.scan_pub.publish(result)
        publish_end_ns = time.monotonic_ns()
        if self.tf_producer_trace:
            print("SCAN_DIAG "+json.dumps({"stamp_ns":stamp_ns(message.header.stamp),
                "receive_monotonic_ns":receive_monotonic_ns,"receive_wall_ns":receive_wall_ns,
                "publish_start_ns":publish_start_ns,"publish_end_ns":publish_end_ns,
                "publish_duration_ns":publish_end_ns-publish_start_ns,"accepted":True},
                separators=(",",":")),flush=True)

    def report(self):
        now = time.monotonic()
        ages = {key: None if value is None else (now-value)*1000 for key,value in self.receipts.items()}
        reason = self.fault
        if reason is None:
            if self.clock_ns is None or self.clock_progress is None:
                reason = "clock_missing"
            elif now-self.clock_progress >= .5:
                reason = "clock_stale"
            else:
                for kind, deadline in self.deadlines.items():
                    if deadline is None:
                        reason = kind+"_missing"
                        break
                    if now >= deadline or not 0 <= self.clock_ns-self.last[kind] < 500_000_000:
                        reason = kind+"_stale"
                        break
        self.status.publish(String(data=json.dumps({"ready": reason is None, "reason": reason,
            "receipt_ages_ms": ages, "source_stamp_ns": self.last, "wall_ns": time.time_ns()})))


if __name__ == "__main__":
    rclpy.init()
    node = FrameBridge()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
