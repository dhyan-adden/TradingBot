"""Run one DAG stage in-process: load prompt + named inputs, call the model,
validate the output against the stage schema (retry once on invalid), and write
both the validated .json and a human-readable .md artifact into the run dir.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from tradeloop.lib.llm import routing
from tradeloop.lib.llm.client import LLMValidationError
from tradeloop.lib.llm.schemas import SCHEMA_FOR_STAGE

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
    "13_technical": ["10_news.md", "02_setups_raw.md", "00_context.md"],
    "14_shortlist": ["10_news.md", "11_sentiment.md", "12_fundamentals.md", "13_technical.md"],
    "20_bull": ["14_shortlist.md"],
    "21_bear": ["14_shortlist.md"],
    "22_debate": ["20_bull.md", "21_bear.md"],
    "30_trade_plan": ["22_debate.md", "13_technical.md", "00_context.md"],
    "40_risk_report": ["30_trade_plan.md", "00_context.md"],
    "41_pm_decision": ["40_risk_report.md", "30_trade_plan.md"],
    "50_post_trade": ["fills.json"],
}

# stages whose prompt file lives under a different name/dir
PROMPT_PATH: dict[str, str] = {
    "10_news": "10_news_analyst",
    "11_sentiment": "11_sentiment_analyst",
    "12_fundamentals": "12_fundamentals_analyst",
    "13_technical": "13_technical_analyst",
    "14_shortlist": "14_shortlister",
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


def run_stage(name: str, run_dir: Path, client: SupportsCallJson) -> BaseModel:
    system = _prompt_text(name)  # raises FileNotFoundError first for unknown stages
    schema = SCHEMA_FOR_STAGE[name]
    user = _user_message(name, run_dir)
    model = routing.model_for(name)
    try:
        result = client.call_json(name, system, user, schema, model)
    except LLMValidationError:
        result = client.call_json(name, system, user, schema, model)  # one retry
    (run_dir / f"{name}.json").write_text(
        result.model_dump_json(indent=2), encoding="utf-8")
    (run_dir / f"{name}.md").write_text(
        f"# {name}\n\n```json\n{result.model_dump_json(indent=2)}\n```\n",
        encoding="utf-8")
    return result
