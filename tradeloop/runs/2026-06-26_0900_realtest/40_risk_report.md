# 40 Risk Report — 2026-06-26 premarket

**Role:** Risk Manager. Apply position- and portfolio-level limits to the
HDFCBANK ticket from `30_trade_plan.md`. Approve, resize, or reject. Indian cash
equities, paper, long-only CNC, no leverage.

**Data basis:** `30_trade_plan.md`, `22_debate.md`, `13_technical.md`,
`00_context.md`, `config/settings.yaml`, and memory. Kite daily closes to
2026-06-25.

**Live broker state:** UNAVAILABLE. Every Zerodha MCP call this run
(`margins`, `positions`, `holdings`, `quote NSE:HDFCBANK`) returned
**403 TokenException** — same failure logged in all upstream stages. I cannot
read live cash, open positions, or a live LTP. Risk checks below run against the
declared paper account state (Rs.100,000, zero open positions) carried from the
trade plan. **This is the single largest open risk on this ticket and the basis
for the conditional verdict.**

---

## Verdict: APPROVE (RESIZED + REGATED) — CONDITIONAL

The ticket is risk-policy compliant at the reference entry of 800.00, but it sits
**0.2% under the 25% position cap with zero headroom**. A fill anywhere above
~806.45 breaches the cap at 31 shares. I therefore **cut size to 30 shares** to
restore a margin of safety and add a hard entry-price ceiling. The trade remains
**conditional** on the trigger, a live LTP, and a live account-state re-check at
the broker step.

---

## 1. Account state used for checks

| Field | Value | Source |
|---|---|---|
| Equity (paper) | Rs.100,000 | settings.yaml / trade plan |
| Open positions | 0 (assumed) | trade plan — **NOT broker-confirmed (403)** |
| Open risk in book | 0.0% (assumed) | trade plan — **NOT broker-confirmed (403)** |
| Day P&L | 0.0% (assumed) | trade plan — **NOT broker-confirmed (403)** |

Drawdown circuit (-3% daily): cannot be evaluated against live P&L. Assumed not
tripped (premarket, flat book). Broker step MUST re-verify before routing.

## 2. Ticket as submitted (trade plan)

HDFCBANK BUY CNC, ref entry 800.00, stop 775.00, T1 820, T2 835, **qty 31**,
strategy `breakout_20d_pullback`.

## 3. Limit-by-limit check (as submitted, 31 sh @ 800)

| Limit (config) | Threshold | This ticket | Pass? |
|---|---|---|---|
| Per-trade risk | <= 1.5% equity | 31 × 25 = Rs.775 = **0.78%** | PASS |
| Total open risk | <= 4.0% | 0.78% (only position) | PASS |
| Max concurrent positions | 4 | 1 | PASS |
| Min position size | >= Rs.15,000 | Rs.24,800 | PASS |
| Max single position | <= 25% (Rs.25,000) | Rs.24,800 = **24.80%** | PASS (thin) |
| Max sector exposure (banking) | <= 40% | 24.80% | PASS |
| Position vs 1% ADV20 | <= 1% ADV20 | **NOT EVALUABLE — no ADV20 upstream** | UNVERIFIED |
| Long-only / CNC / no leverage | required | BUY / CNC / unlevered | PASS |

Risk-per-share is Rs.25.00 off the 800.00 reference entry (entry 800 − stop 775),
not the Rs.21.30 the debate quoted off the 796.30 close. Sizing must use the
entry, so Rs.25 is the correct 1R. This makes the position slightly riskier per
share than the debate implied, but still well inside the 1.5% budget.

## 4. The binding problem — cap headroom and fill slippage

The 25% cap is the binding constraint, and at 31 shares it is satisfied only
because the reference entry is exactly 800. The position notional reaches the
Rs.25,000 cap at an entry of **Rs.806.45** (25,000 / 31). The trade plan's own
entry zone is 800.00–801.00 with a disqualify only above 805 "without volume" —
i.e. a volume-confirmed fill up to ~805 is permitted, and a breakout entry can
realistically print at 801–805. At 805, 31 × 805 = Rs.24,955 (still 24.96%, ok),
but any fill at 806.46+ silently breaches the 25% cap. With slippage on a 20-day-
high breakout this is a live, not theoretical, risk.

