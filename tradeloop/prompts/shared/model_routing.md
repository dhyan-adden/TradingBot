# Model Routing

Phase 1: the Python reasoning layer calls OpenRouter directly, one model per stage.
`tradeloop/lib/llm/routing.py` (`STAGE_MODELS`) is the single source of truth; this table mirrors it.
Tier intent: haiku = light classification, sonnet = analysis/research, opus = high-stakes decisions, deepseek = cheaper analysis tier.

| Stage | Team | Model |
| --- | --- | --- |
| `05_adhoc_intake` | Ad Hoc Intake | `anthropic/claude-haiku-4.5` |
| `10_news` | News Analyst | `deepseek/deepseek-v3.2` |
| `11_sentiment` | Sentiment Analyst | `anthropic/claude-haiku-4.5` |
| `12_fundamentals` | Fundamentals Analyst | `anthropic/claude-sonnet-4.5` |
| `13_technical` | Technical Analyst | `deepseek/deepseek-v3.2` |
| `14_shortlist` | Shortlister | `anthropic/claude-sonnet-4.5` |
| `20_bull` | Bull Researcher | `anthropic/claude-sonnet-4.5` |
| `21_bear` | Bear Researcher | `anthropic/claude-sonnet-4.5` |
| `22_debate` | Debate Moderator | `anthropic/claude-opus-4.5` |
| `30_trade_plan` | Trader | `anthropic/claude-opus-4.5` |
| `40_risk_report` | Risk Manager | `anthropic/claude-opus-4.5` |
| `41_pm_decision` | Portfolio Manager | `anthropic/claude-opus-4.5` |
| `50_post_trade` | Post Trade Analyst | `anthropic/claude-sonnet-4.5` |

Structured output uses `response_format: {type: json_schema}`; brace-balanced JSON extraction is the universal fallback for providers that do not honor it.
An unknown stage falls back to `DEFAULT_MODEL` (`anthropic/claude-sonnet-4.5`).
To change a stage's model, edit `STAGE_MODELS` in `routing.py` and update this table to match; the doc test enforces they agree.

Newer tiers exist on OpenRouter (`anthropic/claude-opus-4.8`, `anthropic/claude-sonnet-5`, `deepseek/deepseek-v4-pro`) if a quality upgrade is wanted; the 4.5 tier above is the reviewed default.

## Legacy

The pre-P1 external backend selected reasoning via `TRADELOOP_AGENT=codex|claude` in `scripts/run_cycle.sh` (Codex through OpenRouter, or Claude Code subagents).
Phase 1 replaced that with the in-process reasoning layer above.
`scripts/run_cycle.sh` and the `.claude/agents/tradeloop-*` subagent definitions remain on disk for reference only and are no longer on the orchestrator's path.
