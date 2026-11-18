#!/usr/bin/env python3
"""Freeze the Stage 3C serving replay batches with offline expectations.

Constructs request batches from the Stage 3A navigation runs using exact
graph-derived planning inputs (unrounded headings and rises, matching the
dataset builder), and records the offline expectations per segment: the
dataset's frozen physics values plus the frozen release's XGBoost residual
predictions. The replay file lets the serving qualification verify
offline/server parity without needing xgboost in the qualification client.
Runs in the pinned pod with the vendored xgboost.
"""
import argparse
import json
import math
from pathlib import Path

import xgboost

import predictor as predictor_module


def exact_inputs(fixture, rows):
    """Rebuild exact request inputs for every navigation run."""
    nodes = fixture["geometry"]["nodes"]
    runs = {}
    for row in rows:
        if row["class"] != "nav":
            continue
        runs.setdefault(row["run_id"], []).append(row)
    batches = []
    for run_id in sorted(runs):
        segments_rows = sorted(runs[run_id], key=lambda r: r["segment_index"])
        path = [segments_rows[0]["segment_name"].split("->")[0]]
        path += [r["segment_name"].split("->")[1] for r in segments_rows]
        headings = [math.atan2(nodes[b][1] - nodes[a][1], nodes[b][0] - nodes[a][0])
                    for a, b in zip(path, path[1:])]
        segments = []
        for index, row in enumerate(segments_rows):
            start, end = row["segment_name"].split("->")
            change = 0.0 if index == 0 else abs(math.atan2(
                math.sin(headings[index] - headings[index - 1]),
                math.cos(headings[index] - headings[index - 1])))
            segments.append({
                "length_m": math.dist(nodes[start][:2], nodes[end][:2]),
                "ramp_run_m": row["ramp_run_m"],
                "signed_rise_m": nodes[end][2] - nodes[start][2],
                "speed_mps": row["speed_mps"],
                "heading_change_rad": change,
                "planned_stops": 0,
                "planned_dwell_s": row["planned_dwell_s"],
                "total_mass_kg": row["total_mass_kg"],
                "class": "nav",
            })
        batches.append({"name": run_id, "segments": segments,
                        "rows": segments_rows})
    return batches


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--physics-model", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text())
    rows = [json.loads(line) for line in (args.dataset / "segments.jsonl").open()]
    predictor = predictor_module.EnergyPredictor(
        args.release_dir, args.physics_model, args.manifest, xgboost_module=xgboost)
    batches = exact_inputs(fixture, rows)
    output = {"schema": "energy-serving-replay/v1", "batches": []}
    for batch in batches:
        # Offline expectations: derived features must equal the dataset rows
        # bit for bit, then the frozen booster supplies the residual.
        derived = [predictor.derive(segment) for segment in batch["segments"]]
        for item, row in zip(derived, batch["rows"]):
            expected_features = [
                row["length_m"], row["ramp_run_m"] or 0.0, row["ascent_m"], row["descent_m"],
                row["max_abs_grade"], row["mean_grade"], abs(row["heading_change_rad"]),
                row["speed_mps"], row["planned_stops_in_segment"], row["planned_dwell_s"],
                row["total_mass_kg"], row["physics_wh"], row["planned_duration_s"], 1.0]
            if item["features"] != expected_features:
                raise SystemExit(f"feature derivation mismatch for {batch['name']} "
                                 f"{row['segment_name']}")
        results = predictor.predict_segments(batch["segments"])
        output["batches"].append({
            "name": batch["name"],
            "segments": batch["segments"],
            "expected": results,
        })
    # A maximum-size batch for the latency target (frozen batch limit 32).
    latency = batches[0]["segments"]
    while len(latency) < 32:
        latency = latency + batches[0]["segments"]
    latency = latency[:32]
    output["latency_batch"] = {"segments": latency,
                               "expected": predictor.predict_segments(latency)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps({"batches": len(output["batches"]),
                      "segments": sum(len(b["expected"]) for b in output["batches"]),
                      "latency_batch_segments": 32}))


if __name__ == "__main__":
    main()
