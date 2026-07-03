from tradeloop.lib.llm import routing


def test_every_dag_stage_has_a_real_model():
    stages = [
        "05_adhoc_intake", "10_news", "11_sentiment", "12_fundamentals",
        "13_technical", "14_shortlist", "20_bull", "21_bear", "22_debate",
        "30_trade_plan", "40_risk_report", "41_pm_decision", "50_post_trade",
    ]
    for s in stages:
        model = routing.model_for(s)
        assert "/" in model, f"{s} -> {model!r} is not an org/model slug"
        assert "minimax" not in model and "mimo" not in model and "hy3" not in model, \
            f"{s} still points at a fake placeholder model {model!r}"


def test_decision_stages_use_opus():
    for s in ("22_debate", "30_trade_plan", "40_risk_report", "41_pm_decision"):
        assert routing.model_for(s) == "anthropic/claude-opus-4.5"


def test_classify_stages_use_haiku():
    for s in ("05_adhoc_intake", "11_sentiment"):
        assert routing.model_for(s) == "anthropic/claude-haiku-4.5"


def test_unknown_stage_falls_back_to_default():
    assert routing.model_for("99_unknown") == routing.DEFAULT_MODEL
