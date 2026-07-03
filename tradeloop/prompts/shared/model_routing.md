# Model Routing

Reasoning runs through one of two backends, selected by `--backend` (or the `TRADELOOP_BACKEND` env), default `claude`.
Either way the P0 order path is identical: `orders.json` is schema-validated and every order runs through `evaluate()`, so risk control is backend-independent.

## `claude` backend (default) - Claude Code subagents on your subscription

An Opus master orchestrator (`00_master_orchestrator.md`, launched by `scripts/run_cycle.sh` claude path) dispatches each team as a Claude Code subagent via the Task tool.
No OpenRouter and no metered API - it uses your Claude subscription, and Opus is in the loop as both the master and the decision-stage model.
Tiers live in the subagent definitions under `.claude/agents/`: Haiku for classification, Sonnet for analysis/research, Opus for high-stakes decisions.
To guarantee Opus oversight of the master session, run Claude Code with Opus as the default model or set `TRADELOOP_CLAUDE_MODEL`.

| Stage | subagent_type | Claude tier |
| --- | --- | --- |
| Ad Hoc Intake | `tradeloop-adhoc-intake` | haiku |
| News Analyst | `tradeloop-news` | sonnet |
| Sentiment Analyst | `tradeloop-sentiment` | haiku |
| Fundamentals Analyst | `tradeloop-fundamentals` | sonnet |
| Technical Analyst | `tradeloop-technical` | sonnet |
| Shortlister | `tradeloop-shortlister` | sonnet |
| Bull Researcher | `tradeloop-bull` | sonnet |
| Bear Researcher | `tradeloop-bear` | sonnet |
| Debate Moderator | `tradeloop-debate` | opus |
| Trader | `tradeloop-trader` | opus |
| Risk Manager | `tradeloop-risk` | opus |
| Portfolio Manager | `tradeloop-pm` | opus |
| Post Trade Analyst | `tradeloop-post-trade` | sonnet |

## `openrouter` backend (optional) - in-process P1 engine

For headless or autonomous runs outside a Claude Code session, Python calls OpenRouter directly, one model per stage.
`tradeloop/lib/llm/routing.py` (`STAGE_MODELS`) is the single source of truth; this table mirrors it.
Four models chosen for fitness per stage: minimax = decisions, mimo = analysis/research, flash = cheap high-volume, hy3 = lightest classification.

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

`tencent/hy3-preview` has no native structured-output support, so it is confined to the two lowest-stakes stages where the client's json_object -> brace-balanced-extraction fallback carries it; the other three support structured output directly.
An unknown stage falls back to `DEFAULT_MODEL` (`xiaomi/mimo-v2.5`).
To change a stage's model, edit `STAGE_MODELS` in `routing.py` and update this table to match; the doc test enforces they agree.
