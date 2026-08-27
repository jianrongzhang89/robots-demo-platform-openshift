# OpenRMF + Zenoh + Nav2 Integration
# Base: Working rmf-hotel-navgraph-extended image (Ubuntu-based)
FROM image-registry.openshift-image-registry.svc:5000/ros2-rmf-hotel-federated/rmf-hotel-navgraph-extended:latest

USER root

# Install Nav2 and dependencies (Ubuntu/apt-based)
RUN apt-get update && apt-get install -y \
    ros-jazzy-navigation2 \
    ros-jazzy-nav2-bringup \
    ros-jazzy-nav2-msgs \
    ros-jazzy-nav2-common \
    ros-jazzy-dwb-core \
    ros-jazzy-dwb-plugins \
    ros-jazzy-dwb-critics \
    ros-jazzy-nav2-amcl \
    ros-jazzy-nav2-controller \
    ros-jazzy-nav2-planner \
    ros-jazzy-nav2-behaviors \
    ros-jazzy-nav2-bt-navigator \
    ros-jazzy-nav2-costmap-2d \
    ros-jazzy-nav2-lifecycle-manager \
    ros-jazzy-nav2-map-server \
    ros-jazzy-nav2-navfn-planner \
    ros-jazzy-nav2-smac-planner \
    ros-jazzy-nav2-theta-star-planner \
    ros-jazzy-nav2-regulated-pure-pursuit-controller \
    ros-jazzy-nav2-rotation-shim-controller \
    ros-jazzy-nav2-rviz-plugins \
    ros-jazzy-nav2-util \
    ros-jazzy-nav2-waypoint-follower \
    ros-jazzy-nav2-core \
    python3-transforms3d \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create Nav2 directories
RUN mkdir -p /opt/nav2_config /opt/nav2_scripts /opt/nav2_maps

# Copy Nav2 configuration files
COPY nav2_params_robot2.yaml /opt/nav2_config/
COPY map_gen_container.py /opt/nav2_scripts/
COPY nav2_launch.py /opt/nav2_scripts/
COPY rmf_nav2_bridge.py /opt/nav2_scripts/

# ADDED: Copy modified TinyRobot model with diff_drive plugin for Nav2
# This overlays the original slotcar-only model with one that supports both
# RMF slotcar control AND Nav2 cmd_vel control
COPY custom_models/TinyRobot/model.sdf /opt/rmf_demos_ws/install/share/rmf_demos_assets/models/TinyRobot/model.sdf

# Copy and configure Nav2 bridge startup script
COPY start_nav2_bridge.sh /opt/nav2_scripts/
COPY start_nav2_stack.sh /opt/nav2_scripts/
COPY generate_hotel_map.sh /opt/nav2_scripts/
COPY entrypoint-nav2.sh /entrypoint-nav2.sh

# Make all scripts executable
RUN chmod +x /opt/nav2_scripts/*.sh && \
    chmod +x /opt/nav2_scripts/*.py && \
    chmod +x /entrypoint-nav2.sh

# Set permissions for OpenShift (non-root)
RUN chown -R 1001:0 /opt/nav2_config /opt/nav2_scripts /opt/nav2_maps && \
    chmod -R g=u /opt/nav2_config /opt/nav2_scripts /opt/nav2_maps

USER 1001

WORKDIR /tmp
