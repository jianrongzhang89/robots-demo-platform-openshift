#!/usr/bin/env python3
"""No-motion semantic preflight or monitored RMF multi-floor trial."""

from __future__ import annotations

import argparse
import json
import math
import time
import uuid
from pathlib import Path

import rclpy
import yaml
from action_msgs.msg import GoalStatus, GoalStatusArray
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
from nav2_msgs.action import ComputePathToPose
from nav_msgs.msg import OccupancyGrid, Odometry, Path as NavPath
from nav2_msgs.srv import GetCost, GetCostmap
from rclpy.clock import Clock as RosClock, ClockType
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import (DurabilityPolicy, HistoryPolicy, QoSProfile,
                        ReliabilityPolicy)
from rmf_fleet_msgs.msg import FleetState
from rmf_lift_msgs.msg import LiftState
from rmf_task_msgs.msg import ApiRequest, ApiResponse, DispatchStates
from sensor_msgs.msg import PointCloud2
from std_msgs.msg import String
from rosgraph_msgs.msg import Clock


TASK_QOS = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE,
                      durability=DurabilityPolicy.TRANSIENT_LOCAL,
                      history=HistoryPolicy.KEEP_LAST)
GRID_QOS = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                      durability=DurabilityPolicy.TRANSIENT_LOCAL)
MAT_CENTER = (15.1384977554, -30.1803625369)
MAT_SIZE = (1.0, 1.4)  # across route, along route
MAT_YAW = 1.755291
ROBOT_RADIUS = 0.246
REQUIRED_CLEARANCE = 0.20


def mat_local(x: float, y: float) -> tuple[float, float]:
    dx, dy = x - MAT_CENTER[0], y - MAT_CENTER[1]
    c, s = math.cos(MAT_YAW), math.sin(MAT_YAW)
    return c * dx + s * dy, -s * dx + c * dy


def mat_world(local_x: float, local_y: float) -> tuple[float, float]:
    c, s = math.cos(MAT_YAW), math.sin(MAT_YAW)
    return (MAT_CENTER[0] + c * local_x - s * local_y,
            MAT_CENTER[1] + s * local_x + c * local_y)


def mat_aabb() -> tuple[float, float, float, float]:
    hx, hy = MAT_SIZE[0] / 2.0, MAT_SIZE[1] / 2.0
    c, s = abs(math.cos(MAT_YAW)), abs(math.sin(MAT_YAW))
    ex, ey = c * hx + s * hy, s * hx + c * hy
    return (MAT_CENTER[0] - ex, MAT_CENTER[0] + ex,
            MAT_CENTER[1] - ey, MAT_CENTER[1] + ey)


def mat_contains(x: float, y: float) -> bool:
    lx, ly = mat_local(x, y)
    return abs(lx) <= MAT_SIZE[0] / 2.0 and abs(ly) <= MAT_SIZE[1] / 2.0


def point_clearance(x: float, y: float) -> float:
    lx, ly = mat_local(x, y)
    dx = max(abs(lx) - MAT_SIZE[0] / 2.0, 0.0)
    dy = max(abs(ly) - MAT_SIZE[1] / 2.0, 0.0)
    return math.hypot(dx, dy) - ROBOT_RADIUS


def grid_cost(grid: OccupancyGrid, x: float, y: float) -> int | None:
    info = grid.info
    ix = int((x - info.origin.position.x) / info.resolution)
    iy = int((y - info.origin.position.y) / info.resolution)
    if ix < 0 or iy < 0 or ix >= info.width or iy >= info.height:
        return None
    return int(grid.data[iy * info.width + ix]) % 256


