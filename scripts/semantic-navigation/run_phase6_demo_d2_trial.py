#!/usr/bin/env python3
"""Run one isolated Phase 6D D2 Nav2 trial with a continuously asserted speed cap."""
import argparse
import json
import math
import time

import rclpy
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped, Twist
from nav2_msgs.action import (
    ComputePathThroughPoses, ComputePathToPose, NavigateThroughPoses, NavigateToPose,
)
from nav2_msgs.msg import CollisionMonitorState, CostmapUpdate, SpeedLimit
from nav_msgs.msg import Odometry, Path
from rclpy.action import ActionClient
from rclpy.parameter_client import AsyncParameterClient
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from rosgraph_msgs.msg import Clock

from demo_target_geometry import (
    REQUIRED_HULL_CLEARANCE,
    mat_bounds,
    polyline_enters_clearance_envelope,
    polyline_intersects_mat,
    polyline_min_hull_clearance,
)


SEMANTIC_TARGET_COST = 254
EXPECTED_INFLATION_RADIUS = 0.60
EXPECTED_ROBOT_RADIUS = 0.246
EXPECTED_LOOKAHEAD = 0.5
EXPECTED_MIN_LOOKAHEAD = 0.25


class Trial:
    def __init__(self, args):
        self.args = args
        self.node = rclpy.create_node("phase6_d2_trial_runner")
        self.via = args.via
        self.navigate_type = NavigateThroughPoses if self.via else NavigateToPose
        self.compute_type = ComputePathThroughPoses if self.via else ComputePathToPose
        self.navigate_endpoint = (
            "/navigate_through_poses" if self.via else "/navigate_to_pose")
        self.compute_endpoint = (
            "/compute_path_through_poses" if self.via else "/compute_path_to_pose")
        self.action = ActionClient(self.node, self.navigate_type, self.navigate_endpoint)
        self.compute_action = ActionClient(self.node, self.compute_type,
                                           self.compute_endpoint)
        self.speed_pub = self.node.create_publisher(SpeedLimit, "/speed_limit", 10)
        self.node.create_subscription(Odometry, "/odom", self.odom_cb, 20)
        self.node.create_subscription(Odometry, "/demo/ground_truth", self.truth_cb, 20)
        self.node.create_subscription(Path, "/received_global_plan", self.path_cb, 5)
        self.node.create_subscription(Twist, "/cmd_vel", self.cmd_cb, 20)
        self.node.create_subscription(CollisionMonitorState, "/collision_monitor_state",
                                      self.collision_cb, 20)
        self.semantic_counts = {"global": None, "local": None}
        self.semantic_enabled_confirmed = False
        self.node.create_subscription(CostmapUpdate,
            "/global_costmap/semantic_layer_raw_updates",
            lambda msg: self.costmap_cb("global", msg), 20)
        self.node.create_subscription(CostmapUpdate,
            "/local_costmap/semantic_layer_raw_updates",
            lambda msg: self.costmap_cb("local", msg), 20)
        clock_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
        )
        self.node.create_subscription(Clock, "/clock", self.clock_cb, clock_qos)
        self.costmap_params = {
            "global": AsyncParameterClient(self.node, "/global_costmap/global_costmap"),
            "local": AsyncParameterClient(self.node, "/local_costmap/local_costmap"),
        }
        self.controller_params = AsyncParameterClient(self.node, "/controller_server")
        self.smoother_params = AsyncParameterClient(self.node, "/velocity_smoother")
        self.node.create_timer(0.1, self.publish_speed_cap)
        self.latest_odom = None
        self.odom_received = None
        self.latest_truth = None
        self.truth_received = None
        self.truth_liveness_breach = False
        self.odom_liveness_breach = False
        self.pose_alignment_breach = False
        self.max_truth_speed = 0.0
        self.max_truth_angular = 0.0
        self.max_odom_truth_position_error = 0.0
        self.max_odom_truth_yaw_error = 0.0
        self.latest_plan = None
        self.trajectory = []
        self.collision_events = []
        self.max_odom_speed = 0.0
        self.max_cmd_speed = 0.0
        self.max_angular_speed = 0.0
        self.first_sim_ns = None
        self.last_sim_ns = None
        self.cap_messages = 0
        self.clearance_monitor_triggered = False
        self.minimum_hull_clearance_m = math.inf
        self.latest_cmd_angular = 0.0

    def publish_speed_cap(self):
        msg = SpeedLimit()
        msg.header.stamp = self.node.get_clock().now().to_msg()
        msg.percentage = False
        msg.speed_limit = self.args.speed_limit
        self.speed_pub.publish(msg)
        self.cap_messages += 1

    def odom_cb(self, msg):
        p, q = msg.pose.pose.position, msg.pose.pose.orientation
        if not all(math.isfinite(value) for value in (
                p.x, p.y, q.x, q.y, q.z, q.w,
                msg.twist.twist.linear.x, msg.twist.twist.linear.y,
                msg.twist.twist.angular.z)):
            return
        if not 0.99 <= q.x*q.x + q.y*q.y + q.z*q.z + q.w*q.w <= 1.01:
            return
        if self.latest_odom is not None:
            previous = self.latest_odom.header.stamp
            stamp = msg.header.stamp
            if (stamp.sec, stamp.nanosec) <= (previous.sec, previous.nanosec):
                return
        self.latest_odom = msg
        self.odom_received = time.monotonic()
        speed = math.hypot(msg.twist.twist.linear.x, msg.twist.twist.linear.y)
        self.max_odom_speed = max(self.max_odom_speed, speed)
        self.max_angular_speed = max(self.max_angular_speed,
                                      abs(msg.twist.twist.angular.z))

    def truth_cb(self, msg):
        if msg.header.frame_id != "map":
            return
        stamp = msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec
        if self.latest_truth is not None:
            previous = self.latest_truth.header.stamp
            if stamp <= previous.sec * 1_000_000_000 + previous.nanosec:
                return  # Frozen/replayed truth must not renew freshness.
        p, q = msg.pose.pose.position, msg.pose.pose.orientation
        values = (p.x, p.y, p.z, q.x, q.y, q.z, q.w,
                  msg.twist.twist.linear.x, msg.twist.twist.linear.y,
                  msg.twist.twist.angular.z)
        if not all(math.isfinite(value) for value in values):
            return
        if not 0.99 <= q.x*q.x + q.y*q.y + q.z*q.z + q.w*q.w <= 1.01:
            return
        self.latest_truth = msg
        self.truth_received = time.monotonic()
        self.max_truth_speed = max(self.max_truth_speed,
            math.hypot(msg.twist.twist.linear.x, msg.twist.twist.linear.y))
        self.max_truth_angular = max(self.max_truth_angular, abs(msg.twist.twist.angular.z))

    def pose_alignment(self):
        p = self.latest_odom.pose.pose.position
        truth = self.latest_truth.pose.pose.position
        distance = math.hypot(self.args.map_origin_x + p.x - truth.x,
                              self.args.map_origin_y + p.y - truth.y)
        odom_q = self.latest_odom.pose.pose.orientation
        truth_q = self.latest_truth.pose.pose.orientation

        def yaw(q):
            return math.atan2(2 * (q.w * q.z + q.x * q.y),
                              1 - 2 * (q.y * q.y + q.z * q.z))

        delta = yaw(odom_q) - yaw(truth_q)
        angle = abs(math.atan2(math.sin(delta), math.cos(delta)))
        self.max_odom_truth_position_error = max(self.max_odom_truth_position_error, distance)
        self.max_odom_truth_yaw_error = max(self.max_odom_truth_yaw_error, angle)
        return distance, angle

    def verify_start_pose(self):
        """Recheck after planning/settling too, not just on first receipt."""
        now = time.monotonic()
        if (self.truth_received is None or now - self.truth_received > 0.5 or
                self.odom_received is None or now - self.odom_received > 0.5):
            raise RuntimeError("fresh wheel odometry and Gazebo body pose required")
        p = self.latest_truth.pose.pose.position
        distance, angle = self.pose_alignment()
        if distance > 0.10 or angle > 0.08:
            raise RuntimeError(f"wheel odometry disagrees with Gazebo pose at start: "
                               f"position {distance:.3f} m, yaw {angle:.3f} rad")
        if math.hypot(p.x - self.args.expected_start_x,
                      p.y - self.args.expected_start_y) > self.args.start_tolerance:
            raise RuntimeError(f"unexpected start pose map=({p.x:.3f},{p.y:.3f})")
        for msg in (self.latest_odom, self.latest_truth):
            if (math.hypot(msg.twist.twist.linear.x, msg.twist.twist.linear.y) > 0.01 or
                    abs(msg.twist.twist.angular.z) > 0.01):
                raise RuntimeError("robot is moving at trial start")
        return p.x, p.y, distance, angle

    def path_cb(self, msg):
        if msg.poses:
            self.latest_plan = msg

    def costmap_cb(self, name, msg):
        self.semantic_counts[name] = sum(value == SEMANTIC_TARGET_COST for value in msg.data)

    def cmd_cb(self, msg):
        self.max_cmd_speed = max(self.max_cmd_speed,
                                  math.hypot(msg.linear.x, msg.linear.y))
        self.latest_cmd_angular = msg.angular.z

    def truth_yaw(self):
        q = self.latest_truth.pose.pose.orientation
        return math.atan2(2 * (q.w * q.z + q.x * q.y),
                          1 - 2 * (q.y * q.y + q.z * q.z))

    def steering_summary(self):
        """Describe actual steering, not camera movement; not a safety gate."""
        samples = self.trajectory
        deltas = [math.atan2(math.sin(b["yaw_rad"] - a["yaw_rad"]),
                             math.cos(b["yaw_rad"] - a["yaw_rad"]))
                  for a, b in zip(samples, samples[1:])]
        absolute = sum(abs(delta) for delta in deltas)
        net = sum(deltas)
        # Ignore near-zero steering noise when counting direction changes.
        directions = [1 if p["w_radps"] > 0 else -1
                      for p in samples if abs(p["w_radps"]) >= 0.05]
        return {
            "angular_deadband_radps": 0.05,
            "turn_direction_changes": sum(a != b for a, b in
                                           zip(directions, directions[1:])),
            "absolute_yaw_travel_rad": round(absolute, 4),
            "net_yaw_change_rad": round(net, 4),
            "extra_yaw_travel_rad": round(max(0.0, absolute - abs(net)), 4),
        }

    def collision_cb(self, msg):
        if msg.action_type != CollisionMonitorState.DO_NOTHING:
            self.collision_events.append({
                "wall_time": time.time(), "action_type": msg.action_type,
                "polygon_name": msg.polygon_name,
            })

    def clock_cb(self, msg):
        stamp = msg.clock.sec * 1_000_000_000 + msg.clock.nanosec
        if self.first_sim_ns is None:
            self.first_sim_ns = stamp
        self.last_sim_ns = stamp

    def wait_until(self, pred, timeout, label):
        end = time.monotonic() + timeout
        while not pred() and time.monotonic() < end:
            rclpy.spin_once(self.node, timeout_sec=0.05)
        if not pred():
            raise TimeoutError(label)

    def verify_profile_parameters(self):
        expected = {
            "global": {
                "semantic_layer.enabled": self.args.semantic_arm == "on",
                "semantic_layer.target_cost": SEMANTIC_TARGET_COST,
                "inflation_layer.enabled": True,
                "inflation_layer.inflation_radius": EXPECTED_INFLATION_RADIUS,
                "robot_radius": EXPECTED_ROBOT_RADIUS,
            },
            "local": {
                "semantic_layer.enabled": False,
                "inflation_layer.enabled": True,
                "inflation_layer.inflation_radius": EXPECTED_INFLATION_RADIUS,
                "robot_radius": EXPECTED_ROBOT_RADIUS,
            },
        }
        for name, client in self.costmap_params.items():
            if not client.wait_for_services(timeout_sec=5.0):
                raise TimeoutError(f"{name} costmap parameter service unavailable")
            names = list(expected[name])
            future = client.get_parameters(names)
            rclpy.spin_until_future_complete(self.node, future, timeout_sec=5.0)
            result = future.result()
            if result is None or len(result.values) != len(names):
                raise RuntimeError(f"{name} costmap profile parameters unavailable")
            for parameter, value in zip(names, result.values):
                expected_value = expected[name][parameter]
                actual = (value.bool_value if isinstance(expected_value, bool) else
                          value.integer_value if isinstance(expected_value, int) else
                          value.double_value)
                if isinstance(expected_value, float):
                    matches = abs(actual - expected_value) <= 1e-6
                else:
                    matches = actual == expected_value
                if not matches:
                    raise RuntimeError(
                        f"{name} profile mismatch for {parameter}: "
                        f"expected {expected_value}, got {actual}")

        if not self.controller_params.wait_for_services(timeout_sec=5.0):
            raise TimeoutError("controller parameter service unavailable")
        controller_expected = {
            "FollowPath.lookahead_dist": EXPECTED_LOOKAHEAD,
            "FollowPath.min_lookahead_dist": EXPECTED_MIN_LOOKAHEAD,
            "FollowPath.desired_linear_vel": 0.12,
            "FollowPath.regulated_linear_scaling_min_speed": 0.06,
            "FollowPath.min_approach_linear_velocity": 0.04,
            "FollowPath.use_rotate_to_heading": False,
            "FollowPath.stateful": False,
        }
        names = list(controller_expected)
        future = self.controller_params.get_parameters(names)
        rclpy.spin_until_future_complete(self.node, future, timeout_sec=5.0)
        result = future.result()
        if result is None or len(result.values) != len(names):
            raise RuntimeError("controller clearance parameters unavailable")
        for name, value in zip(names, result.values):
            expected_value = controller_expected[name]
            actual = (value.bool_value if isinstance(expected_value, bool)
                      else value.double_value)
            if value.type == 0 or abs(actual - expected_value) > 1e-6:
                raise RuntimeError(
                    f"controller profile mismatch for {name}: "
                    f"expected {expected_value}, got {actual}")

        if not self.smoother_params.wait_for_services(timeout_sec=5.0):
            raise TimeoutError("velocity smoother parameter service unavailable")
        smoother_expected = {
            "max_velocity": [0.12, 0.0, 0.45],
            "min_velocity": [-0.12, 0.0, -0.45],
            "max_accel": [0.3, 0.0, 0.4],
            "max_decel": [-0.5, 0.0, -0.6],
        }
        names = list(smoother_expected)
        future = self.smoother_params.get_parameters(names)
        rclpy.spin_until_future_complete(self.node, future, timeout_sec=5.0)
        result = future.result()
        if result is None or len(result.values) != len(names):
            raise RuntimeError("velocity smoother parameters unavailable")
        for name, value in zip(names, result.values):
            actual = list(value.double_array_value)
            expected_value = smoother_expected[name]
            if len(actual) != 3 or any(abs(a - b) > 1e-6
                                       for a, b in zip(actual, expected_value)):
                raise RuntimeError(f"smoother profile mismatch for {name}: "
                                   f"expected {expected_value}, got {actual}")

    def verify_semantic_arm(self):
        self.verify_profile_parameters()
        if self.args.semantic_arm == "on":
            self.wait_until(lambda: self.semantic_counts["global"] is not None and
                            self.semantic_counts["global"] > 0,
                            15.0, "fresh lethal semantic costs did not reach global costmap")
        self.semantic_enabled_confirmed = True

    def goal_poses(self):
        """Use identical ordered waypoints for preflight and navigation."""
        poses = []
        for x, y in [*self.via, (self.args.goal_x, self.args.goal_y)]:
            pose = PoseStamped()
            pose.header.frame_id = "map"
            pose.header.stamp = self.node.get_clock().now().to_msg()
            pose.pose.position.x = x
            pose.pose.position.y = y
            pose.pose.orientation.w = 1.0
            poses.append(pose)
        # Match the requested finish heading to the final approach leg. The
        # opposite-side route approaches southbound, unlike the eastbound
        # bypass-only finish. Forcing east yaw there can cause a goal orbit.
        poses[-1].pose.orientation.z = math.sin(self.args.goal_yaw / 2)
        poses[-1].pose.orientation.w = math.cos(self.args.goal_yaw / 2)
        return poses

    def compute_preflight_path(self):
        if not self.compute_action.wait_for_server(timeout_sec=10):
            raise TimeoutError(f"{self.compute_endpoint} action unavailable")
        goal = self.compute_type.Goal()
        if self.via:
            goal.goals = self.goal_poses()
        else:
            goal.goal = self.goal_poses()[0]
        goal.use_start = False
        goal.planner_id = "GridBased"
        sent = self.compute_action.send_goal_async(goal)
        rclpy.spin_until_future_complete(self.node, sent, timeout_sec=10)
        handle = sent.result()
        if handle is None or not handle.accepted:
            raise RuntimeError("Nav2 rejected the D2 path preflight")
        result_future = handle.get_result_async()
        rclpy.spin_until_future_complete(self.node, result_future, timeout_sec=30)
        if result_future.result() is None:
            raise TimeoutError("D2 path preflight timed out")
        result = result_future.result().result
        points = [[p.pose.position.x, p.pose.position.y] for p in result.path.poses]
        xmin, xmax, ymin, ymax = mat_bounds()
        mat_samples = sum(xmin <= x <= xmax and ymin <= y <= ymax
                          for x, y in points)
        if result.error_code != 0 or not points:
            raise RuntimeError(f"D2 path preflight failed: {result.error_msg}")
        intersects_mat = polyline_intersects_mat(points)
        minimum_clearance = polyline_min_hull_clearance(points)
        enters_clearance_envelope = polyline_enters_clearance_envelope(points)
        if self.args.semantic_arm == "off" and not intersects_mat:
            raise RuntimeError("semantic-off preflight does not cross the staged mat")
        if self.args.semantic_arm == "on" and enters_clearance_envelope:
            raise RuntimeError(
                "semantic-on preflight violates the 0.10 m circumscribed-hull "
                "clearance envelope; no goal was dispatched")
        return {"planner_error_code": result.error_code,
                "planning_time_s": result.planning_time.sec +
                    result.planning_time.nanosec / 1e9,
                "mat_centerline_samples": mat_samples,
                "mat_centerline_intersection": intersects_mat,
                "minimum_hull_clearance_m": round(minimum_clearance, 4),
                "required_hull_clearance_m": REQUIRED_HULL_CLEARANCE,
                "clearance_envelope_intersection": enters_clearance_envelope,
                "path_map_xy": [[round(x, 4), round(y, 4)] for x, y in points]}

    def run(self):
        self.verify_semantic_arm()
        self.wait_until(lambda: self.latest_odom is not None, 20,
                         "odometry not received")
        self.wait_until(lambda: self.latest_truth is not None and
                        time.monotonic() - self.truth_received < 0.5, 20,
                        "fresh independent Gazebo body pose not received")
        self.verify_start_pose()
        if not self.action.wait_for_server(timeout_sec=15):
            raise TimeoutError(f"{self.navigate_endpoint} action unavailable")

        path_preflight = self.compute_preflight_path()
        map_x, map_y, distance, angle = self.verify_start_pose()
        if self.args.preflight_only:
            preflight_result = {
                "trial": self.args.trial,
                "semantic_arm": self.args.semantic_arm,
                "semantic_layer_enabled": self.args.semantic_arm == "on",
                "semantic_arm_state_confirmed": self.semantic_enabled_confirmed,
                "semantic_layer_cost254_samples": self.semantic_counts,
                "path_preflight": path_preflight,
                "motion_dispatched": False,
                "via_map": self.via,
                "goal_map": [self.args.goal_x, self.args.goal_y],
                "goal_yaw_rad": self.args.goal_yaw,
                "navigation_action": self.navigate_endpoint,
                "clearance_pose_source": "gazebo_model_pose",
                "odom_truth_position_error_m": round(distance, 4),
                "odom_truth_yaw_error_rad": round(angle, 4),
            }
            if self.args.summary_only:
                preflight_result["path_preflight"].pop("path_map_xy", None)
            print(json.dumps(preflight_result, separators=(",", ":")), flush=True)
            return

        # Assert the speed cap for a settling interval before dispatch.
        for _ in range(10):
            rclpy.spin_once(self.node, timeout_sec=0.1)
        map_x, map_y, distance, angle = self.verify_start_pose()
        goal = self.navigate_type.Goal()
        if self.via:
            goal.poses = self.goal_poses()
        else:
            goal.pose = self.goal_poses()[0]
        sent_wall = time.time()
        last_sample_xy = (map_x, map_y)
        send_future = self.action.send_goal_async(goal)
        rclpy.spin_until_future_complete(self.node, send_future, timeout_sec=15)
        handle = send_future.result()
        if handle is None or not handle.accepted:
            raise RuntimeError("Nav2 rejected the D2 goal")
        result_future = handle.get_result_async()
        deadline = time.monotonic() + self.args.timeout
        last_sample = 0.0
        cap_breach = False
        while not result_future.done() and time.monotonic() < deadline:
            rclpy.spin_once(self.node, timeout_sec=0.05)
            now = time.monotonic()
            if self.truth_received is None or now - self.truth_received > 0.5:
                self.truth_liveness_breach = True
                handle.cancel_goal_async()
                break
            if self.odom_received is None or now - self.odom_received > 0.5:
                self.odom_liveness_breach = True
                handle.cancel_goal_async()
                break
            distance, angle = self.pose_alignment()
            if distance > 0.15 or angle > 0.15:
                self.pose_alignment_breach = True
                handle.cancel_goal_async()
                break
            if self.latest_truth and now - last_sample >= 0.05:
                pos = self.latest_truth.pose.pose.position
                point = (pos.x, pos.y)
                segment = [last_sample_xy, point]
                segment_clearance = polyline_min_hull_clearance(segment)
                self.minimum_hull_clearance_m = min(
                    self.minimum_hull_clearance_m, segment_clearance)
                self.trajectory.append({
                    "t_wall": round(time.time() - sent_wall, 3),
                    "x_map": round(point[0], 4),
                    "y_map": round(point[1], 4),
                    "hull_clearance_m": round(segment_clearance, 4),
                    "yaw_rad": self.truth_yaw(),
                    "w_radps": self.latest_truth.twist.twist.angular.z,
                    "wheel_w_radps": self.latest_odom.twist.twist.angular.z,
                    "cmd_w_radps": self.latest_cmd_angular,
                    "v_mps": round(math.hypot(self.latest_truth.twist.twist.linear.x,
                                                self.latest_truth.twist.twist.linear.y), 4),
                })
                if (self.args.semantic_arm == "on" and
                        polyline_enters_clearance_envelope(segment)):
                    self.clearance_monitor_triggered = True
                    handle.cancel_goal_async()
                    break
                last_sample_xy = point
                last_sample = now
            if max(self.max_odom_speed, self.max_truth_speed) > self.args.speed_limit + self.args.speed_tolerance:
                cap_breach = True
                handle.cancel_goal_async()
                break
        if (not result_future.done() and not cap_breach and
                not self.clearance_monitor_triggered and
                not self.truth_liveness_breach and not self.odom_liveness_breach and
                not self.pose_alignment_breach):
            handle.cancel_goal_async()
        if not result_future.done():
            wait_end = time.monotonic() + 10
            while not result_future.done() and time.monotonic() < wait_end:
                rclpy.spin_once(self.node, timeout_sec=0.05)

        # Include the terminal Gazebo body pose even if it arrived inside the
        # normal 50 ms trajectory-sampling interval.
        final = self.latest_truth
        if final:
            fp = final.pose.pose.position
            final_xy = (fp.x, fp.y)
            if math.dist(last_sample_xy, final_xy) > 1e-6:
                segment = [last_sample_xy, final_xy]
                segment_clearance = polyline_min_hull_clearance(segment)
                self.minimum_hull_clearance_m = min(
                    self.minimum_hull_clearance_m, segment_clearance)
                self.trajectory.append({
                    "t_wall": round(time.time() - sent_wall, 3),
                    "x_map": round(final_xy[0], 4),
                    "y_map": round(final_xy[1], 4),
                    "hull_clearance_m": round(segment_clearance, 4),
                    "yaw_rad": self.truth_yaw(),
                    "w_radps": self.latest_truth.twist.twist.angular.z,
                    "wheel_w_radps": self.latest_odom.twist.twist.angular.z,
                    "cmd_w_radps": self.latest_cmd_angular,
                    "v_mps": round(math.hypot(final.twist.twist.linear.x,
                                                final.twist.twist.linear.y), 4),
                })
                if (self.args.semantic_arm == "on" and
                        polyline_enters_clearance_envelope(segment)):
                    self.clearance_monitor_triggered = True

        status = result_future.result().status if result_future.done() else None
        final_pose = None
        if final:
            fp = final.pose.pose.position
            final_pose = [round(fp.x, 4), round(fp.y, 4)]
        plan_points = []
        if self.latest_plan:
            plan_points = [[round(q.pose.position.x, 4), round(q.pose.position.y, 4)]
                           for q in self.latest_plan.poses]
        result = {
            "trial": self.args.trial,
            "semantic_arm": self.args.semantic_arm,
            "semantic_cells_cost254": self.semantic_counts,
            "semantic_arm_state_confirmed": self.semantic_enabled_confirmed,
            "semantic_layer_enabled": self.args.semantic_arm == "on",
            "path_preflight": path_preflight,
            "goal_map": [self.args.goal_x, self.args.goal_y],
            "goal_yaw_rad": self.args.goal_yaw,
            "via_map": self.via,
            "navigation_action": self.navigate_endpoint,
            "action_status": status,
            "succeeded": status == GoalStatus.STATUS_SUCCEEDED,
            "cap_breach": cap_breach,
            "speed_limit_mps": self.args.speed_limit,
            "max_odom_speed_mps": round(self.max_odom_speed, 4),
            "max_truth_speed_mps": round(self.max_truth_speed, 4),
            "clearance_pose_source": "gazebo_model_pose",
            "truth_liveness_breach": self.truth_liveness_breach,
            "odom_liveness_breach": self.odom_liveness_breach,
            "pose_alignment_breach": self.pose_alignment_breach,
            "max_odom_truth_position_error_m": round(self.max_odom_truth_position_error, 4),
            "max_odom_truth_yaw_error_rad": round(self.max_odom_truth_yaw_error, 4),
            "max_cmd_speed_mps": round(self.max_cmd_speed, 4),
            "max_angular_speed_radps": round(self.max_truth_angular, 4),
            "max_wheel_angular_speed_radps": round(self.max_angular_speed, 4),
            "collision_monitor_events": self.collision_events,
            "minimum_hull_clearance_m": (
                round(self.minimum_hull_clearance_m, 4)
                if math.isfinite(self.minimum_hull_clearance_m) else None),
            "clearance_monitor_triggered": self.clearance_monitor_triggered,
            "required_hull_clearance_m": REQUIRED_HULL_CLEARANCE,
            "mat_hull_overlap_detected": self.minimum_hull_clearance_m < 0.0,
            "sim_duration_s": (round((self.last_sim_ns - self.first_sim_ns) / 1e9, 3)
                               if self.last_sim_ns is not None and self.first_sim_ns is not None
                               else None),
            "wall_duration_s": round(time.time() - sent_wall, 3),
            "final_map_pose": final_pose,
            "speed_cap_messages": self.cap_messages,
            "steering_metrics": self.steering_summary(),
            "path_map_xy": plan_points,
            "trajectory_map_xyv": self.trajectory,
        }
        if self.args.summary_only:
            result["path_preflight"].pop("path_map_xy", None)
            result.pop("path_map_xy", None)
            result.pop("trajectory_map_xyv", None)
        print(json.dumps(result, separators=(",", ":")), flush=True)
        if self.truth_liveness_breach or self.odom_liveness_breach or self.pose_alignment_breach:
            raise RuntimeError("independent body pose became stale or disagreed with wheel odometry")
        if cap_breach:
            raise RuntimeError("measured odometry exceeded the D2 speed cap")
        if self.clearance_monitor_triggered:
            raise RuntimeError(
                "semantic-on trajectory entered the 0.10 m hull-clearance envelope; "
                "the goal was canceled")
        if status != GoalStatus.STATUS_SUCCEEDED:
            raise RuntimeError(f"Nav2 goal did not succeed (status={status})")
        if max(self.max_odom_speed, self.max_truth_speed) > self.args.speed_limit + self.args.speed_tolerance:
            raise RuntimeError("D2 speed cap exceeded")
        if self.collision_events:
            raise RuntimeError("Collision Monitor intervention occurred; hold D2 pair")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", required=True)
    parser.add_argument("--semantic-arm", choices=("on", "off"), required=True)
    parser.add_argument("--expected-start-x", type=float, required=True)
    parser.add_argument("--expected-start-y", type=float, required=True)
    parser.add_argument("--goal-x", type=float, required=True)
    parser.add_argument("--goal-y", type=float, required=True)
    parser.add_argument("--goal-yaw", type=float, default=0.0,
                        help="final map-frame heading in radians; default east. "
                             "Use -1.57079632679 for a southbound final leg")
    parser.add_argument("--via", type=float, nargs=2, action="append", default=[],
                        metavar=("X", "Y"),
                        help="optional ordered approach waypoint; repeat as needed. "
                             "The full waypoint path and live trajectory retain "
                             "the same clearance checks")
    parser.add_argument("--map-origin-x", type=float, default=15.402)
    parser.add_argument("--map-origin-y", type=float, default=-31.594)
    parser.add_argument("--start-tolerance", type=float, default=0.25)
    parser.add_argument("--speed-limit", type=float, default=0.12)
    parser.add_argument("--speed-tolerance", type=float, default=0.005)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--preflight-only", action="store_true",
                        help="validate arm state and route without sending a goal")
    parser.add_argument("--summary-only", action="store_true",
                        help="omit point-by-point paths and trajectories from output")
    args = parser.parse_args()
    if not 0 < args.speed_limit <= 0.15:
        parser.error("D2 speed limit must be in (0, 0.15] m/s")
    if not math.isfinite(args.goal_yaw):
        parser.error("goal yaw must be finite")
    rclpy.init()
    trial = Trial(args)
    try:
        trial.run()
    finally:
        trial.node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
