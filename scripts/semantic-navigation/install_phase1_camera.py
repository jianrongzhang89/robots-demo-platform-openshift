#!/usr/bin/env python3
"""Add the isolated semantic-navigation RGB-D sensor to a hotel world."""

from __future__ import annotations

import argparse
import math
import os
import xml.etree.ElementTree as ET
from pathlib import Path


def add_camera(world_path: Path, robot_name: str = "robot_1") -> None:
    tree = ET.parse(world_path)
    model = tree.getroot().find(f".//model[@name='{robot_name}']")
    if model is None:
        raise ValueError(f"robot model {robot_name!r} not found in {world_path}")
    if model.find("link[@name='camera_link']") is not None:
        raise ValueError("camera_link already exists; refusing to patch twice")

    link = ET.SubElement(model, "link", {"name": "camera_link"})
    ET.SubElement(link, "pose", {"relative_to": "base_link"}).text = "0.11 0 0.15 0 0 0"
    inertial = ET.SubElement(link, "inertial")
    ET.SubElement(inertial, "mass").text = "0.01"
    inertia = ET.SubElement(inertial, "inertia")
    for name, value in (("ixx", "0.00001"), ("iyy", "0.00001"), ("izz", "0.00001"),
                        ("ixy", "0"), ("ixz", "0"), ("iyz", "0")):
        ET.SubElement(inertia, name).text = value

    sensor = ET.SubElement(link, "sensor", {"name": "rgbd_camera", "type": "rgbd_camera"})
    ET.SubElement(sensor, "always_on").text = "true"
    ET.SubElement(sensor, "update_rate").text = "10"
    ET.SubElement(sensor, "topic").text = f"/{robot_name}/camera"
    ET.SubElement(sensor, "gz_frame_id").text = "camera_color_optical_frame"
    camera = ET.SubElement(sensor, "camera")
    ET.SubElement(camera, "horizontal_fov").text = "1.04719755"
    image = ET.SubElement(camera, "image")
    ET.SubElement(image, "width").text = "640"
    ET.SubElement(image, "height").text = "480"
    ET.SubElement(image, "format").text = "R8G8B8"
    clip = ET.SubElement(camera, "clip")
    ET.SubElement(clip, "near").text = "0.15"
    ET.SubElement(clip, "far").text = "5.0"
    ET.SubElement(sensor, "visualize").text = "false"

    joint = ET.SubElement(model, "joint", {"name": "camera_joint", "type": "fixed"})
    ET.SubElement(joint, "parent").text = "base_link"
    ET.SubElement(joint, "child").text = "camera_link"

    tree.write(world_path, encoding="utf-8", xml_declaration=True)


def add_bridge_to_entrypoint(entrypoint_path: Path, bridge_config: str) -> None:
    script = entrypoint_path.read_text()
    marker = 'echo "[hotel-sim] Canonical federated Gazebo simulation ready"'
    if "semantic_camera_bridge" in script:
        raise ValueError("semantic camera bridge is already installed in entrypoint")
    if marker not in script:
        raise ValueError(f"expected startup marker not found in {entrypoint_path}")
    command = (
        'echo "[semantic-camera] Starting RGB-D Gazebo-to-ROS bridge"\n'
        f'ros2 launch ros_gz_bridge ros_gz_bridge.launch.py '
        f'bridge_name:=semantic_camera_bridge config_file:={bridge_config} &\n'
        'pids+=("$!")\n\n'
    )
    entrypoint_path.write_text(script.replace(marker, command + marker))


