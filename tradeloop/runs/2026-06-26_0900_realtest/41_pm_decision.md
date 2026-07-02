# 41 PM Decision — 2026-06-26 premarket

**Role:** Portfolio Manager. Final gate on the HDFCBANK ticket from
`40_risk_report.md` (risk-approved 30 sh, entry ceiling 805, stop 775, T1 820 /
T2 835, conditional). RELIANCE/TCS/INFY were PASSED upstream — no tickets, no
action here. Indian cash equities, PAPER, long-only CNC, no leverage.

**Data basis:** `30_trade_plan.md`, `40_risk_report.md`, `22_debate.md`,
`13_technical.md`, memory. Closes to 2026-06-25.

---

## Verdict: APPROVED IN PRINCIPLE — HELD (no live order emitted this run)

I concur with Risk on the thesis and the sizing: HDFCBANK BUY CNC, **30 shares**,
stop **775**, T1 **820** / T2 **835**, hard entry ceiling **805**, strategy
`breakout_20d_pullback`. At those numbers the trade is policy-clean (risk 0.75%,
notional 24.0%, single position, all limits PASS). I do not override Risk; I am
only more conservative on one point, below.

**But the ticket does not become a live order this run, and I will not emit one.**
Both gating conditions Risk attached are unmet and unmeetable right now:

1. **No live LTP.** My own Zerodha MCP sanity check this run returned
   **403 TokenException** on all four calls (`quote NSE:HDFCBANK`, `positions`,
   `holdings`, `margins`) — identical to every upstream stage. There is no live
   price. The only price in the system is the stale 796.30 close. Risk condition 2
   ("no fill on a stale close") is therefore failed by definition.

2. **No trigger confirmation possible.** The entry is conditional on an *intraday*
   hold above 799.50 on volume (or stabilisation 788–793). With no live quote
   stream, the trigger cannot be observed or confirmed. A breakout-pullback entry
   placed blind, off a close, is exactly the chase the plan forbids.

3. **No broker-state verification.** The flat-book / Rs.100,000-cash / no-other-
   banking-exposure / drawdown-circuit-not-tripped assumptions are all inherited,
   not confirmed — the 403 means `positions`, `holdings` and `margins` are unread.
   Routing real size against unverified account state is not acceptable even in
   paper, because the loop's contract is that the broker step re-checks live.

These are not reasons to **reject** the thesis — the analysis is sound and the
name is the single structurally intact long in the universe. They are reasons the
order is **not yet executable**. The right state is: ticket approved, parameters
locked, execution held until a live session restores quotes and account reads.

### My one conservative tightening over Risk
Risk left the pullback alternate (788–793) approved at 30 shares. I keep that, but
I add: **if the only fill available is a gap-up open above 805, stand down for the
session — do not re-size up the ceiling.** Risk already says don't chase above 805;
I am making explicit that the response is *no trade today*, not a recalculated
larger ceiling. This costs nothing and removes a slippage-chase failure mode.

---

## Locked ticket parameters (for the broker step, when live)

| Field | Value |
|---|---|
| Ticker | HDFCBANK |
| Side | BUY (open) |
| Product | CNC |
| Strategy family | `breakout_20d_pullback` |
| Quantity | **30 shares** |
| Reference entry | 800.00 |
| Order type | LIMIT |
| Limit / max entry price (hard ceiling) | **805.00** — never fill above |
| Hard stop | **775.00** |
| Target 1 / Target 2 | **820.00 / 835.00** |
| Per-trade risk @ 805 | 30 × (805−775) capped at plan = ~0.75–0.90% |
| Notional @ 805 ceiling | Rs.24,150 = 24.15% (inside 25% cap) |

## Execution gate (ALL must hold before any live order — unchanged + held)
1. Live Zerodha session restored (no 403); a **live LTP** is read.
2. **Trigger fired:** intraday hold > 799.50 on volume, OR stabilisation 788–793
   above SMA20. No pre-trigger entry.
3. **Fill price <= 805.00.** Above this: stand down for the session (PM addendum).
4. **Live broker re-check:** cash covers ~Rs.24,150; open positions <= 3; no other
   HDFCBANK/banking exposure breaching 40% sector cap; day P&L above −3% circuit.
5. **Disqualify:** opens < 788 and fails to recover, gap > 805 without volume, or
   NIFTY breaks 23900.

## orders.json contents
`orders.json` is written as an **empty live-order array** with a `held` block
documenting the approved-but-not-routed ticket and the blocking reason (403, no
live quote). This is PAPER — no live order is placed by this loop regardless. The
broker router reads `orders.json`; an empty `orders` array means it routes nothing,
which is the correct outcome while quotes are dark.

## Memory
Clean slate confirmed: no HDFCBANK dossier, no prior HDFCBANK debate, no
`breakout_20d_pullback` performance history, no lessons_learned entries. The only
logged item is the 2026-05-17 RELIANCE skip — irrelevant to this name. No conflict,
nothing to override. **Process note worth carrying forward (not a market lesson):**
this is the second consecutive artifact dependent on a dead Kite token; the loop
cannot route any conditional intraday entry while the session is 403. Token refresh
is a precondition for this strategy family, not an afterthought.

---

**PM decision:** APPROVE HDFCBANK BUY CNC 30 sh, stop 775, T1 820 / T2 835, entry
ceiling 805 — **HELD, not routed**, because no live LTP / trigger / broker-state
is obtainable (403). RELIANCE/TCS/INFY: no action (passed upstream). No shorts, no
F&O, no leverage, CNC only. `orders.json` carries zero live orders this run.
