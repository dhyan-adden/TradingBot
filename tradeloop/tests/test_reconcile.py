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
from tradeloop.lib.broker.cost_model import estimate_cost
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


def _fill(symbol, side, qty, price, product="CNC"):
    return {"symbol": symbol, "side": side, "quantity": qty, "fill_price": price, "status": "FILLED", "product": product}


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
    # fills-derived cash (cost-aware, via estimate_cost) vs. a book that's off by ~2000
    starting_cash = 100000.0
    fills = [_fill("TCS", "BUY", 10, 100.0)]
    costs = estimate_cost("BUY", "CNC", 10, 100.0).total
    expected_cash = round(starting_cash - (10 * 100.0 + costs), 2)
    broker = FakeBroker(cash_inr=98000.0, positions={"TCS": 10}, avg_prices={"TCS": 100.0})
    deltas = compare(broker, FakeLedger(fills), kite_holdings=None, orders=None, starting_cash=starting_cash)
    cash_deltas = [d for d in deltas if d.field == "cash"]
    assert cash_deltas and abs(cash_deltas[0].value_a - expected_cash) < 0.01


def test_compare_no_cash_delta_when_book_reflects_real_costs():
    # book that correctly deducted exchange costs (like PaperBroker._apply_fill does)
    # must NOT be flagged, even though it disagrees with a naive gross-value calc.
    starting_cash = 100000.0
    fills = [_fill("TCS", "BUY", 10, 100.0)]
    costs = estimate_cost("BUY", "CNC", 10, 100.0).total
    real_cash = round(starting_cash - (10 * 100.0 + costs), 2)
    broker = FakeBroker(cash_inr=real_cash, positions={"TCS": 10}, avg_prices={"TCS": 100.0})
    deltas = compare(broker, FakeLedger(fills), kite_holdings=None, orders=None, starting_cash=starting_cash)
    assert not any(d.field == "cash" for d in deltas)


def test_compare_ignores_slippage_between_fills_and_orders():
    # fill settled at slipped price (830.62) vs. order's limit price (830.20), same qty.
    # orders-intent comparison is qty-only, so no avg_price Delta should fire.
    fills = [_fill("TCS", "BUY", 30, 830.62)]
    of_orders = OrdersFile(mode="premarket", orders=[Order(ticker="TCS", side="BUY", quantity=30, price=830.20, status="FILLED")])
    broker = FakeBroker(cash_inr=100000.0, positions={"TCS": 30}, avg_prices={"TCS": 830.62})
    assert compare(broker, FakeLedger(fills), kite_holdings=None, orders=of_orders) == []
