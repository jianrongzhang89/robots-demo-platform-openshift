#!/usr/bin/env python3
"""Create short-lived, validation-only Phase 7 credentials as an OpenShift Secret.

Credential bytes are generated in a private temporary directory, streamed to
the API, and never printed or retained locally. These identities are only for
the native watchdog/mTLS integration fixture, not a production robot.
"""
import base64
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile


NAMESPACE = "semantic-navigation"
SECRET_NAME = "semantic-phase7-fixture-credentials"


def run(command, *, data=None):
    result = subprocess.run(command, input=data, capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError(f"{command[0]} failed with exit {result.returncode}")
    return result.stdout


def main():
    existing = subprocess.run(
        ["oc", "get", "secret", SECRET_NAME, "-n", NAMESPACE,
         "--ignore-not-found", "-o", "name"],
        capture_output=True, timeout=30)
    if existing.returncode == 0 and existing.stdout.strip():
        raise RuntimeError(f"refusing to replace Secret/{SECRET_NAME}")
    if existing.returncode != 0:
        raise RuntimeError("could not determine whether the validation Secret exists")

    with tempfile.TemporaryDirectory(prefix="phase7-fixture-credentials-") as directory:
        root = Path(directory)
        os.chmod(root, 0o700)

        def openssl(*args):
            subprocess.run(["openssl", *args], cwd=root, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "30",
                "-subj", "/CN=Phase7 validation client CA", "-keyout", "ca.key",
                "-out", "client-ca.crt", "-addext", "basicConstraints=critical,CA:TRUE",
                "-addext", "keyUsage=critical,keyCertSign,cRLSign")
        for name, usage, san in (
            ("server", "serverAuth", "DNS:localhost,IP:127.0.0.1"),
            ("operator-17", "clientAuth", "URI:spiffe://operator-17"),
        ):
            openssl("req", "-newkey", "rsa:2048", "-nodes", "-subj", f"/CN={name}",
                    "-keyout", f"{name}.key", "-out", f"{name}.csr")
            (root / "ext").write_text(
                "basicConstraints=critical,CA:FALSE\n"
                "keyUsage=critical,digitalSignature,keyEncipherment\n"
                f"extendedKeyUsage={usage}\nsubjectAltName={san}\n")
            openssl("x509", "-req", "-in", f"{name}.csr", "-CA", "client-ca.crt",
                    "-CAkey", "ca.key", "-CAcreateserial", "-days", "7",
                    "-extfile", "ext", "-out", f"{name}.crt")

        files = {
            "signing.key": secrets.token_bytes(32),
            "operators.json": json.dumps({
                "operator-17": secrets.token_urlsafe(32)
            }, sort_keys=True).encode(),
        }
        for name in ("client-ca.crt", "server.crt", "server.key",
                     "operator-17.crt", "operator-17.key"):
            files[name] = (root / name).read_bytes()
        payload = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {
                "name": SECRET_NAME,
                "namespace": NAMESPACE,
                "labels": {"semantic-navigation.robots-demo/phase": "phase7-validation"},
            },
            "type": "Opaque",
            "data": {name: base64.b64encode(value).decode("ascii")
                     for name, value in files.items()},
        }
        run(["oc", "apply", "-f", "-"], data=json.dumps(payload).encode())
    print(f"created validation-only Secret/{SECRET_NAME}; credential material was not printed")


if __name__ == "__main__":
    main()
