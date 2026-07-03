import json
from pathlib import Path

from tradeloop.lib.broker.paper_broker import Fill, OrderTicket, PaperBroker


def hydrate(book_path: Path, starting_cash_inr: float, slippage_bps: float = 5) -> PaperBroker:
    """Rebuild a PaperBroker by replaying every persisted FILLED fill through
    the broker's own fill math. Replay runs at slippage 0 so a stored fill
    reproduces exactly; the broker is handed back at `slippage_bps` so NEW
    orders keep realistic slippage. Missing book file => empty book at
    starting cash (first run)."""
    broker = PaperBroker(cash_inr=float(starting_cash_inr), slippage_bps=0)
    path = Path(book_path)
    if not path.exists():
        broker.slippage_bps = float(slippage_bps)
        return broker
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if rec.get("status") != "FILLED":
            continue
        broker.place_order(
            OrderTicket(
                symbol=str(rec["symbol"]).strip().upper(),
                side=rec["side"],
                quantity=int(rec["quantity"]),
                price=float(rec["fill_price"]),
                product=str(rec.get("product", "CNC")),
            )
        )
    broker.slippage_bps = float(slippage_bps)
    return broker


def append(book_path: Path, fills: list[Fill], hard_stops: dict[str, float] | None = None) -> None:
    """Append FILLED fills as JSON lines (append-only, never rewrites). Each
    line carries hard_stop (from hard_stops[symbol]) so open-risk can be
    computed from held positions when the book is replayed."""
    # ponytail: flat JSONL book now; Phase 2 replaces it with the hash-chained
    # SQLite event log behind the same hydrate/append interface.
    hard_stops = hard_stops or {}
    path = Path(book_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for fill in fills:
        if fill.status != "FILLED":
            continue
        rec = dict(fill.__dict__)
        rec["hard_stop"] = hard_stops.get(fill.symbol)
        lines.append(json.dumps(rec, default=str))
    if lines:
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
