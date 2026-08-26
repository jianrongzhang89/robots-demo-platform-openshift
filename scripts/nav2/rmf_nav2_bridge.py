#!/usr/bin/env python3
"""Bridge between RMF fleet adapter and Nav2"""

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from rmf_fleet_msgs.msg import PathRequest, RobotState, RobotMode
from nav2_msgs.action import NavigateToPose
from geometry_msgs.msg import PoseStamped, Twist
from nav_msgs.msg import Odometry
import math

class RMFNav2Bridge(Node):
    def __init__(self):
        super().__init__('rmf_nav2_bridge')
        
        # RMF subscriptions
        self.path_sub = self.create_subscription(
            PathRequest,
            '/robot_path_requests',
            self.path_request_callback,
            10
        )
        
        # Nav2 action client
        self.nav_client = ActionClient(
            self,
            NavigateToPose,
            '/deliveryBot_1/navigate_to_pose'
        )
        
        # RMF state publisher
        self.state_pub = self.create_publisher(
            RobotState,
            '/robot_state',
            10
        )
        
        # Odometry subscriber (from simulation)
        self.odom_sub = self.create_subscription(
            Odometry,
            '/deliveryBot_1/odom',
            self.odom_callback,
            10
        )
        
        # Cmd_vel publisher (for slotcar compatibility)
        self.cmd_vel_pub = self.create_publisher(
            Twist,
            '/cmd_vel',
            10
        )
        
        self.current_pose = None
        self.current_goal = None
        
        self.get_logger().info('RMF-Nav2 Bridge initialized')
        self.get_logger().info('  Listening for path requests on /robot_path_requests')
        self.get_logger().info('  Sending goals to /deliveryBot_1/navigate_to_pose')
    
    def odom_callback(self, msg):
        """Track current robot pose from odometry"""
        self.current_pose = msg.pose.pose
    
    def path_request_callback(self, msg):
        """Convert RMF path request to Nav2 goal"""
        if msg.fleet_name != 'deliveryRobot' or msg.robot_name != 'deliveryBot_1':
            return
        
        if not msg.path or len(msg.path) == 0:
            self.get_logger().warn('Received empty path request')
            return
        
        # Get the final waypoint as the goal
        final_waypoint = msg.path[-1]
        
        self.get_logger().info(f'Received path request with {len(msg.path)} waypoints')
        self.get_logger().info(f'Final goal: ({final_waypoint.x:.2f}, {final_waypoint.y:.2f})')
        
        # Create Nav2 goal
        goal_msg = NavigateToPose.Goal()
        goal_msg.pose = PoseStamped()
        goal_msg.pose.header.frame_id = 'map'
        goal_msg.pose.header.stamp = self.get_clock().now().to_msg()
        goal_msg.pose.pose.position.x = final_waypoint.x
        goal_msg.pose.pose.position.y = final_waypoint.y
        goal_msg.pose.pose.position.z = 0.0
        
        # Convert yaw to quaternion
        yaw = final_waypoint.yaw
        goal_msg.pose.pose.orientation.z = math.sin(yaw / 2.0)
        goal_msg.pose.pose.orientation.w = math.cos(yaw / 2.0)
        
        # Send goal to Nav2
        self.get_logger().info('Waiting for Nav2 action server...')
        self.nav_client.wait_for_server(timeout_sec=5.0)
        
        self.get_logger().info('Sending goal to Nav2...')
        self.current_goal = self.nav_client.send_goal_async(
            goal_msg,
            feedback_callback=self.nav_feedback_callback
        )
        self.current_goal.add_done_callback(self.nav_goal_response_callback)
    
    def nav_goal_response_callback(self, future):
        """Handle Nav2 goal acceptance/rejection"""
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().error('Nav2 goal rejected!')
            return
        
        self.get_logger().info('Nav2 goal accepted, robot navigating...')
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self.nav_result_callback)
    
    def nav_feedback_callback(self, feedback_msg):
        """Handle Nav2 navigation feedback"""
        feedback = feedback_msg.feedback
        dist = feedback.distance_remaining
        self.get_logger().info(f'Distance remaining: {dist:.2f}m', throttle_duration_sec=2.0)
    
    def nav_result_callback(self, future):
        """Handle Nav2 navigation result"""
        result = future.result().result
        self.get_logger().info(f'Navigation result: {result}')
        
        if result:
            self.get_logger().info('✅ Navigation completed successfully!')
        else:
            self.get_logger().error('❌ Navigation failed!')

def main(args=None):
    rclpy.init(args=args)
    bridge = RMFNav2Bridge()
    
    try:
        rclpy.spin(bridge)
    except KeyboardInterrupt:
        pass
    finally:
        bridge.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
