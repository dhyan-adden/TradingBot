from dataclasses import dataclass
from typing import Dict, List

from tradingbot.data.market import nse_yfinance_symbol


@dataclass(frozen=True)
class MarketInstrument:
    symbol: str
    exchange: str
    yfinance_symbol: str
    benchmark_symbol: str
    currency: str = "INR"


def vendor_chain(vendor_config: str) -> List[str]:
    return [item.strip() for item in vendor_config.split(",") if item.strip()]


def normalize_indian_symbol(
    symbol: str,
    exchange: str = "NSE",
    suffixes: Dict[str, str] | None = None,
    benchmarks: Dict[str, str] | None = None,
) -> MarketInstrument:
    normalized_exchange = exchange.strip().upper()
    normalized_symbol = symbol.strip().upper()
    suffix_map = suffixes or {"NSE": ".NS", "BSE": ".BO"}
    benchmark_map = benchmarks or {"NSE": "^NSEI", "BSE": "^BSESN"}
    suffix = suffix_map.get(normalized_exchange, ".NS")

    if normalized_symbol.endswith(".NS") or normalized_symbol.endswith(".BO"):
        yfinance_symbol = normalized_symbol
    elif normalized_exchange == "NSE":
        yfinance_symbol = nse_yfinance_symbol(normalized_symbol)
    else:
        yfinance_symbol = f"{normalized_symbol}{suffix}"

    return MarketInstrument(
        symbol=normalized_symbol.removesuffix(".NS").removesuffix(".BO"),
        exchange=normalized_exchange,
        yfinance_symbol=yfinance_symbol,
        benchmark_symbol=benchmark_map.get(normalized_exchange, "^NSEI"),
    )
