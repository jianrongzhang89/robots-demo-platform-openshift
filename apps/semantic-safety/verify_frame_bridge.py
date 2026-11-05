"""Real ROS message/node callback tests; not moving TF qualification."""
import time
import unittest
from unittest.mock import Mock
import rclpy
from nav_msgs.msg import Odometry
from rosgraph_msgs.msg import Clock
from sensor_msgs.msg import LaserScan
from frame_bridge import FrameBridge


class FrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rclpy.init()

    @classmethod
    def tearDownClass(cls):
        rclpy.shutdown()

    def setUp(self):
        self.node = FrameBridge()
        self.node.tf.sendTransform = Mock()
        self.node.scan_pub.publish = Mock()
        self.node.status.publish = Mock()
        clock = Clock()
        clock.clock.sec = 20
        self.node.on_clock(clock)

    def tearDown(self):
        self.node.destroy_node()

    def odom(self):
        msg = Odometry()
        msg.header.stamp.sec = 20
        msg.header.frame_id = "odom"
        msg.child_frame_id = "base_footprint"
        msg.pose.pose.position.x = 1.23
        msg.pose.pose.orientation.w = 1.0
        return msg

    def test_pose_and_stamp_preserved_no_map_edge(self):
        msg = self.odom()
        self.node.on_odom(msg)
        tf = self.node.tf.sendTransform.call_args.args[0]
        self.assertEqual(tf.header, msg.header)
        self.assertEqual(tf.child_frame_id, "base_footprint")
        self.assertEqual(tf.transform.translation.x, 1.23)
        self.node.report()
        self.node.on_odom(msg)  # repeated receipt cannot produce fresh TF
        self.assertEqual(self.node.tf.sendTransform.call_count, 1)

    def test_stale_and_missing_clock_rejected(self):
        msg = self.odom()
        msg.header.stamp.sec = 19
        self.node.on_odom(msg)
        self.node.tf.sendTransform.assert_not_called()
        self.node.clock_progress = time.monotonic()-.6
        self.node.on_odom(self.odom())
        self.node.tf.sendTransform.assert_not_called()

    def test_delayed_capture_does_not_restart_deadline(self):
        msg = self.odom()
        msg.header.stamp.sec = 19
        msg.header.stamp.nanosec = 600000000
        before = time.monotonic()
        self.node.on_odom(msg)
        self.assertLessEqual(self.node.deadlines["odom"]-before, .11)

    def test_scan_stamp_preserved_and_sensor_offset_frame_used(self):
        msg = LaserScan()
        msg.header.stamp.sec = 20
        msg.header.frame_id = "robot_1/base_scan/lidar"
        self.node.on_scan(msg)
        fixed = self.node.scan_pub.publish.call_args.args[0]
        self.assertEqual(fixed.header.stamp, msg.header.stamp)
        self.assertEqual(fixed.header.frame_id, "lidar_frame")
        self.assertEqual(msg.header.frame_id, "robot_1/base_scan/lidar")

    def test_rollback_latches(self):
        clock = Clock()
        clock.clock.sec = 19
        self.node.on_clock(clock)
        clock.clock.sec = 20
        self.node.on_clock(clock)
        self.node.on_odom(self.odom())
        self.node.tf.sendTransform.assert_not_called()
        self.assertEqual(self.node.fault, "simulation_clock_rollback_restart_required")

    def test_unknown_frames_and_invalid_pose_fail_closed(self):
        msg = self.odom()
        msg.header.frame_id = "map"
        self.node.on_odom(msg)
        self.assertEqual(self.node.fault, "unexpected_odometry_frames")
        self.node.tf.sendTransform.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
