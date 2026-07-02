from tradingbot.data.market import nse_yfinance_symbol


def test_nse_yfinance_symbol_adds_suffix() -> None:
    assert nse_yfinance_symbol("RELIANCE") == "RELIANCE.NS"


def test_nse_yfinance_symbol_preserves_existing_suffix() -> None:
    assert nse_yfinance_symbol("INFY.NS") == "INFY.NS"
