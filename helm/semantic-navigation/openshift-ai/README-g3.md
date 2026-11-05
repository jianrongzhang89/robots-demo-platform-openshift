# G3 qualification topology

G3 runs the signed-off CPU adapter against the signed-off OpenShift AI endpoint with real Gazebo RGB-D capture traces and isolated diagnostic costmaps. It does not connect semantic output to navigation control.

The configuration is cluster-specific and pins the qualified images and worker hostnames. `render_g3.py` derives the private sensor/bridge topology from the existing Phase 4 profile and adds the HTTP adapter, TLS identity, a 0.5 CPU background worker and an odometry-frame costmap observer. The model image, shared inference code, prompt and precision remain unchanged.

The adapter's maximum queued-work wait is 60 ms; all results still expire from capture at 500 ms, with one in-flight request and one queued bundle. Both the adapter and diagnostic consumers request a bounded 4 MiB DDS receive buffer. Apply `g3-adapter-tuned.yaml` before creating them: it inherits the node's existing `openshift-node` profile and raises the receive-buffer ceiling to 8 MiB on only `ip-10-0-53-174.ec2.internal`. It has no MachineConfig labels or kernel boot parameters.

The rendering GPU was reserved by `sam3-g0-rendering-reservation`. Save its pod and restoration specification before handing that reservation to `semantic-s3-simulator`. Retain the accepted local SAM3 pod. Start the private router and simulator before the inference pod; readiness requires fresh RGB-D output.

Build the observer wrapper, leaving the installed costmap plugin unchanged:

```sh
oc apply -f helm/semantic-navigation/openshift-ai/g3-costmap-build.yaml
oc start-build semantic-g3-costmap -n semantic-navigation --from-dir=apps/semantic-costmap
```

The build executes 23 projection/lifecycle tests against that installed plugin. Use the completed image digest with `render_g3.py --costmap-image IMAGE@sha256:...`. Retain server-side dry-run output, manifests and source hashes. The qualified manifest and image digest are in the [G3 evidence](../../../docs/validation/semantic-navigation/openshift-ai/S3/).

Before long measurements, run the capture observer, costmap collector, bounded observation-motion helper, and `verify_phase4_lifecycle.py --inference-pod semantic-s3-inference --simulator-pod semantic-s3-simulator` on short pilots. The motion helper runs only inside the private simulator, checks odometry freshness and bounded displacement, and always sends zero commands on exit. `/tmp/g3-motion-stop` is its explicit interruption flag.

For each independent ten-minute run, use a new output directory:

```sh
PATH=/Users/zhangj/bin:$PATH python3 scripts/semantic-navigation/run_g3_timing.py \
  --oc /Users/zhangj/bin/oc \
  --resources docs/validation/semantic-navigation/openshift-ai/S3/g3-qualification-20261031/resources-final.json \
  --output-dir /tmp/g3-new-stationary-run
```

Use `--moving` for each of the two observation-motion repetitions. The runner recreates only the private adapter/costmap pod, resets only the private world, retains raw results, and evaluates fixed thresholds. It never retries a failed measurement. Each moving run includes verified stopped-state evidence.

`evaluate_g3.py` requires ≥5 fresh results/s, p95 ≤250 ms at publication and after observer validation, ≥95% pairing, no identity/order/age/payload-binding errors, costmap p95 ≤300 ms, no publication gaps over 500 ms, bounded queues and memory, and a full 600 seconds. The runner also requires zero pod restarts. The observer checks full mask/cloud SHA-256 binding and all original value/layout invariants; its optimized value checks have equivalence tests.

To retire the fixture, stop the motion helper, stop/pause the private source, retain final evidence, remove only the `semantic-s3-*` objects, and restore the saved rendering reservation. The TuneD profile is a declared prerequisite for subsequent qualification on this CPU worker. To roll it back, remove `semantic-g3-adapter` and restore the captured previous `net.core.rmem_max` value (212992); the initial diagnostic sysctl change was made before TuneD took ownership. Do not remove that prerequisite while an adapter requiring a 4 MiB minimum is expected to start.

See the [G3 report](../../../docs/validation/semantic-navigation/openshift-ai/S3/report.md) for results, retained failures and scope limitations.
