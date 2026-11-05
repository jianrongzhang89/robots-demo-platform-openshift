#!/usr/bin/env python3
"""Read-only navigation telemetry exporter. Never supplies safety authority.

Only source-stamped snapshots younger than ten seconds produce status gauges.
Freshness limits here describe dashboard data, not the robot's 500 ms stop gate.
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import math
from pathlib import Path
import time

REASONS = {'clear','semantic_stale','camera_stale','inference_heartbeat_stale','tf_stale','command_expired',
           'semantic_invalid_age','camera_invalid_age','inference_heartbeat_invalid_age',
           'semantic_epoch_changed','camera_epoch_changed','inference_heartbeat_epoch_changed',
           'native_session_lost','startup_disarmed','armed','armed_waiting_first_packet','goal_succeeded','not_armed','cancelled','other','none'}


def fresh(stamp, now):
    return type(stamp) in (int,float) and math.isfinite(stamp) and 0 <= now-stamp <= 10_000_000_000


def metrics(row, now_ns):
    lines=[]
    def emit(name,value):
        if type(value) in (int,float) and math.isfinite(value):lines.append(f'g5_navigation_{name} {value}')
    sampled=fresh(row.get('observed_wall_ns'),now_ns)
    emit('snapshot_available',int(sampled))
    adapter=row.get('adapter') or {}; fixture=row.get('fixture') or {}
    adapter_ok=sampled and fresh(adapter.get('status_wall_ns'),now_ns)
    fixture_ok=sampled and fresh(fixture.get('written_wall_ns'),now_ns)
    emit('adapter_available',int(adapter_ok));emit('safety_available',int(fixture_ok))
    if adapter_ok:
        emit('adapter_ready',int(adapter.get('ready') is True))
        for key in ['emitted_results','timestamp_discards','input_queue_drops','work_queue_drops','work_wait_drops','trace_errors']:
            emit(key,adapter.get(key))
        last=adapter.get('last_result') or {}; capture=last.get('capture_wall_ns'); result=last.get('result_wall_ns')
        if type(capture) is int and type(result) is int and 0<capture<=result<=now_ns:
            emit('last_capture_timestamp_seconds',capture/1e9)
            emit('capture_to_result_seconds',(result-capture)/1e9)
        emit('capture_age_upper_seconds',last.get('capture_age_upper_ms')/1000 if type(last.get('capture_age_upper_ms')) in (int,float) else None)
    if fixture_ok:
        emit('armed',int(fixture.get('armed') is True))
        reason=fixture.get('gate_reason') or 'none';reason=reason if reason in REASONS else 'other'
        lines.append('g5_navigation_stop_reason{reason='+json.dumps(reason)+'} 1')
    # Costmap data must come from its own applied-update observation, never from
    # model latency or a simulated timestamp. Fault fixtures may have no costmap.
    costmap=row.get('costmap') or {}
    capture=costmap.get('capture_wall_ns'); applied=costmap.get('costmap_wall_ns')
    costmap_ok=sampled and fresh(costmap.get('observed_wall_ns'),now_ns) and type(capture) is int and type(applied) is int and 0<capture<=applied<=now_ns
    emit('costmap_available',int(costmap_ok))
    if costmap_ok:
        capture=costmap.get('capture_wall_ns'); applied=costmap.get('costmap_wall_ns')
        if type(capture) is int and type(applied) is int and 0<capture<=applied<=now_ns:
            emit('capture_to_costmap_seconds',(applied-capture)/1e9)
    if adapter_ok and fresh(row.get('rtf_source_wall_ns'),now_ns):emit('capture_stream_rtf',row.get('rtf'))
    return ('\n'.join(lines)+'\n').encode()


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        if self.path!='/metrics':self.send_error(404);return
        try:row=json.loads(Path('/tmp/navigation.json').read_text())
        except (OSError,ValueError):row={}
        body=metrics(row,time.time_ns());self.send_response(200)
        self.send_header('Content-Type','text/plain; version=0.0.4');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)


if __name__=='__main__':HTTPServer(('0.0.0.0',8080),Handler).serve_forever()
