"""Exercise the real callback without loading a model or starting ROS nodes."""
from collections import deque
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from sam3_ros_node import Sam3Runtime


class ClockRollbackTests(unittest.TestCase):
    def state(self):
        return SimpleNamespace(lock=threading.Lock(), sim_clock_ns=20_000_000_000,
            sim_clock_received=0, epoch="old", guard=Mock(), ready=True, last_error=None,
            capture_after_wall_ns=0, clock_uncertainty_ms=2,
            rgb_queue=deque([1]), depth_queue=deque([2]), info_queue=deque([3]), work_queue=deque([4]),
            capture_traces={1: "old"}, compression_traces={1: "old"}, last_input_stamp={"rgb": 1})

    def test_reset_invalidates_before_new_camera_message(self):
        state = self.state()
        Sam3Runtime.on_clock(state, SimpleNamespace(clock=SimpleNamespace(sec=0, nanosec=0)))
        self.assertNotEqual(state.epoch, "old")
        state.guard.reset.assert_called_once_with(state.epoch, 1)
        self.assertFalse(state.ready)
        self.assertEqual(state.last_error, "simulation_clock_rollback")
        self.assertGreater(state.capture_after_wall_ns, 0)
        for queue in (state.rgb_queue, state.depth_queue, state.info_queue, state.work_queue,
                      state.capture_traces, state.compression_traces, state.last_input_stamp):
            self.assertFalse(queue)

    def test_forward_clock_preserves_inflight_identity(self):
        state = self.state()
        Sam3Runtime.on_clock(state, SimpleNamespace(clock=SimpleNamespace(sec=21, nanosec=0)))
        self.assertEqual(state.epoch, "old")
        state.guard.reset.assert_not_called()
        self.assertTrue(state.ready)
