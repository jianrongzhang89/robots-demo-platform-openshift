#!/usr/bin/env python3
"""
Remove <static>True</static> tag from robot_1 model.

CRITICAL BUG: robot_1 has <static>True</static> which prevents it from moving!
Static models cannot be moved by physics - they're frozen in place.
"""

import re
import sys
from pathlib import Path


def remove_static_tag(world_path: Path) -> bool:
    """Remove static tag from robot_1 model."""
    try:
        with open(world_path, 'r') as f:
            content = f.read()

        print(f"[patch] Removing static tag from robot_1 in {world_path}")

        # Find robot_1 model section
        pattern = r'(<model name="robot_1">.*?)<static>True</static>(.*?</model>)'

        if not re.search(pattern, content, flags=re.DOTALL):
            print("[patch] WARNING: No <static>True</static> found in robot_1 model")
            # Try case-insensitive
            pattern = r'(<model name="robot_1">.*?)<static>true</static>(.*?</model>)'
            if not re.search(pattern, content, flags=re.DOTALL | re.IGNORECASE):
                print("[patch] ERROR: Could not find static tag to remove")
                return False

        # Remove the static tag
        content = re.sub(
            r'(<model name="robot_1">.*?)\s*<static>(?:True|true)</static>\s*(.*?</model>)',
            r'\1\2',
            content,
            flags=re.DOTALL | re.IGNORECASE
        )

        # Write back
        with open(world_path, 'w') as f:
            f.write(content)

        print(f"[patch] SUCCESS: Removed <static> tag from robot_1")
        print(f"[patch]   • Robot is now DYNAMIC (can move!)")
        print(f"[patch]   • DiffDrive plugin should now be able to actuate wheels")
        print(f"[patch]   • THIS WAS THE BUG PREVENTING MOVEMENT!")
        return True

    except Exception as e:
        print(f"[patch] ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    if len(sys.argv) != 2:
        print("Usage: patch_robot1_remove_static.py <hotel.world>")
        sys.exit(1)

    world_file = Path(sys.argv[1])
    if not world_file.exists():
        print(f"ERROR: {world_file} not found")
        sys.exit(1)

    if remove_static_tag(world_file):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
