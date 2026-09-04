#!/usr/bin/env bash
# Deploy Hotel + Nav2 hybrid architecture
# Run this after hotel image build completes

set -e

echo "====================================="
echo " Hotel + Nav2 Hybrid Deployment"
echo "====================================="
echo ""

# Check we're in the right directory
if [ ! -f "helm/multi-robot-demo/values-hotel-nav2.yaml" ]; then
  echo "ERROR: Run this from repository root"
  exit 1
fi

# Deploy
echo "Deploying hybrid architecture..."
helm upgrade --install multi-robot-demo ./helm/multi-robot-demo \
  -f helm/multi-robot-demo/values.yaml \
  -f helm/multi-robot-demo/values-hotel-nav2.yaml \
  -n ros2-rmf-hotel \
  --create-namespace \
  --wait \
  --timeout 10m

echo ""
echo "====================================="
echo " Deployment Complete!"
echo "====================================="
echo ""
echo "Checking pod status..."
oc get pods -n ros2-rmf-hotel

echo ""
echo "Expected pods:"
echo "  - hotel-sim (with optional Zenoh sidecar)"
echo "  - zenoh-router"
echo "  - robot-nav-robot-1"
echo "  - rmf-core"
echo ""
echo "Next: Wait for all pods to be Running, then run:"
echo "  ./verify-deployment.sh"
