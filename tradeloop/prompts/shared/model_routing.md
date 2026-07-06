# Model Routing

The cycle is split into propose and approve.
Propose: `python -m tradeloop.orchestrator premarket` reasons via a backend and STOPS at a validated `orders.json` (`AWAITING_APPROVAL`).
Approve: a human/overseer (you + a strong model in Claude Code) reviews the orders and evidence, then `python -m tradeloop.orchestrator route <run_dir>` sends them through the risk gate.
The reasoning backend is selected by `--backend` (or the `TRADELOOP_BACKEND` env), default `openrouter`.
Either way the P0 order path is identical: `orders.json` is schema-validated and every order runs through `evaluate()`, so risk control is backend-independent.

## `openrouter` backend (default) - in-process P1 engine

For the propose phase, Python calls OpenRouter directly, one cheap zero-tool model per stage, with full provenance in `llm_calls.jsonl`.
`tradeloop/lib/llm/routing.py` (`STAGE_MODELS`) is the single source of truth; this table mirrors it.
Four models chosen for fitness per stage: minimax = decisions, mimo = analysis/research, flash = cheap high-volume, hy3 = lightest classification.

| Stage | Team | Model |
| --- | --- | --- |
| `05_adhoc_intake` | Ad Hoc Intake | `deepseek/deepseek-v4-flash` |
| `10_news` | News Analyst | `deepseek/deepseek-v4-flash` |
| `11_sentiment` | Sentiment Analyst | `deepseek/deepseek-v4-flash` |
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

`tencent/hy3-preview` was demoted from the DAG on 2026-07-06 after returning empty/truncated content on real payloads; it also has no native structured-output support. All routed models now support structured output directly.
An unknown stage falls back to `DEFAULT_MODEL` (`xiaomi/mimo-v2.5`).
To change a stage's model, edit `STAGE_MODELS` in `routing.py` and update this table to match; the doc test enforces they agree.

## `claude` backend (optional) - Claude Code subagents on your subscription

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
