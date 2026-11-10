from __future__ import annotations

import argparse
import unittest

from capture_phase2_sample import format_pose_arguments, parse_gazebo_pose


class CapturePoseArgumentTests(unittest.TestCase):
    def test_gazebo_pose_accepts_tiny_negative_quaternion_values(self):
        payload = '{"pose":[{"name":"robot_1","position":{"x":1,"y":-2,"z":0.01},"orientation":{"x":-9.8e-8,"y":-0.029,"z":1.0e-7,"w":0.99957}}]}'
        values = parse_gazebo_pose(payload)
        tokens = format_pose_arguments(values)

        self.assertEqual(len(tokens), 7)
        self.assertTrue(all("e" not in token.lower() for token in tokens))
        self.assertEqual([float(token) for token in tokens], values)

        parser = argparse.ArgumentParser()
        parser.add_argument("--world-from-base-link", type=float, nargs=7)
        parsed = parser.parse_args(["--world-from-base-link", *tokens])
        self.assertEqual(parsed.world_from_base_link, values)

    def test_rejects_invalid_pose_argument_count(self):
        with self.assertRaisesRegex(ValueError, "seven values"):
            format_pose_arguments([0.0] * 6)


if __name__ == "__main__":
    unittest.main()
