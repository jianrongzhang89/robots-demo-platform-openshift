set -euo pipefail
record=$(crictl inspect "$1")
test "$(printf '%s' "$record" | jq -r '.status.metadata.name')" = kserve-container
test "$(printf '%s' "$record" | jq -r '.status.state')" = CONTAINER_RUNNING
pid=$(printf '%s' "$record" | jq -r '.info.pid')
test "$pid" -gt 1
grep -qF "$1" /proc/"$pid"/cgroup
tr '\0' ' ' < /proc/"$pid"/cmdline | grep -qF /app/server.py
kill -STOP "$pid"
printf 'target_pid=%s\n' "$pid"
grep '^State:' /proc/"$pid"/status
