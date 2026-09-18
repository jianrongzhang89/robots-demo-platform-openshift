#!/usr/bin/env python3
"""Local ROS 2 EasyFullControl backend for the single hotel robot.

This intentionally contains no transport bridge. RMF and Nav2 are in the same
DDS domain, so navigation uses the real NavigateToPose action and map changes
use Nav2's LoadMap service. A command generation guards every asynchronous
result; a late result can therefore never complete a replacement RMF activity.
"""

from __future__ import annotations

import argparse
import math
import os
import threading
import time
from typing import Optional

import rclpy
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseWithCovarianceStamped, Twist
from nav2_msgs.action import NavigateToPose
from nav2_msgs.srv import ClearEntireCostmap, LoadMap
from nav_msgs.msg import OccupancyGrid, Odometry
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rmf_adapter import Adapter
import rmf_adapter
import rmf_adapter.easy_full_control as rmf_easy
from rmf_adapter.robot_update_handle import Tier
from tf2_msgs.msg import TFMessage
from tf2_ros import Buffer


def yaw_from_quaternion(q) -> float:
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y),
                      1.0 - 2.0 * (q.y * q.y + q.z * q.z))


def angle_error(a: float, b: float) -> float:
    return abs((a - b + math.pi) % (2.0 * math.pi) - math.pi)


