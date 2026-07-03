"""Stage -> OpenRouter model routing for the 13-role DAG.

Tier intent (from prompts/shared/model_routing.md): haiku=classify,
sonnet=analysis, opus=high-stakes decisions. The prior OpenRouter IDs
(minimax/mimo/hy3/deepseek-v4-flash) were placeholders that do not exist on
the provider; these are real current slugs.
"""
from __future__ import annotations

HAIKU = "anthropic/claude-haiku-4.5"     # light classification / sentiment
SONNET = "anthropic/claude-sonnet-4.5"   # analysis / research
OPUS = "anthropic/claude-opus-4.5"       # debate / trade / risk / PM decisions
DEEPSEEK = "deepseek/deepseek-v3.2"       # cheaper analysis tier (news/technical)

DEFAULT_MODEL = SONNET

STAGE_MODELS: dict[str, str] = {
    "05_adhoc_intake": HAIKU,
    "10_news": DEEPSEEK,
    "11_sentiment": HAIKU,
    "12_fundamentals": SONNET,
    "13_technical": DEEPSEEK,
    "14_shortlist": SONNET,
    "20_bull": SONNET,
    "21_bear": SONNET,
    "22_debate": OPUS,
    "30_trade_plan": OPUS,
    "40_risk_report": OPUS,
    "41_pm_decision": OPUS,
    "50_post_trade": SONNET,
}


def model_for(stage: str) -> str:
    return STAGE_MODELS.get(stage, DEFAULT_MODEL)
