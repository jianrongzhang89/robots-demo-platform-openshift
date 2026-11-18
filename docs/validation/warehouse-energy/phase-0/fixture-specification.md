# Warehouse energy fixture v0

Date: 2026-11-16. Status: **historical design candidate; superseded by [fixture v1](fixture-specification-v1.md)**.
This implements the design work in Stage 0 of the
[approved proposal](../../../warehouse-ramp-energy-navigation-proposal.md).
The executable definition is [fixture-v0.json](../../../../config/warehouse-energy/fixture-v0.json).
Design targets are frozen for this revision before data collection. Changing the
robot, geometry or thresholds requires a new fixture revision and repeated affected gates.
No training or comparative evaluation has started.

## Baseline and robot

Reuse the digest-pinned Jazzy/Gazebo hotel image and the custom differential-drive
robot, with the existing rear ball supports. Treat it as a simulation research
robot, not a manufacturer-qualified TurtleBot3. The live SDF has total mass
**1.653 kg**, wheel radius **0.033 m**, and configured wheel separation **0.287 m**.
SDF wheel centers are 0.288 m apart; reconcile that discrepancy in the isolated
warehouse model before calibration. The source URDF's masses and frame origins
also differ from SDF. SDF is the dynamics source of truth; establish matching
sensor transforms before using pitched-camera projection.

The wheel joints currently allow effort and velocity of 1000 in their respective
SDF units, and DiffDrive does not establish a calibrated motor/efficiency model.
Those values are not credible actuator capability evidence. **Effort limit and
permitted payload remain unset** until a bounded drivetrain model is qualified.
Do not reuse the hotel RMF constant SOC or its mass/battery parameters as energy
measurements. The existing hotel controller uses 0.70 m/s desired speed; the new
warehouse profile starts at 0.10 m/s and 0.10 m/s² acceleration.

Candidate payloads are 0, 0.25 and 0.50 kg. Their 0/50/100% interpretation applies
only if 0.50 kg becomes the qualified maximum. Use a fixed 0.10 × 0.10 × 0.05 m
box centered at (-0.06, 0, 0.165) m in the physical base-link frame. Add physical
mass, collision and box inertia, not just a visual. For payload mass m, principal
inertias about its center are m/12 × (0.0125, 0.0125, 0.0200) kg·m². Attach or
remove only while stopped at a station; record mass, placement and time. Empty
payload has no zero-mass dynamic link. Check chassis/camera clearance in Stage 1.

## Geometry and qualification

All graph vertices use one planar map, `warehouse`, with separate elevation.
No lift/map switch is used for ramps. Routes share loading and transfer stations
and split at the lower decision point. The two ramp corridors do not overlap.

| Property | Route A | Route B |
| --- | --- | --- |
| Initial elevation change | 0.20 m | 0.20 m |
| Horizontal ramp run | 10 m | 20 m |
| Initial nominal grade | 2% | 1% |
| Nominal pitch | 1.146° | 0.573° |
| Entire idealized route length | 14.002 m | 42.001 m |

Corridors are 1.5 m wide, with 1 m transition regions included within each ramp
run and at least 1 m of level stopping area at its ends. Use smooth entry/exit
profiles; their final peak grade and true arc length must be recalculated from
the built world. The straight-line values above are design calculations, not a
finished world or collision mesh. The original proposal's 1 m rise (10%/5%
nominal grades) is a later candidate, not an operating permission.

Before adopting the envelope, execute at least three independently reset trials
for each route × direction × payload: **36 trials**. Require zero collision,
departure, uncontrolled sliding, chassis grounding, or payload instability.
Verify stationary downhill braking, stop/restart, ramp entry/exit, recovery and
physical roll/pitch/height against the surveyed surface. Set measured attitude,
traction, clearance and braking limits before those acceptance trials; they
cannot be inferred from flat-floor or elevator evidence. If any candidate fails,
reduce the envelope or revise the robot and repeat the affected matrix.

Keep independent Gazebo full-pose observations, wheel telemetry and contact
evidence. The planar navigation interface must not conceal pitch, roll or height.
Qualify laser obstacle handling and capture-time camera transforms on ramps.
SAM3 exclusions remain hard constraints; unknown warehouse labels and surface
classes cannot become energy features until separately validated.

## Route coordination decision

