# OpenShift AI for Robotics: Research, Customer Use Cases, and Demo Proposal

- **Research date:** October 5, 2026
- **Context:** Existing ROS 2, Nav2, Zenoh, Gazebo, and Open-RMF deployments in this repository
- **Recommendation:** Build an AI-enabled robotics operations platform, with an initial hotel/facility demo and a reusable model-development-to-deployment workflow.

**Jump to:** [Executive recommendation](#1-executive-recommendation) · [Platform capabilities](#4-what-openshift-ai-contributes-today) · [Use cases](#5-prioritized-customer-use-cases) · [Architecture](#6-reference-architecture) · [Demo packages](#8-three-concrete-customer-demonstration-packages) · [Roadmap](#9-implementation-roadmap) · [Customer value](#103-customer-value-model) · [Sources](#references)

## 1. Executive recommendation

OpenShift and OpenShift AI can provide substantial customer value at three connected levels:

1. **Operate robots as enterprise applications.** OpenShift runs fleet services, integration APIs, site applications, telemetry processing, and simulation with consistent deployment and operations practices.
2. **Make robot operations more effective with AI.** OpenShift AI serves models for inspection, operator assistance, incident diagnosis, travel-time prediction, and equipment-health analysis.
3. **Continuously improve robot intelligence.** OpenShift AI provides workbenches, training, pipelines, model metadata, evaluation, and serving; OpenShift GitOps and complementary edge-management tools distribute the resulting applications and models.

The strongest customer message is:

> **Run heterogeneous robot fleets and continuously improve their AI on a common enterprise platform, from the datacenter to the customer site.**

### What to build first

Build a **“Smart Facility Robot Operations”** demonstration using the existing federated hotel world:

- An operator requests a mission in natural language.
- A model served by OpenShift AI converts the request into a typed mission intent.
- An application gateway resolves approved destinations and submits an ordinary Open-RMF task.
- The robot travels from the L1 lobby to the L3 hallway through Lift2.
- Live task, lift, navigation, and platform events explain progress and delays.
- A second demonstration adds a robot camera and an inspection model, then shows an evaluation pipeline, deployment of a better model, and rollback of a regressing candidate.

These two demonstrations answer different buyer questions: **“What can robots do for my operation?”** and **“How do I operate and improve this reliably across sites?”**

**Recommended initial use-case portfolio:**

| Sequence | Demonstration | Main customer outcome | Main platform proof |
|---|---|---|---|
| 1 | Fleet copilot + evidence-based incident explanation | Less operator effort and faster troubleshooting | Private model serving integrated with real fleet operations |
| 2 | Mobile visual inspection + continuous model improvement | More consistent inspections and faster adaptation | Training, evaluation, model versioning, serving, and GitOps delivery |
| 3 | Predictive ETA and congestion-aware mission release | Higher service reliability and fleet productivity | Predictive ML trained on operational data and integrated with RMF |
| 4 | Site-local inference and controlled multisite rollout | Operational continuity and lower rollout effort | Hybrid/edge deployment and lifecycle management |

A chat interface is an effective entry point. The durable differentiation is the **complete data → model → evaluation → deployment → operational outcome → feedback loop**.

## 2. Research scope and evidence

This report combines:

- Repository architecture and integration-point inspection.
- Red Hat product information, the current supported-configurations matrix, and lifecycle policy.
- Open Data Hub documentation source for technical explanations.
- Upstream ROS 2, Open-RMF, Zenoh, Nav2, and robot-learning documentation.
- A runnable Red Hat multimodal monitoring quickstart and an adjacent enterprise customer case study.

**Evidence conventions:**

- **Verified platform capability:** documented in the Red Hat supported-configurations matrix or official product material.
- **Upstream mechanism:** documented by its project; product support depends on the selected distribution and configuration.
- **Proposed integration:** application engineering recommended here; it is not a built-in robotics feature of OpenShift AI.
- **Demo target:** a proposed acceptance goal, not a measured customer result.

The Red Hat supported-configurations article was updated **October 2, 2026** and lists OpenShift AI 3.3, 3.4, and 3.5. This report uses **3.5 on x86_64 as a reference target**, rather than assuming an older 2.x feature set. The actual cluster version, installed operators, accelerators, and entitlements were not queried. [S01]

Several rendered `docs.redhat.com` pages returned HTTP 403 during research. Technical descriptions were cross-checked against accessible documentation source and the Customer Portal support matrix. Open Data Hub `main` is a moving upstream source; it is used to explain mechanisms, not to establish a downstream GA claim. The support matrix takes precedence for component status. References list only material successfully retrieved and used.

## 3. Starting point in this repository

The most useful baseline is the federated hotel deployment described in [README.md](../README.md) and [MULTI-LEVEL-NAVIGATION-DEMO.md](../MULTI-LEVEL-NAVIGATION-DEMO.md):

```text
hotel-sim              Gazebo, robot sensors and actuation, lifts and doors
robot-nav-robot-1       Nav2, AMCL, floor-map switching, navigation relays
rmf-core               RMF scheduling, tasks, Free Fleet, building coordination
zenoh-router           Cross-pod ROS 2 transport

Demonstrated route: lobby (L1) → Lift2 → L3_middle_hallway → lobby (L1)
```

The following are documentary/code findings, not a fresh cluster acceptance test:

| Existing asset | How it helps | Additional work for the AI proposal |
|---|---|---|
| Working hotel mission route | Immediate visible outcome for AI mission dispatch | Typed mission API, destination lookup, request/result correlation |
| `demo/dispatch_multilevel_task.py` | Shows `/task_api_requests` and `/task_api_responses` integration | Extract a long-lived mission service; retain task status beyond submission |
| `entrypoints/nav2_relay.py` | Navigation command/result handling | Export structured execution events and durations |
| Lift/door and localization integration | Real operational context for incident analysis and ETA prediction | Normalize states and correlate them with mission IDs |
| Helm deployment and pinned Zenoh 1.5.0 configuration | Reusable infrastructure and transport baseline | An AI overlay, telemetry collector, inference adapters, persistent storage |
| Gazebo/noVNC visual experience | Easy customer demonstration | Add an actual robot-view sensor stream for computer vision |
| Multiple single-floor demo worlds | More evaluation scenarios | Automated scenario launch, isolation, reset, and result collection |

### Important data and scenario implications

- **Battery health is not currently a real measurement.** `entrypoints/entrypoint-rmf.sh` notes that adapter `battery_soc=1.0` is hardcoded. Energy and maintenance demos require new telemetry or explicitly labeled synthetic data.
- **The Gazebo viewing camera is not a confirmed robot camera feed.** The entrypoints launch a camera-follow supervisor; the inspected world/configuration files do not establish a robot `image_raw` pipeline. Inspection requires a camera sensor, ROS-Gazebo bridge, and inference adapter.
- **Current task dispatch is patrol.** The existing script submits a route, not physical pickup, payload verification, or delivery handover. A “delivery” customer story needs those additional task actions or must be described as a delivery-route demonstration.
- **The narrow-corridor LiDAR demo is a hybrid scenario.** Its README documents one RMF-managed robot and a second directly commanded robot. Use the hotel route first; demonstrate predictive multifleet optimization only after establishing a suitable all-RMF-managed baseline.
- **Simulation clocks reset.** Record an episode/run ID and both simulation and wall-clock timestamps. Independent scenarios should get independent namespaces, transport/domain isolation, and clean restarts.

These findings favor a **mission copilot and operational diagnosis first**, followed by camera-based inspection and predictive fleet optimization.

## 4. What OpenShift AI contributes today

### 4.1 Version-aware capability map

The component status below is from the **x86_64** table in the current supported-configurations article. “GA” applies to the platform component, not automatically to a third-party robotics application or every upstream feature. [S01]

| Capability | 3.3 | 3.4 | 3.5 | Robotics relevance |
|---|---|---|---|---|
| AI Pipelines | GA | GA | GA | Reproducible data preparation, training, evaluation, and release workflows |
| KServe | GA | GA | GA | Serve predictive, vision, and language models through APIs |
| MLflow | Technology Preview | GA | GA | Track experiments; instrument and compare AI application runs |
| Feature Store / Feast | GA | GA | GA | Reuse consistent fleet/robot features for training and inference |
| Kubeflow Trainer v2 | GA | GA | GA | Distributed training through `TrainJob` and training runtimes |
| KubeRay | GA | GA | GA | Distributed preprocessing, experiments, and custom simulation orchestration |
| TrustyAI / LM-Eval | GA | GA | GA | Model monitoring and language-model evaluation tooling |
| NeMo Guardrails | Technology Preview | GA | GA | Language-application constraints; separate from motion execution |
| Models as a Service | Technology Preview | GA | GA | Shared enterprise model access and consumption controls |
| Distributed inference / llm-d | GA | GA | GA | Large shared LLM capacity if demand justifies it |
| AI Hub | GA | GA | GA | Discover and organize model assets |
| AutoML / AutoRAG | Not listed | Technology Preview | Technology Preview | Optional experimentation, not required for initial demos |
| EvalHub | Not listed | Not listed | Technology Preview | Optional evaluation exploration |

**Reference deployment:** OpenShift AI 3.5 supports OpenShift **4.19.9+, 4.20, 4.21, and 4.22** in the matrix. Distributed inference with llm-d requires OpenShift **4.20 or later**. Start with a single model-serving instance for the copilot; the demo does not need distributed LLM serving. [S01]

**Architecture matters:** ARM support is not identical to x86_64 support. For example, the 3.5 ARM table does not list MLflow or MLServer. A central x86_64 AI platform can train and serve centrally while packaging different inference artifacts for each robot/site hardware class. Do not infer a full on-robot OpenShift AI stack from aarch64 support alone. [S01]

**Training API choice:** Use Trainer v2 for new distributed-training work. Training Operator v1 is deprecated, with a component-specific support cutoff described in the matrix. Component lifecycle can differ from the overall product release lifecycle. [S01, S03, S08]

### 4.2 Model/runtime selection

| Model workload | Practical starting choice | Integration detail |
|---|---|---|
| Mission intent, incident explanation, runbook assistance | A small instruction model with demonstrated tool/structured-output quality, served by the supported vLLM runtime | The installed model, parser, template, and runtime version must work together; JSON validity does not establish mission correctness |
| ETA, battery consumption, anomaly scoring | Gradient-boosted trees or scikit-learn/ONNX models through MLServer | Good CPU-first option; lower resource cost and easier baseline comparison |
| Object detection and inspection | An ONNX detector via an appropriate supported runtime, or Intel-optimized OpenVINO deployment | Pre/postprocessing, coordinates, confidence handling, and camera integration are application code |
| Complex vision ensembles or hardware-specific engines | Triton or a custom runtime where needed | Triton is listed as **tested and verified**, which is a different support category from a directly supported runtime |
| Learned robot action policies | Custom PyTorch/policy runtime or on-device inference process | Requires temporal state, observation/action synchronization, robot adapters, and hardware evaluation |

The current matrix lists MLServer support for scikit-learn, XGBoost, LightGBM, and ONNX; it also lists an NVIDIA GPU MLServer runtime for ONNX and OpenVINO Model Server. vLLM accelerators and model compatibility are governed by the relevant runtime/support matrices. [S01, S04, S05, S26]

The Red Hat video-monitoring quickstart has both CPU/OpenVINO and GPU/KServe-Triton paths. It provides useful application code, but its gRPC configuration and hardware claims should not be copied into a different supported runtime profile without validation. A ROS-to-model adapter should explicitly implement the protocol available in the selected deployment. [S12, S13]

### 4.3 Where platform responsibility ends and robotics engineering begins

| Layer | Responsibility |
|---|---|
| OpenShift | Workload deployment, networking, access control, resource allocation, storage integration, application observability |
| OpenShift AI | Model development, training/pipelines, model metadata, inference serving, AI evaluation/monitoring capabilities |
| Open-RMF | Fleet tasks, traffic schedules, fleet adapters, building coordination |
| Nav2 / robot autonomy | Localization, path planning, local navigation, recovery, velocity execution |
| Zenoh | Configured robotics communication between hosts/pods/sites |
| Proposed application services | Mission semantics, telemetry normalization, inference adapters, inspection-to-task rules, incident correlation, business-system connectors |
| Complementary fleet tooling | Site-cluster lifecycle and on-device OS/application/model distribution |

OpenShift AI provides reusable AI infrastructure; **robot management semantics are implemented through RMF and application integrations**. There is no out-of-the-box ROS subscription, robot task planner, hardware driver, or physical fleet digital twin established by the researched product sources.

## 5. Prioritized customer use cases

Ratings are qualitative judgments for this repository: **H = high, M = medium, L = low**. Demo effort assumes the documented navigation baseline is reproducible. Model lifecycle is a foundation for the other use cases, even though the visible copilot can be delivered first.

| ID | Use case | Customer value | OpenShift AI visibility | Fit with current demo | Additional demo effort | Priority |
|---|---|---|---|---|---|---|
| U1 | Natural-language fleet copilot | H | H | H | Low–medium | First visible demo |
| U2 | Mobile visual inspection and response | H | H | M | Medium | First business-outcome demo |
| U3 | Incident diagnosis and predictive health | H | H | H for diagnosis; L for physical health | Medium | Pair diagnosis with U1 |
| U4 | Predictive ETA and congestion-aware mission release | H | H | M | Medium–high | Second wave |
| U5 | Learned energy use and charging coordination | M–H | H | L | Medium–high | After telemetry |
| U6 | Robot AI lifecycle and continuous improvement | H | Very high | H | Medium | Foundational |
| U7 | Multisite, site-local inference and version governance | H | H | M | High with real edge hardware | Platform-scale demo |
| U8 | Human-aware semantic navigation | M–H | H | M | High | After inspection |
| U9 | Learning robot skills / VLA policies | Potentially H | Very high | L | Very high | Research track |

### U1. Natural-language fleet copilot

**Detailed follow-up:** [U1 Fleet Copilot: Detailed Design and Gated Implementation Proposal](fleet-copilot-design-and-implementation-proposal.md) develops the external-model-first architecture, RMF lifecycle/recovery contracts, local OpenShift AI migration, and phase-by-phase acceptance gates.

**Customers and buyers:** Hospitals, hotels, campuses, warehouses; operations managers, dispatch supervisors, and robotics integrators.

**Problem:** Fleet interfaces require specialist knowledge, and users need to consult multiple screens to understand mission status.

**Proposed workflow:**

1. User says: “Send the robot from the lobby to the third-floor middle hallway and bring it back.”
2. An LLM produces a typed mission intent using destinations returned by a live lookup tool.
3. A mission service checks destination existence, task capability, user/site scope, current state, and duplicate request identity.
4. The service translates the intent into the pinned RMF task schema and records the resulting task ID.
5. The copilot answers “Where is it?” and “Why is it waiting?” using actual mission and lift events, including their timestamps.

**AI role:** Language interpretation and evidence-based explanation. RMF remains responsible for task allocation and execution. Structured output/tool calling is available in vLLM, but the caller still implements and executes the tools. [S14, S15, S26]

**OpenShift value:** Host the copilot, gateway, RMF integration, state service, and business-system connectors with shared identity and deployment practices.

**OpenShift AI value:** Serve a private model, compare model/prompt configurations, record experiments/traces, and manage model versions. MaaS becomes useful when multiple sites or applications share language models. [S01, S02]

**Demo:** Reuse the hotel patrol route. Show the natural-language request, the typed mission, actual RMF task acceptance, lift travel, and task completion. For an unknown location, ask the user to select a known destination rather than inventing coordinates.

**Baseline and KPIs:** Compare with the existing CLI/dashboard workflow. Measure operator interaction time, correct destination/task interpretation, duplicate tasks per retried request, status-answer freshness, and end-to-end task completion.

**Proposed acceptance target:** At least 95% correct interpretation on a held-out set of 100 supported paraphrases; every accepted submission linked to an RMF task ID; repeated transport retries create no duplicate mission. Report navigation failures separately from language errors.

**Engineering needed:** Mission API, destination catalog, RMF request/result adapter, persistent task state, model client, simple UI. Voice input is an optional later addition, not needed to prove the use case.

### U2. Mobile visual inspection with an operational response

**Customers and buyers:** Manufacturers, logistics operators, utilities, facility managers; quality leaders, site operations, maintenance teams.

**Problem:** Inspection coverage is inconsistent, and visual findings are separated from workflows that resolve them.

**Proposed workflow:** An RMF patrol visits inspection points. Camera frames are analyzed by a detector or inspection model. The application associates findings with robot pose, floor, location, and mission; records evidence; and generates a facility work item or follow-up task.

**Initial targets:** Blocked corridor, missing inventory tote, missing asset, or a visible status indicator. Use one clearly observable condition. Spill detection or subtle defect classification needs domain-specific data and should be a separately evaluated extension.

**AI role:** Detection/classification; optional vision-language explanation of selected evidence. Run a small detector frequently and invoke a larger model only for relevant frames or operator questions.

**OpenShift value:** Connect mobile sensing, fleet coordination, persistent evidence, and facility/WMS/MES/CMMS applications.

**OpenShift AI value:** Fine-tune and serve inspection models, run held-out evaluation, track versions, and compare deployment performance. The Red Hat multimodal quickstart supplies reusable video ingestion, detection, tracking, storage, annotation, and conversational analytics patterns. Its extension to moving robot cameras and spatial context is proposed work. [S12, S13]

**Demo:** Add a robot-view camera to the hotel. Place a recognizable object at an L3 inspection waypoint. The robot visits, detects the object, records a timestamped finding, and creates a work item. If no alternate route exists, demonstrate a wait/escalation; use a world with a validated alternative route for rerouting.

**Baseline and KPIs:** Manual inspection or scheduled patrol with manual video review. Measure precision/recall on customer-relevant examples, false alerts per inspection hour, inspection coverage, time from finding to work-item creation, and operator review time.

**Proposed acceptance target:** Report per-condition precision/recall on a location/session-held-out set; every finding includes image evidence and spatial/time context; repeated frames of one condition are deduplicated into one incident. Set required accuracy with the customer rather than using general object-detection benchmark scores.

**Engineering needed:** Camera and calibration, bridge/topic routing, image preprocessing, inference client, spatial association, incident persistence/deduplication, and one workflow connector. Reuse quickstart components selectively rather than importing its full application stack.

### U3. Evidence-based incident diagnosis, progressing to predictive health

**Customers and buyers:** Robot operators and fleet OEMs; service operations, site reliability teams, maintenance leaders.

**Problem:** A late robot could be waiting for a lift, blocked by an obstacle, poorly localized, disconnected, or affected by a failed pod. Operators often investigate each layer separately.

**Proposed workflow:**

- Normalize task, navigation, localization, lift, Zenoh connectivity, and OpenShift workload events.
- Build a mission timeline and use deterministic signals to identify known fault classes.
- Retrieve relevant runbooks and recent evidence for an LLM to explain the likely cause and next action.
- Add a learned anomaly detector when historical data supports it.
- Add physical predictive-maintenance models after acquiring motor current, temperature, vibration, battery and service-history data.

**AI role:** Explanation and runbook retrieval immediately; anomaly classification later; remaining-useful-life estimates only with appropriate real failure history.

**OpenShift value:** Consolidated application/platform observability and repeatable service recovery workflows.

**OpenShift AI value:** Serve diagnostic and anomaly models, run evaluation pipelines, track experiments and input distributions. TrustyAI provides drift metrics, but application-specific temporal and sensor-quality monitoring still needs implementation. [S01, S10]

**Demo:** Introduce controlled lift delay and a separate simulated telemetry outage. Ask “Why is robot_1 late?” The application produces different, evidence-backed explanations. Show telemetry age explicitly so an old robot state is not presented as a live position.

**Baseline and KPIs:** Dashboard/log-based diagnosis and a deterministic rule-only classifier. Measure diagnosis correctness, time to diagnosis, evidence citation correctness, false alarms, and mean time to restore service. Evaluate whether the LLM improves operator comprehension beyond a structured event timeline.

**Proposed acceptance target:** Correctly distinguish at least four controlled fault classes; every factual diagnosis references event IDs/time ranges; detect absent/stale evidence and state that the cause is unresolved. Synthetic anomaly data demonstrates the integration, not predictive-maintenance accuracy.

**Engineering needed:** Event collectors, correlation IDs, telemetry freshness, runbook index, diagnostic rules/model, and incident UI. Most of the first demo can use data already present in the hotel execution path.

### U4. Predictive ETA and congestion-aware mission release

**Customers and buyers:** Warehouse/3PL operators, hospitals, airports, large facilities; throughput and service-level owners.

**Problem:** A feasible mission can still miss a service target because travel and shared-infrastructure delays vary by time, zone, and fleet load.

**Proposed workflow:** Train a travel/lift-wait-time model using segment durations and conditions available at decision time. A policy service uses predictions to sequence or release business missions, recommend staging positions, or warn that a target ETA is unlikely. RMF still computes feasible traffic schedules and allocates tasks.

**AI role:** Probabilistic travel-time and queue-delay prediction. Use gradient-boosted trees and quantile estimates before considering reinforcement learning.

**Integration detail:** Begin with an external mission-release policy. Replacing RMF bidding costs or injecting learned lane costs is a deeper adapter/scheduler integration that must be tested against the pinned RMF API. It is not established by simply hosting a model.

**OpenShift value:** Run fleet, forecast service, demand/WMS connector, scenario jobs, and business metrics together.

**OpenShift AI value:** Train and serve the prediction model, preserve feature definitions, evaluate it against historical baselines, and track experiments. Feast becomes useful when the same operational features are needed by multiple models. [S01, S09, S11]

**Demo:** First show a delayed lift producing a better ETA forecast on the one-robot hotel route. Then add multiple RMF-managed robots/tasks and compare fixed release order with prediction-informed release on identical scenario seeds and demand schedules.

**Baseline and KPIs:** Ordinary RMF scheduling plus historical median segment ETA; compare against a simple hand-tuned release heuristic as well. Measure ETA MAE/p90 error, on-time completion, queue delay, tasks per robot-hour, and mission wait time by priority class.

**Proposed acceptance target:** Demonstrate a consistent reduction in held-out ETA error. Claim throughput improvement only if paired scenario runs show it without shifting unacceptable delays onto lower-priority tasks. AI value is incremental to RMF, not credit for RMF's existing coordination.

**Engineering needed:** Segment-event extraction, operational dataset, workload generator, model endpoint, mission-release policy, and a multi-robot baseline suitable for comparison.

### U5. Learned energy use and charging coordination

**Customers and buyers:** Large AMR fleets, distribution centers, hospitals; fleet operations and asset management.

**Problem:** Fixed battery thresholds can cause premature charging, charger queues, or tasks assigned without sufficient energy margin.

**Proposed workflow:** Predict mission energy consumption from route, payload, stops, robot type, and battery condition. An energy policy combines these predictions with existing RMF charging and battery constraints to recommend mission eligibility and charging windows.

**AI role:** Energy forecasting and battery-health estimation. RMF already models battery/charging concepts, so the incremental value must be demonstrated against its configured battery-aware baseline, not against a battery-unaware strawman.

**OpenShift value:** Integrate charger state, fleet state, maintenance records, and enterprise demand.

**OpenShift AI value:** Train and serve regressors and health models; reuse features; evaluate fleet-specific error and drift.

**Demo:** Add a calibrated simulation energy model with explicit synthetic labels. Replay the same demand with fixed/standard battery settings and learned consumption estimates. A real-robot pilot then replaces synthetic voltage/current/SOC with measured values.

**Baseline and KPIs:** RMF battery-aware task allocation and fixed charging thresholds. Measure energy prediction error, mission refusals/interruptions, charger queue time, productive robot-hours, and energy per completed task.

**Engineering needed:** Real or modeled battery discharge, charger state, payload and route telemetry, calibrated battery constraints, and policy integration. Current constant SOC is insufficient for this demonstration.

### U6. Robot AI lifecycle and continuous improvement

**Customers and buyers:** Robot OEMs, integrators, operators with multiple sites; platform engineering and AI/robotics engineering leaders.

**Problem:** Models perform differently at different sites, and manual updates make it difficult to know which data, model, runtime, and map produced a result.

**Proposed lifecycle:**

```text
robot observations/events
  → selected recordings and labeled examples
  → dataset validation and versioned manifest
  → model training/fine-tuning
  → offline evaluation + isolated simulation + target-hardware checks
  → model metadata registration + immutable artifact publication
  → shadow inference
  → site/robot-cohort deployment
  → outcome monitoring
  → improved dataset and next candidate
```

**OpenShift value:** Reproducible jobs, artifact builds, GitOps desired state, deployment reconciliation, and site-specific configuration.

**OpenShift AI value:** Workbenches, AI Pipelines, Trainer v2/KubeRay where justified, MLflow, model registry/catalog, inference serving, and model monitoring. ROS recordings become pipeline inputs through custom processing components. [S06–S10, S19, S20]

**Important distinction:** A **model registry stores metadata and references**; model weights live in object storage, PVCs, or OCI artifacts. Registry metadata alone does not create a robot rollout or an enforced promotion rule. The pipeline and delivery controller implement those behaviors. [S04, S07, S24]

**Demo:** Model v1 misses a visually changed inspection condition. Label selected new observations and train v2. Show improvement on a held-out set, registered lineage, shadow comparison, and promotion for one site/robot cohort. Introduce a v3 candidate that regresses and demonstrate rejection or a controlled rollback.

**Baseline and KPIs:** Manual notebook-to-container deployment. Measure candidate-to-deployment elapsed time, reproducibility, lineage completeness, validation failures caught before deployment, rollout/rollback time, and performance by site/model version.

**Proposed acceptance target:** Every deployed version resolves to data manifest, training configuration, evaluation results, artifact digest, and runtime version. Rejected candidates do not become the deployed desired state. Shadow inference never creates a second robot command stream.

**Engineering needed:** A real pipeline with data/model checks, model metadata integration, artifact publication, a GitOps application or edge delivery path, and outcome-based deployment metrics. This is the strongest demonstration of value specific to OpenShift AI beyond ordinary container hosting.

### U7. Multisite operations with site-local inference

**Customers and buyers:** Retail/logistics chains, manufacturers, hospitals, utilities; central IT, site operations, and robot-service providers.

**Problem:** Centralized intelligence can become unavailable during network interruptions, and hundreds of sites can accumulate incompatible software/model versions.

**Proposed architecture:** Train and evaluate centrally. Run required inference and fleet coordination at the customer site; retain robot-local execution. Distribute hardware-appropriate artifacts to sites/devices and aggregate selected events when connected.

**OpenShift value:** Consistent site-cluster applications; GitOps for desired state; optional Advanced Cluster Management for managing multiple clusters. Device/OS management is a separate layer—Flight Control illustrates an agent-based device management approach. Product availability and support depend on the chosen commercial offering. [S20–S22]

**OpenShift AI value:** Central model development and lineage; site model serving where a supported OpenShift AI topology is appropriate; shared model access where remote calls are acceptable.

**Product constraint:** The current support matrix explicitly supports OpenShift AI on Single Node OpenShift and explicitly excludes an OpenShift AI Self-Managed installation on MicroShift. A lightweight MicroShift/Podman device can consume packaged inference artifacts without being described as running the full OpenShift AI product. [S01]

**Demo:** Two simulated site deployments, each with local mission state and a resident inspection model. Interrupt the central link. Site-local inference and an already executable mission continue under the defined local policy. Restore the link, synchronize stored findings without duplicates, and roll a new model to site A before site B.

**Baseline and KPIs:** Central-only inference and manual site updates. Measure useful operation during network loss, telemetry reconciliation, bytes transferred, site-version visibility, deployment success, and rollback recovery time.

**Engineering needed:** Site-local storage and services, bounded buffering, model preloading, command expiry/idempotency, hardware variants, and delivery orchestration. Two namespaces can demonstrate software isolation; they do not prove WAN or physical edge-device performance.

### U8. Human-aware semantic navigation

**Customers and buyers:** Hospitals, airports, hospitality, public-facing logistics; facility operations and service quality teams.

**Problem:** Geometrically traversable routes may be operationally inappropriate because a corridor is crowded, an inspection zone is active, or a route passes through a sensitive area.

**Proposed workflow:** A perception service produces spatially grounded semantic observations. A policy service maps those observations to temporary route restrictions, zone preferences, or mission release decisions through supported Nav2/RMF interfaces.

**AI role:** Semantic perception and, where justified, prediction of crowd/zone occupancy. Route and motion execution remain in the robotics stack.

**OpenShift value:** Connect robots and building context; deploy perception/policy services consistently.

**OpenShift AI value:** Train and serve perception models and monitor accuracy under changing site conditions.

**Demo:** A camera identifies congestion in a mapped zone; the system uses a validated alternate corridor, waits, or defers a mission. Compare mission completion and excessive rerouting with a LiDAR-only/static-policy baseline.

**KPIs:** Semantic detection accuracy, stale-zone events, unnecessary restrictions, travel time, and operator interventions. Measure geometry/transform correctness separately from model accuracy.

**Engineering needed:** Calibrated camera/depth/pose association, temporal persistence, zone mapping, restriction expiry, and pinned API integration. An image bounding box is not automatically a metric obstacle or an RMF lane restriction.

### U9. Learning robot skills and vision-language-action policies

**Customers and buyers:** Robot OEMs, manufacturing integrators, R&D teams; robot-learning engineering and product development.

**Problem:** New manipulation tasks require demonstrations, training, and physical evaluation that are difficult to reproduce and scale.

**Proposed workflow:** Collect synchronized demonstrations, train or fine-tune a policy, evaluate in suitable simulation and on representative hardware, and distribute a policy plus its normalization/preprocessing configuration to a robot execution process.

**Research basis:** LeRobot provides PyTorch policies, a synchronized video/state/action dataset format, training, simulation evaluation, and hardware adapters. This is a credible ecosystem integration path, not evidence of a packaged LeRobot/OpenShift AI or VLA/RMF integration. [S18]

**OpenShift value:** Dataset services, simulation/training jobs, hardware-test coordination, artifact builds, and delivery.

**OpenShift AI value:** GPU workbenches, experiment tracking, distributed training, evaluation pipelines, policy metadata, and serving infrastructure where suitable.

**Demo:** Add a manipulator and a simple pick/place skill. RMF can coordinate travel to a workcell; a custom task action hands off to the manipulation runtime and reports completion. The existing TurtleBot navigation demo does not provide that robot, workcell, or action interface.

**KPIs:** Skill success on held-out objects/conditions, demonstrations required, train-to-evaluate time, target-device latency, and intervention rate.

**Engineering needed:** Manipulator hardware or a suitable simulator, demonstrations, robot/policy adapters, temporal observation/action processing, and hardware evaluation. A generic LLM vLLM endpoint is not interchangeable with a stateful action-policy runtime.

**Recommendation:** Maintain this as a research/partner track after U1–U7 establish the platform story. Navigation and inspection have a much shorter path to a credible customer demonstration.

## 6. Reference architecture

### 6.1 Development and deployment topology

```text
                        CENTRAL / DEVELOPMENT OPENSHIFT
  ┌──────────────────────────────────────────────────────────────────────┐
  │ OpenShift AI                                                        │
  │ Workbenches → AI Pipelines → training → evaluation → model metadata │
  │                     │                           │                   │
  │              versioned datasets          model artifacts            │
  │                     │                           │                   │
  │ Object storage / recording store      OCI registry or object store  │
  │                     │                           │                   │
  │ Isolated Gazebo scenarios + hardware evaluation jobs                │
  │                                                                     │
  │ GitOps desired state / optional multicluster and device management  │
  └───────────────────────────────────┬──────────────────────────────────┘
                                      │ applications/models/config
                                      ▼
                              SITE OPENSHIFT
  ┌──────────────────────────────────────────────────────────────────────┐
  │ Operator / WMS / MES / facility system                               │
  │                 │                                                   │
  │ Copilot / workflow service ↔ model endpoints                        │
  │                 │                 language / vision / predictive ML │
  │                 ▼                                                   │
  │ Mission gateway ↔ RMF integration ↔ rmf-core                         │
  │                         │                 │                         │
  │ Telemetry/state/evidence store          Zenoh router                 │
  │            ▲                              │                         │
  │            └──────── robotics observations/events ──────────────────┤
  └───────────────────────────────────────────┬──────────────────────────┘
                                               │ configured robot link
                                               ▼
                                    PHYSICAL ROBOT
          Robot-local ROS 2 + Nav2 + local perception where needed
          Drivers, sensors, localization, motion execution, watchdogs
```

For the current simulation, `hotel-sim` and `robot-nav-robot-1` represent the robot/environment within OpenShift. For a physical deployment, place latency-sensitive navigation and motion execution on the robot or a validated local execution environment. Fleet/AI services remain site-local or central according to response-time and continuity needs.

Zenoh's upstream bridge supports ROS topics, services, and actions. The repository's command/result relay is a local integration choice; do not generalize its earlier action-response difficulties into an assertion that Zenoh cannot bridge actions. Retain the proven relay initially and add AI at the RMF task boundary. [S14, S16]

### 6.2 New application services

| Service | Responsibility | Initial implementation |
|---|---|---|
| `mission-gateway` | Stable business mission contract, destination resolution, idempotency, RMF submission | Small HTTP service with persistent request/task mapping |
| `robot-state-collector` | ROS/RMF event normalization, freshness, clock/episode context | ROS 2 process with the existing bridge pattern; explicit topic/QoS mapping |
| `fleet-state-api` | Current mission/robot/building state plus event history | Database-backed API; bounded live snapshots |
| `robot-inference-adapter` | Prepare camera/feature data, call model endpoint, attach spatial/time/version metadata | ROS-aware edge/site process with bounded queues |
| `fleet-copilot` | Language UI and model/tool orchestration | Model client plus typed fleet tools |
| `inspection-workflow` | Detection persistence, deduplication, business response | Event-driven service with a facility connector |
| `robot-ai-pipeline` | Dataset preparation, training, evaluation, artifact metadata and release evidence | Kubeflow-based AI Pipeline with containerized steps |

These names describe proposed components; they are not already implemented in this repository.

**Namespace proposal:** Keep the documented robotics namespace, add a project for AI development, and a site-serving/application project with explicit network connections. Use additional isolated namespaces for evaluation episodes. A namespace alone does not isolate ROS domains, clocks, or Zenoh keyspaces; configure all three.

### 6.3 Interface contracts

Start with a small tool/API surface:

| Proposed operation | Returns or performs |
|---|---|
| `list_destinations(site_id)` | Exact supported location IDs, floors, and aliases |
| `get_robot_state(site_id, robot_id)` | Timestamped pose/floor, mission, navigation state, freshness |
| `get_mission(task_id)` | Acceptance, assignment, execution and completion state |
| `submit_patrol(...)` | One mission submission and its RMF task ID |
| `cancel_mission(task_id)` | Version-validated RMF cancellation and recorded outcome |
| `get_incident_evidence(task_id, time_range)` | Relevant event IDs and measurements |

Expose these over ordinary typed HTTP APIs; MCP is useful if the selected agent clients benefit from tool discovery/interoperability. MCP does not supply RMF semantics—the fleet tool server must implement them. [S27]

Example **application-level** mission envelope, not an upstream RMF request schema:

```json
{
  "request_id": "mission-demo-001",
  "site_id": "hotel-demo",
  "task_type": "patrol",
  "places": ["lobby", "L3_middle_hallway", "lobby"],
  "rounds": 1,
  "clock_context": "simulation",
  "episode_id": "hotel-run-042"
}
```

The gateway constructs the pinned RMF schema in application code, publishes in the correct ROS domain using the required QoS, and tracks the actual response. RMF task acceptance, robot assignment, navigation success, and business-task completion are different states and should be shown separately.

For model-produced events include:

```text
site_id, robot_id, mission_id, episode_id
sensor_timestamp, received_timestamp, clock_context
floor_id, pose, frame_id, transform/calibration version
model_id, model_version, artifact digest, preprocessing version
prediction, confidence/uncertainty, evidence reference
```

### 6.4 Response-time and failure behavior

| Function | Placement/design principle |
|---|---|
| Motion execution and immediate obstacle reaction | Robot-local; never wait for a WAN model request |
| Camera inference supporting immediate local decisions | On-device or validated site-local execution, with explicit freshness limits |
| Mission-language interpretation | Site or central service; seconds-scale interaction is normally acceptable |
| ETA, health forecasts, and incident summaries | Asynchronous/site or central; retain timestamps and uncertainty |
| Training, dataset preparation, and simulation evaluation | Central batch resources; not in the motion path |

Use bounded inference queues, drop obsolete images, and enforce event expiry. If a model is unavailable, ordinary RMF/Nav2 operation can continue for missions that do not require that model. If a required inspection action cannot execute, report the action failure instead of completing the task falsely.

The Nav2 Collision Monitor is useful for the current obstacle-stop demonstration, but upstream explicitly says it does not provide hard real-time safety certification. It should be described accurately as a local collision-monitoring component, with physical robot protection provided by the customer's robot platform. [S17]

Stateless model/API replicas can be scaled. Stateful RMF processes need state ownership and recovery design; adding replicas does not automatically provide valid fleet failover. Likewise, replacing a failed pod restores a software process, not necessarily a physical robot's mission state.

## 7. Data strategy and evaluation

### 7.1 Initial operational dataset

| Dataset | Sources | Useful labels/targets |
|---|---|---|
| Mission lifecycle | RMF requests/responses, assignment and execution events | Completion, lateness, segment duration |
| Navigation | Command/result IDs, localization/odom, recovery events | Failure type, recovery count, progress |
| Building infrastructure | Lift/door states and requests | Lift wait, door wait, unavailable infrastructure |
| Transport/platform | Link state, message age, pod/service metrics | Disconnection, stale telemetry, process restart |
| Inspection | Robot-view images plus calibration and pose | Condition class, location, persistence, resolution |
| Physical health, later | Battery current/voltage/SOC, temperatures, motor signals, service records | Energy use, labeled degradation/failure |

Record selected ROS data locally in rosbag2/MCAP and upload immutable recordings or event windows to object storage. Export structured feature tables for predictive models; keep images and sequence data with their metadata for perception/policy training. ROS bag recording/playback is an upstream tool, not an OpenShift AI feature. Pin to the repository's ROS release because upstream rolling options can differ. [S19]

### 7.2 Evaluation that can support customer claims

- **Split by episode, recording session, location, robot, or time.** Adjacent frames/segments from one run should not leak across training and evaluation.
- **Separate simulation ground truth from deployment features.** Gazebo exact poses or scripted fault labels can be used for evaluation, but not as features if they will not exist on the physical robot.
- **For prediction, use information available at decision time.** Final task duration and eventual lift delay are labels, not input features for the original ETA.
- **Use paired scenario runs.** Compare baseline and AI policy under matched seeds, tasks, map versions, and resources. Report variation and failed episodes.
- **Evaluate end-to-end outcomes.** Higher detection accuracy alone is insufficient if false incidents, stale transforms, or slower inference make operations worse.
- **Compare against simple alternatives.** A lookup table, rules engine, historical median ETA, or standard RMF policy may solve a small demonstration equally well. Train a model when varying conditions justify it.
- **Treat drift as a trigger to investigate.** Input drift does not prove loss of model quality; new labeled examples and outcome checks establish that.
- **Evaluate physical hardware separately.** Gazebo software-rendered timing and synthetic battery signals do not establish robot latency or energy performance.

## 8. Three concrete customer demonstration packages

### Demo A — “Ask, dispatch, and explain”

- **Audience:** Operations leaders and robotics integrators.
- **Assets reused:** Federated hotel, multi-level route, task API, lift/navigation states.
- **Narrative:** “Make robot operations accessible while retaining observable, structured execution.”

1. Display the four robotics workloads and the AI model endpoint.
2. Enter the L1-to-L3-and-return mission in ordinary language.
3. Display resolved waypoints and the actual RMF task ID.
4. Watch lift use and mission progress in Gazebo and the event timeline.
5. Introduce a controlled lift delay; ask why the mission is late.
6. Display the lift event/time evidence supporting the explanation.
7. Ask for an unsupported destination; demonstrate resolution against the real destination catalog.
8. Compare operator interaction/diagnosis time with the baseline workflow.

**Customer takeaway:** A private AI service can connect to an existing robot fleet and reduce operational friction. The platform gives a reproducible deployment and an observable task outcome.

### Demo B — “Inspect, improve, and roll back”

- **Audience:** Manufacturing/facility quality teams and AI/platform engineering.
- **New assets:** Robot camera, one labeled condition, inference adapter, model pipeline, deployment overlay.
- **Narrative:** “The customer can adapt robot intelligence to a changing site using a repeatable lifecycle.”

1. Robot completes an inspection patrol and generates spatially grounded findings.
2. Introduce a new visual variant that v1 handles poorly.
3. Show selected recordings, annotation, and a held-out evaluation set.
4. Execute the data/training/evaluation pipeline and show v2 lineage.
5. Run v2 in shadow on the same frames; show performance/latency comparison.
6. Promote the candidate for a selected robot/site cohort via desired-state deployment.
7. Demonstrate rejection of a regressing v3 or rollback using application outcome metrics.
8. Display that the active fleet uses the expected model/runtime/map versions.

**Customer takeaway:** Models become maintainable operational assets rather than files copied manually to robots.

### Demo C — “Meet the service target under variable demand”

- **Audience:** Logistics and large-facility operations; IT leaders responsible for rollout scale.
- **New assets:** Multi-robot baseline, demand generator, segment dataset, forecast service, mission-release policy.
- **Narrative:** “Prediction improves reliability, and site-local deployment preserves useful operation during connectivity loss.”

1. Run ordinary RMF with historical-median ETAs under a recorded demand pattern.
2. Run the same scenarios with learned ETA and mission-release recommendations.
3. Show ETA error, lateness, completed tasks, wait time, and inference cost.
4. Repeat across enough matched episodes to show variability rather than one favorable run.
5. At a site-local deployment, interrupt central connectivity and demonstrate resident-model operation and event reconciliation.

**Customer takeaway:** Business improvement is measurable and deployment continuity is designed into the application.

## 9. Implementation roadmap

These are planning estimates, not commitments. Assume two engineers spanning robotics/application integration and AI/platform work, an accessible OpenShift AI environment, and a reproducible existing hotel route. Real-robot procurement, site data collection, and customer-system integration add separate lead time.

| Phase | Indicative duration | Deliverables | Exit evidence |
|---|---|---|---|
| 0. Establish baseline and data | 1–2 weeks | Confirm cluster/version/resources; repeat hotel route; normalize mission/lift/nav events; baseline timing | Repeated traceable missions; correlated, timestamped dataset |
| 1. Mission copilot and diagnosis | 2–3 weeks | Model endpoint, mission gateway/state API, destination tool, UI, controlled fault cases | Demo A; held-out intent results; diagnosis evidence |
| 2. Inspection and AI lifecycle | 3–5 weeks | Robot camera, one detector/condition, labeled data, pipeline, model metadata, GitOps delivery | Demo B; held-out quality/latency; demonstrable lineage and rollback |
| 3. Forecast and scale | 3–5 weeks | Demand generator, all-RMF-managed multi-robot baseline, ETA model, mission-release policy | Paired scenario results; measured improvement beyond RMF/heuristics |
| 4. Edge/customer pilot | Scope after discovery | Representative robot/site hardware, resident inference, distribution and actual workflow connector | Hardware results, network-loss behavior, customer KPIs |

Phases can overlap once the common telemetry contracts stabilize. U5 and U9 should not be placed on the critical path for the initial customer demonstrations.

### Suggested repository additions for implementation

```text
services/mission-gateway/             business mission API and RMF adapter
services/fleet-state/                 state/event API and collectors
services/fleet-copilot/               language interface and typed tools
services/inspection-workflow/        findings and facility integration
robot_ai/                            ROS inference/recording adapters
pipelines/robot-ai/                   data, training, and evaluation steps
models/                              model cards/configuration and metadata references
scenarios/ai-robotics/                repeatable fault/inspection/demand episodes
helm/robot-ai-demo/                   AI application/serving integration overlay
docs/                                scenario runbooks and measured results
```

Start by extracting integration patterns from `demo/dispatch_multilevel_task.py`, instrumenting `entrypoints/nav2_relay.py`, and adding explicit collector routing around `helm/multi-robot-demo/templates/configmap-zenoh.yaml`. Image routing requires a sensor producer as well as transport configuration.

## 10. Resource and cost considerations

### 10.1 Sensible initial footprint

These are **application planning envelopes**, excluding OpenShift/OpenShift AI platform requirements and the existing robotics workload. They are not benchmark results.

| Workload | Initial planning envelope | What to measure |
|---|---|---|
| Mission/state APIs and collectors | Approximately 2–4 vCPU and 4–8 GiB total for a small demo | Event throughput, storage growth, request latency |
| Tabular predictive models | CPU serving; roughly 1–2 vCPU and 1–4 GiB per small service | p95 inference time, model size, concurrency |
| Small language model | A compatible GPU with roughly 24–48 GiB as an initial sizing candidate, depending on model precision and concurrency | Actual memory, input length, KV cache, p95 latency, tool accuracy |
| One low-rate inspection feed | CPU ONNX/OpenVINO first where appropriate; GPU if measured needs justify it | Resolution/FPS, preprocessing, inference, response age |
| Training/evaluation | Separate batch allocation; scale only with observed training needs | Completion time, resource-hours, queue wait |

A 4B–8B model's parameter count alone is not a sizing rule: precision, runtime support, context length, KV cache, and concurrent requests change memory demand. Benchmark one chosen model and dataset before increasing serving complexity.

Accelerators require the relevant operator/driver integration. NVIDIA's OpenShift GPU Operator documentation covers setup, monitoring, MIG, and time slicing; each has hardware and operational constraints. GPU time slicing should not be treated as equivalent to isolated MIG partitions. [S01, S23]

Keep training and simulation batch jobs from exhausting resources needed by mission services. Kueue helps admit eligible batch/distributed work; ordinary quotas, placement, and scheduling remain necessary for other workloads. Not every AI Pipeline step or arbitrary Gazebo job is automatically a managed distributed workload. [S09]

### 10.2 Bandwidth and data retention

Raw RGB at 640 × 480 × 3 bytes × 10 frames/s is **9,216,000 bytes/s**, approximately **9.2 MB/s or 73.7 Mb/s per camera**, before transport overhead. Twenty such streams would be approximately 1.47 Gb/s. Compression and selective upload therefore matter even for relatively small fleets.

Use local inference, selected event clips, low-rate previews, and structured findings. Measure the real compressed stream rather than deriving a WAN budget from raw images alone. The Zenoh bridge can filter and rate-limit selected robotics traffic, but data selection and evidence-retention rules belong to the application. [S14, S16]

### 10.3 Customer value model

Track value in four buckets:

1. **Operations capacity:** Reduced dispatch, inspection, and diagnosis effort.
2. **Service quality:** More on-time missions, fewer missed inspections, less unresolved downtime.
3. **Engineering productivity:** Shorter model and application release cycles; fewer manual site changes.
4. **Infrastructure efficiency:** Resource-hours, GPU utilization, storage/network use, and inference cost per useful task.

Useful calculations:

```text
operator capacity released = tasks × interaction seconds saved / 3600
inspection capacity released = inspections × review minutes saved / 60
downtime value = avoided downtime hours × customer-specific hourly impact
delivery productivity = successful tasks / active robot-hours
AI unit cost = attributable serving + training + data costs / useful completed tasks
net benefit = operational value + engineering value − incremental platform/AI costs
```

**Illustrative arithmetic only:** 100 missions/day × 45 seconds less operator interaction × 250 days/year releases **312.5 operator-hours/year**. At $45/hour, that is **$14,062.50/year of capacity value** for this one workflow. It is a hypothesis to test, not a cash-saving or robotics ROI claim; deployment costs and realized staffing effects must be included.

Avoid attributing all robot productivity to AI. Show separately what the OpenShift/RMF baseline provides and what the AI integration improves.

## 11. Customer positioning and evidence strength

### 11.1 Buyer-specific message

| Buyer | Message | Best evidence to show |
|---|---|---|
| Operations executive | “Improve inspection coverage and service reliability.” | Findings connected to work items; paired mission KPI comparisons |
| IT/platform leader | “Bring robotics workloads into a consistent enterprise operations model.” | Deployment reconstruction, observability, site versions, rollout/rollback |
| AI engineering leader | “Use operational robot data to improve models through a repeatable lifecycle.” | Data lineage, evaluation pipeline, model metadata, shadow comparison |
| Robotics integrator/OEM | “Keep robot interfaces while standardizing supporting services and AI delivery.” | RMF adapters, Zenoh transport, reusable APIs and hardware-specific model artifacts |

### 11.2 Why this platform can be valuable

- **Against separate notebooks and manually managed robot services:** shared identity, repeatable deployment, persistent data, resource management, and reproducible AI workflows.
- **Alongside robot-vendor fleet managers:** RMF and adapters can coordinate interoperable fleet capabilities while the platform hosts enterprise AI and business integrations. Interoperability still depends on each vendor's available control/state interfaces.
- **For customers already using OpenShift:** robotics services and AI can reuse established platform operations, staff skills, and deployment practices.
- **For distributed sites:** hybrid deployment and artifact portability allow deployment near the customer's data and execution environment, with device-specific optimization where needed.

The differentiator is the **operational integration and supported platform lifecycle**, not the assertion that container deployment or open-source ML is unique to OpenShift.

### 11.3 Evidence we can responsibly cite

| Evidence | What it supports | Limit of the evidence |
|---|---|---|
| Red Hat support matrix | Current component maturity, architectures, runtime categories and topologies | Does not validate this proposed robotics application |
| Multimodal monitoring quickstart | Runnable vision + model serving + storage + language analytics pattern | Moving robot cameras, spatial grounding and RMF responses are new integrations |
| Free Fleet / RMF Web / Zenoh | Documented robotics interfaces and fleet/transport mechanisms | Local patches and physical device integrations still need evaluation |
| LeRobot | Open ecosystem for robot data, policies, training and evaluation | No verified packaged integration with this demo or OpenShift AI |
| DenizBank/Intertech customer case | Enterprise adoption of self-service ML, standardization, GitOps and shared GPU infrastructure | A banking case, not proof of robot throughput or maintenance ROI |

The DenizBank case describes more than 120 data scientists and an on-premises platform across 15 clusters. Its “one week to ten minutes” AI-model time-to-market statement is explicitly an **expectation**, so it should not be repeated as a measured robotics outcome. [S25]

## 12. Decisions for a customer pilot

The research supports beginning with the facility/hotel demonstration. Customer discovery should determine:

1. Which measurable workflow matters most: inspection, dispatch, late missions, downtime, or model rollout?
2. Which robot/vendor interfaces expose task control, current state, images, and physical telemetry?
3. What must operate locally when the central connection is unavailable?
4. Which OpenShift/OpenShift AI version, site topology, and hardware are available?
5. Is labeled operational data available, and does it represent multiple conditions/sites?
6. Which WMS, MES, facility, or maintenance system should receive the robot outcome?
7. What baseline and success criteria will make the pilot commercially convincing?

**Bottom line:** Lead with **fleet copilot + diagnosis** for fast visibility, **inspection + model lifecycle** for strong business and platform value, and **predictive scheduling + site-local rollout** for scale. Use advanced robot learning as an additional research path once the common operations and AI lifecycle foundation is demonstrated.

## References

All sources below were retrieved on October 5, 2026. Moving upstream branches describe mechanisms; the Red Hat support matrix establishes the downstream support status used in this report.

| ID | Source | Contribution |
|---|---|---|
| S01 | [Red Hat OpenShift AI: Supported Configurations for 3.x](https://access.redhat.com/articles/rhoai-supported-configs-3.x) | October 2, 2026 matrix; 3.3/3.4/3.5 statuses, architectures, supported runtimes, SNO/MicroShift distinction |
| S02 | [Red Hat OpenShift AI product page](https://www.redhat.com/en/technologies/cloud-computing/openshift/openshift-ai) | Current MLOps/GenAIOps/AgentOps, hybrid deployment and shared model access positioning |
| S03 | [OpenShift AI Self-Managed lifecycle](https://access.redhat.com/support/policy/updates/rhoai-sm/lifecycle) | Release/support lifecycle and component-specific exceptions |
| S04 | [Documentation source: About model serving](https://github.com/opendatahub-io/opendatahub-documentation/blob/main/modules/about-model-serving.adoc) | KServe/API model serving; S3/PVC/OCI model locations |
| S05 | [Documentation source: Tested and verified runtimes](https://github.com/opendatahub-io/opendatahub-documentation/blob/main/modules/ref-tested-verified-runtimes.adoc) | Distinction between tested/verified and directly supported runtime categories |
| S06 | [Documentation source: Working with AI pipelines](https://github.com/opendatahub-io/opendatahub-documentation/blob/main/working-with-ai-pipelines.adoc) | Containerized ML workflows, Kubeflow v2, experiments/runs and object-store artifacts |
| S07 | [Documentation source: Model catalog and registries](https://github.com/opendatahub-io/opendatahub-documentation/blob/main/modules/overview-of-model-registries.adoc) | Model metadata, versioning and deployment lifecycle concepts |
| S08 | [Documentation source: Kubeflow Trainer v2](https://github.com/opendatahub-io/opendatahub-documentation/blob/main/assemblies/running-kubeflow-trainerv2.adoc) | Unified TrainJob API and training runtimes |
| S09 | [Documentation source: Distributed workloads overview](https://github.com/opendatahub-io/opendatahub-documentation/blob/main/modules/overview-of-distributed-workloads.adoc) | KubeRay, resource admission, training components and pipeline/distributed-workload boundary |
| S10 | [Documentation source: Monitoring data drift](https://github.com/opendatahub-io/opendatahub-documentation/blob/main/assemblies/monitoring-data-drift.adoc) | TrustyAI statistical drift metrics |
| S11 | [Documentation source: Working with ML features](https://github.com/opendatahub-io/opendatahub-documentation/blob/main/working-with-machine-learning-features.adoc) | Feature Store integration and training features |
| S12 | [Red Hat: Building an AI-powered multimodal compliance monitor](https://www.redhat.com/en/blog/building-ai-powered-multimodal-compliance-monitor-training-tracking-chat) | September 30, 2026 end-to-end vision, tracking, storage and conversational application pattern |
| S13 | [Multimodal compliance monitor quickstart](https://github.com/rh-ai-quickstart/multimodal-compliance-monitor) | Runnable application; CPU/OpenVINO and GPU/KServe-Triton options, training and annotation |
| S14 | [Open-RMF Free Fleet](https://github.com/open-rmf/free_fleet) | Zenoh-based fleet adapter, Nav2 integration, filtering/rate controls and examples |
| S15 | [RMF Web](https://github.com/open-rmf/rmf-web) | Fleet API/dashboard and version-specific integration guidance |
| S16 | [Zenoh ROS 2 DDS bridge](https://github.com/eclipse-zenoh/zenoh-plugin-ros2dds) | ROS topics/services/actions, namespaces, transport topology and DDS isolation |
| S17 | [Nav2 Collision Monitor](https://github.com/ros-navigation/navigation2/blob/main/nav2_collision_monitor/README.md) | Local collision response architecture and explicit certification limitation |
| S18 | [Hugging Face LeRobot](https://github.com/huggingface/lerobot) | Robotics policies, dataset format, training, simulation evaluation and hardware adapters |
| S19 | [ROS 2 rosbag2](https://github.com/ros2/rosbag2/blob/rolling/README.md) | Recording/playback, MCAP, simulation-time and recording concepts |
| S20 | [Red Hat OpenShift GitOps](https://www.redhat.com/en/technologies/cloud-computing/openshift/gitops) | Declarative deployment, Argo CD and rollout integration |
| S21 | [Red Hat Advanced Cluster Management](https://www.redhat.com/en/technologies/management/advanced-cluster-management) | Multicluster/site management and observability |
| S22 | [Flight Control](https://github.com/flightctl/flightctl) | Upstream declarative device/OS/workload lifecycle, agent and staged rollout patterns |
| S23 | [NVIDIA GPU Operator on OpenShift](https://docs.nvidia.com/datacenter/cloud-native/openshift/latest/index.html) | GPU integration, monitoring, MIG/time slicing and disconnected installation |
| S24 | [Red Hat: MLOps for edge AI—preparing models for deployment](https://www.redhat.com/en/blog/mlops-edge-ai-preparing-ai-models-deployment-edge) | October 5, 2026 central/edge split, hardware-specific artifacts, Modelcar, model metadata versus distribution |
| S25 | [DenizBank/Intertech customer case study](https://www.redhat.com/en/resources/denizbank-intertech-transform-ai-operations-case-study) | Enterprise platform adoption and limits on interpreting expected productivity gains |
| S26 | [vLLM tool calling](https://docs.vllm.ai/en/latest/features/tool_calling/) | Tool-calling application responsibilities, structured output and model/parser coupling; upstream developer-preview documentation |
| S27 | [Model Context Protocol specification repository](https://github.com/modelcontextprotocol/modelcontextprotocol) | Tool-protocol interoperability; no robotics semantics supplied by the protocol |

### Repository sources

- [README.md](../README.md): Supported demo topology, route, components, and hybrid narrow-corridor limitations.
- [MULTI-LEVEL-NAVIGATION-DEMO.md](../MULTI-LEVEL-NAVIGATION-DEMO.md): Hotel baseline and federated ownership/message flow.
- [demo/dispatch_multilevel_task.py](../demo/dispatch_multilevel_task.py): Existing task API request/response and simulation-clock pattern.
- [entrypoints/nav2_relay.py](../entrypoints/nav2_relay.py): Existing navigation relay integration.
- [entrypoints/entrypoint-rmf.sh](../entrypoints/entrypoint-rmf.sh): Constant battery SOC note.
- [entrypoints/entrypoint-hotel-sim-federated.sh](../entrypoints/entrypoint-hotel-sim-federated.sh): Gazebo camera-follow behavior.
- [helm/multi-robot-demo/templates/configmap-zenoh.yaml](../helm/multi-robot-demo/templates/configmap-zenoh.yaml): Existing selected robotics topics/actions and bridge pattern.
- [helm/multi-robot-demo/values-hotel-nav2.yaml](../helm/multi-robot-demo/values-hotel-nav2.yaml): Federated hotel configuration.
