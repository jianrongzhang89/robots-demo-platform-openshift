import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from phase6_trial import completion_divergence, recycle_topology


class TopologyRecoveryTests(unittest.TestCase):
    def test_recycle_generates_pod_and_waits_for_router_before_starting_bridge(self):
        events = []

        def run(command, **kwargs):
            if "create" in command:
                events.append(json.loads(kwargs["input"])["kind"])
            return SimpleNamespace(stdout="Running true true", returncode=0)

        def router_ready(*args):
            events.append("router-ready")
            return True

        with patch("subprocess.run", side_effect=run), patch(
                "phase6_topology.wait_router_available", side_effect=router_ready):
            recycle_topology()
        self.assertEqual(events, ["Deployment", "router-ready", "Pod"])


def physical_row(sim_ns, x, y, wall_ns):
    return {"physical": {"sim_ns": sim_ns, "x": x, "y": y, "wall_ns": wall_ns,
                         "velocity_valid": True}}


class CompletionDivergenceTests(unittest.TestCase):
    """The October 28, 2026 fork decision: the goal checker fires on the
    AMCL belief pose, so every trial record must carry the belief/truth
    divergence at the arrival instant — a multi-metre-diverged "arrival"
    stays visible for the sign-off review instead of silently passing."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        runtime = self.dir / "runtime"
        runtime.mkdir(parents=True)
        # The belief sits on the goal at arrival; the physical robot is 2 m
        # away (the series-18 001-on shape, scaled down to a clean fixture).
        goal = {"x": 19.402, "y": -31.594}
        geometry = [
            {"stamp": 10_000_000_000, "map_x": 18.4, "map_y": -31.6,
             "planner_endpoint": dict(goal, frame="map", end_stamp=1, stamp=1, yaw=0.0)},
            {"stamp": 20_000_000_000, "map_x": 19.3, "map_y": -31.65,
             "planner_endpoint": dict(goal, frame="map", end_stamp=1, stamp=1, yaw=0.0)},
            # Arrival: belief 0.1 m from the goal, truth 2.0 m away.
            {"stamp": 30_000_000_000, "map_x": 19.302, "map_y": -31.594,
             "planner_endpoint": dict(goal, frame="map", end_stamp=1, stamp=1, yaw=0.0)},
            # Post-goal dwell drifts further (must not be reported as the
            # arrival measure).
            {"stamp": 40_000_000_000, "map_x": 19.302, "map_y": -31.594,
             "planner_endpoint": dict(goal, frame="map", end_stamp=1, stamp=1, yaw=0.0)},
        ]
        (runtime / "control-geometry.json").write_text(json.dumps(geometry))
        trace = [
            physical_row(10_000_000_000, 18.4, -31.6, 1_793_200_000_000_000_000),
            physical_row(20_000_000_000, 19.2, -31.7, 1_793_200_010_000_000_000),
            physical_row(30_000_000_000, 19.302, -33.594, 1_793_200_020_000_000_000),
            physical_row(40_000_000_000, 19.302, -33.794, 1_793_200_030_000_000_000),
        ]
        (runtime / "trace.jsonl").write_text(
            "\n".join(json.dumps(r) for r in trace) + "\n")
        self.runtime = runtime

    def physical(self):
        rows = []
        for line in (self.runtime / "trace.jsonl").read_text().splitlines():
            rows.append(json.loads(line)["physical"])
        return rows

    def write_goal_log(self, wall_seconds):
        (self.runtime / "controller_server.log").write_text(
            f"[INFO] [{wall_seconds}] [robot_1.controller_server]: Reached the goal!\n")

    def test_arrival_divergence_measured_at_goal_reached(self):
        # The controller fires "Reached the goal!" at wall 1793200015 — the
        # trace row at sim 30 s (belief 0.1 m out, truth 2.0 m out).
        self.write_goal_log("1793200015.500000000")
        result = completion_divergence(self.dir, self.physical())
        self.assertIsNotNone(result)
        arrival = result["at_arrival"]
        self.assertAlmostEqual(2.0, arrival["belief_truth_divergence_m"], places=2)
        self.assertAlmostEqual(0.1, arrival["belief_goal_distance_m"], places=2)
        self.assertAlmostEqual(2.0, arrival["physical_goal_distance_m"], places=2)
        # The final row (post-goal dwell) is reported separately, never as
        # the arrival measure.
        self.assertAlmostEqual(2.2, result["final"]["belief_truth_divergence_m"], places=2)

    def test_missing_goal_log_reports_final_only(self):
        result = completion_divergence(self.dir, self.physical())
        self.assertIsNotNone(result)
        self.assertNotIn("at_arrival", result)
        self.assertAlmostEqual(2.2, result["final"]["belief_truth_divergence_m"], places=2)

    def test_missing_geometry_returns_none(self):
        (self.runtime / "control-geometry.json").unlink()
        self.assertIsNone(completion_divergence(self.dir, self.physical()))

    def test_teardown_marker_rows_are_ignored(self):
        geometry = json.loads((self.runtime / "control-geometry.json").read_text())
        geometry.append({"rotating": False, "wall_ns": 1})
        (self.runtime / "control-geometry.json").write_text(json.dumps(geometry))
        result = completion_divergence(self.dir, self.physical())
        self.assertIsNotNone(result)
        # The marker row carries no map pose; the final measure still comes
        # from the last real belief row.
        self.assertAlmostEqual(2.2, result["final"]["belief_truth_divergence_m"], places=2)

    def test_runtime_partial_fallback(self):
        physical = self.physical()
        self.write_goal_log("1793200015.500000000")
        (self.dir / "runtime").rename(self.dir / "runtime-full")
        # With the primary runtime gone and no partial copy, there is no
        # geometry to measure.
        self.assertIsNone(completion_divergence(self.dir, physical))
        (self.dir / "runtime-partial").mkdir()
        for name in ("control-geometry.json", "controller_server.log"):
            (self.dir / f"runtime-full/{name}").rename(self.dir / f"runtime-partial/{name}")
        result = completion_divergence(self.dir, physical)
        self.assertAlmostEqual(2.0, result["at_arrival"]["belief_truth_divergence_m"], places=2)


if __name__ == "__main__":
    unittest.main()
