import pytest


@pytest.fixture(autouse=True)
def _no_live_llm(monkeypatch):
    """Unit tests must be deterministic and offline. The real config/agents.yaml
    has the model provider enabled; without these keys ModelRouter falls back to
    deterministic stubs instead of calling OpenRouter live (slow + flaky)."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
