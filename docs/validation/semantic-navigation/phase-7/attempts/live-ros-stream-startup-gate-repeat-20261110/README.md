# Phase 7 ROS endpoint startup gate repeat — live pass

This exact repeat used candidate #66 (`sha256:bdcc039a9a0279fccecdcfad9231cdeaa3facc0ccf5f36fc06912b949cd91148`), adapter candidate #9 (`sha256:d5b22eae66497af2bd3230d43767f862d6b0923d73ffb8f54a865e21c9258c28`), and the same two-sided ROS endpoint readiness gate plus reliable destination route setting.

Both readiness checks passed before the camera bridges started. Source domain 181 received 68–69 messages on all five streams; destination domain 182 received 67–68 on all five streams. The adapter paired 48 RGB-D-CameraInfo triplets and emitted 29 fresh results. The mTLS check confirmed the API was loopback-only; `red mat` returned HTTP 200 with `changed:false`, and unapproved `blue crate` returned HTTP 400 without transition effects. Nav2 accepted a real goal and canceled it with `STATUS_CANCELED`; both cancel services acknowledged. All 415 native samples remained disarmed with zero applied commands; maximum measured speed was 0.0010035701 m/s. All 19 containers exited zero.

Phase 6 and the shared Phase 5 router match before and after for readiness, status, restart counts, IPs, and nodes. The bundle contains the exact manifest, build #66 test record, pod state, events, all container logs, and SHA-256 checksums. The temporary validation pod and fixture Secret were deleted.
