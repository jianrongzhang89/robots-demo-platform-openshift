#!/usr/bin/env python3
"""Planar Gazebo pose odometry for the Phase 8 simulator-only demo.

World x/y are common to all hotel floors. Vertical lift travel is deliberately
excluded from Nav2's 2-D odom frame; the independent physics monitor retains z.
This node measures pose, never commands or teleports the robot.
"""
import math
import os
import threading
import time

import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from gz.transport13 import Node as GzNode
from gz.msgs10.pose_v_pb2 import Pose_V


class SimOdometry(Node):
    def __init__(self):
        super().__init__('phase8_sim_odometry')
        self.origin = (float(os.environ.get('INITIAL_X', '15.402')),
                       float(os.environ.get('INITIAL_Y', '-31.594')))
        self.lock = threading.Lock()
        self.latest = None
        self.previous = None
        self.pub = self.create_publisher(Odometry, '/robot_1/odom', 10)
        self.gz = GzNode()
        if not self.gz.subscribe(Pose_V, '/world/sim_world/pose/info', self.receive):
            raise RuntimeError('Gazebo odometry subscription failed')
        self.create_timer(0.05, self.publish)

    def receive(self, msg):
        p = next((p for p in msg.pose if p.name == 'robot_1'), None)
        if p is None:
            return
        q = p.orientation
        yaw = math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))
        stamp = msg.header.stamp
        with self.lock:
            self.latest = (stamp.sec, stamp.nsec, p.position.x, p.position.y, yaw, time.monotonic())

    def publish(self):
        with self.lock:
            row = self.latest
        if row is None or time.monotonic() - row[5] > 0.5:
            return
        sec, nsec, x, y, yaw, _ = row
        now = sec + nsec * 1e-9
        msg = Odometry()
        msg.header.stamp.sec, msg.header.stamp.nanosec = sec, nsec
        msg.header.frame_id, msg.child_frame_id = 'odom', 'base_footprint'
        msg.pose.pose.position.x = x - self.origin[0]
        msg.pose.pose.position.y = y - self.origin[1]
        msg.pose.pose.orientation.z = math.sin(yaw / 2)
        msg.pose.pose.orientation.w = math.cos(yaw / 2)
        if self.previous is not None:
            then, px, py, pyaw = self.previous
            dt = now - then
            if dt <= 0:
                return
            if dt < 0.5:
                vx, vy = (x-px)/dt, (y-py)/dt
                msg.twist.twist.linear.x = math.cos(yaw)*vx + math.sin(yaw)*vy
                msg.twist.twist.linear.y = -math.sin(yaw)*vx + math.cos(yaw)*vy
                msg.twist.twist.angular.z = math.atan2(math.sin(yaw-pyaw), math.cos(yaw-pyaw))/dt
        self.previous = (now, x, y, yaw)
        self.pub.publish(msg)


def main():
    rclpy.init()
    node = SimOdometry()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
