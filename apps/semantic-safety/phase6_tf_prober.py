"""Read-only /tf arrival prober for the Phase 6 arm diagnostics.

Why this exists (pair-1-off-gcfix, October 2026): the tf lease starved at
mat-close because the fixture's TF buffer fell ~100 ms of simulation time
behind the scan stamps, while the frame bridge relayed fresh odom->base
transforms and the fixture's own /robot_1/odom DDS receipts stayed at ~3 ms.
The delay therefore lives somewhere between the frame bridge's
sendTransform and the fixture's buffer. This prober is a disinterested
third reader of the SAME /tf topic on the SAME private domain in the SAME
pod: it records every transform's (stamp, arrival wall) pair and nothing
else. If the prober sees odom->base edges promptly while the fixture's
buffer lags, the delay is specific to the fixture process (reader/exec
scheduling under its ~94% CPU busy pump); if the prober lags identically,
the delay is writer-side or loopback-level. It subscribes nothing else,
publishes nothing, and grants no authority; rows are JSON lines on stdout,
retained with the pod logs by the series runner.
"""
import json
import os
import sys
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from tf2_msgs.msg import TFMessage

ROW_LIMIT = 40000


def main():
    if os.getenv("ROS_DOMAIN_ID") != "85":
        raise RuntimeError("private safety domain 85 required")
    if not os.getenv("GZ_PARTITION", "").startswith("phase5-watchdog-"):
        raise RuntimeError("private fixture partition required")
    rclpy.init()
    node = Node("phase6_tf_prober")
    rows = {"count": 0}

    def on_tf(message):
        wall = time.time_ns()
        for transform in message.transforms:
            if rows["count"] >= ROW_LIMIT:
                return
            rows["count"] += 1
            print(json.dumps({
                "c": transform.child_frame_id,
                "p": transform.header.frame_id,
                "s": transform.header.stamp.sec * 1_000_000_000
                     + transform.header.stamp.nanosec,
                "w": wall}), flush=True)

    # Same reliability as the fixture's proven /tf readers (the frame
    # bridge's TransformBroadcaster publishes reliably; a reliable
    # subscription matches it exactly).
    node.create_subscription(TFMessage, "/tf", on_tf,
                             QoSProfile(depth=100,
                                        reliability=ReliabilityPolicy.RELIABLE))
    print(json.dumps({"event": "tf_prober_started", "pid": os.getpid(),
                      "row_limit": ROW_LIMIT}), flush=True)
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
