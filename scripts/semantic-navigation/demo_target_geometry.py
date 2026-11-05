"""Ground-truth geometry and conservative hull-clearance checks for D2 demo."""
from __future__ import annotations

import math


MAT_CENTER_X = 17.4014
MAT_CENTER_Y = -31.5940
MAT_LENGTH_X = 1.2  # Motion-feasible D2 length; 2.7 m left the start inside
# the envelope corner's turning radius (measured 2026-10-30, notouch-run3/4:
# RPP cut to 0.091 m hull clearance and the monitor canceled every trial).
MAT_WIDTH_Y = 1.95  # Standalone demo width: three times the previous 0.65 m.
ROBOT_HULL_RADIUS = 0.246
REQUIRED_HULL_CLEARANCE = 0.10


def mat_bounds(padding: float = 0.0) -> tuple[float, float, float, float]:
    """Return (xmin, xmax, ymin, ymax), conservatively expanded by padding."""
    return (
        MAT_CENTER_X - MAT_LENGTH_X / 2 - padding,
        MAT_CENTER_X + MAT_LENGTH_X / 2 + padding,
        MAT_CENTER_Y - MAT_WIDTH_Y / 2 - padding,
        MAT_CENTER_Y + MAT_WIDTH_Y / 2 + padding,
    )


def point_rect_distance(point: tuple[float, float], bounds=None) -> float:
    if bounds is None:
        bounds = mat_bounds()
    x, y = point
    xmin, xmax, ymin, ymax = bounds
    dx = max(xmin - x, 0.0, x - xmax)
    dy = max(ymin - y, 0.0, y - ymax)
    return math.hypot(dx, dy)


def _point_segment_distance(point, start, end) -> float:
    vx, vy = end[0] - start[0], end[1] - start[1]
    length_sq = vx * vx + vy * vy
    if length_sq == 0:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    t = max(0.0, min(1.0, ((point[0] - start[0]) * vx +
                           (point[1] - start[1]) * vy) / length_sq))
    nearest = (start[0] + t * vx, start[1] + t * vy)
    return math.hypot(point[0] - nearest[0], point[1] - nearest[1])


def _orientation(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_intersect(a, b, c, d) -> bool:
    o1, o2 = _orientation(a, b, c), _orientation(a, b, d)
    o3, o4 = _orientation(c, d, a), _orientation(c, d, b)
    eps = 1e-12
    if ((o1 > eps and o2 < -eps or o1 < -eps and o2 > eps) and
            (o3 > eps and o4 < -eps or o3 < -eps and o4 > eps)):
        return True

    def on_segment(p, q, r):
        return (min(p[0], r[0]) - eps <= q[0] <= max(p[0], r[0]) + eps and
                min(p[1], r[1]) - eps <= q[1] <= max(p[1], r[1]) + eps)

    return ((abs(o1) <= eps and on_segment(a, c, b)) or
            (abs(o2) <= eps and on_segment(a, d, b)) or
            (abs(o3) <= eps and on_segment(c, a, d)) or
            (abs(o4) <= eps and on_segment(c, b, d)))


def segment_intersects_rect(start, end, bounds) -> bool:
    """Liang-Barsky segment/AABB test, including boundary contact."""
    xmin, xmax, ymin, ymax = bounds
    dx, dy = end[0] - start[0], end[1] - start[1]
    lower, upper = 0.0, 1.0
    for p, q in ((-dx, start[0] - xmin), (dx, xmax - start[0]),
                 (-dy, start[1] - ymin), (dy, ymax - start[1])):
        if abs(p) < 1e-15:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            lower = max(lower, t)
        else:
            upper = min(upper, t)
        if lower > upper:
            return False
    return True


def segment_rect_distance(start, end, bounds=None) -> float:
    if bounds is None:
        bounds = mat_bounds()
    if segment_intersects_rect(start, end, bounds):
        return 0.0
    xmin, xmax, ymin, ymax = bounds
    corners = ((xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax))
    edges = tuple(zip(corners, corners[1:] + corners[:1]))
    distances = [point_rect_distance(start, bounds), point_rect_distance(end, bounds)]
    for corner in corners:
        distances.append(_point_segment_distance(corner, start, end))
    for edge_start, edge_end in edges:
        if _segments_intersect(start, end, edge_start, edge_end):
            return 0.0
        distances.extend((
            _point_segment_distance(start, edge_start, edge_end),
            _point_segment_distance(end, edge_start, edge_end),
            _point_segment_distance(edge_start, start, end),
            _point_segment_distance(edge_end, start, end),
        ))
    return min(distances)


def polyline_min_hull_clearance(points) -> float:
    """Minimum conservative circular-hull clearance from the staged mat."""
    if not points:
        return math.inf
    if len(points) == 1:
        center_distance = point_rect_distance(points[0])
    else:
        center_distance = min(segment_rect_distance(a, b)
                              for a, b in zip(points, points[1:]))
    return center_distance - ROBOT_HULL_RADIUS


def polyline_enters_clearance_envelope(points, clearance=REQUIRED_HULL_CLEARANCE) -> bool:
    """Conservative gate: reject a path within hull radius + margin of the mat.

    Expanding an AABB by a circle's radius produces a square at its corners;
    this is intentionally conservative and cannot understate circle overlap.
    """
    if not points:
        return True
    expanded = mat_bounds(ROBOT_HULL_RADIUS + clearance)
    if len(points) == 1:
        return point_rect_distance(points[0], expanded) == 0.0
    return any(segment_intersects_rect(a, b, expanded)
               for a, b in zip(points, points[1:]))


def polyline_intersects_mat(points) -> bool:
    if not points:
        return False
    bounds = mat_bounds()
    if len(points) == 1:
        return point_rect_distance(points[0], bounds) == 0.0
    return any(segment_intersects_rect(a, b, bounds)
               for a, b in zip(points, points[1:]))
