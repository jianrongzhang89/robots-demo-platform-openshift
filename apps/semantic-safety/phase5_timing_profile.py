"""Value-based guards for private Phase 5 timing profiles."""

MOVING_TRACE_GEOMETRY = (0.002, 12.0, 200.0)


def moving_trace_geometry_matches(physics_step, lidar_range, odom_frequency):
    try:
        profile = (float(physics_step), float(lidar_range), float(odom_frequency))
    except (TypeError, ValueError):
        return False
    return profile == MOVING_TRACE_GEOMETRY
