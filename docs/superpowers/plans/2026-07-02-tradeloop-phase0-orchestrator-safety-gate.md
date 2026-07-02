# TradeLoop Phase 0 — Orchestrator Skeleton + Mandatory Risk Gate Implementation Plan

**Goal:** Make `evaluate()` run on every order before routing, enforce all hard caps in code, persist the paper book across cycles, and turn the holiday/kill-switch/promotion gates into real branches — all behind a Python orchestrator (`python -m tradeloop.orchestrator <mode>`), paper by default.

**Architecture:** A single Python orchestrator owns the cycle: it loads typed `Settings` from `config/settings.yaml`, runs three halt-gates (holiday / kill-switch / live-not-ready) as real branches, takes a global lockfile with a per-cycle timeout, scaffolds the run dir via existing `prepare_cycle.prepare`, runs the unchanged external reasoning backend behind a `_run_reasoning` seam, then runs a deterministic order path. The order path hydrates a persisted append-only JSONL paper book, parses the real `orders.json` object shape into typed `Order`/`OrdersFile`, builds `RiskState`+`RiskCaps` from the book + settings + universe, calls the existing `evaluate()` gate on every order, routes only approved orders through the existing `PaperBroker`, writes `fills.json`, and logs each gate verdict to `decisions.jsonl`.

**Tech Stack:** Python 3.11, pydantic v2 (already a dep), PyYAML + pandas (declared this phase), pytest with recorded fixtures only (no live network), stdlib `subprocess`/`fcntl`/`threading` for the orchestrator control flow.

## Global Constraints

- India cash equities only (segment EQ); no other segment routes.
- Long-only: `BUY` opens/adds, `SELL` exits only — enforced by `evaluate()` (`long_only_sell_exceeds_position`) and `PaperBroker`.
- No shorts, no F&O, no NRML, no leverage; `to_zerodha_payload` raises on NRML.
- Products: `CNC` or `MIS` only; `evaluate()` emits `unsupported_product` otherwise.
- `tradeloop/kill_switch.md` present ⇒ cycle HALTs before any order path (exit 0).
- Paper default: `ZERODHA_ENABLE_TRADING=false`; live only past the promotion gate (`settings.yaml live_promotion_gates`: min_paper_trades 40, min_win_rate 0.45, min_expectancy_r 0.3, max_drawdown_pct 8).
- The risk gate `checks.evaluate()` runs on **every** order before any fill.
- NSE holiday "today" ⇒ SKIP before reasoning (exit 0).
- Live-enabled but promotion not ready ⇒ LIVE_NOT_READY (exit 2).
- Security (AGENTS.md): never read/print `.env`; never log values whose name contains KEY/SECRET/TOKEN/PASSWORD/AUTH/CREDENTIAL. The reasoning subprocess sources `OPENROUTER_API_KEY` the same sanctioned way `run_cycle.sh` does and never prints it.

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` (modify) | Package `tradeloop*` alongside `tradingbot*`; declare `pandas` (PyYAML already declared). |
| `tradeloop/lib/config.py` (new) | `Settings` dataclass + `load_settings()` + `risk_caps()`; single source for caps/costs/promotion gates. |
| `tradeloop/lib/broker/orders_schema.py` (new) | Pydantic `Order`/`OrdersFile` matching real `orders.json`; `load_orders()`; `to_ticket()`. |
| `tradeloop/lib/broker/paper_book.py` (new) | `hydrate()`/`append()` — persisted append-only JSONL book replayed into a `PaperBroker`. |
| `tradeloop/lib/broker/router.py` (modify) | Rewrite `route_orders_file` to build `RiskState`+`RiskCaps`, call `evaluate()` on every order, route only approved, skip `held[]`, log `decisions.jsonl`; read promotion thresholds from `Settings`. |
| `tradeloop/lib/util/holidays.py` (modify) | Populate `NSE_HOLIDAYS_2026`. |
| `tradeloop/config/settings.yaml` (modify) | Add `capital.max_total_deployed_pct: 90` and top-level `cycle_timeout_seconds: 1200`. |
| `tradeloop/orchestrator.py` (new) | `python -m tradeloop.orchestrator <mode>`: gates → global lock → timeout → prepare → `_run_reasoning` seam → order path → summary. |
| `tradeloop/prompts/00_master_orchestrator.md` (modify) | Agent stops at `orders.json`; Python owns routing and `fills.json`. |
| `tradeloop/prompts/41_portfolio_manager.md` (modify) | PM writes `orders.json` only; does not write `fills.json`. |
| `tradeloop/tests/test_paper_book.py` (new) | Book hydrate/append round-trip + hydrated SELL. |
| `tradeloop/tests/test_orders_schema.py` (new) | Object shape parses, `held` preserved, legacy array parses, malformed raises. |
| `tradeloop/tests/test_config.py` (new) | Settings load + `risk_caps()` mapping + promotion thresholds from yaml. |
| `tradeloop/tests/test_router_gate.py` (new) | The four canonical rejections + hydrated SELL fills + object routes orders/skips held + malformed raises. |
| `tradeloop/tests/test_orchestrator.py` (new) | Holiday halt, kill-switch halt, malformed orders abort loud, packaging import. |

Existing tests `tradeloop/tests/test_paper_broker.py` and `test_sizing.py` are already present and passing; they are **kept as-is** (Task 12 only confirms they still pass — no port/rewrite needed since they already live in the package).

---

### Task 1: Fix packaging (package `tradeloop`, declare pandas)

**Files:** modify `pyproject.toml`; test `tradeloop/tests/test_orchestrator.py` (new file, packaging test only for now).

**Interfaces:**
- Consumes: nothing.
- Produces: importable `tradeloop.*` package on a clean install; `pandas` available for `lib/ta/indicators.py` and `lib/portfolio/state.py` (PyYAML).

1. Write failing test — create `tradeloop/tests/test_orchestrator.py`:
```python
import importlib


def test_tradeloop_package_is_importable() -> None:
    # tradeloop must be a real importable package (packaging fix), not only
    # reachable via a sys.path hack inside scripts.
    mod = importlib.import_module("tradeloop.lib.broker.paper_broker")
    assert hasattr(mod, "PaperBroker")
    orch = importlib.import_module("tradeloop.orchestrator")
    assert hasattr(orch, "main")
```
2. Run it — expect FAIL (`tradeloop.orchestrator` does not exist yet):
```
python -m pytest tradeloop/tests/test_orchestrator.py::test_tradeloop_package_is_importable -q
```
Expected: `ModuleNotFoundError: No module named 'tradeloop.orchestrator'`.
3. Minimal implementation — edit `pyproject.toml` `[tool.setuptools.packages.find]` and `dependencies`. Replace the packages-find block and add pandas:
```toml
dependencies = [
  "httpx>=0.27",
  "pydantic>=2.7",
  "PyYAML>=6.0",
  "pandas>=2.0",
  "yfinance>=0.2.40",
  "langgraph>=0.2.0"
]
```
```toml
[tool.setuptools.packages.find]
where = ["src", "."]
include = ["tradingbot*", "tradeloop*"]
```
The `tradeloop.orchestrator` module is created in Task 10; this task only fixes packaging + deps. The test still fails until Task 10 — that is expected; re-run it at Task 10. For this task, verify the packaging half passes by checking the import of an existing module:
```
python -c "import tradeloop.lib.broker.paper_broker; print('ok')"
```
4. Run pass — for this task the acceptance is the existing-module import above prints `ok`, and:
```
pip install -e . && python -c "import tradeloop.lib.risk.checks; print('installed-import ok')"
```
Expected: `ok` then `installed-import ok`.
5. Commit:
```
git commit -am "P0: package tradeloop and declare pandas dependency"
```

---

### Task 2: Populate NSE_HOLIDAYS_2026

**Files:** modify `tradeloop/lib/util/holidays.py`; test `tradeloop/tests/test_orchestrator.py`.

**Interfaces:**
- Consumes: `is_nse_holiday(day: date) -> bool` (existing signature, unchanged).
- Produces: non-empty `NSE_HOLIDAYS_2026: set[date]`.

1. Write failing test — append to `tradeloop/tests/test_orchestrator.py`:
```python
from datetime import date

