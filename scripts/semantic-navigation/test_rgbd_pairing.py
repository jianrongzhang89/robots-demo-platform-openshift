#!/usr/bin/env python3
"""Unit tests for timestamp-ordered RGB-D pairing."""

from collections import deque
import unittest

from camera_qos import subscription_history_depth
from rgbd_pairing import drain_synchronized_pairs


class TestRgbdPairing(unittest.TestCase):
    def test_subscription_history_depth_is_configurable_and_validated(self):
        self.assertEqual(subscription_history_depth(None), 2)
        self.assertEqual(subscription_history_depth("20"), 20)
        for value in ("0", "-1", "many"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                subscription_history_depth(value)

    def test_pairs_all_aligned_frames_arriving_as_a_batch(self):
        rgb = deque([0, 100, 200, 300])
        depth = deque([0, 100, 200, 300])

        pairs, discarded, checks, max_skew = drain_synchronized_pairs(
            rgb, depth, lambda stamp: stamp, tolerance_ns=0
        )

        self.assertEqual(pairs, [(0, 0), (100, 100), (200, 200), (300, 300)])
        self.assertEqual(discarded, {"rgb": 0, "depth": 0})
        self.assertEqual(checks, 4)
        self.assertEqual(max_skew, 0)
        self.assertFalse(rgb)
        self.assertFalse(depth)

    def test_discards_only_older_unmatched_frames(self):
        rgb = deque([0, 100, 200])
        depth = deque([5, 105, 250])

        pairs, discarded, _, _ = drain_synchronized_pairs(
            rgb, depth, lambda stamp: stamp, tolerance_ns=10
        )

        self.assertEqual(pairs, [(0, 5), (100, 105)])
        self.assertEqual(discarded, {"rgb": 1, "depth": 0})
        self.assertEqual(list(depth), [250])

    def test_retains_messages_when_other_queue_is_empty(self):
        rgb = deque([10, 20])
        depth = deque()

        pairs, discarded, checks, _ = drain_synchronized_pairs(
            rgb, depth, lambda stamp: stamp, tolerance_ns=30
        )

        self.assertEqual(pairs, [])
        self.assertEqual(discarded, {"rgb": 0, "depth": 0})
        self.assertEqual(checks, 0)
        self.assertEqual(list(rgb), [10, 20])

    def test_rejects_negative_tolerance(self):
        with self.assertRaises(ValueError):
            drain_synchronized_pairs(deque(), deque(), lambda stamp: stamp, -1)


if __name__ == "__main__":
    unittest.main()
