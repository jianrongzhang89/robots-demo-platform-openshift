#!/usr/bin/env python3
"""Keep the Gazebo GUI camera stable while RMF moves a lift."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rmf_lift_msgs.msg import LiftState


PARTITION = os.environ.get("GZ_PARTITION", "hotel_nav2_rmf")
FOLLOW = (
    'track_mode: FOLLOW_LOOK_AT follow_target: {name: "robot_1"} '
    'track_target: {name: "robot_1"} follow_offset: {x: 0 y: 0 z: 5} '
    'track_offset: {x: 0 y: 0 z: 0} follow_pgain: 0.02 track_pgain: 0.02'
)


class CameraSupervisor(Node):
    def __init__(self):
        super().__init__("hotel_camera_follow_supervisor")
        qos = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )
        self.create_subscription(LiftState, "/lift_states", self._state, qos)
        self._moving = False
        self._transition = 0
        self._command_lock = threading.Lock()
        self._restart_lock = threading.Lock()
        self._last_restart = 0.0
        self.create_timer(2.0, self._check_camera_pose)

    def _run(self, args: list[str], timeout: float = 3.0) -> None:
        env = os.environ.copy()
        env["GZ_PARTITION"] = PARTITION
        try:
            subprocess.run(
                args, env=env, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired):
            pass

    def _check_camera_pose(self) -> None:
        if self._restart_lock.locked():
            return
        threading.Thread(target=self._check_camera_pose_thread, daemon=True).start()

    def _check_camera_pose_thread(self) -> None:
        if time.monotonic() - self._last_restart < 30.0:
            return
        env = os.environ.copy()
        env["GZ_PARTITION"] = PARTITION
        try:
            result = subprocess.run(
                ["timeout", "2", "gz", "topic", "-e", "-t",
                 "/gui/camera/pose", "-n", "1"],
                env=env, capture_output=True, text=True, timeout=3, check=False)
            match = re.search(
                r"position\s*\{.*?\bz:\s*([-+0-9.eE]+)",
                result.stdout, re.DOTALL)
            if match and float(match.group(1)) < 0.0:
                self._restart_gui()
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass

    def _restart_gui(self) -> None:
        if not self._restart_lock.acquire(blocking=False):
            return
        try:
            self._last_restart = time.monotonic()
            self.get_logger().warning("Restarting Gazebo GUI after invalid camera pose")
            result = subprocess.run(
                ["ps", "-eo", "pid=,args="], capture_output=True,
                text=True, check=False)
            gui_pids = []
            for line in result.stdout.splitlines():
                fields = line.strip().split(None, 1)
                if len(fields) == 2 and "gz sim -g" in fields[1]:
                    try:
                        gui_pids.append(int(fields[0]))
                    except (OSError, ValueError):
                        pass
            for pid in gui_pids:
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass
            time.sleep(1.0)
            for pid in gui_pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
            time.sleep(2.0)
            env = os.environ.copy()
            env["GZ_PARTITION"] = PARTITION
            env["GZ_LOG_PATH"] = "/tmp/gz-gui-logs"
            env["DISPLAY"] = env.get("DISPLAY", ":99")
            subprocess.Popen(
                ["gz", "sim", "--force-version", "8", "-g", "-v", "2",
                 "/opt/ros2-demo/hotel-assets/hotel.world"],
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _attempt in range(60):
                track_info = subprocess.run(
                    ["gz", "topic", "-i", "-t", "/gui/track"],
                    env=env, capture_output=True, text=True, check=False)
                follow_info = subprocess.run(
                    ["gz", "service", "-i", "-s", "/gui/follow"],
                    env=env, capture_output=True, text=True, check=False)
                if ("Subscribers" in track_info.stdout and
                        "gz.msgs.StringMsg" in follow_info.stdout):
                    break
                time.sleep(0.5)
            self._publish_mode("follow")
        finally:
            self._restart_lock.release()

    def _publish_mode(self, mode: str | None) -> None:
        with self._command_lock:
            if mode is None:
                self._run([
                    "timeout", "2", "gz", "topic", "-t", "/gui/track",
                    "-m", "gz.msgs.CameraTrack", "-p", "track_mode: NONE",
                ])
                return
            self._run([
                "gz", "service", "-s", "/gui/follow",
                "--reqtype", "gz.msgs.StringMsg",
                "--reptype", "gz.msgs.Boolean", "--timeout", "3000",
                "--req", 'data: "robot_1"',
            ])
            self._run([
                "gz", "service", "-s", "/gui/follow/offset",
                "--reqtype", "gz.msgs.Vector3d",
                "--reptype", "gz.msgs.Boolean", "--timeout", "3000",
                "--req", "x: 0 y: 0 z: 5",
            ])
            self._run([
                "timeout", "2", "gz", "topic", "-t", "/gui/track",
                "-m", "gz.msgs.CameraTrack", "-p", FOLLOW,
            ])

    def _state(self, message: LiftState) -> None:
        if message.lift_name != "Lift2":
            return
        moving = (
            message.motion_state != 0 or
            message.current_floor != message.destination_floor)
        if moving == self._moving:
            return
        self._moving = moving
        self._transition += 1
        transition = self._transition
        if moving:
            self.get_logger().info("Pausing camera tracking during lift motion")
            threading.Thread(target=self._publish_mode, args=(None,), daemon=True).start()
        else:
            self.get_logger().info("Resuming overhead camera tracking")
            threading.Thread(
                target=self._resume_after_settle,
                args=(transition,), daemon=True).start()

    def _resume_after_settle(self, transition: int) -> None:
        time.sleep(10.0)
        if transition == self._transition and not self._moving:
            self._publish_mode("follow")


def main() -> None:
    rclpy.init()
    node = CameraSupervisor()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
