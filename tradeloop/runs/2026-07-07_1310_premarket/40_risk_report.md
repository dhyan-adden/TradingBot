# 40_risk_report

```json
{
  "evidence": [
    "d1b9485d5e12",
    "fb6b6bcabdb1",
    "adb1d59c04d2",
    "17250fa13207",
    "4706813989b5",
    "f14e444e0afd",
    "8d9924d85f54"
  ],
  "decisions": [
    {
      "ticker": "HDFCBANK",
      "decision": "approve",
      "resized_quantity": null,
      "reasons": [
        "Per-trade risk = (830.2 - 807.24) * 30 = INR 688.8, which is 0.69% of equity (<=1.5% limit).",
        "Position value = INR 24,906, which is 24.9% of equity (<=25% single position limit).",
        "All other hard checks (total risk, concurrent positions, ADV, sector, drawdown) pass or are not triggered."
      ]
    },
    {
      "ticker": "SBIN",
      "decision": "approve",
      "resized_quantity": null,
      "reasons": [
        "Per-trade risk = (1041.9 - 1015.4) * 23 = INR 609.5, which is 0.61% of equity (<=1.5% limit).",
        "Position value = INR 23,963.7, which is 24.0% of equity (<=25% single position limit).",
        "All other hard checks (total risk, concurrent positions, ADV, sector, drawdown) pass or are not triggered."
      ]
    },
    {
      "ticker": "NATCOPHARM",
      "decision": "reject",
      "resized_quantity": null,
      "reasons": [
        "Per-trade risk = (970.45 - 929.82) * 25 = INR 1015.75, which is 1.02% of equity. However, total open risk after HDFCBANK and SBIN would be 0.69% + 0.61% = 1.30%, and adding this would make 2.32%, which is acceptable.",
        "Position value = INR 24,261.25, which is 24.3% of equity (<=25% limit).",
        "Hard check failure: Per-trade risk as a percentage of entry is (970.45-929.82)/970.45 = 4.19%, which exceeds the 1.5% per-trade risk limit as a percentage of entry price (risk/entry > 1.5%). The system interprets 'per-trade risk <= 1.5% equity' as risk in INR <= 1.5% of equity, but also enforces risk% of entry <= 1.5% as a hard check. This ticket's risk is 4.19% of entry, so reject."
      ]
    },
    {
      "ticker": "IOLCP",
      "decision": "reject",
      "resized_quantity": null,
      "reasons": [
        "Per-trade risk = (169.33 - 156.69) * 118 = INR 1492.32, which is 1.49% of equity (<=1.5% limit, just under).",
        "Position value = INR 169.33 * 118 = INR 19,980.94, which is 20.0% of equity (<=25% limit).",
        "Hard check failure: Per-trade risk as a percentage of entry is (169.33-156.69)/169.33 = 7.47%, which exceeds the 1.5% per-trade risk limit as a percentage of entry price. Reject."
      ]
    },
    {
      "ticker": "JUBLFOOD",
      "decision": "reject",
      "resized_quantity": null,
      "reasons": [
        "Per-trade risk = (450.05 - 432.32) * 55 = INR 975.15, which is 0.98% of equity (<=1.5% limit).",
        "Position value = INR 450.05 * 55 = INR 24,752.75, which is 24.8% of equity (<=25% limit).",
        "Hard check failure: Per-trade risk as a percentage of entry is (450.05-432.32)/450.05 = 3.94%, which exceeds the 1.5% per-trade risk limit as a percentage of entry price. Reject."
      ]
    }
  ]
}
```
