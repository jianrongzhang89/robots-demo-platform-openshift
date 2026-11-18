# Phase 0 simulation qualification evidence

Date: 2026-11-16. **PASS:** all 36 physical ramp trials, all four full-warehouse
route trials, and both independent audits. The top-level
[Phase 0 report](../phase-0-report.md) is the gate record.

| Artifact | Purpose |
| --- | --- |
| [ramp-summary.json](ramp-summary.json) | Worst-case physical metrics across the 36 independently reset traversals |
| [ramp-audit.json](ramp-audit.json) | Separate audit of raw pose/torque observations, physical mass, drive limits, route endpoints and slope holds |
| [ramp-matrix-result.json](ramp-matrix-result.json) | Per-trial live-runner results, including both directions and all three payloads |
| [ramp-evidence.tar.gz](ramp-evidence.tar.gz) | Complete generated worlds/meshes, pose and torque traces, logs and source hashes for all 36 trials |
| [development-attempts.md](development-attempts.md) | Failed, invalid and superseded attempts, retained separately from qualification counts |
| [development-attempts.tar.gz](development-attempts.tar.gz) | Raw development artifacts, including the full-world deck-overlap failure |
| [runtime-inventory.json](runtime-inventory.json) | Isolated pod identity and actual image digest |
| [local-tests.log](local-tests.log) | Geometry, mass, force-control, energy sanity and adversarial audit checks |
| [navigation-audit.json](navigation-audit.json) | Independent replay of accepted schedules, goal results, route geometry, physical endpoints and stopped wheels |
| [navigation-series-result.json](navigation-series-result.json) | Four completed RMF tasks in the corrected world |
| [navigation-evidence.tar.gz](navigation-evidence.tar.gz) | Complete final route-series worlds, maps, requests, schedules, poses, torque traces, logs and source hashes |
| [ramp-mesh-equivalence.sha256](ramp-mesh-equivalence.sha256) | Identical ramp meshes in isolated qualification and full-warehouse worlds |

The archive contains a `matrix-v1/` directory. Extract it into a new temporary
directory and replay the independent audit from the repository root:

```sh
python3 scripts/warehouse-energy/audit_qualification.py /tmp/warehouse-audit/matrix-v1 \
  --output /tmp/warehouse-audit/ramp-audit.json
```

Force observations are simulator **actuator command torques**, paired with joint
velocity. They are neither battery-terminal measurements nor calibrated energy
labels. Payloads are physical SDF links with mass/inertia, and trajectories come
from Gazebo full-pose messages. Qualification applies to the frozen simulation
fixture only. The nominal 10× ramp / 3× route simulation speed targets affect
wall-clock duration, not the 0.10 m/s physical velocity or simulated timestamps.

The final route evidence includes both submitted RMF itineraries and the schedule
server's returned mirror updates. Ordered Nav2 goal results and physical waypoint
crossings must agree with the selected route. Each task starts from a fresh
world and schedule database, and each launcher stops its process groups at exit.
The pod can remain Ready while idle; this is not evidence that a background trial
is still executing.
