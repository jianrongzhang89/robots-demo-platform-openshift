#!/usr/bin/env python3
"""Fixed ten-trial private baseline or recovery series; no automatic retries."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def trial_passed(evidence, returncode, *, recovery_probe=False, controller_endpoint_capture=False,
                 console_only_server=False):
    required={"baseline_contact_window", "baseline_native_stop_metrics"}
    if recovery_probe:
        required.update(("guarded_recovery_probe_terminal",
            "guarded_backup_and_wait_actions_completed", "backup_reverse_commands_bounded",
            "wait_interval_native_applied_velocity_zero", "wait_zero_holds_are_bounded_and_continuous",
            "independent_native_motion_observed"))
    if controller_endpoint_capture:
        required.add("opt_in_controller_overlay_loaded")
    if console_only_server:
        required.update(("console_server_preflight","console_server_identity",
            "console_server_recording_absent_before_arm","console_server_recording_absent",
            "console_server_shutdown"))
        if evidence.get("console_only_server") is not True or evidence.get("world_recording") is not False:
            return False
    checks={c["case"]:c for c in evidence.get("checks",[])}
    return (returncode==0 and evidence.get("passed") is True
            and not evidence.get("diagnostic_only",False)
            and all(checks.get(name,{}).get("passed") is True for name in required)
            and all(c.get("passed") is True for c in evidence.get("checks",[])))


def placement_error(recovery_probe, node_name, require_non_gpu_node, gpu_rendering=False):
    if require_non_gpu_node and gpu_rendering:
        return "--gpu-rendering cannot combine with --require-non-gpu-node"
    if require_non_gpu_node and not node_name:
        return "--require-non-gpu-node requires --node-name"
    if gpu_rendering and not node_name:
        return "--gpu-rendering requires --node-name pinned to a GPU worker"
    if recovery_probe and not node_name:
        return "--recovery-probe requires a pinned node (--node-name)"
    if recovery_probe and not (require_non_gpu_node or gpu_rendering):
        return "--recovery-probe requires --node-name with --require-non-gpu-node or --gpu-rendering"
    return None


def placement_args(node_name, require_non_gpu_node, gpu_rendering=False):
    flags = ["--node-name", node_name] if node_name else []
    if require_non_gpu_node:
        flags.append("--require-non-gpu-node")
    if gpu_rendering:
        flags.append("--gpu-rendering")
    return flags


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oc",default="oc")
    parser.add_argument("--image",required=True)
    parser.add_argument("--output-dir",type=Path,required=True)
    parser.add_argument("--rear-casters",action="store_true",help="use the separately qualified private support candidate")
    parser.add_argument("--physics-step",type=float,choices=(.001,.002,.01))
    parser.add_argument("--lidar-range",type=float,choices=(3.5,12.))
    parser.add_argument("--odom-frequency",type=float,choices=(50.,200.))
    parser.add_argument("--recovery-probe",action="store_true",
                        help="separate fixed BackUp/Wait/FollowPath series; not the one-meter baseline")
    parser.add_argument("--controller-endpoint-capture",action="store_true")
    parser.add_argument("--console-only-server",action="store_true")
    parser.add_argument("--node-name",help="pin every trial to one Kubernetes hostname")
    parser.add_argument("--require-non-gpu-node",action="store_true",
                        help="require the pinned moving-trial node to be Ready and GPU-free")
    parser.add_argument("--gpu-rendering",action="store_true",
                        help="pin every trial to a GPU worker and render the RGB-D camera through EGL on the allocated GPU")
    args=parser.parse_args()
    error=placement_error(args.recovery_probe,args.node_name,args.require_non_gpu_node,args.gpu_rendering)
    if error:
        parser.error(error)
    root=Path(__file__).resolve().parents[2]
    args.output_dir.mkdir(parents=True,exist_ok=False)
    # Freeze all runtime inputs for the entire series, not merely the image.
    files=sorted((root/"apps/semantic-safety").glob("*.py"))+[
        root/"apps/semantic-safety/phase5-baseline.xml",root/"helm/semantic-navigation/phase5-nav2-candidate.yaml",
        root/"scripts/semantic-navigation/run_phase5_native.py",root/"scripts/semantic-navigation/install_phase1_camera.py",
        root/"scripts/semantic-navigation/run_phase5_baseline.py"]
    if args.recovery_probe: files.append(root/"apps/semantic-safety/phase5-recovery-probe.xml")
    if args.console_only_server:
        files.extend(sorted((root/"apps/semantic-safety/console-launcher").glob("*")))
        files.append(root/"apps/semantic-safety/Containerfile.console")
    hashes=lambda:{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    frozen=hashes()
    scenario=("fresh-world BackUp 0.10 m / Wait 1 s / FollowPath to 0.50 m target"
              if args.recovery_probe else "fresh-world one-meter straight target")
    plan={"image":args.image,"planned_trials":10,"scenario":scenario,
          "recovery_probe":args.recovery_probe,
          "controller_endpoint_capture":args.controller_endpoint_capture,
          "console_only_server":args.console_only_server,
          "node_name":args.node_name,
          "require_non_gpu_node":args.require_non_gpu_node,
          "world_recording":not args.console_only_server,
          "contact_audit":True,"rear_casters":args.rear_casters,
          "physics_step":args.physics_step,"lidar_range":args.lidar_range,
          "odom_frequency":args.odom_frequency,
          "retry_policy":"none; stop series on first failure","source_hashes":frozen}
    (args.output_dir/"plan.json").write_text(json.dumps(plan,indent=2))
    results=[]
    for trial in range(1,11):
        if hashes()!=frozen: raise RuntimeError("runtime inputs changed during fixed series")
        directory=args.output_dir/f"trial-{trial:02d}"
        print(json.dumps({"event":"trial_started","trial":trial}),flush=True)
        command=[sys.executable,str(root/"scripts/semantic-navigation/run_phase5_native.py"),
            "--oc",args.oc,"--suite","hotel-guarded","--contact-audit","--image",args.image,
            "--output-dir",str(directory)]
        command.extend(placement_args(args.node_name,args.require_non_gpu_node,args.gpu_rendering))
        if args.rear_casters: command.append("--rear-casters")
        if args.recovery_probe: command.append("--recovery-probe")
        if args.controller_endpoint_capture: command.append("--controller-endpoint-capture")
        if args.console_only_server: command.append("--console-only-server")
        if args.physics_step is not None: command.extend(("--physics-step",str(args.physics_step)))
        if args.lidar_range is not None: command.extend(("--lidar-range",str(args.lidar_range)))
        if args.odom_frequency is not None: command.extend(("--odom-frequency",str(args.odom_frequency)))
        run=subprocess.run(command)
        path=directory/"runtime/summary.json"
        evidence=json.loads(path.read_text()) if path.is_file() else {}
        passed=trial_passed(evidence,run.returncode,recovery_probe=args.recovery_probe,
                            controller_endpoint_capture=args.controller_endpoint_capture,
                            console_only_server=args.console_only_server)
        if hashes()!=frozen:
            passed=False
        results.append({"trial":trial,"passed":passed,"returncode":run.returncode,"evidence":str(path)})
        summary={"passed":len(results)==10 and all(r["passed"] for r in results),
                 "planned":10,"attempted":len(results),"succeeded":sum(r["passed"] for r in results),
                 "results":results,"scope":("BackUp/Wait/FollowPath geometry-only recovery repeatability; not full Phase 5"
                     if args.recovery_probe else "straight no-recovery geometry-only baseline; not full Phase 5")}
        (args.output_dir/"summary.json").write_text(json.dumps(summary,indent=2))
        print(json.dumps({"event":"trial_finished",**results[-1]}),flush=True)
        if not passed: raise RuntimeError("baseline series failed; no automatic retry")


if __name__=="__main__": main()
