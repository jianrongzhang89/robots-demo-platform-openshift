"""Bind checked/smoothed commands to original source capture deadlines.

The ROS adapter must supply a validated source wall capture (NOT receipt time).
For simulator stamps that requires a qualified simulation-to-wall mapping; this
module deliberately does not invent one. No publishers or actuator authority.
"""
from dataclasses import dataclass
from safety_core import COMMAND_NS, UNCERTAINTY_NS, integer, velocity_finite, velocity_ok


@dataclass(frozen=True)
class SourceCommand:
    session: str
    ros_stamp: int
    wall_stamp: int
    deadline: int
    velocity: tuple


class CommandLedger:
    def __init__(self):
        self.session = None
        self.barrier = 0
        self.entries = {}
        self.last_stamp = -1

    def reset(self, session, barrier_ros):
        self.session, self.barrier = session, barrier_ros
        self.entries.clear()
        self.last_stamp = barrier_ros

    def record(self, session, ros_stamp, wall_stamp, velocity, now):
        if (not session or session != self.session or not integer(ros_stamp)
                or not integer(wall_stamp) or not velocity_finite(velocity)
                or ros_stamp <= self.last_stamp
                or not 0 <= now.ros-ros_stamp < COMMAND_NS-UNCERTAINTY_NS
                or not -UNCERTAINTY_NS <= now.wall-wall_stamp < COMMAND_NS-UNCERTAINTY_NS):
            return False
        self.last_stamp = ros_stamp
        remaining = COMMAND_NS-max(0, now.wall-wall_stamp+UNCERTAINTY_NS)
        self.entries[ros_stamp] = SourceCommand(session, ros_stamp, wall_stamp,
                                               now.steady+remaining, tuple(velocity))
        self.entries = dict(list(self.entries.items())[-32:])
        return True

    def resolve(self, session, ros_stamp, velocity, now):
        source = self.entries.get(ros_stamp)
        if (not source or session != self.session or source.session != session
                or not velocity_ok(velocity) or now.steady >= source.deadline
                or now.wall-source.wall_stamp+UNCERTAINTY_NS >= COMMAND_NS
                or now.wall < source.wall_stamp-UNCERTAINTY_NS
                or not 0 <= now.ros-source.ros_stamp < COMMAND_NS-UNCERTAINTY_NS):
            return None
        # Repeated smoothing outputs may change velocity but cannot extend the
        # original source deadline or manufacture a new source timestamp.
        return source

