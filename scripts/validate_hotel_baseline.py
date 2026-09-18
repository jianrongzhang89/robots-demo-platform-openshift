#!/usr/bin/env python3
"""Static validation for the simplified hotel runtime assets."""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml
from PIL import Image


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("asset_dir", type=Path)
    args = parser.parse_args()
    root = args.asset_dir
    required = [root / "hotel.building.yaml", root / "hotel.world",
                root / "nav_graph.yaml", root / "manifest.json"]
    required += [root / "maps" / f"hotel_{level}.yaml" for level in ("L1", "L2", "L3")]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("missing assets:")
        print("\n".join(missing))
        return 1
    world = ET.parse(root / "hotel.world")
    unresolved = []
    for include in world.findall(".//include"):
        uri = include.findtext("uri", default="")
        if not uri.startswith("model://"):
            continue
        model_path = root / "models" / uri.removeprefix("model://")
        if not ((model_path / "model.config").is_file() or
                (model_path / "model.sdf").is_file()):
            unresolved.append(uri)
    if unresolved:
        print("hotel world references missing models:")
        print("\n".join(sorted(set(unresolved))))
        return 1
    building = yaml.safe_load((root / "hotel.building.yaml").read_text())
    if set(building.get("levels", {})) != {"L1", "L2", "L3"}:
        print("hotel building map must contain L1, L2, and L3")
        return 1
    if not building.get("lifts"):
        print("hotel building map has no lifts")
        return 1
    graph = yaml.safe_load((root / "nav_graph.yaml").read_text())
    if not graph.get("levels"):
        print("RMF graph has no levels")
        return 1
    for level in ("L1", "L2", "L3"):
        map_config = yaml.safe_load((root / "maps" / f"hotel_{level}.yaml").read_text())
        image = (root / "maps" / map_config["image"])
        if not image.is_file():
            print(f"{level} map image is missing: {image}")
            return 1
        width, height = Image.open(image).size
        resolution = map_config["resolution"]
        origin_x, origin_y = map_config["origin"][:2]
        for vertex in graph["levels"][level]["vertices"]:
            x, y = vertex[:2]
            if not (origin_x <= x <= origin_x + width * resolution and
                    origin_y <= y <= origin_y + height * resolution):
                print(f"{level} graph vertex is outside its occupancy map: {x}, {y}")
                return 1
    print("hotel baseline assets are structurally valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
