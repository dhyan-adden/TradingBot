from tradeloop.lib.llm import routing

APPROVED = {
    "minimax/minimax-m3", "xiaomi/mimo-v2.5",
    "deepseek/deepseek-v4-flash", "tencent/hy3-preview",
}


def test_every_dag_stage_maps_to_an_approved_model():
    stages = [
        "05_adhoc_intake", "10_news", "11_sentiment", "12_fundamentals",
        "13_technical", "14_shortlist", "20_bull", "21_bear", "22_debate",
        "30_trade_plan", "40_risk_report", "41_pm_decision", "50_post_trade",
    ]
    for s in stages:
        model = routing.model_for(s)
        assert model in APPROVED, f"{s} -> {model!r} is not one of the four approved models"
        # guard against stale anthropic/deepseek-v3.2 slugs leaking back in
        assert "anthropic/" not in model and model != "deepseek/deepseek-v3.2"


def test_decision_stages_use_minimax():
    for s in ("22_debate", "30_trade_plan", "40_risk_report", "41_pm_decision"):
        assert routing.model_for(s) == "minimax/minimax-m3"


def test_classify_stages_use_hy3():
    for s in ("05_adhoc_intake", "11_sentiment"):
        assert routing.model_for(s) == "tencent/hy3-preview"


def test_news_and_technical_use_flash():
    for s in ("10_news", "13_technical"):
        assert routing.model_for(s) == "deepseek/deepseek-v4-flash"


def test_unknown_stage_falls_back_to_default():
    assert routing.model_for("99_unknown") == routing.DEFAULT_MODEL
    assert routing.DEFAULT_MODEL in APPROVED
