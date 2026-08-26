"""Portfolio + transaction view over the hash-chained ledger (read-only).

Holdings/cash come from Ledger.project_positions (the authoritative replay);
this module adds the human view: dated transactions, realized P&L per SELL
(avg-cost basis, same cost model as the broker), and best-effort live marks.
"""
from __future__ import annotations

from pathlib import Path

from tradeloop.lib.audit.ledger import ORDER_FILLED, Ledger
from tradeloop.lib.broker.cost_model import estimate_cost


def _flat(starting_cash_inr: float) -> dict:
    return {
        "cash_inr": round(starting_cash_inr, 2),
        "invested_inr": 0.0,
        "market_value_inr": 0.0,
        "equity_inr": round(starting_cash_inr, 2),
        "unrealized_pnl_inr": 0.0,
        "realized_pnl_inr": 0.0,
        "return_pct": 0.0,
        "prices_live": False,
        "holdings": [],
        "transactions": [],
        "exposure": {
            "deployed_pct": 0.0,
            "open_positions": 0,
            "positions_limit": None,
            "sector_exposure": [],
        },
    }


def portfolio_view(ledger_path: Path, starting_cash_inr: float, price_fn=None,
                   max_open_positions: int | None = None,
                   sector_map: dict[str, str] | None = None) -> dict:
    """price_fn: (list[str]) -> {symbol: ltp}; failures degrade to book values."""
    ledger_path = Path(ledger_path)
    if not ledger_path.exists():
        return _flat(starting_cash_inr)

    led = Ledger(ledger_path)
    events = led.replay([ORDER_FILLED])
    book = led.project_positions(starting_cash_inr)

    # Transaction list + realized P&L need the avg cost AT SELL TIME, so walk
    # the events with the same avg-cost + cost-model math as PaperBroker.
    avg: dict[str, float] = {}
    qty: dict[str, int] = {}
    stops: dict[str, float] = {}
    realized_total = 0.0
    transactions = []
    for e in events:
        symbol, side = e["symbol"], e["side"]
        quantity, price = int(e["quantity"]), float(e["fill_price"])
        product = e.get("product", "CNC")
        value = price * quantity
        costs = estimate_cost(side, "MIS" if product == "MIS" else "CNC", quantity, price).total
        realized = None
        if side == "BUY":
            old_q = qty.get(symbol, 0)
            avg[symbol] = ((old_q * avg.get(symbol, 0.0)) + value) / (old_q + quantity)
            qty[symbol] = old_q + quantity
        else:
            realized = (value - costs) - avg.get(symbol, 0.0) * quantity
            realized_total += realized
            qty[symbol] = qty.get(symbol, 0) - quantity
            if qty[symbol] <= 0:
                qty.pop(symbol, None)
                avg.pop(symbol, None)
        if float(e.get("hard_stop", 0.0)) > 0:
            stops[symbol] = float(e["hard_stop"])
        transactions.append({
            "ts": e.get("ts", ""),
            "order_id": e.get("order_id", ""),
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": round(price, 2),
            "value_inr": round(value, 2),
            "costs_inr": round(costs, 2),
            "realized_pnl_inr": round(realized, 2) if realized is not None else None,
        })

    prices: dict[str, float] = {}
    if price_fn is not None and book.positions:
        try:
            prices = dict(price_fn(sorted(book.positions))) or {}
        except Exception:
            prices = {}  # stale token / MCP down -> book values, never a crash

    holdings = []
    invested_total = market_total = 0.0
    sector_totals: dict[str, float] = {}
    for symbol in sorted(book.positions):
        quantity = book.positions[symbol]
        avg_price = book.avg_prices.get(symbol, 0.0)
        invested = avg_price * quantity
        ltp = prices.get(symbol)
        market = (ltp if ltp is not None else avg_price) * quantity
        stop = stops.get(symbol)
        holdings.append({
            "symbol": symbol,
            "quantity": quantity,
            "avg_price": round(avg_price, 2),
            "invested_inr": round(invested, 2),
            "ltp": round(ltp, 2) if ltp is not None else None,
            "market_value_inr": round(market, 2),
            "unrealized_pnl_inr": round(market - invested, 2) if ltp is not None else None,
            "unrealized_pct": round((market - invested) / invested * 100, 2) if ltp is not None and invested else None,
            "hard_stop": stop,
            "stop_distance_pct": round((ltp - stop) / ltp * 100, 2) if ltp is not None and stop else None,
        })
        sector = (sector_map or {}).get(symbol, "UNKNOWN") or "UNKNOWN"
        sector_totals[sector] = sector_totals.get(sector, 0.0) + market
        invested_total += invested
        market_total += market

    equity = book.cash_inr + market_total
    sector_exposure = [{
        "sector": sector,
        "market_value_inr": round(value, 2),
        "equity_pct": round(value / equity * 100, 2) if equity else 0.0,
    } for sector, value in sorted(sector_totals.items(), key=lambda item: item[1], reverse=True)]
    return {
        "cash_inr": round(book.cash_inr, 2),
        "invested_inr": round(invested_total, 2),
        "market_value_inr": round(market_total, 2),
        "equity_inr": round(equity, 2),
        "unrealized_pnl_inr": round(market_total - invested_total, 2) if prices else None,
        "realized_pnl_inr": round(realized_total, 2),
        "return_pct": round((equity - starting_cash_inr) / starting_cash_inr * 100, 2),
        "prices_live": bool(prices),
        "holdings": holdings,
        "transactions": list(reversed(transactions)),  # newest first for display
        "exposure": {
            "deployed_pct": round(market_total / equity * 100, 2) if equity else 0.0,
            "open_positions": len(book.positions),
            "positions_limit": max_open_positions,
            "sector_exposure": sector_exposure,
        },
    }
