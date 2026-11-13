#!/usr/bin/env python3
"""Temporarily attach RMF task dispatch to the isolated Phase 6 Nav2 demo.

The existing Nav2 pod is saved for restoration. Phase 8 uses the accepted
Phase 6 D2 renderer plus local RMF schedule/dispatcher and fleet-adapter
sidecars. The original pod is restored by ``down``.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import time
from pathlib import Path

import yaml
import render_phase6_demo_d2 as phase6


ROOT = Path(__file__).resolve().parents[2]
NAMESPACE = "semantic-navigation"
SOURCE_POD = "semantic-phase6-nav2"
SIMULATOR_POD = "semantic-phase6-simulator"
GZ_PARTITION = "semantic_navigation_phase6_demo"
DEMO_START = [15.402, -31.594, 0.0]
PHASE8_POD = "semantic-phase8-nav2"
CONFIG_MAP = "semantic-phase8-rmf-config"
BRIDGE_CONFIG_MAP = "semantic-phase8-bridge-config"
NAV2_CONFIG_MAP = "semantic-phase8-nav2-config"
PHASE8_DIR = ROOT / "scripts/semantic-navigation/phase8-demo"
ADAPTER = ROOT / "scripts/local_nav2_fleet_adapter.py"
ADAPTER_CONTRACT = ROOT / "scripts/local_nav2_fleet_adapter_contract.py"
TASK_CLIENT = ROOT / "demo/phase8_rmf_task.py"
TASK_MONITOR = ROOT / "demo/phase8_rmf_monitor.py"
PATH_PREFLIGHT = ROOT / "demo/phase8_nav2_preflight.py"
SEMANTIC_TRIAL = ROOT / "demo/phase8_semantic_trial.py"
SERVED_POLICY = PHASE8_DIR / "phase8_sam3_http_policy.py"
SERVING_GATE = json.loads((ROOT / "docs/validation/semantic-navigation/openshift-ai/S5/gate-result.json").read_text())
SERVING_RUNTIME = json.loads((ROOT / "docs/validation/semantic-navigation/openshift-ai/S2/gate-result.json").read_text())
SERVING_ADAPTER_IMAGE = SERVING_RUNTIME["runtime_image"]
SERVING_IDENTITY_VALUE = SERVING_GATE["deployment_identity"]
SERVING_ENDPOINT = "https://sam3-mat-v1-tls.semantic-model-serving.svc:8443"


def oc(*args: str, input_text: str | None = None, check: bool = True,
       timeout: int = 180) -> subprocess.CompletedProcess:
    result = subprocess.run(["oc", *args], input=input_text, text=True,
                            capture_output=True, check=False, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(
            f"oc {' '.join(args)} failed ({result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result


def clean_pod(obj: dict) -> dict:
    obj = json.loads(json.dumps(obj))
    obj.pop("status", None)
    metadata = obj["metadata"]
    for key in ("creationTimestamp", "deletionTimestamp", "deletionGracePeriodSeconds",
                "generation", "managedFields", "resourceVersion", "selfLink", "uid"):
        metadata.pop(key, None)
    metadata.pop("annotations", None)
    return obj


def get_live_pose(pod: str = SOURCE_POD) -> list[float]:
    command = ("source /opt/ros/jazzy/setup.bash; "
               "ros2 topic echo --once /amcl_pose --field pose.pose")
    result = oc("exec", "-n", NAMESPACE, pod, "-c", "nav2", "--",
                "bash", "-lc", command, timeout=30)
    pose = yaml.safe_load(result.stdout.split("---", 1)[0])
    position = pose["position"]
    orientation = pose["orientation"]
    yaw = 2.0 * math.atan2(float(orientation["z"]), float(orientation["w"]))
    return [float(position["x"]), float(position["y"]), yaw]


def get_ground_truth_pose(pod: str = SOURCE_POD) -> list[float]:
    command = ("source /opt/ros/jazzy/setup.bash; "
               "ros2 topic echo --once /demo/ground_truth --field pose.pose")
    result = oc("exec", "-n", NAMESPACE, pod, "-c", "nav2", "--",
                "bash", "-lc", command, timeout=30)
    pose = yaml.safe_load(result.stdout.split("---", 1)[0])
    position = pose["position"]
    orientation = pose["orientation"]
    yaw = 2.0 * math.atan2(float(orientation["z"]), float(orientation["w"]))
    return [float(position["x"]), float(position["y"]), yaw]


def teleport_demo_robot() -> None:
    request = (
        "export GZ_PARTITION=" + GZ_PARTITION + "; "
        "gz service -s /world/sim_world/set_pose "
        "--reqtype gz.msgs.Pose --reptype gz.msgs.Boolean --timeout 3000 "
        "--req 'name: \"robot_1\" position: {x: 15.402, y: -31.594, z: 0.01} "
        "orientation: {w: 1.0}'"
    )
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        result = oc("exec", "-n", NAMESPACE, SIMULATOR_POD, "-c", "simulator",
                    "--", "bash", "-lc", request, check=False, timeout=10)
        if result.returncode == 0 and "data: true" in result.stdout:
            return
        time.sleep(2)
    raise RuntimeError("Gazebo did not teleport robot_1 to the Phase 8 start pose")


def restart_pod(saved_pod: dict, timeout: str = "12m") -> None:
    name = saved_pod["metadata"]["name"]
    oc("delete", "pod", name, "-n", NAMESPACE, "--wait=true", "--timeout=120s")
    oc("create", "-f", "-", input_text=json.dumps(clean_pod(saved_pod)))
    wait_pod(name, "Ready", timeout)


def reset_demo_scene(nav_pod: str = SOURCE_POD) -> None:
    teleport_demo_robot()
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        probe = oc("exec", "-n", NAMESPACE, nav_pod, "-c", "nav2", "--",
                   "bash", "-lc",
                   "source /opt/ros/jazzy/setup.bash; ros2 topic info /initialpose",
                   check=False, timeout=10)
        match = re.search(r"Subscription count: (\d+)", probe.stdout)
        minimum_subscribers = 2 if nav_pod == PHASE8_POD else 1
        if match and int(match.group(1)) >= minimum_subscribers:
            break
        time.sleep(2)
    else:
        raise RuntimeError(f"Nav2 did not subscribe to /initialpose in {nav_pod}")

    oc("exec", "-n", NAMESPACE, nav_pod, "-c", "nav2", "--", "bash", "-lc",
       "source /opt/ros/jazzy/setup.bash; "
       "ros2 topic pub --once /initialpose "
       "geometry_msgs/msg/PoseWithCovarianceStamped "
       "\"{header: {frame_id: map}, pose: {pose: {position: {x: 15.402, y: -31.594}, "
       "orientation: {w: 1.0}}, covariance: [0.04,0,0,0,0,0,"
       "0,0.04,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,"
       "0,0,0,0,0,0,0,0,0,0,0,0.02]}}\"",
       timeout=30)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        pose = get_live_pose(nav_pod)
        if math.hypot(pose[0] - 15.402, pose[1] + 31.594) < 0.20 and abs(pose[2]) < 0.20:
            break
        time.sleep(2)
    else:
        raise RuntimeError(f"AMCL did not converge to Phase 8 start pose: {pose}")

    truth = get_ground_truth_pose(nav_pod)
    if (math.hypot(pose[0] - truth[0], pose[1] - truth[1]) > 0.25 or
            abs(pose[2] - truth[2]) > 0.20):
        raise RuntimeError(
            f"AMCL and simulator ground truth disagree at demo start: {pose} vs {truth}")

    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        probe = oc("exec", "-n", NAMESPACE, nav_pod, "-c", "nav2", "--",
                   "bash", "-lc",
                   "source /opt/ros/jazzy/setup.bash; "
                   "timeout 6 ros2 topic echo --once /robot_1/semantic/points --field width",
                   check=False, timeout=10)
        try:
            width = int(probe.stdout.strip().splitlines()[0])
        except (IndexError, ValueError):
            width = 0
        if probe.returncode == 0 and width > 0:
            return
        time.sleep(3)
    raise RuntimeError("fresh non-empty red-mat semantic points did not reach Nav2")


def generated_graph(start: list[float]) -> str:
    graph = yaml.safe_load((PHASE8_DIR / "nav_graph.yaml").read_text())
    graph["levels"]["L1"]["vertices"][0][:2] = start[:2]
    return yaml.safe_dump(graph, sort_keys=False)


def accepted_nav2_config() -> dict:
    config = phase6.render_documents(candidate_pods=True, semantic_arm="on")[0]
    config["metadata"]["name"] = NAV2_CONFIG_MAP
    return config


def apply_config_map(evidence_dir: Path, graph: str) -> None:
    graph_path = evidence_dir / "nav_graph.yaml"
    graph_path.write_text(graph)
    identity_path = evidence_dir / "serving-identity.json"
    identity_path.write_text(json.dumps(SERVING_IDENTITY_VALUE, indent=2))
    command = ["oc", "create", "configmap", CONFIG_MAP, "-n", NAMESPACE,
               f"--from-file=local_nav2_fleet_adapter.py={ADAPTER}",
               f"--from-file=local_nav2_fleet_adapter_contract.py={ADAPTER_CONTRACT}",
               f"--from-file=phase8_rmf_task.py={TASK_CLIENT}",
               f"--from-file=phase8_rmf_monitor.py={TASK_MONITOR}",
               f"--from-file=phase8_nav2_preflight.py={PATH_PREFLIGHT}",
               f"--from-file=phase8_semantic_trial.py={SEMANTIC_TRIAL}",
               f"--from-file=phase8_sam3_http_policy.py={SERVED_POLICY}",
               f"--from-file=identity.json={identity_path}",
               f"--from-file=run_phase6_demo_d2_trial.py={ROOT / 'scripts/semantic-navigation/run_phase6_demo_d2_trial.py'}",
               f"--from-file=demo_target_geometry.py={ROOT / 'scripts/semantic-navigation/demo_target_geometry.py'}",
               f"--from-file=nav_graph.yaml={graph_path}",
               f"--from-file=fleet_config.yaml={PHASE8_DIR / 'fleet_config.yaml'}",
               f"--from-file=rmf-core.sh={PHASE8_DIR / 'rmf-core.sh'}",
               "--dry-run=client", "-o", "json"]
    manifest = subprocess.run(command, text=True, capture_output=True, check=True).stdout
    oc("apply", "-f", "-", input_text=manifest)


def apply_bridge_config_map(evidence_dir: Path, source_pod: dict) -> None:
    """Keep Phase 8's demonstrated velocity-route fix in a private clone."""
    bridge_volume = next(volume for volume in source_pod["spec"]["volumes"]
                         if volume["name"] == "bridge-config")
    source_name = bridge_volume["configMap"]["name"]
    source = json.loads(oc("get", "configmap", source_name, "-n", NAMESPACE,
                           "-o", "json").stdout)
    (evidence_dir / "phase6-bridge-config-restore.json").write_text(
        json.dumps(source, indent=2))
    clone = json.loads(json.dumps(source))
    clone["metadata"]["name"] = BRIDGE_CONFIG_MAP
    clone["metadata"].pop("resourceVersion", None)
    clone["metadata"].pop("uid", None)
    clone["metadata"].pop("creationTimestamp", None)
    clone["metadata"].pop("managedFields", None)
    bridge = json.loads(clone["data"]["nav2-motion-output-gated.json5"])
    bridge["plugins"]["ros2dds"]["allow"]["subscribers"] = ["^robot_1/cmd_vel$"]
    clone["data"]["nav2-motion-output-gated.json5"] = json.dumps(bridge, indent=2)
    oc("apply", "-f", "-", input_text=json.dumps(clone))
    (evidence_dir / "phase8-bridge-config.json").write_text(
        json.dumps(clone, indent=2))


