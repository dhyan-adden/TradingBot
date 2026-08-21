"""Run one DAG stage in-process: load prompt + named inputs, call the model,
validate the output against the stage schema (retry once on invalid), and write
both the validated .json and a human-readable .md artifact into the run dir.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from tradeloop.lib.llm.budget import LLMBudgetError, stage_budget
from tradeloop.lib.llm.client import LLMValidationError
from tradeloop.lib.llm.quality import validate_stage_quality
from tradeloop.lib.llm.schemas import SCHEMA_FOR_STAGE
from tradeloop.lib.data.evidence import canonicalize_evidence_ids
from tradeloop.lib.data.snapshot import load_snapshot

PROMPTS_DIR = Path("tradeloop") / "prompts"

# 13-role DAG order (00_master_orchestrator.md steps 1-8). 05_adhoc_intake runs
# only in adhoc mode and is invoked separately by the orchestrator.
DAG: list[str] = [
    "10_news", "11_sentiment", "12_fundamentals", "13_technical",
    "14_shortlist", "20_bull", "21_bear", "22_debate",
    "30_trade_plan", "40_risk_report", "41_pm_decision",
]

# named input artifacts per stage, from each prompt's Reads: block
STAGE_INPUTS: dict[str, list[str]] = {
    "05_adhoc_intake": ["user_request.md", "00_context.md"],
    "10_news": ["01_news_raw.md", "00_context.md"],
    "11_sentiment": ["10_news.md"],
    "12_fundamentals": ["10_news.md", "00_context.md"],
    "13_technical": ["10_news.md", "02_setups_raw.md", "03_market_regime.md", "00_context.md"],
    "14_shortlist": ["10_news.md", "11_sentiment.md", "12_fundamentals.md", "13_technical.md",
                      "03_market_regime.md"],
    "15_holdings_review": ["00_context.md", "holdings_ltp.json", "03_market_regime.md", "10_news.md",
                            "11_sentiment.md", "12_fundamentals.md", "13_technical.md"],
    "20_bull": ["14_shortlist.md"],
    "21_bear": ["14_shortlist.md"],
    "22_debate": ["20_bull.md", "21_bear.md", "analysis_quality.jsonl"],
    "30_trade_plan": ["22_debate.md", "13_technical.md", "02_setups_raw.md", "03_market_regime.md",
                       "00_context.md", "analysis_quality.jsonl"],
    "40_risk_report": ["30_trade_plan.md", "03_market_regime.md", "00_context.md", "analysis_quality.jsonl"],
    "41_pm_decision": ["40_risk_report.md", "30_trade_plan.md", "03_market_regime.md",
                       "analysis_quality.jsonl"],
    "50_post_trade": ["fills.json"],
}

# stages whose prompt file lives under a different name/dir
PROMPT_PATH: dict[str, str] = {
    "10_news": "10_news_analyst",
    "11_sentiment": "11_sentiment_analyst",
    "12_fundamentals": "12_fundamentals_analyst",
    "13_technical": "13_technical_analyst",
    "14_shortlist": "14_shortlister",
    "15_holdings_review": "15_holdings_reviewer",
    "20_bull": "20_bull_researcher",
    "21_bear": "21_bear_researcher",
    "22_debate": "22_debate_moderator",
    "30_trade_plan": "30_trader",
    "40_risk_report": "40_risk_manager",
    "41_pm_decision": "41_portfolio_manager",
    "50_post_trade": "50_post_trade_analyst",
}


class SupportsCallJson(Protocol):
    def call_json(self, role: str, system: str, user: str,
                  schema: type[BaseModel], model: str | None = None) -> BaseModel: ...


def _prompt_text(name: str) -> str:
    fname = PROMPT_PATH.get(name, name)
    path = PROMPTS_DIR / f"{fname}.md"
    if not path.exists():
        raise FileNotFoundError(path)
    return path.read_text(encoding="utf-8")


def _user_message(name: str, run_dir: Path) -> str:
    parts: list[str] = []
    for fname in STAGE_INPUTS.get(name, []):
        fpath = run_dir / fname
        if fpath.exists():  # degrade-not-crash on missing optional inputs
            parts.append(f"### {fname}\n{fpath.read_text(encoding='utf-8')}")
    return "\n\n".join(parts) if parts else "(no input artifacts present)"


def run_stage(name: str, run_dir: Path, client: SupportsCallJson, settings=None) -> BaseModel:
    system = _prompt_text(name)  # raises FileNotFoundError first for unknown stages
    schema = SCHEMA_FOR_STAGE[name]
    user = _user_message(name, run_dir)
    max_tokens = None
    if settings is not None:
        budget = stage_budget(name, settings)
        estimated_input_chars = len(system) + len(user)
        if estimated_input_chars > budget.max_input_chars:
            raise LLMBudgetError(
                f"{name}: estimated prompt {estimated_input_chars} chars exceeds budget "
                f"{budget.max_input_chars} chars (small-model context guard); reduce stage "
                f"inputs instead of truncating.")
        max_tokens = budget.max_output_tokens
    call_kwargs = {}
    if max_tokens is not None:
        call_kwargs["max_tokens"] = max_tokens
    try:
        result = client.call_json(name, system, user, schema, **call_kwargs)
    except LLMValidationError:
        result = client.call_json(name, system, user, schema, **call_kwargs)  # one retry
    snap = load_snapshot(run_dir)
    if snap is not None:
        repaired, corrections = canonicalize_evidence_ids(result.model_dump(), snap.news_ids)
        if corrections:
            result = schema.model_validate(repaired)
            with (run_dir / "evidence_corrections.jsonl").open("a", encoding="utf-8") as fh:
                for correction in corrections:
                    fh.write(json.dumps({"stage": name, **correction}) + "\n")
    validate_stage_quality(name, result, run_dir)
    (run_dir / f"{name}.json").write_text(
        result.model_dump_json(indent=2), encoding="utf-8")
    (run_dir / f"{name}.md").write_text(
        f"# {name}\n\n```json\n{result.model_dump_json(indent=2)}\n```\n",
        encoding="utf-8")
    return result
