"""Phase 4: per-stage LLM budget guardrails.

Small/free analysis stages are protected from oversized prompts; strong
decision stages get larger budgets; over-budget never truncates - it fails
loudly. All tests use a fake client; no real model calls.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from tradeloop.lib.config import load_settings
from tradeloop.lib.llm.budget import LLMBudgetError, StageBudget, stage_budget
from tradeloop.lib.llm.schemas import NewsAnalysis, SCHEMA_FOR_STAGE
from tradeloop.lib.llm.stages import run_stage

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = load_settings(ROOT / "config" / "settings.yaml")


class _NeverCalledClient:
    """Fails the test if the stage ever reaches the model call."""

    def call_json(self, role, system, user, schema, model=None, max_tokens=None):
        raise AssertionError("client.call_json must not be reached on over-budget stage")


class _RecordingClient:
    """Returns a valid schema object and records the max_tokens passed."""

    def __init__(self) -> None:
        self.last_max_tokens = None

    def call_json(self, role, system, user, schema, model=None, max_tokens=None):
        self.last_max_tokens = max_tokens
        return schema()


def test_explicit_small_stage_budget_loaded():
    b = stage_budget("10_news", SETTINGS)
    assert b == StageBudget(max_input_chars=80000, max_output_tokens=2000,
                            model_tier="small_free")


def test_pm_stage_allowed_larger_budget():
    b = stage_budget("41_pm_decision", SETTINGS)
    assert b.max_input_chars == 160000
    assert b.max_output_tokens == 4000
    assert b.model_tier == "strong_paid"


def test_unlisted_stage_falls_back_to_defaults():
    b = stage_budget("13_technical", SETTINGS)
    assert b.max_input_chars == 120000
    assert b.max_output_tokens == 2500
    assert b.model_tier == "small_free"


def test_over_budget_small_stage_raises_no_truncation(monkeypatch):
    monkeypatch.setattr(
        "tradeloop.lib.llm.stages._prompt_text",
        lambda name: "system",  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        "tradeloop.lib.llm.stages._user_message",
        lambda name, run_dir: "x" * 100000,
    )
    # tiny default budget so any non-trivial prompt is over budget
    tiny = replace(SETTINGS, llm_stage_budgets={
        "default_max_input_chars": 100,
        "default_max_output_tokens": 2500,
        "default_model_tier": "small_free", "stages": {}})
    import pytest

    with pytest.raises(LLMBudgetError):
        run_stage("10_news", Path("/tmp"), _NeverCalledClient(), settings=tiny)


def test_within_budget_passes_max_tokens_to_client(monkeypatch):
    monkeypatch.setattr(
        "tradeloop.lib.llm.stages._prompt_text",
        lambda name: "system",  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        "tradeloop.lib.llm.stages._user_message",
        lambda name, run_dir: "x",
    )
    big = replace(SETTINGS, llm_stage_budgets={
        "default_max_input_chars": 1000000,
        "default_max_output_tokens": 2500,
        "default_model_tier": "small_free", "stages": {}})
    client = _RecordingClient()
    result = run_stage("10_news", Path("/tmp"), client, settings=big)
    assert isinstance(result, NewsAnalysis)
    assert client.last_max_tokens == 2500


def test_run_stage_without_settings_keeps_backward_compat(monkeypatch):
    # Callers that pass no settings must not send max_tokens (claude_client / fakes).
    monkeypatch.setattr(
        "tradeloop.lib.llm.stages._prompt_text",
        lambda name: "system",  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        "tradeloop.lib.llm.stages._user_message",
        lambda name, run_dir: "x",
    )
    client = _RecordingClient()
    result = run_stage("10_news", Path("/tmp"), client)
    assert isinstance(result, SCHEMA_FOR_STAGE["10_news"])
    assert client.last_max_tokens is None
