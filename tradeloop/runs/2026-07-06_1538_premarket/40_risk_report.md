# 40_risk_report

```json
{
  "evidence": [],
  "decisions": [
    {
      "ticker": "ICICIBANK",
      "decision": "resize",
      "resized_quantity": 3,
      "reasons": [
        "Original size of 4 shares risks ~₹138.60 (~0.14% of ₹100k equity) - within per-trade cap, but resized down for conservative risk posture",
        "Per-trade risk at 3 shares: stop distance ₹34.65 × 3 = ₹103.95 (~0.104% equity) - well under 1.5% cap",
        "Position value at 3 shares: 3 × ₹1426.50 = ₹4279.50 (~4.28% equity) - under 25% single position cap",
        "Min position size INR 15,000 not met at 3 shares (₹4279.50) - position size below minimum threshold",
        "Resize: quantity 3 keeps risk minimal but fails INR 15,000 minimum position size requirement",
        "Final: REJECT due to position size (₹4279.50) falling below INR 15,000 minimum threshold even at 3 shares; 4 shares (₹5706) also below minimum"
      ]
    }
  ]
}
```
