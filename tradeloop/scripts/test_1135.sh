#!/usr/bin/env bash
# ONE-OFF TEST (today only): wait until 11:35 Asia/Qatar, then run the Qatar
# premarket cycle with paper auto-routing enabled. Not a recurring schedule.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TARGET="${TRADELOOP_TEST_TARGET:-11:35}"

now_epoch="$(date +%s)"
target_epoch="$(TZ=Asia/Qatar date -j -f '%Y-%m-%d %H:%M:%S' "$(TZ=Asia/Qatar date +%Y-%m-%d) ${TARGET}:00" +%s)"
wait_secs=$((target_epoch - now_epoch))

if (( wait_secs > 0 )); then
  echo "test_1135: waiting ${wait_secs}s until ${TARGET} Asia/Qatar"
  sleep "$wait_secs"
else
  echo "test_1135: ${TARGET} Asia/Qatar already passed; running immediately"
fi

echo "test_1135: firing premarket + auto-route at $(TZ=Asia/Qatar date '+%H:%M:%S %Z')"

export TRADELOOP_AUTO_ROUTE_PAPER=true
exec "$PROJECT_ROOT/tradeloop/scripts/auto_run_qatar.sh" premarket
