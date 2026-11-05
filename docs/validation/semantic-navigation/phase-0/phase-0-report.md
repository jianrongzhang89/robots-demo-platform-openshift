# Semantic navigation phase 0 evidence

- **Date:** October 13, 2026
- **Status:** **PASS — complete with reviewer sign-off.** Recognition quality for the hotel target is not qualified; Phase 1 is now in progress.
- **Repository commit at start:** `2007f219d60e16374064ce632449905a5c82b0f7`
- **OpenShift context:** `api-ai-dev02.kni.syseng.devcluster.openshift.com:6443`
- **Existing demo project:** `ros2-rmf-hotel`
- **Isolated semantic project:** `semantic-navigation` (created from the version-controlled [namespace manifest](../../../../helm/semantic-navigation/namespace.yaml))

## Decision and acceptance

Use the NVIDIA CUDA path for the initial local inference backend. The cluster has an available NVIDIA L40S and an operational NVIDIA device plugin/driver stack. The L40S node reports CUDA driver compatibility for CUDA 13.0; the pinned SAM3 code's documented minimum is CUDA 12.6. Direct model loading, finite-output/mask checks, accelerator memory measurement, and cached restarts **were demonstrated** as described below. Hotel-scene recognition quality remains unqualified.

**Phase 0 runtime gate passes.** The authenticated, user-approved Hugging Face account downloaded original `facebook/sam3` at revision `3c879f39826c281e95690f02c7821c4de09afae7`. Local and encrypted gp3 PVC SHA-256 hashes match (`9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e`); the credential was never copied to OpenShift. The pinned CUDA runtime image loaded the checkpoint and completed inference three times on the L40S, including two runs with `HF_HUB_OFFLINE=1` and the image/checkpoint already cached. Masks/scores were finite and the model reported accelerator allocations. **This does not pass the recognition gate:** at the configured 0.5 confidence threshold, the upstream basketball sample produced zero masks for both `floor mat` and `person`. Phase 2 must qualify prompts/thresholds on an independent hotel-scene set before any semantic output is connected to navigation.

| Check | Result | Evidence |
|---|---|---|
| Existing deployment preserved and healthy | Pass | Hotel simulation, RMF core, Nav2, and Zenoh router were each 1/1 ready; running image digests are listed below |
| Existing single-floor route reproduced | Pass | RMF task `patrol.dispatch-4`, `lobby → tinybot_charger → lobby`; all three phases completed, finish timestamp present, robot returned idle on L1 |
| Isolated project created | Pass | `semantic-navigation` namespace is Active; it contains the checkpoint PVC, image-build records, and completed one-shot smoke Job only; no long-running inference deployment exists |
| Accelerator inventory and access | Pass for candidate selection | 12 NVIDIA GPUs in the cluster: 9 A10G and 3 L40S; candidate L40S has no workload allocation and `nvidia-smi` reports 0 MiB used, 0% utilization |
| Model access approval | Pass (user confirmed) | User reports access request approved |
| Local Hugging Face authentication and gated checkpoint download | Pass | Authenticated account accessed `facebook/sam3`; checkpoint pinned to `3c879f39826c281e95690f02c7821c4de09afae7` |
| Checkpoint integrity and isolated staging | Pass | Local and encrypted gp3 PVC hashes match: `9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e` |
| Pinned runtime image | Pass | Final image `image-registry.openshift-image-registry.svc:5000/semantic-navigation/sam3-smoke@sha256:0df314c66fa1cdf00680cfab244e00c99d60ef05f5e5eb4eaf9d16ff0eb07cc3`; built from pinned source plus explicit `einops`, `pycocotools`, and `psutil` dependencies |
| Model load and image inference | Pass — runtime only | Three L40S runs completed with finite outputs; two cached/offline reruns; load 31.1 s, inference 0.87 s on a 1280×720 image |
| Recognition on smoke image | Hold for Phase 2 | `floor mat` and `person` both returned zero masks at confidence 0.5 on the unrelated upstream basketball photo; no hotel-scene accuracy claim |
| Accelerator and memory | Pass | CUDA BF16; NVIDIA L40S; peak allocated 5,336,111,616 B (~4.97 GiB), peak reserved 5,588,910,080 B (~5.21 GiB); pod requested 16 GiB and capped at 32 GiB |
| Offline/cached second startup | Pass | Same image digest and local read-only checkpoint PVC; `HF_HUB_OFFLINE=1`; second and third runs succeeded without HF access |
| Runtime lock / dependency closure | Pass for deployed artifact | Immutable image digest pins the complete deployed closure; direct versions are recorded below. Full rebuild still resolves transitive packages during its build and is not claimed bit-for-bit reproducible |

