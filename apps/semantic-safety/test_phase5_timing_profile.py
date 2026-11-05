import unittest

from phase5_timing_profile import moving_trace_geometry_matches


class MovingTraceProfileTests(unittest.TestCase):
    def test_numeric_cli_serializations_are_equivalent(self):
        self.assertTrue(moving_trace_geometry_matches("0.002", "12", "200"))
        self.assertTrue(moving_trace_geometry_matches("0.002", "12.0", "200.0"))

    def test_missing_or_changed_geometry_fails_closed(self):
        for profile in ((None, "12.0", "200.0"), ("0.01", "12.0", "200.0"),
                        ("0.002", "3.5", "200.0"), ("0.002", "12.0", "50.0"),
                        ("nan", "12.0", "200.0")):
            with self.subTest(profile=profile):
                self.assertFalse(moving_trace_geometry_matches(*profile))


if __name__ == "__main__":
    unittest.main()
