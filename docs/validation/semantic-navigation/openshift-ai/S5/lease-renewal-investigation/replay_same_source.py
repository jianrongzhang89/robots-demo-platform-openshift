"""Offline deterministic reproduction of same-source grace withdrawal."""
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0,str(ROOT/'apps/semantic-safety'))
from test_safety_core import armed, command, instant
from safety_core import COMMAND_GRACE_NS, MS

gate, token = armed()
assert command(gate, token, 1)
assert gate.extend_command_deadline(instant(80), COMMAND_GRACE_NS)
before = gate.command_deadline
# A repeated checked copy of the SAME source at 96.91555 ms source age.
# It is still within admission's 98 ms window, but only has 1.08445 ms left.
now = instant(97.91555)
assert gate.command(token, 2, instant(1).wall, (.1,0.,0.), now)
after = gate.command_deadline
packet = gate.packet(now)
result = {'same_source_admitted':True,
          'deadline_regression_ms':(before-after)/MS,
          'grace_flag_after_duplicate':gate.command_grace_used,
          'emitted_window_ms':(packet.expires_wall-packet.issued_wall)/MS,
          'native_minimum_window_ms':2,
          'would_be_rejected_even_without_delivery_delay':packet.expires_wall<=packet.issued_wall+2*MS}
assert result['deadline_regression_ms']==25
assert result['would_be_rejected_even_without_delivery_delay']
Path(__file__).with_name('same-source-replay-result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
