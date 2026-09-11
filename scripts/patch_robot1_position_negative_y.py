#!/usr/bin/env python3
"""
Move robot_1 to NEGATIVE Y coordinates like the cleaner robots.

CRITICAL FIX: Cleaner robots are at Y=-32 (negative!)
robot_1 was at positive Y values, putting it in wrong area.
Move to (20, -30, 0.1) to be near cleaners.
"""

import re
import sys
from pathlib import Path


def move_robot_negative_y(world_path: Path) -> bool:
    """Move robot_1 to (20, -30, 0.1) - near cleaner robots."""
    try:
        with open(world_path, 'r') as f:
            content = f.read()

        print(f"[patch] CRITICAL FIX: Moving robot_1 to NEGATIVE Y in {world_path}")

        # Change position from any current position to (20, -30, 0.1)
        pattern = r'(<model name="robot_1">[\s\S]*?<pose>)[0-9.-]+ [0-9.-]+ [0-9.-]+'
        replacement = r'\g<1>20 -30 0.1'

        new_content = re.sub(pattern, replacement, content, count=1)

        if new_content == content:
            print("[patch] ERROR: Could not find robot_1 pose to change")
            return False

        print("[patch] ✓ Moved robot_1 to (20, -30, 0.1)")
        content = new_content

        # Write back
        with open(world_path, 'w') as f:
            f.write(content)

        print(f"[patch] SUCCESS: robot_1 is now:")
        print(f"[patch]   • Position: (20, -30, 0.1) - NEGATIVE Y!")
        print(f"[patch]   • Near cleaner robots at (19-23, -32)")
        print(f"[patch]   • Should FINALLY be in the visible area!")
        return True

    except Exception as e:
        print(f"[patch] ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    if len(sys.argv) != 2:
        print("Usage: patch_robot1_position_negative_y.py <hotel.world>")
        sys.exit(1)

    world_file = Path(sys.argv[1])
    if not world_file.exists():
        print(f"ERROR: {world_file} not found")
        sys.exit(1)

    if move_robot_negative_y(world_file):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
