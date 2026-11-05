import unittest
import xml.etree.ElementTree as ET
from prepare_assets import prepare, micro_world

WORLD = '''<sdf><world name="w"><model name="robot_1"><pose>1 2 .1 0 0 0</pose>
<link name="base_footprint"/><link name="base_link"/>
<link name="base_scan"><pose>-.032 0 .172 0 0 0</pose><sensor name="lidar"><pose>0 0 .01 0 0 0</pose><update_rate>5</update_rate></sensor></link>
<plugin name="gz::sim::systems::DiffDrive"><topic>/robot_1/cmd_vel</topic><wheel_radius>.033</wheel_radius><wheel_separation>.287</wheel_separation></plugin></model></world></sdf>'''
URDF = '''<robot><link name="base_link"/>
<joint name="base_joint"><parent link="base_footprint"/><child link="base_link"/><origin xyz="0 0 .10"/></joint>
<joint name="scan_joint"><parent link="base_link"/><child link="base_scan"/><origin xyz="-.064 0 .172"/></joint></robot>'''


class AssetsTests(unittest.TestCase):
    def test_extrinsics(self):
        _, xml = prepare(WORLD, URDF)
        robot = ET.fromstring(xml)
        self.assertEqual(robot.find("joint[@name='base_joint']/origin").get("xyz"), "0 0 0")
        self.assertEqual(robot.find("joint[@name='scan_joint']/origin").get("xyz"), "-0.032 0 0.172")
        self.assertEqual(robot.find("joint[@name='lidar_sensor_joint']/origin").get("xyz"), "0 0 0.01")

    def test_only_private_drive_topic_and_one_watchdog(self):
        xml, _ = prepare(WORLD, URDF)
        model = ET.fromstring(xml).find(".//model")
        self.assertEqual(model.find("plugin/topic").text, "/phase5/internal_drive")
        self.assertEqual(len(model.findall("plugin[@name='phase5::DriveWatchdog']")), 1)
        self.assertNotIn("/robot_1/cmd_vel", xml)

    def test_unknown_geometry_and_double_patch_rejected(self):
        with self.assertRaises(ValueError): prepare(WORLD.replace("-.032", "-.099"), URDF)
        world, urdf = prepare(WORLD, URDF)
        with self.assertRaises(ValueError): prepare(world, urdf)

    def test_micro_world_preserves_robot_but_removes_sensors(self):
        world, _ = prepare(WORLD, URDF)
        micro = ET.fromstring(micro_world(world))
        self.assertFalse(micro.findall(".//sensor"))
        self.assertEqual(micro.find(".//model[@name='robot_1']/pose").text, "0 0 0.1 0 0 0")
        self.assertEqual(micro.find("world").get("name"), "phase5_watchdog_fixture")

    def test_private_lidar_rate_override(self):
        world, _ = prepare(WORLD, URDF, lidar_update_rate=20)
        sensor = ET.fromstring(world).find(".//sensor[@name='lidar']")
        self.assertEqual(float(sensor.findtext("update_rate")), 20.0)
        with self.assertRaises(ValueError): prepare(WORLD, URDF, lidar_update_rate=0)

    def test_private_step_and_virtual_range_preserve_sensor_pose_and_drive(self):
        source=WORLD.replace('</sensor>','<lidar><range><min>.12</min><max>3.5</max></range></lidar></sensor>')
        source=source.replace('</world>','<physics><max_step_size>.01</max_step_size></physics></world>')
        result,_=prepare(source,URDF,physics_step=.001,lidar_max_range=12.)
        tree=ET.fromstring(result)
        self.assertEqual(float(tree.findtext('world/physics/max_step_size')),.001)
        self.assertEqual(float(tree.findtext('.//sensor/lidar/range/max')),12.)
        self.assertEqual(tree.findtext('.//sensor/pose'),'0 0 .01 0 0 0')
        self.assertEqual(float(tree.findtext('.//sensor/lidar/range/min')),.12)
        with self.assertRaises(ValueError): prepare(source,URDF,physics_step=.1)
        with self.assertRaises(ValueError): prepare(source,URDF,lidar_max_range=100)

    def test_native_odometry_rate_override_does_not_change_frames(self):
        source=WORLD.replace('</plugin>','<odom_publish_frequency>50</odom_publish_frequency></plugin>')
        result,_=prepare(source,URDF,odom_frequency=200.)
        tree=ET.fromstring(result)
        self.assertEqual(float(tree.findtext('.//plugin/odom_publish_frequency')),200.)
        self.assertEqual(tree.findtext('.//plugin/wheel_radius'),'.033')
        with self.assertRaises(ValueError): prepare(source,URDF,odom_frequency=0)


if __name__ == "__main__":
    unittest.main()
