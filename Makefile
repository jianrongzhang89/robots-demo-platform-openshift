REGISTRY   ?= quay.io/jianrzha
IMAGE      ?= ros2-demo
TAG        ?= latest
NAMESPACE  ?= ros2-multi-robot
RELEASE    ?= multi-robot-demo
CHART      := helm/multi-robot-demo

IMAGE_REF  := $(REGISTRY)/$(IMAGE):$(TAG)

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
build: ## Build the container image (requires podman)
	$(PODMAN) build --platform linux/amd64 -t $(IMAGE_REF) -f Containerfile .

.PHONY: push
push: ## Push the container image to the registry
	$(PODMAN) push $(IMAGE_REF)

.PHONY: build-push
build-push: build push ## Build and push the container image

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
restart: ## Rolling restart of all demo pods
	oc rollout restart deployment/gazebo-sim -n $(NAMESPACE)
	@for d in $$(oc get deployments -n $(NAMESPACE) -o name | grep robot-nav); do \
	  oc rollout restart $$d -n $(NAMESPACE); \
	done

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

##@ Utilities

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
