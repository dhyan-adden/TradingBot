# TradeLoop Handoff - 2026-07-04 (post live smoke)

Resume point for a fresh chat.
Supersedes `docs/handoff-2026-07-01-tradeloop-data-accountability.md` (stale).
The running project memory is `~/.claude/projects/-Volumes-D-DRIVE-TradingBot/memory/tradeloop-data-accountability-design.md` (auto-loaded each session) - this doc is the short, actionable version.

## One-line state

The 13-agent Indian-equity swing-trading loop (engine 2, `tradeloop/`) runs a full cycle end to end on live data with enforced evidence accountability.
P0-P3 plus the live-smoke fixes are all merged to `main`.
It proposes 0 orders for exactly one reason: the Kite candle scan is dormant, so the trader has no price data to size entries.
The system has never completed a paper trade end to end.

## Git state

- Branch: `main`, HEAD `23baa41`.
- 19 commits ahead of `origin/main` - nothing is pushed (deliberate; push only when asked).
- Suite: `152 passed` under `-W error`.
- Untracked runtime output only: `tradeloop/runs/*` and `tradeloop/state/` (smoke artifacts; consider gitignoring - minor hygiene, not urgent).
- Python interp for everything: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python`.
- Run pytest from repo root: `.../python -m pytest tradeloop/tests -q -W error`.

## What is proven working (live, this session)

- Live news ingest -> word-boundary ticker tagging -> frozen hashed snapshot (per-cycle `news_id`s) -> renders `01_news_raw.md`.
  ET Markets + Google News + NSE/BSE feeds returned real data; Moneycontrol + Reddit degraded to `[]` (UA block / moved feed) without crashing.
- Full in-process OpenRouter DAG: 11 premarket stages, all 4 leaderboard models return schema-valid JSON on real payloads (deepseek-v4-flash, minimax-m3, hy3-preview, mimo-v2.5).
- Retry/validation resilience: a malformed model response recovered on retry.
- Evidence gate enforced: `10_news` cited 5/5 real snapshot ids; the gate was observed to BLOCK fabricated ids (`EVIDENCE_INVALID`) and PASS genuine ones (`AWAITING_APPROVAL`).
- Propose/approve split intact: `run_cycle` stops at `AWAITING_APPROVAL`; nothing routes.

## The bug the smoke caught (and the lesson)

All 150 hermetic tests were green, yet live the reasoning was producing hollow output.
`StageFakeClient` bypasses the real client and prompt, so the tests never exercised the real model contract.
Root cause: the pydantic schema was never shown to the model, so models invented prose JSON keys and pydantic `extra="ignore"` silently defaulted every field.
Fixes (commits `915a02d` + merge `23baa41`):
1. `client.py` - inject `schema.model_json_schema()` into each call + instruct copying `[news_id]` tokens into `evidence`.
2. `schemas.py` `EvidenceMixin` - a `field_validator` keeps only 12-hex `news_id`s (drops prose; keeps a fabricated-but-well-formed id so the gate can still catch it).
Two guard tests added (schema-reaches-model regression; evidence-filter).
Lesson: a live smoke as close to production as possible is non-negotiable; hermetic green means little on its own.

## How to run a live cycle (exact)

Prereq - the OpenRouter key must reach the Bash-tool subprocess, which is non-interactive and sources `~/.zshenv` only (NOT `.zshrc`, NOT an interactive `export`, NOT `.env`).
So the key must be a line in `~/.zshenv`: `export OPENROUTER_API_KEY=sk-or-v1-<real key>`.
Gotcha from this session: a literal `export OPENROUTER_API_KEY=...` placeholder was once pasted verbatim, setting a 3-char key -> 401. Verify with `echo ${#OPENROUTER_API_KEY}` = ~73.

Today's date logic: `is_nse_holiday` treats weekends as holidays, so `run_cycle` SKIPs on Sat/Sun.
The smoke runner pins `orchestrator._today` to a Wednesday (2026-07-01) so the gate passes.

Runner (propose-only, routes nothing):
`/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python /private/tmp/claude-501/-Volumes-D-DRIVE-TradingBot/97b8d4c9-1253-49c6-ae16-c1d9f8649053/scratchpad/smoke_reason.py`
Note: that scratchpad path is session-specific and may be gone in a new session; the script is ~20 lines (pin `_today`, call `run_cycle("premarket", root=ROOT, backend="openrouter")`, summarize the newest run_dir). Re-create it if missing.
Cost: ~35k tokens per cycle.

## What's left

To actually trade on paper (the real goal, in order):
1. Activate live Kite scan - the only reason it proposes 0 orders.
   Pass `kite_client=KiteClient()` in `prepare_cycle.prepare` (currently omitted; see the `# ponytail:` comment there marking it dormant), and run a Kite-auth login smoke (`npm run -s mcp:zerodha` needs a valid Kite session).
   Then `02_setups_raw.md` fills and the trader can size entries.
2. Smoke the approval half - `route_cycle(run_dir)` has never run live. It is the money path: risk gate -> paper fill -> hash-chained ledger write -> position.
3. One real end-to-end paper trade - propose (with Kite) -> review (`/review-trade` skill exists) -> approve -> fill -> confirm it lands in `state/ledger.db` and survives to the next cycle's hydrate.

Beyond-DoD:
- P4 (finance controls) - reconcile positions 3 ways, re-run the risk gate over actual fills (SOX-style), expected-vs-realized R attribution, provenanced learning loop into `strategy_performance.md`, health check.
  Plan: `docs/superpowers/plans/2026-07-02-tradeloop-phase4-finance-controls.md` (11 tasks).
  Predates option-D/P2/P3 - RE-VERIFY the plan against current code before building (this pattern has caught real drift every phase).
  Premature until real fills exist (steps 1-3), since it audits/learns from trades that have not happened.

Follow-ups / hygiene:
- Chained-ledger fetch + model-call logging (fetches live in the snapshot, model calls in `llm_calls.jsonl`; neither is in the P2 hash chain).
- Fix Moneycontrol / Reddit sources (returning 0 live).
- Only premarket, weekday-pinned, 6-symbol universe tested live; intraday/postclose/adhoc modes unrun live.
- Push `main` to origin (19 commits local).

## Recommended next step

Start with #1 (activate Kite), because #2 and #3 are blocked on it and it is the shortest path to the system's actual purpose.
Before wiring: confirm Kite auth works (`mcp:zerodha` login), decide paper-safe posture (Kite reads are read-only), and re-verify the `prepare_cycle` wiring keeps tests hermetic (the adhoc tests must not go live - same trap as P3 Task 13).

## Constraints to carry (non-negotiable)

- India cash equities, long-only (BUY opens/adds, SELL exits only), CNC/MIS, no shorts/F&O/leverage.
- Paper by default; live only past the promotion gate. `kill_switch.md` halts orders.
- No-bypass invariant: only the gated `route_order` (router.py) calls `place_order` - re-grep after any broker-adjacent change.
- Secrets: never read/print/grep `.env`; only sanctioned read is `OPENROUTER_API_KEY` via `os.getenv`, never echoed.
- Never use the em dash; no agent name as commit co-author; re-verify each phase plan against code before building.
- Testing standard: planned tests covering normal/edge/failure, every money-path guard branch, e2e as close to production as possible - not green-count padding.
- Execution model: Sonnet subagents implement, Opus/Fable orchestrates and reviews inline; state scale before fan-out (credit-sensitive).

## Key pointers

- Orchestrator (split cycle): `tradeloop/orchestrator.py` (`run_cycle` propose, `route_cycle` approve, evidence gate at ~line 178).
- Reasoning DAG + prompts: `tradeloop/lib/llm/{stages,client,schemas,routing}.py`, `tradeloop/prompts/`.
- Data backbone (P3): `tradeloop/lib/data/` (`ingest`, `snapshot`, `sources/`, `tickers`, `kite`, `evidence`, `http`).
- Ledger (P2): `tradeloop/lib/audit/ledger.py`.
- Review skill: `.claude/skills/review-trade/SKILL.md`.
- Plans: `docs/superpowers/plans/2026-07-02-tradeloop-phase{0..4}-*.md` (P3 plan carries the VERIFICATION block pattern near the top).
