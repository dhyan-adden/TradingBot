from tradingbot.event_log import EventLog
from tradingbot.llm import ModelRouter


def test_model_router_skips_when_provider_disabled(tmp_path) -> None:
    event_log = EventLog(tmp_path / "trading.db")
    router = ModelRouter(
        {
            "model_provider": {"enabled": False, "default_model": "test-model"},
            "agents": {"trader_agent": {"model": "test-trader"}},
        },
        event_log,
    )

    result = router.call_json("trader_agent", "{}", {"action": "Hold"})

    assert result.used_model is False
    assert result.model == "test-trader"
    assert result.content == {"action": "Hold"}
    assert event_log.latest("model.skipped").payload["reason"] == "model_provider_disabled"


def test_model_router_skips_without_api_key(tmp_path, monkeypatch) -> None:
    event_log = EventLog(tmp_path / "trading.db")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    router = ModelRouter(
        {
            "model_provider": {"enabled": True, "default_model": "test-model", "api_key_env": "OPENAI_API_KEY"},
            "agents": {"news_analyst": {"model": "test-news"}},
        },
        event_log,
    )

    result = router.call_json("news_analyst", "{}", {"summary": "fallback"})

    assert result.used_model is False
    assert result.model == "test-news"
    assert result.content == {"summary": "fallback"}
    assert event_log.latest("model.skipped").payload["reason"] == "api_key_missing"
