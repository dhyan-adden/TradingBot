"""Phase 2 (batch 2): live expected-position book.

The paper ledger simulates positions and must never authorize a real SELL. The
live book records only symbols TradeLoop believes it owns in Zerodha, populated
by broker-confirmed fill sync (never by payload generation).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

LIVE_BOOK_FILE = "live_book.json"


def load_live_expected_book(root: Path) -> Dict[str, int]:
    """Expected live positions by symbol. Missing file -> empty book. Malformed
    file fails closed (raises ValueError) so route code blocks reconciliation."""
    path = Path(root) / "state" / LIVE_BOOK_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise ValueError(f"malformed {path}: {exc}") from exc
    positions = data.get("positions")
    if not isinstance(positions, dict):
        raise ValueError(f"malformed {path}: positions must be an object")
    out: Dict[str, int] = {}
    for sym, qty in positions.items():
        symbol = str(sym).strip().upper()
        if not symbol:
            continue
        try:
            quantity = int(qty)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"malformed {path}: non-integer qty for {symbol}") from exc
        if quantity < 0:
            raise ValueError(f"malformed {path}: negative qty for {symbol}")
        if quantity > 0:
            out[symbol] = quantity
    return out


def persist_live_expected_book(root: Path, positions: Dict[str, int], source: str) -> None:
    """Persist expected live positions. Reserved for broker-confirmed fill sync."""
    state = Path(root) / "state"
    state.mkdir(parents=True, exist_ok=True)
    cleaned = {str(sym).strip().upper(): int(qty)
               for sym, qty in positions.items() if int(qty) > 0}
    (state / LIVE_BOOK_FILE).write_text(json.dumps({
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "positions": cleaned,
        "source": source,
    }, indent=2), encoding="utf-8")