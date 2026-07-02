# 22 Debate Moderator — 2026-06-26 premarket

**Role:** Adjudicate bull (20_bull.md) vs bear (21_bear.md) into a decision-ready
verdict per candidate. Output conviction score (0-10) and verdict
(`tradeable` / `watch` / `pass`).

**Data basis:** Kite daily closes to 2026-06-25 (00_context.md, 13_technical.md).
No live news this run — every thesis rests on price/indicator/memory evidence only.
Live MCP quote attempt failed (Kite 403). All entries require intraday confirmation
before the broker step reads orders.json.

**Account:** Rs.100,000 paper, long-only CNC, 1.5% risk/trade, max 4 positions,
max 25%/position, 3% daily drawdown circuit. No open positions.

---

## HDFCBANK — verdict: WATCH (tradeable on intraday breakout confirmation)

**Conviction: 6 / 10**

### Round 1 — Bull opens, Bear rebuts
- **Bull:** Sole name above both SMA20 (765.5) and SMA50 (773.6); +5.0% over 20D
  on a flat-to-down index = genuine relative strength; pressing the 20D high (799)
  with RSI 68.5 confirming live buying; defined stop at 775; clean memory slate.
- **Bear:** RSI 68.5 is already overbought — thin momentum buffer for a 5-20 day
  swing. Trend label is "chop (transitioning bullish)," not a confirmed uptrend;
  60D return is only +1.8%. The breakout above 799 has NOT fired yet — entering
  pre-trigger violates breakout discipline. No catalyst. Mildly negative tape.

### Round 2 — Bear's strongest punch, Bull defends
- **Bear (position-size objection, point 6):** Stop 775 is Rs.21.30 (2.67%) below
  close. At 1.5% risk (Rs.1,500), that sizes to ~70 shares = Rs.55,720 = 55.7%
  weight — more than double the 25% cap. Stop is "policy-incompatible."
- **Moderator finding — the bear OVERSTATES this.** The two limits are independent;
  the binding one is the 25% position cap, not the risk budget. The trade-plan
  stage sizes to the *lower* of (risk-budget shares, cap shares). Cap = Rs.25,000
  / Rs.~800 ≈ **31 shares**. At 31 shares the actual risk is 31 × Rs.21.30 =
  **Rs.660 = 0.66% of account** — well *inside* the 1.5% policy, not outside it.
  The stop is therefore policy-COMPATIBLE; it simply caps reward in rupee terms,
  not in R-multiple. The R:R geometry (entry ~800, stop 775, target 820-835) is
  ~2:1 to 2.5:1 and unaffected by share count. **Bear point 6 is rejected as a
  reason to pass; it is a sizing detail the trade-plan resolves.**

### Round 3 — what survives
- **Bear points that stand:** (a) breakout above 799.50 is NOT yet confirmed —
  yesterday's close 796.30 is below trigger; (b) RSI 68.5 leaves limited headroom;
  (c) no catalyst; (d) index tape mildly negative. These are **timing** objections,
  not a thesis rejection — the bear itself concedes this ("legitimate setup… timing
  is the issue").
- **Bull points that stand:** relative strength is real and the strongest in the
  universe; structure is the only intact one of the four; risk is genuinely defined
  and policy-compliant when correctly sized; memory is clean (no prior failed long).

**Adjudication:** This is a real long setup gated on one event — an intraday hold
above 799.50 on reasonable volume. Until that prints it is a WATCH, not a live BUY.
Conviction 6/10: high structural quality, docked for unconfirmed breakout + RSI
headroom + no catalyst + down tape. Becomes effectively tradeable the moment the
trigger fires intraday with a 775 stop sized to the 25% cap (~31 shares).

- **Tradeable trigger:** intraday hold above **799.50** on volume → BUY ~800,
  stop **775**, target zone **820-835**, size to 25% cap (~31 sh), risk ~0.66%.
- **Pullback alt:** stabilise in **788-793** above SMA20 → same stop/target.
- **Disqualify if:** opens below 788 and fails to recover, or NIFTY breaks 23900.

---

## RELIANCE — verdict: PASS (watchlist maintained)

**Conviction: 3 / 10**

- **Bull (weak, self-flagged):** above SMA20 (1304.2); RSI recovered to 57.4 from
  ~40 at the May debate; second-closest to its 20D high (-1.1%); 7 pts above the
  1311 invalidation. Bull explicitly labels this a WATCH, not a BUY.
- **Bear:** below SMA50 (1346.8) overhang; -6.7% 60D structural downtrend; only 7
  pts above the 1311 invalidation (uncontrolled downside below); 47 pts below the
  dossier reclaim zone (1365-1389); two prior debates (2026-05-17, both 3.5/10)
  passed for exactly these reasons; no catalyst to override.

**Adjudication:** Bull and bear agree on the outcome — neither argues for a live
long. RSI/SMA20 improvement is incremental and does not meet the dossier's own
re-entry standard (reclaim 1365+). Same call as the two prior debates. PASS, retain
on watchlist; reconsider only on a close above 1365 with the SMA50 overhang cleared.

---

## TCS — verdict: PASS (hard)

**Conviction: 1 / 10**

- **Bull (thin, for completeness):** large-cap franchise approaching oversold
  (RSI 36.6); asymmetric bounce potential if NIFTY stabilises.
- **Bear:** confirmed downtrend, price < SMA20 (2187.1) < SMA50 (2319.2) all
  declining; -14.4% from 20D high with 5D -4.9% (decline still accelerating);
  RSI 36.6 in a downtrend is a continuation, not a reversal, signal; oversold-bounce
  is Tier-C speculation only.

**Adjudication:** No contest. Bull concedes all arguments "fail the policy filter."
Buying into a confirmed downtrend violates the swing-positive-trend mandate. Hard
PASS. Reassess only on SMA20 reclaim (~2187) with RSI improving through 45.

---

## INFY — verdict: PASS (hard; falling knife)

**Conviction: 0 / 10**

- **Bull (none actionable):** RSI 28.2 oversold could precede a relief bounce.
- **Bear:** weakest name by every metric (-16.3% from 20D high, -16.8% 60D, -7.7%
  5D, accelerating); RSI 28 in a downtrend (90 pts below SMA20) is the strongest
  continuation signal, not a buy; no base, no stabilisation; stop is unquantifiable
  (no support to anchor); institutional supply overhang on any bounce.

**Adjudication:** No contest. Catching a falling knife — explicitly prohibited by
policy. Hard PASS, no capital. Revisit only after a multi-day base above 1080,
SMA20 (1130) reclaim, and RSI recovery through 40.

---

## Debate Summary

| Symbol | Verdict | Conviction | Decisive reason |
|---|---|---|---|
| HDFCBANK | **WATCH** (tradeable on breakout confirm) | 6/10 | Only intact structure + real relative strength; gated on intraday hold > 799.50; stop is policy-compliant when sized to 25% cap (bear's size objection rejected) |
| RELIANCE | **PASS** (watchlist) | 3/10 | Below SMA50 + below dossier reclaim 1365; both researchers agree no live long; matches two prior 3.5/10 debates |
| TCS | **PASS** (hard) | 1/10 | Confirmed downtrend; Tier-C bounce only |
| INFY | **PASS** (hard) | 0/10 | Falling knife; RSI 28 in downtrend is continuation |

**Advances to trade-plan stage:** HDFCBANK only, as a conditional setup —
BUY ~800 on intraday hold above 799.50, stop 775, target 820-835, size to 25%
cap (~31 shares, risk ~0.66%). No trade fires until the trigger confirms intraday
and live Kite quotes are available. No shorts, no F&O, CNC only.