## Existing demo baseline

The cluster had 24 Ready nodes. The following deployments in `ros2-rmf-hotel` were observed at 1/1 ready with zero restarts in the Nav2 pod:

| Deployment | Image digest(s) observed |
|---|---|
| `hotel-sim` | `quay.io/jianrzha/ros2-rmf-hotel-sim@sha256:e515525dc4abb61e24097e1f1a556553f35febfc22c060faab67017a20b880d9`; `image-registry.openshift-image-registry.svc:5000/ros2-rmf-hotel/rmf-image@sha256:659344b583dbde5804e5dfc8fea38dfd5c1160a52a2f09dfb05a4447e691c0d5`; `docker.io/eclipse/zenoh-bridge-ros2dds@sha256:38f162ae5236412f4f02e77927e22585356f7e706db39ec1c6194b9bd0d05b18` |
| `rmf-core` | `image-registry.openshift-image-registry.svc:5000/ros2-rmf-hotel/rmf-image@sha256:659344b583dbde5804e5dfc8fea38dfd5c1160a52a2f09dfb05a4447e691c0d5`; `docker.io/eclipse/zenoh-bridge-ros2dds@sha256:38f162ae5236412f4f02e77927e22585356f7e706db39ec1c6194b9bd0d05b18` |
| `robot-nav-robot-1` | `quay.io/jianrzha/ros2-rmf-nav2@sha256:fcf66afcc12e213bc13ee8a50eb6b141b4a9af3b4a4b86123421e58624ec54b6`; `docker.io/eclipse/zenoh-bridge-ros2dds@sha256:38f162ae5236412f4f02e77927e22585356f7e706db39ec1c6194b9bd0d05b18` |
| `zenoh-router` | `docker.io/eclipse/zenoh@sha256:137310456cc7a75d955063513207c737f25071fbb74fd7641835c50ab8e3369f` |

The active Nav2 container requests 1 CPU and 1 GiB memory, limits 2 CPU and 2 GiB, and requests no GPU. All existing releases remain unchanged. The `ros2-rmf-hotel` namespace has no ResourceQuota or LimitRange.

The first route probe requested `lobby → restaurant → lobby` as task `patrol.dispatch-2`. RMF and Nav2 moved through initial L1 waypoints, then the task stopped progressing before the `L1_door2` passage step; the door-open and subsequent navigation events remained in standby. We canceled this test task, verified it was canceled, and dispatched a return-to-lobby task (`patrol.dispatch-3`), which completed with all phases finished. This longer route is not counted as the baseline pass.

We then ran the shorter, door-free L1 patrol `lobby → tinybot_charger → lobby` as RMF task `patrol.dispatch-4`. RMF assigned it to `hotel_nav2/robot_1`; all phases `[1,2,3]` were completed, `pending` was empty, and a finish timestamp was present. The fleet state afterward showed an empty task ID, no path, and the robot at L1 lobby. The terminal predicate checks phase completion and timestamps rather than trusting the RMF top-level display status.

## GPU and runtime inventory

| GPU type | Ready nodes | GPU memory reported by node labels | Total devices |
|---|---:|---:|---:|
| NVIDIA A10G | 9 | 23,028 MiB each | 9 |
| NVIDIA L40S | 3 | 46,068 MiB each | 3 |

Candidate node `ip-10-0-18-251.ec2.internal` advertises one allocatable `nvidia.com/gpu`, is Ready, and reports `NVIDIA-L40S`. Its `nvidia-smi` output showed driver `580.95.05`, CUDA compatibility `13.0`, 46,068 MiB total, 0 MiB in use, 0% GPU utilization, and no processes. The node is tainted `g6e-gpu=true:NoSchedule`; the inference workload will need an explicit matching toleration, GPU request, and node affinity/selector. The NVIDIA `ClusterPolicy` is Ready. The available GPU is observed capacity, not a reservation; it can be allocated to another workload before the SAM3 smoke test.

