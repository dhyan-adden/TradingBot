# 40 Risk Report

## Risk Decision
Rejected because there is no approved trade ticket from `30_trade_plan.md`.

## Hard Checks
- Per-trade risk <= 1.5% equity: not applicable; no ticket.
- Total open risk <= 4%: current open risk is 0 because there are no positions.
- Max concurrent positions <= 4: current positions are none.
- Min position size INR 15,000: not applicable; no ticket.
- Max single position 25%: not applicable; no ticket.
- Max sector exposure 40%: not applicable; no ticket.
- Position size <= 1% ADV20: liquidity would not be a blocker for a small paper order, but no order is approved.
- Daily drawdown circuit -3%: current context shows daily P&L INR 0, so no circuit trigger.
- Long-only/no F&O/no leverage: satisfied by process; no SELL/short/F&O/NRML proposal exists.

## Reasoning
Risk should not resize a low-quality setup into existence. The debate verdict is pass and the trader produced no ticket. The safest risk action is to reject execution and preserve cash.
