#!/usr/bin/env python3
"""Publish Phase 6 epoch-bound label metadata for the served ROS adapter."""
import json
import sys

sys.path.insert(0, "/opt/semantic-perception")
import sam3_ros_node as runtime
from rclpy.clock import Clock, ClockType
from std_msgs.msg import String


class Phase8ServedSam3Runtime(runtime.Sam3Runtime):
    def __init__(self):
        super().__init__()
        self.create_timer(1.0, self.publish_label_info,
                          clock=Clock(clock_type=ClockType.STEADY_TIME))

    def publish_label_info(self):
        self.label_pub.publish(String(data=json.dumps({
            "policy": runtime.POLICY,
            "generation": getattr(self, "policy_generation", 1),
            "stream_epoch": self.epoch,
            "labels": {"0": "unobserved", "1": "traversable", "2": "avoid_target"},
            "active_labels": [0, 2],
            "prompt": self.prompt,
        }, sort_keys=True)))


if __name__ == "__main__":
    runtime.Sam3Runtime = Phase8ServedSam3Runtime
    runtime.main()
