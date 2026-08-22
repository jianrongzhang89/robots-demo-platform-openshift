REGISTRY    ?= quay.io/jianrzha
IMAGE       ?= ros2-demo
IMAGE_RMF   ?= ros2-rmf
IMAGE_HOTEL ?= ros2-rmf-hotel
TAG         ?= latest
# Use ROS_DEMO_NS to avoid clashing with any NAMESPACE env var set by the shell
ROS_DEMO_NS ?= ros2-multi-robot
RELEASE    ?= multi-robot-demo
CHART      := helm/multi-robot-demo

# Convenience alias so existing targets keep working
NAMESPACE  := $(ROS_DEMO_NS)

IMAGE_REF       := $(REGISTRY)/$(IMAGE):$(TAG)
IMAGE_RMF_REF   := $(REGISTRY)/$(IMAGE_RMF):$(TAG)
IMAGE_HOTEL_REF := $(REGISTRY)/$(IMAGE_HOTEL):$(TAG)

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

.PHONY: build-house
build-house: ## Build turtlebot3-house image (extends multi-demo, adds house assets)
	$(PODMAN) build --platform linux/amd64 -t $(IMAGE_REF) -f Containerfile.turtlebot3-house .

.PHONY: build-push-house
build-push-house: build-house push ## Build and push the turtlebot3-house image

.PHONY: build-rmf
build-rmf: ## Build the Open-RMF core container image (~20 min first build)
	$(PODMAN) build --platform linux/amd64 -t $(IMAGE_RMF_REF) -f Containerfile.rmf .

.PHONY: push-rmf
push-rmf: ## Push the RMF image to the registry
	$(PODMAN) push $(IMAGE_RMF_REF)

.PHONY: build-push-rmf
build-push-rmf: build-rmf push-rmf ## Build and push the RMF image

.PHONY: build-hotel
build-hotel: ## Build the Open-RMF Hotel World image (source-builds rmf_demos; slow first build)
	$(PODMAN) build --platform linux/amd64 -t $(IMAGE_HOTEL_REF) -f Containerfile.hotel .

.PHONY: push-hotel
push-hotel: ## Push the Hotel World image to the registry
	$(PODMAN) push $(IMAGE_HOTEL_REF)

.PHONY: build-push-hotel
build-push-hotel: build-hotel push-hotel ## Build and push the Hotel World image

##@ Deploy

.PHONY: deploy
deploy: ## Install or upgrade the Helm release on OpenShift
	helm upgrade --install $(RELEASE) $(CHART) \
	  --namespace $(NAMESPACE) \
	  --create-namespace \
	  --set image.repository=$(REGISTRY)/$(IMAGE) \
	  --set image.tag=$(TAG) \
	  --wait --timeout 10m

