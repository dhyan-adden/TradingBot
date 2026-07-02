# Trader

## Trade proposals

None.

`22_debate.md` did not emit a `tradeable` verdict. The best candidate, INFY,
has only a tactical sector/momentum case and lacks the required executable
inputs: deterministic current price, ATR-derived stop, validated entry zone,
and sizeable risk/reward.

## Conditional watchlist

These are not orders and should not be routed.

| Ticker | Strategy family to reassess | Condition required before future ticket |
| --- | --- | --- |
| INFY | sector_rotation_leader or results_day_momentum | Hold above the 19 May high area after NSE open with volume confirmation and a calculable ATR stop. |
| TCS | sector_rotation_leader | Reclaim short-term trend and show follow-through; public 50/200 DMA context is still overhead. |
| SBIN | sector_rotation_leader | Confirm strength while Bank/Financial Services indices stabilize. |
| RELIANCE | ema_trend_pullback / repair | Reclaim and hold 1365-1389; higher-quality trigger remains above 1405. |

## orders.json instruction

Leave `orders.json` as an empty array.
