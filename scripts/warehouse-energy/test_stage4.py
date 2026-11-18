#!/usr/bin/env python3
"""Unit tests for the Stage 4 selector, order, statistics, and analyzer."""
import json
import math
import unittest
from pathlib import Path

from physics_model import PhysicsModel
import route_selector
from build_stage4_order import build_order
from analyze_stage4 import paired_summary, t_quantile_975

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT / "config/warehouse-energy/fixture-v1.json").read_text())
MODEL = PhysicsModel.load(ROOT / "config/warehouse-energy/physics-model-v1.json")
RELEASE = json.loads((ROOT / "config/warehouse-energy/energy-model-release-v1/release.json").read_text())
EXPERIMENT = json.loads((ROOT / "config/warehouse-energy/stage4-experiment-v1.json").read_text())
DATASET = ROOT / "docs/validation/warehouse-energy/phase-3a/dataset/segments.jsonl"
PHYSICS_ALLOWANCE = RELEASE["frozen"]["uncertainty_calibration"]["allowance_physics_fallback_wh"]


class StatisticsTest(unittest.TestCase):
    def test_t_quantile_matches_table(self):
        for df, expected in [(1, 12.706), (4, 2.776), (9, 2.262), (29, 2.045),
                             (59, 2.001), (120, 1.980)]:
            self.assertAlmostEqual(t_quantile_975(df), expected, places=3,
                                   msg=f"df={df}")

    def test_paired_summary_known(self):
        # Differences 1..10: mean 5.5, sd ~3.028, t(9)=2.262.
        summary = paired_summary([float(i) for i in range(1, 11)])
        self.assertEqual(summary["n"], 10)
        self.assertAlmostEqual(summary["mean"], 5.5, places=8)
        self.assertTrue(summary["ci95"][0] < 5.5 < summary["ci95"][1])
        half = t_quantile_975(9) * math.sqrt(sum((d - 5.5) ** 2 for d in range(1, 11)) / 9)
        half /= math.sqrt(10)
        self.assertAlmostEqual(summary["ci95"][1] - summary["mean"], half, places=6)

    def test_paired_summary_degenerate(self):
        self.assertIsNone(paired_summary([1.0])["mean"])


class OrderTest(unittest.TestCase):
    def test_frozen_order_shape(self):
        trials = build_order(EXPERIMENT)
        self.assertEqual(len(trials), 121)
        self.assertEqual(sum(1 for t in trials if t["kind"] == "oneway"), 91)
        self.assertEqual(sum(1 for t in trials if t["kind"].startswith("roundtrip")), 30)
        self.assertEqual(trials[-1]["name"], "fallback-armC-serving-unavailable")
        self.assertTrue(trials[-1]["serving_unavailable"])
        again = build_order(EXPERIMENT)
        self.assertEqual([t["name"] for t in trials], [t["name"] for t in again])
        # Every triplet contains exactly one trial per arm.
        groups = {}
        for trial in trials:
            if trial["name"].startswith("ow-"):
                groups.setdefault("-".join(trial["name"].split("-")[:4]), []).append(
                    trial["arm"])
        for arms in groups.values():
            self.assertEqual(sorted(arms), ["A", "B", "C"])

    def test_strata_coverage(self):
        trials = build_order(EXPERIMENT)
        strata = {(t["payload"], t["direction"]) for t in trials if t["kind"] == "oneway"}
        self.assertEqual(len(strata), 6)


class SegmentInputsTest(unittest.TestCase):
    def test_route_inputs_match_dataset_rows(self):
        if not DATASET.exists():
            self.skipTest("dataset not present")
        rows = [json.loads(line) for line in DATASET.open()]
        nav = [r for r in rows if r["class"] == "nav" and r["speed_mps"] == 0.1]
        checked = 0
        for direction in ("up", "down"):
            for route_name in ("A", "B"):
                path = FIXTURE["geometry"]["routes"][route_name]
                if direction == "down":
                    path = list(reversed(path))
                for payload in (0.0, 0.25, 0.5):
                    mass = FIXTURE["robot"]["physical_mass_kg"] + payload
                    segments = route_selector.route_segment_inputs(FIXTURE, path, payload)
                    candidates = [r for r in nav if r["total_mass_kg"] == mass
                                  and r["direction"] == direction
                                  and r["route"] == route_name]
                    if not candidates:
                        continue
                    run_id = candidates[0]["run_id"]
                    run_rows = sorted((r for r in candidates if r["run_id"] == run_id),
                                      key=lambda r: r["segment_index"])
                    for segment, row in zip(segments, run_rows):
                        self.assertAlmostEqual(segment["length_m"], row["length_m"], places=6)
                        self.assertEqual(segment["ramp_run_m"], row["ramp_run_m"])
                        self.assertAlmostEqual(segment["planned_dwell_s"],
                                               row["planned_dwell_s"], places=6)
                        checked += 1
        self.assertGreaterEqual(checked, 48)  # all 24 speed-0.10 navigation runs


