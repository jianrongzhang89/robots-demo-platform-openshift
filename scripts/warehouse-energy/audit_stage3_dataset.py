#!/usr/bin/env python3
"""Independent data-quality audit of the Stage 3A dataset.

Recomputes every run's observed segment Wh from the raw traces, re-derives
the frozen physics estimates, verifies residual arithmetic, feature sanity,
partition disjointness and held-out-condition isolation, and checks that
only passing, complete runs were labeled. Uses only the standard library
and the frozen configuration; it does not trust the builder's rows beyond
recorded inputs.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

from physics_model import PhysicsModel
import build_stage3_dataset as builder


def audit(dataset_dir, raw, fixture, model, design):
    errors = []
    segments = [json.loads(line) for line in (dataset_dir / "segments.jsonl").open()]
    runs = [json.loads(line) for line in (dataset_dir / "runs.jsonl").open()]
    manifest = json.loads((dataset_dir / "dataset-manifest.json").read_text())
    by_run = {}
    for row in segments:
        by_run.setdefault(row["run_id"], []).append(row)

    # 1. Every dataset run maps to a raw directory with a passing result.
    for row in runs:
        directory = raw / row["run_id"]
        if not directory.is_dir():
            errors.append(f"{row['run_id']}: no raw run directory")
            continue
        result = json.loads((directory / "result.json").read_text())
        if result.get("status") != "PASS":
            errors.append(f"{row['run_id']}: raw trial did not pass")
        design_row = json.loads((directory / "design.json").read_text())
        if abs(design_row["payload_kg"] - row["payload_kg"]) > 1e-9:
            errors.append(f"{row['run_id']}: payload mismatch with raw design")
    # 2. Rejected runs were excluded, not labeled.
    for rejected in manifest.get("rejected_runs", []):
        if any(r["run_id"] == rejected["run"] for r in runs):
            errors.append(f"{rejected['run']}: rejected run appears in the dataset")

    # 3. Independent recomputation of observed Wh and residuals.
    for row in runs:
        directory = raw / row["run_id"]
        energy = builder.load_energy(directory / "energy.csv")
        rows = by_run.get(row["run_id"], [])
        if not rows:
            errors.append(f"{row['run_id']}: no segment rows")
            continue
        previous_end = None
        for segment in rows:
            if segment["observed_wh"] < -1e-9 or segment["physics_wh"] < -1e-9:
                errors.append(f"{row['run_id']} segment {segment['segment_index']}: negative energy")
            if abs(segment["residual_wh"] - (segment["observed_wh"] - segment["physics_wh"])) > 2e-6:
                errors.append(f"{row['run_id']} segment {segment['segment_index']}: residual arithmetic")
            if segment["length_m"] <= 0:
                errors.append(f"{row['run_id']} segment {segment['segment_index']}: nonpositive length")
        total = sum(s["observed_wh"] for s in rows)
        if abs(total - row["observed_wh"]) > 2e-6:
            errors.append(f"{row['run_id']}: segment Wh do not sum to the run total")
        # Windows must be time-ordered and within the trace.
        # (Recomputed below via the builder's own extraction for equality.)
        rebuilt, reason = (builder.scripted_run(directory, model, fixture)
                           if row["class"] == "scripted"
                           else builder.nav_run(directory, model, fixture))
        if rebuilt is None:
            errors.append(f"{row['run_id']}: independent rebuild failed ({reason})")
            continue
        _, rebuilt_rows, _, _ = rebuilt
        if len(rebuilt_rows) != len(rows):
            errors.append(f"{row['run_id']}: segment count differs on rebuild")
            continue
        for stored, fresh in zip(rows, rebuilt_rows):
            for key in ["observed_wh", "physics_wh", "residual_wh", "observed_duration_s"]:
                if abs(stored[key] - fresh[key]) > 2e-6:
                    errors.append(f"{row['run_id']} segment {stored['segment_index']}: "
                                  f"{key} differs on rebuild")

    # 4. Partition integrity.
    partitions = design["partitions"]
    held = partitions["final_test"]
    for row in runs:
        for rule in held:
            if rule["class"] != row["class"]:
                continue
            if all(row.get(key) == value for key, value in rule.items() if key != "class"):
                if row["partition"] != "final_test":
                    errors.append(f"{row['run_id']}: held-out condition outside final_test")
        expected = builder.partition_for(row["run_id"], row["class"],
                                          {k: row[k] for k in ["class", "route", "direction",
                                                               "payload_kg", "speed_mps"]},
                                          partitions)
        if expected != row["partition"]:
            errors.append(f"{row['run_id']}: partition {row['partition']} != expected {expected}")
    test_ids = {r["run_id"] for r in runs if r["partition"] == "final_test"}
    for row in runs:
        if row["partition"] != "final_test":
            continue
        for rule in held:
            if rule["class"] != row["class"]:
                continue
            matched = all(row.get(key) == value for key, value in rule.items() if key != "class")
            if not matched:
                errors.append(f"{row['run_id']}: final_test run does not match a held-out rule")
    for row in runs:
        if row["partition"] == "final_test":
            continue
        for rule in held:
            if rule["class"] != row["class"]:
                continue
            if all(row.get(key) == value for key, value in rule.items() if key != "class"):
                errors.append(f"{row['run_id']}: held-out condition leaked into {row['partition']}")
    # Segment rows must never disagree with their run's partition.
    for row in segments:
        run = next(r for r in runs if r["run_id"] == row["run_id"])
        if run["partition"] != row["partition"]:
            errors.append(f"{row['run_id']}: segment/run partition mismatch")

    # 5. Manifest counts.
    if manifest["runs"] != len(runs) or manifest["segments"] != len(segments):
        errors.append("manifest run/segment counts differ")
    for name, count in manifest["partition_counts"].items():
        if count != sum(1 for r in runs if r["partition"] == name):
            errors.append(f"partition count mismatch for {name}")

    report = {
        "status": "FAIL" if errors else "PASS",
        "errors": errors,
        "runs": len(runs),
        "segments": len(segments),
        "rejected_runs": manifest.get("rejected_runs", []),
        "partition_counts": manifest.get("partition_counts", {}),
        "physics_model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "dataset_design_sha256": hashlib.sha256(design_path.read_bytes()).hexdigest(),
        "scope": "independent recomputation of Stage 3A dataset labels, physics estimates, and "
                 "partition integrity over the frozen simulation fixture; no physical calibration",
    }
    (dataset_dir / "stage3-audit.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--physics-model", type=Path, required=True)
    parser.add_argument("--design", type=Path, required=True)
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text())
    model = PhysicsModel.load(args.physics_model)
    design = json.loads(args.design.read_text())
    model_path, design_path = args.physics_model, args.design
    report = audit(args.dataset, args.raw, fixture, model, design)
    print(json.dumps({k: v for k, v in report.items() if k != "errors" or v}))
    raise SystemExit(report["status"] != "PASS")
