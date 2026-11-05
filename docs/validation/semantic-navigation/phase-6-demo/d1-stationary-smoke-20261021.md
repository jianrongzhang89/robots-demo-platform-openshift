# Phase 6D D1 — stationary perception-to-costmap smoke

Date: October 21, 2026  
Status: **DEMO PASS — stationary semantic insertion, target-removal clearing, inference-loss expiry, and recovery were verified in both costmaps.**  
Motion: **none** — no goal sent; no command bridge attached.

## Deployed isolated profile

- Namespace: `semantic-navigation`; separate Gazebo partition
  `semantic_navigation_phase6_demo` and private router `semantic-phase6-router`.
- One simulator/`robot_1`, one GPU SAM3 pod, one Nav2 pod. The canonical
  `ros2-rmf-hotel` deployments and existing Phase 1 semantic deployment were
  not changed.
- Current workload manifest:
  [`phase6-demo-d1.yaml`](../../../../helm/semantic-navigation/phase6-demo-d1.yaml),
  rendered with
  [`render_phase6_demo_d1.py`](../../../../scripts/semantic-navigation/render_phase6_demo_d1.py).
- Router/topic config:
  [`phase6-demo-topic-bridges.yaml`](../../../../helm/semantic-navigation/phase6-demo-topic-bridges.yaml).
- SAM3 is pinned to the Phase 4 payload-bound runtime
  `sam3-runtime@sha256:478ec01a7a47fbb0c862fbbef495c71b4a512ff59ed8d6ed5b7234422cc35686`,
  with the approved checkpoint revision/hash and prompt `red mat`.
- Simulator/compressor use the trace-instrumented Phase 4 images:
  `semantic-hotel-sim@sha256:d417c9f252d1f89dd859290a4bca1f634bcfd7d3cde6d1702c409d432bd48894`
  and `semantic-hotel-sim@sha256:c3ba94bbcbbe2283f1c46ea0f2baba398da313ffe83d2b59a63272ef91d95ebf`.
- D1-specific simulator bridge has no subscribers. The three Nav2 bridges have
  empty publisher allowlists. The separately gated motion bridge is not mounted.

## Checks that pass so far

- All three isolated pods and the private router are running; Nav2 lifecycle
  servers are active.
- Nav2 receives `/clock`, `/odom`, `/scan`, `/tf`, `/tf_static`, and
  `/robot_1/semantic/{mask,points,timing,label_info}`. Each of the two costmap
  nodes reports subscriptions to all four semantic topics.
- `map → camera_color_optical_frame` TF was available. The Nav2 map is 693×845
  at 0.05 m resolution with origin `(0, -42.25)`; the robot's current map pose
  `(15.402, -31.594)` lies inside it.
- A matched live SAM3 mask/cloud/timing sample had 640×480 dimensions, mask
  encoding `mono8` with labels `{0,2}`, expected XYZ `PointCloud2` layout and
  frame `camera_color_optical_frame`, valid label metadata, and matching
  `mask_sha256`/`cloud_sha256`. One sample's conservative wall age was 293.87 ms
  and simulation age was 260 ms, both below the configured 500 ms admission age.
- SAM3 runtime logs show repeated `valid_result` records (about 116–122 ms
  inference in sampled lines); drops are nonzero under the current camera rate.
- The first diagnostic Nav2 build (digest
  `semantic-nav2@sha256:5d80c9af5d3c8487eaf49f6d23ac37762212d4a5ec9f1157276eb404d6bc721d`)
  reports accepted observations in both layers, with projected-cell counts of
  156 local and 271 global in sampled logs. Some samples are rejected as
  `stale_or_wrong_identity`, while fresh samples continue to be accepted.
- Over a 10-second Gazebo stats sample, mean real-time factor was 0.996
  (minimum 0.623, maximum 1.869; 95 samples). A `oc adm top pods` sample showed
  simulator 11,486m CPU / 2,250 MiB, SAM3 998m / 1,556 MiB, and Nav2 964m /
  368 MiB. These are single-window observations, not resource qualification.
