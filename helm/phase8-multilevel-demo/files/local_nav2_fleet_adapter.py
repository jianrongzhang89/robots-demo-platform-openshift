#!/usr/bin/env python3
"""Local ROS 2 EasyFullControl backend for the single hotel robot.

This intentionally contains no transport bridge. RMF and Nav2 are in the same
DDS domain, so navigation uses the real NavigateToPose action and map changes
use Nav2's LoadMap service. A command generation guards every asynchronous
result; a late result can therefore never complete a replacement RMF activity.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import threading
import time
from typing import Optional

import rclpy
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseWithCovarianceStamped, Twist
from std_msgs.msg import Bool, String
from nav2_msgs.action import NavigateToPose
from nav2_msgs.srv import ClearEntireCostmap, LoadMap, ManageLifecycleNodes
from rcl_interfaces.srv import SetParameters
from nav_msgs.msg import OccupancyGrid, Odometry
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.time import Time
from rmf_adapter import Adapter
import rmf_adapter
import rmf_adapter.easy_full_control as rmf_easy
from rmf_adapter.robot_update_handle import Tier
from tf2_msgs.msg import TFMessage
from tf2_ros import Buffer
from rmf_lift_msgs.msg import LiftState
from local_nav2_fleet_adapter_contract import (
    cancellation_confirmed, keep_active_goal, nav2_success, ros_topic)


def yaw_from_quaternion(q) -> float:
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y),
                      1.0 - 2.0 * (q.y * q.y + q.z * q.z))


def angle_error(a: float, b: float) -> float:
    return abs((a - b + math.pi) % (2.0 * math.pi) - math.pi)


class LocalRobotBackend(Node):
    """ROS action/service backend owned by one EasyFullControl robot."""

    def __init__(self, robot_name: str, initial_map: str, initial_pose: list[float],
                 ros_namespace: str | None = None):
        super().__init__(f"{robot_name}_local_backend")
        self.set_parameters([Parameter("use_sim_time", Parameter.Type.BOOL, True)])
        self.robot_name = robot_name
        self.ros_namespace = robot_name if ros_namespace is None else ros_namespace
        self.current_map = initial_map
        self.pose = list(initial_pose)
        self.last_pose_time = 0.0
        self.velocity = [0.0, 0.0]
        self.map_received = threading.Event()
        self.global_costmap_received = threading.Event()
        self.pose_received = threading.Event()
        self._tf_pose_time = 0.0
        self._map_shape = None
        self._lock = threading.RLock()
        self._generation = 0
        self._active_goal = None
        self._pending_goal_generation = None
        self._active_execution = None
        self._active_target = None
        self._active_command_position = None
        self._active_lift_exit = False
        self._exit_lift_command = False
        self._face_l1_return_direction = False
        self._payload_state = None
        self._navigation_retries = 0
        self._hallway_dwell_generation = None
        self.update_handle = None
        self._activity = None
        self._map_switch_in_progress = False
        self._lift_states = {}
        self._physical_entry_execution = None
        entry_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.create_subscription(String, "/phase8/lift_payload", self._payload_status, entry_qos)
        self._entry_start_pub = self.create_publisher(
            Bool, "/lift_entry_start", entry_qos)
        self._command_lock = threading.Lock()
        self.callback_group = ReentrantCallbackGroup()

        qos = 10
        self.create_subscription(
            PoseWithCovarianceStamped, ros_topic("amcl_pose", self.ros_namespace),
            self._amcl_callback, qos, callback_group=self.callback_group)
        self.create_subscription(
            Odometry, ros_topic("odom", self.ros_namespace), self._odom_callback, qos,
            callback_group=self.callback_group)
        map_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.create_subscription(
            OccupancyGrid, ros_topic("map", self.ros_namespace), self._map_callback, map_qos,
            callback_group=self.callback_group)
        costmap_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.create_subscription(
            OccupancyGrid, ros_topic("global_costmap/costmap", self.ros_namespace),
            self._global_costmap_callback, costmap_qos,
            callback_group=self.callback_group)
        self.initial_pose_pub = self.create_publisher(
            PoseWithCovarianceStamped, ros_topic("initialpose", self.ros_namespace), qos)
        self.action_client = ActionClient(
            self, NavigateToPose, ros_topic("navigate_to_pose", self.ros_namespace),
            callback_group=self.callback_group)
        self.load_map_client = self.create_client(
            LoadMap, ros_topic("map_server/load_map", self.ros_namespace),
            callback_group=self.callback_group)
        self.navigation_lifecycle_client = self.create_client(
            ManageLifecycleNodes,
            ros_topic("lifecycle_manager_navigation/manage_nodes", self.ros_namespace),
            callback_group=self.callback_group)
        self.clear_global_client = self.create_client(
            ClearEntireCostmap,
            ros_topic("global_costmap/clear_entirely_global_costmap", self.ros_namespace),
            callback_group=self.callback_group)
        self.clear_local_client = self.create_client(
            ClearEntireCostmap,
            ros_topic("local_costmap/clear_entirely_local_costmap", self.ros_namespace),
            callback_group=self.callback_group)
        self.controller_parameters_client = self.create_client(
            SetParameters,
            ros_topic("controller_server/set_parameters", self.ros_namespace),
            callback_group=self.callback_group)
        self.tf_buffer = Buffer()
        tf_qos = QoSProfile(
            depth=100,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )
        static_tf_qos = QoSProfile(
            depth=100,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.create_subscription(
            TFMessage, ros_topic("tf", self.ros_namespace), self._tf_callback, tf_qos,
            callback_group=self.callback_group)
        self.create_subscription(
            TFMessage, ros_topic("tf_static", self.ros_namespace), self._static_tf_callback,
            static_tf_qos, callback_group=self.callback_group)
        self.create_subscription(
            LiftState, "/lift_states", self._lift_state_callback, 10,
            callback_group=self.callback_group)
        self.create_subscription(
            Bool, "/lift_entry_complete", self._physical_entry_callback,
            entry_qos,
            callback_group=self.callback_group)

    def _lift_state_callback(self, message):
        with self._lock:
            self._lift_states[message.lift_name] = message

    @staticmethod
    def _is_physical_lift_entry(destination) -> bool:
        x, y = destination.position[0], destination.position[1]
        return (math.hypot(x - 16.984098, y + 24.221069) < 0.5 or
                math.hypot(x - 16.170208, y + 23.481081) < 0.5)

    def _physical_entry_callback(self, message):
        if not message.data:
            return
        with self._lock:
            execution = self._physical_entry_execution
            self._physical_entry_execution = None
            if execution is None:
                return
            self._active_execution = None
            self._active_target = None
            self._active_command_position = None
            self._activity = None
        execution.finished()

    def _wait_for_lift_door(self, destination, lift) -> bool:
        lift_name = getattr(lift, "name", None) or "Lift2"
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            with self._lock:
                state = self._lift_states.get(lift_name)
            if (state is not None and
                    state.current_floor == destination.map and
                    state.door_state == LiftState.DOOR_OPEN and
                    state.motion_state == LiftState.MOTION_STOPPED):
                return True
            time.sleep(0.1)
        self._issue("lift", f"{lift_name} door did not fully open on {destination.map}")
        return False

    def _payload_status(self, message):
        self._payload_state = json.loads(message.data).get("state")

    def _tf_callback(self, msg: TFMessage) -> None:
        for transform in msg.transforms:
            self.tf_buffer.set_transform(transform, self.get_name())
        try:
            transform = self.tf_buffer.lookup_transform(
                "map", "base_footprint", Time())
        except Exception:
            return
        translation = transform.transform.translation
        with self._lock:
            self.pose = [translation.x, translation.y,
                         yaw_from_quaternion(transform.transform.rotation)]
            self.last_pose_time = time.monotonic()
            self._tf_pose_time = self.last_pose_time
            self.pose_received.set()

    def _static_tf_callback(self, msg: TFMessage) -> None:
        for transform in msg.transforms:
            self.tf_buffer.set_transform_static(transform, self.get_name())

    def _amcl_callback(self, msg: PoseWithCovarianceStamped) -> None:
        with self._lock:
            # AMCL can publish only on a new localization update. Prefer the
            # live map-frame TF once odometry and AMCL have composed it.
            if time.monotonic() - self._tf_pose_time > 1.0:
                p = msg.pose.pose
                self.pose = [p.position.x, p.position.y,
                             yaw_from_quaternion(p.orientation)]
                self.last_pose_time = time.monotonic()
            self.pose_received.set()

    def _odom_callback(self, msg: Odometry) -> None:
        with self._lock:
            self.velocity = [msg.twist.twist.linear.x, msg.twist.twist.angular.z]

    def _map_callback(self, msg: OccupancyGrid) -> None:
        self._map_shape = (msg.info.width, msg.info.height)
        self.map_received.set()

    def _global_costmap_callback(self, msg: OccupancyGrid) -> None:
        if (msg.info.width > 0 and msg.info.height > 0 and
                len(msg.data) == msg.info.width * msg.info.height):
            self.global_costmap_received.set()

    def _cancel_active(self) -> bool:
        with self._lock:
            goal = self._active_goal
        if goal is None:
            return True
        try:
            future = goal.cancel_goal_async()
        except Exception as exc:
            self.get_logger().error(f"Nav2 cancel request failed: {exc}")
            return False
        deadline = time.monotonic() + 5.0
        while not future.done() and time.monotonic() < deadline:
            time.sleep(0.02)
        if not future.done():
            self.get_logger().error("Nav2 cancel request timed out")
            return False
        try:
            response = future.result()
        except Exception as exc:
            self.get_logger().error(f"Nav2 cancel response failed: {exc}")
            return False
        if not response.goals_canceling:
            self.get_logger().error("Nav2 did not acknowledge cancellation of the active goal")
            return False

        result_future = goal.get_result_async()
        deadline = time.monotonic() + 5.0
        while not result_future.done() and time.monotonic() < deadline:
            time.sleep(0.02)
        if not result_future.done():
            self.get_logger().error(
                "Nav2 acknowledged cancellation but returned no terminal goal result")
            return False
        try:
            status = result_future.result().status
        except Exception as exc:
            self.get_logger().error(f"Nav2 canceled-goal result failed: {exc}")
            return False
        if not cancellation_confirmed(len(response.goals_canceling), status):
            self.get_logger().error(f"Nav2 cancellation ended with unexpected status {status}")
            return False
        return True

    def _issue(self, category: str, message: str) -> None:
        self.get_logger().error(f"{category}: {message}")
        if self.update_handle is None:
            return
        try:
            self.update_handle.more().create_issue(
                Tier.Error, category, {"message": message})
            self.update_handle.more().replan()
        except Exception as exc:
            self.get_logger().error(f"Unable to report RMF issue: {exc}")

    def _entry_command_position(self, destination):
        position = list(destination.position)
        # Consume the one-shot exit flag at the outward waypoint. Previously
        # an early return left it armed until the later return-to-cabin goal.
        if self._exit_lift_command and not self._is_physical_lift_entry(destination):
            self._exit_lift_command = False
        if (destination.map == "L1" and
                math.hypot(position[0] - 17.010633,
                           position[1] + 21.787325) < 0.3):
            # The Phase 8 map now preserves the real doorway. Use RMF's
            # waypoint itself: the legacy offset plus Nav2 stopping tolerance
            # could leave the robot outside RMF's path acceptance distance.
            if os.environ.get("PHASE8_MULTILEVEL_SEMANTIC") == "1":
                return position
            return [16.984098, -21.500000, position[2]]
        lift = destination.inside_lift
        if callable(lift):
            lift = lift()
        if lift is None:
            return position
        # Lift2's graph cabin waypoint is offset from the physical cabin
        # model. Entry must target the model center so the lift request gate
        # can verify that the robot is fully inside before motion starts.
        if math.hypot(position[0] - 16.170208,
                      position[1] + 23.481081) < 0.5:
            position[0], position[1] = 16.984098, -24.221069
        with self._lock:
            current = list(self.pose)
        # Lift waypoints are marked inside_lift for both cabin entry and exit.
        # Do not pull an exit goal back into the cabin: an outward destination
        # is farther from the cabin center than the robot's current pose.
        cabin_center = min(
            ((16.984098, -24.221069), (16.170208, -23.481081)),
            key=lambda center: math.hypot(
                position[0] - center[0], position[1] - center[1]))
        target_cabin_distance = math.hypot(
            position[0] - cabin_center[0], position[1] - cabin_center[1])
        current_cabin_distance = math.hypot(
            current[0] - cabin_center[0], current[1] - cabin_center[1])
        if self._exit_lift_command:
            exit_points = {
                # These are outward approach points, not cabin centers. L3
                # uses Lift2, whose cabin is at (16.1702, -23.4811).
                "L1": (17.010633, -21.787325),
                "L3": (16.984098, -21.800000),
            }
            exit_point = exit_points.get(destination.map)
            if exit_point is not None:
                position[0], position[1] = exit_point
            self._exit_lift_command = False
            return position
        if target_cabin_distance >= current_cabin_distance:
            if target_cabin_distance > 0.01:
                position[0] += (position[0] - cabin_center[0]) / target_cabin_distance * 0.4
                position[1] += (position[1] - cabin_center[1]) / target_cabin_distance * 0.4
            return position
        # Entry destinations are cabin-center waypoints. The lift-door
        # collisions are removed from the prepared world, so stopping short
        # of the center leaves the robot straddling the doorway.
        return position

    @staticmethod
    def _is_l3_hallway(destination) -> bool:
        return (
            destination.map == "L3" and
            math.hypot(destination.position[0] - 14.157826,
                       destination.position[1] + 21.651426) < 0.2)

    @staticmethod
    def _is_phase8_l1_lobby(destination) -> bool:
        if destination.map != "L1":
            return False
        spawn_x = float(os.environ.get("INITIAL_X", "15.402"))
        spawn_y = float(os.environ.get("INITIAL_Y", "-31.594"))
        return math.hypot(destination.position[0] - spawn_x,
                          destination.position[1] - spawn_y) < 0.3

    def _hold_at_hallway(self, destination, execution, generation) -> bool:
        if not self._is_l3_hallway(destination):
            return True
        with self._lock:
            if self._hallway_dwell_generation == generation:
                return True
            self._hallway_dwell_generation = generation
        self.get_logger().info(
            "Holding at L3_middle_hallway for 10 seconds before returning")
        time.sleep(10.0)
        with self._lock:
            return (generation == self._generation and
                    execution is self._active_execution)

    def _goal_pose(self, destination) -> NavigateToPose.Goal:
        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = "map"
        # Let TF2 resolve the latest transform; the adapter callback can run
        # after the simulator clock has advanced past the node's cached time.
        goal.pose.header.stamp.sec = 0
        goal.pose.header.stamp.nanosec = 0
        with self._lock:
            position = (self._active_command_position
                        if self._active_target is destination
                        else destination.position)
            current = list(self.pose)
            lift_exit = self._active_lift_exit
            face_l1_return = self._face_l1_return_direction
        goal.pose.pose.position.x = float(position[0])
        goal.pose.pose.position.y = float(position[1])
        yaw = float(destination.position[2])
        lift = destination.inside_lift
        if callable(lift):
            lift = lift()
        # On the L3 -> L1 return, the robot otherwise backs toward its lobby
        # waypoint while still facing north. That points the RGB-D camera away
        # from the red mat after the floor change has cleared semantic memory.
        # Face the actual travel direction so served SAM3 can re-observe the
        # mat before Nav2 reaches it.
        if (face_l1_return and destination.map == "L1" and
                lift is None and not lift_exit):
            dx = float(position[0]) - current[0]
            dy = float(position[1]) - current[1]
            if math.hypot(dx, dy) > 0.25:
                yaw = math.atan2(dy, dx)
                self.get_logger().info(
                    f"Phase 8 L1 return camera heading {yaw:.3f} rad toward "
                    f"[{position[0]:.3f}, {position[1]:.3f}]")
        if lift is not None and not lift_exit:
            # The map/odom pose can jump when RMF replans at a lift. Use the
            # physical Lift2 door direction instead of that stale pose.
            yaw = -math.pi / 2.0
        goal.pose.pose.orientation.z = math.sin(yaw / 2.0)
        goal.pose.pose.orientation.w = math.cos(yaw / 2.0)
        return goal

    def navigate(self, destination, execution) -> None:
        """Send exactly one local Nav2 goal for the current RMF activity."""
        with self._command_lock:
            self.get_logger().info(
                f"RMF navigate callback: map={destination.map} "
                f"pose={list(destination.position)}")
            with self._lock:
                old_target = self._active_target
                old_execution = self._active_execution
                exit_requested = self._exit_lift_command
                new_target = (old_execution is None or old_target is None or
                        old_target.map != destination.map or
                        math.hypot(old_target.position[0] - destination.position[0],
                                   old_target.position[1] - destination.position[1]) > 0.1)
                same_activity = (
                    old_execution is not None and
                    execution.identifier == old_execution.identifier)
                goal_in_flight = (
                    self._active_goal is not None or
                    self._pending_goal_generation is not None)
                if keep_active_goal(
                        same_activity, not new_target, goal_in_flight):
                    self.get_logger().info(
                        "Keeping the active Nav2 goal for a duplicate RMF navigate callback")
                    return

                self._generation += 1
                generation = self._generation
                if new_target:
                    self._navigation_retries = 0
                    self._active_command_position = self._entry_command_position(destination)
                    self._active_lift_exit = exit_requested
                self._active_execution = execution
                self._active_target = destination
                self._activity = execution.identifier
                lift = destination.inside_lift
                if callable(lift):
                    lift = lift()
                if new_target and lift is not None and not exit_requested:
                    cabin = min(
                        ((16.984098, -24.221069), (16.170208, -23.481081)),
                        key=lambda center: math.hypot(
                            destination.position[0] - center[0],
                            destination.position[1] - center[1]))
                    current_distance = math.hypot(
                        self.pose[0] - cabin[0], self.pose[1] - cabin[1])
                    target_distance = math.hypot(
                        destination.position[0] - cabin[0],
                        destination.position[1] - cabin[1])
                    self._active_lift_exit = target_distance >= current_distance

            if old_execution is not None:
                if not self._cancel_active():
                    self._issue("navigation", "preempted Nav2 goal cancellation was not confirmed")
                    return
                with self._lock:
                    self._active_goal = None

            if destination.map != self.current_map:
                self._issue("navigation", f"map changed during navigation: {self.current_map} -> {destination.map}")
                return

            lift = destination.inside_lift
            if callable(lift):
                lift = lift()
            if lift is not None:
                self.get_logger().info(
                    f"Navigating into lift {lift} on {destination.map}; "
                    f"target={self._active_command_position}")
                with self._lock:
                    lift_exit = self._active_lift_exit
                if not lift_exit and self._is_physical_lift_entry(destination):
                    if not self._wait_for_lift_door(destination, lift):
                        return
                    with self._lock:
                        self._physical_entry_execution = execution
                    self._entry_start_pub.publish(Bool(data=True))
                    self.get_logger().info(
                        "Handing physical lift entry to Gazebo pose controller")
                    return
                if not lift_exit and not self._wait_for_lift_door(destination, lift):
                    return

            # Reverse only for the narrow lift-exit maneuver. On floor routes,
            # reverse motion makes the robot's camera face away from obstacles
            # and can back the chassis into the spawn-side wall.
            try:
                with self._lock:
                    reverse_for_lift_exit = self._active_lift_exit
                self._set_allow_reversing(reverse_for_lift_exit)
            except Exception as exc:
                self._issue("navigation", str(exc))
                return

            if not self.action_client.wait_for_server(timeout_sec=10.0):
                self._issue("navigation", "NavigateToPose action server is unavailable")
                return

            with self._lock:
                self._pending_goal_generation = generation
            send_future = self.action_client.send_goal_async(self._goal_pose(destination))

        def goal_response(future) -> None:
            try:
                goal_handle = future.result()
            except Exception as exc:
                self._issue("navigation", f"goal request failed: {exc}")
                with self._lock:
                    if self._pending_goal_generation == generation:
                        self._pending_goal_generation = None
                return
            with self._lock:
                if generation != self._generation:
                    if self._pending_goal_generation == generation:
                        self._pending_goal_generation = None
                    goal_handle.cancel_goal_async()
                    return
                if self._pending_goal_generation == generation:
                    self._pending_goal_generation = None
                if not goal_handle.accepted:
                    self._issue("navigation", "Nav2 rejected the goal")
                    return
                self._active_goal = goal_handle
            result_future = goal_handle.get_result_async()
            result_future.add_done_callback(
                lambda result: self._goal_result(result, generation, destination, execution))

        send_future.add_done_callback(goal_response)

    def _at_destination(self, destination) -> bool:
        lift = destination.inside_lift
        if callable(lift):
            lift = lift()
        inside_lift = lift is not None
        with self._lock:
            target = list(self._active_command_position or destination.position)
        position_tolerance = 0.25
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            with self._lock:
                pose = list(self.pose)
                velocity = list(self.velocity)
                fresh = time.monotonic() - self.last_pose_time < 1.0
            yaw_tolerance = 0.20 if inside_lift else 0.35
            yaw_ok = (angle_error(pose[2], target[2]) <= yaw_tolerance or
                      angle_error(pose[2], target[2] + math.pi) <= yaw_tolerance)
            if (fresh and math.hypot(pose[0] - target[0], pose[1] - target[1]) <= position_tolerance
                    and yaw_ok
                    and abs(velocity[0]) < 0.15 and abs(velocity[1]) < 0.15):
                with self._lock:
                    lift_exit = self._active_lift_exit
                if (lift_exit and
                        math.hypot(pose[0] - 16.984098,
                                   pose[1] + 24.221069) < 1.8):
                    time.sleep(0.1)
                    continue
                return True
            time.sleep(0.05)
        return False

    def _goal_result(self, future, generation, destination, execution) -> None:
        with self._lock:
            if generation != self._generation or execution is not self._active_execution:
                return
        try:
            wrapped = future.result()
            status = wrapped.status
        except Exception as exc:
            self._issue("navigation", f"result retrieval failed: {exc}")
            return
        at_destination = self._at_destination(destination)
        with self._lock:
            lift_exit = self._active_lift_exit
            pose = list(self.pose)
        lift = destination.inside_lift
        if callable(lift):
            lift = lift()
        if (not lift_exit and lift is not None and destination.map == "L3" and
                nav2_success(status) and
                math.hypot(pose[0] - destination.position[0],
                           pose[1] - destination.position[1]) <= 1.3):
            at_destination = True
        if not nav2_success(status) or not at_destination:
            with self._lock:
                same_execution = self._active_execution is execution
                retries = self._navigation_retries
                if same_execution:
                    self._navigation_retries += 1
                    # This result is terminal. A retry must be allowed to
                    # submit a fresh goal instead of being deduplicated as
                    # the still-active goal.
                    self._active_goal = None
            if same_execution and retries < 3:
                self.get_logger().warning(
                    f"Nav2 status {status} at destination; retrying goal "
                    f"({retries + 1}/3)")

                def retry():
                    time.sleep(0.5)
                    with self._lock:
                        if self._active_execution is not execution:
                            return
                    self.navigate(destination, execution)

                threading.Thread(target=retry, daemon=True).start()
                return
            with self._lock:
                self._active_goal = None
            message = (f"Nav2 returned terminal status {status}"
                       if not nav2_success(status)
                       else "Nav2 succeeded but final pose or velocity validation failed")
            self._issue("navigation", message)
            return

        if not self._hold_at_hallway(destination, execution, generation):
            return
        with self._lock:
            self._active_goal = None
            self._active_execution = None
            self._active_command_position = None
            self._active_lift_exit = False
            self._activity = None
        self.get_logger().info(
            f"RMF activity {execution.identifier} finished after Nav2 success and pose validation")
        with self._lock:
            if self._is_phase8_l1_lobby(destination) and not lift_exit:
                self._face_l1_return_direction = False
        execution.finished()

    def stop(self, activity) -> None:
        with self._command_lock:
            with self._lock:
                if self._activity is None or not activity.is_same(self._activity):
                    return
                self._generation += 1
                self._active_execution = None
                self._active_command_position = None
                self._active_lift_exit = False
                self._activity = None
            if not self._cancel_active():
                self._issue("navigation", "Nav2 cancellation was not acknowledged and confirmed")
                return
            with self._lock:
                self._active_goal = None
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                with self._lock:
                    if abs(self.velocity[0]) < 0.03 and abs(self.velocity[1]) < 0.05:
                        self.get_logger().info(
                            "RMF stop confirmed: Nav2 cancellation terminal and measured velocity is zero")
                        return
                time.sleep(0.05)
            self._issue("navigation", "stop requested but measured velocity did not reach zero")

    def _publish_initial_pose(self, destination) -> None:
        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = "map"
        msg.header.stamp.sec = 0
        msg.header.stamp.nanosec = 0
        msg.pose.pose.position.x = float(destination.position[0])
        msg.pose.pose.position.y = float(destination.position[1])
        msg.pose.pose.orientation.z = math.sin(float(destination.position[2]) / 2.0)
        msg.pose.pose.orientation.w = math.cos(float(destination.position[2]) / 2.0)
        msg.pose.covariance[0] = 0.04
        msg.pose.covariance[7] = 0.04
        msg.pose.covariance[35] = 0.02
        self.initial_pose_pub.publish(msg)

    def _refresh_current_pose(self) -> None:
        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = "map"
        msg.header.stamp = self.get_clock().now().to_msg()
        with self._lock:
            x, y, yaw = self.pose
        msg.pose.pose.position.x = x
        msg.pose.pose.position.y = y
        msg.pose.pose.orientation.z = math.sin(yaw / 2.0)
        msg.pose.pose.orientation.w = math.cos(yaw / 2.0)
        msg.pose.covariance[0] = 0.04
        msg.pose.covariance[7] = 0.04
        msg.pose.covariance[35] = 0.02
        self.initial_pose_pub.publish(msg)

    def _wait_future(self, future, timeout: float):
        deadline = time.monotonic() + timeout
        while not future.done() and time.monotonic() < deadline:
            time.sleep(0.02)
        return future.result() if future.done() else None

    def _set_allow_reversing(self, enabled: bool) -> None:
        if not self.controller_parameters_client.wait_for_service(timeout_sec=3.0):
            raise RuntimeError("Nav2 controller parameter service is unavailable")
        request = SetParameters.Request()
        request.parameters = [Parameter(
            "FollowPath.allow_reversing", Parameter.Type.BOOL, enabled
        ).to_parameter_msg()]
        response = self._wait_future(
            self.controller_parameters_client.call_async(request), 3.0)
        if (response is None or not response.results or
                not response.results[0].successful):
            reason = (response.results[0].reason if response and response.results
                      else "parameter update timed out")
            raise RuntimeError(f"unable to set Nav2 reverse mode: {reason}")

    def localize(self, destination, execution) -> None:
        """Load a destination floor and only finish after fresh AMCL data."""
        self.get_logger().info(f"RMF localize callback: map={destination.map}")
        with self._lock:
            came_from_l3 = self.current_map == "L3"
            self._generation += 1
            self._active_execution = None
            self._active_lift_exit = False
            self._activity = execution.identifier
            self._map_switch_in_progress = True
        self._cancel_active()
        try:
            with self._lock:
                self.velocity = [0.0, 0.0]
            if not self.load_map_client.wait_for_service(timeout_sec=5.0):
                raise RuntimeError("map_server/load_map is unavailable")
            self.map_received.clear()
            self.global_costmap_received.clear()
            self.pose_received.clear()
            request = LoadMap.Request()
            request.map_url = self._map_url(destination.map)
            response = self._wait_future(self.load_map_client.call_async(request), 20.0)
            if response is None or response.result != LoadMap.Response.RESULT_SUCCESS:
                raise RuntimeError(f"failed to load map for {destination.map}")
            if not self.map_received.wait(timeout=5.0):
                raise RuntimeError("new occupancy map was not observed")
            if not self.navigation_lifecycle_client.wait_for_service(timeout_sec=5.0):
                raise RuntimeError("navigation lifecycle manager is unavailable")
            reset = ManageLifecycleNodes.Request()
            reset.command = ManageLifecycleNodes.Request.RESET
            response = self._wait_future(
                self.navigation_lifecycle_client.call_async(reset), 30.0)
            if response is None or not response.success:
                raise RuntimeError("failed to reset Nav2 navigation lifecycle")
            startup = ManageLifecycleNodes.Request()
            startup.command = ManageLifecycleNodes.Request.STARTUP
            response = self._wait_future(
                self.navigation_lifecycle_client.call_async(startup), 30.0)
            if response is None or not response.success:
                raise RuntimeError("failed to restart Nav2 navigation lifecycle")
            if not self.global_costmap_received.wait(timeout=20.0):
                raise RuntimeError("global costmap did not switch to the new map")
            self._publish_initial_pose(destination)
            for client in (self.clear_global_client, self.clear_local_client):
                if client.wait_for_service(timeout_sec=3.0):
                    self._wait_future(client.call_async(ClearEntireCostmap.Request()), 5.0)
            if not self.pose_received.wait(timeout=15.0):
                raise RuntimeError("fresh AMCL pose was not observed")
            tf = self.tf_buffer.lookup_transform("map", "base_footprint", rclpy.time.Time())
            if tf is None:
                raise RuntimeError("map -> base_footprint transform is unavailable")
            with self._lock:
                self.current_map = destination.map
                if (os.environ.get("PHASE8_MULTILEVEL_SEMANTIC") == "1" and
                        came_from_l3 and destination.map == "L1"):
                    self._face_l1_return_direction = True
                self._map_switch_in_progress = False
                self._activity = None
                self._exit_lift_command = True
            # Let RMF observe the new floor and pose before the lift phase
            # releases its localization execution and replans the exit.
            self.get_logger().info(
                f"Settling RMF state on {destination.map} before lift exit")
            time.sleep(5.0)
            if os.environ.get("PHASE8_MULTILEVEL_SEMANTIC") == "1":
                deadline = time.monotonic() + 15.0
                while self._payload_state != "detached" and time.monotonic() < deadline:
                    time.sleep(0.1)
                if self._payload_state != "detached":
                    raise RuntimeError("lift payload did not detach before Nav2 exit")
            execution.finished()
        except Exception as exc:
            with self._lock:
                self._map_switch_in_progress = True
            self._issue("localization", str(exc))

    @staticmethod
    def _map_url(level: str) -> str:
        template = os.environ.get("HOTEL_MAP_TEMPLATE", "/opt/ros2-demo/maps/hotel_{level}.yaml")
        return template.format(level=level)

    def update_state(self) -> None:
        if self.update_handle is None:
            return
        with self._lock:
            state = rmf_easy.RobotState(self.current_map, list(self.pose), 1.0)
            activity = self._activity
        self.update_handle.update(state, activity)


def start(args) -> None:
    rclpy.init()
    rmf_adapter.init_rclcpp()
    node = LocalRobotBackend(args.robot_name, args.initial_map,
                             [args.initial_x, args.initial_y, args.initial_yaw],
                             args.ros_namespace)
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    # Publish RMF pose updates at 4 Hz so fleet state can track faster Nav2
    # motion without accumulating a full second of position lag.
    state_timer = node.create_timer(0.25, node.update_state)
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()
    reassign_timer = None
    def run_in_thread(function, *callback_args):
        threading.Thread(
            target=function, args=callback_args, daemon=True).start()

    def execute_action(category, description, execution):
        node.get_logger().info(
            f"RMF action callback: category={category} description={description}")
        run_in_thread(lambda: execution.finished())

    callbacks = rmf_easy.RobotCallbacks(
        lambda destination, execution: run_in_thread(
            node.navigate, destination, execution),
        lambda activity: run_in_thread(node.stop, activity),
        execute_action,
    )
    callbacks.localize = lambda destination, execution: run_in_thread(
        node.localize, destination, execution)
    node.callbacks = callbacks
    try:
        deadline = time.monotonic() + 180.0
        last_readiness_log = 0.0
        while time.monotonic() < deadline:
            with node._lock:
                pose_ready = (node.pose_received.is_set() and
                              time.monotonic() - node.last_pose_time < 2.0)
                pose = list(node.pose)
                map_shape = node._map_shape
                pose_age = (time.monotonic() - node.last_pose_time
                            if node.pose_received.is_set() else None)
            ready = (pose_ready and node.map_received.is_set() and
                     node.action_client.server_is_ready())
            if ready:
                break
            now = time.monotonic()
            if now - last_readiness_log >= 15.0:
                node.get_logger().info(
                    "Waiting for Nav2 readiness: "
                    f"fresh_pose={pose_ready} pose_age={pose_age} "
                    f"map={node.map_received.is_set()} shape={map_shape} "
                    f"global_costmap={node.global_costmap_received.is_set()} "
                    f"action_server={node.action_client.server_is_ready()}")
                last_readiness_log = now
            time.sleep(0.25)
        else:
            raise RuntimeError(
                "Nav2 is not ready for RMF admission: need fresh map-frame TF pose, "
                "map, and NavigateToPose server")

        if (math.hypot(pose[0] - args.initial_x, pose[1] - args.initial_y) > 0.75 or
                angle_error(pose[2], args.initial_yaw) > 0.75):
            raise RuntimeError(
                f"AMCL pose {pose} does not match the staged RMF start "
                f"{[args.initial_x, args.initial_y, args.initial_yaw]}")
        node.get_logger().info(
            "RMF backend ready: fresh map-frame TF pose, map, and Nav2 action server")

        fleet_config = rmf_easy.FleetConfiguration.from_config_files(
            args.fleet_config, args.nav_graph)
        if not fleet_config:
            raise RuntimeError("failed to parse RMF fleet or navigation graph")
        adapter = Adapter.make(f"{fleet_config.fleet_name}_local_adapter")
        if adapter is None:
            raise RuntimeError("failed to create RMF adapter; is rmf_traffic_schedule running?")
        adapter.node.use_sim_time()
        adapter.start()
        fleet_handle = adapter.add_easy_fleet(fleet_config)
        if fleet_handle is None:
            raise RuntimeError("failed to create EasyFullControl fleet")
        robot_config = fleet_config.get_known_robot_configuration(args.robot_name)
        if robot_config is None:
            raise RuntimeError(f"robot {args.robot_name} is not in {args.fleet_config}")
        initial_state = rmf_easy.RobotState(args.initial_map, pose, 1.0)
        node.update_handle = fleet_handle.add_robot(
            args.robot_name, initial_state, robot_config, callbacks)
        if node.update_handle is None:
            raise RuntimeError("failed to add robot to EasyFullControl fleet")
        fleet_handle.more().reassign_dispatched_tasks()
        reassign_timer = node.create_timer(
            30.0, fleet_handle.more().reassign_dispatched_tasks)
        node.get_logger().info(
            f"RMF robot registered: fleet={fleet_config.fleet_name} "
            f"robot={args.robot_name} map={args.initial_map} pose={pose}")
        while spin_thread.is_alive():
            time.sleep(0.5)
    finally:
        if reassign_timer is not None:
            node.destroy_timer(reassign_timer)
        node.destroy_timer(state_timer)
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fleet-config", default="/opt/ros2-demo/rmf/fleet_config.yaml")
    parser.add_argument("--nav-graph", default="/opt/ros2-demo/rmf/nav_graph.yaml")
    parser.add_argument("--robot-name", default="robot_1")
    parser.add_argument("--initial-map", default="L1")
    parser.add_argument("--initial-x", type=float, default=15.402)
    parser.add_argument("--initial-y", type=float, default=-31.594)
    parser.add_argument("--initial-yaw", type=float, default=0.0)
    parser.add_argument("--ros-namespace", default=None,
                         help="Nav2 topic namespace; empty string for root-level topics")
    start(parser.parse_args())


if __name__ == "__main__":
    main()
