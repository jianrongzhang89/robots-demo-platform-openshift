#!/usr/bin/env python3
"""Restore physical Lift2 geometry erased by the hotel graph-lane map raster.

Only the shaft/doorway area changes. Wall polygons come from the same generated
collision meshes as Gazebo; the cabin keepout follows its physical platform.
The semantic mat remains exclusively a served-model costmap observation.
"""
import argparse
import math
from pathlib import Path
import xml.etree.ElementTree as ET
import yaml
from PIL import Image, ImageDraw

REGION = (15.2, 19.3, -25.8, -21.3)
PLATFORM = (15.6324587, 18.3324587, -25.7208837, -22.7208837)


def repair(source, models, output):
    output.mkdir(parents=True, exist_ok=True)
    for level in ('L1', 'L2', 'L3'):
        meta = yaml.safe_load((source / f'hotel_{level}.yaml').read_text())
        original = Image.open(source / meta['image']).convert('L')
        patch = original.copy()
        draw = ImageDraw.Draw(patch)
        resolution = meta['resolution']
        ox, oy, _ = meta['origin']
        def pixel(x, y):
            return ((x-ox)/resolution, patch.height-1-(y-oy)/resolution)
        def rectangle(x0, x1, y0, y1, fill):
            a, b = pixel(x0, y1), pixel(x1, y0)
            draw.rectangle((*a, *b), fill=fill)
        rectangle(*REGION, 255)
        # Outside the cabin there is a shaft, not traversable floor.
        rectangle(REGION[0], PLATFORM[0], REGION[2], PLATFORM[3], 0)
        rectangle(PLATFORM[1], REGION[1], REGION[2], PLATFORM[3], 0)
        rectangle(REGION[0], REGION[1], REGION[2], PLATFORM[2], 0)
        model_dir = models / f'hotel_{level}'
        root = ET.parse(model_dir / 'model.sdf').getroot()
        walls = 0
        for link in root.findall('.//link'):
            uri = link.findtext('collision/geometry/mesh/uri', '')
            if not Path(uri).name.startswith('wall_'):
                continue
            pose = [float(v) for v in link.findtext('pose', '0 0 0 0 0 0').split()]
            if abs(pose[3]) + abs(pose[4]) > 1e-6:
                raise ValueError('expected planar hotel wall collision meshes')
            vertices = []
            for line in (model_dir/'meshes'/Path(uri).name).read_text().splitlines():
                if line.startswith('v '):
                    x,y,z = map(float, line.split()[1:])
                    vertices.append((pose[0]+math.cos(pose[5])*x-math.sin(pose[5])*y,
                                     pose[1]+math.sin(pose[5])*x+math.cos(pose[5])*y,z))
            if len(vertices) % 8:
                raise ValueError('expected generated eight-vertex wall segments')
            for i in range(0, len(vertices), 8):
                polygon = [vertices[i+j] for j in (0,2,4,6)]
                draw.polygon([pixel(x,y) for x,y,_ in polygon], fill=0)
                walls += 1
        if not walls:
            raise ValueError(f'no physical wall meshes found for {level}')
        # Keep the rest of the original map byte-for-byte unchanged.
        mask = Image.new('L', original.size, 0)
        md = ImageDraw.Draw(mask)
        a,b = pixel(REGION[0],REGION[3]),pixel(REGION[1],REGION[2])
        md.rectangle((*a,*b), fill=255)
        original.paste(patch, (0,0), mask)
        original.save(output / f'hotel_{level}.pgm')
        meta['image'] = f'hotel_{level}.pgm'
        (output / f'hotel_{level}.yaml').write_text(yaml.safe_dump(meta, sort_keys=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--models', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    repair(args.source, args.models, args.output)


if __name__ == '__main__':
    main()