initialize_camera_follow() {
  for _attempt in $(seq 1 90); do
    if timeout 3 gz service -i -s /gui/follow 2>/dev/null |
        grep -q 'gz.msgs.StringMsg, gz.msgs.Boolean' &&
        timeout 4 gz service -s /gui/follow \
          --reqtype gz.msgs.StringMsg --reptype gz.msgs.Boolean \
          --timeout 3000 --req 'data: "robot_1"' 2>/dev/null |
        grep -q 'data: true' &&
        timeout 4 gz service -s /gui/follow/offset \
          --reqtype gz.msgs.Vector3d --reptype gz.msgs.Boolean \
          --timeout 3000 --req 'x: 0 y: 0 z: 5' 2>/dev/null |
        grep -q 'data: true' &&
        timeout 3 gz topic -i -t /gui/track 2>/dev/null |
        grep -q 'Subscribers'; then
      for _publish in $(seq 1 3); do
        timeout 2 gz topic -t /gui/track -m gz.msgs.CameraTrack \
          -p 'track_mode: FOLLOW_LOOK_AT follow_target: {name: "robot_1"} track_target: {name: "robot_1"} follow_offset: {x: 0 y: 0 z: 5} track_offset: {x: 0 y: 0 z: 0} follow_pgain: 0.02 track_pgain: 0.02' \
          >/dev/null 2>&1 || true
        sleep 0.5
      done
      echo "[semantic-navigation] Gazebo camera following robot_1 (overhead)"
      return 0
    fi
    sleep 1
  done
  echo "[semantic-navigation] camera follow initialization timed out" >&2
  return 1
}
initialize_camera_follow
