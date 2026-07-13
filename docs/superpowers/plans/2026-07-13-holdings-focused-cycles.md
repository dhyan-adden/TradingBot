# Holdings-Focused Intraday/Postclose Cycles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repurpose the non-order cycle modes (intraday, postclose) from new-stock discovery into holdings review: per-position HOLD/ADD/TIGHTEN_STOP/TRIM/EXIT verdicts, a real intraday exit path, deterministic stop enforcement, and carry-forward wiring into the next session.

**Architecture:** Non-order modes get their own short DAGs ending in a new `15_holdings_review` stage (intraday: 10, 13, 15; postclose: 10, 11, 12, 13, 15).
Python, not the LLM, derives SELL orders (intraday only) and stop updates from the validated review, enforces recorded stops deterministically, and writes the review into `memory/carry_forward_context.md` between auto-markers.
Stops become mutable via a new hash-chained ledger event `paper.stop.updated`, applied tighten-only at route time.
Premarket/adhoc are untouched.

**Tech Stack:** Python 3.11 (conda env `tradingbot`), pydantic, sqlite ledger, pytest.

## Global Constraints

- Test runner: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest` (the repo `.venv` is a broken 3.9 - never use it).
- Full suite must be green before every commit: `cd /Volumes/D-DRIVE/TradingBot && /Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests -q`.
- Commit messages: repo style `feat(scope): ...` / `fix(scope): ...` / `test(scope): ...`. NEVER add a Co-Authored-By line (user rule).
- No em dash in any file; use plain dash.
- Mode policy invariants that must survive: postclose fills NOTHING (`_MODE_ALLOWED_SIDES["postclose"] == set()`); intraday allows SELL only; stop updates may only tighten (new stop strictly greater than the recorded one) and only for held symbols.
- Money-path branches all need tests (user testing standard); non-money rendering can be lighter.
- All work on branch `feat/holdings-focused-cycles` (created in Task 1).

---

### Task 1: Preflight - suite green, commit pre-existing work, branch

The working tree carries uncommitted, already-live-validated changes from 2026-07-13 (adhoc-intake hollow-run fix, dashboard, evidence) plus today's run archives and `run_detached.sh`.
They must land as their own commits BEFORE feature work so this feature's diff stays reviewable.

**Files:**
- No source changes; git only.

- [ ] **Step 1: Run the full suite on the current tree**

Run: `cd /Volumes/D-DRIVE/TradingBot && /Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests -q`
Expected: all pass (suite was 264+ green at last commit; the tree's pending changes shipped with their tests).
If anything fails: STOP and report to the user before committing anything.

- [ ] **Step 2: Commit the pre-existing work as two commits on main**

```bash
cd /Volumes/D-DRIVE/TradingBot
git add tradeloop/dashboard/ tradeloop/lib/data/evidence.py tradeloop/lib/llm/schemas.py \
  tradeloop/orchestrator.py tradeloop/prompts/05_adhoc_intake.md tradeloop/prompts/22_debate_moderator.md \
  tradeloop/tests/ tradeloop/scripts/run_detached.sh
git commit -m "fix(adhoc): constrain intake required_stages to real DAG artifacts; dashboard + evidence follow-ups"
git add tradeloop/runs/2026-07-13_1029_premarket tradeloop/runs/2026-07-13_1246_adhoc \
  tradeloop/runs/2026-07-13_1330_adhoc tradeloop/runs/2026-07-13_1739_postclose tradeloop/reports/source_health.json
git commit -m "test(runs): archive 2026-07-13 premarket/adhoc/postclose runs"
```

- [ ] **Step 3: Create the feature branch**

```bash
git checkout -b feat/holdings-focused-cycles
```

---

### Task 2: HoldingsReview schema

**Files:**
- Modify: `tradeloop/lib/llm/schemas.py`
- Test: `tradeloop/tests/test_llm_schemas.py`

**Interfaces:**
- Produces: `HoldingVerdict` (fields: `ticker: str`, `verdict: Literal["HOLD","ADD","TIGHTEN_STOP","TRIM","EXIT"]`, `conviction: float 0-10`, `reason_code: Literal["stop_breach","tripwire","thesis_break","event_risk","profit_protect","thesis_intact","thesis_strengthened"]`, `rationale: str`, `new_stop: float|None`, `exit_quantity: int|None`) and `HoldingsReview` (`reviews: list[HoldingVerdict]`, `carry_forward: str`), both `EvidenceMixin` subclasses, registered as `SCHEMA_FOR_STAGE["15_holdings_review"]`.

- [ ] **Step 1: Write the failing tests**

Append to `tradeloop/tests/test_llm_schemas.py`:

```python
import pytest
from pydantic import ValidationError

from tradeloop.lib.llm.schemas import SCHEMA_FOR_STAGE, HoldingsReview, HoldingVerdict


def test_holdings_review_registered_for_stage():
    assert SCHEMA_FOR_STAGE["15_holdings_review"] is HoldingsReview


def test_holding_verdict_happy_paths():
    hold = HoldingVerdict(ticker="CDSL", verdict="HOLD", conviction=6.0,
                          reason_code="thesis_intact", rationale="breakout intact")
    assert hold.new_stop is None
    tighten = HoldingVerdict(ticker="HDFCBANK", verdict="TIGHTEN_STOP", conviction=5.0,
                             reason_code="profit_protect", rationale="lock gain", new_stop=820.0)
    assert tighten.new_stop == 820.0
    trim = HoldingVerdict(ticker="SBIN", verdict="TRIM", conviction=3.0,
                          reason_code="event_risk", rationale="derisk", exit_quantity=10)
    assert trim.exit_quantity == 10


def test_tighten_stop_requires_new_stop():
    with pytest.raises(ValidationError):
        HoldingVerdict(ticker="HDFCBANK", verdict="TIGHTEN_STOP", conviction=5.0,
                       reason_code="profit_protect", rationale="lock gain")


def test_trim_requires_exit_quantity():
    with pytest.raises(ValidationError):
        HoldingVerdict(ticker="SBIN", verdict="TRIM", conviction=3.0,
                       reason_code="event_risk", rationale="derisk")


