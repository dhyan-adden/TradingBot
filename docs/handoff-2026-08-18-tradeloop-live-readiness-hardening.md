# TradeLoop Handoff - 2026-08-18 (live readiness hardening)

Resume point for a fresh worker session.
This file is the single source of truth for the current hardening batch.
Supersedes the older handoffs for execution purposes:
`docs/handoff-2026-07-04-tradeloop-live-smoke.md` and earlier.
The running project memory is auto-loaded each session; this doc is the short, actionable version.

## One-line state

TradeLoop runs a full Indian cash-equity swing loop end to end on live data with enforced evidence accountability.
It currently proposes orders and stops at `AWAITING_APPROVAL`; nothing routes live.
The system has zero closed paper trades, so live trading must stay disabled until the gates below are built and earned.

## Objective

Harden the existing TradeLoop system for eventual real Zerodha trading without redesigning the core architecture.

This is not a rewrite.
Keep the existing flow:

`prepare cycle -> analyst DAG -> PM decision -> orders.json -> approval -> route_cycle -> deterministic risk gate -> paper/live routing -> ledger -> audit`

## Non-negotiable constraints

- Do not change the core orchestrator lifecycle (`tradeloop/orchestrator.py`).
- Do not replace the existing analyst DAG (`tradeloop/lib/llm/stages.py`).
- Do not make small/free analysis models responsible for final trade decisions.
- Do not let markdown files unlock live trading.
- Do not enable real Zerodha order placement by default.
- Do not inspect, print, grep, or parse `.env` or any secret value.
- Human-in-loop must remain the default approval mode.
- Auto mode must exist but must never live-route unless an explicit policy gate is passed.
- Live trading requires at least 60 closed paper trades plus clean audits.
- The first live phase must be one-share canary only.
- Deterministic code always has the final route veto.
- Never add a comment claiming a task is "for later"; if a phase is deferred, it stays out of scope.

## Working environment

- Python interpreter: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python`.
- Run pytest from repo root: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests -q -W error`.
- Repo root is `/Volumes/D-DRIVE/TradingBot`.
- Never run code that reads `.env`.
- Never echo or serialize `process.env` or `.env` contents.

## Model architecture constraint

TradeLoop calls multiple analysis models per cycle.
Small/free models are used for bounded analysis stages and have under 250K context.
The strong paid model is reserved for final synthesis and verdict stages.

The responsibility split must hold:

| Stage | Model tier | Authority |
| --- | --- | --- |
| `10_news` | small/free | evidence extraction |
| `11_sentiment` | small/free | sentiment scoring |
| `12_fundamentals` | small/free | fundamental tags |
| `13_technical` | small/free | setup classification |
| `14_shortlist` | small/free | candidate compression |
| `20_bull` | small/free | argument generation |
| `21_bear` | small/free | counterargument generation |
| `22_debate` | strong paid | conflict resolution |
| `30_trade_plan` | strong paid | proposed trade tickets |
| `40_risk_report` | strong paid | model-side risk review |
| `41_pm_decision` | strong paid | final proposal only |
| `router`/`evaluate` | deterministic code | final route veto |

Principle:
small models analyze slices.
strong model adjudicates.
code enforces.

The existing model routing lives in `tradeloop/lib/llm/routing.py` (`STAGE_MODELS` and `CLAUDE_STAGE_MODELS`).
It already assigns cheap models to analysis stages and strong models to debate/trade/risk/PM.
Do not rebalance model names in this batch unless a phase below requires it.

## Current code seams

