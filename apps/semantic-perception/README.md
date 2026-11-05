# Semantic perception backends

`sam3_ros_node.py` supports `backend:=local` (the default GPU runner) and `backend:=http` (the CPU ROS adapter). Selection is explicit; remote failures never switch to local inference. Both paths use the same capture-time deadline, retained RGB-D bundle, result guard, mask normalization and organized point-cloud projection.

Remote configuration requires an HTTPS origin, CA/client certificate/key, and a complete pinned `semantic-deployment/v1` identity JSON. Set `SEMANTIC_ENDPOINT`, `SEMANTIC_TLS_CA`, `SEMANTIC_TLS_CERT`, `SEMANTIC_TLS_KEY`, and `SEMANTIC_DEPLOYMENT_IDENTITY`, or use the corresponding ROS parameters `endpoint`, `tls_ca`, `tls_cert`, `tls_key`, and `deployment_identity`. Configure `robot_id`, `stream_id`, `input_prefix` and `output_prefix` for the intended stream. Configuration changes require restarting the node.

The transport verifies TLS hostname and client authentication, compares full model identity at initialization and on each response, bounds the whole request by its remaining capture budget, and permits one HTTP request at a time. A deployment identity mismatch latches a failure until restart. DNS uses one bounded-wait resolver thread and caches its result; a failed lookup or a changed endpoint address requires an explicit restart. Prediction requests are never retried. Metadata initialization may retry, but cannot grant sensor readiness.

The adapter retains at most one pending request, one queued bundle, and 20 entries per sensor queue. Inputs are limited to 640×480 pixels and 8 MiB per compressed image; response bodies are bounded by the shared contract's 28 MiB limit. Errors, expired results, invalid correlation, reset epochs and missing retained bundles produce no mask or cloud. Readiness requires a valid fresh RGB-D result and expires at the original capture deadline.

`Containerfile.cpu` builds the ROS Jazzy CPU image from the repository root, without Torch, CUDA, SAM3 installation or model weights. It runs 42 unit tests and 12 ROS tests during the build. The historical GPU overlay Containerfiles also copy the backend modules; the deployed accepted local image is retained separately for rollback.

For the isolated G2 deployment:

```sh
python3 helm/semantic-navigation/openshift-ai/render_adapter.py \
  --identity docs/validation/semantic-navigation/openshift-ai/S1/g1-qualification-20261031/expected-identity.json \
  --node ip-10-0-53-174.ec2.internal > /tmp/g2-adapter.json
oc apply -f /tmp/g2-adapter.json
```

The renderer pins the qualified CPU image, uses the `sam3-replay` identity, mounts its TLS credentials, and sets diagnostic topics under `/g2/robot_1/`. DDS uses loopback in private domain 188, with no navigation bridge. No GPU, checkpoint volume or Kubernetes API token is mounted. The pod readiness probe checks fresh ROS status; **0/1 Ready while idle is expected**, even with a healthy model server. The pod remains running for controlled replay. Do not treat this isolated renderer as a production navigation deployment.

`qualify_ros_adapter.py` runs inside this pod using the G1 frozen RGB requests plus synthetic one-metre aligned depth. Its checks cover exact union-mask parity, original headers, organized depth alignment, freshness transitions and the isolated ROS graph. The ROS fault suite uses real mTLS with deterministic injected server responses; it does not mutate the live model deployment.

See the [G2 qualification report](../../docs/validation/semantic-navigation/openshift-ai/S2/report.md) for adapter evidence and the [G3 report](../../docs/validation/semantic-navigation/openshift-ai/S3/report.md) for completed timing/projection qualification and its required tuning.
