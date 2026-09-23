#!/usr/bin/env python3
"""Prepare immutable hotel runtime artifacts during image construction.

The upstream building map remains the source of truth. This script only
removes upstream robot spawn annotations, copies the generated fleet graph, and
converts the upstream floor drawings to runtime occupancy maps. It never
creates cross-level lanes by hand.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageOps


SPAWN_KEYS = {"spawn_robot_name", "spawn_robot_type"}
SLOT_CAR_NAMES = {"tinyBot_1", "cleanerBotA_1", "cleanerBotA_2", "deliveryBot_1"}


def remove_spawn_annotations(value):
    if isinstance(value, dict):
        return {
            key: remove_spawn_annotations(item)
            for key, item in value.items()
            if key not in SPAWN_KEYS
        }
    if isinstance(value, list):
        return [remove_spawn_annotations(item) for item in value]
    return value


def prepare_building(source: Path, output: Path) -> None:
    building = yaml.safe_load(source.read_text())
    if not building.get("levels") or not building.get("lifts"):
        raise ValueError("upstream hotel building map has no levels or lifts")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump(remove_spawn_annotations(building), sort_keys=False))


def prepare_world(source: Path, output: Path, x: float, y: float, yaw: float) -> None:
    # Import the existing, tested normal-scale Waffle SDF rather than creating
    # a second robot definition that could drift from the simulator model.
    sys.path.insert(0, str(Path(__file__).parent))
    from patch_hotel_world_add_robot import TURTLEBOT3_MODEL

    tree = ET.parse(source)
    root = tree.getroot()
    world = root.find("world")
    if world is None:
        raise ValueError("hotel world has no world element")

    for model in list(world.findall("model")):
        if model.get("name") in SLOT_CAR_NAMES:
            world.remove(model)
    for include in list(world.findall("include")):
        name = include.findtext("name", default="")
        if name in SLOT_CAR_NAMES:
            world.remove(include)

    old_robot = world.find("model[@name='robot_1']")
    if old_robot is not None:
        world.remove(old_robot)
    for parent in root.iter():
        for plugin in list(parent):
            if (plugin.tag == "plugin" and
                    plugin.get("name", "").startswith(("toggle_charging", "toggle_floors"))):
                parent.remove(plugin)
    # RMF controls these doors through their registered joint components. The
    # upstream collision meshes remain closed in Gazebo even when LiftState
    # reports DOOR_OPEN, trapping the robot at the cabin threshold.
    for model in world.findall("model"):
        if model.get("name", "").startswith(("ShaftDoor_Lift", "CabinDoor_Lift")):
            for collision in list(model.findall(".//collision")):
                for parent in model.iter():
                    if collision in list(parent):
                        parent.remove(collision)
                        break
        if model.get("name", "") in {"Lift1", "Lift2"}:
            # The cabin's moving door leaves otherwise remain solid in Gazebo
            # after RMF reports the door open, blocking robot entry and exit.
            for collision in list(model.findall(".//collision")):
                if collision.get("name", "").endswith("_door_collision"):
                    for parent in model.iter():
                        if collision in list(parent):
                            parent.remove(collision)
                            break
    if not world.findall("plugin[@name='gz::sim::systems::Sensors']"):
        sensors = ET.Element(
            "plugin",
            {
                "filename": "libgz-sim-sensors-system.so",
                "name": "gz::sim::systems::Sensors",
            },
        )
        ET.SubElement(sensors, "render_engine").text = "ogre2"
        world.append(sensors)
    robot = ET.fromstring(TURTLEBOT3_MODEL)
    robot.find("pose").text = f"{x} {y} 0.1 0 0 {yaw}"
    world.insert(0, robot)
    gui = world.find("gui")
    if gui is not None:
        for plugin in gui.findall("plugin"):
            if plugin.get("filename") == "CameraTracking":
                ET.SubElement(plugin, "follow_target").text = "robot_1"
                ET.SubElement(plugin, "follow_offset").text = "-6 0 3"
                break
    output.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output, encoding="utf-8", xml_declaration=True)


def prepare_maps(map_dir: Path, nav_graph_path: Path, output_dir: Path,
                 resolution: float) -> None:
    graph = yaml.safe_load(nav_graph_path.read_text())
    output_dir.mkdir(parents=True, exist_ok=True)
    for level in ("L1", "L2", "L3"):
        candidates = sorted(map_dir.glob(f"**/hotel_{level}.png"))
        if not candidates:
            raise FileNotFoundError(f"upstream hotel_{level}.png was not found under {map_dir}")
        source = candidates[0]
        image = ImageOps.grayscale(Image.open(source))
        shutil.copy2(source, output_dir.parent / source.name)
        # Traffic Editor drawings use dark geometry on a light floor. Keep a
        # deterministic threshold; surveyed origin/resolution remains explicit
        # in the generated YAML and is validated before deployment.
        occupancy = image.point(lambda pixel: 0 if pixel < 100 else 255)
        graph_level = graph["levels"][level]
        vertices = graph_level["vertices"]
        draw = ImageDraw.Draw(occupancy)

        def pixel(vertex):
            return (
                round(vertex[0] / resolution),
                round(image.height - 1 + vertex[1] / resolution),
            )

        # Traffic Editor graph lanes are the navigation source of truth. Clear
        # a robot-width corridor because source drawings include closed door
        # leaves and wall pixels at otherwise valid graph waypoints.
        corridor_width = max(1, round(0.60 / resolution))
        for entry, exit_, _properties in graph_level["lanes"]:
            entry_properties = vertices[entry][2] or {}
            exit_properties = vertices[exit_][2] or {}
            lift_lane = bool(
                entry_properties.get("lift_cabin") or
                exit_properties.get("lift_cabin"))
            lane_width = max(
                corridor_width,
                round((2.0 if lift_lane else 0.60) / resolution))
            draw.line(
                [pixel(vertices[entry]), pixel(vertices[exit_])],
                fill=255,
                width=lane_width,
            )
        for vertex in vertices:
            x, y = pixel(vertex)
            radius = corridor_width // 2
            if (vertex[2] or {}).get("lift_cabin"):
                radius = max(radius, round(1.0 / resolution))
            draw.ellipse(
                (x - radius, y - radius, x + radius, y + radius),
                fill=255,
            )
        image_path = output_dir / f"hotel_{level}.pgm"
        occupancy.save(image_path)
        map_yaml = {
            "image": image_path.name,
            "resolution": resolution,
            # Traffic Editor reference images have their origin at the upper
            # left; Nav2 map coordinates use the lower-left corner.
            "origin": [0.0, -image.height * resolution, 0.0],
            "negate": 0,
            "occupied_thresh": 0.65,
            "free_thresh": 0.196,
            "mode": "trinary",
        }
        (output_dir / f"hotel_{level}.yaml").write_text(
            yaml.safe_dump(map_yaml, sort_keys=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--building", type=Path, required=True)
    parser.add_argument("--world", type=Path, required=True)
    parser.add_argument("--maps", type=Path, required=True)
    parser.add_argument("--nav-graph", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--robot-x", type=float, default=15.402)
    parser.add_argument("--robot-y", type=float, default=-31.594)
    parser.add_argument("--robot-yaw", type=float, default=0.0)
    parser.add_argument("--resolution", type=float, default=0.05)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    prepare_building(args.building, args.output / "hotel.building.yaml")
    prepare_world(args.world, args.output / "hotel.world",
                  args.robot_x, args.robot_y, args.robot_yaw)
    prepare_maps(args.maps, args.nav_graph, args.output / "maps", args.resolution)
    if not args.nav_graph.is_file():
        raise FileNotFoundError(f"generated RMF graph not found: {args.nav_graph}")
    graph = yaml.safe_load(args.nav_graph.read_text())
    # Give the L3 junction after the lift an explicit patrol place so a
    # round-trip task visibly exits the lift before requesting the return.
    hallway = graph["levels"]["L3"]["vertices"][2][2]
    hallway["name"] = "L3_middle_hallway"
    (args.output / "nav_graph.yaml").write_text(
        yaml.safe_dump(graph, sort_keys=False))
    (args.output / "manifest.json").write_text(json.dumps({
        "rmf_demos_commit": args.commit,
        "robot": "robot_1",
        "robot_scale": 1.0,
        "source_building": str(args.building),
        "source_graph": str(args.nav_graph),
        "maps": ["L1", "L2", "L3"],
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
