import os
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from tradeloop.lib.broker.paper_broker import Fill, OrderTicket, PaperBroker
from tradeloop.lib.broker.zerodha_mcp import to_zerodha_payload
from tradeloop.lib.risk.circuit_breaker import kill_switch_active


@dataclass(frozen=True)
class RoutedOrder:
    mode: str
    status: str
    payload: Dict[str, object]


def live_enabled() -> bool:
    return os.getenv("ZERODHA_ENABLE_TRADING", "false").strip().lower() == "true"


def route_order(
    ticket: OrderTicket,
    paper_broker: PaperBroker,
    confirm_live: bool = False,
    root: Path = Path("tradeloop"),
) -> RoutedOrder:
    if kill_switch_active(root):
        return RoutedOrder("blocked", "KILL_SWITCH_ACTIVE", {"symbol": ticket.symbol, "side": ticket.side})
    if not live_enabled():
        fill: Fill = paper_broker.place_order(ticket)
        return RoutedOrder("paper", fill.status, fill.__dict__)
    if not live_promotion_ready(root):
        return RoutedOrder("blocked", "LIVE_PROMOTION_GATE_NOT_CLEARED", {"symbol": ticket.symbol, "side": ticket.side})
    payload = to_zerodha_payload(ticket, confirm=confirm_live)
    return RoutedOrder("live_mcp_required", "READY_FOR_CODEX_TOOL_CALL", payload)


def live_promotion_ready(root: Path = Path("tradeloop")) -> bool:
    performance = root / "memory" / "strategy_performance.md"
    if not performance.exists():
        return False
    text = performance.read_text(encoding="utf-8").lower()
    if "live_ready: true" in text:
        return True
    paper_trades = _metric(text, "paper_trades")
    win_rate = _metric(text, "win_rate")
    expectancy = _metric(text, "expectancy_r")
    drawdown = _metric(text, "max_drawdown_pct")
    return paper_trades >= 40 and win_rate >= 0.45 and expectancy >= 0.3 and drawdown <= 8


def _metric(text: str, key: str) -> float:
    match = re.search(rf"{re.escape(key)}\s*:\s*([-+]?\d+(?:\.\d+)?)", text)
    return float(match.group(1)) if match else 0.0


def ticket_from_order(order: Dict[str, object]) -> OrderTicket:
    return OrderTicket(
        symbol=str(order.get("ticker") or order.get("symbol", "")).strip().upper(),
        side=str(order.get("side", "BUY")).strip().upper(),  # type: ignore[arg-type]
        quantity=int(order.get("quantity", 0)),
        price=float(order.get("price", order.get("entry", 0))),
        product=str(order.get("product", "CNC")).strip().upper(),
        reason=str(order.get("reason", "")),
    )


def route_orders_file(orders_path: Path, fills_path: Path, paper_broker: PaperBroker, root: Path = Path("tradeloop")) -> list[RoutedOrder]:
    orders = json.loads(orders_path.read_text(encoding="utf-8")) if orders_path.exists() else []
    routed: list[RoutedOrder] = []
    for order in orders:
        routed.append(route_order(ticket_from_order(order), paper_broker, confirm_live=False, root=root))
    fills_path.write_text(json.dumps([item.__dict__ for item in routed], indent=2, default=str), encoding="utf-8")
    return routed
