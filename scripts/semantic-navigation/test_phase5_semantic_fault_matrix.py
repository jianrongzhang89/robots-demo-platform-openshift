import copy
import unittest

from run_phase5_semantic_fault_matrix import trial_passed


class SemanticFaultMatrixAcceptanceTests(unittest.TestCase):
    def setUp(self):
        names = ("semantic_fault_hung_inference", "semantic_fault_native_stop_metrics",
                 "late_success_does_not_resume_motion",
                 "sam3_observation_ready", "sam3_semantic_isolation",
                 "guarded_semantic_fault_terminal",
                 "cancellation_terminal_and_acknowledged",
                 "closed_graph_and_descendants_terminal",
                 "baseline_contact_window",
                 "independent_native_motion_observed", "settled_support_geometry")
        self.evidence = {"passed": True, "semantic_fault_mode": "hung_inference",
                         "sam3_observation": True, "console_only_server": True,
                         "world_recording": False,
                         "checks": [{"case": n, "passed": True} for n in names]}

    def test_complete_semantic_fault_trial(self):
        self.assertTrue(trial_passed(self.evidence, 0, "hung_inference"))

    def test_each_required_check_must_exist_and_pass(self):
        for index in range(len(self.evidence["checks"])):
            evidence = copy.deepcopy(self.evidence)
            del evidence["checks"][index]
            self.assertFalse(trial_passed(evidence, 0, "hung_inference"))
            evidence = copy.deepcopy(self.evidence)
            evidence["checks"][index]["passed"] = False
            self.assertFalse(trial_passed(evidence, 0, "hung_inference"))

    def test_wrong_mode_or_configuration_fails(self):
        self.assertFalse(trial_passed(self.evidence, 0, "process_loss"))
        evidence = copy.deepcopy(self.evidence)
        evidence["semantic_fault_mode"] = "camera_path_loss"
        self.assertFalse(trial_passed(evidence, 0, "camera_path_loss"))
        self.assertFalse(trial_passed(self.evidence, 1, "hung_inference"))
        for key, value in (("passed", False), ("sam3_observation", False),
                           ("console_only_server", False),
                           ("world_recording", True), ("diagnostic_only", True)):
            evidence = copy.deepcopy(self.evidence)
            evidence[key] = value
            self.assertFalse(trial_passed(evidence, 0, "hung_inference"))


if __name__ == "__main__":
    unittest.main()
