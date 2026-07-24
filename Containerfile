FROM registry.fedoraproject.org/fedora:43

ENV TURTLEBOT3_MODEL=waffle \
    ROS_DISTRO=jazzy

RUN dnf install -y dnf-plugins-core && \
    dnf copr enable -y tavie/ros2

RUN dnf install -y \
      ros-jazzy-ros-base \
      ros-jazzy-navigation2 \
      ros-jazzy-nav2-bringup \
      ros-jazzy-nav2-minimal-tb3-sim \
      ros-jazzy-teleop-twist-keyboard \
      ros-jazzy-ros-gz-bridge \
      ros-jazzy-ros-gz-sim \
      ros-jazzy-gz-sim-vendor \
    && dnf clean all

RUN dnf install -y \
      mesa-libGL \
      mesa-dri-drivers \
      mesa-libEGL \
      xorg-x11-server-Xvfb \
      x11vnc \
      novnc \
      python3-websockify \
      openbox \
      xterm \
      python3 \
    && dnf clean all

RUN mkdir -p /tmp/.X11-unix && chmod 1777 /tmp/.X11-unix

RUN printf '<!DOCTYPE html>\n<html><head><meta http-equiv="refresh" content="0;url=vnc_lite.html?autoconnect=true&resize=scale"></head></html>\n' > /usr/share/novnc/index.html

ENV ROS_PREFIX=/usr/lib64/ros-jazzy \
    GZ_SIM_RESOURCE_PATH=/usr/lib64/ros-jazzy/share/nav2_minimal_tb3_sim/models \
    GZ_SIM_SYSTEM_PLUGIN_PATH=/usr/lib64/ros-jazzy/opt/gz_sim_vendor/lib64/gz-sim-8/plugins \
    GZ_SIM_PHYSICS_ENGINE_PATH=/usr/lib64/ros-jazzy/opt/gz_physics_vendor/lib64/gz-physics-7/engine-plugins \
    GZ_RENDERING_PLUGIN_PATH=/usr/lib64/ros-jazzy/opt/gz_rendering_vendor/lib64/gz-rendering-8/engine-plugins \
    GZ_GUI_PLUGIN_PATH=/usr/lib64/ros-jazzy/opt/gz_gui_vendor/lib64/gz-gui-8/plugins:/usr/lib64/ros-jazzy/opt/gz_sim_vendor/lib64/gz-sim-8/plugins/gui

RUN echo "/usr/lib64/ros-jazzy/opt/gz_sim_vendor/lib64" > /etc/ld.so.conf.d/gz-vendor.conf && \
    for d in /usr/lib64/ros-jazzy/opt/*/lib64; do echo "$d" >> /etc/ld.so.conf.d/gz-vendor.conf; done && \
    ldconfig && \
    mkdir -p /etc/gz/sim/8 && \
    cp /usr/lib64/ros-jazzy/opt/gz_sim_vendor/share/gz/gz-sim8/server.config /etc/gz/sim/8/

RUN mkdir -p /builddir/build/BUILD/ros-jazzy-gz-rendering-vendor-0.0.7-build && \
    ln -s / /builddir/build/BUILD/ros-jazzy-gz-rendering-vendor-0.0.7-build/BUILDROOT && \
    mkdir -p /usr/lib64/ros-jazzy/opt/gz_rendering_vendor/share/gz/gz-rendering8/ogre2/src && \
    ln -s ../media /usr/lib64/ros-jazzy/opt/gz_rendering_vendor/share/gz/gz-rendering8/ogre2/src/media && \
    mkdir -p /builddir/build/BUILD/ros-jazzy-gz-ogre-next-vendor-0.0.5-build && \
    ln -s / /builddir/build/BUILD/ros-jazzy-gz-ogre-next-vendor-0.0.5-build/BUILDROOT && \
    mkdir -p /builddir/build/BUILD/ros-jazzy-gz-sim-vendor-0.0.10-build && \
    ln -s / /builddir/build/BUILD/ros-jazzy-gz-sim-vendor-0.0.10-build/BUILDROOT

WORKDIR /opt/ros2-demo

COPY entrypoints/entrypoint-gazebo.sh /entrypoint-gazebo.sh
COPY entrypoints/entrypoint-nav2.sh /entrypoint-nav2.sh
COPY config/worlds/ /opt/ros2-demo/worlds/
COPY config/www/ /opt/ros2-demo/www/
COPY config/nav2/ /opt/ros2-demo/nav2/

RUN chmod +x /entrypoint-gazebo.sh /entrypoint-nav2.sh

EXPOSE 6080 8080

CMD ["/bin/bash"]
