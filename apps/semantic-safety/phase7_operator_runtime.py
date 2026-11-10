"""Runtime bindings for the authenticated Phase 7 prompt operator.

Run this only beside a private Phase 7 simulator that exposes the Phase 5
native watchdog in the same Gazebo partition. The watchdog remains the final
stop authority; this process never arms or sends motion leases.
"""
import json
import multiprocessing
import os
import copy
import math
from pathlib import Path
import threading
import time

from native_clock import NativeClock
from phase7_operator_api import create_operator_server
from phase7_operator_control import PromptTransitionControl


def native_stop_service_worker(connection):
    """Keep blocking Gazebo RequestRaw calls away from status callbacks/GIL."""
    from gz.msgs10.boolean_pb2 import Boolean
    from gz.msgs10.stringmsg_pb2 import StringMsg
    from gz.transport13 import Node as GzNode

    node = GzNode()
    while True:
        request = connection.recv()
        if request is None:
            return
        reason, timeout_ms = request
        ok, response = node.request(
            "/phase5/drive/stop", StringMsg(data=reason), StringMsg, Boolean,
            timeout_ms)
        connection.send((bool(ok), bool(response is not None and response.data)))


class NativeStopServiceClient:
    """Isolate Gazebo's blocking service binding in a subscription-free process."""
    def __init__(self):
        context = multiprocessing.get_context("spawn")
        self.connection, child = context.Pipe()
        self.process = context.Process(
            target=native_stop_service_worker, args=(child,))
        self.process.start()
        child.close()
        self.lock = threading.Lock()

    def request(self, reason, timeout_ms):
        with self.lock:
            if not self.process.is_alive():
                return False, False
            self.connection.send((reason, timeout_ms))
            if not self.connection.poll(timeout_ms / 1000 + 3):
                return False, False
            return self.connection.recv()

    def close(self):
        if self.process.is_alive():
            self.connection.send(None)
            self.process.join(timeout=3)
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=3)
        self.connection.close()


class NativeClockFeed:
    """Thread-safe view of the capture-time native status stream."""
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = None

    def observe_json(self, text, now_wall_ns=None):
        now = time.time_ns() if now_wall_ns is None else now_wall_ns
        try:
            status = json.loads(text)
            epoch = status.get("clock_epoch")
            if not isinstance(epoch, str) or not epoch:
                return False
            with self.lock:
                physical = status.get("physical")
                if self.clock is not None and isinstance(physical, dict):
                    wall = physical.get("wall_ns")
                    sequence = physical.get("sequence")
                    steady = physical.get("steady_ns")
                    previous = self.clock.last or {}
                    if (type(wall) is int and type(sequence) is int and
                            type(steady) is int and not -2_000_000 <= now-wall < 100_000_000 and
                            sequence > previous.get("sequence", -1) and
                            steady > previous.get("steady_ns", -1)):
                        # A delayed but otherwise monotonic capture must not
                        # refresh readiness or permanently poison the feed.
                        # NativeClock resets the quiet interval on the next
                        # fresh sample when it detects the capture gap.
                        return False
                if self.clock is None:
                    if (not isinstance(physical, dict) or
                            any(type(physical.get(name)) is not int
                                for name in ("wall_ns", "steady_ns", "sim_ns", "sequence")) or
                            physical.get("velocity_valid") is not True or
                            any(type(physical.get(name)) not in (int, float) or
                                not math.isfinite(physical[name])
                                for name in ("x", "y", "yaw", "speed", "angular_speed"))):
                        # The watchdog publishes before its first physics
                        # capture. Wait for one complete physical sample
                        # before binding the epoch; later invalid samples on
                        # an established clock still fault closed.
                        return False
                    self.clock = NativeClock(epoch)
                return self.clock.observe(status, now)
        except (TypeError, ValueError, json.JSONDecodeError):
            return False

    def stationary(self, now_wall_ns):
        with self.lock:
            return bool(self.clock and self.clock.stationary(now_wall_ns))

    def snapshot(self):
        """Freeze one internally consistent native proof for permit signing."""
        with self.lock:
            if self.clock is None:
                raise RuntimeError("native status is unavailable")
            return copy.deepcopy(self.clock)

    @property
    def status(self):
        with self.lock:
            return self.clock.status if self.clock else None

    @property
    def epoch(self):
        with self.lock:
            return self.clock.epoch if self.clock else None

    @property
    def quiet_since(self):
        with self.lock:
            return self.clock.quiet_since if self.clock else None

    @property
    def fault(self):
        with self.lock:
            return self.clock.fault if self.clock else "native_status_unavailable"


