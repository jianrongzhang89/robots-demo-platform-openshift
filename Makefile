REGISTRY    ?= quay.io/jianrzha
IMAGE       ?= ros2-demo
IMAGE_RMF   ?= ros2-rmf
TAG         ?= latest
# Use ROS_DEMO_NS to avoid clashing with any NAMESPACE env var set by the shell
ROS_DEMO_NS ?= ros2-multi-robot
RELEASE    ?= multi-robot-demo
CHART      := helm/multi-robot-demo

# Convenience alias so existing targets keep working
NAMESPACE  := $(ROS_DEMO_NS)

IMAGE_REF     := $(REGISTRY)/$(IMAGE):$(TAG)
IMAGE_RMF_REF := $(REGISTRY)/$(IMAGE_RMF):$(TAG)

# Auto-detect podman (handles non-standard install paths like /opt/podman/bin)
PODMAN     := $(shell which podman 2>/dev/null || echo /opt/podman/bin/podman)

.DEFAULT_GOAL := help

##@ General

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} \
	  /^[a-zA-Z_0-9-]+:.*?##/ { printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2 } \
	  /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

##@ Build

.PHONY: build
build: ## Build the Gazebo/Nav2 container image
	$(PODMAN) build --platform linux/amd64 -t $(IMAGE_REF) -f Containerfile .

.PHONY: push
push: ## Push the Gazebo/Nav2 image to the registry
	$(PODMAN) push $(IMAGE_REF)

.PHONY: build-push
build-push: build push ## Build and push the Gazebo/Nav2 image

.PHONY: build-rmf
build-rmf: ## Build the Open-RMF core container image (~20 min first build)
	$(PODMAN) build --platform linux/amd64 -t $(IMAGE_RMF_REF) -f Containerfile.rmf .

.PHONY: push-rmf
push-rmf: ## Push the RMF image to the registry
	$(PODMAN) push $(IMAGE_RMF_REF)

.PHONY: build-push-rmf
build-push-rmf: build-rmf push-rmf ## Build and push the RMF image

##@ Deploy

.PHONY: deploy
deploy: ## Install or upgrade the Helm release on OpenShift
	helm upgrade --install $(RELEASE) $(CHART) \
	  --namespace $(NAMESPACE) \
	  --create-namespace \
	  --set image.repository=$(REGISTRY)/$(IMAGE) \
	  --set image.tag=$(TAG) \
	  --wait --timeout 10m

.PHONY: undeploy
undeploy: ## Uninstall the Helm release
	helm uninstall $(RELEASE) --namespace $(NAMESPACE) || true
	oc delete namespace $(NAMESPACE) --ignore-not-found

.PHONY: restart
restart: ## Rolling restart of all demo pods (Gazebo first, then nav2 + rmf-core)
	@echo "Step 1: Restarting Gazebo and waiting for it to be fully ready..."
	oc rollout restart deployment/gazebo-sim -n $(NAMESPACE)
	oc rollout status deployment/gazebo-sim -n $(NAMESPACE) --timeout=5m
	@echo "Step 2: Restarting nav2 pods (Gazebo is ready, odom is fresh)..."
	@for d in $$(oc get deployments -n $(NAMESPACE) -o name | grep robot-nav); do \
	  oc rollout restart $$d -n $(NAMESPACE); \
	done
	oc rollout restart deployment/rmf-core -n $(NAMESPACE)

##@ Helm

.PHONY: template
template: ## Render Helm templates to stdout (for review/debugging)
	helm template $(RELEASE) $(CHART) --namespace $(NAMESPACE)

.PHONY: lint
lint: ## Lint the Helm chart
	helm lint $(CHART)

.PHONY: package
package: ## Package the Helm chart into a .tgz
	helm package $(CHART) --destination dist/

##@ SLAM Map Building

