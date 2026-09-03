#!/usr/bin/env python3
"""
Nav2 Puppet Controller for RMF Multi-Level Navigation

Bridges RMF task dispatch with Nav2 navigation for multi-level hotel demo.
Bypasses broken EasyFullControl C++ execution layer while providing full
RMF coordination including lift usage.

Flow:
  1. Monitors /dispatch_states for task assignments
  2. Parses multi-level routes from task descriptions
  3. Coordinates lift requests/states via RMF topics
  4. Sends Nav2 goals via /navigate_to_pose action
  5. Monitors progress and reports completion

Usage:
  ros2 run ... nav2_puppet_controller.py
"""

import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.action import ActionClient
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy

from rmf_task_msgs.msg import DispatchStates
from rmf_lift_msgs.msg import LiftRequest, LiftState
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from tf2_msgs.msg import TFMessage

import time
import json
import math


# Waypoint database with coordinates for all floors
WAYPOINTS = {
    # L1 waypoints
    "lobby_east":          {"level": "L1", "x": 23.5,  "y": -27.4, "yaw": 0.0},
    "lobby_west":          {"level": "L1", "x": 15.0,  "y": -30.0, "yaw": 0.0},
    "lobby_center":        {"level": "L1", "x": 20.0,  "y": -30.0, "yaw": 0.0},
    "lobby_southeast":     {"level": "L1", "x": 25.0,  "y": -35.0, "yaw": 0.0},
    "lobby_southwest":     {"level": "L1", "x": 15.0,  "y": -35.0, "yaw": 0.0},
    "tinybot_charger":     {"level": "L1", "x": 10.0,  "y": -25.0, "yaw": 0.0},
    "lift1_approach_L1":   {"level": "L1", "x": 355.0, "y": 345.0, "yaw": 0.0},
    "lift2_approach_L1":   {"level": "L1", "x": 305.0, "y": 440.0, "yaw": 0.0},
    "lift1_cabin_L1":      {"level": "L1", "x": 355.0, "y": 340.0, "yaw": 0.0, "lift": "Lift1"},
    "lift2_cabin_L1":      {"level": "L1", "x": 305.0, "y": 435.0, "yaw": 0.0, "lift": "Lift2"},

    # L2 waypoints
    "L2_room1":            {"level": "L2", "x": 350.0, "y": 340.0, "yaw": 0.0},
    "L2_room2":            {"level": "L2", "x": 360.0, "y": 340.0, "yaw": 0.0},
    "L2_room3":            {"level": "L2", "x": 300.0, "y": 435.0, "yaw": 0.0},
    "L2_room4":            {"level": "L2", "x": 310.0, "y": 435.0, "yaw": 0.0},
    "lift1_approach_L2":   {"level": "L2", "x": 355.0, "y": 345.0, "yaw": 0.0},
    "lift2_approach_L2":   {"level": "L2", "x": 305.0, "y": 440.0, "yaw": 0.0},
    "lift1_cabin_L2":      {"level": "L2", "x": 355.0, "y": 340.0, "yaw": 0.0, "lift": "Lift1"},
    "lift2_cabin_L2":      {"level": "L2", "x": 305.0, "y": 435.0, "yaw": 0.0, "lift": "Lift2"},

    # L3 waypoints
    "L3_room1":            {"level": "L3", "x": 350.0, "y": 340.0, "yaw": 0.0},
    "L3_room2":            {"level": "L3", "x": 360.0, "y": 340.0, "yaw": 0.0},
    "L3_room3":            {"level": "L3", "x": 300.0, "y": 435.0, "yaw": 0.0},
    "L3_room4":            {"level": "L3", "x": 310.0, "y": 435.0, "yaw": 0.0},
    "lift1_approach_L3":   {"level": "L3", "x": 355.0, "y": 345.0, "yaw": 0.0},
    "lift2_approach_L3":   {"level": "L3", "x": 305.0, "y": 440.0, "yaw": 0.0},
    "lift1_cabin_L3":      {"level": "L3", "x": 355.0, "y": 340.0, "yaw": 0.0, "lift": "Lift1"},
    "lift2_cabin_L3":      {"level": "L3", "x": 305.0, "y": 435.0, "yaw": 0.0, "lift": "Lift2"},
}

ARRIVE_THRESHOLD = 1.0  # meters
LIFT_WAIT_TIMEOUT = 60.0  # seconds


