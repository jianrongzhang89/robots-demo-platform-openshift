#!/usr/bin/env python3
"""Temporary physical constraint for a wheel-driven Gazebo lift payload."""
import json
import os
import time
from pathlib import Path



class LiftPayload:
    def __init__(self, node):
        from gz.transport13 import Node as GzNode
        from gz.msgs10.empty_pb2 import Empty
        from gz.msgs10.stringmsg_pb2 import StringMsg
        from std_msgs.msg import String
        from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy
        from rmf_lift_msgs.msg import LiftState
        self._empty = Empty
        self._string = String
        self._motion_stopped = LiftState.MOTION_STOPPED
        self._door_open = LiftState.DOOR_OPEN
        self.node = node
        self.state = None
        self.wanted = False  # Detach the plugin's initial fixed joint at startup.
        self.destination = None
        self.gz = GzNode()
        self.attach = self.gz.advertise('/phase8/lift2/attach', Empty)
        self.detach = self.gz.advertise('/phase8/lift2/detach', Empty)
        if not self.gz.subscribe(StringMsg, '/phase8/lift2/joint_state', self.changed):
            raise RuntimeError('lift payload joint-state subscription failed')
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.publisher = node.create_publisher(String, '/phase8/lift_payload', qos)
        node.create_timer(.1, self.tick)

    def changed(self, msg):
        if msg.data not in ('attached', 'detached'):
            return
        self.state = msg.data
        self.node.get_logger().info(f'Lift2 physical payload joint {self.state}')
        with open('/tmp/phase8-lift-payload.jsonl', 'a') as trace:
            trace.write(json.dumps({'wall_time':time.time(), 'state':self.state,
                                    'destination':self.destination})+'\n')

    def prepare(self):
        self.wanted = True
        return self.state == 'attached'

    def begin_trip(self, destination):
        if self.state != 'attached':
            raise RuntimeError('refusing lift travel before payload attachment')
        self.destination = destination

    def observe_lift(self, msg):
        if (self.destination and msg.lift_name == 'Lift2' and
                msg.current_floor == self.destination and
                msg.motion_state == self._motion_stopped and
                msg.door_state == self._door_open):
            self.wanted = False
            self.destination = None

    def tick(self):
        target = 'attached' if self.wanted else 'detached'
        if self.state != target:
            (self.attach if self.wanted else self.detach).publish(self._empty())
        payload = json.dumps({'wall_time':time.time(), 'state':self.state,
                              'wanted':target, 'destination':self.destination})
        self.publisher.publish(self._string(data=payload))
        Path('/tmp/phase8-lift-payload.tmp').write_text(payload)
        os.replace('/tmp/phase8-lift-payload.tmp', '/tmp/phase8-lift-payload.json')
