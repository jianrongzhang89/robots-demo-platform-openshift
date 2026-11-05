#!/usr/bin/env python3
"""Exercise the installed adapter's late-capture reset barrier without a model."""
from collections import OrderedDict
import threading
import time
from types import SimpleNamespace
import unittest

from sam3_ros_node import Sam3Runtime


class ResetBarrierTests(unittest.TestCase):
    def test_late_pre_reset_capture_rejected_even_with_overlapping_sim_stamp(self):
        wall, mono = time.time_ns(), time.monotonic()
        trace = {"source_epoch": "source", "capture_wall_ns": wall-100_000_000}
        state = SimpleNamespace(require_trace=True, stale_after_s=.5,
            stop_event=threading.Event(), lock=threading.Lock(),
            capture_traces={100_000_000: trace}, compression_traces={100_000_000: {"schema": "test"}},
            capture_after_wall_ns=wall-80_000_000, source_epoch="source", epoch="adapter",
            sim_clock_ns=200_000_000, sim_clock_received=mono, clock_uncertainty_ms=2)
        rgb = SimpleNamespace(header=SimpleNamespace(stamp=SimpleNamespace(sec=0, nanosec=100_000_000)))
        bundle = SimpleNamespace(rgb=rgb, received_monotonic=mono, epoch="adapter")
        with self.assertRaisesRegex(TimeoutError, "predates observed simulation reset"):
            Sam3Runtime.capture_context(state, bundle)
        # A truly post-reset wall capture with the SAME simulation stamp is valid.
        trace["capture_wall_ns"] = wall-50_000_000
        _, _, deadline = Sam3Runtime.capture_context(state, bundle)
        self.assertGreater(deadline, time.monotonic())
        self.assertLessEqual(deadline-mono, .5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
