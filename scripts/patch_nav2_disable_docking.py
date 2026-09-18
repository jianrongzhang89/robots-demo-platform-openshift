#!/usr/bin/env python3
"""Remove the unused docking server from the Jazzy Nav2 bringup launch."""

from pathlib import Path


launch_file = Path(
    "/opt/ros/jazzy/share/nav2_bringup/launch/navigation_launch.py")
text = launch_file.read_text()
text = text.replace("        'docking_server',\n", "", 1)
start_marker = "            Node(\n                package='opennav_docking',"
end_marker = "            Node(\n                package='nav2_lifecycle_manager',"
start = text.index(start_marker)
end = text.index(end_marker, start)
launch_file.write_text(text[:start] + text[end:])