def add_phase2_targets(world_path: Path, *, phase6_demo: bool = False) -> None:
    """Add a recognizable mat and a visual distractor to the isolated world.

    ``phase6_demo`` is an explicit D2-only geometry variant: 1.2 m along
    the route and 1.95 m across it (three times the previous 0.65 m width).
    The Phase 2/fixture geometry remains unchanged for default callers.
    """
    tree = ET.parse(world_path)
    world = tree.getroot().find("world")
    if world is None:
        raise ValueError(f"world element not found in {world_path}")
    if world.find("model[@name='semantic_target_mat']") is not None:
        raise ValueError("Phase 2 target already exists; refusing to patch twice")

    def slab(name: str, x: float, y: float, sx: float, sy: float,
             color: tuple[float, float, float]) -> ET.Element:
        model = ET.Element("model", {"name": name})
        ET.SubElement(model, "static").text = "true"
        ET.SubElement(model, "pose").text = f"{x} {y} 0.005 0 0 0"
        link = ET.SubElement(model, "link", {"name": "surface"})
        visual = ET.SubElement(link, "visual", {"name": "visual"})
        visual_geometry = ET.SubElement(visual, "geometry")
        ET.SubElement(visual_geometry, "box")
        ET.SubElement(visual_geometry.find("box"), "size").text = f"{sx} {sy} 0.012"
        material = ET.SubElement(visual, "material")
        ET.SubElement(material, "ambient").text = f"{color[0]} {color[1]} {color[2]} 1"
        ET.SubElement(material, "diffuse").text = f"{color[0]} {color[1]} {color[2]} 1"
        return model

    # The validated hotel runtime pose is (15.4014, -31.5940, yaw≈0).
    # Place the target 2 m ahead; do not use the separate TB3 template pose.
    # 2.7 m (2026-10-30 prepared value) left only 0.30 m of runway between
    # the start and the hull-clearance envelope's west edge — the >65 deg
    # escape turn is kinematically infeasible for RPP and the robot cut the
    # corner into the envelope in every motion trial (notouch-run3/4:
    # canceled at 0.091 m hull clearance). 1.2 m keeps the direct route
    # blocked while giving ~1.05 m of runway before the envelope's west edge.
    mat_length_x = 1.2 if phase6_demo else 0.9
    # Widen only the standalone demo mat; keep its center, X length,
    # thickness, and the distractor unchanged.
    mat_width_y = 1.95 if phase6_demo else 0.65
    world.append(slab("semantic_target_mat", 17.4014, -31.5940, mat_length_x, mat_width_y,
                      (0.85, 0.08, 0.06)))
    # Similar footprint, but a neutral tile-like distractor, offset laterally.
    world.append(slab("semantic_distractor_tile", 17.4014, -30.0940, 0.9, 0.65,
                      (0.55, 0.52, 0.45)))
    tree.write(world_path, encoding="utf-8", xml_declaration=True)


def add_lighting_profile(world_path: Path, profile: str) -> None:
    """Apply a repeatable world lighting profile before Gazebo starts."""
    if profile == "baseline":
        return
    if profile != "dim":
        raise ValueError(f"unsupported lighting profile {profile!r}")
    tree = ET.parse(world_path)
    world = tree.getroot().find("world")
    if world is None:
        raise ValueError(f"world element not found in {world_path}")
    scene = world.find("scene")
    light = world.find("light[@name='sun']")
    if scene is None or light is None:
        raise ValueError("world must contain a scene and the directional light named 'sun'")
    scene.find("ambient").text = "0.08 0.08 0.08"
    scene.find("background").text = "0.12 0.12 0.12"
    light.find("diffuse").text = "0.25 0.25 0.25 1"
    light.find("specular").text = "0.05 0.05 0.05 1"
    tree.write(world_path, encoding="utf-8", xml_declaration=True)


WARMUP_CAMERA_TEMPLATE = """<model name="phase5_warmup_camera_{index}">
  <static>true</static>
  <pose>{x} {y} 0.15 0 0 {yaw}</pose>
  <link name="link">
    <sensor name="rgbd_camera" type="rgbd_camera">
      <always_on>true</always_on>
      <update_rate>5</update_rate>
      <topic>/phase5/warmup/{index}</topic>
      <gz_frame_id>phase5_warmup_{index}_optical</gz_frame_id>
      <camera>
        <horizontal_fov>1.8</horizontal_fov>
        <image><width>640</width><height>480</height><format>R8G8B8</format></image>
        <clip><near>0.15</near><far>5.0</far></clip>
      </camera>
      <visualize>false</visualize>
    </sensor>
  </link>
</model>"""


