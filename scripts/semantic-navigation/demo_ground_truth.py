#!/usr/bin/env python3
"""Publish independent Gazebo model-pose telemetry for the private D2 demo.

This is an observation path, never a velocity publisher or a TF authority.
Wheel-integrated odometry is deliberately not used to construct this pose.
"""
import math

import rclpy
from gz.msgs10.pose_v_pb2 import Pose_V
from gz.transport13 import Node as GazeboNode
from nav_msgs.msg import Odometry


def planar_velocity(previous, current):
    """Return body-frame vx/vy and yaw rate from consecutive truth samples."""
    dt = (current[0] - previous[0]) / 1e9
    if dt <= 0 or dt > 0.5:
        return None
    vx = (current[1] - previous[1]) / dt
    vy = (current[2] - previous[2]) / dt
    yaw = current[3]
    dyaw = math.atan2(math.sin(yaw - previous[3]), math.cos(yaw - previous[3]))
    return (math.cos(yaw) * vx + math.sin(yaw) * vy,
            -math.sin(yaw) * vx + math.cos(yaw) * vy, dyaw / dt)


class GroundTruth:
    def __init__(self):
        self.node = rclpy.create_node("phase6_demo_ground_truth")
        self.publisher = self.node.create_publisher(
            Odometry, "/robot_1/demo/ground_truth", 10)
        self.previous = None
        self.gz = GazeboNode()
        if not self.gz.subscribe(Pose_V, "/world/sim_world/dynamic_pose/info",
                                 self.on_pose):
            raise RuntimeError("could not subscribe to Gazebo model poses")

    def on_pose(self, message):
        stamp = message.header.stamp
        ns = stamp.sec * 1_000_000_000 + stamp.nsec
        if self.previous is not None and ns < self.previous[0]:
            self.previous = None  # New simulator epoch, not a velocity impulse.
        if self.previous is not None and ns - self.previous[0] < 50_000_000:
            return
        pose = next((p for p in message.pose if p.name == "robot_1"), None)
        if pose is None:
            return  # No heartbeat without an actual model-pose observation.
        q = pose.orientation
        yaw = math.atan2(2 * (q.w * q.z + q.x * q.y),
                         1 - 2 * (q.y * q.y + q.z * q.z))
        current = (ns, pose.position.x, pose.position.y, yaw)
        velocity = planar_velocity(self.previous, current) if self.previous else None
        self.previous = current
        if velocity is None:
            return  # Need two fresh samples to assert a measured velocity.
        result = Odometry()
        result.header.frame_id = "map"
        result.header.stamp.sec = stamp.sec
        result.header.stamp.nanosec = stamp.nsec
        result.child_frame_id = "base_footprint"
        result.pose.pose.position.x = pose.position.x
        result.pose.pose.position.y = pose.position.y
        result.pose.pose.position.z = pose.position.z
        result.pose.pose.orientation.x = q.x
        result.pose.pose.orientation.y = q.y
        result.pose.pose.orientation.z = q.z
        result.pose.pose.orientation.w = q.w
        result.twist.twist.linear.x, result.twist.twist.linear.y = velocity[:2]
        result.twist.twist.angular.z = velocity[2]
        self.publisher.publish(result)


def main():
    rclpy.init()
    telemetry = GroundTruth()
    try:
        rclpy.spin(telemetry.node)
    finally:
        telemetry.node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
