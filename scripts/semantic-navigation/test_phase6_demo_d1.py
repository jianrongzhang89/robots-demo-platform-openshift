#!/usr/bin/env python3
"""Static checks for the stationary Phase 6D D1 deployment boundary."""
from pathlib import Path
import subprocess
import sys
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "helm/semantic-navigation/phase6-demo-d1.yaml"
BRIDGES = ROOT / "helm/semantic-navigation/phase6-demo-topic-bridges.yaml"
PARAMS = ROOT / "helm/semantic-navigation/phase6-demo-nav2-candidate.yaml"
RENDERER = ROOT / "scripts/semantic-navigation/render_phase6_demo_d1.py"


class Phase6D1ManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = list(yaml.safe_load_all(MANIFEST.read_text()))
        cls.bridge_doc = list(yaml.safe_load_all(BRIDGES.read_text()))[0]
        cls.workloads = {doc["metadata"]["name"]: doc for doc in cls.docs
                         if doc["kind"] == "Pod"}

    def test_manifest_is_opt_in_and_contains_only_three_stationary_pods(self):
        self.assertEqual([doc["kind"] for doc in self.docs],
                         ["ConfigMap", "Pod", "Pod", "Pod"])
        self.assertEqual(set(self.workloads), {
            "semantic-phase6-simulator", "semantic-phase6-sam3", "semantic-phase6-nav2"})

    def test_d1_has_no_velocity_or_command_bridge_mounted(self):
        manifest = MANIFEST.read_text()
        self.assertNotIn("nav2-motion-output-gated.json5", manifest)
        sim = self.workloads["semantic-phase6-simulator"]
        sim_bridge = next(c for c in sim["spec"]["containers"]
                          if c["name"] == "sim-zenoh-bridge")
        self.assertEqual(sim_bridge["args"],
                         ["-c", "/phase6-bridges/sim-bridge-d1.json5"])
        bridge_data = self.bridge_doc["data"]
        import json
        allowed = json.loads(bridge_data["sim-bridge-d1.json5"])["plugins"]["ros2dds"]["allow"]
        self.assertEqual(allowed["subscribers"], [])
        nav2 = self.workloads["semantic-phase6-nav2"]
        for container in nav2["spec"]["containers"]:
            if container["name"].endswith("bridge"):
                config_name = container["args"][-1].rsplit("/", 1)[-1]
                cfg = json.loads(bridge_data[config_name])["plugins"]["ros2dds"]
                self.assertEqual(cfg["allow"]["publishers"], [], container["name"])

    def test_nav2_adapters_mount_their_cyclonedds_config(self):
        nav2 = self.workloads["semantic-phase6-nav2"]["spec"]
        by_name = {c["name"]: c for c in nav2["containers"]}
        for name in ("odom-tf", "scan-frame-rewriter"):
            self.assertTrue(any(mount["name"] == "nav2-config"
                                for mount in by_name[name]["volumeMounts"]))

    def test_domains_images_and_node_placement_match_pinned_profile(self):
        sim = self.workloads["semantic-phase6-simulator"]["spec"]
        sam = self.workloads["semantic-phase6-sam3"]["spec"]
        nav = self.workloads["semantic-phase6-nav2"]["spec"]
        self.assertEqual(sim["nodeSelector"]["kubernetes.io/hostname"],
                         "ip-10-0-38-113.ec2.internal")
        self.assertEqual(sam["nodeSelector"]["kubernetes.io/hostname"],
                         "ip-10-0-18-251.ec2.internal")
        self.assertEqual(nav["nodeSelector"]["kubernetes.io/hostname"],
                         "ip-10-0-38-113.ec2.internal")
        simulator = next(c for c in sim["containers"] if c["name"] == "simulator")
        compressor = next(c for c in sim["containers"] if c["name"] == "camera-compressor")
        self.assertIn("semantic-hotel-sim@sha256:d417c9f252d1f89dd859290a4bca1f634bcfd7d3cde6d1702c409d432bd48894",
                      simulator["image"])
        self.assertIn("semantic-hotel-sim@sha256:c3ba94bbcbbe2283f1c46ea0f2baba398da313ffe83d2b59a63272ef91d95ebf",
                      compressor["image"])
        self.assertIn({"name": "SEMANTIC_CAPTURE_TRACE", "value": "1"},
                      simulator["env"])
        sam_container = next(c for c in sam["containers"] if c["name"] == "sam3-inference")
        self.assertIn("sam3-runtime@sha256:478ec01a7a47fbb0c862fbbef495c71b4a512ff59ed8d6ed5b7234422cc35686",
                      sam_container["image"])
        self.assertEqual(sam_container["resources"]["requests"]["nvidia.com/gpu"], "1")
        nav2_container = next(c for c in nav["containers"] if c["name"] == "nav2")
        self.assertIn("semantic-nav2@sha256:d23d20a8decdd9a6cc0f9419874c1b610333e033867e579aeb022a5bb1b97b0e",
                      nav2_container["image"])
        for pod, expected in ((sim, "81"), (sam, "82"), (nav, "87")):
            domains = {env["value"] for c in pod["containers"] for env in c.get("env", [])
                       if env["name"] == "ROS_DOMAIN_ID"}
            self.assertEqual(domains, {expected})

    def test_embedded_nav2_params_equal_reviewed_candidate(self):
        output = subprocess.run([sys.executable, str(RENDERER)], check=True,
                                capture_output=True, text=True).stdout
        rendered = list(yaml.safe_load_all(output))
        config = rendered[0]["data"]["phase6-demo-nav2-candidate.yaml"]
        self.assertEqual(yaml.safe_load(config), yaml.safe_load(PARAMS.read_text()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
