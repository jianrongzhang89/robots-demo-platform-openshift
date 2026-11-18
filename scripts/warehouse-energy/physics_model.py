#!/usr/bin/env python3
"""Planning-time physics energy estimator for the warehouse fixture (Stage 2).

Predicts battery-terminal Wh for a directed path from planning-time inputs
only: segment geometry (length and elevation profile), planned speed and
acceleration caps, total mass, waypoint stops, heading changes, and a
per-goal transition allowance. The force model follows the approved
proposal: F = m*a + m*g*sin(theta) + Crr*m*g*cos(theta), traction power
max(F*v, 0)/eta, no regeneration credit, plus a constant auxiliary load.

This module never reads observed telemetry. Calibration of its parameters
happens in calibrate_physics.py against frozen Phase 0 calibration runs.
"""
import json
import math
from pathlib import Path

GRAVITY = 9.80665
SAMPLE_DT = 0.05


class PhysicsModel:
    def __init__(self, document):
        parameters = document["parameters"]
        planning = document["planning_assumptions"]
        self.crr = float(parameters["rolling_resistance_coefficient"])
        self.drive_efficiency = float(parameters["drive_efficiency"])
        self.auxiliary_power_w = float(parameters["auxiliary_power_w"])
        self.speed_cap_mps = float(planning["speed_cap_mps"])
        self.acceleration_cap_mps2 = float(planning["acceleration_cap_mps2"])
        self.goal_transition_base_s = float(planning["goal_transition_base_s"])
        self.rotate_angular_vel_rad_s = float(planning["rotate_to_heading_angular_vel_rad_s"])
        self.document = document

    @classmethod
    def load(cls, path):
        return cls(json.loads(Path(path).read_text()))

    def integrate(self, samples, mass):
        """Integrate a planned profile.

        samples: iterable of (dt_s, speed_mps, sin_grade, cos_grade, accel_mps2)
        where the grade and acceleration are along the direction of travel.
        Returns traction mechanical J, electrical J, and duration s.
        """
        traction_j = 0.0
        electrical_j = 0.0
        duration_s = 0.0
        for dt, speed, sin_grade, cos_grade, accel in samples:
            force = (mass * accel + mass * GRAVITY * sin_grade
                     + self.crr * mass * GRAVITY * cos_grade)
            mechanical_w = max(force * speed, 0.0)
            traction_j += mechanical_w * dt
            electrical_j += (mechanical_w / self.drive_efficiency
                             + self.auxiliary_power_w) * dt
            duration_s += dt
        return {"traction_j": traction_j, "electrical_j": electrical_j,
                "wh": electrical_j / 3600.0, "duration_s": duration_s}

    @staticmethod
    def dwell(duration_s):
        """Stationary aux-only samples (goal transitions, holds, settling)."""
        steps = max(1, round(duration_s / SAMPLE_DT))
        dt = duration_s / steps
        return [(dt, 0.0, 0.0, 1.0, 0.0)] * steps

    def stop_to_stop(self, length_m, elevation_fn, speed_mps=None):
        """Planned rest-to-rest traversal of one segment of given length.

        elevation_fn(distance_along_segment) returns ground height, used for
        the local grade. Accel/cruise/decel follow the declared caps using
        the exact kinematic profile. speed_mps overrides the declared speed
        cap for sweep conditions planned below the qualified maximum.
        """
        if length_m <= 0:
            return []
        v_cap = self.speed_cap_mps if speed_mps is None else speed_mps
        a_cap = self.acceleration_cap_mps2
        d_acc = v_cap * v_cap / (2 * a_cap)
        if length_m >= 2 * d_acc:
            v_peak = v_cap
        else:
            v_peak = math.sqrt(length_m * a_cap / 2.0)
        t_ramp = v_peak / a_cap
        d_ramp = v_peak * v_peak / (2 * a_cap)
        cruise_length = length_m - 2 * d_ramp
        t_cruise = cruise_length / v_peak if v_peak > 0 else 0.0
        total = 2 * t_ramp + t_cruise

        def position_at(t):
            if t <= t_ramp:
                return 0.5 * a_cap * t * t
            if t <= t_ramp + t_cruise:
                return d_ramp + v_peak * (t - t_ramp)
            tau = t - t_ramp - t_cruise
            return min(length_m, d_ramp + cruise_length + v_peak * tau - 0.5 * a_cap * tau * tau)

        samples = []
        previous_height = elevation_fn(0.0)
        steps = max(1, math.ceil(total / SAMPLE_DT))
        dt = total / steps
        for index in range(steps):
            t_mid = (index + 0.5) * dt
            if t_mid < t_ramp:
                speed = a_cap * t_mid
                accel = a_cap
            elif t_mid < t_ramp + t_cruise:
                speed = v_peak
                accel = 0.0
            else:
                speed = max(0.0, v_peak - a_cap * (t_mid - t_ramp - t_cruise))
                accel = -a_cap
            position = position_at((index + 1) * dt)
            height = elevation_fn(position)
            run = max(dt * speed, 1e-9)
            drop = height - previous_height
            hypot = math.hypot(run, drop)
            sin_grade = drop / hypot if hypot > 1e-12 else 0.0
            cos_grade = run / hypot if hypot > 1e-12 else 1.0
            samples.append((dt, speed, sin_grade, cos_grade, accel))
            previous_height = height
        return samples

    def rotation(self, heading_change_rad):
        """In-place rotate-to-heading allowance: aux-only, no traction credit."""
        if abs(heading_change_rad) < 1e-6:
            return []
        duration = abs(heading_change_rad) / self.rotate_angular_vel_rad_s
        return self.dwell(duration)


