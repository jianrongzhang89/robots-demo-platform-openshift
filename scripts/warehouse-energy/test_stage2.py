#!/usr/bin/env python3
"""Unit tests for the Stage 2 physics model, calibration, and route selector."""
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

from physics_model import PhysicsModel, ramp_height, predict_path
import calibrate_physics
import route_selector

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT / "config/warehouse-energy/fixture-v1.json").read_text())


def model_with(crr=0.003, eta=0.6, aux=10.0):
    return PhysicsModel({
        "parameters": {"rolling_resistance_coefficient": crr, "drive_efficiency": eta,
                       "auxiliary_power_w": aux},
        "planning_assumptions": {"speed_cap_mps": 0.1, "acceleration_cap_mps2": 0.1,
                                 "goal_transition_base_s": 13.5,
                                 "rotate_to_heading_angular_vel_rad_s": 0.3},
    })


class PhysicsModelTest(unittest.TestCase):
    def test_flat_cruise_matches_force_balance(self):
        model = model_with(crr=0.01, eta=0.5, aux=10.0)
        mass = 2.0
        duration = 10.0
        speed = 0.1
        samples = [(0.1, speed, 0.0, 1.0, 0.0)] * 100
        result = model.integrate(samples, mass)
        expected_traction = 0.01 * mass * 9.80665 * speed * duration
        self.assertAlmostEqual(result["traction_j"], expected_traction, places=6)
        self.assertAlmostEqual(result["electrical_j"],
                               expected_traction / 0.5 + 10.0 * duration, places=6)

    def test_uphill_adds_gravity_and_downhill_clips(self):
        model = model_with(crr=0.0, eta=1.0, aux=0.0)
        mass = 2.0
        up = model.integrate([(1.0, 0.1, 0.5, math.sqrt(0.75), 0.0)], mass)
        self.assertAlmostEqual(up["traction_j"], mass * 9.80665 * 0.5 * 0.1, places=6)
        # Steeper downhill than rolling resistance: no regeneration credit.
        down = model.integrate([(1.0, 0.1, -0.5, math.sqrt(0.75), 0.0)], mass)
        self.assertEqual(down["traction_j"], 0.0)
        self.assertEqual(down["electrical_j"], 0.0)

    def test_stop_to_stop_duration_and_distance(self):
        model = model_with()
        length = 14.0
        samples = model.stop_to_stop(length, lambda u: 0.0)
        duration = sum(s[0] for s in samples)
        distance = sum(s[1] * s[0] for s in samples)
        self.assertAlmostEqual(distance, length, places=2)
        self.assertAlmostEqual(duration, length / 0.1 + 0.1 / 0.1, delta=0.2)
        self.assertLess(samples[-1][1], 0.01)  # at rest within the final half step

    def test_ramp_height_endpoints(self):
        self.assertEqual(ramp_height(0.0, 10.0, 0.2), 0.0)
        self.assertEqual(ramp_height(10.0, 10.0, 0.2), 0.2)
        self.assertAlmostEqual(ramp_height(5.0, 10.0, 0.2), 0.1, places=6)

    def test_predict_path_routes(self):
        model = model_with()
        nodes = FIXTURE["geometry"]["nodes"]
        edges = route_selector.ramp_edges(FIXTURE)
        a = predict_path(model, nodes, FIXTURE["geometry"]["routes"]["A"], edges, 2.153)
        b = predict_path(model, nodes, FIXTURE["geometry"]["routes"]["B"], edges, 2.153)
        self.assertAlmostEqual(a["distance_m"], 14.0, places=6)
        self.assertAlmostEqual(b["distance_m"], 42.0, places=6)
        # Route B is longer and must not predict lower energy than A here.
        self.assertGreater(b["wh"], a["wh"])
        self.assertGreater(b["duration_s"], a["duration_s"])
        # Duration: cruise + accel/decel + waypoint turns and overhead.
        self.assertAlmostEqual(a["duration_s"], 14 / 0.1 + 3 * 1.0 + 2 * 13.5, delta=1.0)
        expected_b = 42 / 0.1 + 5 * 1.0 + 4 * (math.pi / 2) / 0.3 + 4 * 13.5
        self.assertAlmostEqual(b["duration_s"], expected_b, delta=1.5)


