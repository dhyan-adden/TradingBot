from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol


@dataclass(frozen=True)
class MarketQuote:
    symbol: str
    source_symbol: str
    last_price: float
    timestamp: str
    source: str


class MarketDataAdapter(Protocol):
    source: str

    def quote(self, symbol: str) -> MarketQuote:
        raise NotImplementedError


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def nse_yfinance_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if normalized.endswith(".NS"):
        return normalized
    return f"{normalized}.NS"
