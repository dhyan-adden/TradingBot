# Memory Schema

## Source of Truth

SQLite is the machine source of truth. Every signal, risk decision, simulated
order, fill, close, lesson, and proposal is written as an append-only event.

Markdown files under `memory/` are projections. They are designed for human
review and template refinement. Manual edits should never change trade truth.

## Event Requirements

Each event stores:

- `event_id`
- `event_type`
- `aggregate_id`
- JSON payload
- creation timestamp
- stable event hash

The stable hash is computed from event type, aggregate ID, and canonical JSON
payload. This lets replay and markdown projections detect drift.

## Markdown Projection Rules

- Projection output must be idempotent.
- Atomic writes should use temp file + fsync + rename.
- Each generated markdown file should include source hashes.
- If a generated file has manual edits, regeneration should refuse overwrite
  unless `--force` is passed.
- A `--dry-run` mode should show diffs without writing files.

## TradingAgents-Inspired Decision Memory

In addition to daily, trade, scorecard, lesson, and proposal projections, the
Indian-market graph should emit decision projections:

- analyst reports for market/news/fundamentals/sentiment
- bull and bear debate summaries
- research manager plan
- trader proposal
- portfolio manager final decision
- post-outcome reflection after a paper trade closes

These files are still projections. The source of truth remains SQLite events.

## Closed Loop Learning Events

The closed-loop runner adds rule-first learning events after a paper position is
closed:

- `learning.metrics_written`
- `learning.lesson_written`
- `learning.proposal_written`

Lessons are generated from deterministic trade metrics first. Proposal files
are always `pending_review` and must not be auto-applied.

## Agent-Led Research Events

The agent-led loop writes online research and decision events before any paper
execution gate:

- `research.news_fetched`
- `research.trend_summary_written`
- `agent.report_written`
- `agent.trader_proposal_written`
- `agent.portfolio_decision_written`
- `agent.vetoed`

These events let markdown projections and the dashboard explain why a signal was
allowed, vetoed, risk-rejected, or executed.

## V1 Taxonomy

Start with simple labels and refine during the first paper-trading week:

- Mistake classes: `entered_against_trend`, `stop_too_tight`,
  `stop_too_wide`, `sized_too_large`, `chased_after_gap`,
  `held_through_earnings`, `ignored_volume_dryup`.
- Insight classes: `regime_detection_worked`, `exit_discipline_held`,
  `sizing_appropriate_for_volatility`.

The post-trade learning agent may propose config changes, but it must never
apply them directly.