| File | Purpose |
| --- | --- |
| `tradeloop/orchestrator.py` | cycle and route lifecycle |
| `tradeloop/lib/llm/stages.py` | DAG stage runner |
| `tradeloop/lib/llm/routing.py` | per-stage model routing |
| `tradeloop/lib/llm/client.py` | OpenRouter JSON client with retry/fallback |
| `tradeloop/lib/llm/schemas.py` | Pydantic stage output models |
| `tradeloop/lib/config.py` | settings loader and risk cap mapping |
| `tradeloop/config/settings.yaml` | config knobs |
| `tradeloop/lib/broker/router.py` | paper/live route decision and promotion gate |
| `tradeloop/lib/broker/zerodha_mcp.py` | live payload builder |
| `tradeloop/lib/risk/checks.py` | deterministic risk engine |
| `tradeloop/lib/audit/ledger.py` | hash-chained ledger |
| `tradeloop/lib/audit/attribution.py` | paper performance calculation and report render |
| `tradeloop/lib/audit/reconcile.py` | ledger/book reconciliation helpers |
| `src/mcp/zerodha.ts` | Zerodha MCP place-order tool |
| `tradeloop/scripts/run_cycle.sh` | shell entrypoint with unsafe `.env` fallback |
| `tradeloop/scripts/cron_dispatch.sh` | launchd dispatcher with unsafe `.env` fallback |

Current facts a worker must know before touching code:

- `router.live_promotion_ready()` reads `tradeloop/memory/strategy_performance.md` and treats a literal `live_ready: true` line as authority.
- `attribution.render_strategy_performance()` writes `max_drawdown_pct` from worst single-trade R, not a true equity-curve drawdown.
- `route_order()` returns `live_mcp_required`/`READY_FOR_CODEX_TOOL_CALL` for live; it does not execute directly.
- `route_cycle()` re-checks holiday, kill switch, ledger tamper, mode, and promotion before routing.
- `evaluate()` runs on every routed order inside `route_orders_file`.
- `route_orders_file()` rebuilds the risk state per order so batch fills count toward cumulative caps.
- `run_cycle.sh:56` and `cron_dispatch.sh:23` grep `.env` for `OPENROUTER_API_KEY`.
- `settings.yaml` currently has `live_promotion_gates.min_paper_trades: 40`.
- `mode` is derived from the run-dir name trailing token (`<ts>_<mode>`).

## Execution modes (new)

Two approval modes, explicit and typed:

| Mode | Meaning |
| --- | --- |
| `human_in_loop` | TradeLoop proposes orders, waits for explicit human approval, then routes if all gates pass. Default. |
| `auto` | TradeLoop can route without per-trade human approval, but only after stricter promotion gates pass. |

Both modes share the same deterministic safety gates:
data health, broker reconciliation, risk checks, ledger integrity, kill switch, live caps, order idempotency, audit logging.
The only difference is the approval source:
human-in-loop approval comes from the human.
auto approval comes from the policy engine after promotion.

Auto mode must not imply live trading.
Live routing in auto mode requires all of:
`allow_auto_live: true` config, promotion pass, clean audits, broker reconciliation, and no kill switch.

## Implementation phases

### Phase 1 - Add execution mode config

Goal: add explicit `human_in_loop` and `auto` modes without changing default behavior.

Files:

- `tradeloop/config/settings.yaml`
- `tradeloop/lib/config.py`
- `tradeloop/tests/test_config.py`

Add config under a new top-level `execution:` block:

```yaml
execution:
  approval_mode: human_in_loop
  allow_auto_live: false
  live_canary:
    enabled: true
    max_quantity: 1
  promotion:
    min_closed_paper_trades: 60
    min_win_rate: 0.45
    min_expectancy_r: 0.3
    max_drawdown_r: 8.0
    require_clean_audits: true
```

Rules:

- Default `approval_mode` must be `human_in_loop`.
- `auto` mode must not imply live trading by itself.
- Auto live requires `allow_auto_live: true` plus promotion pass, clean audits, broker reconciliation, and no kill switch.
- Do not remove or alter the existing `modes:` cycle config.

Implementation notes:

- Add typed fields to the `Settings` dataclass in `tradeloop/lib/config.py`.
- Validate `approval_mode` is one of `{"human_in_loop", "auto"}` at load time.
- Keep `live_promotion_gates.min_paper_trades` for now; Phase 6 reworks the promotion source, and Phase 1 only adds the execution block.
- Move the promotion threshold to the new `execution.promotion.min_closed_paper_trades` field in Phase 6 and update `test_config.py` accordingly.

Tests to add in `tradeloop/tests/test_config.py`:

- Loading settings exposes `approval_mode` equal to `human_in_loop`.
- Invalid `approval_mode` value fails load.
- `allow_auto_live` defaults to `false`.
- `live_canary.max_quantity` defaults to `1`.
- Promotion threshold reads `60` from the new field.
- Promotion gates expose `min_win_rate`, `min_expectancy_r`, and `max_drawdown_r`.

Success criteria:

- No existing cycle behavior changes.
- Existing tests still pass.
- New config fields are typed in `Settings`.

### Phase 2 - Remove markdown as live authority

Goal: `strategy_performance.md` becomes report-only and can never unlock live trading.

Files:

- `tradeloop/lib/broker/router.py`
- `tradeloop/lib/audit/attribution.py`
- `tradeloop/tests/test_config.py`

Current risky code in `router.py`:

```python
if "live_ready: true" in text:
    return True
```

Required changes:

- Remove the `live_ready: true` shortcut from `live_promotion_ready`.
- Live readiness must come from ledger-derived closed paper trades and audit state, never from the markdown literal.
- Keep the markdown render for human readability, but make the `live_ready:` line informational only.
- The function signature of `live_promotion_ready` may stay; its behavior changes to ledger-based in Phase 6.
- Until Phase 6 lands, `live_promotion_ready` must return `False` when only the literal is present and no ledger-derived evidence exists.

Tests to add:

- A report containing `live_ready: true` with zero trades returns `False`.
- A report with `live_ready: true` and 59 trades returns `False`.
- Missing performance report returns `False`.
- A report with 60 trades but failing expectancy returns `False`.

Success criteria:

- Accidental markdown edits cannot enable live.
- Report generation remains human-readable.

### Phase 3 - Fix paper performance metrics

Goal: promotion uses real closed-trade stats, and drawdown is no longer mislabeled.

Files:

- `tradeloop/lib/audit/attribution.py`
- Add `tradeloop/tests/test_attribution.py`

Current issue:

`_aggregate()` computes `max_drawdown_pct` from `abs(min(realized_r))`, the worst single-trade loss in R.
That is not a percent drawdown.
A cluster of small losses can produce a larger equity-curve drawdown than the worst single trade.

Required changes:

- Keep `_episodes()` behavior for closed round trips unchanged.
- Add portfolio-level stats derived from the closed episodes.
- Compute closed paper trades, win rate, expectancy R, and a true equity-curve drawdown.
- Build the drawdown from the cumulative realized-R curve over the closed episode sequence.
- Name the R-based curve metric clearly, for example `max_drawdown_r`.
- Do not label an R-based number as `max_drawdown_pct`.
- Only a percent-of-equity drawdown may use the `_pct` name, and it is out of scope for this batch unless a percent series already exists.

Suggested implementation:

- Keep the `StrategyStat` per-strategy aggregation as-is.
- Add a `PortfolioStats` dataclass or extend `StrategyPerformance` with a portfolio-level record holding `max_drawdown_r`.
- Update `render_strategy_performance()` to emit the correct name.
- Stop using `max_drawdown_pct` for promotion in this batch.
- Phase 6 must consume `max_drawdown_r` only.
- If `max_drawdown_pct` remains in the markdown for historical readability, mark it deprecated and never use it as a gate input.

Tests to add in `tradeloop/tests/test_attribution.py`:

- Sequence `[+1R, -0.5R, -0.5R]` produces a drawdown from peak, not just the worst single trade.
- Sequence `[-1R, +2R]` handles an initial drawdown from zero.
- Open positions do not count as closed paper trades.
- A fill with no recorded hard stop is skipped and does not inflate the trade count.
- Re-running attribution over the same ledger does not duplicate trades.

Success criteria:

- Promotion metrics are reproducible from ledger events.
- Metric names match the actual math.

### Phase 4 - Add small-model stage budgets

Goal: prevent suboptimal outputs from smaller/free analysis models by bounding their input and output.

Files:

- `tradeloop/lib/llm/routing.py`
- `tradeloop/lib/llm/stages.py`
- `tradeloop/lib/llm/client.py`
- `tradeloop/config/settings.yaml`
- Add `tradeloop/tests/test_llm_stage_budgets.py`