def phase8_pod(saved: dict, pose: list[float]) -> dict:
    # Inherit the versioned, accepted profile rather than an arbitrary live
    # pod's possibly stale image, parameters, or TF implementation.
    pod = phase6.render_documents(candidate_pods=True, semantic_arm="on")[2]
    metadata = pod["metadata"]
    metadata["name"] = PHASE8_POD
    metadata["labels"] = dict(metadata.get("labels") or {})
    metadata["labels"].update({
        "app": PHASE8_POD,
        "semantic-navigation.robots-demo/phase": "phase8-topology",
    })
    pod = clean_pod(pod)
    spec = pod["spec"]
    # The source pod's nodeName is assigned by OpenShift at runtime. Reusing
    # it can strand the larger demo pod on a node without enough free CPU.
    spec.pop("nodeName", None)
    # Phase 6 also carries a hostname nodeSelector. The demo sidecars increase
    # CPU requests, so retain its tolerations but let the scheduler choose any
    # eligible node with room for the complete pod.
    spec.pop("nodeSelector", None)
    if saved.get("spec", {}).get("nodeName"):
        spec["affinity"] = {"nodeAffinity": {"preferredDuringSchedulingIgnoredDuringExecution": [{
            "weight": 100, "preference": {"matchExpressions": [{
                "key": "kubernetes.io/hostname", "operator": "In",
                "values": [saved["spec"]["nodeName"]]}]}}]}}
    image = next(c["image"] for c in spec["containers"] if c["name"] == "nav2")
    env_base = [
        {"name": "ROS_DISTRO", "value": "jazzy"},
        {"name": "ROS_DOMAIN_ID", "value": "87"},
        {"name": "RMW_IMPLEMENTATION", "value": "rmw_cyclonedds_cpp"},
        {"name": "CYCLONEDDS_URI", "value": "file:///phase6-nav2-config/cyclonedds.xml"},
    ]
    config_mount = {"name": "phase8-config", "mountPath": "/phase8", "readOnly": True}
    next(c for c in spec["containers"] if c["name"] == "nav2")["volumeMounts"].append(config_mount)
    nav2_mount = {"name": "nav2-config", "mountPath": "/phase6-nav2-config", "readOnly": True}
    spec["containers"].extend([
        {
            "name": "rmf-core",
            "image": image,
            "imagePullPolicy": "IfNotPresent",
            "command": ["/bin/bash", "/phase8/rmf-core.sh"],
            "env": env_base + [
                {"name": "HOME", "value": "/tmp/phase8-rmf-core-home"},
                {"name": "ROS_LOG_DIR", "value": "/tmp/phase8-rmf-core-logs"},
            ],
            "volumeMounts": [config_mount, nav2_mount],
            "resources": {"requests": {"cpu": "500m", "memory": "512Mi"},
                          "limits": {"cpu": "1", "memory": "1Gi"}},
        },
        {
            "name": "rmf-fleet-adapter",
            "image": image,
            "imagePullPolicy": "IfNotPresent",
            "command": ["/bin/bash", "-lc"],
            "args": [
                "source /opt/ros/jazzy/setup.bash; "
                "source /opt/rmf_demos_ws/install/setup.bash; "
                "exec python3 -u /phase8/local_nav2_fleet_adapter.py "
                "--fleet-config /phase8/fleet_config.yaml "
                "--nav-graph /phase8/nav_graph.yaml "
                "--robot-name robot_1 --initial-map L1 "
                f"--initial-x {pose[0]:.6f} --initial-y {pose[1]:.6f} "
                f"--initial-yaw {pose[2]:.6f} --ros-namespace ''"
            ],
            "env": env_base + [
                {"name": "HOME", "value": "/tmp/phase8-adapter-home"},
                {"name": "ROS_LOG_DIR", "value": "/tmp/phase8-adapter-logs"},
            ],
            "volumeMounts": [config_mount, nav2_mount],
            "resources": {"requests": {"cpu": "500m", "memory": "512Mi"},
                          "limits": {"cpu": "1", "memory": "1Gi"}},
        },
    ])
    spec["volumes"].append({"name": "phase8-config", "configMap": {"name": CONFIG_MAP}})
    next(volume for volume in spec["volumes"] if volume["name"] == "nav2-config")[
        "configMap"]["name"] = NAV2_CONFIG_MAP
    next(volume for volume in spec["volumes"] if volume["name"] == "bridge-config")[
        "configMap"]["name"] = BRIDGE_CONFIG_MAP
    return pod


