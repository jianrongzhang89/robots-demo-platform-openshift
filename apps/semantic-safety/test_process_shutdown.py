import signal
import subprocess
import unittest
from unittest.mock import patch
from process_shutdown import shutdown, gazebo_stop, timeout_snapshot, CONSOLE_STOP_SERVICE


class Child:
    def __init__(self,pid,*,hung=False,exited=False):
        self.pid=pid; self.hung=hung; self.returncode=0 if exited else None
    def poll(self): return self.returncode
    def wait(self,timeout):
        if self.hung:
            self.hung=False
            raise subprocess.TimeoutExpired("fake",timeout)
        if self.returncode is None: self.returncode=0
        return self.returncode


class ShutdownTests(unittest.TestCase):
    def test_display_outlives_gazebo(self):
        children=[("resource_probe",Child(1)),("display",Child(2)),("gazebo",Child(3)),("nav2",Child(4))]
        def send(pid,sig):
            if pid==2: self.assertEqual(children[2][1].returncode,0)
            if pid==3: self.assertIsNone(children[1][1].returncode)
        report=shutdown(children,signal_group=send)
        events=report["events"]
        end=next(i for i,e in enumerate(events) if e["name"]=="gazebo" and e["event"]=="reaped")
        display=next(i for i,e in enumerate(events) if e["name"]=="display" and e["event"]=="sigint")
        self.assertLess(end,display)
        self.assertEqual(report["forced"],[])

    def test_timeout_retains_forced_failure_evidence(self):
        calls=[]
        report=shutdown([("gazebo",Child(3,hung=True))],signal_group=lambda *args:calls.append(args))
        self.assertEqual(calls,[(3,signal.SIGINT),(3,signal.SIGKILL)])
        self.assertEqual(report["forced"],["gazebo"])

    def test_already_exited_is_not_misreported_alive(self):
        calls=[]
        report=shutdown([("gazebo",Child(3,exited=True))],signal_group=lambda *args:calls.append(args))
        self.assertEqual(calls,[])
        self.assertFalse(report["alive_at_shutdown"]["gazebo"])

    def test_accepted_graceful_request_avoids_signal(self):
        calls=[]
        report=shutdown([("gazebo",Child(3))],signal_group=lambda *args:calls.append(args),
                        graceful={"gazebo":lambda:{"passed":True}})
        self.assertEqual(calls,[])
        self.assertTrue(report["graceful"]["gazebo"]["passed"])

    def test_failed_graceful_request_is_retained_with_signal_fallback(self):
        calls=[]
        report=shutdown([("gazebo",Child(3))],signal_group=lambda *args:calls.append(args),
                        graceful={"gazebo":lambda:{"passed":False}})
        self.assertEqual(calls,[(3,signal.SIGINT)])
        self.assertFalse(report["graceful"]["gazebo"]["passed"])

    def test_positive_ack_cannot_hide_failure_to_exit(self):
        calls=[]
        report=shutdown([("gazebo",Child(3,hung=True))],signal_group=lambda *args:calls.append(args),
                        graceful={"gazebo":lambda:{"passed":True}})
        self.assertEqual(calls,[(3,signal.SIGKILL)])
        self.assertTrue(report["graceful"]["gazebo"]["passed"])
        self.assertEqual(report["forced"],["gazebo"])

    def test_snapshot_only_after_failure_and_cannot_hide_forced_kill(self):
        calls=[]
        report=shutdown([("gazebo",Child(3,hung=True))],signal_group=lambda *args:calls.append(args),
                        on_timeout={"gazebo":lambda pid:{"pid":pid}})
        self.assertEqual(report["timeout_evidence"],{"gazebo":{"pid":3}})
        self.assertEqual(report["forced"],["gazebo"])
        self.assertEqual(calls[-1],(3,signal.SIGKILL))
        report=shutdown([("gazebo",Child(3))],signal_group=lambda *args:None,
                        on_timeout={"gazebo":lambda pid:self.fail("not timed out")})
        self.assertEqual(report["timeout_evidence"],{})

    def test_failed_snapshot_still_kills(self):
        def fail(pid): raise OSError("diagnostic denied")
        calls=[]
        report=shutdown([("gazebo",Child(3,hung=True))],signal_group=lambda *args:calls.append(args),
                        on_timeout={"gazebo":fail})
        self.assertEqual(report["timeout_evidence"]["gazebo"]["error"],"diagnostic denied")
        self.assertEqual(calls[-1],(3,signal.SIGKILL))

    @patch("process_shutdown.subprocess.run",side_effect=FileNotFoundError("no debugger"))
    def test_snapshot_unavailable_process_and_debugger_is_evidence(self,run):
        report=timeout_snapshot(999999999)
        self.assertIn("proc_error",report)
        self.assertIn("debugger_error",report)

    @patch("process_shutdown.subprocess.run",side_effect=subprocess.TimeoutExpired(
        "gdb",3,output=b"partial stack",stderr=b"symbol warning"))
    def test_snapshot_retains_partial_debugger_output(self,run):
        report=timeout_snapshot(999999999)
        self.assertEqual(report["debugger_partial_stdout"],"partial stack")
        self.assertEqual(report["debugger_partial_stderr"],"symbol warning")

    @patch("process_shutdown.subprocess.run")
    def test_service_requires_private_transport_and_positive_ack(self,run):
        with patch.dict("os.environ",{"GZ_IP":"0.0.0.0","GZ_PARTITION":"phase5-watchdog-test"}):
            self.assertFalse(gazebo_stop()["passed"])
            run.assert_not_called()
        with patch.dict("os.environ",{"GZ_IP":"127.0.0.1","GZ_PARTITION":"phase5-watchdog-test"}):
            for stdout,returncode,passed in (("data: true\n",0,True),("data: false\n",0,False),
                                           ("",0,False),("data: true",1,False)):
                run.return_value=subprocess.CompletedProcess([],returncode,stdout,"")
                self.assertEqual(gazebo_stop()["passed"],passed)
                self.assertIn(CONSOLE_STOP_SERVICE,run.call_args.args[0])
            run.side_effect=subprocess.TimeoutExpired("gz service",5)
            self.assertFalse(gazebo_stop()["passed"])

    @patch("process_shutdown.subprocess.run")
    def test_smoke_uses_separate_transport_and_rejects_non_stop_request(self,run):
        env={"GZ_IP":"127.0.0.1","GZ_PARTITION":"phase5-watchdog-test-console-smoke"}
        run.return_value=subprocess.CompletedProcess([],0,"data: false\n","")
        self.assertFalse(gazebo_stop(env=env,stop=False)["passed"])
        self.assertEqual(run.call_args.kwargs["env"],env)
        self.assertIn("stop: false",run.call_args.args[0])


if __name__=="__main__": unittest.main()
