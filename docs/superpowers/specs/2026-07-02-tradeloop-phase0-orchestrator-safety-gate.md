# Spec — TradeLoop Phase 0: Orchestrator skeleton + mandatory risk gate

**Date:** 2026-07-02
**Phase:** 0 of 5 (re-architecture). Gate-first.
**Status:** DRAFT — awaiting user review. No implementation until this spec is approved, then `writing-plans`.
**Depends on:** nothing. **Unblocks:** P1 (reasoning), P2 (ledger), P3 (data), P4 (controls).

---

## 1. Why this phase exists

TradeLoop has two hollow load-bearing pieces (the whole re-architecture exists to fill them):

1. Agents reason over **empty research files** — deferred to Phase 3.
2. The deterministic risk gate `lib/risk/checks.py::evaluate()` is **dead code** (zero callers); orders route on a kill-switch flag alone — **this phase**.

Phase 0 closes hole #2 and lays the Python orchestrator spine that Phases 1–4 attach to. It delivers **Definition-of-Done criterion #4**: *no order can bypass the rules — `evaluate()` runs on every order before routing, caps enforced in code, paper default, live behind the promotion gate.*

Phase 0 does **not** change how reasoning happens (still the existing external CLI backend) and does **not** add real data. Orders may still be produced from empty inputs; the point is that whatever the LLM proposes, **Python now gates and routes it**, and the control-flow gates (holiday / kill-switch / promotion) **actually halt** instead of being computed and ignored.

---

## 2. Current-state facts this phase corrects

Verified against the code (file:line):

- `scripts/run_cycle.sh:41` calls `verify_setup.py` but **ignores its exit code**; `SKIP` (holiday) and `HALTED` (kill-switch) both `return 0`, so the cycle proceeds anyway. Holiday/kill-switch gating is effectively dead.
- `lib/util/holidays.py:4` — `NSE_HOLIDAYS_2026 = set()` is **empty**, so `is_nse_holiday()` always returns `False` even if the exit code were honored.
- `lib/broker/router.py:24-38` `route_order()` gates on `kill_switch_active` + `live_enabled` + `live_promotion_ready` only — **never calls `evaluate()`**. Sizing/allocation/position-count/sector/deployment caps are not enforced anywhere in code.
- `lib/broker/router.py:71-77` `route_orders_file()` iterates `orders` as a **list**, but the real emitted `orders.json` is an **object** (`{mode, live_orders_enabled, run, generated_by, orders[], held[]}`). Iterating the dict yields keys → `ticket_from_order()` crashes. It also never hydrates positions and routes `held[]` items it should skip.
- `lib/broker/router.py` is **not invoked by any runtime path** — the external agent places orders via the Zerodha MCP directly. Phase 0 makes the Python order path the *only* router and forbids the agent from placing orders (the master prompt already declares this intent at `prompts/00_master_orchestrator.md:69-70`; only the code was missing).
- `router.py:52` re-hardcodes the promotion-gate thresholds that already exist in `config/settings.yaml:66-70` (`live_promotion_gates`) — drift risk.
- `pyproject.toml:26-28` packages only `src/tradingbot`; **`tradeloop` is not packaged** and `pandas`/`pyyaml` (used by `lib/ta/indicators.py`, `lib/portfolio/state.py`) are undeclared → `tradeloop` is unimportable on a clean install.
- `lib/portfolio/state.py:17-20` `empty_state_from_settings()` always returns an **empty book** — every cycle tells the agents "Positions: None" and any SELL is rejected because positions are unknown.

---

## 3. Scope

