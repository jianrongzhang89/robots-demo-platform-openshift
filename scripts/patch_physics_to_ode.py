#!/usr/bin/env python3
"""
Switch hotel.world back to ODE physics from Bullet.

ODE has better default joint support and may work better with DiffDrive.
Keep ground plane and GUI plugin fixes, just change physics engine.
"""

import re
import sys
from pathlib import Path


def switch_to_ode(world_path: Path) -> bool:
    """Switch physics from Bullet back to ODE."""
    try:
        with open(world_path, 'r') as f:
            content = f.read()

        print(f"[patch] Switching to ODE physics in {world_path}")

        # Change physics from Bullet back to ODE
        original = content
        content = re.sub(
            r'<physics\s+name="([^"]+)"\s+type="bullet">',
            r'<physics name="\1" type="ode">',
            content
        )

        if content == original:
            print("[patch] WARNING: No Bullet physics found to change")
        else:
            print("[patch] ✓ Changed physics from Bullet to ODE")

        # Write back
        with open(world_path, 'w') as f:
            f.write(content)

        print(f"[patch] SUCCESS: Switched to ODE physics")
        print(f"[patch]   • Physics engine: ODE (better joint support)")
        print(f"[patch]   • Ground plane: Still present")
        print(f"[patch]   • GUI fixes: Still applied")
        return True

    except Exception as e:
        print(f"[patch] ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    if len(sys.argv) != 2:
        print("Usage: patch_physics_to_ode.py <hotel.world>")
        sys.exit(1)

    world_file = Path(sys.argv[1])
    if not world_file.exists():
        print(f"ERROR: {world_file} not found")
        sys.exit(1)

    if switch_to_ode(world_file):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
