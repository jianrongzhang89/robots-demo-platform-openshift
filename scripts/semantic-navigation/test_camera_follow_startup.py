"""Exercise the standalone GUI initialization without Gazebo or robot motion."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ENTRYPOINT = Path(__file__).with_name("entrypoint-phase1.sh")


def follow_function():
    return re.search(r"initialize_camera_follow\(\) \{.*?\n\}",
                     ENTRYPOINT.read_text(), re.DOTALL).group(0)


class CameraFollowStartupTest(unittest.TestCase):
    def initialize(self, failure=""):
        # Shell functions stand in for transport and time; the actual startup
        # function runs unchanged, including its finite retry/publish loops.
        stubs = r'''
timeout() { shift; "$@"; }
sleep() { :; }
gz() {
  printf '%s\n' "$*" >> "$CAMERA_TEST_LOG"
  case "$*" in
    'service -i -s /gui/follow')
      [ "$CAMERA_TEST_FAILURE" != discovery ] || return 0
      echo 'tcp://127.0.0.1:1234, gz.msgs.StringMsg, gz.msgs.Boolean';;
    'service -s /gui/follow '*| 'service -s /gui/follow/offset '*)
      [ "$CAMERA_TEST_FAILURE" != response ] || { echo 'data: false'; return 0; }
      echo 'data: true';;
    'topic -i -t /gui/track')
      [ "$CAMERA_TEST_FAILURE" != subscriber ] || return 0
      echo 'Subscribers [Address, Message Type]:';;
    'topic -t /gui/track -m gz.msgs.CameraTrack '*) return 0;;
    *) return 1;;
  esac
}
'''
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "calls.log"
            env = dict(os.environ, CAMERA_TEST_LOG=str(log), CAMERA_TEST_FAILURE=failure)
            result = subprocess.run(["bash", "-c", "set -eo pipefail\n" + stubs +
                                     follow_function() + "\ninitialize_camera_follow"],
                                    env=env, text=True, capture_output=True, timeout=60)
            return result, log.read_text().splitlines()

    def test_service_handshake_precedes_three_smoothed_overhead_requests(self):
        result, calls = self.initialize()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("following robot_1", result.stdout)
        self.assertTrue(calls[0].startswith("service -i -s /gui/follow"))
        self.assertIn('--req data: "robot_1"', calls[1])
        self.assertIn("--req x: 0 y: 0 z: 5", calls[2])
        self.assertEqual(calls[3], "topic -i -t /gui/track")
        self.assertEqual(len(calls[4:]), 3)
        for call in calls[4:]:
            self.assertIn("track_mode: FOLLOW_LOOK_AT", call)
            self.assertIn('follow_target: {name: "robot_1"}', call)
            self.assertIn('track_target: {name: "robot_1"}', call)
            self.assertIn("follow_pgain: 0.02 track_pgain: 0.02", call)
        self.assertNotIn("cmd_vel", "\n".join(calls))

    def test_missing_services_false_responses_or_subscriber_fail_with_bounded_retries(self):
        for failure in ("discovery", "response", "subscriber"):
            with self.subTest(failure=failure):
                result, calls = self.initialize(failure)
                self.assertEqual(result.returncode, 1)
                self.assertIn("initialization timed out", result.stderr)
                self.assertEqual(calls.count("service -i -s /gui/follow"), 90)
                self.assertFalse(any(c.startswith("topic -t /gui/track -m") for c in calls))


if __name__ == "__main__":
    unittest.main()
