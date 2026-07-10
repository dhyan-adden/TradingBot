# 40 Risk Report - 2026-07-09 1129 Premarket

Run: `2026-07-09_1129_premarket`
Mode: premarket (new entries allowed).
Basis: equity INR 99,992.66; cash INR 51,098.40; daily P&L INR 0.00 (from `00_context.md`).
Caps source: `tradeloop/config/settings.yaml` (max_sector_exposure_pct = 50, raised from 40 on 2026-07-07 - settings value used).
Long-only cash equities, CNC. No shorts, no F&O, no leverage.

Account-state note: Kite `zerodha_margins` returns net INR 64,500 with empty `positions`/`holdings`.
This is the live-broker demat/margin surface and does NOT reflect the paper trades.
The TradeLoop paper ledger (`00_context.md`) is the authoritative book for this cycle:
positions HDFCBANK (30 @ 830.62) and SBIN (23 @ 1042.42), equity INR 99,992.66. All checks below use the ledger.

Tickets evaluated: 1 new BUY (SUNPHARMA). No SELL/exit tickets this cycle.

---

## Verdict Summary

| Ticker | Side | Verdict | Binding constraint |
|--------|------|---------|--------------------|
| SUNPHARMA | BUY CNC | **REJECT** | `below_min_position_size` - notional INR 9,686.50 < INR 15,000 floor (hard cap) |

**orders.json new-entry side: EMPTY.** No new BUY passes the hard checks this cycle.
Existing positions unchanged (HDFCBANK HOLD stop 807.24; SBIN HOLD / EXIT-WATCH tripwire 1019, hard stop 1015.40).

---

## SUNPHARMA - BUY - CNC - REJECT

Ticket: qty 5, entry 1937.30, hard_stop 1886.55, T1 2004.97, T2 2038.81, `breakout_20d_pullback`.

### Hard checks against settings.yaml

| Check | Cap | This ticket | Pass? |
|-------|-----|-------------|-------|
| Per-trade risk <= 1.5% equity | INR 1,499.89 | 5 x (1937.30 - 1886.55) = 5 x 50.75 = INR 253.75 (0.254%) | PASS |
| Total open risk <= 4% equity | INR 3,999.71 | existing 1,322.86 + 253.75 = INR 1,576.61 (1.58%) | PASS |
| Max concurrent positions <= 4 | 4 | 2 open (HDFCBANK, SBIN) + SUNPHARMA = 3 | PASS |
| **Min position size >= INR 15,000** | **INR 15,000** | **notional 5 x 1937.30 = INR 9,686.50** | **FAIL** |
| Max single position <= 25% equity | INR 24,998.17 | INR 9,686.50 (9.69%) | PASS |
| Max sector exposure <= 50% equity | INR 49,996.33 | Pharma (new sector) = INR 9,686.50 (9.69%) | PASS |
| Max total deployed <= 90% equity | INR 89,993.39 | 48,894.26 + 9,686.50 = INR 58,580.76 (58.6%) | PASS |
| Position size <= 1% ADV20 | not provided | ~INR 9.7k on a large-cap; far under 1% ADV by inspection, but ADV20 value not in run inputs - data-unverified, not binding | N/A (not binding) |
| Daily drawdown circuit at -3% | -INR 2,999.78 | daily P&L 0.00 - not tripped | PASS |
| Long-only / no F&O / no leverage | - | BUY, CNC, EQ, delivery | PASS |
| Affordability vs cash | INR 51,098.40 | INR 9,686.50 (leaves ~INR 41,411.90) | PASS |

Existing open-risk detail (for the total-open-risk line):
- HDFCBANK: 30 x (830.62 - 807.24) = 30 x 23.38 = INR 701.40
- SBIN: 23 x (1042.42 - 1015.40) = 23 x 27.02 = INR 621.46
- Existing total = INR 1,322.86.

### Binding constraint

The single breach is the **INR 15,000 minimum position size floor**. Notional INR 9,686.50 is INR 5,313.50 (35%) below the floor.
`tradeloop/lib/risk/checks.py::evaluate` emits `below_min_position_size` for any BUY under `min_position_size_inr`, and `sizing.py::apply_guardrails` returns 0 shares when `capped * entry_price < min_position_size_inr`.
This is a hard, deterministic reject - not a resize-to-fit case, because resizing UP to clear the floor conflicts with the Trader's stated intent and every path is blocked:

- To clear the INR 15,000 floor at entry 1937.30 requires >= 8 shares (8 x 1937.30 = INR 15,498.40). That is a 60% size increase over the ticket.
- Resizing up to 8 shares is inside every OTHER cap (risk 8 x 50.75 = INR 406 = 0.41% per-trade; total open risk 1,322.86 + 406 = INR 1,728.86 = 1.73%; notional 15.5% single-position; still affordable, leaving ~INR 35,600 cash).
- But the Trader deliberately undersized to 5 shares to preserve the ~INR 41k reserve for the Priority-1 ICICIBANK slot that frees when SBIN exits. The Risk Manager does not override a capital-allocation intent by inflating size; the floor is a MINIMUM-viable-position gate, and a position the desk deliberately wants smaller than the floor is by definition not a position the book should open. The floor exists precisely to stop sub-scale, cost-inefficient toe-holds (CNC DP charge INR 15.93/scrip + slippage are a larger % drag on a INR 9.7k lot).

### Resize option surfaced (not applied)

If the Portfolio Manager judges the ICICIBANK-reserve rationale subordinate to taking the SUNPHARMA breakout NOW, the compliant resize is **8 shares** (INR 15,498.40 notional, INR 406.00 risk / 0.41% equity), which clears the floor and every other cap. This is a PM policy call between two legitimate objectives (capital reserve vs. floor compliance), not a risk-limit call - so it is surfaced, not auto-applied. The Risk Manager's own verdict on the ticket AS SUBMITTED (5 shares) is REJECT.

### Execution-gate note (carried, not a risk check)

Even on any approved size, the Trader's gate stands: fill only if the next-session open holds >= 1937.30; live LTP 1934.50 (Zerodha MCP) is ~0.14% below trigger, so the order would not fill at present price regardless. This is an entry-quality gate, orthogonal to the risk reject.

---

## Memory Consultation

- No SUNPHARMA dossier (`memory/stock_dossiers/` holds only RELIANCE), no SUNPHARMA trade-journal entry, no debate-archive precedent.
- `strategy_performance.md` and `lessons_learned.md` carry no `breakout_20d_pullback` precedent - this would be the first instance of the family; nothing to increment.
- No prior lesson is contradicted or reinforced by this reject. Recommend the PM/journal log this as the first `below_min_position_size` reject to seed the pattern: deliberate sub-floor sizing is not a viable book position - either commit to >= floor size or hold the name to watch until a full-size slot exists.

## Portfolio-level notes

- Post-cycle open positions remain 2 of 4 (HDFCBANK, SBIN). Bank-sector deployment INR 48,894.26 = 48.9% of equity, under the 50% cap but with only ~1.1% headroom - a new bank long (ICICIBANK) still needs the SBIN exit to free both the slot and the sector room, consistent with the plan.
- Total open risk stays at INR 1,322.86 (1.32% equity); ample headroom under the 4% ceiling for a properly-sized future entry.
- No circuit tripped; cash INR 51,098.40 fully preserved for the next scan-healthy, floor-clearing entry.
