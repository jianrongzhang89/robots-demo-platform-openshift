#!/usr/bin/env bash
# Verify Hotel + Nav2 hybrid deployment
# Run after deploy-hotel-nav2.sh completes

set -e

NAMESPACE="ros2-rmf-hotel"

echo "==========================================="
echo " Hotel + Nav2 Deployment Verification"
echo "==========================================="
echo ""

# Get pod names
echo "[1/6] Getting pod names..."
HOTEL_POD=$(oc get pod -n $NAMESPACE -l app=hotel-sim -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
ZENOH_POD=$(oc get pod -n $NAMESPACE -l app=zenoh-router -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
NAV2_POD=$(oc get pod -n $NAMESPACE -l app=robot-nav-robot-1 -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
RMF_POD=$(oc get pod -n $NAMESPACE -l app=rmf-core -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")

if [ -z "$HOTEL_POD" ]; then
  echo "  ✗ hotel-sim pod not found"
else
  echo "  ✓ hotel-sim: $HOTEL_POD"
fi

if [ -z "$ZENOH_POD" ]; then
  echo "  ✗ zenoh-router pod not found"
else
  echo "  ✓ zenoh-router: $ZENOH_POD"
fi

if [ -z "$NAV2_POD" ]; then
  echo "  ✗ robot-nav pod not found"
else
  echo "  ✓ robot-nav: $NAV2_POD"
fi

if [ -z "$RMF_POD" ]; then
  echo "  ✗ rmf-core pod not found"
else
  echo "  ✓ rmf-core: $RMF_POD"
fi

echo ""

# Check pod status
echo "[2/6] Checking pod status..."
oc get pods -n $NAMESPACE
echo ""

# Check TurtleBot3 spawn
if [ -n "$HOTEL_POD" ]; then
  echo "[3/6] Checking TurtleBot3 spawn..."
  if oc logs -n $NAMESPACE $HOTEL_POD -c hotel --tail=100 | grep -q "robot_1 spawn complete"; then
    echo "  ✓ TurtleBot3 spawned successfully"
  else
    echo "  ⚠ TurtleBot3 spawn not confirmed (check logs)"
  fi
  echo ""
fi

# Check Nav2 multi-level mode
if [ -n "$NAV2_POD" ]; then
  echo "[4/6] Checking Nav2 multi-level mode..."
  if oc logs -n $NAMESPACE $NAV2_POD -c nav2 --tail=100 | grep -q "Multi-level navigation ENABLED"; then
    echo "  ✓ Multi-level navigation enabled"
  else
    echo "  ⚠ Multi-level mode not confirmed (check logs)"
  fi
  echo ""
fi

# Check Free Fleet
if [ -n "$RMF_POD" ]; then
  echo "[5/6] Checking Free Fleet registration..."
  if oc logs -n $NAMESPACE $RMF_POD -c rmf-core --tail=100 | grep -q "robot_1"; then
    echo "  ✓ robot_1 detected in Free Fleet logs"
  else
    echo "  ⚠ robot_1 not yet in Free Fleet logs"
  fi
  echo ""
fi

# Get noVNC URL
echo "[6/6] Getting noVNC URL..."
NOVNC_URL=$(oc get route -n $NAMESPACE hotel-novnc -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
if [ -n "$NOVNC_URL" ]; then
  echo "  ✓ noVNC: https://$NOVNC_URL"
else
  echo "  ⚠ noVNC route not found"
fi
echo ""

echo "==========================================="
echo " Verification Complete"
echo "==========================================="
echo ""
echo "Next steps:"
echo "  1. Open noVNC in browser to see TurtleBot3"
echo "  2. Check detailed logs:"
echo "       oc logs -n $NAMESPACE $HOTEL_POD -c hotel --tail=50"
echo "       oc logs -n $NAMESPACE $NAV2_POD -c nav2 --tail=50"
echo "       oc logs -n $NAMESPACE $RMF_POD -c rmf-core --tail=50"
echo "  3. Test single-level navigation (see DEPLOYMENT-STEPS.md)"
echo "  4. Test multi-level navigation (see DEPLOYMENT-STEPS.md)"
