# TradeLoop Operator Runbook

This runbook explains how to execute TradeLoop, monitor it, route paper orders, debug issues, and confirm that the system learned from trades.

## Safety Boundary

TradeLoop should run in paper mode until paper performance, audits, reconciliation, and live promotion gates are clean.

The paper route button and paper route commands force `ZERODHA_ENABLE_TRADING=false`.

Do not enable live trading unless the live-readiness gates explicitly pass.

Use `tradeloop/kill_switch.md` to halt routing immediately.

## Visual Flow

```text
Start cycle
  -> collect news, prices, holdings, memory
  -> scan strategy setups
  -> classify market regime
  -> run expert pipeline
  -> write orders.json
  -> Python risk gate validates orders
  -> route paper orders
  -> write fills and ledger events
  -> post-trade audit and learning
  -> next cycle reads updated memory
```

## Start The Dashboard

Run this from the repo root.

```bash
cd /Volumes/D-DRIVE/TradingBot
/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m tradeloop.dashboard
```

Open the dashboard.

```text
http://127.0.0.1:8765/
```

Use the dashboard to monitor runs, expert outputs, model usage, orders, fills, portfolio state, source health, and live-readiness gates.

## Run A Cycle Manually

Use the OpenCode backend for the intended hybrid setup.

```bash
cd /Volumes/D-DRIVE/TradingBot
TRADELOOP_AGENT=opencode ./tradeloop/scripts/run_cycle_logged.sh premarket
```

Run intraday holdings management.

```bash
cd /Volumes/D-DRIVE/TradingBot
TRADELOOP_AGENT=opencode ./tradeloop/scripts/run_cycle_logged.sh intraday
```

Run postclose review and learning.

```bash
cd /Volumes/D-DRIVE/TradingBot
TRADELOOP_AGENT=opencode ./tradeloop/scripts/run_cycle_logged.sh postclose
```

Use detached runs when the cycle should survive a terminal or agent session ending.

```bash
cd /Volumes/D-DRIVE/TradingBot
./tradeloop/scripts/run_detached.sh premarket --backend opencode
```

Resume an interrupted run in place.

```bash
cd /Volumes/D-DRIVE/TradingBot
./tradeloop/scripts/run_detached.sh premarket --backend opencode tradeloop/runs/<run_dir>
```

## Cycle Types

`premarket` finds new opportunities and may propose BUY or SELL orders.

`intraday` manages current holdings and may ADD, TRIM, EXIT, HOLD, or TIGHTEN_STOP.

`postclose` reviews, audits, attributes results, and updates memory.

`postclose` does not route orders because the market is closed.

## Monitor A Run

Each run is written here.

```text
tradeloop/runs/<timestamp>_<mode>/
```

Important files inside a run directory are listed below.

```text
00_context.md              portfolio, cash, positions, stops, memory context
01_news_raw.md             raw news and macro stories
02_setups_raw.md           technical setup scan
03_market_regime.md        regime, cycle, risk posture, strategy bias
03_market_regime.json      machine-readable regime output
10_news.md                 news expert output
11_sentiment.md            sentiment expert output
12_fundamentals.md         fundamentals expert output
13_technical.md            technical expert output
14_shortlist.md            shortlist output
15_holdings_review.md      holdings review output
20_bull.md                 bull case
21_bear.md                 bear case
22_debate.md               judge/debate output
30_trade_plan.md           trade plan
40_risk_report.md          risk expert output
41_pm_decision.md          final portfolio decision
orders.json                proposed orders
fills.json                 routed paper/live outcomes
decisions.jsonl            risk gate decisions per order
controls.json              post-route audit output
llm_calls.jsonl            per-stage model and usage records
```

Cycle logs are written here.

```text
tradeloop/reports/cycle_logs/
```

Cron logs are written here.

```text
tradeloop/reports/cron.log
```

## Route Paper Orders

Use the dashboard button after reviewing a run.

```text
Route paper orders
```

The button requires confirmation and routes only through `PaperBroker`.

It never sends a live Zerodha order.

You can also route a run from the command line in paper mode.

```bash
cd /Volumes/D-DRIVE/TradingBot
ZERODHA_ENABLE_TRADING=false /Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m tradeloop.orchestrator route tradeloop/runs/<run_dir>
```

After routing, check these files.

```text
tradeloop/runs/<run_dir>/fills.json
tradeloop/runs/<run_dir>/decisions.jsonl
tradeloop/state/ledger.db
```

## Holdings Actions

The holdings reviewer can produce these actions.

```text
HOLD          no order
ADD           buy more of an already-held symbol if risk sizing allows it
TRIM          sell part of the current position
EXIT          sell the full current position
TIGHTEN_STOP  raise the recorded stop without selling
```

`ADD` cannot open a brand-new intraday position.

`TRIM` cannot sell more than the current held quantity.

`EXIT` sells the full current held quantity.

Stop breaches are force-exited even if the model misses them.

## Market Regime Check

Every prepared run now writes a regime artifact.

```text
tradeloop/runs/<run_dir>/03_market_regime.md
```

The regime classifier can output these regimes.

```text
data_sparse
risk_off
trend_up
pullback_in_uptrend
choppy
range_bound
```

It also writes the cycle, risk posture, strategy bias, and reasons.

Use this file to check whether the system thinks the current environment favors trend following, mean reversion, breakout continuation, momentum pullback, or reduced risk.

## Strategy Families

The active strategy shape is an ensemble of simple families.

```text
trend_following
mean_reversion
breakout_continuation
momentum_pullback
news_catalyst
position_management
```

