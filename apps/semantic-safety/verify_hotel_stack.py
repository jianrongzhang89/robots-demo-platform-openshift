"""Actual hotel sensor/Nav2 graph qualification, disarmed by default.

Native guard is never armed. No lease publisher, transport worker, command
bridge, RMF dispatcher or synthetic sensor publisher exists in this process.
A short actual NavigateToPose action exercises the command chain while the
robot remains physically disarmed; this is not a navigation success trial.
PHASE5_SUITE=hotel-guarded explicitly selects a private moving integration
subgate through HotelGuardAdapter; never a canonical deployment.
"""
import hashlib
import json
import xml.etree.ElementTree as ET
import collections
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
import traceback

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.executors import SingleThreadedExecutor
from rclpy.qos import (DurabilityPolicy, QoSProfile, ReliabilityPolicy,
                       qos_profile_sensor_data)
from rclpy.time import Time
from geometry_msgs.msg import PoseWithCovarianceStamped, TwistStamped, PointStamped
from lifecycle_msgs.srv import ChangeState, GetState
from nav2_msgs.action import ComputePathToPose, NavigateToPose
from nav2_msgs.msg import CollisionMonitorState
from nav2_msgs.srv import GetCostmap
from nav_msgs.msg import Odometry, Path as NavPath
from rosgraph_msgs.msg import Clock
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String, Bool
from tf2_ros import Buffer, TransformListener
from gz.transport13 import Node as GzNode
from gz.msgs10.stringmsg_pb2 import StringMsg
from gz.msgs10.image_pb2 import Image as GzImage
import yaml
from rosidl_runtime_py.utilities import get_message

from command_ledger import CommandLedger
from capture_joiner import CaptureJoiner
from command_audit import validate_graph, validate_observations, validate_publisher_binding
from install_phase1_camera import add_camera, add_phase2_targets, add_phase6_render_warmup
from native_clock import NativeClock
from prepare_assets import write_assets
from safety_core import Now
from hotel_guard_adapter import HotelGuardAdapter
from contact_evidence import instrument, assess, support_pairs, collision_inventory
from baseline_metrics import metrics
from support_geometry import add_rear_casters
from priority_pump import StageTimings, audit_timing, pump_round
from wait_metrics import wait_zero_metrics
from console_evidence import EXECUTABLE as CONSOLE_SERVER, identity as console_identity, recording_absent, validate_world, lifecycle_complete
from console_server_smoke import verify as verify_console_server
from process_shutdown import shutdown, gazebo_stop, timeout_snapshot
from tf_fault_probe import map_failure, stop_reason_qualified
from tf_fault_buffer import ProbeTfBuffer
from phase5_timing_profile import moving_trace_geometry_matches
from fault_stop_probe import (MODES as FAULT_STOP_MODES,
    stop_reason_qualified as fault_stop_reason_qualified,
    stop_wait_seconds as fault_stop_wait_seconds,
    stop_latency_floor_ms as fault_stop_latency_floor_ms, obstacle_spawn_pose,
    obstacle_staging_pose, OBSTACLE_POST_MODEL, OBSTACLE_NAME,
    OBSTACLE_AHEAD_M, OBSTACLE_LATERAL_M)
from sam3_observation import (decode_mask, decode_points_xyz,
    MAT_MODEL, parse_mat_ground_truth, points_in_rectangle, registration_summary,
    timing_summary, transform_points)
from phase6_semantic_checks import (MAT_SURFACE_Z, SOFT_COST, cells_in_rectangle,
    clearance_bound_s, grid_cost_cells, mat_removal_pose, normalize_grid,
    semantic_costs_at_target, smoke_registration_summary)
from semantic_fault_probe import observation_window


def ns(stamp):
    return stamp.sec*1_000_000_000+stamp.nanosec


class WaitTimeout(RuntimeError):
    pass