from tradeloop.lib.util.holidays import NSE_HOLIDAYS_2026, is_nse_holiday


def test_republic_day_2026_is_a_holiday() -> None:
    assert is_nse_holiday(date(2026, 1, 26)) is True
    assert date(2026, 8, 15) in NSE_HOLIDAYS_2026  # Independence Day
    assert is_nse_holiday(date(2026, 7, 1)) is False  # ordinary weekday
    assert len(NSE_HOLIDAYS_2026) >= 12
```
2. Run it — expect FAIL:
```
python -m pytest tradeloop/tests/test_orchestrator.py::test_republic_day_2026_is_a_holiday -q
```
Expected: `assert False is True` (set is empty).
3. Minimal implementation — replace the body of `tradeloop/lib/util/holidays.py`:
```python
from datetime import date


# NSE trading holidays 2026 (full-day equity segment closures).
NSE_HOLIDAYS_2026: set[date] = {
    date(2026, 1, 26),   # Republic Day
    date(2026, 2, 16),   # Maha Shivratri
    date(2026, 3, 3),    # Holi
    date(2026, 3, 21),   # Id-Ul-Fitr (Ramzan Id)
    date(2026, 3, 27),   # Ram Navami
    date(2026, 4, 1),    # Mahavir Jayanti
    date(2026, 4, 3),    # Good Friday
    date(2026, 4, 14),   # Dr. Ambedkar Jayanti
    date(2026, 5, 1),    # Maharashtra Day
    date(2026, 5, 27),   # Bakri Id
    date(2026, 8, 15),   # Independence Day
    date(2026, 9, 14),   # Ganesh Chaturthi
    date(2026, 10, 2),   # Gandhi Jayanti
    date(2026, 10, 20),  # Dussehra
    date(2026, 11, 9),   # Diwali (Laxmi Pujan)
    date(2026, 11, 10),  # Diwali Balipratipada
    date(2026, 11, 24),  # Guru Nanak Jayanti
    date(2026, 12, 25),  # Christmas
}
# ponytail: hardcoded 2026 set; swap for an exchange-calendar lib when a second
# year is needed (the is_nse_holiday signature stays the same).


def is_nse_holiday(day: date) -> bool:
    return day in NSE_HOLIDAYS_2026
```
4. Run pass:
```
python -m pytest tradeloop/tests/test_orchestrator.py::test_republic_day_2026_is_a_holiday -q
```
Expected: `1 passed`.
5. Commit:
```
git commit -am "P0: populate NSE_HOLIDAYS_2026 so the holiday gate is real"
```

---

### Task 3: Add settings knobs (`max_total_deployed_pct`, `cycle_timeout_seconds`)

**Files:** modify `tradeloop/config/settings.yaml`; test `tradeloop/tests/test_config.py` (new, first case).

**Interfaces:**
- Consumes: nothing.
- Produces: `capital.max_total_deployed_pct: 90`, top-level `cycle_timeout_seconds: 1200` in the yaml (read by Tasks 4 and 10).

1. Write failing test — create `tradeloop/tests/test_config.py`:
```python
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_settings_yaml_has_phase0_knobs() -> None:
    data = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))
    assert data["capital"]["max_total_deployed_pct"] == 90
    assert data["cycle_timeout_seconds"] == 1200
```
2. Run it — expect FAIL:
```
python -m pytest tradeloop/tests/test_config.py::test_settings_yaml_has_phase0_knobs -q
```
Expected: `KeyError: 'max_total_deployed_pct'`.
3. Minimal implementation — edit `tradeloop/config/settings.yaml`. Add one line under `capital:` (after `daily_drawdown_circuit_pct: 3`):
```yaml
  max_total_deployed_pct: 90
```
Add a top-level line at the end of the file:
```yaml
cycle_timeout_seconds: 1200
```
4. Run pass:
```
python -m pytest tradeloop/tests/test_config.py::test_settings_yaml_has_phase0_knobs -q
```
Expected: `1 passed`.
5. Commit:
```
git commit -am "P0: add max_total_deployed_pct and cycle_timeout_seconds to settings"
```

---

### Task 4: Typed Settings loader + `risk_caps()`

**Files:** create `tradeloop/lib/config.py`; test `tradeloop/tests/test_config.py`.

**Interfaces:**
- Consumes: `settings.yaml` (Task 3); `RiskCaps` from `tradeloop.lib.risk.checks` (existing frozen dataclass).
- Produces:
  - `class Settings` (frozen) with fields: `raw: dict`, `paper_starting_inr: float`, `per_trade_risk_pct: float`, `max_open_positions: int`, `max_position_pct: float`, `max_total_deployed_pct: float`, `max_sector_pct: float`, `daily_drawdown_pct: float`, `max_open_risk_pct: float`, `min_position_size_inr: float`, `promotion_gates: dict`, `cycle_timeout_seconds: int`.
  - `load_settings(path: Path) -> Settings`
  - `risk_caps(settings: Settings, universe: Iterable[str], capital_inr: float) -> RiskCaps`

1. Write failing test — append to `tradeloop/tests/test_config.py`:
```python
from tradeloop.lib.config import load_settings, risk_caps


def test_load_settings_and_risk_caps_mapping() -> None:
    settings = load_settings(ROOT / "config" / "settings.yaml")
    assert settings.paper_starting_inr == 100000
    assert settings.max_open_positions == 4
    assert settings.max_position_pct == 25
    assert settings.max_total_deployed_pct == 90
    assert settings.max_sector_pct == 40
    assert settings.daily_drawdown_pct == 3
    assert settings.promotion_gates["min_paper_trades"] == 40
    assert settings.cycle_timeout_seconds == 1200

    caps = risk_caps(settings, ["RELIANCE", "TCS"], capital_inr=250000.0)
    assert caps.capital_inr == 250000.0
    assert caps.max_open_positions == 4
    assert caps.max_position_allocation_pct == 25
    assert caps.max_total_deployed_pct == 90
    assert caps.max_sector_allocation_pct == 40
    assert caps.max_daily_drawdown_pct == 3
    assert caps.max_open_risk_pct == 4.0
    assert caps.min_position_size_inr == 15000
    assert set(caps.universe) == {"RELIANCE", "TCS"}
```
2. Run it — expect FAIL:
```
python -m pytest tradeloop/tests/test_config.py::test_load_settings_and_risk_caps_mapping -q
```
Expected: `ModuleNotFoundError: No module named 'tradeloop.lib.config'`.
3. Minimal implementation — create `tradeloop/lib/config.py`:
```python
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

from tradeloop.lib.risk.checks import RiskCaps


@dataclass(frozen=True)
class Settings:
    raw: dict
    paper_starting_inr: float
    per_trade_risk_pct: float
    max_open_positions: int
    max_position_pct: float
    max_total_deployed_pct: float
    max_sector_pct: float
    daily_drawdown_pct: float
    max_open_risk_pct: float
    min_position_size_inr: float
    promotion_gates: dict
    cycle_timeout_seconds: int


def load_settings(path: Path) -> Settings:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    capital = data.get("capital", {})
    gates = data.get("live_promotion_gates", {})
    return Settings(
        raw=data,
        paper_starting_inr=float(capital.get("paper_starting_inr", 100000)),
        per_trade_risk_pct=float(capital.get("per_trade_risk_pct", 1.5)),
        max_open_positions=int(capital.get("max_concurrent_positions", 4)),
        max_position_pct=float(capital.get("max_position_pct", 25)),
        max_total_deployed_pct=float(capital.get("max_total_deployed_pct", 90)),
        max_sector_pct=float(capital.get("max_sector_exposure_pct", 40)),
        daily_drawdown_pct=float(capital.get("daily_drawdown_circuit_pct", 3)),
        max_open_risk_pct=float(capital.get("max_open_risk_pct", 4.0)),
        min_position_size_inr=float(capital.get("min_position_size_inr", 15000)),
        promotion_gates=dict(gates),
        cycle_timeout_seconds=int(data.get("cycle_timeout_seconds", 1200)),
    )


