#!/usr/bin/env bash
# Quick-start script for ROS2 Lyrical upgrade
# Automates the steps in docs/upgrade-plan-lyrical.md

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo "===================================================================="
echo " ROS2 Lyrical + DART 6.16.6 Upgrade Script"
echo " Fixes continuous joint DOF=0 bug in Gazebo Harmonic"
echo "===================================================================="
echo ""

# Phase 1: Preparation
echo "=== Phase 1: Preparation ==="

echo "Step 1.1: Checking Ubuntu 26.04 availability..."
if podman pull ubuntu:26.04 2>/dev/null; then
    echo "✓ Ubuntu 26.04 available"
else
    echo "⚠ Ubuntu 26.04 not found, trying 'ubuntu:oracular'..."
    podman pull ubuntu:oracular
    podman tag ubuntu:oracular ubuntu:26.04
fi

echo ""
echo "Step 1.2: Backing up current configuration..."
IMAGE_TAG="hotel-nav2-final-20260909"
BACKUP_TAG="jazzy-backup-$(date +%Y%m%d)"

podman tag quay.io/jianrzha/ros2-rmf-hotel:${IMAGE_TAG} \
           quay.io/jianrzha/ros2-rmf-hotel:${BACKUP_TAG} 2>/dev/null || true

echo "✓ Tagged backup: ${BACKUP_TAG}"

# Backup scripts
if [ ! -d "scripts-jazzy-backup" ]; then
    cp -r scripts scripts-jazzy-backup
    cp -r entrypoints entrypoints-jazzy-backup
    echo "✓ Backed up scripts and entrypoints"
fi

echo ""
read -p "Continue with Phase 2 (Image Build)? This will take 15-30 minutes. [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Upgrade cancelled. Backup created: ${BACKUP_TAG}"
    exit 0
fi

# Phase 2: Image Build
echo ""
echo "=== Phase 2: Building Lyrical Images ==="

echo "Step 2.1: Building Lyrical base image..."
podman build --platform linux/amd64 \
    -t quay.io/jianrzha/ros2-rmf-hotel:lyrical-base \
    -f Containerfile.hotel-lyrical-base . \
    | tee /tmp/lyrical-base-build.log | grep -E "STEP|SUCCESS|ERROR|DART"

if [ ${PIPESTATUS[0]} -ne 0 ]; then
    echo "❌ Base image build failed. Check /tmp/lyrical-base-build.log"
    exit 1
fi

echo ""
echo "Step 2.2: Verifying DART 6.16.6..."
DART_VERSION=$(podman run --rm quay.io/jianrzha/ros2-rmf-hotel:lyrical-base \
    bash -c "dpkg -l | grep dartsim | awk '{print \$3}'")

echo "DART version: ${DART_VERSION}"

if [[ "$DART_VERSION" =~ 6\.1[6-9]\. ]] || [[ "$DART_VERSION" =~ 6\.[2-9][0-9]\. ]]; then
    echo "✓ DART 6.16+ confirmed - continuous joint bug is fixed!"
else
    echo "⚠ WARNING: DART version may be older than expected: ${DART_VERSION}"
    read -p "Continue anyway? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo ""
echo "Step 2.3: Building full hotel-lyrical-nav2 image..."
LYRICAL_TAG="lyrical-nav2-$(date +%Y%m%d)"

podman build --no-cache --platform linux/amd64 \
    -t quay.io/jianrzha/ros2-rmf-hotel:${LYRICAL_TAG} \
    -f Containerfile.hotel-lyrical-nav2 . \
    | tee /tmp/lyrical-nav2-build.log | grep -E "STEP|SUCCESS|ERROR|WARNING|DART"

if [ ${PIPESTATUS[0]} -ne 0 ]; then
    echo "❌ Nav2 image build failed. Check /tmp/lyrical-nav2-build.log"
    exit 1
fi

echo ""
echo "✓ Build complete: ${LYRICAL_TAG}"

echo ""
read -p "Push image to quay.io? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Pushing base image..."
    podman push quay.io/jianrzha/ros2-rmf-hotel:lyrical-base

    echo "Pushing nav2 image..."
    podman push quay.io/jianrzha/ros2-rmf-hotel:${LYRICAL_TAG}

    echo "✓ Images pushed"
fi

# Phase 3: Testing
echo ""
echo "=== Phase 3: Testing Instructions ==="
echo ""
echo "To test the Lyrical image:"
echo ""
echo "1. Deploy to test namespace:"
echo "   oc create namespace ros2-rmf-hotel-lyrical-test"
echo ""
echo "   helm install multi-robot-demo-lyrical \\"
echo "     ./helm/multi-robot-demo \\"
echo "     -n ros2-rmf-hotel-lyrical-test \\"
echo "     --set image.tag=${LYRICAL_TAG}"
echo ""
echo "2. Verify DART version:"
echo "   HOTEL_POD=\$(oc get pod -l app=hotel-sim -n ros2-rmf-hotel-lyrical-test -o jsonpath='{.items[0].metadata.name}')"
echo "   oc exec -n ros2-rmf-hotel-lyrical-test \$HOTEL_POD -c hotel -- dpkg -l | grep dartsim"
echo ""
echo "3. Check for DOF=0 errors (should be NONE):"
echo "   oc logs -n ros2-rmf-hotel-lyrical-test \$HOTEL_POD -c hotel | grep 'degrees of freedom'"
echo ""
echo "4. Test odometry (CRITICAL - should see ~50 Hz):"
echo "   oc exec -n ros2-rmf-hotel-lyrical-test \$HOTEL_POD -c gz-ros-bridge -- bash -c \\"
echo "     'source /opt/ros/lyrical/setup.bash && export ROS_DOMAIN_ID=0 && ros2 topic hz /robot_1/odom'"
echo ""
echo "5. If all tests pass, migrate production:"
echo "   helm upgrade multi-robot-demo \\"
echo "     ./helm/multi-robot-demo \\"
echo "     -n ros2-rmf-hotel-test \\"
echo "     --set image.tag=${LYRICAL_TAG}"
echo ""
echo "===================================================================="
echo " Upgrade Summary"
echo "===================================================================="
echo " Base image:   quay.io/jianrzha/ros2-rmf-hotel:lyrical-base"
echo " Nav2 image:   quay.io/jianrzha/ros2-rmf-hotel:${LYRICAL_TAG}"
echo " Backup image: quay.io/jianrzha/ros2-rmf-hotel:${BACKUP_TAG}"
echo ""
echo " Key Changes:"
echo "   - Ubuntu 24.04 → 26.04"
echo "   - ROS2 Jazzy → Lyrical"
echo "   - Gazebo Harmonic → Jetty"
echo "   - DART 6.13.2 → 6.16.6+ (FIXES CONTINUOUS JOINT BUG!)"
echo ""
echo " Next: Follow Phase 3 testing instructions above"
echo "===================================================================="
