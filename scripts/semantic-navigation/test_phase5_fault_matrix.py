import copy
import unittest

from run_phase5_fault_matrix import trial_passed


class FaultMatrixAcceptanceTests(unittest.TestCase):
    def setUp(self):
        names = ("fault_stop_scan_loss", "fault_stop_native_stop_metrics",
                 "no_automatic_resume_after_fault_restore",
                 "cancellation_terminal_and_acknowledged",
                 "closed_graph_and_descendants_terminal",
                 "guarded_fault_stop_probe_terminal",
                 "independent_native_motion_observed",
                 "baseline_contact_window", "settled_support_geometry")
        self.evidence = {"passed": True, "fault_stop_mode": "scan_loss",
                         "fault_stop_probe": True,
                         "console_only_server": True, "world_recording": False,
                         "checks": [{"case": n, "passed": True} for n in names]}

    def test_complete_fault_trial(self):
        self.assertTrue(trial_passed(self.evidence, 0, "scan_loss"))

    def test_each_required_check_must_exist_and_pass(self):
        for index in range(len(self.evidence["checks"])):
            evidence = copy.deepcopy(self.evidence)
            del evidence["checks"][index]
            self.assertFalse(trial_passed(evidence, 0, "scan_loss"))
            evidence = copy.deepcopy(self.evidence)
            evidence["checks"][index]["passed"] = False
            self.assertFalse(trial_passed(evidence, 0, "scan_loss"))

    def test_mode_mismatch_wrong_mode_or_diagnostics_fail(self):
        self.assertFalse(trial_passed(self.evidence, 0, "command_stall"))
        evidence = copy.deepcopy(self.evidence)
        evidence["fault_stop_mode"] = "collision_state"
        self.assertFalse(trial_passed(evidence, 0, "collision_state")
                         and evidence["checks"][0]["case"] != "fault_stop_collision_state")
        self.assertFalse(trial_passed(self.evidence, 1, "scan_loss"))
        evidence = copy.deepcopy(self.evidence)
        evidence["passed"] = False
        self.assertFalse(trial_passed(evidence, 0, "scan_loss"))
        evidence = copy.deepcopy(self.evidence)
        evidence["diagnostic_only"] = True
        self.assertFalse(trial_passed(evidence, 0, "scan_loss"))
        evidence = copy.deepcopy(self.evidence)
        evidence["world_recording"] = True
        self.assertFalse(trial_passed(evidence, 0, "scan_loss"))
        evidence = copy.deepcopy(self.evidence)
        evidence["console_only_server"] = False
        self.assertFalse(trial_passed(evidence, 0, "scan_loss"))

    def test_mode_specific_check_must_match_the_planned_mode(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["checks"][0] = {"case": "fault_stop_command_stall", "passed": True}
        self.assertFalse(trial_passed(evidence, 0, "scan_loss"))


if __name__ == "__main__":
    unittest.main()
