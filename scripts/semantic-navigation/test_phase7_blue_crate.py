import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
import xml.etree.ElementTree as ET

import cv2
import numpy as np

from patch_phase7_blue_crate import TARGET, add_blue_crate, blue_crate_metadata_only
from capture_phase7_compressed import decode_color, decode_depth


class BlueCrateScenePatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.world = Path(self.temp.name) / "world.sdf"
        self.world.write_text('<sdf version="1.9"><world name="sim_world"/></sdf>')

    def tearDown(self):
        self.temp.cleanup()

    def test_adds_static_blue_box_with_geometry_metadata(self):
        metadata = add_blue_crate(self.world)
        model = ET.parse(self.world).getroot().find(".//model[@name='phase7_blue_crate']")
        self.assertEqual(metadata, TARGET)
        self.assertEqual(model.findtext("static"), "true")
        self.assertEqual(model.findtext("link/visual/geometry/box/size"), "0.45 0.35 0.4")
        self.assertEqual(model.findtext("link/collision/geometry/box/size"), "0.45 0.35 0.4")
        self.assertEqual(model.findtext("link/visual/material/diffuse"), "0.04 0.22 0.92 1")

    def test_refuses_to_patch_a_world_twice(self):
        add_blue_crate(self.world)
        with self.assertRaisesRegex(ValueError, "already exists"):
            add_blue_crate(self.world)

    def test_metadata_only_mode_preserves_a_crate_absent_world(self):
        metadata = blue_crate_metadata_only(self.world)
        self.assertEqual(metadata, TARGET)
        self.assertNotIn(TARGET["model"], self.world.read_text())

    def test_metadata_only_mode_refuses_a_present_crate(self):
        add_blue_crate(self.world)
        with self.assertRaisesRegex(ValueError, "crate is present"):
            blue_crate_metadata_only(self.world)

    def test_requires_a_world_element(self):
        self.world.write_text('<sdf version="1.9"><model name="x"/></sdf>')
        with self.assertRaisesRegex(ValueError, "no world"):
            add_blue_crate(self.world)

    def test_compressed_color_and_depth_decode_with_expected_layouts(self):
        color = np.zeros((5, 7, 3), dtype=np.uint8)
        depth = np.full((5, 7), 1234, dtype=np.uint16)
        ok_color, encoded_color = cv2.imencode(".jpg", color)
        ok_depth, encoded_depth = cv2.imencode(".png", depth)
        self.assertTrue(ok_color and ok_depth)
        self.assertEqual(decode_color(SimpleNamespace(data=encoded_color.tobytes())).shape,
                         (5, 7, 3))
        decoded_depth = decode_depth(SimpleNamespace(data=encoded_depth.tobytes()))
        self.assertEqual(decoded_depth.dtype, np.uint16)
        self.assertTrue(np.all(decoded_depth == 1234))

    def test_depth_decoder_rejects_non_uint16_payload(self):
        ok, encoded = cv2.imencode(".png", np.zeros((5, 7), dtype=np.uint8))
        self.assertTrue(ok)
        with self.assertRaisesRegex(ValueError, "uint16"):
            decode_depth(SimpleNamespace(data=encoded.tobytes()))


if __name__ == "__main__":
    unittest.main()
