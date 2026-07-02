#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IST_DAY="$(TZ=Asia/Kolkata date +%u)"
IST_TIME="$(TZ=Asia/Kolkata date +%H%M)"

if [[ "$IST_DAY" -lt 1 || "$IST_DAY" -gt 5 ]]; then
  exit 0
fi

case "$IST_TIME" in
  0800)
    exec "$PROJECT_ROOT/tradeloop/scripts/premarket.sh"
    ;;
  1230)
    exec "$PROJECT_ROOT/tradeloop/scripts/intraday.sh"
    ;;
  1600)
    exec "$PROJECT_ROOT/tradeloop/scripts/postclose.sh"
    ;;
  *)
    exit 0
    ;;
esac
