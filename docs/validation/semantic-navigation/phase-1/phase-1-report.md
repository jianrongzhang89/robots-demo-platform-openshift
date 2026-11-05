# Semantic navigation Phase 1 evidence

- **Date:** October 13, 2026
- **Status:** **PASS — Phase 1 technical gates met and reviewer-approved October 13, 2026.** Phase 2 is in progress.
- **OpenShift project:** `semantic-navigation`
- **Production project:** `ros2-rmf-hotel` was not modified by Phase 1.
- **Latest simulator image:** `semantic-hotel-sim:phase1`, digest `sha256:a6ccee8f09cfaea21731f98b319136805e51f66fdaa82984afac49935f1b6bd8`

## Implemented

- Added a 640×480, 10 Hz Gazebo RGB-D sensor to a runtime copy of `hotel.world`, mounted 0.11 m forward and 0.15 m above `base_link`; the checked-in/base world is not patched in place.
- Added `camera_link` and REP-103 `camera_color_optical_frame` to the matching robot URDF.
- Bridged RGB, depth, and CameraInfo locally in the simulator pod. Raw images are not sent over Zenoh. The cross-pod path JPEG-compresses RGB and PNG-compresses uint16 millimeter depth, transports CameraInfo and TF, and reconstructs XYZ at the receiver. Compression runs in a dedicated sidecar with reliable, shallow-depth subscriptions to raw images.
- Kept all deployments in the separate `semantic-navigation` project. No model inference or Nav2 costmap subscription is active.
- Raised the isolated simulator CPU limit from 8 to 12 cores after measuring saturation at the former limit. This is a test configuration, not yet a justified production sizing recommendation.

## Evidence observed

- Local tests: two camera-world patch tests passed; Phase 1 Python modules compiled; entrypoint passed `bash -n`; manifests passed server-side dry run and `git diff --check` at the time of deployment.
- CameraInfo reached the receiver with width 640, height 480, frame `camera_color_optical_frame`, and intrinsic matrix `fx=fy=554.2563`, `cx=320`, `cy=240`.
- The captured robot view is [phase1-camera-view.jpg](phase1-camera-view.jpg); the lower image shows the unobstructed floor test region.
- The first managed probe exposed raw image transport/synchronization and TF-remap problems. These were corrected by compressing before Zenoh, using a dedicated compressor sidecar with reliable subscriptions, and remapping receiver TF to `/robot_1/tf` and `/robot_1/tf_static`.
- The final managed 600-second receiver probe completed with 3,451 synchronized RGB-D pairs (**5.751 pairs/s**), zero invalid layouts, and 3,451/3,451 successful TF lookups. Capture-interval p95 was 0.4 s; paired RGB/depth timestamps satisfy the 30 ms compressor match window. CameraInfo delivered 5,929 messages.
- At the 600-second measurement boundary, the simulator compressor had emitted 3,450 pairs and the receiver had counted 3,451. The compressor's latest measured skew was 0 ms. Its cumulative input counters were 5,682 RGB and 5,837 depth callbacks; these are since sidecar start, not exact-window counters, so no precise raw-frame loss percentage is claimed.
- A late-starting receiver joined the running stream and received 77 synchronized pairs in 15.04 s (**5.12 pairs/s**), plus 151 CameraInfo messages.
- A separate 15-second `/clock` measurement observed 1,501 samples and 15.0 s simulation time over 15.0 s wall time (**Gazebo RTF 1.0**).
- A matched color/depth sample and CameraInfo were checked against the known floor plane (`z=0`) using the Gazebo robot model pose (`z=0.010045 m`, pitch `-0.058435 rad`). For the 56,661-pixel floor ROI above, all depth values were valid; the 95th-percentile 3D distance error from expected ray/plane intersections was 0.0125 m, with all tested points within 0.10 m. This is a stationary floor-region calibration check, not yet a multi-view or target-surface evaluation.
- Whole-frame mean valid depth is about 39%; that includes the blank upper image area and is not representative of the floor ROI.
- An earlier sample before the GUI was stopped showed RGB/depth latest-capture skew of 300–700 ms. The later short diagnostic had much better alignment; the full skew distribution under the final runtime has not been established.

## Gate disposition

| Check | Result | Evidence / remaining work |
|---|---|---|
| RGB-D topic, calibration, compressed delivery | **Pass** | CameraInfo and decoded RGB/depth match at 640×480; 3,451 synchronized pairs reached the receiver in 600 s with no invalid layouts. |
| At least 5 synchronized pairs/s at receiver for 10 minutes | **Pass** | 3,451 / 600.025 s = 5.751 pairs/s; capture-interval p95 was 0.4 s. |
| ≥95% valid depth on test region | **Pass** | 100% valid across the 56,661-pixel known floor ROI. The semantic target surface is evaluated in Phase 2. |
| 95% projected known points within 0.10 m | **Pass** | 95th-percentile 3D ray-to-floor-plane error was 0.0125 m; all tested points were within 0.10 m. |
| Capture-to-TF transform | **Pass** | 3,451/3,451 receiver-side TF lookups succeeded. |
| Late subscriber | **Pass** | 77 synchronized pairs in 15.04 s (5.12/s) after joining the established stream. |
| Gazebo real-time factor | **Pass** | 1.0 over a separate 15 s sample. |
| No semantic influence on navigation | Pass | No semantic inference/costmap path was launched. |
| Isolation from production hotel demo | Pass | Phase 1 resources and image are in `semantic-navigation`; production project was not changed. |

## Phase 1 disposition

The user approved Phase 1 on October 13, 2026. Phase 2 may proceed using a separate simulator image/tag in the isolated project. The current Phase 1 image remains available for rollback. Phase 1's stationary floor projection evidence is not being generalized to the target surface; target ROI depth/projection must be checked in Phase 2.

Semantic output remains disconnected from navigation until the later recognition, adapter, projection, and navigation gates pass.

Phase 1 technical gates passed. Phase 2 is not authorized until reviewer sign-off.
