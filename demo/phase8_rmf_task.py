#!/usr/bin/env python3
"""Submit or cancel a correlated task in the isolated Phase 8 RMF graph."""

from __future__ import annotations

import argparse
import json
import time
import uuid

import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import (DurabilityPolicy, HistoryPolicy, QoSProfile,
                       ReliabilityPolicy)
from rmf_task_msgs.msg import ApiRequest, ApiResponse


TASK_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)


class TaskApi(Node):
    def __init__(self):
        super().__init__("phase8_rmf_task_api")
        self.set_parameters([Parameter("use_sim_time", Parameter.Type.BOOL, True)])
        self.request_id = None
        self.publisher = self.create_publisher(
            ApiRequest, "/task_api_requests", TASK_QOS)
        self.response = None
        self.subscription = self.create_subscription(
            ApiResponse, "/task_api_responses", self._response, TASK_QOS)

    def _response(self, message: ApiResponse):
        if self.request_id and message.request_id == self.request_id:
            try:
                self.response = json.loads(message.json_msg)
            except json.JSONDecodeError:
                self.response = {"invalid_json": message.json_msg}

    def submit(self, request: dict, timeout: float) -> dict:
        self.request_id = str(uuid.uuid4())
        message = ApiRequest()
        message.request_id = self.request_id
        message.json_msg = json.dumps(request, separators=(",", ":"))

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and self.publisher.get_subscription_count() == 0:
            rclpy.spin_once(self, timeout_sec=0.1)
        if self.publisher.get_subscription_count() == 0:
            raise TimeoutError("RMF task dispatcher is not subscribed")

        self.publisher.publish(message)
        while time.monotonic() < deadline and self.response is None:
            rclpy.spin_once(self, timeout_sec=0.1)
        if self.response is None:
            raise TimeoutError(f"no response correlated to request {self.request_id}")
        return {"request_id": self.request_id, "response": self.response}


def dispatch_request(pickup: str, dropoff: str) -> dict:
    return {
        "type": "dispatch_task_request",
        "request": {
            "category": "delivery",
            "description": {
                "pickup": {"place": pickup, "handler": "phase8_pickup",
                           "payload": []},
                "dropoff": {"place": dropoff, "handler": "phase8_dropoff",
                            "payload": []},
            },
            "fleet_name": "phase8_semantic",
            "requester": "phase8-demo",
        },
    }


def cancel_request(task_id: str) -> dict:
    return {
        "type": "cancel_task_request",
        "task_id": task_id,
        "requester": "phase8-demo",
    }


def navigation_request(waypoint: str) -> dict:
    return {
        "type": "dispatch_task_request",
        "request": {
            "category": "compose",
            "description": {
                "category": "go_to_place",
                "phases": [{
                    "activity": {
                        "category": "go_to_place",
                        "description": {"one_of": [{"waypoint": waypoint}]},
                    },
                }],
            },
            "fleet_name": "phase8_semantic",
            "requester": "phase8-demo",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    dispatch = subparsers.add_parser("dispatch")
    dispatch.add_argument("pickup", nargs="?", default="phase8_pickup")
    dispatch.add_argument("dropoff", nargs="?", default="phase8_dropoff")
    navigate = subparsers.add_parser("navigate")
    navigate.add_argument("waypoint", nargs="?", default="phase8_dropoff")
    cancel = subparsers.add_parser("cancel")
    cancel.add_argument("task_id")
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    rclpy.init()
    node = TaskApi()
    try:
        if args.command == "dispatch":
            request = dispatch_request(args.pickup, args.dropoff)
        elif args.command == "navigate":
            request = navigation_request(args.waypoint)
        else:
            request = cancel_request(args.task_id)
        result = node.submit(request, args.timeout)
        response = result["response"]
        result["success"] = bool(response.get("success"))
        state = response.get("state") or {}
        result["task_id"] = (state.get("booking") or {}).get("id")
        print(json.dumps(result, sort_keys=True))
        return 0 if result["success"] else 1
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
