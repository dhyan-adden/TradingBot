# Handoff — TradeLoop re-architecture: architecture + all-phase plans done

**Date:** 2026-07-02
**Status:** Design + planning COMPLETE. Architecture doc + Phase 0 spec + all 5 phase implementation plans are written, consistency-reviewed, and fixed. **Next = user reviews the plans, then execute (subagent-driven, P0 first).** No code written yet.
**Supersedes:** `docs/handoff-2026-07-01-tradeloop-data-accountability.md` (that one assumed "harden in place"; we since pivoted to a full re-architecture).

---

## What this project is (one paragraph)

Re-architect **tradeloop** (engine 2 — the 13-agent loop) from a system that runs on empty research with a switched-off risk gate into one that runs on real, auditable data and **cannot route an order that breaks the rules**. India-only, long-only, swing-first cash equities. Paper by default; live only after an earned promotion gate. AIM: eventually trade real money profitably — but trust the inputs and enforce the rules first. **tradeloop only** — `src/tradingbot` (engine 1, LangGraph) is out of scope, reference-only for proven patterns.

## The two holes being fixed
1. Agents reason over EMPTY files (`tradeloop/scripts/prepare_cycle.py:43-44` renders blank news + setups).
2. The risk gate `tradeloop/lib/risk/checks.py::evaluate()` is DEAD CODE (zero callers); orders route on a kill-switch flag alone.

## Definition of done (all four)
1. Real inputs — 4 news sources + Kite price, deduped/ticker-tagged/frozen snapshot, loud "NO NEWS DATA" never silent blank.
2. Every fetch logged (success + failure) to an append-only ledger.
3. Every decision accountable — `evidence:[news_id]` validated against the cycle snapshot; model/response recorded (input-reproducibility).
4. No order bypasses the rules — `evaluate()` on every order, paper default, live behind the promotion gate.

## Locked decisions (do not re-litigate)
- **LLM backend:** OpenRouter multi-model, per-stage tiers (Python calls the model directly, replacing the external CLI). Real model IDs pinned in the P1 plan (`anthropic/claude-{haiku,sonnet,opus}-4.5`, `deepseek/deepseek-3.2`) — the ones in `model_routing.md` were fake.
- **Audit + state:** append-only, hash-chained SQLite event log + markdown projections; positions/P&L by replay.
- **Market data:** Kite MCP (price/OHLC/historical), drop yfinance. Needs a `historical`/`instrument_token` tool added to `src/mcp/zerodha.ts` (no candles endpoint today); Python speaks MCP-stdio to it.
- Earlier-locked: all 4 news sources; finance = reconcile + control-testing + R-attribution (no double-entry); bounded scan + max_fetch; input-reproducibility only; fenced-JSON evidence trailer; safety-first phasing.

---

## Deliverables (all in the repo)

- **Architecture (plain English + the shared contract):** `docs/tradeloop-architecture.md` — component roles by analogy, end-to-end cycle, module layout (§5), pinned interfaces (§6). §6 is the contract all phases build against.
- **Phase 0 spec:** `docs/superpowers/specs/2026-07-02-tradeloop-phase0-orchestrator-safety-gate.md`.
- **All 5 implementation plans** (TDD, exact paths + complete code per step) in `docs/superpowers/plans/`:
  - `2026-07-02-tradeloop-phase0-orchestrator-safety-gate.md` — 12 tasks
  - `2026-07-02-tradeloop-phase1-reasoning-layer.md` — 6 tasks
  - `2026-07-02-tradeloop-phase2-audit-ledger.md` — 8 tasks
  - `2026-07-02-tradeloop-phase3-data-backbone.md` — 14 tasks
  - `2026-07-02-tradeloop-phase4-finance-controls.md` — 10 tasks

