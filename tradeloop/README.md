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
- `intraday` at 12:30 IST: manage-only; no new entries at current capital.
- `postclose` at 16:00 IST: no trading; fills, P&L, dossiers, and learning.

## Manual Run

```bash
./tradeloop/scripts/verify_setup.py --mode premarket
./tradeloop/scripts/run_cycle.sh premarket
```

Cron examples are in `scripts/crontab.txt`.
