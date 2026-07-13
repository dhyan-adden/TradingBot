#!/usr/bin/env bash
# Launch a one-off orchestrator cycle fully detached (own session, reparented to
# PID 1) so it survives the launching terminal/agent session dying. Scheduled
# runs don't need this - cron owns them; this is for manual/adhoc cycles.
# Usage: ./tradeloop/scripts/run_detached.sh adhoc --backend claude --request "..."
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python"
LOG="$PROJECT_ROOT/tradeloop/reports/detached_$(date +%Y%m%d_%H%M%S).log"
cd "$PROJECT_ROOT"
# ponytail: macOS has no setsid(1); fork+setsid+exec in python does the same job
nohup env ZERODHA_ENABLE_DATA=true "$PY" -c '
import os, sys
if os.fork() == 0:
    os.setsid()
    os.execvp(sys.argv[1], sys.argv[1:])
' "$PY" -m tradeloop.orchestrator "$@" >>"$LOG" 2>&1 &
echo "detached log=$LOG"
echo "watch with: tail -f $LOG"