def heading(a, b):
    return math.atan2(b[1] - a[1], b[0] - a[0])


def predict_path(model, nodes, path, ramp_edges, mass, speed_mps=None):
    """Predict energy and duration for a directed node path.

    ramp_edges maps (start_node, end_node) -> run length for sloped segments;
    both directions must be present when traversable both ways. All other
    edges are treated as level. speed_mps overrides the declared speed cap.
    """
    segments = []
    samples = []
    distance_m = 0.0
    previous_direction = None
    for start, end in zip(path, path[1:]):
        a, b = nodes[start], nodes[end]
        length = math.dist(a[:2], b[:2])
        run = ramp_edges.get((start, end))
        if run is not None:
            def elevation_fn(u, run=run, a=a, b=b):
                # Ramp meshes begin at the lower node; local coordinate from
                # the segment start along the direction of travel.
                if a[2] > b[2]:  # descending traversal
                    u = run - u
                return ramp_height(u, run, abs(b[2] - a[2]))
        else:
            def elevation_fn(u, level=a[2]):
                return level
        edge_samples = model.stop_to_stop(length, elevation_fn, speed_mps)
        # Waypoint turn and fixed transition overhead before the next edge.
        direction = heading(a, b)
        turn = []
        if previous_direction is not None:
            change = math.atan2(math.sin(direction - previous_direction),
                                math.cos(direction - previous_direction))
            turn = model.rotation(change) + model.dwell(model.goal_transition_base_s)
        previous_direction = direction
        samples.extend(edge_samples)
        samples.extend(turn)
        distance_m += length
        integrated = model.integrate(edge_samples + turn, mass)
        segments.append({"from": start, "to": end, "distance_m": length,
                         "ramp_run_m": run, **integrated})
    total = model.integrate(samples, mass)
    return {"path": list(path), "distance_m": distance_m,
            "segments": segments, **total}


def ramp_height(u, run, rise):
    """Mirror of the fixture's C1 cosine-transition ramp profile."""
    if u <= 0:
        return 0.0
    if u >= run:
        return rise
    transition = 1.0
    slope = rise / (run - transition)

    def start(x):
        return slope * (x / 2 - transition * math.sin(math.pi * x / transition) / (2 * math.pi))
    if u < transition:
        return start(u)
    if u > run - transition:
        return rise - start(run - u)
    return slope * (u - transition / 2)
