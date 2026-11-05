"""Observation-only SAM3 checks for the private guarded moving fixture.

Pure decoding/aggregation helpers only: no clock, command, lease or
freshness threshold is changed. The semantic layer is NOT loaded in any
costmap of this fixture; these helpers only verify that the separately
qualified SAM3 runtime registers correctly at capture time while the
guarded chain drives, and that its transport does not break the qualified
observation timing contracts.
"""
import math

MAT_MODEL = "semantic_target_mat"
# Registration contract: capture-time projected points of the avoid_target
# mask must land on the staged mat's ground-truth rectangle. The 0.10 m
# tolerance matches the Phase 1 projection gate; the pooled >=95% fraction
# matches the Phase 1/2 checked-point criteria.
REGISTRATION_FRACTION = 0.95
REGISTRATION_TOLERANCE_M = 0.10
REGISTRATION_Z_MIN_M = -0.05
REGISTRATION_Z_MAX_M = 0.25
MIN_MOVING_RESULTS = 10
MIN_SELECTED_PIXELS = 50
# Observation timing contract: cross-pod Zenoh transport adds latency to
# the qualified Phase 3 in-process path, so the admission bound used by the
# Phase 4 layer and the D1 smoke (500 ms capture age) is the limit here.
P95_CAPTURE_AGE_LIMIT_MS = 500.0
MIN_RESULTS_PER_SECOND = 5.0


def parse_mat_ground_truth(world_text):
    """Axis-aligned ground truth of the staged mat parsed from the world SDF."""
    import re
    model = re.search(r"<model name=[\"']" + MAT_MODEL + r"[\"']>(.*?)</model>",
                      world_text, re.DOTALL)
    if not model:
        raise ValueError("semantic target mat missing from the private world")
    pose = re.search(r"<pose>([^<]+)</pose>", model.group(1))
    size = re.search(r"<size>([^<]+)</size>", model.group(1))
    if not pose or not size:
        raise ValueError("mat pose/size missing from the private world")
    pose_values = pose.group(1).split()
    size_values = size.group(1).split()
    x, y = float(pose_values[0]), float(pose_values[1])
    sx, sy = float(size_values[0]), float(size_values[1])
    return {"xmin": x - sx / 2, "xmax": x + sx / 2,
            "ymin": y - sy / 2, "ymax": y + sy / 2}


def decode_mask(data, width, height):
    """Decode a mono8 label mask into a (height, width) uint8 array."""
    import numpy as np
    if len(data) != width * height:
        raise ValueError("mask payload does not match mono8 dimensions")
    return np.frombuffer(bytes(data), dtype=np.uint8).reshape(height, width)


def decode_points_xyz(data, width, height, point_step, offsets):
    """Decode an organized XYZ cloud into an (height, width, 3) float array.

    offsets is the (x, y, z) byte offset triple taken from the PointCloud2
    field definitions; all fields are float32 little-endian as emitted by
    the qualified SAM3 runtime.
    """
    import numpy as np
    if point_step <= 0 or len(data) != point_step * width * height:
        raise ValueError("point payload does not match organized dimensions")
    raw = np.frombuffer(bytes(data), dtype=np.uint8).reshape(-1, point_step)

    def field(offset):
        return raw[:, offset:offset + 4].copy().view("<f4").reshape(-1)

    return np.stack([field(offsets[i]) for i in range(3)], axis=-1).reshape(height, width, 3)


def points_in_rectangle(points_map, rectangle, tolerance=REGISTRATION_TOLERANCE_M):
    """Fraction of (N,3) map-frame points inside the mat rectangle."""
    import numpy as np
    if len(points_map) == 0:
        return 0, 0.0
    xs, ys, zs = points_map[:, 0], points_map[:, 1], points_map[:, 2]
    inside = ((xs >= rectangle["xmin"] - tolerance) & (xs <= rectangle["xmax"] + tolerance)
              & (ys >= rectangle["ymin"] - tolerance) & (ys <= rectangle["ymax"] + tolerance)
              & (zs >= REGISTRATION_Z_MIN_M) & (zs <= REGISTRATION_Z_MAX_M))
    return len(points_map), float(np.count_nonzero(inside)) / len(points_map)


def transform_points(points, translation, quaternion):
    """Apply a rigid transform to an (N,3) point array."""
    import numpy as np
    x, y, z, w = quaternion
    norm = (x * x + y * y + z * z + w * w) ** 0.5
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    rotation = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    return points @ rotation.T + np.asarray(translation, dtype=float)


def selected_points_in_rectangle(mask, xyz_map, rectangle,
                                 tolerance=REGISTRATION_TOLERANCE_M):
    """Count avoid_target pixels and their in-rectangle fraction."""
    selected = mask == 2
    count = int(selected.sum())
    if count == 0:
        return 0, 0.0
    return points_in_rectangle(xyz_map[selected], rectangle, tolerance)


def registration_summary(results):
    """Aggregate per-result registration measurements.

    results is a list of {"selected": int, "inside_fraction": float,
    "moving": bool} rows; only rows captured while the robot was
    independently moving and with enough selected pixels count.
    """
    moving = [r for r in results
              if r.get("moving") and r.get("selected", 0) >= MIN_SELECTED_PIXELS]
    total = sum(r["selected"] for r in moving)
    inside = sum(r["inside_fraction"] * r["selected"] for r in moving)
    pooled = inside / total if total else 0.0
    passed = len(moving) >= MIN_MOVING_RESULTS and pooled >= REGISTRATION_FRACTION
    return {"passed": passed, "moving_results": len(moving),
            "pooled_selected_points": total, "pooled_inside_fraction": pooled,
            "minimum_result_fraction": min((r["inside_fraction"] for r in moving), default=None),
            "contract": (f">= {REGISTRATION_FRACTION:.0%} of capture-time projected "
                         f"points inside the ground-truth mat over >= {MIN_MOVING_RESULTS} "
                         f"moving results with >= {MIN_SELECTED_PIXELS} selected pixels"),
            "scope": "observation-only registration on the private guarded fixture; "
                     "no semantic cost influence on navigation"}


def timing_summary(ages_ms, result_count, window_seconds):
    """Evaluate the observation timing contract over the task window."""
    if not ages_ms or window_seconds <= 0:
        return {"passed": False, "reason": "missing_timing_records",
                "p95_capture_age_limit_ms": P95_CAPTURE_AGE_LIMIT_MS,
                "rate_limit_per_s": MIN_RESULTS_PER_SECOND}
    ordered = sorted(ages_ms)
    index = min(len(ordered) - 1, max(0, math.ceil(0.95 * len(ordered)) - 1))
    p95 = ordered[index]
    rate = result_count / window_seconds
    passed = p95 <= P95_CAPTURE_AGE_LIMIT_MS and rate >= MIN_RESULTS_PER_SECOND
    return {"passed": passed, "p95_capture_age_ms": p95,
            "p95_capture_age_limit_ms": P95_CAPTURE_AGE_LIMIT_MS,
            "results_per_second": rate, "rate_limit_per_s": MIN_RESULTS_PER_SECOND,
            "records": len(ages_ms)}
