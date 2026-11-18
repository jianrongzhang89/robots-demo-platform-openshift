# Warehouse Phase 0/1 qualification tools

These tools qualify a **simulation-only**, surveyed, empty two-ramp fixture.
Phase 0 established motion and route evidence. Phase 1 added an RGB-D stream,
an explicitly assumed modeled-energy/SOC trace, and a bounded SAM3 semantic
avoidance qualification across all four route/direction combinations at
320×240. Stage 2 adds the calibrated planning physics model, the pre-dispatch
route selector with reserve/deadline gates, and the arm A/B routing trials.
None of this calibrates electrical Wh against a physical robot, qualifies
other objects, trains a learned model, or operates hardware. The hotel
baseline is unchanged. The current Phase 1
gate is accepted: see
`docs/validation/warehouse-energy/phase-1/phase-1-report.md` and
`gate-result.json` for the accepted evidence, the passed semantic
repeatability series, and the remaining 640×480 resolution work. The
repeated-run series (original plus amended-B) and its cross-run audit are in
`docs/validation/warehouse-energy/phase-1/sam3-repeatability/` and
`docs/validation/warehouse-energy/phase-1/sam3-repeatability-b-amended/`
(`audit_semantic_repeatability.py`, which merges multiple series directories
with later directories overriding trial names).

## Runtime isolation

`config/warehouse-energy/qualification-pod.yaml` pins the accepted hotel runtime
image in namespace `warehouse-energy`. Physics trials use one Gazebo partition
per payload group. Navigation trials use partition `warehouse_navigation_trial`
and ROS domain 85; the existing hotel uses a different namespace/domain/partition.
No transport bridge connects these experiments to the hotel.

Create the namespace and grant its default service account image-pull permission
on `semantic-navigation`, then apply the pod manifest. Copy this script directory,
`scripts/local_nav2_fleet_adapter{,_contract}.py`, the fixture configs, and the
captured `phase8-multilevel-hotel.world` under their repository-relative paths
inside `/work`. The simulator contains no credentials; use the existing cluster
login for `oc`.

Compile the observation-only plugin inside the pinned pod:

```sh
g++ -std=c++17 -shared -fPIC /work/scripts/warehouse-energy/WarehouseTelemetry.cc \
  -o /work/libWarehouseTelemetry.so \
  $(pkg-config --cflags --libs gz-sim8 gz-plugin2-register)
```

The observer samples joint force commands **before** the physics step, after the
two force-mode JointControllers. PostUpdate force reads are invalid because the
physics system clears the command components. It does not issue motor commands.
Phase 1 also writes `energy.csv`: positive wheel mechanical power is divided by
the assumed 0.60 drive efficiency, then the assumed 10 W auxiliary load is
added. This is integrated in simulation time and converted to Wh; SOC uses the
assumed 24 Wh battery and 80% starting charge. Negative wheel power receives no
regeneration credit. These values are sensitivity-design assumptions, not
measured or calibrated robot parameters. See
`config/warehouse-energy/phase1-telemetry-v1.json`.
The generated SDF removes DiffDrive, bounds each wheel controller to ±0.080 Nm,
uses 8 rad/s joint limits and 0.001 Nm joint friction, and adds real payload mass,
inertia, collision geometry and a fixed attachment. These are declared simulator
design parameters, not hardware ratings.

## Execute and audit

Inside the pod after sourcing `/opt/ros/jazzy/setup.bash` and
`/opt/rmf_demos_ws/install/setup.bash`:

```sh
python3 /work/scripts/warehouse-energy/run_matrix.py \
  --source /work/docs/validation/warehouse-energy/phase-0/baseline-20261116/phase8-multilevel-hotel.world \
  --output /work/new-ramp-matrix
python3 /work/scripts/warehouse-energy/audit_qualification.py /work/new-ramp-matrix \
  --output /work/new-ramp-matrix/independent-audit.json
python3 /work/scripts/warehouse-energy/run_navigation_matrix.py \
  --source /work/docs/validation/warehouse-energy/phase-0/baseline-20261116/phase8-multilevel-hotel.world \
  --fixture /work/config/warehouse-energy/fixture-v0.json \
  --output /work/new-navigation-series
```

