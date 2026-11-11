#!/usr/bin/env python3
"""Publish epoch-bound policy metadata from the pinned D2 inference runtime.

The older local SAM3 image emits one label_info message without stream_epoch.
The current costmap requires that identity, and late DDS/Zenoh consumers need
periodic metadata. Read the producer's own state; do not infer an epoch from
received results or change masks, point clouds, prompts, or inference behavior.
"""
import json
import sys

sys.path.insert(0, "/opt/semantic-perception")
import sam3_ros_node as runtime
from rclpy.clock import Clock, ClockType
from std_msgs.msg import String


class DemoSam3Runtime(runtime.Sam3Runtime):
    def __init__(self):
        super().__init__()
        self.publish_demo_policy()
        self.create_timer(1.0, self.publish_demo_policy,
                          clock=Clock(clock_type=ClockType.STEADY_TIME))

    def publish_demo_policy(self):
        with self.lock:
            metadata = {
                "policy": runtime.POLICY,
                "generation": getattr(self, "policy_generation", 1),
                "stream_epoch": self.epoch,
                "labels": {"0": "unobserved", "1": "traversable", "2": "avoid_target"},
                "active_labels": [0, 2], "prompt": self.prompt,
            }
            self.label_pub.publish(String(data=json.dumps(metadata, sort_keys=True)))


if __name__ == "__main__":
    runtime.Sam3Runtime = DemoSam3Runtime
    runtime.main()
