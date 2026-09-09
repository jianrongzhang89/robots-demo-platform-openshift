#!/usr/bin/env python3
"""
Patch hotel.world to add Sensors system plugin for gpu_lidar support.
"""
import sys
import re

def patch_world(input_path, output_path):
    with open(input_path, 'r') as f:
        content = f.read()

    # Find the SceneBroadcaster plugin closing tag and add Sensors system after it
    sensors_plugin = '''    <plugin filename="libgz-sim-sensors-system.so" name="gz::sim::systems::Sensors">
      <render_engine>ogre2</render_engine>
    </plugin>'''

    # Insert after SceneBroadcaster plugin
    pattern = r'(    <plugin filename="libgz-sim-scene-broadcaster-system\.so"[^>]*>\s*</plugin>)'
    replacement = r'\1\n' + sensors_plugin

    patched = re.sub(pattern, replacement, content)

    if patched == content:
        print("ERROR: Could not find SceneBroadcaster plugin to patch after", file=sys.stderr)
        return False

    with open(output_path, 'w') as f:
        f.write(patched)

    print(f"Patched {input_path} -> {output_path}")
    print(f"Added Sensors system plugin for gpu_lidar support")
    return True

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: patch_hotel_world.py <input_world> <output_world>")
        sys.exit(1)

    if not patch_world(sys.argv[1], sys.argv[2]):
        sys.exit(1)