Add per-stage budget config:

```yaml
llm_stages:
  default_max_input_chars: 120000
  default_max_output_tokens: 2500
  stages:
    10_news:
      max_input_chars: 80000
      max_output_tokens: 2000
      model_tier: small_free
    14_shortlist:
      max_input_chars: 120000
      max_output_tokens: 3000
      model_tier: small_free
    22_debate:
      max_input_chars: 160000
      max_output_tokens: 4000
      model_tier: strong_paid
    41_pm_decision:
      max_input_chars: 160000
      max_output_tokens: 4000
      model_tier: strong_paid
```

Required behavior:

- Before each stage call, estimate prompt size from `system + user` character count.
- The character budget is a conservative proxy for the sub-250K-context constraint, not an exact tokenizer.
- If over budget, fail loudly with a clear error rather than silently sending an oversized prompt.
- Do not silently truncate final-decision context (debate, trade plan, risk, PM).
- Small stages must receive compact, stage-specific inputs.
- Strong stages can receive compressed outputs from prior stages.
- Wire the budget lookup through `run_stage()` in `stages.py` and `call_json()` in `client.py`.

Implementation notes:

- Add a helper such as `stage_budget(stage, settings) -> StageBudget` in a small module or in `routing.py`.
- `run_stage()` computes the prompt before calling the client and raises `LLMConfigError` (or a new `LLMBudgetError`) when over budget.
- Use `max_tokens` from the budget when the client builds the request.
- Record the budget fields in the audit `CallRecord` if cheap to add; otherwise log the estimated input chars in the run dir.

Tests to add in `tradeloop/tests/test_llm_stage_budgets.py`:

- An over-budget small stage raises the budget error.
- The PM stage is allowed a larger budget.
- Budget lookup falls back to defaults for stages without explicit entries.
- No stage silently truncates input on over-budget; it raises instead.
- A fake client is used; never make real model calls in tests.

Success criteria:

- Smaller/free models are protected from huge context.
- Failures are explicit and auditable.

### Phase 5 - Add analyst output quality gates

Goal: weak small-model output degrades safely instead of becoming a confident trade.

Files:

- `tradeloop/lib/llm/schemas.py`
- `tradeloop/lib/llm/stages.py`
- Add `tradeloop/lib/llm/quality.py` (new)
- Add `tradeloop/tests/test_llm_quality_gates.py`

Required checks:

- Reject hollow outputs beyond the existing `{}` check in `client._parse_json_object`.
- Require evidence IDs for news-driven candidates.
- Require explicit uncertainty or empty arrays when evidence is missing.
- Small-model stages must not emit final trading verbs as authoritative output.
- Small stages may say evidence is bullish/bearish, but never a final BUY/SELL decision.
- Final BUY/SELL orders remain only in `41_pm_decision.orders`.

Suggested minimal approach:

- Add `validate_stage_quality(stage: str, result: BaseModel, run_dir: Path) -> None`.
- Call it from `run_stage()` after the schema-validated result is produced.
- Hard failures raise `LLMValidationError`.
- Soft degradations append a JSON line to `<run_dir>/analysis_quality.jsonl` and do not raise.
- Each quality line must include `stage`, `severity`, `scope`, `reason`, and `created_at`.
- Allowed `severity` values are `info`, `degraded`, and `hard_block`.
- Allowed `scope` values are `new_buys`, `all_orders`, and `research_only`.
- Keep schema changes minimal; prefer checks over schema surgery.
- Add `analysis_quality.jsonl` to the later manager-stage inputs in `STAGE_INPUTS` for `22_debate`, `30_trade_plan`, `40_risk_report`, and `41_pm_decision` so the strong paid stages see the degraded-research state.
- Add a deterministic pre-approval check in `orchestrator.run_cycle()` after reasoning and before printing `AWAITING_APPROVAL`.
- If `analysis_quality.jsonl` contains `severity=hard_block` and `scope=new_buys`, `orders.json` must contain no `BUY` orders.
- If `orders.json` contains a `BUY` under that condition, the cycle must print `tradeloop_cycle=QUALITY_BLOCKED`, write `quality_block.json`, and return non-zero before route approval is possible.

