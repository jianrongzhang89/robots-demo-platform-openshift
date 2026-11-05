#!/usr/bin/env python3
"""Frozen armed-semantic fault matrix on the private guarded fixture.

The semantic-task supervisor runs ARMED (camera/semantic/inference-heartbeat
leases required at the unchanged 500 ms capture-age freshness) while semantic
costs remain excluded from navigation. Each trial injects one perception
fault after the fixture reports verified semantic-armed motion; the
fixture-internal modes (camera_path_loss, tf_loss) are injected by the
fixture itself, and the pod-level modes (hung_inference, process_loss,
transport_loss) are injected by this runner through the coordinator status
file. Every fault must stop the chain fail-closed with a mode-qualified
first reason, zero within 100 ms of the 500 ms freshness trigger, and no
automatic resume after restoration — even though fresh successful perception
responses flow again (the late-success proof). No retries; the matrix stops
on the first failure. The parked demo SAM3 pod is saved, deleted and
restored exactly as in the observation series.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from run_phase5_baseline import placement_args, placement_error
from run_phase5_sam3_series import (BRIDGE_CONFIG, DEMO_SAM3_POD, GPU_NODE,
                                    NAMESPACE, ROUTER, ROUTER_CONFIG, SAM3_POD,
                                    restore_spec)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps/semantic-safety"))
from semantic_fault_probe import MODES

EXTERNAL_MODES = ("hung_inference", "process_loss", "transport_loss")
FIXTURE_POD = "semantic-phase5-native"
STATUS_PATH = "/tmp/phase5-native-results/semantic-armed-status.json"


def trial_passed(evidence, returncode, mode):
    required = {"semantic_fault_" + mode, "semantic_fault_native_stop_metrics",
                "late_success_does_not_resume_motion",
                "sam3_observation_ready", "sam3_semantic_isolation",
                "guarded_semantic_fault_terminal",
                "cancellation_terminal_and_acknowledged",
                "closed_graph_and_descendants_terminal",
                "baseline_contact_window",
                "independent_native_motion_observed", "settled_support_geometry"}
    if evidence.get("semantic_fault_mode") != mode:
        return False
    if evidence.get("sam3_observation") is not True:
        return False
    if evidence.get("console_only_server") is not True or evidence.get("world_recording") is not False:
        return False
    if evidence.get("diagnostic_only", False):
        return False
    checks = {c["case"]: c for c in evidence.get("checks", [])}
    return (returncode == 0 and evidence.get("passed") is True
            and all(checks.get(name, {}).get("passed") is True for name in required)
            and all(c.get("passed") is True for c in evidence.get("checks", [])))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oc", default="oc")
    parser.add_argument("--image", required=True)
    parser.add_argument("--sam3-image", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--modes", nargs="+", choices=MODES, default=list(MODES))
    parser.add_argument("--node-name", default="ip-10-0-44-146.ec2.internal")
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("at least one repetition per fault mode is required")
    error = placement_error(False, args.node_name, False, True)
    if error:
        parser.error(error)
    root = Path(__file__).resolve().parents[2]
    args.output_dir.mkdir(parents=True, exist_ok=False)
    files = sorted((root / "apps/semantic-safety").glob("*.py")) + [
        root / "apps/semantic-safety/phase5-baseline.xml",
        root / "helm/semantic-navigation/phase5-nav2-candidate.yaml",
        root / "scripts/semantic-navigation/run_phase5_native.py",
        root / "scripts/semantic-navigation/run_phase5_semantic_fault_matrix.py"]
    hashes = lambda: {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    frozen = hashes()
    trials = [{"mode": mode, "repetition": repetition}
              for repetition in range(1, args.repetitions + 1)
              for mode in args.modes]
    plan = {"image": args.image, "sam3_image": args.sam3_image,
            "planned_trials": len(trials), "modes": args.modes,
            "repetitions": args.repetitions, "node_name": args.node_name,
            "sam3_node": GPU_NODE,
            "scenario": ("armed-semantic fault matrix on the guarded fixture; "
                         "semantic costs excluded; zero <=100 ms after the 500 ms "
                         "freshness trigger; late success must not resume motion"),
            "retry_policy": "none; stop series on first failure",
            "qualified_profile": {"console_only_server": True, "contact_audit": True,
                                  "rear_casters": True, "physics_step": 0.002,
                                  "lidar_range": 12.0, "odom_frequency": 200.0,
                                  "gpu_rendering": True,
                                  "require_semantics": True},
            "source_hashes": frozen}
    (args.output_dir / "plan.json").write_text(json.dumps(plan, indent=2))

    def oc(*argv, check=True, input=None):
        return subprocess.run([args.oc, "-n", NAMESPACE, *argv], text=True,
                              capture_output=True, check=check, timeout=180, input=input)

    def fixture_status():
        result = oc("exec", FIXTURE_POD, "--container", "fixture", "--",
                    "cat", STATUS_PATH, check=False)
        if result.returncode != 0:
            return {}
        try:
            return json.loads(result.stdout)
        except ValueError:
            return {}

    def inject(mode):
        """Inject one pod-level perception fault; returns evidence."""
        steady = time.monotonic_ns()
        if mode == "hung_inference":
            result = oc("exec", SAM3_POD, "-c", "sam3-inference", "--", "bash", "-c",
                        'kill -STOP "$(cat /tmp/sam3-python.pid)"', check=False)
        elif mode == "process_loss":
            result = oc("exec", SAM3_POD, "-c", "sam3-inference", "--", "bash", "-c",
                        'kill -KILL "$(cat /tmp/sam3-python.pid)"', check=False)
        elif mode == "transport_loss":
            # Force-delete the SAM3 pod: the perception backend's entire
            # connectivity vanishes instantly (its TCP sockets close with the
            # containers), stopping the semantic flow in milliseconds while
            # the router and the fixture-side session stay alive. The repair
            # recreates the pod, whose fresh bridge and process reconnect
            # through the live router — the same mechanics as the proven
            # post-process-loss recycle. Router-kill and bridge-kill
            # injections are both unrepairable mid-trial: a zenoh client
            # session never re-dials a lost router (matrices 8 and 9), and a
            # wrapper-run bridge never delivered camera data to the process
            # (matrix 10).
            result = oc("delete", "pod", SAM3_POD, "--grace-period=0",
                        "--force", "--wait=true", "--timeout=30s", check=False)
        else:
            raise ValueError(mode)
        return {"mode": mode, "steady_ns": steady, "wall_ns": time.time_ns(),
                "returncode": result.returncode,
                "stdout": result.stdout[-500:], "stderr": result.stderr[-500:]}

    def restore(mode, deployment):
        """Repair the injected fault; the late successful response must flow
        again through the repaired path."""
        steady = time.monotonic_ns()
        if mode == "hung_inference":
            result = oc("exec", SAM3_POD, "-c", "sam3-inference", "--", "bash", "-c",
                        'kill -CONT "$(cat /tmp/sam3-python.pid)"', check=False)
        elif mode == "process_loss":
            # The wrapper exits with python and restartPolicy Always restarts
            # the container; verify the recorded evidence below.
            result = None
        elif mode == "transport_loss":
            # Recreate the deleted pod; the fresh bridge reconnects to the
            # live router and the fresh process resumes publishing once its
            # model reloads.
            result = oc("create", "-f", "-", input=json.dumps(sam3_pod), check=False)
            if result.returncode == 0:
                deadline = time.monotonic() + 300
                while time.monotonic() < deadline:
                    status = json.loads(oc("get", "pod", SAM3_POD, "-o", "json",
                                           check=False).stdout or "{}").get("status", {})
                    if status.get("phase") == "Running" and all(
                            c.get("ready") for c in status.get("containerStatuses", [])):
                        break
                    time.sleep(3)
        else:
            raise ValueError(mode)
        return {"mode": mode, "steady_ns": steady, "wall_ns": time.time_ns(),
                "returncode": result.returncode if result else None}

    results = []
    demo_live = json.loads(oc("get", "pod", DEMO_SAM3_POD, "-o", "json").stdout)
    (args.output_dir / "demo-sam3-saved-pod.json").write_text(json.dumps(demo_live, indent=2))
    restore_pod = restore_spec(demo_live)
    (args.output_dir / "demo-sam3-restore-pod.json").write_text(json.dumps(restore_pod, indent=2))
    created = []
    router_deployment = None
    try:
        oc("delete", "pod", DEMO_SAM3_POD, "--wait=true", "--timeout=120s")
        config_map = {"apiVersion": "v1", "kind": "ConfigMap",
            "metadata": {"name": ROUTER_CONFIG, "namespace": NAMESPACE,
                         "labels": {"app": ROUTER}},
            "data": {
                "cyclonedds.xml": '<CycloneDDS><Domain id="any"><General><Interfaces><NetworkInterface name="lo"/></Interfaces><AllowMulticast>false</AllowMulticast></General><Discovery><ParticipantIndex>auto</ParticipantIndex></Discovery></Domain></CycloneDDS>',
                "router.json5": '{\n  "mode": "router",\n  "listen": { "endpoints": ["tcp/0.0.0.0:17448"] },\n  "scouting": { "multicast": { "enabled": false } }\n}\n',
                "sam3-bridge.json5": BRIDGE_CONFIG}}
        service = {"apiVersion": "v1", "kind": "Service",
            "metadata": {"name": ROUTER, "namespace": NAMESPACE,
                         "labels": {"app": ROUTER}},
            "spec": {"selector": {"app": ROUTER},
                     "ports": [{"name": "zenoh", "port": 17448, "targetPort": 17448}]}}
        router_deployment = {"apiVersion": "apps/v1", "kind": "Deployment",
            "metadata": {"name": ROUTER, "namespace": NAMESPACE,
                         "labels": {"app": ROUTER}},
            "spec": {"replicas": 1, "selector": {"matchLabels": {"app": ROUTER}},
                "template": {"metadata": {"labels": {"app": ROUTER}},
                    "spec": {"containers": [{"name": "router",
                        "image": "docker.io/eclipse/zenoh@sha256:137310456cc7a75d955063513207c737f25071fbb74fd7641835c50ab8e3369f",
                        "imagePullPolicy": "IfNotPresent",
                        "args": ["-c", "/phase5-config/router.json5"],
                        "ports": [{"name": "zenoh", "containerPort": 17448}],
                        "resources": {"requests": {"cpu": "100m", "memory": "128Mi"},
                                      "limits": {"cpu": "500m", "memory": "512Mi"}},
                        "volumeMounts": [{"name": "config", "mountPath": "/phase5-config", "readOnly": True}]}],
                        "volumes": [{"name": "config", "configMap": {"name": ROUTER_CONFIG}}]}}}}
        sam3_pod = {"apiVersion": "v1", "kind": "Pod",
            "metadata": {"name": SAM3_POD, "namespace": NAMESPACE,
                         "labels": {"app": SAM3_POD}},
            "spec": {"restartPolicy": "Always",
                "securityContext": {"fsGroup": 1001340000, "fsGroupChangePolicy": "OnRootMismatch"},
                "nodeSelector": {"kubernetes.io/hostname": GPU_NODE},
                "tolerations": [{"key": "g6e-gpu", "operator": "Equal", "value": "true", "effect": "NoSchedule"}],
                "containers": [
                    {"name": "sam3-zenoh-bridge",
                     "image": "eclipse/zenoh-bridge-ros2dds@sha256:38f162ae5236412f4f02e77927e22585356f7e706db39ec1c6194b9bd0d05b18",
                     "args": ["-c", "/phase5-bridges/sam3-bridge.json5"],
                     "env": [{"name": k, "value": v} for k, v in {
                         "ROS_DOMAIN_ID": "86", "ROS_DISTRO": "jazzy",
                         "RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp",
                         "CYCLONEDDS_URI": "file:///phase5-bridges/cyclonedds.xml"}.items()],
                     "volumeMounts": [{"name": "bridge-config", "mountPath": "/phase5-bridges", "readOnly": True}],
                     "resources": {"requests": {"cpu": "100m", "memory": "128Mi"},
                                   "limits": {"cpu": "500m", "memory": "512Mi"}}},
                    {"name": "sam3-inference", "image": args.sam3_image,
                     "imagePullPolicy": "IfNotPresent",
                     # python runs as a CHILD of the wrapper, not as the
                     # container's PID 1: signals sent to a PID namespace's
                     # init from inside the namespace are dropped (even
                     # SIGSTOP/SIGKILL — pilot matrix 1 trial 3 injected
                     # "successfully" and SAM3 kept running). The wrapper
                     # records python's PID for the fault injections.
                     "command": ["/bin/bash", "-c"],
                     "args": ["source /opt/ros/jazzy/setup.bash; "
                              "/opt/sam3-venv/bin/python /opt/semantic-perception/sam3_ros_node.py & "
                              "echo $! > /tmp/sam3-python.pid; "
                              "wait $(cat /tmp/sam3-python.pid)"],
                     "env": [{"name": k, "value": v} for k, v in {
                         "ROS_DOMAIN_ID": "86", "ROS_DISTRO": "jazzy",
                         "HOME": "/tmp/phase5-sam3-home", "ROS_LOG_DIR": "/tmp/phase5-sam3-logs",
                         "RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp",
                         "CYCLONEDDS_URI": "file:///phase5-bridges/cyclonedds.xml",
                         "SAM3_PROMPT": "red mat",
                         "SEMANTIC_REQUIRE_CAPTURE_TRACE": "1",
                         "SEMANTIC_MAX_WORK_WAIT_MS": "40",
                         "SEMANTIC_CLOCK_UNCERTAINTY_MS": "2"}.items()],
                     "volumeMounts": [
                         {"name": "bridge-config", "mountPath": "/phase5-bridges", "readOnly": True},
                         {"name": "model", "mountPath": "/models", "readOnly": True}],
                     "resources": {"requests": {"cpu": "3", "memory": "12Gi", "nvidia.com/gpu": 1},
                                   "limits": {"cpu": "6", "memory": "24Gi", "nvidia.com/gpu": 1}}}],
                "volumes": [
                    {"name": "bridge-config", "configMap": {"name": ROUTER_CONFIG}},
                    {"name": "model", "persistentVolumeClaim": {"claimName": "sam3-checkpoint"}}]}}
        for obj in (config_map, service, router_deployment, sam3_pod):
            oc("create", "-f", "-", input=json.dumps(obj))
            created.append((obj["kind"], obj["metadata"]["name"]))
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            status = json.loads(oc("get", "pod", SAM3_POD, "-o", "json").stdout).get("status", {})
            if status.get("phase") == "Running" and all(
                    c.get("ready") for c in status.get("containerStatuses", [])):
                break
            time.sleep(5)
        else:
            raise RuntimeError("private SAM3 pod did not become ready")
        (args.output_dir / "sam3-topology.json").write_text(json.dumps(
            {"created": created, "ready_wall_ns": time.time_ns()}, indent=2))

        for trial in trials:
            if hashes() != frozen:
                raise RuntimeError("runtime inputs changed during fixed series")
            directory = args.output_dir / f"trial-{len(results)+1:02d}-{trial['mode']}-r{trial['repetition']}"
            print(json.dumps({"event": "trial_started", **trial}), flush=True)
            command = [sys.executable,
                str(root / "scripts/semantic-navigation/run_phase5_native.py"),
                "--oc", args.oc, "--suite", "hotel-guarded", "--contact-audit",
                "--sam3-observation", "--semantic-fault-probe",
                "--semantic-fault-mode", trial["mode"],
                "--console-only-server", "--rear-casters",
                "--physics-step", "0.002", "--lidar-range", "12", "--odom-frequency", "200",
                "--gpu-rendering", "--node-name", args.node_name,
                "--image", args.image, "--output-dir", str(directory)]
            command.extend(placement_args(args.node_name, False, True))
            run = subprocess.Popen(command)
            injection_log = {"mode": trial["mode"], "events": []}
            try:
                # Wait for the fixture to report verified semantic-armed
                # motion, then inject the pod-level fault from outside. The
                # deadline covers the fixture's full bounded budget: a
                # process-loss restart can spend 300 s at the SAM3 readiness
                # gate before motion even starts.
                deadline = time.monotonic() + 960
                injected = False
                while time.monotonic() < deadline and run.poll() is None:
                    status = fixture_status()
                    if not injected and status.get("phase") == "motion_verified":
                        if trial["mode"] in EXTERNAL_MODES:
                            injection_log["events"].append(
                                {"event": "injected", **inject(trial["mode"])})
                        injected = True
                    if injected and status.get("phase") == "stopped":
                        if trial["mode"] in EXTERNAL_MODES:
                            injection_log["events"].append(
                                {"event": "restore", **restore(trial["mode"], router_deployment)})
                        break
                    # 0.5 s: the injection must land well before the short
                    # 1 m goal completes after motion verification.
                    time.sleep(0.5)
                if injected and trial["mode"] in EXTERNAL_MODES:
                    # Safety net if the stopped phase was missed: restore anyway.
                    if not any(e["event"] == "restore" for e in injection_log["events"]):
                        injection_log["events"].append(
                            {"event": "restore_late", **restore(trial["mode"], router_deployment)})
            finally:
                run.wait()
            (directory / "injection-log.json").write_text(json.dumps(injection_log, indent=2))
            path = directory / "runtime/summary.json"
            evidence = json.loads(path.read_text()) if path.is_file() else {}
            passed = trial_passed(evidence, run.returncode, trial["mode"])
            if hashes() != frozen:
                passed = False
            if not passed:
                # The teardown deletes the SAM3 topology; retain its state
                # and container logs first so a failed trial can be
                # root-caused from evidence (matrix 4 trial 5 left no SAM3
                # artifacts to diagnose the post-restart readiness hang).
                capture = {"sam3_pod": json.loads(oc("get", "pod", SAM3_POD,
                    "-o", "json", check=False).stdout or "{}"),
                    "fixture_pod": json.loads(oc("get", "pod", FIXTURE_POD,
                    "-o", "json", check=False).stdout or "{}"),
                    "router_deployment": json.loads(oc("get", "deployment", ROUTER,
                    "-o", "json", check=False).stdout or "{}")}
                router_pods = oc("get", "pod", "-l", f"app={ROUTER}",
                                 "-o", "json", check=False)
                try:
                    capture["router_pods"] = [p["metadata"]["name"] for p in
                        json.loads(router_pods.stdout).get("items", [])]
                except ValueError:
                    capture["router_pods"] = []
                for container in ("sam3-inference", "sam3-zenoh-bridge"):
                    logs = oc("logs", SAM3_POD, "-c", container, check=False)
                    capture[f"{container}.log"] = logs.stdout[-100000:]
                (directory / "sam3-pod-state.json").write_text(json.dumps(capture, indent=2))
            results.append({"trial": len(results) + 1, **trial, "passed": passed,
                            "returncode": run.returncode, "evidence": str(path)})
            summary = {"passed": len(results) == len(trials) and all(r["passed"] for r in results),
                       "planned": len(trials), "attempted": len(results),
                       "succeeded": sum(r["passed"] for r in results),
                       "results": results,
                       "scope": "armed semantic fault matrix on the private guarded "
                                "fixture; semantic costs excluded; not full Phase 5 "
                                "acceptance without the evidence review"}
            (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2))
            print(json.dumps({"event": "trial_finished", **results[-1]}), flush=True)
            if not passed:
                raise RuntimeError("armed semantic fault matrix failed; no automatic retry")
            if trial["mode"] == "process_loss":
                # The auto-restarted inference process does not rejoin the
                # bridge's camera relay: it keeps publishing status through
                # the SAM3-side bridge (which the late-success check sees)
                # but never receives frames again — deterministically
                # reproduced as a readiness hang in the following trial in
                # matrices 3, 4 and 5. Recreate the pod so every trial
                # starts from the same fresh topology the passing trials
                # used; the within-trial fault and late-success semantics
                # are unchanged.
                recycle = {"mode": trial["mode"]}
                oc("delete", "pod", SAM3_POD, "--wait=true", "--timeout=120s")
                oc("create", "-f", "-", input=json.dumps(sam3_pod))
                deadline = time.monotonic() + 600
                while time.monotonic() < deadline:
                    status = json.loads(oc("get", "pod", SAM3_POD, "-o", "json").stdout).get("status", {})
                    if status.get("phase") == "Running" and all(
                            c.get("ready") for c in status.get("containerStatuses", [])):
                        recycle["ready_wall_ns"] = time.time_ns()
                        break
                    time.sleep(5)
                else:
                    raise RuntimeError("recreated SAM3 pod did not become ready")
                (directory / "sam3-pod-recycled.json").write_text(json.dumps(recycle, indent=2))
                print(json.dumps({"event": "sam3_pod_recycled", **recycle}), flush=True)
    finally:
        cleanup = []
        for kind, name in reversed(created):
            result = oc("delete", kind, name, "--wait=true", "--timeout=120s", check=False)
            cleanup.append({"kind": kind, "name": name,
                            "returncode": result.returncode, "stderr": result.stderr})
        restore_result = oc("create", "-f", "-", input=json.dumps(restore_pod), check=False)
        cleanup.append({"kind": "Pod", "name": DEMO_SAM3_POD,
                        "returncode": restore_result.returncode,
                        "stderr": restore_result.stderr})
        if restore_result.returncode == 0:
            deadline = time.monotonic() + 600
            restored = False
            while time.monotonic() < deadline:
                status = json.loads(oc("get", "pod", DEMO_SAM3_POD, "-o", "json",
                                       check=False).stdout).get("status", {})
                if status.get("phase") == "Running" and all(
                        c.get("ready") for c in status.get("containerStatuses", [])):
                    restored = True
                    break
                time.sleep(5)
            cleanup.append({"kind": "Pod", "name": DEMO_SAM3_POD, "restored": restored})
        (args.output_dir / "cleanup.json").write_text(json.dumps(cleanup, indent=2))


if __name__ == "__main__":
    main()
