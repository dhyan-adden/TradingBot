# Output Schemas

## Ad Hoc Intake

```markdown
## Classification
full_trade_request

## Safe Interpretation
Evaluate RELIANCE for a long-only CNC swing setup.

## Required Stages
- 10_news.md
- 11_sentiment.md
- 12_fundamentals.md
- 13_technical.md
- 14_shortlist.md
- 20_bull.md
- 21_bear.md
- 22_debate.md
- 30_trade_plan.md
- 40_risk_report.md
- 41_pm_decision.md

## Refused Or Ignored Parts
None.
```

## Trade Ticket

```json
{
  "ticker": "RELIANCE",
  "side": "BUY",
  "product": "CNC",
  "strategy_family": "breakout_20d_pullback",
  "entry": 2500.0,
  "hard_stop": 2425.0,
  "target_1": 2625.0,
  "target_2": 2750.0,
  "quantity": 8,
  "time_horizon": "5-20 days",
  "thesis": "..."
}
```

`SELL` tickets are exit-only and must include the existing position reference.

## orders.json

```json
[
  {
    "ticker": "RELIANCE",
    "side": "BUY",
    "product": "CNC",
    "quantity": 8,
    "order_type": "LIMIT",
    "price": 2500.0,
    "strategy_family": "breakout_20d_pullback",
    "reason": "PM approved after risk resize"
  }
]
```
