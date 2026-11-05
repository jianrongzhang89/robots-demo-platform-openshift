#!/usr/bin/env python3
"""Static safety and routing checks for the Phase 6D candidate bridges."""
import json
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "helm/semantic-navigation/phase6-demo-topic-bridges.yaml"
ENTRYPOINT = ROOT / "scripts/semantic-navigation/entrypoint_phase6_nav2.sh"


def load_profile():
    docs = list(yaml.safe_load_all(MANIFEST.read_text()))
    config = docs[0]
    bridges = {name: json.loads(value) for name, value in config["data"].items()
               if name.endswith(".json5")}
    return docs, bridges


class Phase6DemoTopologyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs, cls.bridges = load_profile()

    def test_candidate_is_isolated_and_router_image_is_pinned(self):
        self.assertEqual([doc["kind"] for doc in self.docs],
                         ["ConfigMap", "Service", "Deployment"])
        deployment = self.docs[2]
        self.assertEqual(deployment["spec"]["replicas"], 1)
        image = deployment["spec"]["template"]["spec"]["containers"][0]["image"]
        self.assertRegex(image, r"@sha256:[0-9a-f]{64}$")
        self.assertEqual(
            deployment["spec"]["template"]["spec"]["containers"][0]["args"],
            ["-c", "/phase6-config/router.json5"],
        )
        self.assertIn("candidate-not-deployed",
                      self.docs[0]["metadata"]["annotations"][
                          "semantic-navigation.robots-demo/status"])

    def test_all_bridges_use_the_private_phase6_router(self):
        self.assertEqual(set(self.bridges), {
            "router.json5", "sim-bridge.json5", "sim-bridge-d1.json5", "sam3-bridge.json5",
            "nav2-sim-input-bridge.json5", "nav2-semantic-input-bridge.json5",
            "nav2-clock-bridge.json5", "nav2-motion-output-gated.json5",
            "nav2-cmd-vel-keepalive.json5",
        })
        for name, bridge in self.bridges.items():
            if name == "router.json5":
                self.assertEqual(bridge["mode"], "router")
                continue
            self.assertEqual(bridge["mode"], "client")
            self.assertEqual(
                bridge["connect"]["endpoints"],
                ["tcp/semantic-phase6-router:17448"],
            )

    def test_simulator_publishes_only_required_topics_and_accepts_one_cmd_vel(self):
        allow = self.bridges["sim-bridge.json5"]["plugins"]["ros2dds"]["allow"]
        self.assertEqual(set(allow["publishers"]), {
            "^/clock$", "^/robot_1/odom$", "^/robot_1/scan$",
            "^/robot_1/demo/ground_truth$",
            "^/robot_1/tf$", "^/robot_1/tf_static$",
            "^/robot_1/camera/color/image_compressed$",
            "^/robot_1/camera/depth/image_compressed$",
            "^/robot_1/camera/color/camera_info$",
            "^/robot_1/camera/capture_trace$",
            "^/robot_1/camera/compression_trace$",
        })
        self.assertEqual(allow["subscribers"], ["^/robot_1/cmd_vel$"])

    def test_d1_simulator_bridge_has_no_command_subscriber(self):
        allow = self.bridges["sim-bridge-d1.json5"]["plugins"]["ros2dds"]["allow"]
        self.assertEqual(allow["subscribers"], [])
        self.assertEqual(set(allow["publishers"]), set(
            self.bridges["sim-bridge.json5"]["plugins"]["ros2dds"]["allow"]["publishers"]) -
                         {"^/robot_1/demo/ground_truth$"})

    def test_sam3_receives_only_sensor_tf_and_clock_and_exports_semantics(self):
        allow = self.bridges["sam3-bridge.json5"]["plugins"]["ros2dds"]["allow"]
        self.assertEqual(set(allow["subscribers"]), {
            "^/clock$", "^/robot_1/tf$", "^/robot_1/tf_static$",
            "^/robot_1/camera/color/image_compressed$",
            "^/robot_1/camera/depth/image_compressed$",
            "^/robot_1/camera/color/camera_info$",
            "^/robot_1/camera/capture_trace$",
            "^/robot_1/camera/compression_trace$",
        })
        self.assertEqual(set(allow["publishers"]), {
            "^/robot_1/semantic/mask$", "^/robot_1/semantic/points$",
            "^/robot_1/semantic/timing$", "^/robot_1/semantic/label_info$",
            "^/robot_1/semantic/status$", "^/robot_1/semantic/ready$",
        })

    def test_stationary_nav2_input_bridges_cannot_publish_commands(self):
        for name in ("nav2-sim-input-bridge.json5",
                     "nav2-semantic-input-bridge.json5",
                     "nav2-clock-bridge.json5"):
            config = self.bridges[name]["plugins"]["ros2dds"]
            self.assertEqual(config["allow"]["publishers"], [], name)
        sim = self.bridges["nav2-sim-input-bridge.json5"]["plugins"]["ros2dds"]
        self.assertEqual(sim["namespace"], "/robot_1")
        self.assertEqual(set(sim["allow"]["subscribers"]),
                         {".*/tf", ".*/tf_static", ".*/scan", ".*/odom",
                          ".*/demo/ground_truth"})
        semantic = self.bridges[
            "nav2-semantic-input-bridge.json5"]["plugins"]["ros2dds"]
        self.assertNotIn("namespace", semantic)
        self.assertEqual(set(semantic["allow"]["subscribers"]), {
            "^/robot_1/semantic/mask$", "^/robot_1/semantic/points$",
            "^/robot_1/semantic/timing$", "^/robot_1/semantic/label_info$",
        })
        clock = self.bridges["nav2-clock-bridge.json5"]["plugins"]["ros2dds"]
        self.assertEqual(clock["allow"]["subscribers"], ["^/clock$"])

    def test_motion_route_is_separate_and_exactly_one_topic(self):
        config = self.bridges[
            "nav2-motion-output-gated.json5"]["plugins"]["ros2dds"]
        self.assertEqual(config["namespace"], "/robot_1")
        # Anchored to the local topic only: a route created from the remote
        # subscriber announcement (zenoh key "robot_1/cmd_vel", no leading
        # slash) never creates its local DDS reader in the pinned bridge
        # version — see test_phase6_demo_d2 for the full rationale.
        self.assertEqual(config["allow"]["publishers"], ["^/cmd_vel$"])
        self.assertEqual(config["allow"]["subscribers"], [])
        # This manifest deploys only the private router; no Nav2 pod mounts
        # the gated motion config until a later phase explicitly enables it.
        self.assertEqual(self.docs[2]["metadata"]["name"],
                         "semantic-phase6-router")

    def test_no_bridge_routes_navigation_actions_or_fleet_commands(self):
        content = MANIFEST.read_text()
        for forbidden in ("navigate_to_pose", "navigate_through_poses",
                          "rmf_navigate_cmd", "initialpose", "lift_requests",
                          "door_requests"):
            self.assertNotIn(forbidden, content)

    def test_nav2_candidate_entrypoint_uses_overlay_without_duplicate_pose_sources(self):
        script = ENTRYPOINT.read_text()
        executable = "\n".join(line.split("#", 1)[0] for line in script.splitlines())
        self.assertIn("source /opt/ros/jazzy/setup.bash", script)
        self.assertIn("source /opt/semantic-costmap-ws/install/setup.bash", script)
        self.assertIn("hotel_nav2_federated_launch.py", script)
        self.assertIn("phase6-demo-nav2-candidate.yaml", script)
        self.assertNotIn("set -Eeuo", executable)
        self.assertNotIn("robot_state_publisher", executable)
        self.assertNotIn("initialpose", executable)
        self.assertNotIn("cmd_vel", executable)


if __name__ == "__main__":
    unittest.main(verbosity=2)
