#!/usr/bin/env python3
"""Add a fixed-geometry blue crate to a private Phase 7 capture world."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET


TARGET = {
    "model": "phase7_blue_crate",
    "center_xy": [17.4014, -31.5940],
    "size_xyz": [0.45, 0.35, 0.40],
    "bottom_z": 0.006,
    "top_z": 0.406,
    "prompt": "blue crate",
}


def add_blue_crate(world_path: Path) -> dict:
    tree = ET.parse(world_path)
    world = tree.getroot().find("world")
    if world is None:
        raise ValueError("SDF has no world element")
    if world.find(f"model[@name='{TARGET['model']}']") is not None:
        raise ValueError("blue crate already exists; refusing to patch twice")

    x, y = TARGET["center_xy"]
    sx, sy, sz = TARGET["size_xyz"]
    model = ET.SubElement(world, "model", {"name": TARGET["model"]})
    ET.SubElement(model, "static").text = "true"
    ET.SubElement(model, "pose").text = f"{x} {y} {TARGET['bottom_z'] + sz / 2} 0 0 0"
    link = ET.SubElement(model, "link", {"name": "body"})

    collision = ET.SubElement(link, "collision", {"name": "crate_collision"})
    collision_geometry = ET.SubElement(collision, "geometry")
    collision_box = ET.SubElement(collision_geometry, "box")
    ET.SubElement(collision_box, "size").text = f"{sx} {sy} {sz}"

    visual = ET.SubElement(link, "visual", {"name": "crate_visual"})
    visual_geometry = ET.SubElement(visual, "geometry")
    visual_box = ET.SubElement(visual_geometry, "box")
    ET.SubElement(visual_box, "size").text = f"{sx} {sy} {sz}"
    material = ET.SubElement(visual, "material")
    ET.SubElement(material, "ambient").text = "0.03 0.12 0.72 1"
    ET.SubElement(material, "diffuse").text = "0.04 0.22 0.92 1"
    ET.SubElement(material, "specular").text = "0.12 0.12 0.18 1"

    tree.write(world_path, encoding="utf-8", xml_declaration=True)
    return dict(TARGET)


def blue_crate_metadata_only(world_path: Path) -> dict:
    """Validate a clean world and return the fixed annotation geometry."""
    tree = ET.parse(world_path)
    world = tree.getroot().find("world")
    if world is None:
        raise ValueError("SDF has no world element")
    if world.find(f"model[@name='{TARGET['model']}']") is not None:
        raise ValueError("blue crate is present in metadata-only negative scene")
    return dict(TARGET)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("world", type=Path)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--metadata-only", action="store_true",
                        help="record annotation geometry without adding the crate")
    args = parser.parse_args()
    metadata = (blue_crate_metadata_only(args.world) if args.metadata_only
                else add_blue_crate(args.world))
    if args.metadata:
        args.metadata.parent.mkdir(parents=True, exist_ok=True)
        args.metadata.write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps(metadata, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
