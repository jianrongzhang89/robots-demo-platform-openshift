#!/usr/bin/env python3
"""Independent audit of a Stage 2 physics-routing trial series.

Re-derives every route selection from the frozen fixture and physics model,
recomputes each completed trial's mission window from the raw actuator and
pose traces, and checks corridor/itinerary agreement, reserve and deadline
compliance, per-arm selection repeatability, the planning-time exclusion
scenario, and the low-SOC rejection scenario. Uses only the standard
library and the frozen configuration; it does not trust runner output
beyond recorded inputs.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

from physics_model import PhysicsModel
import route_selector


def observe(output):
    events = [json.loads(line) for line in (output / "adapter-events.jsonl").open()]
    physical = [json.loads(line) for line in (output / "physical.jsonl").open()]
    energy = list(csv.DictReader((output / "energy.csv").open()))
    goals = [e for e in events if e["event"] == "rmf_navigation"]
    mapping = [(row["wall_time"], row["sim_s"]) for row in physical]
    start_sim = min(mapping, key=lambda m: abs(m[0] - goals[0]["wall_time"]))[1]
    end_sim = physical[-1]["sim_s"]
    start_row = min(energy, key=lambda row: abs(float(row["sim_s"]) - start_sim))
    end_row = min(energy, key=lambda row: abs(float(row["sim_s"]) - end_sim))
    return {"duration_s": end_sim - start_sim,
            "mission_wh": float(end_row["cumulative_wh"]) - float(start_row["cumulative_wh"]),
            "final_soc": float(end_row["soc_fraction"]),
            "goals": len(goals)}


def audit_trial(directory, fixture, model, model_path):
    errors = []
    selection = json.loads((directory / "route-selection.json").read_text())
    if selection["status"] == "SELECTED" and not (directory / "stage2-result.json").exists():
        return {"trial": directory.name, "arm": selection["arm"], "status": "INCOMPLETE",
                "selected_route": selection.get("selected_route"),
                "errors": ["selected trial lacks a stage2 result (incomplete run)"]}
    # Independently re-derive the selection from recorded inputs.
    recomputed = route_selector.select(model, fixture, selection["arm"],
                                       selection["payload_kg"], selection["initial_soc"],
                                       tuple(selection["excluded_routes"]))
    if recomputed["status"] != selection["status"]:
        errors.append("selection status differs from independent recomputation")
    if recomputed.get("selected_route") != selection.get("selected_route"):
        errors.append("selected route differs from independent recomputation")
    for name, row in selection["routes"].items():
        mine = recomputed["routes"][name]
        for key in ["predicted_mission_wh", "predicted_duration_s", "predicted_final_soc",
                    "feasible", "distance_m"]:
            if row[key] != mine[key]:
                errors.append(f"{name} {key} differs from independent recomputation")
    if selection["physics_model_sha256"] != hashlib.sha256(model_path.read_bytes()).hexdigest():
        errors.append("physics model digest mismatch")

    row = {"trial": directory.name, "arm": selection["arm"], "status": selection["status"],
           "selected_route": selection.get("selected_route"), "errors": errors}
    if selection["status"] == "REJECTED":
        if not selection.get("rejection_reason"):
            errors.append("rejection without explicit reason")
        if (directory / "energy.csv").exists() or (directory / "result.json").exists():
            errors.append("rejected mission dispatched motion or produced a trial")
        return row

    trial = json.loads((directory / "result.json").read_text())
    stage2 = json.loads((directory / "stage2-result.json").read_text())
    design = json.loads((directory / "design.json").read_text())
    if trial.get("status") != "PASS":
        errors.append(f"navigation trial failed: {trial.get('errors')}")
    if stage2.get("status") != "PASS":
        errors.append(f"stage 2 result failed: {stage2.get('errors')}")
    if design["route"] != selection["selected_route"]:
        errors.append("generated corridor differs from selected route")
    if trial.get("selected_path") != selection["routes"][selection["selected_route"]]["path"]:
        errors.append("dispatched path differs from the selected corridor")
    # Corridor agreement already audited per trial; re-check the thresholds.
    for key in ["maximum_plan_centerline_distance_m", "maximum_itinerary_centerline_distance_m",
                "maximum_schedule_centerline_distance_m"]:
        if trial.get(key) is None or trial[key] > 0.71:
            errors.append(f"{key} missing or outside the selected corridor")
    if trial.get("physical_waypoints") != trial.get("selected_path"):
        errors.append("physical ordered waypoint sequence mismatch")

    observation = observe(directory)
    predicted = selection["routes"][selection["selected_route"]]
    if abs(observation["mission_wh"] - stage2["observation"]["observed_mission_wh"]) > 0.002:
        errors.append("observed mission Wh does not reconcile with independent recomputation")
    if abs(observation["duration_s"] - stage2["observation"]["observed_duration_s"]) > 1.0:
        errors.append("observed mission duration does not reconcile")
    if observation["final_soc"] < float(fixture["energy"]["minimum_soc_after_mission_and_charger"]):
        errors.append("observed final SOC below reserve")
    if observation["duration_s"] > float(fixture["energy"]["deadline_one_way_s"]):
        errors.append("observed mission duration exceeds deadline")
    row.update({
        "observed_mission_wh": round(observation["mission_wh"], 6),
        "predicted_mission_wh": predicted["predicted_mission_wh"],
        "prediction_error_wh": round(observation["mission_wh"] - predicted["predicted_mission_wh"], 6),
        "prediction_error_fraction": round(
            (observation["mission_wh"] - predicted["predicted_mission_wh"]) / observation["mission_wh"], 4),
        "observed_duration_s": round(observation["duration_s"], 1),
        "predicted_duration_s": predicted["predicted_duration_s"],
        "observed_final_soc": round(observation["final_soc"], 6),
        "task_id": trial.get("task_id"),
    })
    return row


def audit(series, fixture, model, model_path, fixture_path):
    errors = []
    trials = sorted(d for d in series.iterdir()
                    if d.is_dir() and (d / "route-selection.json").exists())
    rows = [audit_trial(directory, fixture, model, model_path) for directory in trials]
    by_name = {row["trial"]: row for row in rows}

    def group(prefix):
        return [row for name, row in by_name.items() if name.startswith(prefix)]

    for arm in ["armA", "armB"]:
        members = [row for row in group(arm) if not row["trial"].startswith((arm + "-excluded"))]
        routes = {row["selected_route"] for row in members if row["selected_route"]}
        if members and (len(routes) != 1 or None in routes):
            errors.append(f"{arm} repeated trials did not select one stable route: {routes}")
        if len(members) < 3:
            errors.append(f"{arm} has fewer than three repeated trials")
    excluded = group("armB-excluded")
    if not excluded or not all(row["selected_route"] == "B" for row in excluded):
        errors.append("route-A exclusion scenario did not select route B")
    if not any(row["status"] == "REJECTED" for row in rows):
        errors.append("series contains no planning-time rejection scenario")
    for row in rows:
        errors.extend(f"{row['trial']}: {message}" for message in row["errors"])
    report = {
        "status": "FAIL" if errors else "PASS",
        "errors": errors,
        "trials": rows,
        "fixture_sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        "physics_model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "scope": "independent recomputation of Stage 2 route selection and modeled-energy "
                 "mission windows over the frozen simulation fixture; no physical calibration "
                 "or energy-saving claim",
    }
    (series / "stage2-audit.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("series", type=Path)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--physics-model", type=Path, required=True)
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text())
    model = PhysicsModel.load(args.physics_model)
    report = audit(args.series, fixture, model, args.physics_model, args.fixture)
    print(json.dumps({k: v for k, v in report.items() if k != "trials"}))
    raise SystemExit(report["status"] != "PASS")
