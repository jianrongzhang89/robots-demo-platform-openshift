#!/usr/bin/env python3
"""
Drive robot in a pattern to build slam_toolbox map
Publishes cmd_vel commands to make the robot explore
"""

import sys
import time
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist


class PatternDriver(Node):
    def __init__(self, robot_name):
        super().__init__(f'{robot_name}_pattern_driver')
        self.robot_name = robot_name

        # Publisher for cmd_vel
        self.cmd_vel_pub = self.create_publisher(
            Twist,
            f'/{robot_name}/cmd_vel',
            10
        )

        self.get_logger().info(f'Pattern driver started for {robot_name}')
        self.get_logger().info('Publishing to /{}/cmd_vel'.format(robot_name))

    def drive_pattern(self):
        """Drive in a pattern: forward, rotate, forward, rotate, etc."""

        # Pattern: drive around in a rectangular-ish pattern
        # This helps slam_toolbox build a good map

        movements = [
            # (linear_x, angular_z, duration_sec, description)
            (0.3, 0.0, 5.0, "Forward 5s"),
            (0.0, 0.5, 3.14, "Rotate 90° left"),
            (0.3, 0.0, 4.0, "Forward 4s"),
            (0.0, 0.5, 3.14, "Rotate 90° left"),
            (0.3, 0.0, 5.0, "Forward 5s"),
            (0.0, 0.5, 3.14, "Rotate 90° left"),
            (0.3, 0.0, 4.0, "Forward 4s"),
            (0.0, 0.5, 3.14, "Rotate 90° left"),
            # Back to start, now explore another area
            (0.3, 0.0, 3.0, "Forward 3s"),
            (0.0, -0.5, 3.14, "Rotate 90° right"),
            (0.3, 0.0, 6.0, "Forward 6s"),
            (0.0, -0.5, 3.14, "Rotate 90° right"),
            (0.3, 0.0, 4.0, "Forward 4s"),
            (0.0, 0.0, 2.0, "Stop and settle"),
        ]

        for linear_x, angular_z, duration, desc in movements:
            self.get_logger().info(f'Movement: {desc}')

            twist = Twist()
            twist.linear.x = linear_x
            twist.angular.z = angular_z

            # Publish at 10 Hz for the duration
            rate = self.create_rate(10)
            start_time = time.time()

            while (time.time() - start_time) < duration:
                self.cmd_vel_pub.publish(twist)
                try:
                    rate.sleep()
                except:
                    pass

        # Final stop
        self.get_logger().info('Pattern complete, stopping robot')
        stop = Twist()
        for _ in range(10):
            self.cmd_vel_pub.publish(stop)
            time.sleep(0.1)


def main(args=None):
    if len(sys.argv) < 2:
        print("Usage: drive_robot_pattern.py <robot_name>")
        print("Example: drive_robot_pattern.py tinyBot_1")
        sys.exit(1)

    robot_name = sys.argv[1]

    rclpy.init(args=args)
    node = PatternDriver(robot_name)

    try:
        # Wait a bit for everything to be ready
        time.sleep(2.0)

        # Drive the pattern
        node.drive_pattern()

        # Let it settle
        time.sleep(2.0)

    except KeyboardInterrupt:
        pass
    finally:
        # Stop the robot
        stop = Twist()
        for _ in range(10):
            node.cmd_vel_pub.publish(stop)
            time.sleep(0.1)

        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
