#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="${TRADELOOP_PYTHON:-/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python}"
BACKEND="${TRADELOOP_BACKEND:-opencode}"
AUTO_ROUTE_PAPER="${TRADELOOP_AUTO_ROUTE_PAPER:-false}"
MODE="${1:-}"
export ZERODHA_ENABLE_TRADING=false

case "$MODE" in
  premarket|intraday|postclose) ;;
  postmarket|post-market|post_market) MODE="postclose" ;;
  *)
    echo "usage: $0 premarket|intraday|postclose"
    exit 2
    ;;
esac

LOG_DIR="$PROJECT_ROOT/tradeloop/reports/cycle_logs"
mkdir -p "$LOG_DIR"
STAMP="$(TZ=Asia/Qatar date +%Y-%m-%d_%H%M%S)"
LOG_FILE="$LOG_DIR/${STAMP}_qatar_${MODE}.log"
LATEST_FILE="$LOG_DIR/latest_qatar.log"

IST_DAY="$(TZ=Asia/Kolkata date +%u)"
if [[ "$IST_DAY" -lt 1 || "$IST_DAY" -gt 5 ]]; then
  echo "tradeloop_qatar_autorun=SKIP reason=nse_weekend mode=$MODE"
  exit 0
fi

record_alert() {
  "$PY" "$PROJECT_ROOT/tradeloop/scripts/record_alert.py" "$1" "$2" >/dev/null 2>&1 || true
}

run_cycle() {
  cd "$PROJECT_ROOT"
  echo "TradeLoop Qatar auto-run"
  echo "Mode: $MODE"
  echo "Backend: $BACKEND"
  echo "Started Qatar: $(TZ=Asia/Qatar date '+%Y-%m-%d %H:%M:%S %Z')"
  echo "Started IST: $(TZ=Asia/Kolkata date '+%Y-%m-%d %H:%M:%S %Z')"
  echo "Paper route after propose: $AUTO_ROUTE_PAPER"
  echo

  if [[ "$MODE" == "premarket" ]]; then
    if npm run --silent auth:zerodha -- --auto; then
      :
    else
      record_alert "zerodha_auth_failed" "Qatar autorun Zerodha auto-auth failed"
      echo "tradeloop_qatar_autorun=AUTH_DEGRADED reason=zerodha_auto_auth_failed"
    fi
  fi

  "$PY" tradeloop/scripts/verify_setup.py --mode "$MODE"
  env ZERODHA_ENABLE_DATA=true ZERODHA_ENABLE_TRADING=false \
    "$PY" -m tradeloop.orchestrator "$MODE" --backend "$BACKEND"
}

set +e
run_cycle 2>&1 | tee "$LOG_FILE"
RC=${PIPESTATUS[0]}
set -e

cp "$LOG_FILE" "$LATEST_FILE"

if [[ "$RC" -ne 0 ]]; then
  record_alert "qatar_autorun_failed" "mode=$MODE rc=$RC log=$LOG_FILE"
  echo "tradeloop_qatar_autorun=FAILED mode=$MODE rc=$RC log=$LOG_FILE"
  exit "$RC"
fi

if [[ "$AUTO_ROUTE_PAPER" == "true" && "$MODE" != "postclose" ]]; then
  RUN_DIR="$(grep -Eo '(tradeloop_)?run_dir=[^ ]+' "$LOG_FILE" | tail -n 1 | cut -d= -f2- || true)"
  if [[ -n "$RUN_DIR" ]]; then
    {
      echo
      echo "Routing paper orders for $RUN_DIR"
      env ZERODHA_ENABLE_TRADING=false "$PY" -m tradeloop.orchestrator route "$RUN_DIR"
    } 2>&1 | tee -a "$LOG_FILE"
    cp "$LOG_FILE" "$LATEST_FILE"
  else
    echo "tradeloop_qatar_autorun=NO_RUN_DIR_FOR_PAPER_ROUTE mode=$MODE" | tee -a "$LOG_FILE"
  fi
fi

echo "tradeloop_qatar_autorun=OK mode=$MODE log=$LOG_FILE"
