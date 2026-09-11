#!/usr/bin/env python3
"""
Fix DiffDrive plugin parameters to match the scaled robot.

CRITICAL BUG: Robot was scaled 3x but DiffDrive plugin still has original parameters:
  - wheel_radius: 0.033m (original) → should be 0.10m (actual wheel size)
  - wheel_separation: 0.287m → should be 0.288m (actual wheel spacing)

This mismatch causes the plugin to calculate wrong wheel velocities.
"""

import re
import sys
from pathlib import Path


def fix_diffdrive_params(world_path: Path) -> bool:
    """Fix DiffDrive plugin wheel parameters to match scaled robot."""
    try:
        with open(world_path, 'r') as f:
            content = f.read()

        print(f"[patch] Fixing DiffDrive parameters in {world_path}")

        original = content

        # Fix wheel_radius: 0.033 → 0.10 (matches actual cylinder radius)
        content = re.sub(
            r'(<model name="robot_1">.*?<wheel_radius>)0\.033(</wheel_radius>)',
            r'\g<1>0.10\2',
            content,
            flags=re.DOTALL
        )

        # Fix wheel_separation: 0.287 → 0.288 (matches actual wheel positions)
        # wheel_left at y=0.144, wheel_right at y=-0.144 → separation = 0.288
        content = re.sub(
            r'(<model name="robot_1">.*?<wheel_separation>)0\.287(</wheel_separation>)',
            r'\g<1>0.288\2',
            content,
            flags=re.DOTALL
        )

        if content == original:
            print("[patch] ERROR: Could not find DiffDrive parameters to fix")
            return False

        # Write back
        with open(world_path, 'w') as f:
            f.write(content)

        print(f"[patch] SUCCESS: Fixed DiffDrive plugin parameters")
        print(f"[patch]   • wheel_radius: 0.033m → 0.10m (3x scale)")
        print(f"[patch]   • wheel_separation: 0.287m → 0.288m (actual)")
        print(f"[patch]   • This should fix cmd_vel → wheel velocity conversion")
        print(f"[patch]   • Robot should FINALLY move!")
        return True

    except Exception as e:
        print(f"[patch] ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    if len(sys.argv) != 2:
        print("Usage: patch_robot1_diffdrive_params.py <hotel.world>")
        sys.exit(1)

    world_file = Path(sys.argv[1])
    if not world_file.exists():
        print(f"ERROR: {world_file} not found")
        sys.exit(1)

    if fix_diffdrive_params(world_file):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