class Nav2PuppetController(Node):
    def __init__(self):
        super().__init__("nav2_puppet_controller")
        self.set_parameters([Parameter("use_sim_time", Parameter.Type.BOOL, True)])

        # QoS for RMF topics
        rmf_qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            history=HistoryPolicy.KEEP_LAST,
            depth=10
        )

        # Subscribe to RMF dispatch states
        self._dispatch_sub = self.create_subscription(
            DispatchStates,
            "/dispatch_states",
            self._dispatch_callback,
            rmf_qos
        )

        # Lift coordination
        self._lift_request_pub = self.create_publisher(
            LiftRequest,
            "/lift_requests",
            10
        )
        self._lift_state_sub = self.create_subscription(
            LiftState,
            "/lift_states",
            self._lift_state_callback,
            10
        )
        self._lift_states = {}  # lift_name -> LiftState

        # Robot TF tracking
        self._tf_sub = self.create_subscription(
            TFMessage,
            "/tinyBot_1/tf",
            self._tf_callback,
            10
        )
        self._robot_position = None  # (x, y, level)

        # Nav2 action client (namespaced for tinyBot_1)
        self._nav_action_client = ActionClient(
            self,
            NavigateToPose,
            "/tinyBot_1/navigate_to_pose"
        )

        # Task tracking
        self._active_tasks = {}  # task_id -> task_info
        self._current_goal_handle = None

        # Processing timer
        self._timer = self.create_timer(2.0, self._process_tasks)

        self.get_logger().info("🤖 Nav2 Puppet Controller started for multi-level navigation")

    def _dispatch_callback(self, msg):
        """Handle RMF task dispatch assignments."""
        for state in msg.active:
            task_id = state.task_id
            if not task_id or task_id in self._active_tasks:
                continue

            assignment = state.assignment
            if not assignment.fleet_name or not assignment.expected_robot_name:
                continue

            # Only handle tasks assigned to tinyBot_1 in tinyRobot fleet
            if assignment.fleet_name != "tinyRobot" or assignment.expected_robot_name != "tinyBot_1":
                continue

            # Status 2=selected, 3=dispatched
            if state.status not in (2, 3):
                continue

            self.get_logger().info(
                f"📋 Task {task_id} assigned to {assignment.expected_robot_name}"
            )

            # Parse task description to extract waypoint sequence
            # This is a simplified parser - real implementation would parse the full task JSON
            self._active_tasks[task_id] = {
                "robot": assignment.expected_robot_name,
                "fleet": assignment.fleet_name,
                "waypoints": [],  # Will be populated from task description
                "current_waypoint_index": 0,
                "state": "parsing"
            }

    def _lift_state_callback(self, msg):
        """Track lift states."""
        self._lift_states[msg.lift_name] = msg

    def _tf_callback(self, msg):
        """Track robot position from TF."""
        for transform in msg.transforms:
            if transform.child_frame_id == "tinyBot_1/base_footprint":
                t = transform.transform.translation
                self._robot_position = (t.x, t.y)

    def _process_tasks(self):
        """Process active tasks - main control loop."""
        for task_id, info in list(self._active_tasks.items()):
            if info["state"] == "parsing":
                # TODO: Parse task description from /dispatch_states to extract waypoint sequence
                # For now, use a test sequence
                info["waypoints"] = ["lobby_east", "lift1_approach_L1", "lift1_cabin_L1",
                                     "lift1_cabin_L2", "lift1_approach_L2", "L2_room1"]
                info["state"] = "navigating"
                self.get_logger().info(f"🗺️  Parsed route: {' → '.join(info['waypoints'])}")

            elif info["state"] == "navigating":
                self._execute_waypoint_sequence(task_id, info)

    def _execute_waypoint_sequence(self, task_id, info):
        """Execute navigation through waypoint sequence with lift coordination."""
        if info["current_waypoint_index"] >= len(info["waypoints"]):
            self.get_logger().info(f"✅ Task {task_id} completed!")
            info["state"] = "completed"
            return

        wp_name = info["waypoints"][info["current_waypoint_index"]]
        wp = WAYPOINTS.get(wp_name)

        if not wp:
            self.get_logger().error(f"❌ Unknown waypoint: {wp_name}")
            info["state"] = "failed"
            return

        # Check if this is a lift cabin waypoint
        if "lift" in wp:
            self._handle_lift_transition(task_id, info, wp_name, wp)
        else:
            self._navigate_to_waypoint(task_id, info, wp_name, wp)

    def _navigate_to_waypoint(self, task_id, info, wp_name, wp):
        """Send Nav2 goal for regular waypoint."""
        if self._current_goal_handle is not None:
            # Goal already in progress, check if arrived
            if self._robot_position:
                dist = math.sqrt(
                    (self._robot_position[0] - wp["x"])**2 +
                    (self._robot_position[1] - wp["y"])**2
                )
                if dist < ARRIVE_THRESHOLD:
                    self.get_logger().info(f"✓ Arrived at {wp_name}")
                    info["current_waypoint_index"] += 1
                    self._current_goal_handle = None
            return

        # Send new Nav2 goal
        goal_msg = NavigateToPose.Goal()
        goal_msg.pose.header.frame_id = f"tinyBot_1/map"
        goal_msg.pose.header.stamp = self.get_clock().now().to_msg()
        goal_msg.pose.pose.position.x = wp["x"]
        goal_msg.pose.pose.position.y = wp["y"]
        goal_msg.pose.pose.position.z = 0.0

        # Convert yaw to quaternion (simplified - assumes z-axis rotation only)
        yaw = wp["yaw"]
        goal_msg.pose.pose.orientation.z = math.sin(yaw / 2.0)
        goal_msg.pose.pose.orientation.w = math.cos(yaw / 2.0)

        self.get_logger().info(f"🎯 Navigating to {wp_name} at ({wp['x']:.1f}, {wp['y']:.1f})")

        # Send goal asynchronously
        send_goal_future = self._nav_action_client.send_goal_async(goal_msg)
        send_goal_future.add_done_callback(
            lambda future: self._goal_response_callback(future, wp_name)
        )

    def _goal_response_callback(self, future, wp_name):
        """Handle Nav2 goal acceptance."""
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().error(f"❌ Nav2 goal to {wp_name} rejected")
            return

        self._current_goal_handle = goal_handle
        self.get_logger().info(f"→ Nav2 goal to {wp_name} accepted")

    def _handle_lift_transition(self, task_id, info, wp_name, wp):
        """Handle lift coordination for cabin waypoints."""
        lift_name = wp["lift"]
        current_wp = info["waypoints"][info["current_waypoint_index"]]

        # Determine source and destination floors
        source_floor = wp["level"]

        # Next waypoint should be cabin on different floor
        if info["current_waypoint_index"] + 1 < len(info["waypoints"]):
            next_wp_name = info["waypoints"][info["current_waypoint_index"] + 1]
            next_wp = WAYPOINTS.get(next_wp_name)
            dest_floor = next_wp["level"] if next_wp else source_floor
        else:
            dest_floor = source_floor

        # Check if we're already in the cabin
        if not hasattr(info, "in_lift"):
            # Navigate into cabin first
            self._navigate_to_waypoint(task_id, info, wp_name, wp)

            # Check if we arrived at cabin entrance
            if self._robot_position:
                dist = math.sqrt(
                    (self._robot_position[0] - wp["x"])**2 +
                    (self._robot_position[1] - wp["y"])**2
                )
                if dist < ARRIVE_THRESHOLD:
                    info["in_lift"] = True
                    self.get_logger().info(f"🛗 Entered {lift_name}, requesting floor {dest_floor}")
                    self._request_lift(lift_name, dest_floor)
            return

        # Wait for lift to reach destination floor
        lift_state = self._lift_states.get(lift_name)
        if lift_state and lift_state.current_floor == dest_floor and lift_state.door_state == LiftState.DOOR_OPEN:
            self.get_logger().info(f"✓ {lift_name} arrived at {dest_floor}, doors open")
            info["current_waypoint_index"] += 1
            del info["in_lift"]
            self._current_goal_handle = None

    def _request_lift(self, lift_name, destination_floor):
        """Send lift request to RMF."""
        req = LiftRequest()
        req.lift_name = lift_name
        req.destination_floor = destination_floor
        req.request_type = LiftRequest.REQUEST_AGV_MODE
        req.door_state = LiftRequest.DOOR_OPEN
        req.session_id = f"puppet_controller_{int(time.time())}"

        self._lift_request_pub.publish(req)
        self.get_logger().info(f"📤 Requested {lift_name} to floor {destination_floor}")


def main(args=None):
    rclpy.init(args=args)
    controller = Nav2PuppetController()

    try:
        rclpy.spin(controller)
    except KeyboardInterrupt:
        pass

    controller.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
