import unittest

from semantic_fault_probe import (MODES, QUALIFIED_REASONS, STREAK_GAP_NS,
                                  late_success_key,
                                  late_success_wait_seconds,
                                  observe_result_for_streak,
                                  observation_window,
                                  observation_window_end,
                                  result_streak_seconds,
                                  stop_reason_qualified,
                                  stop_wait_seconds)


class SemanticFaultProbeTests(unittest.TestCase):
    def test_every_mode_has_a_qualified_reason_set(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                self.assertTrue(QUALIFIED_REASONS[mode])
                self.assertFalse(stop_reason_qualified(mode, "navigation_trial_timeout"))
                self.assertFalse(stop_reason_qualified(mode, ""))
                self.assertGreater(stop_wait_seconds(mode), 0)
                self.assertGreater(late_success_wait_seconds(mode), 0)

    def test_semantic_faults_qualify_through_the_semantic_leases(self):
        for mode in ("camera_path_loss", "hung_inference", "process_loss",
                     "transport_loss"):
            for reason in ("camera_stale", "semantic_stale",
                           "inference_heartbeat_stale", "inference_heartbeat_invalid_age"):
                self.assertTrue(stop_reason_qualified(mode, reason), (mode, reason))

    def test_tf_loss_keeps_the_geometry_only_acceptance(self):
        self.assertTrue(stop_reason_qualified("tf_loss", "tf_stale"))
        self.assertTrue(stop_reason_qualified("tf_loss", "command_expired"))
        # The semantic leases stay fresh through TF loss: a semantic-stale
        # stop would mean the wrong path tripped.
        for reason in ("semantic_stale", "inference_heartbeat_stale"):
            self.assertFalse(stop_reason_qualified("tf_loss", reason))

    def test_semantic_leases_do_not_qualify_a_navigation_timeout(self):
        for mode in MODES:
            self.assertFalse(stop_reason_qualified(mode, "native_session_lost"))
            self.assertFalse(stop_reason_qualified(mode, "command_expired")
                             if mode != "tf_loss" else False)

    def test_late_success_key_and_waits(self):
        self.assertEqual(late_success_key("camera_path_loss"), "camera")
        self.assertIsNone(late_success_key("tf_loss"))
        self.assertEqual(late_success_key("process_loss"), "inference_heartbeat")
        # Process loss waits for the container restart and model reload.
        self.assertGreater(late_success_wait_seconds("process_loss"),
                           late_success_wait_seconds("hung_inference"))
        # Externally injected modes wait longer for the stop (runner latency).
        self.assertGreater(stop_wait_seconds("transport_loss"),
                           stop_wait_seconds("camera_path_loss"))

    def test_observation_window_scopes_to_the_pre_fault_period(self):
        receipts = [1000, 1100, 1200, 1300, 1400]
        self.assertEqual(observation_window_end(1250, receipts), [1000, 1100, 1200])
        self.assertEqual(observation_window_end(None, receipts), receipts)
        self.assertEqual(observation_window_end(500, receipts), [])

    def test_observation_window_trims_the_leading_warmup(self):
        # A fresh pod's stream begins during the camera warmup: a few
        # results, a long gap, then the settled stream the arming streak
        # requires. The throughput window must measure only the settled part.
        receipts = [1000, 1100, 1200, 15_000_000_000, 15_000_100_000,
                    15_000_200_000, 15_000_300_000]
        window = observation_window(None, receipts)
        self.assertEqual(window, receipts[3:])
        # The stop scope still applies after the warmup trim.
        self.assertEqual(observation_window(15_000_250_000, receipts), receipts[3:6])
        # Gaps at or below the lease freshness stay in the window.
        dense = [1000, 1100, 2100, 3100]
        self.assertEqual(observation_window(None, dense, warmup_gap_s=1.0), dense)
        # An empty or single receipt window is preserved.
        self.assertEqual(observation_window(None, [5]), [5])
        self.assertEqual(observation_window(None, []), [])

    def test_fresh_dense_results_grow_the_streak(self):
        state = {}
        start = 1_000_000_000_000
        for i in range(20):
            now = start + i * 100_000_000
            observe_result_for_streak(state, now, now - 200_000_000)
            self.assertLessEqual(result_streak_seconds(state, now), (i + 1) * 0.1 + 1e-9)
        self.assertGreaterEqual(result_streak_seconds(state, start + 1_900_000_000), 1.9 - 1e-9)

    def test_stale_result_resets_the_streak(self):
        state = {}
        start = 1_000_000_000_000
        for i in range(10):
            observe_result_for_streak(state, start + i * 100_000_000, start + i * 100_000_000 - 200_000_000)
        # A result whose capture age exceeds the bound restarts the streak.
        observe_result_for_streak(state, start + 1_000_000_000, start + 100_000_000)
        self.assertEqual(result_streak_seconds(state, start + 1_000_000_000), 0.0)
        observe_result_for_streak(state, start + 1_100_000_000, start + 900_000_000)
        # The restarted streak measures the span covered by dense fresh
        # results: one result alone covers nothing yet.
        self.assertAlmostEqual(result_streak_seconds(state, start + 1_100_000_000), 0.0)
        observe_result_for_streak(state, start + 1_200_000_000, start + 1_000_000_000)
        self.assertAlmostEqual(result_streak_seconds(state, start + 1_200_000_000), 0.1)

    def test_result_gap_resets_the_streak(self):
        state = {}
        start = 1_000_000_000_000
        observe_result_for_streak(state, start, start - 100_000_000)
        observe_result_for_streak(state, start + 100_000_000, start)
        # A multi-second burst gap restarts the streak even for fresh results.
        observe_result_for_streak(state, start + 2_100_000_000, start + 2_000_000_000)
        self.assertAlmostEqual(result_streak_seconds(state, start + 2_100_000_000), 0.0)

    def test_stopped_results_report_zero_streak(self):
        state = {}
        start = 1_000_000_000_000
        for i in range(15):
            observe_result_for_streak(state, start + i * 100_000_000, start + i * 100_000_000)
        # Once results stop arriving the streak must not linger.
        self.assertAlmostEqual(
            result_streak_seconds(state, start + 1_400_000_000 + STREAK_GAP_NS), 0.0)


if __name__ == "__main__":
    unittest.main()
