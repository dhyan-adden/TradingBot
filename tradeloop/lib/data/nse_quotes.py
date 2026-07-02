from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, List


@dataclass(frozen=True)
class Quote:
    symbol: str
    source_symbol: str
    last_price: float
    timestamp: str
    source: str


def normalize_nse_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if normalized.endswith(".NS"):
        return normalized
    if normalized.endswith(".BO"):
        return normalized
    return f"{normalized}.NS"


def base_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    return normalized.removesuffix(".NS").removesuffix(".BO")


def quote(symbol: str) -> Quote:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("yfinance is required for NSE quote fetches") from exc

    source_symbol = normalize_nse_symbol(symbol)
    ticker: Any = yf.Ticker(source_symbol)
    history = ticker.history(period="1d", interval="1m")
    if history.empty:
        history = ticker.history(period="5d", interval="1d")
    if history.empty:
        raise ValueError(f"No quote data returned for {source_symbol}")
    close = history["Close"].dropna()
    if close.empty:
        raise ValueError(f"No close price returned for {source_symbol}")
    timestamp = str(history.index[-1]) if len(history.index) else datetime.now(timezone.utc).isoformat()
    return Quote(
        symbol=base_symbol(symbol),
        source_symbol=source_symbol,
        last_price=float(close.iloc[-1]),
        timestamp=timestamp,
        source="yfinance",
    )


def quotes(symbols: Iterable[str]) -> List[Quote]:
    return [quote(symbol) for symbol in symbols]


def fetch_ohlcv(symbol: str, period: str = "6mo", interval: str = "1d", cache_dir: Path | None = None):
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("yfinance is required for NSE OHLCV fetches") from exc

    source_symbol = normalize_nse_symbol(symbol)
    cache_path = None
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        safe_interval = interval.replace("/", "_")
        cache_path = cache_dir / f"{source_symbol}_{period}_{safe_interval}.csv"
        if cache_path.exists():
            import pandas as pd

            return pd.read_csv(cache_path, index_col=0, parse_dates=True)

    data = yf.Ticker(source_symbol).history(period=period, interval=interval, auto_adjust=False)
    if data.empty:
        try:
            from nsepy import get_history  # type: ignore
        except ImportError as exc:
            raise ValueError(f"No YFinance OHLCV data returned for {source_symbol}") from exc
        raise ValueError("nsepy fallback requires explicit date range and is not configured in v1")
    if "Adj Close" in data.columns:
        data["AdjustedClose"] = data["Adj Close"]
    if cache_path is not None:
        data.to_csv(cache_path)
    return data
