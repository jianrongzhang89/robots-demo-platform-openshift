"""Regression: a graph-cleared lift lane must retain the actual shaft wall."""
import sys
import tempfile
import unittest
from pathlib import Path
import yaml
from PIL import Image, ImageChops

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from phase8_lift_maps import repair


class LiftMapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source, self.models, self.output = root/'source', root/'models', root/'out'
        self.source.mkdir()
        for level in ('L1', 'L2', 'L3'):
            image = Image.new('L', (700,900), 255)
            image.putpixel((348,631), 128)  # An unrelated map cell must survive.
            image.save(self.source/f'hotel_{level}.pgm')
            (self.source/f'hotel_{level}.yaml').write_text(yaml.safe_dump({
                'image':f'hotel_{level}.pgm', 'resolution':.05,
                'origin':[0.,-45.,0.], 'negate':0, 'occupied_thresh':.65,
                'free_thresh':.196, 'mode':'trinary'}))
            model = self.models/f'hotel_{level}'
            (model/'meshes').mkdir(parents=True)
            (model/'model.sdf').write_text('<sdf><model><link name="wall">'
                '<collision><geometry><mesh><uri>model://hotel/meshes/wall_1.obj</uri>'
                '</mesh></geometry></collision></link></model></sdf>')
            # Eight-vertex generated wall segment, to the right of the door.
            (model/'meshes/wall_1.obj').write_text('\n'.join(
                f'v {x} {y} {z}' for x,y in
                [(17.90,-22.68),(19.10,-22.68),(19.10,-22.78),(17.90,-22.78)]
                for z in (0,2.5)))

    def test_wall_and_shaft_restored_without_blocking_door(self):
        repair(self.source,self.models,self.output)
        for level in ('L1','L2','L3'):
            image=Image.open(self.output/f'hotel_{level}.pgm')
            def cost(x,y):return image.getpixel((int(x/.05),899-int((y+45)/.05)))
            self.assertEqual(cost(18.1,-22.7),0)
            self.assertEqual(cost(17.,-22.7),255)
            self.assertEqual(cost(17.,-24.2),255)
            self.assertEqual(cost(15.5,-24.2),0)

    def test_other_map_cells_and_metadata_preserved(self):
        repair(self.source,self.models,self.output)
        before=Image.open(self.source/'hotel_L1.pgm')
        after=Image.open(self.output/'hotel_L1.pgm')
        difference=ImageChops.difference(before,after)
        box=difference.getbbox()
        self.assertGreaterEqual(box[0],303)
        self.assertLessEqual(box[2],387)
        self.assertGreaterEqual(box[1],425)
        self.assertLessEqual(box[3],517)
        self.assertEqual(after.getpixel((348,631)),128)
        self.assertEqual(yaml.safe_load((self.source/'hotel_L1.yaml').read_text()),
                         yaml.safe_load((self.output/'hotel_L1.yaml').read_text()))

    def test_unrecognized_mesh_fails_instead_of_guessing(self):
        (self.models/'hotel_L1/meshes/wall_1.obj').write_text('v 0 0 0\n')
        with self.assertRaisesRegex(ValueError,'eight-vertex'):
            repair(self.source,self.models,self.output)


if __name__=='__main__':unittest.main()
