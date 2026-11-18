#!/bin/bash
# Stage 2 physics-routing trial series (runs inside the pinned pod).
set +u
source /opt/ros/jazzy/setup.bash
source /opt/rmf_demos_ws/install/setup.bash
set -u
cd /work
SRC=/work/docs/validation/warehouse-energy/phase-0/baseline-20261116/phase8-multilevel-hotel.world
FIX=/work/config/warehouse-energy/fixture-v1.json
MODEL=/work/config/warehouse-energy/physics-model-v1.json
OUT=/work/stage2-series
mkdir -p "$OUT"
run() {
  name=$1; shift
  if [ -d "$OUT/$name" ]; then echo "=== skip $name (exists)"; return; fi
  echo "=== $name start $(date -u +%FT%TZ)"
  python3 scripts/warehouse-energy/run_stage2_trial.py --source "$SRC" --fixture "$FIX" \
    --physics-model "$MODEL" --output "$OUT/$name" "$@" > "$OUT/$name.log" 2>&1
  echo "=== $name exit=$? $(date -u +%FT%TZ)"
}
run rejected-low-soc --arm B --initial-soc 0.22
run armA-r1 --arm A
run armA-r2 --arm A
run armA-r3 --arm A
run armB-r1 --arm B
run armB-r2 --arm B
run armB-r3 --arm B
run armB-excluded-A-r1 --arm B --exclude-route A
echo "=== series complete $(date -u +%FT%TZ)"
