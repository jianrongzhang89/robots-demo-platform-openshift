#!/usr/bin/env python3
"""Capture a compact sample of Nav2's current global plan for Phase 8 evidence."""

import json
import time

import rclpy
from nav_msgs.msg import Path
from rclpy.node import Node


class PlanCapture(Node):
    def __init__(self):
        super().__init__("phase8_nav2_path_capture")
        self.path = None
        self.create_subscription(Path, "/plan", self._path, 1)

    def _path(self, message):
        self.path = [[float(p.pose.position.x), float(p.pose.position.y)]
                     for p in message.poses]


def main():
    rclpy.init()
    node = PlanCapture()
    try:
        deadline = time.monotonic() + 5.0
        while node.path is None and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.2)
        if node.path is None:
            raise TimeoutError("No global plan received from Nav2")
        stride = max(1, len(node.path) // 12)
        print(json.dumps({"pose_count": len(node.path),
                          "first": node.path[0], "last": node.path[-1],
                          "samples": node.path[::stride]}, sort_keys=True))
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
