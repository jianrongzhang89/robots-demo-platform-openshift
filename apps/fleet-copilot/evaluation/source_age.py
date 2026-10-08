from __future__ import annotations

import json
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from rosgraph_msgs.msg import Clock
from rmf_fleet_msgs.msg import FleetState


class SourceAge(Node):
    def __init__(self):
        super().__init__("fleet_copilot_source_age")
        self.clock_ns = None
        self.ages = []
        clock_qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)
        self.create_subscription(Clock, "/clock", self.clock, clock_qos)
        self.create_subscription(FleetState, "/fleet_states", self.fleet, 10)

    def clock(self, message):
        self.clock_ns = message.clock.sec * 1_000_000_000 + message.clock.nanosec

    def fleet(self, message):
        if self.clock_ns is None:
            return
        for robot in message.robots:
            stamp = robot.location.t
            source_ns = stamp.sec * 1_000_000_000 + stamp.nanosec
            age_ms = max(0.0, (self.clock_ns - source_ns) / 1_000_000.0)
            self.ages.append(age_ms)


rclpy.init()
node = SourceAge()
deadline = time.monotonic() + 130
while len(node.ages) < 100 and time.monotonic() < deadline:
    rclpy.spin_once(node, timeout_sec=1.0)
node.destroy_node()
rclpy.shutdown()

if not node.ages:
    raise SystemExit("no fleet-state observations")
values = sorted(node.ages)
percentile = lambda fraction: values[min(len(values) - 1, int(len(values) * fraction + 0.999999) - 1)]
print(json.dumps({
    "count": len(values),
    "p50_ms": percentile(0.5),
    "p95_ms": percentile(0.95),
    "max_ms": max(values),
    "budget_ms": 5000,
    "pass": percentile(0.95) <= 5000,
}, indent=2))