def add_phase6_render_warmup(world_path: Path, goal_xy) -> None:
    """Stage the pre-arm render-warmup cameras around the Phase 6 goal.

    User-approved October 28, 2026: the on-arm's goal-approach orbit sweeps
    the robot camera through scene content not seen on the detour route,
    and its FIRST render there costs ~190 ms of render-thread CPU (the root
    of the remaining endgame failure), delaying the gpu_lidar scan ~450 ms
    and the controller's TF wait ~76 ms past the 100 ms command authority.
    Twelve static, collision-less rgbd cameras: four at the goal facing
    N/E/S/W, and eight on the orbit circle (radius 1.3 m — the observed
    RPP goal-approach orbit radius) facing OUTWARD, matching the robot
    camera's actual viewpoints during the orbit (series-15 trial 000-on:
    the goal-centered set alone missed content visible from the orbit
    circle through parallax/occlusion — a fresh ~190 ms spike at sim 56.3).
    Each covers 1.8 rad of azimuth; the union covers every direction the
    orbit can expose within the main camera's 5 m far clip. The gz Sensors
    system never renders sensors without subscribers, so they cost nothing
    during the armed trial; the fixture subscribes each one briefly during
    the DISARMED startup (a few frames, forcing the lazy scene content to
    load), then unsubscribes and they deactivate again. Identical in BOTH
    arms so the paired scene and load stay identical.
    """
    text = world_path.read_text()
    if "phase5_warmup_camera_" in text:
        raise ValueError("warmup cameras already staged; refusing to patch twice")
    poses = []
    # Four goal-centered cameras facing N/E/S/W.
    for index in range(4):
        poses.append((goal_xy[0], goal_xy[1], index * math.pi / 2))
    # Eight cameras on the orbit circle facing outward, 45 deg apart.
    radius = 1.3
    for step in range(8):
        angle = math.pi / 8 + step * math.pi / 4
        poses.append((goal_xy[0] + radius * math.cos(angle),
                      goal_xy[1] + radius * math.sin(angle),
                      angle))
    models = "".join(WARMUP_CAMERA_TEMPLATE.format(
        index=index, x=x, y=y, yaw=yaw)
        for index, (x, y, yaw) in enumerate(poses))
    world_path.write_text(text.replace("</world>", models + "</world>"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("world", type=Path)
    parser.add_argument("--robot", default="robot_1")
    parser.add_argument("--entrypoint", type=Path)
    parser.add_argument("--phase2-targets", action="store_true")
    parser.add_argument("--bridge-config", default="/opt/ros2-demo/config/semantic-camera-bridge.yaml")
    args = parser.parse_args()
    add_camera(args.world, args.robot)
    if args.phase2_targets:
        phase6_demo = os.environ.get("SEMANTIC_PHASE6_DEMO_TARGETS") == "1"
        if phase6_demo:
            # The un-supported simplified body pitches onto the floor; wheel
            # odometry can report a turn while the Gazebo body stays still.
            # Reuse the private fixture's supports ONLY in the opt-in D2 world.
            # No canonical SDF/URDF or qualified fixture is modified here.
            from support_geometry import add_rear_casters
            supported, _ = add_rear_casters(args.world.read_text(), "<robot/>")
            args.world.write_text(supported)
        add_phase2_targets(args.world, phase6_demo=phase6_demo)
    lighting_profile = os.environ.get("SEMANTIC_LIGHTING_PROFILE", "baseline")
    add_lighting_profile(args.world, lighting_profile)
    if args.entrypoint:
        add_bridge_to_entrypoint(args.entrypoint, args.bridge_config)
    print(f"Installed 640x480 RGB-D camera at 10 Hz on {args.robot}: {args.world}")


if __name__ == "__main__":
    main()