.PHONY: build-slam-maps
build-slam-maps: ## One-time: rebuild slam_toolbox posegraphs with full sandbox coverage
	@echo "=== SLAM posegraph rebuild (one-time setup) ==="
	@echo "Step 1: Building mapping image (swap-nav2-slam-mapping) with SLAM_BUILD_MODE=1 baked in..."
	$(PODMAN) build --platform linux/amd64 --build-arg SLAM_BUILD_MODE=1 \
	  -t $(REGISTRY)/$(IMAGE):swap-nav2-slam-mapping -f Containerfile .
	$(PODMAN) push $(REGISTRY)/$(IMAGE):swap-nav2-slam-mapping
	@echo "Step 2: Deploying mapping image..."
	helm upgrade $(RELEASE) $(CHART) \
	  --namespace $(NAMESPACE) \
	  --reuse-values \
	  --set image.repository=$(REGISTRY)/$(IMAGE) \
	  --set image.tag=swap-nav2-slam-mapping
	@echo "Step 3: Waiting for pods to restart..."
	$(MAKE) restart ROS_DEMO_NS=$(ROS_DEMO_NS)
	oc rollout status deployment/robot-nav-robot-1 -n $(NAMESPACE) --timeout=4m
	oc rollout status deployment/robot-nav-robot-2 -n $(NAMESPACE) --timeout=4m
	@echo "Step 4: Running exploration (drives both robots through full sandbox ~10 min)..."
	@RMFPOD=$$(oc get pod -n $(NAMESPACE) -l app=rmf-core -o jsonpath='{.items[0].metadata.name}' 2>/dev/null); \
	oc cp demo/build_slam_maps.py $(NAMESPACE)/$$RMFPOD:/tmp/build_slam_maps.py -c rmf-core && \
	oc exec -n $(NAMESPACE) $$RMFPOD -c rmf-core -- bash -c \
	  'export HOME=/tmp/ros-home ROS_DEMO_NS=$(NAMESPACE); \
	   source /opt/ros/jazzy/setup.bash; \
	   python3 /tmp/build_slam_maps.py'
	@echo "Step 5: Copying posegraph files from pods..."
	@NS=$(NAMESPACE); \
	for robot in robot-1 robot-2; do \
	  name=$$(echo $$robot | tr '-' '_'); \
	  POD=$$(oc get pod -n $$NS -l app=robot-nav-$$robot -o jsonpath='{.items[0].metadata.name}' 2>/dev/null); \
	  echo "  Copying $${name} posegraph from $$POD..."; \
	  oc cp $$NS/$$POD:/tmp/$${name}_slam.data slam_maps/$${name}_slam.data -c nav2 2>/dev/null || echo "  WARN: .data not found"; \
	  oc cp $$NS/$$POD:/tmp/$${name}_slam.posegraph slam_maps/$${name}_slam.posegraph -c nav2 2>/dev/null || echo "  WARN: .posegraph not found"; \
	done
	@echo "Step 6: Building production image (swap-nav2-rmf) with new full-coverage posegraphs..."
	$(PODMAN) build --platform linux/amd64 \
	  -t $(REGISTRY)/$(IMAGE):swap-nav2-rmf -f Containerfile .
	$(PODMAN) push $(REGISTRY)/$(IMAGE):swap-nav2-rmf
	helm upgrade $(RELEASE) $(CHART) \
	  --namespace $(NAMESPACE) \
	  --reuse-values \
	  --set image.repository=$(REGISTRY)/$(IMAGE) \
	  --set image.tag=swap-nav2-rmf
	$(MAKE) restart ROS_DEMO_NS=$(ROS_DEMO_NS)
	@echo "=== Done. New posegraphs in slam_maps/ and baked into swap-nav2-rmf. ==="
	@echo "    Run 'make dispatch-rmf-swap' to test the LiDAR collision avoidance demo."

##@ Open-RMF

