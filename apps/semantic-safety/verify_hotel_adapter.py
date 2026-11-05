"""Installed ROS callback regression tests; no native transport or motion."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from nav2_msgs.msg import CollisionMonitorState
from nav_msgs.msg import Odometry
from hotel_guard_adapter import HotelGuardAdapter
from safety_core import Now
from test_command_audit import graph
from tf_fault_buffer import ProbeTfBuffer
from tf2_ros import Buffer
from geometry_msgs.msg import TransformStamped
from rclpy.time import Time


class AdapterTests(unittest.TestCase):
    def test_probe_buffer_drops_map_edge_without_changing_other_buffer_or_static_tf(self):
        probe=ProbeTfBuffer(); full=Buffer()
        def transform(parent,child,second):
            t=TransformStamped();t.header.frame_id=parent;t.child_frame_id=child
            t.header.stamp.sec=second;t.transform.rotation.w=1.
            return t
        for buffer in (probe,full):
            buffer.set_transform(transform("map","odom",1),"test")
        probe.delivery.blocked=True
        for buffer in (probe,full):
            buffer.set_transform_static(transform("odom","lidar_frame",0),"test")
            buffer.set_transform(transform("map","odom",2),"test")
        self.assertFalse(probe.can_transform("map","lidar_frame",Time(seconds=2)))
        self.assertTrue(full.can_transform("map","lidar_frame",Time(seconds=2)))
        self.assertTrue(probe.can_transform("odom","lidar_frame",Time(seconds=2)))
        probe.delivery.blocked=False
        probe.set_transform(transform("map","odom",3),"test")
        self.assertTrue(probe.can_transform("map","lidar_frame",Time(seconds=3)))

    def setUp(self):
        self.a=HotelGuardAdapter.__new__(HotelGuardAdapter)
        self.a.expected_scan_max=3.5
        self.a.co=SimpleNamespace(commands_allowed=lambda:True,stop=Mock(),collision=Mock())
        self.a.joiner=SimpleNamespace(receive=Mock())
        self.a.graph=graph(); self.a.events=[]; self.a.command_trace=[]; self.a.samples={}
        self.a.invalid_inputs=set()
        self.a.last_evidence={}; self.a.tf_trace=[]; self.a.tf=Mock()
        self.a.now=lambda:Now(101,101,101)
        self.row={"kind":"raw","publisher_gid":self.a.graph["cmd_vel_nav"][0]["gid"],
                  "frame":"base_footprint","unused_axes":[0,0,0],"source_timestamp":100,
                  "stamp":90,"velocity":[.1,0.,0.]}

    def test_valid_command_enqueued_with_original_stamp(self):
        self.a.command(self.row)
        self.assertEqual(self.a.joiner.receive.call_args.args[0]["stamp"],90)
        self.a.co.stop.assert_not_called()

    def test_normal_navigation_does_not_scan_growing_wait_history(self):
        from priority_pump import StageTimings
        class ForbiddenHistory:
            def __iter__(self):
                raise AssertionError("normal command scanned Wait history")
        self.a.timings=StageTimings()
        self.a.co.task_token="task"
        self.a.co.events=ForbiddenHistory()
        self.a.co.checked=Mock(return_value=True)
        self.a.registry=SimpleNamespace(waiting=lambda *_:False,events=ForbiddenHistory())
        self.a.joiner.drain=lambda _: [dict(self.row,kind="checked",bound=90)]
        self.a._drain_commands(self.a.now())
        self.a.co.checked.assert_called_once_with(90,self.row["velocity"])

    def test_foreign_writer_never_enters_joiner(self):
        self.a.command({**self.row,"publisher_gid":[99]*16})
        self.a.joiner.receive.assert_not_called()
        self.a.co.stop.assert_called_once_with("command_provenance_invalid")

    def test_wrong_frame_rejected_before_admission(self):
        self.a.command({**self.row,"frame":"map"})
        self.a.joiner.receive.assert_not_called()
        self.a.co.stop.assert_called_once_with("command_provenance_invalid")

    def test_no_admission_when_task_not_authorized(self):
        self.a.co.commands_allowed=lambda:False
        self.a.command(self.row)
        self.a.joiner.receive.assert_not_called()

    def test_collision_message_is_delivered_to_latched_coordinator(self):
        self.a.collision(CollisionMonitorState(action_type=CollisionMonitorState.STOP,polygon_name="StopEnvelope"))
        self.a.co.collision.assert_called_once_with(1)

    def test_odometry_capture_not_receipt_time(self):
        message=Odometry(); message.header.frame_id="odom"; message.child_frame_id="base_footprint"
        message.header.stamp.sec=2; message.pose.pose.orientation.w=1.
        self.a.sensor("odom",message)
        self.assertEqual(self.a.samples["odom"],(2_000_000_000,"odom"))
        message.header.frame_id="map"
        self.a.sensor("odom",message)
        self.assertNotIn("odom",self.a.samples)
        self.assertIn("odom",self.a.invalid_inputs)
        self.a.co.stop.assert_called_once_with("odom_payload_invalid")

    def test_qualified_transform_is_not_requeried_or_renewed(self):
        self.a.last_evidence["tf"]=90
        self.a.evidence=Mock()
        self.a.scan_transform(90,"lidar_frame")
        self.a.tf.can_transform.assert_not_called()
        self.a.evidence.assert_not_called()

    def test_transform_uses_exact_capture_not_latest(self):
        self.a.tf.can_transform.return_value=True
        self.a.evidence=Mock()
        self.a.scan_transform(90,"lidar_frame")
        self.assertEqual(self.a.tf.lookup_transform.call_args.args[2].nanoseconds,90)
        self.a.evidence.assert_called_once_with("tf",90)

    def test_missing_capture_transform_never_uses_latest_as_evidence(self):
        self.a.tf.can_transform.return_value=False
        self.a.tf.lookup_transform.side_effect=RuntimeError("future extrapolation")
        self.a.evidence=Mock()
        self.a.scan_transform(90,"lidar_frame")
        self.a.evidence.assert_not_called()
        self.assertEqual(self.a.tf_trace[0]["first_error"],"future extrapolation")


if __name__=="__main__": unittest.main(verbosity=2)