The recorded qualification uses candidate v0 plus the force-limited generator
and `qualification-protocol-v1.json`; fixture v1 records the resulting qualified
envelope. All runners refuse to overwrite prior run directories. The ramp
matrix starts 36 fresh worlds: two routes × two directions × three payloads ×
three resets, including mid-ramp braking, holding and restarting. Spawn poses
are initial conditions; no mid-run pose changes are used.

The navigation series starts fresh Gazebo, measured-pose/clock bridge, Nav2,
RMF schedule/dispatcher, and the scoped adapter for each route/direction. It
uses the high payload. Ordered `compose/go_to_place` activities select the
corridor; Nav2's static map admits that corridor while both physical ramps and
the entire RMF graph remain present. The source adapter handles action
completion/cancellation; the warehouse wrapper records activity/generation/goal
correlation and tightens the stopped-pose completion check. Phase 0 used a
constant **simulated 80% admission placeholder**. Phase 1 route runs publish
modeled SOC from the instrumented trace through RMF fleet state and capture
RGB-D color, depth, and camera calibration topics.

Audit records include requests/responses, actual schedule itinerary publications,
accepted schedule mirror updates, Nav2 terminal goal IDs, global plans and
independent full Gazebo poses. Local navigation uses a planar projection of
Gazebo ground truth, explicitly a simulation localization method. No sensor-based
localization or ramp perception result is claimed. Process groups are stopped
at each trial exit; the pod remains idle after the series.

The ramp raw-data archive can be extracted into a temporary directory and
audited locally with `audit_qualification.py`, which needs only Python's standard
library. Generated ramp meshes include per-face normals: the pinned DART/ODE
mesh loader rejects a normal-less mesh and can crash. Unit tests verify closed
mesh topology, unit normals, smooth transition endpoints, physical payload mass,
exclusive force control, and selected-corridor masking.

```sh
python3 -m unittest discover -s scripts/warehouse-energy -p 'test_*.py' -v
```

For the Phase 1 integrated route/sensing/telemetry trial, run `run_navigation.py`
with the same pinned runtime and source fixture, then independently reconcile
`torque.csv` and `energy.csv`:

```sh
python3 /work/scripts/warehouse-energy/audit_phase1.py /work/new-phase1-trial
```

The result records RGB-D transport metadata, modeled battery telemetry, and
limitations. To enable the red-mat semantic fixture and global semantic layer,
pass `--semantic --camera-width 320 --camera-height 240`. The integrated setup
uses ROS domain 188 and the isolated `warehouse-phase1-sam3` pod generated by
`render_semantic_trial_pod.py`; the runtime and adapter share only the trial's
ROS/Gazebo partition and mounted workspace. The adapter calls the pinned
`sam3-mat-v1` HTTP endpoint over mTLS. It does not connect to the hotel demo.
The pod manifest mounts its TLS secret only in the adapter container and
disables service-account token automount.

The four accepted semantic runs are retained under
`docs/validation/warehouse-energy/phase-1/sam3-attempts/phase1-semantic-320-*/`.
They use prompt `red mat`, policy `avoid-target/v1`, and lethal semantic cost
254 in the global costmap. The local costmap and motion settings match the
baseline. Reconcile modeled energy/RGB-D first with `audit_phase1.py`, then run
the independent semantic audit against the non-semantic A-up configuration:

```sh
python3 /work/scripts/warehouse-energy/audit_semantic_trial.py \
  /work/new-phase1-semantic-trial \
  --baseline-nav2 /work/docs/validation/warehouse-energy/phase-1/camera-320x240-A-up/nav2.yaml \
  --output /work/new-phase1-semantic-trial/semantic-warehouse-audit.json
```

