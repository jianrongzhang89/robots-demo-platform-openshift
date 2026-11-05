#!/usr/bin/env python3
"""Project a known box-shaped simulator target into an image as independent GT."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def pose_matrix(translation: list[float], quaternion_xyzw: list[float]) -> np.ndarray:
    x, y, z, w = quaternion_xyzw
    matrix = np.array([
        [1 - 2 * (y*y + z*z), 2 * (x*y - z*w), 2 * (x*z + y*w), translation[0]],
        [2 * (x*y + z*w), 1 - 2 * (x*x + z*z), 2 * (y*z - x*w), translation[1]],
        [2 * (x*z - y*w), 2 * (y*z + x*w), 1 - 2 * (x*x + y*y), translation[2]],
        [0, 0, 0, 1],
    ], dtype=np.float64)
    return matrix


def camera_geometry(row: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    world_base = row.get("world_from_base_link")
    anchor = row.get("world_to_odom_anchor")
    direct_base_pose = bool(world_base and len(world_base) == 7)
    if not direct_base_pose and (not anchor or len(anchor) != 7):
        raise ValueError("manifest row needs world_from_base_link or a world-to-odom anchor")
    info = row["camera_info"]
    intrinsics = info["k"]
    transforms = row["static_transforms"]
    camera_from_base = np.eye(4, dtype=np.float64)
    chain = (("base_link", "camera_link"), ("camera_link", info["frame_id"]))
    if not direct_base_pose:
        chain = (("base_footprint", "base_link"),) + chain
    for parent, child in chain:
        item = next((t for t in transforms
                     if t["parent_frame"] == parent and t["child_frame"] == child), None)
        if item is None:
            raise ValueError(f"missing static transform {parent} -> {child}")
        tr = item["translation"]
        q = item["rotation_xyzw"]
        camera_from_base = camera_from_base @ pose_matrix(
            [tr["x"], tr["y"], tr["z"]], [q[k] for k in ("x", "y", "z", "w")]
        )

    if direct_base_pose:
        world_from_camera = pose_matrix(world_base[:3], world_base[3:]) @ camera_from_base
    else:
        odom = row["odometry"]
        odom_position = odom["position"]
        odom_orientation = odom["orientation_xyzw"]
        world_from_odom = pose_matrix(anchor[:3], anchor[3:])
        odom_from_base = pose_matrix(
            [odom_position[k] for k in ("x", "y", "z")],
            [odom_orientation[k] for k in ("x", "y", "z", "w")],
        )
        world_from_camera = world_from_odom @ odom_from_base @ camera_from_base
    camera_from_world = np.linalg.inv(world_from_camera)
    return camera_from_world, world_from_camera, np.asarray(intrinsics).reshape(3, 3)


def target_corners(center: tuple[float, float], size: tuple[float, float],
                   bottom_z: float, top_z: float) -> np.ndarray:
    cx, cy = center
    sx, sy = size
    return np.array([
        [x, y, z, 1]
        for z in (bottom_z, top_z)
        for x, y in ((cx - sx/2, cy - sy/2), (cx + sx/2, cy - sy/2),
                     (cx + sx/2, cy + sy/2), (cx - sx/2, cy + sy/2))
    ], dtype=np.float64).T


def project_target(row: dict, center: tuple[float, float], size: tuple[float, float],
                   bottom_z: float, top_z: float) -> np.ndarray:
    camera_from_world, _, intrinsics = camera_geometry(row)
    corners_world = target_corners(center, size, bottom_z, top_z)
    corners_camera = (camera_from_world @ corners_world)[:3]
    if np.any(corners_camera[2] <= 0):
        raise ValueError("target plane is not wholly in front of the camera")
    u = intrinsics[0, 0] * corners_camera[0] / corners_camera[2] + intrinsics[0, 2]
    v = intrinsics[1, 1] * corners_camera[1] / corners_camera[2] + intrinsics[1, 2]
    projected = np.rint(np.column_stack((u, v))).astype(np.int32)
    return cv2.convexHull(projected).reshape(-1, 2)


def depth_visible_mask(row: dict, polygon: np.ndarray, center: tuple[float, float],
                       size: tuple[float, float], bottom_z: float, top_z: float,
                       depth_mm: np.ndarray, tolerance_m: float) -> np.ndarray:
    """Keep projected target pixels whose observed depth agrees with box-ray depth."""
    _, world_from_camera, intrinsics = camera_geometry(row)
    fx, fy, cx, cy = intrinsics[0, 0], intrinsics[1, 1], intrinsics[0, 2], intrinsics[1, 2]
    height, width = depth_mm.shape
    candidate = np.zeros((height, width), dtype=np.uint8)
    cv2.fillConvexPoly(candidate, polygon, 255)
    ys, xs = np.where(candidate > 0)
    if not len(xs):
        return candidate
    camera_origin = world_from_camera[:3, 3]
    camera_rotation = world_from_camera[:3, :3]
    cxw, cyw = center
    sx, sy = size
    box_min = np.array([cxw - sx/2, cyw - sy/2, bottom_z])
    box_max = np.array([cxw + sx/2, cyw + sy/2, top_z])
    visible = np.zeros_like(candidate)
    for u, v in zip(xs, ys):
        observed_m = float(depth_mm[v, u]) / 1000.0
        if observed_m <= 0:
            continue
        ray_world = camera_rotation @ np.array([(u - cx) / fx, (v - cy) / fy, 1.0])
        near, far = -np.inf, np.inf
        intersects = True
        for axis in range(3):
            if abs(ray_world[axis]) < 1e-10:
                if camera_origin[axis] < box_min[axis] or camera_origin[axis] > box_max[axis]:
                    intersects = False
                    break
                continue
            a = (box_min[axis] - camera_origin[axis]) / ray_world[axis]
            b = (box_max[axis] - camera_origin[axis]) / ray_world[axis]
            near = max(near, min(a, b))
            far = min(far, max(a, b))
        if not intersects or far < max(near, 0.0):
            continue
        expected_m = near if near > 0 else far
        if expected_m > 0 and abs(observed_m - expected_m) <= tolerance_m:
            visible[v, u] = 255
    return visible


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--row", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overlay", type=Path)
    parser.add_argument("--depth", type=Path,
                        help="captured uint16 depth PNG in millimeters; ray-test visibility")
    parser.add_argument("--depth-tolerance-m", type=float, default=0.03)
    parser.add_argument("--center", type=float, nargs=2, default=(17.4014, -31.5940),
                        metavar=("X", "Y"))
    parser.add_argument("--size", type=float, nargs=2, default=(0.9, 0.65),
                        metavar=("WIDTH", "LENGTH"))
    parser.add_argument("--bottom-z", type=float, default=-0.001)
    parser.add_argument("--top-z", type=float, default=0.011)
    args = parser.parse_args()

    rows = json.loads(args.manifest.read_text())
    if not 0 <= args.row < len(rows):
        parser.error(f"row index {args.row} outside manifest with {len(rows)} rows")
    row = rows[args.row]
    image_path = Path(row["rgb"])
    if not image_path.is_absolute():
        image_path = args.manifest.parent / image_path
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        parser.error(f"cannot read image {image_path}")
    if image.shape[:2] != (row["height"], row["width"]):
        parser.error("manifest dimensions do not match the captured image")

    if args.bottom_z >= args.top_z:
        parser.error("--bottom-z must be less than --top-z")
    polygon = project_target(row, tuple(args.center), tuple(args.size),
                             args.bottom_z, args.top_z)
    mask = np.zeros(image.shape[:2], dtype=np.uint8)
    cv2.fillConvexPoly(mask, polygon, 255)
    if args.depth:
        depth_path = args.depth
        if not depth_path.is_absolute():
            depth_path = args.manifest.parent / depth_path
        depth_mm = cv2.imread(str(depth_path), cv2.IMREAD_UNCHANGED)
        if depth_mm is None or depth_mm.shape != image.shape[:2]:
            parser.error(f"depth image missing or dimensions differ: {depth_path}")
        if depth_mm.dtype != np.uint16:
            parser.error("depth visibility mode expects uint16 millimeter PNG")
        if args.depth_tolerance_m <= 0:
            parser.error("--depth-tolerance-m must be positive")
        mask = depth_visible_mask(row, polygon, tuple(args.center), tuple(args.size),
                                  args.bottom_z, args.top_z, depth_mm,
                                  args.depth_tolerance_m)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(args.output), mask):
        parser.error(f"cannot write mask {args.output}")
    if args.overlay:
        overlay = image.copy()
        overlay[mask > 0] = (0, 255, 0)
        overlay = cv2.addWeighted(overlay, 0.4, image, 0.6, 0)
        args.overlay.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(args.overlay), overlay):
            parser.error(f"cannot write overlay {args.overlay}")
    print(json.dumps({"mask_pixels": int(np.count_nonzero(mask)),
                      "polygon_uv": polygon.tolist(), "image": str(image_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
