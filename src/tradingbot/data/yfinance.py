from typing import Any

from tradingbot.data.market import MarketQuote, now_utc_iso, nse_yfinance_symbol


class YFinanceMarketDataAdapter:
    source = "yfinance"

    def quote(self, symbol: str) -> MarketQuote:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise RuntimeError("yfinance is required for YFinanceMarketDataAdapter") from exc

        source_symbol = nse_yfinance_symbol(symbol)
        ticker: Any = yf.Ticker(source_symbol)
        history = ticker.history(period="1d", interval="1m")
        if history.empty:
            history = ticker.history(period="5d", interval="1d")
        if history.empty:
            raise ValueError(f"No YFinance quote data returned for {source_symbol}")

        last_price = float(history["Close"].dropna().iloc[-1])
        timestamp = str(history.index[-1]) if len(history.index) else now_utc_iso()
        return MarketQuote(
            symbol=symbol.strip().upper(),
            source_symbol=source_symbol,
            last_price=last_price,
            timestamp=timestamp,
            source=self.source,
        )
