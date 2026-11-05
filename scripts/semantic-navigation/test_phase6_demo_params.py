import copy
import importlib.util
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "render_phase6_demo_params", ROOT / "scripts/semantic-navigation/render_phase6_demo_params.py"
)
renderer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(renderer)


class Phase6DemoParamsTests(unittest.TestCase):
    def setUp(self):
        self.original = yaml.safe_load((ROOT / "config/nav2/hotel_nav2_params.yaml").read_text())
        self.before = copy.deepcopy(self.original)
        self.config = renderer.candidate(self.original)

    def test_original_parameters_are_not_mutated(self):
        self.assertEqual(self.original, self.before)

    def test_only_semantic_layer_additions_differ_from_baseline(self):
        expected = copy.deepcopy(self.before)
        for name in ("global_costmap", "local_costmap"):
            params = expected[name][name]["ros__parameters"]
            params["plugins"].insert(params["plugins"].index("inflation_layer"), "semantic_layer")
            params["semantic_layer"] = copy.deepcopy(renderer.SEMANTIC_CONFIG)
        self.assertEqual(self.config, expected)

    def test_semantic_layer_is_additive_and_precedes_inflation(self):
        for name in ("global_costmap", "local_costmap"):
            params = self.config[name][name]["ros__parameters"]
            plugins = params["plugins"]
            self.assertLess(plugins.index("semantic_layer"), plugins.index("inflation_layer"))
            self.assertEqual(params["semantic_layer"], renderer.SEMANTIC_CONFIG)
            self.assertEqual(params["semantic_layer"]["target_cost"], 200)
            self.assertLess(params["semantic_layer"]["target_cost"], 254)

    def test_safety_and_navigation_settings_remain_identical(self):
        for node in ("controller_server", "planner_server", "collision_monitor", "velocity_smoother"):
            self.assertEqual(self.config[node], self.before[node])

    def test_collision_and_geometric_costmap_layers_are_preserved(self):
        for name, geometry in (("global_costmap", "obstacle_layer"), ("local_costmap", "voxel_layer")):
            before = self.before[name][name]["ros__parameters"]
            after = self.config[name][name]["ros__parameters"]
            self.assertEqual(after[geometry], before[geometry])
            self.assertEqual(after["inflation_layer"], before["inflation_layer"])
            self.assertEqual(after["footprint"] if "footprint" in after else None,
                             before["footprint"] if "footprint" in before else None)

    def test_duplicate_layer_is_rejected_instead_of_silently_overwritten(self):
        with self.assertRaises(ValueError):
            renderer.candidate(self.config)


if __name__ == "__main__":
    unittest.main(verbosity=2)
