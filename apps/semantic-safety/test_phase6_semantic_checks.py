import unittest

from phase6_semantic_checks import (CELL_RECTANGLE_MARGIN_M, SOFT_COST,
                                    cells_in_rectangle, clearance_bound_s,
                                    grid_cost_cells, grid_histogram,
                                    mat_removal_pose, normalize_grid,
                                    semantic_costs_at_target,
                                    smoke_registration_summary, soft_cost_only)

RECTANGLE = {"xmin": 16.95, "xmax": 17.85, "ymin": -31.92, "ymax": -31.27}


class FakeStamp:
    sec, nanosec = 5, 0


class FakePosition:
    def __init__(self, x, y):
        self.x, self.y = x, y


class FakeOrigin:
    def __init__(self, x, y):
        self.position = FakePosition(x, y)


class FakeMetadata:
    def __init__(self, origin_x, origin_y, resolution, size_x, size_y):
        self.update_time = FakeStamp()
        self.layer = "semantic_layer"
        self.resolution = resolution
        self.size_x = size_x
        self.size_y = size_y
        self.origin = FakeOrigin(origin_x, origin_y)


class FakeCostmapMessage:
    """Attribute shape of nav2_msgs/msg/Costmap without any ROS import."""

    def __init__(self, data, origin_x, origin_y, resolution, size_x, size_y):
        self.metadata = FakeMetadata(origin_x, origin_y, resolution, size_x, size_y)
        self.data = data


