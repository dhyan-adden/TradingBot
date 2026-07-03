"""Stage -> OpenRouter model routing for the 13-role DAG.

Four models, chosen for fitness-per-stage (verified 2026-07-04 against
https://openrouter.ai/api/v1/models). Tier intent: minimax = high-stakes
decisions, mimo = analysis/research, flash = cheap high-volume workhorse,
hy3 = lightest classification only.

Note: hy3-preview has NO native structured-output support on OpenRouter, so it
is kept to the two lowest-stakes stages where the client's json_object ->
brace-balanced-extraction fallback carries it. The other three support
response_format directly. To rebalance cost/quality, edit STAGE_MODELS.
"""
from __future__ import annotations

MINIMAX = "minimax/minimax-m3"          # flagship reasoning -> debate/trade/risk/PM
MIMO = "xiaomi/mimo-v2.5"               # analysis / research, structured output
FLASH = "deepseek/deepseek-v4-flash"    # cheap, fast, structured -> news/technical
HY3 = "tencent/hy3-preview"             # lightest classify; no native structured output

DEFAULT_MODEL = MIMO

STAGE_MODELS: dict[str, str] = {
    "05_adhoc_intake": HY3,
    "10_news": FLASH,
    "11_sentiment": HY3,
    "12_fundamentals": MIMO,
    "13_technical": FLASH,
    "14_shortlist": MIMO,
    "20_bull": MIMO,
    "21_bear": MIMO,
    "22_debate": MINIMAX,
    "30_trade_plan": MINIMAX,
    "40_risk_report": MINIMAX,
    "41_pm_decision": MINIMAX,
    "50_post_trade": MIMO,
}


def model_for(stage: str) -> str:
    return STAGE_MODELS.get(stage, DEFAULT_MODEL)
