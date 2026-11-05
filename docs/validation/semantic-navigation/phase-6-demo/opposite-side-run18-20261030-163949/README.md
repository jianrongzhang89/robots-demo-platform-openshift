# Corrected opposite-side run18 — measured standalone demo pass

Run dispatched after the viewer's second “go”, using the corrected endpoint.
Explicit waypoint-guided route: start (15.402, -31.594), via
(15.402, -29.95) and (19.402, -29.95), finish (19.402, -31.594), heading -π/2.
Mat remains 1.2 × 1.95 m at (17.4014, -31.594). Conservative 0.10 m hull
envelope, speed limits, goal tolerances and pose watchdogs were unchanged.
The signed-off fixture was not modified.

## Results

- Navigation SUCCEEDED in **64.001 s**; process exit 0.
- Independent Gazebo-body-pose minimum hull clearance: **0.2980 m**.
- No detected mat overlap, envelope entry, or Collision Monitor intervention.
- Maximum body speed 0.1228 m/s, within 0.12 + 0.005 m/s tolerance.
- Peak body yaw rate 0.2392 rad/s.
- Maximum body/wheel differences 0.0575 m and 0.0279 rad; neither pose
  stream went stale. No pose disagreement or speed cancellation.
- Independent post-run observation confirmed a stop at
  **(19.368120, -31.451961)**, with zero measured linear/yaw speed.
- The stopped body is beyond the mat's east edge and within its Y span:
  the intended opposite side of spawn. Target distance **0.146024 m**,
  within the unchanged 0.20 m position tolerance.

## Steering

One steering-direction change above the **0.05 rad/s** reporting deadband:
initial left turn, followed by right turns onto the bypass and down toward
the corrected destination. Same-direction phases may span intervening
straight sections. No repeated left/right hunting appeared above this
threshold; this does not exclude smaller corrections. Absolute body-yaw
travel was 4.7312 rad across the longer, corrected route.

## Evidence

- `run18-metadata.json`: viewer authorization, route, goal/heading, preparation link.
- `trial18-result.json`: full preflight/result and 1,223 body trajectory samples.
- `trial18.stdout`, `trial18.stderr`: unmodified runner output.
- `steering-and-endpoint-analysis.json`: phases, closest-clearance sample, endpoint check.
- `stop-observer.json`: five-second independent post-run body-pose observation.
- `nav2-after.log`: recent Nav2 runtime logs.

The semantic update count reached zero after the mat left view. This is a
waypoint-guided demo pass, not unconstrained semantic avoidance, a semantic
liveness fault qualification, or a new safety qualification.
