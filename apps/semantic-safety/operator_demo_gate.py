"""Opt-in presentation hold. Releasing this hold grants no actuator authority."""
import json
from pathlib import Path
import time


def wait_for_operator(directory, token, pump, snapshot, timeout=600,
                      monotonic=time.monotonic):
    directory = Path(directory)
    request = directory / 'operator-start.json'
    status = directory / 'operator-ready.json'
    if not token or request.exists():
        raise RuntimeError('fresh operator demo token and absent start file required')
    end = monotonic() + timeout
    while monotonic() < end:
        pump()
        native = snapshot() or {}
        if not (native.get('armed') is False and native.get('pending') is False
                and native.get('applied_vx') == 0 and native.get('applied_wz') == 0):
            raise RuntimeError('operator hold requires disarmed zero-command native state')
        record = {'phase': 'waiting_for_operator', 'token': token,
                  'written_wall_ns': time.time_ns(), 'native': native}
        temp = status.with_suffix('.tmp')
        temp.write_text(json.dumps(record)); temp.replace(status)
        if request.exists():
            supplied = json.loads(request.read_text())
            if supplied != {'token': token, 'action': 'start_navigation'}:
                raise RuntimeError('operator start request does not match this demo')
            request.unlink()
            record['phase'] = 'operator_released'
            status.write_text(json.dumps(record))
            return
    raise TimeoutError('operator did not release demo; navigation remains unstarted')
