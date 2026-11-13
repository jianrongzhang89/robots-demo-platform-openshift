#!/usr/bin/env python3
"""Run the Phase 6 navigation gates around an RMF-dispatched demo task.

Only RMF sends navigation goals. Safety cancellation also goes through RMF.
Record every moving global plan, costmap cell counts, and independent body pose.
"""
import argparse
import json
import math
import time
import uuid
from types import SimpleNamespace

import rclpy
import yaml
from action_msgs.msg import GoalStatusArray
from lifecycle_msgs.srv import GetState
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.task import Future
from rmf_fleet_msgs.msg import FleetState
from rmf_task_msgs.msg import ApiRequest, ApiResponse

from phase8_rmf_task import TASK_QOS, navigation_request, cancel_request
from run_phase6_demo_d2_trial import Trial


class RMFHandle:
    accepted = True

    def __init__(self, trial):
        self.trial = trial

    def get_result_async(self):
        return self.trial.rmf_result

    def cancel_goal_async(self):
        return self.trial.cancel_rmf()


class RMFTrial(Trial):
    def __init__(self, args):
        super().__init__(args)
        self.task_id = None
        self.request_id = None
        self.response = None
        self.cancel_id = None
        self.cancel_response = None
        self.cancel_future = Future()
        self.rmf_result = Future()
        self.baseline_goals = set()
        self.nav2_goals = {}
        self.task_seen_in_fleet = False
        self.fleet_idle = False
        self.dispatching = False
        self.plans = []
        self.api_pub = self.node.create_publisher(ApiRequest, "/task_api_requests", TASK_QOS)
        self.node.create_subscription(ApiResponse, "/task_api_responses", self.api_response, TASK_QOS)
        status_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                                durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.node.create_subscription(GoalStatusArray, "/navigate_to_pose/_action/status",
                                      self.nav_status, status_qos)
        self.node.create_subscription(FleetState, "/fleet_states", self.fleet_state, 10)

    def publish_request(self, request_id, body):
        msg = ApiRequest()
        msg.request_id = request_id
        msg.json_msg = json.dumps(body)
        self.api_pub.publish(msg)

    def api_response(self, msg):
        if msg.request_id == self.request_id:
            self.response = json.loads(msg.json_msg)
            state = self.response.get("state") or {}
            self.task_id = (state.get("booking") or {}).get("id")
        elif msg.request_id == self.cancel_id:
            self.cancel_response = json.loads(msg.json_msg)
            if not self.cancel_future.done():
                self.cancel_future.set_result(self.cancel_response)

    def nav_status(self, msg):
        for row in msg.status_list:
            key = bytes(row.goal_info.goal_id.uuid).hex()
            if not self.dispatching:
                self.baseline_goals.add(key)
            elif key not in self.baseline_goals:
                self.nav2_goals[key] = int(row.status)
        self.maybe_complete()

    def fleet_state(self, msg):
        if msg.name != "phase8_semantic" or not self.task_id:
            return
        robot = next((r for r in msg.robots if r.name == "robot_1"), None)
        if robot is None:
            return
        if robot.task_id == self.task_id:
            self.task_seen_in_fleet = True
        self.fleet_idle = self.task_seen_in_fleet and not robot.task_id
        self.maybe_complete()

    def maybe_complete(self):
        if not self.nav2_goals or self.rmf_result.done():
            return
        statuses = list(self.nav2_goals.values())
        if any(status in (1, 2, 3) for status in statuses):
            return
        if self.cancel_id and 5 in statuses:
            self.rmf_result.set_result(SimpleNamespace(status=5))
        elif 6 in statuses:
            self.cancel_rmf()
            self.rmf_result.set_result(SimpleNamespace(status=6))
        elif all(status == 4 for status in statuses) and self.fleet_idle and self.latest_truth:
            p = self.latest_truth.pose.pose.position
            if math.hypot(p.x - self.args.goal_x, p.y - self.args.goal_y) <= 0.25:
                self.rmf_result.set_result(SimpleNamespace(status=4))

    def global_plan_cb(self, msg):
        super().global_plan_cb(msg)
        if self.dispatching:
            self.plans.append({
                "wall_time": time.time(), "frame_id": msg.header.frame_id,
                "measured_speed_mps": (math.hypot(self.latest_truth.twist.twist.linear.x,
                    self.latest_truth.twist.twist.linear.y) if self.latest_truth else None),
                "semantic_cells": self.semantic_counts["global"],
                "points": [[p.pose.position.x, p.pose.position.y] for p in msg.poses],
            })

    def dispatch_navigation(self, goal):
        # Guard the waypoint-to-preflight binding: RMF must dispatch the same
        # endpoint whose semantic route was checked by the inherited runner.
        with open(self.args.nav_graph) as source:
            vertices = yaml.safe_load(source)["levels"]["L1"]["vertices"]
        target = next(v for v in vertices if v[2].get("name") == self.args.waypoint)
        if math.hypot(target[0] - self.args.goal_x, target[1] - self.args.goal_y) > 1e-6:
            raise RuntimeError("RMF waypoint does not match the checked navigation goal")
        self.wait_until(lambda: self.api_pub.get_subscription_count() > 0, 15,
                        "RMF task dispatcher is unavailable")
        self.request_id = str(uuid.uuid4())
        self.dispatching = True
        self.publish_request(self.request_id, navigation_request(self.args.waypoint))
        self.wait_until(lambda: self.response is not None, 20, "RMF dispatch response missing")
        if not self.response.get("success") or not self.task_id:
            raise RuntimeError(f"RMF rejected navigation task: {self.response}")
        return RMFHandle(self)

    def cancel_rmf(self):
        if self.task_id and not self.cancel_id:
            self.cancel_id = str(uuid.uuid4())
            self.publish_request(self.cancel_id, cancel_request(self.task_id))
        return self.cancel_future

    def dispatch_evidence(self):
        return {"navigation_dispatch": "OpenRMF task API", "rmf_task_id": self.task_id,
                "rmf_request_id": self.request_id, "rmf_response": self.response,
                "rmf_cancel_response": self.cancel_response, "rmf_fleet_idle": self.fleet_idle,
                "rmf_task_seen_in_fleet": self.task_seen_in_fleet,
                "rmf_nav2_goals": self.nav2_goals, "live_global_plans": self.plans,
                "semantic_cell_history": self.semantic_global_count_history}

    def run(self):
        try:
            clients = [self.node.create_client(GetState, name + "/get_state") for name in
                       ("/planner_server", "/controller_server", "/velocity_smoother", "/bt_navigator")]
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                active = True
                for client in clients:
                    if not client.wait_for_service(timeout_sec=1.0):
                        active = False
                        continue
                    future = client.call_async(GetState.Request())
                    rclpy.spin_until_future_complete(self.node, future, timeout_sec=2.0)
                    if not future.done() or future.result().current_state.id != 3:
                        active = False
                if active:
                    break
                rclpy.spin_once(self.node, timeout_sec=0.5)
            else:
                raise TimeoutError("Nav2 navigation lifecycle nodes did not become active")
            for client in self.costmap_params.values():
                if not client.wait_for_services(timeout_sec=60):
                    raise TimeoutError("Nav2 costmap parameter services did not become ready")
            super().run()
        finally:
            if self.task_id and (not self.rmf_result.done() or self.rmf_result.result().status != 4):
                self.cancel_rmf()
                # Keep processing the cancellation and body telemetry even if
                # admission/result handling raised before the common motion loop.
                end = time.monotonic() + 15
                while time.monotonic() < end:
                    rclpy.spin_once(self.node, timeout_sec=0.05)
                    if (self.cancel_response and self.cancel_response.get("success") and
                            self.nav2_goals and all(v in (4, 5, 6) for v in self.nav2_goals.values()) and
                            self.latest_truth and time.monotonic() - self.truth_received < 0.5 and
                            math.hypot(self.latest_truth.twist.twist.linear.x,
                                       self.latest_truth.twist.twist.linear.y) < 0.005):
                        break
                else:
                    raise RuntimeError("RMF cancellation/physical stop could not be confirmed")


def main(preflight_only=False):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", default="phase8-semantic")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--waypoint", default="phase8_dropoff")
    parser.add_argument("--nav-graph", default="/phase8/nav_graph.yaml")
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()
    args.preflight_only = args.preflight_only or preflight_only
    # Fixed-scene Phase 8 inherits the accepted Phase 6 endpoints and gates.
    vars(args).update(semantic_arm="on", expected_start_x=15.402, expected_start_y=-31.594,
        goal_x=19.5, goal_y=-31.594, goal_yaw=0.0, via=[], map_origin_x=15.402,
        map_origin_y=-31.594, start_tolerance=0.25, speed_limit=0.10,
        speed_tolerance=0.005, summary_only=False)
    rclpy.init()
    trial = RMFTrial(args)
    try:
        trial.run()
    finally:
        trial.node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
