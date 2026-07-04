from tradeloop.dashboard.render import (
    STAGE_META, GLOSSARY, pretty_ticker, render_stage, StageView,
)


def test_pretty_ticker_maps_known_and_falls_back():
    assert pretty_ticker("HDFCBANK") == "HDFC Bank"
    assert pretty_ticker("UNKNOWNXY") == "UNKNOWNXY"


def test_every_stage_has_meta():
    for stage in ("10_news", "11_sentiment", "12_fundamentals", "13_technical",
                  "14_shortlist", "20_bull", "21_bear", "22_debate",
                  "30_trade_plan", "40_risk_report", "41_pm_decision"):
        icon, title, role = STAGE_META[stage]
        assert icon and title and role


def test_news_card_lists_names_in_plain_english():
    raw = {"macro_context": "Banks firm on rate hopes",
           "names_in_play": [{"ticker": "HDFCBANK", "catalyst": "strong Q1 update", "tier": "A"}],
           "macro_themes": ["rate cut hopes"]}
    view = render_stage("10_news", raw)
    assert isinstance(view, StageView)
    assert view.title == "News Expert" and view.icon
    assert "HDFC Bank" in view.summary or any("HDFC Bank" in p for p in view.points)
    assert any("strong Q1 update" in p for p in view.points)


def test_technical_card_translates_classification():
    raw = {"setups": [{"ticker": "SBIN", "classification": "bullish_entry",
                       "news_confirmed": True, "notes": "pullback to EMA20"}]}
    view = render_stage("13_technical", raw)
    assert any("SBIN" in p or "State Bank" in p for p in view.points)
    assert "bullish_entry" not in view.summary  # translated, not raw enum


def test_shortlist_card_ranks_candidates():
    raw = {"candidates": [
        {"ticker": "HDFCBANK", "composite_score": 7.5, "thesis": "breakout on Q1", "catalyst_type": "earnings", "source_track": "tier_a", "horizon": "1-5 days"},
        {"ticker": "SBIN", "composite_score": 4.0, "thesis": "weak pullback", "catalyst_type": "technical", "source_track": "tier_b", "horizon": "1-5 days"}]}
    view = render_stage("14_shortlist", raw)
    assert "2" in view.summary  # count of candidates
    assert view.points[0].startswith("HDFC Bank")  # highest score first


def test_glossary_has_core_terms():
    for term in ("cnc", "hard stop", "breakout", "conviction", "swing"):
        assert term in GLOSSARY and GLOSSARY[term]


def test_unknown_stage_returns_generic_card():
    view = render_stage("99_unknown", {"foo": "bar"})
    assert view.status == "done" and view.title
