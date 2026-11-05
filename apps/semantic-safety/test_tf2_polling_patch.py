"""The private TF2 poll patch changes only the advanced two-time lookup."""
from pathlib import Path
import tempfile
import unittest

from patch_tf2_polling import patch_file, SLEEP_1MS, SLEEP_10MS


class Tf2PollingPatchTests(unittest.TestCase):
    def test_only_advanced_lookup_poll_changes(self):
        source = """
bool Buffer::canTransform(const std::string & target_frame, const std::string & source_frame,
  const tf2::TimePoint & time, const tf2::Duration timeout) const
{
  std::this_thread::sleep_for(std::chrono::milliseconds(10));
}
bool Buffer::canTransform(const std::string & target_frame, const tf2::TimePoint & target_time,
  const std::string & source_frame, const tf2::TimePoint & source_time,
  const std::string & fixed_frame, const tf2::Duration timeout) const
{
  std::this_thread::sleep_for(std::chrono::milliseconds(10));
}
TransformStampedFuture Buffer::waitForTransform() { return {}; }
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "buffer.cpp"
            path.write_text(source)
            patch_file(path)
            result = path.read_text()
        self.assertEqual(result.count(SLEEP_1MS), 1)
        self.assertEqual(result.count(SLEEP_10MS), 1)
        self.assertIn("const tf2::TimePoint & time", result)

    def test_refuses_unexpected_or_already_patched_source(self):
        for source in ("no advanced overload", """
bool Buffer::canTransform(const std::string & target_frame, const tf2::TimePoint & target_time,
  const std::string & source_frame, const tf2::TimePoint & source_time,
  const std::string & fixed_frame, const tf2::Duration timeout) const
{
  std::this_thread::sleep_for(std::chrono::milliseconds(1));
}
TransformStampedFuture Buffer::waitForTransform() { return {}; }
"""):
            with self.subTest(source=source[:20]), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "buffer.cpp"
                path.write_text(source)
                with self.assertRaises(RuntimeError):
                    patch_file(path)


if __name__ == "__main__":
    unittest.main()
