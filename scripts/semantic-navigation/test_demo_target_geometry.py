import unittest

from demo_target_geometry import (
    MAT_LENGTH_X,
    MAT_WIDTH_Y,
    REQUIRED_HULL_CLEARANCE,
    mat_bounds,
    polyline_enters_clearance_envelope,
    polyline_intersects_mat,
    polyline_min_hull_clearance,
)


class DemoTargetGeometryTests(unittest.TestCase):
    def test_demo_mat_length_keeps_direct_route_blocked_with_motion_runway(self):
        self.assertEqual(MAT_LENGTH_X, 1.2)
        self.assertEqual(MAT_WIDTH_Y, 1.95)
        for actual, expected in zip(
                mat_bounds(), (16.8014, 18.0014, -32.569, -30.619)):
            self.assertAlmostEqual(actual, expected, places=7)

    def test_straight_baseline_intersects_the_long_mat(self):
        path = [(15.402, -31.594), (19.402, -31.594)]
        self.assertTrue(polyline_intersects_mat(path))
        self.assertLess(polyline_min_hull_clearance(path), 0.0)

    def test_detour_requires_ten_centimeters_beyond_conservative_hull(self):
        clear_path = [(15.402, -33.05), (19.402, -33.05)]
        tight_path = [(15.402, -32.9), (19.402, -32.9)]
        self.assertFalse(polyline_intersects_mat(clear_path))
        self.assertFalse(polyline_enters_clearance_envelope(clear_path))
        self.assertGreaterEqual(polyline_min_hull_clearance(clear_path),
                                REQUIRED_HULL_CLEARANCE)
        self.assertTrue(polyline_enters_clearance_envelope(tight_path))

    def test_clearance_gate_checks_segments_between_path_vertices(self):
        path = [(15.5, -33.05), (17.4, -33.05), (19.3, -33.05)]
        self.assertFalse(polyline_enters_clearance_envelope(path))
        cut_corner = [(15.5, -33.05), (16.2, -31.6), (19.3, -33.05)]
        self.assertTrue(polyline_enters_clearance_envelope(cut_corner))

    def test_former_detour_now_intersects_widened_mat(self):
        path = [(15.402, -32.4), (19.402, -32.4)]
        self.assertTrue(polyline_intersects_mat(path))
        self.assertTrue(polyline_enters_clearance_envelope(path))
        self.assertLess(polyline_min_hull_clearance(path), 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