class StubClient:
    def __init__(self, scale=0.99, fail=False):
        self.scale = scale
        self.fail = fail

    def predict_batch(self, segments, generation):
        if self.fail:
            raise RuntimeError("unreachable")
        from energy_serving_client import local_physics
        import sys
        sys.path.insert(0, str(ROOT / "apps/energy-predictor"))
        import predictor as predictor_module
        p = object.__new__(predictor_module.EnergyPredictor)
        p.physics = MODEL
        p.xgboost = None
        p.booster = None
        base = local_physics(p.derive, segments)
        for row in base:
            row["predicted_wh"] = round(row["physics_wh"] * self.scale, 9)
        return {"mode": "fallback" if self.fail else "served", "cached": False,
                "planning_generation": generation, "segments": base,
                "allowances": {"learned_wh": 0.0047, "physics_fallback_wh": 0.037}}


class SelectStage4Test(unittest.TestCase):
    def test_all_arms_select_route_a(self):
        for arm in ("A", "B", "C"):
            estimator = route_selector.ServedEstimator(StubClient(), FIXTURE) \
                if arm == "C" else None
            decision = route_selector.select_stage4(
                MODEL, FIXTURE, arm, 0.5, 0.8, physics_allowance_wh=PHYSICS_ALLOWANCE,
                estimator=estimator)
            self.assertEqual(decision["status"], "SELECTED", arm)
            self.assertEqual(decision["selected_route"], "A", arm)
            self.assertTrue(all(r["feasible"] for r in decision["routes"].values()))

    def test_arm_c_fallback_uses_physics_values(self):
        estimator = route_selector.ServedEstimator(StubClient(fail=False), FIXTURE)
        served = route_selector.select_stage4(MODEL, FIXTURE, "C", 0.5, 0.8,
                                              physics_allowance_wh=PHYSICS_ALLOWANCE,
                                              estimator=estimator)
        physics = route_selector.select_stage4(MODEL, FIXTURE, "B", 0.5, 0.8,
                                               physics_allowance_wh=PHYSICS_ALLOWANCE)
        self.assertAlmostEqual(served["routes"]["A"]["predicted_mission_wh"],
                               physics["routes"]["A"]["predicted_mission_wh"] * 0.99, places=6)
        self.assertEqual(served["routes"]["A"]["estimator_mode"], "served")

    def test_round_trip_selection_includes_both_legs(self):
        decision = route_selector.select_stage4(
            MODEL, FIXTURE, "B", 0.5, 0.8, round_trip_return_payload_kg=0.0,
            physics_allowance_wh=PHYSICS_ALLOWANCE)
        route = decision["routes"]["A"]
        self.assertAlmostEqual(route["round_trip_predicted_total_wh"],
                               route["predicted_mission_wh"] +
                               decision["routes"]["A"]["predicted_mission_wh"] * 0.75, delta=0.3)
        self.assertIsNotNone(route["round_trip_predicted_total_wh"])
        self.assertEqual(decision["selected_route"], "A")

    def test_low_soc_rejection(self):
        decision = route_selector.select_stage4(MODEL, FIXTURE, "C", 0.5, 0.21,
                                                physics_allowance_wh=PHYSICS_ALLOWANCE,
                                                estimator=route_selector.ServedEstimator(
                                                    StubClient(), FIXTURE))
        self.assertEqual(decision["status"], "REJECTED")
        self.assertIn("below reserve", decision["rejection_reason"])


if __name__ == "__main__":
    unittest.main()