The source capture trace uses the camera bridge's ROS receipt timestamp as a
proxy because Gazebo does not expose wall-clock exposure time. Treat it as
simulated stream provenance/freshness evidence, not exposure-to-inference
latency. The repeated-run semantic series (three audited repeats per
route/direction at 320×240, fifteen preserved development attempts) is
retained under `docs/validation/warehouse-energy/phase-1/sam3-repeatability/`
and `sam3-repeatability-b-amended/` (the B-route red mat was moved from
`[7.0, 6.3]` to `[7.0, 6.5]` m after the original position reproducibly
blocked the B-up planner); reconcile the merged series with
`audit_semantic_repeatability.py` over both directories. Other objects and
640×480 throughput remain unqualified. Physical electrical calibration
remains out of scope.

## Stage 2: physics routing and calibration

Stage 2 freezes a planning-time physics estimator and adds a pre-dispatch
route selector. The estimator predicts mission Wh from planning inputs
only (force balance with rolling resistance and drive efficiency, no
regeneration, constant auxiliary load, stop-to-stop speed profiles, a
declared per-goal transition allowance); the selector enforces the frozen
one-way deadline and the battery-reserve requirement after the mission plus
charger access before any motion starts.

Calibration fits (rolling resistance, drive efficiency, auxiliary power)
on the 36 dedicated Phase 0 fresh-world ramp trials and freezes the result
to `config/warehouse-energy/physics-model-v1.json`. Extract the Phase 0
Phase 0 ramp matrix (regenerated per the
[storage policy](../../docs/validation/warehouse-energy/README.md)), then:

```sh
python3 /work/scripts/warehouse-energy/calibrate_physics.py \
  --matrix /tmp/matrix-v1 \
  --accounting /work/config/warehouse-energy/phase1-telemetry-v1.json \
  --fixture /work/config/warehouse-energy/fixture-v1.json \
  --model-output /work/config/warehouse-energy/physics-model-v1.json \
  --output /work/stage2-calibration-report.json
```

Observed labels are recomputed from the raw actuator traces under the
frozen Phase 1 telemetry accounting model; the calibration is a
simulation-consistency check, not a physical electrical calibration. The
report records the identifiability valley between rolling resistance and
drive efficiency explicitly.

Run one Stage 2 trial (selector gate, then the same ordered RMF compose
dispatch, Nav2 corridor execution, and modeled telemetry as Phase 0/1):

```sh
python3 /work/scripts/warehouse-energy/run_stage2_trial.py \
  --source /work/docs/validation/warehouse-energy/phase-0/baseline-20261116/phase8-multilevel-hotel.world \
  --fixture /work/config/warehouse-energy/fixture-v1.json \
  --physics-model /work/config/warehouse-energy/physics-model-v1.json \
  --output /work/stage2-series/armB-r1 --arm B --payload 0.5
```

`--arm A` routes by shortest feasible distance; `--arm B` routes by minimum
predicted mission energy. `--exclude-route A` removes a corridor at planning
time (blockage scenario). An infeasible mission (for example
`--initial-soc 0.22`) is rejected with an explicit reason before any world
or process starts. `stage2-series.sh` runs the full accepted series
(rejection scenario, three arm A repeats, three arm B repeats, and the
route-A exclusion scenario).

Audit a pulled series directory independently (standard library only):

```sh
python3 scripts/warehouse-energy/audit_stage2.py \
  docs/validation/warehouse-energy/phase-2/series \
  --fixture config/warehouse-energy/fixture-v1.json \
  --physics-model config/warehouse-energy/physics-model-v1.json
```

The audit re-derives every selection from the frozen fixture and model,
recomputes each mission window from the raw traces, and checks corridor,
itinerary, reserve, deadline, and repeatability agreement. Stage 2 unit
tests cover the force model, profile construction, calibration recovery,
selector decisions, hysteresis, and the rejection gate
(`python3 -m unittest test_stage2` from this directory).

## Stage 3A: simulation dataset

