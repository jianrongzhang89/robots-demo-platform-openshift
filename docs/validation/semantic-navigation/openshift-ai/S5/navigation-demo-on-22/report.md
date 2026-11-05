# User-viewed navigation run 22

The viewer and disarmed zero-packet hold were verified before the user's
explicit “go”. Navigation completed with `goal_succeeded` (status 4).
The final physical position was `(19.337125, -31.534836)`, **0.086919 m**
from goal `(19.4008, -31.594)`, beyond the far side of the enlarged mat.
The physical endpoint acceptance passed and the robot was stationary.

All fixture checks passed, including the contact audit with no unexpected
contacts and active-motion capture mapping without a clock fault. Native
applied zero followed goal completion in 3.897 ms; stationary was confirmed
in 548.436 ms. The run used the restored presentation localization and
position-only goal completion documented in `../navigation-completion-fix/`.

Cleanup succeeded and removed the demo pod and noVNC route. The restoration
check is `../preflight-after-navigation-demo-on-22.json`. Full evidence remains
in `result.json`, `physical-endpoint.json`, and `trial/runtime/`.
This is a completed presentation, not broader G5 qualification.