class GridTests(unittest.TestCase):
    def test_normalize_grid_flattens_a_costmap_message(self):
        message = FakeCostmapMessage([200, 255, 200], 16.0, -32.0, 0.05, 3, 1)
        grid = normalize_grid(message)
        self.assertEqual(5_000_000_000, grid["stamp_ns"])
        self.assertEqual("semantic_layer", grid["layer"])
        self.assertEqual(16.0, grid["origin_x"])
        self.assertEqual([200, 255, 200], grid["data"])

    def grid(self, values, origin=(16.0, -32.0), resolution=0.05, size_x=None):
        size_x = size_x or len(values)
        data = []
        for index, value in enumerate(values):
            data.append(value)
        return {"stamp_ns": 5_000_000_000, "layer": "semantic_layer",
                "origin_x": origin[0], "origin_y": origin[1],
                "resolution": resolution, "size_x": size_x,
                "size_y": max(1, len(values) // max(1, size_x)), "data": data}

    def test_cost_cells_are_world_centers(self):
        # origin is the corner of cell (0,0): first cell center is +res/2.
        grid = self.grid([SOFT_COST, 255, SOFT_COST], size_x=3)
        cells = grid_cost_cells(grid)
        self.assertEqual(2, len(cells))
        self.assertAlmostEqual(16.025, cells[0][0])
        self.assertAlmostEqual(-31.975, cells[0][1])
        self.assertAlmostEqual(16.125, cells[1][0])

    def test_histogram_and_soft_cost_only(self):
        self.assertTrue(soft_cost_only({0: 3, 200: 5, 255: 9}))
        self.assertFalse(soft_cost_only({200: 5, 253: 1}))
        self.assertFalse(soft_cost_only({200: 5, 254: 1}))
        self.assertFalse(soft_cost_only({100: 5}))
        self.assertEqual({200: 2, 255: 1}, grid_histogram(self.grid([200, 255, 200], size_x=3)))

    def test_cells_in_rectangle_with_margin(self):
        cells = [(17.0, -31.6), (17.9, -31.6), (16.5, -31.6)]
        inside = cells_in_rectangle(cells, RECTANGLE)
        # 17.9 is within the rectangle's +0.15 m projection margin; 16.5 is not.
        self.assertEqual([(17.0, -31.6), (17.9, -31.6)], inside)
        # Just outside the rectangle but inside the projection margin counts.
        edge = [(RECTANGLE["xmax"] + CELL_RECTANGLE_MARGIN_M - 0.01, -31.6)]
        self.assertEqual(edge, cells_in_rectangle(edge, RECTANGLE))

    def test_costs_at_target_passes_with_global_cells_and_full_containment(self):
        global_grid = self.grid([SOFT_COST, SOFT_COST, 255, 255], size_x=4)
        # The grid's origin places the soft cells at x=16.025/16.075, which
        # are outside the rectangle; shift the origin so they land inside.
        global_grid["origin_x"] = RECTANGLE["xmin"]
        global_grid["origin_y"] = RECTANGLE["ymin"]
        summary = semantic_costs_at_target(global_grid, None, RECTANGLE)
        self.assertTrue(summary["passed"], summary)
        self.assertEqual(2, summary["global_soft_cells"])
        self.assertEqual(2, summary["global_soft_cells_inside_target"])
        self.assertEqual(0, summary["local_soft_cells"])

    def test_costs_at_target_fails_on_outside_cells_or_local_layer(self):
        global_grid = self.grid([SOFT_COST, SOFT_COST], size_x=2)
        # Soft cells at x=16.025.. are outside the rectangle.
        self.assertFalse(semantic_costs_at_target(global_grid, None, RECTANGLE)["passed"])
        # Lethal value on the layer grid fails the soft-only contract.
        lethal = self.grid([SOFT_COST, 254], size_x=2)
        lethal["origin_x"] = RECTANGLE["xmin"]
        lethal["origin_y"] = RECTANGLE["ymin"]
        self.assertFalse(semantic_costs_at_target(lethal, None, RECTANGLE)["passed"])
        # A local grid carrying semantic cells fails: the Phase 6 candidate
        # must keep the local costmap geometry-only (user-approved 2026-10-28).
        local_layer = self.grid([255, SOFT_COST], size_x=2)
        contained = self.grid([SOFT_COST, 255], size_x=2)
        contained["origin_x"] = RECTANGLE["xmin"]
        contained["origin_y"] = RECTANGLE["ymin"]
        self.assertFalse(semantic_costs_at_target(contained, local_layer, RECTANGLE)["passed"])
        # A global map with no soft cells fails.
        empty_global = self.grid([255, 255], size_x=2)
        self.assertFalse(semantic_costs_at_target(empty_global, None, RECTANGLE)["passed"])

    def test_clearance_bound_sums_the_phase4_components(self):
        bound = clearance_bound_s(1.0, 0.1, 250.0, 0.2)
        self.assertAlmostEqual(1.0 + 0.2 + 0.25 + 0.2 + 0.15, bound)
        self.assertGreater(clearance_bound_s(1.0, 0.1, 250.0, 0.2),
                           clearance_bound_s(1.0, 0.1, 100.0, 0.2))


class SmokeSummaryTests(unittest.TestCase):
    def results(self, fractions):
        return [{"selected": 100, "inside_fraction": f, "moving": False}
                for f in fractions]

    def test_pooled_fraction_over_stationary_results(self):
        summary = smoke_registration_summary(self.results([1.0, 1.0, 0.99, 1.0, 1.0]))
        self.assertTrue(summary["passed"], summary)
        self.assertEqual(5, summary["results"])
        self.assertAlmostEqual(0.998, summary["pooled_inside_fraction"])

    def test_too_few_results_or_low_fraction_fails(self):
        self.assertFalse(smoke_registration_summary(self.results([1.0, 1.0]))["passed"])
        low = smoke_registration_summary(self.results([1.0] * 4 + [0.5]))
        self.assertFalse(low["passed"])

    def test_small_pixel_results_are_excluded(self):
        rows = self.results([1.0] * 5) + [{"selected": 10, "inside_fraction": 0.0,
                                           "moving": False}]
        self.assertTrue(smoke_registration_summary(rows)["passed"])


class RemovalPoseTests(unittest.TestCase):
    def test_removal_pose_is_behind_and_beside_the_robot(self):
        pose = mat_removal_pose(15.402, -31.594)
        self.assertLess(pose["x"], 15.402)
        self.assertLess(pose["y"], -31.594)
        self.assertGreater(abs(pose["y"] + 31.594), 4.0)

    def test_removal_pose_preserves_the_mat_surface_height(self):
        # The thin slab's model-origin z must be preserved exactly: a mat
        # lifted to even 0.2 m fails the layer's map-frame height filter
        # (Phase 6 smoke attempt 6).
        pose = mat_removal_pose(15.402, -31.594)
        self.assertAlmostEqual(0.005, pose["z"])


if __name__ == "__main__":
    unittest.main()
