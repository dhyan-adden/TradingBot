# Handoff — tradeloop data-layer + accountability enhancement

**Date:** 2026-07-01
**Phase:** superpowers:brainstorming — design approved through Part 3, spec NOT yet written.
**HARD-GATE:** No code, no implementation skill until the spec is written, self-reviewed, and user-approved. The only skill allowed after brainstorming is `writing-plans`.

---

## End goal (why this project exists)

Make **tradeloop** (engine 2 — the 13-stage markdown-prompt agent loop) into a trading system that can be trusted with real money: India-only, long-only, swing-first cash equities (swing now, algo intraday later, never F&O). The engine already has the shape (13 agents, cron cycles, broker router, paper/live promotion gate). Two things make it real:

1. **Robust research/data** — today the 13 agents reason over EMPTY files. Fix: Google News RSS (hardened) + native Indian RSS + NSE/BSE announcements + Reddit, deduped, correctly ticker-tagged, deterministically scored, frozen into a per-cycle snapshot the agents actually read.
2. **Accountability + safety** — every fetch logged (success AND failure), every agent decision logged with WHY + the evidence it saw, input-reproducible, and a MANDATORY deterministic Python risk gate that enforces caps in code before any order routes.

Through-line: **inputs real and auditable; outputs cannot bypass the rules.** Paper by default; live only through the earned promotion gate.

---

## Locked decisions (do not re-litigate)

- **Target engine:** tradeloop only (not src/tradingbot, no shared layer).
- **Sources:** all four — Google News RSS (harden), native Indian RSS (Moneycontrol/ET/Mint/Business Standard), NSE/BSE official announcements, Reddit/social.
- **Architecture:** Approach B — adapter registry + frozen snapshot + JSONL audit ledger; file-first, sequential+throttled fetch.
- **Finance additions:** reconciliation, SOX-style control-testing, variance/R attribution. NOT double-entry bookkeeping.
- **Risk gate:** mandatory deterministic Python gate — wire `checks.evaluate()` into the order path.
- **Scan scope:** pre-filter to a few dozen symbols + `max_fetch` cap (no full-universe fetch).
- **Reproducibility:** input-reproducibility only (freeze + hash inputs; record model_version/response_id/prompt/response). Drop bit-identical LLM replay claims.
- **Evidence:** required fenced-JSON trailer on decision prompts carrying `evidence:[news_id]`.

---

## Architecture (Approach B)

Source adapters → shared `lib/data/http.py` (retry/backoff/jitter, per-request timeout, conditional GET via ETag/If-Modified-Since, cookie-warmup session for NSE/BSE) → `lib/data/ingest.py` (sequential+throttled orchestrator) → frozen snapshot `runs/<ts>/data/*.jsonl` → render `01_news_raw.md` / `02_setups_raw.md` → agents. `lib/audit/ledger.py` = append-only JSONL (fetch + decision events).

**Resilience:** persistent sqlite seen-set dedup (key guid→url_hash→title_hash, cross-source+cross-cycle); word-boundary ticker matching (alias/ISIN table from NSE EQUITY_L.csv, rapidfuzz fallback ≥92); deterministic sentiment (FinVADER); tier quorum enforced in code (attention_only flag for Tier-C-only).

**New modules to create:** `lib/audit/{ledger,reconcile,controls,attribution}.py`, `lib/data/{http,ingest,dedup,tickers,sentiment,snapshot}.py`, `lib/data/sources/{base,google_news,rss_native,nse_bse,reddit}.py`.

**New deps:** feedparser, finvader, rapidfuzz (optional). sqlite3 stdlib; HTTP on stdlib urllib/http.cookiejar.

---

## Blockers (B) and majors (M) — all folded into the design as non-negotiable

| ID | Where | Issue / fix |
|----|-------|-------------|
| B1/B2/F2 | `lib/broker/router.py` `route_order` (:24-38), `route_orders_file` (:71-77) | Order path checks only kill_switch + promotion. Insert `checks.evaluate()` before routing; hydrate positions. Also fix dict-vs-list orders.json at :72-75 → `orders = data["orders"] if isinstance(data, dict) else data`. |
| B2 | `lib/broker/paper_broker.py:67` | SELL check fails — cron passes fresh `PaperBroker(100000)` with empty positions. Hydrate real positions. |
| — | `lib/risk/checks.py:37` `evaluate()` | DEAD CODE (zero callers). Wire it in — this is the whole safety gate (RiskCaps/RiskState/RiskDecision: universe/position-count/25%/40%/open-risk/drawdown/SELL≤held). |
| B3 | `scripts/prepare_cycle.py:43-44` | THE seam. `render_news_raw(NewsExtraction())` + `render_setups([])` render EMPTY. Wire real ingest/scan behind these renderers (agent contracts unchanged). |
| B4 | `lib/data/news_to_tickers.py:46` | Naive substring `alias in title_upper`. Fix: `re.search(rf'\b{re.escape(alias)}\b', title_upper)`, skip aliases <3 chars, index symbol+curated aliases only. Interface: `extract_tickers(items, records, source_tiers)` at :36. |
| B5 | `lib/data/google_news_rss.py` `NewsItem` (:10-17) | No id/guid/hash. Mint `news_id = sha256(guid|url|title)[:12]` at ingest. |
| M1 | `lib/ta/scanner.py:57-67` | `scan_universe` fetches EVERY symbol then slices `[:limit]`. Bound BEFORE fetch. Kill silent `except: continue` (:62). ATR fallback (:33) fabricates stops at latest*0.02 — flag. |
| M2 | `lib/data/google_news_rss.py:19-40` | No UA/retry/backoff/timeout. Route through `http.py`. Stores Google encrypted redirect as url — resolve lazily. |
| M3 | `scripts/cron_dispatch.sh:13` | Premarket fires exact 0800 slot, no lock/timeout/catch-up. Move fetch/scan earlier (~0730), add lockfile + per-cycle timeout + sentinel (not exact-minute). |
| M6 | `pyproject.toml` | Points packages at nonexistent src/tradingbot; tradeloop missing from packages.find; deps undeclared. Fix packaging + declare deps. |
| M7 | `config/universe.yaml` | Only 6 symbols; no NIFTY500 loader. Add EQUITY_L.csv loader (used as filter source for bounded scan). |
| M8 | `config/settings.yaml` | Capital/universe loader wiring. |
| F4 | prompts `30_trader`/`40_risk_manager`/`41_portfolio_manager` + `shared/output_schemas.md` | Agents emit free-text; only orders.json is JSON, no evidence[]. Add required fenced-JSON trailer + deterministic parser that rejects the cycle if any news_id ∉ that cycle's news.jsonl. |