class Phase7RosBindings:
    """ROS/Gazebo callbacks consumed by PromptTransitionControl."""
    def __init__(self, *, node, gz_node, native_stop_client, action_names, adapter_node,
                 adapter_status_topic, cancel_proxy_service,
                 stop_timeout_s=2.0, ros_timeout_s=3.0):
        from rcl_interfaces.msg import Parameter, ParameterType, ParameterValue
        from rcl_interfaces.srv import SetParametersAtomically
        from std_msgs.msg import String
        from std_srvs.srv import Trigger
        from gz.msgs10.boolean_pb2 import Boolean
        from gz.msgs10.stringmsg_pb2 import StringMsg

        if not action_names or any(not isinstance(name, str) or not name.startswith("/")
                                   for name in action_names):
            raise ValueError("explicit absolute Nav2 action list required")
        self.node, self.gz_node = node, gz_node
        self.native_stop_client = native_stop_client
        self.clock = NativeClockFeed()
        self.status_lock = threading.Lock()
        self.adapter_status_value = None
        self.stop_timeout_s = float(stop_timeout_s)
        self.ros_timeout_s = float(ros_timeout_s)
        self.last_stop_diagnostics = {}
        self.string_message_type = StringMsg
        self.boolean_message_type = Boolean
        self.native_status_subscribed = gz_node.subscribe(
            StringMsg, "/phase5/drive/status", self.clock_status)
        if not self.native_status_subscribed:
            raise RuntimeError("native watchdog status subscription failed")
        self.adapter_subscription = node.create_subscription(
            String, adapter_status_topic, self.on_adapter_status, 10)
        if not isinstance(cancel_proxy_service, str) or not cancel_proxy_service.startswith("/"):
            raise ValueError("absolute Nav2 cancellation proxy service required")
        self.action_names = tuple(action_names)
        self.cancel_proxy_client = node.create_client(Trigger, cancel_proxy_service)
        self.parameter_client = node.create_client(
            SetParametersAtomically, adapter_node.rstrip("/") + "/set_parameters_atomically")
        self.Parameter = Parameter
        self.ParameterType = ParameterType
        self.ParameterValue = ParameterValue
        self.SetParametersAtomically = SetParametersAtomically

    def clock_status(self, message):
        self.clock.observe_json(message.data)

    def on_adapter_status(self, message):
        try:
            value = json.loads(message.data)
            if not isinstance(value, dict):
                return
        except (TypeError, ValueError, json.JSONDecodeError):
            return
        with self.status_lock:
            self.adapter_status_value = value

    def adapter_status(self):
        with self.status_lock:
            return dict(self.adapter_status_value or {})

    def services_ready(self):
        """Require every stop/apply endpoint before advertising the API."""
        return (self.cancel_proxy_client.service_is_ready() and
                self.parameter_client.service_is_ready())

    def _await_ros_future(self, future, timeout_s):
        event = threading.Event()
        future.add_done_callback(lambda _future: event.set())
        if not event.wait(timeout_s):
            return None
        try:
            return future.result()
        except Exception:
            return None

    def stop_navigation(self):
        """Stop the independent watchdog and confirm every Nav2 cancel ACK."""
        self.last_stop_diagnostics = {}
        ok, confirmed = self.native_stop_client.request(
            "phase7_prompt_transition", int(self.stop_timeout_s * 1000))
        self.last_stop_diagnostics["native_stop"] = {
            "transport_ok":bool(ok),
            "confirmed":bool(confirmed),
        }
        if not ok or not confirmed:
            self.node.get_logger().error(
                f"Phase 7 native stop was not confirmed: "
                f"{self.last_stop_diagnostics['native_stop']}")
            return False
        ready = bool(self.cancel_proxy_client.service_is_ready())
        self.last_stop_diagnostics["cancel_proxy_ready"] = ready
        if not ready:
            self.node.get_logger().error("Phase 7 Nav2 cancellation proxy unavailable")
            return False
        from std_srvs.srv import Trigger
        response = self._await_ros_future(
            self.cancel_proxy_client.call_async(Trigger.Request()), self.ros_timeout_s)
        self.last_stop_diagnostics["cancel_proxy_ack"] = (
            None if response is None else {"success": response.success,
                                           "message": response.message})
        if response is None or not response.success:
            self.node.get_logger().error(
                f"Phase 7 Nav2 cancellation proxy was not acknowledged: "
                f"{self.last_stop_diagnostics['cancel_proxy_ack']}")
            return False
        return True

    def apply_prompt(self, prompt, permit):
        if not self.parameter_client.service_is_ready():
            return False
        def string_parameter(name, value):
            return self.Parameter(name=name, value=self.ParameterValue(
                type=self.ParameterType.PARAMETER_STRING, string_value=value))
        request = self.SetParametersAtomically.Request()
        request.parameters = [
            string_parameter("prompt", prompt),
            string_parameter("phase7_transition_permit", permit),
        ]
        future = self.parameter_client.call_async(request)
        response = self._await_ros_future(future, self.ros_timeout_s)
        return bool(response and response.result.successful)

    def pump(self):
        # A dedicated ROS executor thread owns callback pumping. The operator
        # HTTP worker only waits on futures completed by that executor.
        return None


