#!/usr/bin/env python3
"""Train and freeze the Stage 3B residual energy model (offline, CPU).

Trains a small XGBoost regressor on the Stage 3A residual target
(observed Wh minus frozen physics Wh) using only planning-time features,
selects bounded hyperparameters on the development partition by
mission-energy MAE, and compares against a ridge linear-residual
correction trained on the same features. Mission-level uncertainty
allowances for both the learned mode and the physics fallback are
calibrated on the separate uncertainty-calibration partition.

The release is frozen and hash-recorded before the held-out final-test
partition is read; the test is opened exactly once, after freezing. The
combined estimate is validated against physical bounds (nonnegative
energy; correction magnitude within the physics estimate) with fallback
to physics on violation.
"""
import argparse
import hashlib
import json
import math
import platform
import sys
from pathlib import Path

import numpy

try:
    import xgboost
except ImportError:  # training runs in the pinned pod; local hosts may omit it
    xgboost = None

SEED = 17
FEATURES = [
    ("length_m", lambda r: float(r["length_m"])),
    ("ramp_run_m", lambda r: float(r["ramp_run_m"] or 0.0)),
    ("ascent_m", lambda r: float(r["ascent_m"])),
    ("descent_m", lambda r: float(r["descent_m"])),
    ("max_abs_grade", lambda r: float(r["max_abs_grade"])),
    ("mean_grade", lambda r: float(r["mean_grade"])),
    ("turn_rad", lambda r: abs(float(r["heading_change_rad"]))),
    ("speed_mps", lambda r: float(r["speed_mps"])),
    ("planned_stops_in_segment", lambda r: float(r["planned_stops_in_segment"])),
    ("planned_dwell_s", lambda r: float(r["planned_dwell_s"])),
    ("total_mass_kg", lambda r: float(r["total_mass_kg"])),
    ("physics_wh", lambda r: float(r["physics_wh"])),
    ("planned_duration_s", lambda r: float(r["planned_duration_s"])),
    ("is_nav", lambda r: 1.0 if r["class"] == "nav" else 0.0),
]

HYPERGRID = {"max_depth": [2, 3, 4], "n_estimators": [40, 80, 160],
             "learning_rate": [0.05, 0.1], "min_child_weight": [1, 5]}
RIDGE_LAMBDAS = [1e-6, 1e-3, 1e-1, 1.0, 10.0]


def feature_vector(row):
    return [extract(row) for _, extract in FEATURES]


def load(dataset):
    rows = [json.loads(line) for line in (dataset / "segments.jsonl").open()]
    runs = [json.loads(line) for line in (dataset / "runs.jsonl").open()]
    return rows, runs


def partition_rows(rows, partition):
    return [row for row in rows if row["partition"] == partition]


def mission_table(rows):
    """Group segment rows into missions keyed by run."""
    missions = {}
    for row in rows:
        mission = missions.setdefault(row["run_id"], {"observed_wh": 0.0, "physics_wh": 0.0,
                                                      "class": row["class"], "n": 0})
        mission["observed_wh"] += float(row["observed_wh"])
        mission["physics_wh"] += float(row["physics_wh"])
        mission["n"] += 1
    return missions


def apply_bounds(physics_wh, correction):
    """Physical-bound validation; returns (combined_wh, rejected)."""
    combined = physics_wh + correction
    if combined < 0.0 or abs(correction) > physics_wh:
        return physics_wh, True
    return combined, False


def mission_metrics(rows, corrections):
    """Mission MAE with the frozen bounds rule applied per segment."""
    missions = {}
    rejected = 0
    for row, correction in zip(rows, corrections):
        combined, was_rejected = apply_bounds(float(row["physics_wh"]), float(correction))
        rejected += int(was_rejected)
        mission = missions.setdefault(row["run_id"], {"pred": 0.0, "obs": 0.0})
        mission["pred"] += combined
        mission["obs"] += float(row["observed_wh"])
    errors = [abs(m["pred"] - m["obs"]) for m in missions.values()]
    mae = sum(errors) / len(errors) if errors else 0.0
    segment_errors = [abs(float(row["physics_wh"]) + c - float(row["observed_wh"]))
                      for row, c in zip(rows, corrections)]
    return {"mission_mae_wh": round(mae, 8),
            "segment_mae_wh": round(sum(segment_errors) / len(segment_errors), 8) if rows else 0.0,
            "missions": len(missions), "bounds_rejections": rejected,
            "max_mission_abs_error_wh": round(max(errors), 8) if errors else 0.0}


def train_xgb(train_rows, hyper, seed):
    """Native xgboost training (no sklearn dependency in the pinned pod)."""
    if xgboost is None:
        raise RuntimeError("xgboost is required for training (pinned pod environment)")
    matrix = xgboost.DMatrix(numpy.array([feature_vector(r) for r in train_rows], dtype=float),
                             label=numpy.array([float(r["residual_wh"]) for r in train_rows],
                                               dtype=float))
    params = {"objective": "reg:squarederror", "tree_method": "hist", "nthread": 1,
              "seed": seed, "max_depth": hyper["max_depth"],
              "learning_rate": hyper["learning_rate"],
              "min_child_weight": hyper["min_child_weight"]}
    return xgboost.train(params, matrix, num_boost_round=hyper["n_estimators"])


