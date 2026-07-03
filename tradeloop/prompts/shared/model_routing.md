# Model Routing

Phase 1: the Python reasoning layer calls OpenRouter directly, one model per stage.
`tradeloop/lib/llm/routing.py` (`STAGE_MODELS`) is the single source of truth; this table mirrors it.
Four models chosen for fitness per stage: minimax = high-stakes decisions, mimo = analysis/research, flash = cheap high-volume workhorse, hy3 = lightest classification.

| Stage | Team | Model |
| --- | --- | --- |
| `05_adhoc_intake` | Ad Hoc Intake | `tencent/hy3-preview` |
| `10_news` | News Analyst | `deepseek/deepseek-v4-flash` |
| `11_sentiment` | Sentiment Analyst | `tencent/hy3-preview` |
| `12_fundamentals` | Fundamentals Analyst | `xiaomi/mimo-v2.5` |
| `13_technical` | Technical Analyst | `deepseek/deepseek-v4-flash` |
| `14_shortlist` | Shortlister | `xiaomi/mimo-v2.5` |
| `20_bull` | Bull Researcher | `xiaomi/mimo-v2.5` |
| `21_bear` | Bear Researcher | `xiaomi/mimo-v2.5` |
| `22_debate` | Debate Moderator | `minimax/minimax-m3` |
| `30_trade_plan` | Trader | `minimax/minimax-m3` |
| `40_risk_report` | Risk Manager | `minimax/minimax-m3` |
| `41_pm_decision` | Portfolio Manager | `minimax/minimax-m3` |
| `50_post_trade` | Post Trade Analyst | `xiaomi/mimo-v2.5` |

Rough OpenRouter cost (output $/M tokens, 2026-07-04): minimax-m3 $1.20, mimo-v2.5 $0.28, deepseek-v4-flash $0.18, hy3-preview $0.21.
All four expose a 1M-token context except hy3-preview (256K), which is fine for the light classify stages it serves.

Structured output uses `response_format: {type: json_object}`; brace-balanced JSON extraction is the universal fallback for providers that do not honor it.
`tencent/hy3-preview` has no native structured-output support, so it is confined to `05_adhoc_intake` and `11_sentiment` (the lowest-stakes, simplest-schema stages) where the extraction fallback carries it; the other three models support structured output directly.
An unknown stage falls back to `DEFAULT_MODEL` (`xiaomi/mimo-v2.5`).
To change a stage's model, edit `STAGE_MODELS` in `routing.py` and update this table to match; the doc test enforces they agree.

## Legacy

The pre-P1 external backend selected reasoning via `TRADELOOP_AGENT=codex|claude` in `scripts/run_cycle.sh` (Codex through OpenRouter, or Claude Code subagents).
Phase 1 replaced that with the in-process reasoning layer above.
`scripts/run_cycle.sh` and the `.claude/agents/tradeloop-*` subagent definitions remain on disk for reference only and are no longer on the orchestrator's path.
