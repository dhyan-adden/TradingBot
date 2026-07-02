# 30 Trade Plan — 2026-06-26 premarket

**Role:** Trader. Convert the debate verdict into long-only CNC trade ticket(s)
with entry, hard stop, targets, and ATR/cap-based size.

**Data basis:** Kite daily closes to 2026-06-25 (00_context.md, 13_technical.md,
22_debate.md). **Live MCP quote attempt this run: FAILED — Kite 403 TokenException
(zerodha_quote NSE:HDFCBANK).** All levels below are anchored to yesterday's close
(796.30) and the structural levels in technical/debate. The ticket is CONDITIONAL —
it does not fire until the intraday trigger confirms and a live quote is obtainable
at the broker step.

**Account:** Rs.100,000 paper, long-only CNC, 1.5% risk/trade, max 4 positions,
max 25%/position, 3% daily drawdown circuit. No open positions. Cash Rs.100,000.

**Advanced from debate:** HDFCBANK only (conviction 6/10, WATCH → tradeable on
breakout confirmation). RELIANCE (3/10), TCS (1/10), INFY (0/10) all PASSED — no
tickets written for them.

---

## Ticket 1 — HDFCBANK (CONDITIONAL BUY)

| Field | Value |
|---|---|
| Ticker | HDFCBANK |
| Side | BUY (open) |
| Product | CNC |
| Strategy family | `breakout_20d_pullback` |
| Entry zone | **800.00–801.00** primary (on intraday hold > 799.50); **788–793** pullback alternate (stabilise above SMA20) |
| Reference entry (sizing) | 800.00 |
| Hard stop | **775.00** (below SMA20 765.5 / SMA50 773.6 cluster) |
| Target 1 (T1) | **820.00** (book partial) |
| Target 2 (T2) | **835.00** |
| Quantity | **31 shares** |
| Conviction | 6 / 10 |
| Time horizon | 3–10 days (breakout-pullback family) |

### Position sizing (ATR-/cap-based)

No ATR series was provided upstream; the stop is anchored to the SMA20/SMA50
support cluster (775), giving a **risk-per-share of Rs.25.00 (entry 800 − stop 775,
≈3.1%)** — this serves as the explicit per-share risk unit (1R) in place of a raw
ATR multiple, and the 775 anchor sits structurally where a true ATR stop would.

- Risk-budget shares: 1.5% × 100,000 = Rs.1,500 ÷ Rs.25 = **60 shares**
- Position-cap shares: 25% × 100,000 = Rs.25,000 ÷ Rs.800 = **31 shares**
- **Binding constraint = 25% position cap → 31 shares** (take the lower of the two).

Resulting exposure:
- Notional: 31 × 800 = **Rs.24,800 (24.8% of account — inside 25% cap)**
- Actual risk at stop: 31 × Rs.25 = **Rs.775 = 0.78% of account** (well inside 1.5%)
- R:R — T1 820 = +Rs.20/sh = 0.8R; T2 835 = +Rs.35/sh = 1.4R. Blended on a
  50/50 partial scale-out ≈ 1.1R, with the runner managed to a trailing stop
  above breakeven after T1.

### Execution gating (must all hold before broker routes)
1. **Trigger:** intraday hold **above 799.50** on reasonable volume (20D-high
   breakout). OR pullback into **788–793** stabilising above SMA20.
2. **Live quote available** (current Kite token is 403 — broker step must confirm
   a live LTP before placing).
3. **Disqualify / do NOT enter if:** opens below 788 and fails to recover, price
   gaps above 805 without volume confirmation (no chase), or NIFTY breaks **23900**.

### Thesis
HDFCBANK is the only structurally intact name in the universe: sole stock above
both SMA20 (765.5) and SMA50 (773.6), +5.0% over 20 sessions on a flat-to-down
NIFTY (genuine relative strength), pressing the 20-day high (799) with RSI 68.5
confirming live buying. The debate adjudicated the bear's position-size objection
as rejected — the stop is policy-compliant once sized to the 25% cap (31 shares,
0.78% risk), so the only remaining objection is timing. This is therefore a clean
breakout-pullback long gated on a single event: an intraday hold above 799.50.
RSI 68.5 leaves limited momentum headroom, so the plan scales partial profit at
T1 (820) and trails the runner. Conviction docked to 6/10 for unconfirmed breakout,
RSI headroom, no catalyst, and a mildly negative tape.

### Memory citation
No HDFCBANK dossier, no prior debates, no lessons_learned entries, no
strategy_performance history for HDFCBANK — clean memory slate (confirmed in
13_technical.md and memory files). The only logged item is a 2026-05-17 RELIANCE
skip (strategy_performance.md), which does not apply to this name. No memory
conflict; nothing to override.

---

## Tickets NOT written (debate PASS — recorded for audit)
- **RELIANCE** — PASS (3/10): below SMA50 1346.8, below dossier reclaim 1365, only
  7 pts above 1311 invalidation. Watchlist only.
- **TCS** — PASS (1/10): confirmed downtrend, Tier-C bounce only.
- **INFY** — PASS (0/10): falling knife, RSI 28 in downtrend = continuation.

No shorts. No F&O. No leverage. CNC only. This file is a decision artifact only —
no live order is placed here; orders.json is produced by the downstream
deterministic broker step after PM/risk approval.
