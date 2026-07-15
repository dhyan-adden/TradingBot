# 41_pm_decision

```json
{
  "evidence": [],
  "orders": [
    {
      "ticker": "HYUNDAI",
      "side": "BUY",
      "product": "CNC",
      "quantity": 8,
      "price": 2037.0,
      "order_type": "LIMIT",
      "hard_stop": 1954.84,
      "target_1": 2201.31,
      "target_2": 2283.47,
      "max_entry_price": 2037.0,
      "strategy_family": "20d_breakout",
      "status": null,
      "reason": "Accept risk's resize from 12 to 8 shares (the plan's own thesis sizes and justifies 8: ~16,296 INR, ~657 INR/share risk within 1.5% equity, above the 15,000 INR min-position floor). 8 keeps single-position notional ~16.3% of equity and total open risk ~74.9% of the 4% cap, versus 12 shares pinning both caps at ~98% with no margin. Entry is contingent on the flagged SBIN stop-breach exit freeing the 4th slot and cash (10,557 < 16,296 required); the deterministic risk/broker controls sequence fill, max-4-concurrent and cash checks on that exit. Clean score-8 20d breakout, conviction 6.0, diversifying add to a bank-heavy book; no adverse catalyst and no evidence to veto more conservatively than risk's 8."
    }
  ],
  "held": []
}
```
