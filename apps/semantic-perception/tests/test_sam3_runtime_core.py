from collections import deque
from types import SimpleNamespace
import unittest

import numpy as np

from sam3_runtime_core import (
    normalize_masks,
    pop_synchronized_triplet,
    replace_oldest_bounded,
)


def message(stamp_ns):
    sec, nanosec = divmod(stamp_ns, 1_000_000_000)
    return SimpleNamespace(
        header=SimpleNamespace(stamp=SimpleNamespace(sec=sec, nanosec=nanosec))
    )


class RuntimeCoreTests(unittest.TestCase):
    def test_triplet_match_within_tolerance_and_preserves_headers(self):
        rgb, depth, info = deque([message(100)]), deque([message(120)]), deque([message(90)])
        matched, discarded = pop_synchronized_triplet(rgb, depth, info, 30)
        self.assertIsNotNone(matched)
        self.assertEqual([item.header.stamp.sec * 1_000_000_000 + item.header.stamp.nanosec
                          for item in matched], [100, 120, 90])
        self.assertEqual(discarded, {"rgb": 0, "depth": 0, "info": 0})
        self.assertFalse(rgb or depth or info)

    def test_discards_only_oldest_until_triplet_can_match(self):
        rgb = deque([message(0), message(100)])
        depth = deque([message(100)])
        info = deque([message(105)])
        matched, discarded = pop_synchronized_triplet(rgb, depth, info, 30)
        self.assertEqual(discarded, {"rgb": 1, "depth": 0, "info": 0})
        self.assertEqual(matched[0].header.stamp.nanosec, 100)

    def test_bounded_queue_drops_oldest_not_newest(self):
        queue = deque(maxlen=2)
        self.assertFalse(replace_oldest_bounded(queue, 1))
        self.assertFalse(replace_oldest_bounded(queue, 2))
        self.assertTrue(replace_oldest_bounded(queue, 3))
        self.assertEqual(list(queue), [2, 3])

    def test_normalizes_empty_result_as_valid_zero_mask(self):
        mask, scores = normalize_masks(np.empty((0, 1, 4, 5)), np.empty((0,)), 5, 4)
        self.assertEqual(mask.shape, (4, 5))
        self.assertEqual(mask.dtype, np.uint8)
        self.assertEqual(int(mask.sum()), 0)
        self.assertEqual(scores.size, 0)

    def test_unions_multiple_instance_masks(self):
        masks = np.zeros((2, 1, 2, 3), dtype=np.float32)
        masks[0, 0, 0, 0] = 0.9
        masks[1, 0, 1, 2] = 0.7
        union, scores = normalize_masks(masks, np.array([0.8, 0.7]), 3, 2)
        self.assertEqual(int(np.count_nonzero(union)), 2)
        self.assertEqual(union[0, 0], 2)
        self.assertEqual(union[1, 2], 2)
        np.testing.assert_allclose(scores, [0.8, 0.7], rtol=1e-6)

    def test_rejects_bad_shape_and_nonfinite_output(self):
        with self.assertRaises(ValueError):
            normalize_masks(np.ones((1, 2, 2)), np.ones(1), 3, 2)
        with self.assertRaises(ValueError):
            normalize_masks(np.array([[[np.nan]]]), np.ones(1), 1, 1)
        with self.assertRaises(ValueError):
            normalize_masks(np.ones((1, 1, 1)), np.array([np.inf]), 1, 1)


if __name__ == "__main__":
    unittest.main()
