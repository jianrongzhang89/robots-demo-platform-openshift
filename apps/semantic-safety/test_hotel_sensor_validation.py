import unittest
from types import SimpleNamespace as N
from hotel_sensor_validation import valid_scan, valid_odom


class SensorValidationTests(unittest.TestCase):
    def scan(self):
        return N(header=N(frame_id="lidar_frame"),ranges=[1.]*360,range_min=.12,range_max=3.5,
                 angle_min=0.,angle_max=6.28,angle_increment=.0175)

    def test_scan_valid_and_infinity_is_no_return(self):
        scan=self.scan(); scan.ranges[0]=float("inf")
        self.assertTrue(valid_scan(scan))
        scan.ranges=[float("inf")]*360
        self.assertTrue(valid_scan(scan))

    def test_empty_nan_and_unknown_geometry_fail(self):
        for ranges in ([],[float("nan")]*360,[float("-inf")]*360,[-1.]*360):
            scan=self.scan(); scan.ranges=ranges
            self.assertFalse(valid_scan(scan))
        scan=self.scan(); scan.header.frame_id="wrong"
        self.assertFalse(valid_scan(scan))

    def test_odom_nonfinite_and_bad_quaternion_fail(self):
        vector=lambda:N(x=0.,y=0.,z=0.)
        odom=N(header=N(frame_id="odom"),child_frame_id="base_footprint",
               pose=N(pose=N(position=vector(),orientation=N(x=0.,y=0.,z=0.,w=1.))),
               twist=N(twist=N(linear=vector(),angular=vector())))
        self.assertTrue(valid_odom(odom))
        odom.pose.pose.orientation.w=0.
        self.assertFalse(valid_odom(odom))
        odom.pose.pose.orientation.w=1.; odom.twist.twist.linear.x=float("nan")
        self.assertFalse(valid_odom(odom))

    def test_virtual_sensor_range_requires_explicit_matching_contract(self):
        scan=self.scan(); scan.range_max=12.
        self.assertFalse(valid_scan(scan))
        self.assertTrue(valid_scan(scan,expected_max_range=12.))
        scan.range_max=3.5
        self.assertFalse(valid_scan(scan,expected_max_range=12.))
        self.assertFalse(valid_scan(scan,expected_max_range=100.))
