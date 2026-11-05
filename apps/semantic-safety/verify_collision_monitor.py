#!/usr/bin/env python3
"""Non-actuating Jazzy smoke test with synthetic scan/TF/footprint/commands.

Run only in the isolated test pod (domain 85, loopback DDS, no bridge). This is
not a physical stop, geometric localization or live SAM3 fault qualification.
"""
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

import rclpy
from geometry_msgs.msg import Point32, PolygonStamped, TransformStamped, TwistStamped
from lifecycle_msgs.srv import ChangeState
from nav2_msgs.msg import CollisionMonitorState
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from tf2_ros import StaticTransformBroadcaster
import yaml
from command_ledger import CommandLedger
from safety_core import Now


def main():
    if os.getenv("ROS_DOMAIN_ID") != "85" or "phase5" not in os.getenv("CYCLONEDDS_URI", ""):
        raise RuntimeError("refusing to run outside isolated Phase 5 fixture")
    profile = yaml.safe_load(Path("/phase5/phase5-nav2-candidate.yaml").read_text())
    params = profile["collision_monitor"]["ros__parameters"]
    params["use_sim_time"] = False  # synthetic fixture uses wall stamps, no simulator
    smoother_params = profile["velocity_smoother"]["ros__parameters"]
    smoother_params["use_sim_time"] = False
    with tempfile.TemporaryDirectory(prefix="phase5-collision-") as directory:
        config = Path(directory) / "params.yaml"
        config.write_text(yaml.safe_dump({"collision_monitor": {"ros__parameters": params},
                                          "velocity_smoother": {"ros__parameters": smoother_params}}))
        with (Path(directory) / "monitor.log").open("w+") as log:
            process = subprocess.Popen(["/opt/ros/jazzy/lib/nav2_collision_monitor/collision_monitor",
                                        "--ros-args", "--params-file", str(config)], stdout=log, stderr=subprocess.STDOUT)
            smoother = subprocess.Popen(["/opt/ros/jazzy/lib/nav2_velocity_smoother/velocity_smoother",
                                         "--ros-args", "--params-file", str(config),
                                         "-r", "cmd_vel:=phase5/source_velocity"], stdout=log, stderr=subprocess.STDOUT)
            rclpy.init()
            node = Node("phase5_non_actuating_fixture")
            records, states, checks = [], [], []
            ledger = CommandLedger(); ledger.reset("fixture", 0)
            def receive(message):
                now = Now(time.monotonic_ns(), time.time_ns(), node.get_clock().now().nanoseconds)
                stamp = message.header.stamp.sec*1_000_000_000+message.header.stamp.nanosec
                velocity = (message.twist.linear.x, message.twist.linear.y, message.twist.angular.z)
                source = ledger.resolve("fixture", stamp, velocity, now)
                records.append({"wall_ns": now.wall, "steady_ns": now.steady, "stamp_ns": stamp,
                                "x": velocity[0], "yaw": velocity[2], "admitted": source is not None,
                                "known_source": stamp in ledger.entries})
            node.create_subscription(TwistStamped, "/phase5/collision_checked", receive, 10)
            node.create_subscription(CollisionMonitorState, "/collision_monitor_state",
                                     lambda m: states.append({"steady_ns": time.monotonic_ns(), "state": str(m)}), 10)
            commands = node.create_publisher(TwistStamped, "/phase5/source_velocity", 10)
            scans = node.create_publisher(LaserScan, "/scan_fixed", 10)
            footprints = node.create_publisher(PolygonStamped, "/local_costmap/published_footprint", 10)
            transforms = StaticTransformBroadcaster(node)
            tfs = []
            for parent, child, z in (("odom", "base_footprint", 0.0), ("base_footprint", "base_scan", .25)):
                tf = TransformStamped()
                tf.header.stamp = node.get_clock().now().to_msg()
                tf.header.frame_id, tf.child_frame_id = parent, child
                tf.transform.translation.z, tf.transform.rotation.w = z, 1.0
                tfs.append(tf)
            transforms.sendTransform(tfs)
            clients = [node.create_client(ChangeState, "/"+name+"/change_state")
                       for name in ("velocity_smoother", "collision_monitor")]

            def drive(duration, obstacle=False, publish_scan=True, speed=.1, publish_command=True):
                started = time.monotonic_ns()
                while time.monotonic_ns() - started < int(duration * 1e9):
                    stamp = node.get_clock().now().to_msg()
                    footprint = PolygonStamped()
                    footprint.header.stamp, footprint.header.frame_id = stamp, "base_footprint"
                    footprint.polygon.points = [Point32(x=x, y=y, z=0.0) for x, y in
                                                ((-.182, -.165), (.118, -.165), (.118, .165), (-.182, .165))]
                    footprints.publish(footprint)
                    if publish_scan:
                        scan = LaserScan()
                        scan.header.stamp, scan.header.frame_id = stamp, "base_scan"
                        scan.angle_min, scan.angle_max, scan.angle_increment = 0.0, 2*math.pi, 2*math.pi/359
                        scan.range_min, scan.range_max = .12, 3.5
                        scan.ranges = [float("inf")] * 360
                        scan.ranges[0] = .22 if obstacle else 2.0
                        scans.publish(scan)
                    message = TwistStamped()
                    message.header.stamp = stamp
                    message.header.frame_id = "base_footprint"
                    message.twist.linear.x = speed
                    if publish_command:
                        source_stamp = stamp.sec*1_000_000_000+stamp.nanosec
                        assert ledger.record("fixture", source_stamp, source_stamp, (speed,0,0),
                                             Now(time.monotonic_ns(),time.time_ns(),node.get_clock().now().nanoseconds))
                        commands.publish(message)
                    rclpy.spin_once(node, timeout_sec=.01)
                    time.sleep(.01)
                return started, [r for r in records if r["steady_ns"] >= started]

            try:
                for client in clients:
                    if not client.wait_for_service(timeout_sec=20):
                        raise RuntimeError("command-chain lifecycle service missing")
                    for transition in (1, 3):
                        req = ChangeState.Request()
                        req.transition.id = transition
                        future = client.call_async(req)
                        rclpy.spin_until_future_complete(node, future, timeout_sec=10)
                        if not future.done() or not future.result().success:
                            raise RuntimeError(f"lifecycle transition {transition} failed")
                start, output = drive(2.0)
                assert any(r["x"] > .09 for r in output), "nominal command blocked"
                checks.append({"case": "clear_scan_passes_command", "passed": True})
                assert any(r["x"]>.09 and r["admitted"] for r in output), "stamped nominal output not admitted"
                checks.append({"case": "source_stamp_preserved_through_smoothing_and_monitor", "passed": True})
                start, output = drive(.5, publish_command=False)
                late = [r for r in output if r["steady_ns"]>=start+120_000_000]
                assert late and all(not r["admitted"] for r in late), "smoothing renewed source authority"
                assert any(r["x"]>0 and not r["known_source"] and not r["admitted"] for r in late), "timeout-restamp regression not exercised"
                checks.append({"case": "smoother_timeout_restamps_cannot_renew_permission", "passed": True})
                drive(.5)
                start, output = drive(1.0, obstacle=True)
                zeros = [r for r in output if r["x"] == 0 and r["yaw"] == 0]
                assert zeros, "stop polygon failed"
                latency_ms = (zeros[0]["steady_ns"] - start)/1e6
                assert latency_ms <= 100, f"fixture intervention took {latency_ms} ms"
                assert all(r["x"] == 0 for r in output if r["steady_ns"] >= start + 200_000_000)
                checks.append({"case": "stop_polygon_intervenes", "passed": True, "fixture_first_zero_ms": latency_ms})
                _, output = drive(1.0)
                assert any(r["x"] > .09 for r in output), "clear scan did not restore native monitor output"
                checks.append({"case": "native_monitor_can_resume_requires_external_latch", "passed": True})
                start, output = drive(1.5, publish_scan=False)
                late = [r for r in output if r["steady_ns"] >= start + 650_000_000]
                assert late and all(r["x"] == 0 for r in late), "expired scan did not stop"
                checks.append({"case": "source_timeout_stops_with_continuing_commands", "passed": True})
                drive(.5)
                # Fresh receipt of an explicitly old stamped input is not a
                # new command; do not record it in the source ledger.
                old = TwistStamped(); old.header.frame_id = "base_footprint"
                ns = node.get_clock().now().nanoseconds-1_000_000_000
                old.header.stamp.sec, old.header.stamp.nanosec = divmod(ns,1_000_000_000)
                old.twist.linear.x = .1
                commands.publish(old)
                start, output = drive(.4, publish_command=False)
                assert all(not r["admitted"] for r in output if r["steady_ns"]>=start+120_000_000)
                checks.append({"case": "late_stamped_input_not_refreshed_on_receipt", "passed": True})
                graph = dict(node.get_topic_names_and_types())
                assert "/robot_1/cmd_vel" not in graph and "/cmd_vel" not in graph
                checks.append({"case": "no_actuator_topic", "passed": True})
                print(json.dumps({"event": "phase5_native_collision_fixture", "passed": True,
                                  "checks": checks, "outputs": records, "states": states,
                                  "topics": graph, "params": params,
                                  "smoother_params": smoother_params}, sort_keys=True), flush=True)
            finally:
                node.destroy_node()
                rclpy.shutdown()
                for child in (process,smoother):
                    child.send_signal(signal.SIGINT)
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=5)
                log.seek(0)
                print("NATIVE_MONITOR_LOG_BEGIN\n" + log.read() + "NATIVE_MONITOR_LOG_END", flush=True)


if __name__ == "__main__":
    main()