---

## Accountability mechanics

- **news_id** minted at ingest; rendered inline in 01_news_raw.md + frozen in news.jsonl.
- **Evidence trailer** on decision stages (30/40/41): `{decision, orders, evidence:[news_id], rationale}`; deterministic parser validates every news_id against the cycle snapshot.
- **Risk gate is source of truth** — route_orders_file logs its OWN evaluate() verdict, not the LLM's claim.
- **controls.py** tests OUTCOMES: independently re-runs evaluate() over orders.json/fills.json vs caps; asserts long-only/kill-switch/universe/caps held; classifies deficiencies.
- **reconcile.py** derives positions two INDEPENDENT ways (replay fills.json vs orders.json intents-minus-rejects; + Kite holdings when live); flags deltas.
- **attribution.py:** expected_R (from trade-plan trailer) vs realized_R (from fills) → strategy_performance.md.
- **Reproducibility:** freeze raw source bytes so snapshot_hash is stable; pin as-of instant per cycle (daily close for postclose); preserve original fetched_at on 304 (add revalidated_at); record model_version/response_id/prompt/response per decision (temp=0 set, not advertised as bit-deterministic).
- **Observability:** per-source last-success timestamp; verify_setup.py dep-import + source-health check (fail loud at deploy). Degrade-not-abort; all-news-failed → loud "NO NEWS DATA" artifact, never silent empty.

---

## Rollout (safety first — each phase ships + tests independently)

- **Phase 0 — Safety wiring (no new data):** wire evaluate() gate into route_orders_file, hydrate positions, fix SELL, pin orders.json schema, declare deps + fix packaging, add NIFTY500/EQUITY_L loader + capital/universe loader. Makes the order path safe BEFORE data flows.
- **Phase 1 — Audit spine:** ledger.py (per-stage files, orchestrator merges), news_id minting, evidence trailer in prompts 30/40/41 + parser + validation.
- **Phase 2 — Ingest core:** http.py, hardened Google News (feedparser/UA/retry/lazy link resolve/dedup), tickers.py, FinVADER, snapshot freeze, bounded scan, wire prepare_cycle.py behind a flag.
- **Phase 3 — Breadth:** native RSS (MC/ET/Mint/BS) + code-enforced tier quorum, NSE/BSE cookie-warmup source, Reddit tier-C.
- **Phase 4 — Finance controls:** controls.py, reconcile.py, attribution.py, health surface.

**Testing:** recorded fixtures, no live net — risk gate (non-universe/oversized/5th-position/SELL>held all rejected), evidence-trailer parse + news_id existence, ticker word-boundary ("Bajaj Finserv profit"→no ticker, "profIT"→no IT), sentiment determinism, http retry/304, dedup keying, ingest end-to-end → byte-stable snapshot+markdown.

---

## Immediate next step

1. Write the spec to `docs/superpowers/specs/2026-07-01-tradeloop-data-accountability-design.md`.
2. Spec self-review (placeholder / consistency / scope / ambiguity scan).
3. Ask user to review the spec file.
4. On approval → invoke `writing-plans` skill (ONLY next skill).

Note: repo is NOT a git repo (`git init` needed if version control wanted) — spec can be written but not committed until then.

---

## Constraints (must remain in effect)

Security (from AGENTS.md): never read/print/grep/cat `.env`; never print env values whose names include KEY/SECRET/TOKEN/PASSWORD/AUTH/CREDENTIAL; no shell that echoes process.env/.env; verify credentials only via masked/status commands; Zerodha MCP stays project-local (`./bin/codex-zerodha`, not `~/.codex/config.toml`).

Non-negotiables: India cash equities, long-only (BUY opens/adds, SELL exits only), no shorts/F&O/leverage, CNC/MIS only, kill_switch.md halts orders, paper default (ZERODHA_ENABLE_TRADING=false), live requires promotion gate (≥40 paper trades, ≥45% win, ≥0.3 R expectancy, ≤8% drawdown).

**Full prior transcript:** `/Users/dhyanpatel/.claude/projects/-Volumes-D-DRIVE-TradingBot/421d4741-83cf-442a-b37f-a0f2aca38f77.jsonl`
