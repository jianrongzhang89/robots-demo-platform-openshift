#!/bin/bash
# Generate a simple occupancy grid map for the hotel world
# This creates a basic map structure for Nav2 navigation

export HOME=/tmp
source /opt/ros/jazzy/setup.bash

# Create maps directory
mkdir -p /opt/nav2_maps

# For now, create a large empty map (50m x 50m)
# In production, this should be generated from the actual hotel world geometry
cat > /opt/nav2_maps/hotel_map.yaml << 'EOF'
image: hotel_map.pgm
resolution: 0.05
origin: [0.0, -50.0, 0.0]
negate: 0
occupied_thresh: 0.65
free_thresh: 0.196
EOF

# Create a simple PGM map file (50m/0.05m = 1000 pixels)
# For now, create an empty map (all free space)
# In production, use slam_toolbox or map generation from SDF
cat > /opt/nav2_maps/hotel_map.pgm << 'EOF'
P5
1000 1000
255
EOF

# Fill with free space (205 = mostly free)
dd if=/dev/zero bs=1 count=1000000 2>/dev/null | tr '\000' '\315' >> /opt/nav2_maps/hotel_map.pgm

echo "Hotel map generated at /opt/nav2_maps/hotel_map.yaml"
ls -lh /opt/nav2_maps/
