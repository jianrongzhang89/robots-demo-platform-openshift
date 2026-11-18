# Phase 1 development attempts

These attempts are not counted in the accepted Phase 1 gate:

1. **Initial A-up run:** the `oc rsync` command nested updated scripts under an extra directory, so the pod executed the Phase 0 runner. The RMF route passed, but there was no `energy.csv` or RGB-D evidence. The run is preserved as `/work/phase1-rgbd-energy-A-up-2` in the qualification pod and is excluded.
2. **A-up v2:** source SDF already contained a camera frame and joint. The first generator version added duplicates, Gazebo rejected the world, and the trial was stopped. The generator now attaches the sensor to the existing camera link and adds only missing frames.
3. **A-up v3:** Gazebo produced camera streams and modeled battery traces, but Nav2's lifecycle manager failed during map-server configuration and no route moved. The attempt is excluded. Camera activation is now lazy and its ROS bridge starts after Nav2 map setup; the subsequent route passed.
4. **Initial semantic A-down attempt:** the isolated camera compressor was missing its `rgbd_pairing.py` and `camera_qos.py` runtime dependencies. RGB-D transport continued, but SAM3 received no paired inputs and no task was dispatched. Preserved as `sam3-attempts/phase1-semantic-320-A-down-1/` and excluded.
5. **Semantic A-down with the first A fixture offset:** the red mat at `[4.5, 0.3]` m was detected and projected, but the global planner could not find a legal path to the fork from the far side of the mat. Nav2 stopped without a physical corridor departure. Preserved as `sam3-attempts/phase1-semantic-320-A-down-2/` and excluded. The A-route red mat was moved to `[4.5, 0.5]` m, leaving a wider free strip on the opposite side; both A directions then completed with the same fixture and unchanged navigation settings.

The accepted four-case 320×240 sensing series and four-case semantic series are reported separately from these development attempts. Failed attempts remain preserved and were not used as PASS evidence or to reinterpret modeled Wh results.
