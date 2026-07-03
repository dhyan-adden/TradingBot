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