.PHONY: deploy-hotel
deploy-hotel: ## Deploy the Open-RMF Hotel World demo (single pod; use ROS_DEMO_NS=ros2-rmf-hotel)
	helm upgrade --install $(RELEASE) $(CHART) \
	  --namespace $(NAMESPACE) \
	  --create-namespace \
	  -f $(CHART)/values.yaml \
	  -f $(CHART)/values-hotel.yaml \
	  --set namespace=$(NAMESPACE) \
	  --set hotel.image=$(IMAGE_HOTEL_REF) \
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
dispatch-rmf-lidar: ## Hybrid RMF+Nav2 demo: robot_1 via RMF fleet management, robot_2 via direct Nav2
	@echo "========================================================================"
	@echo " HYBRID DEMO: Open-RMF fleet management + Nav2 LiDAR collision avoidance"
	@echo "========================================================================"
	@echo ""
	@echo " Architecture:"
	@echo "   robot_1 — FULLY managed by Open-RMF"
	@echo "     dispatch_patrol → RMF task scheduler → free_fleet_adapter"
	@echo "     → rmf_navigate_cmd → nav2_relay → Nav2 navigate_to_pose"
	@echo "     RMF tracks position, computes ETAs, can CANCEL on ETA drift."
	@echo ""
	@echo "   robot_2 — Direct Nav2 (NOT managed by RMF)"
	@echo "     rmf_navigate_cmd published directly, bypassing the fleet adapter."
	@echo "     Nav2 collision_monitor detects robot_1 via LiDAR and slows robot_2."
	@echo "     RMF has no visibility of robot_2 for this navigation leg."
	@echo ""
	@echo " KNOWN LIMITATION — free_fleet_adapter bug (open-rmf/rmf_ros2#503):"
	@echo "   When both robots are RMF-managed on the same bidirectional lane,"
	@echo "   responsive_wait deadlocks if they arrive at both lane endpoints"
	@echo "   simultaneously. The fleet adapter cannot break the symmetry to"
	@echo "   grant one robot transit priority. This hybrid approach works around"
	@echo "   the bug by removing robot_2 from RMF management for the corridor leg."
	@echo "   Full bilateral RMF negotiation requires fixing rmf_ros2#503 upstream."
	@echo "========================================================================"
	@echo ""
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
	@echo ""
	@echo "Step 3: Dispatching robot_1 via RMF, then releasing robot_2 direct when robot_1 is mid-corridor..."
	@NS=$(NAMESPACE); \
	GZPOD=$$(oc get pod -n $$NS -l app=gazebo-sim -o jsonpath='{.items[0].metadata.name}' 2>/dev/null); \
	RMFPOD=$$(oc get pod -n $$NS -l app=rmf-core -o jsonpath='{.items[0].metadata.name}' 2>/dev/null); \
	NAV2POD=$$(oc get pod -n $$NS -l app=robot-nav-robot-2 -o jsonpath='{.items[0].metadata.name}' 2>/dev/null); \
	echo "[RMF ] Dispatching robot_1 patrol: s_in → s_out (3 loops, fully RMF-managed)"; \
	oc exec -n $$NS $$RMFPOD -c rmf-core -- bash -c \
	  'export HOME=/tmp/ros-home; source /opt/ros/jazzy/setup.bash; \
	   ros2 run rmf_demos_tasks dispatch_patrol \
	     -F turtlebot3 -R robot_1 -p s_in s_out -n 3 --use_sim_time 2>/dev/null' 2>/dev/null; \
	echo "[NAV2] Waiting for robot_1 to enter corridor (world x > -0.5)..."; \
	for i in $$(seq 1 120); do \
	  R1X=$$(oc exec -n $$NS $$GZPOD -c gazebo -- bash -c \
	    'export HOME=/tmp/ros-home; source /usr/lib64/ros-jazzy/setup.bash; \
	     for d in /usr/lib64/ros-jazzy/opt/*/lib64; do [ -d "$$d" ] && export LD_LIBRARY_PATH="$${d}:$${LD_LIBRARY_PATH:-}"; done; \
	     gz topic -e -t /world/tb3_sandbox/dynamic_pose/info --duration 100 2>/dev/null | \
	     grep -A 4 "name: .robot_1" | grep "x:" | head -1 | awk '"'"'{print $$2}'"'"'' 2>/dev/null); \
	  [ -n "$$R1X" ] && echo "  [$$i] robot_1 world_x=$$R1X"; \
	  [ -n "$$R1X" ] && python3 -c "import sys; exit(0 if float('$$R1X') > -0.5 else 1)" 2>/dev/null && \
	    { echo ""; echo "[NAV2] robot_1 mid-corridor (x=$$R1X) — sending robot_2 direct rmf_navigate_cmd"; break; }; \
	  sleep 5; \
	done; \
	echo "[NAV2] Direct goal to robot_2: world(-1.5, -1.75) yaw=3.14 (s_in, westbound)"; \
	echo "       Published directly to /rmf_navigate_cmd on robot_2 nav2 pod DDS domain."; \
	echo "       robot_2 navigates home → south outer corridor → s_in, heading toward robot_1."; \
	echo "       Nav2 collision_monitor detects robot_1 via LiDAR and reduces robot_2 velocity."; \
	echo "       RMF is NOT managing this leg — no traffic negotiation for robot_2."; \
	NAV2POD=$$(oc get pod -n $$NS -l app=robot-nav-robot-2 -o jsonpath='{.items[0].metadata.name}' 2>/dev/null); \
	oc exec -n $$NS $$NAV2POD -c nav2 -- bash -c \
	  'export HOME=/tmp/ros-home; source /usr/lib64/ros-jazzy/setup.bash; \
	   timeout 10 ros2 topic pub /rmf_navigate_cmd std_msgs/msg/String \
	     "data: '"'"'R2DIRECT001 -1.5 -1.75 3.14'"'"'" --times 5 2>/dev/null || true' 2>/dev/null; \
	echo "[NAV2] robot_2 command sent. Watch noVNC: both robots in south corridor, head-on approach."; \
	echo ""

