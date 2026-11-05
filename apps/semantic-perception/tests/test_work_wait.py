import unittest

from sam3_runtime_core import work_wait_expired


class WorkWaitTests(unittest.TestCase):
    def test_admits_new_frame_and_discards_waiting_frame(self):
        self.assertFalse(work_wait_expired(10, 10.020, 40))
        self.assertTrue(work_wait_expired(10, 10.041, 40))

    def test_disabled_by_default(self):
        self.assertFalse(work_wait_expired(10, 20, 0))

    def test_invalid_values(self):
        for limit in (-1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                work_wait_expired(10, 10, limit)
