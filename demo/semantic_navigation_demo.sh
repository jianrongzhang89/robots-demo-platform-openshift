#!/usr/bin/env bash
# Semantic-navigation demo on the Phase 6 QUALIFIED fixture configuration
# (series-23, signed off October 30, 2026 — see
# docs/validation/semantic-navigation/phase-6/sign-off-review-20261030.md).
#
# Three acts, each a full fixture trial (~9-11 min):
#   baseline  off-arm:  the robot drives its route straight across the red mat
#   semantic  on-arm:   SAM3 sees the mat from the prompt "red mat", the
#                       semantic costmap marks it, and the robot detours
#                       around it completely (lethal-cost exclusion arm)
#   faultstop on-arm:   the camera path is cut mid-route and the guarded
#                       chain stops the robot fail-closed
#
# Usage:
#   demo/semantic_navigation_demo.sh [all|baseline|semantic|faultstop]
#   demo/semantic_navigation_demo.sh --take-over-gpu ...   # delete the
#       standalone demo's SAM3 pod first (it shares the fixture SAM3 node's
#       single GPU; see demo/semantic-navigation-demo.md)
#
# Output: docs/validation/semantic-navigation/phase-6/demo-runs-<timestamp>/
# Demo evidence, not qualification evidence (same runner, same checks, but
# runs outside a series plan).
set -euo pipefail

OC=/Users/zhangj/bin/oc
NS=semantic-navigation
GPU_NODE=ip-10-0-44-146.ec2.internal
IMAGE=image-registry.openshift-image-registry.svc:5000/semantic-navigation/semantic-safety@sha256:348fc584e70b07c6f73f9e428623240da5fc4c81ead630f0cb051c18de2d4371
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ACT="${ACT:-all}"
if [[ "${1:-}" == "--take-over-gpu" ]]; then TAKE_OVER_GPU=1; shift; fi
[[ -n "${1:-}" ]] && ACT="$1"

OUT="$ROOT/docs/validation/semantic-navigation/phase-6/demo-runs-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"

run_act () {  # name arm extra-args...
  local name="$1"; shift
  local arm="$1"; shift
  echo "==================================================================="
  echo "ACT: $name (${arm}-arm) — evidence: $OUT/$name"
  echo "==================================================================="
  python3 "$ROOT/scripts/semantic-navigation/run_phase5_native.py" \
    --oc "$OC" --suite hotel-guarded --contact-audit --sam3-observation \
    --semantic-arm "$arm" --phase6-tf-witness --controller-endpoint-capture \
    --console-only-server --rear-casters \
    --physics-step 0.002 --lidar-range 12 --odom-frequency 200 \
    --gpu-rendering --node-name "$GPU_NODE" --image "$IMAGE" \
    --output-dir "$OUT/$name" "$@" || echo "  (act ended with a failure — see summary)"
  python3 "$ROOT/demo/semantic_demo_summary.py" "$OUT/$name"
  echo
}

# ---- Preflight -----------------------------------------------------------
echo "Preflight:"
if [[ -n "${TAKE_OVER_GPU:-}" ]]; then
  echo "  --take-over-gpu: deleting the standalone demo SAM3 pod to free the GPU"
  $OC -n "$NS" delete pod semantic-phase6-sam3 --ignore-not-found=true --wait=true --timeout=120s || true
fi
if $OC -n "$NS" get pod semantic-phase6-sam3 >/dev/null 2>&1; then
  echo "  ERROR: the standalone demo SAM3 pod (semantic-phase6-sam3) holds the"
  echo "  fixture SAM3 node's only GPU. Re-run with --take-over-gpu to delete it"
  echo "  for the demo window (restore per demo/semantic-navigation-demo.md)."
  exit 1
fi
gpu_alloc=$($OC -n "$NS" describe node "$GPU_NODE" | awk '/Allocated resources/,/^$/' | grep nvidia || true)
echo "  fixture GPU node $GPU_NODE nvidia allocation: ${gpu_alloc:-none}"
sam3=$($OC -n "$NS" get pod semantic-phase5-sam3 -o 'jsonpath={.status.phase} {.status.containerStatuses[*].ready}' 2>/dev/null || echo "missing")
echo "  fixture SAM3 pod: $sam3"
if [[ "$sam3" != "Running true true" ]]; then
  if [[ ! -f /tmp/sam3-pod-r3.json ]]; then
    echo "  ERROR: fixture SAM3 pod is $sam3 and /tmp/sam3-pod-r3.json is absent;"
    echo "  recreate the topology with scripts/semantic-navigation/phase6_topology.py"
    exit 1
  fi
  echo "  recycling the fixture SAM3 topology..."
  (cd "$ROOT/scripts/semantic-navigation" && python3 -c \
    "from phase6_trial import recycle_topology; recycle_topology()")
fi
echo

case "$ACT" in
  baseline) run_act baseline off ;;
  semantic) run_act semantic on --phase6-lethal ;;
  faultstop) run_act faultstop on --phase6-lethal --semantic-fault-probe --semantic-fault-mode camera_path_loss ;;
  all)
    run_act baseline off
    run_act semantic on --phase6-lethal
    run_act faultstop on --phase6-lethal --semantic-fault-probe --semantic-fault-mode camera_path_loss
    echo "Demo complete. Contrast: baseline drives across the mat (exposure"
    echo "~1.4 m); semantic detours around it (exposure 0.000 m); faultstop"
    echo "halts the robot when perception is lost."
    ;;
  *) echo "usage: $0 [all|baseline|semantic|faultstop] [--take-over-gpu]"; exit 2 ;;
esac
