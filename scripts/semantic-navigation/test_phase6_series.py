import copy
import json
import unittest

from run_phase6_series import (build_trial_plan, completion_divergence_summary,
                               execution_placement_error,
                               hull_exposure_m, phase5_evidence_error,
                               series_gate, speed_ladder_advances,
                               NEGATIVE_CASES, PHASE5_GATES, QUALIFIED_GPU_NODE)

REGION = {"xmin": 17.0, "xmax": 17.6, "ymin": -31.9, "ymax": -31.3}
HULL = 0.18


def nominal_trial(arm, completed=True, exposure=0.0, trial=None):
    return {"trial": trial or f"{arm}-t", "arm": arm, "case": "nominal",
            "completed": completed, "collision": False, "hull_exposure_m": exposure}


class PlanTests(unittest.TestCase):
    def test_plan_alternates_arms_and_covers_cases(self):
        plan = build_trial_plan(20, 3, "off", [0.15])
        nominal = [t for t in plan["trials"] if t["case"] == "nominal"]
        self.assertEqual(40, len(nominal))
        for pair in range(20):
            arms = [t["arm"] for t in nominal if t["pair"] == pair]
            self.assertEqual(["off", "on"], arms)
        for case in NEGATIVE_CASES:
            self.assertEqual(6, len([t for t in plan["trials"] if t["case"] == case]))
        for case in ("nominal",) + NEGATIVE_CASES:
            for pair_trials in ([t for t in plan["trials"] if t["case"] == case and t["pair"] == p]
                                for p in {t["pair"] for t in plan["trials"] if t["case"] == case}):
                speeds = {t["speed_mps"] for t in pair_trials}
                self.assertEqual({0.15}, speeds)

    def test_plan_rejects_short_or_invalid_series(self):
        with self.assertRaises(ValueError):
            build_trial_plan(19, 3, "off", [0.15])
        with self.assertRaises(ValueError):
            build_trial_plan(20, 0, "off", [0.15])
        with self.assertRaises(ValueError):
            build_trial_plan(20, 3, "both", [0.15])
        with self.assertRaises(ValueError):
            build_trial_plan(20, 3, "off", [0.50])


class ExposureTests(unittest.TestCase):
    def test_straight_through_region_is_exposed(self):
        straight = [[16.0, -31.6], [19.0, -31.6]]
        exposure = hull_exposure_m(straight, REGION, HULL)
        # region width 0.6 m plus the hull radius on both sides.
        self.assertGreater(exposure, 0.6 + 2 * HULL - 0.05)
        self.assertLess(exposure, 0.6 + 2 * HULL + 0.05)

    def test_path_around_region_has_zero_exposure(self):
        around = [[16.0, -31.6], [17.3, -30.8], [19.0, -31.6]]
        self.assertEqual(0.0, hull_exposure_m(around, REGION, HULL))

    def test_single_point_and_degenerate_region(self):
        self.assertEqual(0.0, hull_exposure_m([[17.3, -31.6]], REGION, HULL))
        with self.assertRaises(ValueError):
            hull_exposure_m([[16.0, -31.6], [19.0, -31.6]],
                            {"xmin": 1, "xmax": 1, "ymin": 0, "ymax": 2}, HULL)

    def test_short_clip_cannot_hide_contact(self):
        clip = [[16.9, -31.6], [17.0, -31.6]]
        for _ in range(50):
            clip.append([17.0, -31.6])
        clip.append([17.1, -31.6])
        self.assertGreater(hull_exposure_m(clip, REGION, HULL), 0.0)


class LadderTests(unittest.TestCase):
    def test_ladder_requires_all_gates(self):
        ok, nxt = speed_ladder_advances(0.15, {"braking": True, "latency": True, "viewing_distance": True})
        self.assertTrue(ok)
        self.assertEqual(0.20, nxt)
        ok, reason = speed_ladder_advances(0.15, {"braking": True, "latency": True})
        self.assertFalse(ok)
        self.assertIn("viewing_distance", reason)
        ok, _ = speed_ladder_advances(0.35, {"braking": True, "latency": True, "viewing_distance": True})
        self.assertFalse(ok)
        ok, _ = speed_ladder_advances(0.12, {})
        self.assertFalse(ok)


