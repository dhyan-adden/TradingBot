# TradeLoop

TradeLoop is an agent-driven, India-only, news-discovery-first trading loop.
There is no LangGraph runtime or direct LLM API integration in Python. Cron
invokes `scripts/run_cycle.sh <mode>`, which launches a coding-agent CLI against
the master markdown orchestrator.

## Reasoning agent

Pick the agent with `TRADELOOP_AGENT`:

- `codex` (default): Codex CLI talks to OpenRouter directly (no daemon), using
  only the four models DeepSeek V4 Flash, MiMo-V2.5, MiniMax M3, Hy3 preview.
- `claude`: native Claude Code (your Claude auth/models, no OpenRouter). The
  master orchestrator dispatches each TradeLoop team as a Claude Code subagent.
  Optional model override via `TRADELOOP_CLAUDE_MODEL`.

```bash
TRADELOOP_AGENT=codex  ./tradeloop/scripts/run_cycle.sh premarket
TRADELOOP_AGENT=claude ./tradeloop/scripts/run_cycle.sh premarket
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

## Runtime Model

Python does deterministic work: data fetch, ticker extraction, indicators,
sizing, cost model, portfolio state, broker payloads, and markdown memory
updates. Codex does reasoning through file boundaries. Each agent reads named
inputs and writes one named output in `runs/<timestamp>_<mode>/`.

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