def predict(model, rows):
    return model.predict(xgboost.DMatrix(
        numpy.array([feature_vector(r) for r in rows], dtype=float)))

class Ridge:
    """Ridge regression on standardized features (closed form)."""

    def __init__(self, lam):
        self.lam = lam

    def fit(self, rows):
        x = numpy.array([feature_vector(r) for r in rows], dtype=float)
        y = numpy.array([float(r["residual_wh"]) for r in rows], dtype=float)
        self.mean = x.mean(axis=0)
        self.scale = x.std(axis=0)
        self.scale[self.scale == 0] = 1.0
        z = (x - self.mean) / self.scale
        design = numpy.hstack([z, numpy.ones((len(rows), 1))])
        gram = design.T @ design + self.lam * numpy.eye(design.shape[1])
        self.weights = numpy.linalg.solve(gram, design.T @ y)
        return self

    def predict(self, rows):
        x = numpy.array([feature_vector(r) for r in rows], dtype=float)
        z = (x - self.mean) / self.scale
        design = numpy.hstack([z, numpy.ones((len(rows), 1))])
        return design @ self.weights

    def export(self):
        return {"lambda": self.lam,
                "mean": [round(float(v), 10) for v in self.mean],
                "scale": [round(float(v), 10) for v in self.scale],
                "weights": [round(float(v), 10) for v in self.weights]}


def quantile_higher(values, q):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1)
    index = max(0, index)
    return ordered[index]


def allowance(missions_rows, corrections):
    """Mission-level absolute Wh allowance at nominal 95% coverage."""
    errors = []
    by_run = {}
    for row, correction in zip(missions_rows, corrections):
        combined, _ = apply_bounds(float(row["physics_wh"]), float(correction))
        mission = by_run.setdefault(row["run_id"], {"pred": 0.0, "obs": 0.0})
        mission["pred"] += combined
        mission["obs"] += float(row["observed_wh"])
    errors = [abs(m["pred"] - m["obs"]) for m in by_run.values()]
    return quantile_higher(errors, 0.95), len(errors)