`news_catalyst` should confirm or veto trades, not act as a standalone execution strategy.

`position_management` is always available for current holdings.

## Check LLM Usage And Cost

Use the dashboard LLM usage card for the selected run.

The raw per-stage usage file is here when the OpenCode or Claude backend is used.

```text
tradeloop/runs/<run_dir>/llm_calls.jsonl
```

Legacy Codex runs may recover total token usage from cycle logs instead of per-stage calls.

## Check Learning

The system learns through local memory, not model fine-tuning.

After paper fills and closed trades, run postclose.

```bash
cd /Volumes/D-DRIVE/TradingBot
TRADELOOP_AGENT=opencode ./tradeloop/scripts/run_cycle_logged.sh postclose
```

Then check these memory files.

```text
tradeloop/memory/trade_journal.md
tradeloop/memory/strategy_performance.md
tradeloop/memory/stock_dossiers/<TICKER>.md
tradeloop/memory/carry_forward_context.md
```

Learning happened if `trade_journal.md` contains the closed trade.

Learning happened if `strategy_performance.md` updates paper trade count, win rate, expectancy, or drawdown.

Learning happened if the ticker dossier has a new outcome entry.

Learning happened if `carry_forward_context.md` contains updated guidance for the next cycle.

Future cycles read these files through `00_context.md`, so prior outcomes influence later expert decisions.

## Debug A Failed Cycle

First identify the latest run directory from the dashboard or logs.

Then check the run status files.

```text
tradeloop/runs/<run_dir>/reasoning_error.txt
tradeloop/runs/<run_dir>/ingest_error.txt
tradeloop/runs/<run_dir>/ltp_error.txt
tradeloop/runs/<run_dir>/orders.json
tradeloop/runs/<run_dir>/fills.json
tradeloop/runs/<run_dir>/decisions.jsonl
tradeloop/runs/<run_dir>/controls.json
```

Common failure signals are listed below.

```text
tradeloop_cycle=SKIP                 holiday, no holdings, or expected no-op
tradeloop_cycle=LOCKED               another cycle is already running
tradeloop_cycle=REASONING_FAILED     an expert stage failed
tradeloop_cycle=ORDERS_INVALID       orders.json failed validation
tradeloop_cycle=QUALITY_BLOCKED      quality gate blocked new BUY orders
tradeloop_route=ORDERS_INVALID       route failed because orders were malformed
tradeloop_route=ALREADY_ROUTED       fills already exist for this run
tradeloop_route=KILL_SWITCH_ACTIVE   kill switch blocked routing
```

Run setup verification.

```bash
cd /Volumes/D-DRIVE/TradingBot
/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python tradeloop/scripts/verify_setup.py --mode premarket
```

Run tests before a production push.

```bash
cd /Volumes/D-DRIVE/TradingBot
/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests -q
git diff --check
```

## Daily Paper Operating Routine

Start the dashboard before market activity.

Run or schedule `premarket` for entry discovery.

Review the dashboard and route paper orders if the run is clean.

Run or schedule `intraday` to manage current holdings.

Route paper ADD, TRIM, or EXIT orders if the run is clean.

Run `postclose` after market close to update learning.

Check `strategy_performance.md` and the dashboard before the next trading day.

## Cron Reference

The repo includes a cron example here.

```text
tradeloop/scripts/crontab.txt
```

The current default schedule shape is below.

```text
08:00 IST  premarket
14:00 IST  intraday
16:00 IST  postclose
08:30-17:30 IST schedule health checks
```

For the future autonomous paper goal, update this schedule to three market checks plus postclose learning.

Keep live trading disabled while validating paper automation.

## Qatar Auto-Run Schedule

The Qatar-time auto-run scripts are here.

```text
tradeloop/scripts/auto_run_qatar.sh
tradeloop/scripts/install_qatar_autorun_cron.sh
tradeloop/scripts/crontab_qatar.txt
tradeloop/scripts/install_qatar_launchd.sh
```

Install the Qatar cron block.

```bash
cd /Volumes/D-DRIVE/TradingBot
./tradeloop/scripts/install_qatar_autorun_cron.sh install
```

Remove the Qatar cron block.

```bash
cd /Volumes/D-DRIVE/TradingBot
./tradeloop/scripts/install_qatar_autorun_cron.sh uninstall
```

The Qatar schedule is below.

```text
06:30 Qatar  premarket
10:00 Qatar  intraday
13:00 Qatar  intraday
13:30 Qatar  postclose
```

`postmarket`, `post-market`, and `post_market` are accepted aliases for `postclose` in the auto-runner.

Logs are written here.

```text
tradeloop/reports/qatar_autorun.cron.log
tradeloop/reports/cycle_logs/latest_qatar.log
```

Paper auto-routing is active for the Qatar cron `premarket` and `intraday` slots.

The cron entries set `TRADELOOP_AUTO_ROUTE_PAPER=true` and the runner still forces `ZERODHA_ENABLE_TRADING=false`.

`postclose` never auto-routes because it is learning and review only.

For macOS unattended scheduling, use the native `launchd` installer.

```bash
cd /Volumes/D-DRIVE/TradingBot
./tradeloop/scripts/install_qatar_launchd.sh
```

The installer creates four per-user jobs under `~/Library/LaunchAgents`.

`launchd` is preferred over cron on macOS because it is integrated with the user session and is more reliable when the laptop wakes from sleep.

The laptop still needs power and network access, and it must be awake or configured to wake for the scheduled calendar events.
