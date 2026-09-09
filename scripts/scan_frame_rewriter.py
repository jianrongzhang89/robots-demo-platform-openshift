#!/usr/bin/env python3
"""
Scan Frame ID Rewriter

Subscribes to /scan with frame_id robot_1/base_scan/lidar
Republishes to /scan_fixed with frame_id base_scan (will be namespaced to robot_1/scan_fixed)

This is a workaround for Gazebo gpu_lidar auto-generating frame_id as model/link/sensor.
"""
import rclpy
import rclpy.parameter
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
from sensor_msgs.msg import LaserScan


class ScanFrameRewriter(Node):
    def __init__(self):
        super().__init__('scan_frame_rewriter',
                         parameter_overrides=[rclpy.parameter.Parameter('use_sim_time', rclpy.Parameter.Type.BOOL, True)])

        # LaserScan QoS (typically best-effort for sensor data)
        scan_qos = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            durability=DurabilityPolicy.VOLATILE,
        )

        # Subscribe to original scan
        self.scan_sub = self.create_subscription(
            LaserScan,
            '/scan',
            self.scan_callback,
            scan_qos
        )

        # Publish to /scan (overwrites the original - this node processes first due to local DDS priority)
        # The scan is consumed locally by AMCL before Zenoh bridge forwards it
        self.scan_pub = self.create_publisher(LaserScan, '/scan_fixed', scan_qos)

        self.get_logger().info('Scan frame rewriter active: robot_1/base_scan/lidar → base_scan on /scan_fixed')

    def scan_callback(self, msg):
        # Check if frame_id needs rewriting
        if msg.header.frame_id == 'robot_1/base_scan/lidar':
            # Create a copy and rewrite frame_id
            fixed_msg = LaserScan()
            fixed_msg.header = msg.header
            fixed_msg.header.frame_id = 'base_scan'  # Will be namespaced to robot_1/base_scan by zenoh bridge
            fixed_msg.angle_min = msg.angle_min
            fixed_msg.angle_max = msg.angle_max
            fixed_msg.angle_increment = msg.angle_increment
            fixed_msg.time_increment = msg.time_increment
            fixed_msg.scan_time = msg.scan_time
            fixed_msg.range_min = msg.range_min
            fixed_msg.range_max = msg.range_max
            fixed_msg.ranges = msg.ranges
            fixed_msg.intensities = msg.intensities

            self.scan_pub.publish(fixed_msg)
        else:
            # Frame ID already correct, pass through
            self.scan_pub.publish(msg)


def main():
    rclpy.init()
    node = ScanFrameRewriter()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
