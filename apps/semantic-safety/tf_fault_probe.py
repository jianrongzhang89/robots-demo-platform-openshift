"""Fault routing and evidence predicates for the private hotel test only.

No clock, command, or freshness thresholds are changed by these helpers.
"""
import time


class TfDeliveryFilter:
    """Drop only dynamic map->odom updates destined for the probe buffer."""
    def __init__(self):
        self.blocked=False
        self.dropped=[]

    def admit(self, transform):
        if (self.blocked and transform.header.frame_id.lstrip("/")=="map"
                and transform.child_frame_id.lstrip("/")=="odom"):
            stamp=transform.header.stamp
            self.dropped.append({"stamp":stamp.sec*1_000_000_000+stamp.nanosec,
                                 "wall_ns":time.time_ns(),"steady_ns":time.monotonic_ns()})
            return False
        return True


def map_failure(trace, injected_wall, injected_sim):
    """Require a new capture beyond the frozen map edge, with live odometry."""
    return next((r for r in trace
        if r.get("first_failure_wall_ns",0)>=injected_wall and r["stamp"]>injected_sim
        and r.get("transform_available") is False and r.get("first_error")
        and r.get("map_to_odom_latest",float("inf"))<r["stamp"]
        and r.get("odom_to_lidar_frame_latest",-1)>=r["stamp"]),None)


def stop_reason_qualified(mode, reason):
    # A publisher outage can interrupt Nav2's command production before the
    # independently configured TF lease expires. Retain the first reason.
    return reason=="tf_stale" or mode=="amcl" and reason=="command_expired"
