#!/usr/bin/env python3
"""
Test Nav2 autonomous navigation
Sends navigation goals and monitors execution
"""

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from nav2_msgs.action import NavigateToPose, ComputePathToPose, FollowPath
from geometry_msgs.msg import PoseStamped, Twist
from nav_msgs.msg import Path
import time

class Nav2Tester(Node):
    def __init__(self):
        super().__init__('nav2_tester')

        # Action clients
        self.navigate_client = ActionClient(self, NavigateToPose, 'navigate_to_pose')
        self.compute_path_client = ActionClient(self, ComputePathToPose, 'compute_path_to_pose')
        self.follow_path_client = ActionClient(self, FollowPath, 'follow_path')

        # Velocity publisher for direct control fallback
        self.cmd_vel_pub = self.create_publisher(Twist, '/robot_2/cmd_vel', 10)

        self.get_logger().info('Nav2 Tester initialized')

    def create_pose_stamped(self, x, y, theta=0.0):
        """Create a PoseStamped message"""
        pose = PoseStamped()
        pose.header.frame_id = 'map'
        pose.header.stamp = self.get_clock().now().to_msg()
        pose.pose.position.x = x
        pose.pose.position.y = y
        pose.pose.position.z = 0.0

        # Convert theta to quaternion
        import math
        pose.pose.orientation.w = math.cos(theta / 2.0)
        pose.pose.orientation.z = math.sin(theta / 2.0)

        return pose

    def test_path_planning(self, goal_x, goal_y):
        """Test path planning to a goal"""
        self.get_logger().info(f'Testing path planning to ({goal_x}, {goal_y})')

        # Wait for action server
        if not self.compute_path_client.wait_for_server(timeout_sec=5.0):
            self.get_logger().warn('compute_path_to_pose action server not available')
            return False

        # Create goal
        goal_msg = ComputePathToPose.Goal()
        goal_msg.goal = self.create_pose_stamped(goal_x, goal_y)

        # Send goal
        self.get_logger().info('Sending path planning goal...')
        future = self.compute_path_client.send_goal_async(goal_msg)

        rclpy.spin_until_future_complete(self, future, timeout_sec=10.0)

        if future.result() is not None:
            goal_handle = future.result()
            if goal_handle.accepted:
                self.get_logger().info('✅ Path planning goal accepted!')

                # Wait for result
                result_future = goal_handle.get_result_async()
                rclpy.spin_until_future_complete(self, result_future, timeout_sec=10.0)

                if result_future.result() is not None:
                    result = result_future.result().result
                    path_length = len(result.path.poses) if hasattr(result, 'path') else 0
                    self.get_logger().info(f'✅ Path computed with {path_length} waypoints')
                    return True
            else:
                self.get_logger().error('❌ Path planning goal rejected')
        else:
            self.get_logger().error('❌ Path planning goal failed')

        return False

    def test_navigation(self, goal_x, goal_y):
        """Test full navigation to a goal"""
        self.get_logger().info(f'Testing navigation to ({goal_x}, {goal_y})')

        # Wait for action server
        if not self.navigate_client.wait_for_server(timeout_sec=5.0):
            self.get_logger().warn('navigate_to_pose action server not available')
            return False

        # Create goal
        goal_msg = NavigateToPose.Goal()
        goal_msg.pose = self.create_pose_stamped(goal_x, goal_y)

        # Send goal
        self.get_logger().info('Sending navigation goal...')
        future = self.navigate_client.send_goal_async(goal_msg)

        rclpy.spin_until_future_complete(self, future, timeout_sec=10.0)

        if future.result() is not None:
            goal_handle = future.result()
            if goal_handle.accepted:
                self.get_logger().info('✅ Navigation goal accepted!')
                return True
            else:
                self.get_logger().error('❌ Navigation goal rejected')
        else:
            self.get_logger().error('❌ Navigation goal failed')

        return False

    def test_simple_motion(self):
        """Test simple motion as fallback"""
        self.get_logger().info('Testing simple cmd_vel motion as fallback...')

        twist = Twist()
        twist.linear.x = 0.2

        rate = self.create_rate(10)
        for i in range(30):  # 3 seconds at 10Hz
            self.cmd_vel_pub.publish(twist)
            rate.sleep()

        # Stop
        twist.linear.x = 0.0
        self.cmd_vel_pub.publish(twist)

        self.get_logger().info('✅ Simple motion test complete')

def main(args=None):
    rclpy.init(args=args)

    tester = Nav2Tester()

    try:
        print("\n========================================")
        print("  Nav2 Autonomous Navigation Test")
        print("========================================\n")

        # Test 1: Path planning
        print("Test 1: Path Planning")
        print("---------------------")
        success = tester.test_path_planning(23.4, -25.0)  # 2m forward
        time.sleep(2)

        if not success:
            print("\nTest 2: Full Navigation")
            print("-----------------------")
            success = tester.test_navigation(23.4, -25.0)
            time.sleep(2)

        if not success:
            print("\nFallback: Simple Motion Test")
            print("-----------------------------")
            tester.test_simple_motion()

        print("\n========================================")
        print("  Test Complete")
        print("========================================\n")

    except KeyboardInterrupt:
        tester.get_logger().info('Test interrupted')
    finally:
        tester.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
