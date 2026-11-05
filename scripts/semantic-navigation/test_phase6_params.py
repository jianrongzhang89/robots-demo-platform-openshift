import copy
import importlib.util
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "render_phase6_params", ROOT / "scripts/semantic-navigation/render_phase6_params.py")
renderer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(renderer)

DEMO_SPEC = importlib.util.spec_from_file_location(
    "render_phase6_demo_params", ROOT / "scripts/semantic-navigation/render_phase6_demo_params.py")
demo = importlib.util.module_from_spec(DEMO_SPEC)
DEMO_SPEC.loader.exec_module(demo)


def deep_diff(path, before, after, additions):
    """Collect every difference between before and after into additions."""
    if type(before) is not type(after):
        additions.append((path, before, after))
    elif isinstance(before, dict):
        for key in set(before) | set(after):
            if key not in before:
                additions.append((path + [key], None, after[key]))
            elif key not in after:
                additions.append((path + [key], before[key], None))
            else:
                deep_diff(path + [key], before[key], after[key], additions)
    elif before != after:
        additions.append((path, before, after))


class Phase6ParamsTests(unittest.TestCase):
    def setUp(self):
        self.phase5 = yaml.safe_load(
            (ROOT / "helm/semantic-navigation/phase5-nav2-candidate.yaml").read_text())
        self.before = copy.deepcopy(self.phase5)
        self.config = renderer.candidate(self.phase5)

    def test_phase5_candidate_is_not_mutated(self):
        self.assertEqual(self.phase5, self.before)

    def test_only_semantic_layer_additions_differ_from_phase5(self):
        expected = copy.deepcopy(self.before)
        params = expected["global_costmap"]["global_costmap"]["ros__parameters"]
        params["plugins"].insert(params["plugins"].index("inflation_layer"), "semantic_layer")
        params["semantic_layer"] = copy.deepcopy(demo.SEMANTIC_CONFIG)
        self.assertEqual(self.config, expected)
        additions = []
        deep_diff([], self.before, self.config, additions)
        self.assertTrue(additions)
        for path, _, _ in additions:
            self.assertEqual(path[:3], [path[0], path[0], "ros__parameters"], path)
            self.assertIn(path[-1], ("plugins", "semantic_layer"), path)
            self.assertEqual(path[0], "global_costmap", path)

    def test_semantic_layer_is_additive_and_precedes_inflation(self):
        params = self.config["global_costmap"]["global_costmap"]["ros__parameters"]
        plugins = params["plugins"]
        self.assertLess(plugins.index("semantic_layer"), plugins.index("inflation_layer"))
        self.assertEqual(params["semantic_layer"], demo.SEMANTIC_CONFIG)
        self.assertEqual(params["semantic_layer"]["target_cost"], 200)
        self.assertLess(params["semantic_layer"]["target_cost"], 253)

    def test_local_costmap_stays_geometry_only(self):
        """The local costmap keeps the exact Phase 5 configuration.

        User-approved October 28, 2026: the local map's semantic subscription
        loaded ~26 MB/s of observation clouds into the controller's own
        process, whose reader lag tripped the layer's 500 ms isCurrent window
        and blocked the controller's cycle past the 100 ms command authority
        (pilot-1 pair-1-on-tfdiag/-qosfix). The local costmap must not
        subscribe any semantic topic or carry the layer.
        """
        local = self.config["local_costmap"]["local_costmap"]["ros__parameters"]
        before = self.before["local_costmap"]["local_costmap"]["ros__parameters"]
        self.assertEqual(local, before)
        self.assertNotIn("semantic_layer", local["plugins"])
        self.assertNotIn("semantic_layer", local)

    def test_safety_and_navigation_settings_match_phase5_exactly(self):
        for node in ("controller_server", "planner_server", "collision_monitor",
                     "velocity_smoother", "bt_navigator", "behavior_server", "amcl"):
            self.assertEqual(self.config[node], self.before[node])

    def test_geometric_layers_footprint_and_rates_are_unchanged(self):
        for name, geometry in (("global_costmap", "obstacle_layer"), ("local_costmap", "voxel_layer")):
            before = self.before[name][name]["ros__parameters"]
            after = self.config[name][name]["ros__parameters"]
            self.assertEqual(after[geometry], before[geometry])
            self.assertEqual(after["static_layer" if geometry == "obstacle_layer" else "voxel_layer"]
                             if geometry == "obstacle_layer" else after["voxel_layer"],
                             before["static_layer" if geometry == "obstacle_layer" else "voxel_layer"])
            self.assertEqual(after["inflation_layer"], before["inflation_layer"])
            self.assertEqual(after["footprint"], before["footprint"])
            self.assertEqual(after["update_frequency"], before["update_frequency"])

    def test_checked_in_candidate_matches_renderer_output(self):
        checked_in = yaml.safe_load(
            (ROOT / "helm/semantic-navigation/phase6-nav2-candidate.yaml").read_text())
        self.assertEqual(checked_in, self.config)

    def test_duplicate_layer_is_rejected(self):
        with self.assertRaises(ValueError):
            renderer.candidate(self.config)

    def test_lethal_variant_changes_only_the_target_cost(self):
        """The lethal-cost exclusion experiment (implementation plan).

        The variant must differ from the qualified soft-cost candidate ONLY
        by the global semantic layer's target_cost (200 -> 254); everything
        else — including the geometry-only local costmap — stays identical.
        """
        lethal = renderer.candidate(self.phase5, target_cost=254)
        soft = copy.deepcopy(self.config)
        soft["global_costmap"]["global_costmap"]["ros__parameters"][
            "semantic_layer"]["target_cost"] = 254
        self.assertEqual(lethal, soft)
        with self.assertRaises(ValueError):
            renderer.candidate(self.phase5, target_cost=100)
        checked_in = yaml.safe_load(
            (ROOT / "helm/semantic-navigation/phase6-nav2-candidate-lethal.yaml").read_text())
        self.assertEqual(checked_in, lethal)


if __name__ == "__main__":
    unittest.main()