Stage 3A collects the training dataset for the Stage 3B residual learner.
The frozen sweep design (`config/warehouse-energy/stage3-dataset-design-v1.json`)
covers both ramps and directions, all three qualified payloads, planned
speeds at or below the qualified cap, and two stop profiles, in two run
classes: scripted standalone traversals with exactly known planned
profiles (`stage3_trial.py`, Phase 0-style physical checks) and forced
-corridor RMF/Nav2 missions (`run_stage3_nav.py`, the deployment profile).
Labels are the modeled Wh from the observation-only plugin trace under the
frozen Phase 1 accounting model; each run is segmented consistently
(ramp boundaries for scripted runs, graph edges between waypoint crossings
for navigation runs) and paired with planning-time features, the frozen
physics estimate, and the residual.

`stage3-sweep.sh` runs the full sweep inside the pinned pod (launch it
detached, e.g. `setsid nohup bash /work/stage3-sweep.sh > /work/stage3-sweep.out 2>&1 &`,
because a silent long-running `oc exec` connection can drop and kill a
foreground sweep). Build the versioned dataset from the raw runs and audit
it:

```sh
python3 scripts/warehouse-energy/build_stage3_dataset.py \
  --raw docs/validation/warehouse-energy/phase-3a/raw \
  --fixture config/warehouse-energy/fixture-v1.json \
  --physics-model config/warehouse-energy/physics-model-v1.json \
  --design config/warehouse-energy/stage3-dataset-design-v1.json \
  --output docs/validation/warehouse-energy/phase-3a/dataset
python3 scripts/warehouse-energy/audit_stage3_dataset.py \
  docs/validation/warehouse-energy/phase-3a/dataset \
  --raw docs/validation/warehouse-energy/phase-3a/raw \
  --fixture config/warehouse-energy/fixture-v1.json \
  --physics-model config/warehouse-energy/physics-model-v1.json \
  --design config/warehouse-energy/stage3-dataset-design-v1.json
```

Partitions follow the frozen complete-run rules: the scripted payload 0.25
combination and the navigation route-B-up-at-0.08 m/s combination are
reserved for final testing; the remaining runs split deterministically by
`sha256(run_id)` into residual-train, development, and
uncertainty-calibration sets. Failed or invalid runs are rejected and
listed, never labeled as successful samples. Stage 3A unit tests:
`python3 -m unittest test_stage3` (segmentation, features, partitions,
synthetic perfect-observation reconciliation, and a rebuild of real
Phase 2 navigation evidence).

## Stage 3B: offline training

`train_stage3b.py` trains the XGBoost residual regressor and the
ridge linear-residual comparison on the Stage 3A dataset, selects bounded
hyperparameters on the development partition by mission-energy MAE,
calibrates mission-level uncertainty allowances on the separate
uncertainty-calibration partition, freezes the versioned release with a
hash-recorded freeze boundary, and only then opens the held-out
final-test partition once. It enforces the physical-bounds rule (reject
to the physics fallback when the combined estimate is negative or the
correction exceeds the physics estimate). The pinned pod provides the
training environment: xgboost 2.1.4 and its nccl dependency are vendored
at `/work/vendor` (wheel digests recorded in the Stage 3B report) and
loaded via `PYTHONPATH=/work/vendor LD_LIBRARY_PATH=/work/vendor/nvidia/nccl/lib`.
`audit_stage3b.py` independently reloads the artifacts through the native
Booster inference path, recomputes every held-out metric and coverage
figure, and with `--retrain` requires a byte-identical retraining run.
The frozen release is deployed from
`config/warehouse-energy/energy-model-release-v1/`; evaluation and audit
evidence live under `docs/validation/warehouse-energy/phase-3b/`. Stage 3B
unit tests: `python3 -m unittest test_stage3b` (the XGBoost smoke test
skips where xgboost is not installed).

## Stage 3C: serving qualification

