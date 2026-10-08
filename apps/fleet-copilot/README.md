# Fleet Copilot Phase 1

This is the interpretation-only milestone for U1. It turns supported English
requests into a validated hotel patrol preview. It does not publish ROS/RMF
messages, persist missions, or expose a Dispatch operation.

## Run locally

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e 'apps/fleet-copilot[dev]'
python -m pytest apps/fleet-copilot/tests -q
python apps/fleet-copilot/evaluation/run.py
uvicorn copilot.api:app --app-dir apps/fleet-copilot --reload
```

Open `http://127.0.0.1:8000/` for the preview UI. Without
`OPENAI_API_KEY`, the API uses the deterministic mock provider. With a key, it
uses the external structured-output adapter; either path remains preview-only.

## Deploy to OpenShift

The phase-1 preview can be built as an OpenShift binary Docker build and
deployed without ROS/RMF access:

```bash
oc apply -n ros2-rmf-hotel -f openshift/fleet-copilot-phase1.yaml
oc start-build fleet-copilot -n ros2-rmf-hotel --from-dir=apps/fleet-copilot --follow
oc rollout status deployment/fleet-copilot -n ros2-rmf-hotel --timeout=180s
oc get route fleet-copilot -n ros2-rmf-hotel
```

Phase 0 is not accepted yet, so this package intentionally has no RMF bridge
or live dispatch integration. Phase 1 evaluation is limited to semantic intent
and safety behavior.
