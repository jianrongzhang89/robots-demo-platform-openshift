#!/usr/bin/env python3
"""Independent audit of the Stage 4 comparative demonstration.

Recomputes every trial's observed mission energy from the raw traces on
the frozen label convention (dispatch through final waypoint arrival),
re-derives the physics predictions from the fixture and frozen model,
verifies arm C's stored served predictions against the frozen offline
expectations, re-checks route agreement and round-trip chaining, and
recomputes the analyzer's headline statistics. Standard library only.
"""
import argparse
import csv
import json
import math
from pathlib import Path

from physics_model import PhysicsModel
import route_selector


def observe_arrival(directory, end_node_xy):
    events = [json.loads(line) for line in (directory / "adapter-events.jsonl").open()]
    physical = [json.loads(line) for line in (directory / "physical.jsonl").open()]
    energy = list(csv.DictReader((directory / "energy.csv").open()))
    goals = [e for e in events if e["event"] == "rmf_navigation"]
    mapping = [(row["wall_time"], row["sim_s"]) for row in physical]
    start_sim = min(mapping, key=lambda m: abs(m[0] - goals[0]["wall_time"]))[1]
    arrival = next(row["sim_s"] for row in physical
                   if row["sim_s"] >= start_sim
                   and math.hypot(row["x"] - end_node_xy[0], row["y"] - end_node_xy[1]) < 0.20)

    def row_at(target):
        return min(energy, key=lambda row: abs(float(row["sim_s"]) - target))
    return (float(row_at(arrival)["cumulative_wh"])
            - float(row_at(start_sim)["cumulative_wh"]), arrival - start_sim)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("series", type=Path)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--physics-model", type=Path, required=True)
    parser.add_argument("--expectations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text())
    model = PhysicsModel.load(args.physics_model)
    expectations = json.loads(args.expectations.read_text())["expectations"]
    analysis = json.loads(args.analysis.read_text())
    errors = []
    nodes = fixture["geometry"]["nodes"]

    trials = 0
    served_checks = 0
    for directory in sorted(p for p in args.series.iterdir() if p.is_dir()):
        result_path = directory / "stage4-result.json"
        selection_path = directory / "route-selection.json"
        if not result_path.exists():
            continue
        trials += 1
        result = json.loads(result_path.read_text())
        selection = json.loads(selection_path.read_text())
        if result["status"] == "REJECTED":
            if not result.get("rejection_reason"):
                errors.append(f"{directory.name}: rejection without reason")
            continue
        # 1. Observed mission Wh on the frozen arrival convention. The
        #    executed path comes from the generated design (round-trip
        #    return legs plan uphill but execute downhill).
        design = json.loads((directory / "design.json").read_text())
        end_xy = nodes[design["path"][-1]][:2]
        observed_wh, duration = observe_arrival(directory, end_xy)
        if abs(observed_wh - result["observation"]["observed_mission_wh"]) > 0.002:
            errors.append(f"{directory.name}: observed Wh does not reconcile "
                          f"({observed_wh:.6f} vs {result['observation']['observed_mission_wh']})")
        if abs(duration - result["observation"]["observed_duration_s"]) > 1.0:
            errors.append(f"{directory.name}: observed duration does not reconcile")
        # 2. Physics predictions for the evaluated routes. The selection's
        #    recorded payload and direction are the planning values (round
        #    trips always plan on the uphill outbound direction).
        direction = selection["direction"]
        planning_payload = selection["payload_kg"]
        for name, row in selection["routes"].items():
            path = row["path"]
            physics = route_selector.predict_route(model, fixture, path, planning_payload)
            if abs(physics["wh"] - row["predicted_mission_wh"]) > 0.002 and \
                    row["estimator_mode"] == "physics":
                errors.append(f"{directory.name}: physics prediction for {name} "
                              "does not reconcile")
            # 3. Served predictions against the frozen offline expectations.
            if row["estimator_mode"] == "served":
                path_id = f"{name}-{direction}"
                key = f"{path_id}|p{planning_payload}"
                expected = expectations.get(key)
                if expected is None:
                    errors.append(f"{directory.name}: no expectation for {key}")
                elif abs(expected["predicted_wh"] - row["predicted_mission_wh"]) > 0.002:
                    errors.append(f"{directory.name}: served prediction for {name} "
                                  f"differs from frozen expectation "
                                  f"({row['predicted_mission_wh']} vs {expected['predicted_wh']})")
                served_checks += 1
        # 4. Reserve and deadline on the observed outcome.
        if result["observation"]["observed_final_soc"] < \
                float(fixture["energy"]["minimum_soc_after_mission_and_charger"]):
            errors.append(f"{directory.name}: observed final SOC below reserve")
        if result["observation"]["observed_duration_s"] > \
                float(fixture["energy"]["deadline_one_way_s"]):
            errors.append(f"{directory.name}: observed duration exceeds deadline")

    # 5. Analyzer headline numbers.
    checks = analysis.get("checks", {})
    prediction = checks.get("prediction_mae_improvement", {})
    if prediction.get("arm_b_mae_wh") is not None:
        arm_b_errors = []
        arm_c_errors = []
        for directory in sorted(p for p in args.series.iterdir() if p.is_dir()):
            result_path = directory / "stage4-result.json"
            if not result_path.exists():
                continue
            result = json.loads(result_path.read_text())
            if result["status"] != "PASS" or result["mission"] != "oneway":
                continue
            if result["arm"] == "B":
                arm_b_errors.append(abs(result["prediction_error_wh"]))
            elif result["arm"] == "C" and result["prediction"]["estimator_mode"] == "served":
                arm_c_errors.append(abs(result["prediction_error_wh"]))
        mae_b = sum(arm_b_errors) / len(arm_b_errors) if arm_b_errors else None
        mae_c = sum(arm_c_errors) / len(arm_c_errors) if arm_c_errors else None
        if mae_b is not None and abs(mae_b - prediction["arm_b_mae_wh"]) > 1e-4:
            errors.append("analyzer arm B MAE does not reconcile")
        if mae_c is not None and abs(mae_c - prediction["arm_c_served_mae_wh"]) > 1e-4:
            errors.append("analyzer arm C MAE does not reconcile")
    # 6. Round-trip chaining.
    for entry in analysis.get("roundtrips", []):
        out = args.series / f"{entry['key']}-out"
        back = args.series / f"{entry['key']}-return"
        if not (out / "stage4-result.json").exists() or \
                not (back / "stage4-result.json").exists():
            errors.append(f"round trip {entry['key']} legs missing")
            continue
        out_result = json.loads((out / "stage4-result.json").read_text())
        back_result = json.loads((back / "stage4-result.json").read_text())
        total = (out_result["observation"]["observed_mission_wh"]
                 + back_result["observation"]["observed_mission_wh"])
        if abs(total - entry["observed_wh"]) > 0.002:
            errors.append(f"round trip {entry['key']} chained Wh does not reconcile")

    report = {
        "status": "FAIL" if errors else "PASS",
        "errors": errors,
        "trials_audited": trials,
        "served_predictions_verified": served_checks,
        "scope": "independent recomputation of Stage 4 observations, predictions, "
                 "round-trip chaining, and analyzer statistics; modeled energy only",
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    raise SystemExit(report["status"] != "PASS")


if __name__ == "__main__":
    main()
