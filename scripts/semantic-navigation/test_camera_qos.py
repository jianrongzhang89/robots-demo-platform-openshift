#!/usr/bin/env python3
"""Unit tests for RGB-D camera subscription QoS configuration."""

import unittest

from camera_qos import subscription_history_depth


class TestCameraQos(unittest.TestCase):
    def test_default_preserves_existing_depth(self):
        self.assertEqual(subscription_history_depth(None), 2)

    def test_accepts_positive_configured_depth(self):
        self.assertEqual(subscription_history_depth("20"), 20)

    def test_rejects_non_integer_depth(self):
        with self.assertRaises(ValueError):
            subscription_history_depth("many")

    def test_rejects_non_positive_depth(self):
        for value in ("0", "-1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                subscription_history_depth(value)


if __name__ == "__main__":
    unittest.main()
