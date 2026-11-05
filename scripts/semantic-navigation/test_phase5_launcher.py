"""Reject invalid diagnostic combinations before any cluster operation."""
from pathlib import Path
import subprocess
import sys
import unittest

from run_phase5_native import node_has_gpu


class DiagnosticLauncherTests(unittest.TestCase):
    def parse(self, *flags):
        return subprocess.run([sys.executable,str(Path(__file__).with_name("run_phase5_native.py")),
            "--image","invalid-image","--output-dir","unused-diagnostic-test-output",*flags],
            text=True,capture_output=True,timeout=10)

    def test_invalid_combinations_fail_before_image_or_cluster_lookup(self):
        for flags in (("--diagnostic-no-world-recording",),
                      ("--diagnostic-api-world-recording",),
                      ("--suite","hotel-guarded","--diagnostic-no-world-recording",
                       "--diagnostic-api-world-recording"),
                      ("--suite","hotel-guarded","--diagnostic-no-world-recording",
                       "--diagnostic-record-period","3600")):
            with self.subTest(flags=flags):
                result=self.parse(*flags)
                self.assertEqual(result.returncode,2)
                self.assertIn("API recording experiments require",result.stderr)

    def test_valid_modes_still_require_pinned_image(self):
        for flag in ("--diagnostic-no-world-recording","--diagnostic-api-world-recording"):
            with self.subTest(flag=flag):
                result=self.parse("--suite","hotel-guarded",flag)
                self.assertEqual(result.returncode,2)
                self.assertIn("requires digest-pinned namespace safety image",result.stderr)

    def test_console_candidate_rejects_unqualified_combinations(self):
        for flags in ((),("--suite","hotel-guarded"),
                      ("--suite","hotel-guarded","--contact-audit","--diagnostic-no-world-recording"),
                      ("--suite","hotel-guarded","--contact-audit","--diagnostic-record-period",".1")):
            result=self.parse("--console-only-server",*flags)
            self.assertEqual(result.returncode,2)
            self.assertIn("requires hotel contact evidence and no recording diagnostics",result.stderr)
        result=self.parse("--console-only-server","--suite","hotel-guarded","--contact-audit")
        self.assertIn("requires digest-pinned namespace safety image",result.stderr)

    def test_g5_taint_tolerance_is_limited_to_pinned_cm_diagnostics(self):
        result=self.parse("--suite","hotel","--node-name","ip-10-0-44-146.ec2.internal",
                          "--allow-g5-node")
        self.assertEqual(result.returncode,2)
        self.assertIn("requires an explicitly pinned Collision Monitor diagnostic fixture",result.stderr)

        result=self.parse("--suite","hotel","--contact-audit","--console-only-server",
                          "--collision-monitor-diagnostics","--node-name","ip-10-0-44-146.ec2.internal",
                          "--rear-casters","--physics-step","0.002","--lidar-range","12",
                          "--odom-frequency","200",
                          "--allow-g5-node")
        self.assertEqual(result.returncode,2)
        self.assertIn("requires digest-pinned namespace safety image",result.stderr)

    def test_non_gpu_placement_guard_requires_pinned_node(self):
        result=self.parse("--require-non-gpu-node")
        self.assertEqual(result.returncode,2)
        self.assertIn("requires --node-name and cannot allow a G5 node",result.stderr)

        guarded=("--suite","hotel-guarded","--recovery-probe","--contact-audit",
                 "--console-only-server","--rear-casters","--physics-step","0.002",
                 "--lidar-range","12","--odom-frequency","200",
                 "--require-non-gpu-node")
        result=self.parse(*guarded)
        self.assertEqual(result.returncode,2)
        self.assertIn("requires --node-name and cannot allow a G5 node",result.stderr)

        result=self.parse(*guarded,"--node-name","ip-10-0-15-146.ec2.internal")
        self.assertEqual(result.returncode,2)
        self.assertIn("requires digest-pinned namespace safety image",result.stderr)

        result=self.parse(*guarded,"--node-name","ip-10-0-15-146.ec2.internal",
                          "--allow-g5-node")
        self.assertEqual(result.returncode,2)
        self.assertIn("cannot allow a G5 node",result.stderr)

    def test_node_gpu_detection_uses_resources_labels_and_taints(self):
        fixtures=(
            ({"metadata":{"labels":{"nvidia.com/gpu.present":"true"}}},True),
            ({"status":{"allocatable":{"nvidia.com/gpu":"1"}}},True),
            ({"status":{"capacity":{"nvidia.com/mig-1g.5gb":"1"}}},True),
            ({"metadata":{"labels":{"amd.com/gpu.present":"true"}}},True),
            ({"spec":{"taints":[{"key":"g5-gpu","effect":"NoSchedule"}]}},True),
            ({"status":{"allocatable":{"cpu":"15500m","memory":"64Gi"}}},False),
        )
        for node,expected in fixtures:
            with self.subTest(node=node):
                self.assertEqual(node_has_gpu(node),expected)

    def test_tf_edge_probe_is_limited_to_disarmed_cm_diagnostics(self):
        result=self.parse("--tf-edge-probe")
        self.assertEqual(result.returncode,2)
        self.assertIn("requires the disarmed hotel console-only Collision Monitor diagnostic fixture",result.stderr)

        result=self.parse("--suite","hotel","--contact-audit","--console-only-server",
                          "--collision-monitor-diagnostics","--tf-edge-probe",
                          "--rear-casters","--physics-step","0.002","--lidar-range","12",
                          "--odom-frequency","200")
        self.assertEqual(result.returncode,2)
        self.assertIn("requires digest-pinned namespace safety image",result.stderr)

    def test_tf_producer_trace_requires_disarmed_tf_edge_probe(self):
        result=self.parse("--tf-producer-trace")
        self.assertEqual(result.returncode,2)
        self.assertIn("requires --tf-edge-probe",result.stderr)

        result=self.parse("--suite","hotel","--contact-audit","--console-only-server",
                          "--collision-monitor-diagnostics","--tf-edge-probe",
                          "--tf-producer-trace","--rear-casters","--physics-step","0.002",
                          "--lidar-range","12","--odom-frequency","200")
        self.assertEqual(result.returncode,2)
        self.assertIn("requires digest-pinned namespace safety image",result.stderr)

    def test_cm_diagnostics_require_prequalified_support_geometry_profile(self):
        prefix=("--suite","hotel","--contact-audit","--console-only-server",
                "--collision-monitor-diagnostics")
        result=self.parse(*prefix,"--rear-casters","--physics-step","0.002",
                          "--lidar-range","12","--odom-frequency","200")
        self.assertEqual(result.returncode,2)
        self.assertIn("requires digest-pinned namespace safety image",result.stderr)

        for geometry in (("--physics-step","0.002","--lidar-range","12","--odom-frequency","200"),
                         ("--rear-casters","--physics-step","0.01","--lidar-range","12","--odom-frequency","200"),
                         ("--rear-casters","--physics-step","0.002","--lidar-range","3.5","--odom-frequency","200"),
                         ("--rear-casters","--physics-step","0.002","--lidar-range","12","--odom-frequency","50")):
            with self.subTest(geometry=geometry):
                result=self.parse(*prefix,*geometry)
                self.assertEqual(result.returncode,2)
                self.assertIn("requires the qualified private geometry profile",result.stderr)

    def test_tf2_fast_poll_requires_edge_probe_and_200hz(self):
        result=self.parse("--tf2-poll-1ms")
        self.assertEqual(result.returncode,2)
        self.assertIn("requires --tf-edge-probe and --odom-frequency 200",result.stderr)

        result=self.parse("--suite","hotel","--contact-audit","--console-only-server",
                          "--collision-monitor-diagnostics","--tf-edge-probe","--odom-frequency","50",
                          "--rear-casters","--physics-step","0.002","--lidar-range","12",
                          "--tf2-poll-1ms")
        self.assertEqual(result.returncode,2)
        self.assertIn("requires --tf-edge-probe and --odom-frequency 200",result.stderr)

        result=self.parse("--suite","hotel","--contact-audit","--console-only-server",
                          "--collision-monitor-diagnostics","--tf-edge-probe","--odom-frequency","200",
                          "--rear-casters","--physics-step","0.002","--lidar-range","12",
                          "--tf2-poll-1ms")
        self.assertEqual(result.returncode,2)
        self.assertIn("requires digest-pinned namespace safety image",result.stderr)

    def test_matched_threshold_and_cpu_load_are_restricted_to_disarmed_probe(self):
        result=self.parse("--tf-log-threshold-us","1000")
        self.assertEqual(result.returncode,2)
        self.assertIn("requires --tf-edge-probe",result.stderr)

        result=self.parse("--bounded-cpu-contention")
        self.assertEqual(result.returncode,2)
        self.assertIn("requires the disarmed TF edge diagnostic",result.stderr)

        result=self.parse("--suite","hotel","--contact-audit","--console-only-server",
                          "--collision-monitor-diagnostics","--tf-edge-probe",
                          "--odom-frequency","200","--tf-log-threshold-us","1000",
                          "--rear-casters","--physics-step","0.002","--lidar-range","12",
                          "--bounded-cpu-contention")
        self.assertEqual(result.returncode,2)
        self.assertIn("requires digest-pinned namespace safety image",result.stderr)

    def test_moving_trace_requires_exact_guarded_recovery_profile(self):
        result=self.parse("--moving-timing-trace")
        self.assertEqual(result.returncode,2)
        self.assertIn("requires --suite hotel-guarded --recovery-probe",result.stderr)

        guarded=("--suite","hotel-guarded","--recovery-probe","--contact-audit",
                 "--console-only-server","--rear-casters","--physics-step","0.002",
                 "--lidar-range","12","--odom-frequency","200","--moving-timing-trace")
        result=self.parse(*guarded)
        self.assertEqual(result.returncode,2)
        self.assertIn("requires digest-pinned namespace safety image",result.stderr)

    def test_moving_trace_rejects_overlays_load_and_scenario_overrides(self):
        guarded=("--suite","hotel-guarded","--recovery-probe","--contact-audit",
                 "--console-only-server","--rear-casters","--physics-step","0.002",
                 "--lidar-range","12","--odom-frequency","200","--moving-timing-trace")
        for extra in (("--tf2-poll-1ms",), ("--bounded-cpu-contention",),
                      ("--tf-loss-probe",), ("--scan-update-rate","20"),
                      ("--collision-monitor-diagnostics",), ("--diagnostic-no-world-recording",)):
            with self.subTest(extra=extra):
                result=self.parse(*guarded,*extra)
                self.assertEqual(result.returncode,2)
                self.assertIn("single fixed-profile trial",result.stderr)

    def test_gz_thread_probe_requires_console_hotel_and_excludes_moving_trace(self):
        result=self.parse("--gz-thread-probe")
        self.assertEqual(result.returncode,2)
        self.assertIn("requires a hotel suite with --console-only-server",result.stderr)

        console=("--suite","hotel-guarded","--recovery-probe","--contact-audit",
                 "--console-only-server","--rear-casters","--physics-step","0.002",
                 "--lidar-range","12","--odom-frequency","200")
        result=self.parse(*console,"--gz-thread-probe","--moving-timing-trace")
        self.assertEqual(result.returncode,2)
        self.assertIn("not --moving-timing-trace",result.stderr)

        result=self.parse(*console,"--gz-thread-probe")
        self.assertEqual(result.returncode,2)
        self.assertIn("requires digest-pinned namespace safety image",result.stderr)

    def test_gpu_rendering_requires_pinned_hotel_and_excludes_other_placement(self):
        console=("--suite","hotel-guarded","--recovery-probe","--contact-audit",
                 "--console-only-server","--rear-casters","--physics-step","0.002",
                 "--lidar-range","12","--odom-frequency","200")
        result=self.parse(*console,"--gpu-rendering")
        self.assertEqual(result.returncode,2)
        self.assertIn("requires --node-name pinned to a GPU worker",result.stderr)

        for extra in (("--require-non-gpu-node",),("--allow-g5-node",)):
            with self.subTest(extra=extra):
                result=self.parse(*console,"--gpu-rendering","--node-name",
                                  "ip-10-0-44-146.ec2.internal",*extra)
                self.assertEqual(result.returncode,2)
                self.assertIn("cannot combine with",result.stderr)

        result=self.parse("--suite","native","--gpu-rendering",
                          "--node-name","ip-10-0-44-146.ec2.internal")
        self.assertEqual(result.returncode,2)
        self.assertIn("applies only to hotel suites",result.stderr)

        result=self.parse(*console,"--gpu-rendering","--node-name",
                          "ip-10-0-44-146.ec2.internal")
        self.assertEqual(result.returncode,2)
        self.assertIn("requires digest-pinned namespace safety image",result.stderr)

    def test_semantic_fault_probe_requires_sam3_observation_and_runs_alone(self):
        qualified=("--suite","hotel-guarded","--sam3-observation","--semantic-fault-probe",
                   "--semantic-fault-mode","hung_inference","--node-name",
                   "ip-10-0-44-146.ec2.internal","--console-only-server","--contact-audit",
                   "--rear-casters","--physics-step","0.002","--lidar-range","12",
                   "--odom-frequency","200")
        for flags in (("--semantic-fault-mode","hung_inference",),
                      ("--semantic-fault-probe",),
                      ("--semantic-fault-probe","--suite","hotel-guarded"),
                      ("--semantic-fault-probe","--suite","hotel-guarded",
                       "--semantic-fault-mode","tf_loss"),
                      ("--semantic-fault-probe","--sam3-observation","--suite","hotel-guarded",
                       "--semantic-fault-mode","tf_loss","--recovery-probe"),
                      ("--semantic-fault-probe","--sam3-observation","--suite","hotel-guarded",
                       "--semantic-fault-mode","tf_loss","--fault-stop-probe"),
                      ("--semantic-fault-probe","--sam3-observation","--suite","hotel-guarded",
                       "--semantic-fault-mode","tf_loss","--tf-loss-probe")):
            with self.subTest(flags=flags):
                result=self.parse(*flags)
                self.assertEqual(result.returncode,2)
        result=self.parse(*qualified)
        self.assertEqual(result.returncode,2)
        self.assertIn("requires digest-pinned namespace safety image",result.stderr)

    def test_semantic_arm_requires_the_frozen_guarded_sam3_gpu_profile(self):
        qualified=("--suite","hotel-guarded","--sam3-observation","--semantic-arm","on",
                   "--node-name","ip-10-0-44-146.ec2.internal","--gpu-rendering",
                   "--console-only-server","--contact-audit","--rear-casters",
                   "--physics-step","0.002","--lidar-range","12","--odom-frequency","200")
        for flags in (("--semantic-arm","on",),
                      ("--semantic-arm","on","--suite","hotel-guarded"),
                      ("--semantic-arm","on","--suite","hotel-guarded","--sam3-observation"),
                      ("--semantic-arm","on","--suite","hotel-guarded","--sam3-observation",
                       "--recovery-probe"),
                      ("--semantic-arm","on","--suite","hotel-guarded","--sam3-observation",
                       "--semantic-fault-probe","--semantic-fault-mode","tf_loss"),
                      # Qualified profile but missing --gpu-rendering.
                      ("--semantic-arm","on","--suite","hotel-guarded","--sam3-observation",
                       "--console-only-server","--contact-audit","--rear-casters",
                       "--physics-step","0.002","--lidar-range","12","--odom-frequency","200",
                       "--node-name","ip-10-0-44-146.ec2.internal"),
                      # Non-finite goal coordinates are refused.
                      qualified+("--phase6-goal-x","nan"),
                      ("--phase6-stationary-smoke","--semantic-arm","off"),
                      ("--phase6-stationary-smoke",)):
            with self.subTest(flags=flags):
                result=self.parse(*flags)
                self.assertEqual(result.returncode,2)
        result=self.parse(*qualified)
        self.assertEqual(result.returncode,2)
        self.assertIn("requires digest-pinned namespace safety image",result.stderr)
        result=self.parse(*qualified,"--phase6-stationary-smoke")
        self.assertEqual(result.returncode,2)
        self.assertIn("requires digest-pinned namespace safety image",result.stderr)

    def test_fault_stop_probe_requires_qualified_pinned_moving_profile(self):
        qualified=("--suite","hotel-guarded","--fault-stop-probe","--fault-stop-mode",
                   "scan_loss","--node-name","ip-10-0-44-146.ec2.internal",
                   "--console-only-server","--contact-audit","--rear-casters",
                   "--physics-step","0.002","--lidar-range","12","--odom-frequency","200")
        for flags in (("--fault-stop-mode","scan_loss",),
                      ("--fault-stop-probe",),
                      ("--fault-stop-probe","--suite","native"),
                      ("--fault-stop-probe","--suite","hotel-guarded"),
                      ("--fault-stop-probe","--suite","hotel-guarded","--fault-stop-mode",
                       "collision_state"),
                      ("--fault-stop-probe","--suite","hotel-guarded","--fault-stop-mode",
                       "collision_state","--recovery-probe"),
                      ("--fault-stop-probe","--suite","hotel-guarded","--fault-stop-mode",
                       "collision_state","--tf-loss-probe"),
                      ("--fault-stop-probe","--suite","hotel-guarded","--fault-stop-mode",
                       "collision_state","--node-name","ip-10-0-44-146.ec2.internal"),
                      ("--fault-stop-probe","--suite","hotel-guarded","--fault-stop-mode",
                       "collision_state","--node-name","ip-10-0-44-146.ec2.internal",
                       "--console-only-server"),
                      ("--fault-stop-probe","--suite","hotel-guarded","--fault-stop-mode",
                       "collision_state","--node-name","ip-10-0-44-146.ec2.internal",
                       "--console-only-server","--contact-audit"),
                      ("--fault-stop-probe","--suite","hotel-guarded","--fault-stop-mode",
                       "collision_state","--node-name","ip-10-0-44-146.ec2.internal",
                       "--console-only-server","--contact-audit","--rear-casters",
                       "--physics-step","0.002","--lidar-range","12")):
            with self.subTest(flags=flags):
                result=self.parse(*flags)
                self.assertEqual(result.returncode,2)
        # The fully qualified profile reaches the digest-pin gate only.
        result=self.parse(*qualified)
        self.assertEqual(result.returncode,2)
        self.assertIn("requires digest-pinned namespace safety image",result.stderr)
        # The same profile rejects diagnostic overlays it cannot combine with.
        for extra in (("--moving-timing-trace",),("--gz-thread-probe",),
                      ("--diagnostic-no-world-recording",)):
            with self.subTest(extra=extra):
                result=self.parse(*qualified,*extra)
                self.assertEqual(result.returncode,2)


if __name__=="__main__": unittest.main()
