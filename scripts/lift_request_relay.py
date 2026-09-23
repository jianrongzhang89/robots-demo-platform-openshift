#!/usr/bin/env python3
"""Forward EasyFullControl lift requests to the simulator lift plugin."""

import rclpy
import math
import os
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rmf_lift_msgs.msg import LiftRequest
from rmf_lift_msgs.msg import LiftState
from nav_msgs.msg import Odometry


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
        self._initial_x = float(os.environ.get("INITIAL_X", "15.402"))
        self._initial_y = float(os.environ.get("INITIAL_Y", "-31.594"))
        self.create_subscription(
            LiftRequest, "/adapter_lift_requests", self._forward, qos)
        self.create_subscription(LiftState, "/lift_states", self._state, state_qos)
        self.create_subscription(Odometry, "/robot_1/odom", self._odom, 10)

    def _state(self, message):
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
        # The robot must visibly leave the cabin before a descent is allowed.
        if math.hypot(x - 16.984, y + 24.221) > 1.0:
            self._l3_exited = True

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
        if (message.lift_name == "Lift2" and
                message.request_type == LiftRequest.REQUEST_AGV_MODE and
                message.destination_floor == "L1"):
            state = self._states.get("Lift2")
            if state and state.current_floor == "L3" and state.session_id:
                if (not self._l3_exited or self._robot_pose is None or
                        math.hypot(self._robot_pose[0] - 16.984,
                                   self._robot_pose[1] + 24.221) > 1.0):
                    return
        if (message.lift_name == "Lift2" and
                message.request_type == LiftRequest.REQUEST_AGV_MODE and
                message.destination_floor == "L3" and
                self._descent_requested):
            return
        self._last_forwarded = key
        self.publisher.publish(message)
        descent_request = (
            message.lift_name == "Lift2" and
            message.request_type == LiftRequest.REQUEST_AGV_MODE and
            message.destination_floor == "L1" and
            self._states.get("Lift2") is not None and
            self._states["Lift2"].current_floor == "L3")
        if descent_request:
            self._descent_requested = True


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