class GateTests(unittest.TestCase):
    def passing_trials(self, off_exposure=1.2, on_exposure=0.0):
        trials = []
        for i in range(20):
            trials.append(nominal_trial("off", exposure=off_exposure, trial=f"off-{i}"))
            trials.append(nominal_trial("on", exposure=on_exposure, trial=f"on-{i}"))
        for case in NEGATIVE_CASES:
            for i in range(3):
                for arm in ("off", "on"):
                    trials.append({"trial": f"{arm}-{case}-{i}", "arm": arm, "case": case,
                                   "completed": True, "collision": False,
                                   "fault_stop_criteria_met": True})
        return trials

    def test_passing_series(self):
        gate = series_gate(self.passing_trials())
        self.assertTrue(gate["passed"])
        self.assertEqual({"off": 24.0, "on": 0.0}, gate["aggregate_hull_exposure_m"])

    def test_incomplete_arm_fails(self):
        trials = self.passing_trials()
        trials[0]["completed"] = False
        gate = series_gate(trials)
        self.assertFalse(gate["passed"])
        self.assertTrue(any("incomplete" in p for p in gate["problems"]))

    def test_insufficient_reduction_fails(self):
        gate = series_gate(self.passing_trials(off_exposure=1.2, on_exposure=0.3))
        self.assertFalse(gate["passed"])
        self.assertTrue(any("below 0.90" in p for p in gate["problems"]))

    def test_zero_baseline_is_inconclusive(self):
        gate = series_gate(self.passing_trials(off_exposure=0.0, on_exposure=0.0))
        self.assertFalse(gate["passed"])
        self.assertTrue(any("inconclusive" in p for p in gate["problems"]))

    def test_collision_fails(self):
        trials = self.passing_trials()
        trials[1]["collision"] = True
        gate = series_gate(trials)
        self.assertFalse(gate["passed"])
        self.assertTrue(any("collisions" in p for p in gate["problems"]))

    def test_negative_regression_fails(self):
        trials = self.passing_trials()
        trials.append({"trial": "on-target_absent-x", "arm": "on", "case": "target_absent",
                       "completed": False, "collision": False})
        gate = series_gate(trials)
        self.assertFalse(gate["passed"])
        self.assertTrue(any("negative/fault" in p for p in gate["problems"]))

    def test_perception_fault_must_meet_stopping_criteria(self):
        trials = self.passing_trials()
        trials.append({"trial": "on-perception_failure-x", "arm": "on",
                       "case": "perception_failure", "completed": True,
                       "collision": False, "fault_stop_criteria_met": False})
        gate = series_gate(trials)
        self.assertFalse(gate["passed"])
        self.assertTrue(any("phase 5 criteria" in p for p in gate["problems"]))


class CompletionDivergenceSummaryTests(unittest.TestCase):
    """The series result must surface every completed arrival's belief/truth
    divergence (the October 28 fork decision) — descriptively, never as a
    gate: a multi-metre-diverged passing trial still passes here and stays
    visible for the sign-off review."""

    def test_summary_lists_arrivals_and_maxima_per_arm(self):
        trials = [
            {"trial": "000-off", "arm": "off", "case": "nominal", "completed": True,
             "completion_divergence": {"at_arrival": {
                 "belief_truth_divergence_m": 0.4, "physical_goal_distance_m": 0.5}}},
            {"trial": "001-on", "arm": "on", "case": "nominal", "completed": True,
             "completion_divergence": {"at_arrival": {
                 "belief_truth_divergence_m": 2.7, "physical_goal_distance_m": 2.6}}},
            {"trial": "002-on", "arm": "on", "case": "nominal", "completed": True,
             "completion_divergence": {"final": {
                 "belief_truth_divergence_m": 2.7}}},  # no arrival row
            {"trial": "003-on", "arm": "on", "case": "nominal", "completed": False},
            {"trial": "004-on", "arm": "on", "case": "target_absent", "completed": True,
             "completion_divergence": {"at_arrival": {
                 "belief_truth_divergence_m": 9.9, "physical_goal_distance_m": 9.9}}},
        ]
        summary = completion_divergence_summary(trials)
        self.assertEqual(1, summary["off"]["arrivals"])
        self.assertEqual(0.4, summary["off"]["max_belief_truth_divergence_at_arrival_m"])
        self.assertEqual(1, summary["on"]["arrivals"])  # no-arrival and failed rows excluded
        self.assertEqual(2.7, summary["on"]["max_belief_truth_divergence_at_arrival_m"])
        self.assertEqual(2.6, summary["on"]["max_physical_goal_distance_at_arrival_m"])
        self.assertEqual(["001-on"], [a["trial"] for a in summary["on"]["trials"]])
        # Non-nominal cases are not part of the completion summary.
        self.assertNotIn("004-on", [a["trial"] for a in summary["on"]["trials"]])

    def test_summary_with_no_arrivals_reports_none(self):
        summary = completion_divergence_summary([
            {"trial": "000-off", "arm": "off", "case": "nominal", "completed": True}])
        self.assertEqual(0, summary["off"]["arrivals"])
        self.assertIsNone(summary["off"]["max_belief_truth_divergence_at_arrival_m"])
        self.assertIsNone(summary["on"]["max_physical_goal_distance_at_arrival_m"])


class PlacementContractTests(unittest.TestCase):
    """The user-approved October 26, 2026 reconciliation: Phase 6 moving
    trials run the frozen guarded GPU-rendering profile, not a GPU-free
    software-rendering placement (which is not qualified for motion)."""

    def test_execution_requires_pinned_node_and_gpu_rendering(self):
        self.assertIsNone(execution_placement_error(QUALIFIED_GPU_NODE, True))

    def test_missing_node_or_gpu_rendering_is_refused(self):
        self.assertIn("--node-name", execution_placement_error("", True))
        self.assertIn("--gpu-rendering", execution_placement_error(QUALIFIED_GPU_NODE, False))
        # Both missing is still refused (the node check reports first).
        self.assertIsNotNone(execution_placement_error("", False))


class Phase5EvidenceTests(unittest.TestCase):
    def passing(self):
        return {"passed": True, "accepted_gates": list(PHASE5_GATES)}

    def test_valid_evidence_passes(self):
        self.assertIsNone(phase5_evidence_error(self.passing()))

    def test_missing_gate_or_unpassed_fails(self):
        broken = self.passing()
        broken["accepted_gates"] = broken["accepted_gates"][:3]
        self.assertIn("armed_fault_matrix", phase5_evidence_error(broken))
        unpassed = self.passing()
        unpassed["passed"] = False
        self.assertIsNotNone(phase5_evidence_error(unpassed))
        self.assertIsNotNone(phase5_evidence_error("not-a-dict"))


if __name__ == "__main__":
    unittest.main()