.PHONY: dispatch-patrol
dispatch-rmf-lidar: ## TRUE RMF+Nav2 demo: traffic planning + negotiation + LiDAR collision avoidance
	@echo "=== RMF traffic planning + Nav2 LiDAR collision avoidance ==="
	@echo "Step 1: Restarting pods with slam_toolbox localization..."
	$(MAKE) restart ROS_DEMO_NS=$(ROS_DEMO_NS)
	oc rollout status deployment/robot-nav-robot-1 -n $(NAMESPACE) --timeout=5m
	oc rollout status deployment/robot-nav-robot-2 -n $(NAMESPACE) --timeout=5m
	oc rollout status deployment/rmf-core           -n $(NAMESPACE) --timeout=4m
	@echo "Step 2: Polling for bt_navigator ACTIVE + fleet adapter ready..."
	@NS=$(NAMESPACE); \
	for i in $$(seq 1 60); do \
	  NAV1=$$(oc get pod -n $$NS -l app=robot-nav-robot-1 -o jsonpath='{.items[0].metadata.name}' 2>/dev/null); \
	  NAV2=$$(oc get pod -n $$NS -l app=robot-nav-robot-2 -o jsonpath='{.items[0].metadata.name}' 2>/dev/null); \
	  RMF=$$(oc get pod -n $$NS -l app=rmf-core -o jsonpath='{.items[0].metadata.name}' 2>/dev/null); \
	  s1=$$(oc exec -n $$NS $$NAV1 -c nav2 -- bash -c \
	    'export HOME=/tmp/ros-home; source /usr/lib64/ros-jazzy/setup.bash; timeout 4 ros2 lifecycle get /bt_navigator 2>/dev/null' 2>/dev/null); \
	  s2=$$(oc exec -n $$NS $$NAV2 -c nav2 -- bash -c \
	    'export HOME=/tmp/ros-home; source /usr/lib64/ros-jazzy/setup.bash; timeout 4 ros2 lifecycle get /bt_navigator 2>/dev/null' 2>/dev/null); \
	  fleet=$$(oc exec -n $$NS $$RMF -c rmf-core -- bash -c \
	    'export HOME=/tmp/ros-home; source /opt/ros/jazzy/setup.bash; timeout 3 ros2 topic echo /fleet_states --once 2>/dev/null' 2>/dev/null); \
	  r1=$$(echo "$$fleet" | grep -c "name: robot_1" 2>/dev/null || echo 0); \
	  r2=$$(echo "$$fleet" | grep -c "name: robot_2" 2>/dev/null || echo 0); \
	  echo "  [$$i] bt1=$$s1 | bt2=$$s2 | fleet r1=$$r1 r2=$$r2"; \
	  echo "$$s1" | grep -q "active \[3\]" && echo "$$s2" | grep -q "active \[3\]" && \
	    [ "$${r1:-0}" -ge 1 ] && [ "$${r2:-0}" -ge 1 ] && echo "ALL READY" && break; \
	  sleep 5; \
	done
	@echo "Step 3: Dispatching bidirectional south corridor patrol via RMF traffic scheduler..."
	@echo "  robot_1: s_in → s_out (direct via nav_graph lane [0→14→15], 3 loops)"
	@echo "  robot_2: s_out → s_in (direct via nav_graph lane [1→15→14], 3 loops, 5s stagger)"
	@echo "  Both homes have direct lanes to corridor entries — no pillar grid traversal."
	@echo "  RMF scheduler detects s_in↔s_out bidirectional conflict → negotiation."
	@RMFPOD=$$(oc get pod -n $(NAMESPACE) -l app=rmf-core -o jsonpath='{.items[0].metadata.name}' 2>/dev/null); \
	oc exec -n $(NAMESPACE) $$RMFPOD -c rmf-core -- bash -c \
	  'export HOME=/tmp/ros-home; \
	   source /opt/ros/jazzy/setup.bash; \
	   source /opt/free_fleet/install/setup.bash 2>/dev/null || true; \
	   echo "[rmf] Dispatching robot_1: s_in → s_out (eastbound corridor, 3 loops)"; \
	   ros2 run rmf_demos_tasks dispatch_patrol \
	     -F turtlebot3 -R robot_1 \
	     -p s_in s_out \
	     -n 3 --use_sim_time & \
	   sleep 5; \
	   echo "[rmf] Dispatching robot_2: s_out → s_in (westbound corridor, 3 loops, 5s stagger)"; \
	   ros2 run rmf_demos_tasks dispatch_patrol \
	     -F turtlebot3 -R robot_2 \
	     -p s_out s_in \
	     -n 3 --use_sim_time; \
	   echo "[rmf] Both dispatched. Monitoring /fleet_states for 10 minutes..."; \
	   timeout 600 ros2 topic echo /fleet_states --use_sim_time 2>/dev/null | \
	     grep -E "name: robot|task_id:|location:" || true'

.PHONY: dispatch-patrol
dispatch-patrol: ## Dispatch patrol: robot_1_home→mid_west→meeting_point (robot_1 only)
	$(eval RMFPOD := $(shell oc get pod -n $(NAMESPACE) -l app=rmf-core -o jsonpath='{.items[0].metadata.name}' 2>/dev/null))
	@test -n "$(RMFPOD)" || { echo "ERROR: rmf-core pod not found in namespace '$(NAMESPACE)'"; exit 1; }
	oc exec -n $(NAMESPACE) $(RMFPOD) -c rmf-core -- bash -c \
	  'export HOME=/tmp/ros-home; \
	   source /opt/ros/jazzy/setup.bash; \
	   source /opt/free_fleet/install/setup.bash 2>/dev/null || true; \
	   ros2 run rmf_demos_tasks dispatch_patrol \
	     -p robot_1_home mid_west meeting_point -n 1 --use_sim_time'

.PHONY: dispatch-dual-patrol
dispatch-dual-patrol: ## Dual patrol: both robots converge at meeting_point via direct Zenoh (bypasses RMF traffic scheduler)
	$(eval RMFPOD := $(shell oc get pod -n $(NAMESPACE) -l app=rmf-core -o jsonpath='{.items[0].metadata.name}' 2>/dev/null))
	@test -n "$(RMFPOD)" || { echo "ERROR: rmf-core pod not found in namespace '$(NAMESPACE)'"; exit 1; }
	@echo "Dispatching dual patrol: robot_1 (home→mid_west→meeting_point) and robot_2 (home→meeting_point)"
	oc cp entrypoints/dual_patrol.py $(NAMESPACE)/$(RMFPOD):/tmp/dual_patrol.py -c rmf-core
	oc exec -n $(NAMESPACE) $(RMFPOD) -c rmf-core -- python3 /tmp/dual_patrol.py

