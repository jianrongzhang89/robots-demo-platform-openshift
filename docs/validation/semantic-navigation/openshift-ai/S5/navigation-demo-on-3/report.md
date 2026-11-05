# Served navigation rerun — November 4, 2026

Demo PASS; cleanup PASS. After the user's fresh “go”, Nav2 reported
`goal_succeeded`, the robot stopped, and the contact audit found no unexpected
contacts. This is a presentation run, not a new G4 or G5 qualification.

The accepted OpenShift AI served SAM3 endpoint supplied the global lethal-254
semantic costmap. Capture-age p95 was 250.267 ms (limit 500 ms), with 7.065
observations/s. No native clock fault was recorded.

Physical path length was 4.929 m; mat hull exposure was zero and minimum hull
clearance was 0.146 m using a 0.246 m radius. Physical goal offset was **0.812 m**
despite belief-to-goal distance 0.043 m; belief/truth divergence was 0.772 m.

The user observed the smaller qualification mat and choppy noVNC motion.
Both are being corrected separately; these original run artifacts stay unchanged.
See `demo-summary.json`, `result.json`, and the retained trial evidence.
