from dataclasses import asdict
from typing import Dict

from tradeloop.lib.broker.paper_broker import OrderTicket


def to_zerodha_payload(ticket: OrderTicket, exchange: str = "NSE", confirm: bool = False) -> Dict[str, object]:
    """Build the payload Codex should pass to the project-local Zerodha MCP.

    Python does not call the MCP directly in v1. Codex Chat/CLI owns tool calls.
    SELL tickets are exits only; callers must run portfolio-aware risk checks
    before building this payload.
    """

    requested_product = ticket.product.strip().upper()
    if requested_product == "NRML":
        raise ValueError("NRML is forbidden in TradeLoop")
    product = requested_product if requested_product in {"CNC", "MIS"} else "CNC"
    return {
        "variety": "regular",
        "exchange": exchange,
        "tradingsymbol": ticket.symbol.strip().upper(),
        "transaction_type": ticket.side,
        "quantity": int(ticket.quantity),
        "product": product,
        "order_type": "LIMIT",
        "price": float(ticket.price),
        "validity": "DAY",
        "tag": "TRADELOOP",
        "confirm": bool(confirm),
        "source_ticket": asdict(ticket),
    }
