#!/usr/bin/env python3
"""Move a stopped Phase 2 robot by odometry distance/angle, then verify stop."""

from __future__ import annotations

import argparse
import json
import math
import time

import rclpy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node


def yaw_from_quaternion(q) -> float:
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y),
                      1.0 - 2.0 * (q.y * q.y + q.z * q.z))


def wrap_angle(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


class Motion(Node):
    def __init__(self, args: argparse.Namespace):
        super().__init__("semantic_phase2_odometry_motion")
        self.args = args
        self.publisher = self.create_publisher(Twist, args.cmd_vel, 10)
        self.create_subscription(Odometry, args.odom, self.odom_cb, 10)
        self.latest: Odometry | None = None
        self.initial: Odometry | None = None

    def odom_cb(self, msg: Odometry) -> None:
        self.latest = msg
        if self.initial is None:
            self.initial = msg

    def publish(self, linear: float = 0.0, angular: float = 0.0) -> None:
        command = Twist()
        command.linear.x = linear
        command.angular.z = angular
        self.publisher.publish(command)

    def run_motion(self) -> dict:
        deadline = time.monotonic() + self.args.timeout
        while self.latest is None and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.05)
        if self.latest is None:
            raise TimeoutError("no odometry received before motion deadline")
        if abs(self.latest.twist.twist.linear.x) > 0.01 or abs(
                self.latest.twist.twist.angular.z) > 0.01:
            raise RuntimeError("robot was not stopped at motion start")
        initial = self.initial
        assert initial is not None
        initial_x = initial.pose.pose.position.x
        initial_y = initial.pose.pose.position.y
        initial_yaw = yaw_from_quaternion(initial.pose.pose.orientation)
        linear_target = self.args.linear_distance
        angular_target = self.args.angular_distance
        if (linear_target is None) == (angular_target is None):
            raise ValueError("specify exactly one of linear or angular distance")
        if linear_target is not None and abs(linear_target) > 0.5:
            raise ValueError("linear move is limited to 0.5 m per command")
        if angular_target is not None and abs(angular_target) > 1.0:
            raise ValueError("angular move is limited to 1 radian per command")

        direction = math.copysign(1.0, linear_target if linear_target is not None
                                  else angular_target)
        motion_started = time.monotonic()
        settled_samples = 0
        while time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.02)
            current = self.latest
            if current is None:
                continue
            position = current.pose.pose.position
            yaw = yaw_from_quaternion(current.pose.pose.orientation)
            if linear_target is not None:
                dx, dy = position.x - initial_x, position.y - initial_y
                progress = dx * math.cos(initial_yaw) + dy * math.sin(initial_yaw)
                remaining = abs(linear_target) - direction * progress
                reached = remaining <= self.args.tolerance
                speed = min(self.args.speed, max(self.args.min_speed, remaining * 0.5))
                self.publish(0.0 if reached else direction * speed)
            else:
                turned = wrap_angle(yaw - initial_yaw)
                remaining = abs(angular_target) - direction * turned
                reached = remaining <= self.args.angular_tolerance
                speed = min(self.args.angular_speed,
                            max(self.args.min_angular_speed, remaining * 0.5))
                self.publish(angular=0.0 if reached else direction * speed)

            if reached:
                self.publish()
                velocity = current.twist.twist
                stopped = (abs(velocity.linear.x) < 0.01
                           and abs(velocity.angular.z) < 0.01)
                settled_samples = settled_samples + 1 if stopped else 0
                if settled_samples >= 3:
                    break
            else:
                settled_samples = 0

        self.publish()
        for _ in range(5):
            rclpy.spin_once(self, timeout_sec=0.05)
            self.publish()
        final = self.latest
        if final is None or settled_samples < 3:
            raise TimeoutError("motion failed to reach target and verify a stopped state")
        final_position = final.pose.pose.position
        final_yaw = yaw_from_quaternion(final.pose.pose.orientation)
        dx, dy = final_position.x - initial_x, final_position.y - initial_y
        return {
            "status": "STOPPED_AT_ODOMETRY_TARGET",
            "requested_linear_distance_m": linear_target,
            "requested_angular_distance_rad": angular_target,
            "measured_forward_distance_m": round(
                dx * math.cos(initial_yaw) + dy * math.sin(initial_yaw), 6
            ),
            "measured_yaw_change_rad": round(wrap_angle(final_yaw - initial_yaw), 6),
            "initial_odom_xy_m": [initial_x, initial_y],
            "final_odom_xy_m": [final_position.x, final_position.y],
            "final_linear_velocity_mps": final.twist.twist.linear.x,
            "final_angular_velocity_radps": final.twist.twist.angular.z,
            "elapsed_seconds": round(time.monotonic() - motion_started, 3),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--odom", default="/robot_1/odom")
    parser.add_argument("--cmd-vel", default="/robot_1/cmd_vel")
    parser.add_argument("--linear-distance", type=float)
    parser.add_argument("--angular-distance", type=float)
    parser.add_argument("--speed", type=float, default=0.04)
    parser.add_argument("--min-speed", type=float, default=0.01)
    parser.add_argument("--angular-speed", type=float, default=0.08)
    parser.add_argument("--min-angular-speed", type=float, default=0.02)
    parser.add_argument("--tolerance", type=float, default=0.005)
    parser.add_argument("--angular-tolerance", type=float, default=0.02)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    if not 0 < args.speed <= 0.05 or not 0 < args.min_speed <= args.speed:
        parser.error("linear speed must be 0 < min_speed <= speed <= 0.05 m/s")
    if not 0 < args.angular_speed <= 0.1 or not 0 < args.min_angular_speed <= args.angular_speed:
        parser.error("angular speed must be 0 < min_speed <= speed <= 0.1 rad/s")
    rclpy.init()
    node = Motion(args)
    try:
        print(json.dumps(node.run_motion(), sort_keys=True))
    finally:
        node.publish()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
