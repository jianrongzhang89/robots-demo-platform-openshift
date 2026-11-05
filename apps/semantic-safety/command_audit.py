"""Offline provenance checks for the isolated, DISARMED hotel observation test.

Not a runtime admission policy: continuous endpoint/owned-action validation is
still required before any command may obtain actuator authority.
"""
from collections import Counter

EXPECTED = {"cmd_vel_nav":{"controller_server":1,"behavior_server":4},
            "cmd_vel_smoothed":{"velocity_smoother":1},
            "phase5/collision_checked":{"collision_monitor":1}}
TOPICS = {"raw":"cmd_vel_nav", "smoothed":"cmd_vel_smoothed", "checked":"phase5/collision_checked"}


def validate_graph(graph):
    if set(graph)!=set(EXPECTED):
        raise ValueError("unexpected command topics")
    identities=set()
    for topic,counts in EXPECTED.items():
        rows=graph[topic]
        if Counter(r["node"] for r in rows)!=counts:
            raise ValueError("unexpected publisher multiplicity")
        for row in rows:
            gid=tuple(row["gid"])
            if (row["namespace"]!="/robot_1" or row["type"]!="geometry_msgs/msg/TwistStamped"
                    or len(gid)!=16 or not all(type(v) is int and 0<=v<=255 for v in gid)
                    or not any(gid) or gid in identities):
                raise ValueError("invalid or reused publisher identity")
            identities.add(gid)


def validate_publisher_binding(graph,rows):
    validate_graph(graph)
    if not rows:
        raise ValueError("missing command evidence")
    for row in rows:
        topic=TOPICS.get(row["kind"])
        if topic is None or row["publisher_gid"] not in [r["gid"] for r in graph[topic]]:
            raise ValueError("unbound command publisher")


def validate_observations(graph,rows):
    validate_publisher_binding(graph,rows)
    for row in rows:
        if row["frame"]!="base_footprint" or row["unused_axes"]!=[0,0,0]:
            raise ValueError("unsupported command frame or axes")
        if row["bound"] is not None:
            if row["source_timestamp"]<=0 or row["bound"]>row["source_timestamp"]:
                raise ValueError("capture bound later than DDS publication")
