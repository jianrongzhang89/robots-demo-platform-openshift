#!/usr/bin/env python3
"""
RMF-Nav2 Bridge using Component Actions

Converts RMF robot path requests into Nav2 component actions:
1. /compute_path_to_pose - Plan path
2. /follow_path - Execute path

Since bt_navigator crashed, we use the 2-step component approach instead
of the single /navigate_to_pose action.
"""

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from nav2_msgs.action import ComputePathToPose, FollowPath
from geometry_msgs.msg import PoseStamped
from rmf_fleet_msgs.msg import RobotState, PathRequest
from std_msgs.msg import String
import json


class RMFNav2BridgeComponent(Node):
    def __init__(self):
        super().__init__('rmf_nav2_bridge_component')

        # RMF subscribers
        self.path_request_sub = self.create_subscription(
            PathRequest,
            '/robot_path_requests',
            self.path_request_callback,
            10
        )

        # Nav2 action clients (component actions)
        self.planner_client = ActionClient(self, ComputePathToPose, '/compute_path_to_pose')
        self.controller_client = ActionClient(self, FollowPath, '/follow_path')

        # Status publisher
        self.status_pub = self.create_publisher(String, '/rmf_nav2_bridge/status', 10)

        self.get_logger().info('RMF-Nav2 Bridge (Component Actions) started')
        self.get_logger().info('Waiting for Nav2 action servers...')

        # Wait for action servers
        self.planner_client.wait_for_server()
        self.controller_client.wait_for_server()

        self.get_logger().info('✅ Connected to Nav2 action servers')

        self.current_goal = None

    def path_request_callback(self, msg: PathRequest):
        """Handle RMF path request - convert to Nav2 actions"""

        # Only handle tinyBot_1 (robot_2)
        if msg.robot_name != 'tinyBot_1':
            return

        # Extract goal from path (last waypoint)
        if not msg.path:
            return

        goal_location = msg.path[-1]

        self.get_logger().info(
            f'Received RMF path request for {msg.robot_name} '
            f'to ({goal_location.x:.2f}, {goal_location.y:.2f}, level {goal_location.level_name})'
        )

        # Create Nav2 goal pose
        goal_pose = PoseStamped()
        goal_pose.header.frame_id = 'map'
        goal_pose.header.stamp = self.get_clock().now().to_msg()
        goal_pose.pose.position.x = goal_location.x
        goal_pose.pose.position.y = goal_location.y
        goal_pose.pose.position.z = 0.0

        # Convert yaw to quaternion
        import math
        yaw = goal_location.yaw
        goal_pose.pose.orientation.z = math.sin(yaw / 2.0)
        goal_pose.pose.orientation.w = math.cos(yaw / 2.0)

        # Step 1: Plan path
        self.plan_and_execute(goal_pose)

    def plan_and_execute(self, goal_pose: PoseStamped):
        """Plan path using /compute_path_to_pose, then execute with /follow_path"""

        # Step 1: Plan path
        plan_goal = ComputePathToPose.Goal()
        plan_goal.goal = goal_pose
        plan_goal.planner_id = 'GridBased'
        plan_goal.use_start = False

        self.get_logger().info(
            f'Planning path to ({goal_pose.pose.position.x:.2f}, '
            f'{goal_pose.pose.position.y:.2f})'
        )

        # Send planning goal
        self.current_goal = self.planner_client.send_goal_async(plan_goal)
        self.current_goal.add_done_callback(self.planning_response_callback)

    def planning_response_callback(self, future):
        """Handle planning result"""
        goal_handle = future.result()

        if not goal_handle.accepted:
            self.get_logger().error('Path planning goal rejected!')
            self.publish_status('planning_rejected')
            return

        self.get_logger().info('Path planning goal accepted')
        self.publish_status('planning')

        # Get result
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self.planning_result_callback)

    def planning_result_callback(self, future):
        """Handle planning result and start path following"""
        result = future.result().result

        if not result.path or not result.path.poses:
            self.get_logger().error('Path planning failed - no path returned')
            self.publish_status('planning_failed')
            return

        self.get_logger().info(
            f'Path planned successfully - {len(result.path.poses)} waypoints'
        )

        # Step 2: Follow the planned path
        follow_goal = FollowPath.Goal()
        follow_goal.path = result.path
        follow_goal.controller_id = 'FollowPath'

        self.get_logger().info('Executing path...')
        self.publish_status('following_path')

        # Send path following goal
        follow_future = self.controller_client.send_goal_async(
            follow_goal,
            feedback_callback=self.path_feedback_callback
        )
        follow_future.add_done_callback(self.following_response_callback)

    def following_response_callback(self, future):
        """Handle path following acceptance"""
        goal_handle = future.result()

        if not goal_handle.accepted:
            self.get_logger().error('Path following goal rejected!')
            self.publish_status('following_rejected')
            return

        self.get_logger().info('Path following goal accepted')

        # Get result
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self.following_result_callback)

    def following_result_callback(self, future):
        """Handle path following completion"""
        result = future.result()

        if result.status == 4:  # SUCCEEDED
            self.get_logger().info('✅ Navigation completed successfully!')
            self.publish_status('completed')
        else:
            self.get_logger().error(f'Navigation failed with status: {result.status}')
            self.publish_status('failed')

    def path_feedback_callback(self, feedback_msg):
        """Handle path following feedback"""
        feedback = feedback_msg.feedback
        self.get_logger().info(
            f'Distance to goal: {feedback.distance_to_goal:.2f}m, '
            f'Speed: {feedback.speed:.3f} m/s',
            throttle_duration_sec=2.0
        )

    def publish_status(self, status: str):
        """Publish bridge status"""
        msg = String()
        msg.data = json.dumps({
            'timestamp': self.get_clock().now().to_msg().sec,
            'status': status
        })
        self.status_pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)

    bridge = RMFNav2BridgeComponent()

    try:
        rclpy.spin(bridge)
    except KeyboardInterrupt:
        pass
    finally:
        bridge.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