.PHONY: dispatch-swap-patrol
dispatch-swap-patrol: ## Swap patrol via RMF+Nav2: direct goal to each other's spawn (Nav2 plans through pillar grid)
	$(eval RMFPOD := $(shell oc get pod -n $(NAMESPACE) -l app=rmf-core -o jsonpath='{.items[0].metadata.name}' 2>/dev/null))
	$(eval NAV1POD := $(shell oc get pod -n $(NAMESPACE) -l app=robot-nav-robot-1 -o jsonpath='{.items[0].metadata.name}' 2>/dev/null))
	$(eval NAV2POD := $(shell oc get pod -n $(NAMESPACE) -l app=robot-nav-robot-2 -o jsonpath='{.items[0].metadata.name}' 2>/dev/null))
	@test -n "$(RMFPOD)" || { echo "ERROR: rmf-core pod not found in namespace '$(NAMESPACE)'"; exit 1; }
	@echo "Waiting for Nav2 bt_navigator to become ACTIVE on both pods..."
	@for pod in $(NAV1POD) $(NAV2POD); do \
	  for i in $$(seq 1 60); do \
	    state=$$(oc exec -n $(NAMESPACE) $$pod -c nav2 -- bash -c \
	      'export HOME=/tmp/ros-home; source /usr/lib64/ros-jazzy/setup.bash; \
	       timeout 5 ros2 lifecycle get /bt_navigator 2>/dev/null' 2>/dev/null); \
	    echo "  $$pod bt_navigator: $$state"; \
	    echo "$$state" | grep -q "active \[3\]" && break || sleep 5; \
	  done; \
	done
	@echo "Dispatching via outer corridors (y=±1.75, avoiding pillar grid)..."
	oc exec -n $(NAMESPACE) $(RMFPOD) -c rmf-core -- bash -c \
	  'export HOME=/tmp/ros-home; \
	   source /opt/ros/jazzy/setup.bash; \
	   source /opt/free_fleet/install/setup.bash 2>/dev/null || true; \
	   ros2 run rmf_demos_tasks dispatch_patrol \
	     -p robot_1_home s_in s_out robot_2_home -n 1 --use_sim_time'
	oc exec -n $(NAMESPACE) $(RMFPOD) -c rmf-core -- bash -c \
	  'export HOME=/tmp/ros-home; \
	   source /opt/ros/jazzy/setup.bash; \
	   source /opt/free_fleet/install/setup.bash 2>/dev/null || true; \
	   ros2 run rmf_demos_tasks dispatch_patrol \
	     -p robot_2_home n_in n_out robot_1_home -n 1 --use_sim_time'

