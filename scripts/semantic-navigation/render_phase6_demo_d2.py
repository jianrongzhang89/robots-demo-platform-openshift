#!/usr/bin/env python3
"""Render the D2-only profile with gated cmd_vel and an exact-key keepalive."""
from copy import deepcopy
import argparse
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[2]
D1_RENDERER = ROOT / "scripts/semantic-navigation/render_phase6_demo_d1.py"
PARAMS = ROOT / "helm/semantic-navigation/phase6-demo-nav2-candidate.yaml"
SCENE_SCRIPT = ROOT / "scripts/semantic-navigation/install_phase1_camera.py"
SUPPORT_SCRIPT = ROOT / "apps/semantic-safety/support_geometry.py"
TRUTH_SCRIPT = ROOT / "scripts/semantic-navigation/demo_ground_truth.py"
POLICY_SCRIPT = ROOT / "scripts/semantic-navigation/phase6_sam3_policy.py"
SIM_ENTRYPOINT = ROOT / "scripts/semantic-navigation/entrypoint-phase1.sh"
BRIDGE_IMAGE = (
    "eclipse/zenoh-bridge-ros2dds@sha256:"
    "38f162ae5236412f4f02e77927e22585356f7e706db39ec1c6194b9bd0d05b18"
)
DEFAULT_NAV2_NODE = "ip-10-0-39-214.ec2.internal"
DEFAULT_NAV2_IMAGE = (
    "image-registry.openshift-image-registry.svc:5000/semantic-navigation/semantic-nav2"
    "@sha256:5a951c79f08804ec7c19512feb0de77e9b9a015463da09d2c4f05bf97e983935"
)