Select **ordered RMF `compose` / `go_to_place` activities** at ramp endpoints and
decision points. The installed planner spike is in
[rmf-route-spike.json](rmf-route-spike.json). It reproduces the requested waypoint
sequence in both directions for both routes. Its request example is a design
artifact; it has not been accepted by a warehouse fleet dispatcher.

The installed Python planner only exposes `get_plan_waypoints`, not a `plan`
method. Collinear intermediate vertices can be omitted from a single endpoint
plan. Explicit intermediate destinations provide the required handoff points;
a plain loading-to-transfer goal does not enforce the alternative ramp.

Use one task per selected route sequence. Keep EasyFullControl responsible for
navigation activities and generation-safe completion. Nav2 receives goals from
the adapter, never independently from the energy service. Add a corridor mask
or equivalent constraint for each leg and keep all legal replans inside it.
Reject/replan only at safe decision points; cancel the active task and confirm
a physical stop before replacing an infeasible sequence.

**Still required for the Stage 0 integration exit:** warehouse task acceptance,
RMF schedule/itinerary and activity IDs, Nav2 goal IDs and results, and independent
physical trajectories agreeing on the selected ramp in both directions. The
offline planner check is not a substitute for this evidence. `nav2-route` is
installed (1.3.13); switching to it is unnecessary for this initial design.

## Energy, battery and acceptance targets

The metric boundary is simulated robot battery terminals. No regeneration credit;
OpenShift power is excluded. Use independent torque/speed-based electrical
observations and a documented motor/loss model before producing labels. Neither
Gazebo displacement nor the sensitivity formula establishes consumed Wh.

Use a **24 Wh simulation battery assumption**, initial SOC 80%, and minimum SOC
20% after completing the mission **and reaching the lower-level charger**.
It is not a hardware battery specification. Feasibility uses a separately
calibrated upper mission-energy estimate, including charger access. Minimize
expected total energy among feasible routes, with 900 s one-way / 1800 s round
trip deadlines. Break energy ties within 0.01 Wh by duration, then route ID.
Require at least 5% predicted improvement to switch an existing feasible route
at a safe stopping point. Hard safety or feasibility failures override hysteresis.

Adopt the proposal's targets unchanged: 20% held-out MAE improvement for C over B;
5% aggregate energy improvement with paired 95% confidence interval above zero;
95% empirical upper-bound coverage separately for learned and fallback modes;
no reserve violations; at most 10% aggregate time increase versus A. Report
failures separately and never count truncated trips as savings. Serving targets
are p95 <250 ms and a 1 s deadline for batches of at most 32 directed segments.
Timeout, invalid data, wrong identity and stale generation must invoke a valid
conservative physics fallback or reject the mission.

Keep the initial 180-run matched A/B/C pilot and separate round-trip evaluation.
Freeze the final test sample size using training-only variance evidence. Partition
complete missions into physics fitting, residual training, development,
uncertainty calibration and held-out evaluation. Calibration and uncertainty
tolerances cannot be honestly set from telemetry that does not yet exist; these
remain explicit Stage 1/2 measurement gates before any held-out test.

## Early sensitivity finding

[sensitivity.json](sensitivity.json) evaluates 162 combinations of candidate
payload, signed direction, rolling resistance, efficiency and auxiliary power.
The short route wins every case when both routes share the same surface and
efficiency. These are uncalibrated constant-speed calculations excluding turns,
dwell and smoothed transitions. They support **no AI-savings claim**. The large
detour and auxiliary demand dominate; increasing rise alone does not remove
the common-endpoint gravitational-work constraint. Preserve negative results
and avoid tuning the fixture after observing held-out outcomes.

## Isolation and ownership

Implement the warehouse in its own namespace, ROS domain and Gazebo partition,
with its own maps, graph, parameters and evidence. Do not edit hotel runtime
sources to implement warehouse dynamics. No warehouse deployment exists yet.
The hotel snapshot pins its existing images/configuration, without exporting
the TLS Secret; restoration requires the referenced serving credentials and
image availability on the same cluster.

Robotics implementation owns dynamics/route evidence; ML implementation owns
calibration/splits/energy validity; platform implementation owns serving and
reproducibility. These responsibilities can be carried out by the implementation
agent. A named human energy-validation reviewer has not been supplied, and is
not presumed assigned. Physical robot access is unknown and is not required for
approved simulation work. Hardware Stage 5 remains outside the current scope.
