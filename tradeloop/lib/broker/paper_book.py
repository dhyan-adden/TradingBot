from pathlib import Path
from typing import Mapping

from tradeloop.lib.audit.ledger import Ledger, ORDER_FILLED
from tradeloop.lib.broker.paper_broker import Fill, PaperBroker


def hydrate(path: Path, starting_cash_inr: float) -> PaperBroker:
    # ponytail: body swapped from P0's JSONL replay to the hash-chained ledger;
    # signature unchanged so orchestrator + route_orders_file callers are untouched.
    return Ledger(path).project_positions(starting_cash_inr)


def append(path: Path, fills: list[Fill], hard_stops: Mapping[str, float] | None = None,
           plan_meta: Mapping[str, Mapping] | None = None) -> None:
    hard_stops = hard_stops or {}
    plan_meta = plan_meta or {}
    led = Ledger(path)
    for fill in fills:
        if fill.status != "FILLED":
            continue
        event = {
            "type": ORDER_FILLED,
            "order_id": fill.order_id,
            "symbol": fill.symbol,
            "side": fill.side,
            "quantity": fill.quantity,
            "fill_price": fill.fill_price,
            "product": fill.product,
            "hard_stop": float(hard_stops.get(fill.symbol, 0.0)),
        }
        # Plan data (target, strategy) rides the entry fill so attribution can
        # score the trade whenever it closes - the closing run's orders.json
        # never carries the entry plan.
        meta = plan_meta.get(fill.symbol) or {}
        if meta.get("target_1") is not None:
            event["target_1"] = float(meta["target_1"])
        if meta.get("strategy_family"):
            event["strategy_family"] = str(meta["strategy_family"])
        led.append(event)
