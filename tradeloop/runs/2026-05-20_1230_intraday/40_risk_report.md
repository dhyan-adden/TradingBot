# Risk Manager

## Portfolio state

- Cash: INR 100,000
- Equity: INR 100,000
- Current positions: none
- Daily P&L: INR 0

## Proposed orders

None. `30_trade_plan.md` emitted no trade ticket.

## Hard checks

| Check | Limit | Result |
| --- | --- | --- |
| Per-trade risk | <= 1.5% equity | Pass, no proposed risk |
| Total open risk | <= 4.0% equity | Pass, no positions |
| Max concurrent positions | 4 | Pass, 0 positions |
| Min position size | INR 15,000 | Not applicable |
| Max single position | 25% equity | Pass, no proposed position |
| Max sector exposure | 40% | Pass, no proposed exposure |
| Position size <= 1% ADV20 | Required for entries | Not applicable, no entry |
| Daily drawdown circuit | -3% | Pass, daily P&L 0 |
| Long-only / no F&O / no leverage | Required | Pass, no order |

## Risk decision

Approve no-action outcome. Risk rejects any fresh exposure because this is an
intraday manage-only cycle and there is no existing position to manage.
