from tradingbot.data.router import normalize_indian_symbol, vendor_chain


def test_vendor_chain_splits_configured_fallbacks() -> None:
    assert vendor_chain("yfinance,zerodha") == ["yfinance", "zerodha"]


def test_normalize_nse_symbol_for_yfinance_and_benchmark() -> None:
    instrument = normalize_indian_symbol("RELIANCE", exchange="NSE")

    assert instrument.symbol == "RELIANCE"
    assert instrument.exchange == "NSE"
    assert instrument.yfinance_symbol == "RELIANCE.NS"
    assert instrument.benchmark_symbol == "^NSEI"
    assert instrument.currency == "INR"


def test_normalize_bse_symbol_for_yfinance_and_benchmark() -> None:
    instrument = normalize_indian_symbol("RELIANCE", exchange="BSE")

    assert instrument.symbol == "RELIANCE"
    assert instrument.exchange == "BSE"
    assert instrument.yfinance_symbol == "RELIANCE.BO"
    assert instrument.benchmark_symbol == "^BSESN"


def test_preserves_existing_exchange_suffix() -> None:
    instrument = normalize_indian_symbol("INFY.NS", exchange="NSE")

    assert instrument.symbol == "INFY"
    assert instrument.yfinance_symbol == "INFY.NS"
