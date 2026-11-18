#!/usr/bin/env python3
"""Unit tests for the Stage 3C predictor, client validation, and fallback."""
import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/energy-predictor"))
sys.path.insert(0, str(ROOT / "scripts/warehouse-energy"))

from predictor import InputError, EnergyPredictor, validate_request  # noqa: E402
from energy_serving_client import (EnergyServingClient, EnergyServingError,  # noqa: E402
                                   local_physics)

DATASET = ROOT / "docs/validation/warehouse-energy/phase-3a/dataset/segments.jsonl"
RELEASE = ROOT / "config/warehouse-energy/energy-model-release-v1"
PHYSICS = ROOT / "config/warehouse-energy/physics-model-v1.json"

BASE_SEGMENT = {"length_m": 10.0, "ramp_run_m": 10.0, "signed_rise_m": 0.2,
                "speed_mps": 0.1, "heading_change_rad": 0.0, "planned_stops": 0,
                "planned_dwell_s": 13.5, "total_mass_kg": 2.153, "class": "nav"}


def base_request(**overrides):
    request = {"schema": "energy-prediction/v1", "request_id": "r1",
               "robot": {"config": "warehouse-bounded-differential-drive-v1"},
               "graph_version": "warehouse-fixture-v1",
               "model_version": "energy-predictor-v1",
               "planning_generation": "g1", "segments": [dict(BASE_SEGMENT)]}
    request.update(overrides)
    return request


def make_predictor():
    predictor = object.__new__(EnergyPredictor)
    import physics_model as shared
    predictor.physics = shared.PhysicsModel(json.loads(PHYSICS.read_text()))
    predictor.xgboost = None
    predictor.booster = None
    return predictor


class ValidateTest(unittest.TestCase):
    def test_valid_request(self):
        self.assertEqual(len(validate_request(base_request())), 1)

    def test_wrong_model_version(self):
        with self.assertRaises(InputError):
            validate_request(base_request(model_version="energy-predictor-v0"))

    def test_wrong_graph_version(self):
        with self.assertRaises(InputError):
            validate_request(base_request(graph_version="other"))

    def test_unsupported_robot(self):
        with self.assertRaises(InputError):
            validate_request(base_request(robot={"config": "some-other-robot"}))

    def test_oversized_batch(self):
        with self.assertRaises(InputError):
            validate_request(base_request(segments=[dict(BASE_SEGMENT)] * 33))

    def test_out_of_envelope_segment(self):
        segment = dict(BASE_SEGMENT, speed_mps=0.5)
        with self.assertRaises(InputError):
            validate_request(base_request(segments=[segment]))

    def test_level_segment_with_rise_rejected(self):
        segment = dict(BASE_SEGMENT, ramp_run_m=None, signed_rise_m=0.1)
        with self.assertRaises(InputError):
            validate_request(base_request(segments=[segment]))

    def test_ramp_segment_without_rise_rejected(self):
        segment = dict(BASE_SEGMENT, signed_rise_m=0.0)
        with self.assertRaises(InputError):
            validate_request(base_request(segments=[segment]))


class DeriveParityTest(unittest.TestCase):
    def test_nav_dataset_rows_reproduce_exactly(self):
        if not DATASET.exists():
            self.skipTest("dataset not present")
        predictor = make_predictor()
        fixture = json.loads((ROOT / "config/warehouse-energy/fixture-v1.json").read_text())
        nodes = fixture["geometry"]["nodes"]
        rows = [json.loads(line) for line in DATASET.open()]
        runs = {}
        for row in rows:
            if row["class"] == "nav":
                runs.setdefault(row["run_id"], []).append(row)
        checked = 0
        for run_id in sorted(runs):
            segments = sorted(runs[run_id], key=lambda r: r["segment_index"])
            path = [segments[0]["segment_name"].split("->")[0]]
            path += [s["segment_name"].split("->")[1] for s in segments]
            headings = [math.atan2(nodes[b][1] - nodes[a][1], nodes[b][0] - nodes[a][0])
                        for a, b in zip(path, path[1:])]
            for index, row in enumerate(segments):
                start, end = row["segment_name"].split("->")
                change = 0.0 if index == 0 else abs(math.atan2(
                    math.sin(headings[index] - headings[index - 1]),
                    math.cos(headings[index] - headings[index - 1])))
                raw = {"length_m": math.dist(nodes[start][:2], nodes[end][:2]),
                       "ramp_run_m": row["ramp_run_m"],
                       "signed_rise_m": nodes[end][2] - nodes[start][2],
                       "speed_mps": row["speed_mps"], "heading_change_rad": change,
                       "planned_stops": 0, "planned_dwell_s": row["planned_dwell_s"],
                       "total_mass_kg": row["total_mass_kg"], "class": "nav"}
                derived = predictor.derive(raw)
                expected = [row["length_m"], row["ramp_run_m"] or 0.0, row["ascent_m"],
                            row["descent_m"], row["max_abs_grade"], row["mean_grade"],
                            abs(row["heading_change_rad"]), row["speed_mps"],
                            row["planned_stops_in_segment"], row["planned_dwell_s"],
                            row["total_mass_kg"], row["physics_wh"],
                            row["planned_duration_s"], 1.0]
                self.assertEqual(derived["features"], expected, f"{run_id} {row['segment_name']}")
                self.assertEqual(derived["physics_wh"], row["physics_wh"])
                checked += 1
        self.assertGreater(checked, 90)