class Phase8Multilevel(Node):
    def __init__(self, args):
        super().__init__("phase8_multilevel_trial")
        self.set_parameters([Parameter("use_sim_time", Parameter.Type.BOOL, True)])
        self.args = args
        self.graph = yaml.safe_load(Path(args.nav_graph).read_text())
        self.vertices = self.graph["levels"]["L1"]["vertices"]
        self.spawn = next(v for v in self.vertices if (v[2] or {}).get("name") == "phase8_spawn")
        lift2_cabin = next(i for i, v in enumerate(self.vertices)
                           if (v[2] or {}).get("lift_cabin") == "Lift2")
        lift2_approach = next(
            b if a == lift2_cabin else a
            for a, b, _ in self.graph["levels"]["L1"]["lanes"]
            if a == lift2_cabin or b == lift2_cabin)
        self.l1_lift_approach = self.vertices[lift2_approach]
        self.clock_ns = 0
        self.pose = None
        self.odom = None
        self.costmap = None
        self.map_size = None
        self.semantic_points = 0
        self.plan_records = []
        self.trajectory = []
        self.physics_history = []
        self.payload_history = []
        self.snapshot_future = None
        self.cost_history = []
        self.floor_history = []
        self.lift_history = []
        self.dispatch_rows = []
        self.task_id = None
        self.request_id = None
        self.api_response = None
        self.saw_task = False
        self.fleet_idle = False
        self.current_level = None
        self.nav_active = False
        self.nav_statuses = {}
        self.create_subscription(String, "/phase8/lift_payload", self._on_payload, TASK_QOS)
        self.create_subscription(String, "/phase8/physics", self._on_physics, 5)
        self.api_pub = self.create_publisher(ApiRequest, "/task_api_requests", TASK_QOS)
        self.create_subscription(ApiResponse, "/task_api_responses", self._on_api, TASK_QOS)
        self.create_subscription(DispatchStates, "/dispatch_states", self._on_dispatch, 10)
        self.create_subscription(FleetState, "/fleet_states", self._on_fleet, 10)
        self.create_subscription(LiftState, "/lift_states", self._on_lift, 10)
        # rclpy.Node owns an internal `_clock` attribute, so keep this callback
        # name distinct to avoid binding the Node clock object as a callback.
        self.create_subscription(Clock, "/clock", self._on_clock, 10)
        self.create_subscription(PoseWithCovarianceStamped, "/robot_1/amcl_pose",
                                 self._on_pose, TASK_QOS)
        self.create_subscription(Odometry, "/robot_1/odom", self._on_odom, 10)
        self.create_subscription(OccupancyGrid, "/robot_1/map", self._on_map, GRID_QOS)
        self.create_subscription(NavPath, "/robot_1/plan", self._on_plan, 10)
        self.create_subscription(GoalStatusArray,
                                 "/robot_1/navigate_to_pose/_action/status",
                                 self._on_nav_status, 10)
        self.plan_client = ActionClient(self, ComputePathToPose,
                                        "/robot_1/compute_path_to_pose")
        self.cost_client = self.create_client(
            GetCost, "/robot_1/global_costmap/get_cost_global_costmap")

        self.snapshot_client = self.create_client(
            GetCostmap, "/robot_1/global_costmap/get_costmap")
        self.create_timer(1.0, self.request_snapshot,
                          clock=RosClock(clock_type=ClockType.STEADY_TIME))

    def request_snapshot(self):
        if self.snapshot_future is not None and not self.snapshot_future.done():
            return
        if not self.snapshot_client.service_is_ready():
            return
        level = self.current_level
        self.snapshot_future = self.snapshot_client.call_async(GetCostmap.Request())
        def received(future):
            if future.exception() is None and level == self.current_level:
                self._on_costmap(future.result().map)
        self.snapshot_future.add_done_callback(received)

    def mat_cost_samples(self):
        """Sample the live master costmap through Nav2's query service.

        The OccupancyGrid costmap topic is latched and may retain the initial
        empty grid while incremental semantic updates are published. GetCost
        queries the current master costmap and therefore reflects those updates.
        """
        values = []
        for local_y in (-0.35, 0.0, 0.35):
            for local_x in (-0.25, 0.0, 0.25):
                x, y = mat_world(local_x, local_y)
                request = GetCost.Request()
                request.use_footprint = False
                request.x, request.y, request.theta = x, y, 0.0
                future = self.cost_client.call_async(request)
                rclpy.spin_until_future_complete(self, future, timeout_sec=2.0)
                if not future.done() or future.result() is None:
                    continue
                values.append({"x": x, "y": y,
                               "cost": int(round(future.result().cost))})
        return values

    def _on_payload(self, msg):
        row = json.loads(msg.data)
        if not self.payload_history or row["state"] != self.payload_history[-1]["state"]:
            self.payload_history.append(row)

    def _on_physics(self, msg):
        row = json.loads(msg.data)
        row["level"] = self.current_level
        row["nav_active"] = self.nav_active
        row["hull_clearance_m"] = point_clearance(row["x"], row["y"])
        if self.trajectory and time.time() - self.trajectory[-1]["wall_time"] < 2.0:
            fleet = self.trajectory[-1]
            row["fleet_position_error_m"] = math.hypot(row["x"] - fleet["x"], row["y"] - fleet["y"])
        self.physics_history.append(row)

    def _on_api(self, msg):
        if msg.request_id == self.request_id:
            self.api_response = json.loads(msg.json_msg)
            state = self.api_response.get("state") or {}
            self.task_id = (state.get("booking") or {}).get("id")

    def _on_dispatch(self, msg):
        for row in list(msg.active) + list(msg.finished):
            if row.task_id == self.task_id:
                self.dispatch_rows.append({
                    "task_id": row.task_id,
                    "status": int(row.status),
                    "assigned": bool(row.assignment.is_assigned),
                    "errors": list(row.errors),
                    "wall_time": time.time(),
                })

    def _on_fleet(self, msg):
        robot = next((r for r in msg.robots if msg.name == "hotel_nav2" and
                      r.name == "robot_1"), None)
        if robot is None:
            return
        level = robot.location.level_name
        if level and level != self.current_level:
            self.floor_history.append({"level": level, "wall_time": time.time(),
                                       "x": float(robot.location.x),
                                       "y": float(robot.location.y)})
            self.current_level = level
        self.trajectory.append({"wall_time": time.time(), "level": level,
                                "x": float(robot.location.x), "y": float(robot.location.y),
                                "hull_clearance_m": point_clearance(robot.location.x, robot.location.y)})
        if self.task_id and robot.task_id == self.task_id:
            self.saw_task = True
        self.fleet_idle = bool(self.saw_task and not robot.task_id)

    def _on_lift(self, msg):
        self.lift_history.append({
            "lift": msg.lift_name, "floor": msg.current_floor,
            "door_state": int(msg.door_state), "motion_state": int(msg.motion_state),
            "wall_time": time.time(),
        })

    def _on_odom(self, msg):
        self.odom = msg

    def _on_clock(self, msg):
        self.clock_ns = msg.clock.sec * 1_000_000_000 + msg.clock.nanosec

    def _on_pose(self, msg):
        p = msg.pose.pose
        self.pose = [float(p.position.x), float(p.position.y)]

    def _on_map(self, msg):
        self.map_size = [int(msg.info.width), int(msg.info.height)]

    def _on_costmap(self, msg):
        self.costmap = msg
        info = msg.metadata
        lethal = sum(1 for value in msg.data if int(value) % 256 == 254)
        mat_lethal = 0
        xmin, xmax, ymin, ymax = mat_aabb()
        for y in range(info.size_y):
            wy = info.origin.position.y + (y + 0.5) * info.resolution
            if not ymin <= wy <= ymax:
                continue
            for x in range(info.size_x):
                wx = info.origin.position.x + (x + 0.5) * info.resolution
                if (xmin <= wx <= xmax and mat_contains(wx, wy) and
                        int(msg.data[y * info.size_x + x]) % 256 == 254):
                    mat_lethal += 1
        self.cost_history.append({"wall_time": time.time(), "level": self.current_level,
                                  "lethal_cells": lethal, "mat_lethal_cells": mat_lethal})

    def _on_points(self, msg):
        self.semantic_points = int(msg.width)

    def _on_plan(self, msg):
        speed = 0.0
        if self.odom:
            t = self.odom.twist.twist.linear
            speed = math.hypot(t.x, t.y)
        clearances = [point_clearance(p.pose.position.x, p.pose.position.y)
                      for p in msg.poses]
        self.plan_records.append({
            "wall_time": time.time(), "level": self.current_level,
            "moving_speed_mps": speed, "frame_id": msg.header.frame_id,
            "mat_minimum_hull_clearance_m": min(clearances) if clearances else None,
            "semantic_lethal_cells": (self.cost_history[-1]["lethal_cells"]
                                       if self.cost_history else 0),
            "semantic_mat_cells": (self.cost_history[-1]["mat_lethal_cells"]
                                   if self.cost_history else 0),
            "path_xy": [[p.pose.position.x, p.pose.position.y] for p in msg.poses],
        })

    def _on_nav_status(self, msg):
        active = {}
        for row in msg.status_list:
            active[bytes(row.goal_info.goal_id.uuid).hex()] = int(row.status)
        self.nav_statuses.update(active)
        self.nav_active = any(v in (GoalStatus.STATUS_ACCEPTED,
                                    GoalStatus.STATUS_EXECUTING,
                                    GoalStatus.STATUS_CANCELING)
                              for v in active.values())

    def wait_for(self, predicate, seconds: float, description: str):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.1)
            if predicate():
                return
        raise TimeoutError(description)

    def served_status(self):
        try:
            status = json.loads(Path("/phase8-status/semantic-status.json").read_text())
        except (OSError, json.JSONDecodeError):
            return None
        return status

    def preflight(self):
        self.wait_for(lambda: self.physics_history, 30.0, "Gazebo physical pose is unavailable")
        self.wait_for(lambda: self.payload_history and self.payload_history[-1]["state"] == "detached",
                      30.0, "lift payload joint was not released at startup")
        self.wait_for(lambda: self.map_size is not None and self.pose is not None,
                      120.0, "L1 map/localization did not become available")
        self.wait_for(lambda: self.costmap is not None and int((self.served_status() or {}).get("emitted_results", 0)) > 0,
                      120.0, "served SAM3 points or global costmap did not become available")
        if not self.cost_client.wait_for_service(timeout_sec=20.0):
            raise TimeoutError("Nav2 live master cost query is unavailable")
        mat_samples = []
        last_cost_sample = 0.0

        def semantic_preflight_ready():
            nonlocal last_cost_sample
            status = self.served_status() or {}
            if status.get("ready") and time.monotonic() - last_cost_sample >= 1.0:
                mat_samples[:] = self.mat_cost_samples()
                last_cost_sample = time.monotonic()
            lethal_samples = sum(sample["cost"] == 254
                                 for sample in mat_samples)
            return (bool(status.get("ready")) and
                    int(status.get("emitted_results", 0)) > 0 and
                    lethal_samples >= 4)

        self.wait_for(semantic_preflight_ready, 120.0,
                      "served SAM3 did not remain fresh long enough to mark the red mat lethal")
        mat_cells = sum(sample["cost"] == 254 for sample in mat_samples)
        if not self.plan_client.wait_for_server(timeout_sec=10.0):
            raise TimeoutError("Nav2 ComputePathToPose action is unavailable")
        goal = ComputePathToPose.Goal()
        goal.goal = PoseStamped()
        goal.goal.header.frame_id = "map"
        goal.goal.pose.position.x = float(self.l1_lift_approach[0])
        goal.goal.pose.position.y = float(self.l1_lift_approach[1])
        goal.goal.pose.orientation.w = 1.0
        goal.planner_id = "GridBased"
        goal.use_start = False
        send = self.plan_client.send_goal_async(goal)
        rclpy.spin_until_future_complete(self, send, timeout_sec=10.0)
        if not send.done() or not send.result().accepted:
            raise RuntimeError("Nav2 rejected the no-motion semantic path query")
        result_future = send.result().get_result_async()
        rclpy.spin_until_future_complete(self, result_future, timeout_sec=60.0)
        if not result_future.done() or result_future.result().result.path.poses == []:
            raise RuntimeError("Nav2 did not return an L1 path to the lift corridor")
        path = result_future.result().result.path
        clearance = min(point_clearance(p.pose.position.x, p.pose.position.y)
                        for p in path.poses)
        if clearance < REQUIRED_CLEARANCE:
            raise RuntimeError(f"preflight path mat clearance {clearance:.3f} m is below {REQUIRED_CLEARANCE:.2f} m")
        return {"status": "PASS", "motion_dispatched": False,
                "level": "L1", "served_model": "OpenShift AI SAM3",
                "mat_cost_samples": mat_samples,
                "mat_cost254_cells": mat_cells,
                "path_poses": len(path.poses),
                "planned_mat_hull_clearance_m": round(clearance, 4),
                "planned_goal": "L1 lift corridor",
                "mat_geometry": {"center": MAT_CENTER, "size": MAT_SIZE,
                                 "yaw_rad": MAT_YAW},
                "robot_pose": self.pose,
                "adapter_emitted_results": self.served_status()["emitted_results"]}

    def patrol(self):
        self.wait_for(lambda: self.clock_ns > 0 and self.current_level == "L1",
                      60.0, "RMF clock/fleet state did not report the robot on L1")
        body = {"type": "dispatch_task_request", "request": {
            "unix_millis_request_time": self.clock_ns // 1_000_000,
            "unix_millis_earliest_start_time": self.clock_ns // 1_000_000,
            "category": "patrol",
            # Start by heading directly from spawn to Lift2, then return to
            # the same named L1 spawn vertex to finish the demonstration.
            "description": {"places": ["L3_middle_hallway", "phase8_spawn"],
                            "rounds": 1},
            "fleet_name": "hotel_nav2",
            "requester": "phase8-multilevel-demo",
        }}
        self.wait_for(lambda: self.api_pub.get_subscription_count() > 0,
                      30.0, "RMF dispatcher is not subscribed")
        self.request_id = str(uuid.uuid4())
        request = ApiRequest()
        request.request_id = self.request_id
        request.json_msg = json.dumps(body, separators=(",", ":"))
        self.api_pub.publish(request)
        self.wait_for(lambda: self.api_response is not None, 30.0,
                      "RMF did not return a correlated patrol response")
        if not self.api_response.get("success") or not self.task_id:
            raise RuntimeError(f"RMF rejected multi-level patrol: {self.api_response}")
        print(json.dumps({"event": "dispatched", "task_id": self.task_id}), flush=True)
        deadline = time.monotonic() + self.args.timeout
        report_at = 0.0
        while time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.1)
            if time.monotonic() >= report_at:
                print(json.dumps({"event": "progress", "level": self.current_level,
                      "pose": self.trajectory[-1] if self.trajectory else None,
                      "plans": len(self.plan_records), "nav_active": self.nav_active}), flush=True)
                report_at = time.monotonic() + 15
            if self.physics_history:
                physical = self.physics_history[-1]
                if time.time() - physical["wall_time"] > 3.0 or physical["z"] < -0.2:
                    raise RuntimeError("Gazebo physical pose stale or robot below floor")
                if physical.get("fleet_position_error_m", 0) > 0.75:
                    raise RuntimeError("RMF localization diverged from physical robot by over 0.75 m")
                if (math.hypot(physical["x"]-16.984098, physical["y"]+24.221069) < .8 and
                        abs(physical["z"]-physical.get("lift2_z", physical["z"])) > .2):
                    raise RuntimeError("physical robot lost lift platform support")
                if abs(physical["roll"]) > 0.6 or abs(physical["pitch"]) > 0.6:
                    raise RuntimeError("Gazebo robot lost upright support")
                if physical["z"] < 0.5 and physical["hull_clearance_m"] < REQUIRED_CLEARANCE:
                    raise RuntimeError("physical robot hull entered mat clearance boundary")
            if (self.current_level == "L1" and self.trajectory and
                    self.trajectory[-1]["hull_clearance_m"] < REQUIRED_CLEARANCE):
                raise RuntimeError("robot hull entered the mat clearance boundary")
            if (self.saw_task and self.fleet_idle and not self.nav_active and
                    self.current_level == "L1" and self.odom is not None and
                    math.hypot(self.odom.twist.twist.linear.x,
                               self.odom.twist.twist.linear.y) < 0.02):
                break
        else:
            raise TimeoutError("RMF multi-level task did not return to an idle L1 robot")
        moving_mat_plans = [p for p in self.plan_records
                            if p["moving_speed_mps"] > 0.02 and p["level"] == "L1" and
                            p["semantic_mat_cells"] >= 4]
        levels = [entry["level"] for entry in self.floor_history]
        transitions = [(a, b) for a, b in zip(levels, levels[1:]) if a != b]
        min_clearance = min((p["mat_minimum_hull_clearance_m"]
                             for p in moving_mat_plans
                             if p["mat_minimum_hull_clearance_m"] is not None),
                            default=None)
        result = {
            "status": "PASS", "task_id": self.task_id,
            "request_id": self.request_id, "rmf_response": self.api_response,
            "nav2_action_statuses": self.nav_statuses,
            "fleet_idle_at_l1": self.fleet_idle and self.current_level == "L1",
            "floor_history": self.floor_history,
            "trajectory": self.trajectory,
            "physics_history": self.physics_history, "payload_history": self.payload_history,
            "floor_transitions": transitions,
            "lift_states": self.lift_history,
            "moving_global_plans": len([p for p in self.plan_records
                                         if p["moving_speed_mps"] > 0.02]),
            "moving_semantic_plans": len(moving_mat_plans),
            "minimum_moving_plan_hull_clearance_m": min_clearance,
            "semantic_costmap_history": self.cost_history,
            "adapter_status": self.served_status(),
            "plans": self.plan_records,
            "dispatch_states": self.dispatch_rows,
        }
        if (not any(b == "L3" for _, b in transitions) or
                not any(a == "L3" and b == "L1" for a, b in transitions)):
            raise RuntimeError("RMF fleet-state evidence does not show L1-to-L3-to-L1 transitions")
        l1_clearances = [row["hull_clearance_m"] for row in self.trajectory if row["level"] == "L1"]
        result["minimum_reported_hull_clearance_m"] = min(l1_clearances, default=None)
        if not l1_clearances or min(l1_clearances) < REQUIRED_CLEARANCE:
            raise RuntimeError("reported robot trajectory did not maintain mat clearance")
        physical_l1 = [r["hull_clearance_m"] for r in self.physics_history if -0.1 < r["z"] < 0.5]
        result["minimum_physical_hull_clearance_m"] = min(physical_l1, default=None)
        if not physical_l1 or min(physical_l1) < REQUIRED_CLEARANCE:
            raise RuntimeError("physical robot did not maintain mat clearance")
        if not any(r["level"] == "L3" and r["nav_active"] and 15.8 < r["z"] < 16.5 for r in self.physics_history):
            raise RuntimeError("physical navigation on L3 was not observed")
        if not any(row["motion_state"] != 0 for row in self.lift_history):
            raise RuntimeError("no lift movement was observed")
        if not moving_mat_plans or min_clearance is None or min_clearance < REQUIRED_CLEARANCE:
            raise RuntimeError("moving Nav2 plans did not prove semantic mat avoidance with clearance")
        if not self.nav_statuses or any(s != GoalStatus.STATUS_SUCCEEDED
                                        for s in self.nav_statuses.values()):
            raise RuntimeError("one or more Nav2 goals did not reach SUCCEEDED")
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--preflight-only", action="store_true")
    action.add_argument("--dispatch", action="store_true",
                        help="send the RMF patrol task; call only after noVNC review")
    parser.add_argument("--timeout", type=float, default=2400.0)
    parser.add_argument("--nav-graph", default="/tmp/phase8-nav-graph.yaml")
    parser.add_argument("--output", default="/tmp/phase8-multilevel-result.json")
    args = parser.parse_args()
    rclpy.init()
    node = Phase8Multilevel(args)
    try:
        preflight = node.preflight()
        result = preflight if args.preflight_only else node.patrol()
        result["preflight"] = dict(preflight) if args.dispatch else None
        result["trial"] = "phase8-multilevel-served-sam3"
        Path(args.output).write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        if node.task_id:
            request = ApiRequest()
            request.request_id = str(uuid.uuid4())
            request.json_msg = json.dumps({"type": "cancel_task_request", "task_id": node.task_id,
                                          "requester": "phase8-multilevel-demo"})
            node.api_pub.publish(request)
            until = time.monotonic() + 3
            while time.monotonic() < until:
                rclpy.spin_once(node, timeout_sec=0.1)
        failure = {"status": "FAIL", "reason": str(error),
                          "task_id": node.task_id,
                          "floor_history": node.floor_history,
                          "lift_states": node.lift_history,
                          "map_size": node.map_size, "pose": node.pose,
                          "semantic_costmap_history": node.cost_history,
                          "plans": node.plan_records, "trajectory": node.trajectory, "physics_history": node.physics_history, "payload_history": node.payload_history, "nav2_action_statuses": node.nav_statuses}
        Path(args.output).write_text(json.dumps(failure, indent=2) + "\n")
        print(json.dumps({"status": "FAIL", "reason": str(error), "output": args.output}), flush=True)
        return 1
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    raise SystemExit(main())