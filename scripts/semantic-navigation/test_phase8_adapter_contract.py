#!/usr/bin/env python3
"""Unit checks for Phase 8 RMF/Nav2 topic, completion, and cancel rules."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from local_nav2_fleet_adapter_contract import (  # noqa: E402
    cancellation_confirmed, keep_active_goal, nav2_success, ros_topic)


class Phase8AdapterContractTests(unittest.TestCase):
    def test_topics_resolve_with_and_without_robot_namespace(self):
        self.assertEqual(ros_topic("amcl_pose", "robot_1"), "/robot_1/amcl_pose")
        self.assertEqual(ros_topic("/navigate_to_pose", ""), "/navigate_to_pose")
        self.assertEqual(ros_topic("tf", None), "/tf")

    def test_only_nav2_succeeded_is_completion(self):
        self.assertTrue(nav2_success(4))
        for status in (0, 1, 2, 3, 5, 6):
            with self.subTest(status=status):
                self.assertFalse(nav2_success(status))

    def test_cancel_requires_ack_and_terminal_canceled_result(self):
        self.assertTrue(cancellation_confirmed(1, 5))
        self.assertFalse(cancellation_confirmed(0, 5))
        self.assertFalse(cancellation_confirmed(1, 4))
        self.assertFalse(cancellation_confirmed(1, 6))

    def test_same_rmf_activity_keeps_its_in_flight_nav2_goal(self):
        self.assertTrue(keep_active_goal(True, True, True))
        self.assertFalse(keep_active_goal(False, True, True))
        self.assertFalse(keep_active_goal(True, False, True))
        self.assertFalse(keep_active_goal(True, True, False))


if __name__ == "__main__":
    unittest.main()
