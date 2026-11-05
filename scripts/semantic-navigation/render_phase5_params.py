#!/usr/bin/env python3
"""Render a candidate shared single-floor profile; does not deploy or move robots.

Output deliberately ends at a non-actuator topic. A separately qualified guard,
receiver and actuator watchdog are required before it can command a simulator.
"""
import argparse
import copy
import json
from pathlib import Path
import yaml

FOOTPRINT = [[-0.172, -0.155], [0.108, -0.155], [0.108, 0.155], [-0.172, 0.155]]
STOP_POLYGON = [[-0.332, -0.315], [0.268, -0.315], [0.268, 0.315], [-0.332, 0.315]]


def candidate(source):
    config = copy.deepcopy(source)
    # Deliberately exclude docking and extra dispatchers from this profile.
    config.pop("docking_server", None)
    amcl = config["amcl"]["ros__parameters"]
    amcl["tf_broadcast"] = True  # AMCL alone owns map -> odom; no fixed-offset relay.
    amcl["transform_tolerance"] = 0.2
    # Particle budget and odometry-noise review (user-approved October 29,
    # 2026, after series-21/22): the mat-NE detour/descent drives AMCL's
    # y-covariance from 0.10 to ~0.9 m (scan-matching ambiguity in the
    # corridor's y-axis), and with the 500-2000 particle cloud the filter
    # collapses onto wrong-y modes — the belief/truth divergence reached
    # 2.3 m while the belief tracked the path, physically overshooting the
    # descent turn into a pure-pursuit limit cycle twice (lookahead 0.4
    # and 0.5; ~13%/trial, series infeasible). The budget rises 500-2000
    # -> 2000-8000 so the cloud represents the ambiguous y-axis without
    # mode collapse, and the alphas tighten 0.2 -> 0.1: the guarded
    # profile's 200 Hz odometry on the flat floor with rear casters is
    # near-ideal between scans, so anchoring propagation to it limits
    # scan-likelihood-driven y wander while x stays scan-corrected.
    # Applied to BOTH arms equally; the readout is std_y at the descent
    # (poses.json) in the requal pair and the early series trials.
    amcl.update(alpha1=0.1, alpha2=0.1, alpha3=0.1, alpha4=0.1, alpha5=0.1,
                min_particles=2000, max_particles=8000)
    controller = config["controller_server"]["ros__parameters"]
    controller["enable_stamped_cmd_vel"] = True  # retain controller capture time end to end
    controller["controller_frequency"] = 40.0
    # Lookahead tightened from the hotel defaults (0.6/0.3) for the Phase 6
    # crossing goal (user-approved October 28, 2026, after series-16): RPP's
    # 0.6 m lookahead cut the lethal-254 detour's northeast corner inside
    # the plan's inflation clearance, clipping the 0.246 m circumscribed
    # hull into the mat rectangle (on-arm hull exposure 0.000-0.710 m per
    # trial, aggregate reduction 82% vs the series' >=90% gate), and the
    # goal-approach pursuit radius scales with the carrot distance
    # (trial 006-on orbited the goal non-convergently for ~30 s:
    # goal-distance 0.48 -> 2.05 at timeout). Revised to 0.5 (user-approved
    # October 29, 2026, after series-21): 0.4 recovered the corner cut but
    # narrowed the off-path recovery envelope until the mat-NE descent turn
    # overshoot (series-21 trial 000-on: 0.3 m south at the descent,
    # growing monotonically to 2 m) entered a pure-pursuit circling limit
    # cycle around the goal — 0.5 sits between the cutting 0.6 and the
    # overshooting 0.4. In-place rotate-to-heading stays DISABLED: its zero
    # linear velocity deadlocks against the goal checker's stale-stamp
    # odom-frame target (see the note below).
    controller["FollowPath"].update(desired_linear_vel=0.15, rotate_to_heading_angular_vel=0.5,
                                     max_angular_accel=1.0, stateful=False,
                                     use_rotate_to_heading=False,
                                     lookahead_dist=0.5, min_lookahead_dist=0.25)
    # RPP must reconsider positional arrival after localization corrections;
    # goal-checker tolerances/statefulness are unchanged. In-place
    # rotate-to-goal-heading is disabled because its zero linear velocity
    # deadlocks against the goal checker's stale-stamp odom-frame target:
    # the checker transforms the path end at the path's planning stamp, so
    # AMCL drift can hold that target outside xy tolerance while RPP's
    # current-frame carrot is already inside, parking the robot between the
    # two (October 23 GPU series trial 2: 0.185 m current vs 0.203 m stale,
    # 1.9 cm drift, permanent micro-rotation). The straight 0.5 m probe goal
    # needs no in-place rotation; the approach creep carries the robot to
    # the checker's target and the 0.35 rad yaw tolerance covers the
    # residual approach yaw.
    config["bt_navigator"]["ros__parameters"]["default_cancel_timeout"] = 2000
    config["planner_server"]["ros__parameters"]["GridBased"]["allow_unknown"] = False
    for name in ("global_costmap", "local_costmap"):
        params = config[name][name]["ros__parameters"]
        params.pop("robot_radius", None)
        params["footprint"] = json.dumps(FOOTPRINT)
        params["footprint_padding"] = 0.01
        params["update_frequency"] = 10.0
        params["publish_frequency"] = 5.0
        params["transform_tolerance"] = 0.2
        params["always_send_full_costmap"] = True
        # Inflation radius 0.45 (was 0.35; user-approved October 28, 2026,
        # after series-16): RPP's lookahead cut the lethal-254 detour's
        # corner inside the 0.35 m inflation clearance, letting the 0.246 m
        # circumscribed hull clip the mat rectangle. 0.45 restores the hull
        # margin at the corner. Applied to BOTH costmaps and BOTH arms — an
        # equal correction to both comparison arms.
        params["inflation_layer"].update(enabled=True, inflation_radius=0.45, cost_scaling_factor=3.0)
        geometry = "obstacle_layer" if name == "global_costmap" else "voxel_layer"
        params[geometry]["enabled"] = True
        params[geometry]["scan"]["expected_update_rate"] = 0.5
        # Costmap nodes have an extra namespace level. A relative scan_fixed
        # resolves to /robot_1/{local,global}_costmap/scan_fixed, not the bridge.
        # This candidate is explicitly the isolated robot_1 single-floor stack.
        params[geometry]["scan"]["topic"] = "/robot_1/scan_fixed"
        # The lidar's actual configured maximum is 3.5 m, not 4 m.
        params[geometry]["scan"]["raytrace_max_range"] = 3.5
    behaviors = config["behavior_server"]["ros__parameters"]
    behaviors.update(enable_stamped_cmd_vel=True, cycle_frequency=40.0, local_frame="odom", global_frame="map",
                     robot_base_frame="base_footprint", max_rotational_vel=0.5,
                     min_rotational_vel=0.1, rotational_acc_lim=1.0)
    smoother = config["velocity_smoother"]["ros__parameters"]
    smoother.update(enable_stamped_cmd_vel=True, stamp_smoothed_velocity_with_smoothing_time=False,
                    smoothing_frequency=100.0,
                    max_velocity=[0.15, 0.0, 0.5], min_velocity=[-0.10, 0.0, -0.5],
                    velocity_timeout=0.1)
    monitor = config["collision_monitor"]["ros__parameters"]
    monitor.update(use_sim_time=True, enable_stamped_cmd_vel=True,
                   cmd_vel_out_topic="phase5/collision_checked",
                   source_timeout=0.5, transform_tolerance=0.1,
                   stop_pub_timeout=2.0, polygons=["StopEnvelope", "FootprintApproach"])
    monitor["StopEnvelope"] = dict(type="polygon", action_type="stop",
                                    points=json.dumps(STOP_POLYGON), min_points=1,
                                    visualize=True, polygon_pub_topic="phase5/stop_polygon", enabled=True)
    monitor["FootprintApproach"].update(enabled=True, time_before_collision=1.0,
                                        simulation_time_step=0.02, min_points=1)
    return config


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="NEW file only")
    args = parser.parse_args()
    config = candidate(yaml.safe_load((root / "config/nav2/hotel_nav2_params.yaml").read_text()))
    with args.output.open("x") as handle:
        handle.write("# GENERATED Phase 5 candidate; NOT motion-qualified. Semantics excluded.\n")
        yaml.safe_dump(config, handle, sort_keys=False)


if __name__ == "__main__":
    main()
