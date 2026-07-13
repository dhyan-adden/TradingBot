# 41_pm_decision

```json
{
  "evidence": [],
  "orders": [],
  "held": [
    {
      "ticker": "UTIAMC",
      "side": "BUY",
      "product": "CNC",
      "quantity": 24,
      "price": 1026.1,
      "order_type": "LIMIT",
      "hard_stop": 989.78,
      "target_1": 1074.52,
      "target_2": 1098.73,
      "max_entry_price": null,
      "strategy_family": "breakout",
      "status": "HELD",
      "reason": "Held per deterministic risk gate rejection; PM concurs and adds no override. (1) max_concurrent_positions: 4 slots already filled (CDSL, DLF, HDFCBANK, SBIN), so UTIAMC would open a non-compliant 5th position. (2) insufficient_cash: 24 sh x 1026.10 = INR 24626 exceeds available cash INR 10557.66, and the ticket qty (24) contradicts its own thesis (10 sh). (3) min_position_size: the only affordable size (~10 sh = INR 10261) is below the INR 15000 floor, so no compliant resize exists. No news catalyst cited."
    }
  ]
}
```