.PHONY: dispatch-swap-patrol
dispatch-swap-patrol: ## Swap patrol: robots exchange spawn positions via separate outer corridors (full RMF)
	@echo "=== Swap Patrol: robots swap positions via separate outer corridors ==="
	@echo ""
	@echo " robot_1 (blue): robot_1_home → s_in(-1.5,-1.75) → s_out(1.5,-1.75) → robot_2_home"
	@echo " robot_2 (red):  robot_2_home → n_in(1.5,1.75)   → n_out(-1.5,1.75) → robot_1_home"
	@echo ""
	@echo " Both robots are fully managed by Open-RMF. They travel on opposite"
	@echo " outer corridors (south y=-1.75, north y=+1.75), 3.5 m apart — no"
	@echo " collision risk. RMF traffic scheduler routes each robot around the"
	@echo " pillar grid via the safe outer-corridor waypoints."
	@echo ""
	$(MAKE) restart ROS_DEMO_NS=$(ROS_DEMO_NS)
	oc rollout status deployment/robot-nav-robot-1 -n $(NAMESPACE) --timeout=5m
	oc rollout status deployment/robot-nav-robot-2 -n $(NAMESPACE) --timeout=5m
	oc rollout status deployment/rmf-core           -n $(NAMESPACE) --timeout=4m
	@echo "Polling for bt_navigator ACTIVE + fleet adapter ready (both robots)..."
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
	@RMFPOD=$$(oc get pod -n $(NAMESPACE) -l app=rmf-core -o jsonpath='{.items[0].metadata.name}' 2>/dev/null); \
	echo "[RMF] Dispatching robot_1: robot_1_home → s_in → s_out → robot_2_home (south corridor)"; \
	oc exec -n $(NAMESPACE) $$RMFPOD -c rmf-core -- bash -c \
	  'export HOME=/tmp/ros-home; \
	   source /opt/ros/jazzy/setup.bash; \
	   source /opt/free_fleet/install/setup.bash 2>/dev/null || true; \
	   ros2 run rmf_demos_tasks dispatch_patrol \
	     -F turtlebot3 -R robot_1 \
	     -p robot_1_home s_in s_out robot_2_home \
	     -n 1 --use_sim_time 2>/dev/null'; \
	echo "[RMF] Dispatching robot_2: robot_2_home → n_in → n_out → robot_1_home (north corridor)"; \
	oc exec -n $(NAMESPACE) $$RMFPOD -c rmf-core -- bash -c \
	  'export HOME=/tmp/ros-home; \
	   source /opt/ros/jazzy/setup.bash; \
	   source /opt/free_fleet/install/setup.bash 2>/dev/null || true; \
	   ros2 run rmf_demos_tasks dispatch_patrol \
	     -F turtlebot3 -R robot_2 \
	     -p robot_2_home n_in n_out robot_1_home \
	     -n 1 --use_sim_time 2>/dev/null'; \
	echo "[RMF] Both tasks dispatched. Watch noVNC: robots crossing in opposite outer corridors."

