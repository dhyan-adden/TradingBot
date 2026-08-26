#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IST_DAY="$(TZ=Asia/Kolkata date +%u)"

if [[ "$IST_DAY" -lt 1 || "$IST_DAY" -gt 5 ]]; then
  exit 0
fi

# Mode comes as an explicit arg from the scheduler (premarket|intraday|postclose)
# so the intended cycle is unambiguous even if the Mac wakes late.
MODE="${1:-}"
if [[ -z "$MODE" ]]; then
  echo "cron_dispatch: missing mode (expected premarket|intraday|postclose)" >&2
  exit 0
fi

# OPENROUTER_API_KEY must be injected into the environment by the caller (launchd
# session wrapper). This script never reads the env file or greps for the key.
PY="/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python"

record_alert() {
  "$PY" "$PROJECT_ROOT/tradeloop/scripts/record_alert.py" "$1" "$2" >/dev/null 2>&1 || true
}

case "$MODE" in
  premarket)
    # Proven autonomous paper path (in-process Claude DAG, on the subscription).
    # In approval_mode=auto, paper orders route after deterministic gates pass.
    # Live routing remains locked unless explicitly enabled in settings and env.
    cd "$PROJECT_ROOT"
    # Headless Kite auth: the ONE daily token refresh. The token stays valid for
    # the whole trading day, so intraday/postclose reuse it - no re-auth there.
    # Best-effort - a failure degrades to an empty scan, not a crash.
    if npm run --silent auth:zerodha -- --auto; then
      :
    else
      record_alert "zerodha_auth_failed" "headless Zerodha auto-auth failed"
      echo "[cron] zerodha auto-auth failed; using existing token"
    fi
    # Preflight: fail loud (no cycle) if the claude CLI login has expired.
    if "$PY" tradeloop/scripts/verify_setup.py --mode premarket --backend claude; then
      :
    else
      rc=$?
      record_alert "setup_failed" "verify_setup failed for premarket rc=$rc"
      exit "$rc"
    fi
    exec env ZERODHA_ENABLE_DATA=true "$PY" -m tradeloop.orchestrator premarket --backend claude
    ;;
  intraday)
    # Intraday pulse (14:00 IST): holdings health only - can auto-route paper exits,
    # stop-tightens, and held-position top-ups that pass deterministic gates.
    # Late-session slot leaves a full hour before the 15:30 close.
    cd "$PROJECT_ROOT"
    # No auth refresh here - premarket's daily token is still valid this session.
    if "$PY" tradeloop/scripts/verify_setup.py --mode intraday --backend claude; then
      :
    else
      rc=$?
      record_alert "setup_failed" "verify_setup failed for intraday rc=$rc"
      exit "$rc"
    fi
    exec env ZERODHA_ENABLE_DATA=true "$PY" -m tradeloop.orchestrator intraday --backend claude
    ;;
  postclose)
    # Postclose review (16:00 IST): analysis-only re-underwrite of the book;
    # verdicts land in carry-forward for the next premarket. Routes nothing.
    cd "$PROJECT_ROOT"
    # No auth refresh here - premarket's daily token is still valid this session.
    if "$PY" tradeloop/scripts/verify_setup.py --mode postclose --backend claude; then
      :
    else
      rc=$?
      record_alert "setup_failed" "verify_setup failed for postclose rc=$rc"
      exit "$rc"
    fi
    exec env ZERODHA_ENABLE_DATA=true "$PY" -m tradeloop.orchestrator postclose --backend claude
    ;;
  *)
    echo "cron_dispatch: unknown mode '$MODE' (expected premarket|intraday|postclose)" >&2
    exit 2
    ;;
esac
