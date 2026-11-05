#!/usr/bin/env python3
"""Audit collision XY bounds in the installed hotel SDF, without modifying it."""
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET


def rotation(roll, pitch, yaw):
    cr, sr, cp, sp, cy, sy = math.cos(roll), math.sin(roll), math.cos(pitch), math.sin(pitch), math.cos(yaw), math.sin(yaw)
    return [[cy*cp, cy*sp*sr-sy*cr, cy*sp*cr+sy*sr],
            [sy*cp, sy*sp*sr+cy*cr, sy*sp*cr-cy*sr], [-sp, cp*sr, cp*cr]]


def pose(element):
    p = element.find("pose")
    if p is not None and p.get("relative_to"):
        raise ValueError("explicit relative_to needs frame-graph resolution")
    values = [float(v) for v in (p.text if p is not None else "0 0 0 0 0 0").split()]
    return values[:3], rotation(*values[3:])


def audit(world_path, urdf_path):
    raw = Path(world_path).read_bytes()
    model = ET.fromstring(raw).find(".//model[@name='robot_1']")
    if model is None:
        raise ValueError("robot_1 missing")
    origin, basis = pose(model.find("link[@name='base_footprint']"))
    if origin != [0, 0, 0] or basis != rotation(0, 0, 0):
        raise ValueError("audit requires base_footprint coincident with model frame")
    boxes = []
    for link in model.findall("link"):
        if not link.findall("collision"):
            continue
        translation, orient = pose(link)
        for collision in link.findall("collision"):
            offset, rot = pose(collision)
            center = [translation[i] + sum(orient[i][j]*offset[j] for j in range(3)) for i in range(3)]
            combined = [[sum(orient[i][k]*rot[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
            geometry = collision.find("geometry")
            if geometry.find("box") is not None:
                half = [float(v)/2 for v in geometry.findtext("box/size").split()]
                extent = [sum(abs(combined[i][j])*half[j] for j in range(3)) for i in range(3)]
            elif geometry.find("cylinder") is not None:
                radius, half_length = float(geometry.findtext("cylinder/radius")), float(geometry.findtext("cylinder/length"))/2
                extent = [radius*math.sqrt(max(0, 1-combined[i][2]**2)) + half_length*abs(combined[i][2]) for i in range(3)]
            else:
                raise ValueError("unsupported collision geometry; manual review required")
            boxes.append({"link": link.get("name"), "collision": collision.get("name"),
                          "min": [center[i]-extent[i] for i in range(3)],
                          "max": [center[i]+extent[i] for i in range(3)]})
    bounds = {"min": [min(b["min"][i] for b in boxes) for i in range(3)],
              "max": [max(b["max"][i] for b in boxes) for i in range(3)]}
    corner_radius = max(math.hypot(x, y) for x in (bounds["min"][0], bounds["max"][0])
                        for y in (bounds["min"][1], bounds["max"][1]))
    urdf_raw = Path(urdf_path).read_bytes()
    urdf = ET.fromstring(urdf_raw)
    base_joint = next(j for j in urdf.findall("joint") if j.find("child").get("link") == "base_link")
    return {"world_sha256": hashlib.sha256(raw).hexdigest(),
            "robot_sdf": ET.tostring(model, encoding="unicode"), "collisions": boxes,
            "xy_bounds": {k: v[:2] for k, v in bounds.items()},
            "bounding_rectangle_radius_m": corner_radius, "canonical_radius_m": 0.22,
            "canonical_radius_covers_rectangle": 0.22 >= corner_radius,
            "urdf_sha256": hashlib.sha256(urdf_raw).hexdigest(),
            "urdf_base_joint_xyz": base_joint.find("origin").get("xyz"),
            "sdf_base_link_pose": model.find("link[@name='base_link']").findtext("pose", "0 0 0 0 0 0"),
            "diff_drive_plugin": ET.tostring(next(p for p in model.findall("plugin") if "DiffDrive" in p.get("name", "")), encoding="unicode"),
            "qualification": "static SDF audit only; moving TF and physical stop tests still required"}


if __name__ == "__main__":
    print(json.dumps(audit("/opt/ros2-demo/hotel-assets/hotel.world", "/opt/ros2-demo/robot/turtlebot3_waffle.urdf"), sort_keys=True))
