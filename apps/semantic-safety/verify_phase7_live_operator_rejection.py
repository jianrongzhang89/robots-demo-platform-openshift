"""Verify a live mTLS operator endpoint rejects an unapproved prompt safely."""
from http.client import HTTPSConnection
import ipaddress
import json
import os
import socket
import ssl
import threading
import time


def expected_unapproved_response(status, body):
    return status == 400 and isinstance(body, dict) and body.get("error") == (
        "prompt is not approved")


def expected_unchanged_response(status, body):
    result = body.get("result") if isinstance(body, dict) else None
    return (status == 200 and isinstance(result, dict) and
            result.get("prompt") == "red mat" and
            result.get("generation") == 1 and
            result.get("changed") is False and
            isinstance(result.get("stream_epoch"), str) and
            bool(result.get("stream_epoch")))


def require_loopback_only_listener(pod_ip, *, port=9443, timeout_s=180.0):
    """Prove the mTLS endpoint is reachable on loopback, not the pod NIC."""
    address = str(ipaddress.ip_address(pod_ip))
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            connection = socket.create_connection(("127.0.0.1", port), timeout=1.0)
            connection.close()
            break
        except OSError as error:
            if time.monotonic() >= deadline:
                raise RuntimeError("operator API is not reachable on loopback") from error
            time.sleep(0.1)
    try:
        connection = socket.create_connection((address, port), timeout=0.5)
    except OSError:
        return
    else:
        connection.close()
        raise RuntimeError("operator API is reachable through the pod IP")


def request_prompt(context, token, prompt):
    connection = HTTPSConnection("localhost", 9443, context=context, timeout=5.0)
    try:
        connection.request(
            "POST", "/v1/prompt-transitions",
            body=json.dumps({"prompt": prompt}),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + token})
        response = connection.getresponse()
        body = json.loads(response.read())
        return response.status, body
    finally:
        connection.close()


def request_unapproved_prompt(credentials, timeout_s=30.0):
    operators = json.loads((credentials / "operators.json").read_text())
    token = operators.get("operator-17")
    if not isinstance(token, str) or not token:
        raise RuntimeError("validation operator credential is unavailable")
    context = ssl.create_default_context(cafile=str(credentials / "client-ca.crt"))
    context.load_cert_chain(
        certfile=str(credentials / "operator-17.crt"),
        keyfile=str(credentials / "operator-17.key"))
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", 9443), timeout=1.0):
                break
        except OSError:
            time.sleep(0.1)
    else:
        raise TimeoutError("live Phase 7 operator endpoint did not start")

    unchanged = request_prompt(context, token, "red mat")
    rejected = request_prompt(context, token, "blue crate")
    return unchanged, rejected


def main():
    credentials = os.environ.get("PHASE7_LIVE_CREDENTIALS_DIR")
    if not credentials:
        raise RuntimeError("mounted validation credentials are required")
    pod_ip = os.environ.get("POD_IP")
    if not pod_ip:
        raise RuntimeError("downward-API pod IP is required for listener-scope check")
    from pathlib import Path
    credentials = Path(credentials)

    require_loopback_only_listener(pod_ip)
    unchanged, rejected = request_unapproved_prompt(credentials, timeout_s=180.0)
    unchanged_status, unchanged_response = unchanged
    if not expected_unchanged_response(unchanged_status, unchanged_response):
        raise RuntimeError("approved current prompt did not return changed=false")
    status_code, response = rejected
    if not expected_unapproved_response(status_code, response):
        raise RuntimeError("unapproved prompt did not receive the expected 400 rejection")

    import rclpy
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.node import Node
    from std_msgs.msg import String
    from gz.msgs10.stringmsg_pb2 import StringMsg
    from gz.transport13 import Node as GzNode

    lock = threading.Lock()
    adapter_rows = []
    native_rows = []

    def adapter_callback(message):
        try:
            row = json.loads(message.data)
        except (TypeError, ValueError):
            return
        if isinstance(row, dict):
            with lock:
                adapter_rows.append(row)
                del adapter_rows[:-20]

    def native_callback(message):
        try:
            row = json.loads(message.data)
        except (TypeError, ValueError):
            return
        if isinstance(row, dict):
            with lock:
                native_rows.append(row)
                del native_rows[:-100]

    rclpy.init()
    node = Node("phase7_live_operator_rejection_verifier")
    node.create_subscription(String, "/robot_1/semantic/status", adapter_callback, 10)
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()
    gz_node = GzNode()
    if not gz_node.subscribe(StringMsg, "/phase5/drive/status", native_callback):
        raise RuntimeError("could not subscribe to private native watchdog status")

    try:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            with lock:
                adapter = adapter_rows[-1] if adapter_rows else None
                native = native_rows[-1] if native_rows else None
            if (isinstance(adapter, dict) and isinstance(native, dict) and
                    adapter.get("prompt") == "red mat" and
                    adapter.get("policy_generation") == 1 and
                    adapter.get("ready") is True and
                    adapter.get("prompt_transition_enabled") is True and
                    adapter.get("last_valid_result_age_ms", 1e9) <= 500.0 and
                    native.get("armed") is False and
                    float(native.get("applied_vx", 1e9)) == 0.0 and
                    float(native.get("applied_wz", 1e9)) == 0.0 and
                    int(native.get("stop_applied_steady_ns", -1)) == 0):
                print(json.dumps({
                    "event": "phase7_live_unapproved_prompt_rejection",
                    "passed": True,
                    "listener_scope": "loopback_only",
                    "approved_idempotent_request": {
                        "http_status": unchanged_status,
                        "changed": unchanged_response["result"]["changed"],
                        "prompt": unchanged_response["result"]["prompt"],
                        "generation": unchanged_response["result"]["generation"],
                    },
                    "http_status": status_code,
                    "rejection": response["error"],
                    "prompt": adapter["prompt"],
                    "policy_generation": adapter["policy_generation"],
                    "ready": adapter["ready"],
                    "prompt_transition_enabled": adapter[
                        "prompt_transition_enabled"],
                    "native_armed": native["armed"],
                    "applied_vx": native["applied_vx"],
                    "applied_wz": native["applied_wz"],
                    "stop_applied_steady_ns": native["stop_applied_steady_ns"],
                }, sort_keys=True), flush=True)
                return
            time.sleep(0.05)
        raise RuntimeError(
            "rejected request changed adapter state or native watchdog did not remain idle")
    finally:
        gz_node.unsubscribe("/phase5/drive/status")
        executor.shutdown(timeout_sec=2.0)
        spin_thread.join(timeout=2.0)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        del gz_node


if __name__ == "__main__":
    main()
