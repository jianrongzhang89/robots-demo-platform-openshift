# Open-RMF and Nav2 AI Integration: Research and Assessment

- **Research cutoff:** October 9, 2026
- **Status:** Draft for review
- **Scope:** Public industry integrations, research, demonstrations, model choices, reusable plugins, and relevance to this repository
- **Validation:** Documentation and selected source-code inspection; external demonstrations were not built or executed

## 1. Findings and recommendation

Open-RMF has public AI integrations for natural-language fleet control, operational analytics, and experimental scheduling. Nav2 has actual AI-related plugins, documented perception pipelines, and research systems using learned navigation models. The most immediately useful references for this platform are **Nayantra for fleet orchestration**, **semantic costmap integrations for AI-informed navigation**, and **NeuPAN for experimental learned local planning**.

The evidence is uneven. Commercial organizations have documented Open-RMF integrations and AI-enabled operations products, but public descriptions often omit their models and do not establish that a specific customer uses the combined functionality. Public Nav2 perception integrations provide more concrete implementation details. Learned fleet scheduling remains a research area with limited reproducible Open-RMF artifacts in the sources located.

| Question | Finding | Assessment |
|---|---|---|
| Has Open-RMF been integrated with AI? | Yes: natural-language dispatch, operations assistance, symbolic planning, and experimental reinforcement learning | Evaluate each integration at its actual layer and maturity |
| Is there a specialized Open-RMF model? | No official or broadly established RMF-specific foundation model, fine-tuned LLM, or standard learned scheduling checkpoint was found | General-purpose models plus RMF-specific tools are the clearest public approach |
| Has Nav2 been integrated with AI models? | Yes: segmentation, depth estimation, learned local planning, social navigation, and semantic exploration | Multiple public implementations are available |
| Are actual Nav2 plugins available? | Yes: semantic segmentation and nvblox costmap plugins, NeuPAN and social-RL controller integrations, and agricultural traversability code | Some are well-documented integrations; others require substantial research engineering |
| What should this platform evaluate first? | Nayantra as an orchestration reference, followed by semantic costmaps | These align with the existing hotel/fleet demonstration and offer distinct, visible AI outcomes |

**Recommended direction:** complete the existing fleet-copilot-to-RMF execution path, then add a camera-based semantic navigation demonstration. Evaluate learned local controllers separately against the existing controller baseline. These are engineering recommendations from the evidence, not measured results for this platform.

