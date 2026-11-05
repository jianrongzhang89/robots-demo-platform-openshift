"""Pod entrypoint, retaining test artifacts until the orchestrator retrieves them."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

root = Path(__file__).resolve().parent
results = []
fixture = {"native":"verify_native_watchdog.py", "combined":"verify_combined_guard.py",
           "contacts":"verify_contact_audit.py",
           "hotel":"verify_hotel_stack.py", "hotel-guarded":"verify_hotel_stack.py"}[os.getenv("PHASE5_SUITE", "native")]
for command in ([sys.executable, "-m", "unittest", "discover", "-s", str(root), "-p", "test_*.py", "-v"],
                [sys.executable, str(root / "verify_frame_bridge.py")],
                [sys.executable, str(root / "verify_hotel_adapter.py")],
                ["/opt/semantic-safety/build/test_native_lease"],
                [sys.executable, str(root / fixture)]):
    # The armed-semantic fault trials carry bounded waits that cannot fit the
    # historical 280 s hotel budget: the SAM3 readiness gate alone may need
    # 300 s (a process-loss restart reloads the model) and the late-success
    # dwell up to 240 s. The orchestrator raises this budget for those
    # trials; every other suite keeps the frozen 280 s cap.
    fixture_timeout = int(os.getenv("PHASE5_FIXTURE_TIMEOUT_S", "280"))
    result = subprocess.run(command, timeout=fixture_timeout if fixture=="verify_hotel_stack.py" else 100)
    results.append({"command": command, "returncode": result.returncode})
    if result.returncode:
        break
Path("/tmp/phase5-suite.json").write_text(json.dumps(results, indent=2))
print(json.dumps({"event": "native_suite_finished", "results": results}), flush=True)
# The pod stays available for evidence retrieval: the host polls every 2 s
# and must exec-cat the marker before the fixture container exits. The
# window was 200 s; a workstation network blip longer than that loses a
# fully passing trial's retrieval (paired-series-11 trial-003-on: suite
# passed, marker window missed, evidence lost). 500 s keeps the marker
# retrievable for essentially the pod's whole remaining budget — the pod's
# activeDeadlineSeconds still bounds everything.
time.sleep(500)  # pod stays available for evidence retrieval; activeDeadline bounds it
