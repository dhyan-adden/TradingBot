"""Stage -> OpenRouter model routing for the 13-role DAG.

Four models, chosen for fitness-per-stage (verified 2026-07-04 against
https://openrouter.ai/api/v1/models). Tier intent: minimax = high-stakes
decisions, mimo = analysis/research, flash = cheap high-volume workhorse,
hy3 = lightest classification only.

Note: hy3-preview was demoted from the DAG 2026-07-06 after returning empty or
truncated content on real premarket payloads (6/6 stage attempts failed, then
1/3 near-empty on direct probes); its two stages moved to flash. It also has NO
native structured-output support on OpenRouter, so restore it only behind the
client's json_object -> brace-balanced-extraction fallback and only to the
lowest-stakes stages. To rebalance cost/quality, edit STAGE_MODELS.
"""
from __future__ import annotations

MINIMAX = "minimax/minimax-m3"               # flagship reasoning -> debate/trade/risk/PM
MIMO = "xiaomi/mimo-v2.5"                    # analysis / research, structured output
FLASH = "deepseek/deepseek-v4-flash-0731"    # cheap, fast, structured -> news/technical
HY3 = "tencent/hy3-preview"                  # unreliable (see note); not currently routed

DEFAULT_MODEL = MIMO

STAGE_MODELS: dict[str, str] = {
    "05_adhoc_intake": FLASH,
    "10_news": FLASH,
    "11_sentiment": FLASH,
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


OPENCODE_FLASH = "openrouter/deepseek/deepseek-v4-flash-0731"
OPENCODE_MIMO = "openrouter/xiaomi/mimo-v2.5"
OPENCODE_LUNA = "openai/gpt-5.6-luna"
OPENCODE_STRONG = "openai/gpt-5.5"
# Free OpenCode Zen models (verified live 2026-08-21). Low/medium-stakes stages
# try these first; paid models are the fallback.
ZEN_NEMOTRON_ULTRA_FREE = "opencode/nemotron-3-ultra-free"
ZEN_BIG_PICKLE = "opencode/big-pickle"
# Amazon Bedrock reasoning models: fallbacks for high-stakes OpenAI stages.
# openrouter/nvidia/nemotron-3-ultra-550b-a55b:free was removed 2026-08-21 -
# OpenRouter privacy/guardrail settings block it (404 no-endpoints).
BEDROCK_KIMI = "amazon-bedrock/moonshotai.kimi-k2.5"
BEDROCK_GLM = "amazon-bedrock/zai.glm-5"

# Routing philosophy (2026-08-21):
#   low stakes (classify/extract): free-but-good Zen model first, paid cheap fallback
#   analysis: free reasoning first, reliable paid structured-output fallback
#   high stakes (decisions): OpenAI subscription first, Bedrock reasoning fallbacks
OPENCODE_STAGE_MODELS: dict[str, str] = {
    "05_adhoc_intake": ZEN_NEMOTRON_ULTRA_FREE,
    "10_news": ZEN_NEMOTRON_ULTRA_FREE,
    "11_sentiment": ZEN_NEMOTRON_ULTRA_FREE,
    "12_fundamentals": ZEN_BIG_PICKLE,
    "13_technical": ZEN_NEMOTRON_ULTRA_FREE,
    "15_holdings_review": OPENCODE_STRONG,
    "14_shortlist": ZEN_BIG_PICKLE,
    "20_bull": ZEN_BIG_PICKLE,
    "21_bear": ZEN_BIG_PICKLE,
    "22_debate": OPENCODE_LUNA,
    "30_trade_plan": OPENCODE_LUNA,
    "40_risk_report": OPENCODE_LUNA,
    "41_pm_decision": OPENCODE_STRONG,
    "50_post_trade": ZEN_BIG_PICKLE,
}

_LOW_STAKES_FALLBACKS = (OPENCODE_FLASH,)
_ANALYSIS_FALLBACKS = (OPENCODE_MIMO,)
_HIGH_STAKES_FALLBACKS = (BEDROCK_GLM, BEDROCK_KIMI)

OPENCODE_STAGE_FALLBACKS: dict[str, tuple[str, ...]] = {
    "05_adhoc_intake": _LOW_STAKES_FALLBACKS,
    "10_news": _LOW_STAKES_FALLBACKS,
    "11_sentiment": _LOW_STAKES_FALLBACKS,
    "13_technical": _LOW_STAKES_FALLBACKS,
    "12_fundamentals": _ANALYSIS_FALLBACKS,
    "14_shortlist": _ANALYSIS_FALLBACKS,
    "20_bull": _ANALYSIS_FALLBACKS,
    "21_bear": _ANALYSIS_FALLBACKS,
    "50_post_trade": _ANALYSIS_FALLBACKS,
    "15_holdings_review": _HIGH_STAKES_FALLBACKS,
    "22_debate": _HIGH_STAKES_FALLBACKS,
    "30_trade_plan": _HIGH_STAKES_FALLBACKS,
    "40_risk_report": _HIGH_STAKES_FALLBACKS,
    "41_pm_decision": _HIGH_STAKES_FALLBACKS,
}


def opencode_model_for(stage: str) -> str:
    return OPENCODE_STAGE_MODELS.get(stage, ZEN_BIG_PICKLE)


def opencode_fallbacks_for(stage: str) -> tuple[str, ...]:
    return OPENCODE_STAGE_FALLBACKS.get(stage, _ANALYSIS_FALLBACKS + _HIGH_STAKES_FALLBACKS)


# Claude-subscription tiers per stage (used by ClaudeStageClient). haiku =
# lightest classification, sonnet = research/analysis, opus = high-stakes
# decisions. Mirrors the intent of STAGE_MODELS but with native Claude models.
CLAUDE_STAGE_MODELS: dict[str, str] = {
    "05_adhoc_intake": "haiku",
    "10_news": "sonnet",
    "11_sentiment": "haiku",
    "12_fundamentals": "sonnet",
    "13_technical": "sonnet",
    "14_shortlist": "sonnet",
    "20_bull": "sonnet",
    "21_bear": "sonnet",
    "22_debate": "opus",
    "30_trade_plan": "opus",
    "40_risk_report": "opus",
    "41_pm_decision": "opus",
    "50_post_trade": "sonnet",
}

CLAUDE_DEFAULT_MODEL = "sonnet"


def claude_model_for(stage: str) -> str:
    return CLAUDE_STAGE_MODELS.get(stage, CLAUDE_DEFAULT_MODEL)