def runtime_config(env=None):
    env = os.environ if env is None else env
    if env.get("PHASE7_RUNTIME_ENABLE") != "1":
        raise RuntimeError("PHASE7_RUNTIME_ENABLE=1 is required")
    if not env.get("GZ_PARTITION", "").startswith("phase5-watchdog-phase7-"):
        raise RuntimeError("private phase5-watchdog-phase7-* Gazebo partition required")
    if env.get("GZ_IP") != "127.0.0.1":
        raise RuntimeError("loopback-only Gazebo transport required")
    required = (
        "PHASE7_SIGNING_KEY_FILE", "PHASE7_OPERATOR_MAP_FILE",
        "PHASE7_SERVER_CERT_FILE", "PHASE7_SERVER_KEY_FILE",
        "PHASE7_CLIENT_CA_FILE", "PHASE7_ADAPTER_NODE",
        "PHASE7_ADAPTER_STATUS_TOPIC", "PHASE7_NAV_ACTIONS",
        "PHASE7_NAV_CANCEL_PROXY",
    )
    missing = [name for name in required if not env.get(name)]
    if missing:
        raise RuntimeError("missing Phase 7 runtime settings: " + ", ".join(missing))
    return {
        # External exposure requires an explicit bind choice and a separately
        # reviewed NetworkPolicy. Keep an unset deployment loopback-only.
        "host": env.get("PHASE7_OPERATOR_HOST", "127.0.0.1"),
        "port": int(env.get("PHASE7_OPERATOR_PORT", "9443")),
        "signing_key": Path(env["PHASE7_SIGNING_KEY_FILE"]).read_bytes(),
        "operators": json.loads(Path(env["PHASE7_OPERATOR_MAP_FILE"]).read_text()),
        "server_cert": env["PHASE7_SERVER_CERT_FILE"],
        "server_key": env["PHASE7_SERVER_KEY_FILE"],
        "client_ca": env["PHASE7_CLIENT_CA_FILE"],
        "adapter_node": env["PHASE7_ADAPTER_NODE"],
        "adapter_status_topic": env["PHASE7_ADAPTER_STATUS_TOPIC"],
        "nav_actions": tuple(filter(None, env["PHASE7_NAV_ACTIONS"].split(","))),
        "nav_cancel_proxy": env["PHASE7_NAV_CANCEL_PROXY"],
        "operator_id": env.get("PHASE7_OPERATOR_ID", "phase7-operator"),
        "timeout_s": float(env.get("PHASE7_TRANSITION_TIMEOUT_S", "10")),
    }


