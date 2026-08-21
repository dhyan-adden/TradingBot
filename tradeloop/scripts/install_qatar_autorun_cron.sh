#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CRON_FILE="$(mktemp)"
ACTION="${1:-install}"
START="# BEGIN TradeLoop Qatar autorun"
END="# END TradeLoop Qatar autorun"

crontab -l > "$CRON_FILE" 2>/dev/null || true

remove_block() {
  awk -v start="$START" -v end="$END" '
    $0 == start {skip=1; next}
    $0 == end {skip=0; next}
    skip != 1 {print}
  ' "$CRON_FILE" > "$CRON_FILE.clean"
  mv "$CRON_FILE.clean" "$CRON_FILE"
}

remove_block

if [[ "$ACTION" == "uninstall" ]]; then
  crontab "$CRON_FILE"
  rm -f "$CRON_FILE"
  echo "Removed TradeLoop Qatar autorun cron block."
  exit 0
fi

if [[ "$ACTION" != "install" ]]; then
  echo "usage: $0 [install|uninstall]"
  exit 2
fi

cat >> "$CRON_FILE" <<CRON
$START
SHELL=/bin/bash
PATH=/Users/dhyanpatel/anaconda3/envs/tradingbot/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
# Cron uses the machine's local timezone. This machine is currently expected to run on Qatar time (+03).
30 6 * * 1-5 cd $PROJECT_ROOT && TRADELOOP_AUTO_ROUTE_PAPER=true ./tradeloop/scripts/auto_run_qatar.sh premarket >> $PROJECT_ROOT/tradeloop/reports/qatar_autorun.cron.log 2>&1
0 10 * * 1-5 cd $PROJECT_ROOT && TRADELOOP_AUTO_ROUTE_PAPER=true ./tradeloop/scripts/auto_run_qatar.sh intraday >> $PROJECT_ROOT/tradeloop/reports/qatar_autorun.cron.log 2>&1
0 13 * * 1-5 cd $PROJECT_ROOT && TRADELOOP_AUTO_ROUTE_PAPER=true ./tradeloop/scripts/auto_run_qatar.sh intraday >> $PROJECT_ROOT/tradeloop/reports/qatar_autorun.cron.log 2>&1
30 13 * * 1-5 cd $PROJECT_ROOT && ./tradeloop/scripts/auto_run_qatar.sh postclose >> $PROJECT_ROOT/tradeloop/reports/qatar_autorun.cron.log 2>&1
$END
CRON

crontab "$CRON_FILE"
rm -f "$CRON_FILE"

echo "Installed TradeLoop Qatar autorun cron block."
echo "Schedule: 06:30 premarket, 10:00 intraday, 13:00 intraday with paper auto-route, 13:30 postclose Qatar time."
