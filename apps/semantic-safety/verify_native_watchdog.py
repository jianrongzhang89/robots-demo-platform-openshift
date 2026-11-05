#!/usr/bin/env python3
"""Private physics fixture: native watchdog, actual hotel robot, no Nav2/SAM3.

Never attach to an existing Gazebo world. This script starts and stops its own
server, only in a phase5-watchdog-* partition, and retains full native traces.
"""
import argparse
import json
import math
import multiprocessing
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import uuid

from gz.transport13 import Node
from gz.msgs10.stringmsg_pb2 import StringMsg
from gz.msgs10.boolean_pb2 import Boolean
from gz.msgs10.world_control_pb2 import WorldControl
from gz.msgs10.twist_pb2 import Twist
from prepare_assets import write_assets


def service_worker(connection):
    # The installed Python binding holds the GIL during blocking RequestRaw.
    # Do not share that process with Python subscription callbacks: they can
    # otherwise stall reception of the service response. This process has no
    # subscriptions and never publishes velocity commands.
    node = Node()
    kinds = {kind.DESCRIPTOR.full_name: kind for kind in (StringMsg, WorldControl)}
    while True:
        command = connection.recv()
        if command is None:
            return
        service, kind, wire, timeout = command
        message = kinds[kind]()
        message.ParseFromString(wire)
        ok, response = node.request(service, message, type(message), Boolean, timeout)
        connection.send((ok, response.SerializeToString()))


class ServiceClient:
    def __init__(self):
        context = multiprocessing.get_context("spawn")
        self.connection, child = context.Pipe()
        self.process = context.Process(target=service_worker, args=(child,))
        self.process.start()
        child.close()

    def request(self, service, message, request_type, response_type, timeout):
        self.connection.send((service, request_type.DESCRIPTOR.full_name,
                              message.SerializeToString(), timeout))
        if not self.connection.poll(timeout/1000+3):
            raise RuntimeError("service worker timed out")
        ok, wire = self.connection.recv()
        response = response_type()
        response.ParseFromString(wire)
        return ok, response

    def close(self):
        if self.process.is_alive():
            self.connection.send(None)
            self.process.join(timeout=3)
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=3)
        self.connection.close()


def request(node, service, data):
    ok, response = node.request(service, data, type(data), Boolean, 2000)
    if not ok:
        raise RuntimeError(f"service unavailable: {service}")
    return response.data


def packet(token, sequence):
    now = time.time_ns()
    return StringMsg(data=json.dumps({"schema": "phase5-drive/v1", "session": token,
        "sequence": sequence, "issued_wall": now, "expires_wall": now+80_000_000,
        "velocity": [.1, 0, 0]}))


