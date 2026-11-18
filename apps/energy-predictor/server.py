#!/usr/bin/env python3
"""Bounded, mutually authenticated HTTPS wrapper around the energy predictor.

Health is served separately on 8080 without authentication; all model data
(including identity) requires a client certificate on 8443. One prediction
batch at a time is admitted; concurrent calls are rejected with 429. No ROS
imports, no downloads, no request-time training, no credentials in logs.
"""
from collections import Counter
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import math
import os
from pathlib import Path
import socket
import socketserver
import ssl
import threading
import time

import xgboost

from predictor import (BATCH_LIMIT, MAX_WIRE_BYTES, MODEL_NAME, SCHEMA,
                       EnergyPredictor, InputError, validate_request)

PREDICT_PATH = f"/v1/models/{MODEL_NAME}:predict"
META_PATH = f"/v1/models/{MODEL_NAME}"


class BoundedServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, address, service, tls=None, health=False):
        self.service = service
        self.health = health
        super().__init__(address, Handler)
        if tls:
            self.socket = tls.wrap_socket(self.socket, server_side=True)


class ModelService:
    def __init__(self, clients, hang_seconds=10):
        self.clients = clients
        self.hang_seconds = hang_seconds
        self.predictor = None
        self.failure = False
        self.busy_since = None
        self.worker = threading.Lock()
        self.metrics_lock = threading.Lock()
        self.counts = Counter()

    def live(self):
        return not self.failure and (self.busy_since is None or
                                     time.monotonic() - self.busy_since < self.hang_seconds)

    def ready(self):
        return self.predictor is not None and self.live()

    def load(self, manifest, release_dir, physics_model):
        try:
            predictor = EnergyPredictor(release_dir, physics_model, manifest,
                                        xgboost_module=xgboost)
            identity = predictor.identity()
            # Warm-up: one full batch inference before readiness.
            probe = {"length_m": 10.0, "ramp_run_m": 10.0, "signed_rise_m": 0.2,
                     "speed_mps": 0.1, "heading_change_rad": 0.0, "planned_stops": 0,
                     "planned_dwell_s": 13.5, "total_mass_kg": 2.153, "class": "nav"}
            results = predictor.predict_segments([probe] * BATCH_LIMIT)
            if len(results) != BATCH_LIMIT or any(
                    not math.isfinite(r["predicted_wh"]) for r in results):
                raise ValueError("warm-up produced invalid predictions")
            self.predictor = predictor
            self.identity = identity
        except Exception:
            self.failure = True

    def record(self, status):
        with self.metrics_lock:
            self.counts[status] += 1

    def metrics(self):
        with self.metrics_lock:
            lines = [f'energy_requests_total{{status="{key}"}} {value}'
                     for key, value in sorted(self.counts.items())]
        lines.append(f"energy_worker_ready {int(self.ready())}")
        return ("\n".join(lines) + "\n").encode()

    def predict(self, request, principal):
        if principal not in self.clients:
            self.record("forbidden")
            return 403, {"schema": SCHEMA, "status": "forbidden"}
        if not self.ready():
            self.record("not_ready")
            return 503, {"schema": SCHEMA, "status": "not_ready"}
        try:
            segments = validate_request(request, robots=self.robot_policy(principal))
        except InputError as exc:
            self.record("invalid_input")
            return 400, {"schema": SCHEMA, "status": "invalid_input",
                         "reason": str(exc)}
        if not self.worker.acquire(blocking=False):
            self.record("overload")
            return 429, {"schema": SCHEMA, "status": "overload"}
        self.busy_since = time.monotonic()
        try:
            results = self.predictor.predict_segments(segments)
            self.record("ok")
            return 200, {
                "schema": SCHEMA,
                "status": "ok",
                "request_id": request["request_id"],
                "planning_generation": request["planning_generation"],
                "model_version": MODEL_NAME,
                "deployment": dict(self.identity),
                "allowances": {
                    "learned_wh": self.predictor.allowance_learned,
                    "physics_fallback_wh": self.predictor.allowance_fallback,
                },
                "segments": results,
            }
        except Exception:
            self.record("backend_error")
            return 500, {"schema": SCHEMA, "status": "backend_error"}
        finally:
            self.busy_since = None
            self.worker.release()

    def robot_policy(self, principal):
        """Map the authenticated principal to its allowed robot configs."""
        return {config: self.predictor.manifest["robot_allowlist"][config]
                for config in self.clients.get(principal, [])
                if config in self.predictor.manifest.get("robot_allowlist", {})}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "energy-predictor/1"

    def log_message(self, *args):
        pass  # No paths, payloads or principals in logs.

    def reply(self, code, body, content_type="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
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
        elif self.path == META_PATH:
            return self.reply(200 if service.ready() else 503,
                              {"ready": service.ready(), "deployment": service.identity})
        elif self.path == "/metrics":
            return self.reply(200, service.metrics(), "text/plain; version=0.0.4")
        self.reply(404, {"status": "not_found"})

    def do_POST(self):
        received = time.monotonic()
        self.close_connection = True
        if self.server.health or self.path != PREDICT_PATH:
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
            request = json.loads(bytes(data))
        except (ValueError, TypeError, RecursionError):
            return self.reply(400, {"status": "invalid_input"})
        except (TimeoutError, socket.timeout):
            return self.reply(408, {"status": "timeout"})
        code, response = self.server.service.predict(request, principal)
        self.reply(code, response)


def main():
    clients = json.loads(Path(os.environ["CLIENT_POLICY"]).read_text())
    if not clients or not isinstance(clients, dict):
        raise ValueError("explicit client policy required")
    data_port = int(os.environ.get("DATA_PORT", "8443"))
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
        os.environ.get("RELEASE_DIR", "/app/release"),
        os.environ.get("PHYSICS_MODEL", "/app/physics-model-v1.json")), daemon=True).start()
    BoundedServer(("0.0.0.0", data_port), service, tls=tls).serve_forever()


if __name__ == "__main__":
    main()
