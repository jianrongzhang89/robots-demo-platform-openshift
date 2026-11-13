#!/usr/bin/env python3
"""Forward EasyFullControl lift requests to the simulator lift plugin."""

import rclpy
import math
import os
import re
import subprocess
import json
import time
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rmf_lift_msgs.msg import LiftRequest
from rmf_lift_msgs.msg import LiftState
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Twist
from std_msgs.msg import Bool, String


class LiftRequestRelay(Node):
    def __init__(self):
        super().__init__("lift_request_relay")
        qos = QoSProfile(
            depth=100,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.publisher = self.create_publisher(LiftRequest, "/lift_requests", qos)
        state_qos = QoSProfile(
            depth=100,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )
        self._last_forwarded = None
        self._states = {}
        self._robot_pose = None
        self._l3_exited = False
        self._descent_requested = False
        self._session_id = None
        self._pending_request = None
        self._robot_speed = 0.0
        self._physics_pose = None
        self._physics_yaw = None
        self._physical_evidence = None
        self._phase8 = os.environ.get("PHASE8_MULTILEVEL_SEMANTIC") == "1"
        self._payload = None
        if self._phase8:
            from phase8_lift_payload import LiftPayload
            self._payload = LiftPayload(self)
        self._entry_assist_requested = False
        self._cmd_vel_pub = self.create_publisher(Twist, "/robot_1/cmd_vel", 10)
        entry_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self._entry_complete_pub = self.create_publisher(
            Bool, "/lift_entry_complete", entry_qos)
        self._initial_x = float(os.environ.get("INITIAL_X", "15.402"))
        self._initial_y = float(os.environ.get("INITIAL_Y", "-31.594"))

        self.create_subscription(
            LiftRequest, "/adapter_lift_requests", self._forward, qos)
        self.create_subscription(LiftState, "/lift_states", self._state, state_qos)
        self.create_subscription(Odometry, "/robot_1/odom", self._odom, 10)
        if self._phase8:
            self.create_subscription(String, "/phase8/physics", self._physical_update, 5)
        else:
            self.create_timer(0.5, self._read_physics_pose)
        self.create_timer(0.05 if self._phase8 else 0.1, self._assist_entry)
        self.create_subscription(
            Bool, "/lift_entry_start", self._entry_start, entry_qos)

    @staticmethod
    def _cabin_center(lift_name):
        return (16.984098, -24.221069)

    def _state(self, message):
        if self._payload is not None:
            self._payload.observe_lift(message)
        previous = self._states.get(message.lift_name)
        self._states[message.lift_name] = message
        if message.lift_name == "Lift2":
            if (message.session_id and
                    message.session_id != self._session_id):
                self._session_id = message.session_id
                self._descent_requested = False
                self._l3_exited = False
            if message.current_floor == "L3" and message.session_id:
                if not previous or previous.current_floor != "L3":
                    self._l3_exited = False
            elif message.current_floor != "L3" or not message.session_id:
                self._l3_exited = False

    def _odom(self, message):
        p = message.pose.pose.position
        x = self._initial_x + p.x
        y = self._initial_y + p.y
        self._robot_pose = (x, y)
        self._robot_speed = abs(message.twist.twist.linear.x) + abs(
            message.twist.twist.angular.z)
        # The robot must visibly leave the cabin before a descent is allowed.
        cabin_x, cabin_y = self._cabin_center("Lift2")
        pose = self._physics_pose or self._robot_pose
        if math.hypot(pose[0] - cabin_x, pose[1] - cabin_y) > 1.0:
            self._l3_exited = True
        if self._pending_request is not None and self._ready_for_lift(
                self._pending_request):
            message = self._pending_request
            self._pending_request = None
            self._publish(message)

    def _physical_update(self, message):
        row = json.loads(message.data)
        self._physical_evidence = row
        self._physics_pose = (row["x"], row["y"])
        self._physics_yaw = row["yaw"]

    def _physically_supported(self, state):
        if not self._phase8:
            return True
        row = self._physical_evidence
        if row is None or time.time() - row["wall_time"] > 2.0:
            return False
        elevation = {"L1": 0.0, "L2": 8.0, "L3": 16.0}.get(state.current_floor)
        return (elevation is not None and abs(row["z"] - elevation) < 0.25
                and abs(row["roll"]) < 0.4 and abs(row["pitch"]) < 0.4)

    def _read_physics_pose(self):
        try:
            result = subprocess.run(
                ["gz", "topic", "-e", "-t", "/world/sim_world/pose/info", "-n", "1"],
                capture_output=True, text=True, timeout=0.8, check=False)
            match = re.search(
                r'name: "robot_1".*?position\s*\{\s*'
                r'x:\s*([-+0-9.eE]+)\s*'
                r'y:\s*([-+0-9.eE]+)', result.stdout, re.DOTALL)
            if match:
                pose = (float(match.group(1)), float(match.group(2)))
                if all(math.isfinite(value) for value in pose):
                    self._physics_pose = pose
            orientation = re.search(
                r'name: "robot_1".*?orientation\s*\{\s*'
                r'x:\s*([-+0-9.eE]+)\s*'
                r'y:\s*([-+0-9.eE]+)\s*'
                r'z:\s*([-+0-9.eE]+)\s*'
                r'w:\s*([-+0-9.eE]+)', result.stdout, re.DOTALL)
            if orientation:
                x, y, z, w = (float(value) for value in orientation.groups())
                self._physics_yaw = math.atan2(
                    2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))
        except (OSError, subprocess.SubprocessError, ValueError):
            pass

    def _entry_start(self, message):
        if message.data:
            self._entry_assist_requested = True

    def _assist_entry(self):
        message = self._pending_request
        if ((message is None and not self._entry_assist_requested) or
                self._physics_pose is None or self._physics_yaw is None):
            return
        state = self._states.get(message.lift_name if message else "Lift2")
        if (state is None or state.door_state != LiftState.DOOR_OPEN or
                state.motion_state != LiftState.MOTION_STOPPED or
                not self._physically_supported(state)):
            self._cmd_vel_pub.publish(Twist())
            return
        cabin_x, cabin_y = self._cabin_center(
            message.lift_name if message is not None else "Lift2")
        dx = cabin_x - self._physics_pose[0]
        dy = cabin_y - self._physics_pose[1]
        distance = math.hypot(dx, dy)
        command = Twist()
        if distance > 0.1:
            target_yaw = math.atan2(dy, dx)
            error = (target_yaw - self._physics_yaw + math.pi) % (2.0 * math.pi) - math.pi
            command.angular.z = max(-0.9, min(0.9, 2.0 * error))
            if abs(error) <= 0.6:
                # Double the Phase 8 lift-entry speed and ease into the cabin
                # using the remaining distance as a stopping profile.
                max_entry_speed = 0.24 if self._phase8 else 0.12
                stopping_distance = max(distance - 0.1, 0.0)
                command.linear.x = min(
                    max_entry_speed, math.sqrt(2.0 * 0.5 * stopping_distance))
            self._cmd_vel_pub.publish(command)
        else:
            self._cmd_vel_pub.publish(command)
            if self._entry_assist_requested:
                self._entry_assist_requested = False
                self._entry_complete_pub.publish(Bool(data=True))
            if message is not None and self._ready_for_lift(message):
                self._pending_request = None
                self._publish(message)

    def _ready_for_lift(self, message):
        state = self._states.get(message.lift_name)
        changing_floor = (
            message.request_type == LiftRequest.REQUEST_AGV_MODE and
            (state is None or message.destination_floor != state.current_floor))
        if not changing_floor:
            return True
        if (state is None or state.door_state != LiftState.DOOR_OPEN or
                state.motion_state != LiftState.MOTION_STOPPED or
                not self._physically_supported(state)):
            return False
        cabin_x, cabin_y = self._cabin_center(message.lift_name)
        pose = self._physics_pose or self._robot_pose
        if (pose is None or
                math.hypot(pose[0] - cabin_x,
                           pose[1] - cabin_y) > 0.35 or
                self._robot_speed > (0.03 if self._phase8 else 0.15)):
            return False
        if (message.lift_name == "Lift2" and
                message.destination_floor == "L1" and
                not self._l3_exited):
            return False
        if self._payload is not None and not self._payload.prepare():
            return False
        return True

    def _publish(self, message):
        state = self._states.get(message.lift_name)
        if (self._payload is not None and message.lift_name == "Lift2" and
                message.request_type == LiftRequest.REQUEST_AGV_MODE and
                state is not None and message.destination_floor != state.current_floor):
            self._payload.begin_trip(message.destination_floor)
        key = (
            message.lift_name,
            message.session_id,
            message.request_type,
            message.destination_floor,
            message.door_state,
        )
        self._last_forwarded = key
        self.publisher.publish(message)
        if (message.lift_name == "Lift2" and
                message.request_type == LiftRequest.REQUEST_AGV_MODE and
                message.destination_floor == "L1"):
            self._descent_requested = True

    def _forward(self, message):
        if (message.request_type == LiftRequest.REQUEST_END_SESSION and
                not message.session_id):
            return
        key = (
            message.lift_name,
            message.session_id,
            message.request_type,
            message.destination_floor,
            message.door_state,
        )
        if key == self._last_forwarded:
            return
        if not self._ready_for_lift(message):
            self._pending_request = message
            return
        if (message.lift_name == "Lift2" and
                message.request_type == LiftRequest.REQUEST_AGV_MODE and
                message.destination_floor == "L3" and
                self._descent_requested):
            return
        self._publish(message)


def main():
    rclpy.init()
    node = LiftRequestRelay()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