def risk_caps(settings: Settings, universe: Iterable[str], capital_inr: float) -> RiskCaps:
    return RiskCaps(
        capital_inr=float(capital_inr),
        max_open_positions=settings.max_open_positions,
        max_position_allocation_pct=settings.max_position_pct,
        max_total_deployed_pct=settings.max_total_deployed_pct,
        max_sector_allocation_pct=settings.max_sector_pct,
        max_daily_drawdown_pct=settings.daily_drawdown_pct,
        universe=[str(s).strip().upper() for s in universe],
        max_open_risk_pct=settings.max_open_risk_pct,
        min_position_size_inr=settings.min_position_size_inr,
    )
```
4. Run pass:
```
python -m pytest tradeloop/tests/test_config.py -q
```
Expected: `2 passed`.
5. Commit:
```
git commit -am "P0: typed Settings loader + risk_caps() mapping from settings.yaml"
```

---

### Task 5: `orders_schema.py` — typed `Order`/`OrdersFile`, `load_orders`, `to_ticket`

**Files:** create `tradeloop/lib/broker/orders_schema.py`; test `tradeloop/tests/test_orders_schema.py` (new).

**Interfaces:**
- Consumes: `OrderTicket` from `tradeloop.lib.broker.paper_broker` (existing frozen dataclass: `symbol, side, quantity, price, product="CNC", reason=""`).
- Produces:
  - `class Order(BaseModel)` — fields per §5.2 (`ticker, side, product="CNC", quantity, price, order_type="LIMIT", hard_stop, target_1, target_2, max_entry_price, strategy_family, status, reason=""`).
  - `class OrdersFile(BaseModel)` — `mode, live_orders_enabled=False, run, generated_by, orders=[], held=[]`.
  - `load_orders(path: Path) -> OrdersFile` (raises on malformed; legacy bare array → `OrdersFile(orders=[...])`).
  - `to_ticket(order: Order) -> OrderTicket`.

1. Write failing test — create `tradeloop/tests/test_orders_schema.py`:
```python
import json
from pathlib import Path

import pytest

from tradeloop.lib.broker.orders_schema import Order, OrdersFile, load_orders, to_ticket

REAL = {
    "mode": "PAPER",
    "live_orders_enabled": False,
    "run": "2026-06-26_0900_realtest",
    "generated_by": "tradeloop-pm",
    "orders": [
        {
            "ticker": "HDFCBANK", "side": "BUY", "product": "CNC", "quantity": 30,
            "order_type": "LIMIT", "price": 800.0, "max_entry_price": 805.0,
            "hard_stop": 775.0, "target_1": 820.0, "target_2": 835.0,
            "strategy_family": "breakout_20d_pullback",
        }
    ],
    "held": [{"ticker": "TCS", "side": "BUY", "quantity": 5, "price": 3000.0}],
}


def test_object_shape_parses_orders_and_held(tmp_path: Path) -> None:
    p = tmp_path / "orders.json"
    p.write_text(json.dumps(REAL), encoding="utf-8")
    of = load_orders(p)
    assert isinstance(of, OrdersFile)
    assert of.mode == "PAPER"
    assert of.live_orders_enabled is False
    assert len(of.orders) == 1 and len(of.held) == 1
    order = of.orders[0]
    assert order.ticker == "HDFCBANK"
    assert order.hard_stop == 775.0
    assert order.strategy_family == "breakout_20d_pullback"


def test_to_ticket_maps_fields() -> None:
    ticket = to_ticket(Order(ticker="reliance", side="BUY", quantity=2, price=1000))
    assert ticket.symbol == "RELIANCE"
    assert ticket.side == "BUY"
    assert ticket.quantity == 2
    assert ticket.price == 1000.0
    assert ticket.product == "CNC"


def test_legacy_bare_array_parses(tmp_path: Path) -> None:
    p = tmp_path / "orders.json"
    p.write_text(json.dumps([{"ticker": "TCS", "side": "BUY", "quantity": 1, "price": 3000}]), encoding="utf-8")
    of = load_orders(p)
    assert len(of.orders) == 1 and of.orders[0].ticker == "TCS"
    assert of.held == []


def test_malformed_orders_raise(tmp_path: Path) -> None:
    bad_side = tmp_path / "a.json"
    bad_side.write_text(json.dumps({"mode": "PAPER", "orders": [{"ticker": "TCS", "side": "SHORT", "quantity": 1, "price": 10}]}), encoding="utf-8")
    with pytest.raises(Exception):
        load_orders(bad_side)

    not_json = tmp_path / "b.json"
    not_json.write_text("{not json", encoding="utf-8")
    with pytest.raises(Exception):
        load_orders(not_json)
```
2. Run it — expect FAIL:
```
python -m pytest tradeloop/tests/test_orders_schema.py -q
```
Expected: `ModuleNotFoundError: No module named 'tradeloop.lib.broker.orders_schema'`.
3. Minimal implementation — create `tradeloop/lib/broker/orders_schema.py`:
```python
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from tradeloop.lib.broker.paper_broker import OrderTicket


class Order(BaseModel):
    ticker: str
    side: Literal["BUY", "SELL"]
    product: Literal["CNC", "MIS"] = "CNC"
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
    mode: str = "PAPER"
    live_orders_enabled: bool = False
    run: str | None = None
    generated_by: str | None = None
    orders: list[Order] = []
    held: list[Order] = []


