# 40_risk_report

```json
{
  "evidence": [],
  "decisions": [
    {
      "ticker": "UTIAMC",
      "decision": "reject",
      "resized_quantity": null,
      "reasons": [
        "max_concurrent_positions: 4 slots already filled (CDSL, DLF, HDFCBANK, SBIN); UTIAMC would open a 5th position, over the 4-position cap",
        "insufficient_cash: 24 sh x 1026.10 = INR 24626 exceeds available cash INR 10557.66; the ticket quantity (24) also contradicts its own thesis (10 sh)",
        "min_position_size: the only cash-affordable size (~10 sh = INR 10261) sits below the INR 15000 floor, so no compliant resize exists"
      ]
    }
  ]
}
```
