#!/usr/bin/env python3
"""
Send a navigation goal to a specific robot to demonstrate Nav2 working.
"""
import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from nav2_msgs.action import NavigateToPose
from geometry_msgs.msg import PoseStamped
import sys


class NavGoalSender(Node):
    def __init__(self, robot_name):
        super().__init__('nav_goal_sender')
        self.robot_name = robot_name
        self.action_client = ActionClient(
            self, NavigateToPose, f'/{robot_name}/navigate_to_pose'
        )

    def send_goal(self, x, y, yaw=0.0):
        """Send navigation goal to robot"""
        goal_msg = NavigateToPose.Goal()
        goal_msg.pose = PoseStamped()
        goal_msg.pose.header.frame_id = 'map'
        goal_msg.pose.header.stamp = self.get_clock().now().to_msg()
        goal_msg.pose.pose.position.x = x
        goal_msg.pose.pose.position.y = y
        goal_msg.pose.pose.position.z = 0.0
        goal_msg.pose.pose.orientation.w = 1.0

        self.get_logger().info(f'Waiting for action server /{self.robot_name}/navigate_to_pose...')
        self.action_client.wait_for_server(timeout_sec=5.0)

        self.get_logger().info(f'Sending goal: ({x}, {y}) to {self.robot_name}')
        send_goal_future = self.action_client.send_goal_async(
            goal_msg, feedback_callback=self.feedback_callback
        )
        send_goal_future.add_done_callback(self.goal_response_callback)

        return send_goal_future

    def goal_response_callback(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().info('Goal rejected')
            return

        self.get_logger().info('Goal accepted, waiting for result...')
        self._get_result_future = goal_handle.get_result_async()
        self._get_result_future.add_done_callback(self.get_result_callback)

    def get_result_callback(self, future):
        result = future.result().result
        self.get_logger().info(f'Navigation result received!')
        rclpy.shutdown()

    def feedback_callback(self, feedback_msg):
        feedback = feedback_msg.feedback
        self.get_logger().info(
            f'Distance remaining: {feedback.distance_remaining:.2f}m'
        )


def main(args=None):
    if len(sys.argv) < 4:
        print("Usage: send_nav_goal.py <robot_name> <x> <y>")
        print("Example: send_nav_goal.py tinyBot_3 20.0 -30.0")
        sys.exit(1)

    robot_name = sys.argv[1]
    x = float(sys.argv[2])
    y = float(sys.argv[3])

    rclpy.init(args=args)
    sender = NavGoalSender(robot_name)

    sender.send_goal(x, y)

    try:
        rclpy.spin(sender)
    except KeyboardInterrupt:
        pass

    sender.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()


if __name__ == '__main__':
    main()
