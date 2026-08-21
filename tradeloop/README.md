# TradeLoop

TradeLoop is an agent-driven, India-only, news-discovery-first trading loop.
Python owns deterministic orchestration, data fetch, validation, routing gates,
paper execution, audit, and dashboard state.
The default manual path uses the in-process Claude backend through
`python -m tradeloop.orchestrator` or `scripts/run_detached.sh`.

## Reasoning agent

The current supported manual backend is Claude:

```bash
./tradeloop/scripts/run_detached.sh premarket --backend claude
```

The OpenCode backend can mix your OpenAI subscription with OpenRouter API models:

```bash
./tradeloop/scripts/run_detached.sh premarket --backend opencode
```

In that mode, `41_pm_decision` uses `openai/gpt-5.5`, debate/trader/risk use
`openai/gpt-5.6-luna`, and OpenAI-limit failures fall back to
`openrouter/deepseek/deepseek-v4-flash-0731`.

The legacy `scripts/run_cycle.sh` entrypoint is the Codex/OpenRouter path only:

- `codex` (default): Codex CLI talks to OpenRouter directly (no daemon), using
  only the four models DeepSeek V4 Flash, MiMo-V2.5, MiniMax M3, Hy3 preview.

```bash
TRADELOOP_AGENT=codex  ./tradeloop/scripts/run_cycle.sh premarket
```

## Non-Negotiables

- Indian cash equities only.
- Long-only. `BUY` opens/adds long exposure; `SELL` only exits existing long
  exposure.
- No short selling, no F&O, no NRML, no leverage.
- CNC for swing/position trades; MIS only for long intraday management.
- `kill_switch.md` in this folder halts all orders.
- `ZERODHA_ENABLE_TRADING=false` is default and routes to paper.
- Live routing additionally requires the strategy-performance promotion gate.
- Codex and scripts must never read `.env` or print secret-like values.

## Readiness Boundary

The implemented target is a live-data, propose-only paper loop.
The scanner currently implements `breakout_20d_pullback` and `ema_trend_pullback`; the other configured families are marked planned.
Live trading remains blocked until the ledger, promotion metrics, clean audits, approval policy, and fresh broker reconciliation all pass.
The validation lab, point-in-time historical data, regime governor, and counterfactual overlay scoreboard described in `docs/vision.md` are not implemented yet.

## Runtime Model

Python does deterministic work: data fetch, ticker extraction, indicators,
sizing, cost model, portfolio state, broker payloads, and markdown memory
updates.
The selected backend does reasoning through file boundaries.
Each stage reads named inputs and writes one named output in
`runs/<timestamp>_<mode>/`.

## Cycles

- `premarket` at 08:00 IST: full pipeline and possible new long entries.
- `intraday` at 14:00 IST: holdings pulse; may propose exits and stop-tightens
  (never new entries), still stops at AWAITING_APPROVAL.
- `postclose` at 16:00 IST: holdings re-underwrite; analysis only, verdicts feed
  carry-forward for the next premarket, plus fills, P&L, dossiers, and learning.

## Manual Run

Always launch manual cycles detached so they survive the launching terminal or
agent session dying (cron-owned runs are already detached):

```bash
./tradeloop/scripts/run_detached.sh premarket --backend claude
```

If a cycle is interrupted anyway, resume it in place - stages with validated
artifacts are skipped, never re-billed:

```bash
./tradeloop/scripts/run_detached.sh postclose --backend claude tradeloop/runs/<dir>
```

Cron examples are in `scripts/crontab.txt`.
