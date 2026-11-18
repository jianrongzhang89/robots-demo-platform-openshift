#!/usr/bin/env python3
"""Unit tests for the Stage 3B trainer and audit (XGBoost parts skip if absent)."""
import json
import math
import unittest
from pathlib import Path

import numpy

from train_stage3b import (FEATURES, Ridge, apply_bounds, feature_vector,
                           mission_metrics, quantile_higher)

try:
    import xgboost
    HAS_XGB = True
except ImportError:
    HAS_XGB = False

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "docs/validation/warehouse-energy/phase-3a/dataset"


def segment_row(**overrides):
    row = {"run_id": "r", "partition": "residual_train", "class": "nav",
           "length_m": 10.0, "ramp_run_m": 10.0, "ascent_m": 0.2, "descent_m": 0.0,
           "max_abs_grade": 0.02, "mean_grade": 0.02, "heading_change_rad": 1.5708,
           "speed_mps": 0.1, "planned_stops_in_segment": 0, "planned_dwell_s": 13.5,
           "total_mass_kg": 2.153, "physics_wh": 0.32, "planned_duration_s": 105.0,
           "observed_wh": 0.30, "residual_wh": -0.02}
    row.update(overrides)
    return row


class FeatureTest(unittest.TestCase):
    def test_feature_vector_order_and_values(self):
        row = segment_row(ramp_run_m=None, heading_change_rad=-0.5)
        vector = feature_vector(row)
        self.assertEqual([name for name, _ in FEATURES][0], "length_m")
        self.assertEqual(vector[FEATURES.index(("ramp_run_m", FEATURES[1][1]))], 0.0)
        turn_index = [name for name, _ in FEATURES].index("turn_rad")
        self.assertAlmostEqual(vector[turn_index], 0.5, places=6)
        is_nav_index = [name for name, _ in FEATURES].index("is_nav")
        self.assertEqual(vector[is_nav_index], 1.0)
        self.assertEqual(len(vector), len(FEATURES))


class BoundsTest(unittest.TestCase):
    def test_normal_correction(self):
        combined, rejected = apply_bounds(0.30, -0.02)
        self.assertAlmostEqual(combined, 0.28)
        self.assertFalse(rejected)

    def test_negative_combined_rejected(self):
        combined, rejected = apply_bounds(0.05, -0.20)
        self.assertEqual(combined, 0.05)
        self.assertTrue(rejected)

    def test_oversized_correction_rejected(self):
        combined, rejected = apply_bounds(0.05, 0.30)
        self.assertEqual(combined, 0.05)
        self.assertTrue(rejected)


class QuantileTest(unittest.TestCase):
    def test_higher_interpolation(self):
        values = [0.1] * 10 + [1.0]
        self.assertEqual(quantile_higher(values, 0.95), 1.0)
        self.assertEqual(quantile_higher([0.5], 0.95), 0.5)
        self.assertEqual(quantile_higher([], 0.95), 0.0)

    def test_ceiling_index(self):
        values = list(range(1, 21))  # 1..20; 95th percentile with 'higher' is 19
        self.assertEqual(quantile_higher(values, 0.95), 19)


class RidgeTest(unittest.TestCase):
    def test_recovers_linear_relation(self):
        rows = []
        for i in range(40):
            value = 0.01 * (i % 10)
            rows.append(segment_row(run_id=f"r{i}", physics_wh=0.2 + value,
                                    residual_wh=-0.05 + 2.0 * value))
        ridge = Ridge(1e-6).fit(rows)
        predictions = ridge.predict(rows)
        for row, prediction in zip(rows, predictions):
            self.assertAlmostEqual(prediction, row["residual_wh"], delta=1e-4)
        exported = ridge.export()
        self.assertEqual(len(exported["weights"]), len(FEATURES) + 1)

    def test_lambda_selection_prefers_stability(self):
        # Identical rows with identical residuals: lambda=1.0 shrinks the
        # constant slightly but every prediction is identical.
        rows = [segment_row(run_id=f"r{i}") for i in range(10)]
        ridge = Ridge(1.0).fit(rows)
        predictions = list(ridge.predict(rows))
        for prediction in predictions:
            self.assertAlmostEqual(prediction, predictions[0], delta=1e-12)
        self.assertAlmostEqual(predictions[0], -0.02, delta=1e-3)


class MissionMetricsTest(unittest.TestCase):
    def test_aggregation_and_bounds(self):
        rows = [segment_row(run_id="m1", physics_wh=0.3, observed_wh=0.28),
                segment_row(run_id="m1", physics_wh=0.2, observed_wh=0.22),
                segment_row(run_id="m2", physics_wh=0.1, observed_wh=0.25)]
        corrections = [-0.02, 0.05, -0.50]  # third is oversized -> rejected
        metrics = mission_metrics(rows, corrections)
        self.assertEqual(metrics["missions"], 2)
        self.assertEqual(metrics["bounds_rejections"], 1)
        # m1: |(0.3-0.02+0.2+0.05) - 0.5| = 0.03; m2: |0.1-0.25| = 0.15
        self.assertAlmostEqual(metrics["mission_mae_wh"], (0.03 + 0.15) / 2, places=8)


@unittest.skipUnless(HAS_XGB and DATASET.exists(), "xgboost or dataset not available")
class TrainingSmokeTest(unittest.TestCase):
    def test_train_on_real_dataset_is_deterministic(self):
        import train_stage3b
        rows = [json.loads(line) for line in (DATASET / "segments.jsonl").open()]
        train = [r for r in rows if r["partition"] == "residual_train"]
        hyper = {"max_depth": 2, "n_estimators": 20, "learning_rate": 0.1,
                 "min_child_weight": 1}
        first = train_stage3b.train_xgb(train, hyper, 17)
        second = train_stage3b.train_xgb(train, hyper, 17)
        probe = train[:10]
        for a, b in zip(train_stage3b.predict(first, probe),
                        train_stage3b.predict(second, probe)):
            self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
