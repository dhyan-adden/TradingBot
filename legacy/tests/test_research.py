from tradingbot.research import ResearchItem, StaticResearchProvider, scan_market_news


def item(symbol: str, title: str) -> ResearchItem:
    return ResearchItem(
        symbol=symbol,
        title=title,
        url=f"https://example.com/{symbol.lower()}",
        source="test",
        published_at="2026-05-16T09:15:00+05:30",
    )


def test_scan_market_news_scores_configured_symbols() -> None:
    provider = StaticResearchProvider(
        [
            item("RELIANCE", "Reliance profit growth strong"),
            item("TCS", "TCS shares fall on weak outlook"),
        ]
    )

    shortlist = scan_market_news(provider, ["RELIANCE", "TCS"], max_shortlist=1)

    assert [candidate.symbol for candidate in shortlist] == ["RELIANCE"]
    assert shortlist[0].score > 0
    assert shortlist[0].sentiment == "positive"


def test_scan_market_news_falls_back_to_universe_when_news_missing() -> None:
    provider = StaticResearchProvider([])

    shortlist = scan_market_news(provider, ["RELIANCE", "TCS"], max_shortlist=2)

    assert [candidate.symbol for candidate in shortlist] == ["RELIANCE", "TCS"]
    assert all(candidate.reason.startswith("Fallback") for candidate in shortlist)
