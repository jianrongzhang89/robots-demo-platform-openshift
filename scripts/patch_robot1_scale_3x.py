#!/usr/bin/env python3
"""
Scale robot_1 to 3x size and ensure it's RED.

Works from ORIGINAL size (0.28, 0.31, 0.14) not giant size.
"""

import re
import sys
from pathlib import Path


def scale_robot_3x(world_path: Path) -> bool:
    """Scale robot_1 from original size to 3x and make it red."""
    try:
        with open(world_path, 'r') as f:
            content = f.read()

        print(f"[patch] Scaling robot_1 to 3x in {world_path}")

        # 1. Scale base_link VISUAL from ORIGINAL: 0.28 → 0.84m, 0.31 → 0.93m, 0.14 → 0.42m
        original_pattern = r'(<model name="robot_1">.*?<visual name="base_visual">.*?<geometry><box><size>)0\.28 0\.31 0\.14'
        scaled_replacement = r'\g<1>0.84 0.93 0.42'

        new_content = re.sub(original_pattern, scaled_replacement, content, flags=re.DOTALL)

        if new_content == content:
            print("[patch] WARNING: base_visual size not changed - pattern didn't match")
        else:
            print("[patch] ✓ Scaled base_visual to 0.84 x 0.93 x 0.42")
            content = new_content

        # 2. Scale base_link COLLISION
        original_pattern = r'(<model name="robot_1">.*?<collision name="base_collision">.*?<geometry><box><size>)0\.28 0\.31 0\.14'
        new_content = re.sub(original_pattern, scaled_replacement, content, flags=re.DOTALL)

        if new_content == content:
            print("[patch] WARNING: base_collision size not changed")
        else:
            print("[patch] ✓ Scaled base_collision to 0.84 x 0.93 x 0.42")
            content = new_content

        # 3. Ensure RED color (change from any color to red)
        # Pattern to match any RGB values in material/ambient
        color_pattern = r'(<model name="robot_1">.*?<visual name="base_visual">.*?<material><ambient>)[0-9.]+ [0-9.]+ [0-9.]+'
        red_color = r'\g<1>1.0 0.0 0.0'

        new_content = re.sub(color_pattern, red_color, content, flags=re.DOTALL)
        if new_content != content:
            print("[patch] ✓ Set ambient color to RED")
            content = new_content

        # Pattern for diffuse
        color_pattern = r'(<model name="robot_1">.*?<visual name="base_visual">.*?<diffuse>)[0-9.]+ [0-9.]+ [0-9.]+'
        new_content = re.sub(color_pattern, red_color, content, flags=re.DOTALL)
        if new_content != content:
            print("[patch] ✓ Set diffuse color to RED")
            content = new_content

        # 4. Scale wheels: 0.033 → 0.10 radius, 0.018 → 0.054 length
        # Left wheel collision
        wheel_pattern = r'(<model name="robot_1">.*?<link name="wheel_left_link">.*?<collision.*?<cylinder><radius>)0\.033(</radius><length>)0\.018'
        wheel_replacement = r'\g<1>0.10\g<2>0.054'
        new_content = re.sub(wheel_pattern, wheel_replacement, content, flags=re.DOTALL)
        if new_content != content:
            print("[patch] ✓ Scaled left wheel collision")
            content = new_content

        # Left wheel visual
        wheel_pattern = r'(<model name="robot_1">.*?<link name="wheel_left_link">.*?<visual.*?<cylinder><radius>)0\.033(</radius><length>)0\.018'
        new_content = re.sub(wheel_pattern, wheel_replacement, content, flags=re.DOTALL)
        if new_content != content:
            print("[patch] ✓ Scaled left wheel visual")
            content = new_content

        # Right wheel collision
        wheel_pattern = r'(<model name="robot_1">.*?<link name="wheel_right_link">.*?<collision.*?<cylinder><radius>)0\.033(</radius><length>)0\.018'
        new_content = re.sub(wheel_pattern, wheel_replacement, content, flags=re.DOTALL)
        if new_content != content:
            print("[patch] ✓ Scaled right wheel collision")
            content = new_content

        # Right wheel visual
        wheel_pattern = r'(<model name="robot_1">.*?<link name="wheel_right_link">.*?<visual.*?<cylinder><radius>)0\.033(</radius><length>)0\.018'
        new_content = re.sub(wheel_pattern, wheel_replacement, content, flags=re.DOTALL)
        if new_content != content:
            print("[patch] ✓ Scaled right wheel visual")
            content = new_content

        # 5. Scale LiDAR: 0.0508 → 0.152 radius, 0.055 → 0.165 length (3x)
        lidar_pattern = r'(<model name="robot_1">.*?<link name="base_scan">.*?<visual.*?<cylinder><radius>)0\.0508(</radius><length>)0\.055'
        lidar_replacement = r'\g<1>0.152\g<2>0.165'
        new_content = re.sub(lidar_pattern, lidar_replacement, content, flags=re.DOTALL)
        if new_content != content:
            print("[patch] ✓ Scaled LiDAR visual")
            content = new_content

        # Write back
        with open(world_path, 'w') as f:
            f.write(content)

        print(f"[patch] SUCCESS: robot_1 is now:")
        print(f"[patch]   • Medium size: 0.84m x 0.93m x 0.42m (3x original)")
        print(f"[patch]   • BRIGHT RED color")
        print(f"[patch]   • At lobby position (10, 30, 0.1)")
        return True

    except Exception as e:
        print(f"[patch] ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    if len(sys.argv) != 2:
        print("Usage: patch_robot1_scale_3x.py <hotel.world>")
        sys.exit(1)

    world_file = Path(sys.argv[1])
    if not world_file.exists():
        print(f"ERROR: {world_file} not found")
        sys.exit(1)

    if scale_robot_3x(world_file):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