def phase8_serving_pod(saved: dict) -> dict:
    """Run the qualified HTTP ROS client on the existing camera Zenoh domain."""
    pod = clean_pod(saved)
    pod["metadata"]["name"] = "semantic-phase8-sam3-adapter"
    pod["metadata"]["labels"] = dict(pod["metadata"].get("labels") or {})
    pod["metadata"]["labels"].update({
        "app": "semantic-phase8-sam3-adapter",
        "semantic-navigation.robots-demo/phase": "phase8-topology",
        "semantic-serving-client": "sam3-mat-v1",
    })
    container = next(c for c in pod["spec"]["containers"] if c["name"] == "sam3-inference")
    container["image"] = SERVING_ADAPTER_IMAGE
    container["imagePullPolicy"] = "IfNotPresent"
    container["command"] = ["/bin/bash", "-lc"]
    container["args"] = [
        "source /opt/ros/jazzy/setup.bash; "
        "exec python3 /phase8/phase8_sam3_http_policy.py "
        "--ros-args -p backend:=http -p robot_id:=robot_1 "
        "-p stream_id:=camera/color -p input_prefix:=/robot_1/camera "
        "-p output_prefix:=/robot_1/semantic"
    ]
    env = {entry["name"]: entry for entry in container.get("env", [])}
    for name, value in {
        "ROS_DOMAIN_ID": "82",
        "CYCLONEDDS_URI": "file:///phase6-bridges/cyclonedds.xml",
        "SEMANTIC_BACKEND": "http",
        "SEMANTIC_ENDPOINT": SERVING_ENDPOINT,
        "SEMANTIC_TLS_CA": "/phase8-serving-tls/ca.crt",
        "SEMANTIC_TLS_CERT": "/phase8-serving-tls/tls.crt",
        "SEMANTIC_TLS_KEY": "/phase8-serving-tls/tls.key",
        "SEMANTIC_DEPLOYMENT_IDENTITY": "/phase8/identity.json",
        "SEMANTIC_REQUIRE_CAPTURE_TRACE": "1",
        "SEMANTIC_CLOCK_UNCERTAINTY_MS": "2",
        "SEMANTIC_MAX_WORK_WAIT_MS": "40",
        "SEMANTIC_STATUS_FILE": "/tmp/semantic-status.json",
        "HOME": "/tmp/phase8-sam3-home",
        "ROS_LOG_DIR": "/tmp/phase8-sam3-logs",
    }.items():
        env[name] = {"name": name, "value": value}
    container["env"] = list(env.values())
    container["resources"] = {"requests": {"cpu": "1", "memory": "1Gi"},
                               "limits": {"cpu": "2", "memory": "2Gi"}}
    container["securityContext"] = {
        "allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
        "capabilities": {"drop": ["ALL"]}, "seccompProfile": {"type": "RuntimeDefault"}}
    container["volumeMounts"] = [
        mount for mount in container.get("volumeMounts", [])
        if mount["name"] not in ("model", "phase6-policy")
    ] + [
        {"name": "phase8-config", "mountPath": "/phase8", "readOnly": True},
        {"name": "phase8-serving-tls", "mountPath": "/phase8-serving-tls", "readOnly": True},
        {"name": "phase8-serving-tmp", "mountPath": "/tmp"},
    ]
    container["readinessProbe"] = {"exec": {"command": ["python3", "-c",
        "import json,time; s=json.load(open('/tmp/semantic-status.json')); "
        "assert s['ready'] and s['backend']=='http' and "
        "s['deployment_identity']==json.load(open('/phase8/identity.json')) and "
        "0 <= time.time_ns()-s['status_wall_ns'] < 500000000"]},
        "periodSeconds": 1, "timeoutSeconds": 1, "failureThreshold": 1}
    pod["spec"]["volumes"] = [v for v in pod["spec"].get("volumes", [])
                               if v["name"] not in ("model", "phase6-policy")]
    pod["spec"]["volumes"].extend([
        {"name": "phase8-config", "configMap": {"name": CONFIG_MAP}},
        {"name": "phase8-serving-tls", "secret": {
            "secretName": "sam3-replay-tls", "defaultMode": 288}},
        {"name": "phase8-serving-tmp", "emptyDir": {"sizeLimit": "256Mi"}},
    ])
    return pod