def test_holdings_review_evidence_filter_still_applies():
    r = HoldingsReview(reviews=[], carry_forward="quiet day",
                       evidence=["not-a-news-id", "a1b2c3d4e5f6"])
    assert r.evidence == ["a1b2c3d4e5f6"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/test_llm_schemas.py -q`
Expected: FAIL with `ImportError: cannot import name 'HoldingsReview'`.

- [ ] **Step 3: Implement the schema**

In `tradeloop/lib/llm/schemas.py`, change the pydantic import line to include `model_validator`:

```python
from pydantic import BaseModel, Field, field_validator, model_validator
```

Insert between the `Debate` block (ends line ~162) and the `# --- 30 trade plan` block:

```python
# --- 15 holdings review (non-order modes only) ------------------------------
class HoldingVerdict(EvidenceMixin):
    ticker: str
    verdict: Literal["HOLD", "ADD", "TIGHTEN_STOP", "TRIM", "EXIT"]
    conviction: float = Field(ge=0, le=10)
    # Exits are reason-coded, never P&L-impulse: cutting winners early because
    # they are green is how swing expectancy dies (profit_protect -> tighten, not exit).
    reason_code: Literal[
        "stop_breach", "tripwire", "thesis_break", "event_risk",
        "profit_protect", "thesis_intact", "thesis_strengthened",
    ]
    rationale: str = ""
    new_stop: float | None = Field(default=None, gt=0)
    exit_quantity: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _verdict_requires_params(self):
        if self.verdict == "TIGHTEN_STOP" and self.new_stop is None:
            raise ValueError("TIGHTEN_STOP requires new_stop")
        if self.verdict == "TRIM" and self.exit_quantity is None:
            raise ValueError("TRIM requires exit_quantity")
        return self


class HoldingsReview(EvidenceMixin):
    reviews: list[HoldingVerdict] = Field(default_factory=list)
    carry_forward: str = ""
```

Add to `SCHEMA_FOR_STAGE` (keep numeric order, after `"14_shortlist"`):

```python
    "15_holdings_review": HoldingsReview,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/test_llm_schemas.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tradeloop/lib/llm/schemas.py tradeloop/tests/test_llm_schemas.py
git commit -m "feat(schemas): HoldingsReview stage schema with reason-coded verdicts"
```

---

### Task 3: Stage wiring and prompt for 15_holdings_review

**Files:**
- Modify: `tradeloop/lib/llm/stages.py`
- Create: `tradeloop/prompts/15_holdings_reviewer.md`
- Test: `tradeloop/tests/test_llm_stages.py`

**Interfaces:**
- Consumes: `SCHEMA_FOR_STAGE["15_holdings_review"]` from Task 2.
- Produces: `stages.run_stage("15_holdings_review", run_dir, client)` works: prompt loads from `prompts/15_holdings_reviewer.md`, inputs are `["00_context.md", "holdings_ltp.json", "10_news.md", "11_sentiment.md", "12_fundamentals.md", "13_technical.md"]` (missing files degrade silently per `_user_message`), output artifacts `15_holdings_review.json` / `.md`.

- [ ] **Step 1: Write the failing test**

Append to `tradeloop/tests/test_llm_stages.py`:

```python
def test_holdings_review_stage_wired(tmp_path):
    from tradeloop.lib.llm import stages, schemas

    class FakeClient:
        def call_json(self, role, system, user, schema, model=None):
            assert role == "15_holdings_review"
            assert schema is schemas.HoldingsReview
            assert "00_context.md" in user           # named inputs assembled
            return schemas.HoldingsReview(reviews=[], carry_forward="nothing to flag")

    (tmp_path / "00_context.md").write_text("# ctx\n", encoding="utf-8")
    out = stages.run_stage("15_holdings_review", tmp_path, FakeClient())
    assert out.carry_forward == "nothing to flag"
    assert (tmp_path / "15_holdings_review.json").exists()
    assert (tmp_path / "15_holdings_review.md").exists()


def test_holdings_review_prompt_file_exists():
    from tradeloop.lib.llm.stages import PROMPTS_DIR, PROMPT_PATH
    assert (PROMPTS_DIR / f"{PROMPT_PATH['15_holdings_review']}.md").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/test_llm_stages.py -q`
Expected: FAIL (KeyError `'15_holdings_review'` or missing prompt).

- [ ] **Step 3: Wire the stage**

In `tradeloop/lib/llm/stages.py`, add to `STAGE_INPUTS` after the `"14_shortlist"` entry:

```python
    "15_holdings_review": ["00_context.md", "holdings_ltp.json", "10_news.md",
                           "11_sentiment.md", "12_fundamentals.md", "13_technical.md"],
```

Add to `PROMPT_PATH` after `"14_shortlist"`:

```python
    "15_holdings_review": "15_holdings_reviewer",
```

- [ ] **Step 4: Create `tradeloop/prompts/15_holdings_reviewer.md`**

```markdown
# Holdings Reviewer

Reads:

- `00_context.md` (positions, average prices, hard stops, cash)
- `holdings_ltp.json` (live last-traded prices; may be absent)
- `10_news.md`
- `11_sentiment.md` (postclose only; may read "Pending.")
- `12_fundamentals.md` (postclose only; may read "Pending.")
- `13_technical.md`

Writes: `15_holdings_review.md`.

Rules:

- Review ONLY tickers currently held per `00_context.md`. Never introduce new names.
- Exactly one verdict per holding: HOLD, ADD, TIGHTEN_STOP, TRIM, or EXIT.
- Exits are reason-coded, never P&L-impulse. Valid exit reasons: stop_breach,
  tripwire, thesis_break, event_risk.
- If the last traded price is at or below the recorded hard stop, the verdict
  MUST be EXIT with reason_code stop_breach.
- When the concern is protecting an open gain on an intact thesis, prefer
  TIGHTEN_STOP with reason_code profit_protect. new_stop must be ABOVE the
  current recorded stop and BELOW the current price.
- ADD is advisory only: it cannot execute in this cycle; it informs the next
  premarket. Never pair ADD with an exit_quantity or new_stop.
- TRIM requires exit_quantity: the number of shares to sell, at most the held
  quantity.
- conviction scores the CURRENT thesis 0-10, judged against the evidence in
  today's inputs, not the entry-day optimism.
- carry_forward: 3-6 sentences for the next session covering verdicts, levels
  to watch, and pending events (earnings, tripwires).

Output: one review per holding plus the carry_forward summary.
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/test_llm_stages.py tradeloop/tests/test_llm_schemas.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tradeloop/lib/llm/stages.py tradeloop/prompts/15_holdings_reviewer.md tradeloop/tests/test_llm_stages.py
git commit -m "feat(stages): wire 15_holdings_review stage with holdings reviewer prompt"
```

---

### Task 4: STOP_UPDATED ledger event and stop projection

**Files:**
- Modify: `tradeloop/lib/audit/ledger.py` (constant only)
- Modify: `tradeloop/scripts/prepare_cycle.py:35` (`_portfolio_state` replay)
- Test: `tradeloop/tests/test_ledger.py`, `tradeloop/tests/data/test_prepare_cycle_wired.py`

**Interfaces:**
- Produces: `tradeloop.lib.audit.ledger.STOP_UPDATED == "paper.stop.updated"`.
  Event shape: `{"type": STOP_UPDATED, "symbol": "<UPPER>", "hard_stop": <float>}`.
  `_portfolio_state` returns the LATEST stop per held symbol across ORDER_FILLED and STOP_UPDATED events in ledger sequence order.

- [ ] **Step 1: Write the failing tests**

Append to `tradeloop/tests/test_ledger.py`:

```python
def test_stop_updated_event_appends_and_replays(tmp_path):
    from tradeloop.lib.audit.ledger import Ledger, STOP_UPDATED
    led = Ledger(tmp_path / "ledger.db")
    led.append({"type": STOP_UPDATED, "symbol": "HDFCBANK", "hard_stop": 820.0})
    events = led.replay([STOP_UPDATED])
    assert events[0]["symbol"] == "HDFCBANK"
    assert events[0]["hard_stop"] == 820.0
    led.verify_chain()
```

Append to `tradeloop/tests/data/test_prepare_cycle_wired.py`:

```python
def test_portfolio_state_takes_latest_stop_update(tmp_path):
    from tradeloop.lib.audit.ledger import Ledger, ORDER_FILLED, STOP_UPDATED
    from tradeloop.scripts.prepare_cycle import _portfolio_state

    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.yaml").write_text("paper_starting_inr: 100000\n", encoding="utf-8")
    (tmp_path / "state").mkdir()
    led = Ledger(tmp_path / "state" / "ledger.db")
    led.append({"type": ORDER_FILLED, "order_id": "X1", "symbol": "HDFCBANK",
                "side": "BUY", "quantity": 30, "fill_price": 830.62,
                "product": "CNC", "hard_stop": 807.24})
    led.append({"type": STOP_UPDATED, "symbol": "HDFCBANK", "hard_stop": 820.0})
    state = _portfolio_state(tmp_path)
    assert state.hard_stops["HDFCBANK"] == 820.0
```

Note: if `empty_state_from_settings` needs more settings keys than `paper_starting_inr`, copy the minimal settings block used by existing tests in this file instead.

- [ ] **Step 2: Run tests to verify they fail**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/test_ledger.py tradeloop/tests/data/test_prepare_cycle_wired.py -q`
Expected: first fails on `ImportError: STOP_UPDATED`, second on stop still 807.24.

- [ ] **Step 3: Implement**

In `tradeloop/lib/audit/ledger.py`, next to `ORDER_FILLED = "paper.order.filled"` add:

```python
STOP_UPDATED = "paper.stop.updated"
```

In `tradeloop/scripts/prepare_cycle.py`, change the import and the replay call in `_portfolio_state`:

```python
from tradeloop.lib.audit.ledger import ORDER_FILLED, STOP_UPDATED, Ledger
```

```python
    for event in Ledger(ledger_path).replay([ORDER_FILLED, STOP_UPDATED]):
        if float(event.get("hard_stop", 0.0)) > 0:
            stops[event["symbol"]] = float(event["hard_stop"])
```

(Only the type list changes; the last-write-wins dict already gives the latest stop because `replay` returns ledger sequence order.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/test_ledger.py tradeloop/tests/data/test_prepare_cycle_wired.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tradeloop/lib/audit/ledger.py tradeloop/scripts/prepare_cycle.py \
  tradeloop/tests/test_ledger.py tradeloop/tests/data/test_prepare_cycle_wired.py
git commit -m "feat(ledger): STOP_UPDATED event; portfolio state projects latest stop"
```

---

### Task 5: Risk gate - exits exempt from the position-allocation cap

An appreciated position's exit notional can exceed `max_position_allocation_pct` even though the entry respected it; the gate must never trap capital in a winner.

**Files:**
- Modify: `tradeloop/lib/risk/checks.py:58`
- Test: `tradeloop/tests/test_router_gate.py`

- [ ] **Step 1: Write the failing test**

Append to `tradeloop/tests/test_router_gate.py` (reuse this file's existing helpers for building `RiskState`/`RiskCaps` if present; otherwise construct directly):

```python
def test_sell_exempt_from_position_allocation_cap():
    from tradeloop.lib.broker.paper_broker import OrderTicket
    from tradeloop.lib.risk.checks import RiskCaps, RiskState, evaluate

    state = RiskState(cash_inr=10000.0, positions={"CDSL": 100},
                      avg_prices={"CDSL": 1000.0}, sectors={})
    caps = RiskCaps(capital_inr=200000.0, max_open_positions=6,
                    max_position_allocation_pct=25.0, max_total_deployed_pct=80.0,
                    max_sector_allocation_pct=50.0, max_daily_drawdown_pct=3.0,
                    universe=["CDSL"])
    # position doubled: exit notional 150000 = 75% of capital, far over the 25% entry cap
    ticket = OrderTicket(symbol="CDSL", side="SELL", quantity=100, price=1500.0)
    verdict = evaluate(ticket, state, caps)
    assert verdict.approved, verdict.reasons
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/test_router_gate.py -q`
Expected: FAIL with reasons containing `max_position_allocation_exceeded`.

- [ ] **Step 3: Implement**

In `tradeloop/lib/risk/checks.py`, change line 58:

```python
    if notional > caps.capital_inr * (caps.max_position_allocation_pct / 100) and ticket.side == "BUY":
        reasons.append("max_position_allocation_exceeded")
```

- [ ] **Step 4: Run the gate tests**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/test_router_gate.py tradeloop/tests/test_router_cumulative_caps.py -q`
Expected: PASS (BUY-side allocation tests must still pass).

- [ ] **Step 5: Commit**

```bash
git add tradeloop/lib/risk/checks.py tradeloop/tests/test_router_gate.py
git commit -m "fix(risk): exempt SELL exits from the position-allocation entry cap"
```

---

### Task 6: prepare_cycle - holdings-scoped scan and holdings_ltp.json

**Files:**
- Modify: `tradeloop/scripts/prepare_cycle.py` (`prepare()`)
- Test: `tradeloop/tests/data/test_prepare_cycle_wired.py`

**Interfaces:**
- Consumes: `ingest_run(now, symbols=..., run_dir=..., config_dir=..., kite_client=..., source_health_root=...)` (symbols override already supported, `tradeloop/lib/data/ingest.py:68`), `KiteClient.ltp(symbols) -> dict[str, float]`.
- Produces: for intraday/postclose, the scan universe is exactly the held symbols and `<run>/holdings_ltp.json` is written as `{"SYMBOL": <float ltp>, ...}` when a kite client is available.
  Order modes are unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `tradeloop/tests/data/test_prepare_cycle_wired.py`:

```python
class _LtpKite:
    """Minimal kite double: records the scan universe, serves LTPs."""
    def __init__(self, ltps):
        self._ltps = ltps
        self.scanned = None

    def ltp(self, symbols):
        return {s: self._ltps[s] for s in symbols if s in self._ltps}


def _seeded_root(tmp_path):
    """Project root with one held position; mirrors this file's existing seeding style."""
    from tradeloop.lib.audit.ledger import Ledger, ORDER_FILLED
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "settings.yaml").write_text("paper_starting_inr: 100000\n", encoding="utf-8")
    (tmp_path / "state").mkdir(exist_ok=True)
    (tmp_path / "memory").mkdir(exist_ok=True)
    Ledger(tmp_path / "state" / "ledger.db").append(
        {"type": ORDER_FILLED, "order_id": "X1", "symbol": "HDFCBANK", "side": "BUY",
         "quantity": 30, "fill_price": 830.62, "product": "CNC", "hard_stop": 807.24})
    return tmp_path


def test_intraday_prepare_scopes_scan_to_holdings_and_writes_ltp(tmp_path, monkeypatch):
    import tradeloop.scripts.prepare_cycle as pc
    root = _seeded_root(tmp_path)
    captured = {}

    def fake_ingest(now, symbols=None, **kwargs):
        captured["symbols"] = symbols
    monkeypatch.setattr(pc, "ingest_run", fake_ingest)

    kite = _LtpKite({"HDFCBANK": 812.5})
    run_dir = pc.prepare("intraday", root=root, kite_client=kite)
    assert captured["symbols"] == ["HDFCBANK"]
    import json
    assert json.loads((run_dir / "holdings_ltp.json").read_text()) == {"HDFCBANK": 812.5}


def test_premarket_prepare_keeps_full_universe(tmp_path, monkeypatch):
    import tradeloop.scripts.prepare_cycle as pc
    root = _seeded_root(tmp_path)
    captured = {}

    def fake_ingest(now, symbols=None, **kwargs):
        captured["symbols"] = symbols
    monkeypatch.setattr(pc, "ingest_run", fake_ingest)
    pc.prepare("premarket", root=root, kite_client=_LtpKite({}))
    assert captured["symbols"] is None


def test_intraday_prepare_degrades_without_ltp(tmp_path, monkeypatch):
    import tradeloop.scripts.prepare_cycle as pc
    root = _seeded_root(tmp_path)
    monkeypatch.setattr(pc, "ingest_run", lambda now, symbols=None, **kwargs: None)

    class _Boom:
        def ltp(self, symbols):
            raise RuntimeError("token expired")
    run_dir = pc.prepare("intraday", root=root, kite_client=_Boom())
    assert not (run_dir / "holdings_ltp.json").exists()
    assert (run_dir / "ltp_error.txt").exists()   # loud degrade, never a crash
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/data/test_prepare_cycle_wired.py -q`
Expected: FAIL (`captured["symbols"]` is None for intraday; no holdings_ltp.json).

- [ ] **Step 3: Implement**

In `tradeloop/scripts/prepare_cycle.py`:

Add `import json` to the imports.

In `prepare()`, replace the ingest block (currently lines 73-82) with:

```python
    if kite_client is None and os.getenv("ZERODHA_ENABLE_DATA", "false").strip().lower() == "true":
        kite_client = KiteClient()
    # Non-order modes review the book, not the market: scan only held symbols
    # (an empty book scans nothing) and snapshot their live LTPs for the
    # deterministic stop-breach check and the holdings reviewer.
    held = sorted(state.positions)
    scan_symbols = held if mode in ("intraday", "postclose") else None
    try:
        ingest_run(now, symbols=scan_symbols, run_dir=run_dir, config_dir=base / "config",
                   kite_client=kite_client, source_health_root=base)
    except Exception as exc:  # degrade-not-abort: never leave a silent blank
        (run_dir / "01_news_raw.md").write_text(
            render_news_raw([], [], news_available=False), encoding="utf-8")
        (run_dir / "02_setups_raw.md").write_text(render_setups([]), encoding="utf-8")
        (run_dir / "ingest_error.txt").write_text(f"ingest failed: {exc}\n", encoding="utf-8")
    if mode in ("intraday", "postclose") and kite_client is not None and held:
        try:
            ltps = kite_client.ltp(held)
            if ltps:
                (run_dir / "holdings_ltp.json").write_text(
                    json.dumps(ltps, indent=2), encoding="utf-8")
        except Exception as exc:  # stale token etc.: review still runs, breach check skips
            (run_dir / "ltp_error.txt").write_text(f"ltp fetch failed: {exc}\n", encoding="utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/data/ -q`
Expected: PASS (including all pre-existing prepare/ingest tests).

- [ ] **Step 5: Commit**

```bash
git add tradeloop/scripts/prepare_cycle.py tradeloop/tests/data/test_prepare_cycle_wired.py
git commit -m "feat(prepare): scope non-order-mode scans to holdings; snapshot holdings LTPs"
```

---

### Task 7: Mode-specific DAGs in the orchestrator

**Files:**
- Modify: `tradeloop/orchestrator.py` (`_run_reasoning_dag`, module constants)
- Test: `tradeloop/tests/test_reasoning_wiring.py`

**Interfaces:**
- Produces: `_MODE_DAGS = {"intraday": [...], "postclose": [...]}` and `_dag_for_mode(mode) -> list[str]`.
  Intraday DAG: `["10_news", "13_technical", "15_holdings_review"]`.
  Postclose DAG: `["10_news", "11_sentiment", "12_fundamentals", "13_technical", "15_holdings_review"]`.
  Premarket/adhoc: `stages.DAG` unchanged.
- Note: Task 8 replaces the orders-derivation `else` branch; in THIS task the `15_holdings_review` case still writes `orders=[]` so the DAG change lands green on its own.

- [ ] **Step 1: Update StageFakeClient and write the failing tests**

In `tradeloop/tests/test_reasoning_wiring.py`, add to `StageFakeClient.DEFAULTS`:

```python
        schemas.HoldingsReview: {"reviews": [], "carry_forward": "", "evidence": []},
```

Update `test_postclose_skips_trade_stages_and_proposes_nothing` (line ~54): after the existing asserts add:

```python
    # discovery is gone from postclose; the review ran instead
    assert not (d / "14_shortlist.json").exists()
    assert not (d / "22_debate.json").exists()
    assert (d / "15_holdings_review.json").exists()
    assert (d / "11_sentiment.json").exists()      # postclose keeps the deep read
```

Add a new test:

```python
def test_intraday_runs_pulse_dag_only(tmp_path):
    d = tmp_path / "runs" / "2026-07-14_1400_intraday"
    d.mkdir(parents=True)
    for f in ("00_context.md", "01_news_raw.md", "02_setups_raw.md"):
        (d / f).write_text(f"# {f}\n")
    rc = orchestrator._run_reasoning(d, "intraday", "openrouter", 1200, client=StageFakeClient())
    assert rc == 0
    assert (d / "10_news.json").exists()
    assert (d / "13_technical.json").exists()
    assert (d / "15_holdings_review.json").exists()
    assert not (d / "11_sentiment.json").exists()   # fundamentals/sentiment do not change intraday
    assert not (d / "12_fundamentals.json").exists()
    assert not (d / "14_shortlist.json").exists()
    assert json.loads((d / "orders.json").read_text())["orders"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/test_reasoning_wiring.py -q`
Expected: FAIL (postclose still runs shortlist/debate; no 15_holdings_review.json).

- [ ] **Step 3: Implement**

In `tradeloop/orchestrator.py`, below `_ORDER_MODES` (line 41) add:

```python
# Non-order modes run a holdings-focused DAG: no discovery (shortlist/debate),
# ending in the holdings review. Intraday is a cheap pulse (news delta + chart
# health); postclose re-underwrites the book with sentiment + fundamentals too.
_MODE_DAGS = {
    "intraday": ["10_news", "13_technical", "15_holdings_review"],
    "postclose": ["10_news", "11_sentiment", "12_fundamentals",
                  "13_technical", "15_holdings_review"],
}


def _dag_for_mode(mode: str) -> list[str]:
    return list(_MODE_DAGS.get(mode, stages.DAG))
```

In `_run_reasoning_dag`, replace:

```python
    dag = list(stages.DAG)
```

with:

```python
    dag = _dag_for_mode(mode)
```

and DELETE the now-redundant pruning block (lines 149-151):

```python
    if mode not in _ORDER_MODES:  # intraday/postclose: no order stages (see _TRADE_STAGES)
        # ponytail: wire a real manage/exit path here when intraday needs to trim positions.
        dag = [s for s in dag if s not in _TRADE_STAGES]
```

(`_TRADE_STAGES` at line 40 becomes unused by the DAG builder; it stays referenced by nothing, so delete the constant too if nothing else imports it: `grep -rn _TRADE_STAGES tradeloop/` first, and keep it if tests reference it.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/test_reasoning_wiring.py tradeloop/tests/test_orchestrator.py tradeloop/tests/test_adhoc_mode.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tradeloop/orchestrator.py tradeloop/tests/test_reasoning_wiring.py
git commit -m "feat(orchestrator): holdings-focused DAGs for intraday and postclose"
```

---

### Task 8: Deterministic holdings actions - intraday SELL orders, stop updates, breach enforcement

**Files:**
- Modify: `tradeloop/orchestrator.py`
- Create: `tradeloop/tests/test_holdings_actions.py`

**Interfaces:**
- Consumes: `HoldingsReview` (Task 2), `_portfolio_state` (Task 4), `holdings_ltp.json` (Task 6).
- Produces: `_holdings_actions(run_dir: Path, mode: str, root: Path) -> tuple[list[Order], dict[str, float]]`.
  Intraday: EXIT verdicts -> full-position SELL at LTP; TRIM -> SELL of `min(exit_quantity, held)`; any held symbol with `ltp <= recorded stop` and no SELL yet -> forced EXIT (`reason "exit:stop_breach_enforced"`).
  Postclose: orders always `[]`.
  Both modes: TIGHTEN_STOP verdicts -> `{symbol: new_stop}` where `new_stop > recorded stop` and the symbol is held; written to `<run>/stop_updates.json` by `_run_reasoning_dag`.

- [ ] **Step 1: Write the failing tests**

Create `tradeloop/tests/test_holdings_actions.py`:

```python
import json
from pathlib import Path

from tradeloop import orchestrator
from tradeloop.lib.audit.ledger import ORDER_FILLED, Ledger


def _root_with_position(tmp_path, symbol="HDFCBANK", qty=30, price=830.62, stop=807.24):
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "settings.yaml").write_text("paper_starting_inr: 100000\n", encoding="utf-8")
    (tmp_path / "state").mkdir(exist_ok=True)
    Ledger(tmp_path / "state" / "ledger.db").append(
        {"type": ORDER_FILLED, "order_id": "X1", "symbol": symbol, "side": "BUY",
         "quantity": qty, "fill_price": price, "product": "CNC", "hard_stop": stop})
    return tmp_path


def _run_dir(root, name="2026-07-14_1400_intraday"):
    d = root / "runs" / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_review(d, reviews, carry_forward=""):
    payload = {"reviews": reviews, "carry_forward": carry_forward, "evidence": []}
    (d / "15_holdings_review.json").write_text(json.dumps(payload), encoding="utf-8")


def test_exit_verdict_becomes_full_sell_at_ltp(tmp_path):
    root = _root_with_position(tmp_path)
    d = _run_dir(root)
    (d / "holdings_ltp.json").write_text(json.dumps({"HDFCBANK": 812.5}), encoding="utf-8")
    _write_review(d, [{"ticker": "HDFCBANK", "verdict": "EXIT", "conviction": 2.0,
                       "reason_code": "thesis_break", "rationale": "bad results", "evidence": []}])
    orders, stops = orchestrator._holdings_actions(d, "intraday", root)
    assert len(orders) == 1
    assert (orders[0].ticker, orders[0].side, orders[0].quantity, orders[0].price) == \
        ("HDFCBANK", "SELL", 30, 812.5)
    assert stops == {}


def test_trim_clamped_to_position(tmp_path):
    root = _root_with_position(tmp_path)
    d = _run_dir(root)
    (d / "holdings_ltp.json").write_text(json.dumps({"HDFCBANK": 812.5}), encoding="utf-8")
    _write_review(d, [{"ticker": "HDFCBANK", "verdict": "TRIM", "conviction": 4.0,
                       "reason_code": "event_risk", "rationale": "derisk into earnings",
                       "exit_quantity": 500, "evidence": []}])
    orders, _ = orchestrator._holdings_actions(d, "intraday", root)
    assert orders[0].quantity == 30   # never sell more than held


def test_stop_breach_forces_exit_even_if_review_missed_it(tmp_path):
    root = _root_with_position(tmp_path, stop=807.24)
    d = _run_dir(root)
    (d / "holdings_ltp.json").write_text(json.dumps({"HDFCBANK": 806.0}), encoding="utf-8")
    _write_review(d, [{"ticker": "HDFCBANK", "verdict": "HOLD", "conviction": 6.0,
                       "reason_code": "thesis_intact", "rationale": "looks fine", "evidence": []}])
    orders, _ = orchestrator._holdings_actions(d, "intraday", root)
    assert len(orders) == 1
    assert orders[0].side == "SELL" and orders[0].quantity == 30
    assert orders[0].reason == "exit:stop_breach_enforced"


def test_postclose_never_produces_orders_but_keeps_stop_updates(tmp_path):
    root = _root_with_position(tmp_path)
    d = _run_dir(root, "2026-07-14_1600_postclose")
    (d / "holdings_ltp.json").write_text(json.dumps({"HDFCBANK": 806.0}), encoding="utf-8")
    _write_review(d, [{"ticker": "HDFCBANK", "verdict": "TIGHTEN_STOP", "conviction": 6.0,
                       "reason_code": "profit_protect", "rationale": "lock gain",
                       "new_stop": 815.0, "evidence": []}])
    orders, stops = orchestrator._holdings_actions(d, "postclose", root)
    assert orders == []                      # market closed: nothing may fill
    assert stops == {"HDFCBANK": 815.0}


def test_tighten_stop_never_loosens_and_needs_position(tmp_path):
    root = _root_with_position(tmp_path, stop=807.24)
    d = _run_dir(root)
    _write_review(d, [
        {"ticker": "HDFCBANK", "verdict": "TIGHTEN_STOP", "conviction": 5.0,
         "reason_code": "profit_protect", "rationale": "wider", "new_stop": 790.0, "evidence": []},
        {"ticker": "GHOST", "verdict": "TIGHTEN_STOP", "conviction": 5.0,
         "reason_code": "profit_protect", "rationale": "not held", "new_stop": 100.0, "evidence": []},
    ])
    _, stops = orchestrator._holdings_actions(d, "intraday", root)
    assert stops == {}   # loosening rejected; unheld symbol rejected


def test_no_ltp_means_no_orders_flagged_for_carry_forward(tmp_path):
    root = _root_with_position(tmp_path)
    d = _run_dir(root)
    _write_review(d, [{"ticker": "HDFCBANK", "verdict": "EXIT", "conviction": 2.0,
                       "reason_code": "thesis_break", "rationale": "bad", "evidence": []}])
    orders, _ = orchestrator._holdings_actions(d, "intraday", root)
    assert orders == []   # no price -> nothing routable; verdict still reaches carry-forward


def test_run_reasoning_dag_writes_sells_and_stop_updates(tmp_path):
    """End to end through _run_reasoning: intraday fake review -> orders.json + stop_updates.json."""
    from tradeloop.lib.llm import schemas
    from tradeloop.tests.test_reasoning_wiring import StageFakeClient

    root = _root_with_position(tmp_path)
    d = _run_dir(root)
    for f in ("00_context.md", "01_news_raw.md", "02_setups_raw.md"):
        (d / f).write_text(f"# {f}\n")
    (d / "holdings_ltp.json").write_text(json.dumps({"HDFCBANK": 812.5}), encoding="utf-8")
    client = StageFakeClient()
    client.DEFAULTS = dict(StageFakeClient.DEFAULTS)
    client.DEFAULTS[schemas.HoldingsReview] = {
        "reviews": [{"ticker": "HDFCBANK", "verdict": "EXIT", "conviction": 2.0,
                     "reason_code": "thesis_break", "rationale": "bad", "evidence": []}],
        "carry_forward": "exited", "evidence": []}
    rc = orchestrator._run_reasoning(d, "intraday", "openrouter", 1200, client=client)
    assert rc == 0
    orders = json.loads((d / "orders.json").read_text())
    assert orders["orders"][0]["side"] == "SELL"
    assert orders["orders"][0]["quantity"] == 30
    assert json.loads((d / "stop_updates.json").read_text()) == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/test_holdings_actions.py -q`
Expected: FAIL with `AttributeError: ... has no attribute '_holdings_actions'`.

- [ ] **Step 3: Implement**

In `tradeloop/orchestrator.py`:

Extend the schemas import (find the existing `from tradeloop.lib.llm.schemas import ...` line) to include `HoldingsReview` and `Order`.
Import `_portfolio_state`:

```python
from tradeloop.scripts.prepare_cycle import prepare as _prepare, _portfolio_state
```

Add after `_size_trade_plan`:

```python
def _holdings_actions(run_dir: Path, mode: str, root: Path) -> tuple[list[Order], dict[str, float]]:
    """Deterministic money-path derivation from the holdings review. Intraday
    EXIT/TRIM verdicts become SELL orders priced at the snapshotted LTP;
    TIGHTEN_STOP verdicts become tighten-only stop updates (applied at route
    time, both modes). A held symbol whose LTP is at/below its recorded stop is
    force-exited even if the review missed it: the stop was approved when the
    position opened, so enforcing it is not a new decision. Postclose produces
    no orders ever - the market is closed and a paper fill would be fiction."""
    review = HoldingsReview.model_validate_json(
        (run_dir / "15_holdings_review.json").read_text(encoding="utf-8"))
    ltp_path = run_dir / "holdings_ltp.json"
    ltps: dict[str, float] = {}
    if ltp_path.exists():
        ltps = {k.strip().upper(): float(v)
                for k, v in json.loads(ltp_path.read_text(encoding="utf-8")).items()}
    state = _portfolio_state(root)
    positions, stops = state.positions, state.hard_stops
    reviewed = {r.ticker.strip().upper(): r for r in review.reviews}

    orders: list[Order] = []
    if mode == "intraday":
        for sym, r in reviewed.items():
            qty, ltp = positions.get(sym, 0), ltps.get(sym)
            if r.verdict not in ("EXIT", "TRIM") or qty <= 0 or not ltp:
                continue  # no price or no position -> nothing routable
            sell_qty = qty if r.verdict == "EXIT" else min(r.exit_quantity or 0, qty)
            if sell_qty <= 0:
                continue
            orders.append(Order(ticker=sym, side="SELL", quantity=sell_qty, price=ltp,
                                strategy_family="position_management",
                                reason=f"{r.verdict.lower()}:{r.reason_code}"))
        ordered = {o.ticker for o in orders}
        for sym, qty in positions.items():
            stop, ltp = stops.get(sym, 0.0), ltps.get(sym)
            if qty > 0 and stop > 0 and ltp and ltp <= stop and sym not in ordered:
                orders.append(Order(ticker=sym, side="SELL", quantity=qty, price=ltp,
                                    strategy_family="position_management",
                                    reason="exit:stop_breach_enforced"))

    stop_updates: dict[str, float] = {}
    for sym, r in reviewed.items():
        if (r.verdict == "TIGHTEN_STOP" and r.new_stop
                and positions.get(sym, 0) > 0 and r.new_stop > stops.get(sym, 0.0)):
            stop_updates[sym] = float(r.new_stop)
    return orders, stop_updates
```

In `_run_reasoning_dag`, thread the root and replace the orders block. Change the signature:

```python
def _run_reasoning_dag(run_dir: Path, mode: str, timeout: int, client,
                       settings=None, generated_by: str = "tradeloop.reasoning.p1",
                       root: Path | None = None) -> int:
```

and at its top add:

```python
    root = root or run_dir.parent.parent  # runs/<name> convention
```

Replace the tail block:

```python
    if "41_pm_decision" in dag:
        pm = PMDecision.model_validate_json((run_dir / "41_pm_decision.json").read_text())
        orders, held = pm.orders, pm.held
    else:  # research-only adhoc: no PM stage ran, so there is nothing to route
        orders, held = [], []
```

with:

```python
    if "41_pm_decision" in dag:
        pm = PMDecision.model_validate_json((run_dir / "41_pm_decision.json").read_text())
        orders, held = pm.orders, pm.held
    elif "15_holdings_review" in dag:
        orders, stop_updates = _holdings_actions(run_dir, mode, root)
        held = []
        (run_dir / "stop_updates.json").write_text(
            json.dumps(stop_updates, indent=2), encoding="utf-8")
    else:  # research-only adhoc: no PM stage ran, so there is nothing to route
        orders, held = [], []
```

Also pass root through `_run_reasoning`: add `root: Path | None = None` to its signature and forward it to `_run_reasoning_dag(...)`; in `run_cycle` call `_run_reasoning(run_dir, mode, backend, settings.cycle_timeout_seconds, settings=settings, root=root)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/test_holdings_actions.py tradeloop/tests/test_reasoning_wiring.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tradeloop/orchestrator.py tradeloop/tests/test_holdings_actions.py
git commit -m "feat(orchestrator): derive intraday exits and stop updates from the holdings review"
```

---

### Task 9: Carry-forward writer

**Files:**
- Modify: `tradeloop/orchestrator.py` (writer + call in `run_cycle`)
- Test: `tradeloop/tests/test_holdings_actions.py` (same file; carry-forward section)

**Interfaces:**
- Produces: `_write_carry_forward(memory_root: Path, run_id: str, review: HoldingsReview) -> None`; maintains ONE auto block in `memory/carry_forward_context.md` between `<!-- auto:holdings_review:start -->` / `<!-- auto:holdings_review:end -->`, replaced on every run, manual notes outside the markers preserved.
  Called from `run_cycle` after successful reasoning when `15_holdings_review.json` exists; failure writes `<run>/carry_forward_error.txt` and never fails the cycle.

- [ ] **Step 1: Write the failing tests**

Append to `tradeloop/tests/test_holdings_actions.py`:

```python
def _review_obj(**kw):
    from tradeloop.lib.llm.schemas import HoldingsReview
    base = {"reviews": [{"ticker": "HDFCBANK", "verdict": "HOLD", "conviction": 6.0,
                         "reason_code": "thesis_intact", "rationale": "steady", "evidence": []}],
            "carry_forward": "Q1 results Wednesday; hold through print.", "evidence": []}
    base.update(kw)
    return HoldingsReview.model_validate(base)


def test_carry_forward_written_and_replaced_not_appended(tmp_path):
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "carry_forward_context.md").write_text(
        "- manual note: SBIN tripwire 1019\n", encoding="utf-8")
    orchestrator._write_carry_forward(mem, "2026-07-14_1400_intraday", _review_obj())
    orchestrator._write_carry_forward(mem, "2026-07-14_1600_postclose", _review_obj(
        carry_forward="All quiet after close."))
    text = (mem / "carry_forward_context.md").read_text(encoding="utf-8")
    assert "manual note: SBIN tripwire 1019" in text          # manual content survives
    assert text.count("auto:holdings_review:start") == 1       # replaced, not stacked
    assert "2026-07-14_1600_postclose" in text                 # latest run wins
    assert "2026-07-14_1400_intraday" not in text
    assert "All quiet after close." in text
    assert "HDFCBANK: HOLD" in text


def test_carry_forward_created_when_file_missing(tmp_path):
    mem = tmp_path / "memory"
    mem.mkdir()
    orchestrator._write_carry_forward(mem, "2026-07-14_1600_postclose", _review_obj())
    text = (mem / "carry_forward_context.md").read_text(encoding="utf-8")
    assert "auto:holdings_review:start" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/test_holdings_actions.py -q`
Expected: FAIL with `AttributeError: ... '_write_carry_forward'`.

- [ ] **Step 3: Implement**

In `tradeloop/orchestrator.py` add below `_holdings_actions`:

```python
_CF_START = "<!-- auto:holdings_review:start -->"
_CF_END = "<!-- auto:holdings_review:end -->"


def _write_carry_forward(memory_root: Path, run_id: str, review: HoldingsReview) -> None:
    """Replace the single auto holdings-review block in carry_forward_context.md.
    prepare_cycle injects this file into every 00_context, so this is the wire
    that makes a postclose verdict actionable at the next premarket. Manual
    notes outside the markers are never touched; the block is replaced, not
    appended, so the context cannot grow without bound."""
    path = memory_root / "carry_forward_context.md"
    lines = [f"### Holdings review ({run_id})", ""]
    for r in review.reviews:
        extra = ""
        if r.verdict == "TIGHTEN_STOP" and r.new_stop:
            extra = f" new_stop={r.new_stop}"
        if r.verdict == "TRIM" and r.exit_quantity:
            extra = f" exit_quantity={r.exit_quantity}"
        lines.append(f"- {r.ticker}: {r.verdict} ({r.reason_code}, "
                     f"conviction {r.conviction}){extra} - {r.rationale}")
    if review.carry_forward.strip():
        lines += ["", review.carry_forward.strip()]
    block = "\n".join([_CF_START, *lines, _CF_END])
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if _CF_START in text and _CF_END in text:
        pre, rest = text.split(_CF_START, 1)
        _, post = rest.split(_CF_END, 1)
        text = pre + block + post
    else:
        text = (text.rstrip() + "\n\n" if text.strip() else "") + block + "\n"
    path.write_text(text, encoding="utf-8")
```

In `run_cycle`, after the orders validation block (after `n_orders = len(orders)`, before the snapshot/evidence block) add:

```python
        review_path = run_dir / "15_holdings_review.json"
        if review_path.exists():
            try:
                _write_carry_forward(root / "memory", run_dir.name,
                                     HoldingsReview.model_validate_json(
                                         review_path.read_text(encoding="utf-8")))
            except Exception as exc:  # analysis plumbing must not fail the cycle
                (run_dir / "carry_forward_error.txt").write_text(
                    f"carry-forward write failed: {exc}\n", encoding="utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/test_holdings_actions.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tradeloop/orchestrator.py tradeloop/tests/test_holdings_actions.py
git commit -m "feat(orchestrator): holdings review verdicts feed carry-forward context"
```

---

### Task 10: route_cycle applies stop updates (tighten-only)

**Files:**
- Modify: `tradeloop/orchestrator.py` (`run_route` / the route body around lines 400-429)
- Test: `tradeloop/tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `stop_updates.json` (Task 8), `STOP_UPDATED` (Task 4).
- Produces: after routing orders (and even in postclose where no order can fill), `stop_updates.json` entries are applied as `STOP_UPDATED` ledger events, guarded tighten-only against the CURRENT recorded stop and only for symbols still held after this batch's fills.
  The route status line gains `stops_tightened=<n>`.

- [ ] **Step 1: Write the failing test**

Append to `tradeloop/tests/test_orchestrator.py`, following this file's existing route-cycle test fixtures (reuse its helpers for building a root with settings/ledger; the test below spells out the essentials):

```python
def test_route_applies_tighten_only_stop_updates(tmp_path, monkeypatch):
    import json
    from tradeloop.lib.audit.ledger import ORDER_FILLED, STOP_UPDATED, Ledger
    from tradeloop.scripts.prepare_cycle import _portfolio_state

    root = _route_root(tmp_path)   # reuse this file's existing root-builder fixture
    led = Ledger(root / "state" / "ledger.db")
    led.append({"type": ORDER_FILLED, "order_id": "X1", "symbol": "HDFCBANK", "side": "BUY",
                "quantity": 30, "fill_price": 830.62, "product": "CNC", "hard_stop": 807.24})
    d = root / "runs" / "2026-07-14_1600_postclose"
    d.mkdir(parents=True)
    (d / "orders.json").write_text(json.dumps(
        {"mode": "postclose", "live_orders_enabled": False,
         "generated_by": "test", "orders": [], "held": []}), encoding="utf-8")
    (d / "stop_updates.json").write_text(json.dumps(
        {"HDFCBANK": 820.0, "GHOST": 50.0}), encoding="utf-8")

    rc = orchestrator.run_route(d, root=root)
    assert rc == 0
    state = _portfolio_state(root)
    assert state.hard_stops["HDFCBANK"] == 820.0     # tightened
    assert "GHOST" not in state.hard_stops           # unheld symbol ignored
    # loosening attempt is a no-op
    (d / "stop_updates.json").write_text(json.dumps({"HDFCBANK": 700.0}), encoding="utf-8")
    (d / "fills.json").write_text("[]\n", encoding="utf-8")   # allow re-route in this test
    orchestrator.run_route(d, root=root)
    assert _portfolio_state(root).hard_stops["HDFCBANK"] == 820.0
```

Adapt the entry point name to this file's existing route tests (the function the CLI `route` mode calls; `grep -n "def run_route\|_already_routed" tradeloop/orchestrator.py` and match the existing tests' call pattern, including any `monkeypatch` they use for settings paths).
If `_already_routed` blocks the second call because `fills.json` is non-empty, follow the reset pattern the existing re-route tests use.

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/test_orchestrator.py -q`
Expected: FAIL (stop remains 807.24; stop_updates.json ignored).

- [ ] **Step 3: Implement**

In `tradeloop/orchestrator.py`, import `STOP_UPDATED` alongside the existing ledger imports.
In the route body, after the `append_book` block (line ~412) and before the counters (line ~413), add:

```python
        # Stop updates ride the same approval as the orders (invoking route IS
        # the approval). Tighten-only and held-only are re-checked here against
        # the live post-fill book, so a full exit cancels its own stale tighten.
        # Postclose may tighten stops (pure risk reduction, no fill involved)
        # even though it can never fill an order.
        stops_applied = 0
        stop_path = run_dir / "stop_updates.json"
        if stop_path.exists():
            try:
                updates = {str(k).strip().upper(): float(v) for k, v in
                           json.loads(stop_path.read_text(encoding="utf-8")).items()}
            except (ValueError, TypeError):
                updates = {}
            current: dict[str, float] = {}
            for event in led.replay([ORDER_FILLED, STOP_UPDATED]):
                if float(event.get("hard_stop", 0.0)) > 0:
                    current[event["symbol"]] = float(event["hard_stop"])
            for sym, new_stop in sorted(updates.items()):
                if book.positions.get(sym, 0) > 0 and new_stop > current.get(sym, 0.0):
                    led.append({"type": STOP_UPDATED, "symbol": sym, "hard_stop": new_stop})
                    stops_applied += 1
```

(`ORDER_FILLED` may need importing too if the module does not already have it; check the imports at the top.)

Change the final print to:

```python
        print(f"tradeloop_route=OK orders={len(routed)} filled={filled} rejected={rejected} "
              f"mode_blocked={mode_blocked} stops_tightened={stops_applied}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/test_orchestrator.py tradeloop/tests/test_postclose_wiring.py -q`
Expected: PASS.
If any pre-existing test asserts on the exact `tradeloop_route=OK ...` line, update it to include `stops_tightened=0`.

- [ ] **Step 5: Commit**

```bash
git add tradeloop/orchestrator.py tradeloop/tests/test_orchestrator.py
git commit -m "feat(route): apply tighten-only stop updates from the holdings review"
```

---

### Task 11: Dashboard surfaces the holdings review

**Files:**
- Modify: `tradeloop/dashboard/runs.py:9` (STAGE_ORDER)
- Modify: `tradeloop/dashboard/render.py` (STAGE_META entry + builder)
- Test: `tradeloop/tests/dashboard/test_render.py`

- [ ] **Step 1: Write the failing test**

Append to `tradeloop/tests/dashboard/test_render.py`:

```python
def test_render_holdings_review_stage():
    from tradeloop.dashboard.render import render_stage
    raw = {"reviews": [
        {"ticker": "HDFCBANK", "verdict": "HOLD", "conviction": 6.0,
         "reason_code": "thesis_intact", "rationale": "steady into results"},
        {"ticker": "SBIN", "verdict": "EXIT", "conviction": 2.0,
         "reason_code": "stop_breach", "rationale": "closed under stop"},
        {"ticker": "CDSL", "verdict": "TIGHTEN_STOP", "conviction": 6.5,
         "reason_code": "profit_protect", "rationale": "lock the move", "new_stop": 1420.0},
    ], "carry_forward": "watch HDFCBANK results"}
    view = render_stage("15_holdings_review", raw)
    assert "3 holdings" in view.summary
    assert any("SBIN" in p and "EXIT" in p for p in view.points)
    assert any("1420.0" in p for p in view.points)
    assert view.title == "Holdings Review"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/dashboard/test_render.py -q`
Expected: FAIL (generic empty card; title equals the raw stage key).

- [ ] **Step 3: Implement**

In `tradeloop/dashboard/runs.py`, add `"15_holdings_review"` to `STAGE_ORDER` after `"14_shortlist"`.

In `tradeloop/dashboard/render.py`:
Add to `STAGE_META` (line ~40), copying the icon key used by the `"40_risk_report"` entry (read the dict; reuse that exact icon string so the frontend map resolves it):

```python
    "15_holdings_review": ("<same icon as 40_risk_report>", "Holdings Review", "Position Manager"),
```

Add a builder next to `_risk` and register it:

```python
def _holdings_review(raw: dict) -> tuple[str, list[str]]:
    rows = raw.get("reviews") or []
    points = []
    for r in rows:
        extra = ""
        if r.get("new_stop") is not None:
            extra = f" new stop {r['new_stop']}"
        if r.get("exit_quantity") is not None:
            extra = f" sell {r['exit_quantity']}"
        points.append(f"{pretty_ticker(r.get('ticker',''))}: {r.get('verdict','')}"
                      f" ({r.get('reason_code','')}){extra} - {r.get('rationale','')}")
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.get("verdict", "?")] = counts.get(r.get("verdict", "?"), 0) + 1
    breakdown = ", ".join(f"{n} {v}" for v, n in sorted(counts.items()))
    summary = (f"{len(rows)} holdings reviewed: {breakdown}." if rows
               else "No holdings to review.")
    return summary, points


_ANALYSIS_BUILDERS["15_holdings_review"] = _holdings_review
```

- [ ] **Step 4: Run the dashboard tests**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests/dashboard -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tradeloop/dashboard/runs.py tradeloop/dashboard/render.py tradeloop/tests/dashboard/test_render.py
git commit -m "feat(dashboard): holdings review card for non-order cycles"
```

---

### Task 12: Cron slots - 14:00 intraday, 16:00 postclose; dedupe crontab

**Files:**
- Modify: `tradeloop/scripts/cron_dispatch.sh`
- Modify: `tradeloop/scripts/crontab.txt`

- [ ] **Step 1: Add the mode slots**

In `tradeloop/scripts/cron_dispatch.sh`, replace the comment block (lines 29-31) with two real cases mirroring the 0800 premarket case:

```bash
  1400)
    # Intraday pulse (14:00 IST): holdings health only - can propose exits and
    # stop-tightens, still stops at AWAITING_APPROVAL. Late-session slot so an
    # approved exit has a full hour to route before the 15:30 close.
    cd "$PROJECT_ROOT"
    "$PY" tradeloop/scripts/verify_setup.py --mode intraday --backend claude || exit $?
    exec env ZERODHA_ENABLE_DATA=true "$PY" -m tradeloop.orchestrator intraday --backend claude
    ;;
  1600)
    # Postclose review (16:00 IST): analysis-only re-underwrite of the book;
    # verdicts land in carry-forward for the next premarket. Routes nothing.
    cd "$PROJECT_ROOT"
    "$PY" tradeloop/scripts/verify_setup.py --mode postclose --backend claude || exit $?
    exec env ZERODHA_ENABLE_DATA=true "$PY" -m tradeloop.orchestrator postclose --backend claude
    ;;