def producer(token):
    node = Node()
    publisher = node.advertise("/phase5/drive/lease", StringMsg)
    end = time.monotonic()+5
    while not publisher.has_connections() and time.monotonic()<end:
        time.sleep(.02)
    if not publisher.has_connections():
        raise RuntimeError("native receiver was not discovered")
    # Advertise a live stream before the independent coordinator arms it.
    # Service response latency must not consume the 80 ms first-packet window.
    # No packet can authorize itself while the receiver is disarmed.
    for sequence in range(6000):
        began = time.monotonic_ns()
        publisher.publish(packet(token, sequence))
        if sequence == 0:
            print("STREAM_READY", flush=True)
        print(json.dumps({"sequence": sequence, "publish_begin_ns": began,
                          "publish_end_ns": time.monotonic_ns()}), flush=True)
        time.sleep(.02)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--producer")
    parser.add_argument("--output", type=Path, default=Path("/tmp/phase5-native-results"))
    args = parser.parse_args()
    if not os.environ.get("GZ_PARTITION", "").startswith("phase5-watchdog-") or os.getenv("GZ_IP") != "127.0.0.1":
        raise RuntimeError("refusing non-private Gazebo partition")
    if args.producer:
        return producer(args.producer)
    args.output.mkdir(exist_ok=False)
    assets = write_assets(args.output / "assets")
    source = Path(__file__).resolve()
    traces, checks = [], []
    lock = threading.Lock()
    node = Node()
    def receive(message):
        with lock:
            traces.append(json.loads(message.data))
    node.subscribe(StringMsg, "/phase5/drive/status", receive)
    replay = node.advertise("/phase5/drive/lease", StringMsg)
    bypass = node.advertise("/phase5/internal_drive", Twist)
    rpc = ServiceClient()

    def snapshot():
        with lock:
            return list(traces)

    def until(predicate, timeout=10):
        end = time.monotonic()+timeout
        while time.monotonic()<end:
            current = snapshot()
            if predicate(current):
                return current
            time.sleep(.01)
        raise RuntimeError("fixture condition timed out")

    process = None
    child = None
    producer_logs = []
    succeeded = False
    with (args.output / "gazebo.log").open("w+") as log:
        try:
            process = subprocess.Popen(["gz", "sim", "--force-version", "8", "-r", "-s", "-v", "2",
                                        "--record-path", str(args.output / "gz-record"),
                                        str(args.output / "assets/watchdog.world")], stdout=log, stderr=subprocess.STDOUT)
            until(lambda t: len(t)>50 and t[-1]["physical"] and t[-1]["physical"]["velocity_valid"] and t[-1]["physical"]["speed"]<.005, 30)
            time.sleep(.5)
            assert all(t["vx"]==0 and not t["armed"] for t in snapshot()), "startup moved"
            checks.append({"case": "startup_disarmed", "passed": True})
            # Exercise the physics-thread clamp against a retained/raw Twist
            # on DiffDrive's internal input, without granting a command lease.
            injected = Twist()
            injected.linear.x = .1
            anchor = snapshot()[-1]["physical"]
            inject_at = time.monotonic_ns()
            for _ in range(20):
                bypass.publish(injected)
                time.sleep(.02)
            after = snapshot()[-1]["physical"]
            assert math.hypot(after["x"]-anchor["x"], after["y"]-anchor["y"]) < .003, "raw drive bypassed clamp"
            assert all(t["physical"]["speed"]<.005 for t in snapshot() if t["steady_ns"]>=inject_at), "raw drive caused motion"
            checks.append({"case": "raw_diffdrive_input_cannot_bypass_disarmed_clamp", "passed": True})
            # Establish control-plane connections while wheels are inhibited.
            # gz-transport's first service connection can hold its shared mutex
            # for 100 ms; it must not consume a moving-command lease.
            services = subprocess.run(["gz", "service", "-l"], capture_output=True, text=True, timeout=10)
            (args.output / "services.txt").write_text(services.stdout+services.stderr)
            assert request(rpc, "/phase5/drive/stop", StringMsg(data="fixture_prepare"))
            assert request(rpc, "/world/phase5_watchdog_fixture/control", WorldControl(pause=False))
            for case in ("producer_killed", "explicit_stop", "paused_simulation"):
                token = str(uuid.uuid4())
                start = time.monotonic_ns()
                producer_log = (args.output / (case+"-producer.log")).open("w+")
                producer_logs.append(producer_log)
                child = subprocess.Popen([sys.executable, str(source), "--producer", token], stdout=producer_log, stderr=subprocess.STDOUT, text=True)
                count = snapshot()[-1]["received_packets"]
                until(lambda t: t[-1]["received_packets"]>=count+150, 8)
                assert request(rpc, "/phase5/drive/arm", StringMsg(data=token)), "explicit native arm rejected"
                moving_start = until(lambda t: t and t[-1]["steady_ns"]>start and t[-1]["armed"] and t[-1]["physical"]["speed"]>.07)[-1]
                time.sleep(.5)
                latest = snapshot()[-1]
                assert latest["armed"] and latest["physical"]["speed"]>.07, "premature stop before fault injection: "+latest["reason"]
                fault_at = time.monotonic_ns()
                assert fault_at-latest["steady_ns"]<50_000_000, "pre-fault telemetry stale"
                checks.append({"case": case+"_injection", "fault_steady_ns": fault_at,
                               "pre_fault_status": latest})
                if case == "producer_killed":
                    child.kill()
                    child.wait(timeout=3)
                elif case == "explicit_stop":
                    assert request(rpc, "/phase5/drive/stop", StringMsg(data="fixture_cancel"))
                else:
                    assert request(rpc, "/world/phase5_watchdog_fixture/control", WorldControl(pause=True))
                until(lambda t: t and t[-1]["steady_ns"]>=fault_at and not t[-1]["armed"] and t[-1]["applied_vx"]==0)
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=3)
                child = None
                if case == "paused_simulation":
                    time.sleep(.2)
                    assert request(rpc, "/world/phase5_watchdog_fixture/control", WorldControl(pause=False))
                until(lambda t: t and t[-1]["physical"]["speed"]<.005)
                time.sleep(.4)
                current = [t for t in snapshot() if t["steady_ns"]>=fault_at]
                zero = next(t for t in current if not t["armed"] and t["vx"]==0 and t["applied_vx"]==0 and t["stop_applied_steady_ns"]>=fault_at and t["stop_applied_trigger_ns"]==t["trigger_steady_ns"])
                assert zero["trigger_steady_ns"]>=fault_at, "stop preceded intended fault"
                expected_reason = {"producer_killed": "lease_expired", "explicit_stop": "fixture_cancel",
                                   "paused_simulation": "simulation_paused"}[case]
                assert zero["reason"]==expected_reason, "unexpected stop reason: "+zero["reason"]
                assert zero["stop_applied_steady_ns"]-zero["trigger_steady_ns"]<=100_000_000, "native expiry latency >100 ms"
                assert zero["steady_ns"]-fault_at<=200_000_000, "fault to zero excessive"
                physical = {t["physical"]["steady_ns"]: t["physical"] for t in current if t["physical"] and t["physical"]["steady_ns"]>=zero["stop_applied_steady_ns"]}
                points = [physical[k] for k in sorted(physical)]
                assert len(points)>2
                distance = sum(math.hypot(b["x"]-a["x"], b["y"]-a["y"]) for a,b in zip(points,points[1:]))
                # Include sample bracketing uncertainty separately, not as a
                # fabricated physical safety limit. The final native trace
                # records independent physics velocity/pose, not wheel odometry.
                previous_nonzero = [t for t in snapshot() if t["steady_ns"]<zero["steady_ns"] and t["applied_vx"]!=0 and t["physical"]]
                assert previous_nonzero, "no pre-stop physical reference"
                anchor = previous_nonzero[-1]["physical"]
                bracket_ms = (points[0]["steady_ns"]-anchor["steady_ns"])/1e6
                moving_wall = latest["physical"]["steady_ns"]-moving_start["physical"]["steady_ns"]
                moving_sim = latest["physical"]["sim_ns"]-moving_start["physical"]["sim_ns"]
                checks.append({"case": case, "passed": True, "fault_steady_ns": fault_at,
                    "moving_observed_wall_s": moving_wall/1e9,
                    "moving_real_time_factor": moving_sim/moving_wall,
                    "trigger_to_zero_ms": (zero["stop_applied_steady_ns"]-zero["trigger_steady_ns"])/1e6,
                    "zero_observed_in_status_ms": (zero["steady_ns"]-zero["trigger_steady_ns"])/1e6,
                    "fault_to_applied_zero_ms": (zero["stop_applied_steady_ns"]-fault_at)/1e6,
                    "fault_to_status_zero_ms": (zero["steady_ns"]-fault_at)/1e6,
                    "reason": zero["reason"], "post_zero_sampled_distance_m": distance,
                    "zero_sample_bracket_ms": bracket_ms,
                    "bracketed_stop_distance_m": math.hypot(points[0]["x"]-anchor["x"], points[0]["y"]-anchor["y"])+distance,
                    "final_physical_speed": points[-1]["speed"]})
                before = time.monotonic_ns()
                for sequence in range(10000, 10010):
                    replay.publish(packet(token, sequence))
                    time.sleep(.02)
                assert all(not t["armed"] and t["vx"]==0 for t in snapshot() if t["steady_ns"]>=before), "late packet resumed motion"
                assert not request(rpc, "/phase5/drive/arm", StringMsg(data=token)), "old session rearmed"
                checks.append({"case": case+"_late_success_and_session_reuse_rejected", "passed": True})
            info = subprocess.run(["gz", "topic", "-i", "-t", "/phase5/internal_drive"], capture_output=True, text=True, timeout=10)
            (args.output / "drive-endpoints.txt").write_text(info.stdout+info.stderr)
            succeeded = True
        finally:
            if child and child.poll() is None:
                child.kill(); child.wait(timeout=3)
            for producer_log in producer_logs:
                producer_log.close()
            try:
                request(rpc, "/phase5/drive/stop", StringMsg(data="fixture_cleanup"))
            except Exception:
                pass
            if process and process.poll() is None:
                process.send_signal(signal.SIGINT)
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
            rpc.close()
            result = {"event": "phase5_native_watchdog_fixture", "passed": succeeded,
                      "checks": checks, "assets": assets, "trace_count": len(traces)}
            (args.output / "summary.json").write_text(json.dumps(result, indent=2))
            with (args.output / "trace.jsonl").open("w") as handle:
                for entry in snapshot(): handle.write(json.dumps(entry)+"\n")
            print(json.dumps(result), flush=True)
            log.seek(0)
            print(log.read(), flush=True)


if __name__ == "__main__":
    main()