- The candidate Nav2 pod was recreated once after fixing shell startup and
  mounting CycloneDDS config in both ROS adapters. These were packaging fixes,
  not navigation changes.

## Current blocker

An initial check of the latched full-map topics appeared to show no semantic
cells. The cause was that `/costmap_raw` publishes a full snapshot that was not
updated in the late subscriber's sample; the live incremental
`/costmap_raw_updates` topics carry the current map deltas. D1 evidence now
confirms SAM3 changes both costmaps: one matched update contained 156 cost-200
local cells and 271 cost-200 global cells. The second diagnostic build reported
the same counts as marked and merged, with zero master-unknown skips.

The corresponding static-map region around the target is known free (247/247
sampled cells were occupancy value 0). The simulator's isolated
`semantic_target_mat` was then removed through Gazebo's `/world/sim_world/remove`
service (`data: true`). Across 68 subsequent mask samples, SAM3 returned zero
target pixels; all nine observed local and global incremental costmap updates
had zero cost-200 cells. The plugin then reported `projected_cells=0` and
`stored_cells=0` for both layers. Target-removal clearing passed.

### Inference-loss expiry and recovery

After restoring the isolated target and confirming cost-200 cells in both
layers, a live ROS `CostmapUpdate` subscriber monitored each semantic-layer raw
update stream. Only the `sam3-inference` container's PID 1 was terminated; its
Zenoh bridge, simulator, and Nav2 stayed running. The subscriber observed the
cost-200 count transition from 271 global / 156 local cells to zero in both
maps about 1.2 seconds after the last positive update, consistent with the
configured 1.0-second capture-based observation lifetime plus costmap update
cadence. The inference container restarted, emitted fresh `valid_result`
records, and both update streams returned to 271 global / 156 local cells.
No robot motion or Nav2 goal was issued during this fault test.

OpenShift build `semantic-nav2-phase6-plugin-4` completed successfully and
produced `semantic-nav2@sha256:5d80c9af5d3c8487eaf49f6d23ac37762212d4a5ec9f1157276eb404d6bc721d`.
It adds rate-limited accept/reject reason and projected-cell counts to candidate
plugin logs without changing admission or cost policy. That image is deployed
in the isolated Nav2 pod. Build `semantic-nav2-phase6-plugin-5` completed; it
adds `updateCosts` merge counters only and produced
`semantic-nav2@sha256:d23d20a8decdd9a6cc0f9419874c1b610333e033867e579aeb022a5bb1b97b0e`.
Do not relax freshness, digest,
identity, TF, height, range, or unknown-space rules to force a visual result.
The candidate remains stationary and disconnected from simulator command
input. In sampled accepted records, simulation age ranged 210–440 ms and wall
age 235–447 ms, within the configured 500 ms limit but with limited margin at
the upper end.

## Startup discrepancies found before any motion

1. The D0 draft's earlier SAM3 pin predated payload hashes required by the
   plugin. It was corrected to the Phase 4 payload-bound image before accepting
   any output.
2. The initial D1 simulator pin lacked the capture-trace library. SAM3 emitted
   `capture trace/calibration timing missing`; no inference was admitted. D1
   switched to the Phase 4 trace-enabled simulator/compressor pair and enabled
   both trace flags.
3. The first Nav2 pod failed because Bash `nounset` conflicted with ROS setup,
   and the odom/scan adapters lacked the mounted CycloneDDS config. Both were
   corrected before the current live test.

## Gate decision and limits

D1 is **DEMO PASS** for the stationary perception-to-costmap smoke test. Fresh
SAM3 semantics were accepted and merged into both costmaps; removing the target
and interrupting inference both cleared the semantic cells, and inference
recovery restored them. This is not a recognition-quality, navigation-benefit,
safety, or Phase 5 qualification. The sampled compute/RTF values above are
observations only. The existing inflation-radius warning (0.200 m below the
computed 0.225 m inscribed radius) remains unresolved and must be visible in
the D2 demo assessment.

D2 is a separate gated paired-navigation comparison. Review this D1 evidence,
keep the Nav2 command bridge disconnected until the D2-specific profile is
explicitly enabled, and preserve the canonical deployment unchanged.
