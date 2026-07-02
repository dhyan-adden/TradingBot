# Raw Technical Setups

## Data Collection Status

- Prepared deterministic setup file was empty.
- Project scanner invocation returned no setups because YFinance DNS resolution
  failed for the tracked NSE symbols. The failures included inability to resolve
  Yahoo hostnames used by YFinance.
- The table below is a public quote snapshot from web evidence, not a validated
  OHLCV/ATR scanner output. It is sufficient for watchlist triage but not
  sufficient for an executable order.

## Public Quote Snapshot

| Ticker | Last public print | Change | Day range | Context |
| --- | ---: | ---: | ---: | --- |
| INFY | Rs 1,196.90 | +4.76% | Rs 1,162.00-1,198.40 | Strong IT rebound; close near high. Source: https://upstox.com/stocks/infosys-limited-share-price/ |
| TCS | Rs 2,327.10 | +1.92% | Rs 2,297.10-2,377.60 | Participated in IT rebound but Dhan lists 50 DMA Rs 2,453.22 and 200 DMA Rs 2,916.20, so trend repair is incomplete. Source: https://dhan.co/stocks/tcs-tata-consultancy-services-ltd-share-price/ |
| SBIN | Rs 948.80 | +1.00% | Rs 939.50-956.60 | Positive close inside weak financial macro tape. Source: https://upstox.com/stocks/state-bank-of-india-share-price/ |
| RELIANCE | Rs 1,322.70 | -0.99% | Rs 1,318.40-1,344.00 | Below prior TradeLoop reclaim zone 1365-1389. Source: https://upstox.com/stocks/reliance-industries-ltd-share-price/ |
| HDFCBANK | Rs 762.45 | -0.81% | Rs 760.25-770.80 | Private-bank weakness. Source: https://upstox.com/stocks/hdfc-bank-ltd-share-price/ |
| ICICIBANK | Rs 1,240.80 | -0.82% | Rs 1,229.80-1,256.30 | Private-bank weakness. Source: https://upstox.com/stocks/icici-bank-ltd-share-price/ |

## Scanner Output

- No validated `breakout_20d_pullback`, `ema_trend_pullback`, or
  `sector_rotation_leader` setup was emitted by the project scanner.
- INFY is the only clear momentum candidate from public evidence, but without
  current OHLCV/ATR and premarket confirmation it remains watchlist-only.
