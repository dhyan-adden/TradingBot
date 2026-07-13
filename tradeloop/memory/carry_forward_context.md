# Carry Forward Context

Use this editable file for durable context that should be forwarded into every
TradeLoop run.

## Operator Notes

- Add manual instructions, watchlist preferences, risk posture, or recurring
  context here.
- Do not add credentials, tokens, API keys, passwords, or other secrets.

## Previous Run Context

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
### Holdings review (2026-07-13_1919_postclose)

- CDSL: TIGHTEN_STOP (profit_protect, conviction 7.0) new_stop=1390.73 - Clean 20d breakout confirmed on normal volume, LTP 1444.5 essentially at the 1444.90 trigger, green fundamentals, no contradicting news. Small open gain on an intact/strengthening thesis - raise stop to the scanner-confirmed level, still under price.
- DLF: HOLD (thesis_intact, conviction 6.0) - No fresh technical setup or news catalyst today. Yellow fundamental flag (DCCDL related-party exposure) is long-standing, not a new development. LTP 682.35 modestly below avg price but well clear of the 655.58 stop.
- HDFCBANK: HOLD (thesis_intact, conviction 6.5) - Tier-B ICICI Securities Buy call (target 1850), green fundamentals, bullish_continuation technical read with no contradicting chart evidence. Q1 FY27 results due this week is a real event-risk window to watch but does not itself break the thesis. LTP 817.95 holds ~1.3% above the 807.24 stop.
- SBIN: HOLD (thesis_intact, conviction 4.5) - No stop breach (LTP 1037.0 vs stop 1015.4, still above the 1019 intraday tripwire). Weak ema20_pullback score (4.0), scanner's stop (1006.91) is looser than the held stop so no tightening case. PSU-bank sector faces a headwind from the oil-driven G-Sec yield spike and bearish rupee options skew; sentiment score 0.25 is echo-chamber-flagged so treated with caution rather than as a fresh signal. Green fundamentals keep the thesis technically intact but conviction stays low.

HOLD across all four holdings; no stop breaches this cycle. CDSL (LTP 1444.5) confirmed a clean 20d breakout on normal volume - stop tightened to 1390.73 to protect the position while staying below price, next levels are targets 1517.13/1553.24. HDFCBANK (LTP 817.95, stop 807.24) carries a tier-B ICICI Securities Buy call (target 1850) into Q1 FY27 results due this week - watch the earnings print as the key event risk, stop unchanged. SBIN (LTP 1037.0, stop 1015.4) stays on exit-watch: weak technical score, PSU-bank pressure from the oil-driven G-Sec yield spike and bearish rupee skew, and an echo-chamber-flagged negative sentiment read - watch the 1019 intraday tripwire for any close back below it. DLF (LTP 682.35, stop 655.58) is a quiet hold with no fresh catalyst; the long-standing DCCDL related-party yellow flag is unchanged. Oil/Middle-East geopolitical escalation remains the dominant macro cross-current to monitor across the book, offsetting otherwise-supportive FII inflows.
<!-- auto:holdings_review:end -->
