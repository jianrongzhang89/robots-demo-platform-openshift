# Closed presentation investigation — run 4

This run never started navigation. It failed during the operator hold because
the resource sampler reached its 20,000-sample capacity (~400 seconds), exited
normally, and the fixture process monitor correctly ended the run. The wrapper
removed the temporary viewer and restored the reservation; cleanup passed.
The original summary/result remain FAIL. This explains the user's unavailable
noVNC link, rather than an expired 600-second operator gate.

Geometry and viewer performance evidence remain valid in
`presentation-fix-report.md` and `viewer-diagnosis/`. The follow-up gives the
read-only sampler capacity for the full bounded presentation pod lifetime;
ordinary fixtures retain 20,000 samples. No safety deadline was changed.
Run 5 owns the fresh presentation and its fresh token. Never release run 4.
