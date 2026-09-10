#!/usr/bin/env python3
"""
Patch hotel.world to use Bullet-Featherstone physics engine.

Bullet has better joint support than TPE and may work where DART 6.13.2 fails.
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def patch_hotel_world_bullet(world_path: Path) -> bool:
    """Patch hotel.world SDF to use Bullet-Featherstone physics engine."""
    try:
        tree = ET.parse(world_path)
        root = tree.getroot()

        world = root.find('.//world')
        if world is None:
            print(f"ERROR: No <world> element found in {world_path}")
            return False

        # Find Physics plugin
        physics_plugin = None
        for plugin in world.findall('plugin'):
            filename = plugin.get('filename', '')
            if 'physics-system' in filename:
                physics_plugin = plugin
                break

        if physics_plugin is None:
            print(f"ERROR: No Physics plugin found in {world_path}")
            return False

        # Check if already Bullet
        existing_engine = physics_plugin.find('engine')
        if existing_engine is not None:
            existing_filename = existing_engine.find('filename')
            if existing_filename is not None and 'bullet' in existing_filename.text.lower():
                print(f"INFO: {world_path} already configured for Bullet physics")
                return True

        # Set Bullet-Featherstone engine
        if existing_engine is None:
            engine_elem = ET.SubElement(physics_plugin, 'engine')
        else:
            engine_elem = existing_engine

        filename_elem = engine_elem.find('filename')
        if filename_elem is None:
            filename_elem = ET.SubElement(engine_elem, 'filename')
        filename_elem.text = 'gz-physics-bullet-featherstone-plugin'

        # Write back
        tree.write(world_path, encoding='utf-8', xml_declaration=True)

        print(f"SUCCESS: Patched {world_path} to use Bullet-Featherstone physics")
        return True

    except Exception as e:
        print(f"ERROR: Failed to patch {world_path}: {e}")
        return False


def main():
    world_file = Path('/opt/rmf_demos_ws/install/share/rmf_demos_maps/maps/hotel/hotel.world')

    if not world_file.exists():
        print(f"ERROR: {world_file} not found")
        sys.exit(1)

    if patch_hotel_world_bullet(world_file):
        print("\n✓ Hotel world successfully patched for Bullet-Featherstone physics")
        print("  Bullet has better dynamics than TPE")
        print("  Testing workaround for DART 6.13.2 continuous joint DOF=0 bug")
        sys.exit(0)
    else:
        print("\n✗ Failed to patch hotel world")
        sys.exit(1)


if __name__ == '__main__':
    main()
