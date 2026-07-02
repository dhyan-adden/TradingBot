# Risk Manager

Reads:

- `30_trade_plan.md`
- `00_context.md`
- `tradeloop/config/settings.yaml`

May invoke:

- `tradeloop/lib/risk/sizing.py`
- `tradeloop/lib/risk/checks.py`

Writes: `40_risk_report.md`.

Hard checks: per-trade risk <= 1.5% equity, total open risk <= 4%, max 4
concurrent positions, min position size INR 15,000, max single position 25%,
max sector exposure 40%, position size <= 1% ADV20, daily drawdown circuit at
-3%, long-only, no F&O, no leverage. May approve, resize, or reject.
