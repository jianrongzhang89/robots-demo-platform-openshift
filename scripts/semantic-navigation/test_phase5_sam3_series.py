import copy
import json
import unittest

from run_phase5_sam3_series import restore_spec, trial_passed


class Sam3SeriesAcceptanceTests(unittest.TestCase):
    def setUp(self):
        names = ("sam3_observation_ready", "sam3_registration_under_motion",
                 "sam3_observation_timing", "sam3_semantic_isolation",
                 "guarded_real_hotel_one_meter_goal",
                 "cancellation_terminal_and_acknowledged",
                 "closed_graph_and_descendants_terminal",
                 "baseline_native_stop_metrics", "baseline_contact_window",
                 "independent_native_motion_observed", "settled_support_geometry")
        self.evidence = {"passed": True, "sam3_observation": True,
                         "console_only_server": True, "world_recording": False,
                         "checks": [{"case": n, "passed": True} for n in names]}

    def test_complete_sam3_trial(self):
        self.assertTrue(trial_passed(self.evidence, 0))

    def test_each_required_check_must_exist_and_pass(self):
        for index in range(len(self.evidence["checks"])):
            evidence = copy.deepcopy(self.evidence)
            del evidence["checks"][index]
            self.assertFalse(trial_passed(evidence, 0))
            evidence = copy.deepcopy(self.evidence)
            evidence["checks"][index]["passed"] = False
            self.assertFalse(trial_passed(evidence, 0))

    def test_wrong_mode_diagnostics_or_runner_fail(self):
        self.assertFalse(trial_passed(self.evidence, 1))
        evidence = copy.deepcopy(self.evidence)
        evidence["passed"] = False
        self.assertFalse(trial_passed(evidence, 0))
        for key, value in (("sam3_observation", False),
                           ("console_only_server", False),
                           ("world_recording", True),
                           ("diagnostic_only", True)):
            evidence = copy.deepcopy(self.evidence)
            evidence[key] = value
            self.assertFalse(trial_passed(evidence, 0))

    def test_restore_spec_strips_api_managed_fields(self):
        live = {"apiVersion": "v1", "kind": "Pod",
                "metadata": {"name": "pod", "namespace": "ns", "uid": "u",
                             "resourceVersion": "9", "creationTimestamp": "t",
                             "managedFields": [], "labels": {"app": "x"}},
                "spec": {"nodeName": "node-a", "containers": [{"name": "c"}]},
                "status": {"phase": "Running"}}
        spec = restore_spec(live)
        self.assertEqual(spec["metadata"]["labels"], {"app": "x"})
        self.assertNotIn("uid", spec["metadata"])
        self.assertNotIn("status", spec)
        self.assertNotIn("nodeName", spec["spec"])
        self.assertEqual(spec["spec"]["containers"], [{"name": "c"}])
        # The live object is not mutated by the strip.
        self.assertIn("status", live)


if __name__ == "__main__":
    unittest.main()
