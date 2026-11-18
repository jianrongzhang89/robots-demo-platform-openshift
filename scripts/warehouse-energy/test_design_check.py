"""Check physical units and signed-grade semantics before calibration exists."""
import math
import unittest

from design_check import segment_energy


class EnergySanityTests(unittest.TestCase):
    def test_auxiliary_wh_units(self):
        # One hour at 20 W, no rolling resistance or grade.
        self.assertAlmostEqual(segment_energy([0, 0, 0], [360, 0, 0],
                               2, 0.1, 0, 0.6, 20), 20)

    def test_identical_endpoint_gravitational_work(self):
        expected = 2 * 9.80665 / 0.5 / 3600
        for run in [10, 20]:
            self.assertAlmostEqual(segment_energy([0, 0, 0], [run, 0, 1],
                                   2, 0.1, 0, 0.5, 0), expected)

    def test_downhill_has_no_regeneration_credit(self):
        self.assertEqual(segment_energy([0, 0, 1], [10, 0, 0],
                         2, 0.1, 0.01, 0.6, 0), 0)

    def test_downhill_preserves_auxiliary_demand(self):
        expected = 20 * math.sqrt(101) / 0.1 / 3600
        self.assertAlmostEqual(segment_energy([0, 0, 1], [10, 0, 0],
                               2, 0.1, 0.01, 0.6, 20), expected)

    def test_rolling_energy_scales_with_mass(self):
        a, b = [0, 0, 0], [10, 0, 0]
        self.assertAlmostEqual(segment_energy(a, b, 4, 0.1, 0.03, 0.6, 0),
                               2 * segment_energy(a, b, 2, 0.1, 0.03, 0.6, 0))


if __name__ == "__main__":
    unittest.main()
