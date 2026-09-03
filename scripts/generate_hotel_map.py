#!/usr/bin/env python3
"""
Generate a Nav2 PGM map for the hotel multilevel world.
Creates a 2.5D map where three floors are arranged horizontally.
"""

import numpy as np
from PIL import Image
import sys
import os

def generate_hotel_map(output_path):
    # Map parameters (in meters)
    resolution = 0.05  # meters per pixel

    # World dimensions
    total_width = 180  # meters (3 floors + gaps)
    total_height = 60  # meters

    # Convert to pixels
    width_px = int(total_width / resolution)
    height_px = int(total_height / resolution)

    # Create map array (255 = free, 0 = occupied, 205 = unknown)
    map_data = np.full((height_px, width_px), 205, dtype=np.uint8)

    # Helper to convert meters to pixels
    def m_to_px(meters):
        return int(meters / resolution)

    # Floor dimensions
    floor_width = 50  # meters
    floor_height = 50  # meters
    margin = 5  # meters padding from edges

    # L1 Lobby: X=[0, 50], Y center
    l1_x_start = m_to_px(5)
    l1_x_end = m_to_px(45)
    l1_y_start = m_to_px(10)
    l1_y_end = m_to_px(50)

    # Fill L1 area as free space (255)
    map_data[l1_y_start:l1_y_end, l1_x_start:l1_x_end] = 255

    # L1 walls (occupied = 0)
    wall_thickness = m_to_px(0.2)
    # North wall
    map_data[l1_y_end-wall_thickness:l1_y_end, l1_x_start:l1_x_end] = 0
    # South wall
    map_data[l1_y_start:l1_y_start+wall_thickness, l1_x_start:l1_x_end] = 0
    # West wall
    map_data[l1_y_start:l1_y_end, l1_x_start:l1_x_start+wall_thickness] = 0
    # East wall (with gap for lift)
    gap_start = m_to_px(25)
    gap_size = m_to_px(5)
    map_data[l1_y_start:gap_start, l1_x_end-wall_thickness:l1_x_end] = 0
    map_data[gap_start+gap_size:l1_y_end, l1_x_end-wall_thickness:l1_x_end] = 0

    # Lift zone L1 side (partially occupied for visualization)
    lift_l1_x = m_to_px(50)
    lift_size = m_to_px(5)
    map_data[gap_start:gap_start+gap_size, lift_l1_x:lift_l1_x+lift_size] = 200  # Slightly darker free space

    # L2 Rooms: X=[60, 110]
    l2_x_start = m_to_px(65)
    l2_x_end = m_to_px(105)
    l2_y_start = m_to_px(10)
    l2_y_end = m_to_px(50)

    # Fill L2 area as free space
    map_data[l2_y_start:l2_y_end, l2_x_start:l2_x_end] = 255

    # L2 walls
    map_data[l2_y_end-wall_thickness:l2_y_end, l2_x_start:l2_x_end] = 0
    map_data[l2_y_start:l2_y_start+wall_thickness, l2_x_start:l2_x_end] = 0
    # West wall (with gap)
    map_data[l2_y_start:gap_start, l2_x_start:l2_x_start+wall_thickness] = 0
    map_data[gap_start+gap_size:l2_y_end, l2_x_start:l2_x_start+wall_thickness] = 0
    # East wall
    map_data[l2_y_start:l2_y_end, l2_x_end-wall_thickness:l2_x_end] = 0

    # Lift zone L2 side
    lift_l2_x = m_to_px(55)
    map_data[gap_start:gap_start+gap_size, lift_l2_x:lift_l2_x+lift_size] = 200

    # L3 Suites: X=[120, 170]
    l3_x_start = m_to_px(125)
    l3_x_end = m_to_px(165)
    l3_y_start = m_to_px(10)
    l3_y_end = m_to_px(50)

    # Fill L3 area as free space
    map_data[l3_y_start:l3_y_end, l3_x_start:l3_x_end] = 255

    # L3 walls
    map_data[l3_y_end-wall_thickness:l3_y_end, l3_x_start:l3_x_end] = 0
    map_data[l3_y_start:l3_y_start+wall_thickness, l3_x_start:l3_x_end] = 0
    # West wall (with gap)
    map_data[l3_y_start:gap_start, l3_x_start:l3_x_start+wall_thickness] = 0
    map_data[gap_start+gap_size:l3_y_end, l3_x_start:l3_x_start+wall_thickness] = 0
    # East wall
    map_data[l3_y_start:l3_y_end, l3_x_end-wall_thickness:l3_x_end] = 0

    # Lift zone L3 side
    lift_l3_x = m_to_px(115)
    map_data[gap_start:gap_start+gap_size, lift_l3_x:lift_l3_x+lift_size] = 200

    # Save as PGM (PIL can save as grayscale)
    # Flip vertically because PGM origin is top-left, but ROS/Nav2 expects bottom-left
    map_image = Image.fromarray(np.flipud(map_data), mode='L')
    map_image.save(output_path)

    print(f"Generated hotel multilevel map: {output_path}")
    print(f"  Dimensions: {width_px} x {height_px} pixels")
    print(f"  Resolution: {resolution} m/px")
    print(f"  L1 (Lobby):  X=[{l1_x_start*resolution:.1f}, {l1_x_end*resolution:.1f}] m")
    print(f"  L2 (Rooms):  X=[{l2_x_start*resolution:.1f}, {l2_x_end*resolution:.1f}] m")
    print(f"  L3 (Suites): X=[{l3_x_start*resolution:.1f}, {l3_x_end*resolution:.1f}] m")

if __name__ == "__main__":
    output_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp"
    output_path = os.path.join(output_dir, "hotel_multilevel.pgm")

    generate_hotel_map(output_path)