## The 5 phases (safety-first build order; each ships + tests independently)
| Phase | Delivers | DoD |
|---|---|---|
| **P0** orchestrator + safety gate | Python orchestrator (gates as real halts, global lock, timeout); wire `evaluate()` into the order path; persisted paper book (positions survive cycles, SELL works); typed `orders.json`; packaging fix (package tradeloop, declare pyyaml+pandas). Reasoning/data unchanged (empty) — the point is Python now gates+routes. | #4 |
| **P1** reasoning layer | `tradeloop/lib/llm/{client,routing,stages,schemas}.py`; per-stage OpenRouter calls with pydantic-validated outputs; record model/response/usage. Replaces P0's `_run_reasoning` body. | #3 (half) |
| **P2** audit ledger | `tradeloop/lib/audit/ledger.py` — append-only hash-chained SQLite; `project_positions()` replaces P0 book's hydrate body; markdown projections; log fetch/model/verdict/fill. | #2 |
| **P3** data backbone | `data/{http,kite,tickers,sentiment,snapshot,ingest,evidence}.py` + `sources/*`; Kite price; 4 news sources hardened; word-boundary ticker match; frozen snapshot + `news_id`; evidence validated vs snapshot; wire `prepare_cycle.py:43-44`; fix scanner. Adds the MCP `historical` tool. | #1, #3 (half) |
| **P4** finance controls | `audit/{reconcile,controls,attribution}.py`; postclose learning loop with provenance; health surface. Wired into orchestrator postclose (Task 11). | polish |
DoD met when P3 lands; P4 is the accountability layer on top.

## Consistency review (done)
A cross-phase reviewer checked all 5 plans against §6. Found + FIXED (verified): (1) blocker — fill event name drift, P4 now uses P2's `ORDER_FILLED`/`paper.order.filled`; (2) blocker — `_run_reasoning` is now `(run_dir, mode, agent, timeout, client=None)` preserving P0's call site + cycle timeout; (3) major — P2 test uses list access `[0].symbol` not P3-only `.symbols()`; (4) minor — `controls.recheck` object-signature reconciled into §6; (5) minor — P4 Task 11 wires the auditor into orchestrator postclose. Plans interlock; DoD complete; no placeholder/format violations.

## Open items to confirm BEFORE executing a phase
- **P1:** verify the OpenRouter model slugs against the live `/models` endpoint (they change).
- **P0:** confirm the official NSE 2026 holiday list (plan populated a best-known set).
- **P3:** the new `historical`/`instrument_token` tool on `src/mcp/zerodha.ts` + MCP-stdio-from-Python transport is the one new integration — review it.
- **P1–P4 did NOT get their own specs** — the plans double as spec+plan. Confirm each plan's design decisions (see its "warnings"/"key decisions") before executing that phase. P0 has a full spec and is the most execution-ready.

---

## Immediate next step
1. User reviews the plans (start with P0).
2. Execute — **subagent-driven** (`superpowers:subagent-driven-development`): fresh agent per task, P0 first, review between tasks. (Alt: `superpowers:executing-plans` inline with checkpoints.)
3. Repo is NOT git — run `git init` first to version-control the docs/specs/plans and land each phase on a branch (account https://github.com/Dhyan-21041).

## Constraints (must remain in effect)
- India cash equities, long-only (BUY opens/adds, SELL exits only), no shorts/F&O/NRML/leverage, CNC/MIS only, `kill_switch.md` halts orders, paper default (`ZERODHA_ENABLE_TRADING=false`), live requires the promotion gate (≥40 paper trades, ≥45% win, ≥0.3 R, ≤8% drawdown).
- Security (AGENTS.md): never read/print/grep/cat `.env`; never print env values whose names include KEY/SECRET/TOKEN/PASSWORD/AUTH/CREDENTIAL; Zerodha MCP stays project-local (`src/mcp/zerodha.ts`, `bin/codex-zerodha`).

## Pointers
- Auto-memory project file: `tradeloop-data-accountability-design` (updated to this state).
- Interactive diagrams were shown this session (architecture views + paper-vs-live step-through) — not saved to repo; the same content is in `docs/tradeloop-architecture.md`.
- The full module keep/wire/rewrite/delete map was a workflow artifact (session tmp, likely gone) — its verdicts are baked into the plans + architecture doc, so it is not needed to resume.