def canonical(document):
    return json.dumps(document, sort_keys=True, separators=(",", ":"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rows, runs = load(args.dataset)
    train = partition_rows(rows, "residual_train")
    dev = partition_rows(rows, "development")
    calibration = partition_rows(rows, "uncertainty_calibration")
    test = partition_rows(rows, "final_test")
    if not train or not dev or not calibration or not test:
        raise SystemExit("dataset partitions missing")

    # 1. Hyperparameter selection on the development partition only.
    candidates = []
    for depth in HYPERGRID["max_depth"]:
        for estimators in HYPERGRID["n_estimators"]:
            for rate in HYPERGRID["learning_rate"]:
                for weight in HYPERGRID["min_child_weight"]:
                    hyper = {"max_depth": depth, "n_estimators": estimators,
                             "learning_rate": rate, "min_child_weight": weight}
                    model = train_xgb(train, hyper, args.seed)
                    metrics = mission_metrics(dev, predict(model, dev))
                    candidates.append((metrics["mission_mae_wh"], -estimators, -depth, hyper))
    candidates.sort(key=lambda candidate: candidate[:3])
    best_hyper = candidates[0][3]
    xgb_model = train_xgb(train, best_hyper, args.seed)
    dev_metrics_xgb = mission_metrics(dev, predict(xgb_model, dev))

    linear_candidates = []
    for lam in RIDGE_LAMBDAS:
        ridge = Ridge(lam).fit(train)
        metrics = mission_metrics(dev, ridge.predict(dev))
        linear_candidates.append((metrics["mission_mae_wh"], lam))
    linear_candidates.sort()
    linear_model = Ridge(linear_candidates[0][1]).fit(train)
    dev_metrics_linear = mission_metrics(dev, linear_model.predict(dev))

    # 2. Uncertainty calibration on its separate partition.
    calib_rows = calibration
    allowance_c, calib_missions = allowance(calib_rows, predict(xgb_model, calib_rows))
    allowance_b, _ = allowance(calib_rows, [0.0 for _ in calib_rows])
    allowance_linear, _ = allowance(calib_rows, linear_model.predict(calib_rows))

    # 3. Freeze the release before reading the test partition.
    model_path = args.output / "xgb-model.json"
    xgb_model.save_model(str(model_path))
    (args.output / "linear-model.json").write_text(json.dumps(linear_model.export(), indent=2) + "\n")
    frozen = {
        "schema_version": "warehouse-energy-model-release-v1",
        "status": "frozen_for_stage_3c_serving",
        "target": "residual_target_Wh = observed_segment_Wh - physics_segment_Wh",
        "feature_schema": {"names": [name for name, _ in FEATURES],
                           "note": "planning-time features only; baseline physics Wh and planned "
                                   "duration are inputs by design"},
        "dataset": {"segments_sha256": hashlib.sha256(
                        (args.dataset / "segments.jsonl").read_bytes()).hexdigest(),
                    "manifest": "warehouse-stage3-dataset-v1 partitions"},
        "xgboost_hyperparameters": best_hyper,
        "linear_model": linear_model.export(),
        "uncertainty_calibration": {
            "method": "mission-level absolute Wh allowance; empirical 95th percentile "
                      "(higher interpolation) of mission absolute error on the "
                      "uncertainty-calibration partition",
            "calibration_missions": calib_missions,
            "allowance_learned_wh": round(allowance_c, 8),
            "allowance_physics_fallback_wh": round(allowance_b, 8),
            "allowance_linear_wh": round(allowance_linear, 8),
            "small_sample_caveat": "13 calibration missions; the empirical 95th percentile has "
                                   "finite-sample coverage below the nominal 95 percent",
        },
        "bounds_rule": "combined = physics + correction; reject to physics fallback when "
                       "combined < 0 or |correction| > physics Wh",
        "training": {"seed": args.seed, "n_jobs": 1, "selection_objective":
                     "development-partition mission-energy MAE",
                     "hypergrid": HYPERGRID, "ridge_lambdas": RIDGE_LAMBDAS},
        "environment": {"python": platform.python_version(),
                        "xgboost": xgboost.__version__ if xgboost else None,
                        "numpy": numpy.__version__},
        "xgb_model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "linear_model_sha256": hashlib.sha256(
            (args.output / "linear-model.json").read_bytes()).hexdigest(),
        "scope_limits": [
            "Simulation-trained for the frozen warehouse fixture, robot, payloads, and "
            "surfaces; not valid across robots, battery systems, or physical facilities.",
            "Labels are modeled energy under the frozen Phase 1 accounting assumptions, not "
            "physical battery measurements.",
        ],
    }
    frozen_sha = hashlib.sha256(canonical(frozen).encode()).hexdigest()

    # 4. Open the held-out test partition exactly once.
    test_corrections_xgb = predict(xgb_model, test)
    test_metrics_xgb = mission_metrics(test, test_corrections_xgb)
    test_metrics_linear = mission_metrics(test, linear_model.predict(test))
    test_metrics_physics = mission_metrics(test, [0.0 for _ in test])

    def coverage(rows, corrections, value_allowance):
        by_run = {}
        for row, correction in zip(rows, corrections):
            combined, _ = apply_bounds(float(row["physics_wh"]), float(correction))
            mission = by_run.setdefault(row["run_id"], {"pred": 0.0, "obs": 0.0})
            mission["pred"] += combined
            mission["obs"] += float(row["observed_wh"])
        covered = sum(1 for m in by_run.values()
                      if m["obs"] <= m["pred"] + value_allowance)
        return covered, len(by_run)

    covered_c, n_c = coverage(test, test_corrections_xgb, allowance_c)
    covered_b, n_b = coverage(test, [0.0 for _ in test], allowance_b)
    evaluation = {
        "held_out_partition": "final_test (scripted payload 0.25 kg and navigation "
                              "route-B-up-at-0.08 m/s combinations)",
        "test_missions": n_c,
        "physics_only": test_metrics_physics,
        "physics_plus_linear": test_metrics_linear,
        "physics_plus_xgboost": test_metrics_xgb,
        "mission_mae_improvement_fraction_linear_vs_physics": round(
            1.0 - test_metrics_linear["mission_mae_wh"] / test_metrics_physics["mission_mae_wh"], 8),
        "mission_mae_improvement_fraction_xgboost_vs_physics": round(
            1.0 - test_metrics_xgb["mission_mae_wh"] / test_metrics_physics["mission_mae_wh"], 8),
        "upper_estimate_coverage": {
            "learned_mode": {"covered": covered_c, "missions": n_c,
                             "fraction": round(covered_c / n_c, 4)},
            "physics_fallback": {"covered": covered_b, "missions": n_b,
                                 "fraction": round(covered_b / n_b, 4)},
        },
        "development_selection_metrics": {
            "xgboost": dev_metrics_xgb, "linear": dev_metrics_linear,
            "selected_hyperparameters": best_hyper,
            "selected_ridge_lambda": linear_model.lam},
        "test_opened_once_after_freeze": True,
    }
    release = {"frozen": frozen, "frozen_sha256": frozen_sha, "evaluation": evaluation}
    (args.output / "release.json").write_text(json.dumps(release, indent=2) + "\n")
    (args.output / "evaluation.json").write_text(json.dumps(evaluation, indent=2) + "\n")
    print(json.dumps({"frozen_sha256": frozen_sha,
                      "selected_hyperparameters": best_hyper,
                      "selected_ridge_lambda": linear_model.lam,
                      "test": {k: evaluation[k] for k in
                               ["physics_only", "physics_plus_linear", "physics_plus_xgboost",
                                "mission_mae_improvement_fraction_xgboost_vs_physics",
                                "upper_estimate_coverage"]}}))


if __name__ == "__main__":
    main()
