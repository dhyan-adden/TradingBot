from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from tradeloop.lib.audit.ledger import ORDER_FILLED
from tradeloop.lib.broker.cost_model import estimate_cost


@dataclass(frozen=True)
class Position:
    qty: int
    avg_price: float


@dataclass(frozen=True)
class Delta:
    symbol: str
    field: str          # "qty" | "avg_price" | "cash"
    source_a: str
    value_a: float
    source_b: str
    value_b: float


def _apply(book: Dict[str, Position], symbol: str, side: str, qty: int, price: float) -> None:
    """VWAP-average BUYs, net SELLs. Mirrors paper_broker fill math (long-only)."""
    symbol = symbol.strip().upper()
    side = side.strip().upper()
    cur = book.get(symbol, Position(0, 0.0))
    if side == "BUY":
        new_qty = cur.qty + qty
        avg = ((cur.qty * cur.avg_price) + (qty * price)) / new_qty if new_qty else 0.0
        book[symbol] = Position(new_qty, round(avg, 6))
    else:  # SELL reduces qty, avg unchanged
        new_qty = cur.qty - qty
        if new_qty <= 0:
            book.pop(symbol, None)
        else:
            book[symbol] = Position(new_qty, cur.avg_price)


def positions_from_fills(fills: List[dict]) -> Dict[str, Position]:
    book: Dict[str, Position] = {}
    for f in fills:
        # Real ledger ORDER_FILLED events carry no "status" key (project_positions
        # hardcodes FILLED); only synthetic/routing dicts do. Default FILLED so
        # replayed fills are not silently dropped.
        if str(f.get("status", "FILLED")).upper() != "FILLED":
            continue
        _apply(book, str(f["symbol"]), str(f["side"]), int(f["quantity"]), float(f["fill_price"]))
    return book


def positions_from_orders(orders) -> Dict[str, Position]:
    """Intent minus rejects: replay only non-REJECTED orders at their order price."""
    book: Dict[str, Position] = {}
    for o in orders.orders:
        if str(getattr(o, "status", "") or "").upper() == "REJECTED":
            continue
        _apply(book, o.ticker, o.side, int(o.quantity), float(o.price))
    return book


def positions_from_kite(holdings: List[dict]) -> Dict[str, Position]:
    book: Dict[str, Position] = {}
    for h in holdings:
        symbol = str(h["tradingsymbol"]).strip().upper()
        book[symbol] = Position(int(h["quantity"]), round(float(h["average_price"]), 6))
    return book


def _cash_from_fills(fills: List[dict], starting_cash: float) -> float:
    """Mirrors PaperBroker._apply_fill exactly: BUY deducts value+costs, SELL adds
    value-costs, where costs come from the same cost_model.estimate_cost the real
    book uses (brokerage/STT/stamp/GST/DP) - not gross value alone."""
    cash = starting_cash
    for f in fills:
        if str(f.get("status", "FILLED")).upper() != "FILLED":  # ledger fills carry no status key
            continue
        side = str(f["side"]).upper()
        quantity = int(f["quantity"])
        price = float(f["fill_price"])
        product = str(f.get("product", "CNC")).upper()
        value = price * quantity
        costs = estimate_cost(side, "MIS" if product == "MIS" else "CNC", quantity, price).total
        cash += -(value + costs) if side == "BUY" else (value - costs)
    return round(cash, 2)


def _diff(a: Dict[str, Position], b: Dict[str, Position], src_a: str, src_b: str, tol: float,
          fields: Sequence[str] = ("qty", "avg_price")) -> List[Delta]:
    out: List[Delta] = []
    for symbol in sorted(set(a) | set(b)):
        pa = a.get(symbol, Position(0, 0.0))
        pb = b.get(symbol, Position(0, 0.0))
        if "qty" in fields and pa.qty != pb.qty:
            out.append(Delta(symbol, "qty", src_a, float(pa.qty), src_b, float(pb.qty)))
        if "avg_price" in fields and abs(pa.avg_price - pb.avg_price) > tol and pa.qty and pb.qty:
            out.append(Delta(symbol, "avg_price", src_a, pa.avg_price, src_b, pb.avg_price))
    return out


def compare(book, ledger, kite_holdings: Optional[List[dict]] = None,
            orders=None, starting_cash: Optional[float] = None, tol: float = 0.01) -> List[Delta]:
    """Reconcile positions across independent derivations; return every disagreement."""
    fills = ledger.replay([ORDER_FILLED])
    from_fills = positions_from_fills(fills)
    book_positions = {
        s.strip().upper(): Position(int(q), round(float(book.avg_prices.get(s, 0.0)), 6))
        for s, q in book.positions.items()
    }

    deltas: List[Delta] = _diff(from_fills, book_positions, "fills_replay", "book", tol)
    if orders is not None:
        # fills settle at slipped prices, order price is the limit - qty only, avg_price
        # would false-positive on every normally-slipped fill.
        deltas += _diff(from_fills, positions_from_orders(orders), "fills_replay", "orders_intent", tol,
                         fields=("qty",))
    if kite_holdings is not None:
        deltas += _diff(book_positions, positions_from_kite(kite_holdings), "book", "kite_holdings", tol)
    if starting_cash is not None:
        derived_cash = _cash_from_fills(fills, starting_cash)
        if abs(derived_cash - book.cash_inr) > tol:
            deltas.append(Delta("_CASH_", "cash", "fills_replay", derived_cash, "book", round(book.cash_inr, 2)))
    return deltas
