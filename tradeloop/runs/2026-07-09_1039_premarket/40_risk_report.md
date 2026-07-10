# Risk Report - 2026-07-09 Premarket

## Decision: APPROVE (no new orders to gate)

The Trader proposed **ZERO new-entry tickets** this cycle (`02_setups_raw.md` empty on a Kite auth-token timing gap, so no name could be price-grounded/sized).
Both existing positions are **HOLD on their existing hard stops** - no adds, no proactive exits.
There are therefore **no BUY tickets to size or gate and no SELL tickets to validate**.
My job reduces to (1) confirming no new risk is being added - confirmed, zero new tickets - and (2) validating the current portfolio against every limit.

Equity base for pct caps: INR 99,992.66. Cash INR 51,098.40. Daily P&L INR 0.0.
Live prices (verified via Zerodha LTP): HDFCBANK 818.45, SBIN 1025.70.

---

## Current Portfolio Standing vs Hard Limits

| # | Limit | Cap | Current | Status |
|---|-------|-----|---------|--------|
| 1 | Per-trade risk | <= 1.5% equity | n/a - no new trade | PASS (no new trade) |
| 2 | Total open risk | <= 4.0% (INR 3,999.71) | **1.32% at cost (INR 1,322.86) / 0.57% at live** | PASS - large headroom |
| 3 | Max concurrent positions | 4 | **2** (HDFCBANK, SBIN) | PASS - 2 slots free |
| 4 | Min position size | >= INR 15,000 | HDFCBANK 24,553.50; SBIN 23,591.10 | PASS |
| 5 | Max single position | <= 25% equity | HDFCBANK **24.56%**; SBIN 23.59% | PASS - HDFCBANK TIGHT (0.44% headroom) |
| 6 | Max sector exposure | <= 50% (settings.yaml, banks) | **48.15% at live (48.90% at cost)** | PASS - TIGHT (~1.1-1.9% headroom) |
| 7 | Daily drawdown circuit | -3.0% (-INR 2,999.78) | 0.0% | PASS - not tripped |
| 8 | Long-only | BUY opens / SELL exits only | no shorts; both are longs held | PASS |
| 9 | No F&O / no leverage | cash equity CNC only | no derivatives, no margin | PASS |

### Open-risk detail (entry -> hard stop, at cost basis)
- HDFCBANK: (830.62 - 807.24) x 30 = INR 701.40
- SBIN: (1042.42 - 1015.40) x 23 = INR 621.46
- **Total open risk = INR 1,322.86 = 1.32% of equity** (cap 4.0%). At live prices, drawdown-to-stop is only INR 573.20 (0.57%).

### Sector exposure detail (both holdings are banks)
- HDFCBANK 30 x 818.45 = 24,553.50; SBIN 23 x 1025.70 = 23,591.10.
- **Bank sector = INR 48,144.60 = 48.15% of equity** at live (48.90% at cost) vs the **50% cap** (raised 40->50 on 2026-07-07 for this two-bank book).

---

## Tight Limits (flag, not breach)

- **Sector exposure ~48% vs 50% cap** - only ~1-2% headroom. No new bank position can be opened without breaching; a third position must be non-bank. Reverting the cap to 40% (per the settings.yaml note) would put the book over-limit, so no de-risk trigger fires while both holdings are HELD.
- **HDFCBANK 24.56% vs 25% single-position cap** - drift-tight from price movement, not from any action this cycle. No add is possible; any further mark-up simply narrows headroom - informational only, no forced trim (it is a market-value drift on a held position, not a new allocation).

No limit is breached. Nothing forces a resize or exit this cycle.

---

## Summary

- **No new orders to gate** - Trader proposed zero new-entry tickets (scan/auth gap); both holdings HOLD on existing hard stops; no adds, no exits. No new risk added.
- **Bank sector exposure: 48.15% (live) / 48.90% (cost) vs 50% cap** - TIGHT (~1-2% headroom); blocks any new bank entry.
- **Total open risk: 1.32% at cost (0.57% at live) vs 4.0% cap** - comfortable headroom.
- **Tight limits:** sector (~48/50) and HDFCBANK single-position (24.56/25) - both drift-tight, neither breached, neither forces action on a held book.
- **Circuit / long-only / no-F&O / no-leverage:** all clear (daily P&L 0.0, 2 of 4 slots used, both longs, CNC cash only).
- **Overall: APPROVE** - portfolio within all limits; nothing to gate, resize, or reject this cycle.

_Risk Manager | Cycle: 2026-07-09 premarket | Zero new tickets; portfolio within all caps; sector ~48/50 and HDFCBANK ~24.6/25 flagged tight_