### In scope (Phase 0)
1. **Packaging** — package `tradeloop`; declare its runtime deps (`pyyaml`, `pandas`).
2. **Typed settings loader** — load `config/settings.yaml` once into a typed object; make it the single source for risk caps, costs, and promotion gates (kill the `router.py:52` / `cost_model.py` hardcoded duplicates).
3. **Python orchestrator** (`python -m tradeloop.orchestrator <mode>`) replacing `run_cycle.sh`'s control flow: real gate branching, lockfile, per-cycle timeout, run-dir scaffolding, a reasoning-backend step (unchanged), then the deterministic order path.
4. **Persisted paper book** — positions/avg-price/cash survive across cycles via an append-only fills file, replayed on load to hydrate the broker and the risk state.
5. **Mandatory risk gate in the order path** — `route_orders_file` parses the real `orders.json` object, validates it, builds `RiskState`+`RiskCaps` from the hydrated book + settings + universe, runs `evaluate()` on **every** order, routes only approved orders through the paper broker, and logs the gate's **own** verdict per order.
6. **Populate `NSE_HOLIDAYS_2026`** so the holiday halt is real.
7. **Prompt edit** — the agent writes `orders.json` and stops; it must not route orders or write `fills.json` (Python owns routing).
8. **Tests** — the risk gate rejects the four canonical violations; holiday and kill-switch halt the cycle; SELL works against a hydrated book; malformed `orders.json` is rejected loudly.

### Explicitly out of scope (later phases)
- Direct OpenRouter model calls / structured per-stage outputs → **P1**.
- SQLite hash-chained audit ledger; the paper book here is a flat file → **P2**.
- Real research data, Kite price/marks, news ingest, `news_id`, evidence trailer → **P3**.
- reconcile / control-testing / R-attribution / learning loop → **P4**.
- Live order submission through the MCP (paper is the Phase-0 default; the live branch stays as today, gated but not exercised).
- Retiring engine 1 (`src/tradingbot`), dropping `langgraph`, deleting engine-1 tests — a separate cleanup; Phase 0 only *adds* `tradeloop` to packaging and leaves engine 1 importable.
- Scheduler catch-up / moving premarket earlier / sentinel-vs-exact-minute cron — cron still triggers the orchestrator; only lockfile + timeout are added here.

---

## 4. Architecture & data flow

```
cron / manual
  └─ python -m tradeloop.orchestrator <mode> [--request ...]
       1. load Settings (typed, from config/settings.yaml)
       2. GATES (real branches — halt, do not proceed):
            is_nse_holiday(today)        -> SKIP  (exit 0)
            kill_switch_active(root)     -> HALT  (exit 0)
            live_enabled() and not live_promotion_ready() -> LIVE_NOT_READY (exit 2)
       3. acquire GLOBAL lockfile (one cycle at a time, across all modes — the
          book is shared state); start timeout watchdog (settings.cycle_timeout_seconds, default 1200)
       4. prepare_cycle.prepare(mode)  -> runs/<ts>_<mode>/ scaffold (unchanged)
       5. REASONING step (Phase-0 seam, unchanged backend):
            _run_reasoning(run_dir, mode)  -> external codex/claude CLI fills
                                              artifacts + writes orders.json
                                              (mirrors run_cycle.sh TRADELOOP_AGENT codex/claude
                                               selection; agent does NOT route / write fills)
       6. ORDER PATH (new, deterministic):
            book   = paper_book.hydrate(book_path, starting_cash)   # replay fills
            result = route_orders_file(run_dir/orders.json,
                                       run_dir/fills.json, book, settings, root)
              for each order in orders.json["orders"]:
                 ticket  = Order -> OrderTicket
                 verdict = evaluate(ticket, risk_state, risk_caps)   # MANDATORY
                 if verdict.approved: route_order(...) -> paper fill
                 else:                RoutedOrder("blocked","RISK_REJECTED",{reasons})
                 append verdict + outcome to run_dir/decisions.jsonl  # gate's own record
            paper_book.append(book_path, new_filled_fills)
       7. (postclose only) _run_reasoning post-trade step (unchanged)
       8. release lock; structured summary line to stdout + reports/
```

**Design boundaries (each a testable unit):**

- `tradeloop/lib/config.py` — *what:* load+validate settings into a `Settings` object and derive `RiskCaps`. *depends on:* `settings.yaml`. *used by:* orchestrator, order path.
- `tradeloop/lib/broker/paper_book.py` — *what:* persist/replay fills → hydrated `PaperBroker`. *depends on:* `paper_broker`, book file. *used by:* orchestrator.
- `tradeloop/lib/broker/orders_schema.py` — *what:* typed `Order`/`OrdersFile`, parse+validate the LLM's `orders.json`. *depends on:* pydantic. *used by:* order path.
- `tradeloop/lib/broker/router.py` (rewritten `route_orders_file`) — *what:* gate + route every order. *depends on:* `checks.evaluate`, `paper_broker`, config, orders_schema.
- `tradeloop/orchestrator.py` — *what:* the control flow above. *depends on:* all of the above + existing gate predicates + `prepare_cycle`.

