"""Static gate checks for the opt-in Phase 6D D2 motion profile."""
import importlib.util
import ast
import json
import math
from pathlib import Path
from types import SimpleNamespace
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/semantic-navigation/render_phase6_demo_d2.py"
PARAMS = ROOT / "helm/semantic-navigation/phase6-demo-nav2-candidate.yaml"
BRIDGE_CONFIG = ROOT / "helm/semantic-navigation/phase6-demo-topic-bridges.yaml"
TRIAL_RUNNER = ROOT / "scripts/semantic-navigation/run_phase6_demo_d2_trial.py"

spec = importlib.util.spec_from_file_location("phase6_demo_d2", SCRIPT)
d2 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(d2)


class Phase6D2ProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = d2.render_documents()
        cls.by_name = {d.get("metadata", {}).get("name"): d for d in cls.docs}

    def test_d2_uses_global_lethal_costs_and_enabled_inflation_for_clearance(self):
        d2_params = yaml.safe_load(
            self.by_name["semantic-phase6-d2-nav2-config-on"]["data"][
                "phase6-demo-nav2-on.yaml"])
        self.assertTrue(d2_params["collision_monitor"]["ros__parameters"][
            "FootprintApproach"]["enabled"])
        self.assertEqual(d2_params["collision_monitor"]["ros__parameters"]
                         ["FootprintApproach"]["time_before_collision"], 0.5)
        global_params = d2_params["global_costmap"]["global_costmap"]["ros__parameters"]
        local_params = d2_params["local_costmap"]["local_costmap"]["ros__parameters"]
        self.assertTrue(global_params["semantic_layer"]["enabled"])
        self.assertEqual(global_params["semantic_layer"]["target_cost"], 254)
        self.assertFalse(local_params["semantic_layer"]["enabled"])
        for costmap in (global_params, local_params):
            self.assertEqual(costmap["robot_radius"], 0.246)
            self.assertTrue(costmap["inflation_layer"]["enabled"])
            self.assertEqual(costmap["inflation_layer"]["inflation_radius"], 0.60)
        follow_path = d2_params["controller_server"]["ros__parameters"]["FollowPath"]
        self.assertEqual(follow_path["desired_linear_vel"], 0.12)
        self.assertEqual(follow_path["lookahead_dist"], 0.5)
        self.assertEqual(follow_path["min_lookahead_dist"], 0.25)
        self.assertEqual(follow_path["regulated_linear_scaling_min_speed"], 0.06)
        self.assertEqual(follow_path["min_approach_linear_velocity"], 0.04)
        self.assertFalse(follow_path["stateful"])
        # In-place rotation deadlocks against the goal checker's stale-stamp
        # odom-frame target (documented in render_phase5_params.py).
        self.assertFalse(follow_path["use_rotate_to_heading"])

    def test_d2_smoother_limits_steering_speed_and_acceleration(self):
        params = yaml.safe_load(self.by_name["semantic-phase6-d2-nav2-config-on"][
            "data"]["phase6-demo-nav2-on.yaml"])
        smoother = params["velocity_smoother"]["ros__parameters"]
        self.assertEqual(smoother["max_velocity"], [0.12, 0.0, 0.45])
        self.assertEqual(smoother["min_velocity"], [-0.12, 0.0, -0.45])
        self.assertEqual(smoother["max_accel"], [0.3, 0.0, 0.4])
        self.assertEqual(smoother["max_decel"], [-0.5, 0.0, -0.6])

    def test_trial_steering_metrics_distinguish_turns_from_reversals(self):
        tree = ast.parse(TRIAL_RUNNER.read_text())
        trial = next(node for node in tree.body
                     if isinstance(node, ast.ClassDef) and node.name == "Trial")
        method = next(node for node in trial.body
                      if isinstance(node, ast.FunctionDef) and node.name == "steering_summary")
        namespace = {"math": math}
        exec(compile(ast.Module(body=[method], type_ignores=[]),
                     str(TRIAL_RUNNER), "exec"), namespace)
        summarize = namespace["steering_summary"]
        runner = SimpleNamespace(trajectory=[])
        self.assertEqual(summarize(runner)["turn_direction_changes"], 0)
        runner.trajectory = [{"yaw_rad": yaw, "w_radps": rate}
                             for yaw, rate in [(3.1, 0.2), (-3.1, 0.2), (-3.0, 0.2)]]
        self.assertEqual(summarize(runner)["turn_direction_changes"], 0)
        self.assertEqual(summarize(runner)["extra_yaw_travel_rad"], 0.0)
        runner.trajectory = [{"yaw_rad": yaw, "w_radps": rate}
                             for yaw, rate in [(0.0, 0.2), (0.2, 0.2),
                                               (0.2, 0.01), (0.0, -0.2)]]
        self.assertEqual(summarize(runner)["turn_direction_changes"], 1)
        self.assertEqual(summarize(runner)["extra_yaw_travel_rad"], 0.4)

    def test_simulator_accepts_only_exact_robot_cmd_vel_route(self):
        bridge_docs = list(yaml.safe_load_all(BRIDGE_CONFIG.read_text()))
        config = bridge_docs[0]["data"]
        import json
        sim = json.loads(config["sim-bridge.json5"])["plugins"]["ros2dds"]["allow"]
        self.assertEqual(sim["subscribers"], ["^/robot_1/cmd_vel$"])
        d1 = json.loads(config["sim-bridge-d1.json5"])["plugins"]["ros2dds"]["allow"]
        self.assertEqual(d1["subscribers"], [])
        sim_pod = self.by_name["semantic-phase6-simulator"]
        bridge = next(c for c in sim_pod["spec"]["containers"]
                      if c["name"] == "sim-zenoh-bridge")
        self.assertEqual(bridge["args"], ["-c", "/phase6-bridges/sim-bridge.json5"])

    def test_only_d2_mounts_the_opt_in_demo_mat_installer(self):
        simulator = self.by_name["semantic-phase6-simulator"]
        data = self.by_name["semantic-phase6-d2-nav2-config-on"]["data"]
        self.assertIn("phase6_demo: bool = False", data["install_phase1_camera.py"])
        container = next(c for c in simulator["spec"]["containers"]
                         if c["name"] == "simulator")
        self.assertIn({"name": "SEMANTIC_PHASE6_DEMO_TARGETS", "value": "1"},
                      container["env"])
        mount = next(m for m in container["volumeMounts"]
                     if m["name"] == "phase6-demo-world-config")
        self.assertEqual(mount["mountPath"],
                         "/opt/semantic-navigation/install_phase1_camera.py")
        volume = next(v for v in simulator["spec"]["volumes"]
                      if v["name"] == "phase6-demo-world-config")
        self.assertEqual(volume["configMap"]["name"],
                          "semantic-phase6-d2-nav2-config-on")

    def test_d2_embeds_private_supports_and_independent_read_only_truth(self):
        data = self.by_name["semantic-phase6-d2-nav2-config-on"]["data"]
        self.assertEqual(data["support_geometry.py"], d2.SUPPORT_SCRIPT.read_text())
        self.assertEqual(data["demo_ground_truth.py"], d2.TRUTH_SCRIPT.read_text())
        simulator = self.by_name["semantic-phase6-simulator"]
        telemetry = next(c for c in simulator["spec"]["containers"]
                         if c["name"] == "demo-ground-truth")
        self.assertIn("demo_ground_truth.py", telemetry["args"][0])
        self.assertNotIn("cmd_vel", data["demo_ground_truth.py"])
        self.assertNotIn("TransformBroadcaster", data["demo_ground_truth.py"])
        self.assertIn("/world/sim_world/dynamic_pose/info", data["demo_ground_truth.py"])

    def test_d2_mounts_auto_follow_startup_without_changing_the_simulator_image(self):
        data = self.by_name["semantic-phase6-d2-nav2-config-on"]["data"]
        self.assertEqual(data["entrypoint-phase1.sh"], d2.SIM_ENTRYPOINT.read_text())
        simulator = self.by_name["semantic-phase6-simulator"]
        container = next(c for c in simulator["spec"]["containers"] if c["name"] == "simulator")
        self.assertIn({"name": "phase6-demo-world-config",
                       "mountPath": "/entrypoint-semantic-navigation-phase1.sh",
                       "subPath": "entrypoint-phase1.sh", "readOnly": True}, container["volumeMounts"])
        volume = next(v for v in simulator["spec"]["volumes"] if v["name"] == "phase6-demo-world-config")
        self.assertIn({"key": "entrypoint-phase1.sh", "path": "entrypoint-phase1.sh"},
                      volume["configMap"]["items"])
        spec = importlib.util.spec_from_file_location("camera_follow_d1", d2.D1_RENDERER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        original = next(d for d in module.render_documents()
                        if d.get("metadata", {}).get("name") == "semantic-phase6-simulator")
        self.assertEqual(container["image"], next(c for c in original["spec"]["containers"]
                                                if c["name"] == "simulator")["image"])

    def test_truth_velocity_handles_wrapping_and_simulator_epoch_changes(self):
        tree = ast.parse(d2.TRUTH_SCRIPT.read_text())
        method = next(node for node in tree.body
                      if isinstance(node, ast.FunctionDef) and node.name == "planar_velocity")
        namespace = {"math": math}
        exec(compile(ast.Module(body=[method], type_ignores=[]),
                     str(d2.TRUTH_SCRIPT), "exec"), namespace)
        velocity = namespace["planar_velocity"]
        self.assertIsNone(velocity((100, 0, 0, 0), (99, 0, 0, 0)))
        self.assertIsNone(velocity((100, 0, 0, 0), (100, 0, 0, 0)))
        self.assertIsNone(velocity((0, 0, 0, 0), (1_000_000_000, 0, 0, 0)))
        vx, vy, rate = velocity((0, 0, 0, math.pi - .01),
                                (100_000_000, 0, 0, -math.pi + .01))
        self.assertEqual((vx, vy), (0.0, -0.0))
        self.assertAlmostEqual(rate, .2)

    def test_truth_uses_transport13_subscription_argument_order(self):
        tree = ast.parse(d2.TRUTH_SCRIPT.read_text())
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == "subscribe"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args[0].id, "Pose_V")
        self.assertEqual(calls[0].args[1].value, "/world/sim_world/dynamic_pose/info")
        self.assertEqual(calls[0].args[2].attr, "on_pose")

    def test_truth_replays_and_invalid_samples_do_not_renew_freshness(self):
        tree = ast.parse(TRIAL_RUNNER.read_text())
        trial = next(node for node in tree.body
                     if isinstance(node, ast.ClassDef) and node.name == "Trial")
        method = next(node for node in trial.body
                      if isinstance(node, ast.FunctionDef) and node.name == "truth_cb")
        clock = SimpleNamespace(now=1.0)
        namespace = {"math": math, "time": SimpleNamespace(monotonic=lambda: clock.now)}
        exec(compile(ast.Module(body=[method], type_ignores=[]),
                     str(TRIAL_RUNNER), "exec"), namespace)
        callback = namespace["truth_cb"]
        runner = SimpleNamespace(latest_truth=None, truth_received=None,
                                 max_truth_speed=0.0, max_truth_angular=0.0)

        def message(sec, x=0.0, frame="map", qw=1.0):
            return SimpleNamespace(
                header=SimpleNamespace(frame_id=frame, stamp=SimpleNamespace(sec=sec, nanosec=0)),
                pose=SimpleNamespace(pose=SimpleNamespace(
                    position=SimpleNamespace(x=x, y=0.0, z=0.0),
                    orientation=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=qw))),
                twist=SimpleNamespace(twist=SimpleNamespace(
                    linear=SimpleNamespace(x=0.0, y=0.0), angular=SimpleNamespace(z=0.0))))

        callback(runner, message(1))
        self.assertEqual(runner.truth_received, 1.0)
        clock.now = 2.0
        for msg in (message(1), message(0), message(2, x=math.nan),
                    message(2, frame="odom"), message(2, qw=0.0)):
            callback(runner, msg)
            self.assertEqual(runner.truth_received, 1.0)
        callback(runner, message(2))
        self.assertEqual(runner.truth_received, 2.0)

    def test_start_guard_rejects_stale_disagreeing_and_moving_body_poses(self):
        tree = ast.parse(TRIAL_RUNNER.read_text())
        trial = next(node for node in tree.body
                     if isinstance(node, ast.ClassDef) and node.name == "Trial")
        method = next(node for node in trial.body
                      if isinstance(node, ast.FunctionDef) and node.name == "verify_start_pose")
        namespace = {"math": math, "time": SimpleNamespace(monotonic=lambda: 10.0)}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(TRIAL_RUNNER), "exec"), namespace)
        verify = namespace["verify_start_pose"]

        def pose():
            return SimpleNamespace(
                pose=SimpleNamespace(pose=SimpleNamespace(position=SimpleNamespace(x=15.402, y=-31.594))),
                twist=SimpleNamespace(twist=SimpleNamespace(
                    linear=SimpleNamespace(x=0.0, y=0.0), angular=SimpleNamespace(z=0.0))))

        runner = SimpleNamespace(
            latest_truth=pose(), latest_odom=pose(), truth_received=10.0, odom_received=10.0,
            pose_alignment=lambda: (0.005, 0.002),
            args=SimpleNamespace(expected_start_x=15.402, expected_start_y=-31.594, start_tolerance=0.25))
        self.assertEqual(verify(runner), (15.402, -31.594, 0.005, 0.002))
        for field in ("truth_received", "odom_received"):
            setattr(runner, field, 9.0)
            with self.assertRaisesRegex(RuntimeError, "fresh wheel"):
                verify(runner)
            setattr(runner, field, 10.0)
        for disagreement in ((0.11, 0.0), (0.0, 0.09)):
            runner.pose_alignment = lambda: disagreement
            with self.assertRaisesRegex(RuntimeError, "disagrees"):
                verify(runner)
        runner.pose_alignment = lambda: (0.0, 0.0)
        runner.latest_truth.twist.twist.angular.z = 0.02
        with self.assertRaisesRegex(RuntimeError, "moving"):
            verify(runner)

    def test_nav2_motion_bridge_exports_only_cmd_vel_and_no_goal_actions(self):
        import json
        bridge_doc = list(yaml.safe_load_all(BRIDGE_CONFIG.read_text()))[0]
        cfg = json.loads(bridge_doc["data"]["nav2-motion-output-gated.json5"])
        allow = cfg["plugins"]["ros2dds"]["allow"]
        self.assertEqual(cfg["plugins"]["ros2dds"]["namespace"], "/robot_1")
        # The regex is anchored to the local topic name: the remote subscriber
        # announcement arrives as the zenoh key "robot_1/cmd_vel" (no leading
        # slash), which must NOT match — a publisher route created from a
        # remote announcement in the pinned bridge version never creates its
        # local DDS reader, so nav2's commands never leave the pod (observed
        # 2026-10-30: route shell, subscription count 0, zero robot motion).
        # With the anchored regex the route is only ever created from the
        # local /cmd_vel publisher (reader included); the sim-side bridge
        # still receives via zenoh key matching at the router.
        self.assertEqual(allow["publishers"], ["^/cmd_vel$"])
        self.assertEqual(allow["subscribers"], [])
        pod = self.by_name["semantic-phase6-nav2"]
        motion = next(c for c in pod["spec"]["containers"]
                      if c["name"] == "motion-output-bridge")
        self.assertEqual(motion["args"], ["-c", "/phase6-bridges/nav2-motion-output-gated.json5"])
        self.assertNotIn("navigate_to_pose", motion["args"])

    def test_route_keepalive_is_exact_and_uses_private_router(self):
        bridge_doc = list(yaml.safe_load_all(BRIDGE_CONFIG.read_text()))[0]
        bridges = {name: json.loads(value)
                   for name, value in bridge_doc["data"].items()
                   if name.endswith(".json5")}
        keepalive = bridges["nav2-cmd-vel-keepalive.json5"]
        ros2dds = keepalive["plugins"]["ros2dds"]
        self.assertNotIn("namespace", ros2dds)
        self.assertEqual(ros2dds["allow"]["publishers"], [])
        self.assertEqual(ros2dds["allow"]["subscribers"], ["robot_1/cmd_vel"])
        self.assertEqual(keepalive["connect"]["endpoints"],
                         ["tcp/semantic-phase6-router:17448"])
        nav2 = next(d for d in self.docs if d.get("metadata", {}).get("name") ==
                    "semantic-phase6-nav2")
        keepalive_container = next(c for c in nav2["spec"]["containers"]
                                   if c["name"] == "cmd-vel-route-keepalive")
        self.assertEqual(keepalive_container["args"],
                         ["-c", "/phase6-bridges/nav2-cmd-vel-keepalive.json5"])

    def test_d2_nav2_waits_for_simulator_inputs_before_lifecycle_start(self):
        entrypoint = self.by_name["semantic-phase6-d2-nav2-config-on"]["data"][
            "entrypoint_phase6_nav2.sh"]
        launch_at = entrypoint.index("exec ros2 launch")
        for topic in ("/clock", "/odom", "/scan_fixed", "/tf"):
            self.assertIn(f"wait_for_topic {topic}", entrypoint[:launch_at])

    def test_trial_runner_uses_sim_clock_compatible_best_effort_qos(self):
        source = TRIAL_RUNNER.read_text()
        self.assertIn("ReliabilityPolicy.BEST_EFFORT", source)
        self.assertIn("self.node.create_subscription(Clock, \"/clock\", self.clock_cb, clock_qos)",
                      source)

    def test_trial_runner_can_emit_compact_auditable_summary(self):
        source = TRIAL_RUNNER.read_text()
        self.assertIn('parser.add_argument("--summary-only"', source)
        self.assertIn('result.pop("trajectory_map_xyv", None)', source)
        self.assertIn('result["path_preflight"].pop("path_map_xy", None)', source)

    def test_d2_does_not_add_rmfor_nav2_action_or_simulator_topics(self):
        nav2 = self.by_name["semantic-phase6-nav2"]
        self.assertEqual(nav2["metadata"]["labels"][
            "semantic-navigation.robots-demo/phase"], "phase6d-d2-on")
        self.assertEqual(nav2["spec"]["nodeSelector"], {
            "kubernetes.io/hostname": d2.DEFAULT_NAV2_NODE})
        self.assertIn({"key": "g5-gpu", "operator": "Equal", "value": "true",
                       "effect": "NoSchedule"}, nav2["spec"]["tolerations"])
        bridge = next(c for c in nav2["spec"]["containers"]
                      if c["name"] == "motion-output-bridge")
        self.assertEqual(bridge["image"], d2.BRIDGE_IMAGE)
        self.assertEqual(self.by_name["semantic-phase6-d2-nav2-config-on"]["kind"], "ConfigMap")

    def test_preflight_renderer_uses_non_live_pod_names(self):
        docs = d2.render_documents(preflight=True)
        self.assertEqual([d["kind"] for d in docs], ["ConfigMap", "Pod", "Pod"])
        self.assertEqual(docs[0]["metadata"]["name"],
                         "semantic-phase6-d2-nav2-config-on-preflight")
        self.assertEqual([d["metadata"]["name"] for d in docs[1:]], [
            "semantic-phase6-simulator-d2-preflight",
            "semantic-phase6-nav2-d2-preflight",
        ])
        sim_volume = next(v for v in docs[1]["spec"]["volumes"]
                          if v["name"] == "phase6-demo-world-config")
        self.assertEqual(sim_volume["configMap"]["name"], docs[0]["metadata"]["name"])

    def test_candidate_deployment_renderer_contains_only_d2_config_and_two_pods(self):
        docs = d2.render_documents(candidate_pods=True)
        self.assertEqual([d["kind"] for d in docs], ["ConfigMap", "Pod", "Pod"])
        self.assertEqual([d["metadata"]["name"] for d in docs[1:]], [
            "semantic-phase6-simulator", "semantic-phase6-nav2"])

    def test_arm_profiles_are_static_and_differ_only_in_semantic_enable_flags(self):
        on = yaml.safe_load(d2.render_documents(semantic_arm="on")[0]["data"][
            "phase6-demo-nav2-on.yaml"])
        off = yaml.safe_load(d2.render_documents(semantic_arm="off")[0]["data"][
            "phase6-demo-nav2-off.yaml"])
        self.assertFalse(on["local_costmap"]["local_costmap"]["ros__parameters"]
                         ["semantic_layer"]["enabled"])
        self.assertTrue(on["global_costmap"]["global_costmap"]["ros__parameters"]
                        ["semantic_layer"]["enabled"])
        self.assertFalse(off["local_costmap"]["local_costmap"]["ros__parameters"]
                         ["semantic_layer"]["enabled"])
        self.assertFalse(off["global_costmap"]["global_costmap"]["ros__parameters"]
                         ["semantic_layer"]["enabled"])
        self.assertTrue(off["collision_monitor"]["ros__parameters"]
                        ["FootprintApproach"]["enabled"])
        for params in (on, off):
            glob = params["global_costmap"]["global_costmap"]["ros__parameters"]
            glob["semantic_layer"]["enabled"] = False
        self.assertEqual(on, off)

    def test_trial_runner_fails_closed_on_insufficient_hull_clearance(self):
        source = TRIAL_RUNNER.read_text()
        self.assertIn("polyline_enters_clearance_envelope(points)", source)
        self.assertIn("polyline_enters_clearance_envelope(segment)", source)
        self.assertIn("no goal was dispatched", source)
        self.assertIn('"minimum_hull_clearance_m"', source)
        self.assertIn('"mat_hull_overlap_detected"', source)

    def test_waypoint_preflight_and_navigation_share_ordered_poses(self):
        source = TRIAL_RUNNER.read_text()
        tree = ast.parse(source)
        trial = next(node for node in tree.body
                     if isinstance(node, ast.ClassDef) and node.name == "Trial")
        method = next(node for node in trial.body
                      if isinstance(node, ast.FunctionDef) and node.name == "goal_poses")

        def pose_stamped():
            return SimpleNamespace(
                header=SimpleNamespace(),
                pose=SimpleNamespace(position=SimpleNamespace(),
                                     orientation=SimpleNamespace()))

        namespace = {"PoseStamped": pose_stamped, "math": math}
        exec(compile(ast.Module(body=[method], type_ignores=[]),
                     str(TRIAL_RUNNER), "exec"), namespace)
        runner = SimpleNamespace(
            via=[[15.402, -29.0], [19.402, -29.0]],
            args=SimpleNamespace(goal_x=19.402, goal_y=-30.2, goal_yaw=0.0),
            node=SimpleNamespace(get_clock=lambda: SimpleNamespace(
                now=lambda: SimpleNamespace(to_msg=lambda: "stamp"))))
        poses = namespace["goal_poses"](runner)
        self.assertEqual([(p.pose.position.x, p.pose.position.y) for p in poses],
                         [(15.402, -29.0), (19.402, -29.0), (19.402, -30.2)])
        self.assertTrue(all(p.header.frame_id == "map" and
                             p.pose.orientation.w == 1.0 for p in poses))
        runner.args.goal_y = -31.594
        runner.args.goal_yaw = -math.pi / 2
        poses = namespace["goal_poses"](runner)
        self.assertEqual((poses[-1].pose.position.x, poses[-1].pose.position.y),
                         (19.402, -31.594))
        self.assertAlmostEqual(poses[-1].pose.orientation.z, -math.sqrt(0.5))
        self.assertAlmostEqual(poses[-1].pose.orientation.w, math.sqrt(0.5))
        self.assertTrue(all(p.pose.orientation.w == 1.0 for p in poses[:-1]))
        runner.via = []
        poses = namespace["goal_poses"](runner)
        self.assertEqual(len(poses), 1)
        self.assertAlmostEqual(poses[0].pose.orientation.z, -math.sqrt(0.5))
        self.assertIn("goal.goals = self.goal_poses()", source)
        self.assertIn("goal.poses = self.goal_poses()", source)
        self.assertIn('"via_map": self.via', source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
