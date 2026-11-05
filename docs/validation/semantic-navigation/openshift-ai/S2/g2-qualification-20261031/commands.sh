#!/bin/sh
# Run from repository root with oc authenticated. Evidence files omit credentials.
# Build was semantic-cpu-adapter-s2-1; do not replace the pinned deployed image implicitly.
python3 - <<'PY'
from pathlib import Path
import tarfile
with tarfile.open('/tmp/g2-build-context.tar', 'w') as archive:
    root = Path('apps/semantic-perception')
    for path in sorted(root.rglob('*.py')):
        if '__pycache__' not in path.parts:
            archive.add(path, arcname=str(path))
    archive.add(root / 'Containerfile.cpu', arcname=str(root / 'Containerfile.cpu'))
PY
oc apply -f helm/semantic-navigation/openshift-ai/adapter-build.yaml
oc start-build semantic-cpu-adapter-s2 -n semantic-navigation --from-archive=/tmp/g2-build-context.tar
# Wait for Complete and retain logs; renderer pins the originally qualified digest.
python3 helm/semantic-navigation/openshift-ai/render_adapter.py \
  --identity docs/validation/semantic-navigation/openshift-ai/S1/g1-qualification-20261031/expected-identity.json \
  --node ip-10-0-53-174.ec2.internal > /tmp/g2-adapter.json
oc apply --dry-run=server -f /tmp/g2-adapter.json
oc apply -f /tmp/g2-adapter.json
# Wait for Running and "Backend initialized" in logs. Idle readiness stays false.
oc cp scripts/semantic-navigation/qualify_ros_adapter.py semantic-navigation/semantic-s2-adapter:/tmp/qualify_ros_adapter.py
oc cp docs/validation/semantic-navigation/openshift-ai/S1/g1-qualification-20261031/frozen semantic-navigation/semantic-s2-adapter:/tmp/frozen
oc exec -n semantic-navigation semantic-s2-adapter -- bash -ec 'source /opt/ros/jazzy/setup.bash; python3 /tmp/qualify_ros_adapter.py --frozen /tmp/frozen --output /tmp/g2-live-1.json'
oc cp semantic-navigation/semantic-s2-adapter:/tmp/g2-live-1.json /tmp/g2-live-1.json
oc exec -n semantic-navigation semantic-s2-adapter -- bash -ec 'source /opt/ros/jazzy/setup.bash; export ROS_DOMAIN_ID=189; cd /opt/semantic-perception; python3 -m unittest discover -s tests_ros -v'