Specific checks:

- `10_news`: a `NewsName` with `tier` A or B and empty `evidence` is flagged.
- `14_shortlist`: a news-driven candidate (`source_track` in tier_a/tier_b/tier_c) with empty `evidence` is flagged.
- `41_pm_decision`: the only stage allowed to produce `orders`; assert no other stage schema carries an orders field (already true today, add a guard test).

Tests to add in `tradeloop/tests/test_llm_quality_gates.py`:

- `10_news` tier-A candidate with no evidence is flagged.
- `14_shortlist` news-driven candidate with empty evidence is degraded or rejected.
- `41_pm_decision` remains the only stage allowed to output `orders`.
- `analysis_quality.jsonl` is included in the manager-stage inputs.
- A `hard_block/new_buys` quality line prevents a new BUY before `AWAITING_APPROVAL`.
- A `hard_block/new_buys` quality line does not block a SELL exit-only `orders.json`.
- A fake client is used; never make real model calls in tests.

Success criteria:

- Small-model failures cannot silently cascade into confident BUYs.

### Phase 6 - Add live promotion service

Goal: centralize live readiness logic outside router markdown parsing.

Files:

- Add `tradeloop/lib/live/promotion.py` (new package `tradeloop/lib/live/`)
- `tradeloop/lib/broker/router.py`
- `tradeloop/orchestrator.py`
- Add `tradeloop/tests/test_live_promotion.py`

Suggested API:

```python
@dataclass(frozen=True)
class PromotionStatus:
    ready: bool
    reasons: list[str]
    closed_paper_trades: int
    win_rate: float
    expectancy_r: float
    max_drawdown_r: float
    clean_audits: bool

def evaluate_live_promotion(root: Path, settings: Settings) -> PromotionStatus:
    ...
```

Rules:

- Minimum closed paper trades is `60` from `execution.promotion.min_closed_paper_trades`.
- Audit gate must be clean.
- Ledger chain must verify.
- The markdown report is not authoritative.
- Return a reason string for every failed gate.
- `route_cycle()` calls the promotion service when live is enabled.
- `route_order()` calls the promotion service as defense in depth.
- Replace the body of `live_promotion_ready()` to delegate to `evaluate_live_promotion`.

Implementation notes:

- Do not make promotion depend on the markdown performance report.
- Add a trade-metrics helper that works from ledger fill events only, for example `portfolio_stats_from_fills(fills: list[dict]) -> PortfolioStats` in `tradeloop/lib/audit/attribution.py` or a small adjacent module.
- The helper may reuse `_episodes(fills)` but must not require a current run's `trade_plans` object.
- Closed-paper-trade count is the number of closed episodes with a valid entry stop and computable realized R.
- Win rate is wins divided by closed-paper-trade count.
- Expectancy is mean realized R.
- Drawdown gate uses `max_drawdown_r` from the cumulative realized-R curve.
- The audit gate is strict and simple for this batch: scan every run directory under `tradeloop/runs` that contains a non-empty `fills.json`.
- A run is audit-clean only if `audit_error.txt` is absent, `controls.json` exists, and `controls.json.deficiencies` contains no item whose `severity` is `material_weakness` or `significant_deficiency`.
- Missing `controls.json` for a routed/non-empty-fills run is not clean.
- `40_reconcile.md` must exist and contain `clean: all sources agree` for the run to be clean until Phase 9 replaces this with structured broker reconciliation.
- Ledger verification uses `Ledger.verify_chain()`; a `LedgerTamperError` becomes a failed gate.
- Keep `router.live_promotion_ready()` callable so existing tests and callers keep working.

Tests to add in `tradeloop/tests/test_live_promotion.py`:

