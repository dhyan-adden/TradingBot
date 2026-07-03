from pathlib import Path
from typing import Mapping

from tradeloop.lib.audit.ledger import Ledger, ORDER_FILLED
from tradeloop.lib.broker.paper_broker import Fill, PaperBroker


def hydrate(path: Path, starting_cash_inr: float) -> PaperBroker:
    # ponytail: body swapped from P0's JSONL replay to the hash-chained ledger;
    # signature unchanged so orchestrator + route_orders_file callers are untouched.
    return Ledger(path).project_positions(starting_cash_inr)


def append(path: Path, fills: list[Fill], hard_stops: Mapping[str, float] | None = None) -> None:
    hard_stops = hard_stops or {}
    led = Ledger(path)
    for fill in fills:
        if fill.status != "FILLED":
            continue
        led.append(
            {
                "type": ORDER_FILLED,
                "order_id": fill.order_id,
                "symbol": fill.symbol,
                "side": fill.side,
                "quantity": fill.quantity,
                "fill_price": fill.fill_price,
                "product": fill.product,
                "hard_stop": float(hard_stops.get(fill.symbol, 0.0)),
            }
        )
