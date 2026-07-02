# RakshaQuant Integration Notes

## Decision

Use RakshaQuant as an architecture reference, not as a vendored dependency.

The useful parts are its paper execution shape, risk-check taxonomy, agent state
flow, and memory-loop concepts. The parts intentionally not copied for this
phase are DhanHQ execution, YFinance-only assumptions, PostgreSQL memory, Groq
agents, dashboards, and live-order paths.

## What Was Ported First

- Event-sourced paper broker with simulated fills and `PAPER-*` order IDs.
- Deterministic risk engine for universe, position size, deployed capital,
  max positions, short-selling guard, and kill switch.
- YFinance market-data adapter for early paper-harness testing.
- LangGraph-compatible workflow boundary with deterministic nodes first.
- Markdown memory projections from SQLite events.

## Current Data Policy

YFinance is the first paper-feed source because it is low-friction and does not
require daily broker auth. Zerodha remains the later validation feed after the
paper harness has run for a few days. Live broker execution stays disabled.

## Current Agent Policy

The workflow is shaped so LangGraph can orchestrate it, but Codex advisory work
must remain markdown-only. Agents can produce lessons and proposals, but they
cannot place orders, edit configs directly, or access secrets.

## Runbook

```bash
conda activate tradingbot
tradingbot config-check
tradingbot paper-loop --symbols RELIANCE --iterations 1
tradingbot paper-status
tradingbot memory-regenerate --dry-run
```

To simulate a paper order explicitly:

```bash
tradingbot paper-order RELIANCE BUY 1 1339 --strategy manual_smoke
```

To test the market-polling loop with simulated buying enabled:

```bash
tradingbot paper-loop --symbols RELIANCE --iterations 1 --buy
```

## Acceptance Checks

- `paper-loop` without `--buy` records quotes, no-trade decisions, marks, and
  memory updates, but does not create orders.
- `paper-order` routes through the risk engine before simulating a fill.
- `memory-regenerate --dry-run` is clean immediately after regeneration.
- `paper-status` reports only fake paper portfolio state.
