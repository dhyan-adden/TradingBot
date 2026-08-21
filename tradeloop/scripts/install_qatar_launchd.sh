#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
# launchd's xpcproxy is sandbox-denied from creating stdout/stderr files on the
# external /Volumes/D-DRIVE volume, which aborts the spawn (exit 78 EX_CONFIG).
# Write the plist's own logs to the system volume; the script's cycle logs still
# land in tradeloop/reports/cycle_logs/ under the user's normal permissions.
LOG_DIR="$HOME/Library/Logs"
UID_VALUE="$(id -u)"

mkdir -p "$LAUNCH_AGENTS" "$LOG_DIR"

remove_job() {
  local label="$1"
  launchctl bootout "gui/$UID_VALUE/$label" >/dev/null 2>&1 || true
  rm -f "$LAUNCH_AGENTS/$label.plist"
}

install_job() {
  local label="$1"
  local hour="$2"
  local minute="$3"
  local mode="$4"
  local auto_route="$5"
  local plist="$LAUNCH_AGENTS/$label.plist"

  cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$label</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$PROJECT_ROOT/tradeloop/scripts/auto_run_qatar.sh</string>
    <string>$mode</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$PROJECT_ROOT</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/Users/dhyanpatel/anaconda3/envs/tradingbot/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>TRADELOOP_AUTO_ROUTE_PAPER</key>
    <string>$auto_route</string>
    <key>TRADELOOP_BACKEND</key>
    <string>opencode</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>$hour</integer>
    <key>Minute</key>
    <integer>$minute</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/$label.out.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/$label.err.log</string>
  <key>ProcessType</key>
  <string>Background</string>
</dict>
</plist>
PLIST

  plutil -lint "$plist" >/dev/null
  launchctl bootstrap "gui/$UID_VALUE" "$plist"
}

LABELS=(
  com.tradeloop.qatar-premarket
  com.tradeloop.qatar-intraday-10
  com.tradeloop.qatar-intraday-13
  com.tradeloop.qatar-postclose
)

for label in "${LABELS[@]}"; do
  remove_job "$label"
done

install_job com.tradeloop.qatar-premarket 6 30 premarket true
install_job com.tradeloop.qatar-intraday-10 10 0 intraday true
install_job com.tradeloop.qatar-intraday-13 13 0 intraday true
install_job com.tradeloop.qatar-postclose 13 30 postclose false

echo "Installed TradeLoop Qatar launchd jobs."
echo "Schedule: 06:30 premarket, 10:00 intraday, 13:00 intraday, 13:30 postclose."
