import tempfile
import unittest
import json
from unittest.mock import patch
from pathlib import Path
from resource_probe import (counters, pressure, process_stat,
                            read_watched_schedstat, resolve_watched_processes, snapshot)


class ResourceProbeTests(unittest.TestCase):
    def test_presentation_sampler_survives_original_capacity(self):
        from resource_probe import main
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "samples.json"
            with patch("sys.argv", ["resource_probe", "--output", str(output),
                                    "--max-samples", "21000"]), \
                 patch("resource_probe.snapshot", return_value={}), \
                 patch("resource_probe.time.sleep"), \
                 patch("resource_probe.signal.signal"):
                main()
            result = json.loads(output.read_text())
            self.assertEqual(len(result["samples"]), 21000)
            self.assertEqual(result["capacity"], 21000)
            self.assertTrue(result["capacity_reached"])

    def test_cpu_counters_remain_integer(self):
        self.assertEqual(counters("nr_throttled 3\nthrottled_usec 42\n"),
                         {"nr_throttled":3,"throttled_usec":42})

    def test_pressure_preserves_cumulative_microseconds(self):
        self.assertEqual(pressure("some avg10=0.12 total=900\nfull avg10=0.00 total=0\n"),
            {"some":{"avg10":.12,"total":900},"full":{"avg10":0.,"total":0}})

    def test_process_name_and_stat_field_positions(self):
        tail=["S"]+[str(n) for n in range(4,25)]
        result=process_stat("123 (a process (worker)) "+" ".join(tail))
        self.assertEqual(result,{"comm":"a process (worker)","state":"S","ppid":4,
            "minflt":10,"majflt":12,"utime_ticks":14,"stime_ticks":15,
            "threads":20,"start_ticks":22,"rss_pages":24})

    def test_missing_sources_are_explicit_not_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            row=snapshot(Path(directory),Path(directory),processes=True)
        self.assertNotIn("cpu.stat",row)
        self.assertIn("cpu.stat",row["errors"])
        self.assertIn("cgroup.procs",row["errors"])
        self.assertGreaterEqual(row["end_steady_ns"],row["steady_ns"])

    def test_watched_main_thread_schedstat_is_pinned_by_kernel_comm(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); cgroup=root/"cgroup"; proc=root/"proc"
            cgroup.mkdir(); proc.mkdir()
            (cgroup/"cgroup.procs").write_text("101\n102\n")
            for pid,comm in (("101","phase5_console_"),("102","collision_monit")):
                process=proc/pid; process.mkdir()
                (process/"comm").write_text(comm+"\n")
                (process/"schedstat").write_text("123 456 7\n")
            watched=resolve_watched_processes(cgroup,proc,{"phase5_console_","collision_monit"})
            self.assertEqual(watched,{"phase5_console_":"101","collision_monit":"102"})
            rows,errors=read_watched_schedstat(proc,watched)
            self.assertEqual(rows["phase5_console_"],{"pid":101,"schedstat":[123,456,7]})
            self.assertEqual(rows["collision_monit"],{"pid":102,"schedstat":[123,456,7]})
            self.assertEqual(errors,{})


if __name__=="__main__": unittest.main()