def serve_until_stopped(server, stop_event, poll_s=0.1):
    """Serve on a worker thread so SIGTERM can stop HTTP and ROS cleanly."""
    serve_thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.25}, daemon=True)
    serve_thread.start()
    try:
        while serve_thread.is_alive() and not stop_event.wait(poll_s):
            pass
    finally:
        if serve_thread.is_alive():
            server.shutdown()
        serve_thread.join(timeout=5.0)
        server.server_close()


def startup_gate_diagnostics(bindings, adapter_status):
    """Describe each startup prerequisite without exposing credential data."""
    approved = adapter_status.get("approved_prompts")
    return {
        "adapter_status_received": bool(adapter_status),
        "adapter_ready": adapter_status.get("ready") is True,
        "prompt_transition_enabled": (
            adapter_status.get("prompt_transition_enabled") is True),
        "approved_prompt_count": len(approved) if isinstance(approved, list) else 0,
        "native_status_ready": bool(bindings.clock.epoch),
        "native_status_fault": bindings.clock.fault,
        "nav_cancel_proxy_ready": (
            bindings.cancel_proxy_client.service_is_ready()),
        "adapter_parameter_service_ready": (
            bindings.parameter_client.service_is_ready()),
    }


def main():
    import rclpy
    import signal
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.node import Node
    from gz.transport13 import Node as GzNode

    config = runtime_config()
    rclpy.init()
    node = Node("phase7_operator_runtime")
    native_stop_client = NativeStopServiceClient()
    bindings = Phase7RosBindings(
        node=node, gz_node=GzNode(), native_stop_client=native_stop_client,
        action_names=config["nav_actions"],
        adapter_node=config["adapter_node"],
        adapter_status_topic=config["adapter_status_topic"],
        cancel_proxy_service=config["nav_cancel_proxy"])
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    executor_thread = threading.Thread(target=executor.spin, daemon=True)
    executor_thread.start()

    try:
        deadline = time.monotonic() + float(
            os.environ.get("PHASE7_STARTUP_TIMEOUT_S", "180"))
        approved = ()
        gate_status = {}
        while time.monotonic() < deadline:
            status = bindings.adapter_status()
            gate_status = startup_gate_diagnostics(bindings, status)
            if (status.get("ready") is True and status.get("prompt_transition_enabled") is True
                    and bindings.clock.epoch and bindings.services_ready()):
                approved = tuple(status.get("approved_prompts") or ())
                if approved:
                    break
            time.sleep(.05)
        if not approved:
            raise RuntimeError(
                "adapter, native status, Nav2 cancel, and adapter parameter "
                "services must be ready before operator API starts; "
                "startup_gate=" + json.dumps(gate_status, sort_keys=True))
        controller = PromptTransitionControl(
            clock=bindings.clock, approved_prompts=approved,
            operator_credential=config["operators"],
            operator_id=config["operator_id"], signing_key=config["signing_key"],
            adapter_status=bindings.adapter_status,
            stop_navigation=bindings.stop_navigation,
            apply_prompt=bindings.apply_prompt, pump=bindings.pump)
        server = create_operator_server(
            controller=controller, host=config["host"], port=config["port"],
            server_cert=config["server_cert"], server_key=config["server_key"],
            client_ca=config["client_ca"], authorized_operators=config["operators"])
        node.get_logger().info("Phase 7 mTLS operator API is ready")
        stop_event = threading.Event()
        previous_handlers = {}
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[sig] = signal.signal(
                sig, lambda _signum, _frame: stop_event.set())
        serve_until_stopped(server, stop_event)
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
    finally:
        executor.shutdown(timeout_sec=2.0)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        native_stop_client.close()


if __name__ == "__main__":
    main()
