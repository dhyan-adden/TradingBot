from tradeloop.lib.llm import routing

APPROVED = {
    "minimax/minimax-m3", "xiaomi/mimo-v2.5",
    "deepseek/deepseek-v4-flash-0731", "tencent/hy3-preview",
}

OPENCODE_APPROVED = {
    "opencode/nemotron-3-ultra-free",
    "opencode/big-pickle",
    "openrouter/deepseek/deepseek-v4-flash-0731",
    "openrouter/xiaomi/mimo-v2.5",
    "openai/gpt-5.6-luna",
    "openai/gpt-5.5",
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


def test_classify_stages_use_flash():
    # hy3-preview demoted 2026-07-06: empty/truncated content on real payloads
    for s in ("05_adhoc_intake", "11_sentiment"):
        assert routing.model_for(s) == "deepseek/deepseek-v4-flash-0731"


def test_news_and_technical_use_flash():
    for s in ("10_news", "13_technical"):
        assert routing.model_for(s) == "deepseek/deepseek-v4-flash-0731"


def test_unknown_stage_falls_back_to_default():
    assert routing.model_for("99_unknown") == routing.DEFAULT_MODEL
    assert routing.DEFAULT_MODEL in APPROVED


def test_claude_model_for_matches_tiering():
    assert routing.claude_model_for("11_sentiment") == "haiku"
    assert routing.claude_model_for("05_adhoc_intake") == "haiku"
    assert routing.claude_model_for("10_news") == "sonnet"
    assert routing.claude_model_for("50_post_trade") == "sonnet"
    assert routing.claude_model_for("22_debate") == "opus"
    assert routing.claude_model_for("30_trade_plan") == "opus"
    assert routing.claude_model_for("40_risk_report") == "opus"
    assert routing.claude_model_for("41_pm_decision") == "opus"


def test_claude_model_for_defaults_to_sonnet_for_unknown_stage():
    assert routing.claude_model_for("99_unknown") == "sonnet"


def test_every_openrouter_stage_has_a_claude_tier():
    for stage in routing.STAGE_MODELS:
        assert stage in routing.CLAUDE_STAGE_MODELS, f"{stage} missing a claude tier"


def test_opencode_routing_uses_openai_for_senior_stages():
    assert routing.opencode_model_for("15_holdings_review") == "openai/gpt-5.5"
    assert routing.opencode_model_for("22_debate") == "openai/gpt-5.6-luna"
    assert routing.opencode_model_for("30_trade_plan") == "openai/gpt-5.6-luna"
    assert routing.opencode_model_for("40_risk_report") == "openai/gpt-5.6-luna"
    assert routing.opencode_model_for("41_pm_decision") == "openai/gpt-5.5"


def test_opencode_low_stages_use_free_zen_models_first():
    for s in ("05_adhoc_intake", "10_news", "11_sentiment", "13_technical"):
        assert routing.opencode_model_for(s) == "opencode/nemotron-3-ultra-free"
    assert routing.opencode_fallbacks_for("10_news") == ("openrouter/deepseek/deepseek-v4-flash-0731",)


def test_opencode_analysis_stages_use_free_reasoning_then_paid():
    for s in ("12_fundamentals", "14_shortlist", "20_bull", "21_bear", "50_post_trade"):
        assert routing.opencode_model_for(s) == "opencode/big-pickle"
    assert routing.opencode_fallbacks_for("14_shortlist") == ("openrouter/xiaomi/mimo-v2.5",)


def test_opencode_high_stakes_fall_back_to_bedrock_reasoning():
    assert routing.opencode_fallbacks_for("41_pm_decision") == (
        "amazon-bedrock/zai.glm-5",
        "amazon-bedrock/moonshotai.kimi-k2.5",
    )
    assert routing.opencode_fallbacks_for("22_debate") == (
        "amazon-bedrock/zai.glm-5",
        "amazon-bedrock/moonshotai.kimi-k2.5",
    )


def test_opencode_postclose_uses_free_and_openai_in_unison():
    postclose_dag = ["10_news", "11_sentiment", "12_fundamentals", "13_technical", "15_holdings_review"]
    models = {routing.opencode_model_for(stage) for stage in postclose_dag}

    assert any(model.startswith("opencode/") for model in models)
    assert any(model.startswith("openai/") for model in models)


def test_every_opencode_stage_maps_to_an_approved_model():
    for stage, model in routing.OPENCODE_STAGE_MODELS.items():
        assert model in OPENCODE_APPROVED, f"{stage} -> {model!r} is not approved"
