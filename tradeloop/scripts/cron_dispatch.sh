#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IST_DAY="$(TZ=Asia/Kolkata date +%u)"
IST_TIME="$(TZ=Asia/Kolkata date +%H%M)"

if [[ "$IST_DAY" -lt 1 || "$IST_DAY" -gt 5 ]]; then
  exit 0
fi

# Sanctioned key sourcing (same allowance as run_cycle.sh): cron does not read
# ~/.zshenv, so pull OPENROUTER_API_KEY from .env internally; never printed.
if [[ -z "${OPENROUTER_API_KEY:-}" && -f "$PROJECT_ROOT/.env" ]]; then
  export OPENROUTER_API_KEY="$(grep '^OPENROUTER_API_KEY=' "$PROJECT_ROOT/.env" | head -1 | cut -d= -f2-)"
fi
PY="/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python"

case "$IST_TIME" in
  0800)
    # Proven propose path (in-process Claude DAG, on the subscription). Propose-only:
    # stops at AWAITING_APPROVAL; a human reviews (/review-trade) and routes. Live Kite
    # scan is best-effort - a stale token degrades to an empty scan, not a crash.
    cd "$PROJECT_ROOT"
    # Preflight: fail loud (no cycle) if the claude CLI login has expired.
    "$PY" tradeloop/scripts/verify_setup.py --mode premarket --backend claude || exit $?
    exec env ZERODHA_ENABLE_DATA=true "$PY" -m tradeloop.orchestrator premarket --backend claude
    ;;
  1400)
    # Intraday pulse (14:00 IST): holdings health only - can propose exits and
    # stop-tightens, still stops at AWAITING_APPROVAL. Late-session slot so an
    # approved exit has a full hour to route before the 15:30 close.
    cd "$PROJECT_ROOT"
    "$PY" tradeloop/scripts/verify_setup.py --mode intraday --backend claude || exit $?
    exec env ZERODHA_ENABLE_DATA=true "$PY" -m tradeloop.orchestrator intraday --backend claude
    ;;
  1600)
    # Postclose review (16:00 IST): analysis-only re-underwrite of the book;
    # verdicts land in carry-forward for the next premarket. Routes nothing.
    cd "$PROJECT_ROOT"
    "$PY" tradeloop/scripts/verify_setup.py --mode postclose --backend claude || exit $?
    exec env ZERODHA_ENABLE_DATA=true "$PY" -m tradeloop.orchestrator postclose --backend claude
    ;;
  *)
    exit 0
    ;;
esac
