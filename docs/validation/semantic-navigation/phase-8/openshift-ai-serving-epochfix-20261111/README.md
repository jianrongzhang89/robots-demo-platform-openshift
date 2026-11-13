# Phase 8 OpenShift AI served SAM3 navigation — PASS

Phase 8 now obtains SAM3 inference from the OpenShift AI KServe service
`sam3-mat-v1`. Its ROS client runs separately on the existing camera bridge
domain, sends bounded requests over mutual TLS, verifies the pinned served
deployment identity, and republishes the semantic ROS topics consumed by Nav2.
The local SAM3 inference pod is stopped while this topology runs and is saved
for restoration.

The OpenShift AI path passed stationary preflight and a full moving OpenRMF
navigation run. During the 83-second costmap-monitor window, the served ROS
adapter log recorded 509 valid SAM3 results; its final status showed 3,779
emitted results and a fresh, ready HTTP backend. The adapter initialized with the pinned served identity,
produced SAM3 results, and Nav2 accepted the epoch-bound label policy and
semantic observations. During the moving run the semantic layer was armed and
the global costmap recorded 1,089 lethal cost-254 cells. OpenRMF task
`compose.dispatch-a294b01aee` completed after Nav2 returned SUCCEEDED (4). The
run took 82.61 seconds; the measured robot hull stayed at least 0.8107 m from
the mat, and monitored global plans stayed at least 0.6215 m clear. There was
no mat overlap, collision-monitor event, speed-cap breach, or clearance breach.
The fleet returned to idle and the robot stopped at map pose
`(19.4298, -31.4171)` with zero measured twist.

The stationary preflight had 957 lethal cost-254 cells and a planned hull
clearance of 0.6167 m. The noVNC route returned HTTP 200. This end-to-end run
confirms that Nav2's successful route used semantic costs populated from the
OpenShift AI served SAM3 results, rather than the local Phase 6 inference pod.

The first served-adapter attempt exposed an interface-version mismatch: the
qualified HTTP client image published label metadata without `stream_epoch`,
which the Phase 6 costmap requires. `phase8_sam3_http_policy.py` now publishes
the adapter's actual stream epoch and policy generation in the established
label schema. SAM3 responses, masks, point clouds, and capture times remain
unchanged. The next preflight confirmed 220-byte valid label metadata and
accepted observations in the global costmap.

Evidence: [full navigation summary](semantic-navigation-summary.json),
[full plans and trajectory](semantic-navigation.json),
[stopped pose](stopped-pose.yaml),
[stationary preflight summary](openshift-ai-preflight-summary.json),
[full stationary preflight](nav2-semantic-path-preflight.json),
[served deployment identity](openshift-ai-serving-identity.json),
[final adapter status](phase8-serving-adapter-final-status.json),
[served inference log](phase8-serving-adapter-final.log),
[adapter pod specification](phase8-serving-adapter-pod.json),
[Nav2 costmap log](nav2-preflight.log), [served adapter log](phase8-serving-adapter.log),
[RMF adapter idle log](rmf-adapter-idle.log), and
[staged physical pose](staged-ground-truth.yaml).

The isolated Phase 8 topology remains running at the staged start for noVNC
review. To restore the saved Phase 6 topology after review, run:

```sh
python3 scripts/semantic-navigation/phase8_topology.py down \
  --evidence-dir docs/validation/semantic-navigation/phase-8/openshift-ai-serving-epochfix-20261111
```
