#!/usr/bin/env python3
"""One isolated G4 serving-unavailable pilot for the lease-evidence transport fix.

Provisions a fresh short-lived loopback proxy certificate/secret, starts the
read-only serving sampler with its own stop file, runs a single serving fault
trial through the unchanged qualification runner (run_g4_faults.py), and always
removes the G4 topology and certificate and restores the A10G rendering
reservation. No acceptance criterion, deadline, watchdog or threshold changes:
the candidate only shortens the renewed semantic lease's path from the
observation worker's status file to the supervisor's gate poll.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from g4_topology import ROOT, OC

SECRET = 'semantic-g4-proxy-tls'
RESERVATION_POD = 'sam3-g0-rendering-reservation'


def sh(*args, cwd=None, check=True):
    return subprocess.run(list(args), text=True, capture_output=True, check=check, cwd=cwd)


def oc(*args, check=True, obj=None, timeout=180):
    return subprocess.run([OC, '-n', 'semantic-navigation', *args],
                          input=json.dumps(obj) if obj else None, text=True,
                          capture_output=True, check=check, timeout=timeout)


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def pod_ready(name):
    state = json.loads(oc('get', 'pod', name, '-o', 'json', check=False).stdout or '{}')
    return (state.get('status', {}).get('phase') == 'Running'
            and all(c.get('ready') for c in state.get('status', {}).get('containerStatuses', [])))


def model_serving_healthy(events):
    pods = json.loads(oc('get', 'pods', '-n', 'semantic-model-serving',
                         '-l', 'serving.kserve.io/inferenceservice=sam3-mat-v1',
                         '-o', 'json').stdout)['items']
    running = [p for p in pods if p.get('status', {}).get('phase') == 'Running'
               and all(c.get('ready') for c in p.get('status', {}).get('containerStatuses', []))]
    events.append({'event': 'model_serving_preflight', 'running_ready': len(running)})
    if len(running) != 1:
        raise RuntimeError('expected exactly one ready model serving pod')


def provision_certificate(events):
    """Fresh short-lived self-signed localhost certificate; key never retained."""
    directory = tempfile.mkdtemp(prefix='g4-proxy-tls-')
    cert, key = Path(directory) / 'tls.crt', Path(directory) / 'tls.key'
    sh('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
       '-keyout', str(key), '-out', str(cert), '-days', '3',
       '-subj', '/CN=localhost',
       '-addext', 'subjectAltName=DNS:localhost,IP:127.0.0.1')
    result = oc('create', 'secret', 'tls', SECRET,
                f'--cert={cert}', f'--key={key}')
    events.append({'event': 'proxy_certificate_provisioned', 'returncode': result.returncode,
                   'metadata': sh('openssl', 'x509', '-in', str(cert), '-noout',
                                  '-subject', '-issuer', '-dates', '-fingerprint', '-sha256').stdout,
                   'key_retained': False})
    key.unlink(); cert.unlink(); os.rmdir(directory)
    if result.returncode:
        raise RuntimeError('proxy certificate secret creation failed')


def lease_margins(trial):
    """Observer-side renewal margins against each lease's capture-age deadline."""
    path = trial / 'observer-timing.jsonl'
    if not path.exists():
        return None
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    margins = []
    for previous, current in zip(rows, rows[1:]):
        deadline = previous['capture_wall_ns'] + 498_000_000
        margins.append((deadline - current['observer_wall_ns']) / 1e6)
    ordered = sorted(margins)
    return {'results': len(rows),
            'margin_min_ms': min(margins) if margins else None,
            'margin_p10_ms': ordered[len(ordered) // 10] if margins else None,
            'margin_median_ms': ordered[len(ordered) // 2] if margins else None,
            'negative_margins': sum(1 for m in margins if m < 0),
            'margins_below_30ms': sum(1 for m in margins if m < 30)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--reservation', type=Path, required=True,
                        help='saved rendering reservation Pod manifest to restore')
    parser.add_argument('--mode', default='serving',
                        choices=('serving', 'network', 'auth', 'overload', 'hang', 'wrong_version'),
                        help='served fault mode for the single trial')
    parser.add_argument('--gate', choices=('observation', 'recovery', 'stop'),
                        help='run one Phase 5 gate trial through run_g4_phase5.py instead of a fault trial')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    events = []
    sampler = None
    stop_file = args.output_dir / 'monitor-stop'
    passed = False
    try:
        # Preflight: clean namespace, reservation Ready, model serving healthy.
        for kind, name in (('pod', 'semantic-phase5-native'), ('configmap', 'semantic-phase5-native'),
                           ('pod', 'semantic-g4-sam3'), ('deployment', 'semantic-g4-sam3-router'),
                           ('secret', SECRET)):
            if oc('get', kind, name, '--ignore-not-found', '-o', 'name', check=False).stdout.strip():
                raise RuntimeError(f'refusing to start: {kind}/{name} already exists')
        if not pod_ready(RESERVATION_POD):
            raise RuntimeError('rendering reservation is not Ready')
        if not args.reservation.is_file():
            raise RuntimeError('saved reservation manifest missing')
        model_serving_healthy(events)
        write(args.output_dir / 'preflight.json', events)

        # Free the A10G for the fixture's GPU rendering placement.
        oc('delete', 'pod', RESERVATION_POD, '--wait=true', '--timeout=120s')
        events.append({'event': 'rendering_reservation_removed'})

        if args.gate:
            # Phase 5 gate trials use configure(False): no fault proxy and
            # therefore no certificate is needed.
            command = [sys.executable, str(ROOT / 'scripts/semantic-navigation/run_g4_phase5.py'),
                       '--gate', args.gate, '--repetitions', '1',
                       '--output-dir', str(args.output_dir / 'gate')]
        else:
            provision_certificate(events)
            command = [sys.executable, str(ROOT / 'scripts/semantic-navigation/run_g4_faults.py'),
                       '--modes', args.mode, '--repetitions', '1',
                       '--output-dir', str(args.output_dir / 'serving-faults')]
        sampler = subprocess.Popen([sys.executable,
                                    str(ROOT / 'scripts/semantic-navigation/sample_g4_serving.py'),
                                    '--oc', OC, '--output', str(args.output_dir / 'serving-resources.jsonl'),
                                    '--stop-file', str(stop_file)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        events.append({'event': 'sampler_started', 'stop_file': str(stop_file)})
        events.append({'event': 'runner_started', 'command': command})
        with (args.output_dir / 'runner.log').open('w') as log:
            runner = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        events.append({'event': 'runner_finished', 'returncode': runner.returncode})
        summary_path = ((args.output_dir / 'gate') if args.gate
                        else args.output_dir / 'serving-faults') / 'summary.json'
        summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
        passed = runner.returncode == 0 and summary.get('passed') is True
        trial_dirs = sorted(((args.output_dir / 'gate') if args.gate
                              else args.output_dir / 'serving-faults').glob('trial-*'))
        analysis = {'summary': summary,
                    'lease_margins': {d.name: lease_margins(d) for d in trial_dirs}}
        write(args.output_dir / 'analysis.json', analysis)
    finally:
        cleanup = []
        if sampler is not None:
            stop_file.touch()
            try:
                sampler.wait(timeout=90)
            except subprocess.TimeoutExpired:
                sampler.terminate()
                sampler.wait(timeout=10)
            cleanup.append({'action': 'stop serving sampler', 'returncode': 0,
                            'stopped': True})
        result = subprocess.run([sys.executable,
                                 str(ROOT / 'scripts/semantic-navigation/g4_topology.py'), 'down'],
                                capture_output=True, text=True)
        cleanup.append({'action': 'remove G4 topology', 'returncode': result.returncode,
                        'stdout': result.stdout, 'stderr': result.stderr})
        result = oc('delete', 'secret', SECRET, '--ignore-not-found', check=False)
        cleanup.append({'action': 'remove fault injector certificate', 'returncode': result.returncode})
        if oc('get', 'pod', RESERVATION_POD, '--ignore-not-found', '-o', 'name',
              check=False).stdout.strip():
            result = oc('delete', 'pod', RESERVATION_POD, '--ignore-not-found',
                        '--wait=true', '--timeout=60s', check=False)
            cleanup.append({'action': 'remove leftover reservation before restore',
                            'returncode': result.returncode})
        result = oc('create', '-f', str(args.reservation), check=False)
        cleanup.append({'action': 'restore rendering reservation',
                        'returncode': result.returncode, 'stderr': result.stderr})
        result = oc('wait', f'pod/{RESERVATION_POD}', '--for=condition=Ready',
                    '--timeout=120s', check=False)
        cleanup.append({'action': 'reservation Ready', 'returncode': result.returncode})
        write(args.output_dir / 'cleanup.json', cleanup)
        write(args.output_dir / 'events.json', events)
        write(args.output_dir / 'result.json',
              {'pilot': 'serving-unavailable lease-transport fix',
               'passed': passed and all(x['returncode'] == 0 for x in cleanup),
               'trial_passed': passed, 'cleanup_ok': all(x['returncode'] == 0 for x in cleanup),
               'events': events, 'cleanup': cleanup})
        print(json.dumps({'passed': passed,
                          'cleanup_ok': all(x['returncode'] == 0 for x in cleanup)}), flush=True)


if __name__ == '__main__':
    main()
