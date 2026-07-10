# 41 PM Decision - 2026-07-09 1129 Premarket

Run: `2026-07-09_1129_premarket`
Mode: premarket (new entries allowed).
Role: Portfolio Manager - final gate. I may override risk only to be MORE conservative; any veto cites evidence.
Basis: equity INR 99,992.66; cash INR 51,098.40; daily P&L INR 0.00 (`00_context.md`, the authoritative paper ledger).
Long-only cash equities, CNC. No shorts, no F&O, no leverage.

## Decision

**PASS on SUNPHARMA this cycle. `orders.json` = [] (empty).**
I uphold the Risk Manager's REJECT of the 5-share ticket and decline to apply the surfaced 8-share resize.
This is the MORE-conservative branch, the only direction the PM gate is permitted to move risk.

Existing positions unchanged and NOT re-ticketed here:
- HDFCBANK HOLD (30 @ 830.62, hard stop 807.24). LTP 820.80 > stop - held, stop governs.
- SBIN HOLD / EXIT-WATCH (23 @ 1042.42, hard stop 1015.40, 1019 tripwire). LTP 1025.20 - above both the tripwire and the stop; not exiting this cycle. Exit remains deferred to the intraday tripwire (break below 1019 on volume), not proposed here.

## Cycle status

**HOLD - no new orders.** New entry DEFERRED on a policy + execution judgment (not data-blocked; the scan was healthy this cycle). SUNPHARMA carried to watch at floor-clearing size.

---

## Live confirmation (Zerodha MCP, this cycle)

| Instrument | LTP | Relevance |
|-----------|-----|-----------|
| NSE:SUNPHARMA | 1934.80 | ~0.13% BELOW the 1937.30 entry trigger - execution gate (open must hold >= 1937.30) not met; a LIMIT 1937.30 order would sit unfilled. |
| NSE:SBIN | 1025.20 | Above 1019 tripwire and 1015.40 stop - SBIN is HOLDING; the Priority-1 ICICIBANK slot does NOT free this cycle. |
| NSE:HDFCBANK | 820.80 | Above 807.24 stop - held. |
| NSE:ICICIBANK | 1383.40 | Watch only - still sector-cap (bank ~48.9%/50%) AND slot blocked; no scan setup line; cannot be ticketed. |

Account-state note: Kite `zerodha_margins` reflects the live-broker demat surface, not the paper trades. The TradeLoop paper ledger (`00_context.md`) is the authoritative book for every check below - consistent with the Risk Manager's basis.

## Reasoning (evidence-cited)

I am NOT overriding a risk limit to take MORE risk - the resize-to-8 was surfaced by Risk as a legitimate PM policy call between two objectives, not mandated. Weighing them, PASS is the conservative and correct call:

1. **The floor's purpose forbids the resize, not just the 5-share ticket.**
   The INR 15,000 `min_position_size_inr` floor exists to block sub-scale, cost-inefficient toe-holds (`checks.py::evaluate` emits `below_min_position_size`; `sizing.py::apply_guardrails` returns 0 shares below the floor). The Trader DELIBERATELY sized to 5 shares (INR 9,686.50) - the desk's own intent is a position below the min-viable floor. Inflating that 60% to 8 shares to defeat a floor whose entire job is to reject positions the desk wants smaller than the floor is backwards. A name the desk wants below floor size is, by policy, a WATCH name, not a book position.

2. **Marginal conviction does not justify inflating the ticket.**
   Conviction is 6.5/10 - the floor of "tradeable" - on an AT-entry breakout with `volume_normal` (no surge) and only 1.33x R/R to T1 (67.67 / 50.75). That is not a signal strong enough to warrant deploying 60% more capital than the desk asked for, against the desk's stated capital-allocation plan.

3. **Neither competing objective is urgent this cycle - deferral has zero cost.**
   - SBIN LTP 1025.20 sits above its 1019 tripwire, so SBIN is not exiting today; the ICICIBANK Priority-1 slot stays sector-cap + slot blocked regardless of what I do with SUNPHARMA. The reserve-vs-floor tension the two objectives create is not live this cycle.
   - SUNPHARMA LTP 1934.80 is below the 1937.30 trigger, so even an approved 8-share LIMIT at 1937.30 would NOT fill at present price. Approving would deploy capital the desk wanted preserved, via a size the desk didn't want, on an order that won't fill, to beat a slot that isn't freeing - motion without edge.

4. **Capital discipline is preserved by passing.**
   Passing keeps cash INR 51,098.40 fully dry. The 8-share path would leave ~INR 35,600 - which the plan and risk report both flag as possibly insufficient for a FULL ICICIBANK slot after SBIN exits. Since the ICICIBANK entry is the higher-conviction Priority-1 name (GREEN fundamentals, confirmed private-bank relative strength), spending down the reserve now for a 6.5-conviction name that won't even fill is the wrong trade-off.

**Not a data-block.** Unlike the 10:39 cycle (empty scan / stale auth), the scan was healthy here and SUNPHARMA carried a real scanner setup line with ATR-grounded levels. This is a deliberate policy + execution PASS on a valid but sub-threshold opportunity, correctly logged as such.

## Risk-limit posture

No risk limit is relaxed. The mandatory hard checks in the Risk Report stand unchanged; the deterministic router will re-run every gate on `orders.json` and, with an empty book, will simply produce no fills. I add no order and take no risk. This is a pure conservative HOLD at the PM gate.

## Watch / carry-forward for next cycle

- **SUNPHARMA (watch, re-ticket condition):** re-evaluate at a FLOOR-CLEARING size (>= 8 shares, >= INR 15,000) ONLY on a confirmed above-trigger entry (next-session open holds >= 1937.30 with normal-or-better volume). Do NOT re-ticket a sub-floor toe-hold. This is the FIRST recorded `below_min_position_size` reject in the loop - seed the pattern: deliberate sub-floor sizing is not a viable book position; commit to >= floor size or hold to watch.
- **ICICIBANK (watch, Priority-1):** unblocks only when SBIN exits (frees both the concurrent slot and the ~1.1% bank-sector headroom under the 50% cap). Reserve INR 51,098.40 kept intact for a full-size slot.
- **SBIN (EXIT-WATCH):** hard stop 1015.40, tripwire break below 1019 on volume. Currently 1025.20 - holding.
- **HDFCBANK (hold):** stop 807.24 governs; no add, no exit.

## orders.json contents

```json
[]
```