.PHONY: dispatch-rmf-swap
dispatch-rmf-swap: ## RMF + Nav2 LiDAR swap: restart pods, wait for ready, then run the combined RMF+LiDAR demo
	@echo "=== RMF + Nav2 LiDAR collision-avoidance swap demo ==="
	@echo "Step 1: Restarting pods..."
	$(MAKE) restart ROS_DEMO_NS=$(ROS_DEMO_NS)
	@echo "Step 2: Waiting for rollout..."
	oc rollout status deployment/robot-nav-robot-1 -n $(NAMESPACE) --timeout=4m
	oc rollout status deployment/robot-nav-robot-2 -n $(NAMESPACE) --timeout=4m
	oc rollout status deployment/rmf-core           -n $(NAMESPACE) --timeout=4m
	@echo "Step 3: Polling for bt_navigator ACTIVE + fleet adapter ready..."
	@NS=$(NAMESPACE); \
	for i in $$(seq 1 60); do \
	  NAV1=$$(oc get pod -n $$NS -l app=robot-nav-robot-1 -o jsonpath='{.items[0].metadata.name}' 2>/dev/null); \
	  NAV2=$$(oc get pod -n $$NS -l app=robot-nav-robot-2 -o jsonpath='{.items[0].metadata.name}' 2>/dev/null); \
	  RMF=$$(oc get pod -n $$NS -l app=rmf-core -o jsonpath='{.items[0].metadata.name}' 2>/dev/null); \
	  s1=$$(oc exec -n $$NS $$NAV1 -c nav2 -- bash -c \
	    'export HOME=/tmp/ros-home; source /usr/lib64/ros-jazzy/setup.bash; timeout 4 ros2 lifecycle get /bt_navigator 2>/dev/null' 2>/dev/null); \
	  s2=$$(oc exec -n $$NS $$NAV2 -c nav2 -- bash -c \
	    'export HOME=/tmp/ros-home; source /usr/lib64/ros-jazzy/setup.bash; timeout 4 ros2 lifecycle get /bt_navigator 2>/dev/null' 2>/dev/null); \
	  fleet=$$(oc exec -n $$NS $$RMF -c rmf-core -- bash -c \
	    'export HOME=/tmp/ros-home; source /opt/ros/jazzy/setup.bash; timeout 3 ros2 topic echo /fleet_states --once 2>/dev/null' 2>/dev/null); \
	  r1=$$(echo "$$fleet" | grep -c "name: robot_1" 2>/dev/null || echo 0); \
	  r2=$$(echo "$$fleet" | grep -c "name: robot_2" 2>/dev/null || echo 0); \
	  echo "  [$$i] bt1=$$s1 | bt2=$$s2 | fleet r1=$$r1 r2=$$r2"; \
	  echo "$$s1" | grep -q "active \[3\]" && echo "$$s2" | grep -q "active \[3\]" && \
	    [ "$${r1:-0}" -ge 1 ] && [ "$${r2:-0}" -ge 1 ] && echo "ALL READY" && break; \
	  if [ $$i -ge 6 ]; then \
	    echo "$$s1" | grep -q "inactive \[2\]" && echo "  [fix] robot_1 inactive — injecting initialpose + RESUME" && \
	      oc exec -n $$NS $$NAV1 -c nav2 -- bash -c \
	        'export HOME=/tmp/ros-home; source /usr/lib64/ros-jazzy/setup.bash; \
	         timeout 20 ros2 topic pub /initialpose geometry_msgs/msg/PoseWithCovarianceStamped \
	           "{header:{frame_id:map},pose:{pose:{position:{x:0.0,y:0.0},orientation:{w:1.0}},covariance:[0.01,0,0,0,0,0,0,0.01,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0.005]}}" \
	           --times 3 --qos-reliability best_effort 2>/dev/null || true; sleep 4; \
	         timeout 30 ros2 service call /lifecycle_manager_navigation/manage_nodes \
	           nav2_msgs/srv/ManageLifecycleNodes "{command:2}" 2>/dev/null || true' 2>/dev/null & \
	    echo "$$s2" | grep -q "inactive \[2\]" && echo "  [fix] robot_2 inactive — injecting initialpose + RESUME" && \
	      oc exec -n $$NS $$NAV2 -c nav2 -- bash -c \
	        'export HOME=/tmp/ros-home; source /usr/lib64/ros-jazzy/setup.bash; \
	         QZ=$$(python3 -c "import math; print(math.sin(math.pi/2))"); \
	         QW=$$(python3 -c "import math; print(math.cos(math.pi/2))"); \
	         timeout 20 ros2 topic pub /initialpose geometry_msgs/msg/PoseWithCovarianceStamped \
	           "{header:{frame_id:map},pose:{pose:{position:{x:0.0,y:0.0},orientation:{z:$${QZ},w:$${QW}}},covariance:[0.01,0,0,0,0,0,0,0.01,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0.005]}}" \
	           --times 3 --qos-reliability best_effort 2>/dev/null || true; sleep 4; \
	         timeout 30 ros2 service call /lifecycle_manager_navigation/manage_nodes \
	           nav2_msgs/srv/ManageLifecycleNodes "{command:2}" 2>/dev/null || true' 2>/dev/null & \
	  fi; \
	  sleep 5; \
	done
	@echo "Step 3.5: Verifying robots at spawn (Gazebo SDF positions — no teleport needed)..."
	@echo "  Robots spawn at their SDF-defined positions on Gazebo restart."
	@echo "  Teleporting after AMCL initialization breaks odom consistency."
	@echo "Step 3.6: Waiting 30s for slam_toolbox TF to stabilize on both robots..."
	@sleep 30
	@echo "Step 4: Running RMF + Nav2 LiDAR swap demo..."
	@RMFPOD=$$(oc get pod -n $(NAMESPACE) -l app=rmf-core -o jsonpath='{.items[0].metadata.name}' 2>/dev/null); \
	oc cp demo/rmf_lidar_swap_demo.py $(NAMESPACE)/$$RMFPOD:/tmp/rmf_lidar_swap_demo.py -c rmf-core && \
	oc exec -n $(NAMESPACE) $$RMFPOD -c rmf-core -- bash -c \
	  'export HOME=/tmp/ros-home; \
	   source /opt/ros/jazzy/setup.bash; \
	   source /opt/free_fleet/install/setup.bash 2>/dev/null || true; \
	   python3 /tmp/rmf_lidar_swap_demo.py'

