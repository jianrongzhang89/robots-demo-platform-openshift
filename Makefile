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

##@ Open-RMF

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
