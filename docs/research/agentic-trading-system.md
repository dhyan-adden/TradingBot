# Agentic Trading System

## Goal

Build a closed-loop paper trading harness for Indian equity CNC swing trading.
The system should use real Zerodha market data while simulating every order,
fill, cash movement, holding, and P&L locally.

The first experiment is not about alpha quality. It is about whether the system
can keep decision state, trade outcomes, lessons, and markdown memory in sync
under realistic market-data flow.

## V1 Boundary

- Market: Indian listed equities.
- Strategy style: CNC swing trading on daily candles.
- Broker data: Zerodha Kite Connect.
- Execution: paper only.
- Capital: fake INR balance from config.
- Learning: durable trade memory plus advisory config proposals.
- Live trading: disabled until a separate review and compliance pass.

## System Loop

1. Fetch daily candles and live LTP for the configured universe.
2. Generate deterministic strategy signals.
3. Run pure risk checks.
4. Send approved signals to the paper broker.
5. Append every state transition to SQLite.
6. Reconcile positions and mark open trades to market.
7. Generate markdown projections for trades, daily reports, scorecards, lessons,
   and proposals.
8. Review markdown manually and refine schemas/templates.

## Closed Loop V1

The implemented v1 loop is continuous and paper-only:

1. `loop.started` and `loop.heartbeat` events mark runtime state.
2. YFinance quotes are written as `data.quote_received`.
3. `daily_breakout_v1` emits `signal.generated`.
4. Deterministic risk emits `risk.approved` or `risk.rejected`.
5. Approved paper entries route to the paper broker.
6. Open positions are marked to market each cycle.
7. Closed paper trades write rule-first learning metrics, lessons, and pending
   advisory proposals.
8. Daily and scorecard markdown projections are regenerated.

Agents and Codex review remain advisory. No live broker order path is connected
to this loop.

## Agent-Led Closed Loop

The agent-led loop runs before paper execution:

1. `research.news_fetched` records online headlines and URLs.
2. `research.trend_summary_written` stores a trend summary and sentiment.
3. `agent.report_written` stores market and news context.
4. `agent.trader_proposal_written` stores the trader proposal.
5. `agent.portfolio_decision_written` stores the portfolio manager decision.
6. A deterministic signal may trigger only if the portfolio manager allows it.
7. Risk remains the final deterministic gate before any paper order.

If the agent layer blocks a trade, the loop writes `agent.vetoed`.

## Agent Roles

- `market_analyst`: prepares technical market notes from quotes, candles, and indicators.
- `news_analyst`: summarizes India-specific company, sector, market, and macro news.
- `fundamentals_analyst`: summarizes company fundamentals when available.
- `sentiment_analyst`: optional layer for social/sentiment sources; disabled by default.
- `bull_researcher`: argues the strongest case for taking or increasing exposure.
- `bear_researcher`: argues the strongest case against exposure.
- `research_manager`: converts analyst reports and debate into a structured plan.
- `trader_agent`: turns the plan into a concrete paper transaction proposal.
- `signal_agent`: produces candidate trades and rationale.
- `risk_agent`: vetoes candidates that violate config limits.
- `portfolio_manager`: produces the final structured paper decision after risk context.
- `execution_agent`: routes to paper broker only in v1.
- `trade_journal_agent`: records lifecycle events and config hashes.
- `post_trade_learning_agent`: writes lesson/proposal markdown after closed
  trades.
- `supervisor_agent`: final gate before any simulated order is accepted.

Agents must not directly mutate the event log unless their role explicitly owns
the event. The event log remains machine truth; markdown remains projection.

## Indian Market Adaptation

- Symbols preserve Indian exchange suffixes: `.NS` for NSE and `.BO` for BSE.
- Currency is INR and the canonical trading timezone is Asia/Kolkata.
- Benchmarks default to `^NSEI` for NSE and `^BSESN` for BSE.
- Zerodha is the broker/data validation path; live execution stays disabled.
- YFinance is acceptable for early paper harness testing.

## Current TradingAgents-Style Graph Scaffold

The first graph implementation is intentionally conservative:

1. `Market Analyst` writes a placeholder technical report.
2. `Research Manager` returns a structured `Hold` research plan.
3. `Trader` returns a structured `Hold` proposal.
4. `Portfolio Manager` returns a structured `Hold` final decision.

This proves the LangGraph state and structured output contracts without giving
any agent order authority. Real analyst tooling can replace one node at a time.

## Day 1 Deliverable

Day 1 establishes:

- Research docs and config files.
- SQLite append-only event log.
- Config validation.
- Zerodha data adapter skeleton for instruments, daily candles, and LTP.
- Data quality gates.
- CLI smoke commands for config and event-log checks.

Sources:

- SEBI retail algo circular: https://www.sebi.gov.in/legal/circulars/feb-2025/safer-participation-of-retail-investors-in-algorithmic-trading_91614.html
- NSE implementation standards: https://nsearchives.nseindia.com/content/circulars/INVG67858.pdf
- Zerodha Kite Connect docs: https://kite.trade/docs/connect/v3/
