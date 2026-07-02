# Risk Report

## Risk Decision

Rejected for new entry now. No order is risk-approved.

## Hard Checks

| Check | Result | Note |
| --- | --- | --- |
| Long-only | pass | No short/F&O/leverage proposal present. |
| Product | pass | Any future trade must be CNC. |
| Per-trade risk <= 1.5% equity | pass for hypothetical, but no approval | Rs 1,500 risk budget on Rs 100,000 equity. Hypothetical 18 shares at 1380/1328 risks Rs 936. |
| Total open risk <= 4% | pass | No current positions. |
| Max concurrent positions <= 4 | pass | No current positions. |
| Min position size Rs 15,000 | pass for hypothetical | 18 shares at 1380 is Rs 24,840. |
| Max single position 25% equity | cap applied | 18 shares is within Rs 25,000 max allocation. |
| Sector exposure <= 40% | pass | No current Energy exposure. |
| Position <= 1% ADV20 | pass for hypothetical | ADV20 is about 20.0 million shares; 18 shares is immaterial. |
| Daily drawdown circuit | pass | Daily P&L in `00_context.md` is 0. |

## Risk Rationale

Risk sizing could make a future confirmed setup small enough, but risk cannot
approve a trade that fails the evidence gate. The current close below the
moving-average cluster makes the stop more likely to be tested before a valid
entry forms.

## Approved Order Adjustments

None. `orders.json` should remain empty.
