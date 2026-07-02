# Risk Manager

Run: `tradeloop/runs/2026-05-21_1230_intraday`
Mode: intraday scheduled cycle

## Risk review

No tickets submitted by `30_trade_plan.md`.

## Hard checks

- Per-trade risk: not applicable.
- Total open risk: 0%, because there are no open positions.
- Concurrent positions: 0 of 4.
- Daily drawdown circuit: not triggered; `00_context.md` reports daily P&L INR 0.0.
- Long-only rule: satisfied because no orders are proposed.
- No F&O, no leverage: satisfied because no orders are proposed.

## Decision

Reject no tickets because none exist. Approve keeping `orders.json` empty.