`apps/energy-predictor/` packages the frozen release as a versioned
OpenShift AI CPU service: `predictor.py` (input validation, physics,
feature derivation matching the Stage 3A dataset bit for bit, XGBoost
residual, bounds, uncertainty), `server.py` (mTLS data port, separate
health port, one-batch admission), a fail-closed manifest, and a
digest-pinned Containerfile that self-tests at build time. Deploy with
`helm/warehouse-energy-demo/openshift-ai/render.py` and provision mTLS
credentials with
`scripts/warehouse-energy/provision_energy_serving_credentials.py`
(Secrets only; credential bytes are never committed). Note the platform
adaptation: OpenShift AI 3.5.2 injects a kube-rbac-proxy on pod port 8443
for new InferenceServices, so the mTLS data port listens on 8090 and the
`energy-predictor-v1-tls` Service targets it on 8443.

`energy_serving_client.py` is the robot-side client: bounded batch
requests, fail-closed response validation (identity, generation echo,
completeness, finite values, allowances), a bounded cache keyed by model
version and segment inputs, and the documented fallback to local
calibrated physics with the frozen conservative allowance.
`build_energy_replay.py` freezes replay batches with offline
expectations in the pinned training pod; `qualify_energy_serving.py`
runs the eleven-check qualification suite (identity, both parity gates,
all fault rejections, fallback, cache, and latency) from a labeled client
pod. Stage 3C unit tests: `python3 -m unittest test_stage3c`.

## Stage 4: comparative demonstration

The frozen experiment (`config/warehouse-energy/stage4-experiment-v1.json`)
compares three arms over matched triplets: A (shortest feasible distance,
energy logged only), B (calibrated-physics energy routing), and C (served
physics-plus-XGBoost energy routing with the documented fallback). It
covers six strata (three payloads x both directions on the single
qualified surface) with five triplets each — 90 one-way missions — plus a
round-trip set (loaded outbound, empty return, chained arithmetically
because the frozen fixture changes payload only at fresh-world
initialization) and an endpoint-unavailable fallback demonstration.
`build_stage4_order.py` emits the deterministic seeded trial order;
`run_stage4_series.py` executes it inside a labeled stage-4 pod
(`warehouse-stage4`, TLS secret mounted, network-policy-authorized
serving client). Mission observations use the model's label convention:
dispatch through final waypoint arrival, with the post-arrival idle
reported separately. `analyze_stage4.py` computes the paired statistics,
coverage, and the frozen criteria, and states the explicit AI-value
decision; `audit_stage4.py` independently recomputes observations,
physics and served predictions (against
`build_stage4_expectations.py`'s frozen offline expectations), round-trip
chaining, and the analyzer's headline numbers. Stage 4 unit tests:
`python3 -m unittest test_stage4`.

## Operator demonstration

`run_energy_demo.py` executes the proposal's demonstration sequence as
one scripted showcase: a warehouse briefing with the route map and
side-by-side estimator views, three matched delivery round trips (the
distance baseline, physics energy routing, and learned energy routing
through the serving endpoint), a predicted-versus-consumed comparison,
the payload-sensitivity planning views, and the endpoint-unavailable
physics-fallback delivery. It writes `demo-evidence.json` (machine
readable) and `demo-summary.html` — a self-contained operator summary
with inline SVG charts of the route graph and the energy comparison plus
robot camera snapshots. Run it inside a labeled serving-client pod
exactly like the Stage 4 series; unit tests for the summary generation:
`python3 -m unittest test_energy_demo`.

### Visual (noVNC) presentation

`demo_viewer.py` renders the same demo pod with a presentation-only
viewer sidecar, following the accepted G5 pattern: a dummy X server, a
view-only x11vnc, websockify/noVNC on port 6080, and a Gazebo GUI-only
client that joins the trial partition on pod-local loopback and follows
`robot_1`. A watchdog restarts the GUI whenever a mission's server ends,
so a browser session follows every delivery leg. Apply the rendered
Pod/Service/Route and open
`https://<route-host>/vnc.html?autoconnect=1`; for a private session
skip the Route and use `oc port-forward pod/warehouse-energy-demo
6080:6080` instead. The viewer never issues commands and does not touch
the audited trial machinery or energy accounting.
