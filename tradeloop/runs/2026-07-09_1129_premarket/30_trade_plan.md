# 30 Trade Plan - 2026-07-09 1129 Premarket

Run: `2026-07-09_1129_premarket`
Macro posture: RISK-OFF (Brent $78+, JGB 30Y 30-year high, Fed hawkish, INR 95.55).
Cash ~INR 51,098; equity ~INR 99,993; per-trade risk 1.5% of equity = ~INR 1,500.
Long-only cash equities, CNC. `SELL` exit-only. No shorts, no F&O, no leverage.

New entries this cycle: **1 (SUNPHARMA).** All other debated names carried `held`.

---

## New Entry Ticket

### SUNPHARMA - BUY - CNC

```json
{
  "ticker": "SUNPHARMA",
  "side": "BUY",
  "product": "CNC",
  "strategy_family": "breakout_20d_pullback",
  "entry": 1937.30,
  "hard_stop": 1886.55,
  "target_1": 2004.97,
  "target_2": 2038.81,
  "quantity": 5,
  "time_horizon": "3-10 days",
  "thesis": "..."
}
```

- **Ticker / side / product:** SUNPHARMA / BUY / CNC (delivery, no leverage).
- **Strategy family:** `breakout_20d_pullback` (scanner `20d_breakout`, score 6.0, `volume_normal`; ATR stop present -> `requires` satisfied).
- **Entry zone:** 1937.30 (scanner `entry`, taken directly from the SUNPHARMA line in `02_setups_raw.md`). Live LTP at plan time 1935.60 (Zerodha MCP), ~0.09% below trigger - price is AT the entry, not above.
- **Hard stop:** 1886.55 (scanner `stop`). Risk/share = 1937.30 - 1886.55 = 50.75 (~2.6%).
- **Target 1:** 2004.97 (scanner target 1). R/R to T1 = 67.67 / 50.75 = 1.33x.
- **Target 2:** 2038.81 (scanner target 2).
- **ATR suggested size:** 5 shares.
  - Risk-cap math: INR 1,500 / 50.75 = 29 shares by the 1.5% rule, but 29 * 1937.30 = INR 56,182 exceeds available cash (INR 51,098) - the risk cap is not the binding constraint here, capital is.
  - Binding constraint is **capital preservation for the Priority-1 ICICIBANK slot** that frees the instant SBIN exits (debate discipline). 5 shares = ~INR 9,687 notional (~19% of cash), leaving ~INR 41,411 in reserve.
  - Actual risk at 5 shares = 5 * 50.75 = INR 253.75 (~0.25% of equity) - well inside the 1.5% ceiling.
- **Conviction:** 6.5 / 10 (debate: only `tradeable` name this cycle; primary and only new-entry slot).
- **Time horizon:** 3-10 days (`breakout_20d_pullback` typical horizon).
- **Execution gate (carried from debate):** confirm the next-session open holds **>= 1937.30** before the order fills. Price is currently 1.3 pts below trigger; if the open fails to reclaim 1937.30, do not chase - hold the ticket unfilled.
- **Memory citation:** No prior SUNPHARMA dossier or trade-journal entry exists; `strategy_performance.md` and `lessons_learned.md` carry no SUNPHARMA/`breakout_20d_pullback` precedent to increment. First recorded instance of this family being ticketed - log the outcome to seed the family win-rate. General lesson honored: only names with a real scanner setup line (real ATR stop) are ticketed; watch names with no scan line are not sized.

**Thesis:** SUNPHARMA is the single cleanest fit for a RISK-OFF tape: a pharma defensive with USD (US generic / specialty) revenue that hedges INR at 95.55, no crude feedstock, and insulation from the G-Sec MTM / yield re-pricing hammering banks and IT. It is a 20-day breakout printing AT the scanner entry (1937.30) with a real ATR stop at 1886.55 and 1.33x R/R to T1 - large-cap institutional volume keeps slippage and manipulation risk low, unlike the small-cap momentum names (BORORENEW, ALKYLAMINE) in the funnel. The bear case is MILD and about execution, not thesis: `volume_normal` (not a surge), price at-entry rather than confirmed above, and a latent US FDA tail (Halol/Mohali history) structural to any pharma long. Those weaknesses are the reason conviction is 6.5 not 8, and the reason size is capped at 5 shares - a deliberately small, capital-preserving toe-hold that keeps ~INR 41k dry for the Priority-1 ICICIBANK entry the moment SBIN exits. Do NOT stack LUPIN as a second pharma this session; a second normal-volume pharma concentrates the shared FDA/price-control tail into one bad scenario for no marginal edge. Note: scanner `entry` (1937.30, the live price frame) governs all levels here - no analyst target or headline was used.

---

## Held / Carried Names (no ticket this cycle)

| Name | State | One-line reason |
|------|-------|-----------------|
| ICICIBANK | held (watch, Priority-1) | Sector-cap blocked (2 bank longs vs 50% cap) + pre-Q1 timing + no scan setup line in `02_setups_raw.md` -> cannot be sized; entry frees only when SBIN exits. |
| HDFCBANK | held (existing position) | HOLD 30 @ 830.62, stop 807.24; below avg cost, no confirmed new breakout -> no add, stop governs, no exit. |
| SBIN | held (existing, EXIT-WATCH) | HOLD 23 @ 1042.42, hard stop 1015.40; 1019 tripwire tested intraday (low 1019.30); exit only on close/volume-break below 1019 - a `SELL` exit ticket is deferred to the tripwire, not proposed here. |
| ALKYLAMINE | held (watch) | Scanner line exists but no fundamentals red-flag screen (pledge/auditor/RPT/OCF unscreened) + Tier-C only + 6% stop; not ticketable as a new position, and no capital slot. |
| LUPIN | held (watch) | Below trigger (2510.00 vs entry 2517.40), `volume_normal`, sector-redundant with SUNPHARMA (no second pharma), no capital path. |
| BORORENEW | held (watch) | Two-part gate unmet: needs close strictly above 640 with margin AND no next-session gap-down; +9.7% one-day pump-risk, Tier-C, cannot ticket on a mid-session depth snapshot. |
| DIXON | held (watch) | Scanner line exists but ~INR 13,554/share (~26.5% of cash each) depletes the ICICIBANK reserve; sizing infeasible within the cash constraint. |
| INFY | held (watch) | Below open (1062.70) and prior close (1069.30); gated on the not-yet-known TCS Q1 result AND reclaim above 1062.70; no scan-confirmed entry today. |
| TCS | held (pass) | Live Q1 FY27 result-day binary; every stage classifies AVOID pre-event; reassess next cycle. |
| RELIANCE | held (pass) | Below the 1365-1389 reclaim zone, O2C crude headwind at $78+, no breakout trigger and no scan setup line. |

---

## Plan Summary

- **1 new BUY ticket:** SUNPHARMA, 5 shares, CNC, entry 1937.30, stop 1886.55, T1 2004.97, T2 2038.81; risk INR ~254 (~0.25% equity); notional ~INR 9,687.
- **Execution gate:** open must hold >= 1937.30 or the order stays unfilled (no chase).
- **Capital after fill:** ~INR 41,411 cash reserved, explicitly to fund the Priority-1 ICICIBANK entry when SBIN's tripwire executes.
- **No second pharma (LUPIN excluded), no bank add (ICICIBANK sector-cap blocked), no small-cap momentum chase (BORORENEW/ALKYLAMINE gated).**
- Existing positions unchanged: HDFCBANK HOLD (stop 807.24), SBIN HOLD / EXIT-WATCH (tripwire 1019, hard stop 1015.40).
