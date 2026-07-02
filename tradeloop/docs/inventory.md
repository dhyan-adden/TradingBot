# Phase 0 Inventory

## TradingAgents Reference

Lift:

- Analyst Team shape: fundamentals, sentiment, news, technical.
- Bull/Bear research debate before trade synthesis.
- Trader synthesis after debate.
- Risk assessment before final portfolio approval.
- Structured output discipline for Research Manager, Trader, and Portfolio
  Manager.
- Persistent decision/memory log idea.

Leave behind:

- LangGraph runtime and server-like orchestration.
- US/global ticker assumptions.
- Any direct LLM API dependency in Python helpers.
- Any agent authority to place trades without file-boundary audit artifacts.

## RakshaQuant Reference

Lift:

- India-market orientation.
- Paper-first execution discipline.
- Risk taxonomy, memory-loop ideas, and practical indicator/scanner shape.

Leave behind:

- Non-Zerodha broker paths.
- Any assumptions that require PostgreSQL, hosted dashboards, or long-running
  services.
- Direct live-order automation without the TradeLoop promotion gate.

## Local Zerodha MCP Shape

The project-local launcher is `./bin/codex-zerodha`. It injects an MCP server
named `zerodha-kite-local`. Relevant tools exposed by `src/mcp/zerodha.ts`:

- `zerodha_profile`
- `zerodha_margins`
- `zerodha_holdings`
- `zerodha_positions`
- `zerodha_orders`
- `zerodha_order_trades`
- `zerodha_quote`
- `zerodha_ltp`
- `zerodha_ohlc`
- `zerodha_place_order`

`zerodha_place_order` accepts `variety`, `exchange`, `tradingsymbol`,
`transaction_type`, `quantity`, `product`, `order_type`, optional `price`,
optional `trigger_price`, optional `validity`, optional `tag`, and `confirm`.
The MCP itself dry-runs unless `ZERODHA_ENABLE_TRADING=true` and `confirm=true`.

