"""Guarded D2 preparation turn; fail on body/wheel disagreement."""
import json
import math
import time

import rclpy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry


def yaw(msg):
    q = msg.pose.pose.orientation
    return math.atan2(2 * (q.w * q.z + q.x * q.y),
                      1 - 2 * (q.y * q.y + q.z * q.z))


def main():
    rclpy.init()
    node = rclpy.create_node("phase6_truth_guarded_prepare")
    observations = {}

    def receive(name, msg):
        observations[name] = (time.monotonic(), msg)

    node.create_subscription(Odometry, "/robot_1/odom", lambda m: receive("wheel", m), 10)
    node.create_subscription(Odometry, "/robot_1/demo/ground_truth", lambda m: receive("body", m), 10)
    pub = node.create_publisher(Twist, "/robot_1/cmd_vel", 10)
    samples = []
    reason = "timeout"
    # Pod Ready precedes Gazebo sensor/physics warmup. Require a sustained
    # fresh-input interval before the first preparation command, rather than
    # consuming a single startup sample and immediately hitting the watchdog.
    deadline = time.monotonic() + 60
    settled_since = None
    while time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=.05)
        now = time.monotonic()
        if len(observations) == 2 and all(now - t < .25 for t, m in observations.values()):
            if settled_since is None:
                settled_since = now
            if now - settled_since >= 2:
                break
        else:
            settled_since = None
    try:
        if settled_since is None or time.monotonic() - settled_since < 2:
            raise RuntimeError("wheel/body inputs did not become continuously fresh")
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=.05)
            if any(time.monotonic() - t > .5 for t, m in observations.values()):
                reason = "stale_pose"
                break
            wheel, body = observations["wheel"][1], observations["body"][1]
            wy, by = yaw(wheel), yaw(body)
            position_error = math.hypot(15.402 + wheel.pose.pose.position.x - body.pose.pose.position.x,
                                        -31.594 + wheel.pose.pose.position.y - body.pose.pose.position.y)
            angle_error = abs(math.atan2(math.sin(wy-by), math.cos(wy-by)))
            samples.append({"wall": time.time(), "wheel_yaw": wy, "body_yaw": by,
                            "position_error_m": position_error,
                            "yaw_error_rad": angle_error})
            if position_error > .08 or angle_error > .08:
                reason = "pose_disagreement"
                break
            if by >= .52:
                reason = "target_reached"
                break
            msg = Twist()
            msg.angular.z = min(.10, max(.025, (.52-by) * .8))
            pub.publish(msg)
    finally:
        for _ in range(30):
            pub.publish(Twist())
            rclpy.spin_once(node, timeout_sec=.05)
        result = {"reason": reason, "samples": samples}
        if len(observations) == 2:
            result["final_wheel_yaw"] = yaw(observations["wheel"][1])
            result["final_body_yaw"] = yaw(observations["body"][1])
        print(json.dumps(result), flush=True)
        node.destroy_node()
        rclpy.shutdown()
    if reason != "target_reached":
        raise RuntimeError(reason)


if __name__ == "__main__":
    main()
