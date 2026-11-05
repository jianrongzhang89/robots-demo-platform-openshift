"""Moving fault-stop injection contract for the private hotel fixture.

Pure routing/evidence predicates only: no clock, command, lease or
freshness threshold is changed by these helpers. Each mode injects one
fault class after independently verified motion and requires the guarded
chain to stop fail-closed with a mode-qualified first reason. The native
watchdog, leases, and every freshness deadline keep their qualified values.
"""

MODES = ("collision_state", "scan_loss", "command_stall", "transport_loss",
         "obstacle_spawn")

# First coordinator stop reasons that prove the injected fault class stopped
# the chain. Any other reason is a qualification failure: the trial records
# it and stops the matrix per the no-retry rule.
QUALIFIED_REASONS = {
    "collision_state": ("collision_monitor_stop",),
    # The supervisor's tf evidence is scan-derived: the capture-time
    # map<-lidar transform qualifies only on new scans, so a scan-evidence
    # cutoff freezes both leases at the same capture bound and they expire
    # together ~500 ms later. Which key is named first is an iteration
    # artifact; stop_latency_floor_ms proves the input-freshness deadline
    # (not the 100 ms command deadline) produced the stop.
    "scan_loss": ("scan_stale", "tf_stale"),
    "command_stall": ("command_expired",),
    # Transport loss is stopped by the independent native watchdog lease
    # expiry; which coordinator reason lands first depends on whether the
    # session-loss status or the bounded command queue fills first.
    "transport_loss": ("native_session_lost", "native_queue_unavailable"),
    "obstacle_spawn": ("collision_monitor_stop",),
}


def stop_reason_qualified(mode, reason):
    return reason in QUALIFIED_REASONS.get(mode, ())


def stop_latency_floor_ms(mode):
    """Minimum injection-to-trigger latency that proves the fault's own
    deadline stopped the chain.

    Input freshness is 500 ms from the last qualified capture; with 10 Hz
    scans the last capture precedes injection by at most ~120 ms, so a
    genuine scan-evidence stop lands >= 300 ms after injection. Anything
    earlier is a different deadline (command freshness or watchdog lease)
    and must not qualify as the scan-loss fault class.
    """
    return 300.0 if mode == "scan_loss" else 0.0


def stop_wait_seconds(mode):
    """Bounded wait from injection to the guarded stop.

    Every chain-level fault stops within its existing deadline (watchdog
    lease <=80 ms, command freshness 100 ms, input freshness 500 ms). The
    physical obstacle must first be detected on the approach, so its wait
    covers the remaining travel to the post.
    """
    return 20.0 if mode == "obstacle_spawn" else 5.0


# StopEnvelope spans y in [-0.315, 0.315] m; the padded hull spans
# [-0.165, 0.165] m. A 0.06 m post centred at y=+0.24 m sits inside the
# monitor's stop polygon but outside the footprint, RPP's footprint
# collision check and the approach polygon, with ~0.045 m margin to each
# boundary for straight-line cross-track drift.
OBSTACLE_AHEAD_M = 0.70
OBSTACLE_LATERAL_M = 0.24
OBSTACLE_NAME = "phase5_fault_post"
# The post is pre-placed in the private world at a far off-corridor staging
# pose (scene and physics load at startup, planner sees a clear straight
# path) and moved into the corridor mid-trial through the blocking set_pose
# service, which only sets a pose command component inside PreUpdate.
# Mid-trial entity CREATION is unusable here: it parses SDF and builds scene
# geometry on the simulation thread and stalled physics ~190 ms, which the
# 100 ms command-freshness contract correctly fails.
OBSTACLE_STAGING_LATERAL_M = 2.5
OBSTACLE_POST_MODEL = """<model name="{name}">
    <pose>{x:.4f} {y:.4f} 0.2 0 0 0</pose>
    <link name="post">
      <inertial>
        <mass>5.0</mass>
        <inertia><ixx>0.02</ixx><iyy>0.02</iyy><izz>0.02</izz>
          <ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia>
      </inertial>
      <collision name="post_collision">
        <geometry><box><size>0.06 0.06 0.4</size></box></geometry>
      </collision>
      <visual name="post_visual">
        <geometry><box><size>0.06 0.06 0.4</size></box></geometry>
        <material><ambient>1 0 0 1</ambient><diffuse>1 0 0 1</diffuse></material>
      </visual>
    </link>
  </model>"""


def obstacle_spawn_pose(physical):
    """Corridor pose the post is moved to at injection time.

    OBSTACLE_AHEAD_M along the straight drive axis and OBSTACLE_LATERAL_M
    to the left of the independently captured native physical pose, so the
    monitor's stop polygon catches real lidar returns while no footprint
    contact can occur.
    """
    return {"x": physical["x"] + OBSTACLE_AHEAD_M,
            "y": physical["y"] + OBSTACLE_LATERAL_M}


def obstacle_staging_pose(start_pose):
    """World pose the post occupies from trial start until injection.

    Far enough off the corridor that neither the planner, the costmap
    inflation nor the stop envelope can see it, and verified free in the
    static map before the world is written.
    """
    return {"x": start_pose[0] + OBSTACLE_AHEAD_M,
            "y": start_pose[1] + OBSTACLE_LATERAL_M + OBSTACLE_STAGING_LATERAL_M}


def obstacle_clears_hull(lateral_m, hull_half_width_m=0.165,
                         envelope_half_width_m=0.315, post_half_width_m=0.03):
    """True when the post is inside the stop envelope but outside the hull."""
    inner = abs(lateral_m) - post_half_width_m
    outer = abs(lateral_m) + post_half_width_m
    return inner > hull_half_width_m and outer < envelope_half_width_m