def wait_pod(name: str, condition: str, timeout: str = "12m") -> None:
    oc("wait", "-n", NAMESPACE, f"--for=condition={condition}",
       f"pod/{name}", f"--timeout={timeout}", timeout=timeout.rstrip("m") and 760)


def recover_motion_bridge(evidence_dir: Path) -> None:
    """Recreate the pinned bridge after the live Nav2 publisher is available."""
    pod = json.loads(oc("get", "pod", PHASE8_POD, "-n", NAMESPACE, "-o", "json").stdout)
    name = "motion-output-bridge"
    before = next(c for c in pod["status"]["containerStatuses"] if c["name"] == name)
    image = next(c["image"] for c in pod["spec"]["containers"] if c["name"] == name)
    base, digest = image.split("@", 1)
    patched_image = base + ":latest@" + digest
    oc("patch", "pod", PHASE8_POD, "-n", NAMESPACE, "--type=strategic", "-p",
       json.dumps({"spec": {"containers": [{"name": name, "image": patched_image}]}}))
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        live = json.loads(oc("get", "pod", PHASE8_POD, "-n", NAMESPACE, "-o", "json").stdout)
        after = next(c for c in live["status"]["containerStatuses"] if c["name"] == name)
        if after.get("ready") and after.get("containerID") != before.get("containerID"):
            (evidence_dir / "motion-bridge-recovery.json").write_text(json.dumps({
                "before": before, "after": after, "image_digest_unchanged": digest}, indent=2))
            return
        time.sleep(1)
    raise TimeoutError("motion-output bridge did not restart")


