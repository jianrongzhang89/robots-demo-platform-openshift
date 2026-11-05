import unittest
from types import SimpleNamespace as NS
from tf_fault_probe import TfDeliveryFilter, map_failure, stop_reason_qualified


class TfFaultProbeTests(unittest.TestCase):
    def test_filter_only_drops_selected_edge_and_can_restore(self):
        delivery=TfDeliveryFilter()
        def edge(parent,child):
            return NS(header=NS(frame_id=parent,stamp=NS(sec=1,nanosec=2)),child_frame_id=child)
        self.assertTrue(delivery.admit(edge("map","odom")))
        delivery.blocked=True
        self.assertFalse(delivery.admit(edge("/map","/odom")))
        self.assertTrue(delivery.admit(edge("odom","base_footprint")))
        self.assertTrue(delivery.admit(edge("base_footprint","lidar_frame")))
        delivery.blocked=False
        self.assertTrue(delivery.admit(edge("map","odom")))
        self.assertEqual(len(delivery.dropped),1)
        self.assertEqual(delivery.dropped[0]["stamp"],1_000_000_002)

    def test_map_failure_requires_new_capture_frozen_map_and_live_odom(self):
        row={"stamp":110,"first_failure_wall_ns":210,"transform_available":False,
             "first_error":"future extrapolation","map_to_odom_latest":105,
             "odom_to_lidar_frame_latest":115}
        self.assertIs(map_failure([row],200,100),row)
        for override in ({"stamp":99},{"first_failure_wall_ns":199},
                         {"map_to_odom_latest":111},{"odom_to_lidar_frame_latest":109},
                         {"transform_available":True},{"first_error":None}):
            with self.subTest(override=override):
                self.assertIsNone(map_failure([{**row,**override}],200,100))

    def test_earlier_command_stop_is_only_qualified_for_publisher_outage(self):
        self.assertTrue(stop_reason_qualified("amcl","command_expired"))
        self.assertFalse(stop_reason_qualified("supervisor","command_expired"))
        for mode in ("amcl","supervisor"):
            self.assertTrue(stop_reason_qualified(mode,"tf_stale"))
            for reason in ("native_capture_stale","navigation_trial_timeout","fixture_shutdown"):
                self.assertFalse(stop_reason_qualified(mode,reason))
