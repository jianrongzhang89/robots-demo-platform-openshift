import math
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from build_fixture import elevation, generate, ramp_mesh
from build_navigation import generate as navigation_fixture

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'docs/validation/warehouse-energy/phase-0/baseline-20261116/phase8-multilevel-hotel.world'


class FixtureTests(unittest.TestCase):
    def test_ramp_endpoints_and_smooth_transitions(self):
        for run in [10,20]:
            self.assertEqual(elevation(0,run),0)
            self.assertEqual(elevation(run,run),.2)
            self.assertLess(elevation(.001,run)/.001,1e-6)
            self.assertLess((.2-elevation(run-.001,run))/.001,1e-6)
            self.assertAlmostEqual(elevation(run/2,run),.1)

    def test_mesh_is_closed_and_normals_are_unit_vectors(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'ramp.obj';ramp_mesh(path,10)
            edges={};normals=0;faces=0
            for line in path.read_text().splitlines():
                if line.startswith('vn '):
                    self.assertAlmostEqual(sum(float(x)**2 for x in line.split()[1:]),1)
                    normals+=1
                if line.startswith('f '):
                    vertices=[int(x.split('//')[0]) for x in line.split()[1:]];faces+=1
                    for a,b in zip(vertices,vertices[1:]+vertices[:1]):
                        key=tuple(sorted((a,b)));edges[key]=edges.get(key,0)+1
            self.assertEqual(normals,faces)
            self.assertTrue(all(v==2 for v in edges.values()))

    def test_payload_is_dynamic_and_no_unbounded_velocity_controller_remains(self):
        before=SOURCE.read_bytes()
        with tempfile.TemporaryDirectory() as temp:
            generate(SOURCE,Path(temp),payload=.5)
            robot=ET.parse(Path(temp)/'world.sdf').find(".//model[@name='robot_1']")
            mass=sum(float(m.text) for m in robot.findall('link/inertial/mass'))
            self.assertAlmostEqual(mass,2.153)
            self.assertIsNotNone(robot.find("joint[@name='payload_fixed']"))
            self.assertFalse(any('DiffDrive' in p.get('name','') for p in robot.findall('plugin')))
            controllers=[p for p in robot.findall('plugin') if 'JointController' in p.get('name','')]
            self.assertEqual(len(controllers),2)
            for controller in controllers:
                self.assertEqual(controller.findtext('use_force_commands'),'true')
                self.assertEqual(float(controller.findtext('cmd_max')),.08)
        self.assertEqual(SOURCE.read_bytes(),before)

    def test_selected_corridor_blocks_other_ramp(self):
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)
            navigation_fixture(SOURCE,ROOT/'config/warehouse-energy/fixture-v0.json',output,'B','up',.5,1)
            header,pixels=(output/'map.pgm').read_bytes().split(b'255\n',1)
            width,height=600,240
            def value(x,y):
                ix=int((x+4)/.05);iy=int((y+3)/.05)
                return pixels[(height-1-iy)*width+ix]
            self.assertEqual(value(7,0),0)
            self.assertEqual(value(7,6),254)
            self.assertEqual(value(2,3),254)
            self.assertEqual(value(22,3),254)
            world=ET.parse(output/'world.sdf')
            exit_deck=world.find(".//model[@name='upper_b_exit']")
            pose=[float(x) for x in exit_deck.findtext('pose').split()]
            size=[float(x) for x in exit_deck.findtext('link/collision/geometry/box/size').split()]
            self.assertLessEqual(pose[1]+size[1]/2,5.25)
            pad=world.find(".//model[@name='upper_b_pad']")
            pose=[float(x) for x in pad.findtext('pose').split()]
            size=[float(x) for x in pad.findtext('link/collision/geometry/box/size').split()]
            self.assertGreaterEqual(pose[0]-size[0]/2,22.)


if __name__=='__main__':unittest.main()