Primary anchors: [Nayantra](https://github.com/shashankbr27/nayantra), [Nav2 AI integrations](https://github.com/ros-navigation/navigation2.ai), [semantic segmentation layer](https://github.com/kiwicampus/semantic_segmentation_layer), and [NeuPAN Nav2 controller](https://github.com/LihanChen2004/nav2_neupan_controller).

## 2. Scope and evidence conventions

The research covered upstream documentation, public implementation repositories, author publications, vendor announcements, and research papers. Selected source files were inspected to confirm model configuration and actual plugin interfaces.

The following distinctions apply throughout:

- **Implemented:** public code or an explicit implementation description exists; this does not mean it was independently executed during this research.
- **Demonstrated:** the source describes an experiment or provides a demonstration. Results remain attributable to its authors.
- **Commercial evidence:** a vendor or its collaborator documents a product or integration. This does not establish every possible combination of that vendor's capabilities in a customer deployment.
- **Proposed/research:** an architecture or experiment is reported, but reusable code, checkpoints, or deployment evidence may be missing.
- **Assessment:** an engineering judgment about suitability for this platform.

No external package was installed, no robot or cluster was exercised, and no external performance claim was reproduced. Repository branches and online documentation are mutable. A reproduction effort should pin commits, model revisions, ROS distributions, and inference dependencies.

The scope is the **Open Robotics Middleware Framework (Open-RMF)**. Search results concerning the NIST AI Risk Management Framework or the unrelated OpenRMF cybersecurity product are excluded.

## 3. Where AI connects to the robotics stack

| Integration point | AI responsibility | Robotics responsibility | Representative evidence |
|---|---|---|---|
| Above Open-RMF | Interpret requests, select tools, generate mission steps, summarize results | Allocate and execute tasks; coordinate traffic and infrastructure | Nayantra |
| Alongside fleet operations | Analyze incidents and telemetry; advise operators | Maintain operational state and execute authorized workflow decisions | InOrbit |
| Around fleet scheduling | Learn priorities or adaptations from fleet state | Preserve the scheduling and execution contracts used by the integration | MAPPO research |
| Feeding Nav2 perception | Classify terrain, identify people, estimate depth | Incorporate spatial observations into navigation | Semantic layer, nvblox, Depth Anything 3 |
| Inside Nav2 control | Generate local trajectories, waypoints, or velocity decisions | Run the controller interface and remaining navigation functions | NeuPAN, Nav2SocialRL |
| Above Nav2 navigation | Select destinations or exploration targets using language and vision | Perform local planning and control | RAI, WildOS |

For example, Nayantra follows `request → LLM → MCP tools → Open-RMF API → fleet adapter → Nav2 → robot`. In a semantic navigation pipeline, a model's masks become costmap observations before the ordinary navigation algorithms use them. These integrations do not require the same model to understand both fleet scheduling and motor control. [Nayantra architecture](https://github.com/shashankbr27/nayantra), [Nav2 semantic navigation tutorial](https://docs.nav2.org/rolling/tutorials/general_tutorials/navigation2_with_semantic_segmentation/navigation2_with_semantic_segmentation/).

## 4. Open-RMF: existing integrations and demonstrations

### 4.1 Nayantra: natural-language fleet control through MCP

Nayantra is the closest public reference for an LLM interface over Open-RMF. It supplies an agent, an MCP-facing tool layer, an RMF client, and integration instructions for Nav2, Isaac Sim, and Zenoh. The repository includes a laptop-friendly stub setup. [Repository](https://github.com/shashankbr27/nayantra).

Selected implementation inspection confirmed provider-specific tool-calling paths for Anthropic, OpenAI, and Gemini. The agent constructs structured plans, handles dependencies between tool calls, executes them, and summarizes the results. The inspected configuration names:

| Provider | Configured model identifier | What this establishes |
|---|---|---|
| Anthropic | `claude-sonnet-4-6` | Repository default/configuration choice |
| OpenAI | `gpt-4o` | Implemented provider path and configured model |
| Google | `gemini-3.5-flash` | Implemented provider path and configured model |

These identifiers are recorded from the project, not independently validated availability or comparative performance claims. [Agent source](https://raw.githubusercontent.com/shashankbr27/nayantra/main/nayantra/agent/agent.py), [configuration](https://raw.githubusercontent.com/shashankbr27/nayantra/main/config/.env.example).

The July 2, 2026 Open Robotics Interoperability SIG recording describes a package pickup/drop-off demonstration: natural language becomes RMF missions, then Nav2 executes navigation in an Isaac Sim warehouse. [Presentation recording](https://vimeo.com/1208218644).

The author's announcement describes an early release, with working end-to-end stub mode and real-robot/simulator integration still maturing. **Assessment:** use it as an architecture and implementation reference; production readiness and compatibility with this repository's RMF interfaces require verification. [Author's status statement](https://discourse.openrobotics.org/t/nayantra-natural-language-fleet-control-via-llm-open-rmf-mcp/54876).

### 4.2 NCS Robotmanager: commercial platform integration

Open Robotics documented collaboration with NCS on Robotmanager, an enterprise platform for heterogeneous autonomous fleets with built-in AI. Work supporting security robots added GPS coordinate support, teleoperation, video streaming, event notifications, and customized tasks to the Open-RMF ecosystem.

The announcement establishes a commercial integration but does not disclose particular neural architectures, weights, or a learned replacement for RMF scheduling. **Assessment:** credible evidence of industry use of RMF within an AI-enabled platform; insufficient detail to select a model or reproduce the AI portion. [Open Robotics announcement](https://www.openrobotics.org/blog/2022/9/22/open-rmf-capabilities-extended-in-collaboration-with-ncs).

### 4.3 InOrbit: RMF interoperability and commercial AI operations

InOrbit and Ekumen released an RMF fleet adapter connecting RMF traffic management and task execution to InOrbit-managed robots. The example repository includes a warehouse configuration and launch instructions. [Adapter announcement](https://www.inorbit.ai/blog/inorbit-rmf-adapter), [warehouse example](https://github.com/inorbit-ai/rmf_inorbit_examples/blob/main/rmf_inorbit_demos/README.md).

InOrbit separately offers RobOps Copilot for natural-language analysis of missions, incidents, telemetry, and robot health, including visual incident analysis. Its 2024 launch announcement names Kärcher as an early user. The cited material does not disclose the exact models or establish that Kärcher's deployment used RMF. [Product description](https://www.inorbit.ai/robopscopilot), [commercial launch](https://www.inorbit.ai/press/inorbit-robops-copilot).

**Assessment:** a useful commercial reference for operational assistance and incident explanation. The adapter and AI product are both documented, but a particular combined RMF–Copilot customer deployment should not be inferred from that alone. An [on-demand demonstration webinar](https://www.inorbit.ai/webinar/robops-copilot) is available.

### 4.4 MAPPO: experimental fleet traffic and communication adaptation

The TICMET'25 paper *Multi Agent Reinforcement Learning Based Communication and Traffic Management Algorithm for Autonomous Mobile Robots* describes MAPPO agents making traffic and DDS communication adaptations around Open-RMF schedules. It reports Gazebo experiments involving 10–50 robots, combining learned adaptation with classical optimization and TEB local navigation.

A public implementation or trained checkpoint associated with this paper was not located. **Assessment:** relevant evidence of proposed and experimentally reported AI augmentation of RMF scheduling, but not a reusable component established by this research. Reported improvements should remain attributed to the paper and should not become platform performance expectations. [Conference proceedings](https://www.ticmet.org/uploads/files2/t25proceedingb.pdf).

### 4.5 ePlanSys: symbolic AI planning over RMF

ePlanSys documents an office-fleet survey demo in which a scout's observation changes the subsequent plan. The bridge submits RMF tasks and waits for reported completion. EPDDL represents the epistemic planning problem, and two office-demo robots perform the mission.

**Assessment:** useful for conditional missions and reasoning about what agents know. This is symbolic AI integration rather than a neural-model example. [Demo instructions](https://eplansys.github.io/eplansys/execution/demo.html).

### 4.6 Early combined fleet and manipulation projects

The `multi-robot-fleet-ros2` repository combines RMF, Nav2, mobile manipulation, and AI skills. Its description advertises SmolVLA, while its README documents an Ollama/Claude language planner for arm actions. The README explicitly says end-to-end RMF dispatch against real Nav2 navigation is not yet verified.

**Assessment:** an exploratory code reference. Coexistence of these components in a repository is insufficient evidence of a demonstrated RMF-to-VLA mission. [Repository and stated limitations](https://github.com/darshmenon/multi-robot-fleet-ros2).

### 4.7 Upstream demonstrations and future integration boundaries

The standard RMF demonstrations cover hotel, office, airport, clinic, campus, and manufacturing/logistics scenarios. They provide useful environments for evaluating an AI extension, but their fleet coordination capabilities do not themselves establish use of a learned model. [Official demonstrations](https://github.com/open-rmf/rmf_demos).

The April 2026 next-generation roadmap describes replaceable traffic planning, task planning, execution, and dashboard modules, plus more expressive task definitions. **Assessment:** this modularity could support alternative learned components, but the roadmap is not evidence of a delivered RMF neural model or guaranteed delivery dates. [Upstream roadmap](https://discourse.openrobotics.org/t/next-generation-open-rmf-roadmap/53820).

## 5. Models specifically targeted at Open-RMF

No official or broadly established RMF-specific foundation model, fine-tuned LLM, or standard downloadable learned scheduling checkpoint was found in the reviewed sources. This is a bounded research finding, not proof that no private or unindexed implementation exists.

| Model approach | Observed role | Open-RMF-specific component |
|---|---|---|
| General-purpose LLMs | Interpret requests and call fleet tools | Schemas, prompts, live context, and API adapters |
| Custom reinforcement-learning policies | Learn traffic priorities or communication adaptations | State/action/reward definitions and scheduling integration |
| Vision or manipulation models | Execute perception or robot skills | Fleet adapter and task-action integration around the robot |
| Symbolic planners | Generate conditional missions | Domain definitions and RMF dispatch/monitoring bridge |

Nayantra specializes the integration rather than introducing a newly trained RMF model. Likewise, an RMF-managed robot can execute a learned skill without its model understanding elevator reservations or fleet traffic negotiation. The primary engineering requirement is matching the model's output to the actual task or robot interface.

## 6. Nav2: actual AI-related plugins

Nav2 has public, loadable extensions for learned perception and control. Its upstream organization also hosts `navigation2.ai`, whose inspected README documents a Depth Anything 3 perception integration. [AI integration repository](https://github.com/ros-navigation/navigation2.ai).

| Plugin or repository | Model connection | Available evidence | Assessment |
|---|---|---|---|
| [`semantic_segmentation_layer`](https://github.com/kiwicampus/semantic_segmentation_layer) | External segmentation masks become navigation costs | Public costmap plugin; upstream tutorials | Strong initial candidate for semantic navigation |
| [`nvblox_nav2`](https://nvidia-isaac-ros.github.io/v/release-3.2/repositories_and_packages/isaac_ros_nvblox/nvblox_nav2/index.html) | nvblox distance maps feed Nav2; documented people pipeline uses PeopleSemSegNet | NVIDIA documentation and examples | Substantial vendor integration; release/hardware matching required |
| [`nav2_neupan_controller`](https://github.com/LihanChen2004/nav2_neupan_controller) | NeuPAN and learned DUNE component generate local trajectories | Public controller implementation and configuration | Concrete experimental learned controller |
| [`Nav2SocialRL`](https://github.com/maxijsseldijk/Nav2SocialRL) | SAC policies; DAgger imitation pretraining | Controller plugins and Gazebo training framework | Research platform requiring training/evaluation work |
| [`visualtraversabilityplugin`](https://github.com/ucmrobotics/visualtraversabilityplugin) | YOLOv8 segmentation corrects local traversability costs | Published field experiments and source | Valuable research reference; sparse repository documentation |

### 6.1 Semantic segmentation costmap layer

The plugin class is `semantic_segmentation_layer::SemanticSegmentationLayer`. It consumes class masks, registered point clouds, and optional confidence masks from a separate inference node. It maps image classifications into spatial costmap cells with configured costs. The plugin itself does not train or run the segmentation model. [Plugin documentation](https://github.com/kiwicampus/semantic_segmentation_layer).

Nav2's Gazebo Baylands/TurtleBot 4 tutorial includes a pretrained ONNX model for sidewalk, grass, and background, plus inference and costmap setup. U-Net, DDRNet, and SegFormer appear as architecture examples in the tutorial; that does not identify the architecture of the supplied checkpoint. [Official tutorial](https://docs.nav2.org/rolling/tutorials/general_tutorials/navigation2_with_semantic_segmentation/navigation2_with_semantic_segmentation/).

Open Navigation also provides a **SAM3** integration. Text prompts select what to segment; masks and registered depth feed the semantic layer; Nav2 uses the resulting costs. Public indoor/outdoor demonstrations run on AMD Strix Halo. Reported inference rates vary approximately from 3–10 Hz with prompt count and detection/tracking settings, so a single rate should not be assumed for another workload. [Implementation and demonstrations](https://github.com/open-navigation/opennav_amd_semantic_navigation), [setup tutorial](https://docs.nav2.org/rolling/tutorials/general_tutorials/navigation2_with_sam3_semantic_segmentation/navigation2_with_sam3_semantic_segmentation/).

**Assessment:** this is the clearest way to demonstrate that a model changes navigation decisions while retaining familiar Nav2 planning and control. It requires a suitable camera pipeline, spatial registration, and class-to-cost policy.

### 6.2 NVIDIA nvblox and PeopleSemSegNet

The `nvblox_nav2` package supplies a custom plugin for nvblox distance-map outputs. In the documented people-reconstruction pipeline, a U-Net inference node runs **PeopleSemSegNet**, and its masks help separate people from the static reconstruction. nvblox supplies the spatial representation used by Nav2; nvblox itself is not a neural navigation policy. [Pipeline description, release 4.3](https://nvidia-isaac-ros.github.io/v/release-4.3/repositories_and_packages/isaac_ros_nvblox/index.html).

**Assessment:** a strong vendor-maintained perception/mapping integration. Select a compatible release before reproduction rather than mixing instructions across ROS and Isaac ROS versions.

### 6.3 NeuPAN learned local controller

The wrapper exports `nav2_neupan_controller::NeuPANController` against `nav2_core::Controller`. It embeds Python in the C++ controller and delegates trajectory generation to NeuPAN, with a configurable DUNE checkpoint path. The README reports testing only on ROS 2 Jazzy with Python 3.12. It exposes several drivetrain modes, but marks some demonstrations as pending. [Wrapper and configuration](https://github.com/LihanChen2004/nav2_neupan_controller).

NeuPAN combines learning with mathematical optimization. Its learned **DUNE** component is trained for robot geometry; the authors specify retraining when the robot's shape or size changes. The upstream project includes checkpoints, training examples, simulation scenarios, and real-robot videos. Its optimization stage is CPU-bound. [Underlying model and demonstrations](https://github.com/hanruihua/NeuPAN).

**Assessment:** the most direct candidate here for evaluating a learned component inside Nav2's local controller. Validate its geometry, inference timing, path tracking, and supported drivetrain against this platform before integrating it into a multi-floor demonstration.

### 6.4 Nav2SocialRL

The framework learns velocity commands or local waypoints/plans and supports multiple downstream control choices. Source inspection confirmed exported Nav2 controller interfaces for `nav2_rl_local_planner::RLLocalPlanner` and `rl_pure_pursuit_controller::RlPurePursuitController`. The README identifies **SAC** for reinforcement learning and **DAgger** for imitation learning.

These are training algorithms for task-specific policies, not universal pretrained navigation models. **Assessment:** suitable for social-navigation research; less suitable as the first general-purpose customer demo because the training and simulation environment must also be reproduced. [Framework](https://github.com/maxijsseldijk/Nav2SocialRL).

### 6.5 Agricultural visual traversability

The ICRA 2024 paper by Sani, Sgorbissa, and Carpin uses YOLOv8 segmentation to recognize traversable vegetation and correct local costmap cells otherwise marked as obstacles. The selected model is `yolov8n-seg`. The authors report field validation on a Clearpath Husky and provide the linked plugin source.

**Assessment:** concrete historical evidence of model-informed Nav2 behavior, with domain-specific training and limited repository guidance. [Paper](https://arxiv.org/abs/2407.18535), [full paper](https://robotics.ucmerced.edu/sites/robotics.ucmerced.edu/files/page/documents/icra24_a.pdf), [source](https://github.com/ucmrobotics/visualtraversabilityplugin).

## 7. Nav2 integrations that are external nodes or agents

These projects integrate with Nav2 without necessarily implementing a loadable planner/controller plugin.

| Project | Model | Connection to Nav2 | Useful demonstration |
|---|---|---|---|
| Nav2 AI depth pipeline | Depth Anything 3 | Estimated depth becomes point-cloud observations for costmaps | Camera-based obstacle perception |
| RobotecAI RAI | Configurable LLMs and multimodal models | Agent tools invoke ROS 2/Nav2 operations | Language-driven mobile-robot tasks |
| WildOS | ExploRFM with C-RADIOv3-B and SigLIP2-related components | Semantic exploration and object search use Nav2 for local planning/control | Search for a described object in unfamiliar outdoor terrain |
| Nayantra | Claude, GPT-4o, Gemini | Open-RMF and fleet adapter dispatch to Nav2 | Natural-language fleet missions |

### 7.1 Depth Anything 3

The upstream tutorial combines RGB capture, preprocessing, TensorRT-accelerated depth inference, and point-cloud output. It shows `DA3METRIC-LARGE` and the associated ROS 2 depth package. Nav2 consumes the output through normal perception interfaces.

**Assessment:** useful for AI-enhanced sensing without replacing navigation algorithms. Camera calibration, metric-depth behavior, inference latency, and observation quality are the practical evaluation points. [Official tutorial](https://docs.nav2.org/rolling/tutorials/general_tutorials/depth_ai_integration/depth_ai_integration/).

### 7.2 RobotecAI RAI

RAI documents ROS 2 and Nav2 tools and a ROSbot XL demonstration. Its model documentation recommends GPT-4o and supports other providers. The demo also documents local `gpt-oss-20b` and `qwen3` configurations, with reduced capabilities for image-dependent tasks.

**Assessment:** a useful application framework for language-driven robot interaction. It is not a replacement controller plugin. [Tools](https://robotecai.github.io/rai/API_documentation/langchain_integration/ROS_2_tools/), [ROSbot XL demo](https://robotecai.github.io/rai/demos/rosbot_xl/), [model configuration](https://robotecai.github.io/rai/setup/vendors/).

### 7.3 WildOS and ExploRFM

WildOS performs open-vocabulary object search using a navigation graph and the **ExploRFM** vision module. The model predicts traversability, exploration frontiers, and object similarity. Its release includes trained prediction heads, training code, and instructions for obtaining C-RADIOv3-B and SigLIP2 weights. The implementation documents ROS 2 Jazzy, Jetson AGX Orin deployment, and Nav2 as a required local planning/control component.

The research reports field experiments across outdoor and urban environments. **Assessment:** a substantive example of a specialized navigation model working with Nav2, but a larger integration effort than a costmap-only extension. [Implementation](https://github.com/nasa-jpl/nebula2-wildos), [2026 paper](https://arxiv.org/abs/2602.19308).

## 8. Model and plugin distinctions to preserve

| Item | Correct interpretation |
|---|---|
| NeuPAN/DUNE | Specialized learned navigation component with a third-party Nav2 controller wrapper |
| ExploRFM | Specialized vision model in a navigation system that explicitly uses Nav2 |
| SAM3, PeopleSemSegNet, Depth Anything 3, YOLOv8 | Perception models used through navigation integrations; not Open-RMF task planners |
| SAC, MAPPO, DAgger | Learning algorithms, not specific pretrained checkpoints |
| MCP, RAI, Nayantra | Protocol or integration/application software, not model weights |
| MPPI, Smac, behavior trees | Standard control, search, or execution mechanisms; their presence alone does not establish a trained model |

A social costmap extension also need not use learning. The public [`nav2_social_costmap_plugin`](https://github.com/robotics-upo/nav2_social_costmap_plugin) supplies social-navigation integration infrastructure; it should not be labeled a neural controller without an additional learned component.

The [`ros2-neural-astar`](https://github.com/aaronj0/ros2-neural-astar) project describes Nav2 planner-server compatibility as a roadmap item. It is therefore not established here as a ready-to-load plugin.

GNM, ViNT, and NoMaD have public training code and checkpoints, but their original deployment examples use their own navigation pipeline. RAI's NoMaD extension publishes velocity commands directly; that is insufficient evidence of a Nav2 controller-server integration. **Assessment:** relevant model research, with additional adapter work before assuming compatibility. [Original model release](https://github.com/robodhruv/visualnav-transformer), [RAI extension](https://robotecai.github.io/rai/extensions/nomad/).

Nav2's [plugin catalog](https://docs.nav2.org/rolling/configuration_and_development/navigation_plugins/) is a useful index, but inclusion of a third-party extension should not be interpreted as equivalent packaging, support, or deployment maturity across all ROS distributions.

## 9. Assessment for this repository

The repository's fleet-copilot README describes interpretation, validated previews, persistent mission handling, and an external-model UI. It also states that its bridge publication boundary is currently an emulator rather than a live RMF/ROS publisher. This is a documentary finding, not a runtime assessment. [Current application README](../apps/fleet-copilot/README.md).

The earlier [OpenShift AI research](openshift-ai-robotics-research-and-use-cases.md) supplies platform context. This report supplements it with public examples and more specific model/plugin evidence; it does not revalidate that document's platform-version or cluster claims.

| Priority | Evaluation | Reason | Proposed acceptance evidence |
|---|---|---|---|
| 1 | Nayantra comparison and completion of live copilot dispatch | Closest architectural match to the existing application | Validated intent leads to an RMF task ID and observed robot completion; retries do not create duplicate tasks |
| 2 | Semantic costmap demonstration | Makes the model's effect on navigation visible | Same scene and goal produce explainable changes when semantic costs are enabled; model output, costmap, and path are recorded |
| 3 | Depth Anything 3 or nvblox | Adds learned perception through existing navigation interfaces | Reproducible camera-to-costmap pipeline, measured latency, and scenario-based obstacle detection results |
| 4 | NeuPAN controller comparison | Tests actual learned local navigation | Comparison with existing controller on completion, tracking, clearance, and compute timing across repeated runs |
| 5 | Nav2SocialRL or WildOS | Supports specialized social navigation or semantic search | Reproduced training/evaluation setup or object-search experiment before fleet integration |

These are proposed evaluation criteria, not results already achieved.

### 9.1 Proposed initial demonstrations

**Fleet mission copilot:** reuse the hotel mission and named destinations. Show the request, interpreted mission, live RMF acceptance, execution state, elevator transition, and completion. Nayantra is the external reference for the language/tool/orchestration path. Record mission completion separately from successful model interpretation or successful API submission.

**Semantic navigation:** add a robot camera pipeline and a semantic costmap layer. Use an observable distinction such as floor versus a restricted surface or a specifically detected object. Compare the same scenario with and without semantic costs. Start with the documented ONNX example if minimizing compute and setup variability is the priority; evaluate SAM3 when runtime text-defined categories are part of the demonstration objective.

**Learned controller experiment:** keep the same robot and navigation task while comparing the existing controller with NeuPAN. Establish the robot-geometry model and runtime performance before introducing multi-floor scheduling. This isolates what the learned controller contributes.

### 9.2 Deployment implications

For this platform, a reasonable architecture is to host mission interpretation and operational analysis as application services near the fleet stack, while locating time-sensitive perception and controller inference close to the robot's navigation process. Exact placement depends on measured latency and available compute; the research does not establish a requirement that every model run centrally or on the robot.

Model serving alone will not supply RMF mission semantics, camera registration, costmap policies, or controller lifecycle integration. Those are application and robotics adapters that must be implemented and evaluated. In particular, a successful tool call must be distinguished from a completed physical mission.

## 10. Review decisions and unresolved evidence

The proposed next engineering work is intentionally narrower than reproducing every research system. Review should settle:

1. Whether the next demonstration should prioritize fleet operation through language, model-informed perception, or learned motion control.
2. Which ROS/Nav2/RMF versions will be pinned for reproduction.
3. Whether the robot has an appropriate camera and registered depth stream, and which compute platform will run inference.
4. Which model and code licenses apply to the selected integration and its dependencies.
5. Which baseline and measurements will establish that the AI extension improves the intended outcome.

Remaining evidence gaps are the exact AI models inside the cited commercial platforms, independently reproducible RMF learning-based scheduling artifacts, and compatibility/performance of the listed projects with this repository's deployment. Public sources establish useful implementation directions, but these questions require targeted reproduction or information from the project owners.
