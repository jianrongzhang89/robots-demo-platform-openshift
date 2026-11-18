#!/bin/bash
# Stage 3A dataset sweep (runs inside the pinned pod).
# Scripted traversals: route x direction x payload x speed x stop-profile (72 runs).
# Navigation missions: route x direction x payload x speed (24 runs).
set +u
source /opt/ros/jazzy/setup.bash
source /opt/rmf_demos_ws/install/setup.bash
set -u
cd /work
SRC=/work/docs/validation/warehouse-energy/phase-0/baseline-20261116/phase8-multilevel-hotel.world
FIX=/work/config/warehouse-energy/fixture-v1.json
OUT=/work/stage3-raw
mkdir -p "$OUT"

for route in A B; do
  for direction in up down; do
    for payload in 0 0.25 0.5; do
      for speed in 0.06 0.08 0.10; do
        for stops in 0 1; do
          name="scripted-${route}-${direction}-p${payload}-v${speed}-s${stops}"
          if [ -d "$OUT/$name" ]; then echo "=== skip $name (exists)"; continue; fi
          echo "=== $name start $(date -u +%FT%TZ)"
          python3 scripts/warehouse-energy/stage3_trial.py --source "$SRC" \
            --output "$OUT/$name" --route "$route" --direction "$direction" \
            --payload "$payload" --speed "$speed" --stops "$stops" --hold 3.0 \
            > "$OUT/$name.log" 2>&1
          echo "=== $name exit=$? $(date -u +%FT%TZ)"
        done
      done
    done
  done
done

for route in A B; do
  for direction in up down; do
    for payload in 0 0.25 0.5; do
      for speed in 0.08 0.10; do
        name="nav-${route}-${direction}-p${payload}-v${speed}"
        if [ -d "$OUT/$name" ]; then echo "=== skip $name (exists)"; continue; fi
        echo "=== $name start $(date -u +%FT%TZ)"
        python3 scripts/warehouse-energy/run_stage3_nav.py --source "$SRC" \
          --fixture "$FIX" --output "$OUT/$name" --route "$route" \
          --direction "$direction" --payload "$payload" --speed "$speed" \
          > "$OUT/$name.log" 2>&1
        echo "=== $name exit=$? $(date -u +%FT%TZ)"
      done
    done
  done
done
echo "=== sweep complete $(date -u +%FT%TZ)"
