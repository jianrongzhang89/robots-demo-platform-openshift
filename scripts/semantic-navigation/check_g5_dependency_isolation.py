#!/usr/bin/env python3
"""Compare direct-IP dependency reachability from serving and control pods.

The already-loaded server is egress-isolated. This does not stop shared platform
components or claim to simulate a registry-wide outage. Pair with replay evidence.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import socket


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    report = {'recorded_at': datetime.now(timezone.utc).isoformat(), 'status': 'FAIL',
              'method': 'existing serving egress isolation, verified direct-IP control connections'}
    with args.output.open('x') as handle:
        try:
            def oc(*argv):
                return subprocess.check_output(['oc', '--request-timeout=20s', *argv], text=True, timeout=30)
            def route(ns, name):
                return json.loads(oc('get', 'route', name, '-n', ns, '-o', 'json'))['spec']['host']
            hosts = {'registry': route('rhoai-model-registries', 'ryans-model-registry-https'),
                     'dashboard': route('redhat-ods-applications', 'rhods-dashboard')}
            # Platform namespace ingress policies block the replay pod's direct
            # ClusterIP path. Use supported ingress routes for positive controls.
            report['route_hosts'] = hosts
            targets = [(name, socket.gethostbyname(host), 443) for name, host in hosts.items()]
            targets.append(('external-https', '1.1.1.1', 443))
            pods = json.loads(oc('get', 'pods', '-n', 'semantic-model-serving', '-l',
                                'serving.kserve.io/inferenceservice=sam3-mat-v1', '-o', 'json'))['items']
            if len(pods) != 1:
                raise ValueError('exactly one serving pod required')
            pod = pods[0]
            report['serving_pod_uid'] = pod['metadata']['uid']
            report['policies'] = json.loads(oc('get', 'networkpolicy', '-n', 'semantic-model-serving', '-o', 'json'))
            code = '''import socket,json,time,sys
out=[]
for name,ip,port in json.loads(sys.argv[1]):
 start=time.monotonic()
 try:
  with socket.create_connection((ip,port),timeout=2): pass
  row={"target":name,"ip":ip,"port":port,"connected":True}
 except OSError as e:
  row={"target":name,"ip":ip,"port":port,"connected":False,"error_type":type(e).__name__,"error":str(e)}
 row["elapsed_seconds"]=time.monotonic()-start;out.append(row)
print(json.dumps(out))
'''
            for label, ns, name, container in [('control', 'semantic-navigation', 'sam3-g5-client', 'client'),
                                             ('serving', 'semantic-model-serving', pod['metadata']['name'], 'kserve-container')]:
                report[label] = json.loads(oc('exec', '-n', ns, name, '-c', container, '--',
                    '/opt/sam3-venv/bin/python', '-c', code, json.dumps(targets)))
            report['status'] = 'PASS' if all(r['connected'] for r in report['control']) and all(
                not r['connected'] and r['error_type'] == 'TimeoutError' for r in report['serving']) else 'FAIL'
        except Exception as error:
            report['error'] = str(error)
            raise
        finally:
            handle.write(json.dumps(report, indent=2)+'\n')
    print(json.dumps({'status':report['status']}))
    if report['status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
