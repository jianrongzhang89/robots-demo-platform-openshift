#!/usr/bin/env python3
"""
Split hotel multi-level map into separate level maps.

The hotel_multilevel.pgm contains three levels arranged horizontally:
- L1 (Lobby):  X=[0, 50]   meters
- L2 (Rooms):  X=[60, 110] meters
- L3 (Suites): X=[120, 170] meters

This script crops the single 2.5D map into three separate maps for multi-level
navigation with map switching.
"""

import os
import sys
import yaml
from PIL import Image


def split_hotel_map(
    input_image: str = 'maps/hotel_multilevel.pgm',
    input_yaml: str = 'maps/hotel_multilevel.yaml',
    output_dir: str = 'maps'
):
    """Split single hotel map into separate level maps."""

    # Load original image
    print(f"Loading map image: {input_image}")
    try:
        img = Image.open(input_image)
        print(f"  Image size: {img.size} (width x height)")
    except Exception as e:
        print(f"ERROR: Failed to load image: {e}")
        return False

    # Load original YAML
    print(f"Loading map config: {input_yaml}")
    try:
        with open(input_yaml) as f:
            base_yaml = yaml.safe_load(f)
        print(f"  Resolution: {base_yaml['resolution']} m/pixel")
        print(f"  Origin: {base_yaml['origin']}")
    except Exception as e:
        print(f"ERROR: Failed to load YAML: {e}")
        return False

    # Define crop regions based on world coordinates
    # Format: {level_name: (world_x_start, world_x_end, new_origin_x)}
    level_regions = {
        'L1': {
            'world_x_range': (0, 50),    # Lobby area
            'origin_x': 0.0,
            'pixel_crop': (200, 0, 1200, 1200),  # (left, top, right, bottom)
            'description': 'Lobby'
        },
        'L2': {
            'world_x_range': (60, 110),  # Rooms area
            'origin_x': 60.0,
            'pixel_crop': (1400, 0, 2400, 1200),
            'description': 'Rooms'
        },
        'L3': {
            'world_x_range': (120, 170), # Suites area
            'origin_x': 120.0,
            'pixel_crop': (2600, 0, 3600, 1200),
            'description': 'Suites'
        }
    }

    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    print(f"\nGenerating level maps...")

    for level, config in level_regions.items():
        print(f"\n{level} ({config['description']}):")
        print(f"  World X range: {config['world_x_range']} meters")
        print(f"  Pixel crop: {config['pixel_crop']}")

        # Crop image
        try:
            crop_box = config['pixel_crop']
            cropped = img.crop(crop_box)

            # Output files
            output_img = os.path.join(output_dir, f'hotel_{level}.pgm')
            output_yaml = os.path.join(output_dir, f'hotel_{level}.yaml')

            # Save cropped image
            cropped.save(output_img)
            print(f"  Saved image: {output_img}")
            print(f"    Size: {cropped.size} pixels")

            # Create level-specific YAML config
            level_yaml = base_yaml.copy()
            level_yaml['image'] = f'hotel_{level}.pgm'

            # Update origin for this cropped region
            # Y and Z stay the same, only X changes
            level_yaml['origin'] = [
                config['origin_x'],        # X origin for this level
                base_yaml['origin'][1],    # Y origin (unchanged)
                0.0                         # Z origin
            ]

            # Save YAML config
            with open(output_yaml, 'w') as f:
                yaml.dump(level_yaml, f, default_flow_style=False, sort_keys=False)

            print(f"  Saved config: {output_yaml}")
            print(f"    Origin: {level_yaml['origin']}")

        except Exception as e:
            print(f"  ERROR: Failed to process {level}: {e}")
            return False

    print(f"\nMap splitting complete!")
    print(f"\nGenerated files:")
    for level in level_regions.keys():
        print(f"  - maps/hotel_{level}.pgm")
        print(f"  - maps/hotel_{level}.yaml")

    print(f"\nThese maps can now be used with the multi-level Nav2 launch configuration.")
    print(f"Set ENABLE_MULTILEVEL=true in the robot pod environment.")

    return True


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Split hotel multilevel map into separate level maps'
    )
    parser.add_argument(
        '--input-image',
        default='maps/hotel_multilevel.pgm',
        help='Input map image file (default: maps/hotel_multilevel.pgm)'
    )
    parser.add_argument(
        '--input-yaml',
        default='maps/hotel_multilevel.yaml',
        help='Input map YAML config (default: maps/hotel_multilevel.yaml)'
    )
    parser.add_argument(
        '--output-dir',
        default='maps',
        help='Output directory for level maps (default: maps)'
    )

    args = parser.parse_args()

    success = split_hotel_map(
        args.input_image,
        args.input_yaml,
        args.output_dir
    )

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
