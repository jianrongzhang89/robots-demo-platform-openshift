# Camera-auto-follow run20 — completed waypoint-guided demo

Dispatched after the viewer opened noVNC and said “go”. The corrected route
bypasses the mat northward and returns to its opposite side: via
(15.402, -29.95) and (19.402, -29.95), goal (19.402, -31.594), heading -π/2.
The 1.2 × 1.95 m mat, 0.10 m conservative hull-clearance envelope, speed
limits and goal tolerances were unchanged. The signed-off fixture was not
modified. This is not unconstrained semantic avoidance or qualification.

## Navigation and clearance

- Nav2 SUCCEEDED; runner exit 0; duration **64.202 s**.
- Independent Gazebo-body-pose minimum hull clearance: **0.2900 m**.
- No detected overlap, envelope entry, or Collision Monitor intervention.
- Maximum body speed 0.1229 m/s, within 0.12 + 0.005 m/s tolerance.
- Body/wheel differences below 0.0372 m and 0.0242 rad; both streams fresh.
- One steering-direction change above the 0.05 rad/s reporting deadband;
  this metric does not exclude smaller-rate corrections.

## Independent endpoint check

The post-run observer confirmed zero measured linear/yaw speed at
**(19.375669, -31.380661)**, beyond the mat's east edge and within its Y span.
The actual target distance is **0.214958 m**, slightly beyond the unchanged
0.20 m goal tolerance despite Nav2's belief-frame success. Do not count this
as independent physical endpoint-tolerance acceptance. No automatic
corrective motion was dispatched.

## Camera follow

Tracking telemetry before and after the run reports FOLLOW_LOOK_AT, both
targets robot_1, overhead offset (0, 0, 5), gains 0.02. The read-only observer
retained **677 fresh camera/body samples over 67.6 s**, including 641 moving
samples. Camera poses stayed finite, near 5.01 m height. Moving horizontal
centering lag: maximum 0.5562 m, 95th percentile 0.5058 m. The settled camera
returned above the final stopped body.

The auxiliary camera observer returned **134 after writing complete JSON
output** (`camera-observer.stdout`). Its stderr is retained; the JSON parses
and contains the recorded samples. This diagnostic-process failure did not
restart the simulator or Nav2, interrupt navigation, or affect robot commands.
The observer source is retained as-run, including that shutdown behavior.

## Evidence

- `run20-metadata.json`: viewer authorization, exact route and preparation link.
- `trial20-result.json`: preflight and all 1,229 body trajectory samples.
- `trial20.stdout`, `trial20.stderr`: original runner output.
- `camera-observer-source.py`, `camera-observer.*`: read-only observer and output.
- `camera-follow-analysis.json`: freshness, finite-pose and moving-lag statistics.
- `tracking-before.txt`, `tracking-after.txt`, `camera-pose-after.txt`: GUI state.
- `stop-observer.json`: independent final stop samples.
- `pods-after.json`: healthy simulator and Nav2 after the run.

Semantic updates reached zero after the mat left view. This is not a
semantic-liveness fault qualification or proof of unconstrained avoidance.