- Missing ledger returns not ready with a reason.
- Tampered ledger returns not ready.
- 59 closed trades returns not ready.
- 60 closed trades plus a dirty audit returns not ready.
- 60 closed trades plus clean audit plus passing metrics returns ready.
- A markdown `live_ready: true` literal has no effect.
- A markdown file with 60 trades but failing expectancy returns not ready.
- Missing `controls.json` on a routed run returns not ready.
- Any `material_weakness` or `significant_deficiency` in `controls.json.deficiencies` returns not ready.
- Missing or non-clean `40_reconcile.md` returns not ready.

Success criteria:

- One source of truth for live promotion.

### Phase 7 - Add one-share live canary gate

Goal: first live rollout cannot accidentally route normal size.

Files:

- `tradeloop/lib/risk/checks.py`
- `tradeloop/lib/broker/router.py`
- `tradeloop/lib/config.py`
- Add `tradeloop/tests/test_live_canary.py`

Rules:

- If the live canary is enabled, every live BUY quantity must be `<= max_quantity` (default 1).
- This phase only implements the live BUY canary cap.
- Do not implement live-holdings-aware SELL checks in this phase; Phase 9 owns broker reconciliation and live holdings.
- SELL quantity remains guarded by the existing deterministic risk gate until Phase 9 adds broker-state checks.
- The canary applies only to the live route path, never the paper path.
- Paper mode keeps existing sizing behavior.
- Canary can be disabled only by config after a clean canary audit.

Implementation notes:

- Add a live-specific pre-route check in `router.route_order()` before `to_zerodha_payload()`.
- Do not put canary logic inside the paper broker.
- A blocked canary order returns a `RoutedOrder` with status such as `LIVE_CANARY_BLOCKED`.

Tests to add in `tradeloop/tests/test_live_canary.py`:

- Paper BUY quantity 20 still fills.
- Live BUY quantity 20 is blocked.
- Live BUY quantity 1 proceeds to the live payload path after promotion passes.
- SELL behavior is unchanged in this phase and remains covered by existing risk-gate tests.
- Canary block writes a decision/fill status for audit.

Success criteria:

- First live phase is mechanically one-share only.

### Phase 8 - Add approval artifact for human-in-loop

Goal: approving a run must bind to the exact `orders.json`.

Files:

- `tradeloop/orchestrator.py`
- Add `tradeloop/lib/approval.py` (new)
- Add `tradeloop/tests/test_approval.py`

Suggested artifact at `<run_dir>/approval.json`:

```json
{
  "run_id": "2026-08-18_0900_premarket",
  "orders_sha256": "...",
  "approval_mode": "human_in_loop",
  "approved_live": false,
  "approved_by": "dhyan",
  "approved_at": "ISO-8601",
  "notes": ""
}
```

Rules:

- Paper route keeps current behavior.
- A live human-in-loop route requires a valid approval artifact.
- `orders_sha256` must match the current `orders.json` hash.
- If `orders.json` changes after approval, the route blocks.
- Auto mode does not use the human approval artifact, but must satisfy the stricter policy gate.

Implementation notes:

- Add `validate_approval(run_dir, orders_path) -> ApprovalStatus` in `tradeloop/lib/approval.py`.
- Call it from `route_cycle()` before routing when the run is a live human-in-loop route.
- Keep paper routing unchanged.

Tests to add in `tradeloop/tests/test_approval.py`:

- Missing approval blocks a live human-in-loop route.
- Wrong hash blocks.
- Correct hash allows the route to continue to the risk gate.
- Paper route is unchanged.
- Auto mode cannot reuse a stale human approval.

Success criteria:

- Human approval is explicit and unambiguous.

### Phase 9 - Add broker reconciliation gate

Goal: a live route cannot proceed unless Zerodha account state matches TradeLoop state.

Files:

- `tradeloop/lib/audit/reconcile.py`
- `tradeloop/orchestrator.py`
- Add `tradeloop/lib/broker/live_state.py` (new)
- Add `tradeloop/tests/test_live_reconciliation.py`

Required checks before a live route:

- Ledger chain verifies.
- Zerodha holdings are fetched.
- Zerodha open orders are fetched.
- Zerodha margins or available cash are fetched.
- TradeLoop ledger book matches Zerodha holdings for symbols TradeLoop manages.
- Live SELL quantity must not exceed Zerodha-held quantity for that symbol.
- No duplicate open order exists for the same run/symbol/side.
- Available cash/margin is enough for proposed BUYs.
- Any mismatch blocks the live route.

