#!/usr/bin/env python3
"""Missing-checkpoint readiness test in private ROS domain 81; no GPU load."""
import json
import os
import subprocess
import sys
import time

os.environ["ROS_DOMAIN_ID"] = "81"
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String


def main():
    child = subprocess.Popen([sys.executable, "/opt/semantic-perception/sam3_ros_node.py",
        "--ros-args", "-p", "checkpoint:=/nonexistent-phase3-checkpoint/sam3.pt"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    rclpy.init()
    node = Node("phase3_missing_model_audit", enable_rosout=False)
    statuses, masks = [], []
    node.create_subscription(String, "/robot_1/semantic/status",
                             lambda msg: statuses.append(json.loads(msg.data)), 20)
    node.create_subscription(Image, "/robot_1/semantic/mask", masks.append, 20)
    try:
        started = time.monotonic()
        while time.monotonic() - started < 6:
            rclpy.spin_once(node, timeout_sec=.1)
        assert statuses and not masks
        assert all(not status["ready"] for status in statuses)
        assert "FileNotFoundError" in statuses[-1]["reason"]
        assert statuses[-1]["last_result"] is None
        result = {"kind": "missing_model", "domain": 81, "status_count": len(statuses),
                  "mask_count": len(masks), "last_status": statuses[-1]}
    finally:
        child.terminate()
        try:
            logs, _ = child.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            logs, _ = child.communicate(timeout=5)
        node.destroy_node()
        rclpy.shutdown()
    result["child_logs"] = logs
    result["child_exit_code"] = child.returncode
    assert child.returncode == 0 and "Traceback" not in logs, result
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
