#!/usr/bin/env python3
"""Independent audit of a frozen Stage 3B energy-model release.

Verifies the freeze boundary (the recorded hash covers the hyperparameters,
models, and uncertainty calibration and nothing from the held-out test),
reloads the XGBoost booster and linear model from their artifacts through
an inference path independent of the training wrappers, re-derives the
planning-time features from the dataset, and recomputes every reported
held-out metric: mission MAE for physics-only, physics-plus-linear, and
physics-plus-XGBoost, bounds rejections, and upper-estimate coverage.

With --retrain, re-runs the deterministic training job and requires a
byte-identical model artifact.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy
import xgboost

from train_stage3b import FEATURES, canonical, quantile_higher


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def features(row):
    return [extract(row) for _, extract in FEATURES]


def combined_with_bounds(row, correction):
    physics = float(row["physics_wh"])
    combined = physics + correction
    if combined < 0.0 or abs(correction) > physics:
        return physics, True
    return combined, False


def mission_summary(rows, corrections):
    by_run = {}
    rejected = 0
    for row, correction in zip(rows, corrections):
        combined, was_rejected = combined_with_bounds(row, correction)
        rejected += int(was_rejected)
        mission = by_run.setdefault(row["run_id"], {"pred": 0.0, "obs": 0.0})
        mission["pred"] += combined
        mission["obs"] += float(row["observed_wh"])
    errors = [abs(m["pred"] - m["obs"]) for m in by_run.values()]
    return {"missions": by_run, "rejected": rejected,
            "mae": sum(errors) / len(errors) if errors else 0.0,
            "max_abs_error": max(errors) if errors else 0.0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release_dir", type=Path)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--retrain", action="store_true")
    args = parser.parse_args()
    errors = []
    release = json.loads((args.release_dir / "release.json").read_text())
    evaluation = json.loads((args.release_dir / "evaluation.json").read_text())
    frozen = release["frozen"]

    # 1. Freeze boundary and artifact integrity.
    if hashlib.sha256(canonical(frozen).encode()).hexdigest() != release["frozen_sha256"]:
        errors.append("frozen portion hash mismatch")
    if frozen["xgb_model_sha256"] != digest(args.release_dir / "xgb-model.json"):
        errors.append("XGBoost artifact digest mismatch")
    if frozen["linear_model_sha256"] != digest(args.release_dir / "linear-model.json"):
        errors.append("linear artifact digest mismatch")
    if frozen["dataset"]["segments_sha256"] != digest(args.dataset / "segments.jsonl"):
        errors.append("dataset digest mismatch")
    for forbidden in ["physics_plus_xgboost", "upper_estimate_coverage", "held_out_partition",
                      "test_opened_once"]:
        if forbidden in json.dumps(frozen):
            errors.append(f"frozen portion contains test-derived value '{forbidden}'")

    # 2. Independent inference from the artifacts.
    booster = xgboost.Booster()
    booster.load_model(str(args.release_dir / "xgb-model.json"))
    linear = json.loads((args.release_dir / "linear-model.json").read_text())

    def linear_predict(rows):
        x = numpy.array([features(r) for r in rows], dtype=float)
        z = (x - numpy.array(linear["mean"])) / numpy.array(linear["scale"])
        return z @ numpy.array(linear["weights"][:-1]) + linear["weights"][-1]

    rows = [json.loads(line) for line in (args.dataset / "segments.jsonl").open()]
    test = [row for row in rows if row["partition"] == "final_test"]
    calibration = [row for row in rows if row["partition"] == "uncertainty_calibration"]

    matrix = xgboost.DMatrix(numpy.array([features(r) for r in test], dtype=float))
    xgb_corrections = booster.predict(matrix)
    linear_corrections = linear_predict(test)

    xgb_summary = mission_summary(test, xgb_corrections)
    linear_summary = mission_summary(test, linear_corrections)
    physics_summary = mission_summary(test, [0.0] * len(test))

    # 3. Recompute the reported metrics.
    reported = evaluation["physics_plus_xgboost"]
    if abs(reported["mission_mae_wh"] - xgb_summary["mae"]) > 1e-6:
        errors.append("XGBoost held-out mission MAE does not reconcile")
    if abs(evaluation["physics_plus_linear"]["mission_mae_wh"] - linear_summary["mae"]) > 1e-6:
        errors.append("linear held-out mission MAE does not reconcile")
    if abs(evaluation["physics_only"]["mission_mae_wh"] - physics_summary["mae"]) > 1e-6:
        errors.append("physics-only held-out mission MAE does not reconcile")
    if reported["bounds_rejections"] != xgb_summary["rejected"]:
        errors.append("bounds rejection count does not reconcile")
    if reported["missions"] != len(xgb_summary["missions"]):
        errors.append("held-out mission count does not reconcile")

    improvement = 1.0 - xgb_summary["mae"] / physics_summary["mae"]
    if abs(evaluation["mission_mae_improvement_fraction_xgboost_vs_physics"] - improvement) > 1e-4:
        errors.append("improvement fraction does not reconcile")

    # 4. Coverage of the frozen allowances on the held-out partition.
    allow_c = frozen["uncertainty_calibration"]["allowance_learned_wh"]
    allow_b = frozen["uncertainty_calibration"]["allowance_physics_fallback_wh"]
    covered_c = sum(1 for m in xgb_summary["missions"].values() if m["obs"] <= m["pred"] + allow_c)
    covered_b = sum(1 for m in physics_summary["missions"].values()
                    if m["obs"] <= m["pred"] + allow_b)
    if evaluation["upper_estimate_coverage"]["learned_mode"]["covered"] != covered_c:
        errors.append("learned-mode coverage does not reconcile")
    if evaluation["upper_estimate_coverage"]["physics_fallback"]["covered"] != covered_b:
        errors.append("physics-fallback coverage does not reconcile")

    # 5. The frozen allowances must equal the calibration-partition quantiles.
    calib_matrix = xgboost.DMatrix(numpy.array([features(r) for r in calibration], dtype=float))
    calib_summary = mission_summary(calibration, booster.predict(calib_matrix))
    calib_errors = sorted(abs(m["pred"] - m["obs"]) for m in calib_summary["missions"].values())
    if abs(allow_c - quantile_higher(calib_errors, 0.95)) > 1e-6:
        errors.append("learned-mode allowance does not reconcile with the calibration partition")

    # 6. Optional byte-identical retraining check.
    if args.retrain:
        import shutil
        import subprocess
        import sys
        shutil.rmtree("/tmp/stage3b-retrain", ignore_errors=True)
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "train_stage3b.py"),
             "--dataset", str(args.dataset), "--output", "/tmp/stage3b-retrain",
             "--seed", str(frozen["training"]["seed"])],
            capture_output=True, text=True)
        if result.returncode != 0:
            errors.append("retraining failed")
        elif digest(Path("/tmp/stage3b-retrain/xgb-model.json")) != frozen["xgb_model_sha256"]:
            errors.append("retrained model artifact is not byte-identical")
        elif json.loads((Path("/tmp/stage3b-retrain/release.json")).read_text())["frozen_sha256"] \
                != release["frozen_sha256"]:
            errors.append("retrained frozen release hash differs")

    report = {
        "status": "FAIL" if errors else "PASS",
        "errors": errors,
        "held_out_missions": len(xgb_summary["missions"]),
        "recomputed": {
            "physics_only_mission_mae_wh": round(physics_summary["mae"], 8),
            "physics_plus_linear_mission_mae_wh": round(linear_summary["mae"], 8),
            "physics_plus_xgboost_mission_mae_wh": round(xgb_summary["mae"], 8),
            "improvement_fraction_vs_physics": round(improvement, 6),
            "bounds_rejections": xgb_summary["rejected"],
            "learned_mode_coverage": f"{covered_c}/{len(xgb_summary['missions'])}",
            "physics_fallback_coverage": f"{covered_b}/{len(physics_summary['missions'])}",
        },
        "retrained_identical": bool(args.retrain) and not any("retrain" in e for e in errors),
        "scope": "independent reload-and-recompute audit of the frozen Stage 3B release over "
                 "the Stage 3A dataset; modeled energy only",
    }
    (args.release_dir / "stage3b-audit.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    raise SystemExit(report["status"] != "PASS")


if __name__ == "__main__":
    main()
