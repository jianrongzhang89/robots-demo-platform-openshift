import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

import yaml
from render_phase5_params import candidate, FOOTPRINT, STOP_POLYGON

ROOT = Path(__file__).resolve().parents[2]


class CandidateProfileTests(unittest.TestCase):
    def setUp(self):
        self.original = yaml.safe_load((ROOT / "config/nav2/hotel_nav2_params.yaml").read_text())
        self.config = candidate(self.original)

    def test_checked_in_candidate_matches_renderer(self):
        self.assertEqual(self.config, yaml.safe_load((ROOT / "helm/semantic-navigation/phase5-nav2-candidate.yaml").read_text()))

    def test_original_unmodified(self):
        self.assertFalse(self.original["global_costmap"]["global_costmap"]["ros__parameters"]["obstacle_layer"]["enabled"])
        self.assertEqual(self.original["collision_monitor"]["ros__parameters"]["cmd_vel_out_topic"], "cmd_vel")

    def test_both_maps_have_same_explicit_hull_and_geometric_layers(self):
        for name, geometry in (("global_costmap", "obstacle_layer"), ("local_costmap", "voxel_layer")):
            params = self.config[name][name]["ros__parameters"]
            self.assertEqual(json.loads(params["footprint"]), FOOTPRINT)
            self.assertEqual(params["footprint_padding"], .01)
            self.assertNotIn("robot_radius", params)
            self.assertTrue(params[geometry]["enabled"])
            self.assertTrue(params["inflation_layer"]["enabled"])
            self.assertFalse(any("semantic" in p.lower() for p in params["plugins"]))

    def test_monitor_enabled_but_output_disconnected(self):
        params = self.config["collision_monitor"]["ros__parameters"]
        self.assertEqual(params["cmd_vel_out_topic"], "phase5/collision_checked")
        self.assertEqual(json.loads(params["StopEnvelope"]["points"]), STOP_POLYGON)
        self.assertTrue(params["StopEnvelope"]["enabled"])
        self.assertTrue(params["FootprintApproach"]["enabled"])
        self.assertEqual(params["source_timeout"], .5)

    def test_limited_speed_no_docking_and_one_map_authority(self):
        self.assertEqual(self.config["controller_server"]["ros__parameters"]["FollowPath"]["desired_linear_vel"], .15)
        self.assertEqual(self.config["velocity_smoother"]["ros__parameters"]["max_velocity"], [.15, 0, .5])
        self.assertNotIn("docking_server", self.config)
        self.assertTrue(self.config["amcl"]["ros__parameters"]["tf_broadcast"])

    def test_command_stamps_preserved(self):
        for name in ("controller_server", "behavior_server", "velocity_smoother", "collision_monitor"):
            self.assertTrue(self.config[name]["ros__parameters"]["enable_stamped_cmd_vel"])
        self.assertFalse(self.config["velocity_smoother"]["ros__parameters"]["stamp_smoothed_velocity_with_smoothing_time"])

    def test_guard_compatible_rates_and_goal_arrival_recheck(self):
        controller=self.config["controller_server"]["ros__parameters"]
        self.assertEqual(controller["controller_frequency"],40.)
        self.assertFalse(controller["FollowPath"]["stateful"])
        # In-place goal rotation is disabled: its zero linear velocity can
        # deadlock against the goal checker's stale-stamp odom-frame target
        # when AMCL drift holds that target outside xy tolerance while RPP's
        # current-frame carrot is already inside (October 23 GPU trial 2).
        self.assertFalse(controller["FollowPath"]["use_rotate_to_heading"])
        self.assertEqual(controller["general_goal_checker"],self.original["controller_server"]["ros__parameters"]["general_goal_checker"])
        self.assertEqual(self.config["behavior_server"]["ros__parameters"]["cycle_frequency"],40.)
        self.assertEqual(self.config["velocity_smoother"]["ros__parameters"]["smoothing_frequency"],100.)
        self.assertEqual(self.config["bt_navigator"]["ros__parameters"]["default_cancel_timeout"],2000)

    def test_baseline_tree_explicitly_excludes_recoveries(self):
        tree=ET.parse(ROOT/"apps/semantic-safety/phase5-baseline.xml")
        self.assertEqual({node.tag for node in tree.iter()},
                         {"root","BehaviorTree","Sequence","ComputePathToPose","FollowPath"})

    def test_costmaps_use_actual_robot_scan_not_child_namespace(self):
        for name,layer in (("local_costmap","voxel_layer"),("global_costmap","obstacle_layer")):
            self.assertEqual(self.config[name][name]["ros__parameters"][layer]["scan"]["topic"],
                             "/robot_1/scan_fixed")

    def test_hull_covers_pinned_sdf_collisions(self):
        path = ROOT / "docs/validation/semantic-navigation/phase-5/preflight-1-20261016/geometry.json"
        evidence = json.loads(path.read_text())
        minimum = [min(p[i] for p in FOOTPRINT) for i in range(2)]
        maximum = [max(p[i] for p in FOOTPRINT) for i in range(2)]
        for item in evidence["collisions"]:
            for i in range(2):
                self.assertLessEqual(minimum[i], item["min"][i] + 1e-9)
                self.assertGreaterEqual(maximum[i], item["max"][i] - 1e-9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
