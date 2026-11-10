"""Subprocess mTLS operator recovery check in a private watchdog fixture.

The operator runtime is the production candidate process and uses ROS/Gazebo
bindings. Adapter and Nav2 services are fixture endpoints; this is not a full
navigation deployment or category-recognition qualification.
"""
from http.client import HTTPSConnection
import json
import os
import queue
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time

from gz.msgs10.stringmsg_pb2 import StringMsg
from gz.transport13 import Node as GzNode

from phase7_operator_runtime import NativeClockFeed
from phase7_prompt_permit import PromptPermitVerifier
from prepare_assets import write_assets


def until(predicate, timeout_s=20):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(.01)
    raise TimeoutError("Phase 7 native operator fixture timed out")


def make_certificates(root):
    def openssl(*args):
        subprocess.run(["openssl", *args], cwd=root, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
            "-subj", "/CN=Phase7 Test CA", "-keyout", "ca.key", "-out", "ca.crt",
            "-addext", "basicConstraints=critical,CA:TRUE",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign")
    for name, usage, san in (("server", "serverAuth", "DNS:localhost"),
                             ("operator-17", "clientAuth", "URI:spiffe://operator-17")):
        openssl("req", "-newkey", "rsa:2048", "-nodes", "-subj", f"/CN={name}",
                "-keyout", f"{name}.key", "-out", f"{name}.csr")
        (root / "ext").write_text(
            "basicConstraints=critical,CA:FALSE\n"
            "keyUsage=critical,digitalSignature,keyEncipherment\n"
            f"extendedKeyUsage={usage}\nsubjectAltName={san}\n")
        openssl("x509", "-req", "-in", f"{name}.csr", "-CA", "ca.crt",
                "-CAkey", "ca.key", "-CAcreateserial", "-days", "1",
                "-extfile", "ext", "-out", f"{name}.crt")


def prepare_operator_credentials(root, managed_dir=None):
    """Load mounted Secret files, or create local ephemeral fixture credentials."""
    if managed_dir is None:
        make_certificates(root)
        shutil.copyfile(root / "ca.crt", root / "client-ca.crt")
        key = b"phase7-integration-signing-key-material-32-bytes"
        (root / "signing.key").write_bytes(key)
        operators = {"operator-17": "fixture-operator-credential"}
        (root / "operators.json").write_text(json.dumps(operators))
        return root, key, operators

    credential_root = Path(managed_dir)
    required = ("signing.key", "operators.json", "server.crt", "server.key",
                "client-ca.crt", "operator-17.crt", "operator-17.key")
    missing = [name for name in required if not (credential_root / name).is_file()]
    if missing:
        raise ValueError(f"mounted credential Secret is incomplete: {missing}")
    key = (credential_root / "signing.key").read_bytes()
    operators = json.loads((credential_root / "operators.json").read_text())
    if len(key) < 32 or not isinstance(operators, dict) or not operators.get("operator-17"):
        raise ValueError("mounted Phase 7 credentials fail the fixture contract")
    return credential_root, key, operators


class AdapterRosFixture:
    """ROS parameter/status endpoint that verifies real signed permits."""
    def __init__(self, node, *, key, events, native_clock):
        from rcl_interfaces.msg import SetParametersResult
        from std_msgs.msg import String

        self.node = node
        self.lock = threading.Lock()
        self.verifier = PromptPermitVerifier(key)
        self.events = events
        self.native_clock = native_clock
        self.state = {"prompt":"red mat", "policy_generation":1,
            "stream_epoch":"fixture-adapter-epoch-1", "prompt_transition_ready":True,
            "prompt_transition_enabled":True, "approved_prompts":["red mat", "blue crate"],
            "ready":True}
        self.ready_delay_s = 1.5
        self.ready_at = None
        self.status_pub = node.create_publisher(String, "/robot_1/semantic/status", 10)
        node.declare_parameter("prompt", "red mat")
        node.declare_parameter("phase7_transition_permit", "")
        node.add_on_set_parameters_callback(self.on_parameters)
        self.timer = node.create_timer(.025, self.publish_status)
        self.SetParametersResult = SetParametersResult
        self.String = String

    def on_parameters(self, parameters):
        values = {parameter.name:parameter.value for parameter in parameters}
        if set(values) != {"prompt", "phase7_transition_permit"}:
            return self.SetParametersResult(successful=False, reason="parameter set mismatch")
        try:
            if not self.native_clock.stationary(time.time_ns()):
                raise RuntimeError("fresh native stationary proof required before apply")
            with self.lock:
                generation = self.state["policy_generation"] + 1
                stream_epoch = self.state["stream_epoch"]
            permit = self.verifier.verify_and_consume(values["phase7_transition_permit"],
                prompt=values["prompt"], generation=generation,
                stream_epoch=stream_epoch)
            if permit["operator_id"] != "operator-17":
                raise PermissionError("unexpected operator identity")
        except Exception as error:
            return self.SetParametersResult(successful=False, reason=str(error))
        with self.lock:
            self.state.update(prompt=values["prompt"], policy_generation=generation,
                stream_epoch=f"fixture-adapter-epoch-{generation}",
                prompt_transition_ready=False, ready=False)
            self.ready_at = time.monotonic() + self.ready_delay_s
        self.events.append("atomic_prompt_apply")
        self.events.append("native_stationary_at_apply")
        return self.SetParametersResult(successful=True)

    def publish_status(self):
        with self.lock:
            if self.ready_at is not None and time.monotonic() >= self.ready_at:
                self.state.update(prompt_transition_ready=True, ready=True)
                self.ready_at = None
            status = dict(self.state)
        message = self.String()
        message.data = json.dumps(status, sort_keys=True)
        self.status_pub.publish(message)

    def snapshot(self):
        with self.lock:
            return dict(self.state)


def main():
    partition = os.getenv("GZ_PARTITION", "")
    if not partition.startswith("phase5-watchdog-phase7-") or os.getenv("GZ_IP") != "127.0.0.1":
        raise RuntimeError("private Phase 7 watchdog partition required")
    executable = shutil.which("gz")
    if not executable:
        raise RuntimeError("Gazebo executable is unavailable")

    root = Path(tempfile.mkdtemp(prefix="phase7-native-operator-"))
    assets_dir = root / "assets"
    write_assets(assets_dir)
    import rclpy
    from action_msgs.srv import CancelGoal
    from rcl_interfaces.srv import SetParametersAtomically
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.node import Node
    from std_msgs.msg import String
    from phase7_nav2_cancel_proxy import Nav2CancelProxy

    gz = GzNode()
    process = None
    operator_process = None
    ros_nodes = []
    executor = None
    executor_thread = None
    rclpy_started = False
    credential_root, key, operator_map = prepare_operator_credentials(
        root, os.environ.get("PHASE7_TEST_CREDENTIALS_DIR"))
    events = []
    native_clock = NativeClockFeed()
    native_samples = []
    cancelled_actions = []
    cancel_policy = {"reject_through_poses":True}

    def receive_native_status(message):
        native_samples.append(message.data)
        native_clock.observe_json(message.data)

    if not gz.subscribe(StringMsg, "/phase5/drive/status", receive_native_status):
        raise RuntimeError("native status subscription failed")

    try:
        rclpy.init()
        rclpy_started = True
        nav2_fixture = Node("phase7_nav2_action_fixture")
        adapter_node = Node("sam3_inference")
        ros_nodes = [nav2_fixture, adapter_node]
        for action_name in ("navigate_to_pose", "navigate_through_poses"):
            def cancel(_request, response, action=action_name):
                cancelled_actions.append(action)
                rejected = (action == "navigate_through_poses" and
                            cancel_policy["reject_through_poses"])
                response.return_code = (CancelGoal.Response.ERROR_REJECTED if rejected
                                        else CancelGoal.Response.ERROR_NONE)
                return response
            nav2_fixture.create_service(CancelGoal,
                f"/{action_name}/_action/cancel_goal", cancel)
        cancel_proxy = Nav2CancelProxy(
            nav2_fixture, ("/navigate_to_pose", "/navigate_through_poses"),
            "/phase7/cancel_navigation")
        nav2_service_probes = [
            nav2_fixture.create_client(
                CancelGoal, f"/{name}/_action/cancel_goal")
            for name in ("navigate_to_pose", "navigate_through_poses")]
        adapter_service_probe = nav2_fixture.create_client(
            SetParametersAtomically, "/sam3_inference/set_parameters_atomically")
        adapter = AdapterRosFixture(adapter_node, key=key, events=events,
                                    native_clock=native_clock)
        executor = MultiThreadedExecutor(num_threads=4)
        for ros_node_item in ros_nodes:
            executor.add_node(ros_node_item)
        executor_thread = threading.Thread(target=executor.spin, daemon=True)
        executor_thread.start()
        until(lambda:all(client.service_is_ready()
                         for client in nav2_service_probes) and
              adapter_service_probe.service_is_ready(), timeout_s=20)

        process = subprocess.Popen([executable, "sim", "--force-version", "8",
            "-r", "-s", "-v", "2", str(assets_dir / "watchdog.world")],
            stdout=(root / "gazebo.log").open("w"), stderr=subprocess.STDOUT)
        try:
            until(lambda: native_clock.stationary(time.time_ns()))
            until(lambda: adapter.snapshot().get("ready") is True and
                adapter.snapshot().get("prompt_transition_enabled") is True)
            def native_stop_ready():
                try:
                    result = subprocess.run(
                        [executable, "service", "-i", "-s", "/phase5/drive/stop"],
                        env=os.environ.copy(), capture_output=True, text=True,
                        timeout=3, check=False)
                except subprocess.TimeoutExpired:
                    return False
                return (result.returncode == 0 and
                        "gz.msgs.StringMsg, gz.msgs.Boolean" in result.stdout)
            until(native_stop_ready, timeout_s=30)
        except TimeoutError as error:
            log = (root / "gazebo.log").read_text(errors="replace")[-4000:]
            raise TimeoutError(
                f"ROS/Gazebo fixture readiness timed out; "
                f"adapter_status={adapter.snapshot()}; "
                f"fault={native_clock.fault}; epoch={native_clock.epoch}; "
                f"native_stop_service_ready={native_stop_ready()}; "
                f"gazebo_log_tail={log}") from error

        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            operator_port = reservation.getsockname()[1]
        operator_env = os.environ.copy()
        operator_env.update({
            "PHASE7_RUNTIME_ENABLE":"1",
            "PHASE7_SIGNING_KEY_FILE":str(credential_root / "signing.key"),
            "PHASE7_OPERATOR_MAP_FILE":str(credential_root / "operators.json"),
            "PHASE7_SERVER_CERT_FILE":str(credential_root / "server.crt"),
            "PHASE7_SERVER_KEY_FILE":str(credential_root / "server.key"),
            "PHASE7_CLIENT_CA_FILE":str(credential_root / "client-ca.crt"),
            "PHASE7_ADAPTER_NODE":"/sam3_inference",
            "PHASE7_ADAPTER_STATUS_TOPIC":"/robot_1/semantic/status",
            "PHASE7_NAV_ACTIONS":"/navigate_to_pose,/navigate_through_poses",
            "PHASE7_NAV_CANCEL_PROXY":"/phase7/cancel_navigation",
            "PHASE7_OPERATOR_HOST":"127.0.0.1",
            "PHASE7_OPERATOR_PORT":str(operator_port),
        })
        operator_script = Path(__file__).with_name("phase7_operator_runtime.py")
        operator_log = root / "operator-runtime.log"

        def start_operator_runtime():
            operator_log.write_text("")
            with operator_log.open("ab") as log:
                return subprocess.Popen([sys.executable, str(operator_script)],
                    env=operator_env, stdout=log, stderr=subprocess.STDOUT)

        def wait_operator_ready(child):
            def ready():
                if child.poll() is not None:
                    raise RuntimeError(
                        f"operator runtime exited {child.returncode}: "
                        f"{operator_log.read_text(errors='replace')[-5000:]}")
                return "Phase 7 mTLS operator API is ready" in \
                    operator_log.read_text(errors="replace")
            try:
                until(ready, timeout_s=30)
            except TimeoutError as error:
                raise TimeoutError(
                    f"operator API did not become ready; child_status={child.poll()}; "
                    f"runtime_log={operator_log.read_text(errors='replace')[-5000:]}") from error

        operator_process = start_operator_runtime()
        wait_operator_ready(operator_process)

        tls = ssl.create_default_context(cafile=str(credential_root / "client-ca.crt"))
        tls.load_cert_chain(str(credential_root / "operator-17.crt"),
                            str(credential_root / "operator-17.key"))

        def operator_request(prompt):
            connection = HTTPSConnection(
                "localhost", operator_port, context=tls, timeout=5)
            try:
                connection.request("POST", "/v1/prompt-transitions",
                    body=json.dumps({"prompt":prompt}),
                    headers={"Content-Type":"application/json"})
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            finally:
                connection.close()

        rejected_status, rejected_result = operator_request("blue crate")
        if rejected_status != 409:
            raise AssertionError(
                f"rejected Nav2 cancel was not fail-closed: "
                f"{rejected_status} {rejected_result}")
        if (adapter.snapshot()["policy_generation"] != 1 or events or
                len(cancelled_actions) != 2 or
                set(cancelled_actions) != {
                    "navigate_to_pose", "navigate_through_poses"}):
            raise AssertionError(
                f"rejected Nav2 cancel did not fail closed: "
                f"response={rejected_status} {rejected_result}; "
                f"adapter={adapter.snapshot()}; events={events}; "
                f"cancelled_actions={cancelled_actions}; "
                f"runtime_log={operator_log.read_text(errors='replace')[-5000:]}")
        cancel_policy["reject_through_poses"] = False

        request_results = queue.Queue()
        def interrupted_transition_request():
            try:
                request_results.put(("response", operator_request("blue crate")))
            except Exception as error:
                request_results.put(("error", f"{type(error).__name__}: {error}"))
        request_thread = threading.Thread(
            target=interrupted_transition_request, daemon=True)
        request_thread.start()
        try:
            until(lambda:adapter.snapshot()["policy_generation"] == 2 and
                adapter.snapshot()["ready"] is False, timeout_s=5)
        except TimeoutError as error:
            request_thread.join(timeout=1)
            result = (request_results.get_nowait()
                      if not request_results.empty() else "request still running")
            raise TimeoutError(
                f"transition did not reach adapter apply: result={result}; "
                f"adapter={adapter.snapshot()}; cancelled={cancelled_actions}; "
                f"native_fault={native_clock.fault}; "
                f"native_status={native_clock.status}; "
                f"runtime_log={operator_log.read_text(errors='replace')[-5000:]}") from error
        # Stop the actual runtime process while it is waiting for the adapter
        # to publish a fresh generation. No ROS or Gazebo fixture process is
        # restarted, so recovery must rediscover committed adapter state.
        operator_process.terminate()
        try:
            operator_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            operator_process.kill()
            operator_process.wait(timeout=3)
        operator_process = None
        request_thread.join(timeout=5)
        if request_thread.is_alive():
            raise TimeoutError("in-flight operator request survived runtime termination")
        interrupted_kind, interrupted_result = request_results.get_nowait()
        if interrupted_kind == "response" and interrupted_result[0] == 200:
            raise AssertionError("killed runtime returned success for the interrupted transition")
        if adapter.snapshot()["policy_generation"] != 2:
            raise AssertionError("accepted adapter generation was lost during runtime restart")
        until(lambda:adapter.snapshot()["ready"] is True, timeout_s=5)

        # A fresh operator process and fresh ROS bindings must attach to the
        # adapter's committed prompt. Repeating that prompt is an idempotent
        # no-op: it cannot issue another stop, permit, or parameter update.
        operator_process = start_operator_runtime()
        wait_operator_ready(operator_process)
        retry_status, retry_result = operator_request("blue crate")
        retry = retry_result.get("result", {})
        if (retry_status != 200 or retry.get("generation") != 2 or
                retry.get("changed") is not False):
            raise AssertionError(
                f"operator restart did not recover committed transition: "
                f"{retry_status} {retry_result}; "
                f"operator_log={operator_log.read_text(errors='replace')[-5000:]}")
        if events != ["atomic_prompt_apply", "native_stationary_at_apply"]:
            raise AssertionError(f"unexpected transition order or replay: {events}")
        # Run the phase gate's 20 alternating changes through the deployed
        # runtime process and mTLS endpoint, not only through adapter tests.
        adapter.ready_delay_s = .05
        cycle_results = []
        for index in range(20):
            prompt = "red mat" if index % 2 == 0 else "blue crate"
            expected_generation = index + 3
            cycle_status, cycle_body = operator_request(prompt)
            cycle = cycle_body.get("result", {})
            if (cycle_status != 200 or cycle.get("changed") is not True or
                    cycle.get("prompt") != prompt or
                    cycle.get("generation") != expected_generation):
                raise AssertionError(
                    f"mTLS alternating transition {index + 1}/20 failed: "
                    f"{cycle_status} {cycle_body}; adapter={adapter.snapshot()}; "
                    f"runtime_log={operator_log.read_text(errors='replace')[-5000:]}")
            until(lambda:adapter.snapshot().get("ready") is True and
                adapter.snapshot().get("policy_generation") == expected_generation,
                timeout_s=2)
            if (adapter.snapshot().get("prompt") != prompt or
                    adapter.snapshot().get("stream_epoch") !=
                    f"fixture-adapter-epoch-{expected_generation}" or
                    not native_clock.stationary(time.time_ns())):
                raise AssertionError(
                    f"mTLS alternating transition {index + 1}/20 did not "
                    f"publish fresh stationary state: {adapter.snapshot()}")
            cycle_results.append({"generation":expected_generation,
                                  "prompt":prompt,"changed":cycle["changed"]})
        if (events.count("atomic_prompt_apply") != 21 or
                events.count("native_stationary_at_apply") != 21):
            raise AssertionError(f"20-cycle apply evidence incomplete: {events}")
        if (set(cancelled_actions) != {"navigate_to_pose", "navigate_through_poses"} or
                len(cancelled_actions) != 44):
            raise AssertionError(
                f"Nav2 cancellation ACK/rejection matrix incomplete: {cancelled_actions}")
        if not native_clock.stationary(time.time_ns()):
            raise AssertionError("native watchdog did not remain stationary")
        if (adapter.snapshot()["prompt"] != "blue crate" or
                adapter.snapshot()["ready"] is not True):
            raise AssertionError("fresh matching adapter generation was not observed")
        status = native_clock.status or {}
        if (status.get("armed") is not False or status.get("applied_vx") != 0 or
                status.get("applied_wz") != 0):
            raise AssertionError(f"robot was not left disarmed and stopped: {status}")
        print(json.dumps({"event":"phase7_native_operator_integration",
            "passed":True,"native_epoch":native_clock.epoch,"generation":22,
            "prompt":adapter.snapshot()["prompt"],"alternating_cycles":cycle_results,
            "apply_count":events.count("atomic_prompt_apply"),
            "native_stationary_at_apply_count":events.count("native_stationary_at_apply"),
            "cancelled_actions":cancelled_actions,
            "rejected_cancel_fail_closed":True,
            "restart_during_transition_recovered":True,
            "interrupted_request":interrupted_kind,
            "retry_changed":retry.get("changed"),
            "transport":"Gazebo native + ROS services/topics + mTLS",
            "motion_resumed":False}, sort_keys=True))
    finally:
        if operator_process is not None:
            operator_process.terminate()
            try:
                operator_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                operator_process.kill()
                operator_process.wait(timeout=3)
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        if executor is not None:
            executor.shutdown(timeout_sec=2.0)
        if executor_thread is not None:
            executor_thread.join(timeout=2.0)
        for ros_node_item in ros_nodes:
            ros_node_item.destroy_node()
        if rclpy_started:
            rclpy.shutdown()
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