The reasoning step is a single function `_run_reasoning(run_dir, mode)`; Phase 1 replaces its body with in-process OpenRouter calls without touching the order path.

---

## 5. Component contracts

### 5.1 `lib/config.py` (new)
```python
@dataclass(frozen=True)
class Settings:
    raw: dict                      # full parsed settings.yaml
    paper_starting_inr: float
    per_trade_risk_pct: float
    promotion_gates: dict          # min_paper_trades, min_win_rate, min_expectancy_r, max_drawdown_pct
    # ... plus typed accessors as needed

def load_settings(path: Path) -> Settings: ...

def risk_caps(settings: Settings, universe: Iterable[str], capital_inr: float) -> RiskCaps: ...
    # maps settings.capital.* -> RiskCaps fields (see 5.4)
```
`live_promotion_ready()` and `cost_model` constants are refactored to read from `Settings` instead of hardcoding.

### 5.2 `lib/broker/orders_schema.py` (new)
Typed model matching the **real** emitted object:
```python
class Order(BaseModel):
    ticker: str
    side: Literal["BUY","SELL"]
    product: Literal["CNC","MIS"] = "CNC"
    quantity: int
    price: float
    order_type: str = "LIMIT"
    hard_stop: float | None = None
    target_1: float | None = None
    target_2: float | None = None
    max_entry_price: float | None = None
    strategy_family: str | None = None
    status: str | None = None
    reason: str = ""

class OrdersFile(BaseModel):
    mode: str
    live_orders_enabled: bool = False
    run: str | None = None
    generated_by: str | None = None
    orders: list[Order] = []
    held: list[Order] = []           # approved-but-not-routed; Phase 0 does NOT route these

def load_orders(path: Path) -> OrdersFile        # raises on malformed -> cycle rejected loudly
def to_ticket(order: Order) -> OrderTicket
```
Backward-compat: a bare-array `orders.json` (legacy) parses as `OrdersFile(orders=[...])`.

### 5.3 `lib/broker/paper_book.py` (new)
```python
def hydrate(book_path: Path, starting_cash_inr: float) -> PaperBroker:
    # new PaperBroker(starting_cash); replay each historical FILLED fill via the
    # broker's own fill math so positions/avg_prices/cash/costs match reality.

def append(book_path: Path, fills: list[Fill]) -> None:
    # append only FILLED fills as JSON lines; append-only, never rewrites.
```
`// ponytail: flat JSONL book now; Phase 2 replaces it with the hash-chained SQLite event log (same hydrate/append interface).`

Book record carries `hard_stop` per fill so open-risk can be computed from held positions.

### 5.4 `RiskCaps` mapping (settings → gate)
`evaluate()` and `RiskCaps` already exist and are correct (`lib/risk/checks.py`). Phase 0 only *builds* the caps and *calls* it. Mapping:

| RiskCaps field | Source |
|---|---|
| `capital_inr` | hydrated equity = cash + Σ(qty × avg_price) *(book value; mark-to-market in P3)* |
| `max_open_positions` | `capital.max_concurrent_positions` (4) |
| `max_position_allocation_pct` | `capital.max_position_pct` (25) |
| `max_total_deployed_pct` | **new** `capital.max_total_deployed_pct` — add to settings, default **90** (tunable) |
| `max_sector_allocation_pct` | `capital.max_sector_exposure_pct` (40) |
| `max_daily_drawdown_pct` | `capital.daily_drawdown_circuit_pct` (3) |
| `max_open_risk_pct` | `capital.max_open_risk_pct` (4) |
| `min_position_size_inr` | `capital.min_position_size_inr` (15000) |
| `universe` | symbols from `ticker_master.load_ticker_master(config/universe.yaml)` |