.PHONY: dispatch-collision-swap
dispatch-collision-swap: ## Collision-avoidance swap: restart pods, wait for ready, then run the 3-phase collision demo
	@echo "=== Collision-avoidance swap demo ==="
	@echo "Step 1: Restarting pods (clears nav2_relay cache — required for correct navigation)"
	$(MAKE) restart ROS_DEMO_NS=$(ROS_DEMO_NS)
	@echo "Step 2: Waiting for all pods to roll out..."
	oc rollout status deployment/robot-nav-robot-1 -n $(NAMESPACE) --timeout=4m
	oc rollout status deployment/robot-nav-robot-2 -n $(NAMESPACE) --timeout=4m
	oc rollout status deployment/rmf-core           -n $(NAMESPACE) --timeout=4m
	@echo "Step 3: Polling for bt_navigator ACTIVE + fleet adapter ready..."
	@echo "        (auto-injects initialpose + RESUME if bt_navigator is stuck at inactive)"
	@NS=$(NAMESPACE); \
	for i in $$(seq 1 60); do \
	  NAV1=$$(oc get pod -n $$NS -l app=robot-nav-robot-1 -o jsonpath='{.items[0].metadata.name}' 2>/dev/null); \
	  NAV2=$$(oc get pod -n $$NS -l app=robot-nav-robot-2 -o jsonpath='{.items[0].metadata.name}' 2>/dev/null); \
	  RMF=$$(oc get pod -n $$NS -l app=rmf-core -o jsonpath='{.items[0].metadata.name}' 2>/dev/null); \
	  s1=$$(oc exec -n $$NS $$NAV1 -c nav2 -- bash -c \
	    'export HOME=/tmp/ros-home; source /usr/lib64/ros-jazzy/setup.bash; timeout 4 ros2 lifecycle get /bt_navigator 2>/dev/null' 2>/dev/null); \
	  s2=$$(oc exec -n $$NS $$NAV2 -c nav2 -- bash -c \
	    'export HOME=/tmp/ros-home; source /usr/lib64/ros-jazzy/setup.bash; timeout 4 ros2 lifecycle get /bt_navigator 2>/dev/null' 2>/dev/null); \
	  fleet=$$(oc exec -n $$NS $$RMF -c rmf-core -- bash -c \
	    'export HOME=/tmp/ros-home; source /opt/ros/jazzy/setup.bash; timeout 3 ros2 topic echo /fleet_states --once 2>/dev/null' 2>/dev/null); \
	  r1=$$(echo "$$fleet" | grep -c "name: robot_1" 2>/dev/null || echo 0); \
	  r2=$$(echo "$$fleet" | grep -c "name: robot_2" 2>/dev/null || echo 0); \
	  echo "  [$$i] bt1=$$s1 | bt2=$$s2 | fleet r1=$$r1 r2=$$r2"; \
	  echo "$$s1" | grep -q "active \[3\]" && echo "$$s2" | grep -q "active \[3\]" && \
	    [ "$${r1:-0}" -ge 1 ] && [ "$${r2:-0}" -ge 1 ] && echo "ALL READY" && break; \
	  if [ $$i -ge 6 ]; then \
	    echo "$$s1" | grep -q "inactive \[2\]" && echo "  [fix] robot_1 inactive — injecting initialpose + RESUME" && \
	      oc exec -n $$NS $$NAV1 -c nav2 -- bash -c \
	        'export HOME=/tmp/ros-home; source /usr/lib64/ros-jazzy/setup.bash; \
	         timeout 20 ros2 topic pub /initialpose geometry_msgs/msg/PoseWithCovarianceStamped \
	           "{header:{frame_id:map},pose:{pose:{position:{x:0.0,y:0.0},orientation:{w:1.0}},covariance:[0.01,0,0,0,0,0,0,0.01,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0.005]}}" \
	           --times 3 --qos-reliability best_effort 2>/dev/null || true; sleep 4; \
	         timeout 30 ros2 service call /lifecycle_manager_navigation/manage_nodes \
	           nav2_msgs/srv/ManageLifecycleNodes "{command:2}" 2>/dev/null || true' 2>/dev/null & \
	    echo "$$s2" | grep -q "inactive \[2\]" && echo "  [fix] robot_2 inactive — injecting initialpose + RESUME" && \
	      oc exec -n $$NS $$NAV2 -c nav2 -- bash -c \
	        'export HOME=/tmp/ros-home; source /usr/lib64/ros-jazzy/setup.bash; \
	         QZ=$$(python3 -c "import math; print(math.sin(math.pi/2))"); \
	         QW=$$(python3 -c "import math; print(math.cos(math.pi/2))"); \
	         timeout 20 ros2 topic pub /initialpose geometry_msgs/msg/PoseWithCovarianceStamped \
	           "{header:{frame_id:map},pose:{pose:{position:{x:0.0,y:0.0},orientation:{z:$${QZ},w:$${QW}}},covariance:[0.01,0,0,0,0,0,0,0.01,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0.005]}}" \
	           --times 3 --qos-reliability best_effort 2>/dev/null || true; sleep 4; \
	         timeout 30 ros2 service call /lifecycle_manager_navigation/manage_nodes \
	           nav2_msgs/srv/ManageLifecycleNodes "{command:2}" 2>/dev/null || true' 2>/dev/null & \
	  fi; \
	  sleep 5; \
	done
	@echo "Step 3.5: Teleporting robots to spawn positions..."
	@GZPOD=$$(oc get pod -n $(NAMESPACE) -l app=gazebo-sim -o jsonpath='{.items[0].metadata.name}' 2>/dev/null); \
	oc exec -n $(NAMESPACE) $$GZPOD -c gazebo -- bash -c '\
	  export HOME=/tmp/ros-home; source /usr/lib64/ros-jazzy/setup.bash; \
	  for d in /usr/lib64/ros-jazzy/opt/*/lib64; do [ -d "$$d" ] && export LD_LIBRARY_PATH="$${d}:$${LD_LIBRARY_PATH:-}"; done; \
	  gz service -s /world/tb3_sandbox/set_pose \
	    --reqtype gz.msgs.Pose --reptype gz.msgs.Boolean \
	    --req "name: \"robot_1\" position {x: -2.0 y: -0.5 z: 0.01} orientation {w: 1.0}" --timeout 3000; \
	  gz service -s /world/tb3_sandbox/set_pose \
	    --reqtype gz.msgs.Pose --reptype gz.msgs.Boolean \
	    --req "name: \"robot_2\" position {x: 2.0 y: 0.5 z: 0.01} orientation {x: 0.0 y: 0.0 z: 1.0 w: 0.0}" --timeout 3000; \
	  echo "Robots teleported to spawn"' 2>/dev/null || echo "Teleport skipped"
	@echo "Step 4: Running collision-avoidance swap demo..."
	@RMFPOD=$$(oc get pod -n $(NAMESPACE) -l app=rmf-core -o jsonpath='{.items[0].metadata.name}' 2>/dev/null); \
	oc cp demo/collision_swap_demo.py $(NAMESPACE)/$$RMFPOD:/tmp/collision_swap_demo.py -c rmf-core && \
	oc exec -n $(NAMESPACE) $$RMFPOD -c rmf-core -- bash -c \
	  'export HOME=/tmp/ros-home; \
	   source /opt/ros/jazzy/setup.bash; \
	   source /opt/free_fleet/install/setup.bash 2>/dev/null || true; \
	   python3 /tmp/collision_swap_demo.py'

