# 40_risk_report

```json
{
  "evidence": [],
  "decisions": [
    {
      "ticker": "CDSL",
      "decision": "approve",
      "resized_quantity": null,
      "reasons": [
        "per_trade_risk 17*53.30 = 906 INR = 0.91% <= 1.5% cap",
        "position 17*1431.50 = 24336 INR = 24.3% <= 25% single-position cap, above the 15k floor",
        "fills open slot 3 of 4; portfolio open risk stays within 4%"
      ]
    },
    {
      "ticker": "DLF",
      "decision": "approve",
      "resized_quantity": null,
      "reasons": [
        "per_trade_risk 36*32.42 = 1167 INR = 1.17% <= 1.5% cap",
        "position 36*688.00 = 24768 INR = 24.8% <= 25% cap; cash covers CDSL+DLF (49104 <= 51098, no leverage)",
        "fills open slot 4 of 4; total open risk = existing 1323 + CDSL 906 + DLF 1167 = 3396 INR = 3.40% <= 4% cap"
      ]
    },
    {
      "ticker": "GRAVITA",
      "decision": "reject",
      "resized_quantity": null,
      "reasons": [
        "max_concurrent_positions: 2 held (HDFCBANK, SBIN) + CDSL + DLF already fills the 4-position cap; GRAVITA would be the 5th - a hard count no resize can cure",
        "total_open_risk breach: adding 13*106.06 = 1379 INR pushes portfolio open risk to 4775 INR = 4.78% > 4% cap",
        "highest per-trade risk of the three (1.38% on the widest 5.7% stop) and the name the plan itself flagged to trim - drop it before the tighter-stop CDSL/DLF"
      ]
    }
  ]
}
```
