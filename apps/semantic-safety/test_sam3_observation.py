import unittest

import numpy as np

import sam3_observation


WORLD = """<sdf version="1.7"><world name="sim_world">
  <model name="semantic_target_mat"><pose>17.4014 -31.594 0.005 0 0 0</pose>
    <link name="surface"><visual name="v"><geometry><box><size>0.9 0.65 0.012</size></box></geometry></visual></link>
  </model>
</world></sdf>"""


class Sam3ObservationTests(unittest.TestCase):
    def setUp(self):
        self.rect = sam3_observation.parse_mat_ground_truth(WORLD)
        self.assertAlmostEqual(self.rect["xmin"], 17.4014 - 0.45)
        self.assertAlmostEqual(self.rect["ymax"], -31.594 + 0.325)

    def test_mat_ground_truth_requires_the_model(self):
        with self.assertRaises(ValueError):
            sam3_observation.parse_mat_ground_truth("<world/>")

    def test_decode_mask_rejects_mismatched_payloads(self):
        with self.assertRaises(ValueError):
            sam3_observation.decode_mask(b"\x00" * 10, 4, 4)

    def test_points_in_rectangle_counts_and_fractions(self):
        points = np.array([
            [17.4, -31.6, 0.0],   # on the mat
            [17.5, -31.5, 0.01],  # on the mat
            [16.0, -31.6, 0.0],   # far outside
            [17.45, -31.59, 2.0],  # inside x/y but implausibly high
            [17.4014 - 0.45 - 0.05, -31.594, 0.0],  # exactly at tolerance edge
        ])
        count, fraction = sam3_observation.points_in_rectangle(points, self.rect)
        self.assertEqual(count, 5)
        self.assertAlmostEqual(fraction, 3 / 5)

    def test_transform_points_applies_a_rigid_transform(self):
        quarter = np.pi / 2
        # z-rotation by 90 degrees, translation (1, 2, 3)
        q = (0.0, 0.0, np.sin(quarter / 2), np.cos(quarter / 2))
        points = np.array([[1.0, 0.0, 0.0]])
        moved = sam3_observation.transform_points(points, (1, 2, 3), q)
        self.assertTrue(np.allclose(moved, [[1.0, 3.0, 3.0]]), moved)

    def test_registration_summary_requires_moving_results_and_fraction(self):
        results = [{"selected": 100, "inside_fraction": 1.0, "moving": True}] * 10
        summary = sam3_observation.registration_summary(results)
        self.assertTrue(summary["passed"], summary)
        self.assertEqual(summary["moving_results"], 10)
        self.assertEqual(summary["pooled_selected_points"], 1000)
        # Stationary or tiny-mask results never count toward the contract.
        mixed = ([{"selected": 100, "inside_fraction": 1.0, "moving": True}] * 9
                 + [{"selected": 100, "inside_fraction": 1.0, "moving": False}]
                 + [{"selected": 10, "inside_fraction": 1.0, "moving": True}] * 5)
        self.assertFalse(sam3_observation.registration_summary(mixed)["passed"])
        # Pooled below the 95% contract fails.
        low = ([{"selected": 100, "inside_fraction": 1.0, "moving": True}] * 9
               + [{"selected": 100, "inside_fraction": 0.0, "moving": True}])
        self.assertFalse(sam3_observation.registration_summary(low)["passed"])
        # Unmatched payload rows are excluded from the moving population.
        self.assertFalse(sam3_observation.registration_summary(
            [{"selected": 0, "inside_fraction": 0.0, "moving": True, "matched": False}] * 20)["passed"])

    def test_timing_summary_enforces_age_and_rate(self):
        ages = [100.0] * 18 + [600.0, 600.0]
        summary = sam3_observation.timing_summary(ages, 20, 4.0)
        self.assertFalse(summary["passed"])
        self.assertEqual(summary["p95_capture_age_ms"], 600.0)
        self.assertAlmostEqual(summary["results_per_second"], 5.0)
        self.assertTrue(sam3_observation.timing_summary([100.0] * 20, 20, 4.0)["passed"])
        self.assertFalse(sam3_observation.timing_summary([], 0, 4.0)["passed"])


if __name__ == "__main__":
    unittest.main()