.PHONY: rmf-status
rmf-status: ## Show fleet state from RMF (robot positions and task status)
	$(eval RMFPOD := $(shell oc get pod -n $(NAMESPACE) -l app=rmf-core -o jsonpath='{.items[0].metadata.name}' 2>/dev/null))
	@test -n "$(RMFPOD)" || { echo "ERROR: rmf-core pod not found"; exit 1; }
	oc exec -n $(NAMESPACE) $(RMFPOD) -c rmf-core -- bash -c \
	  'export HOME=/tmp/ros-home; \
	   source /opt/ros/jazzy/setup.bash; \
	   timeout 5 ros2 topic echo /fleet_states --once 2>/dev/null || echo "No fleet state yet"'

##@ Demo

.PHONY: demo
demo: ## Run the meet-demo: both robots navigate to swap positions
	$(eval GZPOD := $(shell oc get pod -n $(NAMESPACE) -l app=gazebo-sim -o jsonpath='{.items[0].metadata.name}' 2>/dev/null))
	@test -n "$(GZPOD)" || { echo "ERROR: no gazebo-sim pod found in namespace '$(NAMESPACE)'. Run: make demo ROS_DEMO_NS=<your-namespace>"; exit 1; }
	@echo "Copying demo script to $(GZPOD)..."
	oc cp demo/meet_demo.py $(NAMESPACE)/$(GZPOD):/tmp/meet_demo.py -c gazebo
	@echo "Teleporting robots to spawn positions..."
	oc exec -n $(NAMESPACE) $(GZPOD) -c gazebo -- bash -c '\
	  export HOME=/tmp/ros-home; \
	  source /usr/lib64/ros-jazzy/setup.bash; \
	  for d in /usr/lib64/ros-jazzy/opt/*/lib64; do [ -d "$$d" ] && export LD_LIBRARY_PATH="$${d}:$${LD_LIBRARY_PATH:-}"; done; \
	  gz service -s /world/tb3_sandbox/set_pose \
	    --reqtype gz.msgs.Pose --reptype gz.msgs.Boolean \
	    --req "name: \"robot_1\" position {x: -2.0 y: -0.5 z: 0.01} orientation {w: 1.0}" --timeout 3000; \
	  gz service -s /world/tb3_sandbox/set_pose \
	    --reqtype gz.msgs.Pose --reptype gz.msgs.Boolean \
	    --req "name: \"robot_2\" position {x: 2.0 y: 0.5 z: 0.01} orientation {x: 0.0 y: 0.0 z: 1.0 w: 0.0}" --timeout 3000'
	@echo "Starting meet demo (robots swap positions)..."
	$(eval NAV1POD := $(shell oc get pod -n $(NAMESPACE) -l app=robot-nav-robot-1 -o jsonpath='{.items[0].metadata.name}'))
	oc cp demo/meet_demo.py $(NAMESPACE)/$(NAV1POD):/tmp/meet_demo.py -c nav2
	oc exec -n $(NAMESPACE) $(NAV1POD) -c nav2 -- bash -c \
	  'export HOME=/tmp/ros-home; source /usr/lib64/ros-jazzy/setup.bash; python3 /tmp/meet_demo.py'

.PHONY: reset
reset: ## Teleport both robots back to their spawn positions
	$(eval GZPOD := $(shell oc get pod -n $(NAMESPACE) -l app=gazebo-sim -o jsonpath='{.items[0].metadata.name}' 2>/dev/null))
	@test -n "$(GZPOD)" || { echo "ERROR: no gazebo-sim pod found in namespace '$(NAMESPACE)'. Run: make reset ROS_DEMO_NS=<your-namespace>"; exit 1; }
	oc exec -n $(NAMESPACE) $(GZPOD) -c gazebo -- bash -c '\
	  export HOME=/tmp/ros-home; \
	  source /usr/lib64/ros-jazzy/setup.bash; \
	  for d in /usr/lib64/ros-jazzy/opt/*/lib64; do [ -d "$$d" ] && export LD_LIBRARY_PATH="$${d}:$${LD_LIBRARY_PATH:-}"; done; \
	  gz service -s /world/tb3_sandbox/set_pose \
	    --reqtype gz.msgs.Pose --reptype gz.msgs.Boolean \
	    --req "name: \"robot_1\" position {x: -2.0 y: -0.5 z: 0.01} orientation {w: 1.0}" --timeout 3000; \
	  gz service -s /world/tb3_sandbox/set_pose \
	    --reqtype gz.msgs.Pose --reptype gz.msgs.Boolean \
	    --req "name: \"robot_2\" position {x: 2.0 y: 0.5 z: 0.01} orientation {x: 0.0 y: 0.0 z: 1.0 w: 0.0}" --timeout 3000; \
	  echo "Both robots reset to spawn positions."'