def up(args) -> None:
    args.evidence_dir.mkdir(parents=True, exist_ok=False)
    live = json.loads(oc("get", "pod", SOURCE_POD, "-n", NAMESPACE, "-o", "json").stdout)
    simulator_live = json.loads(oc("get", "pod", SIMULATOR_POD, "-n", NAMESPACE,
                                   "-o", "json").stdout)
    saved = clean_pod(live)
    (args.evidence_dir / "phase6-nav2-restore.json").write_text(json.dumps(saved, indent=2))
    (args.evidence_dir / "phase6-nav2-before.json").write_text(json.dumps(live, indent=2))
    (args.evidence_dir / "phase6-simulator-restore.json").write_text(
        json.dumps(clean_pod(simulator_live), indent=2))
    (args.evidence_dir / "phase6-simulator-before.json").write_text(
        json.dumps(simulator_live, indent=2))
    try:
        inference = json.loads(oc("get", "pod", "semantic-phase6-sam3", "-n", NAMESPACE,
                                  "-o", "json").stdout)
        (args.evidence_dir / "phase6-inference-before.json").write_text(json.dumps(inference, indent=2))
        (args.evidence_dir / "openshift-ai-serving-identity.json").write_text(
            json.dumps(SERVING_IDENTITY_VALUE, indent=2))
        config = accepted_nav2_config()
        oc("apply", "-f", "-", input_text=json.dumps(config))
        (args.evidence_dir / "accepted-nav2-config.json").write_text(json.dumps(config, indent=2))
        apply_config_map(args.evidence_dir, generated_graph(DEMO_START))
        apply_bridge_config_map(args.evidence_dir, saved)
        oc("delete", "pod", "semantic-phase6-sam3", "-n", NAMESPACE,
           "--wait=true", "--timeout=120s")
        oc("delete", "pod", SOURCE_POD, "-n", NAMESPACE, "--wait=true", "--timeout=120s")
        restart_pod(simulator_live)
        # A fresh simulator resets wheel odometry as well as world pose. Keep
        # Phase 6's fixed map->odom transform; do not teleport/rebase a live map
        # while it retains static semantic cells.
        oc("exec", "-n", NAMESPACE, SIMULATOR_POD, "-c", "simulator", "--",
           "bash", "-lc", "source /opt/ros/jazzy/setup.bash; "
           "timeout 20 ros2 topic echo --once /clock rosgraph_msgs/msg/Clock", timeout=25)
        pose = list(DEMO_START)
        (args.evidence_dir / "phase8-initial-pose.json").write_text(json.dumps(pose, indent=2))
        oc("create", "-f", "-", input_text=json.dumps(phase8_pod(saved, pose)))
        wait_pod(PHASE8_POD, "Ready")
        serving_pod = phase8_serving_pod(inference)
        (args.evidence_dir / "phase8-serving-adapter-pod.json").write_text(
            json.dumps(serving_pod, indent=2))
        oc("create", "-f", "-", input_text=json.dumps(serving_pod))
        wait_pod("semantic-phase8-sam3-adapter", "Ready")
        (args.evidence_dir / "phase8-serving-adapter-status.json").write_text(
            oc("exec", "-n", NAMESPACE, "semantic-phase8-sam3-adapter", "-c",
               "sam3-inference", "--", "cat", "/tmp/semantic-status.json").stdout)
        # Run the exact Phase 6 profile/localization/semantic/clearance gates
        # before admitting an RMF task. This command does not send a task.
        probe_command = ("exec", "-n", NAMESPACE, PHASE8_POD, "-c", "nav2", "--",
                         "bash", "-lc", "source /opt/ros/jazzy/setup.bash; "
                         "source /opt/rmf_demos_ws/install/setup.bash; "
                         "python3 /phase8/phase8_semantic_trial.py --trial phase8-preflight --preflight-only")
        probe = oc(*probe_command, timeout=150, check=False)
        if probe.returncode and "motion bridge DDS reader missing" in probe.stderr:
            (args.evidence_dir / "preflight-before-bridge-recovery.stderr").write_text(probe.stderr)
            recover_motion_bridge(args.evidence_dir)
            probe = oc(*probe_command, timeout=150, check=False)
        if probe.returncode:
            raise RuntimeError(probe.stderr or probe.stdout)
        (args.evidence_dir / "nav2-semantic-path-preflight.json").write_text(probe.stdout)
        preflight = json.loads(probe.stdout)
        if not preflight.get("semantic_arm_state_confirmed") or preflight.get("motion_dispatched") is not False:
            raise RuntimeError("live Phase 8 Nav2 semantic path preflight failed")
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            log = oc("logs", "-n", NAMESPACE, PHASE8_POD, "-c", "rmf-fleet-adapter",
                     "--tail=100", check=False, timeout=15)
            if "RMF backend ready" in log.stdout and "RMF robot registered" in log.stdout:
                break
            time.sleep(3)
        else:
            raise RuntimeError("RMF adapter did not register after Nav2 readiness checks")
        (args.evidence_dir / "phase8-fleet-adapter-startup.log").write_text(log.stdout)
        print(json.dumps({"phase8_pod": PHASE8_POD, "initial_pose": pose,
                          "evidence_dir": str(args.evidence_dir)}, indent=2))
    except Exception as exc:
        (args.evidence_dir / "startup-error.txt").write_text(str(exc))
        print(f"Phase 8 startup failed: {exc}", flush=True)
        for container in ("nav2", "rmf-core", "rmf-fleet-adapter"):
            log = oc("logs", "-n", NAMESPACE, PHASE8_POD, "-c", container,
                     "--tail=200", check=False, timeout=20)
            (args.evidence_dir / f"startup-failed-{container}.log").write_text(log.stdout + log.stderr)
        adapter_log = oc("logs", "-n", NAMESPACE, "semantic-phase8-sam3-adapter",
                         "-c", "sam3-inference", "--tail=200", check=False, timeout=20)
        (args.evidence_dir / "startup-failed-sam3-serving-adapter.log").write_text(
            adapter_log.stdout + adapter_log.stderr)
        restore(args.evidence_dir)
        raise


