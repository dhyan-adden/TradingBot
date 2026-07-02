# Model Routing

Routing depends on `TRADELOOP_AGENT`:

- **Codex** (`TRADELOOP_AGENT=codex`): reasoning runs through OpenRouter using
  ONLY the four models below. Master runs on `minimax/minimax-m3` (set via
  `TRADELOOP_MODEL` in `scripts/run_cycle.sh`); delegated stages use the model
  assigned in the table. This is the only path that uses OpenRouter.
- **Claude Code** (`TRADELOOP_AGENT=claude`): native Claude models via your
  Claude Code auth — **no OpenRouter, no bridge**. The master session dispatches
  each team below as a Claude Code subagent (Task tool); the OpenRouter column
  does not apply. Assign Claude model tiers per stage if you create named
  subagents (e.g. Haiku for classification, Opus for trader/risk/PM).

## Codex — OpenRouter model assignments

Tiers: decisions → `minimax/minimax-m3`; analysts → `deepseek/deepseek-v4-flash`;
fundamentals/research → `xiaomi/mimo-v2.5`; light classification →
`tencent/hy3-preview`.

| Stage | Team | Model |
| --- | --- | --- |
| `00_master_orchestrator.md` | Master Orchestrator | `minimax/minimax-m3` |
| `05_adhoc_intake.md` | Ad Hoc Intake | `tencent/hy3-preview` |
| `10_news.md` | News Analyst | `deepseek/deepseek-v4-flash` |
| `11_sentiment.md` | Sentiment Analyst | `tencent/hy3-preview` |
| `12_fundamentals.md` | Fundamentals Analyst | `xiaomi/mimo-v2.5` |
| `13_technical.md` | Technical Analyst | `deepseek/deepseek-v4-flash` |
| `14_shortlist.md` | Shortlister | `deepseek/deepseek-v4-flash` |
| `20_bull.md` | Bull Researcher | `xiaomi/mimo-v2.5` |
| `21_bear.md` | Bear Researcher | `xiaomi/mimo-v2.5` |
| `22_debate.md` | Debate Moderator | `minimax/minimax-m3` |
| `30_trade_plan.md` | Trader | `minimax/minimax-m3` |
| `40_risk_report.md` | Risk Manager | `minimax/minimax-m3` |
| `41_pm_decision.md` | Portfolio Manager | `minimax/minimax-m3` |
| `50_post_trade.md` | Post Trade Analyst | `xiaomi/mimo-v2.5` |

## Claude Code — named subagents (Task tool)

Each stage is a project subagent in `.claude/agents/`, tiered by role:
Haiku for classification, Sonnet for analysis/research, Opus for high-stakes
decisions. The master orchestrator (Opus) dispatches each by `subagent_type`.

| Stage | subagent_type | Claude model |
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

Routing rules:

- All four models are reasoning models on OpenRouter's `chat` wire API; do not
  send OpenAI-only `reasoning_effort` parameters.
- Use the assigned model whenever a team is run as a separate Codex invocation
  or delegated agent.
- If a team is executed inline by the master orchestrator, preserve the same
  evidence standard and output contract implied by the assigned model.
- Use a model outside this set for no stage. Prefer `tencent/hy3-preview` only
  for classification or sentiment stages where no order can be approved directly.
