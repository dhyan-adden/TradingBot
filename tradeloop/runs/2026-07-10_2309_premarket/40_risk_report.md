# 40_risk_report

```json
{
  "evidence": [],
  "decisions": [
    {
      "ticker": "DLF",
      "decision": "approve",
      "resized_quantity": null,
      "reasons": [
        "Per-trade risk INR 1167 (36sh x 32.42) = 1.17% equity, under 1.5% cap",
        "Position value INR 24768 = 24.8% of equity, under 25% single-name cap",
        "Real-estate sleeve, no overlap with bank book or CDSL",
        "Highest-conviction fresh long (6.0); DLF+CDSL keep total open risk at 3.40% (<=4%) and fill exactly 4 concurrent positions"
      ]
    },
    {
      "ticker": "CDSL",
      "decision": "approve",
      "resized_quantity": null,
      "reasons": [
        "Per-trade risk INR 906 (17sh x 53.30) = 0.91% equity, under 1.5% cap",
        "Position value INR 24336 = 24.3% of equity, under 25% single-name cap",
        "Sole capital-markets name, no sector doubling",
        "DLF+CDSL cost INR 49104 within INR 51098 cash, long-only CNC, no leverage"
      ]
    },
    {
      "ticker": "GODREJIND",
      "decision": "reject",
      "resized_quantity": null,
      "reasons": [
        "Concurrency cap breached: 2 existing (HDFCBANK, SBIN) + DLF + CDSL already fills the 4-position limit",
        "Approving all three lifts total open risk to 4.64%, over the 4% portfolio cap",
        "All three cost INR 72819 > INR 51098 cash; funding it would require leverage (prohibited)",
        "Lowest conviction of the batch (5.0 vs 6.0), so it is the one dropped to respect the caps"
      ]
    }
  ]
}
```
