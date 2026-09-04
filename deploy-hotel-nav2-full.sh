#!/usr/bin/env bash
# Deploy full hybrid Hotel + Nav2 architecture with all 4 pods
#
# This script deploys the complete hybrid architecture after the hotel image
# has been rebuilt with Free Fleet and entrypoint-rmf.sh:
#   - hotel-sim: Gazebo hotel world + TurtleBot3 spawn + Zenoh bridge
#   - zenoh-router: Federation hub
#   - robot-nav-robot-1: Nav2 stack with multi-level map switching
#   - rmf-core: Free Fleet adapter + RMF task dispatcher

set -e

NAMESPACE="ros2-rmf-hotel"
RELEASE="multi-robot-demo"
CHART="./helm/multi-robot-demo"

echo "===================================================="
echo " Full Hybrid Hotel + Nav2 Deployment (4/4 pods)"
echo "===================================================="
echo ""
echo "Deploying with:"
echo "  - Hotel image: quay.io/jianrzha/ros2-rmf-hotel:latest"
echo "  - TurtleBot3 spawn timeout: 180s"
echo "  - Free Fleet with multi-level navigation"
echo "  - RMF core pod enabled"
echo ""

# Deploy
echo "Deploying Helm release..."
helm upgrade --install "${RELEASE}" "${CHART}" \
  -f "${CHART}/values.yaml" \
  -f "${CHART}/values-hotel-nav2.yaml" \
  --set rmf.enabled=true \
  -n "${NAMESPACE}" \
  --create-namespace

echo ""
echo "Deployment initiated. Waiting 30s for pods to start..."
sleep 30

echo ""
echo "===================================================="
echo " Pod Status"
echo "===================================================="
oc get pods -n "${NAMESPACE}"

echo ""
echo "===================================================="
echo " Verification Steps"
echo "===================================================="
echo ""
echo "1. Check pod status:"
echo "   oc get pods -n ${NAMESPACE}"
echo ""
echo "2. Check hotel-sim logs for TurtleBot3 spawn:"
echo "   oc logs -n ${NAMESPACE} -l app=hotel-sim -c hotel --tail=100 | grep spawn"
echo ""
echo "3. Check rmf-core logs for Free Fleet startup:"
echo "   oc logs -n ${NAMESPACE} -l app=rmf-core -c rmf-core --tail=100"
echo ""
echo "4. Access noVNC to verify TurtleBot3 is visible:"
echo "   https://hotel-novnc-${NAMESPACE}.apps.ai-dev02.kni.syseng.devcluster.openshift.com"
echo ""
echo "5. Test Nav2 AMCL localization:"
echo "   oc exec -n ${NAMESPACE} \$(oc get pod -n ${NAMESPACE} -l app=robot-nav,robot=robot-1 -o name) -c nav2 -- \\"
echo "     bash -c 'source /opt/ros/jazzy/setup.bash && ros2 topic echo /robot_1/amcl_pose --once'"
echo ""
echo "6. Test Free Fleet registration:"
echo "   oc exec -n ${NAMESPACE} \$(oc get pod -n ${NAMESPACE} -l app=rmf-core -o name) -c rmf-core -- \\"
echo "     bash -c 'source /opt/ros/jazzy/setup.bash && ros2 topic echo /fleet_states --once'"
echo ""
echo "===================================================="
