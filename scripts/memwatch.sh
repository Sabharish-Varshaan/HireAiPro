#!/bin/bash
# Memory watchdog for heavy local work on a 16 GB Mac.
#   scripts/memwatch.sh LOGFILE -- command args...
# Runs the command, logs every 5 s (free %, swap, API/worker footprint, Qdrant,
# Judge0, Docker VM RSS) and kills the command if free memory drops below
# MEMWATCH_MIN_FREE (default 15). A kill is a FAIL / MEMORY BLOCKER.
set -u
LOG=$1; shift; [ "${1:-}" = "--" ] && shift
MIN=${MEMWATCH_MIN_FREE:-15}

fp() { local p; p=$(pgrep -f "$1" | head -1); [ -n "$p" ] && footprint -p "$p" 2>/dev/null | grep -oE 'Footprint: [0-9]+ [MG]B' | cut -d' ' -f2-3 | tr -d ' ' || echo "-"; }
dmem() { docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' 2>/dev/null | awk -v n="$1" '$1 ~ n {s=s" "$2} END {print (s==""?"-":s)}'; }
sample() {
  local free swap vm
  free=$(memory_pressure | tail -1 | grep -oE '[0-9]+%' | tr -d %)
  swap=$(sysctl -n vm.swapusage | grep -oE 'used = [0-9.]+M' | grep -oE '[0-9.]+')
  vm=$(ps -axo rss,comm | awk '/Virtualization.VirtualMachine/ {printf "%.0fMB", $1/1024}')
  echo "$(date +%H:%M:%S) free=${free}% swap=${swap}MB api=$(fp 'uvicorn app.main:app') worker=$(fp 'celery -A app.workers') qdrant=$(dmem qdrant) judge0=$(dmem judge0) dockervm=${vm}"
}

echo "# memwatch start $(date '+%F %T') cmd: $*" >> "$LOG"
"$@" &
PID=$!
LOW=100
while kill -0 "$PID" 2>/dev/null; do
  line=$(sample); echo "$line" >> "$LOG"
  f=$(echo "$line" | grep -oE 'free=[0-9]+' | cut -d= -f2)
  [ -n "$f" ] && [ "$f" -lt "$LOW" ] && LOW=$f
  if [ -n "$f" ] && [ "$f" -lt "$MIN" ]; then
    echo "MEMWATCH ABORT: free ${f}% < ${MIN}% — killing $PID (FAIL / MEMORY BLOCKER)" | tee -a "$LOG"
    kill "$PID"; wait "$PID" 2>/dev/null; echo "# min free ${LOW}%" >> "$LOG"; exit 99
  fi
  sleep 5
done
wait "$PID"; RC=$?
echo "# memwatch end rc=$RC min_free=${LOW}%" | tee -a "$LOG"
exit $RC