Implementation notes:

- Keep this as a gate before live payload generation in `router.route_order()` and `orchestrator.route_cycle()`.
- Do not implement a full broker order lifecycle in this phase.
- Add `LiveBrokerSnapshot` and `LiveReconciliationStatus` dataclasses in `tradeloop/lib/broker/live_state.py`.
- Persist the fetched broker snapshot into `<run_dir>/live_broker_snapshot.json` with no secrets.
- Persist the reconciliation result into `<run_dir>/live_reconcile.json`.
- `live_reconcile.json` must include `ok`, `reasons`, `checked_at`, `symbols_checked`, and `open_order_conflicts`.
- The live route gate reads `live_reconcile.json` and blocks unless `ok` is `true` and `checked_at` is fresh.
- Fresh means the timestamp is no older than 120 seconds at route time.
- If the snapshot is missing, malformed, stale, or contains an auth failure marker, block live route.
- Do not require broker snapshots for paper routes.
- Use a fake transport for tests; never hit the real broker in tests.

Tests to add in `tradeloop/tests/test_live_reconciliation.py`:

- Matching holdings pass.
- Quantity mismatch blocks.
- Live SELL exceeding Zerodha-held quantity blocks.
- Duplicate open order blocks.
- Missing broker snapshot blocks live.
- Stale broker auth blocks live.
- Stale `checked_at` blocks live.
- Paper route ignores missing live broker snapshot.

Success criteria:

- A live route never relies only on paper ledger state.

### Phase 10 - Remove unsafe `.env` shell reads

Goal: comply with the repo credential policy.

Files:

- `tradeloop/scripts/run_cycle.sh`
- `tradeloop/scripts/cron_dispatch.sh`
- Add `tradeloop/tests/test_secret_hygiene.py`

Current unsafe patterns:

- `run_cycle.sh:56` runs `grep '^OPENROUTER_API_KEY=' "$PROJECT_ROOT/.env"`.
- `cron_dispatch.sh:23` does the same.

Required behavior:

- Shell scripts must not read `.env`.
- Shell scripts may consume env vars already present in the environment.
- Add masked credential status checks only; output must be `SET` or `MISSING`, never values.
- Keep the project-local Zerodha MCP configuration as-is.

Implementation notes:

- Remove the `.env` fallback blocks from both scripts.
- Document that the caller (launchd, terminal session, or agent harness) is responsible for injecting `OPENROUTER_API_KEY`.
- Add a small status helper that prints only `SET` or `MISSING`, e.g. in `tradeloop/scripts/verify_setup.py` or a new `tradeloop/scripts/env_status.py`.
- The helper may read an env var name from argv and report presence; it must never print the value.

Tests to add in `tradeloop/tests/test_secret_hygiene.py`:

- Static test fails if any shell script under `tradeloop/scripts/` contains `.env`.
- Static test fails if any shell script greps for a key-named variable.
- The status helper prints only `SET` or `MISSING`.

Success criteria:

- No production script reads `.env`.

### Phase 11 - Keep live execution as payload first

Goal: avoid overbuilding broker execution while still hardening live readiness.

Current live path:

- `router.route_order()` returns `live_mcp_required` with status `READY_FOR_CODEX_TOOL_CALL`.
- `src/mcp/zerodha.ts` requires `ZERODHA_ENABLE_TRADING=true` and `confirm=true`.

Plan for this batch:

- Keep this shape.
- Add all gates from Phases 1-10 before payload generation.
- Do not build a direct Python Zerodha execution adapter in this batch.

Reason:
preserving the core system minimizes risk.
A future batch can add Python-owned broker lifecycle only after the gating layer is correct.

Success criteria:

- A live payload can be generated only after all gates pass.
- The actual broker tool call remains separately confirmed.

## Order of implementation

Implement in this order so each phase builds on the previous:

