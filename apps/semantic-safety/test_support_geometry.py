import unittest
import xml.etree.ElementTree as ET
from support_geometry import add_rear_casters, CASTERS

WORLD='''<sdf><world><model name="robot_1">
<link name="base_link"><collision name="base_collision"><pose>-.032 0 .07 0 0 0</pose><geometry><box><size>.28 .31 .14</size></box></geometry></collision></link>
<link name="base_scan"><collision name="lidar_collision"/></link>
<link name="wheel_left_link"><pose>0 .144 .023 -1.57 0 0</pose><collision name="left_wheel_collision"><geometry><cylinder><radius>.033</radius></cylinder></geometry></collision></link>
<link name="wheel_right_link"><pose>0 -.144 .023 -1.57 0 0</pose><collision name="right_wheel_collision"><geometry><cylinder><radius>.033</radius></cylinder></geometry></collision></link>
</model></world></sdf>'''


class SupportTests(unittest.TestCase):
    def test_preserves_original_links_and_adds_rolling_supports_within_hull(self):
        world,urdf=add_rear_casters(WORLD,'<robot><link name="base_link"/></robot>')
        before=ET.fromstring(WORLD).find('.//model'); after=ET.fromstring(world).find('.//model')
        for link in before.findall('link'):
            self.assertEqual(ET.tostring(link),ET.tostring(after.find(f"link[@name='{link.get('name')}']")))
        self.assertEqual(len(after.findall('link/collision')),6)
        for name,x,y in CASTERS:
            self.assertTrue(-.172<x-.005<x+.005<.108 and abs(y)+.005<.155)
            link=after.find(f"link[@name='{name}']")
            self.assertAlmostEqual(float(link.findtext('pose').split()[2])-.005,-.01)
            self.assertEqual(after.find(f"joint[@name='{name}_joint']").get('type'),'ball')
            self.assertEqual(link.findtext('collision/surface/friction/ode/mu'),'1')
            self.assertIsNotNone(ET.fromstring(urdf).find(f"link[@name='{name}']"))
    def test_refuses_double_patch_and_unknown_geometry(self):
        world,urdf=add_rear_casters(WORLD,'<robot/>')
        with self.assertRaises(ValueError): add_rear_casters(world,urdf)
        with self.assertRaises(ValueError): add_rear_casters(WORLD.replace('.033','.04'),'<robot/>')
