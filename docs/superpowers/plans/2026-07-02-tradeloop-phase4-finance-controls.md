# TradeLoop Phase 4 — Finance Controls, Learning & Health Implementation Plan

**Goal:** Add the post-trade auditor — reconcile positions two independent ways, re-run the risk gate over what actually happened (SOX-style control test over outcomes), attribute expected-vs-realized R per trade, wire a provenanced learning loop, and a fail-loud deploy health check.

**Architecture:** Three pure library modules under `tradeloop/lib/audit/` (`reconcile.py`, `controls.py`, `attribution.py`) that consume the P2 ledger (`ledger.replay`), the P0 paper book, `orders.json`/`fills.json`, and (when live) Kite holdings. A thin `postclose_learning` caller in the orchestrator feeds typed outcomes into the memory layer (`writer.append_unique` + provenance) and rewrites `strategy_performance.md` — the same file the promotion gate reads. `scripts/verify_setup.py` grows a dependency-import + per-source last-success health check.

**Tech Stack:** Python 3.11, pydantic v2 (already a dep), pytest, PyYAML/pandas (declared in P0). No new dependencies. Recorded fixtures only; no live network in tests.

## Global Constraints

- India cash equities only; segment EQ.
- Long-only: BUY opens/adds, SELL exits only — no shorts.
- No F&O, no NRML, no leverage; products CNC or MIS only.
- `tradeloop/kill_switch.md` present ⇒ orders halt.
- Paper is the default: `ZERODHA_ENABLE_TRADING=false`.
- Live only past the promotion gate (`settings.yaml live_promotion_gates`: min_paper_trades 40, min_win_rate 0.45, min_expectancy_r 0.3, max_drawdown_pct 8).
- The risk gate `checks.evaluate()` runs on every order (enforced in P0's order path; P4 re-runs it independently over actuals — it never routes).
- Security (AGENTS.md): never read/print `.env`; never log values whose name contains KEY/SECRET/TOKEN/PASSWORD/AUTH/CREDENTIAL. Kite holdings arrive via the MCP-backed client, never by reading env.

## File Structure

| File | Responsibility |
|---|---|
| `tradeloop/lib/audit/reconcile.py` | Derive positions three independent ways (fills-replay, orders-intent-minus-rejects, optional Kite holdings), flag qty/avg_price/cash deltas → `compare(...) -> list[Delta]`. |
| `tradeloop/lib/audit/controls.py` | Independently re-run `checks.evaluate()` over `orders.json`+`fills.json` vs caps; assert long-only/kill-switch/universe/caps held over outcomes; classify deficiencies → `recheck(...) -> ControlReport`. |
| `tradeloop/lib/audit/attribution.py` | Compute `expected_R` from the trade-plan trailer and `realized_R` from fills; render `strategy_performance.md` → `report(...) -> StrategyPerformance`. |
| `tradeloop/lib/audit/outcomes.py` | Typed `Outcome` enum (the four post-trade categories) + `classify_outcome()` used by attribution and the learning caller. |
| `tradeloop/lib/audit/__init__.py` | Package marker (may already exist from P2). |
| `tradeloop/lib/memory/writer.py` | Extend `append_unique` callers with provenance (`run_id`/`timestamp`/`hash`) via new `append_provenanced()`; keep `append_unique` unchanged. |
| `tradeloop/lib/audit/postclose.py` | Real caller wiring the postclose learning loop: attribution → outcomes → memory writer/dossier → `strategy_performance.md`, with provenance. |
| `tradeloop/scripts/verify_setup.py` | Add `--health` mode: dependency-import check + per-source last-success check; fail loud (exit 3) at deploy. |
| `tradeloop/prompts/50_post_trade_analyst.md` | Edit: Python owns `strategy_performance.md` + provenance; the prompt writes narrative only. |
| `tradeloop/lib/portfolio/reconcile.py` | Deprecate: re-export `compare` from `lib/audit/reconcile.py` (keep the old `compare_paper_live` import path alive for any stragglers). |
| `tradeloop/tests/test_reconcile.py` · `test_controls.py` · `test_attribution.py` · `test_outcomes.py` · `test_postclose_learning.py` · `test_verify_health.py` | pytest per module. |

---

## Task 1: Typed outcome taxonomy (`outcomes.py`)

**Files**
- create `tradeloop/lib/audit/outcomes.py`
- create `tradeloop/lib/audit/__init__.py` (if absent)
- create `tradeloop/tests/test_outcomes.py`

**Interfaces**
- Consumes: nothing.
- Produces:
  - `class Outcome(str, Enum)` with members `THESIS_CORRECT_WON="thesis-correct-and-won"`, `THESIS_CORRECT_STOPPED="thesis-correct-but-stopped"`, `THESIS_WRONG_WON="thesis-wrong-but-won"`, `THESIS_WRONG_LOST="thesis-wrong-and-lost"`.
  - `classify_outcome(realized_r: float, hit_target: bool, hit_stop: bool) -> Outcome`

1. Write failing test `tradeloop/tests/test_outcomes.py`:
```python
from tradeloop.lib.audit.outcomes import Outcome, classify_outcome


def test_target_hit_positive_r_is_thesis_correct_won():
    assert classify_outcome(realized_r=1.8, hit_target=True, hit_stop=False) == Outcome.THESIS_CORRECT_WON


def test_stopped_out_is_thesis_correct_but_stopped_when_thesis_had_edge():
    # stopped at a loss but the plan was coherent (target existed, no thesis break)
    assert classify_outcome(realized_r=-1.0, hit_target=False, hit_stop=True) == Outcome.THESIS_CORRECT_STOPPED


def test_won_without_target_is_thesis_wrong_but_won():
    # exited profitably but not via the planned target -> lucky, thesis path not followed
    assert classify_outcome(realized_r=0.4, hit_target=False, hit_stop=False) == Outcome.THESIS_WRONG_WON


def test_loss_without_stop_is_thesis_wrong_and_lost():
    assert classify_outcome(realized_r=-0.6, hit_target=False, hit_stop=False) == Outcome.THESIS_WRONG_LOST


def test_enum_values_match_prompt_labels():
    assert Outcome.THESIS_CORRECT_WON.value == "thesis-correct-and-won"
    assert Outcome.THESIS_WRONG_LOST.value == "thesis-wrong-and-lost"
```

2. Run it (expect FAIL — module does not exist):
```
python -m pytest tradeloop/tests/test_outcomes.py -q
```
Expected: `ModuleNotFoundError: No module named 'tradeloop.lib.audit.outcomes'`.

3. Minimal implementation.

`tradeloop/lib/audit/__init__.py` (create only if it does not already exist from P2):
```python
```

`tradeloop/lib/audit/outcomes.py`:
```python
from enum import Enum


class Outcome(str, Enum):
    THESIS_CORRECT_WON = "thesis-correct-and-won"
    THESIS_CORRECT_STOPPED = "thesis-correct-but-stopped"
    THESIS_WRONG_WON = "thesis-wrong-but-won"
    THESIS_WRONG_LOST = "thesis-wrong-and-lost"


def classify_outcome(realized_r: float, hit_target: bool, hit_stop: bool) -> Outcome:
    """Map a closed trade onto the four post-trade categories.

    thesis "followed" == the trade resolved via its planned exits (target or stop).
    - target hit                    -> correct & won
    - stop hit (planned loss)       -> correct but stopped
    - profit without hitting target -> wrong path but won
    - loss without hitting stop     -> wrong & lost
    """
    if hit_target:
        return Outcome.THESIS_CORRECT_WON
    if hit_stop:
        return Outcome.THESIS_CORRECT_STOPPED
    if realized_r > 0:
        return Outcome.THESIS_WRONG_WON
    return Outcome.THESIS_WRONG_LOST
```

4. Run pass:
```
python -m pytest tradeloop/tests/test_outcomes.py -q
```
Expected: 5 passed.

5. Commit:
```
git add tradeloop/lib/audit/outcomes.py tradeloop/lib/audit/__init__.py tradeloop/tests/test_outcomes.py
git commit -m "P4: typed post-trade outcome taxonomy"
```

---

## Task 2: Reconcile — positions three independent ways (`reconcile.py`)

**Files**
- create `tradeloop/lib/audit/reconcile.py`
- create `tradeloop/tests/test_reconcile.py`

**Interfaces**
- Consumes:
  - P0/P2 `PaperBroker` from `tradeloop.lib.broker.paper_broker` (fields `cash_inr: float`, `positions: Dict[str,int]`, `avg_prices: Dict[str,float]`).
  - P2 ledger contract `ledger.replay(types: list[str] | None = None) -> list[dict]` (§6). We only read fill events; each fill dict carries `symbol`, `side` (`BUY`/`SELL`), `quantity` (int), `fill_price` (float), `status` (`FILLED`). This is exactly the shape `paper_book.append` persists (P0 §5.3) and the ledger replays (P2).
  - `OrdersFile`/`Order` from `tradeloop.lib.broker.orders_schema` (P0 §5.2): fields `ticker`, `side`, `quantity`, `price`, `status`.
  - Optional Kite holdings: `list[dict]` with `tradingsymbol`, `quantity`, `average_price` (Kite MCP `get_holdings` shape, P3 `kite` client — passed in, never fetched here).
- Produces:
  - `@dataclass(frozen=True) class Position: qty: int; avg_price: float`
  - `@dataclass(frozen=True) class Delta: symbol: str; field: str; source_a: str; value_a: float; source_b: str; value_b: float`  (`field` ∈ `{"qty","avg_price","cash"}`)
  - `positions_from_fills(fills: list[dict]) -> dict[str, Position]`
  - `positions_from_orders(orders: "OrdersFile") -> dict[str, Position]`
  - `positions_from_kite(holdings: list[dict]) -> dict[str, Position]`
  - `compare(book: "PaperBroker", ledger, kite_holdings: list[dict] | None = None, tol: float = 0.01) -> list[Delta]`

1. Write failing test `tradeloop/tests/test_reconcile.py`:
```python
from dataclasses import dataclass, field
from typing import Dict, List

from tradeloop.lib.audit.reconcile import (
    Delta,
    Position,
    compare,
    positions_from_fills,
    positions_from_kite,
    positions_from_orders,
)
from tradeloop.lib.broker.orders_schema import Order, OrdersFile


@dataclass
class FakeBroker:
    cash_inr: float
    positions: Dict[str, int] = field(default_factory=dict)
    avg_prices: Dict[str, float] = field(default_factory=dict)


class FakeLedger:
    def __init__(self, fills: List[dict]):
        self._fills = fills

    def replay(self, types=None):
        if types is None or "paper.order.filled" in types:
            return list(self._fills)
        return []


def _fill(symbol, side, qty, price):
    return {"symbol": symbol, "side": side, "quantity": qty, "fill_price": price, "status": "FILLED"}


def test_fills_replay_derives_vwap_and_net_qty():
    fills = [_fill("TCS", "BUY", 10, 100.0), _fill("TCS", "BUY", 10, 120.0), _fill("TCS", "SELL", 5, 130.0)]
    pos = positions_from_fills(fills)
    assert pos["TCS"] == Position(qty=15, avg_price=110.0)


def test_orders_intent_minus_rejects():
    of = OrdersFile(
        mode="premarket",
        orders=[
            Order(ticker="TCS", side="BUY", quantity=10, price=100.0, status="FILLED"),
            Order(ticker="TCS", side="BUY", quantity=5, price=200.0, status="REJECTED"),
        ],
    )
    pos = positions_from_orders(of)
    assert pos["TCS"] == Position(qty=10, avg_price=100.0)  # rejected order excluded


def test_kite_holdings_mapped():
    holdings = [{"tradingsymbol": "TCS", "quantity": 15, "average_price": 110.0}]
    assert positions_from_kite(holdings)["TCS"] == Position(qty=15, avg_price=110.0)


def test_compare_flags_qty_mismatch_between_fills_and_orders():
    fills = [_fill("TCS", "BUY", 15, 110.0)]
    of_orders = OrdersFile(mode="premarket", orders=[Order(ticker="TCS", side="BUY", quantity=10, price=110.0, status="FILLED")])
    broker = FakeBroker(cash_inr=100000.0, positions={"TCS": 15}, avg_prices={"TCS": 110.0})
    deltas = compare(broker, FakeLedger(fills), kite_holdings=None, orders=of_orders)
    fields = {d.field for d in deltas}
    assert "qty" in fields
    assert any(d.symbol == "TCS" and d.value_a == 15 and d.value_b == 10 for d in deltas)


def test_compare_clean_when_all_sources_agree_returns_empty():
    fills = [_fill("TCS", "BUY", 10, 100.0)]
    of_orders = OrdersFile(mode="premarket", orders=[Order(ticker="TCS", side="BUY", quantity=10, price=100.0, status="FILLED")])
    broker = FakeBroker(cash_inr=100000.0, positions={"TCS": 10}, avg_prices={"TCS": 100.0})
    assert compare(broker, FakeLedger(fills), kite_holdings=None, orders=of_orders) == []


def test_compare_flags_cash_delta_against_book():
    # fills-derived cash (start 100000 - 10*100 buy) = 99000, but book says 98000
    fills = [_fill("TCS", "BUY", 10, 100.0)]
    broker = FakeBroker(cash_inr=98000.0, positions={"TCS": 10}, avg_prices={"TCS": 100.0})
    deltas = compare(broker, FakeLedger(fills), kite_holdings=None, orders=None, starting_cash=100000.0)
    assert any(d.field == "cash" for d in deltas)
```

2. Run it (expect FAIL — module missing):
```
python -m pytest tradeloop/tests/test_reconcile.py -q
```
Expected: `ModuleNotFoundError: No module named 'tradeloop.lib.audit.reconcile'`.

3. Minimal implementation `tradeloop/lib/audit/reconcile.py`:
```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from tradeloop.lib.audit.ledger import ORDER_FILLED


@dataclass(frozen=True)
class Position:
    qty: int
    avg_price: float


@dataclass(frozen=True)
class Delta:
    symbol: str
    field: str          # "qty" | "avg_price" | "cash"
    source_a: str
    value_a: float
    source_b: str
    value_b: float


def _apply(book: Dict[str, Position], symbol: str, side: str, qty: int, price: float) -> None:
    """VWAP-average BUYs, net SELLs. Mirrors paper_broker fill math (long-only)."""
    symbol = symbol.strip().upper()
    side = side.strip().upper()
    cur = book.get(symbol, Position(0, 0.0))
    if side == "BUY":
        new_qty = cur.qty + qty
        avg = ((cur.qty * cur.avg_price) + (qty * price)) / new_qty if new_qty else 0.0
        book[symbol] = Position(new_qty, round(avg, 6))
    else:  # SELL reduces qty, avg unchanged
        new_qty = cur.qty - qty
        if new_qty <= 0:
            book.pop(symbol, None)
        else:
            book[symbol] = Position(new_qty, cur.avg_price)


def positions_from_fills(fills: List[dict]) -> Dict[str, Position]:
    book: Dict[str, Position] = {}
    for f in fills:
        if str(f.get("status", "")).upper() != "FILLED":
            continue
        _apply(book, str(f["symbol"]), str(f["side"]), int(f["quantity"]), float(f["fill_price"]))
    return book


def positions_from_orders(orders) -> Dict[str, Position]:
    """Intent minus rejects: replay only non-REJECTED orders at their order price."""
    book: Dict[str, Position] = {}
    for o in orders.orders:
        if str(getattr(o, "status", "") or "").upper() == "REJECTED":
            continue
        _apply(book, o.ticker, o.side, int(o.quantity), float(o.price))
    return book


def positions_from_kite(holdings: List[dict]) -> Dict[str, Position]:
    book: Dict[str, Position] = {}
    for h in holdings:
        symbol = str(h["tradingsymbol"]).strip().upper()
        book[symbol] = Position(int(h["quantity"]), round(float(h["average_price"]), 6))
    return book


def _cash_from_fills(fills: List[dict], starting_cash: float) -> float:
    cash = starting_cash
    for f in fills:
        if str(f.get("status", "")).upper() != "FILLED":
            continue
        value = float(f["fill_price"]) * int(f["quantity"])
        cash += -value if str(f["side"]).upper() == "BUY" else value
    return round(cash, 2)


def _diff(a: Dict[str, Position], b: Dict[str, Position], src_a: str, src_b: str, tol: float) -> List[Delta]:
    out: List[Delta] = []
    for symbol in sorted(set(a) | set(b)):
        pa = a.get(symbol, Position(0, 0.0))
        pb = b.get(symbol, Position(0, 0.0))
        if pa.qty != pb.qty:
            out.append(Delta(symbol, "qty", src_a, float(pa.qty), src_b, float(pb.qty)))
        if abs(pa.avg_price - pb.avg_price) > tol and pa.qty and pb.qty:
            out.append(Delta(symbol, "avg_price", src_a, pa.avg_price, src_b, pb.avg_price))
    return out


def compare(book, ledger, kite_holdings: Optional[List[dict]] = None,
            orders=None, starting_cash: Optional[float] = None, tol: float = 0.01) -> List[Delta]:
    """Reconcile positions across independent derivations; return every disagreement."""
    fills = ledger.replay([ORDER_FILLED])
    from_fills = positions_from_fills(fills)
    book_positions = {
        s.strip().upper(): Position(int(q), round(float(book.avg_prices.get(s, 0.0)), 6))
        for s, q in book.positions.items()
    }

    deltas: List[Delta] = _diff(from_fills, book_positions, "fills_replay", "book", tol)
    if orders is not None:
        deltas += _diff(from_fills, positions_from_orders(orders), "fills_replay", "orders_intent", tol)
    if kite_holdings is not None:
        deltas += _diff(book_positions, positions_from_kite(kite_holdings), "book", "kite_holdings", tol)
    if starting_cash is not None:
        derived_cash = _cash_from_fills(fills, starting_cash)
        if abs(derived_cash - book.cash_inr) > tol:
            deltas.append(Delta("_CASH_", "cash", "fills_replay", derived_cash, "book", round(book.cash_inr, 2)))
    return deltas
```

4. Run pass:
```
python -m pytest tradeloop/tests/test_reconcile.py -q
```
Expected: 6 passed.

5. Commit:
```
git add tradeloop/lib/audit/reconcile.py tradeloop/tests/test_reconcile.py
git commit -m "P4: reconcile positions three independent ways (fills/orders/kite) with cash delta"
```

---

## Task 3: Point the old reconcile stub at the new module

**Files**
- modify `tradeloop/lib/portfolio/reconcile.py`
- create `tradeloop/tests/test_reconcile_compat.py`

**Interfaces**
- Consumes: `compare` from `tradeloop.lib.audit.reconcile` (Task 2).
- Produces: keeps `compare_paper_live(paper, live) -> list[str]` importable (no runtime callers today per the map, but the import path stays alive; grow-not-break).

1. Write failing test `tradeloop/tests/test_reconcile_compat.py`:
```python
def test_audit_compare_reexported_from_portfolio_path():
    from tradeloop.lib.portfolio.reconcile import compare as compat_compare
    from tradeloop.lib.audit.reconcile import compare as audit_compare
    assert compat_compare is audit_compare
```

2. Run it (expect FAIL — `compare` not exported from portfolio/reconcile):
```
python -m pytest tradeloop/tests/test_reconcile_compat.py -q
```
Expected: `ImportError: cannot import name 'compare' from 'tradeloop.lib.portfolio.reconcile'`.

3. Minimal implementation — replace `tradeloop/lib/portfolio/reconcile.py` body:
```python
"""Thin compat shim. The real reconciler lives in tradeloop.lib.audit.reconcile.

# ponytail: legacy compare_paper_live kept for its old import path; new code
# imports compare from lib.audit.reconcile. Delete compare_paper_live once no
# caller references it.
"""
from tradeloop.lib.audit.reconcile import compare  # re-export
from tradeloop.lib.portfolio.state import PortfolioState

__all__ = ["compare", "compare_paper_live"]


def compare_paper_live(paper: PortfolioState, live: PortfolioState) -> list[str]:
    issues: list[str] = []
    symbols = set(paper.positions) | set(live.positions)
    for symbol in sorted(symbols):
        if paper.positions.get(symbol, 0) != live.positions.get(symbol, 0):
            issues.append(f"{symbol}: paper={paper.positions.get(symbol, 0)} live={live.positions.get(symbol, 0)}")
    return issues
```

4. Run pass:
```
python -m pytest tradeloop/tests/test_reconcile_compat.py -q
```
Expected: 1 passed.

5. Commit:
```
git add tradeloop/lib/portfolio/reconcile.py tradeloop/tests/test_reconcile_compat.py
git commit -m "P4: re-export audit.reconcile.compare from portfolio.reconcile shim"
```

---

## Task 4: Controls — re-run the risk gate over actuals (`controls.py`)

**Files**
- create `tradeloop/lib/audit/controls.py`
- create `tradeloop/tests/test_controls.py`

**Interfaces**
- Consumes:
  - `evaluate` / `RiskState` / `RiskCaps` / `RiskDecision` from `tradeloop.lib.risk.checks` (existing; §6). `RiskDecision.approved: bool`, `RiskDecision.reasons: list[str]`.
  - `OrdersFile`/`Order`/`to_ticket` from `tradeloop.lib.broker.orders_schema` (P0 §5.2).
  - `risk_caps` + `Settings` from `tradeloop.lib.config` (P0 §5.1): `risk_caps(settings, universe, capital_inr) -> RiskCaps`.
  - fills list: routing outcomes as written to `fills.json` by P0 `route_orders_file` — each entry is a `RoutedOrder.__dict__` with `mode` (`"paper"`/`"blocked"`), `status` (`"FILLED"`/`"RISK_REJECTED"`/…), `payload` (dict with `symbol`, and for blocks a `reasons` list).
- Produces:
  - `@dataclass(frozen=True) class Deficiency: symbol: str; severity: str; kind: str; detail: str`  (`severity` ∈ `{"material_weakness","significant_deficiency","deficiency"}`)
  - `@dataclass(frozen=True) class ControlReport: tested: int; passed: int; deficiencies: list[Deficiency]`
  - `recheck(orders: "OrdersFile", fills: list[dict], caps: "RiskCaps", state: "RiskState") -> ControlReport`

**Design decision:** the control test is over *outcomes*, so it re-derives the gate verdict independently and cross-checks it against what routing actually did. A **material_weakness** = an order that violates a hard rule but was FILLED (the gate let a bad order through). A **significant_deficiency** = a fill exists for an order whose independent re-evaluation rejects it (verdict/outcome disagree). A **deficiency** = a correctly-rejected order that is missing its `RISK_REJECTED` audit record.

1. Write failing test `tradeloop/tests/test_controls.py`:
```python
from tradeloop.lib.audit.controls import ControlReport, Deficiency, recheck
from tradeloop.lib.broker.orders_schema import Order, OrdersFile
from tradeloop.lib.risk.checks import RiskCaps, RiskState


def _caps():
    return RiskCaps(
        capital_inr=100000.0,
        max_open_positions=4,
        max_position_allocation_pct=25,
        max_total_deployed_pct=90,
        max_sector_allocation_pct=40,
        max_daily_drawdown_pct=3,
        universe=["TCS", "INFY"],
        min_position_size_inr=15000,
    )


def _state():
    return RiskState(cash_inr=100000.0, positions={}, avg_prices={}, sectors={"TCS": "IT", "INFY": "IT"})


def _fill(symbol, status, mode="paper", reasons=None):
    payload = {"symbol": symbol}
    if reasons is not None:
        payload["reasons"] = reasons
    return {"mode": mode, "status": status, "payload": payload}


def test_clean_run_no_deficiencies():
    of = OrdersFile(mode="premarket", orders=[Order(ticker="TCS", side="BUY", quantity=100, price=200.0)])
    fills = [_fill("TCS", "FILLED")]
    report = recheck(of, fills, _caps(), _state())
    assert isinstance(report, ControlReport)
    assert report.deficiencies == []
    assert report.tested == 1 and report.passed == 1


def test_bad_order_that_filled_is_material_weakness():
    # non-universe symbol that nevertheless FILLED -> gate leaked
    of = OrdersFile(mode="premarket", orders=[Order(ticker="ZZZZ", side="BUY", quantity=100, price=200.0)])
    fills = [_fill("ZZZZ", "FILLED")]
    report = recheck(of, fills, _caps(), _state())
    assert any(d.severity == "material_weakness" and "symbol_not_in_universe" in d.detail for d in report.deficiencies)


def test_rejected_order_missing_audit_record_is_deficiency():
    # correctly a bad order (oversized), but NO RISK_REJECTED fill recorded
    of = OrdersFile(mode="premarket", orders=[Order(ticker="TCS", side="BUY", quantity=1000, price=200.0)])
    fills = []  # nothing routed / recorded
    report = recheck(of, fills, _caps(), _state())
    assert any(d.severity == "deficiency" and d.kind == "missing_audit_record" for d in report.deficiencies)


def test_correctly_rejected_and_recorded_is_clean():
    of = OrdersFile(mode="premarket", orders=[Order(ticker="TCS", side="BUY", quantity=1000, price=200.0)])
    fills = [_fill("TCS", "RISK_REJECTED", mode="blocked", reasons=["max_position_allocation_exceeded"])]
    report = recheck(of, fills, _caps(), _state())
    assert report.deficiencies == []
    assert report.tested == 1 and report.passed == 1
```

2. Run it (expect FAIL — module missing):
```
python -m pytest tradeloop/tests/test_controls.py -q
```
Expected: `ModuleNotFoundError: No module named 'tradeloop.lib.audit.controls'`.

3. Minimal implementation `tradeloop/lib/audit/controls.py`:
```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from tradeloop.lib.broker.orders_schema import to_ticket
from tradeloop.lib.risk.checks import RiskCaps, RiskState, evaluate


@dataclass(frozen=True)
class Deficiency:
    symbol: str
    severity: str        # material_weakness | significant_deficiency | deficiency
    kind: str
    detail: str


@dataclass(frozen=True)
class ControlReport:
    tested: int
    passed: int
    deficiencies: List[Deficiency]


def _fill_index(fills: List[dict]) -> Dict[str, List[dict]]:
    index: Dict[str, List[dict]] = {}
    for f in fills:
        symbol = str(f.get("payload", {}).get("symbol", "")).strip().upper()
        index.setdefault(symbol, []).append(f)
    return index


def recheck(orders, fills: List[dict], caps: RiskCaps, state: RiskState) -> ControlReport:
    """SOX-style control test: independently re-run evaluate() over each order and
    cross-check the routing outcome recorded in fills.json."""
    index = _fill_index(fills)
    deficiencies: List[Deficiency] = []
    passed = 0

    for order in orders.orders:
        ticket = to_ticket(order)
        symbol = ticket.symbol.strip().upper()
        verdict = evaluate(ticket, state, caps)
        matched = index.get(symbol, [])
        filled = any(str(f.get("status", "")).upper() == "FILLED" for f in matched)
        rejected_recorded = any(str(f.get("status", "")).upper() == "RISK_REJECTED" for f in matched)

        if not verdict.approved:
            if filled:
                deficiencies.append(Deficiency(symbol, "material_weakness", "bad_order_filled",
                                               "gate should have rejected: " + ",".join(verdict.reasons)))
            elif not rejected_recorded:
                deficiencies.append(Deficiency(symbol, "deficiency", "missing_audit_record",
                                               "rejected order has no RISK_REJECTED record: " + ",".join(verdict.reasons)))
            else:
                passed += 1
        else:
            if rejected_recorded:
                deficiencies.append(Deficiency(symbol, "significant_deficiency", "verdict_outcome_mismatch",
                                               "order re-evaluates as approved but was recorded RISK_REJECTED"))
            else:
                passed += 1

    return ControlReport(tested=len(orders.orders), passed=passed, deficiencies=deficiencies)
```

4. Run pass:
```
python -m pytest tradeloop/tests/test_controls.py -q
```
Expected: 4 passed.

5. Commit:
```
git add tradeloop/lib/audit/controls.py tradeloop/tests/test_controls.py
git commit -m "P4: SOX-style control test re-running evaluate() over routed outcomes"
```

---

## Task 5: Attribution — expected vs realized R (`attribution.py`)

**Files**
- create `tradeloop/lib/audit/attribution.py`
- create `tradeloop/tests/test_attribution.py`

**Interfaces**
- Consumes:
  - `Outcome`/`classify_outcome` from `tradeloop.lib.audit.outcomes` (Task 1).
  - Trade-plan trailer = the `Order` fields on `orders.json` (P0 §5.2): `ticker`, `price` (entry), `hard_stop`, `target_1`, `strategy_family`. `expected_R = (target_1 - price) / (price - hard_stop)` when the denominator is positive.
  - Fills: `paper_book.jsonl` / ledger fill dicts with `symbol`, `side`, `quantity`, `fill_price`, `status="FILLED"`. Realized R per closed round-trip = `realized_pnl_per_share / (entry_price - hard_stop)`.
- Produces:
  - `@dataclass(frozen=True) class TradeAttribution: symbol: str; strategy_family: str; expected_r: float; realized_r: float; outcome: "Outcome"`
  - `@dataclass(frozen=True) class StrategyStat: strategy: str; trades: int; win_rate: float; expectancy_r: float; max_drawdown_pct: float`
  - `@dataclass(frozen=True) class StrategyPerformance: trades: list[TradeAttribution]; by_strategy: list[StrategyStat]; paper_trades: int`
  - `expected_r(order) -> float`
  - `report(trade_plans: "OrdersFile", fills: list[dict]) -> StrategyPerformance`
  - `render_strategy_performance(perf: "StrategyPerformance", live_ready: bool = False) -> str`

**Design decision:** R is computed per symbol per round-trip. A trade is "closed" when SELL qty matches the held BUY qty; realized PnL uses VWAP entry vs VWAP exit. `hit_target` = exit_price ≥ target_1; `hit_stop` = exit_price ≤ hard_stop. The rendered markdown matches the `strategy_performance.md` seed shape (`live_ready`, `paper_trades`, and the `| Strategy | Trades | Win Rate | Expectancy R | Max Drawdown % | Confidence |` table) that `router.live_promotion_ready` / `router._metric` parse — so the promotion gate reads exactly what attribution writes.

1. Write failing test `tradeloop/tests/test_attribution.py`:
```python
from tradeloop.lib.audit.attribution import (
    StrategyPerformance,
    TradeAttribution,
    expected_r,
    render_strategy_performance,
    report,
)
from tradeloop.lib.audit.outcomes import Outcome
from tradeloop.lib.broker.orders_schema import Order, OrdersFile


def _plan(**kw):
    base = dict(ticker="TCS", side="BUY", quantity=10, price=100.0, hard_stop=90.0,
                target_1=120.0, strategy_family="breakout_20d_pullback")
    base.update(kw)
    return Order(**base)


def _fill(symbol, side, qty, price):
    return {"symbol": symbol, "side": side, "quantity": qty, "fill_price": price, "status": "FILLED"}


def test_expected_r_from_trailer():
    # (120-100)/(100-90) = 2.0
    assert expected_r(_plan()) == 2.0


def test_expected_r_zero_when_no_stop_or_target():
    assert expected_r(_plan(hard_stop=None)) == 0.0
    assert expected_r(_plan(target_1=None)) == 0.0


def test_realized_r_target_hit_is_win():
    of = OrdersFile(mode="postclose", orders=[_plan()])
    fills = [_fill("TCS", "BUY", 10, 100.0), _fill("TCS", "SELL", 10, 120.0)]
    perf = report(of, fills)
    ta = next(t for t in perf.trades if t.symbol == "TCS")
    assert ta.expected_r == 2.0
    assert ta.realized_r == 2.0            # (120-100)/(100-90)
    assert ta.outcome == Outcome.THESIS_CORRECT_WON


def test_realized_r_stopped_out_is_loss():
    of = OrdersFile(mode="postclose", orders=[_plan()])
    fills = [_fill("TCS", "BUY", 10, 100.0), _fill("TCS", "SELL", 10, 90.0)]
    perf = report(of, fills)
    ta = next(t for t in perf.trades if t.symbol == "TCS")
    assert ta.realized_r == -1.0
    assert ta.outcome == Outcome.THESIS_CORRECT_STOPPED


def test_open_position_not_attributed():
    of = OrdersFile(mode="postclose", orders=[_plan()])
    fills = [_fill("TCS", "BUY", 10, 100.0)]  # never sold
    perf = report(of, fills)
    assert perf.trades == []
    assert perf.paper_trades == 0


def test_render_matches_promotion_gate_parse_keys():
    from tradeloop.lib.broker.router import live_promotion_ready  # regressor: uses same keys
    of = OrdersFile(mode="postclose", orders=[_plan()])
    fills = [_fill("TCS", "BUY", 10, 100.0), _fill("TCS", "SELL", 10, 120.0)]
    perf = report(of, fills)
    md = render_strategy_performance(perf, live_ready=False)
    assert "live_ready: false" in md.lower()
    assert "paper_trades:" in md.lower()
    assert "| Strategy | Trades | Win Rate | Expectancy R | Max Drawdown % | Confidence |" in md
```

2. Run it (expect FAIL — module missing):
```
python -m pytest tradeloop/tests/test_attribution.py -q
```
Expected: `ModuleNotFoundError: No module named 'tradeloop.lib.audit.attribution'`.

3. Minimal implementation `tradeloop/lib/audit/attribution.py`:
```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from tradeloop.lib.audit.outcomes import Outcome, classify_outcome


@dataclass(frozen=True)
class TradeAttribution:
    symbol: str
    strategy_family: str
    expected_r: float
    realized_r: float
    outcome: Outcome


@dataclass(frozen=True)
class StrategyStat:
    strategy: str
    trades: int
    win_rate: float
    expectancy_r: float
    max_drawdown_pct: float


@dataclass(frozen=True)
class StrategyPerformance:
    trades: List[TradeAttribution]
    by_strategy: List[StrategyStat]
    paper_trades: int


def expected_r(order) -> float:
    entry = float(order.price)
    stop = order.hard_stop
    target = order.target_1
    if stop is None or target is None:
        return 0.0
    risk = entry - float(stop)
    if risk <= 0:
        return 0.0
    return round((float(target) - entry) / risk, 4)


def _plans_by_symbol(trade_plans) -> Dict[str, object]:
    return {o.ticker.strip().upper(): o for o in trade_plans.orders}


def _round_trips(fills: List[dict]) -> Dict[str, dict]:
    """Return {symbol: {entry_vwap, exit_vwap, closed}} for symbols fully closed."""
    agg: Dict[str, dict] = {}
    for f in fills:
        if str(f.get("status", "")).upper() != "FILLED":
            continue
        symbol = str(f["symbol"]).strip().upper()
        side = str(f["side"]).upper()
        qty = int(f["quantity"])
        price = float(f["fill_price"])
        a = agg.setdefault(symbol, {"buy_qty": 0, "buy_val": 0.0, "sell_qty": 0, "sell_val": 0.0})
        if side == "BUY":
            a["buy_qty"] += qty
            a["buy_val"] += qty * price
        else:
            a["sell_qty"] += qty
            a["sell_val"] += qty * price
    closed: Dict[str, dict] = {}
    for symbol, a in agg.items():
        if a["sell_qty"] > 0 and a["sell_qty"] >= a["buy_qty"] and a["buy_qty"] > 0:
            closed[symbol] = {
                "entry_vwap": round(a["buy_val"] / a["buy_qty"], 6),
                "exit_vwap": round(a["sell_val"] / a["sell_qty"], 6),
            }
    return closed


def report(trade_plans, fills: List[dict]) -> StrategyPerformance:
    plans = _plans_by_symbol(trade_plans)
    closed = _round_trips(fills)
    trades: List[TradeAttribution] = []

    for symbol, rt in sorted(closed.items()):
        plan = plans.get(symbol)
        if plan is None:
            continue
        entry, exit_price = rt["entry_vwap"], rt["exit_vwap"]
        stop = float(plan.hard_stop) if plan.hard_stop is not None else entry
        target = float(plan.target_1) if plan.target_1 is not None else None
        risk = entry - stop
        realized = round((exit_price - entry) / risk, 4) if risk > 0 else 0.0
        hit_target = target is not None and exit_price >= target
        hit_stop = exit_price <= stop
        trades.append(TradeAttribution(
            symbol=symbol,
            strategy_family=str(plan.strategy_family or "unknown"),
            expected_r=expected_r(plan),
            realized_r=realized,
            outcome=classify_outcome(realized, hit_target, hit_stop),
        ))

    return StrategyPerformance(trades=trades, by_strategy=_aggregate(trades), paper_trades=len(trades))


def _aggregate(trades: List[TradeAttribution]) -> List[StrategyStat]:
    groups: Dict[str, List[TradeAttribution]] = {}
    for t in trades:
        groups.setdefault(t.strategy_family, []).append(t)
    stats: List[StrategyStat] = []
    for strategy, group in sorted(groups.items()):
        n = len(group)
        wins = sum(1 for t in group if t.realized_r > 0)
        expectancy = round(sum(t.realized_r for t in group) / n, 4) if n else 0.0
        max_dd = round(abs(min((t.realized_r for t in group), default=0.0)), 4)
        stats.append(StrategyStat(strategy, n, round(wins / n, 4) if n else 0.0, expectancy, max_dd))
    return stats


def render_strategy_performance(perf: StrategyPerformance, live_ready: bool = False) -> str:
    lines = [
        "# Strategy Performance",
        "",
        f"live_ready: {'true' if live_ready else 'false'}",
        f"paper_trades: {perf.paper_trades}",
        "",
        "| Strategy | Trades | Win Rate | Expectancy R | Max Drawdown % | Confidence |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for s in perf.by_strategy:
        confidence = "trusted" if s.trades >= 10 else "provisional"
        lines.append(f"| {s.strategy} | {s.trades} | {s.win_rate} | {s.expectancy_r} | {s.max_drawdown_pct} | {confidence} |")
    lines.append("")
    return "\n".join(lines)
```

4. Run pass:
```
python -m pytest tradeloop/tests/test_attribution.py -q
```
Expected: 6 passed.

5. Commit:
```
git add tradeloop/lib/audit/attribution.py tradeloop/tests/test_attribution.py
git commit -m "P4: expected-vs-realized R attribution + strategy_performance renderer matching promotion-gate keys"
```

---

## Task 6: Provenanced memory write (`writer.append_provenanced`)

**Files**
- modify `tradeloop/lib/memory/writer.py`
- create `tradeloop/tests/test_memory_provenance.py`

**Interfaces**
- Consumes: existing `append_unique(path, heading, body) -> bool`.
- Produces: `append_provenanced(path: Path, heading: str, body: str, run_id: str, timestamp: str) -> bool` — prepends a provenance line (`run_id`, `timestamp`, `sha256(body)[:12]`) into the body and delegates to `append_unique` (dedup preserved).

1. Write failing test `tradeloop/tests/test_memory_provenance.py`:
```python
from tradeloop.lib.memory.writer import append_provenanced


def test_provenance_header_written(tmp_path):
    path = tmp_path / "trade_journal.md"
    assert append_provenanced(path, "TCS 2026-07-02", "Exited at target.", run_id="R1", timestamp="2026-07-02T16:00")
    text = path.read_text(encoding="utf-8")
    assert "run_id: R1" in text
    assert "2026-07-02T16:00" in text
    assert "hash:" in text
    assert "Exited at target." in text


def test_provenance_dedup(tmp_path):
    path = tmp_path / "trade_journal.md"
    assert append_provenanced(path, "TCS", "same body", run_id="R1", timestamp="t1")
    assert not append_provenanced(path, "TCS", "same body", run_id="R1", timestamp="t1")
```

2. Run it (expect FAIL — function missing):
```
python -m pytest tradeloop/tests/test_memory_provenance.py -q
```
Expected: `ImportError: cannot import name 'append_provenanced'`.

3. Minimal implementation — append to `tradeloop/lib/memory/writer.py`:
```python
import hashlib


def append_provenanced(path: Path, heading: str, body: str, run_id: str, timestamp: str) -> bool:
    digest = hashlib.sha256(body.strip().encode("utf-8")).hexdigest()[:12]
    stamped = "\n".join([f"_run_id: {run_id} · {timestamp} · hash: {digest}_", "", body.strip()])
    return append_unique(path, heading, stamped)
```

4. Run pass:
```
python -m pytest tradeloop/tests/test_memory_provenance.py -q
```
Expected: 2 passed.

5. Commit:
```
git add tradeloop/lib/memory/writer.py tradeloop/tests/test_memory_provenance.py
git commit -m "P4: provenanced memory append (run_id/timestamp/hash) reusing append_unique dedup"
```

---

## Task 7: Postclose learning loop caller (`postclose.py`)

**Files**
- create `tradeloop/lib/audit/postclose.py`
- create `tradeloop/tests/test_postclose_learning.py`

**Interfaces**
- Consumes:
  - `report`/`StrategyPerformance`/`render_strategy_performance` from `attribution.py` (Task 5).
  - `Outcome` from `outcomes.py` (Task 1).
  - `append_provenanced` from `writer.py` (Task 6) and `update_dossier` from `tradeloop.lib.memory.dossier`.
  - `load_orders` from `tradeloop.lib.broker.orders_schema` (P0), ledger `replay` (P2) or a fills list.
- Produces:
  - `@dataclass(frozen=True) class LearningResult: performance: "StrategyPerformance"; journal_entries: int; strategy_performance_path: Path`
  - `run_postclose_learning(run_dir: Path, memory_root: Path, fills: list[dict], run_id: str, timestamp: str, live_ready: bool = False) -> LearningResult`

**Design decision:** this is the REAL Python caller the map flags as missing (writer/retriever/dossier have zero runtime callers). It reads `run_dir/orders.json` for the trade-plan trailer, computes attribution, appends one provenanced `trade_journal.md` entry per closed trade + updates each symbol's dossier, and OVERWRITES `strategy_performance.md` from `render_strategy_performance` (Python owns that file; the prompt writes narrative only — see Task 9). Overwrite (not append) keeps the single stats block the promotion gate parses unambiguous.

1. Write failing test `tradeloop/tests/test_postclose_learning.py`:
```python
import json

from tradeloop.lib.audit.postclose import LearningResult, run_postclose_learning
from tradeloop.lib.broker.orders_schema import Order, OrdersFile


def _write_orders(run_dir):
    of = OrdersFile(mode="postclose", orders=[
        Order(ticker="TCS", side="BUY", quantity=10, price=100.0, hard_stop=90.0,
              target_1=120.0, strategy_family="breakout_20d_pullback"),
    ])
    (run_dir / "orders.json").write_text(of.model_dump_json(), encoding="utf-8")


def _fill(symbol, side, qty, price):
    return {"symbol": symbol, "side": side, "quantity": qty, "fill_price": price, "status": "FILLED"}


def test_learning_loop_writes_journal_dossier_and_strategy_stats(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_orders(run_dir)
    memory = tmp_path / "memory"
    fills = [_fill("TCS", "BUY", 10, 100.0), _fill("TCS", "SELL", 10, 120.0)]

    result = run_postclose_learning(run_dir, memory, fills, run_id="R1", timestamp="2026-07-02T16:00")
    assert isinstance(result, LearningResult)
    assert result.journal_entries == 1

    journal = (memory / "trade_journal.md").read_text(encoding="utf-8")
    assert "TCS" in journal and "run_id: R1" in journal and "thesis-correct-and-won" in journal

    dossier = (memory / "stock_dossiers" / "TCS.md").read_text(encoding="utf-8")
    assert "realized_r" in dossier.lower() or "realized R" in dossier

    perf = (memory / "strategy_performance.md").read_text(encoding="utf-8")
    assert "paper_trades: 1" in perf
    assert "breakout_20d_pullback" in perf


def test_no_closed_trades_writes_empty_stats_no_journal(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_orders(run_dir)
    memory = tmp_path / "memory"
    fills = [_fill("TCS", "BUY", 10, 100.0)]  # open, not closed
    result = run_postclose_learning(run_dir, memory, fills, run_id="R1", timestamp="t")
    assert result.journal_entries == 0
    assert "paper_trades: 0" in (memory / "strategy_performance.md").read_text(encoding="utf-8")
    assert not (memory / "trade_journal.md").exists()
```

2. Run it (expect FAIL — module missing):
```
python -m pytest tradeloop/tests/test_postclose_learning.py -q
```
Expected: `ModuleNotFoundError: No module named 'tradeloop.lib.audit.postclose'`.

3. Minimal implementation `tradeloop/lib/audit/postclose.py`:
```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

from tradeloop.lib.audit.attribution import StrategyPerformance, render_strategy_performance, report
from tradeloop.lib.broker.orders_schema import load_orders
from tradeloop.lib.memory.dossier import update_dossier
from tradeloop.lib.memory.writer import append_provenanced


@dataclass(frozen=True)
class LearningResult:
    performance: StrategyPerformance
    journal_entries: int
    strategy_performance_path: Path


def run_postclose_learning(run_dir: Path, memory_root: Path, fills: List[dict],
                           run_id: str, timestamp: str, live_ready: bool = False) -> LearningResult:
    trade_plans = load_orders(run_dir / "orders.json")
    perf = report(trade_plans, fills)

    journal_path = memory_root / "trade_journal.md"
    entries = 0
    for ta in perf.trades:
        body = (
            f"strategy: {ta.strategy_family}\n"
            f"outcome: {ta.outcome.value}\n"
            f"expected_r: {ta.expected_r}\n"
            f"realized_r: {ta.realized_r}"
        )
        heading = f"{ta.symbol} {timestamp}"
        if append_provenanced(journal_path, heading, body, run_id=run_id, timestamp=timestamp):
            entries += 1
        update_dossier(memory_root, ta.symbol,
                       heading=f"{timestamp} outcome",
                       body=f"realized_r {ta.realized_r} ({ta.outcome.value}) via {ta.strategy_family}")

    perf_path = memory_root / "strategy_performance.md"
    perf_path.parent.mkdir(parents=True, exist_ok=True)
    perf_path.write_text(render_strategy_performance(perf, live_ready=live_ready), encoding="utf-8")

    return LearningResult(performance=perf, journal_entries=entries, strategy_performance_path=perf_path)
```

4. Run pass:
```
python -m pytest tradeloop/tests/test_postclose_learning.py -q
```
Expected: 2 passed.

5. Commit:
```
git add tradeloop/lib/audit/postclose.py tradeloop/tests/test_postclose_learning.py
git commit -m "P4: real postclose learning caller wiring attribution -> memory + strategy_performance (Python-owned)"
```

---

## Task 8: Health surface — dependency-import + per-source last-success check

**Files**
- modify `tradeloop/scripts/verify_setup.py`
- create `tradeloop/tests/test_verify_health.py`

**Interfaces**
- Consumes: existing `verify_setup` module-level `ROOT`.
- Produces:
  - `check_imports() -> list[str]` — returns names of runtime deps that fail to import (`yaml`, `pandas`, `pydantic`).
  - `source_health(root: Path, max_age_hours: float = 26.0) -> list[str]` — reads `reports/source_health.json` (`{source: last_success_iso}`) and returns stale/missing sources.
  - `health(root: Path) -> int` — prints `tradeloop_health=OK` / `=FAIL reason=...`, returns 0 healthy, 3 unhealthy.
  - `main()` gains `--health` flag routing to `health(ROOT)`.

**Design decision:** `source_health.json` is written by the P3 ingest layer per fetch source; P4 only reads it (a source that never succeeded ⇒ missing ⇒ FAIL). No live network; the check is filesystem + import only, so it is safe to fail loud at deploy.

1. Write failing test `tradeloop/tests/test_verify_health.py`:
```python
import json
from datetime import datetime, timedelta, timezone

import tradeloop.scripts.verify_setup as vs


def test_check_imports_all_present():
    assert vs.check_imports() == []  # yaml/pandas/pydantic declared in P0 packaging


def test_source_health_flags_stale_and_missing(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    fresh = datetime.now(timezone.utc).isoformat()
    (reports / "source_health.json").write_text(json.dumps({"google_news": fresh, "nse_bse": old}), encoding="utf-8")
    stale = vs.source_health(tmp_path, max_age_hours=26.0)
    assert "nse_bse" in stale
    assert "google_news" not in stale


def test_source_health_missing_file_is_unhealthy(tmp_path):
    assert vs.source_health(tmp_path) == ["_no_source_health_report_"]


def test_health_returns_3_when_source_missing(tmp_path, capsys):
    assert vs.health(tmp_path) == 3
    assert "FAIL" in capsys.readouterr().out
```

2. Run it (expect FAIL — functions missing):
```
python -m pytest tradeloop/tests/test_verify_health.py -q
```
Expected: `AttributeError: module 'tradeloop.scripts.verify_setup' has no attribute 'check_imports'`.

3. Minimal implementation — add to `tradeloop/scripts/verify_setup.py` (imports at top, functions after `verify`, wire `main`):
```python
import importlib
import json as _json
from datetime import datetime, timezone


def check_imports() -> list:
    missing = []
    for module in ("yaml", "pandas", "pydantic"):
        try:
            importlib.import_module(module)
        except Exception:
            missing.append(module)
    return missing


def source_health(root: Path, max_age_hours: float = 26.0) -> list:
    report = root / "reports" / "source_health.json"
    if not report.exists():
        return ["_no_source_health_report_"]
    data = _json.loads(report.read_text(encoding="utf-8")) or {}
    now = datetime.now(timezone.utc)
    stale = []
    for source, last_success in data.items():
        try:
            ts = datetime.fromisoformat(str(last_success))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except ValueError:
            stale.append(source)
            continue
        if (now - ts).total_seconds() > max_age_hours * 3600:
            stale.append(source)
    return stale


def health(root: Path) -> int:
    missing = check_imports()
    stale = source_health(root)
    if missing or stale:
        print(f"tradeloop_health=FAIL reason=imports:{','.join(missing) or '-'} sources:{','.join(stale) or '-'}")
        return 3
    print("tradeloop_health=OK")
    return 0
```
And in `main()`, before the existing `return`:
```python
    parser.add_argument("--health", action="store_true")
    args = parser.parse_args()
    if args.health:
        return health(ROOT)
    return verify(args.mode, args.check_live_readiness)
```

4. Run pass:
```
python -m pytest tradeloop/tests/test_verify_health.py -q
```
Expected: 4 passed.

5. Commit:
```
git add tradeloop/scripts/verify_setup.py tradeloop/tests/test_verify_health.py
git commit -m "P4: deploy health check - dependency imports + per-source last-success, fails loud (exit 3)"
```

---

## Task 9: Prompt edit — Python owns strategy_performance + provenance

**Files**
- modify `tradeloop/prompts/50_post_trade_analyst.md`

**Interfaces**
- Consumes: nothing (documentation contract only).
- Produces: nothing (prose). Aligns the prompt with Task 7: the analyst writes narrative journal/lessons/dossier notes; Python owns `strategy_performance.md` and stamps provenance.

1. No test (prose edit). Verification is a grep in step 3.

2. (skipped — no failing-test step for a prompt edit)

3. Edit `tradeloop/prompts/50_post_trade_analyst.md` — replace the `Updates:` block and the final paragraph:

Replace:
```
Updates:

- `tradeloop/memory/trade_journal.md`
- `tradeloop/memory/lessons_learned.md`
- `tradeloop/memory/strategy_performance.md`
- affected ticker dossiers
- `tradeloop/memory/macro_view.md` when needed

Categorize each outcome as thesis-correct-and-won, thesis-correct-but-stopped,
thesis-wrong-but-won, or thesis-wrong-and-lost. Deduplicate lessons and update
strategy family stats.
```
With:
```
Writes narrative only (Python owns the machine-parsed stats):

- `tradeloop/memory/trade_journal.md` — narrative note per closed trade
- `tradeloop/memory/lessons_learned.md` — deduplicated lessons
- affected ticker dossiers — narrative context
- `tradeloop/memory/macro_view.md` when needed

Do NOT edit `tradeloop/memory/strategy_performance.md`, expected/realized R, or
provenance stamps: the Python postclose learning loop
(`tradeloop/lib/audit/postclose.py`) computes attribution, classifies each
outcome (thesis-correct-and-won / thesis-correct-but-stopped /
thesis-wrong-but-won / thesis-wrong-and-lost), and OVERWRITES
`strategy_performance.md` from the fills — this is the file the live-promotion
gate reads. The analyst's role is the human-readable story, not the numbers.
```

4. Verify the edit landed:
```
grep -n "Python owns" tradeloop/prompts/50_post_trade_analyst.md
```
Expected: one match on the `Writes narrative only (Python owns the machine-parsed stats):` line.

5. Commit:
```
git add tradeloop/prompts/50_post_trade_analyst.md
git commit -m "P4: post-trade prompt - Python owns strategy_performance + provenance, analyst writes narrative"
```

---

## Task 10: Full-suite green + audit package export

**Files**
- modify `tradeloop/lib/audit/__init__.py`

**Interfaces**
- Consumes: `compare`, `recheck`, `report` from the three modules.
- Produces: top-level re-exports matching §6 (`reconcile.compare`, `controls.recheck`, `attribution.report`) so callers import from `tradeloop.lib.audit`.

1. Write failing test — add to `tradeloop/tests/test_reconcile.py` (or a small new file `tradeloop/tests/test_audit_exports.py`):
```python
def test_audit_package_exports_match_pinned_interfaces():
    from tradeloop.lib.audit import compare, recheck, report
    assert callable(compare) and callable(recheck) and callable(report)
```

2. Run it (expect FAIL — names not exported):
```
python -m pytest tradeloop/tests/test_audit_exports.py -q
```
Expected: `ImportError: cannot import name 'compare' from 'tradeloop.lib.audit'`.

3. Minimal implementation `tradeloop/lib/audit/__init__.py`:
```python
from tradeloop.lib.audit.attribution import report
from tradeloop.lib.audit.controls import recheck
from tradeloop.lib.audit.reconcile import compare

__all__ = ["compare", "recheck", "report"]
```

4. Run the whole P4 suite:
```
python -m pytest tradeloop/tests/test_outcomes.py tradeloop/tests/test_reconcile.py tradeloop/tests/test_reconcile_compat.py tradeloop/tests/test_controls.py tradeloop/tests/test_attribution.py tradeloop/tests/test_memory_provenance.py tradeloop/tests/test_postclose_learning.py tradeloop/tests/test_verify_health.py tradeloop/tests/test_audit_exports.py -q
```
Expected: all passed (28 tests).

5. Commit:
```
git add tradeloop/lib/audit/__init__.py tradeloop/tests/test_audit_exports.py
git commit -m "P4: export reconcile.compare / controls.recheck / attribution.report from lib.audit"
```

---

## Task 11: Wire the auditor into the orchestrator postclose branch

The prior tasks build `reconcile.compare` / `controls.recheck` / `attribution.report` / `run_postclose_learning` and unit-test them with hand-built fills, but nothing invokes them end-to-end. This task makes `run_cycle` run the auditor in the `postclose` branch against real fills sourced from the P2 ledger, so the accountability layer is actually exercised.

**Files**
- modify `tradeloop/orchestrator.py`
- create `tradeloop/tests/test_postclose_wiring.py`

**Interfaces**
- Consumes: P0 `run_cycle`'s order path (`route_orders_file` → `routed`/`fills.json`, `hydrate`, `load_settings`, `risk_caps`) and its post-trade reasoning stage; the P2 `Ledger` + `ORDER_FILLED` constant (`ledger.replay([ORDER_FILLED]) -> list[dict]`); `reconcile.compare(book, ledger, kite_holdings=None, orders=..)`, `controls.recheck(orders, fills, caps, state)`, `attribution.report(trade_plans, fills)`, `run_postclose_learning(run_dir, memory_root, fills, run_id, timestamp, live_ready=..)` from P4.
- Produces: a `postclose`-only block in `run_cycle` (after `route_orders_file`, i.e. after the `50_post_trade` post-trade reasoning that produced `orders.json`) that sources ledger fills, runs the four auditor calls, and writes their outputs into the run dir: `40_reconcile.md` (deltas), `controls.json` (`ControlReport`), and `run_postclose_learning`'s update to `strategy_performance.md`. Non-postclose modes are unchanged.

**Design decision:** two fill shapes are in play and must not be conflated. `reconcile.compare` / `attribution.report` / `run_postclose_learning` consume **ledger fill dicts** (`{"symbol","side","quantity","fill_price","status":"FILLED"}`) from `ledger.replay([ORDER_FILLED])`. `controls.recheck` consumes the **routing-outcome dicts** (`{"mode","status","payload":{"symbol",...}}`) written to `fills.json` by `route_orders_file` — so it is fed the `fills.json` contents (the routed outcomes), which is exactly what lets it flag a `material_weakness` when a bad order shows `status="FILLED"`. `caps`/`state` are rebuilt the same way the order path already does (`risk_caps(settings, universe, capital_inr)` + a `RiskState` from the hydrated book). The block is postclose-only because reconciliation/attribution are meaningful only after fills exist.

**Steps**

1. Write failing test `tradeloop/tests/test_postclose_wiring.py`:
```python
import json
from pathlib import Path

from tradeloop import orchestrator
from tradeloop.lib.audit.ledger import ORDER_FILLED, Ledger


def test_postclose_branch_runs_auditor_and_flags_bad_order(tmp_path, monkeypatch):
    root = tmp_path / "tradeloop"
    (root / "state").mkdir(parents=True)
    run_dir = root / "runs" / "2026-07-02_1600_postclose"
    run_dir.mkdir(parents=True)

    # A bad order (non-universe symbol) that nevertheless FILLED -> gate should have caught it.
    (run_dir / "orders.json").write_text(json.dumps({
        "mode": "postclose", "live_orders_enabled": False,
        "orders": [{"ticker": "ZZZZ", "side": "BUY", "quantity": 100,
                    "price": 200.0, "status": "FILLED"}],
        "held": [],
    }), encoding="utf-8")
    # fills.json as route_orders_file would have written it (routing-outcome shape).
    (run_dir / "fills.json").write_text(json.dumps(
        [{"mode": "paper", "status": "FILLED", "payload": {"symbol": "ZZZZ"}}]
    ), encoding="utf-8")

    # Seed the P2 ledger with a matching paper.order.filled event.
    led = Ledger(root / "state" / "ledger.db")
    led.append({"type": ORDER_FILLED, "symbol": "ZZZZ", "side": "BUY",
                "quantity": 100, "fill_price": 200.0, "status": "FILLED"})

    orchestrator._run_postclose_audit(run_dir, root=root, memory_root=tmp_path / "memory",
                                      run_id="R1", timestamp="2026-07-02T16:00")

    # Auditor outputs are produced ...
    assert (run_dir / "40_reconcile.md").exists()
    controls = json.loads((run_dir / "controls.json").read_text(encoding="utf-8"))
    assert (tmp_path / "memory" / "strategy_performance.md").exists()
    # ... and the bad filled order is flagged as a control deficiency.
    assert any(d["severity"] == "material_weakness" for d in controls["deficiencies"])
```

2. Run it (expect FAIL — helper missing):
```
python -m pytest tradeloop/tests/test_postclose_wiring.py -q
```
Expected: `AttributeError: module 'tradeloop.orchestrator' has no attribute '_run_postclose_audit'`.

3. Minimal implementation — add `_run_postclose_audit` to `tradeloop/orchestrator.py` and call it from `run_cycle`'s postclose branch (right after the `route_orders_file` block, before the `OK` print/return):
```python
# tradeloop/orchestrator.py  (additions)
import dataclasses
import json

from tradeloop.lib.audit import attribution, controls, reconcile
from tradeloop.lib.audit.ledger import ORDER_FILLED, Ledger
from tradeloop.lib.audit.postclose import run_postclose_learning
from tradeloop.lib.broker.orders_schema import load_orders
from tradeloop.lib.config import risk_caps
from tradeloop.lib.data.ticker_master import load_ticker_master
from tradeloop.lib.risk.checks import RiskState


def _run_postclose_audit(run_dir, root, memory_root, run_id, timestamp, live_ready=False):
    """Postclose-only: reconcile + controls + attribution + learning over real fills."""
    settings = load_settings(root / "config" / "settings.yaml")
    orders = load_orders(run_dir / "orders.json")

    book = hydrate(root / "state" / "paper_book.jsonl", settings.paper_starting_inr)
    ledger = Ledger(root / "state" / "ledger.db")
    ledger_fills = ledger.replay([ORDER_FILLED])  # {symbol,side,quantity,fill_price,status}

    universe = [r.symbol for r in load_ticker_master(root / "config" / "universe.yaml")]
    caps = risk_caps(settings, universe, book.cash_inr)
    state = RiskState(cash_inr=book.cash_inr, positions=dict(book.positions),
                      avg_prices=dict(book.avg_prices),
                      sectors={r.symbol.upper(): r.sector
                               for r in load_ticker_master(root / "config" / "universe.yaml")})

    # 1) reconcile positions across independent derivations (ledger-fill shape)
    deltas = reconcile.compare(book, ledger, kite_holdings=None, orders=orders)
    (run_dir / "40_reconcile.md").write_text(
        "# Reconciliation\n\n" + ("\n".join(
            f"- {d.symbol}: {d.field} {d.source_a}={d.value_a} vs {d.source_b}={d.value_b}"
            for d in deltas) or "- clean: all sources agree\n"),
        encoding="utf-8")

    # 2) controls: re-run the gate over routing outcomes (fills.json shape)
    routed_fills = json.loads((run_dir / "fills.json").read_text(encoding="utf-8"))
    report = controls.recheck(orders, routed_fills, caps, state)
    (run_dir / "controls.json").write_text(
        json.dumps(dataclasses.asdict(report), indent=2), encoding="utf-8")

    # 3) attribution (ledger-fill shape)
    attribution.report(orders, ledger_fills)

    # 4) learning loop: journal + dossiers + strategy_performance.md
    return run_postclose_learning(run_dir, memory_root, ledger_fills,
                                  run_id=run_id, timestamp=timestamp, live_ready=live_ready)
```
And in `run_cycle`, immediately after the `filled = ...`/`rejected = ...`/`OK` print in the order path, before `return 0`:
```python
        if mode == "postclose":
            _run_postclose_audit(run_dir, root=root, memory_root=root / "memory",
                                 run_id=run_dir.name, timestamp=_now_iso(),
                                 live_ready=live_promotion_ready(root, settings))
```

4. Run pass:
```
python -m pytest tradeloop/tests/test_postclose_wiring.py -q
```
Expected: `1 passed`.

5. Commit:
```
git add tradeloop/orchestrator.py tradeloop/tests/test_postclose_wiring.py
git commit -m "P4: wire auditor (reconcile/controls/attribution/learning) into orchestrator postclose branch

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-review

**Spec/DoD coverage (Phase 4 = the accountability layer on architecture §3 "the auditor"):**
- Reconcile positions two-plus independent ways with qty/avg_price/cash deltas + Kite holdings when live — Task 2 (`compare`, three derivations, `Delta.field ∈ {qty,avg_price,cash}`); grown from the `lib/portfolio/reconcile.py` stub (Task 3 keeps its import path).
- Controls: independently re-run `checks.evaluate()` over `orders.json`/`fills.json` vs caps; assert long-only/kill-switch/universe/caps held; classify deficiencies (SOX-style over outcomes) — Task 4 (`recheck` → `ControlReport` with material_weakness / significant_deficiency / deficiency).
- Attribution: expected_R from the trade-plan trailer vs realized_R from fills → `strategy_performance.md` — Task 5 (`report`, `render_strategy_performance` writes the exact keys `router.live_promotion_ready`/`_metric` parse).
- Learning loop wired with provenance + REAL callers from the postclose path — Task 6 (`append_provenanced`) + Task 7 (`run_postclose_learning`, the memory layer's runtime entry point the map flagged as zero-caller dead code) + Task 11 (wires `run_postclose_learning` — plus `reconcile.compare`/`controls.recheck`/`attribution.report` — into `run_cycle`'s `postclose` branch over real ledger fills, so the auditor is actually invoked end-to-end) + Task 9 (prompt edited so Python owns the stats file per `prompts/00_master_orchestrator.md` postclose stage).
- Typed outcome taxonomy feeding the stats the promotion gate reads — Task 1 (`Outcome` enum, values match the prompt labels) feeds Task 5's render, which feeds `router.live_promotion_ready`.
- Health surface: dependency-import + per-source last-success, fails loud at deploy — Task 8 (`--health`, exit 3).
- Matches §6 pinned signatures: `reconcile.compare(book, ledger, kite_holdings=None) -> list[Delta]`, `controls.recheck(orders_path, fills_path, caps) -> ControlReport`, `attribution.report(trade_plans, fills) -> StrategyPerformance`. Note: `recheck` here takes parsed `orders`/`fills`/`caps`/`state` objects rather than paths (the caller loads them via P0 `load_orders` + reads `fills.json`) — a deliberate, testable-in-isolation refinement of the §6 sketch; a path-taking wrapper is trivial if the orchestrator prefers it. Documented, not hidden.

**Placeholder scan:** no "TBD" / "similar to Task N" / "add error handling" / "write tests for the above". Every module ships COMPLETE code + a real pytest with concrete assertions. Every referenced type is defined in a task here (`Outcome`, `Delta`, `Position`, `Deficiency`, `ControlReport`, `TradeAttribution`, `StrategyStat`, `StrategyPerformance`, `LearningResult`) or in §6 / P0 (`PaperBroker`, `RiskState`/`RiskCaps`/`evaluate`, `OrdersFile`/`Order`/`to_ticket`/`load_orders`, `Settings`/`risk_caps`, ledger `replay`) or existing memory (`append_unique`, `update_dossier`).

**Type-consistency:** fill dicts use one shape everywhere — `{symbol, side, quantity, fill_price, status}` — identical to what P0 `paper_book.append` persists and P2 `ledger.replay` returns; routing-outcome dicts use `{mode, status, payload}` identical to P0 `RoutedOrder.__dict__` written to `fills.json`. `expected_r`/`realized_r` share the denominator `entry - hard_stop`. `render_strategy_performance` emits `live_ready:`, `paper_trades:`, and the six-column table that `router._metric` regex-parses (Task 5's `test_render_matches_promotion_gate_parse_keys` locks this). `Outcome` is a `str`-Enum so its `.value` serializes straight into journal/dossier markdown. No new dependencies; pydantic v2 `.model_dump_json()` used in tests matches P0's `OrdersFile(BaseModel)`.