class ClientTest(unittest.TestCase):
    def setUp(self):
        self.predictor = make_predictor()
        self.frozen = json.loads((RELEASE / "release.json").read_text())["frozen"]
        self.identity = {"model_name": "energy-predictor-v1",
                         "frozen_sha256": self.frozen["xgb_model_sha256"],  # arbitrary fixed
                         "xgb_model_sha256": self.frozen["xgb_model_sha256"],
                         "physics_model_sha256": "0" * 64}
        self.client = EnergyServingClient(
            "https://192.0.2.1:8443", "/nonexistent.crt", "/nonexistent.key",
            "/nonexistent.ca", self.identity, self.predictor.derive,
            fallback_allowance_wh=0.037, learned_allowance_wh=0.0047)

    def good_response(self, **overrides):
        response = {"schema": "energy-prediction/v1", "status": "ok", "request_id": "r1",
                    "planning_generation": "g1", "model_version": "energy-predictor-v1",
                    "deployment": dict(self.identity),
                    "allowances": {"learned_wh": 0.0047, "physics_fallback_wh": 0.037},
                    "segments": [{"physics_wh": 0.1, "residual_wh": -0.01,
                                  "predicted_wh": 0.09, "planned_duration_s": 100.0,
                                  "bounds_rejected": False}]}
        response.update(overrides)
        return response

    def test_validator_accepts_good_response(self):
        self.client.validate_response(self.good_response(), "r1", "g1", 1)

    def test_validator_rejects_faults(self):
        cases = {
            "stale_generation": self.good_response(planning_generation="g0"),
            "request_mismatch": self.good_response(request_id="other"),
            "wrong_version": self.good_response(model_version="v0"),
            "wrong_sha": self.good_response(
                deployment=dict(self.identity, frozen_sha256="1" * 64)),
            "count": self.good_response(segments=[]),
            "non_finite": self.good_response(
                segments=[{"physics_wh": 0.1, "residual_wh": 0.0,
                           "predicted_wh": None, "planning_duration_s": 1.0,
                           "bounds_rejected": False}]),
            "allowance": self.good_response(
                allowances={"learned_wh": 0.0047, "physics_fallback_wh": 0.0}),
            "status": self.good_response(status="error"),
        }
        for name, payload in cases.items():
            with self.assertRaises(EnergyServingError, msg=name):
                self.client.validate_response(payload, "r1", "g1", 1)

    def test_unreachable_endpoint_falls_back_to_physics(self):
        result = self.client.predict_batch([dict(BASE_SEGMENT)], "g-fallback")
        self.assertEqual(result["mode"], "fallback")
        expected = self.predictor.derive(BASE_SEGMENT)
        self.assertAlmostEqual(result["segments"][0]["predicted_wh"],
                               expected["physics_wh"], places=9)
        self.assertEqual(result["segments"][0]["residual_wh"], 0.0)
        self.assertEqual(result["allowances"]["physics_fallback_wh"], 0.037)

    def test_local_physics_matches_derive(self):
        results = local_physics(self.predictor.derive, [dict(BASE_SEGMENT)])
        derived = self.predictor.derive(BASE_SEGMENT)
        self.assertEqual(results[0]["physics_wh"], derived["physics_wh"])
        self.assertFalse(results[0]["bounds_rejected"])


if __name__ == "__main__":
    unittest.main()
