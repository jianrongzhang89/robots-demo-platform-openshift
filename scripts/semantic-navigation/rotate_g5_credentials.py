#!/usr/bin/env python3
"""Stopped replay CA/leaf rotation, with old-client rejection and rollback.

No key material is printed or retained as local evidence. Run only after replay
cycles finish and baseline identity is restored. G5 motion qualification is separate.
"""
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
NS = 'semantic-model-serving'
NAV = 'semantic-navigation'
CLIENT = 'sam3-g5-client'


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'status': 'FAIL',
              'scope': 'stopped replay CA and leaf rotation; no motion claim'}

    def run(*command, data=None):
        r = subprocess.run(command, input=data, capture_output=True, timeout=60)
        if r.returncode:
            # Commands may handle secrets; do not echo their input or output.
            raise RuntimeError(f'{command[0]} operation failed with exit {r.returncode}')
        return r.stdout

    def oc(*argv, data=None):
        return run('oc', '--request-timeout=30s', *argv, data=data)

    def secret(namespace, name):
        return json.loads(oc('get', 'secret', name, '-n', namespace, '-o', 'json'))

    def apply_secret(namespace, name, data):
        payload = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': name, 'namespace': namespace},
                   'type': 'Opaque', 'data': data}
        oc('apply', '-f', '-', data=json.dumps(payload).encode())

    def serving_pod():
        pods = json.loads(oc('get', 'pods', '-n', NS, '-l',
                  'serving.kserve.io/inferenceservice=sam3-mat-v1', '-o', 'json'))['items']
        live = [p for p in pods if not p['metadata'].get('deletionTimestamp')]
        return live[0] if len(live) == 1 else None

    expected = json.loads((ROOT / 'docs/validation/semantic-navigation/openshift-ai/S2/gate-result.json').read_text())['deployment_identity']
    initial = serving_pod()
    if not initial or not any(c['name'] == 'kserve-container' and c.get('imageID', '').endswith('@' + expected['container_digest'])
                             for c in initial.get('status', {}).get('containerStatuses', [])):
        raise ValueError('accepted baseline must be restored before rotation')
    clients = json.loads(oc('get', 'pods', '-n', NAV, '-l', 'semantic-serving-client=sam3-mat-v1', '-o', 'json'))['items']
    if [p['metadata']['name'] for p in clients] != [CLIENT]:
        raise ValueError('only the isolated G5 replay client may be present')
    names = [(NS, 'sam3-g0-issuer'), (NS, 'sam3-serving-tls'), (NAV, 'sam3-replay-tls')]
    originals = {(ns, name): secret(ns, name)['data'] for ns, name in names}

    def restart_server():
        old = serving_pod()
        if old is None:
            raise RuntimeError('ambiguous serving pod')
        oc('delete', 'pod', old['metadata']['name'], '-n', NS, '--wait=true', '--timeout=45s')
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            pod = serving_pod()
            if pod and pod['metadata']['uid'] != old['metadata']['uid'] and any(
                c['type'] == 'Ready' and c['status'] == 'True' for c in pod.get('status', {}).get('conditions', [])):
                return pod['metadata']['uid']
            time.sleep(3)
        raise TimeoutError('replacement server not Ready')

    def client(code, data=None):
        return oc('exec', '-i', '-n', NAV, CLIENT, '--', '/opt/sam3-venv/bin/python', '-c', code, data=data)

    def check_current():
        code = ('import ssl,json,urllib.request; c=ssl.create_default_context(cafile="/cert/ca.crt"); '
                'c.load_cert_chain("/cert/tls.crt","/cert/tls.key"); '
                'print(json.dumps(json.load(urllib.request.urlopen('
                '"https://sam3-mat-v1-tls.semantic-model-serving.svc:8443/v1/models/sam3-mat-v1",context=c,timeout=5))))')
        data = json.loads(client(code))
        if not data.get('ready') or data.get('deployment') != expected:
            raise ValueError('post-rotation identity mismatch')
        return data

    changed = False
    try:
        # Keep retired credentials only in the isolated pod's ephemeral directory.
        old = originals[(NAV, 'sam3-replay-tls')]
        client('import sys,json,base64,pathlib,os; d=json.load(sys.stdin); p=pathlib.Path("/tmp/g5-retired"); p.mkdir(mode=0o700); [( (p/k).write_bytes(base64.b64decode(v)), os.chmod(p/k,0o600)) for k,v in d.items()]', data=json.dumps(old).encode())
        with tempfile.TemporaryDirectory(prefix='g5-rotation-') as directory:
            root = Path(directory); os.chmod(root, 0o700)
            def openssl(*args):
                return run('openssl', *args)
            openssl('req', '-x509', '-newkey', 'rsa:3072', '-nodes', '-keyout', str(root/'ca.key'),
                    '-out', str(root/'ca.crt'), '-days', '90', '-subj', '/CN=semantic-serving-G5-issuer',
                    '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign')
            for name, san, usage in [('server', 'DNS:sam3-mat-v1-tls.semantic-model-serving.svc,DNS:sam3-mat-v1-tls.semantic-model-serving.svc.cluster.local', 'serverAuth'),
                                     ('client', 'URI:spiffe://semantic-navigation/sa/sam3-replay', 'clientAuth')]:
                openssl('req', '-new', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(root/(name+'.key')),
                        '-out', str(root/(name+'.csr')), '-subj', '/CN=sam3-g5-'+name)
                (root/'ext').write_text(f'basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage={usage}\nsubjectAltName={san}\n')
                openssl('x509', '-req', '-in', str(root/(name+'.csr')), '-CA', str(root/'ca.crt'), '-CAkey', str(root/'ca.key'),
                        '-CAcreateserial', '-out', str(root/(name+'.crt')), '-days', '7', '-extfile', str(root/'ext'))
                report[name+'_certificate'] = openssl('x509', '-in', str(root/(name+'.crt')), '-noout', '-dates', '-fingerprint', '-sha256', '-serial').decode()
            def encoded(files):
                return {key: base64.b64encode((root/file).read_bytes()).decode() for key,file in files.items()}
            changed = True
            apply_secret(NS, 'sam3-serving-tls', encoded({'tls.crt':'server.crt', 'tls.key':'server.key', 'client-ca.crt':'ca.crt'}))
            apply_secret(NAV, 'sam3-replay-tls', encoded({'tls.crt':'client.crt', 'tls.key':'client.key', 'ca.crt':'ca.crt'}))
            apply_secret(NS, 'sam3-g0-issuer', encoded({'ca.crt':'ca.crt', 'ca.key':'ca.key'}))
            report['new_pod_uid'] = restart_server()
            # Secret projection is asynchronous; bound waiting before checking auth.
            target = (root/'client.crt').read_text()
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                current = client('from pathlib import Path; print(Path("/cert/tls.crt").read_text(),end="")').decode()
                if current == target:
                    break
                time.sleep(3)
            else:
                raise TimeoutError('client secret projection did not refresh')
            report['new_credentials_metadata'] = check_current()
            # Trust the NEW server CA, but present the OLD client leaf/key. Failure
            # must be client authentication, not rejection of the new server chain.
            code = '''import ssl,json,http.client
c=ssl.create_default_context(cafile="/cert/ca.crt")
c.load_cert_chain("/tmp/g5-retired/tls.crt","/tmp/g5-retired/tls.key")
h=http.client.HTTPSConnection("sam3-mat-v1-tls.semantic-model-serving.svc",8443,context=c,timeout=5)
try:
 h.request("GET","/v1/models/sam3-mat-v1"); r=h.getresponse(); r.read()
 print(json.dumps({"rejected":False,"http_status":r.status}))
except ssl.SSLError as e:
 print(json.dumps({"rejected":True,"reason":str(e)}))
finally:
 h.close()
'''
            report['retired_client'] = json.loads(client(code))
            if not report['retired_client']['rejected']:
                raise ValueError('retired client did not fail TLS authentication')
            report['missing_client_certificate'] = json.loads(client(code.replace(
                'c.load_cert_chain("/tmp/g5-retired/tls.crt","/tmp/g5-retired/tls.key")', '')))
            if not report['missing_client_certificate']['rejected']:
                raise ValueError('missing client certificate was accepted')
            report['post_negative_metadata'] = check_current()
            report['status'] = 'PASS'
    except Exception as error:
        report['error'] = str(error)
        if changed:
            try:
                for (ns, name), data in originals.items():
                    apply_secret(ns, name, data)
                report['rollback_pod_uid'] = restart_server()
                report['rollback'] = 'SECRETS_RESTORED_RECHECK_CLIENT_PROJECTION'
            except Exception as restore_error:
                report['rollback'] = 'FAIL'; report['rollback_error'] = str(restore_error)
        raise
    finally:
        try:
            client('import shutil; shutil.rmtree("/tmp/g5-retired",ignore_errors=True)')
        finally:
            (args.output_dir/'result.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({'status':report['status'], 'new_pod_uid':report['new_pod_uid']}))


if __name__ == '__main__':
    main()