OpenShift assigned the `restricted` minimally sufficient security standard and restricted audit/warn labels. The completed Job ran under that restricted policy with a one-GPU request, explicit L40S placement/toleration, and a read-only checkpoint mount. The final namespace contains no long-running inference pod. No OpenShift AI Model Serving resource was used or needed for this local inference gate.

## SAM3 source and runtime candidate

The public SAM3 source had no published Git tags when checked. Pinned source commit: `0570b3a5be9c4e694f23d85232fb55f4a6f1f7fc`. Pinned model snapshot: `3c879f39826c281e95690f02c7821c4de09afae7`, file `sam3.pt`, SHA-256 `9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e`. Runtime versions: Python 3.12, PyTorch `2.10.0+cu128`, torchvision `0.25.0+cu128`, SAM3 `0.1.0`, einops `0.8.1`, pycocotools `2.0.10`, and psutil `7.2.2`. [Pinned SAM3 installation guidance](https://github.com/facebookresearch/sam3/blob/0570b3a5be9c4e694f23d85232fb55f4a6f1f7fc/README.md), [SAM3 checkpoint access](https://huggingface.co/facebook/sam3).

A ROS/Nav2-independent runner is at [`apps/semantic-perception/sam3_smoke.py`](../../../../apps/semantic-perception/sam3_smoke.py). It uses an explicit local checkpoint (`load_from_HF=False`), applies a text prompt, validates finite mask/score tensors, and emits timing and CUDA memory values. It selects BF16 where supported and FP16 otherwise, following Meta's image-inference example. Three runs passed the runtime checks; output stayed empty for `floor mat` and `person` on the upstream basketball sample. A PyTorch warning says the kernel cache path `//.cache/torch/kernels` cannot be created; inference still completed, but set a writable `HOME`/cache path before measuring sustained performance. Local Podman is installed but its VM/socket is not running, so isolated OpenShift builds produced the pinned image.

All trials used the upstream `test_image.jpg` at 1280×720, confidence threshold 0.5, one image, and `HF_HUB_OFFLINE=1`:

| Trial | Prompt | Model load | Inference | Masks | Outcome |
|---|---|---:|---:|---:|---|
| 1 | `floor mat` | 31.135 s | 0.87 s | 0 | Runtime pass; empty output is expected for this unrelated scene |
| 2 (cached restart) | `floor mat` | 31.133 s | 0.876 s | 0 | Runtime pass; same image/checkpoint with HF offline |
| 3 | `person` | 31.102 s | 0.871 s | 0 | Runtime pass; visible people were not detected at the default threshold, so recognition is not qualified |

Each run reported finite masks and scores, `NVIDIA L40S`, and `torch.bfloat16` autocast. Peak allocated GPU memory was 5,336,111,616 bytes (~4.97 GiB); peak reserved was 5,588,910,080 bytes (~5.21 GiB). The Job requested 16 GiB host memory and had a 32 GiB limit. A sampled pod metric during trial 3 was 6,699 MiB; it was not a process high-water measurement.

Checkpoint PVC annotations record the model revision and checksum. The workload mounts it read-only. The final image digest is the immutable dependency/runtime lock for this executed artifact; the current Containerfiles still install some transitive dependencies from the package index, so rebuilding may resolve different transitive versions. Rebuild reproducibility should be tightened before promoting this smoke image to a demo runtime.

The workstation has Python 3.14.5 but no installed `torch` or `sam3` runtime packages. The authorized checkpoint is present in the local Hugging Face cache and staged on the cluster PVC. Python 3.14 is not selected as the container runtime; the executed image uses Python 3.12 and pinned CUDA PyTorch/torchvision builds. Gated access was granted and used for the download; no HF credential is stored in the image or namespace.

## Phase 0 disposition and next gate

Phase 0 is complete with reviewer sign-off for local model-runtime feasibility on the cluster's L40S. The final Job completed, the hotel deployments remain 1/1 ready, and the baseline route evidence remains valid. The empty detections on the smoke image are explicitly **not** a recognition pass; do not connect these outputs to costmaps or claim semantic navigation.

Phase 1 may proceed as a separate verified stage: add the robot camera pipeline and validate synchronized RGB/depth/calibration/TF with semantics disconnected from navigation. Phase 2 must then qualify SAM3 prompts and confidence behavior on a frozen hotel-scene set before implementing semantic cost influence. The kernel-cache warning and transitive dependency lock should be addressed before sustained-performance measurements or a productionized runtime.
