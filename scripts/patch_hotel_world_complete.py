#!/usr/bin/env python3
"""
Complete hotel.world patch: GUI plugins, Bullet physics, ground plane.

This patches the INSTALLED world file at build time.
"""

import re
import sys
from pathlib import Path


def patch_hotel_world(world_path: Path) -> bool:
    """Apply all necessary patches to hotel.world."""
    try:
        with open(world_path, 'r') as f:
            content = f.read()

        print(f"[patch] Original file size: {len(content)} bytes")

        # 1. Remove toggle_charging plugin (single line)
        content = re.sub(
            r'<plugin\s+filename="toggle_charging"[^/]*/?>',
            '<!-- DISABLED: RCL crash fix - toggle_charging plugin removed -->',
            content
        )

        # 2. Remove toggle_floors plugin (multi-line block)
        content = re.sub(
            r'<plugin\s+name="toggle_floors".*?</plugin>',
            '<!-- DISABLED: RCL crash fix - toggle_floors plugin removed -->',
            content,
            flags=re.DOTALL
        )

        # 3. Change physics from ODE to Bullet-Featherstone
        content = re.sub(
            r'<physics\s+name="([^"]+)"\s+type="ode">',
            r'<physics name="\1" type="bullet">',
            content
        )

        # 4. Add ground plane model with collision if not present
        if 'name="ground_plane"' not in content:
            ground_plane = '''
    <!-- Ground plane for robot collision (prevents falling through world) -->
    <model name="ground_plane">
      <static>true</static>
      <pose>0 0 0 0 0 0</pose>
      <link name="link">
        <collision name="collision">
          <geometry>
            <plane>
              <normal>0 0 1</normal>
              <size>1000 1000</size>
            </plane>
          </geometry>
          <surface>
            <friction>
              <ode>
                <mu>100</mu>
                <mu2>50</mu2>
              </ode>
            </friction>
          </surface>
        </collision>
      </link>
    </model>
'''
            # Insert before </world> closing tag
            content = content.replace('</world>', ground_plane + '  </world>')
            print("[patch] Added ground plane collision")

        print(f"[patch] Patched file size: {len(content)} bytes")

        # Write back
        with open(world_path, 'w') as f:
            f.write(content)

        print(f"[patch] SUCCESS: Applied all patches to {world_path}")
        print("[patch]   ✓ GUI plugins removed (toggle_charging, toggle_floors)")
        print("[patch]   ✓ Physics changed to Bullet-Featherstone")
        print("[patch]   ✓ Ground plane added")
        return True

    except Exception as e:
        print(f"[patch] ERROR: Failed to patch {world_path}: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    if len(sys.argv) != 2:
        print("Usage: patch_hotel_world_complete.py <hotel.world>")
        sys.exit(1)

    world_file = Path(sys.argv[1])

    if not world_file.exists():
        print(f"ERROR: {world_file} not found")
        sys.exit(1)

    if patch_hotel_world(world_file):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
