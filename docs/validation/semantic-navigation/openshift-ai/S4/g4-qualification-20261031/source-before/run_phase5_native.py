#!/usr/bin/env python3
"""Run the isolated native-watchdog physics fixture and retain/clean up evidence."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import time
import yaml

NAME = "semantic-phase5-native"
NAMESPACE = "semantic-navigation"


def node_has_gpu(node):
    """Return whether a Kubernetes Node advertises GPU hardware/resources."""
    metadata = node.get("metadata", {})
    labels = metadata.get("labels", {})
    if any(labels.get(key, "").lower() == "true" for key in (
            "nvidia.com/gpu.present", "amd.com/gpu.present")):
        return True
    for section in (node.get("status", {}).get("capacity", {}),
                    node.get("status", {}).get("allocatable", {})):
        if any("gpu" in key.lower() or key.lower().startswith("nvidia.com/mig-")
               for key in section):
            return True
    return any("gpu" in taint.get("key", "").lower()
               for taint in node.get("spec", {}).get("taints", []))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oc", default="oc")
    parser.add_argument("--image", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--node-name",help="pin this private fixture to an explicit Kubernetes hostname")
    parser.add_argument("--allow-g5-node",action="store_true",
                        help="allow only this pinned private disarmed timing fixture onto a g5-gpu-tainted node")
    parser.add_argument("--require-non-gpu-node",action="store_true",
                        help="for a pinned moving trace, fail closed if the selected node advertises GPU hardware/resources")
    parser.add_argument("--suite", choices=("native","combined","contacts","hotel","hotel-guarded"), default="native")
    parser.add_argument("--contact-audit",action="store_true",help="require the read-only native contact observer in hotel tests")
    parser.add_argument("--recovery-probe",action="store_true",help="private guarded tree that exercises bounded BackUp then zero-only Wait")
    parser.add_argument("--controller-endpoint-capture",action="store_true",
                        help="opt-in private controller overlay evaluating fixed map goal at robot capture time")
    parser.add_argument("--console-only-server",action="store_true",
                        help="opt-in pinned private server without world recording; requires contact evidence")
    parser.add_argument("--collision-monitor-diagnostics",action="store_true",
                        help="private disarmed timing instrumentation for Collision Monitor callback/source/TF paths")
    parser.add_argument("--moving-timing-trace",action="store_true",
                        help="one private guarded recovery motion with CM, TF-edge/producer, scan and scheduler timing probes")
    parser.add_argument("--gz-thread-probe",action="store_true",
                        help="read-only per-thread schedstat sampling of the console Gazebo and Collision Monitor processes during a hotel trial")
    parser.add_argument("--gpu-rendering",action="store_true",
                        help="pin to a GPU node and render the RGB-D camera through EGL on the allocated GPU instead of llvmpipe software rendering")
    parser.add_argument("--tf-edge-probe",action="store_true",
                        help="sample fixed-frame TF edge availability in the disarmed Collision Monitor timing fixture")
    parser.add_argument("--tf-producer-trace",action="store_true",
                        help="trace odometry receipt and TF publication in the private frame bridge")
    parser.add_argument("--tf2-poll-1ms",action="store_true",
                        help="opt in to the private 1 ms TF2 advanced-lookup polling overlay (disarmed 200 Hz probe only)")
    parser.add_argument("--tf-log-threshold-us",type=int,choices=(1000,8000),
                        help="set the Collision Monitor timing-log threshold independently of the TF2 implementation")
    parser.add_argument("--bounded-cpu-contention",action="store_true",
                        help="run two bounded-lifetime CPU workers during the disarmed timing fixture")
    parser.add_argument("--diagnostic-record-period",type=float,choices=(.1,3600.),
                        help="hotel performance experiment only; Gazebo state-recording period in simulation seconds")
    parser.add_argument("--diagnostic-no-world-recording",action="store_true",
                        help="private API server diagnostic with console logging but no world recorder")
    parser.add_argument("--diagnostic-api-world-recording",action="store_true",
                        help="recording-enabled API-server control for the recording-disabled diagnostic")
    parser.add_argument("--tf-loss-probe",action="store_true",help="private guarded trial that pauses AMCL after motion to verify TF-loss stopping")
    parser.add_argument("--tf-loss-mode",choices=("amcl","supervisor"),default="amcl",
                        help="AMCL publisher outage or TF delivery loss only to the supervisor buffer")
    parser.add_argument("--fault-stop-probe",action="store_true",
                        help="private guarded trial that injects one fault class after verified motion and requires a fail-closed stop")
    parser.add_argument("--fault-stop-mode",choices=("collision_state","scan_loss","command_stall","transport_loss","obstacle_spawn"),
                        help="fault class injected by the moving fault-stop probe")
    parser.add_argument("--sam3-observation",action="store_true",
                        help="private guarded baseline trial with observation-only SAM3; requires the private SAM3 topology (router and pod) to already exist")
    parser.add_argument("--semantic-fault-probe",action="store_true",
                        help="private armed-semantic fault trial on the SAM3 observation topology; the supervisor requires camera/semantic/heartbeat leases")
    parser.add_argument("--semantic-fault-mode",choices=("camera_path_loss","tf_loss","hung_inference","process_loss","transport_loss"),
                        help="perception fault class injected by the armed semantic fault matrix")
    parser.add_argument("--semantic-arm",choices=("off","on"),
                        help="Phase 6 paired-trial arm: off keeps the Phase 5 candidate (costs excluded); on adds only the additive soft-cost semantic layer to both costmaps")
    parser.add_argument("--phase6-goal-x",type=float,default=19.402,
                        help="map-frame goal x for Phase 6 crossing trials (identical in both arms)")
    parser.add_argument("--phase6-goal-y",type=float,default=-31.594,
                        help="map-frame goal y for Phase 6 crossing trials (identical in both arms)")
    parser.add_argument("--phase6-stationary-smoke",action="store_true",
                        help="disarmed Phase 6 semantic-on wiring and target-removal clearing smoke; no goal is dispatched")
    parser.add_argument("--phase6-no-semantic-bridge",action="store_true",
                        help="diagnostic only: run without the domain-85 semantic bridge and label relay sidecars, isolating their load contribution (pilot-1 off-arm UDP-stall investigation)")
    parser.add_argument("--phase6-controller-snapshot",action="store_true",
                        help="diagnostic only: capture controller/smoother thread stacks via gdb when a Phase 6 arm trial stops on command_expired. WARNING: the gdb fork freezes the fixture's UDP status thread ~1.6 s and latches native_capture_stale — only for stack capture, never for clean timing evidence")
    parser.add_argument("--phase6-tf-probe",action="store_true",
                        help="diagnostic only: localize the mat-close /tf delivery delay — enables the frame-bridge TF producer trace, per-message odom->base arrival recording in the fixture, and a read-only /tf prober sidecar on the safety domain")
    parser.add_argument("--phase6-tf-witness",action="store_true",
                        help="user-approved capture-time TF witness sidecar (2026-10-28): a prompt own-quota process resolves map->sensor at each scan's capture stamp and feeds the gate's tf lease through the same fail-closed evidence path (UDP-companion-path pattern); required for Phase 6 arm trials past the mat-close saturation")
    parser.add_argument("--phase6-costcells",action="store_true",
                        help="diagnostic only: record the mid-trial global semantic-cell timeline (mask-bleed mapping). WARNING: materializing the ~585k-cell service response blocks the fixture pump 33-42 ms per 1 Hz poll — never use it when clean timing evidence matters (pair-1-on-bleedmap lost a trial to exactly this)")
    parser.add_argument("--phase6-lethal",action="store_true",
                        help="the implementation plan's lethal-cost exclusion experiment: the on-arm candidate carries target_cost 254 instead of the qualified soft cost 200 ('Evaluate lethal cost 254 as a separate exclusion experiment. A model-only restriction is not a production safety boundary.')")
    parser.add_argument("--phase6-target-absent",action="store_true",
                        help="the series' target-absent negative case: the staged mat is omitted from the private world; completion must not regress (observed cells recorded as a recognition diagnostic, never gated)")
    parser.add_argument("--phase6-target-removal",action="store_true",
                        help="the series' target-removal negative case: the mat is removed mid-trial through the pre-warmed mover once the robot is under way; completion must not regress")
    parser.add_argument("--rear-casters",action="store_true",help="opt-in private support-geometry candidate; requires contact evidence")
    parser.add_argument("--physics-step",type=float,choices=(.001,.002,.01),help="isolated hotel contact diagnostic timestep in seconds")
    parser.add_argument("--lidar-range",type=float,choices=(3.5,12.),help="private virtual lidar range in metres; not a hardware specification")
    parser.add_argument("--odom-frequency",type=float,choices=(50.,200.),help="native odometry publication frequency; preserves capture stamps")
    parser.add_argument("--controller-frequency", type=float,
                        help="isolated hotel diagnostic override in Hz; candidate profile is unchanged")
    parser.add_argument("--nav-seconds", type=float,
                        help="isolated disarmed hotel observation duration")
    parser.add_argument("--scan-update-rate", type=float,
                        help="isolated hotel lidar-rate override in Hz; installed asset is unchanged")
    parser.add_argument("--smoother-frequency", type=float,
                        help="isolated velocity-smoother diagnostic override in Hz")
    args = parser.parse_args()
    is_hotel = args.suite in ("hotel","hotel-guarded")
    if args.diagnostic_record_period is not None and not is_hotel:
        parser.error("--diagnostic-record-period applies only to private hotel fixtures")
    api_server=args.diagnostic_no_world_recording or args.diagnostic_api_world_recording
    if args.gz_thread_probe and (not is_hotel or not args.console_only_server):
        parser.error("--gz-thread-probe requires a hotel suite with --console-only-server (it watches the console Gazebo process)")
    if args.gz_thread_probe and args.moving_timing_trace:
        parser.error("--gz-thread-probe already samples threads; combine it with the recovery profile, not --moving-timing-trace")
    if args.gpu_rendering and not args.node_name:
        parser.error("--gpu-rendering requires --node-name pinned to a GPU worker")
    if args.gpu_rendering and (args.require_non_gpu_node or args.allow_g5_node):
        parser.error("--gpu-rendering is an explicit GPU placement and cannot combine with --require-non-gpu-node or --allow-g5-node")
    if args.gpu_rendering and not is_hotel:
        parser.error("--gpu-rendering applies only to hotel suites with the RGB-D camera")
    if args.moving_timing_trace:
        conflicting = (args.collision_monitor_diagnostics or args.tf_edge_probe or args.tf_producer_trace
                       or args.tf2_poll_1ms or args.tf_log_threshold_us is not None
                       or args.bounded_cpu_contention or args.tf_loss_probe or args.fault_stop_probe or args.sam3_observation
                       or args.controller_endpoint_capture or api_server
                       or args.diagnostic_record_period is not None
                       or args.controller_frequency is not None or args.nav_seconds is not None
                       or args.scan_update_rate is not None or args.smoother_frequency is not None)
        if conflicting:
            parser.error("--moving-timing-trace is a single fixed-profile trial and cannot be combined with other probes or overrides")
        if not (args.suite == "hotel-guarded" and args.recovery_probe and args.contact_audit
                and args.console_only_server and args.rear_casters and args.physics_step == .002
                and args.lidar_range == 12. and args.odom_frequency == 200.):
            parser.error("--moving-timing-trace requires --suite hotel-guarded --recovery-probe --contact-audit "
                         "--console-only-server --rear-casters --physics-step 0.002 "
                         "--lidar-range 12 --odom-frequency 200")
    if args.console_only_server and (not is_hotel or not args.contact_audit or api_server
                                    or args.diagnostic_record_period is not None):
        parser.error("--console-only-server requires hotel contact evidence and no recording diagnostics")
    if args.collision_monitor_diagnostics and (args.suite != "hotel" or not args.console_only_server):
        parser.error("--collision-monitor-diagnostics requires the disarmed hotel suite and --console-only-server")
    if args.tf_edge_probe and (args.suite != "hotel" or not args.console_only_server or not args.collision_monitor_diagnostics):
        parser.error("--tf-edge-probe requires the disarmed hotel console-only Collision Monitor diagnostic fixture")
    if args.tf_producer_trace and not args.tf_edge_probe:
        parser.error("--tf-producer-trace requires --tf-edge-probe")
    if args.tf2_poll_1ms and (not args.tf_edge_probe or args.odom_frequency != 200.):
        parser.error("--tf2-poll-1ms requires --tf-edge-probe and --odom-frequency 200")
    if args.tf_log_threshold_us is not None and not args.tf_edge_probe:
        parser.error("--tf-log-threshold-us requires --tf-edge-probe")
    if args.bounded_cpu_contention and not args.tf_edge_probe:
        parser.error("--bounded-cpu-contention requires the disarmed TF edge diagnostic")
    cm_diagnostics = args.collision_monitor_diagnostics or args.moving_timing_trace
    edge_probe = args.tf_edge_probe or args.moving_timing_trace
    producer_trace = args.tf_producer_trace or args.moving_timing_trace
    if cm_diagnostics and not (
            args.rear_casters and args.physics_step == .002
            and args.lidar_range == 12. and args.odom_frequency == 200.):
        parser.error("--collision-monitor-diagnostics requires the qualified private geometry profile: "
                     "--rear-casters --physics-step 0.002 --lidar-range 12 --odom-frequency 200")
    if args.node_name and (not is_hotel or not re.fullmatch(r"[a-z0-9][a-z0-9.-]*",args.node_name)):
        parser.error("--node-name requires a hotel suite and a valid Kubernetes hostname")
    if args.require_non_gpu_node and (not args.node_name or args.allow_g5_node):
        parser.error("--require-non-gpu-node requires --node-name and cannot allow a G5 node")
    if args.allow_g5_node and (not args.node_name or not args.collision_monitor_diagnostics):
        parser.error("--allow-g5-node requires an explicitly pinned Collision Monitor diagnostic fixture")
    if api_server and (not is_hotel or args.diagnostic_record_period is not None or
                       args.diagnostic_no_world_recording and args.diagnostic_api_world_recording):
        parser.error("API recording experiments require a hotel fixture and exactly one recording mode")
    if args.contact_audit and not is_hotel:
        parser.error("--contact-audit applies only to hotel suites")
    if args.recovery_probe and args.suite!="hotel-guarded":
        parser.error("--recovery-probe requires the private hotel-guarded suite")
    if args.controller_endpoint_capture and args.suite!="hotel-guarded":
        parser.error("--controller-endpoint-capture requires the private hotel-guarded suite")
    if args.tf_loss_probe and args.suite!="hotel-guarded":
        parser.error("--tf-loss-probe requires the private hotel-guarded suite")
    if args.tf_loss_probe and args.recovery_probe:
        parser.error("--tf-loss-probe and --recovery-probe are separate trials")
    if args.tf_loss_mode!="amcl" and not args.tf_loss_probe:
        parser.error("--tf-loss-mode requires --tf-loss-probe")
    if args.fault_stop_mode and not args.fault_stop_probe:
        parser.error("--fault-stop-mode requires --fault-stop-probe")
    if args.fault_stop_probe:
        if args.suite!="hotel-guarded":
            parser.error("--fault-stop-probe requires the private hotel-guarded suite")
        if args.recovery_probe:
            parser.error("--fault-stop-probe and --recovery-probe are separate trials")
        if args.tf_loss_probe:
            parser.error("--fault-stop-probe and --tf-loss-probe are separate trials")
        if not args.node_name:
            parser.error("--fault-stop-probe requires a pinned node (--node-name)")
        if not (args.console_only_server and args.contact_audit):
            parser.error("--fault-stop-probe requires --console-only-server with --contact-audit")
        if not (args.rear_casters and args.physics_step==.002
                and args.lidar_range==12. and args.odom_frequency==200.):
            parser.error("--fault-stop-probe requires the qualified private geometry profile: "
                         "--rear-casters --physics-step 0.002 --lidar-range 12 --odom-frequency 200")
    if args.sam3_observation:
        if args.suite!="hotel-guarded":
            parser.error("--sam3-observation requires the private hotel-guarded suite")
        for flag,label in ((args.recovery_probe,"--recovery-probe"),
                           (args.tf_loss_probe,"--tf-loss-probe"),
                           (args.fault_stop_probe,"--fault-stop-probe")):
            if flag:
                parser.error(f"--sam3-observation and {label} are separate trials")
        if not args.node_name:
            parser.error("--sam3-observation requires a pinned node (--node-name)")
        if not (args.console_only_server and args.contact_audit):
            parser.error("--sam3-observation requires --console-only-server with --contact-audit")
        if not (args.rear_casters and args.physics_step==.002
                and args.lidar_range==12. and args.odom_frequency==200.):
            parser.error("--sam3-observation requires the qualified private geometry profile: "
                         "--rear-casters --physics-step 0.002 --lidar-range 12 --odom-frequency 200")
    if args.semantic_arm:
        if args.suite!="hotel-guarded":
            parser.error("--semantic-arm requires the private hotel-guarded suite")
        if not args.sam3_observation:
            parser.error("--semantic-arm requires --sam3-observation (the private SAM3 topology)")
        for flag,label in ((args.recovery_probe,"--recovery-probe"),
                           (args.tf_loss_probe,"--tf-loss-probe"),
                           (args.fault_stop_probe,"--fault-stop-probe")):
            if flag:
                parser.error(f"--semantic-arm and {label} are separate trials")
        # --semantic-fault-probe is the ALLOWED companion for the series'
        # perception-failure case: the phase6 arm runs with the armed-semantic
        # supervisor and the Phase 5 fault-stop criteria checks.
        if args.semantic_fault_probe and args.semantic_fault_mode not in ("camera_path_loss","tf_loss"):
            parser.error("the phase6 perception-failure case uses the in-fixture "
                         "fault modes camera_path_loss/tf_loss")
        if args.phase6_target_absent and args.phase6_target_removal:
            parser.error("the negative-scene cases run as separate trials")
        if (args.phase6_target_absent or args.phase6_target_removal) and args.phase6_stationary_smoke:
            parser.error("the negative-scene cases are moving trials")
        if (args.phase6_target_absent or args.phase6_target_removal) and args.semantic_fault_probe:
            parser.error("the negative-scene cases run as separate trials")
        if not (args.console_only_server and args.contact_audit):
            parser.error("--semantic-arm requires --console-only-server with --contact-audit")
        if not (args.rear_casters and args.physics_step==.002
                and args.lidar_range==12. and args.odom_frequency==200.):
            parser.error("--semantic-arm requires the qualified private geometry profile: "
                         "--rear-casters --physics-step 0.002 --lidar-range 12 --odom-frequency 200")
        if not args.gpu_rendering:
            parser.error("--semantic-arm requires --gpu-rendering (the frozen guarded GPU profile)")
        if not args.node_name:
            parser.error("--semantic-arm requires a pinned node (--node-name)")
        if args.phase6_stationary_smoke and args.semantic_arm!="on":
            parser.error("--phase6-stationary-smoke is a semantic-on wiring check")
        if not (math.isfinite(args.phase6_goal_x) and math.isfinite(args.phase6_goal_y)):
            parser.error("--phase6-goal-x/--phase6-goal-y must be finite map coordinates")
    elif args.phase6_stationary_smoke:
        parser.error("--phase6-stationary-smoke requires --semantic-arm on")
    if args.phase6_no_semantic_bridge:
        if not args.semantic_arm:
            parser.error("--phase6-no-semantic-bridge is a Phase 6 arm diagnostic")
        if args.phase6_stationary_smoke:
            parser.error("the stationary smoke requires the semantic bridge (the relay delivers label_info)")
    if args.phase6_tf_probe:
        if not args.semantic_arm:
            parser.error("--phase6-tf-probe is a Phase 6 arm diagnostic")
    if args.phase6_tf_witness:
        if not args.semantic_arm:
            parser.error("--phase6-tf-witness is a Phase 6 arm companion")
    if args.phase6_costcells:
        if not args.semantic_arm:
            parser.error("--phase6-costcells is a Phase 6 arm diagnostic")
    if args.phase6_lethal:
        if args.semantic_arm != "on":
            parser.error("--phase6-lethal is a semantic-on arm experiment")
    if args.rear_casters and not (is_hotel and args.contact_audit or args.suite=="contacts"):
        parser.error("--rear-casters requires hotel --contact-audit or --suite contacts")
    if (args.physics_step is not None or args.lidar_range is not None or args.odom_frequency is not None) and not (is_hotel and args.contact_audit):
        parser.error("physics/range overrides require hotel --contact-audit")
    if not re.fullmatch(r"image-registry\.openshift-image-registry\.svc:5000/semantic-navigation/semantic-safety@sha256:[a-f0-9]{64}", args.image):
        parser.error("requires digest-pinned namespace safety image")
    root = Path(__file__).resolve().parents[2]
    def oc(*argv, input=None, check=True):
        return subprocess.run([args.oc, "-n", NAMESPACE, *argv], input=input, text=True,
                              capture_output=True, check=check, timeout=45)
    # With SAM3 observation the fixture pod also runs compressor and bridge
    # sidecars, so every fixture-pod command must name the fixture container.
    def exec_fixture(*argv, check=True):
        prefix = ("exec", NAME, "--container", "fixture") if args.sam3_observation else ("exec", NAME)
        return oc(*prefix, *argv, check=check)
    def logs_fixture(check=True):
        return oc(*(("logs", NAME, "--container", "fixture") if args.sam3_observation else ("logs", NAME)), check=check)
    def cp_fixture(destination, check=True):
        prefix = ("cp", "--container", "fixture") if args.sam3_observation else ("cp",)
        return oc(*prefix, NAME+":/tmp/phase5-native-results", str(destination), check=check)
    if args.require_non_gpu_node:
        node = json.loads(oc("get", "node", args.node_name, "-o", "json").stdout)
        ready = next((condition.get("status") for condition in
                      node.get("status", {}).get("conditions", [])
                      if condition.get("type") == "Ready"), "unknown")
        if ready != "True":
            raise RuntimeError(f"pinned node {args.node_name} is not Ready")
        if node_has_gpu(node):
            raise RuntimeError(f"pinned node {args.node_name} advertises GPU hardware/resources; refusing non-GPU trace")
    for kind in ("pod", "configmap"):
        if oc("get", kind, NAME, "--ignore-not-found", "-o", "name").stdout.strip():
            raise RuntimeError(f"refusing to replace {kind}/{NAME}")
    if args.sam3_observation:
        # Fail closed before creating any fixture resource unless the
        # private SAM3 topology (managed by the frozen series runner) is
        # deployed and ready on the qualified L40S placement.
        router = json.loads(oc("get", "deploy", "semantic-phase5-sam3-router", "-o", "json").stdout)
        if not router.get("status", {}).get("availableReplicas"):
            raise RuntimeError("private SAM3 router is not available")
        sam3 = json.loads(oc("get", "pod", "semantic-phase5-sam3", "-o", "json").stdout)
        containers_ready = all(c.get("ready") for c in sam3.get("status", {}).get("containerStatuses", []))
        if sam3.get("status", {}).get("phase") != "Running" or not containers_ready:
            raise RuntimeError("private SAM3 pod is not ready")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    builds = json.loads(oc("get", "builds", "-l", "buildconfig in (semantic-safety-phase5,semantic-safety-contacts-phase5,semantic-safety-controller-phase5,semantic-safety-console-phase5,semantic-safety-console-phase6)", "-o", "json").stdout)["items"]
    matching = [b for b in builds if b.get("status", {}).get("output", {}).get("to", {}).get("imageDigest") == args.image.split("@")[1]]
    if len(matching) != 1 or matching[0]["status"]["phase"] != "Complete":
        raise RuntimeError("candidate does not identify one completed safety build")
    build = matching[0]
    (args.output_dir / "build.json").write_text(json.dumps(build, indent=2))
    (args.output_dir / "build.log").write_text(oc("logs", "build/"+build["metadata"]["name"]).stdout)
    files = list((root / "apps/semantic-safety").glob("*.py"))
    data = {p.name: p.read_text() for p in sorted(files)}
    if args.console_only_server:
        data["console-source-hashes.json"]=json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((root/"apps/semantic-safety/console-launcher").iterdir()) if p.is_file()})
    if cm_diagnostics:
        data["instrument_nav2_collision_monitor.py"]=(root/"apps/semantic-safety/instrument_nav2_collision_monitor.py").read_text()
    if api_server:
        for p in sorted((root/"apps/semantic-safety/diagnostic-launcher").iterdir()):
            data[p.name]=p.read_text()
    if is_hotel:
        for p in (root / "helm/semantic-navigation/phase5-nav2-candidate.yaml",
                  root / "apps/semantic-safety/phase5-baseline.xml",
                  root / "scripts/semantic-navigation/install_phase1_camera.py"):
            data[p.name] = p.read_text()
        if args.recovery_probe:
            recovery_tree=root/"apps/semantic-safety/phase5-recovery-probe.xml"
            data[recovery_tree.name]=recovery_tree.read_text()
    data["cyclonedds-phase5.xml"] = '<CycloneDDS><Domain id="any"><General><Interfaces><NetworkInterface name="lo"/></Interfaces><AllowMulticast>false</AllowMulticast></General><Discovery><ParticipantIndex>auto</ParticipantIndex></Discovery></Domain></CycloneDDS>'
    if args.sam3_observation:
        # Fixture-side Zenoh bridge: exports ONLY the compressed camera
        # streams, calibration, render/compression traces and clock to the
        # private router; subscribes the SAM3 semantic outputs back onto
        # this private loopback domain. No TF, no odometry, no commands.
        data["phase5-sam3-bridge.json5"] = """{
  "plugins": { "ros2dds": { "allow": {
      "publishers": [
        "^/clock$",
        "^/robot_1/camera/color/image_compressed$",
        "^/robot_1/camera/depth/image_compressed$",
        "^/robot_1/camera/color/camera_info$",
        "^/robot_1/camera/capture_trace$",
        "^/robot_1/camera/compression_trace$"
      ],
      "subscribers": [
        "^/robot_1/semantic/mask$",
        "^/robot_1/semantic/points$",
        "^/robot_1/semantic/timing$",
        "^/robot_1/semantic/label_info$",
        "^/robot_1/semantic/status$",
        "^/robot_1/semantic/ready$"
      ]
    } } },
  "mode": "client",
  "connect": { "endpoints": ["tcp/semantic-phase5-sam3-router:17448"], "exit_on_failure": false, "timeout_ms": -1 },
  "scouting": { "multicast": { "enabled": false } }
}
"""
    if args.semantic_arm:
        # The Phase 6 "on" arm renders from the semantic-on candidate; the
        # "off" arm keeps the Phase 5 candidate. Only the semantic_layer
        # blocks differ (test_phase6_params.py proves arm identity).
        data["phase6-nav2-candidate.yaml"] = (root / "helm/semantic-navigation/phase6-nav2-candidate.yaml").read_text()
        if args.phase6_lethal:
            # The lethal-cost exclusion experiment's candidate variant
            # (target_cost 254; the implementation plan's separate experiment).
            data["phase6-nav2-candidate-lethal.yaml"] = (root / "helm/semantic-navigation/phase6-nav2-candidate-lethal.yaml").read_text()
        # Domain-85 semantic bridge config: republishes ONLY the four
        # semantic streams the costmap layer consumes onto the safety
        # domain, through the private router, in its own sidecar with its
        # own CPU quota (the multi-megabyte clouds must not load the
        # fixture container's shared budget). Run in BOTH arms so the
        # topology and transport load are identical.
        data["phase6-semantic-bridge.json5"] = """{
  "plugins": { "ros2dds": { "allow": {
      "publishers": [],
      "subscribers": [
        "^/robot_1/semantic/mask$",
        "^/robot_1/semantic/points$",
        "^/robot_1/semantic/timing$"
      ]
    } } },
  "mode": "client",
  "connect": { "endpoints": ["tcp/semantic-phase5-sam3-router:17448"], "exit_on_failure": false, "timeout_ms": -1 },
  "scouting": { "multicast": { "enabled": false } }
}
"""
        # label_info is deliberately NOT in the 85-bridge allowlist: a second
        # zenoh subscriber for the same transient-local key loses the latch
        # (reproduced with read-only diagnostic pods regardless of startup
        # order — pilot 1). The 88-bridge keeps it exclusively (the
        # Phase 5 series shape) and the sam3-label-relay sidecar republishes
        # the identical message on domain 85 for the costmap layers.
    metadata = {"name": NAME, "namespace": NAMESPACE}
    config = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": metadata, "data": data}
    env = {"PHASE5_SUITE":args.suite,"ROS_DOMAIN_ID": "85", "RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp",
           "CYCLONEDDS_URI": "file:///phase5-native/cyclonedds-phase5.xml",
           "ROS_LOG_DIR": "/tmp/phase5-ros-logs", "PYTHONDONTWRITEBYTECODE": "1",
           "GZ_IP": "127.0.0.1", "GZ_PARTITION": "phase5-watchdog-native-qualification",
           "GZ_SIM_SYSTEM_PLUGIN_PATH": "/opt/semantic-safety/lib:/usr/lib/x86_64-linux-gnu/gz-sim-8/plugins:/opt/ros/jazzy/opt/gz_sim_vendor/lib/gz-sim-8/plugins"}
    if args.semantic_fault_probe:
        # The armed-semantic fault trials carry bounded waits (SAM3 readiness
        # up to 300 s after a process-loss restart, late-success dwell up to
        # 240 s) that cannot fit the frozen 280 s suite budget; the in-pod
        # wrapper must outlive them (matrix 4 trial 5 was killed mid-
        # readiness by the hardcoded cap while the restarted SAM3 was still
        # reloading its model).
        env["PHASE5_FIXTURE_TIMEOUT_S"]="900"
    elif args.semantic_arm:
        # Phase 6 arm trials run the 4 m crossing goal (~27 s of motion at
        # 0.15 m/s, ~40 s wall at the observed RTF) plus the full post-goal
        # check suite; the frozen 280 s hotel budget from the 1 m-goal era
        # kills a passing trial mid-run (pair-1-off-joindiag: the wrapper's
        # TimeoutExpired at 280 s while the trial was still in progress).
        env["PHASE5_FIXTURE_TIMEOUT_S"]="600"
    if args.contact_audit: env["PHASE5_CONTACT_AUDIT"]="1"
    if args.recovery_probe: env["PHASE5_RECOVERY_PROBE"]="1"
    if args.controller_endpoint_capture: env["PHASE5_CONTROLLER_ENDPOINT_CAPTURE"]="1"
    if args.console_only_server: env["PHASE5_CONSOLE_ONLY_SERVER"]="1"
    if cm_diagnostics: env["PHASE5_COLLISION_MONITOR_DIAGNOSTICS"]="1"
    if edge_probe: env["PHASE5_TF_EDGE_PROBE"]="1"
    if producer_trace: env["PHASE5_TF_PRODUCER_TRACE"]="1"
    if args.moving_timing_trace: env["PHASE5_MOVING_TIMING_TRACE"]="1"
    if args.gz_thread_probe: env["PHASE5_GZ_THREAD_PROBE"]="1"
    if args.tf2_poll_1ms: env["PHASE5_TF2_POLL_1MS"]="1"
    if args.moving_timing_trace:
        env["PHASE5_TF_LOG_THRESHOLD_US"]="1000"
    elif args.tf_log_threshold_us is not None:
        env["PHASE5_TF_LOG_THRESHOLD_US"]=str(args.tf_log_threshold_us)
    if args.bounded_cpu_contention:
        env["PHASE5_BOUNDED_CPU_CONTENTION"]="1"
    if args.diagnostic_record_period is not None:
        env["PHASE5_DIAGNOSTIC_RECORD_PERIOD"]=str(args.diagnostic_record_period)
    if args.diagnostic_no_world_recording:
        env["PHASE5_DIAGNOSTIC_NO_WORLD_RECORDING"]="1"
    if args.diagnostic_api_world_recording:
        env["PHASE5_DIAGNOSTIC_API_WORLD_RECORDING"]="1"
    if args.tf_loss_probe:
        env["PHASE5_TF_LOSS_PROBE"]="1"
        env["PHASE5_TF_LOSS_MODE"]=args.tf_loss_mode
    if args.fault_stop_probe:
        env["PHASE5_FAULT_STOP_PROBE"]="1"
        env["PHASE5_FAULT_STOP_MODE"]=args.fault_stop_mode
    if args.sam3_observation:
        env["PHASE5_SAM3_OBSERVATION"]="1"
    if args.semantic_arm:
        env["PHASE6_SEMANTIC_ARM"]=args.semantic_arm
        env["PHASE6_GOAL_X"]=str(args.phase6_goal_x)
        env["PHASE6_GOAL_Y"]=str(args.phase6_goal_y)
        if args.phase6_stationary_smoke:
            env["PHASE6_STATIONARY_SMOKE"]="1"
        if args.phase6_no_semantic_bridge:
            env["PHASE6_DIAGNOSTIC_NO_85_BRIDGE"]="1"
        if args.phase6_controller_snapshot:
            env["PHASE6_CONTROLLER_SNAPSHOT"]="1"
        if args.phase6_tf_probe:
            # The producer trace runs in the frame-bridge child process
            # (env inherited through the fixture container); the fixture
            # records per-message odom->base arrivals; the prober sidecar is
            # added below. Diagnostic only — no gate or threshold changes.
            env["PHASE6_TF_PROBE"]="1"
            env["PHASE5_TF_PRODUCER_TRACE"]="1"
        if args.phase6_tf_witness:
            # User-approved 2026-10-28: the capture-time TF witness sidecar
            # feeds the gate's tf lease from its own prompt process. The
            # fixture renews through the same evidence() path; a stale or
            # missing witness record renews nothing (fail-closed).
            env["PHASE6_TF_WITNESS"]="1"
        if args.phase6_costcells:
            # Diagnostic only — blocks the fixture pump 33-42 ms per poll.
            env["PHASE6_COST_CELLS_TIMELINE"]="1"
        if args.phase6_lethal:
            # The lethal-cost exclusion experiment (implementation plan).
            env["PHASE6_LETHAL_EXPERIMENT"]="1"
        if args.phase6_target_absent:
            env["PHASE6_TARGET_ABSENT"]="1"
        if args.phase6_target_removal:
            env["PHASE6_TARGET_REMOVAL"]="1"
    if args.semantic_fault_mode and not args.semantic_fault_probe:
        parser.error("--semantic-fault-mode requires --semantic-fault-probe")
    if args.semantic_fault_probe:
        if not args.sam3_observation:
            parser.error("--semantic-fault-probe requires --sam3-observation (the private SAM3 topology)")
        if args.recovery_probe or args.tf_loss_probe or args.fault_stop_probe:
            parser.error("--semantic-fault-probe runs alone")
        env["PHASE5_SEMANTIC_FAULT_PROBE"]="1"
        env["PHASE5_SEMANTIC_FAULT_MODE"]=args.semantic_fault_mode
    if args.rear_casters: env["PHASE5_REAR_CASTERS"]="1"
    if args.physics_step is not None: env["PHASE5_PHYSICS_STEP"]=str(args.physics_step)
    if args.lidar_range is not None: env["PHASE5_LIDAR_RANGE"]=str(args.lidar_range)
    if args.odom_frequency is not None: env["PHASE5_ODOM_FREQUENCY"]=str(args.odom_frequency)
    if is_hotel:
        if args.controller_frequency is not None:
            if not 1.0 <= args.controller_frequency <= 100.0:
                parser.error("--controller-frequency must be between 1 and 100 Hz")
            env["PHASE5_TEST_CONTROLLER_FREQUENCY"] = str(args.controller_frequency)
        if args.nav_seconds is not None:
            if not 1.0 <= args.nav_seconds <= 20.0:
                parser.error("--nav-seconds must be between 1 and 20")
            env["PHASE5_TEST_NAV_SECONDS"] = str(args.nav_seconds)
        if args.scan_update_rate is not None:
            if not 1.0 <= args.scan_update_rate <= 30.0:
                parser.error("--scan-update-rate must be between 1 and 30 Hz")
            env["PHASE5_TEST_SCAN_UPDATE_RATE"] = str(args.scan_update_rate)
        if args.smoother_frequency is not None:
            if not 1.0 <= args.smoother_frequency <= 200.0:
                parser.error("--smoother-frequency must be between 1 and 200 Hz")
            env["PHASE5_TEST_SMOOTHER_FREQUENCY"] = str(args.smoother_frequency)
        env.update(
                   GZ_SIM_RESOURCE_PATH="/opt/ros2-demo/hotel-assets/models:/opt/ros2-demo/hotel-assets:/opt/rmf_demos_ws/install/share/rmf_demos_assets/models")
        if args.gpu_rendering:
            # EGL headless rendering on the allocated GPU: no X server (Xvfb
            # segfaults under the injected NVIDIA graphics libraries), no
            # forced software GL, and no llvmpipe thread pinning.
            env.update(PHASE5_HEADLESS_RENDERING="1", NVIDIA_DRIVER_CAPABILITIES="all")
        else:
            env.update(DISPLAY=":97", LIBGL_ALWAYS_SOFTWARE="1", LP_NUM_THREADS="4")
    fixture_command = "source /opt/ros/jazzy/setup.bash; source /opt/nav2-smoother-overlay/setup.bash; "
    if args.semantic_arm:
        # Both arms source the semantic-costmap overlay so the environment is
        # identical; the off arm simply does not configure the layer.
        fixture_command += "source /opt/semantic-costmap-overlay/local_setup.bash; "
    if args.tf2_poll_1ms:
        fixture_command += "source /opt/tf2-poll-overlay/local_setup.bash; "
    if cm_diagnostics:
        fixture_command += "source /opt/nav2-collision-monitor-overlay/local_setup.bash; "
    if args.controller_endpoint_capture:
        fixture_command += "source /opt/nav2-controller-overlay/local_setup.bash; "
    if args.bounded_cpu_contention:
        fixture_command += (
            "python3 /phase5-native/phase5_cpu_contention.py "
            "--pid-file /tmp/phase5-cpu-contention.pid & phase5_load_pid=$!; "
            "trap 'kill -TERM \"$phase5_load_pid\" 2>/dev/null || true; "
            "wait \"$phase5_load_pid\" 2>/dev/null || true' EXIT; "
        )
    else:
        fixture_command += "exec "
    fixture_command += "python3 /phase5-native/run_native_suite.py"
    containers = [{"name": "fixture", "image": args.image,
      "command": ["/bin/bash", "-ec"], "args": [fixture_command],
      "env": [{"name": k, "value": v} for k,v in env.items()],
      "volumeMounts": ([{"name": "source", "mountPath": "/phase5-native", "readOnly": True}]
                       + ([{"name": "sam3-shared", "mountPath": "/tmp/phase5-sam3-shared"}]
                          if args.sam3_observation else [])),
      "resources": {"requests": {"cpu": "2" if is_hotel else "1", "memory": "1Gi"}, "limits": {"cpu": "8" if is_hotel else "4", "memory": "5Gi" if is_hotel else "3Gi",
          **({"nvidia.com/gpu": 1} if args.gpu_rendering else {})}},
      "securityContext": {"runAsNonRoot": True, "allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}, "seccompProfile": {"type": "RuntimeDefault"}}}]
    if args.sam3_observation:
        # The trace-instrumented compressor and the scoped Zenoh bridge run
        # as sidecars in the fixture pod on the ISOLATED camera/semantic
        # domain (88), mirroring the Phase 6D D1 wiring: compressed camera
        # streams and traces flow out, semantic results flow back, and the
        # safety domain (85) carries only clock/odom/scan/TF and commands.
        # The observation worker runs as its OWN sidecar with its own CPU
        # quota: deserializing multi-megabyte clouds inside the fixture
        # container's shared quota raised the safety pump's stage latencies
        # and occasionally broke the lease authority chain mid-burst.
        sidecar_env = [{"name": k, "value": v} for k,v in {
            "ROS_DISTRO": "jazzy", "ROS_DOMAIN_ID": "88",
            "RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp",
            "CYCLONEDDS_URI": "file:///phase5-native/cyclonedds-phase5.xml"}.items()]
        containers.append({"name": "camera-compressor",
          "image": "image-registry.openshift-image-registry.svc:5000/semantic-navigation/semantic-hotel-sim@sha256:c3ba94bbcbbe2283f1c46ea0f2baba398da313ffe83d2b59a63272ef91d95ebf",
          "command": ["/bin/bash", "-lc"],
          "args": ["export HOME=/tmp/phase5-camera-home ROS_LOG_DIR=/tmp/phase5-camera-logs; "
                   "mkdir -p \"$ROS_LOG_DIR\"; source /opt/ros/jazzy/setup.bash; "
                   "exec python3 /opt/semantic-navigation/camera_compressor.py"],
          "env": sidecar_env + [{"name": k, "value": v} for k,v in {
              "SEMANTIC_RAW_INPUT": "gz", "SEMANTIC_COMPRESSION_TRACE": "1",
              "SEMANTIC_CAMERA_SUBSCRIPTION_DEPTH": "20",
              "GZ_PARTITION": "phase5-watchdog-native-qualification",
              "GZ_IP": "127.0.0.1"}.items()],
          "volumeMounts": [{"name": "source", "mountPath": "/phase5-native", "readOnly": True}],
          "resources": {"requests": {"cpu": "250m", "memory": "512Mi"},
                        "limits": {"cpu": "2", "memory": "2Gi"}},
          "securityContext": {"runAsNonRoot": True, "allowPrivilegeEscalation": False,
                              "capabilities": {"drop": ["ALL"]},
                              "seccompProfile": {"type": "RuntimeDefault"}}})
        containers.append({"name": "sam3-zenoh-bridge",
          "image": "eclipse/zenoh-bridge-ros2dds@sha256:38f162ae5236412f4f02e77927e22585356f7e706db39ec1c6194b9bd0d05b18",
          "args": ["-c", "/phase5-native/phase5-sam3-bridge.json5"],
          "env": sidecar_env,
          "volumeMounts": [{"name": "source", "mountPath": "/phase5-native", "readOnly": True}],
          "resources": {"requests": {"cpu": "100m", "memory": "128Mi"},
                        "limits": {"cpu": "500m", "memory": "512Mi"}},
          "securityContext": {"runAsNonRoot": True, "allowPrivilegeEscalation": False,
                              "capabilities": {"drop": ["ALL"]},
                              "seccompProfile": {"type": "RuntimeDefault"}}})
        if args.semantic_arm and not args.phase6_no_semantic_bridge:
            # Domain-85 semantic bridge: republishes ONLY the four semantic
            # streams the costmap layer consumes onto the SAFETY domain
            # (the costmaps live there with the guarded chain), through the
            # private router, in its own sidecar with its own CPU quota so
            # the multi-megabyte clouds never load the fixture container's
            # shared budget. Runs in BOTH arms so the topology and transport
            # load are identical; in the off arm nothing subscribes.
            containers.append({"name": "sam3-semantic-bridge",
              "image": "eclipse/zenoh-bridge-ros2dds@sha256:38f162ae5236412f4f02e77927e22585356f7e706db39ec1c6194b9bd0d05b18",
              "args": ["-c", "/phase5-native/phase6-semantic-bridge.json5"],
              "env": [{"name": k, "value": v} for k,v in {
                  "ROS_DISTRO": "jazzy", "ROS_DOMAIN_ID": "85",
                  "RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp",
                  "CYCLONEDDS_URI": "file:///phase5-native/cyclonedds-phase5.xml"}.items()],
              "volumeMounts": [{"name": "source", "mountPath": "/phase5-native", "readOnly": True}],
              "resources": {"requests": {"cpu": "100m", "memory": "128Mi"},
                            "limits": {"cpu": "500m", "memory": "512Mi"}},
              "securityContext": {"runAsNonRoot": True, "allowPrivilegeEscalation": False,
                                  "capabilities": {"drop": ["ALL"]},
                                  "seccompProfile": {"type": "RuntimeDefault"}}})
            # Label metadata relay: the ONLY publisher of label_info on the
            # safety domain, republishing the 88-chain's transient-local
            # latch verbatim for the costmap layers (see the allowlist note
            # above). Runs in BOTH arms so the topology is identical.
            containers.append({"name": "sam3-label-relay",
              "image": args.image,
              "command": ["/bin/bash", "-ec"],
              "args": ["export HOME=/tmp/phase6-relay-home ROS_LOG_DIR=/tmp/phase6-relay-logs; "
                       "mkdir -p \"$ROS_LOG_DIR\"; source /opt/ros/jazzy/setup.bash; "
                       "exec python3 /phase5-native/phase6_label_relay.py "
                       "--shared-dir /tmp/phase5-sam3-shared"],
              "env": [{"name": k, "value": v} for k,v in {
                  "ROS_DOMAIN_ID": "88", "ROS_DISTRO": "jazzy",
                  "RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp",
                  "CYCLONEDDS_URI": "file:///phase5-native/cyclonedds-phase5.xml",
                  "GZ_PARTITION": "phase5-watchdog-native-qualification",
                  "GZ_IP": "127.0.0.1"}.items()],
              "volumeMounts": [{"name": "source", "mountPath": "/phase5-native", "readOnly": True},
                               {"name": "sam3-shared", "mountPath": "/tmp/phase5-sam3-shared"}],
              "resources": {"requests": {"cpu": "100m", "memory": "256Mi"},
                            "limits": {"cpu": "500m", "memory": "1Gi"}},
              "securityContext": {"runAsNonRoot": True, "allowPrivilegeEscalation": False,
                                  "capabilities": {"drop": ["ALL"]},
                                  "seccompProfile": {"type": "RuntimeDefault"}}})
        if args.phase6_tf_probe:
            # Read-only /tf prober sidecar (pair-1-off-gcfix follow-up): a
            # disinterested third reader of the safety domain's /tf with its
            # own CPU quota, recording (stamp, arrival wall) rows to stdout.
            # Its log is retained as phase6-tf-prober.log. See
            # apps/semantic-safety/phase6_tf_prober.py for the contract.
            containers.append({"name": "phase6-tf-prober",
              "image": args.image,
              "command": ["/bin/bash", "-ec"],
              "args": ["export HOME=/tmp/phase6-tf-prober-home ROS_LOG_DIR=/tmp/phase6-tf-prober-logs; "
                       "mkdir -p \"$ROS_LOG_DIR\"; source /opt/ros/jazzy/setup.bash; "
                       "exec python3 /phase5-native/phase6_tf_prober.py"],
              "env": [{"name": k, "value": v} for k,v in {
                  "ROS_DOMAIN_ID": "85", "ROS_DISTRO": "jazzy",
                  "RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp",
                  "CYCLONEDDS_URI": "file:///phase5-native/cyclonedds-phase5.xml",
                  "GZ_PARTITION": "phase5-watchdog-native-qualification",
                  "GZ_IP": "127.0.0.1"}.items()],
              "volumeMounts": [{"name": "source", "mountPath": "/phase5-native", "readOnly": True}],
              "resources": {"requests": {"cpu": "100m", "memory": "128Mi"},
                            "limits": {"cpu": "500m", "memory": "512Mi"}},
              "securityContext": {"runAsNonRoot": True, "allowPrivilegeEscalation": False,
                                  "capabilities": {"drop": ["ALL"]},
                                  "seccompProfile": {"type": "RuntimeDefault"}}})
        if args.phase6_tf_witness:
            # Capture-time TF witness (user-approved 2026-10-28): subscribes
            # the same /robot_1/scan_fixed and /tf streams in its own
            # prompt, own-quota process and records capture-time transform
            # resolutions for the gate's tf lease through the shared
            # emptyDir. Fail-closed: staleness renews nothing. See
            # apps/semantic-safety/phase6_tf_witness.py for the contract.
            containers.append({"name": "phase6-tf-witness",
              "image": args.image,
              "command": ["/bin/bash", "-ec"],
              "args": ["export HOME=/tmp/phase6-tf-witness-home ROS_LOG_DIR=/tmp/phase6-tf-witness-logs; "
                       "mkdir -p \"$ROS_LOG_DIR\"; source /opt/ros/jazzy/setup.bash; "
                       "exec python3 /phase5-native/phase6_tf_witness.py"],
              "env": [{"name": k, "value": v} for k,v in {
                  "ROS_DOMAIN_ID": "85", "ROS_DISTRO": "jazzy",
                  "RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp",
                  "CYCLONEDDS_URI": "file:///phase5-native/cyclonedds-phase5.xml",
                  "GZ_PARTITION": "phase5-watchdog-native-qualification",
                  "GZ_IP": "127.0.0.1"}.items()],
              "volumeMounts": [{"name": "source", "mountPath": "/phase5-native", "readOnly": True},
                               {"name": "sam3-shared", "mountPath": "/tmp/phase5-sam3-shared"}],
              "resources": {"requests": {"cpu": "100m", "memory": "128Mi"},
                            "limits": {"cpu": "500m", "memory": "512Mi"}},
              "securityContext": {"runAsNonRoot": True, "allowPrivilegeEscalation": False,
                                  "capabilities": {"drop": ["ALL"]},
                                  "seccompProfile": {"type": "RuntimeDefault"}}})
        # Observation worker sidecar: its own CPU quota so cloud
        # deserialization can never squeeze the fixture container budget.
        # It polls the shared emptyDir for the fixture-written ground
        # truth and reports its aggregated state through the same volume.
        containers.append({"name": "sam3-observer",
          "image": args.image,
          "command": ["/bin/bash", "-ec"],
          "args": ["export HOME=/tmp/phase5-sam3-home ROS_LOG_DIR=/tmp/phase5-sam3-logs; "
                   "mkdir -p \"$ROS_LOG_DIR\"; source /opt/ros/jazzy/setup.bash; "
                   "exec python3 /phase5-native/sam3_observer_worker.py "
                   "--shared-dir /tmp/phase5-sam3-shared"],
          "env": sidecar_env + [{"name": "GZ_PARTITION", "value": "phase5-watchdog-native-qualification"},
                                {"name": "GZ_IP", "value": "127.0.0.1"}],
          "volumeMounts": [{"name": "source", "mountPath": "/phase5-native", "readOnly": True},
                           {"name": "sam3-shared", "mountPath": "/tmp/phase5-sam3-shared"}],
          "resources": {"requests": {"cpu": "500m", "memory": "1Gi"},
                        "limits": {"cpu": "2", "memory": "3Gi"}},
          "securityContext": {"runAsNonRoot": True, "allowPrivilegeEscalation": False,
                              "capabilities": {"drop": ["ALL"]},
                              "seccompProfile": {"type": "RuntimeDefault"}}})
    pod = {"apiVersion": "v1", "kind": "Pod", "metadata": metadata, "spec": {
        **({"nodeSelector":{"kubernetes.io/hostname":args.node_name}} if args.node_name else {}),
        **({"tolerations":[{"key":"g5-gpu","operator":"Equal","value":"true","effect":"NoSchedule"}]}
           if args.allow_g5_node else {}),
        **({"tolerations":[
                {"key":"g5-gpu","operator":"Equal","value":"true","effect":"NoSchedule"},
                {"key":"g6e-gpu","operator":"Equal","value":"true","effect":"NoSchedule"}]}
           if args.gpu_rendering else {}),
        "restartPolicy": "Never",
        "activeDeadlineSeconds": (1000 if args.semantic_fault_probe
                                  else 700 if args.semantic_arm
                                  else 420 if is_hotel else 300),
        "automountServiceAccountToken": False,
        "containers": containers,
        "volumes": ([{"name": "source", "configMap": {"name": NAME}}]
                    + ([{"name": "sam3-shared", "emptyDir": {}}] if args.sam3_observation else []))}}
    (args.output_dir / "manifest.yaml").write_text(yaml.safe_dump_all([config,pod], sort_keys=False))
    (args.output_dir / "source-hashes.json").write_text(json.dumps({k: hashlib.sha256(v.encode()).hexdigest() for k,v in data.items()}, indent=2))
    created = []
    try:
        for obj in (config,pod):
            oc("create", "-f", "-", input=yaml.safe_dump(obj))
            created.append(obj["kind"].lower())
        deadline = time.monotonic()+(960 if args.semantic_fault_probe
                                     else 660 if args.semantic_arm
                                     else 360 if is_hotel else 240)
        while time.monotonic()<deadline:
            state = json.loads(oc("get", "pod", NAME, "-o", "json").stdout)
            if state["status"]["phase"] == "Running":
                result = exec_fixture("--","cat","/tmp/phase5-suite.json",check=False)
                if result.returncode == 0:
                    break
            if state["status"]["phase"] in ("Failed", "Succeeded"):
                raise RuntimeError("pod ended before evidence retrieval")
            time.sleep(2)
        else:
            raise TimeoutError("native fixture did not finish")
        (args.output_dir / "suite.json").write_text(result.stdout)
        if args.bounded_cpu_contention:
            stop_command = (
                "test -s /tmp/phase5-cpu-contention.pid && "
                "kill -TERM \"$(cat /tmp/phase5-cpu-contention.pid)\""
            )
            stop_result = exec_fixture("--","bash","-ec",stop_command,check=False)
            stop_evidence = {"returncode": stop_result.returncode,
                             "stdout": stop_result.stdout, "stderr": stop_result.stderr}
            if stop_result.returncode:
                (args.output_dir / "cpu-contention-stop.json").write_text(
                    json.dumps(stop_evidence, indent=2))
                raise RuntimeError("bounded CPU contention helper did not accept stop request")
            stop_deadline = time.monotonic() + 8.0
            while time.monotonic() < stop_deadline:
                log_result = logs_fixture(check=False)
                if '"state": "stopped"' in log_result.stdout:
                    stop_evidence["stopped_record_seen"] = True
                    (args.output_dir / "cpu-contention-stop.json").write_text(
                        json.dumps(stop_evidence, indent=2))
                    break
                time.sleep(0.2)
            else:
                stop_evidence["stopped_record_seen"] = False
                (args.output_dir / "cpu-contention-stop.json").write_text(
                    json.dumps(stop_evidence, indent=2))
                raise RuntimeError("bounded CPU contention helper did not stop cleanly")
        (args.output_dir / "pod.json").write_text(json.dumps(state, indent=2))
        # The evidence copy can transiently fail with an unexpected EOF when
        # it races the fixture's own teardown (the tar stream truncates while
        # the container's processes exit — pair-1-on-lethal254-grace4 lost a
        # PASSING trial's main copy to exactly this; the retry landed cleanly
        # because the pod outlives the wrapper by minutes).
        copied = cp_fixture(args.output_dir / "runtime",check=False)
        if copied.returncode:
            time.sleep(5)
            copied = cp_fixture(args.output_dir / "runtime",check=False)
        (args.output_dir / "copy-result.json").write_text(json.dumps({"returncode": copied.returncode, "stderr": copied.stderr}))
        pins = "source /opt/ros/jazzy/setup.bash; source /opt/nav2-smoother-overlay/setup.bash; ros2 pkg prefix nav2_velocity_smoother; git -c safe.directory=/opt/nav2-smoother-src -C /opt/nav2-smoother-src rev-parse HEAD; sha256sum /opt/nav2-smoother-overlay/lib/nav2_velocity_smoother/velocity_smoother /opt/semantic-safety/lib/libphase5_drive_watchdog.so /opt/semantic-safety/lib/libgz-sim-sensors-system.so /opt/semantic-safety/src/native/* /opt/nav2-smoother-src/nav2_velocity_smoother/src/velocity_smoother.cpp"
        if args.controller_endpoint_capture:
            pins += " /opt/nav2-controller-overlay/lib/nav2_controller/controller_server /opt/nav2-controller-overlay/lib/libcontroller_server_core.so /opt/nav2-smoother-src/nav2_controller/src/controller_server.cpp /opt/semantic-safety/nav2_controller-goal-capture.patch"
        if is_hotel:
            pins += " /opt/semantic-safety/bin/phase5_command_observer"
        if args.contact_audit or args.suite=="contacts":
            pins += " /opt/semantic-safety/lib/libphase5_contact_audit.so"
        if args.console_only_server:
            pins += " /opt/semantic-safety/bin/phase5_console_server /opt/semantic-safety/console-launcher/*"
        if cm_diagnostics:
            pins += " /opt/nav2-collision-monitor-overlay/lib/nav2_collision_monitor/collision_monitor /opt/nav2-collision-monitor-overlay/lib/libcollision_monitor_core.so /opt/nav2-smoother-src/nav2_collision_monitor/src/collision_monitor_node.cpp /opt/nav2-smoother-src/nav2_collision_monitor/src/source.cpp /opt/semantic-safety/instrument_nav2_collision_monitor.py"
        if args.tf2_poll_1ms:
            pins = pins.replace("source /opt/nav2-smoother-overlay/setup.bash; ",
                "source /opt/nav2-smoother-overlay/setup.bash; source /opt/tf2-poll-overlay/local_setup.bash; ros2 pkg prefix tf2_ros; ",1)
            pins += " /opt/tf2-poll-overlay/lib/libtf2_ros.so /opt/geometry2-src/tf2_ros/src/buffer.cpp /opt/semantic-safety/patch_tf2_polling.py"
        elif edge_probe:
            pins = pins.replace("source /opt/nav2-smoother-overlay/setup.bash; ",
                "source /opt/nav2-smoother-overlay/setup.bash; ros2 pkg prefix tf2_ros; ",1)
            pins += " /opt/ros/jazzy/lib/libtf2_ros.so"
        pins += "; dpkg-query -W libgz-sim8 libgz-transport13 ros-jazzy-rclpy ros-jazzy-rclcpp ros-jazzy-nav2-controller ros-jazzy-nav2-util ros-jazzy-tf2 ros-jazzy-tf2-ros"
        if args.sam3_observation:
            pins += "; sha256sum /opt/semantic-safety/capture-lib/libgz-sensors8-rgbd_camera.so.8; dpkg-query -W libgz-sensors8"
        if args.semantic_arm:
            pins += ("; source /opt/semantic-costmap-overlay/local_setup.bash; "
                     "ros2 pkg prefix demo_semantic_costmap; "
                     "sha256sum /opt/semantic-costmap-overlay/lib/libdemo_semantic_costmap.so")
        if args.console_only_server: pins="set -e; "+pins
        pin_result = exec_fixture("--","bash","-c",pins,check=False)
        (args.output_dir / "installed-pins.txt").write_text(pin_result.stdout+pin_result.stderr)
        if args.console_only_server and pin_result.returncode:
            raise RuntimeError("console candidate installed-pin capture failed")
        cpu = exec_fixture("--","cat","/sys/fs/cgroup/cpu.stat","/sys/fs/cgroup/cpu.max",check=False)
        (args.output_dir / "cpu-cgroup.txt").write_text(cpu.stdout+cpu.stderr)
        if any(r["returncode"] for r in json.loads(result.stdout)) or copied.returncode:
            raise RuntimeError("native fixture failed; retained evidence")
        print(json.dumps({"passed": True, "evidence": str(args.output_dir)}))
    finally:
        if "pod" in created:
            if not (args.output_dir / "pod.json").exists():
                state = oc("get", "pod", NAME, "-o", "json", check=False)
                (args.output_dir / "pod.json").write_text(state.stdout)
            result = logs_fixture(check=False)
            (args.output_dir / "test.log").write_text(result.stdout+result.stderr)
            if args.sam3_observation:
                # Retain the observation sidecar logs: a broken compressor or
                # bridge otherwise leaves no evidence after pod deletion.
                sidecar_logs = [("camera-compressor", "camera-compressor.log"),
                                ("sam3-zenoh-bridge", "sam3-zenoh-bridge.log"),
                                ("sam3-observer", "sam3-observer.log")]
                if args.semantic_arm:
                    sidecar_logs.append(("sam3-semantic-bridge", "sam3-semantic-bridge.log"))
                    sidecar_logs.append(("sam3-label-relay", "sam3-label-relay.log"))
                if args.phase6_tf_probe:
                    sidecar_logs.append(("phase6-tf-prober", "phase6-tf-prober.log"))
                if args.phase6_tf_witness:
                    sidecar_logs.append(("phase6-tf-witness", "phase6-tf-witness.log"))
                for container, name in sidecar_logs:
                    sidecar = oc("logs", NAME, "--container", container, check=False)
                    (args.output_dir / name).write_text(sidecar.stdout+sidecar.stderr)
            if not (args.output_dir / "runtime/summary.json").is_file():
                # The fixture died before finishing (suite-wrapper timeout,
                # pod deadline, crash): retain whatever partial evidence it
                # had written — the coordinator status file and any partial
                # artifacts are the only record of where it hung.
                partial = cp_fixture(args.output_dir / "runtime-partial", check=False)
                (args.output_dir / "runtime-partial-copy.json").write_text(
                    json.dumps({"returncode": partial.returncode, "stderr": partial.stderr}))
        cleanup = []
        for kind in reversed(created):
            result = oc("delete", kind, NAME, "--wait=true", "--timeout=35s", check=False)
            cleanup.append({"kind": kind, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
        (args.output_dir / "cleanup.json").write_text(json.dumps(cleanup, indent=2))


if __name__ == "__main__":
    main()
