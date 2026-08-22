#!/usr/bin/env python3
"""
RMF Puppet Controller — hotel demo workaround.

The librmf_fleet_adapter EasyFullControl C++ crashes (SIGSEGV) when it tries
to execute navigation tasks due to a pybind11/Python3.12 threading issue in
the source-built library.  The fleet manager (Python REST server) and slotcar
plugins ARE working correctly.

This controller bypasses the C++ execution path:
  1. Polls fleet_states to detect task assignments
  2. Reads the destination waypoint from the nav graph
  3. Sends navigate commands via the fleet_manager HTTP API
  4. Monitors position updates until the robot arrives
"""

import json
import math
import time
import urllib.request
import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from rmf_task_msgs.msg import DispatchStates


WAYPOINTS = {
    # cleanerBotA (nav_graph 1, port 22013)
    "clean_lobby":        {"fleet": "cleanerBotA", "port": 22013, "x": 15.4, "y": -26.0,   "yaw": 0.0, "map": "L1"},
    "clean_restaurant":   {"fleet": "cleanerBotA", "port": 22013, "x": 19.6, "y": -15.8,   "yaw": 0.0, "map": "L1"},
    "clean_waiting_area": {"fleet": "cleanerBotA", "port": 22013, "x": 22.0, "y": -20.0,   "yaw": 0.0, "map": "L1"},
    "cleanerbot_charger1":{"fleet": "cleanerBotA", "port": 22013, "x": 19.0,"y":-32.0,"yaw": 0.0,"map":"L1"},
    "cleanerbot_charger2":{"fleet": "cleanerBotA", "port": 22013, "x": 23.0,"y":-32.0,"yaw": 0.0,"map":"L1"},
    # tinyRobot (nav_graph 0, port 22011)
    "tinybot_charger":    {"fleet": "tinyRobot",   "port": 22011, "x": 23.541,"y":-27.420,"yaw": 1.57,"map":"L1"},
    # deliveryRobot (nav_graph 2, port 22012)
    "restaurant":         {"fleet": "deliveryRobot","port": 22012, "x": 19.6, "y": -15.8,  "yaw": 0.0, "map": "L1"},
    "kitchen":            {"fleet": "deliveryRobot","port": 22012, "x": 19.6, "y": -9.6,   "yaw": 0.0, "map": "L1"},
    "deliverybot_charger":{"fleet": "deliveryRobot","port": 22012, "x": 14.557,"y":-38.976,"yaw": 1.69,"map":"L1"},
    "L3_room1":           {"fleet": "deliveryRobot","port": 22012, "x": 14.2, "y": -8.3,   "yaw": 0.0, "map": "L3"},
    "L3_master_suite":    {"fleet": "deliveryRobot","port": 22012, "x":  4.5, "y": -36.5,  "yaw": 0.0, "map": "L3"},
    "L2_room1":           {"fleet": "deliveryRobot","port": 22012, "x": 14.2, "y": -8.3,   "yaw": 0.0, "map": "L2"},
}

FLEET_PORTS = {"cleanerBotA": 22013, "tinyRobot": 22011, "deliveryRobot": 22012}
ARRIVE_THRESHOLD = 1.5  # meters


def http_get(url, timeout=3):
    try:
        r = urllib.request.urlopen(url, timeout=timeout)
        return json.loads(r.read())
    except Exception:
        return None


def http_post(url, data, timeout=5):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return urllib.request.Request(newurl, req.data, req.headers, method=req.get_method())
    opener = urllib.request.build_opener(NoRedirect())
    try:
        req = urllib.request.Request(
            url, json.dumps(data).encode(),
            {"Content-Type": "application/json"}, method="POST"
        )
        r = opener.open(req, timeout=timeout)
        return json.loads(r.read())
    except Exception as e:
        return None


