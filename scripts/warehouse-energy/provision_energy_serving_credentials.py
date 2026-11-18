#!/usr/bin/env python3
"""Provision Stage 3C energy-serving mTLS credentials as OpenShift Secrets.

Creates the serving-side Secret (server certificate, key, and client CA) in
the serving namespace and the client-side Secret (client certificate, key,
and CA) in the client namespace. Credential bytes are generated in a private
temporary directory, streamed to the API, and never printed or retained
locally. Refuses to replace existing Secrets.
"""
import base64
import json
import subprocess
import tempfile
from pathlib import Path

SERVING_NAMESPACE = "semantic-model-serving"
CLIENT_NAMESPACE = "semantic-navigation"
SERVER_SECRET = "energy-serving-tls"
CLIENT_SECRET = "energy-serving-client-tls"
CLIENT_SPIFFE = "spiffe://warehouse-energy/client/energy-qualifier-v1"
SERVER_DNS = f"energy-predictor-v1-tls.{SERVING_NAMESPACE}.svc"


def oc(*args, data=None, check=True):
    result = subprocess.run(["oc", *args], input=data, capture_output=True, timeout=60)
    if check and result.returncode:
        raise RuntimeError(f"oc {args[0]} failed: {result.stderr.decode()[:300]}")
    return result


def secret(namespace, name, files, labels):
    return {
        "apiVersion": "v1", "kind": "Secret",
        "metadata": {"name": name, "namespace": namespace, "labels": labels},
        "type": "kubernetes.io/tls" if name == SERVER_SECRET else "Opaque",
        "stringData": files,
    }


def main():
    for namespace, name in [(SERVING_NAMESPACE, SERVER_SECRET),
                            (CLIENT_NAMESPACE, CLIENT_SECRET)]:
        existing = oc("get", "secret", name, "-n", namespace,
                      "--ignore-not-found", "-o", "name", check=False)
        if existing.stdout.strip():
            raise RuntimeError(f"refusing to replace Secret/{name} in {namespace}")
    with tempfile.TemporaryDirectory(prefix="energy-serving-tls-") as directory:
        root = Path(directory)

        def openssl(*args):
            subprocess.run(["openssl", *args], cwd=root, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "365",
                "-subj", "/CN=Energy serving client CA", "-keyout", "ca.key",
                "-out", "client-ca.crt",
                "-addext", "basicConstraints=critical,CA:TRUE",
                "-addext", "keyUsage=critical,keyCertSign,cRLSign")
        for name, usage, san in (
                ("server", "serverAuth", f"DNS:{SERVER_DNS},DNS:localhost,IP:127.0.0.1"),
                ("energy-qualifier", "clientAuth", f"URI:{CLIENT_SPIFFE}")):
            openssl("req", "-newkey", "rsa:2048", "-nodes", "-subj", f"/CN={name}",
                    "-keyout", f"{name}.key", "-out", f"{name}.csr")
            (root / "ext").write_text(
                "basicConstraints=critical,CA:FALSE\n"
                "keyUsage=critical,digitalSignature,keyEncipherment\n"
                f"extendedKeyUsage={usage}\nsubjectAltName={san}\n")
            openssl("x509", "-req", "-in", f"{name}.csr", "-CA", "client-ca.crt",
                    "-CAkey", "ca.key", "-CAcreateserial", "-days", "365",
                    "-extfile", "ext", "-out", f"{name}.crt")
        server = secret(SERVING_NAMESPACE, SERVER_SECRET, {
            "tls.crt": (root / "server.crt").read_text(),
            "tls.key": (root / "server.key").read_text(),
            "client-ca.crt": (root / "client-ca.crt").read_text(),
        }, {"app": "energy-predictor-v1"})
        client = secret(CLIENT_NAMESPACE, CLIENT_SECRET, {
            "tls.crt": (root / "energy-qualifier.crt").read_text(),
            "tls.key": (root / "energy-qualifier.key").read_text(),
            "client-ca.crt": (root / "client-ca.crt").read_text(),
        }, {"energy-serving-client": "energy-predictor-v1"})
        oc("apply", "-f", "-", data=json.dumps(server).encode())
        oc("apply", "-f", "-", data=json.dumps(client).encode())
        print(json.dumps({"created": [f"{SERVING_NAMESPACE}/{SERVER_SECRET}",
                                      f"{CLIENT_NAMESPACE}/{CLIENT_SECRET}"],
                          "client_spiffe": CLIENT_SPIFFE}))


if __name__ == "__main__":
    main()