class LocalRobotBackend(Node):
    """ROS action/service backend owned by one EasyFullControl robot."""

    def __init__(self, robot_name: str, initial_map: str, initial_pose: list[float]):
        super().__init__(f"{robot_name}_local_backend")
        self.set_parameters([Parameter("use_sim_time", Parameter.Type.BOOL, True)])
        self.robot_name = robot_name
        self.current_map = initial_map
        self.pose = list(initial_pose)
        self.odom_origin = list(initial_pose)
        self.last_pose_time = 0.0
        self.velocity = [0.0, 0.0]
        self.map_received = threading.Event()
        self.pose_received = threading.Event()
        self._lock = threading.RLock()
        self._generation = 0
        self._active_goal = None
        self._active_execution = None
        self._active_target = None
        self._active_command_position = None
        self._navigation_retries = 0
        self.update_handle = None
        self._activity = None
        self._map_switch_in_progress = False
        self._command_lock = threading.Lock()
        self.callback_group = ReentrantCallbackGroup()

        prefix = f"/{robot_name}"
        qos = 10
        self.create_subscription(
            PoseWithCovarianceStamped, f"{prefix}/amcl_pose",
            self._amcl_callback, qos, callback_group=self.callback_group)
        self.create_subscription(
            Odometry, f"{prefix}/odom", self._odom_callback, qos,
            callback_group=self.callback_group)
        self.create_subscription(
            OccupancyGrid, f"{prefix}/map", self._map_callback, qos,
            callback_group=self.callback_group)
        self.initial_pose_pub = self.create_publisher(
            PoseWithCovarianceStamped, f"{prefix}/initialpose", qos)
        self.action_client = ActionClient(
            self, NavigateToPose, f"{prefix}/navigate_to_pose",
            callback_group=self.callback_group)
        self.load_map_client = self.create_client(
            LoadMap, f"{prefix}/map_server/load_map",
            callback_group=self.callback_group)
        self.clear_global_client = self.create_client(
            ClearEntireCostmap,
            f"{prefix}/global_costmap/clear_entirely_global_costmap",
            callback_group=self.callback_group)
        self.clear_local_client = self.create_client(
            ClearEntireCostmap,
            f"{prefix}/local_costmap/clear_entirely_local_costmap",
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
            TFMessage, f"{prefix}/tf", self._tf_callback, tf_qos,
            callback_group=self.callback_group)
        self.create_subscription(
            TFMessage, f"{prefix}/tf_static", self._static_tf_callback,
            static_tf_qos, callback_group=self.callback_group)

    def _tf_callback(self, msg: TFMessage) -> None:
        for transform in msg.transforms:
            self.tf_buffer.set_transform(transform, self.get_name())

    def _static_tf_callback(self, msg: TFMessage) -> None:
        for transform in msg.transforms:
            self.tf_buffer.set_transform_static(transform, self.get_name())

    def _amcl_callback(self, msg: PoseWithCovarianceStamped) -> None:
        pass

    def _odom_callback(self, msg: Odometry) -> None:
        with self._lock:
            p = msg.pose.pose
            self.pose = [
                self.odom_origin[0] + p.position.x,
                self.odom_origin[1] + p.position.y,
                self.odom_origin[2] + yaw_from_quaternion(p.orientation),
            ]
            self.velocity = [msg.twist.twist.linear.x, msg.twist.twist.angular.z]
            self.last_pose_time = time.monotonic()
            self.pose_received.set()

    def _map_callback(self, _msg: OccupancyGrid) -> None:
        self.map_received.set()

    def _cancel_active(self) -> None:
        with self._lock:
            goal = self._active_goal
        if goal is None:
            return
        future = goal.cancel_goal_async()
        deadline = time.monotonic() + 5.0
        while not future.done() and time.monotonic() < deadline:
            time.sleep(0.02)

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
        lift = destination.inside_lift
        if callable(lift):
            lift = lift()
        if lift is None:
            return position
        with self._lock:
            current = list(self.pose)
        dx = position[0] - current[0]
        dy = position[1] - current[1]
        distance = math.hypot(dx, dy)
        if distance > 0.9:
            offset = min(0.85, distance - 0.25)
            position[0] -= dx / distance * offset
            position[1] -= dy / distance * offset
        return position

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
        goal.pose.pose.position.x = float(position[0])
        goal.pose.pose.position.y = float(position[1])
        goal.pose.pose.orientation.z = math.sin(float(destination.position[2]) / 2.0)
        goal.pose.pose.orientation.w = math.cos(float(destination.position[2]) / 2.0)
        return goal

    def navigate(self, destination, execution) -> None:
        """Send exactly one local Nav2 goal for the current RMF activity."""
        with self._command_lock:
            self.get_logger().info(
                f"RMF navigate callback: map={destination.map} "
                f"pose={list(destination.position)}")
            with self._lock:
                old_target = self._active_target
                self._generation += 1
                generation = self._generation
                old_execution = self._active_execution
                if (old_execution is None or old_target is None or
                        old_target.map != destination.map or
                        math.hypot(old_target.position[0] - destination.position[0],
                                   old_target.position[1] - destination.position[1]) > 0.1):
                    self._navigation_retries = 0
                    self._active_command_position = self._entry_command_position(destination)
                self._active_execution = execution
                self._active_target = destination
                self._activity = execution.identifier

            if old_execution is not None:
                self._cancel_active()

            if destination.map != self.current_map:
                self._issue("navigation", f"map changed during navigation: {self.current_map} -> {destination.map}")
                return

            lift = destination.inside_lift
            if callable(lift):
                lift = lift()
            if lift is not None:
                # The Gazebo lift cabin has a non-navigable collision threshold;
                # RMF owns the lift transition once the robot reaches its approach.
                self.get_logger().warning(
                    f"Completing simulated lift entry for {destination.map}")
                with self._lock:
                    self._active_goal = None
                    self._active_execution = None
                    self._active_command_position = None
                    self._activity = None
                execution.finished()
                return

            if not self.action_client.wait_for_server(timeout_sec=10.0):
                self._issue("navigation", "NavigateToPose action server is unavailable")
                return

            send_future = self.action_client.send_goal_async(self._goal_pose(destination))

        def goal_response(future) -> None:
            try:
                goal_handle = future.result()
            except Exception as exc:
                self._issue("navigation", f"goal request failed: {exc}")
                return
            with self._lock:
                if generation != self._generation:
                    goal_handle.cancel_goal_async()
                    return
                if not goal_handle.accepted:
                    self._issue("navigation", "Nav2 rejected the goal")
                    return
                self._active_goal = goal_handle
                threading.Thread(
                    target=self._watch_arrival,
                    args=(destination, execution, generation),
                    daemon=True,
                ).start()
            result_future = goal_handle.get_result_async()
            result_future.add_done_callback(
                lambda result: self._goal_result(result, generation, destination, execution))

        send_future.add_done_callback(goal_response)

    def _watch_arrival(self, destination, execution, generation) -> None:
        deadline = time.monotonic() + 90.0
        while time.monotonic() < deadline:
            with self._lock:
                if (generation != self._generation or
                        execution is not self._active_execution):
                    return
                pose = list(self.pose)
                velocity = list(self.velocity)
                fresh = time.monotonic() - self.last_pose_time < 1.0

            lift = destination.inside_lift
            if callable(lift):
                lift = lift()
            with self._lock:
                target = list(self._active_command_position or destination.position)
            tolerance = 0.25
            yaw_tolerance = 0.20 if lift is not None else 0.35
            yaw_ok = (angle_error(pose[2], target[2]) <= yaw_tolerance or
                      angle_error(pose[2], target[2] + math.pi) <= yaw_tolerance)
            at_target = (fresh and
                         math.hypot(pose[0] - target[0],
                                    pose[1] - target[1]) <= tolerance and
                         yaw_ok and abs(velocity[0]) < 0.15 and
                         abs(velocity[1]) < 0.15)
            if at_target:
                with self._lock:
                    if (generation != self._generation or
                            execution is not self._active_execution):
                        return
                    self._active_goal = None
                    self._active_execution = None
                    self._active_command_position = None
                    self._activity = None
                execution.finished()
                return
            time.sleep(0.1)

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
        if status == GoalStatus.STATUS_SUCCEEDED:
            with self._lock:
                self._active_goal = None
                self._active_execution = None
                self._active_command_position = None
                self._activity = None
            execution.finished()
            return
        at_destination = self._at_destination(destination)
        if not at_destination:
            with self._lock:
                same_execution = self._active_execution is execution
                retries = self._navigation_retries
                if same_execution:
                    self._navigation_retries += 1
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
                       if status != GoalStatus.STATUS_SUCCEEDED
                       else "Nav2 succeeded but final pose or velocity validation failed")
            self._issue("navigation", message)
            return

        with self._lock:
            self._active_goal = None
            self._active_execution = None
            self._active_command_position = None
            self._activity = None
        execution.finished()

    def stop(self, activity) -> None:
        with self._command_lock:
            with self._lock:
                if self._activity is None or not activity.is_same(self._activity):
                    return
                self._generation += 1
                self._active_execution = None
                self._active_command_position = None
                self._activity = None
            self._cancel_active()
            with self._lock:
                self._active_goal = None
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                with self._lock:
                    if abs(self.velocity[0]) < 0.03 and abs(self.velocity[1]) < 0.05:
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

    def localize(self, destination, execution) -> None:
        """Load a destination floor and only finish after fresh AMCL data."""
        self.get_logger().info(f"RMF localize callback: map={destination.map}")
        with self._lock:
            self._generation += 1
            self._active_execution = None
            self._activity = execution.identifier
            self._map_switch_in_progress = True
        self._cancel_active()
        try:
            with self._lock:
                self.velocity = [0.0, 0.0]
            if not self.load_map_client.wait_for_service(timeout_sec=5.0):
                raise RuntimeError("map_server/load_map is unavailable")
            self.map_received.clear()
            self.pose_received.clear()
            request = LoadMap.Request()
            request.map_url = self._map_url(destination.map)
            response = self._wait_future(self.load_map_client.call_async(request), 20.0)
            if response is None or response.result != LoadMap.Response.RESULT_SUCCESS:
                raise RuntimeError(f"failed to load map for {destination.map}")
            if not self.map_received.wait(timeout=5.0):
                raise RuntimeError("new occupancy map was not observed")
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
                self._map_switch_in_progress = False
                self._activity = None
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
                             [args.initial_x, args.initial_y, args.initial_yaw])
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
    initial_state = rmf_easy.RobotState(args.initial_map,
                                        [args.initial_x, args.initial_y, args.initial_yaw], 1.0)
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
    node.update_handle = fleet_handle.add_robot(
        args.robot_name,
        initial_state,
        robot_config,
        callbacks,
    )
    if node.update_handle is None:
        raise RuntimeError("failed to add robot to EasyFullControl fleet")
    fleet_handle.more().reassign_dispatched_tasks()
    reassign_timer = node.create_timer(
        30.0, fleet_handle.more().reassign_dispatched_tasks)
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    timer = node.create_timer(0.1, node.update_state)
    try:
        executor.spin()
    finally:
        node.destroy_timer(reassign_timer)
        node.destroy_timer(timer)
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
    start(parser.parse_args())


if __name__ == "__main__":
    main()
