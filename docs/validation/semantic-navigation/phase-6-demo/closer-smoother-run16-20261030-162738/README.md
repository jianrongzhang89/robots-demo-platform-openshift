# Closer/smoother run16 — measured standalone demo pass

Run dispatched only after the viewer's “go”. Explicit waypoint-guided route:
via (15.402, -29.95), finish (19.402, -29.95). Mat unchanged at 1.2 × 1.95 m;
conservative 0.10 m hull-clearance envelope unchanged. Signed-off fixture
and its evidence untouched.

## Results

- Navigation SUCCEEDED in 50.751 s; process exit 0.
- Independent Gazebo-body-pose minimum hull clearance: **0.2818 m**.
- No detected mat overlap, envelope entry, or Collision Monitor intervention.
- Maximum body speed 0.1207 m/s, within 0.12 + 0.005 m/s tolerance.
- Peak body yaw rate 0.2391 rad/s.
- Maximum body/wheel differences 0.0187 m and 0.0144 rad; both pose streams
  remained fresh. No pose disagreement or speed cancellation.
- A separate five-second observation confirmed the body stopped near
  (19.215981, -30.000115), with zero terminal measured linear/yaw speed.

## Steering

The trace contains the initial left turn and the right turn onto the bypass,
then small left/right corrective phases. Above a 0.05 rad/s reporting
deadband the two corrections changed heading by approximately +0.0455 rad
and -0.1081 rad (2.6° and 6.2°). Smaller-rate movement is excluded from
those phase figures. Corrections remain; oscillation is not claimed to be
completely eliminated.

Absolute body-yaw travel: 3.4217 rad. The same 0.07 m path-segment direction
proxy used in the earlier investigation gives 3.2578 rad, versus 10.602 rad
from run12's wheel-derived trajectory. Those use different pose sources
and are not a controlled physical before/after measurement.

## Evidence

- `run16-metadata.json`: authorized route and geometry, exit code, preparation link.
- `trial16-result.json`: complete result, preflight path, 967 body trajectory samples.
- `trial16.stdout`, `trial16.stderr`: unmodified runner output.
- `steering-analysis.json`: turn phases, closest-clearance sample, heading proxy.
- `stop-observer.json`: independent post-run body-pose samples and stop confirmation.
- `nav2-after.log`: recent Nav2 runtime logs.

The semantic cell update count reached zero at the finish after the mat left
view. This waypoint-guided result is not unconstrained semantic avoidance,
a semantic-liveness fault qualification, or a new safety qualification.
