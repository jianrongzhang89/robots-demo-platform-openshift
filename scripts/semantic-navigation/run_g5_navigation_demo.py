#!/usr/bin/env python3
"""One served semantic-on presentation, held for an explicit operator start."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

from g4_topology import ROOT, OC, call
from phase6_trial import IMAGE, NODE
from preflight_g5 import collect
from g5_demo_result import endpoint_result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args(); args.output_dir.mkdir(parents=True, exist_ok=False)
    out = args.output_dir
    def save(name, value): (out/name).write_text(json.dumps(value, indent=2)+'\n')
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'passed': False,
              'scope': 'Single semantic-on presentation with accepted serving runtime; explicit operator start; no automatic retry or new gate qualification'}
    owned = False; topology_owned = False; route_owned = False; child = None
    reservation = ROOT/'docs/validation/semantic-navigation/openshift-ai/S4/g4-qualification-20261031/rendering-reservation-saved.json'
    viewer_name = 'semantic-g5-demo-novnc'
    try:
        preflight = collect(OC); save('preflight.json', preflight)
        if preflight['preflight_status'] != 'PASS': raise RuntimeError('preflight did not pass')
        for kind, name in [('pod', 'semantic-phase5-native'), ('configmap', 'semantic-phase5-native'),
                           ('service', viewer_name), ('route', viewer_name)]:
            if call('get', kind, name, '--ignore-not-found', '-o', 'name').stdout.strip():
                raise RuntimeError('existing demo resource: '+name)
        topology_owned = True
        subprocess.run([sys.executable, str(ROOT/'scripts/semantic-navigation/g4_topology.py'),
                        'up', '--output-dir', str(out/'topology')], check=True)
        call('delete', 'pod', 'sam3-g0-rendering-reservation', '--wait=true', '--timeout=120s'); owned = True
        service = {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': viewer_name, 'namespace': 'semantic-navigation'},
                   'spec': {'selector': {'semantic-g5-demo': 'viewer'}, 'ports': [{'name': 'novnc', 'port': 6080, 'targetPort': 'novnc'}]}}
        route = {'apiVersion': 'route.openshift.io/v1', 'kind': 'Route',
                 'metadata': {'name': viewer_name, 'namespace': 'semantic-navigation', 'annotations': {'haproxy.router.openshift.io/timeout': '10m'}},
                 'spec': {'to': {'kind': 'Service', 'name': viewer_name}, 'port': {'targetPort': 'novnc'},
                          'tls': {'termination': 'edge', 'insecureEdgeTerminationPolicy': 'Redirect'}}}
        route_owned = True
        for obj in [service, route]: call('create', '-f', '-', obj=obj)
        save('viewer-resources.json', [service, route])
        host = call('get', 'route', viewer_name, '-o', 'jsonpath={.spec.host}').stdout
        save('viewer.json', {'url': 'https://'+host+'/vnc.html?autoconnect=true&resize=scale&view_only=true', 'view_only': True})
        command = [sys.executable, str(ROOT/'scripts/semantic-navigation/run_phase5_native.py'), '--oc', OC,
                   '--suite', 'hotel-guarded', '--contact-audit', '--sam3-observation', '--served-topology',
                   '--semantic-arm', 'on', '--phase6-lethal', '--phase6-tf-witness', '--controller-endpoint-capture',
                   '--console-only-server', '--rear-casters', '--physics-step', '0.002', '--lidar-range', '12',
                   '--odom-frequency', '200', '--gpu-rendering', '--node-name', NODE, '--image', IMAGE,
                   '--phase6-goal-x', '19.4008', '--phase6-goal-y', '-31.594',
                   '--operator-demo', '--output-dir', str(out/'trial')]
        save('command.json', command)
        with (out/'runner.log').open('w') as handle:
            child = subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT)
            code = child.wait(timeout=3000)
        report['returncode'] = code
        summary_path = out/'trial/runtime/summary.json'
        summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
        trace_path=out/'trial/runtime/trace.jsonl'
        records=[json.loads(line) for line in trace_path.read_text().splitlines()] if trace_path.exists() else []
        report['physical_endpoint']=endpoint_result(summary,records)
        save('physical-endpoint.json',report['physical_endpoint'])
        report['passed'] = code == 0 and report['physical_endpoint']['passed']
    except Exception as error:
        report['error'] = str(error)
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try: child.wait(timeout=20)
            except subprocess.TimeoutExpired: child.kill(); child.wait()
        cleanup = []
        commands = []
        if owned:
            commands += [[OC, '-n', 'semantic-navigation', 'delete', 'pod,configmap', 'semantic-phase5-native', '--ignore-not-found', '--wait=true', '--timeout=90s']]
        if route_owned:
            commands += [[OC, '-n', 'semantic-navigation', 'delete', 'service,route', viewer_name, '--ignore-not-found', '--wait=true', '--timeout=60s']]
        if topology_owned:
            commands += [[sys.executable, str(ROOT/'scripts/semantic-navigation/g4_topology.py'), 'down']]
        if owned:
            commands += [[OC, '-n', 'semantic-navigation', 'create', '-f', str(reservation)],
                         [OC, '-n', 'semantic-navigation', 'wait', 'pod/sam3-g0-rendering-reservation', '--for=condition=Ready', '--timeout=120s']]
        for command in commands:
            try:
                r = subprocess.run(command, text=True, capture_output=True, timeout=180)
                cleanup.append({'command': command, 'returncode': r.returncode, 'stderr': r.stderr})
            except Exception as error: cleanup.append({'command': command, 'returncode': -1, 'error': str(error)})
        report['cleanup'] = cleanup; report['cleanup_ok'] = all(x['returncode'] == 0 for x in cleanup)
        report['passed'] = report['passed'] and report['cleanup_ok']
        report['finished_at'] = datetime.now(timezone.utc).isoformat(); save('result.json', report)
    print(json.dumps(report)); return 0 if report['passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
