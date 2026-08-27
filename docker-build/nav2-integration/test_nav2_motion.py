#!/usr/bin/env python3
"""
Simple Nav2 motion test - bypasses lifecycle complexity
Tests robot motion control via cmd_vel for Nav2 integration verification
"""

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
import time
import math

class Nav2MotionTest(Node):
    def __init__(self):
        super().__init__('nav2_motion_test')

        # Publisher for velocity commands
        self.cmd_vel_pub = self.create_publisher(Twist, '/robot_2/cmd_vel', 10)

        # Subscriber for odometry feedback
        self.odom_sub = self.create_subscription(
            Odometry,
            '/robot_2/odom',
            self.odom_callback,
            10
        )

        self.current_odom = None
        self.get_logger().info('Nav2 Motion Test Node initialized')

    def odom_callback(self, msg):
        """Store latest odometry"""
        self.current_odom = msg

    def move_forward(self, speed=0.3, duration=5.0):
        """Move robot forward at given speed for duration"""
        self.get_logger().info(f'Moving forward at {speed} m/s for {duration}s')

        twist = Twist()
        twist.linear.x = speed

        start_time = time.time()
        rate = self.create_rate(10)  # 10 Hz

        while (time.time() - start_time) < duration:
            self.cmd_vel_pub.publish(twist)
            rate.sleep()

        # Stop
        twist.linear.x = 0.0
        self.cmd_vel_pub.publish(twist)
        self.get_logger().info('Forward motion complete')

    def rotate(self, angular_speed=0.5, duration=3.0):
        """Rotate robot at given angular speed for duration"""
        self.get_logger().info(f'Rotating at {angular_speed} rad/s for {duration}s')

        twist = Twist()
        twist.angular.z = angular_speed

        start_time = time.time()
        rate = self.create_rate(10)  # 10 Hz

        while (time.time() - start_time) < duration:
            self.cmd_vel_pub.publish(twist)
            rate.sleep()

        # Stop
        twist.angular.z = 0.0
        self.cmd_vel_pub.publish(twist)
        self.get_logger().info('Rotation complete')

    def stop(self):
        """Send stop command"""
        twist = Twist()
        self.cmd_vel_pub.publish(twist)
        self.get_logger().info('Robot stopped')

    def run_test_sequence(self):
        """Run a test sequence of motions"""
        self.get_logger().info('Starting Nav2 motion test sequence...')

        # Test 1: Forward motion
        self.get_logger().info('Test 1: Forward motion')
        self.move_forward(speed=0.3, duration=5.0)
        time.sleep(2)

        # Test 2: Rotation
        self.get_logger().info('Test 2: Rotation')
        self.rotate(angular_speed=0.5, duration=3.0)
        time.sleep(2)

        # Test 3: Square pattern
        self.get_logger().info('Test 3: Square pattern')
        for i in range(4):
            self.get_logger().info(f'Side {i+1}')
            self.move_forward(speed=0.2, duration=2.0)
            time.sleep(1)
            self.rotate(angular_speed=0.785, duration=2.0)  # ~90 degrees
            time.sleep(1)

        # Final stop
        self.stop()
        self.get_logger().info('Test sequence complete!')


def main(args=None):
    rclpy.init(args=args)

    node = Nav2MotionTest()

    try:
        # Run test sequence
        node.run_test_sequence()

        # Keep node alive for a bit
        time.sleep(2)

    except KeyboardInterrupt:
        node.get_logger().info('Test interrupted')
        node.stop()

    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
