# TradeLoop

Agent-driven, India-only, news-discovery-first paper trading loop for cash equities.

The current operational target is a safe, propose-only paper loop using live market data.
Live promotion is intentionally not achieved until the ledger contains the configured closed-paper-trade history and all audit gates pass.

Python does the deterministic work (data fetch, ticker extraction, indicators, sizing, cost model, portfolio state, broker payloads, hash-chained ledger, markdown memory).
An LLM reasoning DAG does the judgment through file boundaries.
Every order passes two deterministic gates before it can fill: the risk gate (`evaluate()`) and the cycle-mode gate (postclose never trades, intraday exits only).

## Layout

```
tradeloop/            the system
  orchestrator.py     desk manager: gates -> lock -> prepare -> reason -> propose -> route
  prompts/            00_master + 13 role prompts (news -> ... -> PM, post-trade)
  lib/
    llm/              OpenRouter reasoning DAG (client, routing, schemas, stages)
    data/             ingest + sources/ + snapshot + evidence/grounding gates + Kite client
    ta/               scanner + indicators (full-NSE universe)
    broker/           router (risk + mode gates), paper_broker, orders_schema
    risk/             evaluate() gate, sizing, circuit_breaker (kill switch)
    audit/            hash-chained ledger, reconcile, controls, attribution, postclose learning
    portfolio/  memory/  util/
  dashboard/          stdlib read-only web UI (:8765) - portfolio + run cards
  scripts/            prepare_cycle, verify_setup, cron_dispatch, run_cycle.sh
  config/             settings, universe, indicators, news_sources, strategy_families
  state/              ledger.db (hash-chained) + orchestrator.lock
  memory/             journal, lessons, dossiers, strategy_performance (promotion gate)
  runs/               archived cycle directories (audit trail)

src/mcp/zerodha.ts    Zerodha Kite MCP - the one broker integration (prices, instruments, historical)
scripts/              zerodha-auth.ts, env-status.ts (daily token + env check)
bin/codex-zerodha     launcher that injects the project-only Kite MCP
docs/                 architecture, handoffs, research notes
legacy/               archived engine-1 (LangGraph paper harness) - reference only, not run
```

## Setup

Python runs in the conda env named `tradingbot` (Python 3.11):

```bash
conda activate tradingbot
python -m pip install -e ".[dev]"
```

Node is only needed for the Zerodha MCP and the daily auth helper:

```bash
npm install
cp .env.example .env    # then fill it
```

## Daily token

Zerodha access tokens expire daily and a new login invalidates the previous one.
Refresh before a live-data cycle, then verify with a real price call (the instruments endpoint is lenient on stale tokens):

```bash
npm run auth:zerodha -- --listen
```

## Run a cycle

Cycles are propose-only: they stop at `AWAITING_APPROVAL` and never route until you approve.

```bash
# propose (live market data on; paper routing)
ZERODHA_ENABLE_DATA=true python -m tradeloop.orchestrator premarket

# approve + route a proposed run (this invocation IS the approval)
python -m tradeloop.orchestrator route tradeloop/runs/<timestamp>_<mode>
```

Cycle modes:

- `premarket` (08:00 IST): full pipeline; new long entries allowed.
- `intraday` (12:30 IST): manage existing longs only; no new entries.
- `postclose` (16:00 IST): no trading; learning and memory updates only.
- `adhoc "<request>"`: read the request, then run the necessary path.

Cron runs premarket at 08:00 IST on weekdays via `tradeloop/scripts/cron_dispatch.sh`.

## Dashboard

```bash
python -m tradeloop.dashboard        # http://127.0.0.1:8765
```

## Non-negotiables

- Indian cash equities only. Long-only. No shorts, no F&O, no leverage.
- `tradeloop/kill_switch.md` halts all orders.
- `ZERODHA_ENABLE_TRADING=false` is the default and routes to paper; live routing additionally requires the strategy-performance promotion gate.
- Code and scripts never read `.env` or print secret-like values.

## Current Readiness

- Implemented scanner families: `breakout_20d_pullback` and `ema_trend_pullback`.
- Planned scanner families: post-earnings drift, results-day momentum, and sector-rotation leader.
- The long-term validation-lab and hybrid-fund vision in `tradeloop/docs/vision.md` remains roadmap work.
- Run `python tradeloop/scripts/verify_setup.py --health` before a data-backed cycle.

## Legacy engine-1

`legacy/` holds the original LangGraph paper harness (`tradingbot` package plus its own tests, config, state, and memory).
It is kept as reference only, is not imported by TradeLoop, and is not run.
Its usage notes live in `legacy/README.md`.
