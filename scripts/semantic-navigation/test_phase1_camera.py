import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from install_phase1_camera import add_camera, add_lighting_profile, add_phase2_targets


class Phase1CameraTest(unittest.TestCase):
    def test_camera_and_fixed_joint_are_added_once(self):
        with tempfile.TemporaryDirectory() as directory:
            world = Path(directory) / "world.sdf"
            world.write_text(
                '<sdf version="1.9"><world name="hotel">'
                '<model name="robot_1"><link name="base_link"/></model>'
                '</world></sdf>'
            )
            add_camera(world)
            model = ET.parse(world).find(".//model[@name='robot_1']")
            sensor = model.find("link[@name='camera_link']/sensor[@type='rgbd_camera']")
            self.assertIsNotNone(sensor)
            self.assertEqual(sensor.findtext("topic"), "/robot_1/camera")
            self.assertEqual(sensor.findtext("update_rate"), "10")
            self.assertEqual(sensor.findtext("camera/image/width"), "640")
            self.assertEqual(sensor.findtext("camera/image/height"), "480")
            self.assertEqual(sensor.findtext("gz_frame_id"), "camera_color_optical_frame")
            joint = model.find("joint[@name='camera_joint']")
            self.assertEqual(joint.get("type"), "fixed")
            self.assertEqual(joint.findtext("parent"), "base_link")
            self.assertEqual(joint.findtext("child"), "camera_link")
            with self.assertRaisesRegex(ValueError, "already exists"):
                add_camera(world)

    def test_missing_robot_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            world = Path(directory) / "world.sdf"
            world.write_text('<sdf version="1.9"><world name="hotel"/></sdf>')
            with self.assertRaisesRegex(ValueError, "not found"):
                add_camera(world)

    def test_phase2_adds_non_colliding_target_and_distractor_once(self):
        with tempfile.TemporaryDirectory() as directory:
            world = Path(directory) / "world.sdf"
            world.write_text('<sdf version="1.9"><world name="hotel"/></sdf>')
            add_phase2_targets(world)
            root = ET.parse(world)
            target = root.find(".//model[@name='semantic_target_mat']")
            distractor = root.find(".//model[@name='semantic_distractor_tile']")
            self.assertIsNotNone(target)
            self.assertIsNotNone(distractor)
            self.assertEqual(target.findtext("static"), "true")
            self.assertIsNone(target.find(".//collision"))
            self.assertEqual(target.findtext("pose"), "17.4014 -31.594 0.005 0 0 0")
            self.assertEqual(target.findtext("link/visual/geometry/box/size"),
                             "0.9 0.65 0.012")
            with self.assertRaisesRegex(ValueError, "already exists"):
                add_phase2_targets(world)

    def test_phase6_demo_triples_mat_width_without_changing_center_or_distractor(self):
        with tempfile.TemporaryDirectory() as directory:
            world = Path(directory) / "world.sdf"
            world.write_text('<sdf version="1.9"><world name="hotel"/></sdf>')
            add_phase2_targets(world, phase6_demo=True)
            root = ET.parse(world)
            target = root.find(".//model[@name='semantic_target_mat']")
            distractor = root.find(".//model[@name='semantic_distractor_tile']")
            self.assertEqual(target.findtext("link/visual/geometry/box/size"),
                             "1.2 1.95 0.012")
            self.assertEqual(target.findtext("pose"), "17.4014 -31.594 0.005 0 0 0")
            self.assertEqual(distractor.findtext("link/visual/geometry/box/size"),
                             "0.9 0.65 0.012")
            self.assertIsNone(target.find(".//collision"))

            # The clearance monitor must use exactly the staged dimensions.
            from demo_target_geometry import MAT_LENGTH_X, MAT_WIDTH_Y
            size = tuple(map(float, target.findtext("link/visual/geometry/box/size").split()))
            self.assertEqual(size, (MAT_LENGTH_X, MAT_WIDTH_Y, 0.012))

    def test_dim_lighting_profile_changes_world_ambient_and_sun(self):
        with tempfile.TemporaryDirectory() as directory:
            world = Path(directory) / "world.sdf"
            world.write_text(
                '<sdf version="1.9"><world name="hotel">'
                '<scene><ambient>1 1 1</ambient><background>0.8 0.8 0.8</background></scene>'
                '<light type="directional" name="sun">'
                '<diffuse>1 1 1 1</diffuse><specular>0.2 0.2 0.2 1</specular>'
                '</light></world></sdf>'
            )
            add_lighting_profile(world, "dim")
            root = ET.parse(world)
            self.assertEqual(root.findtext(".//scene/ambient"), "0.08 0.08 0.08")
            self.assertEqual(root.findtext(".//scene/background"), "0.12 0.12 0.12")
            self.assertEqual(root.findtext(".//light/diffuse"), "0.25 0.25 0.25 1")
            self.assertEqual(root.findtext(".//light/specular"), "0.05 0.05 0.05 1")
            with self.assertRaisesRegex(ValueError, "unsupported lighting profile"):
                add_lighting_profile(world, "not-a-profile")


if __name__ == "__main__":
    unittest.main()