```

- [ ] **Step 2: Fix the duplicated crontab line**

`crontab -l` currently shows the dispatch line twice.
`tradeloop/scripts/crontab.txt` must contain it exactly once; then reinstall:

```bash
crontab /Volumes/D-DRIVE/TradingBot/tradeloop/scripts/crontab.txt
crontab -l   # verify: one dispatch line
```

- [ ] **Step 3: Syntax-check the dispatch script**

Run: `bash -n /Volumes/D-DRIVE/TradingBot/tradeloop/scripts/cron_dispatch.sh && echo OK`
Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add tradeloop/scripts/cron_dispatch.sh tradeloop/scripts/crontab.txt
git commit -m "feat(cron): schedule 14:00 intraday pulse and 16:00 postclose review"
```

---

### Task 13: Full-suite gate, E2E validation, docs note

**Files:**
- Modify: `tradeloop/README.md` (mode table/description, if it documents cycle modes; check first)

- [ ] **Step 1: Full suite**

Run: `cd /Volumes/D-DRIVE/TradingBot && /Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m pytest tradeloop/tests -q`
Expected: all green.

- [ ] **Step 2: Live E2E smoke (production-shaped, per user testing standard)**

Run a real postclose cycle on the claude backend against the live book (4 holdings):

```bash
/Volumes/D-DRIVE/TradingBot/tradeloop/scripts/run_detached.sh postclose --backend claude
```

