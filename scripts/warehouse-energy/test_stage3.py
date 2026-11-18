#!/usr/bin/env python3
"""Unit tests for the Stage 3A dataset builder, partitions, and audit."""
import json
import math
import shutil
import tempfile
import unittest
from pathlib import Path

from physics_model import PhysicsModel
import build_stage3_dataset as builder
import calibrate_physics

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT / "config/warehouse-energy/fixture-v1.json").read_text())
MODEL = PhysicsModel.load(ROOT / "config/warehouse-energy/physics-model-v1.json")
DESIGN = json.loads((ROOT / "config/warehouse-energy/stage3-dataset-design-v1.json").read_text())
PHASE2_NAV = ROOT / "docs/validation/warehouse-energy/phase-2/series/armA-r1"


def synthetic_scripted_run(directory, payload=0.5, speed=0.08, stops=1, hold=3.0,
                           direction="up"):
    """A scripted run whose observed trace equals the frozen physics model."""
    end_x = 11.0 if direction == "up" else -1.0
    design = {"route": "A", "direction": direction, "payload_kg": payload, "run_m": 10.0,
              "rise_m": 0.2, "end_x": end_x, "class": "scripted",
              "planned_speed_mps": speed, "planned_mid_stops": stops, "planned_hold_s": hold}
    profile = calibrate_physics.scripted_profile(design)
    mass = FIXTURE["robot"]["physical_mass_kg"] + payload
    directory.mkdir(parents=True)
    (directory / "design.json").write_text(json.dumps(design, indent=2) + "\n")
    (directory / "result.json").write_text(json.dumps({"status": "PASS"}, indent=2) + "\n")
    t = 0.0
    cumulative = 0.0
    energy_rows = ["sim_s,cumulative_wh"]
    pose_rows = []
    x = -1.0 if direction == "up" else 11.0
    direction_sign = 1.0 if direction == "up" else -1.0
    for dt, v, sin_grade, cos_grade, accel in profile:
        t += dt
        x += direction_sign * v * dt
        force = (mass * accel + mass * 9.80665 * sin_grade
                 + MODEL.crr * mass * 9.80665 * cos_grade)
        mechanical = max(force * v, 0.0)
        cumulative += (mechanical / MODEL.drive_efficiency + MODEL.auxiliary_power_w) * dt / 3600.0
        energy_rows.append(f"{t:.6f},{cumulative:.9f}")
        pose_rows.append({"sim_s": t, "x": x, "y": 0.0, "z": 0.0})
    (directory / "energy.csv").write_text("\n".join(energy_rows) + "\n")
    (directory / "physics.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in pose_rows))
    return design


class PartitionTest(unittest.TestCase):
    def test_held_out_combinations(self):
        self.assertEqual(builder.partition_for("s1", "scripted",
            {"class": "scripted", "payload_kg": 0.25, "route": "A", "direction": "up",
             "speed_mps": 0.06}, DESIGN["partitions"]), "final_test")
        self.assertEqual(builder.partition_for("n1", "nav",
            {"class": "nav", "payload_kg": 0.5, "route": "B", "direction": "up",
             "speed_mps": 0.08}, DESIGN["partitions"]), "final_test")

    def test_deterministic_and_stable(self):
        conditions = {"class": "scripted", "payload_kg": 0.0, "route": "A",
                      "direction": "up", "speed_mps": 0.10}
        first = builder.partition_for("run-x", "scripted", conditions, DESIGN["partitions"])
        for _ in range(3):
            self.assertEqual(builder.partition_for("run-x", "scripted", conditions,
                                                   DESIGN["partitions"]), first)
        self.assertIn(first, ["residual_train", "development", "uncertainty_calibration"])

    def test_all_buckets_covered(self):
        conditions = {"class": "scripted", "payload_kg": 0.0, "route": "A",
                      "direction": "up", "speed_mps": 0.10}
        seen = {builder.partition_for(f"run-{i}", "scripted", conditions, DESIGN["partitions"])
                for i in range(200)}
        self.assertTrue({"residual_train", "development", "uncertainty_calibration"} <= seen)


class ScriptedProfileTest(unittest.TestCase):
    def test_no_stop_profile_is_shorter(self):
        base = {"run_m": 10.0, "rise_m": 0.2, "end_x": 11.0, "direction": "up"}
        with_stop = calibrate_physics.scripted_profile(
            {**base, "planned_speed_mps": 0.1, "planned_mid_stops": 1, "planned_hold_s": 3.0})
        without = calibrate_physics.scripted_profile(
            {**base, "planned_speed_mps": 0.1, "planned_mid_stops": 0, "planned_hold_s": 3.0})
        self.assertAlmostEqual(sum(s[0] for s in with_stop) - sum(s[0] for s in without),
                               6.0, delta=0.2)
        self.assertEqual(without[0][1], 0.0)
        self.assertLess(without[-1][1], 0.01)

    def test_lower_speed_takes_longer(self):
        base = {"run_m": 10.0, "rise_m": 0.2, "end_x": 11.0, "direction": "up",
                "planned_mid_stops": 0, "planned_hold_s": 3.0}
        fast = calibrate_physics.scripted_profile({**base, "planned_speed_mps": 0.10})
        slow = calibrate_physics.scripted_profile({**base, "planned_speed_mps": 0.06})
        self.assertGreater(sum(s[0] for s in slow), sum(s[0] for s in fast))
        # Settle 3 s, travel to the finish trigger at x=10.92, decel, finish 4 s.
        self.assertAlmostEqual(sum(s[0] for s in slow),
                               3.0 + 11.92 / 0.06 + 4.0 + 1.0, delta=1.5)


class BuilderTest(unittest.TestCase):
    def test_scripted_run_segments_and_residuals(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "scripted-A-up-p0.5-v0.08-s1"
            synthetic_scripted_run(directory)
            parsed, reason = builder.scripted_run(directory, MODEL, FIXTURE)
            self.assertIsNone(reason)
            design, rows, poses, energy = parsed
            self.assertEqual([r["segment_name"] for r in rows],
                             ["start_pad", "ramp", "end_pad"])
            self.assertEqual(rows[1]["ramp_run_m"], 10.0)
            self.assertAlmostEqual(rows[1]["ascent_m"], 0.2, delta=0.01)
            self.assertAlmostEqual(rows[0]["ascent_m"] + rows[2]["ascent_m"], 0.0, delta=1e-6)
            for row in rows:
                self.assertAlmostEqual(row["residual_wh"], 0.0, delta=2e-4)
            self.assertEqual(rows[1]["planned_stops_in_segment"], 1)

    def test_scripted_down_run_windows_are_ordered(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "scripted-A-down-p0.5-v0.08-s1"
            synthetic_scripted_run(directory, payload=0.5, speed=0.08, stops=1,
                                   direction="down")
            parsed, reason = builder.scripted_run(directory, MODEL, FIXTURE)
            self.assertIsNone(reason)
            _, rows, _, _ = parsed
            self.assertEqual([r["segment_name"] for r in rows],
                             ["start_pad", "ramp", "end_pad"])
            # Descending traversal: the ramp segment descends 0.2 m.
            self.assertAlmostEqual(rows[1]["descent_m"], 0.2, delta=0.01)
            self.assertAlmostEqual(rows[1]["ascent_m"], 0.0, delta=1e-6)
            for row in rows:
                self.assertGreaterEqual(row["observed_wh"], 0.0)
                self.assertGreaterEqual(row["physics_wh"], 0.0)
                self.assertAlmostEqual(row["residual_wh"], 0.0, delta=2e-4)

    def test_nav_run_from_phase2_evidence(self):
        if not PHASE2_NAV.exists():
            self.skipTest("phase 2 evidence not present")
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "nav-A-up-p0.5-v0.10"
            shutil.copytree(PHASE2_NAV, directory, symlinks=True, ignore_dangling_symlinks=True)
            design = json.loads((directory / "design.json").read_text())
            design["class"] = "nav"
            (directory / "design.json").write_text(json.dumps(design, indent=2) + "\n")
            parsed, reason = builder.nav_run(directory, MODEL, FIXTURE)
            self.assertIsNone(reason)
            _, rows, _, _ = parsed
            self.assertEqual([r["segment_name"] for r in rows],
                             ["loading->fork", "fork->a_top", "a_top->transfer"])
            self.assertAlmostEqual(rows[1]["ascent_m"], 0.2, delta=0.02)
            self.assertAlmostEqual(rows[1]["max_abs_grade"], 0.02, delta=0.005)
            # Dataset label convention: dispatch through final waypoint arrival
            # (the Stage 2 mission window additionally counted post-arrival idle).
            total = sum(r["observed_wh"] for r in rows)
            self.assertAlmostEqual(total, 0.4401, delta=0.01)
            total_duration = sum(r["observed_duration_s"] for r in rows)
            self.assertAlmostEqual(total_duration, 157.3, delta=2.0)
            for row in rows:
                self.assertGreater(row["observed_wh"], 0.0)
                self.assertGreater(row["physics_wh"], 0.0)

    def test_build_partitions_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "raw"
            synthetic_scripted_run(raw / "scripted-A-up-p0.25-v0.08-s1", payload=0.25)
            synthetic_scripted_run(raw / "scripted-A-up-p0.5-v0.08-s1", payload=0.5)
            output = Path(tmp) / "dataset"
            manifest = builder.build(raw, FIXTURE, MODEL, DESIGN, output)
            self.assertEqual(manifest["runs"], 2)
            self.assertEqual(manifest["segments"], 6)
            runs = [json.loads(line) for line in (output / "runs.jsonl").open()]
            by_id = {r["run_id"]: r for r in runs}
            self.assertEqual(by_id["scripted-A-up-p0.25-v0.08-s1"]["partition"], "final_test")
            self.assertIn(by_id["scripted-A-up-p0.5-v0.08-s1"]["partition"],
                          ["residual_train", "development", "uncertainty_calibration"])
            failed = raw / "scripted-B-down-p0-v0.06-s0"
            failed.mkdir()
            (failed / "design.json").write_text(json.dumps(
                {"class": "scripted", "route": "B", "direction": "down", "payload_kg": 0.0,
                 "run_m": 20.0, "rise_m": 0.2, "end_x": -1.0, "planned_speed_mps": 0.06,
                 "planned_mid_stops": 0, "planned_hold_s": 3.0}))
            (failed / "result.json").write_text(json.dumps(
                {"status": "FAIL", "errors": ["synthetic failure"]}))
            output2 = Path(tmp) / "dataset2"
            manifest2 = builder.build(raw, FIXTURE, MODEL, DESIGN, output2)
            self.assertEqual(manifest2["runs"], 2)
            self.assertEqual(len(manifest2["rejected_runs"]), 1)
            self.assertEqual(manifest2["rejected_runs"][0]["run"], failed.name)


if __name__ == "__main__":
    unittest.main()
