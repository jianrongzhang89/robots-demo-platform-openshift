#!/usr/bin/env python3
"""Forward EasyFullControl lift requests to the simulator lift plugin."""

import copy

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rmf_lift_msgs.msg import LiftRequest
from rmf_lift_msgs.msg import LiftState


class LiftRequestRelay(Node):
    def __init__(self):
        super().__init__("lift_request_relay")
        qos = QoSProfile(
            depth=100,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.publisher = self.create_publisher(LiftRequest, "/lift_requests", qos)
        self._states = {}
        self.create_subscription(
            LiftRequest, "/adapter_lift_requests", self._forward, qos)
        state_qos = QoSProfile(
            depth=100,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )
        self.create_subscription(
            LiftState, "/lift_states", self._state, state_qos)

    def _state(self, message):
        self._states[message.lift_name] = message

    def _forward(self, message):
        if (message.request_type == LiftRequest.REQUEST_END_SESSION and
                not message.session_id):
            return
        state = self._states.get(message.lift_name)
        if (message.request_type == LiftRequest.REQUEST_AGV_MODE and state and
                not state.session_id and
                state.current_floor == message.destination_floor and
                state.motion_state == LiftState.MOTION_STOPPED):
            alternate = next(
                (floor for floor in state.available_floors
                 if floor != state.current_floor), None)
            if alternate:
                bootstrap = copy.deepcopy(message)
                bootstrap.destination_floor = alternate
                bootstrap.door_state = LiftRequest.DOOR_CLOSED
                self.publisher.publish(bootstrap)
                return
        self.publisher.publish(message)


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