**Resolution — resize to 30 shares.** This restores headroom: the cap is only
breached above Rs.833.33 (25,000 / 30), which is above T2 and structurally
impossible as an entry. 30 shares is the policy-safe size for the entire
permitted entry band.

## 5. Resized ticket (RISK-APPROVED)

| Field | Value |
|---|---|
| Ticker | HDFCBANK |
| Side | BUY (open) |
| Product | CNC |
| Strategy family | `breakout_20d_pullback` |
| Reference entry | 800.00 |
| **Quantity** | **30 shares** (cut from 31) |
| Hard stop | 775.00 |
| Target 1 / Target 2 | 820.00 / 835.00 |
| **Max entry price (risk ceiling)** | **805.00** — do NOT fill above this |

Resized metrics @ 30 sh, 800 entry:
- Notional: 30 × 800 = **Rs.24,000 = 24.0%** (cap, with Rs.1,000 headroom)
- Per-trade risk: 30 × 25 = **Rs.750 = 0.75%** (<= 1.5%)
- At the 805 ceiling: 30 × 805 = Rs.24,150 = 24.15% (still inside cap)
- Min size Rs.15,000: PASS
- R:R unchanged: T1 +20 = 0.8R, T2 +35 = 1.4R; blended ~1.1R on 50/50 scale-out

The pullback alternate (788–793) is also approved at 30 shares — lower entry only
reduces notional and risk, so it stays inside every limit by a wider margin.

## 6. Conditions on this approval (all must hold at broker step)

1. **Trigger fired:** intraday hold above 799.50 on reasonable volume, OR
   stabilisation in 788–793 above SMA20. No pre-trigger entry.
2. **Live LTP obtained.** Current Kite token is 403 — the broker step MUST get a
   live quote before placing. No fill on a stale 796.30 close.
3. **Entry price <= 805.00.** Hard ceiling. Above this, do not chase — re-size or
   stand down. This guards the 25% cap against breakout slippage.
4. **Live account re-check.** Broker step MUST confirm via Zerodha (a) cash/
   margin covers Rs.24,150, (b) actual open positions <= 3 so this is the <=4th,
   (c) no other HDFCBANK/banking exposure pushing sector past 40%, (d) day P&L
   above the -3% drawdown circuit. The 403 means none of this is verified now;
   the flat-book assumption is inherited, not confirmed.
5. **Disqualify:** opens below 788 and fails to recover, gap above 805 without
   volume, or NIFTY breaks 23900.

## 7. Unresolved gaps (flagged, do not block at this size)

- **ADV20 / 1%-of-ADV liquidity check NOT EVALUABLE** — no ADV20 series was
  provided by any upstream stage. HDFCBANK is the most liquid bank on the NSE
  (daily turnover in thousands of crore), so a ~Rs.24k order is microscopic
  versus 1% of ADV20 — the limit is satisfied in substance with overwhelming
  margin. Marked UNVERIFIED only because the raw number was never passed through;
  it is not a real liquidity concern for this name and size.
- **Live broker state (403)** — see condition 4. The principal residual risk.

## 8. Memory

No HDFCBANK dossier, no prior HDFCBANK debate, no `breakout_20d_pullback`
performance history, no lessons_learned entries — clean slate (confirmed in
`lessons_learned.md`, `strategy_performance.md`, `stock_dossiers/`). The only
logged item is the 2026-05-17 RELIANCE skip, which does not bear on this name or
this decision. No memory conflict; nothing to override.

---

**Risk Manager decision:** APPROVE HDFCBANK BUY CNC at **30 shares** (resized
down from 31 for cap headroom), stop 775, targets 820/835, with a hard
**805.00 entry ceiling**, conditional on trigger confirmation, a live LTP, and a
live broker-state re-check at routing. Per-trade risk 0.75%, notional 24.0%,
single position, all portfolio limits satisfied. No shorts, no F&O, no leverage,
CNC only. This file is a decision artifact only — no live order is placed here.
