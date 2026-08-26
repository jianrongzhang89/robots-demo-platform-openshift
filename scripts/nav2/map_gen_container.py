#!/usr/bin/env python3
import sys
import struct

print("Generating hotel L1 map (pure Python)...")

# Map parameters
resolution = 0.05
origin_x = 0.0
origin_y = -45.0
map_width_m = 35.0
map_height_m = 40.0

width_px = int(map_width_m / resolution)
height_px = int(map_height_m / resolution)

print(f"Map: {width_px}x{height_px} pixels, {resolution}m/px")

# Create map array (255=free, 0=occupied, 205=unknown)
map_data = [[205 for _ in range(width_px)] for _ in range(height_px)]

def world_to_pixel(x, y):
    px = int((x - origin_x) / resolution)
    py = int((map_height_m - (y - origin_y)) / resolution)
    return px, py

# Waypoints
waypoints = [
    (14.56, -38.98), (14.25, -36.40), (15.40, -31.59),
    (19.44, -31.01), (23.53, -30.31), (21.00, -27.00),
    (20.50, -24.50), (20.20, -22.50), (19.90, -20.50),
    (19.85, -21.79), (19.77, -18.93),
]

radius_px = 30  # 1.5m at 0.05m/px
corridor_px = 50  # 2.5m corridor width

# Mark waypoints as free
for wx, wy in waypoints:
    px, py = world_to_pixel(wx, wy)
    for dx in range(-radius_px, radius_px):
        for dy in range(-radius_px, radius_px):
            if dx*dx + dy*dy <= radius_px*radius_px:
                new_px = px + dx
                new_py = py + dy
                if 0 <= new_px < width_px and 0 <= new_py < height_px:
                    map_data[new_py][new_px] = 255

# Connect waypoints
connections = [(0,1),(1,2),(2,3),(3,4),(4,5),(5,6),(6,7),(7,8),(8,9),(9,10)]

for i, j in connections:
    x1, y1 = waypoints[i]
    x2, y2 = waypoints[j]
    px1, py1 = world_to_pixel(x1, y1)
    px2, py2 = world_to_pixel(x2, y2)
    
    steps = max(abs(px2-px1), abs(py2-py1)) * 2 + 1
    for s in range(steps):
        t = s / max(steps - 1, 1)
        px = int(px1 + t * (px2 - px1))
        py = int(py1 + t * (py2 - py1))
        
        for dx in range(-corridor_px//2, corridor_px//2):
            for dy in range(-corridor_px//2, corridor_px//2):
                new_px = px + dx
                new_py = py + dy
                if 0 <= new_px < width_px and 0 <= new_py < height_px:
                    map_data[new_py][new_px] = 255

# Boundaries
for i in range(height_px):
    for j in range(10):
        map_data[i][j] = 0
        map_data[i][width_px-1-j] = 0
for j in range(width_px):
    for i in range(10):
        map_data[i][j] = 0
        map_data[height_px-1-i][j] = 0

# Count
free = sum(row.count(255) for row in map_data)
occ = sum(row.count(0) for row in map_data)
print(f"Free: {free}, Occupied: {occ}")

# Write PGM
with open('/tmp/hotel_L1_map.pgm', 'wb') as f:
    f.write(b'P5\n')
    f.write(f'{width_px} {height_px}\n'.encode())
    f.write(b'255\n')
    for row in map_data:
        f.write(bytes(row))

print("✅ /tmp/hotel_L1_map.pgm")