1. Phase 1 (execution mode config).
2. Phase 2 (remove markdown authority).
3. Phase 3 (fix metrics).
4. Phase 4 (stage budgets).
5. Phase 5 (quality gates).
6. Phase 6 (promotion service) - depends on 2 and 3.
7. Phase 7 (canary) - depends on 1 and 6.
8. Phase 8 (approval artifact).
9. Phase 9 (reconciliation) - depends on 8.
10. Phase 10 (secret hygiene).
11. Phase 11 (payload-first confirmation) - no code, verify.

A single worker should implement one phase at a time and run that phase's tests before moving on.

## Verification commands

Run the existing targeted tests first to confirm a clean baseline:

```bash
/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/test_config.py tradeloop/tests/test_router_gate.py tradeloop/tests/test_orchestrator.py tradeloop/tests/test_ledger_production.py tradeloop/tests/test_verify_health.py -q -W error
```

Run the full suite after every phase:

```bash
/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests -q -W error
```

## Worker instructions

Each worker implements only one phase.

Each worker must:

- Read this file first.
- Read the named files for their phase.
- Make the smallest change that satisfies the phase.
- Add or update tests for the phase.
- Run the targeted tests, then the full suite.
- Never refactor unrelated code.
- Never inspect `.env` or print secret values.
- Never enable live trading.
- Never change the default behavior away from paper/human-in-loop.
- Never touch `docs/CHANGELOG.md` or auto-generated files.
- Report back: files changed, tests added, test results, and any assumption made.

## Implementation status

All 11 phases are implemented and verified in this batch.

- Phase 1: `config.py` `Settings` + `load_settings` (flat promotion/canary/approval fields); `settings.yaml` `execution:` + `llm_stages:`.
- Phase 2: `router.live_promotion_ready` no longer reads `live_ready: true`; markdown cannot unlock live.
- Phase 3: `attribution._max_drawdown_r` true cumulative R drawdown; `max_drawdown_r` emitted.
- Phase 4: `budget.py` + per-stage `max_tokens`; `stages.run_stage` budget check.
- Phase 5: `quality.py` gates; wired into `stages.run_stage` + `orchestrator.run_cycle` (`QUALITY_BLOCKED`).
- Phase 6: `attribution.portfolio_stats_from_fills` + `live/promotion.py` `evaluate_live_promotion`; `router.live_promotion_ready` delegates.
- Phase 7: `router.route_order` one-share live canary cap (`LIVE_CANARY_BLOCKED`).
- Phase 8: `approval.py` `validate_approval` bound to `orders.json` sha256; wired into `orchestrator.route_cycle` (`APPROVAL_REQUIRED`).
- Phase 9: `broker/live_state.py` reconciliation; gate wired into `orchestrator.route_cycle` (`LIVE_RECONCILE_BLOCKED`).
- Phase 10: removed `.env` reads from `run_cycle.sh` + `cron_dispatch.sh`; added `scripts/env_status.py` (SET/MISSING only).
- Phase 11: live path stays payload-first (`READY_FOR_CODEX_TOOL_CALL`); all gates run before payload.

Verification: `pytest tradeloop/tests -q -W error` -> 412 passed, 1 skipped. Pre-existing, unrelated LSP noise remains in `attribution.py` (object-typed plan fields) and `test_attribution.py` (mixed-type `_plan` helper); no runtime or test impact.

## Definition of done

The hardening batch is complete when all of the following hold:

- The existing core cycle still works.
- `human_in_loop` is the default approval mode.
- `auto` mode exists but cannot live-route unless `allow_auto_live` plus full promotion pass.
- Live promotion requires at least 60 closed paper trades.
- Live promotion requires clean audits.
- Markdown cannot unlock live.
- Drawdown metric is no longer mislabeled as percent.
- Small/free model stages have input/output budgets.
- Small/free model outputs are quality-gated.
- One-share live canary is enforced.
- Human approval binds to the `orders.json` hash.
- Broker reconciliation blocks mismatches before live payload generation.
- Shell scripts no longer read `.env`.
- Full `pytest tradeloop/tests` passes with `-W error`.
