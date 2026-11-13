#!/usr/bin/env python3
"""Record RMF dispatch and fleet-state evidence for a Phase 8 task."""

from __future__ import annotations

import argparse
import json
import time

import rclpy
from action_msgs.msg import GoalStatus, GoalStatusArray
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rmf_fleet_msgs.msg import FleetState
from rmf_task_msgs.msg import DispatchStates


class Monitor(Node):
    def __init__(self, fleet_name: str):
        super().__init__("phase8_rmf_monitor")
        self.fleet_name = fleet_name
        self.set_parameters([Parameter("use_sim_time", Parameter.Type.BOOL, True)])
        dispatch_qos = QoSProfile(depth=10,
                                  reliability=ReliabilityPolicy.RELIABLE,
                                  durability=DurabilityPolicy.VOLATILE)
        fleet_qos = QoSProfile(depth=10,
                               reliability=ReliabilityPolicy.RELIABLE,
                               durability=DurabilityPolicy.VOLATILE)
        self.dispatch_states = []
        self.fleet_states = []
        self.nav2_active = False
        self.odometry_speed = None
        self.create_subscription(DispatchStates, "/dispatch_states",
                                 self._dispatch, dispatch_qos)
        self.create_subscription(FleetState, "/fleet_states",
                                 self._fleet, fleet_qos)
        action_status_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(GoalStatusArray,
                                 "/navigate_to_pose/_action/status",
                                 self._nav2_status, action_status_qos)
        self.create_subscription(Odometry, "/odom", self._odometry, 10)

    def _nav2_status(self, message):
        self.nav2_active = any(
            goal.status == GoalStatus.STATUS_EXECUTING
            for goal in message.status_list)

    def _odometry(self, message):
        twist = message.twist.twist.linear
        self.odometry_speed = (twist.x ** 2 + twist.y ** 2) ** 0.5

    def _dispatch(self, message):
        self.dispatch_states.append({
            "active": [self._dispatch_row(row) for row in message.active],
            "finished": [self._dispatch_row(row) for row in message.finished],
            "wall_time": time.time(),
        })

    @staticmethod
    def _dispatch_row(row):
        return {
            "task_id": row.task_id,
            "status": int(row.status),
            "is_assigned": bool(row.assignment.is_assigned),
            "fleet_name": row.assignment.fleet_name,
            "expected_robot_name": row.assignment.expected_robot_name,
            "errors": list(row.errors),
        }

    def _fleet(self, message):
        if message.name != self.fleet_name:
            return
        self.fleet_states.append({
            "name": message.name,
            "robots": [{
                "name": robot.name,
                "task_id": robot.task_id,
                "mode": int(robot.mode.mode),
                "x": float(robot.location.x),
                "y": float(robot.location.y),
                "level": robot.location.level_name,
                "path_length": len(robot.path),
            } for robot in message.robots],
            "wall_time": time.time(),
        })

    def snapshot(self, task_id: str):
        dispatch_by_task = {}
        for event in self.dispatch_states:
            for row in event["active"] + event["finished"]:
                if row["task_id"] == task_id:
                    dispatch_by_task[row["task_id"]] = row
        latest_fleet_by_robot = {}
        for event in self.fleet_states:
            for robot in event["robots"]:
                latest_fleet_by_robot[robot["name"]] = robot
        fleet = [robot for robot in latest_fleet_by_robot.values()
                 if robot["task_id"] == task_id]
        return {
            "task_id": task_id,
            "dispatch": list(dispatch_by_task.values()),
            "fleet": fleet,
            "nav2_active": self.nav2_active,
            "odometry_speed_mps": self.odometry_speed,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id")
    parser.add_argument("--fleet", default="phase8_semantic")
    parser.add_argument("--state", choices=("moving", "idle", "dispatched"),
                        default="moving")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    rclpy.init()
    node = Monitor(args.fleet)
    deadline = time.monotonic() + args.timeout
    found = False
    try:
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.25)
            snapshot = node.snapshot(args.task_id)
            if args.state == "dispatched":
                found = any(row["status"] == 3 and row["is_assigned"]
                            for row in snapshot["dispatch"])
            elif args.state == "moving":
                speed = snapshot["odometry_speed_mps"] or 0.0
                found = bool(snapshot["fleet"]) and (
                    snapshot["nav2_active"] or speed > 0.02)
            else:
                found = (not snapshot["fleet"] and
                         not snapshot["nav2_active"] and
                         snapshot["odometry_speed_mps"] is not None and
                         snapshot["odometry_speed_mps"] < 0.02)
            if found:
                print(json.dumps(snapshot, sort_keys=True))
                return 0
        print(json.dumps(node.snapshot(args.task_id), sort_keys=True))
        return 1
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
