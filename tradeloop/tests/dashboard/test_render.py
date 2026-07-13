from tradeloop.dashboard.render import (
    STAGE_META, GLOSSARY, pretty_ticker, render_debate, render_stage, StageView,
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


def test_debate_card_shows_the_judges_rationale():
    raw = {"names": [{"ticker": "HDFCBANK", "conviction": 6.0, "verdict": "watch",
                      "rationale": "bear's earnings-risk point outweighs the buy call"}]}
    view = render_stage("22_debate", raw)
    assert any("bear's earnings-risk point" in p for p in view.points)


def test_debate_card_renders_legacy_runs_without_rationale():
    # pre-rationale archives must render exactly as before, no trailing separator
    raw = {"names": [{"ticker": "SBIN", "conviction": 4.0, "verdict": "pass"}]}
    view = render_stage("22_debate", raw)
    assert view.points == ["State Bank of India: passed on (conviction 4.0/10)"]


def test_debate_card_carries_the_complete_exchange_per_name():
    # the full recorded debate: bull claims + bear claims grouped under each
    # name's verdict, in the judge's order - not scattered across three cards
    debate = {"names": [
        {"ticker": "UTIAMC", "conviction": 6.0, "verdict": "tradeable", "rationale": "risk tightest"},
        {"ticker": "HEG", "conviction": 5.5, "verdict": "tradeable"},
    ]}
    bull = {"arguments": [
        {"ticker": "UTIAMC", "claim": "volume-confirmed breakout"},
        {"ticker": "UTIAMC", "claim": "3.5% stop"},
        {"ticker": "HEG", "claim": "clean structure"},
    ]}
    bear = {"arguments": [{"ticker": "UTIAMC", "claim": "beta rally risk"}]}
    view = render_debate(debate, bull, bear)
    assert view.points == [
        "UTIAMC: green-lit to trade (conviction 6.0/10) - risk tightest",
        "For: volume-confirmed breakout",
        "For: 3.5% stop",
        "Against: beta rally risk",
        "HEG: green-lit to trade (conviction 5.5/10)",
        "For: clean structure",
    ]


def test_debate_card_without_bull_bear_falls_back_to_verdicts():
    debate = {"names": [{"ticker": "SBIN", "conviction": 4.0, "verdict": "pass"}]}
    view = render_debate(debate, None, None)
    assert view.points == ["State Bank of India: passed on (conviction 4.0/10)"]


def test_glossary_has_core_terms():
    for term in ("cnc", "hard stop", "breakout", "conviction", "swing"):
        assert term in GLOSSARY and GLOSSARY[term]


def test_cards_carry_the_model_that_actually_ran():
    # the badge reflects the model read from the run's audit log, not a config guess
    assert render_stage("22_debate", {}, "claude:opus").model == "Claude Opus"
    assert render_stage("10_news", {}, "claude:sonnet").model == "Claude Sonnet"
    # legacy OpenRouter runs still render their true historical model
    assert render_stage("22_debate", {}, "minimax/minimax-m3").model == "MiniMax M3"
    # no recorded call -> no badge, never a fabricated one
    assert render_stage("10_news", {}).model == ""


def test_unknown_stage_returns_generic_card():
    view = render_stage("99_unknown", {"foo": "bar"})
    assert view.status == "done" and view.title


def test_render_holdings_review_stage():
    from tradeloop.dashboard.render import render_stage
    raw = {"reviews": [
        {"ticker": "HDFCBANK", "verdict": "HOLD", "conviction": 6.0,
         "reason_code": "thesis_intact", "rationale": "steady into results"},
        {"ticker": "SBIN", "verdict": "EXIT", "conviction": 2.0,
         "reason_code": "stop_breach", "rationale": "closed under stop"},
        {"ticker": "CDSL", "verdict": "TIGHTEN_STOP", "conviction": 6.5,
         "reason_code": "profit_protect", "rationale": "lock the move", "new_stop": 1420.0},
    ], "carry_forward": "watch HDFCBANK results"}
    view = render_stage("15_holdings_review", raw)
    assert "3 holdings" in view.summary
    assert any(("SBIN" in p or "State Bank" in p) and "EXIT" in p for p in view.points)
    assert any("1420.0" in p for p in view.points)
    assert view.title == "Position Manager"


def test_render_holdings_review_empty():
    from tradeloop.dashboard.render import render_stage
    view = render_stage("15_holdings_review", {"reviews": [], "carry_forward": ""})
    assert "No holdings" in view.summary
