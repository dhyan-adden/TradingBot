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
    # Proven propose path (in-process OpenRouter DAG). Propose-only: stops at
    # AWAITING_APPROVAL; a human reviews (/review-trade) and routes. Live Kite
    # scan is best-effort - a stale token degrades to an empty scan, not a crash.
    cd "$PROJECT_ROOT"
    exec env ZERODHA_ENABLE_DATA=true "$PY" -m tradeloop.orchestrator premarket
    ;;
  # 1230 (intraday) and 1600 (postclose) intentionally not scheduled: those
  # modes are unproven live and each cycle costs ~35k tokens. Re-enable by
  # mirroring the premarket line with the mode swapped, once validated.
  *)
    exit 0
    ;;
esac
