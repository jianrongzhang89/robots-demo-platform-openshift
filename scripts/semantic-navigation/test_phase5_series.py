import copy
import unittest

from run_phase5_baseline import placement_args, placement_error, trial_passed


class SeriesAcceptanceTests(unittest.TestCase):
    def setUp(self):
        names=("baseline_contact_window", "baseline_native_stop_metrics",
            "guarded_recovery_probe_terminal", "guarded_backup_and_wait_actions_completed",
            "backup_reverse_commands_bounded", "wait_interval_native_applied_velocity_zero",
            "wait_zero_holds_are_bounded_and_continuous", "independent_native_motion_observed")
        self.evidence={"passed":True,"checks":[{"case":n,"passed":True} for n in names]}

    def test_complete_recovery_trial(self):
        self.assertTrue(trial_passed(self.evidence,0,recovery_probe=True))

    def test_each_required_check_must_exist_and_pass(self):
        for index in range(len(self.evidence["checks"])):
            evidence=copy.deepcopy(self.evidence)
            del evidence["checks"][index]
            self.assertFalse(trial_passed(evidence,0,recovery_probe=True))
            evidence=copy.deepcopy(self.evidence)
            evidence["checks"][index]["passed"]=False
            self.assertFalse(trial_passed(evidence,0,recovery_probe=True))

    def test_baseline_cannot_substitute_for_recovery(self):
        evidence={"passed":True,"checks":self.evidence["checks"][:2]}
        self.assertTrue(trial_passed(evidence,0))
        self.assertFalse(trial_passed(evidence,0,recovery_probe=True))

    def test_runner_and_overall_result_must_pass(self):
        self.assertFalse(trial_passed(self.evidence,1,recovery_probe=True))
        self.evidence["passed"]=False
        self.assertFalse(trial_passed(self.evidence,0,recovery_probe=True))

    def test_candidate_requires_runtime_overlay_identity(self):
        self.assertFalse(trial_passed(self.evidence,0,controller_endpoint_capture=True))
        self.evidence["checks"].append({"case":"opt_in_controller_overlay_loaded","passed":True})
        self.assertTrue(trial_passed(self.evidence,0,controller_endpoint_capture=True))

    def test_diagnostic_run_is_not_qualification(self):
        self.evidence["diagnostic_only"]=True
        self.assertFalse(trial_passed(self.evidence,0,recovery_probe=True))

    def test_console_candidate_requires_all_runtime_evidence(self):
        self.evidence.update(console_only_server=True,world_recording=False)
        names=("console_server_preflight","console_server_identity",
               "console_server_recording_absent_before_arm","console_server_recording_absent",
               "console_server_shutdown")
        self.evidence["checks"].extend({"case":n,"passed":True} for n in names)
        self.assertTrue(trial_passed(self.evidence,0,recovery_probe=True,console_only_server=True))
        for name in names:
            evidence=copy.deepcopy(self.evidence)
            evidence["checks"]=[c for c in evidence["checks"] if c["case"]!=name]
            self.assertFalse(trial_passed(evidence,0,recovery_probe=True,console_only_server=True))
        for key,value in (("console_only_server",False),("world_recording",True),("diagnostic_only",True)):
            evidence=copy.deepcopy(self.evidence); evidence[key]=value
            self.assertFalse(trial_passed(evidence,0,recovery_probe=True,console_only_server=True))

    def test_recovery_series_requires_a_pinned_non_gpu_worker(self):
        self.assertIn("--node-name",placement_error(True,None,False))
        self.assertIn("--require-non-gpu-node",placement_error(True,"worker.example",False))
        self.assertIn("--node-name",placement_error(False,None,True))
        self.assertIsNone(placement_error(True,"worker.example",True))
        self.assertEqual(placement_args("worker.example",True),
                         ["--node-name","worker.example","--require-non-gpu-node"])

    def test_recovery_series_accepts_pinned_gpu_rendering_worker(self):
        self.assertIsNone(placement_error(True,"gpu.example",False,True))
        self.assertEqual(placement_args("gpu.example",False,True),
                         ["--node-name","gpu.example","--gpu-rendering"])
        self.assertIn("cannot combine with",placement_error(True,"gpu.example",True,True))
        self.assertIn("with --require-non-gpu-node or --gpu-rendering",
                      placement_error(True,"worker.example",False,False))


if __name__=="__main__": unittest.main()
