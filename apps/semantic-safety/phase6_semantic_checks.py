"""Pure Phase 6 semantic-cost checks for the guarded fixture.

No clock, command, lease or freshness threshold is changed here. These
helpers evaluate the semantic costmap wiring on the frozen guarded profile:
the additive soft-cost layer must mark only the ground-truth mat region with
exactly the configured soft cost, never a lethal cost, and stale cells must
clear within the Phase 4 expiry bound once the target is removed. The
grids are pulled through the costmap's own `get_<layer>` service
(nav2_costmap_2d creates one publisher per CostmapLayer), so no steady-state
subscription load is added to the safety pump.
"""

SOFT_COST = 200
NO_INFORMATION = 255
# The staged mat's SDF model-origin height (install_phase1_camera.slab
# writes pose z=0.005 for the 0.012 m-thick surface). Moves must preserve
# it exactly: the layer's height filter is map-frame [-0.15, 0.15].
MAT_SURFACE_Z = 0.005
# Projection tolerance for tying costmap cells to the ground-truth rectangle:
# the Phase 5 observation series measured 100% in-rectangle registration at a
# 0.10 m tolerance; the cell check allows one extra cell of rasterization.
CELL_RECTANGLE_MARGIN_M = 0.15


def normalize_grid(message):
    """Flatten a nav2_msgs/Costmap service/publisher message into a dict."""
    metadata = message.metadata
    return {"stamp_ns": metadata.update_time.sec * 1_000_000_000
            + metadata.update_time.nanosec,
            "layer": metadata.layer,
            "origin_x": metadata.origin.position.x,
            "origin_y": metadata.origin.position.y,
            "resolution": metadata.resolution,
            "size_x": metadata.size_x,
            "size_y": metadata.size_y,
            "data": list(message.data)}


def grid_cost_cells(grid, value=SOFT_COST):
    """World-frame (x, y) centers of every cell carrying `value`."""
    cells = []
    resolution = grid["resolution"]
    for index, cell in enumerate(grid["data"]):
        if cell != value:
            continue
        x, y = index % grid["size_x"], index // grid["size_x"]
        cells.append((grid["origin_x"] + (x + 0.5) * resolution,
                      grid["origin_y"] + (y + 0.5) * resolution))
    return cells


def grid_histogram(grid):
    histogram = {}
    for cell in grid["data"]:
        histogram[cell] = histogram.get(cell, 0) + 1
    return histogram


def soft_cost_only(histogram, allowed_values=None):
    """The layer's own grid may only carry free, the target cost, or unknown.

    A lethal (254) or inscribed (253) value on the semantic layer's own grid
    would mean the fixed soft-cost policy was violated; any other value means
    an unexpected writer touched the layer's costmap. The lethal-cost
    exclusion experiment (implementation plan: "Evaluate lethal cost 254 as a
    separate exclusion experiment") passes its target cost explicitly.
    """
    allowed = allowed_values or {0, SOFT_COST, NO_INFORMATION}
    return set(histogram) <= allowed


def cells_in_rectangle(cells, rectangle, margin_m=CELL_RECTANGLE_MARGIN_M):
    inside = [(x, y) for x, y in cells
              if rectangle["xmin"] - margin_m <= x <= rectangle["xmax"] + margin_m
              and rectangle["ymin"] - margin_m <= y <= rectangle["ymax"] + margin_m]
    return inside


def semantic_costs_at_target(global_grid, local_grid, rectangle,
                             target_cost=SOFT_COST):
    """Evaluate the semantic-on wiring against the ground-truth rectangle.

    The Phase 6 candidate carries the semantic layer in the GLOBAL costmap
    only (user-approved October 28, 2026 — the local map's semantic
    subscription loaded the controller's process and tripped its command
    authority; see pilot-1 pair-1-on-tfdiag/-qosfix), so the global costmap's
    target-cost cells are checked against the ground truth and the local grid
    must carry no semantic layer at all (it is passed as None by callers
    that verified its absence structurally). The default target cost is the
    qualified soft cost 200; the lethal-cost-254 exclusion experiment passes
    its cost explicitly.
    """
    allowed_values = {0, target_cost, NO_INFORMATION}
    global_cells = grid_cost_cells(global_grid, value=target_cost)
    local_cells = ([grid_cost_cells(local_grid, value=target_cost)]
                   if local_grid is not None else [])
    inside = cells_in_rectangle(global_cells, rectangle)
    histograms = {"global": grid_histogram(global_grid)}
    if local_grid is not None:
        histograms["local"] = grid_histogram(local_grid)
    passed = (bool(global_cells) and not any(local_cells)
              and len(inside) == len(global_cells)
              and all(soft_cost_only(h, allowed_values) for h in histograms.values())
              and target_cost in histograms["global"])
    return {"passed": passed,
            "global_soft_cells": len(global_cells),
            "global_soft_cells_inside_target": len(inside),
            "local_soft_cells": sum(len(c) for c in local_cells),
            "soft_cost_value": target_cost,
            "histograms": {name: {str(k): v for k, v in h.items()}
                           for name, h in histograms.items()},
            "outside_target_cells": [cell for cell in global_cells
                                     if cell not in inside],
            "contract": (f"target-cost-{target_cost} cells in the global costmap, all inside the "
                         "ground-truth rectangle (+"
                         f"{CELL_RECTANGLE_MARGIN_M} m), no value other than "
                         "free/target/unknown on the layer grid, and no semantic "
                         "layer in the local costmap")}


def clearance_bound_s(observation_lifetime_s, update_period_s,
                      p95_capture_age_ms, publish_period_s, margin_s=0.15):
    """Phase 4 expiry bound for stale semantic cells, measured from target
    removal: the last observation of the old location arrives within the
    measured result latency, cells expire after the capture-based lifetime,
    and at most two costmap update periods plus one publish period elapse
    before the cleared grid is observable."""
    return (observation_lifetime_s + 2 * update_period_s
            + p95_capture_age_ms / 1000.0 + publish_period_s + margin_s)


def smoke_registration_summary(results, minimum_results=5,
                               minimum_pixels=50, minimum_fraction=0.99):
    """Pooled in-rectangle fraction over the stationary smoke's results.

    The moving-trial registration contract (sam3_observation.registration_summary)
    only counts results captured while the robot was moving; the stationary
    smoke has none, so this variant pools every pre-removal result with enough
    selected pixels. Same math, honestly labeled.
    """
    usable = [r for r in results if r.get("selected", 0) >= minimum_pixels]
    total = sum(r["selected"] for r in usable)
    inside = sum(r["inside_fraction"] * r["selected"] for r in usable)
    pooled = inside / total if total else 0.0
    return {"passed": len(usable) >= minimum_results and pooled >= minimum_fraction,
            "results": len(usable), "pooled_selected_points": total,
            "pooled_inside_fraction": pooled,
            "contract": (f">= {minimum_fraction:.0%} of capture-time projected points "
                         f"inside the ground-truth mat over >= {minimum_results} "
                         "stationary results (pre-removal window)")}


def mat_removal_pose(start_x, start_y):
    """A visual-only away pose behind and beside the robot, out of the
    forward-facing camera's view, so the old mat location stops being
    observed and its cells must clear by observation expiry. The z is the
    slab's exact SDF model-origin height: a thin floor slab lifted by even
    tens of centimetres fails the layer's map-frame height filter (Phase 6
    smoke attempt 6)."""
    return {"x": start_x - 2.0, "y": start_y - 4.5, "z": MAT_SURFACE_Z}
