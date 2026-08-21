"""Per-stage LLM budgets.

A conservative character proxy for the sub-250K-context constraint on
smaller/free analysis models. Strong decision stages (debate, trade plan,
risk, PM) get larger budgets and are never silently truncated; over-budget
small stages fail loudly instead of sending an oversized prompt.
"""
from __future__ import annotations

from dataclasses import dataclass

from tradeloop.lib.config import Settings


class LLMBudgetError(RuntimeError):
    """Stage prompt exceeded its character budget; fail loudly, never truncate."""


@dataclass(frozen=True)
class StageBudget:
    max_input_chars: int
    max_output_tokens: int
    model_tier: str


def stage_budget(stage: str, settings: Settings) -> StageBudget:
    cfg = getattr(settings, "llm_stage_budgets", None) or {}
    def_in = int(cfg.get("default_max_input_chars", 120000))
    def_out = int(cfg.get("default_max_output_tokens", 2500))
    def_tier = str(cfg.get("default_model_tier", "small_free"))
    stage_cfg = (cfg.get("stages", {}) or {}).get(stage, {}) or {}
    return StageBudget(
        max_input_chars=int(stage_cfg.get("max_input_chars", def_in)),
        max_output_tokens=int(stage_cfg.get("max_output_tokens", def_out)),
        model_tier=str(stage_cfg.get("model_tier", def_tier)),
    )
