import hashlib
from pathlib import Path
import tempfile
import unittest
from console_evidence import identity, recording_absent, validate_world, lifecycle_complete


class ConsoleEvidenceTests(unittest.TestCase):
    def test_shutdown_serializes_join_before_destruction(self):
        for markers in (("stop_begin","run_returned result=0","stop_end","stop_worker_joined",
                         "destructor_begin","destructor_end"),
                        ("stop_begin","stop_end","run_returned result=0","stop_worker_joined",
                         "destructor_begin","destructor_end")):
            self.assertTrue(lifecycle_complete("\n".join("phase5 lifecycle: "+m for m in markers))["passed"])

    def test_incomplete_or_overlapping_teardown_is_not_success(self):
        for markers in (("stop_begin","run_returned result=0","destructor_begin","stop_end",
                         "stop_worker_joined","destructor_end"),
                        ("stop_begin","run_returned result=0","stop_end","stop_worker_joined","destructor_begin"),
                        ("stop_begin","run_returned result=1","stop_end","stop_worker_joined",
                         "destructor_begin","destructor_end")):
            self.assertFalse(lifecycle_complete("\n".join("phase5 lifecycle: "+m for m in markers))["passed"])

    def test_requires_one_world_without_log_plugin(self):
        validate_world('<sdf><world name="test"/></sdf>')
        for text in ('<sdf/>','<sdf><world/><world/></sdf>',
                     '<sdf><world><plugin name="gz::sim::systems::LogRecord"/></world></sdf>',
                     '<sdf><world><plugin filename="gz-sim-log-system"/></world></sdf>',
                     '<sdf><world><plugin name="gz::sim::systems::LogPlayback"/></world></sdf>'):
            with self.subTest(text=text),self.assertRaises(ValueError): validate_world(text)

    def test_file_or_loaded_recorder_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            self.assertTrue(recording_absent(root)["passed"])
            self.assertFalse(recording_absent(root,"a b /lib/libgz-sim8-log-system.so")["passed"])
            (root/"state.tlog-journal").write_text("partial recording")
            self.assertFalse(recording_absent(root)["passed"])

    def test_identity_requires_executable_and_source_hash_match(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); process=root/"123"; process.mkdir()
            binary=root/"server"; binary.write_bytes(b"binary")
            (root/"source.cc").write_text("source")
            (process/"exe").symlink_to(binary)
            (process/"maps").write_text("no recorder")
            hashes={"source.cc":hashlib.sha256(b"source").hexdigest()}
            self.assertTrue(identity(123,hashes,proc=root,executable=binary,source=root)["passed"])
            self.assertFalse(identity(123,{"source.cc":"changed"},proc=root,executable=binary,source=root)["passed"])
            other=root/"other"; other.write_bytes(b"binary")
            self.assertFalse(identity(123,hashes,proc=root,executable=other,source=root)["passed"])


if __name__=="__main__": unittest.main()
