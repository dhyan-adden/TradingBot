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
