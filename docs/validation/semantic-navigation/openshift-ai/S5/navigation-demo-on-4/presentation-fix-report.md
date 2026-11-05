# Mat restoration and viewer performance correction

The historical change is commit `ca60315af` (October 30, 2026): standalone
D2 uses a 1.2 × 1.95 m mat at (17.4014, -31.594). Width is three times the
previous 0.65 m. The G5 presentation incorrectly called the default fixture
builder and therefore staged a 0.9 × 0.65 m mat.

`verify_hotel_stack.py` now selects the existing enlarged geometry for an
operator presentation. Ordinary qualification trials retain their original
geometry. Costmap containment and trajectory evaluation derive the target
bounds from the generated world. Live XML confirms `1.2 1.95 0.012`; mat
center, thickness and distractor are preserved.

The CPU-only OGRE2 viewer had a one-CPU limit, 1280 × 800 rendering, and default
8-sample anti-aliasing. Its measured first-ten-sample median was 1.253 FPS,
with CPU throttling. Raising the CPU limit alone produced about 2.7 FPS;
disabling anti-aliasing and reducing resolution with OGRE2 gave about 3.3 FPS.
Switching only the viewer to OGRE, keeping 960 × 600, no anti-aliasing and a
3-CPU limit produced a final 30-sample median of 20.875 FPS. These are live
Mesa renderer measurements, not measured browser delivery rates. The robot
remained disarmed throughout, with zero command packets.

The persisted viewer also crops unused desktop pixels, uses 20 ms VNC polling
and 10 ms deferral, initializes overhead camera follow, and retains FPS/CPU
logs after future runs. The simulator's GPU RGB-D renderer and OpenShift AI
inference endpoint are unchanged. No actuator/clock/freshness limit changed.

Validation: five existing geometry tests, two operator-gate tests, Python
compilation, shell syntax, and whitespace checks pass. A live generated world
and viewer screenshots were inspected. Navigation with the enlarged mat is
pending the user's viewing-ready release. This is not a G4/G5 qualification.

Run 4 began with the original viewer manifest and was adjusted while held:
CPU resources were resized through the Pod resize API; only the GUI and VNC
processes were restarted. `viewer-diagnosis/` retains baseline, intermediate,
and final FPS samples, final GUI config and actual Pod resources. Future runs
get these settings from `g5_demo_viewer.py`; the initial manifest remains intact.

Relevant upstream configuration:
[MinimalScene parameters](https://github.com/gazebosim/gz-gui/blob/gz-gui8/src/plugins/minimal_scene/MinimalScene.hh).

## Session closure

Run 4 ended before navigation: the diagnostic resource sampler reached its
20,000-sample cap (~400 seconds), which was shorter than the operator hold.
Its exit caused fixture teardown and removal of the viewer route. Cleanup
passed. Run 5 uses 65,000 diagnostic samples to cover the bounded 1,300-second
presentation pod lifetime. Motion, clock and lease limits are unchanged.
A regression test exercises the sampler beyond its original 20,000 limit.
