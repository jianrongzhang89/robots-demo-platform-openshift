#!/usr/bin/env python3
"""Build the Stage 3A versioned dataset from instrumented sweep runs.

Each sweep run becomes one or more segment rows pairing planning-time
features with the observed modeled Wh from the raw trace, the frozen
physics estimate, and their residual. Segmentation is consistent per run
class: scripted traversals split at the ramp boundaries; navigation
missions split at the directed graph edges crossed between dispatch and
task completion. Partitions are assigned by the frozen complete-run rules
in the dataset design and never split a run across partitions. Failed or
invalid runs are rejected and listed separately, never labeled as
successful low-energy samples.

Outputs: segments.jsonl, runs.jsonl, and dataset-manifest.json.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

from physics_model import PhysicsModel, ramp_height, predict_path
from route_selector import ramp_edges
import calibrate_physics

DATASET_VERSION = "warehouse-stage3-dataset-v1"

DEFAULT_DESIGN = {
    "schema_version": "warehouse-stage3-dataset-design-v1",
    "status": "frozen_before_collection",
    "sweep": {
        "scripted": {"routes": ["A", "B"], "directions": ["up", "down"],
                     "payloads_kg": [0.0, 0.25, 0.5], "speeds_mps": [0.06, 0.08, 0.10],
                     "stop_profiles": [{"stops": 0}, {"stops": 1, "hold_s": 3.0}], "repeats": 1},
        "nav": {"routes": ["A", "B"], "directions": ["up", "down"],
                "payloads_kg": [0.0, 0.25, 0.5], "speeds_mps": [0.08, 0.10], "repeats": 1},
    },
    "partitions": {
        "final_test": [
            {"class": "scripted", "payload_kg": 0.25},
            {"class": "nav", "route": "B", "direction": "up", "speed_mps": 0.08},
        ],
        "deterministic_split": {
            "rule": "first byte of sha256(run_id) modulo 10",
            "residual_train": [0, 1, 2, 3, 4, 5],
            "development": [6, 7],
            "uncertainty_calibration": [8, 9],
        },
        "complete_run_separation": True,
        "seed_note": "the pinned fixture is deterministic (Phase 0 finding); repeat variation "
                     "comes from real-time-factor wall-clock jitter, not seeds",
    },
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_energy(path):
    with path.open() as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError("empty energy trace")
    return [(float(r["sim_s"]), float(r["cumulative_wh"])) for r in rows]


def energy_at(energy, t):
    return min(energy, key=lambda row: abs(row[0] - t))[1]


def observed_span(energy, t0, t1):
    return energy_at(energy, t1) - energy_at(energy, t0)


def load_poses(path):
    with path.open() as stream:
        return [json.loads(line) for line in stream]


def partition_for(run_id, run_class, conditions, rules):
    for held in rules["final_test"]:
        if held["class"] != run_class:
            continue
        if all(conditions.get(key) == value for key, value in held.items() if key != "class"):
            return "final_test"
    split = rules["deterministic_split"]
    bucket = int(hashlib.sha256(run_id.encode()).hexdigest()[:2], 16) % 10
    for name, buckets in [("residual_train", split["residual_train"]),
                          ("development", split["development"]),
                          ("uncertainty_calibration", split["uncertainty_calibration"])]:
        if bucket in buckets:
            return name
    raise ValueError("incomplete deterministic split rules")


def grade_features(samples):
    ascent = descent = 0.0
    max_grade = 0.0
    net = 0.0
    length = 0.0
    for dt, speed, sin_grade, _, _ in samples:
        distance = speed * dt
        drop = sin_grade * distance
        length += distance
        net += drop
        ascent += max(drop, 0.0)
        descent += max(-drop, 0.0)
        max_grade = max(max_grade, abs(sin_grade))
    return {"ascent_m": round(ascent, 4), "descent_m": round(descent, 4),
            "max_abs_grade": round(max_grade, 6), "mean_grade": round(net / length, 6) if length else 0.0}


def scripted_run(directory, model, fixture):
    design = json.loads((directory / "design.json").read_text())
    result = json.loads((directory / "result.json").read_text())
    if result.get("status") != "PASS":
        return None, f"trial status {result.get('status')}"
    energy = load_energy(directory / "energy.csv")
    poses = load_poses(directory / "physics.jsonl")
    run_m = float(design["run_m"])
    direction = design["direction"]
    up = direction == "up"
    # Boundary crossings in traversal order: ascending runs cross the ramp
    # foot then the crest; descending runs cross the crest then the foot.
    boundaries = [0.0, run_m] if up else [run_m, 0.0]
    crossings = []
    for boundary in boundaries:
        crossing = next((p["sim_s"] for p in poses
                         if (p["x"] >= boundary if up else p["x"] <= boundary)), None)
        if crossing is None:
            return None, f"missing x={boundary} crossing"
        crossings.append(crossing)
    window_starts = [poses[0]["sim_s"]] + crossings
    window_ends = crossings + [poses[-1]["sim_s"]]
    names = ["start_pad", "ramp", "end_pad"]
    # Boundaries are in traversal order, so the spans unify across directions.
    start_x = -1.0 if up else run_m + 1.0
    end_x = run_m + 1.0 if up else -1.0
    spans = [(start_x, boundaries[0]), (boundaries[0], boundaries[1]),
             (boundaries[1], end_x)]
    # Planned profile and x positions for physics-per-segment.
    profile = calibrate_physics.scripted_profile(design)
    direction_sign = 1.0 if up else -1.0
    xs = []
    x = -1.0 if up else run_m + 1.0
    for dt, speed, _, _, _ in profile:
        x += direction_sign * speed * dt
        xs.append(x)
    mass = fixture["robot"]["physical_mass_kg"] + float(design["payload_kg"])
    stops_in_ramp = int(design["planned_mid_stops"]) > 0
    rows = []
    for index, (name, (lo, hi), t0, t1) in enumerate(zip(names, spans, window_starts, window_ends)):
        # Interval membership in traversal order: the first segment keeps
        # samples at its entry (start pad); later segments take samples
        # strictly past their entry boundary through their exit boundary.
        low, high = min(lo, hi), max(lo, hi)
        if index == 0:
            inside = [sample for sample, sx in zip(profile, xs)
                      if low - 1e-9 <= sx <= high + 1e-9]
        elif hi > lo:  # ascending traversal
            inside = [sample for sample, sx in zip(profile, xs)
                      if lo + 1e-9 <= sx <= hi + 1e-9]
        else:  # descending traversal
            inside = [sample for sample, sx in zip(profile, xs)
                      if hi - 1e-9 <= sx <= lo - 1e-9]
        physics = model.integrate(inside, mass)
        observed_wh = observed_span(energy, t0, t1)
        features = grade_features(inside)
        dwell = 0.0
        if index == 0:
            dwell += calibrate_physics.SETTLE_S
        if name == "ramp" and stops_in_ramp:
            dwell += float(design["planned_hold_s"]) + 2.0  # brake stationary tail
        if index == len(names) - 1:
            dwell += calibrate_physics.FINISH_S
        rows.append({
            "segment_index": index, "segment_name": name,
            "length_m": round(abs(hi - lo), 3), "ramp_run_m": run_m if name == "ramp" else None,
            "heading_change_rad": 0.0,
            "planned_stops_in_segment": (1 if name == "ramp" and stops_in_ramp else 0),
            "planned_dwell_s": round(dwell, 2),
            "physics_wh": round(physics["wh"], 6),
            "planned_duration_s": round(physics["duration_s"], 2),
            "observed_wh": round(observed_wh, 6),
            "observed_duration_s": round(t1 - t0, 2),
            "residual_wh": round(observed_wh - physics["wh"], 6),
            **features,
        })
    return (design, rows, poses, energy), None


def nav_run(directory, model, fixture):
    design = json.loads((directory / "design.json").read_text())
    result = json.loads((directory / "result.json").read_text())
    if result.get("status") != "PASS":
        return None, f"trial status {result.get('status')}"
    energy = load_energy(directory / "energy.csv")
    poses = load_poses(directory / "physical.jsonl")
    events = [json.loads(line) for line in (directory / "adapter-events.jsonl").open()]
    goals = [e for e in events if e["event"] == "rmf_navigation"]
    if not goals:
        return None, "no goal submissions"
    mapping = [(p["wall_time"], p["sim_s"]) for p in poses]
    dispatch = min(mapping, key=lambda m: abs(m[0] - goals[0]["wall_time"]))[1]
    path = design["path"]
    nodes = design["nodes"]
    # Ordered waypoint crossings after dispatch.
    starts = [dispatch]
    cursor = 1
    for node in path[1:]:
        crossing = None
        for p in poses:
            if p["sim_s"] <= starts[-1]:
                continue
            if math.dist([p["x"], p["y"]], nodes[node][:2]) < 0.20:
                crossing = p["sim_s"]
                break
        if crossing is None:
            return None, f"missing waypoint crossing for {node}"
        starts.append(crossing)
    window_ends = starts[1:] + [poses[-1]["sim_s"]]
    mass = fixture["robot"]["physical_mass_kg"] + float(design["payload_kg"])
    prediction = predict_path(model, nodes, path, ramp_edges(fixture), mass,
                              float(design.get("planned_speed_mps", 0.1)))
    edges = ramp_edges(fixture)
    rows = []
    previous_heading = None
    for index, (start, end, t0, t1) in enumerate(zip(path, path[1:], starts, window_ends)):
        a, b = nodes[start], nodes[end]
        heading = math.atan2(b[1] - a[1], b[0] - a[0])
        change = 0.0 if previous_heading is None else abs(
            math.atan2(math.sin(heading - previous_heading), math.cos(heading - previous_heading)))
        previous_heading = heading
        length = math.dist(a[:2], b[:2])
        run = edges.get((start, end))
        rise = abs(b[2] - a[2]) if run else 0.0
        ascent = descent = 0.0
        max_grade = 0.0
        if run:
            steps = 40
            previous = ramp_height(0.0, run, rise) if a[2] < b[2] else rise
            for step in range(1, steps + 1):
                u = length * step / steps
                local = u if a[2] < b[2] else run - u
                height = ramp_height(local, run, rise)
                drop = (height - previous) if a[2] < b[2] else (previous - height)
                ascent += max(drop, 0.0)
                descent += max(-drop, 0.0)
                max_grade = max(max_grade, abs(drop) / (length / steps))
                previous = height
        segment = prediction["segments"][index]
        observed_wh = observed_span(energy, t0, t1)
        rows.append({
            "segment_index": index, "segment_name": f"{start}->{end}",
            "length_m": round(length, 3), "ramp_run_m": run,
            "heading_change_rad": round(change, 4),
            "planned_stops_in_segment": 0,
            "planned_dwell_s": 0.0 if index == 0 else model.goal_transition_base_s,
            "physics_wh": round(segment["wh"], 6),
            "planned_duration_s": round(segment["duration_s"], 2),
            "observed_wh": round(observed_wh, 6),
            "observed_duration_s": round(t1 - t0, 2),
            "residual_wh": round(observed_wh - segment["wh"], 6),
            "ascent_m": round(ascent, 4), "descent_m": round(descent, 4),
            "max_abs_grade": round(max_grade, 6),
            "mean_grade": round((b[2] - a[2]) / length, 6),
        })
    return (design, rows, poses, energy), None


def build(raw, fixture, model, design_rules, output):
    runs = []
    segments = []
    rejected = []
    for directory in sorted(p for p in raw.iterdir() if p.is_dir()):
        design_path = directory / "design.json"
        if not design_path.exists():
            rejected.append({"run": directory.name, "reason": "no design file"})
            continue
        design = json.loads(design_path.read_text())
        run_class = design.get("class")
        if run_class == "scripted":
            parsed, reason = scripted_run(directory, model, fixture)
        elif run_class == "nav":
            parsed, reason = nav_run(directory, model, fixture)
        else:
            parsed, reason = None, f"unknown run class {run_class!r}"
        if parsed is None:
            rejected.append({"run": directory.name, "reason": reason})
            continue
        design, rows, poses, energy = parsed
        conditions = {"class": run_class, "route": design["route"],
                      "direction": design["direction"],
                      "payload_kg": float(design["payload_kg"]),
                      "speed_mps": float(design.get("planned_speed_mps", 0.1))}
        if run_class == "scripted":
            conditions["stops"] = int(design["planned_mid_stops"])
            conditions["hold_s"] = float(design["planned_hold_s"])
        partition = partition_for(directory.name, run_class, conditions,
                                  design_rules["partitions"])
        run_id = directory.name
        run_row = {"run_id": run_id, "partition": partition, **conditions,
                   "total_mass_kg": fixture["robot"]["physical_mass_kg"] + conditions["payload_kg"],
                   "segments": len(rows),
                   "observed_wh": round(sum(r["observed_wh"] for r in rows), 6),
                   "physics_wh": round(sum(r["physics_wh"] for r in rows), 6),
                   "residual_wh": round(sum(r["residual_wh"] for r in rows), 6),
                   "observed_duration_s": round(poses[-1]["sim_s"] - poses[0]["sim_s"], 1),
                   "result_status": "PASS"}
        runs.append(run_row)
        for row in rows:
            segments.append({"run_id": run_id, "partition": partition, **conditions,
                             "total_mass_kg": run_row["total_mass_kg"], **row})
    output.mkdir(parents=True, exist_ok=True)
    with (output / "segments.jsonl").open("w") as stream:
        for row in segments:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    with (output / "runs.jsonl").open("w") as stream:
        for row in runs:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    counts = {}
    for row in runs:
        counts[row["partition"]] = counts.get(row["partition"], 0) + 1
    manifest = {
        "schema_version": DATASET_VERSION,
        "dataset_status": "collected_pending_stage3b_training",
        "runs": len(runs), "segments": len(segments), "rejected_runs": rejected,
        "partition_counts": counts,
        "partition_rules": design_rules["partitions"],
        "sweep_design": design_rules["sweep"],
        "scope": "simulated modeled-energy labels for the frozen warehouse fixture; "
                 "planning-time features, frozen physics estimates, and residuals; "
                 "no physical electrical calibration",
        "label_definition": "observed modeled Wh from the observation-only plugin trace under the "
                            "frozen Phase 1 accounting model, segmented between consecutive "
                            "waypoint or ramp-boundary crossings",
    }
    (output / "dataset-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--physics-model", type=Path, required=True)
    parser.add_argument("--design", type=Path, default=None,
                        help="frozen dataset design JSON (defaults to the embedded v1 rules)")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text())
    model = PhysicsModel.load(args.physics_model)
    rules = json.loads(args.design.read_text()) if args.design else DEFAULT_DESIGN
    manifest = build(args.raw, fixture, model, rules, args.output)
    print(json.dumps({k: v for k, v in manifest.items()
                      if k not in ("partition_rules", "sweep_design")}))


if __name__ == "__main__":
    main()