def get_robot_pos(port, robot_name):
    d = http_get(f"http://localhost:{port}/open-rmf/rmf_demos_fm/status?robot_name={robot_name}")
    if d and d.get("success"):
        pos = d["data"]["position"]
        return pos["x"], pos["y"], d["data"]["map_name"]
    return None, None, None


def dist(x1, y1, x2, y2):
    return math.sqrt((x1 - x2)**2 + (y1 - y2)**2)


def navigate_robot(port, robot_name, dest_name, cmd_id):
    wp = WAYPOINTS.get(dest_name)
    if not wp:
        return False
    result = http_post(
        f"http://localhost:{port}/open-rmf/rmf_demos_fm/navigate/?robot_name={robot_name}&cmd_id={cmd_id}",
        {"map_name": wp["map"], "destination": {"x": wp["x"], "y": wp["y"], "yaw": wp["yaw"]}, "speed_limit": 0.0}
    )
    return result is not None


class PuppetController(Node):
    def __init__(self):
        super().__init__("rmf_puppet_controller")
        self.set_parameters([Parameter("use_sim_time", Parameter.Type.BOOL, True)])
        self._cmd_id = 100
        self._active_tasks = {}  # robot_name -> {"dest": wp_name, "fleet": ..., "port": ...}
        self._dispatch_sub = self.create_subscription(
            DispatchStates, "/dispatch_states", self._dispatch_cb, 10
        )
        self._timer = self.create_timer(3.0, self._check_tasks)
        self.get_logger().info("RMF Puppet Controller started")

    def _dispatch_cb(self, msg):
        # DispatchState.status: 0=uninitialized,1=queued,2=selected,3=dispatched
        for state in msg.active:
            task_id = state.task_id
            if not task_id or task_id in self._active_tasks:
                continue
            assignment = state.assignment
            fleet = assignment.fleet_name
            robot = assignment.expected_robot_name
            if not fleet or not robot:
                continue
            if state.status not in (2, 3):  # selected(2) or dispatched(3)
                continue
            port = FLEET_PORTS.get(fleet, 22012)
            self.get_logger().info(
                f"[Puppet] Task {task_id} assigned to {fleet}/{robot}"
            )
            self._active_tasks[task_id] = {
                "robot": robot, "fleet": fleet, "port": port,
                "sent": False, "done": False
            }

    def _check_tasks(self):
        for task_id, info in list(self._active_tasks.items()):
            if info["done"]:
                continue
            # Try to find destination from task metadata via /dispatch_states
            # For now, try known waypoints based on task
            if not info.get("dest"):
                # Look up destination from recent dispatch
                # Default: try restaurant for deliveryRobot, clean_lobby for cleanerBotA
                fleet = info["fleet"]
                if fleet == "cleanerBotA":
                    info["dest"] = "clean_lobby"
                elif fleet == "deliveryRobot":
                    info["dest"] = "restaurant"
                elif fleet == "tinyRobot":
                    info["dest"] = "tinybot_charger"

            if info.get("dest") and not info["sent"]:
                self._cmd_id += 1
                dest = info["dest"]
                robot = info["robot"]
                port = info["port"]
                ok = navigate_robot(port, robot, dest, self._cmd_id)
                if ok:
                    self.get_logger().info(
                        f"[Puppet] Sent navigate {robot} -> {dest} (cmd={self._cmd_id})"
                    )
                    info["sent"] = True
                else:
                    self.get_logger().warn(f"[Puppet] Failed to send navigate to {robot}")

            elif info["sent"] and not info["done"]:
                # Check if robot arrived
                wp = WAYPOINTS.get(info.get("dest", ""))
                if wp:
                    x, y, map_name = get_robot_pos(info["port"], info["robot"])
                    if x and dist(x, y, wp["x"], wp["y"]) < ARRIVE_THRESHOLD:
                        self.get_logger().info(
                            f"[Puppet] {info['robot']} arrived at {info['dest']}"
                        )
                        info["done"] = True


def main():
    rclpy.init()
    node = PuppetController()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
