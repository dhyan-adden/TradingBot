#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IST_DAY="$(TZ=Asia/Kolkata date +%u)"

if [[ "$IST_DAY" -lt 1 || "$IST_DAY" -gt 5 ]]; then
  exit 0
fi

# Mode comes as an explicit arg from the launchd scheduler
# (premarket|intraday|postclose) - fires the right cycle even if the Mac woke
# late and the wall clock drifted past the slot. A bare, no-arg call means a
# STALE cron entry fired (scheduling moved from cron to launchd); do nothing, so
# the leftover cron and launchd can never double-fire the same cycle.
MODE="${1:-}"
if [[ -z "$MODE" ]]; then
  exit 0
fi

# Sanctioned key sourcing (same allowance as run_cycle.sh): cron does not read
# ~/.zshenv, so pull OPENROUTER_API_KEY from .env internally; never printed.
if [[ -z "${OPENROUTER_API_KEY:-}" && -f "$PROJECT_ROOT/.env" ]]; then
  export OPENROUTER_API_KEY="$(grep '^OPENROUTER_API_KEY=' "$PROJECT_ROOT/.env" | head -1 | cut -d= -f2-)"
fi
PY="/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python"

case "$MODE" in
  premarket)
    # Proven propose path (in-process Claude DAG, on the subscription). Propose-only:
    # stops at AWAITING_APPROVAL; a human reviews (/review-trade) and routes. Live Kite
    # scan is best-effort - a stale token degrades to an empty scan, not a crash.
    cd "$PROJECT_ROOT"
    # Headless Kite auth: the ONE daily token refresh. The token stays valid for
    # the whole trading day, so intraday/postclose reuse it - no re-auth there.
    # Best-effort - a failure degrades to an empty scan, not a crash.
    npm run --silent auth:zerodha -- --auto || echo "[cron] zerodha auto-auth failed; using existing token"
    # Preflight: fail loud (no cycle) if the claude CLI login has expired.
    "$PY" tradeloop/scripts/verify_setup.py --mode premarket --backend claude || exit $?
    exec env ZERODHA_ENABLE_DATA=true "$PY" -m tradeloop.orchestrator premarket --backend claude
    ;;
  intraday)
    # Intraday pulse (14:00 IST): holdings health only - can propose exits and
    # stop-tightens, still stops at AWAITING_APPROVAL. Late-session slot so an
    # approved exit has a full hour to route before the 15:30 close.
    cd "$PROJECT_ROOT"
    # No auth refresh here - premarket's daily token is still valid this session.
    "$PY" tradeloop/scripts/verify_setup.py --mode intraday --backend claude || exit $?
    exec env ZERODHA_ENABLE_DATA=true "$PY" -m tradeloop.orchestrator intraday --backend claude
    ;;
  postclose)
    # Postclose review (16:00 IST): analysis-only re-underwrite of the book;
    # verdicts land in carry-forward for the next premarket. Routes nothing.
    cd "$PROJECT_ROOT"
    # No auth refresh here - premarket's daily token is still valid this session.
    "$PY" tradeloop/scripts/verify_setup.py --mode postclose --backend claude || exit $?
    exec env ZERODHA_ENABLE_DATA=true "$PY" -m tradeloop.orchestrator postclose --backend claude
    ;;
  *)
    echo "cron_dispatch: unknown mode '$MODE' (expected premarket|intraday|postclose)" >&2
    exit 2
    ;;
esac
