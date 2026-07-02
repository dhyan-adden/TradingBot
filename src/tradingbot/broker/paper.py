from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict

from tradingbot.event_log import Event, EventLog


@dataclass(frozen=True)
class PaperOrderRequest:
    symbol: str
    side: str
    quantity: int
    price: float
    strategy: str = "manual"
    source: str = "paper"


@dataclass(frozen=True)
class PaperPortfolio:
    cash_inr: float
    positions: Dict[str, int]
    avg_prices: Dict[str, float]
    realized_pnl_inr: float


def utc_now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


class PaperBroker:
    def __init__(self, event_log: EventLog, starting_cash_inr: float, order_prefix: str = "PAPER"):
        self.event_log = event_log
        self.starting_cash_inr = float(starting_cash_inr)
        self.order_prefix = order_prefix

    def portfolio(self) -> PaperPortfolio:
        cash = self.starting_cash_inr
        positions: Dict[str, int] = {}
        avg_prices: Dict[str, float] = {}
        realized = 0.0

        for event in self.event_log.replay():
            payload = event.payload
            if event.event_type != "paper.order.filled":
                continue
            symbol = str(payload["symbol"])
            side = str(payload["side"]).upper()
            quantity = int(payload["quantity"])
            price = float(payload["fill_price"])
            value = quantity * price
            if side == "BUY":
                old_qty = positions.get(symbol, 0)
                old_avg = avg_prices.get(symbol, 0.0)
                new_qty = old_qty + quantity
                avg_prices[symbol] = ((old_qty * old_avg) + value) / new_qty
                positions[symbol] = new_qty
                cash -= value
            elif side == "SELL":
                old_qty = positions.get(symbol, 0)
                close_qty = min(old_qty, quantity)
                avg = avg_prices.get(symbol, 0.0)
                positions[symbol] = old_qty - close_qty
                cash += close_qty * price
                realized += close_qty * (price - avg)
                if positions[symbol] == 0:
                    positions.pop(symbol, None)
                    avg_prices.pop(symbol, None)

        return PaperPortfolio(
            cash_inr=round(cash, 2),
            positions=positions,
            avg_prices={k: round(v, 4) for k, v in avg_prices.items()},
            realized_pnl_inr=round(realized, 2),
        )

    def place_order(self, request: PaperOrderRequest) -> Event:
        symbol = request.symbol.strip().upper()
        side = request.side.strip().upper()
        order_id = self._next_order_id(symbol)
        created_payload = {
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "quantity": request.quantity,
            "price": request.price,
            "strategy": request.strategy,
            "source": request.source,
        }
        self.event_log.append_event("paper.order.created", order_id, created_payload)

        rejection = self._rejection_reason(symbol, side, request.quantity, request.price)
        if rejection:
            return self.event_log.append_event(
                "paper.order.rejected",
                order_id,
                {**created_payload, "reason": rejection},
            )

        fill_payload = {
            **created_payload,
            "fill_price": float(request.price),
            "fill_value": round(float(request.price) * int(request.quantity), 2),
            "status": "FILLED",
        }
        event = self.event_log.append_event("paper.order.filled", order_id, fill_payload)
        position_event = "paper.position.opened" if side == "BUY" else "paper.position.closed"
        self.event_log.append_event(position_event, f"POSITION-{symbol}", fill_payload)
        return event

    def mark_to_market(self, symbol: str, last_price: float, source: str) -> Event:
        portfolio = self.portfolio()
        normalized = symbol.strip().upper()
        quantity = portfolio.positions.get(normalized, 0)
        avg_price = portfolio.avg_prices.get(normalized, 0.0)
        unrealized = quantity * (float(last_price) - avg_price)
        return self.event_log.append_event(
            "paper.position.marked",
            f"POSITION-{normalized}",
            {
                "symbol": normalized,
                "quantity": quantity,
                "avg_price": avg_price,
                "last_price": float(last_price),
                "unrealized_pnl_inr": round(unrealized, 2),
                "source": source,
            },
        )

    def _rejection_reason(self, symbol: str, side: str, quantity: int, price: float) -> str:
        if quantity <= 0:
            return "quantity_must_be_positive"
        if price <= 0:
            return "price_must_be_positive"

        portfolio = self.portfolio()
        if side == "BUY" and quantity * price > portfolio.cash_inr:
            return "insufficient_cash"
        if side == "SELL" and quantity > portfolio.positions.get(symbol, 0):
            return "insufficient_position"
        if side not in {"BUY", "SELL"}:
            return "unsupported_side"
        return ""

    def _next_order_id(self, symbol: str) -> str:
        existing = list(self.event_log.by_types(["paper.order.created"]))
        return f"{self.order_prefix}-{utc_now_compact()}-{symbol}-{len(existing) + 1:04d}"


def portfolio_value(portfolio: PaperPortfolio, marks: Dict[str, float]) -> float:
    value = portfolio.cash_inr
    for symbol, quantity in portfolio.positions.items():
        value += quantity * float(marks.get(symbol, portfolio.avg_prices.get(symbol, 0.0)))
    return round(value, 2)
