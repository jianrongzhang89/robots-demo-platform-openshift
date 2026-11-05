"""Private flat-world integration: real ROS actions + gate + native wheel guard.

Task backend, raw/checked commands and scan/TF evidence are CONTROLLED FIXTURES,
not Nav2 planning/perception. Native clock, physical motion and actuator are real
Gazebo components. Never attach to an existing simulator or canonical domain.
"""
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import threading
import time

import rclpy
from geometry_msgs.msg import TwistStamped
from nav2_msgs.action import NavigateToPose
from nav2_msgs.msg import CollisionMonitorState
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from gz.transport13 import Node as GzNode
from gz.msgs10.stringmsg_pb2 import StringMsg

from guarded_coordinator import GuardedCoordinator
from native_clock import NativeClock
from native_link import NativeLink
from nav_task_client import NavTaskClient
from prepare_assets import write_assets
from safety_core import Evidence, Now, MS
from verify_nav_task_client import Backend


def main():
    if (os.getenv("ROS_DOMAIN_ID") != "85" or not os.getenv("GZ_PARTITION","").startswith("phase5-watchdog-")
            or os.getenv("GZ_IP") != "127.0.0.1"):
        raise RuntimeError("private fixture only")
    output = Path("/tmp/phase5-native-results"); output.mkdir(exist_ok=False)
    assets = write_assets(output / "assets")
    traces, pending, checks, captures = [], [], [], []
    mutex = threading.Lock()
    gz = GzNode()
    def receive(message):
        item = json.loads(message.data)
        with mutex:
            traces.append(item); pending.append(item)
    gz.subscribe(StringMsg,"/phase5/drive/status",receive)
    rclpy.init()
    backend = Backend()
    holder = {}
    task = NavTaskClient("/phase5_fixture/navigate_to_pose",
                         lambda token,reason: holder["coordinator"].stop(reason) if "coordinator" in holder else None)
    traffic = Node("phase5_controlled_commands")
    executor = SingleThreadedExecutor()
    for node in (backend,task,traffic): executor.add_node(node)
    raw_pub = traffic.create_publisher(TwistStamped,"/phase5_fixture/raw",10)
    checked_pub = traffic.create_publisher(TwistStamped,"/phase5_fixture/checked",10)
    collision_pub = traffic.create_publisher(CollisionMonitorState,"/phase5_fixture/collision_state",10)
    traffic.create_subscription(CollisionMonitorState,"/phase5_fixture/collision_state",
        lambda m:holder["coordinator"].collision(m.action_type) if "coordinator" in holder else None,10)
    raw = {}
    def decode(message):
        if (message.header.frame_id != "base_footprint" or message.twist.linear.z != 0
                or message.twist.angular.x != 0 or message.twist.angular.y != 0):
            raise ValueError("invalid command frame/axes")
        return (message.header.stamp.sec*1_000_000_000+message.header.stamp.nanosec,
                (message.twist.linear.x,message.twist.linear.y,message.twist.angular.z))
    def on_raw(message):
        stamp, velocity = decode(message)
        raw[stamp] = velocity
        while len(raw)>32: raw.pop(next(iter(raw)))
        if supervisor_running and "coordinator" in holder: holder["coordinator"].source(stamp,velocity)
    def on_checked(message):
        stamp, velocity = decode(message)
        # Immediate forwarding is also a supervisor output path. Stalling
        # only tick() no longer simulates a stalled producer; suspend ingress
        # too while keeping the independent native-status observer running.
        if not supervisor_running or "coordinator" not in holder: return
        co = holder["coordinator"]
        if stamp in raw: co.neutral_capture(stamp,raw[stamp],velocity)
        co.checked(stamp,velocity)
    traffic.create_subscription(TwistStamped,"/phase5_fixture/raw",on_raw,10)
    traffic.create_subscription(TwistStamped,"/phase5_fixture/checked",on_checked,10)
    link = NativeLink()
    clock = None
    server = None
    mode, scan_enabled, supervisor_running = "normal", True, True
    last_publish = last_tick = 0
    successful = False

    def now():
        return Now(time.monotonic_ns(),time.time_ns(),clock.last["sim_ns"] if clock and clock.last else 0)

    def pump():
        nonlocal clock,last_tick,last_publish
        with mutex:
            chunk = list(pending); pending.clear()
        if "coordinator" not in holder:
            link.poll()
            if not link.ready:
                return  # zero authority; finish transport setup before binding capture epoch
        for status in chunk:
            if not status["physical"]: continue
            if clock is None:
                if time.time_ns()-status["physical"]["wall_ns"]>=100*MS: continue
                clock = NativeClock(status["clock_epoch"])
            if clock.observe(status,time.time_ns()):
                if "coordinator" not in holder:
                    # This launch contains ONLY our owned fake NavigateToPose
                    # server. Never reuse this predicate for the full Nav2 graph.
                    holder["coordinator"] = GuardedCoordinator(clock,link,task,
                        lambda: task.client.server_is_ready() and all(not h.is_active for h in backend.goals.values()),now,
                        registry_owned=lambda token: task.client.server_is_ready() and all(
                            not handle.is_active or key==token for key,handle in backend.goals.items()))
                p = clock.last
                ev = Evidence(clock.epoch,p["sequence"],p["wall_ns"],p["sim_ns"])
                if supervisor_running:
                    for key in ("clock","odom","tf") + (("scan",) if scan_enabled else ()):
                        holder["coordinator"].gate.observe(key,ev,now())
        for _ in range(12): executor.spin_once(timeout_sec=0)
        if "coordinator" not in holder:
            link.poll(); return
        co = holder["coordinator"]
        t = time.monotonic_ns()
        if t-last_publish>=20*MS and clock.last:
            last_publish = t
            stamp = clock.last["sim_ns"]
            message = TwistStamped(); message.header.frame_id = "base_footprint"
            message.header.stamp.sec,message.header.stamp.nanosec = divmod(stamp,1_000_000_000)
            message.twist.linear.x = .1 if co.state=="active" and task.session.may_command(co.task_token) else 0.
            bound = clock.wall_bound(stamp,time.time_ns())
            captured = time.time_ns()
            if bound is not None:
                assert bound<=captured, "clock mapping manufactured a future capture"
                captures.append({"stamp_ns":stamp,"wall_lower_bound":bound,"publisher_wall":captured,
                                 "conservative_age_ms":(captured-bound)/1e6})
            if mode=="normal": raw_pub.publish(message)
            checked_pub.publish(message)
        if supervisor_running and t-last_tick>=20*MS:
            last_tick = t; co.tick()
        if server and server.poll() is not None: raise RuntimeError("private Gazebo server exited")

    def until(predicate, timeout=10):
        end = time.monotonic()+timeout
        while time.monotonic()<end:
            pump()
            if predicate(): return
            time.sleep(.002)
        co = holder.get("coordinator")
        raise RuntimeError("combined timeout: "+json.dumps({"clock_fault":clock.fault if clock else None,
            "state":co.state if co else None,"reason":co.gate.reason if co else None,
            "task":vars(task.session),"native":clock.status if clock else None}))

    def dwell(seconds):
        end = time.monotonic()+seconds
        until(lambda:time.monotonic()>=end,seconds+2)

    def ready():
        co = holder.get("coordinator")
        return bool(co and link.ready and clock.stationary(time.time_ns()) and co.neutral
                    and task.client.server_is_ready() and task.session.state=="idle")

    def goal():
        value = NavigateToPose.Goal(); value.pose.header.frame_id="map"
        value.pose.pose.orientation.w=1.
        return value

    with (output/"gazebo.log").open("w+") as log:
        try:
            server = subprocess.Popen(["gz","sim","--force-version","8","-r","-s","-v","2",
                "--record-path",str(output/"gz-record"),str(output/"assets/watchdog.world")],stdout=log,stderr=subprocess.STDOUT)
            until(ready,40)
            co = holder["coordinator"]
            assert not any(t["applied_vx"]!=0 for t in traces)
            checks.append({"case":"startup_live_stationary_neutral_and_idle","passed":True})
            # Native applied-zero proof is required, not an idle Nav2 heartbeat.
            saved = clock.status["applied_vx"]; clock.status["applied_vx"] = .1
            assert not co.request(goal()); clock.status["applied_vx"] = saved
            checks.append({"case":"nonzero_native_output_blocks_arm","passed":True})
            for case in ("operator_cancel","collision_stop","scan_loss","orphan_checked_commands","supervisor_output_stalled","transport_worker_killed"):
                mode, scan_enabled = "normal", True
                until(ready)
                assert co.request(goal()), "readiness arm rejected"
                if case=="operator_cancel":
                    mode="checked_only"
                    until(lambda:co.state=="active")
                    setup_begin=time.monotonic_ns()
                    dwell(.4)
                    assert co.gate.armed and clock.last["speed"]<.005
                    assert all(row["applied_vx"]==0 for row in traces if row["steady_ns"]>=setup_begin)
                    checks.append({"case":"bounded_setup_remains_zero_without_bound_source_command","passed":True})
                    mode="normal"
                until(lambda:co.state=="active" and clock.last["speed"]>.07)
                dwell(.5)
                assert co.gate.armed and clock.last["speed"]>.07, "premature stop before injection"
                fault = time.monotonic_ns()
                token = co.task_token
                if case=="operator_cancel": co.stop("operator_cancel")
                elif case=="collision_stop":
                    collision_pub.publish(CollisionMonitorState(action_type=CollisionMonitorState.STOP,
                                                                polygon_name="injected_fixture_stop"))
                elif case=="scan_loss": scan_enabled=False
                elif case=="orphan_checked_commands": mode="checked_only"
                elif case=="supervisor_output_stalled": supervisor_running=False
                else: link.process.kill(); link.process.join(timeout=3)
                if case=="supervisor_output_stalled":
                    until(lambda:clock.status["stop_applied_steady_ns"]>=fault and clock.status["applied_vx"]==0)
                    assert clock.status["stop_applied_steady_ns"]-fault<=100*MS
                    supervisor_running=True
                until(lambda:co.state=="stopped" and clock.status["stop_applied_steady_ns"]>=fault
                      and clock.status["applied_vx"]==0)
                stop = clock.status.copy()
                if case=="collision_stop":
                    collision_pub.publish(CollisionMonitorState(action_type=CollisionMonitorState.DO_NOTHING))
                until(lambda:clock.last["speed"]<.005)
                dwell(.4)
                assert not co.request(goal()), "unresolved action allowed rearm"
                assert not task.session.may_command(token)
                revoke = next(e for e in reversed(co.events) if e["event"]=="permission_revoked")
                zero = stop["stop_applied_steady_ns"]
                latency = (zero-revoke["trigger_steady_ns"])/1e6
                assert latency<=100, f"supervisor-trigger to wheel zero exceeded 100 ms: {latency}"
                if case=="scan_loss": assert co.gate.reason=="scan_stale"
                if case=="collision_stop": assert co.gate.reason=="collision_monitor_stop"
                if case=="orphan_checked_commands": assert co.gate.reason in ("command_expired","native_session_lost")
                with mutex: samples = list(traces)
                before = [v["physical"] for v in samples if v["physical"] and v["physical"]["steady_ns"]<=fault]
                after = {v["physical"]["steady_ns"]:v["physical"] for v in samples
                         if v["physical"] and v["physical"]["steady_ns"]>fault}
                points = [before[-1]]+[after[k] for k in sorted(after)]
                distance = sum(math.hypot(b["x"]-a["x"],b["y"]-a["y"]) for a,b in zip(points,points[1:]))
                checks.append({"case":case,"passed":True,"fault_steady_ns":fault,
                    "reason":co.gate.reason,"native_reason":stop["reason"],
                    "trigger_to_applied_zero_ms":latency,"fault_to_applied_zero_ms":(zero-fault)/1e6,
                    "native_zero_preceded_supervisor_trigger":zero<revoke["trigger_steady_ns"],
                    "fault_to_stopped_sampled_distance_m":distance,
                    "first_sample_before_fault_ms":(fault-points[0]["steady_ns"])/1e6,
                    "final_physical_speed":clock.last["speed"],"cancel_ack":task.session.cancel_ack})
                until(lambda:task.session.cancel_ack is True)
                backend.finish(token,5)
                until(lambda:task.session.state=="idle")
                assert co.state=="stopped" and not co.gate.armed
            checks.append({"case":"terminal_completion_does_not_automatically_rearm","passed":True})
            assert captures and all(x["wall_lower_bound"]<=x["publisher_wall"] for x in captures)
            checks.append({"case":"native_source_time_bound_never_refreshed_from_receipt","passed":True,
                           "captures":len(captures),"maximum_conservative_age_ms":max(x["conservative_age_ms"] for x in captures)})
            successful = True
        finally:
            co = holder.get("coordinator")
            if co: co.stop("fixture_cleanup")
            link.close()
            if server and server.poll() is None:
                server.send_signal(signal.SIGINT)
                try: server.wait(timeout=10)
                except subprocess.TimeoutExpired: server.kill(); server.wait(timeout=5)
            result = {"event":"phase5_combined_guard_fixture","passed":successful,"checks":checks,"assets":assets,
                "scope":"private physics; controlled commands, action backend and scan/TF evidence; not Nav2 hotel navigation"}
            (output/"summary.json").write_text(json.dumps(result,indent=2))
            (output/"coordinator-events.json").write_text(json.dumps(co.events if co else [],indent=2))
            (output/"task-events.json").write_text(json.dumps(task.events,indent=2))
            (output/"command-captures.json").write_text(json.dumps(captures,indent=2))
            with (output/"trace.jsonl").open("w") as handle:
                for row in traces: handle.write(json.dumps(row)+"\n")
            print(json.dumps(result),flush=True)
            executor.shutdown(); backend.server.destroy(); task.client.destroy()
            for node in (backend,task,traffic): node.destroy_node()
            rclpy.shutdown()


if __name__=="__main__": main()