.PHONY: dispatch-house-patrol
dispatch-house-patrol: ## House demo: robot_1 left corridor, robot_2 right corridor (validated waypoints)
	@echo "=== TurtleBot3 House patrol demo ==="
	@echo " robot_1 (blue): robot_1_home(-2,-0.5) ↔ left_north(-2,+0.5) ↔ sw_open(-1.5,-1.5)"
	@echo " robot_2 (red):  robot_2_home(+2,-0.5) ↔ right_north(+2,+0.5) ↔ se_open(+1.5,-1.5)"
	@echo " All waypoints confirmed free in map analysis (pixel=254, 100% clearance at r=5px)"
	@RMFPOD=$$(oc get pod -n $(NAMESPACE) -l app=rmf-core -o jsonpath='{.items[0].metadata.name}' 2>/dev/null); \
	echo "[RMF] Dispatching robot_1: robot_1_home → left_north → sw_open (3 loops)..."; \
	oc exec -n $(NAMESPACE) $$RMFPOD -c rmf-core -- bash -c \
	  'export HOME=/tmp/ros-home; source /opt/ros/jazzy/setup.bash; \
	   source /opt/free_fleet/install/setup.bash 2>/dev/null || true; \
	   ros2 run rmf_demos_tasks dispatch_patrol \
	     -F turtlebot3 -R robot_1 \
	     -p robot_1_home left_north sw_open -n 3 --use_sim_time 2>/dev/null'; \
	echo "[RMF] Dispatching robot_2: robot_2_home → right_north → se_open (3 loops)..."; \
	oc exec -n $(NAMESPACE) $$RMFPOD -c rmf-core -- bash -c \
	  'export HOME=/tmp/ros-home; source /opt/ros/jazzy/setup.bash; \
	   source /opt/free_fleet/install/setup.bash 2>/dev/null || true; \
	   ros2 run rmf_demos_tasks dispatch_patrol \
	     -F turtlebot3 -R robot_2 \
	     -p robot_2_home right_north se_open -n 3 --use_sim_time 2>/dev/null'; \
	echo "[RMF] Both dispatched. Watch noVNC: robots patrol opposite corridors of the house."

# Hotel demo dispatch — overridable waypoints/loops.
# Default: multi-level patrol from lobby up to a level-3 room via the lift.
# Waypoint names come from the source-built rmf_demos_maps hotel nav graphs;
# confirm them with:  oc exec ... -- ros2 run rmf_demos_tasks dispatch_patrol -h
# and by inspecting the generated nav_graphs. Override with:
#   make dispatch-hotel HOTEL_WAYPOINTS="L1_n1 L3_room1" HOTEL_LOOPS=1
HOTEL_WAYPOINTS ?= L3_room1 L3_room1
HOTEL_LOOPS     ?= 1

.PHONY: dispatch-hotel
dispatch-hotel: ## Hotel demo: dispatch a multi-level patrol (lobby → level-3 room via lift)
	@echo "=== Open-RMF Hotel World dispatch ==="
	@echo " Waypoints: $(HOTEL_WAYPOINTS)   loops: $(HOTEL_LOOPS)"
	@POD=$$(oc get pod -n $(NAMESPACE) -l app=hotel-sim -o jsonpath='{.items[0].metadata.name}' 2>/dev/null); \
	test -n "$$POD" || { echo "ERROR: hotel-sim pod not found in namespace '$(NAMESPACE)'"; exit 1; }; \
	echo "[RMF] Dispatching patrol on pod $$POD ..."; \
	oc exec -n $(NAMESPACE) $$POD -c hotel -- bash -c \
	  'export HOME=/tmp/ros-home; source /opt/ros/jazzy/setup.bash; \
	   source /opt/rmf_demos_ws/install/setup.bash 2>/dev/null || true; \
	   ros2 run rmf_demos_tasks dispatch_patrol \
	     -p $(HOTEL_WAYPOINTS) -n $(HOTEL_LOOPS) --use_sim_time'; \
	echo "[RMF] Dispatched. Watch noVNC: robot routes to the lift, waits, rides up, completes."

.PHONY: patrol-hotel
patrol-hotel: ## Hotel demo: start continuous 4-robot patrol loop (runs until Ctrl-C)
	@POD=$$(oc get pod -n $(NAMESPACE) -l app=hotel-sim -o jsonpath='{.items[0].metadata.name}' 2>/dev/null); \
	test -n "$$POD" || { echo "ERROR: hotel-sim pod not found in namespace '$(NAMESPACE)'"; exit 1; }; \
	echo "[Hotel] Starting continuous patrol loop on pod $$POD ..."; \
	echo "[Hotel] Each robot patrols its own zone — Ctrl-C to stop."; \
	oc exec -n $(NAMESPACE) $$POD -- python3 /scripts/hotel_patrol_loop.py

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