`RiskState` is built from the hydrated book: `cash_inr`, `positions`, `avg_prices`, `sectors` (from `ticker_master`), `open_risk_inr` (Σ per-position `max(0, avg_price − hard_stop) × qty` from the book), `daily_pnl_inr` (realized-only from today's SELL fills; unrealized deferred to P3 marks).

**Settings additions (Phase 0):** `capital.max_total_deployed_pct` (default **90**, tunable) and top-level `cycle_timeout_seconds` (default **1200**).

### 5.5 `route_orders_file` (rewritten, `lib/broker/router.py`)
```python
def route_orders_file(orders_path, fills_path, book: PaperBroker,
                      settings: Settings, root=Path("tradeloop")) -> list[RoutedOrder]:
    of = load_orders(orders_path)                       # typed; raises if malformed
    tm = ticker_master.load_ticker_master(root/"config"/"universe.yaml")  # universe + sectors
    caps  = risk_caps(settings, tm.symbols(), equity(book))
    state = risk_state(book, tm)                         # positions/avg/sectors/open_risk/daily_pnl
    routed = []
    for order in of.orders:                             # held[] intentionally skipped
        ticket  = to_ticket(order)
        verdict = evaluate(ticket, state, caps)         # <-- the mandatory gate
        if not verdict.approved:
            routed.append(RoutedOrder("blocked","RISK_REJECTED",
                                      {"symbol": ticket.symbol, "reasons": verdict.reasons}))
        else:
            routed.append(route_order(ticket, book, root=root))  # paper place / live payload
        append_decision(orders_path.parent/"decisions.jsonl", order, verdict, routed[-1])
    fills_path.write_text(json.dumps([r.__dict__ for r in routed], indent=2, default=str))
    return routed
```
`route_order()` keeps its existing signature and callers (paper place / live payload); it does **not** need `evaluate()` inside it (the gate runs one level up so `route_order`'s existing test stays valid).

### 5.6 Existing gate predicates
`is_nse_holiday`, `kill_switch_active`, `live_promotion_ready` are reused **as real branches** by the orchestrator (not via ignored exit codes). `verify_setup.py` remains as a standalone preflight CLI. `NSE_HOLIDAYS_2026` is populated with the 2026 NSE trading-holiday dates.

---

## 6. Risk-gate coverage in Phase 0

`evaluate()` runs on every order. Of its checks:

**Fully enforced in P0** (computable from orders.json + hydrated book + settings + universe): `symbol_not_in_universe`, `unsupported_side`, `long_only_sell_exceeds_position`, `quantity_must_be_positive`, `price_must_be_positive`, `unsupported_product`, `below_min_position_size`, `max_position_allocation_exceeded`, `max_open_positions_exceeded`, `max_total_deployed_exceeded`, `max_sector_allocation_exceeded`, `max_open_risk_exceeded` (from persisted `hard_stop`).

**Best-effort in P0**: `daily_drawdown_circuit` uses realized daily PnL only; unrealized PnL needs live marks (Kite, P3). Documented, not hidden.

So 12 of 13 checks are hard-enforced immediately; the drawdown circuit reaches full enforcement when marks land in P3. DoD #4 ("evaluate() runs on every order, caps enforced in code") is met in Phase 0.

---

## 7. Error handling & failure modes

- **Malformed / unparseable `orders.json`** → `load_orders` raises → orchestrator aborts the order path, writes a loud `ORDERS_INVALID` marker to `fills.json` and the summary, exits non-zero. Never silently routes or writes empty fills.
- **Holiday / kill-switch / promotion-not-ready** → halt before reasoning; structured reason logged; exit code honored (0 for SKIP/HALT, 2 for LIVE_NOT_READY).
- **Lock contention** (a prior cycle still running) → refuse to start, log `LOCKED`, exit 0 (cron-safe; no stacking).
- **Per-cycle timeout** exceeded → terminate the reasoning subprocess, release lock, log `TIMEOUT`, exit non-zero. No order path runs on a timed-out reasoning step.
- **Reasoning backend failure** (CLI non-zero) → do not run the order path; log and exit non-zero.
- **Missing book file** → start from `paper_starting_inr` with an empty book (first run).
- **Every order gets a `decisions.jsonl` record** carrying the ticket, the gate verdict + reasons, and the routed outcome — the gate logs its own verdict, never the LLM's claim.

---

## 8. Persistence & state

- `tradeloop/state/paper_book.jsonl` — append-only FILLED fills (incl. `hard_stop`); replayed to hydrate. *(New `state/` dir; the flat-file precursor to P2's SQLite ledger.)*
- `runs/<ts>_<mode>/orders.json` — LLM-written, Python-validated (unchanged location).
- `runs/<ts>_<mode>/fills.json` — Python-written routing outcomes (now includes RISK_REJECTED entries).
- `runs/<ts>_<mode>/decisions.jsonl` — per-order gate verdict record (new).
- `tradeloop/reports/` — structured per-cycle summary line (folds in `run_cycle_logged.sh`'s logging intent).

---

## 9. Constraints preserved (non-negotiable)

- India cash equities, long-only (`BUY` opens/adds, `SELL` exits only), no shorts/F&O/NRML/leverage, CNC/MIS only — enforced by `evaluate()` + `paper_broker` + `to_zerodha_payload`.
- Paper default (`ZERODHA_ENABLE_TRADING=false`); live only past the promotion gate.
- `kill_switch.md` halts orders — now as a real branch.
- Security (AGENTS.md): the orchestrator never reads/prints `.env` beyond the existing sanctioned `OPENROUTER_API_KEY` sourcing for the reasoning subprocess; never logs secret-like values. Zerodha MCP stays project-local.

---

## 10. Testing (acceptance net; recorded fixtures, no live net)

Port `tradeloop/tests/test_paper_broker.py` + `test_sizing.py` (they pin long-only / paper-default / kill-switch / promotion-gate / sizing). Add:

1. **Gate rejects the four canonical violations** — non-universe symbol, oversized (> max position allocation), 5th concurrent position, `SELL > held` — each returns `RISK_REJECTED` with the right reason code and **no fill**, driven through `route_orders_file` with a hydrated book. *(Proves DoD success criterion "provable by a test, not by inspection.")*
2. **Holiday halt** — with a populated holiday date "today", the orchestrator halts before reasoning.
3. **Kill-switch halt** — `kill_switch.md` present → halt, no order path.
4. **Hydrated SELL works** — book with a prior BUY → a SELL within held qty is approved and fills.
5. **Malformed orders.json** — object with a bad field / non-JSON → cycle aborts loudly, no fills routed.
6. **orders.json object shape** — `{orders:[...], held:[...]}` routes `orders` and skips `held`; legacy bare array still parses.
7. **Promotion-gate thresholds come from settings** — changing `settings.yaml` moves the gate (guards against the `router.py:52` hardcode returning).
8. **Packaging** — `pip install -e .` then `import tradeloop.orchestrator` succeeds on a clean env.

The order path is independently invokable (`route_orders_file` / a `route(run_dir)` helper) so tests exercise the gate without the LLM.

---

## 11. Deferred shortcuts (ponytail ledger)

- Flat-file paper book → SQLite hash-chained ledger (P2), same interface.
- `daily_drawdown_circuit` realized-only → full with live marks (P3).
- Tradable universe = the 6 configured symbols → NIFTY500 / EQUITY_L loader (P3).
- Reasoning via external CLI subprocess → in-process OpenRouter calls (P1).
- cron exact-minute trigger kept (lock+timeout added) → catch-up/sentinel scheduler (later).
- `langgraph` drop + engine-1 retirement → separate cleanup once P1–P4 land.

---

## 12. Acceptance criteria (Phase 0 is done when)

1. `python -m tradeloop.orchestrator premarket` runs end-to-end: gates branch for real, reasoning runs, and **every** order in `orders.json` passes through `evaluate()` before any fill.
2. An order violating any hard cap (non-universe / oversized / 5th position / SELL>held) is **rejected by code**, with the rejection and reason in `fills.json` + `decisions.jsonl` — demonstrated by a passing test.
3. Positions persist across cycles; a SELL against a real held position fills; a fresh cycle no longer shows "Positions: None" when the book is non-empty.
4. Holiday and kill-switch **halt** the cycle (exit code honored); promotion gate blocks live.
5. `tradeloop` installs and imports on a clean environment; risk caps, costs, and promotion thresholds are read from `settings.yaml` (no hardcoded duplicates).
6. Full test suite green.

---

## 13. Next

On approval → `writing-plans` to produce the step-by-step implementation plan for this spec. Phases 1–4 get their own spec → plan → build cycles.
