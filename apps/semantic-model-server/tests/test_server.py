import copy
import http.client
import importlib.util
import json
from pathlib import Path
import ssl
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from artifact import sha256, verify_artifact, verify_deployment_identity
from inference_contract import MAX_WIRE_BYTES, POLICY, VERSIONS, decode_response, dumps, loads, make_request
from sam3_backend import LocalSam3Backend
from server import BoundedServer, ModelService

PRINCIPAL = "spiffe://semantic-navigation/sa/sam3-replay"
CLIENTS = {PRINCIPAL: [["robot_1", "camera/color"]]}
IDENTITY = {"schema": "semantic-deployment/v1", "prompt": "red mat", "threshold": 0.5,
            "precision": "bfloat16", "weights_sha256": "test-double", "source_revision": "test-double",
            "versions": VERSIONS, "policy": POLICY}


class Runner:
    dtype = "torch.bfloat16"

    def infer(self, image, prompt, threshold):
        mask = np.asarray(image)[:, :, 0] > 100
        if not mask.any():
            return np.empty((0, image.height, image.width)), np.array([])
        return mask[None, ...], np.array([0.9])


def request():
    return make_request(Image.new("RGB", (3, 2), (200, 0, 0)), sequence=1,
        epoch="replay", generation=1, stamp=100, frame="optical", prompt="red mat",
        threshold=0.5, budget_ms=1000)


def service():
    model = ModelService(CLIENTS)
    model.backend = LocalSam3Backend(Runner())
    model.identity = copy.deepcopy(IDENTITY)
    return model


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.model = service()

    def predict(self, body=None, principal=PRINCIPAL, received=None):
        code, result = self.model.predict(request() if body is None else body, principal,
            time.monotonic() if received is None else received)
        return code, loads(result) if isinstance(result, bytes) else result

    def test_parity_and_additive_identity(self):
        req = request()
        code, result = self.predict(req)
        self.assertEqual(code, 200)
        np.testing.assert_array_equal(decode_response(req, result)[0],
            decode_response(req, LocalSam3Backend(Runner()).predict(req))[0])
        verify_deployment_identity(result["deployment"], IDENTITY)
        with self.assertRaises(ValueError):
            verify_deployment_identity(result["deployment"], {**IDENTITY, "precision": "float16"})

    def test_empty_is_fresh_success(self):
        req = request()
        req["image"] = "A" * 24
        code, result = self.predict(req)
        self.assertEqual((code, result["count"]), (200, 0))
        self.assertFalse(decode_response(req, result)[0].any())

    def test_invalid_envelopes_do_not_execute_model(self):
        with patch.object(self.model.backend, "predict") as infer:
            for body in ({}, [], "bad", {"identity": {}}, {**request(), "identity": []},
                         {**request(), "threshold": True}, {**request(), "budget_ms": float("nan")},
                         {**request(), "width": 100000}, {**request(), "image": "!"},
                         {**request(), "versions": {}}):
                with self.subTest(body=body):
                    self.assertEqual(self.predict(body)[0], 400)
            infer.assert_not_called()

    def test_auth_policy_and_prompt_policy(self):
        self.assertEqual(self.predict(principal="untrusted")[0], 403)
        req = request()
        req["identity"]["robot"] = "robot_2"
        self.assertEqual(self.predict(req)[0], 403)
        for key, value in (("prompt", "person"), ("threshold", 0.6)):
            self.assertEqual(self.predict({**request(), key: value})[0], 400)

    def test_not_ready_overload_and_expired_input(self):
        self.model.backend = None
        self.assertEqual(self.predict()[0], 503)
        self.model = service()
        self.model.worker.acquire()
        try:
            self.assertEqual(self.predict()[0], 429)
        finally:
            self.model.worker.release()
        with patch.object(self.model.backend, "predict") as infer:
            self.assertEqual(self.predict(received=time.monotonic() - 2)[0], 504)
            infer.assert_not_called()

    def test_late_results_are_timeout_not_empty(self):
        runner = self.model.backend.runner
        original = runner.infer
        def slow(*args):
            time.sleep(0.02)
            return original(*args)
        with patch.object(runner, "infer", side_effect=slow):
            code, result = self.predict({**request(), "budget_ms": 5})
        self.assertEqual((code, result["status"]), (504, "timeout"))
        self.assertNotIn("masks", result)

    def test_worker_hang_is_unhealthy_and_no_queue(self):
        entered, release = threading.Event(), threading.Event()
        def hang(*args):
            entered.set()
            release.wait(2)
            return np.empty((0, 2, 3)), []
        self.model.hang_seconds = 0.01
        with patch.object(self.model.backend.runner, "infer", side_effect=hang):
            worker = threading.Thread(target=self.predict)
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                self.assertEqual(self.predict()[0], 429)
                time.sleep(0.02)
                self.assertFalse(self.model.live())
                self.assertFalse(self.model.ready())
                self.assertEqual(self.predict()[0], 503)
            finally:
                release.set()
                worker.join(2)

    def test_readiness_requires_warmup_and_precision(self):
        model = ModelService(CLIENTS)
        self.assertFalse(model.ready())
        with patch("server.verify_artifact", return_value=("checkpoint", IDENTITY)):
            def factory(*args):
                self.assertFalse(model.ready())
                runner = Runner()
                original = runner.infer
                def warmup(*args):
                    self.assertFalse(model.ready())
                    return original(*args)
                runner.infer = warmup
                return runner
            model.load("a", "b", "c", "d", factory)
            self.assertTrue(model.ready())
            bad = ModelService(CLIENTS)
            runner = Runner()
            runner.dtype = "torch.float16"
            bad.load("a", "b", "c", "d", lambda *args: runner)
            self.assertFalse(bad.live())
            self.assertFalse(bad.ready())

    def test_metrics_account_for_failed_backend_without_queuing(self):
        with patch.object(self.model.backend, "predict", side_effect=RuntimeError("GPU failed")):
            self.assertEqual(self.predict()[0], 500)
        self.assertEqual(self.model.histograms["backend"]["count"], 1)
        self.assertEqual(self.model.histograms["worker"]["count"], 1)
        self.assertEqual(self.model.histograms["queue"]["sum"], 0)
        self.assertIsNone(self.model.busy_since)
        self.assertTrue(self.model.worker.acquire(False))
        try:
            self.assertEqual(self.predict()[0], 429)
            self.assertEqual(self.model.histograms["backend"]["count"], 1)
        finally:
            self.model.worker.release()
        metrics = self.model.metrics().decode()
        self.assertIn('semantic_backend_duration_seconds_bucket{le="+Inf"} 1', metrics)
        self.assertNotIn("request_id", metrics)

    def test_histograms_have_cumulative_buckets(self):
        self.model.observe("backend", 0.02)
        self.model.observe("backend", 0.2)
        h = self.model.histograms["backend"]
        self.assertEqual(h["count"], 2)
        self.assertAlmostEqual(h["sum"], 0.22)
        self.assertEqual(h["buckets"], [0, 0, 0, 1, 1, 1, 2, 2, 2, 2, 2, 2])

    def test_checksum_failure_prevents_loading(self):
        model = ModelService(CLIENTS)
        with patch("server.verify_artifact", side_effect=ValueError("checksum")), \
                patch("server.Sam3ModelRunner") as runner:
            model.load("a", "b", "c", "d", runner)
            runner.assert_not_called()
        self.assertFalse(model.ready())


