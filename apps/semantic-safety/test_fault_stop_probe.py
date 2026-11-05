import unittest

from fault_stop_probe import (MODES, OBSTACLE_LATERAL_M, OBSTACLE_NAME,
                              OBSTACLE_POST_MODEL, OBSTACLE_STAGING_LATERAL_M,
                              obstacle_clears_hull, obstacle_spawn_pose,
                              obstacle_staging_pose, stop_latency_floor_ms,
                              stop_reason_qualified, stop_wait_seconds)


class FaultStopProbeTests(unittest.TestCase):
    def test_every_mode_has_a_qualified_reason_and_wait(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                self.assertTrue(stop_reason_qualified(mode, "sentinel") is False)
                self.assertGreater(stop_wait_seconds(mode), 0)

    def test_stop_reason_qualification(self):
        self.assertTrue(stop_reason_qualified("scan_loss", "scan_stale"))
        # The tf lease is scan-derived; both expire together on cutoff.
        self.assertTrue(stop_reason_qualified("scan_loss", "tf_stale"))
        self.assertTrue(stop_reason_qualified("command_stall", "command_expired"))
        self.assertTrue(stop_reason_qualified("collision_state", "collision_monitor_stop"))
        self.assertTrue(stop_reason_qualified("obstacle_spawn", "collision_monitor_stop"))
        self.assertTrue(stop_reason_qualified("transport_loss", "native_session_lost"))
        self.assertTrue(stop_reason_qualified("transport_loss", "native_queue_unavailable"))
        # A fault must not be requalified by an unrelated first reason.
        for mode in MODES:
            if mode not in ("collision_state", "obstacle_spawn"):
                self.assertFalse(stop_reason_qualified(mode, "collision_monitor_stop"))
            if mode != "scan_loss":
                self.assertFalse(stop_reason_qualified(mode, "tf_stale"))
            self.assertFalse(stop_reason_qualified(mode, "navigation_trial_timeout"))
        self.assertFalse(stop_reason_qualified("unknown", "scan_stale"))

    def test_scan_loss_requires_the_input_freshness_latency_band(self):
        # A genuine scan-evidence stop lands >= 300 ms after injection (the
        # 500 ms input deadline minus at most one 10 Hz scan interval);
        # faster stops belong to the command or watchdog deadlines.
        self.assertGreaterEqual(stop_latency_floor_ms("scan_loss"), 300.0)
        for mode in MODES:
            if mode != "scan_loss":
                self.assertEqual(stop_latency_floor_ms(mode), 0.0)

    def test_physical_obstacle_wait_is_longer_than_chain_faults(self):
        self.assertGreater(stop_wait_seconds("obstacle_spawn"),
                           stop_wait_seconds("scan_loss"))
        self.assertGreater(stop_wait_seconds("obstacle_spawn"),
                           stop_wait_seconds("command_stall"))

    def test_spawn_pose_is_ahead_and_left_of_the_physical_pose(self):
        pose = {"x": 15.4, "y": -31.6}
        spawn = obstacle_spawn_pose(pose)
        self.assertAlmostEqual(spawn["x"] - pose["x"], 0.70)
        self.assertAlmostEqual(spawn["y"] - pose["y"], 0.24)

    def test_staging_pose_is_far_off_the_corridor(self):
        start = (15.4, -31.6, 0.1, 0., 0., 0.)
        staging = obstacle_staging_pose(start)
        corridor = obstacle_spawn_pose({"x": start[0], "y": start[1]})
        # Same x as the corridor target but well outside the stop envelope,
        # the padded hull and the costmap inflation reach of the path.
        self.assertAlmostEqual(staging["x"], corridor["x"])
        self.assertGreater(abs(staging["y"] - corridor["y"]), OBSTACLE_STAGING_LATERAL_M - 0.1)
        self.assertGreater(abs(staging["y"] - start[1]), 0.315 + 0.35 + 0.03)

    def test_spawned_post_is_inside_envelope_but_outside_hull(self):
        # The whole post (half-width 0.03) must clear the padded hull
        # (|y| > 0.165) while staying inside the stop envelope (|y| < 0.315),
        # leaving symmetric drift margin on both boundaries.
        self.assertTrue(obstacle_clears_hull(OBSTACLE_LATERAL_M))
        inner = OBSTACLE_LATERAL_M - 0.03
        outer = OBSTACLE_LATERAL_M + 0.03
        self.assertGreater(inner - 0.165, 0.03)
        self.assertGreater(0.315 - outer, 0.03)
        self.assertFalse(obstacle_clears_hull(0.19))
        self.assertFalse(obstacle_clears_hull(0.30))

    def test_post_model_is_a_named_embeddable_model(self):
        model = OBSTACLE_POST_MODEL.format(name=OBSTACLE_NAME, x=15.0, y=-30.0)
        self.assertIn(f'<model name="{OBSTACLE_NAME}">', model)
        self.assertNotIn("<sdf", model)  # embedded inside the world, not a document
        self.assertIn("</model>", model)
        self.assertIn("<collision", model)


if __name__ == "__main__":
    unittest.main()
