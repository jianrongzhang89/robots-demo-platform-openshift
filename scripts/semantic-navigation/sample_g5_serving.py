#!/usr/bin/env python3
"""Bounded authenticated G5 samples during stopped replay; no inference requests."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=300)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 3600:
        raise ValueError('sample duration must be 1..3600 seconds')
    code = ('import ssl,json,urllib.request; c=ssl.create_default_context(cafile="/cert/ca.crt"); '
            'c.load_cert_chain("/cert/tls.crt","/cert/tls.key"); '
            'u="https://sam3-mat-v1-tls.semantic-model-serving.svc:8443"; '
            'print(json.dumps({"metadata":json.load(urllib.request.urlopen(u+"/v1/models/sam3-mat-v1",context=c,timeout=3)),'
            '"metrics":urllib.request.urlopen(u+"/metrics",context=c,timeout=3).read().decode()}))')
    end = time.monotonic() + args.seconds
    with args.output.open('x') as handle:
        while time.monotonic() < end:
            sample = {'recorded_at': datetime.now(timezone.utc).isoformat(), 'navigation': 'UNAVAILABLE: stopped replay, no ROS fixture'}
            try:
                r = subprocess.run(['oc', '--request-timeout=10s', 'exec', '-n', 'semantic-navigation',
                    'sam3-g5-client', '--', '/opt/sam3-venv/bin/python', '-c', code],
                    capture_output=True, text=True, timeout=15)
                if r.returncode:
                    sample['status'] = 'UNAVAILABLE'; sample['error'] = r.stderr
                else:
                    sample.update(json.loads(r.stdout)); sample['status'] = 'AVAILABLE'
            except (subprocess.SubprocessError, ValueError) as error:
                sample['status'] = 'UNAVAILABLE'; sample['error'] = str(error)
            handle.write(json.dumps(sample) + '\n'); handle.flush()
            time.sleep(min(5, max(0, end-time.monotonic())))


if __name__ == '__main__':
    main()
