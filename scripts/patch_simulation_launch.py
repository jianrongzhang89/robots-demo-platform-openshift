#!/usr/bin/env python3
"""
Patch simulation.launch.xml to add --headless-rendering flag for gpu_lidar support.
"""
import sys
import re

def patch_launch(input_path, output_path):
    with open(input_path, 'r') as f:
        content = f.read()

    # Find the gz sim command line and add --headless-rendering flag
    # Original: gz sim --force-version $(var gazebo_version) $(var gz_headless) -r -v 3 $(var world_path)
    # Updated:  gz sim --force-version $(var gazebo_version) $(var gz_headless) --headless-rendering -r -v 3 $(var world_path)

    pattern = r'(gz sim --force-version \$\(var gazebo_version\) \$\(var gz_headless\))( -r -v 3)'
    replacement = r'\1 --headless-rendering\2'

    patched = re.sub(pattern, replacement, content)

    if patched == content:
        print("ERROR: Could not find gz sim command to patch", file=sys.stderr)
        return False

    with open(output_path, 'w') as f:
        f.write(patched)

    print(f"Patched {input_path} -> {output_path}")
    print(f"Added --headless-rendering flag for server-side sensor rendering")
    return True

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: patch_simulation_launch.py <input_launch> <output_launch>")
        sys.exit(1)

    if not patch_launch(sys.argv[1], sys.argv[2]):
        sys.exit(1)
