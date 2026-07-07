from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Literal

from tradeloop.lib.broker.cost_model import estimate_cost


Side = Literal["BUY", "SELL"]


@dataclass(frozen=True)
class OrderTicket:
    symbol: str
    side: Side
    quantity: int
    price: float
    product: str = "CNC"
    reason: str = ""


@dataclass(frozen=True)
class Fill:
    order_id: str
    symbol: str
    side: Side
    quantity: int
    fill_price: float
    status: str
    product: str = "CNC"
    reason: str = ""


@dataclass
class PaperBroker:
    cash_inr: float
    slippage_bps: float = 5
    positions: Dict[str, int] = field(default_factory=dict)
    avg_prices: Dict[str, float] = field(default_factory=dict)
    fills: List[Fill] = field(default_factory=list)

    def place_order(self, ticket: OrderTicket) -> Fill:
        normalized = ticket.symbol.strip().upper()
        rejection = self._rejection_reason(normalized, ticket)
        order_id = self._order_id(normalized)
        if rejection:
            fill = Fill(order_id, normalized, ticket.side, ticket.quantity, 0.0, "REJECTED", ticket.product, rejection)
            self.fills.append(fill)
            return fill

        fill_price = self._slipped_price(ticket.price, ticket.side)
        fill = Fill(order_id, normalized, ticket.side, ticket.quantity, fill_price, "FILLED", ticket.product)
        self._apply_fill(fill)
        self.fills.append(fill)
        return fill

    def _rejection_reason(self, symbol: str, ticket: OrderTicket) -> str:
        if ticket.side not in {"BUY", "SELL"}:
            return "unsupported_side"
        if ticket.quantity <= 0:
            return "quantity_must_be_positive"
        if ticket.price <= 0:
            return "price_must_be_positive"
        if ticket.product not in {"CNC", "MIS"}:
            return "unsupported_product"
        if ticket.side == "BUY" and self._slipped_price(ticket.price, ticket.side) * ticket.quantity > self.cash_inr:
            return "insufficient_cash"
        if ticket.side == "SELL" and ticket.quantity > self.positions.get(symbol, 0):
            return "long_only_sell_exceeds_position"
        return ""

    def _apply_fill(self, fill: Fill) -> None:
        value = fill.fill_price * fill.quantity
        costs = estimate_cost(fill.side, "MIS" if fill.product == "MIS" else "CNC", fill.quantity, fill.fill_price).total
        if fill.side == "BUY":
            old_quantity = self.positions.get(fill.symbol, 0)
            old_average = self.avg_prices.get(fill.symbol, 0.0)
            new_quantity = old_quantity + fill.quantity
            self.avg_prices[fill.symbol] = ((old_quantity * old_average) + value) / new_quantity
            self.positions[fill.symbol] = new_quantity
            self.cash_inr -= value + costs
            return
        existing = self.positions.get(fill.symbol, 0)
        self.positions[fill.symbol] = existing - fill.quantity
        self.cash_inr += value - costs
        if self.positions[fill.symbol] == 0:
            self.positions.pop(fill.symbol, None)
            self.avg_prices.pop(fill.symbol, None)

    def _slipped_price(self, price: float, side: Side) -> float:
        multiplier = 1 + (self.slippage_bps / 10000) if side == "BUY" else 1 - (self.slippage_bps / 10000)
        return round(float(price) * multiplier, 2)

    def _order_id(self, symbol: str) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"PAPER-{stamp}-{symbol}-{len(self.fills) + 1:04d}"