class ArtifactTests(unittest.TestCase):
    def test_artifact_and_shared_source_tampering(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = json.loads((source / "model-manifest.json").read_text())
            (root / "sam3.pt").write_bytes(b"test weights")
            manifest["weights_sha256"] = sha256(root / "sam3.pt")
            shared = {}
            for name in ("sam3_backend.py", "inference_contract.py", "sam3_runtime_core.py"):
                (root / name).write_text(name)
                shared[name] = sha256(root / name)
            (root / "build.json").write_text(json.dumps({
                "source_revision": manifest["source_revision"], "shared_sha256": shared}))
            (root / "manifest.json").write_text(json.dumps(manifest))
            args = (root / "manifest.json", root, root / "build.json", "sha256:" + "a" * 64)
            with patch("artifact.WEIGHTS_SHA256", manifest["weights_sha256"]):
                _, identity = verify_artifact(*args)
                self.assertEqual(identity["weights_sha256"], manifest["weights_sha256"])
                (root / "sam3.pt").write_bytes(b"tampered")
                with self.assertRaisesRegex(ValueError, "checkpoint"):
                    verify_artifact(*args)
                (root / "sam3.pt").write_bytes(b"test weights")
                (root / "sam3_backend.py").write_text("tampered")
                with self.assertRaisesRegex(ValueError, "shared source"):
                    verify_artifact(*args)


class TransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        def openssl(*args):
            subprocess.run(["openssl", *args], cwd=cls.root, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                "-subj", "/CN=Test CA", "-keyout", "ca.key", "-out", "ca.crt",
                "-addext", "basicConstraints=critical,CA:TRUE",
                "-addext", "keyUsage=critical,keyCertSign,cRLSign")
        for name, san, usage in (("server", "DNS:localhost", "serverAuth"),
                ("client", "URI:" + PRINCIPAL, "clientAuth"),
                ("wrong", "URI:spiffe://untrusted/client", "clientAuth")):
            openssl("req", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=" + name,
                    "-keyout", name + ".key", "-out", name + ".csr")
            (cls.root / (name + ".ext")).write_text(
                f"subjectAltName={san}\nextendedKeyUsage={usage}\n"
                "basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n")
            openssl("x509", "-req", "-days", "1", "-in", name + ".csr", "-CA", "ca.crt",
                    "-CAkey", "ca.key", "-CAcreateserial", "-extfile", name + ".ext",
                    "-out", name + ".crt")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.verify_mode = ssl.CERT_REQUIRED
        tls.load_cert_chain(self.root / "server.crt", self.root / "server.key")
        tls.load_verify_locations(self.root / "ca.crt")
        self.model = service()
        self.server = BoundedServer(("127.0.0.1", 0), self.model, tls=tls)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def connect(self, name="client"):
        context = ssl.create_default_context(cafile=str(self.root / "ca.crt"))
        if name:
            context.load_cert_chain(self.root / (name + ".crt"), self.root / (name + ".key"))
        return http.client.HTTPSConnection("localhost", self.server.server_port, context=context, timeout=2)

    def post(self, body, headers=None, name="client"):
        connection = self.connect(name)
        try:
            connection.request("POST", "/v1/models/sam3-mat-v1:predict", body,
                               headers or {"Content-Type": "application/json"})
            response = connection.getresponse()
            return response.status, loads(response.read())
        finally:
            connection.close()

    def test_https_parity_and_reuse(self):
        conn = self.connect()
        try:
            for _ in range(2):
                req = request()
                conn.request("POST", "/v1/models/sam3-mat-v1:predict", dumps(req), {"Content-Type": "application/json"})
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                body = loads(response.read())
                verify_deployment_identity(body["deployment"], IDENTITY)
                self.assertTrue(decode_response(req, body)[0].any())
        finally:
            conn.close()

    def test_monitor_principal_can_read_but_cannot_infer(self):
        # An empty allowed-pairs policy is deliberately read-only.
        self.model.clients = {PRINCIPAL: []}
        conn = self.connect()
        try:
            conn.request("GET", "/metrics")
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIn(b"semantic_queue_capacity 0", response.read())
        finally:
            conn.close()
        with patch.object(self.model.backend, "predict") as infer:
            self.assertEqual(self.post(dumps(request()))[0], 403)
            infer.assert_not_called()

    def test_no_certificate_and_unbound_certificate(self):
        with self.assertRaises((ssl.SSLError, OSError, http.client.HTTPException)):
            self.post(dumps(request()), name=None)
        self.assertEqual(self.post(dumps(request()), name="wrong")[0], 403)

    def test_oversized_malformed_and_chunked(self):
        self.assertEqual(self.post(b"{bad")[0], 400)
        self.assertEqual(self.post(b"[]")[0], 400)
        self.assertEqual(self.post(b"{\"budget_ms\":NaN}")[0], 400)
        self.assertEqual(self.post(b"", {"Content-Type": "application/json",
            "Content-Length": str(MAX_WIRE_BYTES + 1)})[0], 413)
        self.assertEqual(self.post(b"", {"Transfer-Encoding": "chunked"})[0], 400)

    def test_replay_report_preserves_per_frame_failures(self):
        root = Path(__file__).resolve().parents[3]
        spec = importlib.util.spec_from_file_location("replay", root / "scripts/semantic-navigation/replay_serving_parity.py")
        replay = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(replay)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            rows = []
            for index, case in enumerate(("mat", "absent-target", "empty-mask")):
                req = request()
                if case != "mat":
                    req["image"] = "A" * 24
                row = {"case": case}
                for key, value in (("request", req), ("local_response", LocalSam3Backend(Runner()).predict(req))):
                    path = output / f"{index}-{key}.json"
                    path.write_bytes(dumps(value))
                    row[key] = path.name
                    row[key + "_sha256"] = sha256(path)
                rows.append(row)
            manifest = output / "manifest.json"
            manifest.write_text(json.dumps({"local_identity": IDENTITY, "frames": rows}))
            identity = output / "identity.json"
            identity.write_text(json.dumps(IDENTITY))
            args = SimpleNamespace(manifest=manifest, identity=identity,
                endpoint=f"https://localhost:{self.server.server_port}", ca=self.root / "ca.crt",
                cert=self.root / "client.crt", key=self.root / "client.key")
            self.assertEqual(replay.replay(args)["status"], "PASS")
            (output / rows[1]["request"]).write_bytes(b"tampered")
            report = replay.replay(args)
            self.assertEqual(report["status"], "FAIL")
            self.assertEqual([row["passed"] for row in report["frames"]], [True, False, True])


if __name__ == "__main__":
    unittest.main()
