# Risk Report

## Decision

Approve no action.

## Inputs

- Equity INR: 100000.0
- Daily P&L INR: 0.0
- Current positions from `00_context.md`: none
- Proposed orders from `30_trade_plan.md`: none

## Hard Checks

| Check | Limit | Result |
| --- | --- | --- |
| Per-trade risk | <= 1.5% equity | Pass, no trade proposed |
| Total open risk | <= 4.0% equity | Pass, no positions |
| Max concurrent positions | 4 | Pass, 0 positions |
| Min position size | INR 15000 | Not applicable |
| Max single position | 25% equity | Pass, no positions |
| Max sector exposure | 40% | Pass, no positions |
| Daily drawdown circuit | -3% | Pass, daily P&L is 0.0 |
| Long-only / no F&O / no leverage | Required | Pass, no order proposed |

## Risk Action

No resize, reject, or protective order is required.