def render_documents(preflight=False, candidate_pods=False, semantic_arm="on",
                     nav2_node=DEFAULT_NAV2_NODE, nav2_image=DEFAULT_NAV2_IMAGE):
    if semantic_arm not in ("on", "off"):
        raise ValueError("semantic_arm must be 'on' or 'off'")
    # Import the D1 renderer so the D2 profile always starts from its exact,
    # current static candidate. D2 adds its private scene/supports, observation
    # telemetry, controller tuning, and gated one-topic motion-output bridge.
    import importlib.util

    spec = importlib.util.spec_from_file_location("phase6_demo_d1", D1_RENDERER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    documents = module.render_documents()

    params = yaml.safe_load(PARAMS.read_text())
    params["collision_monitor"]["ros__parameters"]["FootprintApproach"]["enabled"] = True
    follow_path = params["controller_server"]["ros__parameters"]["FollowPath"]
    # Closer, smoother waypoint-guided candidate (October 30 user request).
    # The former 0.3 m lookahead / 0.8 rad/s steering produced visible
    # corrections in run12. Give pursuit a longer horizon and permit actual
    # slowing on curves instead of the plugin's 0.25 m/s minimum default.
    follow_path["desired_linear_vel"] = 0.12
    follow_path["lookahead_dist"] = 0.5
    follow_path["min_lookahead_dist"] = 0.25
    follow_path["regulated_linear_scaling_min_speed"] = 0.06
    follow_path["min_approach_linear_velocity"] = 0.04
    # Finish the requested goal orientation in place. Disabling this made the
    # direct-goal demo circle past its goal after successfully avoiding the mat.
    # The runner now uses simulation-time goals and verifies command transport.
    follow_path["stateful"] = True
    follow_path["use_rotate_to_heading"] = True
    # Limit steering in the existing smoother, not with an extra command
    # publisher. Collision Monitor remains the last stage before transport.
    smoother = params["velocity_smoother"]["ros__parameters"]
    smoother["max_velocity"] = [0.12, 0.0, 0.45]
    smoother["min_velocity"] = [-0.12, 0.0, -0.45]
    smoother["max_accel"] = [0.3, 0.0, 0.4]
    smoother["max_decel"] = [-0.5, 0.0, -0.6]
    for name in ("global_costmap", "local_costmap"):
        costmap = params[name][name]["ros__parameters"]
        costmap["robot_radius"] = 0.246
        costmap["inflation_layer"]["enabled"] = True
        # Keep a 0.60 m local gradient for the closer controller lane. The
        # semantic-on global map uses a 1.0 m gradient to preserve hull standoff
        # when the moving camera only observes part of the fixed mat.
        costmap["inflation_layer"]["inflation_radius"] = (
            1.0 if semantic_arm == "on" and name == "global_costmap" else 0.60)
        # Keep the observed standalone D2 behavior: semantics are global-only.
        # Local lethal cells made RPP abort in place at the mat in the live demo.
        costmap["semantic_layer"]["enabled"] = (
            semantic_arm == "on" and name == "global_costmap")
        costmap["semantic_layer"]["target_cost"] = 254
        if semantic_arm == "on" and name == "global_costmap":
            # This demo's mat is fixed. Keep observed world cells through a
            # complete run even when the camera turns away; capture freshness
            # and epoch/reset clearing remain independent of this memory.
            costmap["semantic_layer"]["observation_lifetime"] = 5.0
            costmap["semantic_layer"]["static_obstacle_memory"] = 300.0
    config = documents[0]
    config_name = f"semantic-phase6-d2-nav2-config-{semantic_arm}"
    config["metadata"]["name"] = config_name
    config["metadata"]["labels"]["semantic-navigation.robots-demo/phase"] = f"phase6d-d2-{semantic_arm}"
    config["data"].pop("phase6-demo-nav2-candidate.yaml", None)
    config["data"][f"phase6-demo-nav2-{semantic_arm}.yaml"] = yaml.safe_dump(
        params, sort_keys=False
    )
    # The standalone simulator image is pinned and shared with older D1
    # profiles. Mount the repository's installer only for this isolated D2
    # candidate so its staged mat geometry is independently versioned without
    # rebuilding or changing the image used by D1/canonical workloads.
    config["data"]["install_phase1_camera.py"] = SCENE_SCRIPT.read_text()
    config["data"]["support_geometry.py"] = SUPPORT_SCRIPT.read_text()
    config["data"]["demo_ground_truth.py"] = TRUTH_SCRIPT.read_text()
    config["data"]["phase6_sam3_policy.py"] = POLICY_SCRIPT.read_text()
    config["data"]["entrypoint-phase1.sh"] = SIM_ENTRYPOINT.read_text()
    entrypoint_key = "entrypoint_phase6_nav2.sh"
    entrypoint = config["data"][entrypoint_key]
    launch_marker = "exec ros2 launch /opt/ros2-demo/nav2/hotel_nav2_federated_launch.py"
    startup_wait = """wait_for_topic() {
  local topic="$1"
  for attempt in {1..30}; do
    if timeout 3 ros2 topic echo "$topic" --once >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "required D2 input did not become live: $topic" >&2
  return 1
}
# The simulator and its bridge start independently. Give the adapter sidecars
# time to establish live inputs before Nav2's lifecycle manager activates its
# costmaps (which require odom->base TF immediately).
wait_for_topic /clock
wait_for_topic /odom
wait_for_topic /scan_fixed
wait_for_topic /tf
sleep 2

"""
    if entrypoint.count(launch_marker) != 1:
        raise ValueError("unexpected D1 Nav2 entrypoint; cannot add D2 startup gate")
    config["data"][entrypoint_key] = entrypoint.replace(
        launch_marker, startup_wait + launch_marker, 1)

    sam3 = next(d for d in documents if d.get("metadata", {}).get("name") ==
                "semantic-phase6-sam3")
    inference = next(c for c in sam3["spec"]["containers"] if c["name"] == "sam3-inference")
    inference["command"] = ["/bin/bash", "-lc"]
    inference["args"] = [
        "mkdir -p \"$HOME\" \"$ROS_LOG_DIR\"; source /opt/ros/jazzy/setup.bash; "
        "exec /opt/sam3-venv/bin/python /phase6-policy/phase6_sam3_policy.py"]
    inference["volumeMounts"].append({
        "name": "phase6-policy", "mountPath": "/phase6-policy", "readOnly": True})
    sam3["spec"]["volumes"].append({
        "name": "phase6-policy", "configMap": {"name": config_name,
        "items": [{"key": "phase6_sam3_policy.py", "path": "phase6_sam3_policy.py"}]}})

    simulator = next(d for d in documents if d.get("metadata", {}).get("name") ==
                     "semantic-phase6-simulator")
    simulator["metadata"]["labels"]["semantic-navigation.robots-demo/phase"] = "phase6d-d2"
    simulator_container = next(c for c in simulator["spec"]["containers"]
                               if c["name"] == "simulator")
    simulator_container["env"].append({
        "name": "SEMANTIC_PHASE6_DEMO_TARGETS", "value": "1"})
    simulator_container["volumeMounts"].append({
        "name": "phase6-demo-world-config",
        "mountPath": "/opt/semantic-navigation/install_phase1_camera.py",
        "subPath": "install_phase1_camera.py",
        "readOnly": True,
    })
    simulator_container["volumeMounts"].append({
        "name": "phase6-demo-world-config",
        "mountPath": "/opt/semantic-navigation/support_geometry.py",
        "subPath": "support_geometry.py",
        "readOnly": True,
    })
    # Keep the pinned simulator image; version the standalone GUI startup
    # alongside its existing private installer/helpers instead of rebuilding
    # images shared by the older profiles or qualified fixture.
    simulator_container["volumeMounts"].append({
        "name": "phase6-demo-world-config",
        "mountPath": "/entrypoint-semantic-navigation-phase1.sh",
        "subPath": "entrypoint-phase1.sh",
        "readOnly": True,
    })
    simulator["spec"]["volumes"].append({
        "name": "phase6-demo-world-config",
        "configMap": {
            "name": config["metadata"]["name"],
            "items": [{"key": name, "path": name} for name in
                       ("install_phase1_camera.py", "support_geometry.py",
                        "demo_ground_truth.py", "entrypoint-phase1.sh")],
        },
    })
    simulator["spec"]["containers"].append({
        "name": "demo-ground-truth",
        "image": simulator_container["image"],
        "command": ["/bin/bash", "-lc"],
        "args": [
            "export HOME=/tmp/demo-truth-home ROS_LOG_DIR=/tmp/demo-truth-logs; "
            "mkdir -p \"$ROS_LOG_DIR\"; source /opt/ros/jazzy/setup.bash; "
            "exec python3 /phase6-demo-helpers/demo_ground_truth.py"],
        "env": deepcopy([e for e in simulator_container["env"] if e["name"] in
                         ("ROS_DOMAIN_ID", "ROS_DISTRO", "RMW_IMPLEMENTATION",
                          "CYCLONEDDS_URI", "GZ_PARTITION", "GZ_IP")]),
        "volumeMounts": [
            {"name": "bridge-config", "mountPath": "/phase6-bridges", "readOnly": True},
            {"name": "phase6-demo-world-config", "mountPath": "/phase6-demo-helpers",
             "readOnly": True}],
        "resources": {"requests": {"cpu": "100m", "memory": "128Mi"},
                      "limits": {"cpu": "500m", "memory": "512Mi"}},
    })
    sim_bridge = next(c for c in simulator["spec"]["containers"]
                      if c["name"] == "sim-zenoh-bridge")
    sim_bridge["args"] = ["-c", "/phase6-bridges/sim-bridge.json5"]

    nav2 = next(d for d in documents if d.get("metadata", {}).get("name") ==
                "semantic-phase6-nav2")
    nav2["metadata"]["labels"]["semantic-navigation.robots-demo/phase"] = f"phase6d-d2-{semantic_arm}"
    # Gazebo is CPU hungry on the source node. Keep Nav2 on a separate, lightly
    # loaded node so its 20 Hz controller/costmap loops are not starved by the
    # simulator. The selected demo node carries a g5-gpu taint but Nav2 is CPU-only.
    nav2["spec"]["nodeSelector"] = {"kubernetes.io/hostname": nav2_node}
    nav2["spec"].setdefault("tolerations", []).append({
        "key": "g5-gpu", "operator": "Equal", "value": "true",
        "effect": "NoSchedule",
    })
    nav2["spec"]["volumes"][0]["configMap"]["name"] = config["metadata"]["name"]
    main = next(c for c in nav2["spec"]["containers"] if c["name"] == "nav2")
    main["image"] = nav2_image
    for env in main["env"]:
        if env["name"] == "PHASE6_PARAMS":
            env["value"] = f"/phase6-nav2-config/phase6-demo-nav2-{semantic_arm}.yaml"
    nav2["spec"]["containers"].append({
        "name": "motion-output-bridge",
        "image": BRIDGE_IMAGE,
        "args": ["-c", "/phase6-bridges/nav2-motion-output-gated.json5"],
        "env": deepcopy(next(c for c in nav2["spec"]["containers"]
                             if c["name"] == "clock-bridge")["env"]),
        "volumeMounts": [{"name": "bridge-config", "mountPath": "/phase6-bridges",
                          "readOnly": True}],
        "resources": {"requests": {"cpu": "150m", "memory": "128Mi"},
                      "limits": {"cpu": "500m", "memory": "512Mi"}},
    })
    nav2["spec"]["containers"].append({
        "name": "cmd-vel-route-keepalive",
        "image": BRIDGE_IMAGE,
        "args": ["-c", "/phase6-bridges/nav2-cmd-vel-keepalive.json5"],
        "env": deepcopy(next(c for c in nav2["spec"]["containers"]
                             if c["name"] == "clock-bridge")["env"]),
        "volumeMounts": [{"name": "bridge-config", "mountPath": "/phase6-bridges",
                          "readOnly": True}],
        "resources": {"requests": {"cpu": "100m", "memory": "64Mi"},
                      "limits": {"cpu": "200m", "memory": "128Mi"}},
    })
    if preflight:
        config = deepcopy(config)
        config["metadata"]["name"] += "-preflight"
        selected = [config]
        for name in ("semantic-phase6-simulator", "semantic-phase6-nav2", "semantic-phase6-sam3"):
            pod = next(d for d in documents if d.get("metadata", {}).get("name") == name)
            pod = deepcopy(pod)
            pod["metadata"]["name"] += "-d2-preflight"
            if name == "semantic-phase6-nav2":
                pod["spec"]["volumes"][0]["configMap"]["name"] = config["metadata"]["name"]
            else:
                for volume in pod["spec"]["volumes"]:
                    if volume["name"] in ("phase6-demo-world-config", "phase6-policy"):
                        volume["configMap"]["name"] = config["metadata"]["name"]
            selected.append(pod)
        return selected
    if candidate_pods:
        return [config, simulator, nav2, sam3]
    return documents


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", action="store_true",
                        help="render uniquely named config/pods for API dry-run only")
    parser.add_argument("--candidate-pods", action="store_true",
                        help="render the D2 ConfigMap and simulator, Nav2, inference Pods")
    parser.add_argument("--semantic-arm", choices=("on", "off"), default="on",
                        help="bake the Nav2 semantic layer state at startup")
    parser.add_argument("--nav2-node", default=DEFAULT_NAV2_NODE,
                        help="hostname for the isolated CPU-only Nav2 candidate")
    parser.add_argument("--nav2-image", default=DEFAULT_NAV2_IMAGE,
                        help="pinned image containing the D2 semantic memory plugin")
    args = parser.parse_args()
    yaml.safe_dump_all(render_documents(preflight=args.preflight,
                                        candidate_pods=args.candidate_pods,
                                        semantic_arm=args.semantic_arm,
                                        nav2_node=args.nav2_node,
                                        nav2_image=args.nav2_image),
                       sys.stdout, sort_keys=False)
