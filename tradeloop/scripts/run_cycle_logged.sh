#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="$PROJECT_ROOT/tradeloop/reports/cycle_logs"
mkdir -p "$LOG_DIR"

CYCLE="${1:-premarket}"
STAMP="$(TZ=Asia/Kolkata date +%Y-%m-%d_%H%M%S)"
LOG_FILE="$LOG_DIR/${STAMP}_${CYCLE}.log"
LATEST_FILE="$LOG_DIR/latest.log"

{
  echo "TradeLoop log: $LOG_FILE"
  echo "Started: $(TZ=Asia/Kolkata date '+%Y-%m-%d %H:%M:%S %Z')"
  echo "Command: tradeloop/scripts/run_cycle.sh $*"
  echo
  "$PROJECT_ROOT/tradeloop/scripts/run_cycle.sh" "$@"
} 2>&1 | tee "$LOG_FILE"

cp "$LOG_FILE" "$LATEST_FILE"
echo
echo "Saved log: $LOG_FILE"
echo "Latest log: $LATEST_FILE"
