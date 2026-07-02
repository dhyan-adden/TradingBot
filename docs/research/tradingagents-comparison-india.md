# TradingAgents Comparison For Indian Markets

## Current TradingBot

TradingBot is an Indian-market paper harness. It already has:

- YFinance quote polling with Zerodha reserved for live-data validation.
- SQLite append-only event log as machine truth.
- Paper broker for simulated fills, fake cash, positions, and P&L.
- Deterministic risk checks and kill switch.
- Markdown memory projections and a local dashboard.

It does not yet have a full analyst/researcher/trader/portfolio-manager graph.

## TradingAgents Reference

TradingAgents is a richer LangGraph research framework. Its key architecture is:

- Analyst nodes: market, sentiment, news, fundamentals.
- Debate nodes: bull researcher and bear researcher.
- Research manager: converts debate into an investment plan.
- Trader: converts plan into a transaction proposal.
- Risk analysts: aggressive, neutral, conservative.
- Portfolio manager: produces final structured decision.
- Memory log: stores decisions and later reflections.
- Data router: routes stock, indicator, fundamental, and news tools to vendors.

## Differences

| Area | TradingBot Now | TradingAgents | Indian-Market Target |
| --- | --- | --- | --- |
| Market | India-first | Global/general | NSE/BSE equities first |
| Execution | Paper broker exists | Research only | Paper-only until separate live review |
| Data | YFinance + Zerodha skeleton | YFinance/Alpha Vantage routing | YFinance first, Zerodha validation |
| Graph | Single paper workflow | Full LangGraph team | Indian-adapted analyst/debate graph |
| Memory | SQLite truth + markdown projections | Markdown decision log | SQLite truth + decision/reflection markdown |
| Compliance | SEBI/NSE notes | Not India-specific | SEBI/NSE guardrails in config/code |

## What To Port

- Agent state shape for analyst reports, debates, plans, trader proposals, and
  final portfolio decisions.
- Structured output schemas for research plans, trader proposals, and portfolio
  decisions.
- Vendor routing concept, adapted to Indian data sources.
- Reflection loop, but driven by closed paper trades in SQLite.

## What Not To Port

- Direct live execution assumptions.
- US-centric ticker and benchmark defaults.
- Alpha Vantage as a required dependency.
- Any agent permission to place orders, edit config, or read secrets.

## Indian-Market Rules

- Preserve exchange-qualified symbols: `.NS` for NSE and `.BO` for BSE.
- Default benchmark is `^NSEI` for NSE and `^BSESN` for BSE.
- Currency is INR and timezone is Asia/Kolkata.
- First universe is equity-only; F&O can be added later.
- Zerodha is a data-validation path first, not live execution.