def main():
    if (os.getenv("ROS_DOMAIN_ID") != "85" or os.getenv("GZ_IP") != "127.0.0.1"
            or not os.getenv("GZ_PARTITION", "").startswith("phase5-watchdog-")):
        raise RuntimeError("isolated private hotel only")
    # The cyclic garbage collector is disabled for the fixture's lifetime.
    # A gen-2 collection over the evidence/message heap stalls the pump for
    # tens of milliseconds at allocation-deterministic moments (pilot-1
    # off-arm, pair-1-off-joindiag-2: a single 53.4 ms observer-stage pause
    # ended 6 ms after the command_expired trip; the in-window checked
    # renewal sat unprocessed in the joiner through the same pause and
    # expired in its 20 ms window). The 20 ms join window and the 100 ms
    # command deadline cannot absorb interpreter-level pauses. Reference
    # counting still frees every acyclic object; the private fixture runs
    # for minutes, not hours, and its pod is torn down afterwards.
    import gc
    gc.disable()
    root = Path(__file__).resolve().parent
    guarded = os.getenv("PHASE5_SUITE") == "hotel-guarded"
    contact_audit = os.getenv("PHASE5_CONTACT_AUDIT") == "1"
    rear_casters = os.getenv("PHASE5_REAR_CASTERS") == "1"
    recovery_probe = os.getenv("PHASE5_RECOVERY_PROBE") == "1"
    controller_endpoint_capture = os.getenv("PHASE5_CONTROLLER_ENDPOINT_CAPTURE") == "1"
    record_period=os.getenv("PHASE5_DIAGNOSTIC_RECORD_PERIOD")
    no_world_recording=os.getenv("PHASE5_DIAGNOSTIC_NO_WORLD_RECORDING")=="1"
    api_world_recording=os.getenv("PHASE5_DIAGNOSTIC_API_WORLD_RECORDING")=="1"
    api_server=no_world_recording or api_world_recording
    console_only_server=os.getenv("PHASE5_CONSOLE_ONLY_SERVER")=="1"
    collision_monitor_diagnostics=os.getenv("PHASE5_COLLISION_MONITOR_DIAGNOSTICS")=="1"
    moving_timing_trace=os.getenv("PHASE5_MOVING_TIMING_TRACE")=="1"
    gz_thread_probe=os.getenv("PHASE5_GZ_THREAD_PROBE")=="1"
    headless_rendering=os.getenv("PHASE5_HEADLESS_RENDERING")=="1"
    if collision_monitor_diagnostics and ((guarded and not moving_timing_trace) or not console_only_server):
        raise RuntimeError("Collision Monitor timing instrumentation requires the disarmed fixture or explicit guarded moving trace")
    if moving_timing_trace and not (guarded and recovery_probe and contact_audit and rear_casters
            and console_only_server and not api_server):
        raise RuntimeError("moving timing trace requires the private guarded recovery/contact-audit console fixture")
    if moving_timing_trace and not (
            collision_monitor_diagnostics
            and os.getenv("PHASE5_TF_EDGE_PROBE") == "1"
            and os.getenv("PHASE5_TF_PRODUCER_TRACE") == "1"
            and os.getenv("PHASE5_TF_LOG_THRESHOLD_US") == "1000"
            and os.getenv("PHASE5_TF2_POLL_1MS") != "1"
            and os.getenv("PHASE5_BOUNDED_CPU_CONTENTION") != "1"):
        raise RuntimeError("moving timing trace requires stock TF2, source/target edge and producer probes, and a 1000 us diagnostic threshold")
    if console_only_server and (not contact_audit or api_server or record_period is not None):
        raise ValueError("console candidate requires contact evidence without recording diagnostics")
    if api_server and (record_period is not None or no_world_recording and api_world_recording):
        raise ValueError("recording experiments must be separate")
    if record_period is not None and float(record_period) not in (.1,3600.):
        raise ValueError("unqualified diagnostic recording period")
    if controller_endpoint_capture and not guarded:
        raise RuntimeError("controller candidate is private guarded only")
    tf_loss_probe = os.getenv("PHASE5_TF_LOSS_PROBE") == "1"
    tf_loss_mode=os.getenv("PHASE5_TF_LOSS_MODE","amcl")
    if tf_loss_mode not in ("amcl","supervisor"):
        raise ValueError("unknown TF-loss mode")
    if tf_loss_probe and (not guarded or recovery_probe):
        raise RuntimeError("TF-loss probe requires the private guarded baseline tree")
    fault_stop_probe = os.getenv("PHASE5_FAULT_STOP_PROBE") == "1"
    fault_stop_mode = os.getenv("PHASE5_FAULT_STOP_MODE", "")
    if fault_stop_mode and not fault_stop_probe:
        raise ValueError("fault-stop mode requires the fault-stop probe")
    if fault_stop_probe and fault_stop_mode not in FAULT_STOP_MODES:
        raise ValueError("unknown fault-stop mode")
    if fault_stop_probe and (not guarded or recovery_probe or tf_loss_probe):
        raise RuntimeError("fault-stop probe requires the private guarded baseline tree alone")
    if fault_stop_probe and fault_stop_mode == "obstacle_spawn" and not contact_audit:
        raise ValueError("obstacle fault-stop trials require contact evidence")
    sam3_observation = os.getenv("PHASE5_SAM3_OBSERVATION") == "1"
    served_topology = os.getenv("PHASE5_SERVED_TOPOLOGY") == "1"
    if sam3_observation and (not guarded or (not served_topology and (recovery_probe or tf_loss_probe or fault_stop_probe))):
        raise RuntimeError("SAM3 observation requires the private guarded baseline tree alone")
    if sam3_observation and not contact_audit:
        raise ValueError("SAM3 observation trials require contact evidence")
    semantic_fault_probe = os.getenv("PHASE5_SEMANTIC_FAULT_PROBE") == "1"
    semantic_fault_mode = os.getenv("PHASE5_SEMANTIC_FAULT_MODE", "")
    if semantic_fault_mode and not semantic_fault_probe:
        raise ValueError("semantic fault mode requires the semantic fault probe")
    if semantic_fault_probe:
        from semantic_fault_probe import MODES, SERVED_MODES
        SEMANTIC_FAULT_MODES = MODES + (SERVED_MODES if os.getenv("PHASE5_SERVED_TOPOLOGY") == "1" else ())
        from semantic_fault_probe import ARMING_STREAK_S as SEMANTIC_ARMING_STREAK_S
        if semantic_fault_mode not in SEMANTIC_FAULT_MODES:
            raise ValueError("unknown semantic fault mode")
        if not sam3_observation:
            raise ValueError("the semantic fault matrix requires the SAM3 observation topology")
        if recovery_probe or tf_loss_probe or fault_stop_probe:
            raise ValueError("the semantic fault matrix runs alone")
    # Phase 6 paired-trial arm: "off" keeps the Phase 5 guarded candidate
    # (semantic costs excluded, SAM3 observation-only); "on" adds ONLY the
    # fixed-policy soft-cost semantic layer to both costmaps of the same
    # guarded profile. The stationary smoke is a disarmed semantic-on wiring
    # and target-removal clearing check; no goal is dispatched.
    phase6_semantic_arm = os.getenv("PHASE6_SEMANTIC_ARM", "")
    phase6_stationary_smoke = os.getenv("PHASE6_STATIONARY_SMOKE") == "1"
    phase6_diagnostic_no_85_bridge = os.getenv("PHASE6_DIAGNOSTIC_NO_85_BRIDGE") == "1"
    # Diagnostic only (pair-1-off-gcfix follow-up): enables the frame-bridge
    # TF producer trace and the read-only /tf prober sidecar to localize the
    # mat-close /tf delivery delay. Never changes a gate or threshold.
    phase6_tf_probe = os.getenv("PHASE6_TF_PROBE") == "1"
    if phase6_tf_probe and not phase6_semantic_arm:
        raise RuntimeError("the Phase 6 TF probe is a Phase 6 arm diagnostic")
    # Opt-in diagnostic only (pair-1-on-bleedmap lesson): the mid-trial
    # cost-cells timeline blocks the pump 33-42 ms per poll — never run it
    # in a trial whose timing matters. The bleed data is already captured.
    phase6_cost_cells_timeline = os.getenv("PHASE6_COST_CELLS_TIMELINE") == "1"
    if phase6_cost_cells_timeline and not phase6_semantic_arm:
        raise RuntimeError("the cost-cells timeline is a Phase 6 arm diagnostic")
    # User-approved remedy (October 28, 2026) for the mat-close tf starvation:
    # the capture-time TF witness sidecar feeds the gate's tf lease from its
    # own (prompt, own-quota) process — the same fail-closed evidence()
    # path, clock bound and 500 ms freshness; a stale or missing witness
    # record renews nothing. Mirrors the qualified UDP companion path.
    phase6_tf_witness = os.getenv("PHASE6_TF_WITNESS") == "1"
    if phase6_tf_witness and not phase6_semantic_arm:
        raise RuntimeError("the Phase 6 TF witness is a Phase 6 arm companion")
    # The implementation plan's lethal-cost exclusion experiment ("Evaluate
    # lethal cost 254 as a separate exclusion experiment. A model-only
    # restriction is not a production safety boundary."): the on-arm
    # candidate carries target_cost 254 instead of the qualified soft cost
    # 200. Experiment only — never a production boundary.
    phase6_lethal_experiment = os.getenv("PHASE6_LETHAL_EXPERIMENT") == "1"
    if phase6_lethal_experiment and phase6_semantic_arm != "on":
        raise RuntimeError("the lethal-cost exclusion experiment is a semantic-on arm experiment")
    # Phase 6 series negative cases (the plan's verification: "plus
    # target-absent, target-removal, and perception-failure cases").
    # target_absent: the staged mat is omitted from the private world; the
    # scene's completion must not regress (the on arm plans and crosses the
    # would-be location with no semantic cells — recorded as a diagnostic,
    # not gated: false positives are the Phase 2 recognition waiver's
    # territory). target_removal: the mat is removed mid-trial through the
    # pre-warmed mover once the robot is under way; completion must not
    # regress (the stale cells clear by the Phase 4 expiry contract).
    phase6_target_absent = os.getenv("PHASE6_TARGET_ABSENT") == "1"
    phase6_target_removal = os.getenv("PHASE6_TARGET_REMOVAL") == "1"
    if (phase6_target_absent or phase6_target_removal) and not phase6_semantic_arm:
        raise RuntimeError("the Phase 6 negative-scene cases are Phase 6 arm trials")
    if phase6_target_absent and phase6_target_removal:
        raise ValueError("the negative-scene cases run as separate trials")
    if phase6_target_absent and phase6_stationary_smoke:
        raise ValueError("the stationary smoke requires the staged target")
    if phase6_semantic_arm:
        if phase6_semantic_arm not in ("off", "on"):
            raise ValueError("unknown Phase 6 semantic arm")
        if not (guarded and sam3_observation and console_only_server and contact_audit):
            raise RuntimeError("Phase 6 semantic arms require the guarded SAM3-observation "
                               "console fixture with contact evidence")
        if recovery_probe or tf_loss_probe or fault_stop_probe:
            raise RuntimeError("Phase 6 semantic arms run as their own trials")
        # The semantic fault probe is the ALLOWED companion for the series'
        # perception-failure case: the phase6 arm runs with the armed-semantic
        # supervisor (require_semantics) and the Phase 5 fault-stop criteria
        # checks — camera_path_loss/tf_loss inject in-fixture, the external
        # modes arrive through the coordinator status file as in the matrix.
        if semantic_fault_probe and not sam3_observation:
            raise RuntimeError("the perception-failure case requires the SAM3 topology")
        if not headless_rendering:
            raise RuntimeError("Phase 6 semantic arms run on the frozen guarded GPU-rendering profile")
        if phase6_stationary_smoke and phase6_semantic_arm != "on":
            raise ValueError("the Phase 6 stationary smoke is a semantic-on wiring check")
    elif phase6_stationary_smoke:
        raise ValueError("the Phase 6 stationary smoke requires PHASE6_SEMANTIC_ARM=on")
    if rear_casters and not contact_audit: raise RuntimeError("caster candidate requires contact audit")
    allowed_pairs=support_pairs(rear_casters)
    expected_collisions=collision_inventory(rear_casters)
    output = Path("/tmp/phase5-native-results"); output.mkdir(exist_ok=False)
    # Native-link send-path instrumentation (see native_link.py): retained in
    # the copied runtime evidence, so any future watchdog lease expiry is
    # attributable to a sender stall, a dropped renewal or a near-zero
    # command-boundary window.
    os.environ.setdefault("PHASE5_NATIVE_LINK_LOG", str(output/"native-link-sends.jsonl"))
    scan_update_rate=float(os.getenv("PHASE5_TEST_SCAN_UPDATE_RATE","10" if guarded else "5"))
    if not math.isfinite(scan_update_rate) or not 1.0<=scan_update_rate<=30.0:
        raise ValueError("diagnostic lidar update rate must be in [1, 30] Hz")
    physics_step=os.getenv("PHASE5_PHYSICS_STEP")
    lidar_range=os.getenv("PHASE5_LIDAR_RANGE")
    odom_frequency=os.getenv("PHASE5_ODOM_FREQUENCY")
    if moving_timing_trace and not moving_trace_geometry_matches(
            physics_step,lidar_range,odom_frequency):
        raise RuntimeError("moving timing trace requires 2 ms physics, 12 m virtual lidar and 200 Hz odometry")
    if fault_stop_probe:
        if not console_only_server:
            raise RuntimeError("fault-stop probe requires the qualified console-only moving fixture")
        if not moving_trace_geometry_matches(physics_step,lidar_range,odom_frequency):
            raise RuntimeError("fault-stop probe requires 2 ms physics, 12 m virtual lidar and 200 Hz odometry")
    if sam3_observation:
        if not console_only_server:
            raise RuntimeError("SAM3 observation requires the qualified console-only moving fixture")
        if not moving_trace_geometry_matches(physics_step,lidar_range,odom_frequency):
            raise RuntimeError("SAM3 observation requires 2 ms physics, 12 m virtual lidar and 200 Hz odometry")
        if not Path("/opt/semantic-safety/capture-lib/libgz-sensors8-rgbd_camera.so.8").is_file():
            raise RuntimeError("SAM3 observation requires the console image's capture-trace override library")
    if phase6_semantic_arm and not moving_trace_geometry_matches(physics_step,lidar_range,odom_frequency):
        raise RuntimeError("Phase 6 semantic arms require 2 ms physics, 12 m virtual lidar and 200 Hz odometry")
    if (physics_step or lidar_range or odom_frequency) and not contact_audit: raise ValueError("diagnostic changes require contact audit")
    write_assets(output / "assets",lidar_update_rate=scan_update_rate,
                 physics_step=float(physics_step) if physics_step else None,
                 lidar_max_range=float(lidar_range) if lidar_range else None,
                 odom_frequency=float(odom_frequency) if odom_frequency else None)
    world = output / "assets/hotel.world"
    add_camera(world)
    if served_topology:
        # G4's full guarded world runs below real time. Increase sensor
        # sampling, never a safety deadline, so the served capture lease has
        # headroom when one pending bundle replaces another. 30 simulation-Hz
        # (candidate change, November 2, user-approved): a fresher capture is
        # available whenever the serial inference pipeline frees, adding
        # ~24 ms of capture-age margin to every armed lease renewal
        # (qualification-7 trial-12 lost its renewal 3.9 ms past the
        # deadline on a coincident adapter/model jitter event).
        camera_tree=ET.parse(world)
        camera_rate=camera_tree.find(".//model[@name='robot_1']/link[@name='camera_link']/sensor/update_rate")
        if camera_rate is None: raise RuntimeError("G4 RGB-D sensor not found")
        camera_rate.text="30"
        camera_tree.write(world,encoding="utf-8",xml_declaration=True)
    if not phase6_target_absent:
        # Operator presentations use the enlarged standalone D2 mat. Ordinary
        # qualification trials retain their original geometry. The evaluator
        # below reads its bounds from this same generated world.
        add_phase2_targets(world, phase6_demo=bool(os.getenv("PHASE5_OPERATOR_DEMO_TOKEN")))
    if phase6_semantic_arm:
        # Pre-arm render-warmup cameras at the goal (user-approved October
        # 28, 2026): staged in BOTH arms so the paired scene stays
        # identical; inactive without subscribers (zero armed-phase cost).
        # See install_phase1_camera.add_phase6_render_warmup.
        add_phase6_render_warmup(world, (float(os.getenv("PHASE6_GOAL_X", "19.402")),
                                         float(os.getenv("PHASE6_GOAL_Y", "-31.594"))))
    if rear_casters:
        urdf=output/"assets/robot.urdf"
        new_world,new_urdf=add_rear_casters(world.read_text(),urdf.read_text())
        world.write_text(new_world); urdf.write_text(new_urdf)
    if contact_audit:
        world.write_text(instrument(world.read_text(),rear_casters=rear_casters))
        model=Path("/opt/ros2-demo/hotel-assets/models/hotel_L1/model.sdf")
        if model.is_file(): (output/"hotel-L1-model.sdf").write_text(model.read_text())
        floor=model.parent/"meshes/floor_3.obj"
        if floor.is_file(): (output/"hotel-floor-3.obj").write_text(floor.read_text())
    static_map_cache = {}
    def static_map_free(x, y, radius):
        """Every static-map cell covered by the disk must be free.

        Shared by the fault-obstacle staging check and the Phase 6 goal and
        mat-removal pose validation; identical computation to the original
        inline obstacle-staging check.
        """
        if "raster" not in static_map_cache:
            import numpy as np
            from PIL import Image
            map_config = yaml.safe_load((output / "assets/hotel_L1.yaml").read_text())
            raster = np.asarray(Image.open(output / "assets/hotel_L1.pgm").convert("L"))
            static_map_cache.update(
                raster=raster,
                free=(255 - raster.astype(float)) / 255 < map_config["free_thresh"],
                origin=map_config["origin"], resolution=map_config["resolution"])
        import numpy as np
        raster = static_map_cache["raster"]
        free, origin = static_map_cache["free"], static_map_cache["origin"]
        resolution = static_map_cache["resolution"]
        for column in range(int(np.floor((x - radius - origin[0]) / resolution)),
                            int(np.ceil((x + radius - origin[0]) / resolution)) + 1):
            for row in range(int(np.floor((y - radius - origin[1]) / resolution)),
                             int(np.ceil((y + radius - origin[1]) / resolution)) + 1):
                cell_x = origin[0] + (column + .5) * resolution
                cell_y = origin[1] + (row + .5) * resolution
                if (cell_x - x) ** 2 + (cell_y - y) ** 2 > radius ** 2:
                    continue
                if not (0 <= column < raster.shape[1] and 0 <= row < raster.shape[0]):
                    return False
                if not free[raster.shape[0] - 1 - row, column]:
                    return False
        return True
    if fault_stop_probe and fault_stop_mode == "obstacle_spawn":
        # Pre-place the fault post far off the corridor (map-verified free)
        # so the scene, physics and the planner all load a clear straight
        # path. The trial moves it into the corridor with the blocking
        # set_pose service, which only sets a pose command component inside
        # PreUpdate: mid-trial entity creation parses SDF and builds scene
        # geometry on the simulation thread and stalled physics ~190 ms,
        # which the 100 ms command-freshness contract correctly fails.
        start_pose = json.loads((output / "assets/map-audit.json").read_text())["initial_model_pose"]
        staging = obstacle_staging_pose(start_pose)
        corridor_target = {"x": start_pose[0] + OBSTACLE_AHEAD_M,
                           "y": start_pose[1] + OBSTACLE_LATERAL_M}
        if not (static_map_free(staging["x"], staging["y"], 0.15)
                and static_map_free(corridor_target["x"], corridor_target["y"], 0.15)):
            raise RuntimeError("fault obstacle staging/corridor pose not free in the static map")
        world.write_text(world.read_text().replace("</world>",
            OBSTACLE_POST_MODEL.format(name=OBSTACLE_NAME,
                x=staging["x"], y=staging["y"]) + "\n  </world>"))
    # Phase 6 crossing goal and ground truth: the goal must lie beyond the
    # staged mat on a map-free cell so the baseline straight route crosses
    # the mat; the removal pose (stationary smoke) must be map-free too. The
    # mat rectangle is the exposure ground truth and is recorded in the
    # trial evidence for the series evaluator.
    phase6_goal = None
    mat_rectangle = None
    mat_removal = None
    if phase6_semantic_arm:
        if phase6_target_absent:
            # The negative case's ground truth stays the WOULD-BE rectangle
            # (recorded for the series' exposure measurement) even though the
            # mat is not staged; the fixture's own target-dependent gates are
            # skipped and the observed cells at the rectangle are recorded as
            # a recognition diagnostic, never a gate (the Phase 2 waiver).
            mat_rectangle = None
        else:
            mat_rectangle = parse_mat_ground_truth(world.read_text())
        phase6_goal = (float(os.getenv("PHASE6_GOAL_X", "19.402")),
                       float(os.getenv("PHASE6_GOAL_Y", "-31.594")))
        if not all(math.isfinite(value) for value in phase6_goal):
            raise ValueError("Phase 6 goal must be finite map coordinates")
        if not static_map_free(phase6_goal[0], phase6_goal[1], 0.15):
            raise RuntimeError("Phase 6 goal is not free in the static map")
        if phase6_stationary_smoke or phase6_target_removal:
            start_pose = json.loads((output / "assets/map-audit.json").read_text())["initial_model_pose"]
            mat_removal = mat_removal_pose(start_pose[0], start_pose[1])
            if not static_map_free(mat_removal["x"], mat_removal["y"], 0.5):
                raise RuntimeError("Phase 6 mat removal pose is not free in the static map")
    # Gazebo world name for the fault-obstacle create service. Parsed from
    # the final private world asset after every modification.
    world_name = re.search(r'<world[^>]*\bname="([^"]+)"', world.read_text()).group(1)
    # The Phase 6 "on" arm uses the semantic-on candidate; it differs from
    # the Phase 5 guarded candidate ONLY by the additive soft-cost semantic
    # layer in both costmaps (see test_phase6_params.py). The "off" arm and
    # every other suite use the Phase 5 candidate unchanged.
    candidate_yaml = ("phase6-nav2-candidate-lethal.yaml" if phase6_semantic_arm == "on" and phase6_lethal_experiment
                      else "phase6-nav2-candidate.yaml" if phase6_semantic_arm == "on"
                      else "phase5-nav2-candidate.yaml")
    profile = yaml.safe_load((root/candidate_yaml).read_text())
    if guarded:
        tree="phase5-recovery-probe.xml" if recovery_probe else "phase5-baseline.xml"
        profile["bt_navigator"]["ros__parameters"]["default_nav_to_pose_bt_xml"] = str(root/tree)
    # Diagnostic-only isolated experiment; never change the checked-in candidate
    # or any deployed Nav2 configuration through this override.
    test_frequency = os.getenv("PHASE5_TEST_CONTROLLER_FREQUENCY")
    if test_frequency is not None:
        frequency = float(test_frequency)
        if not math.isfinite(frequency) or not 1.0 <= frequency <= 100.0:
            raise ValueError("diagnostic controller frequency must be in [1, 100] Hz")
        profile["controller_server"]["ros__parameters"]["controller_frequency"] = frequency
    test_smoother_frequency=os.getenv("PHASE5_TEST_SMOOTHER_FREQUENCY")
    if test_smoother_frequency is not None:
        frequency=float(test_smoother_frequency)
        if not math.isfinite(frequency) or not 1.0<=frequency<=200.0:
            raise ValueError("diagnostic smoother frequency must be in [1, 200] Hz")
        profile["velocity_smoother"]["ros__parameters"]["smoothing_frequency"] = frequency
    profile["map_server"] = {"ros__parameters":{"use_sim_time":True,
        "yaml_filename":str(output/"assets/hotel_L1.yaml")}}
    if os.getenv("PHASE5_OPERATOR_DEMO_TOKEN"):
        # Restore the historical standalone simulation-demo localization:
        # known map origin + measured wheel odometry, one map->odom authority.
        # AMCL's scan ambiguity in this room permits metre-scale drift.
        profile["amcl"]["ros__parameters"]["tf_broadcast"]=False
        profile["controller_server"]["ros__parameters"]["general_goal_checker"]["xy_goal_tolerance"]=0.1
        profile["controller_server"]["ros__parameters"]["general_goal_checker"]["yaw_goal_tolerance"]=math.pi
    params = output/"hotel-params.yaml"
    params.write_text(yaml.safe_dump({"robot_1":profile}))
    (output/"prepared-hashes.json").write_text(json.dumps({str(p.relative_to(output)):
        hashlib.sha256(p.read_bytes()).hexdigest() for p in (world,params,output/"assets/robot.urdf")},indent=2))
    records, pending, checks, commands, sensors, states = [], [], [], [], {}, {}
    camera_pending = []
    timing_events = []
    stage_timings = StageTimings()
    clock_events = []
    mutex = threading.Lock()
    contact_rows=[]
    scan_audit=[]
    gz = GzNode()
    def contact(message):
        row=json.loads(message.data)
        row["observer_wall_ns"]=time.time_ns()
        with mutex: contact_rows.append(row)
    if contact_audit: gz.subscribe(StringMsg,"/phase5/contact_audit",contact)
    def native(message):
        row = json.loads(message.data)
        row["observer_received_wall_ns"] = time.time_ns()
        with mutex: records.append(row); pending.append(row)
    if sam3_observation:
        # With SAM3 observation the native status arrives through the
        # watchdog's UDP companion path: rendering the perception camera
        # holds the console server's shared gz transport mutex long enough
        # to delay the status PUBLICATION itself by hundreds of milliseconds
        # (measured p95 ~575 ms), which the 20 ms capture-bracket joins
        # cannot absorb. The UDP sendto cannot be blocked by that mutex.
        import socket as socket_module
        import collections as collections_module
        status_receiver=socket_module.socket(socket_module.AF_INET,socket_module.SOCK_DGRAM)
        status_receiver.bind(("127.0.0.1",45985))
        status_receiver.settimeout(.5)
        # Lock-free loop timing for the receive thread (deque.append is
        # GIL-atomic; no mutex on this path): pilot-1 proved the thread
        # freezes ~1.6 s at the deterministic off-arm failure (backlog
        # drain + rcvbuf drops) while the pump keeps running. The recorded
        # (iteration start, recvfrom return, post-append) triples separate
        # recvfrom blocking, mutex waiting and GIL starvation.
        udp_loop_timing=collections_module.deque(maxlen=8192)
        def native_udp():
            while True:
                iteration_start=time.time_ns()
                try: data,_=status_receiver.recvfrom(65536)
                except socket_module.timeout:
                    udp_loop_timing.append((iteration_start,0,0)); continue
                except OSError: return
                recv_return=time.time_ns()
                row=json.loads(data.decode())
                row["observer_received_wall_ns"]=time.time_ns()
                with mutex: records.append(row); pending.append(row)
                udp_loop_timing.append((iteration_start,recv_return,time.time_ns()))
        threading.Thread(target=native_udp,daemon=True,
                         name="phase5_status_udp").start()
    else:
        gz.subscribe(StringMsg,"/phase5/drive/status",native)
    def camera(kind,message):
        frames=[e.value[0] for e in message.header.data if e.key=="frame_id" and e.value]
        row={"stamp":message.header.stamp.sec*1_000_000_000+message.header.stamp.nsec,
             "frame":frames[0] if len(frames)==1 else "INVALID", "wall_received":time.time_ns(),
             "width":message.width,"height":message.height,"transport":"native_gazebo",
             "pixel_format":message.pixel_format_type}
        with mutex: camera_pending.append((kind,row))
    if not sam3_observation:
        gz.subscribe(GzImage,"/robot_1/camera/image",lambda m:camera("rgb",m))
        gz.subscribe(GzImage,"/robot_1/camera/depth_image",lambda m:camera("depth",m))
    # With SAM3 observation the compressor sidecar already subscribes the gz
    # images; a SECOND image subscription from this fixture would double the
    # console server's per-frame transport sends on the shared node and
    # delayed the watchdog's native-status publications by hundreds of
    # milliseconds in bursts (series trial 1 stopped command_expired on the
    # resulting capture-bracket lag). Camera liveness instead comes from the
    # compressor's tiny compression_trace records on this private domain;
    # the worker's mask/cloud decoding proves the dimensions end to end.
    rclpy.init()
    node = Node("phase5_hotel_observer", parameter_overrides=[rclpy.parameter.Parameter("use_sim_time",value=True)])
    # Read-only TF edge recorder: the controller's synchronous current-time
    # lookups wait on transform edges (notably map->odom, published by AMCL
    # per scan). Recording edge arrival times correlates any controller
    # block with late edges; it grants no authority and changes no behavior.
    tf_edge_rows=[]
    # Per-message odom->base arrival rows (Phase 6 arm trials only): the
    # gcfix analysis proved the tf lease starves when the fixture buffer's
    # odom->base stamps fall behind the scan stamps (the mat-close /tf
    # delivery delay), while the frame bridge relay and the odom DDS stream
    # stay fresh — the per-edge (stamp, wall) record measures the fixture
    # side of that path directly. Bounded; dumped with the evidence.
    odom_edge_rows=collections.deque(maxlen=16384)
    odom_base_state={"last_wall":None,"gaps":[]}
    from tf2_msgs.msg import TFMessage
    def tf_edges(message):
        wall=time.time_ns()
        for transform in message.transforms:
            child=transform.child_frame_id
            stamp=transform.header.stamp.sec*10**9+transform.header.stamp.nanosec
            if child=="odom" and transform.header.frame_id=="map":
                tf_edge_rows.append({"stamp_ns":stamp,
                                     "wall_received_ns":wall})
            elif child=="base_footprint" and transform.header.frame_id=="odom":
                if phase6_semantic_arm:
                    odom_edge_rows.append({"stamp_ns":stamp,"wall_ns":wall})
                previous=odom_base_state["last_wall"]
                if previous is not None and wall-previous>50_000_000:
                    odom_base_state["gaps"].append({"gap_ms":(wall-previous)/1e6,
                                                    "wall_ns":wall})
                odom_base_state["last_wall"]=wall
    node.create_subscription(TFMessage,"/tf",tf_edges,50)
    # Camera liveness in observation mode comes from the worker's status
    # file (it counts the compressor's trace records on the isolated
    # camera/semantic domain); this safety domain carries no camera data.
    # Observation-only SAM3 results are handled by a SEPARATE worker process
    # (sam3_observer_worker.py): the multi-megabyte semantic clouds must be
    # deserialized and projected outside this fixture's single-threaded safety
    # pump, where they hold the interpreter lock and can expire the 20 ms
    # raw-command capture-bracket joins. The worker reports only small files;
    # semantic costs are NOT in any costmap of this fixture.
    # With SAM3 observation the camera and semantic streams move to their
    # OWN private ROS domain (88): multi-megabyte clouds on the safety
    # domain delayed the frame bridge's odom->base_footprint TF past the
    # controller's transform waits (series 2 trial 2: 732/625/109 ms TF gaps,
    # the controller stopped publishing and the chain correctly stopped
    # command_expired). The safety domain keeps only clock/odom/scan/TF and
    # the command topics, exactly as qualified.
    # Observation-only SAM3 results are handled by a SEPARATE worker
    # SIDECAR (its own CPU quota; see the runner): the multi-megabyte
    # semantic clouds must be deserialized and projected outside this
    # fixture's container budget and safety pump, where they hold the
    # interpreter lock and can expire the 20 ms raw-command
    # capture-bracket joins. The worker reports only small files through
    # the shared emptyDir; semantic costs are NOT in any costmap of this
    # fixture. The fixture publishes the mat ground truth for it once the
    # private world is final.
    sam3_worker_files=None
    if sam3_observation:
        shared_dir=Path("/tmp/phase5-sam3-shared")
        shared_dir.mkdir(exist_ok=True)
        (shared_dir/"ground-truth.json").write_text(
            json.dumps({"mat":None if phase6_target_absent
                        else parse_mat_ground_truth(world.read_text())}))
        sam3_worker_files=(shared_dir/"status.json",shared_dir/"observation.json")
    # No background thread or sim-clock subscription on the ingress node. Its
    # bounded executor is polled explicitly ahead of the busy observer node.
    ingress_node = Node("phase5_command_ingress")
    ingress_executor = SingleThreadedExecutor()
    ingress_executor.add_node(ingress_node)
    observer_executor = SingleThreadedExecutor()
    observer_executor.add_node(node)
    task_executor = SingleThreadedExecutor()
    tf = Buffer(); listener = TransformListener(tf,node)
    supervisor_tf=ProbeTfBuffer() if tf_loss_probe and tf_loss_mode=="supervisor" else tf
    supervisor_listener=TransformListener(supervisor_tf,node) if supervisor_tf is not tf else None
    processes, handles = [], []
    paused_processes, fault_events = [], []
    injected_steady=None
    clock, ros_clock, success = None, 0, False
    adapter = None
    ledger = CommandLedger(); ledger.reset("disarmed-observation",0)
    joiner = CaptureJoiner(ledger,lambda stamp,wall:clock.wall_bound(stamp,wall) if clock else None)
    frame_reports, poses = [], []
    control_geometry=[]
    planner_paths=[]
    def yaw(q):
        return math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))
    def planned_path(message):
        if not message.poses: return
        end=message.poses[-1]
        planner_paths.append({"stamp":ns(message.header.stamp),"frame":message.header.frame_id,
            "end_stamp":ns(end.header.stamp),"x":end.pose.position.x,"y":end.pose.position.y,
            "yaw":yaw(end.pose.orientation)})
    node.create_subscription(NavPath,"/robot_1/plan",planned_path,10)
    def carrot(message):
        row={"stamp":ns(message.header.stamp),"carrot_distance":math.hypot(message.point.x,message.point.y)}
        if tf.can_transform("map","base_footprint",Time()):
            transform=tf.lookup_transform("map","base_footprint",Time())
            row.update(map_x=transform.transform.translation.x,map_y=transform.transform.translation.y)
        # Diagnostic only: compare the goal checker's original endpoint stamp
        # with the current controller capture. Neither lookup supplies guard
        # evidence. Failed/late TF remains explicitly missing, never latest.
        if planner_paths:
            endpoint=planner_paths[-1]
            row["planner_endpoint"]=endpoint
            capture=Time(nanoseconds=row["stamp"])
            if endpoint["frame"]=="map" and tf.can_transform("odom","base_footprint",capture):
                robot=tf.lookup_transform("odom","base_footprint",capture).transform
                for label,stamp in (("historical",endpoint["end_stamp"]),("capture",row["stamp"])):
                    when=Time(nanoseconds=stamp)
                    if not tf.can_transform("odom","map",when): continue
                    transform=tf.lookup_transform("odom","map",when).transform
                    angle=yaw(transform.rotation)
                    x=transform.translation.x+math.cos(angle)*endpoint["x"]-math.sin(angle)*endpoint["y"]
                    y=transform.translation.y+math.sin(angle)*endpoint["x"]+math.cos(angle)*endpoint["y"]
                    error=angle+endpoint["yaw"]-yaw(robot.rotation)
                    row[label+"_endpoint_distance_m"]=math.hypot(x-robot.translation.x,y-robot.translation.y)
                    row[label+"_endpoint_yaw_error_rad"]=math.atan2(math.sin(error),math.cos(error))
        control_geometry.append(row)
    node.create_subscription(PointStamped,"/robot_1/lookahead_point",carrot,10)
    node.create_subscription(Bool,"/robot_1/is_rotating_to_heading",
        lambda m:control_geometry.append({"rotating":m.data,"wall_ns":time.time_ns()}),10)

    def launch(name, command, env=None):
        handle = (output/(name+".log")).open("w")
        handles.append(handle)
        child = subprocess.Popen(command,stdout=handle,stderr=subprocess.STDOUT,
                                 start_new_session=True,
                                 env={**os.environ,**env} if env else None)
        processes.append((name,child))
        return child

    def launch_node(package, name, *extra):
        prefix="/opt/nav2-smoother-overlay" if package=="nav2_velocity_smoother" else "/opt/ros/jazzy"
        if package=="nav2_controller" and controller_endpoint_capture:
            prefix="/opt/nav2-controller-overlay"
        if package=="nav2_collision_monitor" and collision_monitor_diagnostics:
            prefix="/opt/nav2-collision-monitor-overlay"
        return launch(name,[f"{prefix}/lib/{package}/{name}","--ros-args",
                           "--params-file",str(params),"-r","__ns:=/robot_1",*extra])

    def receive_sensor(kind, message):
        stamp = ns(message.header.stamp)
        if adapter: adapter.sensor(kind,message)
        old = sensors.get(kind)
        sensors[kind] = {"stamp":stamp,"frame":message.header.frame_id,
            "wall_received":time.time_ns(),"count":1+(old["count"] if old else 0),
            "rollback": bool(old and (old["rollback"] or stamp<old["stamp"]))}
        if kind=="odom":
            p=message.pose.pose.position; q=message.pose.pose.orientation
            sensors[kind]["pose"]={"x":p.x,"y":p.y,
                "yaw":math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))}
        if kind=="scan":
            scan_received_steady_ns=time.monotonic_ns()
            scan_received_wall_ns=time.time_ns()
            scan_audit.append({"stamp":stamp,"wall_ns":time.time_ns(),"samples":len(message.ranges),
                "nan":sum(math.isnan(v) for v in message.ranges),"negative":sum(v<0 for v in message.ranges),
                "positive_infinity":sum(v==float("inf") for v in message.ranges),
                "below_minimum":sum(math.isfinite(v) and v<message.range_min for v in message.ranges)})
            sensors[kind].update(samples=len(message.ranges),finite=sum(math.isfinite(v) for v in message.ranges))
            timing_events.append({"kind":"scan","stamp":stamp,"steady_received":scan_received_steady_ns,
                                  "wall_received":scan_received_wall_ns})
    def receive_clock(message):
        nonlocal ros_clock
        ros_clock = ns(message.clock)
    # With SAM3 observation the clock subscription must be reliable: a
    # dropped /clock message under the observation load stalls this
    # fixture's ros knowledge in bursts, leaving controller stamps ahead of
    # now.ros past the 20 ms capture-join window (series 17 trial 2: six
    # joins expired together). The topic is tiny; reliability costs nothing.
    clock_qos=(QoSProfile(depth=10,reliability=ReliabilityPolicy.RELIABLE)
               if sam3_observation else qos_profile_sensor_data)
    node.create_subscription(Clock,"/clock",receive_clock,clock_qos)
    # NOTE: the scan/odom subscriptions stay best-effort sensor-data QoS —
    # the sensor bridge's publishers for these topics are best-effort, so a
    # reliable subscriber does not match at all (pair-1-off-scanreliable:
    # zero scans, no motion). The mat-close scan-delivery drops
    # (pair-1-off-gcfix) need a publisher-side or transport-side remedy.
    for kind, topic, cls in (("odom","/robot_1/odom",Odometry), ("scan","/robot_1/scan_fixed",LaserScan)):
        def sensor_callback(k):
            def callback(message): receive_sensor(k,message)
            return callback
        node.create_subscription(cls,topic,sensor_callback(kind),qos_profile_sensor_data)
    node.create_subscription(String,"/robot_1/phase5/frames",lambda m:frame_reports.append(json.loads(m.data)),10)
    node.create_subscription(PoseWithCovarianceStamped,"/robot_1/amcl_pose",lambda m:poses.append({
        "stamp":ns(m.header.stamp),"x":m.pose.pose.position.x,"y":m.pose.pose.position.y,
        "covariance":list(m.pose.covariance)}),10)
    def command(message, info):
        callback_wall=time.time_ns()
        row=json.loads(message.data)
        now = Now(time.monotonic_ns(),time.time_ns(),ros_clock)
        # These timestamps describe the audit String hop, NOT the original
        # Twist. Diagnostics only: never replace its source/capture deadline.
        row.update(audit_timing(info,callback_wall),ros_now=ros_clock)
        joiner.receive(row,now)
        commands.append(row)
        if adapter: adapter.command(row)
    ingress_node.create_subscription(String,"/phase5/command_audit",command,100)

    bind_clock = False

    def ingest_native():
        nonlocal clock
        with mutex:
            chunk=list(pending); pending.clear()
            images=list(camera_pending); camera_pending.clear()
        for kind,row in images:
            old=sensors.get(kind)
            row.update(count=1+(old["count"] if old else 0),
                       rollback=bool(old and (old["rollback"] or row["stamp"]<old["stamp"])))
            sensors[kind]=row
        for row in chunk:
            p=row.get("physical")
            if not p: continue
            if bind_clock and clock is None and time.time_ns()-p["wall_ns"]<100_000_000:
                clock=NativeClock(row["clock_epoch"])
                if adapter: adapter.clock=adapter.co.clock=clock
                clock_events.append({"event":"bound_while_disarmed","wall_ns":time.time_ns(),"sim_ns":p["sim_ns"]})
            if clock:
                previous_fault=clock.fault
                processed=time.time_ns()
                clock.observe(row,processed)
                if clock.fault and not previous_fault:
                    clock_events.append({"event":"latched_clock_fault","reason":clock.fault,
                        "sim_ns":p["sim_ns"],"capture_wall_ns":p["wall_ns"],"status_wall_ns":row["wall_ns"],
                        "callback_wall_ns":row["observer_received_wall_ns"],"processed_wall_ns":processed,
                        "capture_age_at_native_publish_ms":(row["wall_ns"]-p["wall_ns"])/1e6,
                        "capture_age_at_callback_ms":(row["observer_received_wall_ns"]-p["wall_ns"])/1e6,
                        "capture_age_at_processing_ms":(processed-p["wall_ns"])/1e6})
                # Fast-path wait-hold renewal at pump frequency: this ingest
                # runs far more often than the observer pass, so the hold
                # fires within milliseconds of the native confirming the
                # settling tail instead of racing the command deadline on the
                # slower observer loop (October 23 isolated-node pilot).
                if (adapter and guarded and not clock.fault and row.get("armed")
                        and not row.get("pending")
                        and abs(row.get("applied_vx",1))<=0.005
                        and abs(row.get("applied_wz",1))<=0.005):
                    adapter.maybe_wait_hold()
            if not guarded and (row["armed"] or row["pending"] or row["applied_vx"] or row["applied_wz"]):
                raise RuntimeError("disarmed-only fixture acquired motion authority")

    # Armed-semantic supervisor: poll the observation worker's small status
    # file and feed the camera/semantic/inference-heartbeat lease evidence to
    # the gate, which applies the unchanged 500 ms capture-age and wall-clock
    # freshness contract. The same poll writes the coordinator status file
    # the semantic fault-matrix runner uses to time external injections.
    semantic_probe={"phase":"starting","last_sequences":{},"leases":{},
                    "injected_steady":None,"observe_error":None}
    semantic_poll_last={"read":0.0,"write":0.0}
    def write_status_json(path, payload):
        temporary=Path(str(path)+".tmp")
        temporary.write_text(json.dumps(payload))
        temporary.replace(path)
    def semantic_lease_urgent():
        """True within 40 ms of the newest armed semantic lease's capture-age
        deadline. Normal renewals land 50-80 ms before their deadline, so this
        fires only when a renewal is already late — exactly when the poll and
        pump cadence must tighten so the renewal still reaches the gate in
        time. Pure scheduling; the 500 ms contract itself is unchanged."""
        if not semantic_fault_probe or adapter is None: return False
        if not adapter.co.gate.armed: return False
        latest=(semantic_probe["leases"].get("semantic") or {})
        deadline=(latest.get("wall_ns") or 0)/1e9+0.498
        return 0<deadline-time.time_ns()/1e9<0.04
    def semantic_lease_poll():
        if not semantic_fault_probe: return
        now_mono=time.monotonic()
        # Normally 5 ms; 1 ms while a renewal is urgently due. The armed
        # 500 ms capture-age contract is unchanged; the finer poll only
        # shortens the renewed lease's path from the worker's status file to
        # the gate (attempt-3 trial-10 and qualification-4 trial-07 lost that
        # race by milliseconds with a healthy backend).
        if now_mono-semantic_poll_last["read"]<(0.001 if semantic_lease_urgent() else 0.005):
            return
        semantic_poll_last["read"]=now_mono
        try:
            status=json.loads(sam3_worker_files[0].read_text())
        except (OSError,ValueError):
            status={}
        leases=status.get("leases") or {}
        semantic_probe["leases"]=leases
        if adapter is not None:
            for key in ("camera","semantic","inference_heartbeat"):
                item=leases.get(key)
                if not item: continue
                if item.get("sequence",0)<=semantic_probe["last_sequences"].get(key,-1):
                    continue
                try:
                    adapter.observe_semantic_lease(key,item.get("epoch",""),
                        item.get("sequence",0),item.get("wall_ns",0),item.get("ros_ns",0))
                    semantic_probe["last_sequences"][key]=item["sequence"]
                except Exception as error:
                    semantic_probe["observe_error"]=str(error)
        if now_mono-semantic_poll_last["write"]<0.1: return
        semantic_poll_last["write"]=now_mono
        write_status_json(output/"semantic-armed-status.json",{
            "phase":semantic_probe["phase"],
            "mode":semantic_fault_mode,
            "armed":bool(adapter is not None and adapter.co.gate.armed),
            "gate_reason":adapter.co.gate.reason if adapter is not None else None,
            "leases":{k:(v or {}).get("sequence") for k,v in leases.items()},
            "written_wall_ns":time.time_ns()})

    # Capture-time TF witness poll (user-approved October 28, 2026): the    # witness sidecar resolves map->sensor at each scan's capture stamp in
    # its own prompt process (pair-1-off-tfprobe proved the fixture's own
    # /tf reader queues to ~180 ms at mat-close while an idle process
    # receives the same stream in ~1.4 ms). The renewal goes through the
    # SAME evidence() path — clock bound, monotonicity and the unchanged
    # 500 ms capture-age freshness; a stale, missing or regressing record
    # renews nothing, so witness loss fails closed exactly like before.
    tf_witness_state={"last_seq":-1,"last_read":0.0,"records":0,"stale":0,"applied":0}
    def tf_witness_poll():
        if not (phase6_tf_witness and adapter is not None): return
        # The native clock binds only during the disarmed setup window; the
        # adapter's own tick() has the same precondition before evidence.
        if adapter.clock is None: return
        now_mono=time.monotonic()
        if now_mono-tf_witness_state["last_read"]<0.02: return
        tf_witness_state["last_read"]=now_mono
        try:
            record=json.loads((Path("/tmp/phase5-sam3-shared")/"tf-witness.json").read_text())
        except (OSError,ValueError):
            return
        if record.get("schema")!="phase6-tf-witness/v1": return
        seq=record.get("seq",-1)
        stamp=record.get("scan_stamp_ns")
        if not isinstance(seq,int) or seq<=tf_witness_state["last_seq"]: return
        if not isinstance(stamp,int) or stamp<=0: return
        tf_witness_state["last_seq"]=seq
        tf_witness_state["records"]+=1
        # Staleness bound: a heartbeat older than 500 ms renews nothing.
        if time.time_ns()-record.get("written_wall_ns",0)>500_000_000:
            tf_witness_state["stale"]+=1
            return
        # evidence() renews silently (it has no return value); success is
        # proven by the lease's last renewed stamp advancing to this record.
        adapter.evidence("tf",stamp)
        if adapter.last_evidence.get("tf")==stamp:
            tf_witness_state["applied"]+=1
            adapter.tf_trace.append({"stamp":stamp,"frame":record.get("frame"),
                "source":"tf_witness","witness_seq":seq,
                "witness_qualified_wall_ns":record.get("qualified_wall_ns"),
                "renewal_wall_ns":time.time_ns()})

    # Mid-trial global semantic-cell timeline (user-approved October 28,
    # 2026 — mask-bleed mapping): pair-1-on-globalonly completed the on-arm
    # crossing but showed no route contrast at soft cost 200 and degraded
    # registration on the shifted views (pooled 0.688 vs 1.0 from the
    # baseline lane) — the north-hugging lane's grazing views bleed the
    # mask onto non-mat areas. This poll snapshots the global costmap's
    # cost-200 cells once per second through the trial and records how many
    # fall outside the ground-truth rectangle (with a bounded sample of
    # their coordinates), so the bleed's location and dynamics are retained
    # before any lethal-cost experiment. Async and non-blocking: the service
    # request is issued with call_async and read on a later poll once the
    # observer executor has serviced it — no recursive pumping, no waiting.
    #
    # OPT-IN ONLY (pair-1-on-bleedmap lesson): materializing the service
    # response converts the ~585k-cell grid in pure Python inside the
    # pump's guard stage — a measured 33-42 ms pump block PER POLL at 1 Hz.
    # One such block landed on the lease-issuance path while the command
    # source was near its 100 ms deadline: the coordinator's lease cadence
    # gapped 46 ms, the watchdog's lease (capped by the aging source
    # deadline) expired, and the trial stopped native_session_lost — every
    # apparent "delivery excursion" in that run (fixture /tf and scan
    # spikes, missing command audits, the lease packet gap) was this pump
    # block. The bleed data it collected is complete; never run it in a
    # trial whose timing matters.
    cost_cells_timeline=[]
    cost_cells_state={"client":None,"future":None,"last":0.0}
    def cost_cells_poll():
        if not phase6_cost_cells_timeline: return
        if phase6_semantic_arm!="on" or mat_rectangle is None: return
        if cost_cells_state["future"] is None:
            if time.monotonic()-cost_cells_state["last"]<1.0: return
            if cost_cells_state["client"] is None:
                cost_cells_state["client"]=node.create_client(
                    GetCostmap,"/robot_1/global_costmap/get_semantic_layer")
            if not cost_cells_state["client"].service_is_ready(): return
            cost_cells_state["future"]=cost_cells_state["client"].call_async(
                GetCostmap.Request())
            cost_cells_state["last"]=time.monotonic()
            return
        future=cost_cells_state["future"]
        if not future.done(): return
        cost_cells_state["future"]=None
        row={"wall_ns":time.time_ns()}
        try:
            grid=normalize_grid(future.result().map)
            cells=grid_cost_cells(grid)
            inside=cells_in_rectangle(cells,mat_rectangle)
            outside=[cell for cell in cells if cell not in inside]
            row.update(cells=len(cells),inside=len(inside),outside=len(outside),
                outside_sample=[[round(x,3),round(y,3)] for x,y in outside[:40]])
        except Exception as error:
            row["error"]=str(error)[:200]
        cost_cells_timeline.append(row)

    def pump():
        ingest_native()
        for _ in range(16):
            pump_round(
                ingress=lambda:stage_timings.call("ingress",lambda:ingress_executor.spin_once(timeout_sec=0)),
                observer=lambda:stage_timings.call("observer",lambda:observer_executor.spin_once(timeout_sec=0)),
                task=lambda:stage_timings.call("task",lambda:task_executor.spin_once(timeout_sec=0) if adapter else None),
                native=lambda:stage_timings.call("native",ingest_native),
                guard=lambda:stage_timings.call("guard",lambda:(
                    stage_timings.call("tf_witness",tf_witness_poll),
                    stage_timings.call("semantic_lease",semantic_lease_poll),
                    stage_timings.call("cost_cells",cost_cells_poll),
                    adapter.tick() if adapter else None)),
                diagnostics=lambda:stage_timings.call("diagnostics",lambda:joiner.drain(
                    Now(time.monotonic_ns(),time.time_ns(),
                        max(ros_clock,(clock.last or {}).get("sim_ns",0) if clock else 0)))))
        for name,child in processes:
            if child.poll() is not None: raise RuntimeError(f"{name} exited {child.returncode}")

    def until(predicate, timeout=20, label="condition"):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            pump()
            if predicate(): return
            # While a semantic-lease renewal is urgently due, pump and poll
            # faster so a last-instant renewal reaches the gate before its
            # capture-age deadline. Scheduling only; no contract changes.
            time.sleep(.0005 if semantic_lease_urgent() else .003)
        raise WaitTimeout("timeout: "+label)

    def dwell(seconds):
        end=time.monotonic()+seconds
        until(lambda:time.monotonic()>=end,seconds+2)

    def service(name, cls, request):
        client=node.create_client(cls,name)
        until(client.service_is_ready,label=name)
        future=client.call_async(request)
        until(future.done,label=name+" response")
        result=future.result(); node.destroy_client(client)
        return result

    def activate(name):
        for transition in (1,3):
            req=ChangeState.Request(); req.transition.id=transition
            assert service("/robot_1/"+name+"/change_state",ChangeState,req).success, name
        state=service("/robot_1/"+name+"/get_state",GetState,GetState.Request()).current_state
        states[name]={"id":state.id,"label":state.label}
        assert state.id==3,name+" not active"

    def pull_semantic_grid(name):
        """Pull one costmap's semantic-layer raw grid through nav2_costmap_2d's
        own per-layer get_semantic_layer service. A pull, never a
        subscription: the map-sized raw grid must not add steady-state
        callback load to the safety pump (the Phase 5 load findings)."""
        reply=service(f"/robot_1/{name}_costmap/get_semantic_layer",GetCostmap,
                      GetCostmap.Request())
        return normalize_grid(reply.map)

    def semantic_costs_at_target_now():
        if mat_rectangle is None:
            return {"passed":False,"reason":"no_phase6_target"}
        try:
            # The Phase 6 candidate carries the semantic layer in the global
            # costmap only (user-approved October 28, 2026); the local map has
            # no layer and no get_semantic_layer service, and its structural
            # absence is proven by the phase6_semantic_wiring check. The
            # lethal-cost exclusion experiment checks for its own target.
            return semantic_costs_at_target(pull_semantic_grid("global"),
                                            None, mat_rectangle,
                                            target_cost=254 if phase6_lethal_experiment else SOFT_COST)
        except Exception as error:
            return {"passed":False,"reason":"grid_pull_failed:"+str(error),
                    "traceback":traceback.format_exc()}

    def capture_sensor_transforms():
        capture_transforms={}
        if sam3_observation:
            # Refresh the camera sample from the worker's live status: the
            # row was populated at readiness time and its stamp would be
            # older than the TF buffer's history by this point.
            try:
                worker_camera_rows()
            except Exception:
                pass
        for kind in ("rgb","depth","scan"):
            sample=sensors[kind].copy()
            capture=Time(nanoseconds=sample["stamp"])
            until(lambda:tf.can_transform("map",sample["frame"],capture),label=kind+" capture TF")
            transform=tf.lookup_transform("map",sample["frame"],capture)
            t,q=transform.transform.translation,transform.transform.rotation
            capture_transforms[kind]={"stamp":sample["stamp"],"frame":sample["frame"],
                "translation":[t.x,t.y,t.z],"rotation":[q.x,q.y,q.z,q.w]}
        (output/"capture-transforms.json").write_text(json.dumps(capture_transforms,indent=2))
        checks.append({"case":"actual_capture_time_sensor_to_map_transforms","passed":True})

    def sam3_observation_checks(scope_stop_wall=None, stationary_smoke=False,
                                target_absent=False):
        """Evaluate the observation worker's aggregated evidence.

        scope_stop_wall bounds the timing window (the semantic fault stop or,
        for the stationary smoke, the target-removal move). The stationary
        smoke has no moving results, so its registration variant pools every
        pre-removal result; moving trials keep the frozen contract. The
        target-absent negative case inverts the registration contract: no
        moving result may carry a substantive mask (a detection with no
        staged target would be a false positive — recorded as a check, with
        the recognition waiver carried in the plan)."""
        try:
            observation=json.loads(sam3_worker_files[1].read_text())
        except (OSError, ValueError):
            observation={"results": [], "ages_ms": [], "labels": None,
                         "isolation": None, "capture_stamps_ns": []}
        physical_timeline=[(r["physical"]["wall_ns"],r["physical"].get("speed",0))
            for r in records if r.get("physical") and r["physical"].get("velocity_valid")]
        for result in observation.get("results", []):
            receipt=result.get("receipt_wall_ns")
            near=[speed for wall,speed in physical_timeline
                  if receipt is not None and 0<=receipt-wall<=50_000_000]
            result["moving"]=bool(near and max(near)>.02)
        task_receipts=[r["receipt_wall_ns"] for r in observation.get("results", [])
                       if r.get("matched")]
        if scope_stop_wall is not None:
            task_receipts=observation_window(scope_stop_wall,task_receipts)
        window=((task_receipts[-1]-task_receipts[0])/1e9
                if len(task_receipts)>=2 else 0.)
        if stationary_smoke:
            pre=[r for r in observation.get("results", [])
                 if r.get("receipt_wall_ns",float("inf"))<=scope_stop_wall]
            checks.append({"case":"phase6_smoke_registration",
                **smoke_registration_summary(pre)})
        elif target_absent:
            moving=[r for r in observation.get("results", []) if r.get("moving")]
            substantive=[r for r in moving if r.get("selected",0)>=50]
            checks.append({"case":"sam3_registration_target_absent",
                "passed": not substantive, "moving_results": len(moving),
                "substantive_results": len(substantive),
                "max_selected": max((r.get("selected",0) for r in moving),default=0),
                "contract": "no moving result carries >=50 selected mask pixels "
                            "with no target staged (false positives are the "
                            "Phase 2 recognition waiver's territory)"})
        elif phase6_semantic_arm == "on":
            # The on-arm detour's registration is a RECORDED DIAGNOSTIC, not
            # a gate (series-4 trial 000-on: pooled 0.940 vs the 95% check).
            # The Phase 5 observation series validated the >=95% contract on
            # the CROSSING route's views; the detour's grazing views are
            # outside that envelope (the standing Phase 2 recognition
            # waiver), with lane-dependent pooled fractions of 0.688-0.9999
            # and sub-cell edge bleed only — no cost cell has ever left the
            # ground-truth rectangle (the gated containment check). The
            # Phase 6 series gate itself evaluates completion, collision,
            # exposure reduction and the fault criteria, not registration.
            summary = registration_summary(observation.get("results", []))
            checks.append({"case":"sam3_registration_detour_diagnostic",
                "passed": True,
                "pooled_inside_fraction": summary.get("pooled_inside_fraction"),
                "moving_results": summary.get("moving_results"),
                "note": "diagnostic only under the Phase 2 recognition "
                        "waiver; the gated semantic-accuracy contract is the "
                        "costmap containment (phase6_semantic_costs_at_target)"})
        else:
            checks.append({"case":"sam3_registration_under_motion",
                **registration_summary(observation.get("results", []))})
        checks.append({"case":"sam3_observation_timing",
            **timing_summary(observation.get("ages_ms", []),
                len(task_receipts),window)})
        isolation=observation.get("isolation") or {}
        checks.append({"case":"sam3_semantic_isolation","passed":
            bool(isolation.get("semantic_topics"))
            and not isolation.get("costmap_subscriptions"),
            **isolation})
        (output/"sam3-observation.json").write_text(json.dumps(observation,indent=2))

    try:
        if console_only_server:
            validate_world(world.read_text())
            preflight=verify_console_server(output/"console-preflight")
            checks.append({"case":"console_server_preflight",**preflight})
            if not preflight["passed"]: raise RuntimeError("console server preflight failed")
        resource_probe_command=["python3",str(root/"resource_probe.py"),
                                "--output",str(output/"resource-samples.json")]
        if os.getenv("PHASE5_OPERATOR_DEMO_TOKEN"):
            # The 20,000-sample default ends after ~400 s, before the 600 s
            # operator hold. Cover the full bounded presentation pod lifetime;
            # this changes diagnostic capacity, never motion or lease limits.
            resource_probe_command.extend(("--max-samples", "65000"))
        if moving_timing_trace:
            resource_probe_command.extend(("--watch-comm","phase5_console_",
                                           "--watch-comm","collision_monit"))
        if gz_thread_probe:
            # controller_serv/velocity_smooth: per-thread schedstat of the
            # command-chain processes, for the Phase 6 off-arm silent-stop
            # investigation (the async computeControl worker's state during
            # the block: futex-wait vs run-queue starvation vs busy loop).
            resource_probe_command.extend(("--watch-threads-of","phase5_console_",
                                           "--watch-threads-of","collision_monit",
                                           "--watch-threads-of","controller_serv",
                                           "--watch-threads-of","velocity_smooth"))
        launch("resource_probe",resource_probe_command)
        # EGL headless rendering needs no X server, and Xvfb segfaults in
        # InitExtensions when the pod-wide NVIDIA graphics libraries are
        # injected with the GPU allocation. Xvfb belongs to the non-GPU
        # software-rendering profile only.
        if not headless_rendering:
            launch("display",["Xvfb",":97","-screen","0","1024x768x24","-nolisten","tcp"])
        if console_only_server:
            # With SAM3 observation, prefer the image's capture-trace
            # override library so the patched RGB-D sensor publishes
            # render-time capture traces on this private partition, exactly
            # as the qualified Phase 3 capture path requires.
            gazebo_env = {"SEMANTIC_CAPTURE_TRACE":"1",
                          "LD_LIBRARY_PATH":"/opt/semantic-safety/capture-lib:"
                                             +os.environ.get("LD_LIBRARY_PATH","")} if sam3_observation else None
            gazebo_child=launch("gazebo",[str(CONSOLE_SERVER),str(world),str(output/"gz-console")],
                                env=gazebo_env)
        elif api_server:
            build=output/"diagnostic-server-build"
            with (output/"diagnostic-server-build.log").open("x") as build_log:
                for command in (["cmake","-S",str(root),"-B",str(build),"-DCMAKE_BUILD_TYPE=Release"],
                                ["cmake","--build",str(build),"-j2"]):
                    subprocess.run(command,check=True,stdout=build_log,stderr=subprocess.STDOUT,timeout=45)
            executable=build/"phase5_diagnostic_server"
            (output/"diagnostic-server.json").write_text(json.dumps({
                "executable":str(executable),"sha256":hashlib.sha256(executable.read_bytes()).hexdigest(),
                "world_recording":api_world_recording,"qualification":False},indent=2))
            launch("gazebo",[str(executable),str(world),str(output/"gz-console"),
                             "on" if api_world_recording else "off"])
        else:
            launch("gazebo",["gz","sim","--force-version","8","-r","-s","-v","2",
                "--record-path",str(output/"gz-record")]+
                (["--record-period",record_period] if record_period is not None else [])+[str(world)])
        bridge_pairs=["/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock",
            "/robot_1/odom@nav_msgs/msg/Odometry[gz.msgs.Odometry",
            "/scan@sensor_msgs/msg/LaserScan[gz.msgs.LaserScan"]
        launch("sensor_bridge",["/opt/ros/jazzy/lib/ros_gz_bridge/parameter_bridge",
            *bridge_pairs,
            "--ros-args","-r","__node:=phase5_sensor_bridge","-r","/scan:=/robot_1/scan"])
        if sam3_observation:
            # SAM3 requires camera_info and the render-time capture trace on
            # the isolated camera/semantic domain; the compressor consumes
            # the gz images directly.
            launch("camera_bridge",["/opt/ros/jazzy/lib/ros_gz_bridge/parameter_bridge",
                "/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock",
                "/robot_1/camera/camera_info@sensor_msgs/msg/CameraInfo[gz.msgs.CameraInfo",
                "/robot_1/camera/capture_trace@std_msgs/msg/String[gz.msgs.StringMsg",
                "--ros-args","-r","__node:=phase5_camera_bridge",
                "-r","/robot_1/camera/camera_info:=/robot_1/camera/color/camera_info"],
                env={"ROS_DOMAIN_ID":"88"})
        launch("robot_state_publisher",["/opt/ros/jazzy/lib/robot_state_publisher/robot_state_publisher",
            "--ros-args","-p","use_sim_time:=true","-p","robot_description:="+(output/"assets/robot.urdf").read_text()])
        launch("frames",["python3",str(root/"frame_bridge.py")])
        if os.getenv("PHASE5_OPERATOR_DEMO_TOKEN"):
            origin=json.loads((output/"assets/map-audit.json").read_text())["initial_model_pose"]
            if any(abs(v)>1e-9 for v in origin[3:]):
                raise RuntimeError("demo origin requires zero spawn rotation")
            launch("demo_map_origin",["/opt/ros/jazzy/lib/tf2_ros/static_transform_publisher",
                "--x",str(origin[0]),"--y",str(origin[1]),"--z","0",
                "--frame-id","map","--child-frame-id","odom"])

        launch("command_observer",["/opt/semantic-safety/bin/phase5_command_observer"])
        mat_worker_files=None
        if phase6_stationary_smoke:
            # Pre-warmed mover for the semantic target mat, using the same
            # persistent-worker pattern as the fault obstacle: the blocking
            # set_pose connection is established and warmed with a no-op move
            # to the mat's current pose while the robot is disarmed, and the
            # removal move is served through files so no transport connection
            # is ever created during the smoke window.
            mat_worker_files=tuple(output/name for name in
                ("phase6-mat-ready.json","phase6-mat-target.json","phase6-mat-reply.json"))
            launch("phase6_mat_worker",[sys.executable,str(root/"fault_obstacle_worker.py"),
                "--world",world_name,"--name",MAT_MODEL,
                "--x",str((mat_rectangle["xmin"]+mat_rectangle["xmax"])/2),
                "--y",str((mat_rectangle["ymin"]+mat_rectangle["ymax"])/2),
                "--z",str(MAT_SURFACE_Z),
                "--ready-file",str(mat_worker_files[0]),
                "--target-file",str(mat_worker_files[1]),
                "--reply-file",str(mat_worker_files[2])])
        elif phase6_target_removal:
            # The series' target-removal negative case: the same pre-warmed
            # mover, staged with the trial and triggered MID-ROUTE once the
            # robot is under way (the fault-obstacle spawn pattern — the
            # blocking set_pose connection is warmed while disarmed, the
            # removal move is served through files during the armed trial).
            mat_worker_files=tuple(output/name for name in
                ("phase6-mat-ready.json","phase6-mat-target.json","phase6-mat-reply.json"))
            launch("phase6_mat_worker",[sys.executable,str(root/"fault_obstacle_worker.py"),
                "--world",world_name,"--name",MAT_MODEL,
                "--x",str((mat_rectangle["xmin"]+mat_rectangle["xmax"])/2),
                "--y",str((mat_rectangle["ymin"]+mat_rectangle["ymax"])/2),
                "--z",str(MAT_SURFACE_Z),
                "--ready-file",str(mat_worker_files[0]),
                "--target-file",str(mat_worker_files[1]),
                "--reply-file",str(mat_worker_files[2])])
        obstacle_worker_files=None
        if fault_stop_probe and fault_stop_mode=="obstacle_spawn":
            # Persistent pre-warmed mover: gz service-connection
            # establishment stalls the simulation server ~100 ms (native-7
            # lesson; reproduced October 24), so the set_pose connection is
            # established and warmed while the robot is still disarmed and
            # no new connection is ever created during the armed trial.
            obstacle_worker_files=tuple(output/name for name in
                ("fault-obstacle-ready.json","fault-obstacle-target.json","fault-obstacle-reply.json"))
            launch("fault_obstacle_worker",[sys.executable,str(root/"fault_obstacle_worker.py"),
                "--world",world_name,"--name",OBSTACLE_NAME,
                "--x",str(staging["x"]),"--y",str(staging["y"]),
                "--ready-file",str(obstacle_worker_files[0]),
                "--target-file",str(obstacle_worker_files[1]),
                "--reply-file",str(obstacle_worker_files[2])])
        required_sensors=("odom","scan") if sam3_observation else ("odom","scan","rgb","depth")
        until(lambda: all(sensors.get(k,{}).get("count",0)>=5 for k in required_sensors)
              and sensors.get("scan",{}).get("finite",0)>0 and frame_reports and frame_reports[-1]["ready"],
              60,"real sensors and loaded lidar geometry")
        if sam3_observation:
            # Camera liveness from the worker's status file: the worker
            # counts the compressor's trace records on the isolated
            # camera/semantic domain (this fixture holds no camera data on
            # the safety domain); dimensions are proven end to end by the
            # worker's mask/cloud decoding.
            def worker_camera_rows():
                try:
                    status=json.loads(sam3_worker_files[0].read_text())
                except (OSError, ValueError):
                    return False
                camera=status.get("camera") or {}
                if camera.get("count",0)<5:
                    return False
                for kind in ("rgb","depth"):
                    sensors[kind]={"stamp":camera.get("stamp_ns",0),
                        "frame":"camera_color_optical_frame",
                        "wall_received":status.get("written_wall_ns",0),
                        "count":camera.get("count",0),
                        "rollback":bool(camera.get("rollback")),
                        "transport":camera.get("input_transport"),
                        "traced":True}
                return True
            until(worker_camera_rows,90,"camera liveness from the observation worker")
        assert all(not v["rollback"] for v in sensors.values())
        assert sensors["scan"]["frame"]=="lidar_frame" and sensors["scan"]["finite"]>0
        if sam3_observation:
            assert all(sensors[k]["count"]>=5 and sensors[k]["frame"]=="camera_color_optical_frame"
                       and sensors[k]["transport"]=="gz" for k in ("rgb","depth")),dict(sensors)
        else:
            assert all(sensors[k]["frame"]=="camera_color_optical_frame" and sensors[k]["width"]==640
                       and sensors[k]["height"]==480 for k in ("rgb","depth"))
        assert frame_reports and frame_reports[-1]["ready"],frame_reports[-1:]
        checks.append({"case":"real_hotel_rgbd_scan_odom_clock","passed":True,"sensors":dict(sensors)})
        # The Sensors-system override must actually be the LOADED plugin (the
        # silent-non-rebuild lesson: the file's presence proves nothing). The
        # override's Configure prints the marker to the server's stdout at
        # startup; absence means the system library was loaded instead and
        # the render/physics coupling stall class is NOT fixed — fail closed.
        # Conditional on the override library existing in this image so older
        # pinned chains (without the override) remain re-runnable.
        override_lib=Path("/opt/semantic-safety/lib/libgz-sim-sensors-system.so")
        if override_lib.is_file():
            override_marker="phase5 sensors-system override: non-blocking PostUpdate active"
            override_log=(output/"gazebo.log").read_text(errors="replace") \
                if (output/"gazebo.log").exists() else ""
            checks.append({"case":"console_sensors_system_override_loaded",
                "passed":override_marker in override_log})
            if override_marker not in override_log:
                raise RuntimeError("Sensors-system override not loaded; arming forbidden")
        if console_only_server:
            runtime=console_identity(gazebo_child.pid,json.loads((root/"console-source-hashes.json").read_text()))
            (output/"console-server-runtime.json").write_text(json.dumps(runtime,indent=2))
            checks.append({"case":"console_server_identity",**{k:v for k,v in runtime.items() if k!="maps"}})
            absent=recording_absent(output,runtime["maps"])
            checks.append({"case":"console_server_recording_absent_before_arm",**absent})
            if not runtime["passed"] or not absent["passed"]:
                raise RuntimeError("console server identity/recording mismatch; arming forbidden")
        if contact_audit:
            until(lambda:contact_rows and contact_rows[-1]["steps"]>=500,label="native contact observer")
            assert contact_rows[-1]["missing"]==0 and {m["name"] for m in contact_rows[-1]["monitored"]}==expected_collisions
            checks.append({"case":"native_contact_components_live","passed":True})
            # Settled disarmed observation must pass before even starting Nav2.
            # Exact support whitelist, not a blanket floor-contact exemption.
            support_start=contact_rows[-1]["sim_ns"]
            dwell(.6)
            support_end=contact_rows[-1]["sim_ns"]
            support=assess(list(contact_rows),allowed_pairs=allowed_pairs,expected_names=expected_collisions,
                           start_sim=support_start,end_sim=support_end)
            checks.append({"case":"settled_support_geometry","enforced_before_arm":guarded,**support})
            if guarded and not support["passed"]:
                raise RuntimeError("contact-qualified baseline blocked by settled support geometry")
        launch_node("nav2_map_server","map_server"); launch_node("nav2_amcl","amcl")
        activate("map_server"); activate("amcl")
        initial=node.create_publisher(PoseWithCovarianceStamped,"/robot_1/initialpose",10)
        until(lambda:initial.get_subscription_count()>0,label="AMCL initial pose subscriber")
        pose=json.loads((output/"assets/map-audit.json").read_text())["initial_model_pose"]
        message=PoseWithCovarianceStamped(); message.header.frame_id="map"
        message.header.stamp=node.get_clock().now().to_msg()
        message.pose.pose.position.x,message.pose.pose.position.y=pose[:2]
        message.pose.pose.orientation.w=1.
        initial_variance=0.01
        message.pose.covariance[0]=message.pose.covariance[7]=initial_variance
        message.pose.covariance[35]=initial_variance
        initial.publish(message)
        until(lambda:poses and tf.can_transform("map","camera_color_optical_frame",Time()),30,"AMCL camera TF")
        assert math.hypot(poses[-1]["x"]-pose[0],poses[-1]["y"]-pose[1])<.2,poses[-1]
        for target in ("lidar_frame","camera_color_optical_frame"):
            transform=tf.lookup_transform("base_footprint",target,Time())
            t=transform.transform.translation
            expected=(-.032,0,.182) if target=="lidar_frame" else (.11,0,.15)
            assert all(abs(a-b)<1e-6 for a,b in zip((t.x,t.y,t.z),expected)),str(transform)
        checks.append({"case":"amcl_and_corrected_static_sensor_frames","passed":True,"amcl":poses[-1]})
        nodes=(("nav2_controller","controller_server"),("nav2_smoother","smoother_server"),
               ("nav2_planner","planner_server"),("nav2_behaviors","behavior_server"),
               ("nav2_velocity_smoother","velocity_smoother"),("nav2_collision_monitor","collision_monitor"),
               ("nav2_bt_navigator","bt_navigator"))
        for package,name in nodes:
            remaps=("-r","cmd_vel:=cmd_vel_nav") if name in ("controller_server","behavior_server","velocity_smoother") else ()
            launch_node(package,name,*remaps)
        for _,name in nodes: activate(name)
        if collision_monitor_diagnostics:
            monitor=next(child for name,child in processes if name=="collision_monitor")
            executable=os.readlink(f"/proc/{monitor.pid}/exe")
            libraries=sorted({line.split()[-1] for line in Path(f"/proc/{monitor.pid}/maps").read_text().splitlines()
                              if "libcollision_monitor_core.so" in line})
            tf2_libraries=sorted({line.split()[-1] for line in Path(f"/proc/{monitor.pid}/maps").read_text().splitlines()
                                  if "libtf2_ros.so" in line})
            expect_tf2_poll_overlay=os.getenv("PHASE5_TF2_POLL_1MS")=="1"
            expected_tf2_origin=("/opt/tf2-poll-overlay/" if expect_tf2_poll_overlay else "/opt/ros/jazzy/")
            identity={"executable":executable,"collision_monitor_libraries":libraries,
                "tf2_ros_libraries":tf2_libraries,"tf2_poll_overlay_expected":expect_tf2_poll_overlay,
                "tf2_origin_expected":expected_tf2_origin,
                "passed":executable=="/opt/nav2-collision-monitor-overlay/lib/nav2_collision_monitor/collision_monitor"
                    and libraries==["/opt/nav2-collision-monitor-overlay/lib/libcollision_monitor_core.so"]
                    and len(tf2_libraries)==1 and tf2_libraries[0].startswith(expected_tf2_origin)}
            (output/"collision-monitor-runtime.json").write_text(json.dumps(identity,indent=2))
            checks.append({"case":"opt_in_collision_monitor_timing_overlay_loaded",**identity})
            if not identity["passed"]:
                raise RuntimeError("required Collision Monitor/TF2 diagnostic libraries not loaded; disarmed observation aborted")
        if controller_endpoint_capture:
            controller=next(child for name,child in processes if name=="controller_server")
            executable=os.readlink(f"/proc/{controller.pid}/exe")
            libraries=sorted({line.split()[-1] for line in Path(f"/proc/{controller.pid}/maps").read_text().splitlines()
                              if "libcontroller_server_core.so" in line})
            identity={"executable":executable,"controller_libraries":libraries,
                "passed":executable=="/opt/nav2-controller-overlay/lib/nav2_controller/controller_server"
                    and libraries==["/opt/nav2-controller-overlay/lib/libcontroller_server_core.so"]}
            (output/"controller-runtime.json").write_text(json.dumps(identity,indent=2))
            checks.append({"case":"opt_in_controller_overlay_loaded",**identity})
            if not identity["passed"]: raise RuntimeError("controller candidate binary/library not loaded")
        # Record every action server currently visible in the real Nav2 graph.
        # This is an inventory for the future all-producer registry; it does
        # not claim that the observer owns/cancels these actions at runtime.
        action_services = {}
        # NOTE: do not name this loop variable "service" — it would shadow
        # the service() helper in main's scope and break every later call
        # (Phase 6 smoke attempt 9: the grid pull died with
        # "'str' object is not callable").
        for service_name, types in node.get_service_names_and_types():
            if "/_action/" in service_name:
                action_services[service_name] = sorted(types)
        action_names = sorted({service_name.split("/_action/", 1)[0]
                               for service_name in action_services})
        (output/"action-endpoint-inventory.json").write_text(json.dumps({
            "services": action_services,
            "action_names": action_names,
            "qualification": "disarmed graph inventory only; not runtime ownership or cancellation proof"
        }, indent=2))
        checks.append({"case":"nav2_action_endpoint_inventory_recorded",
                       "passed":bool(action_names), "action_names":action_names})
        endpoint_graph={}
        for topic,types in node.get_topic_names_and_types():
            if "/local_costmap/" in topic or "/global_costmap/" in topic:
                pubs=node.get_publishers_info_by_topic(topic)
                subs=node.get_subscriptions_info_by_topic(topic)
                endpoint_graph[topic]={"types":types,
                    "publishers":[{"node":p.node_name,"namespace":p.node_namespace} for p in pubs],
                    "subscriptions":[{"node":s.node_name,"namespace":s.node_namespace} for s in subs]}
            if topic.startswith("/robot_1/local_costmap/") and "costmap" in topic and types:
                for type_name in types:
                    message_type=get_message(type_name)
                    node.create_subscription(message_type,topic,
                        lambda _message,t=topic:timing_events.append({"kind":"costmap",
                            "topic":t,"wall_received":time.time_ns()}),10)
        (output/"costmap-endpoint-graph.json").write_text(json.dumps(endpoint_graph,indent=2))
        checks.append({"case":"actual_candidate_lifecycle_active","passed":True,"states":states})
        if phase6_semantic_arm:
            # Wiring contract for the paired arms: with the semantic layer
            # configured, BOTH costmaps must subscribe the SAM3 streams on
            # this safety domain (delivered by the runner's domain-85
            # semantic bridge sidecar) and nav2's per-layer publisher proves
            # the plugin is loaded in both maps; with costs excluded, no
            # costmap may subscribe any semantic topic and no semantic layer
            # may exist in the graph.
            semantic_topics=tuple(f"/robot_1/semantic/{kind}" for kind in
                                  ("mask","points","timing","label_info"))
            def semantic_subscription_rows():
                return {topic:[f"{s.node_namespace}/{s.node_name}"
                               for s in node.get_subscriptions_info_by_topic(topic)]
                        for topic in semantic_topics}
            global_costmap_node="/robot_1/global_costmap/global_costmap"
            local_costmap_node="/robot_1/local_costmap/local_costmap"
            layer_raw_topics=sorted(t for t,_ in node.get_topic_names_and_types()
                                    if t.endswith("/semantic_layer_raw"))
            if phase6_semantic_arm=="on":
                # The candidate carries the semantic layer in the GLOBAL
                # costmap only (user-approved October 28, 2026 — the local
                # map's semantic subscription loaded the controller's own
                # process; see pilot-1 pair-1-on-tfdiag/-qosfix). The global
                # costmap must subscribe all four semantic streams and nav2's
                # per-layer publisher must exist; the LOCAL costmap must stay
                # geometry-only — no semantic subscription, no layer.
                until(lambda:all(global_costmap_node in rows
                                 for rows in semantic_subscription_rows().values()),
                      60,"global costmap subscribed to the semantic streams")
                until(lambda:sorted(t for t,_ in node.get_topic_names_and_types()
                                    if t.endswith("/semantic_layer_raw"))==
                      ["/robot_1/global_costmap/semantic_layer_raw"],
                      30,"semantic layer publisher present in the global costmap")
                rows=semantic_subscription_rows()
                assert not any(local_costmap_node in subs for subs in rows.values()),rows
                assert "/robot_1/local_costmap/semantic_layer_raw" not in layer_raw_topics,layer_raw_topics
                # The label relay is the sole label_info publisher on this
                # domain; its shared status proves the transient-local latch
                # from the 88-chain actually arrived and was republished.
                relay_status=Path("/tmp/phase5-sam3-shared/label-relay.json")
                until(lambda:relay_status.is_file() and json.loads(
                          relay_status.read_text()).get("published",0)>0,
                      45,"label metadata relayed onto the safety domain")
                relay_state=json.loads(relay_status.read_text())
            else:
                rows=semantic_subscription_rows()
                costmap_nodes={global_costmap_node,local_costmap_node}
                assert not any(costmap_nodes&set(subs) for subs in rows.values()),rows
                assert not layer_raw_topics,layer_raw_topics
                relay_state=None
            checks.append({"case":"phase6_semantic_wiring","passed":True,
                "arm":phase6_semantic_arm,
                "layer_raw_topics":sorted(t for t,_ in node.get_topic_names_and_types()
                                          if t.endswith("/semantic_layer_raw")),
                "label_relay":relay_state,
                "subscriptions":semantic_subscription_rows()})
        sensor_graph={}
        for topic,_ in node.get_topic_names_and_types():
            if "scan" in topic:
                sensor_graph[topic]=[{"node":r.node_name,"namespace":r.node_namespace,
                    "type":r.topic_type} for r in node.get_subscriptions_info_by_topic(topic)]
        (output/"sensor-graph.json").write_text(json.dumps(sensor_graph,indent=2))
        scan_consumers={r["namespace"]+"/"+r["node"] for r in sensor_graph.get("/robot_1/scan_fixed",[])}
        assert {"/robot_1/local_costmap/local_costmap","/robot_1/global_costmap/global_costmap"}<=scan_consumers,sensor_graph
        checks.append({"case":"actual_costmaps_subscribe_to_corrected_lidar","passed":True})
        graph={}
        for topic,expected in (("cmd_vel_nav",{"controller_server","behavior_server"}),
                               ("cmd_vel_smoothed",{"velocity_smoother"}),
                               ("phase5/collision_checked",{"collision_monitor"})):
            rows=node.get_publishers_info_by_topic("/robot_1/"+topic)
            graph[topic]=[{"node":r.node_name,"namespace":r.node_namespace,"type":r.topic_type,
                           "gid":list(r.endpoint_gid)} for r in rows]
            assert {r.node_name for r in rows}==expected,graph
            assert all(r.node_namespace=="/robot_1" and r.topic_type=="geometry_msgs/msg/TwistStamped" for r in rows)
        assert not node.get_publishers_info_by_topic("/robot_1/cmd_vel")
        assert not node.get_publishers_info_by_topic("/cmd_vel")
        (output/"command-graph.json").write_text(json.dumps(graph,indent=2))
        validate_graph(graph)
        audit_publishers=node.get_publishers_info_by_topic("/phase5/command_audit")
        assert len(audit_publishers)==1 and audit_publishers[0].node_name=="phase5_command_observer"
        checks.append({"case":"actual_command_publisher_routes","passed":True})
        # Probe an unexpected writer on the disconnected final-command topic
        # before starting the timed navigation window. Only zero commands are
        # sent; the native drive guard remains disarmed.
        probe_topic="/robot_1/phase5/collision_checked"
        probe_gids=[]
        probe_observations=[]
        def probe_writer(name):
            probe_node=Node(name,namespace="/robot_1")
            publisher=probe_node.create_publisher(TwistStamped,probe_topic,10)
            until(lambda:publisher.get_subscription_count()>0,label=name+" observer subscription")
            endpoints=[p for p in probe_node.get_publishers_info_by_topic(probe_topic)
                       if p.node_name==name and p.node_namespace=="/robot_1"]
            assert len(endpoints)==1,(name,endpoints)
            gid=list(endpoints[0].endpoint_gid)
            assert len(gid)==16 and any(gid),gid
            start=len(commands)
            message=TwistStamped(); message.header.frame_id="base_footprint"
            message.header.stamp=node.get_clock().now().to_msg()
            for _ in range(3):
                publisher.publish(message); dwell(.05)
            until(lambda:any(r["kind"]=="checked" and r["publisher_gid"]==gid
                             for r in commands[start:]),label=name+" exact GUID observation")
            observed=next(r for r in commands[start:]
                          if r["kind"]=="checked" and r["publisher_gid"]==gid)
            try:
                validate_publisher_binding(graph,[observed])
            except ValueError:
                pass
            else:
                raise AssertionError("unexpected writer was accepted by the expected-publisher graph")
            probe_gids.append(gid); probe_observations.append(observed)
            probe_node.destroy_publisher(publisher); probe_node.destroy_node()
            until(lambda:all(list(p.endpoint_gid)!=gid
                             for p in node.get_publishers_info_by_topic(probe_topic)),
                  label=name+" endpoint removal")

        probe_writer("phase5_unexpected_writer_probe")
        probe_writer("phase5_unexpected_writer_probe")
        assert probe_gids[0]!=probe_gids[1],"publisher restart reused the old endpoint GUID"
        checks.append({"case":"unexpected_writer_and_publisher_restart_binding","passed":True,
            "first_guid":probe_gids[0],"replacement_guid":probe_gids[1],
            "both_resolved_and_rejected":len(probe_observations)==2})
        if os.getenv("PHASE5_OPERATOR_DEMO_TOKEN"):
            from operator_demo_gate import wait_for_operator
            def latest_disarmed_native():
                with mutex:
                    return dict(records[-1]) if records else {}
            # Presentation waiting and synchronous costmap inspection precede
            # native-clock binding, as in normal stopped setup. Never reset a
            # bound/latched clock to make a presentation proceed.
            assert clock is None and not bind_clock and adapter is None
            wait_for_operator(output, os.environ["PHASE5_OPERATOR_DEMO_TOKEN"],
                              lambda: dwell(.1), latest_disarmed_native,
                              timeout=1800)
            checks.append({"case":"explicit_operator_demo_release","passed":True})
        if phase6_semantic_arm=="on" and phase6_target_absent:
            # The target-absent negative case: no semantic cells are expected
            # and the layer's currency comes from accepted EMPTY observations
            # (SAM3 publishes valid empty detections; the layer accepts them
            # and stays current). Gate the plan on the observation worker's
            # sustained result streak so the stream's burst phase cannot
            # starve the layer's 500 ms acceptance window at plan time, then
            # record any observed target-cost cells as a recognition
            # diagnostic — never a gate (the Phase 2 waiver's territory).
            def phase6_absent_streak():
                try:
                    streak=json.loads(sam3_worker_files[0].read_text()).get("result_streak_s",0)
                except (OSError,ValueError):
                    streak=0
                return streak>=1.0
            until(phase6_absent_streak,60,
                  "observation result streak before planning (target absent)")
            absent_grid=pull_semantic_grid("global")
            absent_cells=grid_cost_cells(absent_grid,
                value=254 if phase6_lethal_experiment else SOFT_COST)
            checks.append({"case":"phase6_target_absent_cells","passed":True,
                "observed_cells":len(absent_cells),
                "cell_sample":[[round(x,3),round(y,3)] for x,y in absent_cells[:20]],
                "note":"diagnostic only: no target staged; false positives are "
                       "the Phase 2 recognition waiver's territory"})
        elif phase6_semantic_arm=="on":
            # The semantic layer's isCurrent() gates the costmap currency the
            # planner waits on: Nav2 cannot plan until a fresh semantic
            # observation has been ACCEPTED (the layer rejects startup
            # replays and pre-settling bursts, and NavFn then aborts with
            # "Costmap timed out waiting for update" — retained smoke
            # attempt 2). Gate the plan request on live soft costs at the
            # mat plus a sustained fresh-result streak from the observation
            # worker, so the SAM3 stream's burst phase cannot starve the
            # layer's 500 ms acceptance window at plan time.
            last_costs_pull=[0.0]
            gate_diagnostic={"last_costs":None,"last_streak":None}
            def phase6_costs_ready():
                now=time.monotonic()
                if now-last_costs_pull[0]<0.2:
                    return False
                last_costs_pull[0]=now
                gate_diagnostic["last_costs"]=semantic_costs_at_target_now()
                if not gate_diagnostic["last_costs"]["passed"]:
                    return False
                try:
                    streak=json.loads(sam3_worker_files[0].read_text()).get("result_streak_s",0)
                except (OSError,ValueError):
                    streak=0
                gate_diagnostic["last_streak"]=streak
                return streak>=1.0
            try:
                until(phase6_costs_ready,60,
                      "semantic soft costs accepted at the mat before planning")
            except WaitTimeout:
                # The gate must not swallow its own reason: retain the last
                # pull summary and worker streak for diagnosis.
                checks.append({"case":"phase6_costs_gate_diagnostic","passed":False,
                    "last_costs":gate_diagnostic["last_costs"],
                    "last_streak":gate_diagnostic["last_streak"]})
                raise
            costs=semantic_costs_at_target_now()
            checks.append({"case":"phase6_semantic_costs_at_target",
                **{k:v for k,v in costs.items() if k!="outside_target_cells"},
                "outside_target_cells":costs.get("outside_target_cells",[])[:20]})
        planner=ActionClient(node,ComputePathToPose,"/robot_1/compute_path_to_pose")
        until(planner.server_is_ready,label="planner action")
        # 0.35 m minus the 0.20 m arrival tolerance cannot reliably meet the
        # independent >0.20 m displacement criterion. Freeze this probe at
        # 0.50 m; do not relax the arrival or motion acceptance thresholds.
        goal_distance=0.50 if recovery_probe else 1.0
        goal=ComputePathToPose.Goal(); goal.goal.header.frame_id="map"
        if phase6_semantic_arm:
            # Frozen Phase 6 crossing goal (map-verified free): the straight
            # route from the start pose crosses the staged mat, and a detour
            # exists around it. Identical in both arms.
            goal.goal.pose.position.x,goal.goal.pose.position.y=phase6_goal
        else:
            goal.goal.pose.position.x=pose[0]+goal_distance; goal.goal.pose.position.y=pose[1]
        goal.goal.pose.orientation.w=1.
        goal.planner_id="GridBased"
        future=planner.send_goal_async(goal); until(future.done,label="plan accept")
        handle=future.result(); assert handle.accepted
        future=handle.get_result_async(); until(future.done,label="plan result")
        result=future.result(); assert result.status==4 and len(result.result.path.poses)>2,str(result)
        (output/"planned-path.json").write_text(json.dumps([[p.pose.position.x,p.pose.position.y] for p in result.result.path.poses]))
        checks.append({"case":"actual_hotel_plan_recovery_probe" if recovery_probe else
                       "actual_hotel_plan_phase6_crossing" if phase6_semantic_arm else
                       "actual_hotel_plan_one_meter",
                       "passed":True,"points":len(result.result.path.poses),
                       "goal_distance_m":(math.hypot(phase6_goal[0]-pose[0],phase6_goal[1]-pose[1])
                                          if phase6_semantic_arm else goal_distance),
                       "goal_xy":list(phase6_goal) if phase6_semantic_arm else None})
        nav=ActionClient(node,NavigateToPose,"/robot_1/navigate_to_pose")
        # The guarded "now" uses the authoritative native physics sim for
        # its ros field, not this fixture's transport-delayed /clock copy:
        # the controller's stamps derive from its own /clock subscription,
        # and the inter-subscriber skew under load exceeded the 20 ms
        # capture-join window (series 18 trial 1). The future-stamp guard
        # still rejects anything ahead of the ACTUAL current simulation
        # time; the native sim is its source.
        def guarded_now():
            native_sim=(clock.last or {}).get("sim_ns",0) if clock else 0
            return Now(time.monotonic_ns(),time.time_ns(),max(ros_clock,native_sim))
        until(nav.server_is_ready,label="navigator action")
        # Bind only after rendering/lifecycle AND action-client discovery, while still disarmed.
        # Never reset a latched clock once observation of task commands starts.
        request=NavigateToPose.Goal(); request.pose=goal.goal
        if guarded:
            adapter=HotelGuardAdapter(node,clock,supervisor_tf,
                guarded_now,graph,action_names,
                expected_scan_max=float(lidar_range) if lidar_range else 3.5,
                allow_backup_wait=recovery_probe,
                require_semantics=semantic_fault_probe)
            task_executor.add_node(adapter.task)
            # Discover all clients before freezing the private graph. Priming
            # cancels every freshly started server without actuator authority.
            until(lambda:adapter.link.ready and adapter.task.client.server_is_ready()
                  and all(c.service_is_ready() for c in adapter.cancel_clients.values()),
                  30,"guard transport and complete action graph")
            dwell(1.)
            adapter.prepare()
            bind_clock=True
            until(lambda:clock and clock.stationary(time.time_ns()),label="native stationary capture epoch")
            if sam3_observation:
                # The separately qualified SAM3 runtime must be ready and
                # streaming fresh results BEFORE the guarded readiness gate:
                # with the semantic leases required, adapter.ready cannot
                # pass until results flow, and a process-loss restart needs
                # minutes to reload the model (matrix 3 trial 5 timed out
                # adapter.ready's 10 s window against a still-reloading
                # SAM3). The worker reports readiness through its status
                # file with a window that covers the model reload.
                def sam3_worker_ready():
                    try:
                        status=json.loads(sam3_worker_files[0].read_text())
                    except (OSError, ValueError):
                        return False
                    last=status.get("last_result_receipt_wall_ns")
                    # Armed-semantic trials may only arm from a sustained
                    # fresh-result streak: the SAM3 stream has a reproducible
                    # burst phase clustered in the pre-arm readiness window,
                    # and arming on a momentary fresh receipt during those
                    # bursts starves the 500 ms semantic lease within seconds
                    # (matrix 7 trial 4 stopped 0.2 s after arming). The
                    # observation-only series keeps its frozen predicate.
                    streak_ok=(status.get("result_streak_s",0)>=SEMANTIC_ARMING_STREAK_S
                               if semantic_fault_probe else True)
                    return (status.get("ready") is True
                            and status.get("labels") is not None
                            and last is not None
                            and time.time_ns()-last<1_000_000_000
                            and streak_ok)
                until(sam3_worker_ready,120,"SAM3 observation readiness before arming")
                labels=(json.loads(sam3_worker_files[0].read_text()).get("labels") or {})
                checks.append({"case":"sam3_observation_ready","passed":
                    labels.get("prompt")=="red mat"
                    and set(labels.get("active_labels",[]))=={0,2},
                    "labels":labels})
            if phase6_tf_witness:
                # The tf witness must be live and already resolving capture
                # stamps before any authority is granted: a dead witness
                # discovered at the mat would waste the trial (and its
                # absence still fails closed later through the lease).
                witness_file=Path("/tmp/phase5-sam3-shared")/"tf-witness.json"
                def tf_witness_ready():
                    try: record=json.loads(witness_file.read_text())
                    except (OSError,ValueError): return False
                    return (record.get("schema")=="phase6-tf-witness/v1"
                            and record.get("seq",0)>=1
                            and time.time_ns()-record.get("written_wall_ns",0)<1_000_000_000)
                until(tf_witness_ready,45,
                      "capture-time TF witness live and qualified before arming")
            if phase6_semantic_arm:
                # Pre-arm render warmup (user-approved October 28, 2026): the
                # on-arm's goal-approach orbit sweeps the camera through
                # scene content not seen on the detour route; its FIRST
                # render there costs ~190 ms of render-thread CPU (the root
                # of the remaining endgame failure), delaying the gpu_lidar
                # scan ~450 ms and the controller's TF wait ~76 ms past the
                # 100 ms command authority. The staged warmup cameras are
                # inactive without subscribers; subscribe each one briefly
                # NOW — still disarmed — so the render thread loads that
                # content, then unsubscribe (they deactivate again). Both
                # arms warm identically. Fail closed if any camera produced
                # no frames: an unwarmed trial is exactly the failure class
                # this exists to prevent.
                warmup_counts={}
                def warmup_callback(topic):
                    def callback(_message):
                        warmup_counts[topic]=warmup_counts.get(topic,0)+1
                    return callback
                for index in range(12):
                    topic=f"/phase5/warmup/{index}/image"
                    warmup_counts[topic]=0
                    gz.subscribe(GzImage,topic,warmup_callback(topic))
                    until(lambda t=topic: warmup_counts[t]>=5,30,
                          f"render warmup frames from camera {index}")
                    gz.unsubscribe(topic)
                checks.append({"case":"phase6_render_warmup",
                    "passed":all(count>=5 for count in warmup_counts.values()),
                    "frames":dict(warmup_counts)})
                if min(warmup_counts.values())<5:
                    raise RuntimeError("render warmup incomplete; arming forbidden")
            until(adapter.ready,10,"native-zero real-sensor registry readiness")
            (output/"guard-client-graph.json").write_text(json.dumps(adapter.expected_clients,indent=2))
            if obstacle_worker_files is not None:
                until(lambda:obstacle_worker_files[0].is_file(),90,
                      "fault obstacle worker connection warmed before arming")
            if phase6_target_removal:
                # The mid-trial removal mover must be warm before arming (the
                # fault-obstacle spawn pattern: no transport connection is
                # ever created during the armed trial).
                until(lambda:mat_worker_files[0].is_file(),90,
                      "semantic mat mover connection warmed before arming")
            if phase6_stationary_smoke:
                # Phase 6 semantic-on stationary smoke: no goal is dispatched
                # and the native guard stays disarmed. With wiring and fresh
                # soft costs verified above, remove the staged mat through
                # the pre-warmed mover and require the stale cells to clear
                # within the Phase 4 expiry bound (observation lifetime plus
                # two update periods, plus the measured result latency and
                # one publish period). The pump keeps its full cadence: the
                # native clock fails closed at a 100 ms processing-time
                # capture age (matrix 12 lesson).
                smoke={"case":"phase6_stationary_smoke","passed":False,
                       "stage":"costs_verified"}
                checks.append(smoke)
                until(lambda:mat_worker_files[0].is_file(),90,
                      "semantic mat mover connection warmed")
                mat_worker_files[1].write_text(json.dumps(mat_removal))
                until(lambda:mat_worker_files[2].is_file(),15,
                      "semantic mat removal move completion")
                reply=json.loads(mat_worker_files[2].read_text())
                if not reply.get("moved"):
                    raise RuntimeError("semantic mat removal failed: "+json.dumps(reply))
                moved_wall=time.time_ns()
                smoke.update(stage="target_removed")
                try:
                    ages=json.loads(sam3_worker_files[1].read_text()).get("ages_ms") or []
                except (OSError,ValueError):
                    ages=[]
                ordered=sorted(ages)
                p95=(ordered[min(len(ordered)-1,max(0,math.ceil(.95*len(ordered))-1))]
                     if ordered else 500.)
                bound=clearance_bound_s(1.0,0.1,p95,0.2)
                cleared_wall=None
                last_clear_pull=[0.0]
                def old_target_cleared():
                    nonlocal cleared_wall
                    now=time.monotonic()
                    if now-last_clear_pull[0]<0.1:
                        return bool(cleared_wall)
                    last_clear_pull[0]=now
                    grid=pull_semantic_grid("global")
                    if cells_in_rectangle(grid_cost_cells(grid),mat_rectangle):
                        return False
                    cleared_wall=time.time_ns()
                    return True
                until(old_target_cleared,bound+5,
                      "stale semantic cells cleared after target removal")
                clear_ms=(cleared_wall-moved_wall)/1e6 if cleared_wall else None
                smoke.update(stage="target_removed_and_cleared",
                    passed=clear_ms is not None and clear_ms<=bound*1000,
                    removal_pose=mat_removal,move_reply=reply,
                    p95_capture_age_ms=p95,clearance_bound_s=bound,
                    clear_time_ms=clear_ms,mover_wall_ns=moved_wall)
                capture_sensor_transforms()
                sam3_observation_checks(scope_stop_wall=moved_wall,stationary_smoke=True)
                with mutex: smoke_snapshot=list(records)
                assert smoke_snapshot and all(not r["armed"] and not r["pending"]
                    and r["applied_vx"]==r["applied_wz"]==0 for r in smoke_snapshot)
                smoke_physical=[r["physical"] for r in smoke_snapshot
                    if r.get("physical") and r["physical"]["velocity_valid"]]
                assert smoke_physical and max(math.hypot(p["x"]-pose[0],p["y"]-pose[1])
                    for p in smoke_physical)<.02
                checks.append({"case":"native_never_armed_and_robot_stationary","passed":True})
                success=all(c["passed"] for c in checks)
                if not success:
                    raise RuntimeError("phase 6 stationary smoke failed; retained evidence")
                return
            if phase6_semantic_arm and os.getenv("PHASE6_CONTROLLER_SNAPSHOT") == "1":
                # Opt-in diagnostic only: capture controller/smoother/console
                # stacks when a Phase 6 arm trial stops on command_expired.
                # The console server is included since the v3 override: the
                # remaining stall class lives outside the Sensors system and
                # its per-thread wchan/syscall (unprivileged /proc reads; the
                # gdb attach itself is ptrace-blocked) names the wait site.
                # The gdb fork freezes the fixture's UDP status thread ~1.6 s
                # and latches native_capture_stale — never use it when clean
                # timing evidence matters.
                phase6_snapshot_pids={name:child.pid for name,child in processes
                      if name in ("controller_server","velocity_smoother","gazebo")}
            contact_start=adapter.clock.last["sim_ns"]
            assert adapter.request(request),"explicit guarded request rejected"
            if phase6_semantic_arm:
                # Per-row joiner/ledger drain diagnostics (pilot-1 off-arm
                # admission-gap investigation): every drain attempt for every
                # row, with the phase, bracket and ledger state. Lock-free
                # deque append; dumped with the evidence at shutdown.
                joiner_diag=collections.deque(maxlen=262144)
                adapter.joiner.diagnostics=joiner_diag
                adapter.joiner.clock=clock
            try:
                if tf_loss_probe or fault_stop_probe or semantic_fault_probe:
                    # Shared pre-injection predicate: an actively commanded,
                    # armed session with independently verified physical
                    # motion. A stop before injection fails either probe.
                    probe_state={"check":None}
                    def moving_with_verified_command():
                        if adapter.co.state=="stopped":
                            if probe_state["check"] is not None:
                                probe_state["check"].update(stage="stopped_before_injection",
                                    reason=adapter.co.gate.reason)
                            raise RuntimeError("probe stopped before injection: "+adapter.co.gate.reason)
                        status=clock.status or {}; physical=status.get("physical") or {}
                        recent=next((r for r in reversed(adapter.command_trace)
                            if r.get("kind")=="checked" and r.get("forwarded") is True),{})
                        return (adapter.co.state=="active" and status.get("armed") is True
                            and not status.get("pending") and not clock.fault
                            and adapter.task.session.may_command(adapter.co.task_token)
                            and physical.get("velocity_valid") and physical.get("speed",0)>.02
                            and status.get("applied_vx",0)>.02
                            and 0<=time.time_ns()-physical.get("wall_ns",0)<100_000_000
                            and 0<=time.time_ns()-recent.get("processed_wall",0)<100_000_000
                            and recent.get("velocity",[0])[0]>.02
                            # 0.3 m of established motion (user-approved
                            # November 2, matching the semantic fault
                            # probe's standard): the SAM3 registration
                            # contract needs >=10 moving results, and the
                            # fault must stop a fully moving robot, not the
                            # first creep (qualification-12 moving-stop
                            # trial-01 injected at 0.5 s with 4 moving
                            # results; the stop itself was perfect at
                            # 56.4 ms).
                            and math.hypot(physical["x"]-pose[0],physical["y"]-pose[1])>=.3)
                if tf_loss_probe:
                    probe_check={"case":"tf_loss_revokes_motion_permission","passed":False,
                                 "mode":tf_loss_mode,"stage":"waiting_for_current_motion",
                                 "tf_freshness_ms":500,"command_freshness_ms":100}
                    checks.append(probe_check)
                    probe_state["check"]=probe_check
                    until(moving_with_verified_command,10,"verified command and physical motion before TF fault")
                    amcl=next(child for name,child in processes if name=="amcl")
                    injected_steady=time.monotonic_ns()
                    injected_wall=time.time_ns()
                    injected_sim=clock.status["physical"]["sim_ns"]
                    probe_check["stage"]="fault_injected"
                    try:
                        if tf_loss_mode=="amcl":
                            os.killpg(amcl.pid,signal.SIGSTOP)
                            paused_processes.append(amcl)
                        else:
                            supervisor_tf.delivery.blocked=True
                        fault_events.append({"event":"tf_loss_injected","mode":tf_loss_mode,
                            "steady_ns":injected_steady,"wall_ns":injected_wall,"sim_ns":injected_sim,
                            "pid":amcl.pid if tf_loss_mode=="amcl" else None,
                            "native_status":clock.status,"tf_freshness_ms":500,"command_freshness_ms":100})
                        # Continue collecting failure evidence even if command
                        # freshness stops motion before the buffered TF runs out.
                        until(lambda:adapter.co.state=="stopped" and map_failure(
                            adapter.tf_trace,injected_wall,injected_sim) is not None,
                            3,"stop plus observed frozen map TF with live odometry")
                        failure=map_failure(adapter.tf_trace,injected_wall,injected_sim)
                        fault_reason=adapter.co.gate.reason
                        fault_trigger=adapter.co.gate.trigger_steady
                        fault_events.append({"event":"observed_map_tf_failure",**failure})
                        fault_events.append({"event":"guard_stopped_after_tf_loss","steady_ns":fault_trigger,
                            "reason":fault_reason,"latency_ms":(fault_trigger-injected_steady)/1e6})
                        probe_check.update(stage="observed_fault_and_stop",
                            passed=stop_reason_qualified(tf_loss_mode,fault_reason) and fault_trigger>=injected_steady,
                            reason=fault_reason,injection_to_trigger_ms=(fault_trigger-injected_steady)/1e6,
                            injection_to_failed_lookup_ms=(failure["first_failure_wall_ns"]-injected_wall)/1e6)
                        if tf_loss_mode=="supervisor":
                            capture=Time(nanoseconds=failure["stamp"])
                            full_tf_ok=bool(tf.can_transform("map",failure["frame"],capture))
                            dropped=list(supervisor_tf.delivery.dropped)
                            checks.append({"case":"supervisor_tf_loss_isolated_from_nav2","passed":bool(dropped) and full_tf_ok,
                                "full_buffer_has_same_capture":full_tf_ok,"dropped_transforms":len(dropped)})
                            fault_events.append({"event":"supervisor_tf_dropped","transforms":dropped})
                    except BaseException:
                        adapter.co.stop("tf_loss_probe_error")
                        raise
                    finally:
                        if tf_loss_mode=="amcl" and amcl in paused_processes:
                            os.killpg(amcl.pid,signal.SIGCONT)
                            paused_processes.remove(amcl)
                        elif tf_loss_mode=="supervisor":
                            supervisor_tf.delivery.blocked=False
                        fault_events.append({"event":"tf_delivery_restored","mode":tf_loss_mode,
                            "steady_ns":time.monotonic_ns(),"wall_ns":time.time_ns()})
                if fault_stop_probe:
                    probe_check={"case":"fault_stop_"+fault_stop_mode,"passed":False,
                                 "mode":fault_stop_mode,"stage":"waiting_for_current_motion",
                                 "command_freshness_ms":100,"input_freshness_ms":500}
                    checks.append(probe_check)
                    probe_state["check"]=probe_check
                    until(moving_with_verified_command,10,"verified command and physical motion before fault injection")
                    injected_steady=time.monotonic_ns()
                    injected_wall=time.time_ns()
                    injected_sim=clock.status["physical"]["sim_ns"]
                    probe_check["stage"]="fault_injected"
                    state_publisher=None
                    stalled_processes=[]
                    try:
                        if fault_stop_mode=="collision_state":
                            # Chain-level collision intervention: the same
                            # CollisionMonitorState STOP message the real
                            # monitor publishes, injected on the observed
                            # topic after verified motion.
                            state_publisher=node.create_publisher(CollisionMonitorState,
                                "/robot_1/collision_monitor_state",10)
                            until(lambda:state_publisher.get_subscription_count()>0,
                                  5,"collision state subscriber")
                            message=CollisionMonitorState()
                            message.action_type=1; message.polygon_name="StopEnvelope"
                            state_publisher.publish(message)
                        elif fault_stop_mode=="scan_loss":
                            # Supervisor-side evidence cutoff only: Nav2,
                            # the costmaps and the Collision Monitor keep
                            # receiving the real scan stream.
                            adapter.fault_scan_blocked=True
                        elif fault_stop_mode=="command_stall":
                            controller=next(child for name,child in processes
                                            if name=="controller_server")
                            os.killpg(controller.pid,signal.SIGSTOP)
                            stalled_processes.append(controller)
                        elif fault_stop_mode=="transport_loss":
                            os.kill(adapter.link.process.pid,signal.SIGSTOP)
                        elif fault_stop_mode=="obstacle_spawn":
                            # Physical fault: the pre-placed post is moved
                            # mid-trial into the corridor, inside the
                            # Collision Monitor stop envelope but outside
                            # the padded hull, so real lidar returns trip
                            # the monitor's STOP while no footprint contact
                            # can occur. Served by the persistent pre-warmed
                            # worker through files, so the armed trial never
                            # creates a transport connection and the pump
                            # keeps running throughout.
                            spawn_pose=obstacle_spawn_pose(clock.status["physical"])
                            obstacle_worker_files[1].write_text(json.dumps(spawn_pose))
                            until(lambda:obstacle_worker_files[2].is_file(),15,
                                  "fault obstacle move completion")
                            reply=json.loads(obstacle_worker_files[2].read_text())
                            if not reply.get("moved"):
                                raise RuntimeError("fault obstacle move failed: "+json.dumps(reply))
                            fault_events.append({"event":"obstacle_moved","pose":spawn_pose,
                                "reply":reply,"steady_ns":time.monotonic_ns(),
                                "wall_ns":time.time_ns()})
                        fault_events.append({"event":"fault_injected","mode":fault_stop_mode,
                            "steady_ns":injected_steady,"wall_ns":injected_wall,"sim_ns":injected_sim,
                            "native_status":clock.status,"command_freshness_ms":100,
                            "input_freshness_ms":500})
                        until(lambda:adapter.co.state=="stopped",
                              fault_stop_wait_seconds(fault_stop_mode),
                              "guarded stop after fault injection")
                        fault_reason=adapter.co.gate.reason
                        fault_trigger=adapter.co.gate.trigger_steady
                        fault_events.append({"event":"guard_stopped_after_fault","steady_ns":fault_trigger,
                            "reason":fault_reason,"latency_ms":(fault_trigger-injected_steady)/1e6})
                        probe_check.update(stage="observed_fault_and_stop",
                            passed=(fault_stop_reason_qualified(fault_stop_mode,fault_reason)
                                    and fault_trigger>=injected_steady
                                    and (fault_trigger-injected_steady)/1e6
                                        >= fault_stop_latency_floor_ms(fault_stop_mode)),
                            reason=fault_reason,
                            injection_to_trigger_ms=(fault_trigger-injected_steady)/1e6)
                        if fault_stop_mode=="obstacle_spawn":
                            # The stop must come from the real monitor's STOP
                            # state, not from a coincidental other path.
                            collisions=[e for e in adapter.events
                                if e.get("event")=="collision_state" and e.get("action")==1]
                            probe_check["collision_state_events"]=len(collisions)
                            probe_check["passed"]=bool(probe_check["passed"] and collisions)
                    except BaseException:
                        adapter.co.stop("fault_stop_probe_error")
                        raise
                    finally:
                        # Restore every injected fault before evidence
                        # collection; restoration must never resume motion.
                        if fault_stop_mode=="scan_loss":
                            adapter.fault_scan_blocked=False
                        for child in stalled_processes:
                            os.killpg(child.pid,signal.SIGCONT)
                        if fault_stop_mode=="transport_loss":
                            try: os.kill(adapter.link.process.pid,signal.SIGCONT)
                            except ProcessLookupError: pass
                        if fault_stop_mode=="collision_state" and state_publisher is not None:
                            clear=CollisionMonitorState()
                            clear.action_type=0; clear.polygon_name="StopEnvelope"
                            state_publisher.publish(clear)
                        fault_events.append({"event":"fault_restored","mode":fault_stop_mode,
                            "steady_ns":time.monotonic_ns(),"wall_ns":time.time_ns()})
                if semantic_fault_probe:
                    from semantic_fault_probe import (late_success_key as semantic_late_success_key,
                        late_success_wait_seconds as semantic_late_success_wait,
                        stop_reason_qualified as semantic_reason_qualified,
                        stop_wait_seconds as semantic_stop_wait)
                    probe_check={"case":"semantic_fault_"+semantic_fault_mode,"passed":False,
                                 "mode":semantic_fault_mode,"stage":"waiting_for_current_motion",
                                 "input_freshness_ms":500,"command_zero_limit_ms":100}
                    checks.append(probe_check)
                    def semantic_motion_verified():
                        # Stronger than the fault-stop predicate: the armed
                        # supervisor must be actively observing motion (a
                        # fresh semantic result while the robot is moving and
                        # past 0.3 m) before the perception fault is injected.
                        if adapter.co.state=="stopped":
                            probe_check.update(stage="stopped_before_injection",
                                reason=adapter.co.gate.reason)
                            raise RuntimeError("semantic probe stopped before injection: "
                                               +adapter.co.gate.reason)
                        status=clock.status or {}; physical=status.get("physical") or {}
                        recent=next((r for r in reversed(adapter.command_trace)
                            if r.get("kind")=="checked" and r.get("forwarded") is True),{})
                        latest=(semantic_probe["leases"].get("semantic") or {})
                        return (adapter.co.state=="active" and status.get("armed") is True
                            and not status.get("pending") and not clock.fault
                            and physical.get("velocity_valid") and physical.get("speed",0)>.02
                            and status.get("applied_vx",0)>.02
                            and math.hypot(physical["x"]-pose[0],physical["y"]-pose[1])>=.3
                            and latest and 0<=time.time_ns()-latest.get("wall_ns",0)<1_000_000_000)
                    until(semantic_motion_verified,15,
                          "verified semantic-armed motion before perception fault")
                    semantic_probe["phase"]="motion_verified"
                    injected_steady=time.monotonic_ns()
                    injected_wall=time.time_ns()
                    injected_sim=clock.status["physical"]["sim_ns"]
                    probe_check["stage"]="fault_injected"
                    paused_semantic=[]
                    try:
                        if semantic_fault_mode=="camera_path_loss":
                            # The camera data path onto the perception domain:
                            # the capture traces, calibration and clock all
                            # stop, starving SAM3 and the camera lease.
                            bridge=next(child for name,child in processes
                                        if name=="camera_bridge")
                            os.killpg(bridge.pid,signal.SIGSTOP)
                            paused_semantic.append(bridge)
                        elif semantic_fault_mode=="tf_loss":
                            amcl=next(child for name,child in processes if name=="amcl")
                            os.killpg(amcl.pid,signal.SIGSTOP)
                            paused_semantic.append(amcl)
                        # hung_inference / process_loss / transport_loss are
                        # injected externally by the semantic fault-matrix
                        # runner through the coordinator status file.
                        fault_events.append({"event":"semantic_fault_injected",
                            "mode":semantic_fault_mode,"injected_by":"fixture"
                                if paused_semantic else "series-runner",
                            "steady_ns":injected_steady,"wall_ns":injected_wall,
                            "sim_ns":injected_sim,"native_status":clock.status,
                            "input_freshness_ms":500,"command_zero_limit_ms":100})
                        until(lambda:adapter.co.state=="stopped",
                              semantic_stop_wait(semantic_fault_mode),
                              "guarded stop after semantic fault")
                        fault_reason=adapter.co.gate.reason
                        fault_trigger=adapter.co.gate.trigger_steady
                        fault_events.append({"event":"guard_stopped_after_semantic_fault",
                            "steady_ns":fault_trigger,"reason":fault_reason,
                            "latency_ms":(fault_trigger-injected_steady)/1e6})
                        probe_check.update(stage="observed_fault_and_stop",
                            passed=(semantic_reason_qualified(semantic_fault_mode,fault_reason)
                                    and fault_trigger>=injected_steady),
                            reason=fault_reason,
                            injection_to_trigger_ms=(fault_trigger-injected_steady)/1e6)
                    except BaseException:
                        adapter.co.stop("semantic_fault_probe_error")
                        raise
                    finally:
                        for child in paused_semantic:
                            try: os.killpg(child.pid,signal.SIGCONT)
                            except ProcessLookupError: pass
                        semantic_probe["phase"]="stopped"
                        fault_events.append({"event":"semantic_fault_restored",
                            "mode":semantic_fault_mode,
                            "steady_ns":time.monotonic_ns(),"wall_ns":time.time_ns()})
                if recovery_probe:
                    until(lambda:any(r["endpoint"]=="/robot_1/backup" and r["status"]==2
                                     for r in adapter.registry.events),
                          20,"guarded BackUp action entered active state")
                # The Phase 6 crossing goal needs ~27 s of simulation time
                # (~42 s wall at the observed RTF) of motion alone; the
                # frozen 20 s window from the 1 m-goal era killed a healthy
                # crossing mid-motion at 2.0 m (pair-1-off-tfwitness-2, the
                # robot on the mat and still moving at 0.15 m/s).
                # RTF recalibration (user-approved class, 2026-11-02): the
                # 90 s wall window was set when the crossing took ~30 s wall
                # at RTF ~0.9 (a 3x margin). The 30 Hz G4 candidate runs at
                # RTF ~0.675, where the same route takes ~40 s of motion
                # and observed on-arm navigations run 60-100+ s wall
                # (series-3 trial-010-on stalled the window at ~90 s while
                # the robot was still creeping toward the goal). 135 s
                # restores the historical 3x-motion multiple with headroom.
                navigation_window_s = 135 if phase6_semantic_arm else 20
                # The target-removal negative case: fire the pre-warmed mover
                # once the robot is independently under way (~1.0 m of
                # displacement, before the mat), so the removal happens
                # mid-route through files with no transport connection.
                removal_state={"moved_wall_ns":None,"reply":None,"displacement_m":None}
                def phase6_removal_trigger():
                    if removal_state["moved_wall_ns"] is not None: return
                    status=clock.status or {}; physical=status.get("physical") or {}
                    if not physical.get("velocity_valid"): return
                    start=json.loads((output/"assets/map-audit.json").read_text())["initial_model_pose"]
                    displacement=math.hypot(physical["x"]-start[0],physical["y"]-start[1])
                    if displacement<1.0 or adapter.co.state!="active": return
                    removal_state["displacement_m"]=round(displacement,3)
                    removal_state["moved_wall_ns"]=time.time_ns()
                    mat_worker_files[1].write_text(json.dumps(mat_removal))
                def navigation_terminal():
                    if phase6_target_removal: phase6_removal_trigger()
                    return (adapter.co.state=="stopped" or adapter.task.session.state=="idle"
                            and adapter.task.session.token is not None)
                until(navigation_terminal,
                      navigation_window_s,"guarded navigation terminal or latched stop")
                if phase6_target_removal:
                    # The negative case's evidence: the removal fired mid-route
                    # and the pre-warmed mover served it. Completion itself is
                    # judged by the standard goal check; the stale cells clear
                    # by the Phase 4 expiry contract (not re-gated here).
                    removal_reply=None
                    try:
                        until(lambda:mat_worker_files[2].is_file(),15,
                              "semantic mat mid-trial removal move completion")
                        removal_reply=json.loads(mat_worker_files[2].read_text())
                    except WaitTimeout:
                        pass
                    checks.append({"case":"phase6_target_removal",
                        "passed":removal_state["moved_wall_ns"] is not None
                                 and bool(removal_reply and removal_reply.get("moved")),
                        "trigger_displacement_m":removal_state["displacement_m"],
                        "trigger_wall_ns":removal_state["moved_wall_ns"],
                        "move_reply":removal_reply})
                if (phase6_semantic_arm and os.getenv("PHASE6_CONTROLLER_SNAPSHOT") == "1"
                        and adapter.co.state=="stopped"
                        and adapter.co.gate.reason=="command_expired"
                        and not (output/"controller-block-snapshot.json").is_file()):
                    # The command chain expired during active motion: the
                    # controller is very likely still inside its block (the
                    # cancel is only processed seconds later). Capture the
                    # thread stacks NOW — post-failure, bounded, in the act.
                    last_raw=None
                    for row in reversed(commands):
                        if row.get("kind")=="raw":
                            last_raw=row.get("wall_received",0)
                            break
                    in_act={"detected_wall_ns":time.time_ns(),
                            "last_raw_wall_received_ns":last_raw,
                            "trigger":"command_expired_during_controller_silence"}
                    for name,pid in phase6_snapshot_pids.items():
                        in_act[name]=timeout_snapshot(pid)
                    (output/"controller-block-snapshot.json").write_text(
                        json.dumps(in_act,indent=2))
            except WaitTimeout as error:
                adapter.co.stop("navigation_trial_timeout")
                if tf_loss_probe:
                    probe_check.update(passed=False,error=str(error),reason=adapter.co.gate.reason)
            until(lambda:adapter.task.session.state=="idle" and not any(adapter.registry.active().values())
                  and adapter.cancel_acks==adapter.registry.endpoints,
                  10,"parent/descendants terminal and cancellation acknowledgements")
            checks.append({"case":"cancellation_terminal_and_acknowledged","passed":True})
            stationary_check={"case":"native_stationary_after_task","passed":False}
            checks.append(stationary_check)
            try:
                until(lambda:adapter.clock.stationary(time.time_ns()),10,"native stationary after task")
                stationary_check["passed"]=True
            except WaitTimeout as error:
                # Keep the gate FAILED and the clock latched, but retain the
                # remaining independent checks/stop metrics for diagnosis.
                stationary_check.update(error=str(error),clock_fault=adapter.clock.fault)
            if tf_loss_probe:
                hold_start=time.monotonic_ns()
                until(lambda:supervisor_tf.can_transform("map",sensors["scan"]["frame"],
                    Time(nanoseconds=sensors["scan"]["stamp"])),3,"restored capture-time supervisor TF")
                dwell(.5)
                held=[r for r in records if r["steady_ns"]>=hold_start]
                checks.append({"case":"no_automatic_resume_after_tf_restore","passed":bool(held)
                    and all(not r["armed"] and not r["pending"] and r["applied_vx"]==r["applied_wz"]==0 for r in held)
                    and adapter.co.state=="stopped" and adapter.task.session.state=="idle",
                    "native_samples":len(held)})
            if fault_stop_probe:
                # Every fault is restored (or, for the spawned obstacle,
                # simply remains present): nothing may resume motion.
                hold_start=time.monotonic_ns()
                dwell(.5)
                held=[r for r in records if r["steady_ns"]>=hold_start]
                checks.append({"case":"no_automatic_resume_after_fault_restore","passed":bool(held)
                    and all(not r["armed"] and not r["pending"] and r["applied_vx"]==r["applied_wz"]==0 for r in held)
                    and adapter.co.state=="stopped" and adapter.task.session.state=="idle",
                    "native_samples":len(held),"mode":fault_stop_mode})
            if semantic_fault_probe:
                # Late-success proof: after restoration, wait (bounded) for a
                # fresh successful perception response — the camera lease, the
                # inference heartbeat, or restored capture-time TF — then
                # verify it does not resume motion.
                from semantic_fault_probe import late_success_key as semantic_late_success_key
                from semantic_fault_probe import late_success_wait_seconds as semantic_late_success_wait
                late={"case":"late_success_does_not_resume_motion","passed":False,
                      "mode":semantic_fault_mode,"stage":"waiting_for_late_success"}
                checks.append(late)
                key=semantic_late_success_key(semantic_fault_mode)
                if served_topology and key in ("inference_heartbeat", "camera"):
                    # A resumed status publisher alone is insufficient: the
                    # served path must produce a new successful result.
                    key = "semantic"
                baseline_sequence=(semantic_probe["last_sequences"].get(key,0) if key else 0)
                def late_success_observed():
                    if key is None:
                        # TF loss: restored capture-time map->camera TF.
                        latest=(semantic_probe["leases"].get("semantic") or {})
                        capture=latest.get("ros_ns",0)
                        return bool(capture and tf.can_transform(
                            "map","camera_color_optical_frame",Time(nanoseconds=capture)))
                    item=semantic_probe["leases"].get(key) or {}
                    return item.get("sequence",0)>baseline_sequence
                deadline=time.monotonic()+semantic_late_success_wait(semantic_fault_mode)
                while time.monotonic()<deadline:
                    pump()
                    if late_success_observed(): break
                    # Full until-loop cadence: the native clock latches
                    # native_capture_stale at a 100 ms processing-time capture
                    # age, and a relaxed dwell cadence lets the ingest queue
                    # lag creep past it during the long transport-loss dwell
                    # (matrix 12 trial 5: 104.5 ms, a false latch — the
                    # capture was 52 ms old at callback).
                    time.sleep(.003)
                else:
                    late.update(stage="late_success_not_observed",
                        passed=False,
                        reason="no fresh perception response within the bounded wait")
                if late.get("stage")=="waiting_for_late_success":
                    hold_start=time.monotonic_ns()
                    dwell(3)
                    held=[r for r in records if r["steady_ns"]>=hold_start]
                    late.update(stage="late_success_observed",
                        passed=bool(held)
                        and all(not r["armed"] and not r["pending"]
                                and r["applied_vx"]==r["applied_wz"]==0 for r in held)
                        and adapter.co.state=="stopped"
                        and adapter.task.session.state=="idle",
                        native_samples=len(held),
                        late_success_key=key or "capture_time_tf")
            terminal_status=adapter.task.session.terminal_status
            checks.append({"case":"guarded_recovery_probe_terminal" if recovery_probe else
                           "guarded_tf_loss_probe_terminal" if tf_loss_probe else
                           "guarded_fault_stop_probe_terminal" if fault_stop_probe else
                           "guarded_semantic_fault_terminal" if semantic_fault_probe else "guarded_real_hotel_one_meter_goal",
                           "passed":terminal_status==(5 if (tf_loss_probe or fault_stop_probe
                                                            or semantic_fault_probe) else 4),
                           "terminal_status":terminal_status,"reason":adapter.co.gate.reason})
            if (phase6_semantic_arm and terminal_status==5
                    and os.getenv("PHASE6_CONTROLLER_SNAPSHOT") == "1"):
                # Opt-in post-failure evidence only (see the warning above).
                # permission is revoked): capture the controller/smoother
                # thread stacks to diagnose the silent mid-route controller
                # stop class (pair-1-off attempts 1-2: deterministic stop at
                # x~16.5, full speed, no log, action EXECUTING). Same
                # discipline as the console-shutdown snapshot: bounded,
                # unprivileged, never during a live measurement.
                block_snapshot={}
                if not (output/"controller-block-snapshot.json").is_file():
                    # The silence watchdog may already have captured the
                    # block in the act; never overwrite that evidence.
                    for name,child in processes:
                        if name in ("controller_server","velocity_smoother") and child.poll() is None:
                            block_snapshot[name]=timeout_snapshot(child.pid)
                    if block_snapshot:
                        (output/"controller-block-snapshot.json").write_text(
                            json.dumps(block_snapshot,indent=2))
            checks.append({"case":"closed_graph_and_descendants_terminal","passed":bool(
                adapter.registry.idle() and adapter.cancel_acks==adapter.registry.endpoints)})
            if recovery_probe:
                transitions=adapter.registry.events
                def completed(endpoint):
                    rows=[r["status"] for r in transitions if r["endpoint"]==endpoint]
                    return 2 in rows and 4 in rows
                backup=[r for r in adapter.command_trace if r["kind"]=="checked"
                        and r.get("forwarded") is True and r["velocity"][0]<-0.001]
                checks.append({"case":"guarded_backup_and_wait_actions_completed","passed":
                    completed("/robot_1/backup") and completed("/robot_1/wait"),
                    "transitions":transitions})
                checks.append({"case":"backup_reverse_commands_bounded","passed":bool(backup)
                    and min(r["velocity"][0] for r in backup)>=-0.055,
                    "reverse_commands":len(backup),
                    "minimum_checked_vx":min((r["velocity"][0] for r in backup),default=0.)})
                wait=[r for r in transitions if r["endpoint"]=="/robot_1/wait" and r["status"]==2]
                done=[r for r in transitions if r["endpoint"]=="/robot_1/wait" and r["status"]==4]
                holds=[e for e in adapter.co.events if e["event"]=="wait_zero_hold"]
                interval_holds=[e for e in holds if wait and done
                    and wait[0].get("steady_ns",0)<=e["steady_ns"]<=done[-1].get("steady_ns",0)]
                first_hold=min((e["steady_ns"] for e in interval_holds),default=None)
                wait_end=done[-1]["steady_ns"]-50_000_000 if done and done[-1].get("steady_ns") else None
                checks.append({"case":"wait_interval_native_applied_velocity_zero",
                    **wait_zero_metrics(records,first_hold,wait_end,adapter.co.native_token)})
                hold_gaps=[(b["steady_ns"]-a["steady_ns"])/1e6
                           for a,b in zip(interval_holds,interval_holds[1:])]
                checks.append({"case":"wait_zero_holds_are_bounded_and_continuous",
                    "passed":len(interval_holds)>=20 and (not hold_gaps or max(hold_gaps)<=50),
                    "hold_count":len(interval_holds),"maximum_gap_ms":max(hold_gaps,default=None)})
            contact_end=next(r["physical"]["sim_ns"] for r in reversed(records) if r.get("physical"))
        else:
            bind_clock=True
            until(lambda:clock and clock.stationary(time.time_ns()),label="native stationary capture epoch")
            future=nav.send_goal_async(request); until(future.done,label="navigation accept")
            handle=future.result(); assert handle.accepted
            terminal=handle.get_result_async()
            dwell(float(os.getenv("PHASE5_TEST_NAV_SECONDS", "3")))
            cancel=handle.cancel_goal_async(); until(cancel.done,label="cancel acknowledge")
            assert cancel.result().goals_canceling
            until(terminal.done,label="navigation terminal cancellation")
            assert terminal.result().status==5,str(terminal.result())
            terminal_status=terminal.result().status
        dwell(.5)
        matched=[r for r in commands if r["kind"]=="checked" and r["admitted"] and r["velocity"][0]>0]
        positives=[r for r in commands if r["kind"]=="checked" and r["velocity"][0]>0]
        checks.append({"case":"real_nav2_nonzero_chain_and_terminal_result","passed":bool(positives),
            "positive_checked":len(positives),"terminal_status":terminal_status})
        checks.append({"case":"real_command_capture_mapping","passed":bool(matched and clock and not clock.fault),
            "matched_positive_checked":len(matched),"clock_fault":clock.fault if clock else "missing native clock"})
        ordinary_commands=[r for r in commands if r.get("publisher_gid") not in probe_gids]
        try:
            validate_publisher_binding(graph,ordinary_commands)
            checks.append({"case":"per_message_publisher_binding","passed":True})
        except ValueError as error:
            # Independent disarmed diagnostics may continue, but never turn a
            # failed binding into actuator permission or an overall PASS.
            checks.append({"case":"per_message_publisher_binding","passed":False,"reason":str(error)})
        try:
            validate_observations(graph,ordinary_commands)
            checks.append({"case":"command_frame_and_axes","passed":True})
        except ValueError as error:
            checks.append({"case":"command_frame_and_axes","passed":False,"reason":str(error)})
        capture_sensor_transforms()
        with mutex: snapshot=list(records)
        physical=[r["physical"] for r in snapshot if r.get("physical") and r["physical"]["velocity_valid"]]
        if guarded:
            minimum_motion=.02 if (tf_loss_probe or fault_stop_probe) else .2
            checks.append({"case":"independent_native_motion_observed","passed":bool(physical and
                max(math.hypot(p["x"]-pose[0],p["y"]-pose[1]) for p in physical)>minimum_motion),
                "minimum_required_m":minimum_motion})
            injected=(tf_loss_probe or fault_stop_probe) and injected_steady is not None
            stopping=({"passed":False,"reason":"fault_not_injected"}
                if (tf_loss_probe or fault_stop_probe) and injected_steady is None else
                metrics(snapshot,adapter.co.events,
                    fault_injected_steady_ns=injected_steady if injected else None))
            if tf_loss_probe:
                stopping["scope"]="private "+tf_loss_mode+" TF-loss trial; native stop metrics, not full fault-matrix qualification"
            if fault_stop_probe:
                stopping["scope"]="private "+fault_stop_mode+" moving fault-stop trial; native stop metrics for this fault class only"
            if semantic_fault_probe:
                # Externally injected modes have no in-fixture injection
                # timestamp; the stop is bound to the armed session and the
                # latency measured from the gate's 500 ms freshness trigger.
                stopping["scope"]=("private "+semantic_fault_mode+
                    " armed-semantic fault trial; zero within 100 ms of the"
                    " 500 ms semantic freshness trigger; not the full matrix")
            checks.append({"case":"tf_loss_native_stop_metrics" if tf_loss_probe else
                           "fault_stop_native_stop_metrics" if fault_stop_probe else
                           "semantic_fault_native_stop_metrics" if semantic_fault_probe else
                           "baseline_native_stop_metrics",**stopping})
            if contact_audit:
                checks.append({"case":"baseline_contact_window","start_sim":contact_start,
                    "end_sim":contact_end,**assess(list(contact_rows),allowed_pairs=allowed_pairs,expected_names=expected_collisions,
                        start_sim=contact_start,end_sim=contact_end)})
            if sam3_observation:
                # The worker process owns every semantic subscription; this
                # analysis only reads its aggregated file. The timing window
                # is scoped to the pre-fault period for the armed semantic
                # fault trials.
                stop_wall=None
                if semantic_fault_probe:
                    stop_wall=(adapter.now().wall if adapter.co.gate.trigger_steady
                               else None)
                sam3_observation_checks(scope_stop_wall=stop_wall,
                                        target_absent=phase6_target_absent)
        else:
            assert snapshot and all(not r["armed"] and not r["pending"] and r["applied_vx"]==r["applied_wz"]==0 for r in snapshot)
            assert physical and max(math.hypot(p["x"]-pose[0],p["y"]-pose[1]) for p in physical)<.02
            checks.append({"case":"native_never_armed_and_robot_stationary","passed":True})
        success=all(c["passed"] for c in checks)
    finally:
        for child in paused_processes:
            try: os.killpg(child.pid,signal.SIGCONT)
            except ProcessLookupError: pass
        (output/"fault-injection-events.json").write_text(json.dumps(fault_events,indent=2))
        if adapter:
            adapter.co.stop("fixture_shutdown")
            (output/"guard-events.json").write_text(json.dumps({"coordinator":adapter.co.events,
                "adapter":adapter.events,"task":adapter.task.events,"registry_fault":adapter.registry.fault,
                "registry_goals":adapter.registry.goals,"registry_events":adapter.registry.events,
                "gate_reason":adapter.co.gate.reason,
                "task_state":adapter.task.session.state,"task_outcome":adapter.task.session.outcome},indent=2))
            (output/"guard-commands.json").write_text(json.dumps(adapter.command_trace,indent=2))
            (output/"guard-tf.json").write_text(json.dumps(adapter.tf_trace,indent=2))
            task_executor.remove_node(adapter.task)
            adapter.close()
        shutdown_report=shutdown(processes,
            graceful={"gazebo":gazebo_stop} if console_only_server else None,
            timeout=30 if sam3_observation else 5,
                                 on_timeout={"gazebo":timeout_snapshot} if console_only_server else None)
        (output/"process-shutdown.json").write_text(json.dumps(shutdown_report,indent=2))
        alive_at_shutdown=shutdown_report["alive_at_shutdown"]
        forced_shutdown=shutdown_report["forced"]
        for handle in handles: handle.close()
        if console_only_server:
            gazebo=next((child for name,child in processes if name=="gazebo"),None)
            lifecycle=lifecycle_complete((output/"gazebo.log").read_text()
                                         if (output/"gazebo.log").exists() else "")
            checks.append({"case":"console_server_shutdown","passed":bool(gazebo is not None
                and alive_at_shutdown["gazebo"] and "gazebo" not in forced_shutdown
                and shutdown_report["graceful"].get("gazebo",{}).get("passed") is True
                and gazebo.returncode==0 and lifecycle["passed"]),
                "returncode":gazebo.returncode if gazebo else None,"forced": "gazebo" in forced_shutdown,
                "lifecycle":lifecycle})
            checks.append({"case":"console_server_recording_absent",**recording_absent(output)})
            success=success and all(c["passed"] for c in checks)
        (output/"commands.json").write_text(json.dumps(commands,indent=2))
        (output/"clock-events.json").write_text(json.dumps(clock_events,indent=2))
        (output/"timing-events.json").write_text(json.dumps(timing_events,indent=2))
        (output/"stage-timings.json").write_text(json.dumps({
            "pump":stage_timings.report(),
            "adapter":adapter.timings.report() if adapter else None},indent=2))
        (output/"frames.json").write_text(json.dumps(frame_reports,indent=2))
        (output/"poses.json").write_text(json.dumps(poses,indent=2))
        (output/"control-geometry.json").write_text(json.dumps(control_geometry,indent=2))
        (output/"planner-endpoints.json").write_text(json.dumps(planner_paths,indent=2))
        (output/"trace.jsonl").write_text("".join(json.dumps(r)+"\n" for r in records))
        # stdout tee for network-outage evidence recovery (user-approved
        # November 3): the pod's log survives on the node after oc cp becomes
        # impossible (paired-series-7/8/11/12 all lost PASSING trials to
        # workstation network outages spanning the retrieval window). The
        # trajectory rows phase6_trial needs are printed compactly; the
        # runner reconstructs trace.jsonl from these lines when the copy
        # path fails. Byte-faithful to the same records the copy delivers.
        for row in records:
            item=row.get("physical") if isinstance(row,dict) else None
            if isinstance(item,dict) and item.get("velocity_valid"):
                print(f"TRACE_PHYS {item['wall_ns']} {item['x']:.6f} {item['y']:.6f}", flush=True)
        if sam3_observation:
            (output/"udp-loop-timing.json").write_text(json.dumps(
                [{"s":a,"r":b,"a":c} for a,b,c in udp_loop_timing]))
        if phase6_semantic_arm and adapter is not None and getattr(adapter.joiner,"diagnostics",None) is not None:
            (output/"joiner-drain-diag.json").write_text(json.dumps(
                list(adapter.joiner.diagnostics)))
        if phase6_semantic_arm=="on":
            (output/"phase6-costcells-timeline.json").write_text(json.dumps(
                cost_cells_timeline,indent=2))
        (output/"contacts.json").write_text(json.dumps(contact_rows,indent=2))
        (output/"scan-audit.json").write_text(json.dumps(scan_audit,indent=2))
        (output/"tf-edges.json").write_text(json.dumps({
            "map_odom_edges":tf_edge_rows,
            "odom_base_edges_phase6":list(odom_edge_rows) if phase6_semantic_arm else None,
            "odom_base_gaps_over_50ms":odom_base_state["gaps"]},indent=2))
        summary={"passed":success,"checks":checks,"sensors":sensors,"states":states,
            "controller_endpoint_capture":controller_endpoint_capture,
            "collision_monitor_diagnostics":collision_monitor_diagnostics,
            "moving_timing_trace":moving_timing_trace,
            "gz_thread_probe":gz_thread_probe,
            "fault_stop_probe":fault_stop_probe,
            "fault_stop_mode":fault_stop_mode,
            "sam3_observation":sam3_observation,
            "semantic_fault_probe":semantic_fault_probe,
            "semantic_fault_mode":semantic_fault_mode,
            "phase6_semantic_arm":phase6_semantic_arm,
            "phase6_stationary_smoke":phase6_stationary_smoke,
            "phase6_diagnostic_no_85_bridge":phase6_diagnostic_no_85_bridge,
            "phase6_tf_probe":phase6_tf_probe,
            "phase6_cost_cells_timeline":phase6_cost_cells_timeline,
            "phase6_lethal_experiment":phase6_lethal_experiment,
            "phase6_target_absent":phase6_target_absent,
            "phase6_target_removal":phase6_target_removal,
            "phase6_tf_witness":phase6_tf_witness,
            "phase6_tf_witness_stats":tf_witness_state,
            "demo_localization":("fixed_spawn_origin_wheel_odometry" if os.getenv("PHASE5_OPERATOR_DEMO_TOKEN") else "amcl"),
            "phase6_goal_xy":list(phase6_goal) if phase6_goal else None,
            "phase6_mat_ground_truth":mat_rectangle,
            "phase6_candidate_yaml":candidate_yaml if phase6_semantic_arm else None,
            "headless_gpu_rendering":headless_rendering,
            "console_only_server":console_only_server,
            "world_record_period_s":float(record_period) if record_period is not None else 0.,
            "world_recording":not (no_world_recording or console_only_server),
            "diagnostic_only":(record_period is not None or api_server
                               or collision_monitor_diagnostics or moving_timing_trace
                               or phase6_stationary_smoke
                               or (phase6_semantic_arm and phase6_diagnostic_no_85_bridge)
                               or (phase6_semantic_arm and phase6_tf_probe)
                               or (phase6_semantic_arm and phase6_cost_cells_timeline)),
            "clock_fault":clock.fault if clock else None,"qualification":
                "private "+tf_loss_mode+" TF-loss probe; normal 500 ms TF / 100 ms command thresholds; NOT full Phase 5/SAM3" if tf_loss_probe else
                "private "+fault_stop_mode+" moving fault-stop probe; unchanged watchdog/lease/freshness thresholds; NOT full Phase 5/SAM3" if fault_stop_probe else
                "private "+semantic_fault_mode+" armed-semantic fault trial; supervisor armed with semantic leases, costs excluded; zero <=100 ms after the 500 ms trigger; NOT full Phase 5" if semantic_fault_probe else
                "private Phase 6 stationary semantic-on wiring/clearing smoke; disarmed, no goal dispatched; NOT a Phase 6 navigation trial" if phase6_stationary_smoke else
                "private Phase 6 "+phase6_semantic_arm+"-arm paired navigation trial on the guarded fixture"+(
                    "; capture-time TF witness sidecar feeds the tf lease (user-approved 2026-10-28, fail-closed, UDP-companion-path pattern)"+(
                        " plus TF probe diagnostics" if phase6_tf_probe else "")
                    if phase6_tf_witness else
                    ("; TF probe diagnostics" if phase6_tf_probe else ""))+(
                    "; LETHAL-COST EXCLUSION EXPERIMENT (target 254, not the qualified soft cost 200; a model-only restriction is not a production safety boundary)"
                    if phase6_lethal_experiment else "")+"; NOT a Phase 6 series pass" if phase6_semantic_arm else
                "private observation-only SAM3 registration/load trial; semantic costs excluded from navigation; NOT full Phase 5" if sam3_observation else
                "private BackUp/Wait/FollowPath 0.50 m recovery probe; NOT full Phase 5/SAM3" if recovery_probe else
                "private guarded hotel no-recovery integration; NOT full baseline or SAM3" if guarded else
                "stationary disarmed real hotel/Nav2; NOT moving navigation or SAM3"}
        (output/"summary.json").write_text(json.dumps(summary,indent=2))
        print(json.dumps(summary),flush=True)
        ingress_executor.shutdown()
        observer_executor.shutdown()
        task_executor.shutdown()
        ingress_node.destroy_node()
        node.destroy_node(); rclpy.shutdown()
    if not success:
        raise RuntimeError("hotel subgates failed; retained independent checks and native trace")


if __name__=="__main__": main()