Verify, once finished:
- `15_holdings_review.json` exists with one verdict per held ticker and no unheld names.
- `orders.json` has `"orders": []`.
- `stop_updates.json` exists (possibly `{}`).
- `memory/carry_forward_context.md` now contains the auto block with this run's id.
- Dashboard shows the Holdings Review card.
Then route it (`python -m tradeloop.orchestrator route <run_dir>`) and check `stops_tightened=` in the output and, if a tighten was proposed, `_portfolio_state` shows the new stop.

An intraday smoke needs market hours; if outside hours, note it in the final report and validate intraday on the next trading day at 14:00 via cron.

- [ ] **Step 3: Update README if it documents modes**

`grep -n "intraday\|postclose" tradeloop/README.md` - if the mode semantics are described, update them to: intraday = holdings pulse, may propose exits/stop-tightens; postclose = holdings re-underwrite, analysis only, feeds carry-forward.
Keep the edit minimal.

- [ ] **Step 4: Final commit and report**

```bash
git add -A tradeloop/README.md
git commit -m "docs(readme): holdings-focused intraday/postclose mode semantics"
```

Report to the user: suite count, E2E observations, and that merging `feat/holdings-focused-cycles` to main + pushing awaits their call (pre-push hook needs `PATH=/Users/dhyanpatel/anaconda3/envs/tradingbot/bin:$PATH`).
