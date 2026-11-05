"""Bounded, mutually authenticated HTTPS wrapper around the shared SAM3 runner.

No ROS imports, downloading, tracking state, or command credentials. Health is
served separately; all model data (including metadata) requires a client cert.
"""
from collections import Counter
import copy
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import math
import os
from pathlib import Path
import socket
from socketserver import ThreadingMixIn
import ssl
import threading
import time

from PIL import Image

from artifact import verify_artifact
from inference_contract import (MAX_WIRE_BYTES, SCHEMA, dumps, loads,
                                response_base, validate_request)
from sam3_backend import LocalSam3Backend, Sam3ModelRunner


class ModelService:
    def __init__(self, clients, hang_seconds=10):
        self.clients = clients
        self.hang_seconds = hang_seconds
        self.backend = None
        self.identity = None
        self.failure = False
        self.busy_since = None
        self.worker = threading.Lock()
        self.metrics_lock = threading.Lock()
        self.counts = Counter()
        self.duration = 0.0
        # Fixed buckets and names: bounded memory, no robot/request-ID labels.
        self.histogram_bounds = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10)
        self.histograms = {name: {"buckets": [0] * len(self.histogram_bounds),
                                  "count": 0, "sum": 0.0}
                           for name in ("admission", "queue", "backend", "worker")}

    def observe(self, name, seconds):
        with self.metrics_lock:
            histogram = self.histograms[name]
            histogram["count"] += 1
            histogram["sum"] += seconds
            for index, bound in enumerate(self.histogram_bounds):
                if seconds <= bound:
                    histogram["buckets"][index] += 1

    def metrics(self):
        with self.metrics_lock:
            lines = [f'semantic_requests_total{{status="{key}"}} {value}'
                     for key, value in sorted(self.counts.items())]
            # Retain the original successful-response work sum for compatibility.
            lines += [f"semantic_inference_duration_seconds_sum {self.duration}",
                      f"semantic_worker_ready {int(self.ready())}",
                      f"semantic_worker_busy {int(self.busy_since is not None)}",
                      "semantic_queue_capacity 0"]
            for name, histogram in self.histograms.items():
                metric = f"semantic_{name}_duration_seconds"
                lines.append(f"# TYPE {metric} histogram")
                lines.extend(f'{metric}_bucket{{le="{bound}"}} {count}'
                             for bound, count in zip(self.histogram_bounds, histogram["buckets"]))
                lines += [f'{metric}_bucket{{le="+Inf"}} {histogram["count"]}',
                          f'{metric}_count {histogram["count"]}',
                          f'{metric}_sum {histogram["sum"]}']
            return ("\n".join(lines) + "\n").encode()


    def live(self):
        return not self.failure and (self.busy_since is None or
            time.monotonic() - self.busy_since < self.hang_seconds)

    def ready(self):
        return self.backend is not None and self.live()

    def load(self, manifest, models, build, digest, runner_factory=Sam3ModelRunner):
        # No readiness until verification, load AND full-size warm-up succeed.
        try:
            checkpoint, identity = verify_artifact(manifest, models, build, digest)
            runner = runner_factory(str(checkpoint), identity["threshold"])
            if str(runner.dtype).split(".")[-1] != identity["precision"]:
                raise ValueError("runtime precision differs from frozen manifest")
            runner.infer(Image.new("RGB", (640, 480)), identity["prompt"], identity["threshold"])
            self.identity = identity
            self.backend = LocalSam3Backend(runner)
        except Exception:
            # No filesystem paths, payloads or credentials in health responses/logs.
            self.failure = True

    def record(self, status, duration=0):
        with self.metrics_lock:
            self.counts[status] += 1
            self.duration += duration

    def predict(self, request, principal, received):
        if principal not in self.clients:
            self.record("forbidden")
            return 403, {"schema": SCHEMA, "status": "forbidden"}
        try:
            # Strict numeric types and finite values: bool is not a budget.
            if not isinstance(request, dict):
                raise ValueError("object required")
            for key in ("threshold", "budget_ms"):
                if type(request[key]) not in (int, float) or not math.isfinite(request[key]):
                    raise ValueError("finite numeric policy required")
            validate_request(request)
            if not isinstance(request["capture"]["frame_id"], str):
                raise ValueError("invalid frame")
        except (ValueError, KeyError, TypeError, OverflowError):
            self.record("invalid_input")
            # An invalid envelope may have no identity/dimensions; don't echo it.
            return 400, {"schema": SCHEMA, "status": "invalid_input"}
        pair = [request["identity"]["robot"], request["identity"]["stream"]]
        if pair not in self.clients[principal]:
            self.record("forbidden")
            return 403, {"schema": SCHEMA, "status": "forbidden"}

        def error(status, code):
            self.record(status)
            result = response_base(request, status, status)
            if self.identity:
                result["deployment"] = copy.deepcopy(self.identity)
            return code, result

        if not self.ready():
            return error("not_ready", 503)
        if request["prompt"] != self.identity["prompt"] or request["threshold"] != self.identity["threshold"]:
            return error("invalid_input", 400)
        if not self.worker.acquire(blocking=False):
            return error("overload", 429)
        started = time.monotonic()
        self.busy_since = started
        self.observe("admission", max(0.0, started - received))
        # There is no waiting queue: busy admission rejects immediately.
        self.observe("queue", 0.0)
        try:
            remaining = request["budget_ms"] - (started - received) * 1000
            if remaining <= 0:
                return error("timeout", 504)
            work = dict(request, budget_ms=remaining)
            backend_started = time.monotonic()
            try:
                result = self.backend.predict(work)
            finally:
                self.observe("backend", time.monotonic() - backend_started)
            result["deployment"] = copy.deepcopy(self.identity)
            encoded = dumps(result)  # Account for serialization within budget.
            if (time.monotonic() - received) * 1000 >= request["budget_ms"]:
                return error("timeout", 504)
            self.record(result["status"], time.monotonic() - started)
            code = {"ok": 200, "timeout": 504, "inference_error": 500,
                    "invalid_input": 400, "not_ready": 503}[result["status"]]
            return code, encoded
        except Exception:
            return error("inference_error", 500)
        finally:
            self.observe("worker", time.monotonic() - started)
            self.busy_since = None
            self.worker.release()


class BoundedServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    request_queue_size = 8

    def __init__(self, address, service, *, tls=None, health=False):
        self.service, self.tls, self.health = service, tls, health
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(address, Handler)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            request.settimeout(2)
            if self.tls:
                # Handshake in bounded worker: a slow TLS peer can't block accept.
                request = self.tls.wrap_socket(request, server_side=True)
            super().process_request_thread(request, address)
        except (OSError, ssl.SSLError):
            self.shutdown_request(request)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        self.service.record("transport_error")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "semantic-model-server"

    def log_message(self, *args):
        pass

    def reply(self, code, body, content_type="application/json"):
        data = body if isinstance(body, bytes) else dumps(body)
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def principal(self):
        if not isinstance(self.connection, ssl.SSLSocket):
            return None
        certificate = self.connection.getpeercert()
        if not (ssl.cert_time_to_seconds(certificate["notBefore"]) <= time.time() <
                ssl.cert_time_to_seconds(certificate["notAfter"])):
            return None
        uris = [value for kind, value in certificate.get("subjectAltName", [])
                if kind == "URI"]
        return uris[0] if len(uris) == 1 else None

    def do_GET(self):
        service = self.server.service
        if self.server.health:
            if self.path in ("/live", "/ready"):
                ok = service.live() if self.path == "/live" else service.ready()
                return self.reply(200 if ok else 503, {"ok": ok})
        elif self.principal() not in service.clients:
            return self.reply(403, {"status": "forbidden"})
        elif self.path == "/v1/models/sam3-mat-v1":
            return self.reply(200 if service.ready() else 503,
                              {"ready": service.ready(), "deployment": service.identity})
        elif self.path == "/metrics":
            return self.reply(200, service.metrics(), "text/plain; version=0.0.4")
        self.reply(404, {"status": "not_found"})

    def do_POST(self):
        received = time.monotonic()
        # Close on every rejected upload so unread bytes cannot become a request.
        self.close_connection = True
        if self.server.health or self.path != "/v1/models/sam3-mat-v1:predict":
            return self.reply(404, {"status": "not_found"})
        principal = self.principal()
        if principal not in self.server.service.clients:
            return self.reply(403, {"status": "forbidden"})
        lengths = self.headers.get_all("Content-Length", [])
        if (self.headers.get("Transfer-Encoding") or len(lengths) != 1 or
                len(lengths[0]) > 10 or not lengths[0].isdigit()):
            return self.reply(400, {"status": "invalid_input"})
        length = int(lengths[0])
        if not 0 < length <= MAX_WIRE_BYTES:
            return self.reply(413, {"status": "invalid_input"})
        if self.headers.get_content_type() != "application/json":
            return self.reply(415, {"status": "invalid_input"})
        try:
            data = bytearray()
            deadline = received + 5
            while len(data) < length:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                self.connection.settimeout(min(2, remaining))
                chunk = self.rfile.read1(min(65536, length - len(data)))
                if not chunk:
                    raise ValueError("short body")
                data.extend(chunk)
            request = loads(data)
        except (ValueError, TypeError, RecursionError):
            return self.reply(400, {"status": "invalid_input"})
        except (TimeoutError, socket.timeout):
            return self.reply(408, {"status": "timeout"})
        self.connection.settimeout(2)
        self.close_connection = self.headers.get("Connection", "").lower() == "close"
        code, response = self.server.service.predict(request, principal, received)
        self.reply(code, response)


def main():
    clients = json.loads(Path(os.environ["CLIENT_POLICY"]).read_text())
    if not clients or not isinstance(clients, dict):
        raise ValueError("explicit client policy required")
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.verify_mode = ssl.CERT_REQUIRED
    tls.load_cert_chain(os.environ["TLS_CERT"], os.environ["TLS_KEY"])
    tls.load_verify_locations(os.environ["CLIENT_CA"])
    service = ModelService(clients)
    health = BoundedServer(("0.0.0.0", 8080), service, health=True)
    threading.Thread(target=health.serve_forever, daemon=True).start()
    threading.Thread(target=service.load, args=(
        os.environ.get("MODEL_MANIFEST", "/app/model-manifest.json"),
        os.environ.get("MODEL_DIR", "/models"), "/app/build-identity.json",
        os.environ["RUNTIME_IMAGE_DIGEST"]), daemon=True).start()
    BoundedServer(("0.0.0.0", 8443), service, tls=tls).serve_forever()


if __name__ == "__main__":
    main()