def restore(evidence_dir: Path) -> None:
    restore_path = evidence_dir / "phase6-nav2-restore.json"
    saved = json.loads(restore_path.read_text())
    oc("delete", "pod", PHASE8_POD, "-n", NAMESPACE, "--ignore-not-found=true",
       "--wait=true", "--timeout=120s", check=False)
    oc("delete", "pod", "semantic-phase8-sam3-adapter", "-n", NAMESPACE,
       "--ignore-not-found=true", "--wait=true", "--timeout=120s", check=False)
    oc("delete", "configmap", CONFIG_MAP, "-n", NAMESPACE,
       "--ignore-not-found=true", check=False)
    oc("delete", "configmap", BRIDGE_CONFIG_MAP, "-n", NAMESPACE,
       "--ignore-not-found=true", check=False)
    oc("delete", "configmap", NAV2_CONFIG_MAP, "-n", NAMESPACE,
       "--ignore-not-found=true", check=False)
    current = oc("get", "pod", SOURCE_POD, "-n", NAMESPACE, "-o", "json", check=False)
    if current.returncode == 0:
        oc("delete", "pod", SOURCE_POD, "-n", NAMESPACE, "--wait=true", "--timeout=120s")
    simulator_restore = evidence_dir / "phase6-simulator-restore.json"
    if simulator_restore.exists():
        saved_simulator = json.loads(simulator_restore.read_text())
        current_sim = oc("get", "pod", SIMULATOR_POD, "-n", NAMESPACE, "-o", "json",
                         check=False)
        if current_sim.returncode == 0:
            oc("delete", "pod", SIMULATOR_POD, "-n", NAMESPACE,
               "--wait=true", "--timeout=120s")
        oc("create", "-f", "-", input_text=json.dumps(clean_pod(saved_simulator)))
        wait_pod(SIMULATOR_POD, "Ready")
        oc("exec", "-n", NAMESPACE, SIMULATOR_POD, "-c", "simulator", "--",
           "bash", "-lc", "source /opt/ros/jazzy/setup.bash; "
           "timeout 20 ros2 topic echo --once /clock rosgraph_msgs/msg/Clock", timeout=25)
    inference_restore = evidence_dir / "phase6-inference-before.json"
    if inference_restore.exists():
        current_inference = oc("get", "pod", "semantic-phase6-sam3", "-n", NAMESPACE,
                               "-o", "json", check=False)
        if current_inference.returncode == 0:
            oc("delete", "pod", "semantic-phase6-sam3", "-n", NAMESPACE,
               "--wait=true", "--timeout=120s")
        oc("create", "-f", "-", input_text=json.dumps(
            clean_pod(json.loads(inference_restore.read_text()))))
        wait_pod("semantic-phase6-sam3", "Ready")
    oc("create", "-f", "-", input_text=json.dumps(clean_pod(saved)))
    wait_pod(SOURCE_POD, "Ready")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    up_parser = sub.add_parser("up")
    up_parser.add_argument("--evidence-dir", type=Path, required=True)
    down_parser = sub.add_parser("down")
    down_parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "up":
        up(args)
    else:
        restore(args.evidence_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
