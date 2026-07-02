# Raw Technical Setups

## Deterministic Fetch Status

Local project scanner was attempted for `RELIANCE`:

`tradeloop.lib.ta.scanner.scan_symbol("RELIANCE")`

Result: failed due DNS/network restriction while resolving Yahoo Finance:
`DNSError: Could not resolve host: guce.yahoo.com`.

## Fallback Evidence Used

Public OHLC rows from StockAnalysis were used for the technical stage:

Source: https://stockanalysis.com/quote/nse/RELIANCE/history/

Latest rows:

| Date | Open | High | Low | Close | Volume |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2026-05-15 | 1356.80 | 1364.80 | 1329.20 | 1336.40 | 19,976,192 |
| 2026-05-14 | 1365.20 | 1378.00 | 1358.40 | 1361.80 | 17,303,059 |
| 2026-05-13 | 1361.40 | 1372.40 | 1352.40 | 1358.80 | 13,797,989 |
| 2026-05-12 | 1392.00 | 1393.50 | 1360.30 | 1364.00 | 24,357,500 |
| 2026-05-11 | 1420.00 | 1428.00 | 1382.00 | 1388.20 | 15,261,787 |

Calculated from the 50 visible daily rows through May 15, 2026:

- Close: 1336.40
- SMA5: 1361.84
- SMA10: 1404.52
- SMA20: 1388.55
- SMA50: 1378.84
- RSI14: 39.97
- ATR14: 32.48
- MACD line/signal/histogram: -1.68 / 6.10 / -7.78
- 20-day high/low: 1473.40 / 1311.00
- Average volume 20D: 20,030,574
- 10-day change: -8.66%