def load_orders(path: Path) -> OrdersFile:
    """Parse the LLM-written orders.json. Raises on malformed input so the
    orchestrator can abort the order path loudly instead of mis-routing."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):  # legacy bare array
        return OrdersFile(orders=data)
    return OrdersFile.model_validate(data)


def to_ticket(order: Order) -> OrderTicket:
    return OrderTicket(
        symbol=order.ticker.strip().upper(),
        side=order.side,
        quantity=int(order.quantity),
        price=float(order.price),
        product=order.product,
        reason=order.reason,
    )
```
4. Run pass:
```
python -m pytest tradeloop/tests/test_orders_schema.py -q
```
Expected: `4 passed`.
5. Commit:
```
git commit -am "P0: typed Order/OrdersFile schema matching real orders.json; load_orders + to_ticket"
```

---

### Task 6: `paper_book.py` — persisted `hydrate()`/`append()`

**Files:** create `tradeloop/lib/broker/paper_book.py`; test `tradeloop/tests/test_paper_book.py` (new).

**Interfaces:**
- Consumes: `PaperBroker`, `Fill`, `OrderTicket` from `tradeloop.lib.broker.paper_broker`.
- Produces:
  - `hydrate(book_path: Path, starting_cash_inr: float) -> PaperBroker` — new broker at `starting_cash`, replays each persisted FILLED fill through `broker.place_order` so positions/avg/cash/costs match reality. Persists `hard_stop` per fill.
  - `append(book_path: Path, fills: list[Fill]) -> None` — append-only JSONL of FILLED fills only, each carrying `hard_stop`.
  - `FILL_FIELDS` order used for serialization (internal).

Note: `Fill` has no `hard_stop` field, so the book carries it as a separate JSON key alongside the serialized fill. `hydrate` replays by re-issuing the original `OrderTicket` (side/qty/price/product) so the broker's own fill math (slippage + costs) runs identically to the live path — with `slippage_bps=0` on replay so a persisted fill reproduces exactly.

1. Write failing test — create `tradeloop/tests/test_paper_book.py`:
```python
from pathlib import Path

from tradeloop.lib.broker.paper_book import append, hydrate
from tradeloop.lib.broker.paper_broker import OrderTicket, PaperBroker


def test_hydrate_replays_persisted_fills(tmp_path: Path) -> None:
    book = tmp_path / "paper_book.jsonl"
    broker = PaperBroker(cash_inr=100000, slippage_bps=0)
    buy = broker.place_order(OrderTicket("RELIANCE", "BUY", 10, 1000))
    append(book, [buy], hard_stops={"RELIANCE": 950.0})

    rehydrated = hydrate(book, starting_cash_inr=100000)
    assert rehydrated.positions == {"RELIANCE": 10}
    assert rehydrated.avg_prices["RELIANCE"] == 1000.0
    assert rehydrated.cash_inr == broker.cash_inr


def test_hydrated_sell_reduces_position(tmp_path: Path) -> None:
    book = tmp_path / "paper_book.jsonl"
    seed = PaperBroker(cash_inr=100000, slippage_bps=0)
    buy = seed.place_order(OrderTicket("TCS", "BUY", 5, 3000))
    append(book, [buy], hard_stops={"TCS": 2900.0})

    broker = hydrate(book, starting_cash_inr=100000)
    sell = broker.place_order(OrderTicket("TCS", "SELL", 2, 3100))
    assert sell.status == "FILLED"
    assert broker.positions == {"TCS": 3}


def test_missing_book_starts_empty(tmp_path: Path) -> None:
    broker = hydrate(tmp_path / "nope.jsonl", starting_cash_inr=50000)
    assert broker.positions == {}
    assert broker.cash_inr == 50000
```
2. Run it — expect FAIL:
```
python -m pytest tradeloop/tests/test_paper_book.py -q
```
Expected: `ModuleNotFoundError: No module named 'tradeloop.lib.broker.paper_book'`.
3. Minimal implementation — create `tradeloop/lib/broker/paper_book.py`:
```python
import json
from pathlib import Path

from tradeloop.lib.broker.paper_broker import Fill, OrderTicket, PaperBroker


def hydrate(book_path: Path, starting_cash_inr: float) -> PaperBroker:
    """Rebuild a PaperBroker by replaying every persisted FILLED fill through
    the broker's own fill math (slippage_bps=0 so a stored fill reproduces
    exactly). Missing book file => empty book at starting cash (first run)."""
    broker = PaperBroker(cash_inr=float(starting_cash_inr), slippage_bps=0)
    path = Path(book_path)
    if not path.exists():
        return broker
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if rec.get("status") != "FILLED":
            continue
        broker.place_order(
            OrderTicket(
                symbol=str(rec["symbol"]).strip().upper(),
                side=rec["side"],
                quantity=int(rec["quantity"]),
                price=float(rec["fill_price"]),
                product=str(rec.get("product", "CNC")),
            )
        )
    return broker


def append(book_path: Path, fills: list[Fill], hard_stops: dict[str, float] | None = None) -> None:
    """Append FILLED fills as JSON lines (append-only, never rewrites). Each
    line carries hard_stop (from hard_stops[symbol]) so open-risk can be
    computed from held positions when the book is replayed."""
    # ponytail: flat JSONL book now; Phase 2 replaces it with the hash-chained
    # SQLite event log behind the same hydrate/append interface.
    hard_stops = hard_stops or {}
    path = Path(book_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for fill in fills:
        if fill.status != "FILLED":
            continue
        rec = dict(fill.__dict__)
        rec["hard_stop"] = hard_stops.get(fill.symbol)
        lines.append(json.dumps(rec, default=str))
    if lines:
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
```
4. Run pass:
```
python -m pytest tradeloop/tests/test_paper_book.py -q
```
Expected: `3 passed`.
5. Commit:
```
git commit -am "P0: persisted append-only paper book with hydrate/append"
```

---

### Task 7: Rewrite `route_orders_file` — gate every order + route approved only

**Files:** modify `tradeloop/lib/broker/router.py`; test `tradeloop/tests/test_router_gate.py` (new).

**Interfaces:**
- Consumes: `load_orders`, `to_ticket` (Task 5); `PaperBroker` (existing); `Settings`, `risk_caps` (Task 4); `evaluate`, `RiskState` (existing `checks.py`); `load_ticker_master`, `alias_index` (existing `ticker_master.py` — returns `List[TickerRecord]`); `route_order`, `RoutedOrder`, `live_promotion_ready` (existing router).
- Produces:
  - New `route_orders_file(orders_path, fills_path, book: PaperBroker, settings: Settings, root=Path("tradeloop")) -> list[RoutedOrder]` — parses object, builds `RiskState`+`RiskCaps`, calls `evaluate()` on each order, routes only approved, skips `held[]`, writes `fills.json`, appends `decisions.jsonl`.
  - Helper `_risk_state(book, tm_records) -> RiskState`.
  - Helper `_equity(book) -> float`.
  - `live_promotion_ready(root, settings: Settings | None = None)` reads thresholds from `settings.promotion_gates` when provided (kills the `router.py:52` hardcode).
  - `append_decision(path, order, verdict, routed) -> None`.

Design decisions (open in spec, fixed here):
- `RiskState.open_risk_inr` is computed from the hydrated book's per-position `hard_stop` (persisted in Task 6). Because `hydrate` re-issues tickets and doesn't retain the stop, Phase 0 computes open-risk in `route_orders_file` from the `paper_book.jsonl` stops loaded via a small `book_hard_stops(book_path)` read. To keep the router pure, the orchestrator passes stops in; but for a standalone-testable router we read them from `root/state/paper_book.jsonl` if present, else `open_risk_inr=0.0`. **Decision:** `route_orders_file` accepts the book only; open-risk uses `avg_price - hard_stop` where a stop is available on the book file, and `0.0` otherwise. The four canonical tests don't exercise open-risk, so this stays simple.
- `daily_pnl_inr` = realized-only (0.0 in Phase 0 unless SELL fills happened this cycle); unrealized deferred to P3 marks. **Decision:** `0.0` at gate-build time (documented best-effort per §6).
- `route_order` keeps its existing signature and its own kill-switch/promotion checks; the mandatory `evaluate()` runs one level up so `route_order`'s existing test stays valid.

1. Write failing test — create `tradeloop/tests/test_router_gate.py`:
```python
import json
from pathlib import Path

import pytest

from tradeloop.lib.broker.orders_schema import OrdersFile, Order
from tradeloop.lib.broker.paper_book import append, hydrate
from tradeloop.lib.broker.paper_broker import OrderTicket, PaperBroker
from tradeloop.lib.broker.router import route_orders_file
from tradeloop.lib.config import load_settings

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = load_settings(ROOT / "config" / "settings.yaml")


def _write(tmp_path: Path, of: dict) -> tuple[Path, Path]:
    orders = tmp_path / "orders.json"
    fills = tmp_path / "fills.json"
    orders.write_text(json.dumps(of), encoding="utf-8")
    return orders, fills


def _reasons(routed) -> list[str]:
    return list(routed.payload.get("reasons", []))


def test_rejects_non_universe_symbol(tmp_path: Path) -> None:
    orders, fills = _write(tmp_path, {"orders": [
        {"ticker": "FAKECO", "side": "BUY", "quantity": 5, "price": 4000}]})
    routed = route_orders_file(orders, fills, PaperBroker(500000), SETTINGS, root=ROOT)
    assert routed[0].status == "RISK_REJECTED"
    assert "symbol_not_in_universe" in _reasons(routed[0])


def test_rejects_oversized_position(tmp_path: Path) -> None:
    # 100000 capital, 25% cap = 25000; 100 * 3000 = 300000 notional -> reject.
    orders, fills = _write(tmp_path, {"orders": [
        {"ticker": "TCS", "side": "BUY", "quantity": 100, "price": 3000}]})
    routed = route_orders_file(orders, fills, PaperBroker(100000), SETTINGS, root=ROOT)
    assert routed[0].status == "RISK_REJECTED"
    assert "max_position_allocation_exceeded" in _reasons(routed[0])


def test_rejects_fifth_concurrent_position(tmp_path: Path) -> None:
    book = tmp_path / "state" / "paper_book.jsonl"
    seed = PaperBroker(cash_inr=10_000_000, slippage_bps=0)
    for sym, px in [("RELIANCE", 1000), ("TCS", 1000), ("HDFCBANK", 1000), ("INFY", 1000)]:
        fill = seed.place_order(OrderTicket(sym, "BUY", 1, px))
        append(book, [fill])
    broker = hydrate(book, starting_cash_inr=10_000_000)
    orders, fills = _write(tmp_path, {"orders": [
        {"ticker": "ICICIBANK", "side": "BUY", "quantity": 10, "price": 1000}]})
    routed = route_orders_file(orders, fills, broker, SETTINGS, root=ROOT)
    assert routed[0].status == "RISK_REJECTED"
    assert "max_open_positions_exceeded" in _reasons(routed[0])


def test_rejects_sell_exceeding_held(tmp_path: Path) -> None:
    book = tmp_path / "state" / "paper_book.jsonl"
    seed = PaperBroker(cash_inr=1_000_000, slippage_bps=0)
    fill = seed.place_order(OrderTicket("RELIANCE", "BUY", 3, 1000))
    append(book, [fill])
    broker = hydrate(book, starting_cash_inr=1_000_000)
    orders, fills = _write(tmp_path, {"orders": [
        {"ticker": "RELIANCE", "side": "SELL", "quantity": 10, "price": 1050}]})
    routed = route_orders_file(orders, fills, broker, SETTINGS, root=ROOT)
    assert routed[0].status == "RISK_REJECTED"
    assert "long_only_sell_exceeds_position" in _reasons(routed[0])


def test_hydrated_sell_within_held_fills(tmp_path: Path) -> None:
    book = tmp_path / "state" / "paper_book.jsonl"
    seed = PaperBroker(cash_inr=1_000_000, slippage_bps=0)
    fill = seed.place_order(OrderTicket("RELIANCE", "BUY", 5, 1000))
    append(book, [fill])
    broker = hydrate(book, starting_cash_inr=1_000_000)
    orders, fills = _write(tmp_path, {"orders": [
        {"ticker": "RELIANCE", "side": "SELL", "quantity": 2, "price": 1050}]})
    routed = route_orders_file(orders, fills, broker, SETTINGS, root=ROOT)
    assert routed[0].status == "FILLED"
    assert broker.positions == {"RELIANCE": 3}


def test_routes_orders_and_skips_held(tmp_path: Path) -> None:
    orders, fills = _write(tmp_path, {
        "orders": [{"ticker": "RELIANCE", "side": "BUY", "quantity": 20, "price": 1000}],
        "held": [{"ticker": "TCS", "side": "BUY", "quantity": 5, "price": 3000}],
    })
    routed = route_orders_file(orders, fills, PaperBroker(500000), SETTINGS, root=ROOT)
    assert len(routed) == 1  # held[] not routed
    written = json.loads(fills.read_text(encoding="utf-8"))
    assert len(written) == 1
    decisions = (tmp_path / "decisions.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(decisions) == 1


def test_malformed_orders_file_raises(tmp_path: Path) -> None:
    bad = tmp_path / "orders.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(Exception):
        route_orders_file(bad, tmp_path / "fills.json", PaperBroker(100000), SETTINGS, root=ROOT)
```
2. Run it — expect FAIL:
```
python -m pytest tradeloop/tests/test_router_gate.py -q
```
Expected: `TypeError` (old `route_orders_file` takes no `settings` arg / no gate).
3. Minimal implementation — replace `route_orders_file` and add helpers in `tradeloop/lib/broker/router.py`. Update imports at the top and edit the promotion helper. Full new/edited regions:

Add imports (top of file, after existing imports):
```python
from tradeloop.lib.broker.orders_schema import load_orders, to_ticket
from tradeloop.lib.config import Settings
from tradeloop.lib.data.ticker_master import alias_index, load_ticker_master
from tradeloop.lib.risk.checks import RiskState, evaluate
```
Replace `live_promotion_ready` to accept optional `Settings`:
```python
def live_promotion_ready(root: Path = Path("tradeloop"), settings: "Settings | None" = None) -> bool:
    performance = root / "memory" / "strategy_performance.md"
    if not performance.exists():
        return False
    text = performance.read_text(encoding="utf-8").lower()
    if "live_ready: true" in text:
        return True
    gates = settings.promotion_gates if settings else {}
    min_trades = float(gates.get("min_paper_trades", 40))
    min_win = float(gates.get("min_win_rate", 0.45))
    min_exp = float(gates.get("min_expectancy_r", 0.3))
    max_dd = float(gates.get("max_drawdown_pct", 8))
    paper_trades = _metric(text, "paper_trades")
    win_rate = _metric(text, "win_rate")
    expectancy = _metric(text, "expectancy_r")
    drawdown = _metric(text, "max_drawdown_pct")
    return paper_trades >= min_trades and win_rate >= min_win and expectancy >= min_exp and drawdown <= max_dd
```
Replace the old `route_orders_file` and add helpers:
```python
def _equity(book: PaperBroker) -> float:
    deployed = sum(qty * book.avg_prices.get(sym, 0.0) for sym, qty in book.positions.items())
    return book.cash_inr + deployed


def _risk_state(book: PaperBroker, sectors: Dict[str, str]) -> RiskState:
    return RiskState(
        cash_inr=book.cash_inr,
        positions=dict(book.positions),
        avg_prices=dict(book.avg_prices),
        sectors={sym: sectors.get(sym, "") for sym in book.positions},
        open_risk_inr=0.0,   # best-effort in P0; full from persisted stops + marks in P3
        daily_pnl_inr=0.0,   # realized-only; unrealized deferred to P3 marks
    )


def append_decision(path: Path, order, verdict, routed: RoutedOrder) -> None:
    record = {
        "ticker": order.ticker,
        "side": order.side,
        "quantity": order.quantity,
        "price": order.price,
        "approved": verdict.approved,
        "reasons": verdict.reasons,
        "routed_status": routed.status,
        "routed_mode": routed.mode,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, default=str) + "\n")


def route_orders_file(
    orders_path: Path,
    fills_path: Path,
    book: PaperBroker,
    settings: Settings,
    root: Path = Path("tradeloop"),
) -> list[RoutedOrder]:
    of = load_orders(orders_path)  # typed; raises on malformed -> cycle aborts loudly
    records = load_ticker_master(root / "config" / "universe.yaml")
    symbols = [r.symbol for r in records]
    sectors = {r.symbol.upper(): r.sector for r in records}
    caps = risk_caps_from(settings, symbols, _equity(book))
    state = _risk_state(book, sectors)
    decisions_path = orders_path.parent / "decisions.jsonl"
    routed: list[RoutedOrder] = []
    for order in of.orders:  # held[] intentionally skipped in Phase 0
        ticket = to_ticket(order)
        verdict = evaluate(ticket, state, caps)  # the mandatory gate
        if not verdict.approved:
            outcome = RoutedOrder("blocked", "RISK_REJECTED",
                                  {"symbol": ticket.symbol, "reasons": verdict.reasons})
        else:
            outcome = route_order(ticket, book, root=root)
        routed.append(outcome)
        append_decision(decisions_path, order, verdict, outcome)
    fills_path.write_text(json.dumps([r.__dict__ for r in routed], indent=2, default=str), encoding="utf-8")
    return routed
```
Add the caps import alias near the other imports (keeps the call above readable and avoids shadowing `risk_caps` if it is ever imported elsewhere):
```python
from tradeloop.lib.config import risk_caps as risk_caps_from
```
Remove the now-obsolete `ticket_from_order` (superseded by `to_ticket`) only if nothing else imports it; grep first:
```
grep -rn "ticket_from_order" tradeloop
```
If the only hit is `router.py`, delete the function; otherwise leave it. (`alias_index` import may be unused — drop it if flake flags it.)
4. Run pass:
```
python -m pytest tradeloop/tests/test_router_gate.py -q
```
Expected: `7 passed`.
5. Commit:
```
git commit -am "P0: route_orders_file gates every order via evaluate(); skips held[]; logs decisions.jsonl"
```

---

### Task 8: Prompt edits — agent stops at orders.json, Python routes

**Files:** modify `tradeloop/prompts/00_master_orchestrator.md`, `tradeloop/prompts/41_portfolio_manager.md`; test `tradeloop/tests/test_orchestrator.py`.

**Interfaces:**
- Consumes: nothing (documentation invariant).
- Produces: prompts that forbid the agent from routing orders or writing `fills.json`.

1. Write failing test — append to `tradeloop/tests/test_orchestrator.py`:
```python
from pathlib import Path

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


def test_master_prompt_hands_routing_to_python() -> None:
    text = (PROMPTS / "00_master_orchestrator.md").read_text(encoding="utf-8").lower()
    assert "do not route orders" in text
    assert "does not write fills.json" in text or "do not write fills.json" in text


def test_pm_prompt_writes_orders_only_not_fills() -> None:
    text = (PROMPTS / "41_portfolio_manager.md").read_text(encoding="utf-8").lower()
    assert "orders.json" in text
    assert "do not write" in text and "fills.json" in text
```
2. Run it — expect FAIL:
```
python -m pytest tradeloop/tests/test_orchestrator.py::test_master_prompt_hands_routing_to_python tradeloop/tests/test_orchestrator.py::test_pm_prompt_writes_orders_only_not_fills -q
```
Expected: `assert ... in text` fails.
3. Minimal implementation — edit `tradeloop/prompts/00_master_orchestrator.md`. Replace step 7 of "Required stage order":
```
7. Stop after writing `orders.json`. Do not route orders and do not write
   `fills.json`. Broker routing is a separate deterministic Python step
   (`tradeloop.orchestrator`) that reads only `orders.json`, runs the risk gate
   on every order, and writes `fills.json` + `decisions.jsonl`.
```
Edit `tradeloop/prompts/41_portfolio_manager.md`. Replace the "Writes" line and closing sentence:
```
Writes: `41_pm_decision.md` and `orders.json`.

Final gate. You may override risk only to be more conservative. Reasons for
veto must cite evidence. Write `orders.json` only. Do not write `fills.json`
and do not place any order — Python's deterministic router reads `orders.json`,
runs the mandatory risk gate on every order, and writes `fills.json`.
```
4. Run pass:
```
python -m pytest tradeloop/tests/test_orchestrator.py::test_master_prompt_hands_routing_to_python tradeloop/tests/test_orchestrator.py::test_pm_prompt_writes_orders_only_not_fills -q
```
Expected: `2 passed`.
5. Commit:
```
git commit -am "P0: prompts stop the agent at orders.json; Python owns routing and fills.json"
```

---

### Task 9: Reasoning seam `_run_reasoning`

**Files:** create `tradeloop/orchestrator.py` (partial — reasoning seam + gates only; order path added in Task 10). test `tradeloop/tests/test_orchestrator.py`.

**Interfaces:**
- Consumes: existing env `TRADELOOP_AGENT`, `TRADELOOP_MODEL`; `run_cycle.sh` backend selection semantics.
- Produces:
  - `_run_reasoning(run_dir: Path, mode: str, agent: str) -> int` — runs the external codex/claude backend as a subprocess (mirrors `run_cycle.sh`), returns its exit code. Overridable in tests via monkeypatch.
  - Gate helpers on the module: `_gate_holiday`, `_gate_kill_switch`, `_gate_live_ready` (thin wrappers returning a reason string or None).

**Decision (spec seam):** `_run_reasoning` shells to `bin/codex-zerodha` / `claude` exactly as `run_cycle.sh` does, sourcing `OPENROUTER_API_KEY` from the process env only (never reading `.env` in Python — that stays the shell's job; if unset the subprocess handles its own key). Phase 1 replaces this body with in-process OpenRouter calls without touching the order path. Tests never invoke the real backend — they monkeypatch `_run_reasoning`.

1. Write failing test — append to `tradeloop/tests/test_orchestrator.py`:
```python
from tradeloop import orchestrator


def test_run_reasoning_is_a_seam(monkeypatch, tmp_path) -> None:
    calls = {}

    def fake(run_dir, mode, agent):
        calls["run_dir"] = run_dir
        calls["mode"] = mode
        return 0

    monkeypatch.setattr(orchestrator, "_run_reasoning", fake)
    rc = orchestrator._run_reasoning(tmp_path, "premarket", "codex")
    assert rc == 0
    assert calls["mode"] == "premarket"
```
2. Run it — expect FAIL:
```
python -m pytest tradeloop/tests/test_orchestrator.py::test_run_reasoning_is_a_seam -q
```
Expected: `ModuleNotFoundError: No module named 'tradeloop.orchestrator'`.
3. Minimal implementation — create `tradeloop/orchestrator.py` (gates + seam; `main`/order path in Task 10):
```python
"""TradeLoop desk manager: gates -> lock -> prepare -> reason -> order path."""
import os
import subprocess
from datetime import date
from pathlib import Path

from tradeloop.lib.risk.circuit_breaker import kill_switch_active
from tradeloop.lib.util.holidays import is_nse_holiday

ROOT = Path(__file__).resolve().parent


def _gate_holiday(today: date) -> str | None:
    return "nse_holiday" if is_nse_holiday(today) else None


def _gate_kill_switch(root: Path) -> str | None:
    return "kill_switch" if kill_switch_active(root) else None


def _run_reasoning(run_dir: Path, mode: str, agent: str) -> int:
    """Phase-0 seam: run the unchanged external reasoning backend as a
    subprocess. Phase 1 replaces this body with in-process OpenRouter calls
    without touching the order path. Sources no secrets in Python — the child
    reads OPENROUTER_API_KEY from the already-exported env (AGENTS.md safe)."""
    script = ROOT / "scripts" / "run_cycle.sh"
    env = dict(os.environ, TRADELOOP_AGENT=agent)
    proc = subprocess.run(["bash", str(script), mode], env=env, cwd=str(ROOT.parent))
    return proc.returncode
```
4. Run pass:
```
python -m pytest tradeloop/tests/test_orchestrator.py::test_run_reasoning_is_a_seam -q
```
Expected: `1 passed`.
5. Commit:
```
git commit -am "P0: orchestrator gates + _run_reasoning subprocess seam"
```

---

### Task 10: Orchestrator control flow — gates, lock, timeout, order path, `main`

**Files:** modify `tradeloop/orchestrator.py`; test `tradeloop/tests/test_orchestrator.py`.

**Interfaces:**
- Consumes: `load_settings`, `Settings` (Task 4); `hydrate` (Task 6); `route_orders_file` (Task 7); `live_enabled`, `live_promotion_ready` (router); `prepare` from `tradeloop.scripts.prepare_cycle`; `_run_reasoning`, `_gate_holiday`, `_gate_kill_switch` (Task 9).
- Produces:
  - `run_cycle(mode: str, request: str = "", root: Path = ROOT) -> int` — the full flow, returns exit code.
  - `main(argv=None) -> int` and `python -m tradeloop.orchestrator <mode>` entrypoint.
  - Exit codes: SKIP/HALT/LOCKED → 0; LIVE_NOT_READY → 2; ORDERS_INVALID/TIMEOUT/reasoning-failure → 1.
  - Book path: `root/state/paper_book.jsonl`.

**Decisions:**
- **Global lock:** a single lockfile `root/state/orchestrator.lock` acquired with `fcntl.flock(LOCK_EX | LOCK_NB)`; on contention → `LOCKED`, exit 0 (cron-safe). `// ponytail: global flock across all modes since the book is shared state; per-mode locks only if throughput ever matters.`
- **Timeout:** `_run_reasoning` is run under `subprocess`'s own timeout via `settings.cycle_timeout_seconds`; on `TimeoutExpired` → release lock, `TIMEOUT`, exit 1. Implemented by threading the timeout into `_run_reasoning` (add a `timeout` param there).
- **Order path only runs when reasoning returns 0.**
- **Malformed orders.json** → `route_orders_file` raises → catch → write `{"error": "ORDERS_INVALID"}` marker to `fills.json`, exit 1. Never route empty fills.

1. Write failing test — append to `tradeloop/tests/test_orchestrator.py`:
```python
import json
from datetime import date


def _fresh_root(tmp_path):
    """Copy the minimal config the orchestrator reads into an isolated root."""
    import shutil
    root = tmp_path / "tradeloop"
    (root / "config").mkdir(parents=True)
    (root / "state").mkdir()
    src = Path(__file__).resolve().parents[1]
    shutil.copy(src / "config" / "settings.yaml", root / "config" / "settings.yaml")
    shutil.copy(src / "config" / "universe.yaml", root / "config" / "universe.yaml")
    return root


def test_holiday_halts_before_reasoning(monkeypatch, tmp_path) -> None:
    root = _fresh_root(tmp_path)
    called = {"reasoned": False}
    monkeypatch.setattr(orchestrator, "_run_reasoning", lambda *a, **k: called.__setitem__("reasoned", True) or 0)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 1, 26))  # Republic Day
    rc = orchestrator.run_cycle("premarket", root=root)
    assert rc == 0
    assert called["reasoned"] is False


def test_kill_switch_halts_before_reasoning(monkeypatch, tmp_path) -> None:
    root = _fresh_root(tmp_path)
    (root / "kill_switch.md").write_text("halt", encoding="utf-8")
    called = {"reasoned": False}
    monkeypatch.setattr(orchestrator, "_run_reasoning", lambda *a, **k: called.__setitem__("reasoned", True) or 0)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))
    rc = orchestrator.run_cycle("premarket", root=root)
    assert rc == 0
    assert called["reasoned"] is False


def test_malformed_orders_aborts_loud(monkeypatch, tmp_path) -> None:
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))

    def fake_reason(run_dir, mode, agent, timeout):
        (run_dir / "orders.json").write_text("{not json", encoding="utf-8")
        return 0

    def fake_prepare(mode, request="", root=None):
        run_dir = root / "runs" / f"test_{mode}"
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    monkeypatch.setattr(orchestrator, "_run_reasoning", fake_reason)
    monkeypatch.setattr(orchestrator, "_prepare", fake_prepare)
    rc = orchestrator.run_cycle("premarket", root=root)
    assert rc == 1
```
2. Run it — expect FAIL:
```
python -m pytest tradeloop/tests/test_orchestrator.py -k "halts or malformed" -q
```
Expected: `AttributeError: module 'tradeloop.orchestrator' has no attribute 'run_cycle'`.
3. Minimal implementation — extend `tradeloop/orchestrator.py`. Add imports and the flow. Update `_run_reasoning` to take `timeout`:
```python
import fcntl
import json
import sys
from contextlib import contextmanager

from tradeloop.lib.broker.paper_book import hydrate
from tradeloop.lib.broker.router import live_enabled, live_promotion_ready, route_orders_file
from tradeloop.lib.config import load_settings
from tradeloop.scripts.prepare_cycle import prepare as _prepare


def _today() -> date:
    return date.today()


def _run_reasoning(run_dir: Path, mode: str, agent: str, timeout: int) -> int:
    script = ROOT / "scripts" / "run_cycle.sh"
    env = dict(os.environ, TRADELOOP_AGENT=agent)
    try:
        proc = subprocess.run(["bash", str(script), mode], env=env,
                              cwd=str(ROOT.parent), timeout=timeout)
    except subprocess.TimeoutExpired:
        return -1
    return proc.returncode


@contextmanager
def _global_lock(root: Path):
    lock_path = root / "state" / "orchestrator.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # ponytail: global flock across all modes since the book is shared state;
    # per-mode locks only if throughput ever matters.
    handle = lock_path.open("w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        yield False
        return
    try:
        yield True
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def run_cycle(mode: str, request: str = "", root: Path = ROOT,
              agent: str | None = None) -> int:
    settings = load_settings(root / "config" / "settings.yaml")
    agent = agent or os.getenv("TRADELOOP_AGENT", "codex")

    reason = _gate_holiday(_today())
    if reason:
        print(f"tradeloop_cycle=SKIP reason={reason}")
        return 0
    reason = _gate_kill_switch(root)
    if reason:
        print(f"tradeloop_cycle=HALT reason={reason}")
        return 0
    if live_enabled() and not live_promotion_ready(root, settings):
        print("tradeloop_cycle=LIVE_NOT_READY")
        return 2

    with _global_lock(root) as acquired:
        if not acquired:
            print("tradeloop_cycle=LOCKED")
            return 0
        run_dir = _prepare(mode, request, root=root) if _prepare_takes_root() else _prepare(mode, request)
        rc = _run_reasoning(run_dir, mode, agent, settings.cycle_timeout_seconds)
        if rc == -1:
            print("tradeloop_cycle=TIMEOUT")
            return 1
        if rc != 0:
            print(f"tradeloop_cycle=REASONING_FAILED rc={rc}")
            return 1

        orders_path = run_dir / "orders.json"
        fills_path = run_dir / "fills.json"
        book_path = root / "state" / "paper_book.jsonl"
        book = hydrate(book_path, settings.paper_starting_inr)
        try:
            routed = route_orders_file(orders_path, fills_path, book, settings, root=root)
        except Exception as exc:  # malformed orders.json -> loud abort, no routing
            fills_path.write_text(json.dumps({"error": "ORDERS_INVALID", "detail": str(exc)}), encoding="utf-8")
            print("tradeloop_cycle=ORDERS_INVALID")
            return 1
        filled = sum(1 for r in routed if r.status == "FILLED")
        rejected = sum(1 for r in routed if r.status == "RISK_REJECTED")
        print(f"tradeloop_cycle=OK mode={mode} orders={len(routed)} filled={filled} rejected={rejected}")
        return 0


def _prepare_takes_root() -> bool:
    import inspect
    return "root" in inspect.signature(_prepare).parameters


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="tradeloop.orchestrator")
    parser.add_argument("mode", choices=["premarket", "intraday", "postclose", "adhoc"])
    parser.add_argument("--request", default="")
    args = parser.parse_args(argv)
    return run_cycle(args.mode, args.request)


if __name__ == "__main__":
    raise SystemExit(main())
```
Note: the malformed test monkeypatches `orchestrator._prepare`; `prepare_cycle.prepare` currently has signature `prepare(mode, request="")` (module-level `ROOT`, no `root` param). To let the orchestrator target an isolated root in tests, add an optional `root` param to `prepare_cycle.prepare` (default keeps existing behavior):
- Edit `tradeloop/scripts/prepare_cycle.py`: change `def prepare(mode: str, request: str = "") -> Path:` to `def prepare(mode: str, request: str = "", root: Path | None = None) -> Path:` and add at the top of the body `base = root or ROOT` then use `base` in place of `ROOT` for `run_dir`, `state`, `macro_path`, `carry_forward_path`. This keeps `run_cycle.sh`'s call (`--mode` only) unchanged. With this, `_prepare_takes_root()` returns True and the orchestrator passes `root`.
4. Run pass:
```
python -m pytest tradeloop/tests/test_orchestrator.py -q
```
Expected: all orchestrator tests pass (`halts`, `malformed`, seam, holiday, packaging, prompts).
5. Commit:
```
git commit -am "P0: orchestrator run_cycle with gates, global lock, timeout, order path, main"
```

---

### Task 11: Wire the promotion gate to settings in `verify_setup.py`

**Files:** modify `tradeloop/scripts/verify_setup.py`; test `tradeloop/tests/test_config.py`.

**Interfaces:**
- Consumes: `load_settings` (Task 4); `live_promotion_ready(root, settings)` (Task 7).
- Produces: `verify_setup` reads promotion thresholds from settings (no hardcoded duplicate path); its behavior stays otherwise unchanged (it remains a standalone preflight CLI).

1. Write failing test — append to `tradeloop/tests/test_config.py`:
```python
from tradeloop.lib.broker.router import live_promotion_ready


def test_promotion_gate_reads_thresholds_from_settings(tmp_path) -> None:
    root = tmp_path / "tradeloop"
    (root / "memory").mkdir(parents=True)
    (root / "memory" / "strategy_performance.md").write_text(
        "paper_trades: 5\nwin_rate: 0.9\nexpectancy_r: 1.0\nmax_drawdown_pct: 1\n",
        encoding="utf-8",
    )
    settings = load_settings(ROOT / "config" / "settings.yaml")
    # 5 paper trades < 40 required by settings -> not ready.
    assert live_promotion_ready(root, settings) is False

    class LooseSettings:
        promotion_gates = {"min_paper_trades": 1, "min_win_rate": 0.1,
                           "min_expectancy_r": 0.1, "max_drawdown_pct": 50}
    assert live_promotion_ready(root, LooseSettings()) is True
```
2. Run it — expect FAIL (before Task 7's `settings`-aware `live_promotion_ready` is in place this errors; if Task 7 already landed it, this passes — run to confirm the wiring):
```
python -m pytest tradeloop/tests/test_config.py::test_promotion_gate_reads_thresholds_from_settings -q
```
Expected: PASS if Task 7 landed (the signature already accepts `settings`); this task's real change is `verify_setup.py`.
3. Minimal implementation — edit `tradeloop/scripts/verify_setup.py` to pass settings into the gate. Replace the import and the live-readiness block:
```python
from tradeloop.lib.broker.router import live_enabled, live_promotion_ready
from tradeloop.lib.config import load_settings
from tradeloop.lib.risk.circuit_breaker import kill_switch_active
from tradeloop.lib.util.holidays import is_nse_holiday
```
```python
    if check_live_readiness or live_enabled():
        settings = load_settings(ROOT / "config" / "settings.yaml")
        if not live_promotion_ready(ROOT, settings):
            print("tradeloop_setup=LIVE_NOT_READY")
            return 2
```
4. Run pass:
```
python -m pytest tradeloop/tests/test_config.py -q
```
Expected: all config tests pass.
5. Commit:
```
git commit -am "P0: verify_setup reads promotion thresholds from settings (no hardcoded duplicate)"
```

---

### Task 12: Full-suite green + acceptance smoke

**Files:** no new source; test run only. Existing `tradeloop/tests/test_paper_broker.py` and `test_sizing.py` are confirmed still green (they were never modified).

**Interfaces:**
- Consumes: everything above.
- Produces: a green suite and a working `python -m tradeloop.orchestrator` entrypoint on a monkeypatched reasoning backend.

1. Write failing test — append an end-to-end acceptance case to `tradeloop/tests/test_orchestrator.py`:
```python
def test_end_to_end_gate_runs_on_every_order(monkeypatch, tmp_path) -> None:
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))

    def fake_prepare(mode, request="", root=None):
        run_dir = root / "runs" / f"e2e_{mode}"
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def fake_reason(run_dir, mode, agent, timeout):
        # One approved BUY (in universe, sized under caps) + one non-universe reject.
        (run_dir / "orders.json").write_text(json.dumps({"orders": [
            {"ticker": "RELIANCE", "side": "BUY", "quantity": 10, "price": 1000},
            {"ticker": "FAKECO", "side": "BUY", "quantity": 1, "price": 5000},
        ]}), encoding="utf-8")
        return 0

    monkeypatch.setattr(orchestrator, "_prepare", fake_prepare)
    monkeypatch.setattr(orchestrator, "_run_reasoning", fake_reason)
    rc = orchestrator.run_cycle("premarket", root=root)
    assert rc == 0

    run_dir = root / "runs" / "e2e_premarket"
    fills = json.loads((run_dir / "fills.json").read_text(encoding="utf-8"))
    statuses = {f.get("status") for f in fills}
    assert "FILLED" in statuses            # approved order routed
    assert "RISK_REJECTED" in statuses     # non-universe order gated
    decisions = (run_dir / "decisions.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(decisions) == 2             # gate logged its own verdict per order
```
2. Run it — expect FAIL first if any wiring is off; otherwise PASS. Run the targeted case:
```
python -m pytest tradeloop/tests/test_orchestrator.py::test_end_to_end_gate_runs_on_every_order -q
```
Expected on first run: PASS once Tasks 1-11 are in; if it FAILs, fix the offending task, not this test.
3. Minimal implementation — none beyond Tasks 1-11 (this task is the acceptance net). If the e2e reveals a defect (e.g. `state/` dir missing for the book), fix at the source task.
4. Run pass — full suite:
```
pip install -e . && python -m pytest tradeloop/tests -q
```
Expected: all tests pass (existing `test_paper_broker`, `test_sizing`, `test_cost_model`, `test_indicators`, `test_news_to_tickers`, `test_adhoc_mode` plus the new `test_config`, `test_orders_schema`, `test_paper_book`, `test_router_gate`, `test_orchestrator`).
5. Commit:
```
git commit -am "P0: end-to-end acceptance test — evaluate() gates every order; full suite green"
```

---

## Self-review

**Spec / DoD coverage (Phase 0, DoD #4):**
- §3.1 Packaging → Task 1 (`tradeloop*` packaged, pandas + PyYAML declared, `pip install -e .` import proven).
- §3.2 Typed settings loader → Task 4 (`Settings`, `load_settings`, `risk_caps`); §5.1 `live_promotion_ready` refactored to read `Settings` → Tasks 7, 11 (kills the `router.py:52` hardcode).
- §3.3 Python orchestrator → Tasks 9, 10 (`run_cycle`: gates as real branches, global flock lock, `cycle_timeout_seconds` timeout, `prepare`, `_run_reasoning` seam, order path, `main`, `python -m` entry).
- §3.4 Persisted paper book → Task 6 (`hydrate`/`append`, append-only JSONL, `hard_stop` carried).
- §3.5 Mandatory gate in order path → Task 7 (`route_orders_file` parses the real object, builds `RiskState`+`RiskCaps`, `evaluate()` on every order, routes only approved, skips `held[]`, logs `decisions.jsonl`).
- §3.6 Populate `NSE_HOLIDAYS_2026` → Task 2.
- §3.7 Prompt edit → Task 8 (agent stops at `orders.json`; PM does not write `fills.json`).
- §3.8 / §10 Tests → four canonical rejections (Task 7: non-universe, oversized, 5th position, SELL>held), holiday + kill-switch halt (Task 10), hydrated SELL fills (Tasks 6, 7), malformed orders abort loud (Tasks 5, 7, 10), object-shape routes/skips-held + legacy array (Tasks 5, 7), promotion thresholds from settings (Tasks 4, 11), packaging import (Task 1). §12 acceptance #1 (evaluate runs on every order end-to-end) → Task 12.
- §7 error/failure modes: ORDERS_INVALID marker + non-zero exit (Task 10), holiday/kill-switch/LIVE_NOT_READY exit codes (Task 10), LOCKED exit 0 (Task 10), TIMEOUT non-zero (Task 10), missing book → empty at starting cash (Task 6).
- Non-negotiable constraints (India cash equity, long-only, CNC/MIS, no NRML/F&O, kill-switch, paper default, promotion gate, evaluate on every order) are enforced by reused `evaluate()`/`PaperBroker`/`to_zerodha_payload` and asserted by Tasks 7, 10.
- Best-effort in P0 (documented, not hidden): `open_risk_inr` and `daily_pnl_inr` are `0.0` at gate-build (§6 daily_drawdown best-effort; full open-risk/marks in P3). Stated in Task 7 decisions and code comments.

**Placeholder scan:** No "TBD", "similar to Task N", "add error handling", or "write tests for the above". Every task shows the real failing test, the exact FAIL/PASS commands, complete implementation code, and a real commit message. Every referenced type/function is defined in a task or in existing code read during planning: `OrderTicket`/`Fill`/`PaperBroker` (`paper_broker.py`), `evaluate`/`RiskState`/`RiskCaps`/`RiskDecision` (`checks.py`), `RoutedOrder`/`route_order`/`live_enabled`/`_metric` (`router.py`), `load_ticker_master`/`TickerRecord` (`ticker_master.py`), `prepare` (`prepare_cycle.py`), `kill_switch_active` (`circuit_breaker.py`), `is_nse_holiday` (`holidays.py`), `to_zerodha_payload` (`zerodha_mcp.py`).

**Type-consistency note:** `route_orders_file` signature matches §5.5 / §6 exactly (`orders_path, fills_path, book: PaperBroker, settings: Settings, root`). `load_orders(path) -> OrdersFile` and `to_ticket(order) -> OrderTicket` match §6. `paper_book.hydrate(path, starting_cash_inr) -> PaperBroker` and `append(path, fills)` match §6 (plus an optional `hard_stops` kwarg on `append`, additive and back-compatible). `risk_caps(settings, universe, capital_inr) -> RiskCaps` matches §6; `RiskCaps` field names map 1:1 to the existing frozen dataclass in `checks.py`. Reality-corrected deviations from the spec pseudocode, made explicit: (a) `load_ticker_master` returns `List[TickerRecord]` (not an object with `.symbols()`), so the router derives `symbols`/`sectors` from the list directly; (b) `OrderTicket` has no `hard_stop`/`target` fields, so those live only on `Order`/the book record, and open-risk reads stops from the book — never from the ticket. Both are consistent with the code read at plan time.
