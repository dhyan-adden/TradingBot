from tradeloop.lib.data.google_news_rss import NewsItem
from tradeloop.lib.data.fundamentals import _snapshot_from_html
from tradeloop.lib.data.news_to_tickers import categorize, extract_tickers, render_news_raw
from tradeloop.lib.data.ticker_master import TickerRecord


def test_news_to_tickers_matches_symbol_and_renders() -> None:
    items = [
        NewsItem("q", "Reliance wins large order as RBI holds rates", "https://example.com", "google_news_generic", "today")
    ]
    records = [TickerRecord(symbol="RELIANCE", name="Reliance Industries", sector="Energy")]

    extraction = extract_tickers(items, records, {"google_news_generic": "tier_C"})
    rendered = render_news_raw(extraction)

    assert "RELIANCE" in extraction.by_ticker
    assert "Macro Stories" in rendered
    assert categorize("Company wins new order") == "order_win"


def test_fundamentals_extracts_screener_number() -> None:
    html = '<li>Stock P/E <span class="number">22.5</span></li>'

    snapshot = _snapshot_from_html("RELIANCE", html, "test")

    assert snapshot.available
    assert snapshot.metrics["pe"] == 22.5
