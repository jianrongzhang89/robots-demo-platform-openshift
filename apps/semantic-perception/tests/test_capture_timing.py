import unittest
from capture_timing import capture_age_upper_ms, capture_deadline, validate_capture_trace, simulation_capture_age_ms


class TimingTests(unittest.TestCase):
    def setUp(self):
        self.trace = dict(schema="semantic-capture/v1", source_epoch="epoch", sequence=1,
            stamp_ns=100, capture_wall_ns=1_000_000_000, rendered_wall_ns=1_010_000_000,
            source_publish_wall_ns=1_012_000_000, render_duration_ns=10_000_000,
            source_duration_ns=12_000_000)

    def test_valid_trace_and_conservative_age(self):
        validate_capture_trace(self.trace)
        self.assertEqual(capture_age_upper_ms(self.trace, 1_100_000_000, 2), 102)

    def test_transport_delay_does_not_refresh_deadline(self):
        early = capture_deadline(self.trace, 1_100_000_000, 20.1, .5, 2)
        late = capture_deadline(self.trace, 1_400_000_000, 20.4, .5, 2)
        self.assertAlmostEqual(early, late)
        with self.assertRaises(TimeoutError):
            capture_deadline(self.trace, 1_600_000_000, 20.6, .5, 2)

    def test_future_trace_clock_jump_and_malformed_data_fail(self):
        with self.assertRaises(ValueError):
            capture_age_upper_ms(self.trace, 900_000_000, 2)
        for key, value in [("source_epoch", ""), ("stamp_ns", -1), ("sequence", "1"),
                           ("source_publish_wall_ns", 2_000_000_000)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_capture_trace({**self.trace, key: value})

    def test_pause_cannot_make_capture_fresh(self):
        # Simulation stamp is deliberately unchanged; wall age still expires.
        with self.assertRaises(TimeoutError):
            capture_deadline(self.trace, 3_000_000_000, 22, .5, 2)

    def test_clock_reset_and_forward_jump_rejected_at_publication(self):
        for clock in (0, 2_000_000_000):
            with self.assertRaises(TimeoutError):
                simulation_capture_age_ms(clock, 1_000_000_000, 500)
        self.assertEqual(simulation_capture_age_ms(1_200_000_000, 1_000_000_000, 500), 200)
