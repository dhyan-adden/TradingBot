# Carry Forward Context

Use this editable file for durable context that should be forwarded into every
TradeLoop run.

## Operator Notes

- Add manual instructions, watchlist preferences, risk posture, or recurring
  context here.
- Do not add credentials, tokens, API keys, passwords, or other secrets.

## Previous Run Context
- 2026-08-19 16:10 premarket: HOLD/EXIT cycle. Scanner was EMPTY this cycle (`02_setups_raw.md` 24 bytes, `full_scan.jsonl` 0 lines) — data-blocked for new entries, same signature as the 2026-07-09 10:39 cycle. Followed that lesson: no manufactured HOLD. Cash was INR 10,464.89 (BELOW INR 15,000 min-position-size floor), so new entries were doubly blocked even if scanner were healthy. Two deterministic stop-breach EXITs queued: CDSL SELL 11 sh CNC MARKET (LTP 1329.0 < stop 1390.73, ~4.4% below) and HDFCBANK SELL 30 sh CNC MARKET (LTP 720.0 << stop 807.24, ~10.8% below). Both verdicts carry forward from the 2026-08-18 1941 postclose review and are unchanged by intervening cycles. DLF: HOLD-fragile (LTP 669.9 above stop 655.58, ~2.2% above; below 688.34 avg; YELLOW fundamentals; no add). SBIN: HOLD-thesis-intact with stop already at 1021.89 (LTP 1048.6 above avg 1042.42 and stop; Q1 FY27 strength carry-forward GREEN; oil-above-$90 + rising global yields remain PSU-bank risks). Post-EXIT book posture: 2 positions (DLF + SBIN); bank exposure ~24% (well under 50% cap); open risk ~1.65% (well under 4% cap); cash ~INR 46,683 (above INR 15K floor, below 25% single-position ceiling ~INR 25K). No new long entries today. Watchlist carry-forward unchanged: ICICIBANK Priority-1 (bank slot freed by today's EXITs but no scanner ATR forbids sizing today; re-evaluate next scanner-healthy premarket; Tier-C MF flow rotation confirmed; LTP 1402 above 1383-1390 watch zone); SUNPHARMA re-ticket ONLY at >= 8 sh (>= INR 15,498) and confirmed close/open above 1937.30 trigger (LTP 1900 below trigger); INFY watch (reclaim above 1062.70 present at LTP 1119.8 but IT downgrade echo overhang; gated on TCS Q1 FY27 read-through); TCS pass (Q1 FY27 result not yet digested). Macro: oil-shock risk-off persists (Asia bond inflows 4-month low, INR near 3-week low, BSE closing-auction turmoil noise) — keep stops tight, do not add rate-sensitive or PSU-bank exposure beyond current sizing. Full debate archived to `tradeloop/memory/debate_archive/2026-08-19_1610_premarket.md`.

- 2026-07-09 11:29 premarket: HOLD, `orders.json` empty - but a REASONED hold,
  NOT data-blocked. Scanner was healthy this time (`full_scan.jsonl` 236 lines,
  ~150 setups downstream), full pipeline ran end-to-end. Only SUNPHARMA cleared
  debate as `tradeable` (6.5/10, pharma-defensive 20d breakout fitting the
  RISK-OFF tape; scanner levels entry 1937.30 / stop 1886.55 / T1 2004.97 /
  T2 2038.81). Trader deliberately sized it 5 sh (~INR 9,687) to reserve capital
  for the Priority-1 ICICIBANK slot. Risk Manager REJECTED on the deterministic
  `min_position_size` floor: 5 sh is INR 9,687, 35% below the INR 15,000 floor
  (first `below_min_position_size` reject in the loop). An 8-sh compliant version
  (INR 15,498) was surfaced but NOT auto-applied. PM PASSED: 6.5 conviction /
  at-entry / `volume_normal` / 1.33x R/R is too weak to justify inflating a
  position 60% just to defeat the floor, and deferral was zero-cost this cycle -
  SBIN (LTP 1025.20) sat above its 1019 tripwire so the ICICIBANK slot never
  freed, and SUNPHARMA (LTP 1934.80) was below its 1937.30 trigger so even an
  approved LIMIT would not have filled. Full INR 51,098 reserve kept dry.
  Lesson: a sub-floor toe-hold is a WATCH, not an upsize-to-clear-the-floor.
- 2026-07-09 10:39 premarket: HOLD, `orders.json` empty. New entries were
  DATA-BLOCKED, not passed on conviction: the Kite universe scan came up empty
  (`02_setups_raw.md`/`full_scan.jsonl` had 0 setups vs the normal ~350), an
  auth-token timing failure at the 08:09 prepare step (MCP auth was live later
  in the cycle). With no scanner ATR levels, the Trader's price-grounding hard
  rule forbids sizing any new entry, so no candidate could be ticketed.
  P0 operational fix: ensure `npm run auth:zerodha` runs and the token is valid
  BEFORE prepare_cycle runs, so the universe scan populates. If a future run
  again shows an empty scan, treat new entries as data-blocked (do not
  manufacture a confident HOLD).
- 2026-07-09 watchlist carried forward for the next premarket:
  ICICIBANK (conviction 6.0, watch) remains the top candidate - GREEN
  fundamentals, best-in-class metrics, confirmed private-bank relative strength;
  Priority-1 to ATR-size the instant the SBIN exit frees a bank slot (bank
  sector still ~48%/50% cap). Entry near 1383-1390. SUNPHARMA (6.5, watch) -
  re-ticket ONLY at >= floor size (>= 8 sh) on a confirmed close/open above the
  1937.30 trigger. INFY (3.5, watch) is gated on the TCS Q1 FY27 read-through
  (result was due 2026-07-09) plus a reclaim above its open ~1062.70. TCS (2.0,
  pass) - reassess only after its result is digested.
- 2026-07-09 positions (LTPs from the 11:29 cycle): HDFCBANK (30 @ 830.62, stop
  807.24, GREEN) HOLD, LTP ~820.80 (~1.1% underwater, no add/no exit); SBIN
  (23 @ 1042.42, stop 1015.40) HOLD but EXIT-WATCH - LTP ~1025.20, thin cushion,
  PSU-bank laggard tape and G-Sec MTM risk from rising global yields; intraday
  tripwire is a break/close below 1019 on volume (low 1019.30 was tested 07-09).
- 2026-05-17 19:55 adhoc RELIANCE: pass for fresh long entry; watch only until
  price reclaims 1365-1389 and holds. Higher-quality trigger above 1405 with
  improved index tone. Avoid letting Jio listing optionality override weak
  swing technicals.

<!-- auto:holdings_review:start -->
### Holdings review (2026-08-27_1600_postclose)

- DALBHARAT: TIGHTEN_STOP (profit_protect, conviction 4.5) new_stop=1875.5 - LTP 1876.2 is still above the recorded hard stop 1875.0, so no stop-breach exit is triggered. The position remains above avg_price 1853.93 and technicals classify it as bullish_continuation via EMA20 pullback in a mean-reversion-favored but risk_off regime. Cushion above stop is extremely narrow, so protect the open gain rather than add exposure.
- DLF: HOLD (thesis_intact, conviction 2.0) - LTP 676.15 remains above the recorded hard stop 655.58, so no mandatory exit is triggered. The holding is below avg_price 688.34, fundamentals are yellow, and technicals flag exit_watch with no fresh catalyst support. Keep as a fragile hold with stop unchanged and no add.
- SBIN: HOLD (thesis_intact, conviction 4.5) - LTP 1042.9 remains above the recorded hard stop 1021.89 and just above avg_price 1042.42, so the stop is intact. Technicals classify SBIN as bullish_continuation and fundamentals are green, but sentiment is slightly negative with echo risk and the risk_off macro backdrop remains unfriendly for PSU-bank exposure. No add or stop raise is justified today.

DALBHARAT remains the only holding with fresh technical support, but the cushion above stop is extremely narrow; carry forward TIGHTEN_STOP to 1875.5 and force exit if price trades at or below the active hard stop. DLF remains the weakest holding, below avg_price with yellow fundamentals and no catalyst; 655.58 is the hard invalidation level. SBIN stays a cautious HOLD while above 1021.89, but PSU-bank macro risks and weak sentiment echo argue against adding. Overall regime remains risk_off with reduced posture, so next session should prioritize defense and stop discipline over fresh exposure.
<!-- auto:holdings_review:end -->

<!-- auto:holdings_review:start -->
### Holdings review (2026-08-19_1610_premarket)

- CDSL: EXIT (stop_breach, conviction 2.0) - LTP 1329.0 is below the recorded hard stop 1390.73 (~4.4% below). Stop-breach rule forces EXIT regardless of other evidence. Fundamentals RED carry-forward, technicals avoid, no fresh Tier-A/B catalyst to invalidate the stop. SELL 11 sh CNC MARKET queued in orders.json.
- DLF: HOLD (thesis_intact, conviction 1.5) - LTP 669.9 remains above the recorded hard stop 655.58 (~2.2% above). No stop-breach. Hold is fragile: price below 688.34 avg, YELLOW fundamentals, no fresh news/sentiment/technical support strong enough to justify adding. No order this cycle. Watch for fresh Tier-A/B catalyst or break below 655.58.
- HDFCBANK: EXIT (stop_breach, conviction 3.0) - LTP 720.0 is far below the recorded hard stop 807.24 (~10.8% below). Stop-breach rule forces EXIT. Tier-B ICICI Securities Buy target Rs 1,850 does not override breached stop (target ~157% above live LTP, anchored to pre-rerating tape). Tier-C echo this cycle confirms near 52-week low and leveraged-bets climbing; YELLOW fundamentals with leverage-governance concern persists. SELL 30 sh CNC MARKET queued in orders.json.
- SBIN: HOLD (thesis_intact, conviction 5.5) - LTP 1048.6 is above the recorded hard stop 1021.89 (~2.6% above) and above the recorded avg 1042.42 (~+0.6% open gain). Q1 FY27 profit strength, better asset quality, GREEN fundamentals, and bullish-continuation technicals keep the thesis intact. Stop is ALREADY tightened to 1021.89 from the prior cycle's TIGHTEN_STOP verdict. No fresh Tier-A/B catalyst this cycle and no deterioration; no order this cycle. Watch oil above $90 and rising global yields as PSU-bank risks; watch ability to hold above 1021.89 and progress toward prior T1 1121.21 and T2 1154.32.

CDSL and HDFCBANK are deterministic EXIT verdicts because current LTPs are below their recorded hard stops; both SELL orders queued in orders.json for next open. DLF remains a fragile HOLD above 655.58 with no add justification; a move to or below the stop should force exit. SBIN is the only constructive holding with thesis intact and stop tightened to 1021.89 protecting the open gain. Post-EXIT cash will be ~INR 46,683 (above INR 15K floor, below 25% single-position ceiling ~INR 25K) — the next scanner-healthy premarket can size a single fresh entry. Watchlist Priority-1 ICICIBANK remains gated on ATR sizing being available; SUNPHARMA re-ticket gated on trigger; INFY gated on IT-echo fading; TCS gated on Q1 FY27 read-through.
<!-- auto:holdings_review:end -->
