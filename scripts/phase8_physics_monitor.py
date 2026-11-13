#!/usr/bin/env python3
"""Publish independent Gazebo world pose evidence for the multi-level trial."""
import json
import math
import threading
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from gz.transport13 import Node as GzNode
from gz.msgs10.pose_v_pb2 import Pose_V


class PhysicsMonitor(Node):
    def __init__(self):
        super().__init__('phase8_physics_monitor')
        self.lock = threading.Lock()
        self.latest = None
        self.pub = self.create_publisher(String, '/phase8/physics', 5)
        self.gz = GzNode()
        if not self.gz.subscribe(Pose_V, '/world/sim_world/pose/info', self.receive):
            raise RuntimeError('Gazebo world pose subscription failed')
        self.trace = open('/tmp/phase8-physics.jsonl', 'a', buffering=1)
        # Provide fresh Gazebo poses to lift-entry control and diagnostics.
        self.create_timer(0.05, self.publish)

    def receive(self, msg):
        p = next((p for p in msg.pose if p.name == 'robot_1'), None)
        if p is None:
            return
        lift = next((p for p in msg.pose if p.name == "Lift2"), None)
        q = p.orientation
        row = {'wall_time': time.time(), 'x': p.position.x,
               'y': p.position.y, 'z': p.position.z,
               'yaw': math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z)),
               'roll': math.atan2(2*(q.w*q.x+q.y*q.z), 1-2*(q.x*q.x+q.y*q.y)),
               'pitch': math.asin(max(-1., min(1., 2*(q.w*q.y-q.z*q.x))))}
        if lift is not None:
            row['lift2_z'] = lift.position.z
        with self.lock:
            self.latest = row

    def publish(self):
        with self.lock:
            row = self.latest
        if row is not None:
            payload = json.dumps(row)
            self.pub.publish(String(data=payload))
            self.trace.write(payload + '\n')


def main():
    rclpy.init()
    node = PhysicsMonitor()
    try:
        rclpy.spin(node)
    finally:
        node.trace.close()
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
