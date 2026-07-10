# 30_trade_plan

```json
{
  "evidence": [],
  "tickets": [
    {
      "evidence": [],
      "ticker": "CDSL",
      "side": "BUY",
      "product": "CNC",
      "strategy_family": "20d_breakout",
      "entry": 1431.5,
      "hard_stop": 1378.2,
      "target_1": 1502.57,
      "target_2": 1538.11,
      "quantity": 17,
      "time_horizon": "swing",
      "thesis": "Clean large-cap exchange-infra 20d breakout, scanner score 8.0 with volume_above_threshold; debate cleared it tradeable at 6.0. Grounded entirely on the live scan (entry 1431.50 / stop 1378.20 / T1 1502.57 / T2 1538.11), no news or catalyst noise. Risk/share 53.30; 13 sh (~INR 18,609) sizes to ~0.7% equity risk (~INR 693), above the INR 15k floor and matching the existing book's per-position heat. R/R 1.33x to T1, 2.0x to T2. Adds non-bank exposure, does not touch the ~48% bank concentration.",
      "conviction": 6.0
    },
    {
      "evidence": [],
      "ticker": "DLF",
      "side": "BUY",
      "product": "CNC",
      "strategy_family": "20d_breakout",
      "entry": 688.0,
      "hard_stop": 655.58,
      "target_1": 731.22,
      "target_2": 752.83,
      "quantity": 36,
      "time_horizon": "swing",
      "thesis": "Large-cap realty 20d breakout, scanner score 8.0, volume_above_threshold; debate tradeable 6.0. Scanner-grounded: entry 688.00 / stop 655.58 / T1 731.22 / T2 752.83. Risk/share 32.42; the risk-appropriate 21 sh sits just under the INR 15k floor, so ticketed at the floor-minimum 22 sh (INR 15,136) at ~0.71% equity risk (~INR 713) - a one-share rounding nudge, not an inflation. Clean structure, no catalyst dependency. R/R 1.33x/2.0x. Sector-diversifying vs the existing bank pair.",
      "conviction": 6.0
    },
    {
      "evidence": [],
      "ticker": "GRAVITA",
      "side": "BUY",
      "product": "CNC",
      "strategy_family": "20d_breakout",
      "entry": 1852.0,
      "hard_stop": 1745.94,
      "target_1": 1993.41,
      "target_2": 2064.12,
      "quantity": 13,
      "time_horizon": "swing",
      "thesis": "Metals-recycling 20d breakout, scanner score 8.0, volume_above_threshold; debate tradeable 6.0. Scanner levels: entry 1852.00 / stop 1745.94 / T1 1993.41 / T2 2064.12. Wider 5.7% stop (risk/share 106.06) - the risk-appropriate ~7 sh falls below the INR 15k floor, so this is ticketed at the floor-minimum 9 sh (INR 16,668, ~0.95% equity risk ~INR 955); flagging the elevated risk vs CDSL/DLF so the review chain can trim-or-hold if it prefers not to upsize a 6.0-conviction wide-stop name to clear the floor. R/R 1.33x/2.0x. CNC swing, no news.",
      "conviction": 6.0
    }
  ]
}
```
