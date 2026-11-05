"""Read-only camera/body observations during the viewer-authorized demo."""
import json
import math
from pathlib import Path
import time

import rclpy
from gz.msgs10.pose_pb2 import Pose
from gz.transport13 import Node as GazeboNode
from nav_msgs.msg import Odometry


def main():
    rclpy.init()
    node = rclpy.create_node("phase6_camera_follow_observer")
    latest = {}
    samples = []
    start = time.monotonic()
    stop = Path("/tmp/auto-follow-run20-observer-stop")

    def camera_cb(msg):
        latest["camera"] = (time.monotonic(), msg)

    def body_cb(msg):
        latest["body"] = (time.monotonic(), msg)

    gz = GazeboNode()
    if not gz.subscribe(Pose, "/gui/camera/pose", camera_cb):
        raise RuntimeError("camera pose subscription failed")
    node.create_subscription(Odometry, "/robot_1/demo/ground_truth", body_cb, 10)

    def sample():
        now = time.monotonic()
        if len(latest) != 2:
            return
        ct, camera = latest["camera"]
        bt, body = latest["body"]
        cp, bp = camera.position, body.pose.pose.position
        samples.append({
            "elapsed_wall_s": now - start,
            "camera_age_s": now - ct, "body_age_s": now - bt,
            "camera_xyz": [cp.x, cp.y, cp.z],
            "body_xyz": [bp.x, bp.y, bp.z],
            "body_speed_mps": math.hypot(body.twist.twist.linear.x,
                                          body.twist.twist.linear.y),
            "horizontal_center_error_m": math.hypot(cp.x - bp.x, cp.y - bp.y),
        })

    node.create_timer(.1, sample)
    try:
        while time.monotonic() - start < 230 and not stop.exists():
            rclpy.spin_once(node, timeout_sec=.1)
    finally:
        print(json.dumps({"read_only": True, "samples": samples}), flush=True)
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