class CalibrationTest(unittest.TestCase):
    def test_fit_recovers_synthetic_parameters(self):
        true = model_with(crr=0.003, eta=0.6, aux=10.0)
        runs = []
        for route, run_m in [("A", 10.0), ("B", 20.0)]:
            for direction in ["up", "down"]:
                for payload in [0.0, 0.5]:
                    design = {"run_m": run_m, "rise_m": 0.2, "direction": direction,
                              "end_x": run_m + 1.0 if direction == "up" else -1.0,
                              "payload_kg": payload}
                    profile = calibrate_physics.scripted_profile(design)
                    mass = FIXTURE["robot"]["physical_mass_kg"] + payload
                    observed = true.integrate(profile, mass)
                    runs.append({"profile": profile, "mass_kg": mass,
                                 "planned_duration_s": observed["duration_s"],
                                 "observed_wh": observed["wh"]})
        best = calibrate_physics.fit(runs)
        self.assertAlmostEqual(best["crr"], 0.003, delta=0.0004)
        self.assertAlmostEqual(1.0 / best["u_efficiency"], 0.6, delta=0.03)
        self.assertAlmostEqual(best["aux_w"], 10.0, delta=0.2)

    def test_scripted_profile_is_stationary_at_both_ends(self):
        design = {"run_m": 10.0, "rise_m": 0.2, "direction": "up", "end_x": 11.0}
        profile = calibrate_physics.scripted_profile(design)
        self.assertEqual(profile[0][1], 0.0)
        self.assertEqual(profile[-1][1], 0.0)
        # Phase 0 trials: 3 s settle, mid-ramp brake and hold, 4 s finish.
        duration = sum(s[0] for s in profile)
        self.assertAlmostEqual(duration, 132.9, delta=1.0)


class RouteSelectorTest(unittest.TestCase):
    def test_arm_a_and_b_select_shortest_and_minimum_energy(self):
        model = model_with()
        for arm in ["A", "B"]:
            decision = route_selector.select(model, FIXTURE, arm, 0.5, 0.8)
            self.assertEqual(decision["status"], "SELECTED")
            self.assertEqual(decision["selected_route"], "A")
            self.assertTrue(all(row["feasible"] for row in decision["routes"].values()))

    def test_exclusion_selects_route_b(self):
        model = model_with()
        decision = route_selector.select(model, FIXTURE, "B", 0.5, 0.8, excluded=("A",))
        self.assertEqual(decision["selected_route"], "B")
        self.assertIn("route excluded at planning time: A",
                      decision["routes"]["A"]["violations"])

    def test_low_soc_rejection_with_explicit_reason(self):
        model = model_with()
        decision = route_selector.select(model, FIXTURE, "B", 0.5, 0.22)
        self.assertEqual(decision["status"], "REJECTED")
        self.assertIsNone(decision["selected_route"])
        self.assertIn("below reserve", decision["rejection_reason"])
        for row in decision["routes"].values():
            self.assertFalse(row["feasible"])

    def test_charger_access_reduces_final_soc(self):
        model = model_with()
        decision = route_selector.select(model, FIXTURE, "B", 0.5, 0.8)
        route_a = decision["routes"]["A"]
        mission_only = 0.8 - route_a["predicted_mission_wh"] / 24.0
        self.assertGreater(route_a["predicted_final_soc"], 0.0)
        self.assertLess(route_a["predicted_final_soc"], mission_only)
        self.assertGreater(route_a["charger_access_wh"], 0.0)

    def test_hysteresis_blocks_small_switches(self):
        estimates = {
            "A": {"feasible": True, "predicted_mission_wh": 0.500},
            "B": {"feasible": True, "predicted_mission_wh": 0.480},
        }
        self.assertEqual(route_selector.should_switch("A", estimates, 0.05), "A")
        estimates["B"]["predicted_mission_wh"] = 0.400
        self.assertEqual(route_selector.should_switch("A", estimates, 0.05), "B")
        self.assertEqual(route_selector.should_switch("B", estimates, 0.05), "B")


class RejectionRunnerTest(unittest.TestCase):
    def test_infeasible_mission_is_rejected_without_motion(self):
        import run_stage2_trial
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "rejected"
            class Args:
                pass
            args = Args()
            args.source = Path("/nonexistent-source.world")
            args.fixture = ROOT / "config/warehouse-energy/fixture-v1.json"
            args.physics_model = ROOT / "config/warehouse-energy/physics-model-v1.json"
            args.output = output
            args.arm = "B"
            args.payload = 0.5
            args.initial_soc = 0.22
            args.exclude_route = []
            args.direction = "up"
            args.rtf = 3
            args.camera_width = 320
            args.camera_height = 240
            code = run_stage2_trial.run(args)
            self.assertEqual(code, 0)
            result = json.loads((output / "stage2-result.json").read_text())
            self.assertEqual(result["status"], "REJECTED")
            self.assertFalse(result["motion_started"])
            self.assertIn("below reserve", result["rejection_reason"])
            self.assertFalse((output / "energy.csv").exists())
            self.assertFalse((output / "result.json").exists())


if __name__ == "__main__":
    unittest.main()