##@ Utilities

.PHONY: rerun-patrol
rerun-patrol: ## Reset and re-dispatch patrol without a full pod restart
	@echo "Step 1: Resetting robots to spawn positions..."
	$(MAKE) reset
	@echo "Step 2: Clearing costmaps on both nav2 pods..."
	$(eval NAV1POD := $(shell oc get pod -n $(NAMESPACE) -l app=robot-nav-robot-1 -o jsonpath='{.items[0].metadata.name}' 2>/dev/null))
	$(eval NAV2POD := $(shell oc get pod -n $(NAMESPACE) -l app=robot-nav-robot-2 -o jsonpath='{.items[0].metadata.name}' 2>/dev/null))
	-oc exec -n $(NAMESPACE) $(NAV1POD) -c nav2 -- bash -c \
	  'export HOME=/tmp/ros-home; source /usr/lib64/ros-jazzy/setup.bash; \
	   ros2 service call /global_costmap/clear_entirely_global_costmap std_srvs/srv/Empty "{}" 2>/dev/null; \
	   ros2 service call /local_costmap/clear_entirely_local_costmap  std_srvs/srv/Empty "{}" 2>/dev/null' &
	-oc exec -n $(NAMESPACE) $(NAV2POD) -c nav2 -- bash -c \
	  'export HOME=/tmp/ros-home; source /usr/lib64/ros-jazzy/setup.bash; \
	   ros2 service call /global_costmap/clear_entirely_global_costmap std_srvs/srv/Empty "{}" 2>/dev/null; \
	   ros2 service call /local_costmap/clear_entirely_local_costmap  std_srvs/srv/Empty "{}" 2>/dev/null' &
	sleep 5
	@echo "Step 3: Re-publishing initial poses..."
	-oc exec -n $(NAMESPACE) $(NAV1POD) -c nav2 -- bash -c \
	  'export HOME=/tmp/ros-home; source /usr/lib64/ros-jazzy/setup.bash; \
	   ros2 topic pub "/initialpose" geometry_msgs/msg/PoseWithCovarianceStamped \
	     "{header: {frame_id: map}, pose: {pose: {position: {x: -2.0, y: -0.5}, orientation: {w: 1.0}}, \
	       covariance: [0.02,0,0,0,0,0, 0,0.02,0,0,0,0, 0,0,0,0,0,0, 0,0,0,0,0,0, 0,0,0,0,0,0, 0,0,0,0,0,0.005]}}" \
	     --once 2>/dev/null' &
	-oc exec -n $(NAMESPACE) $(NAV2POD) -c nav2 -- bash -c \
	  'export HOME=/tmp/ros-home; source /usr/lib64/ros-jazzy/setup.bash; \
	   QZ=$$(python3 -c "import math; print(math.sin(math.pi/2))"); \
	   QW=$$(python3 -c "import math; print(math.cos(math.pi/2))"); \
	   ros2 topic pub "/initialpose" geometry_msgs/msg/PoseWithCovarianceStamped \
	     "{header: {frame_id: map}, pose: {pose: {position: {x: 2.0, y: 0.5}, orientation: {z: $${QZ}, w: $${QW}}}, \
	       covariance: [0.02,0,0,0,0,0, 0,0.02,0,0,0,0, 0,0,0,0,0,0, 0,0,0,0,0,0, 0,0,0,0,0,0, 0,0,0,0,0,0.005]}}" \
	     --once 2>/dev/null' &
	sleep 5
	@echo "Step 4: Restarting rmf-core only (clears stuck task, keeps nav2 and Gazebo running)..."
	oc rollout restart deployment/rmf-core -n $(NAMESPACE)
	oc rollout status deployment/rmf-core -n $(NAMESPACE) --timeout=5m
	@echo "Step 5: Waiting 120s for AMCL convergence + RMF 90s startup..."
	sleep 120
	@echo "Step 6: Fleet state (verify before dispatching)..."
	$(MAKE) rmf-status

.PHONY: status
status: ## Show pod status in the demo namespace
	oc get pods -n $(NAMESPACE) -o wide

.PHONY: routes
routes: ## Show OpenShift route URLs
	oc get routes -n $(NAMESPACE)

.PHONY: set-image
set-image: ## Upgrade the release with a new image tag (make set-image TAG=v1.2)
	helm upgrade $(RELEASE) $(CHART) \
	  --namespace $(NAMESPACE) \
	  --reuse-values \
	  --set image.repository=$(REGISTRY)/$(IMAGE) \
	  --set image.tag=$(TAG)
