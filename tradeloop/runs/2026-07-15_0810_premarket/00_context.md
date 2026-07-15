# Context

Mode: premarket
Cash INR: 10557.659999999998
Equity INR: 99986.58
Daily P&L INR: 0.0

## Positions
- CDSL: quantity=11, avg_price=1432.22, hard_stop=1390.73
- DLF: quantity=36, avg_price=688.34, hard_stop=655.58
- HDFCBANK: quantity=30, avg_price=830.62, hard_stop=807.24
- SBIN: quantity=23, avg_price=1042.42, hard_stop=1015.4

## Macro Snapshot
# Macro View

Rolling India macro snapshot. Updated by the News Analyst during premarket and
by the Post-Trade Analyst during postclose when relevant.

## Carry Forward Context

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
### Holdings review (2026-07-14_1703_intraday)

- CDSL: HOLD (thesis_intact, conviction 6.0) - No fresh news or technical setup today. LTP 1428.50 pulled back slightly below the 1432.22 average entry but remains comfortably above the 1390.73 stop (~2.7% cushion). Breakout thesis stays intact; watch for a reclaim above 1444 to resume the uptrend toward 1517.13/1553.24.
- DLF: HOLD (thesis_intact, conviction 6.0) - No fresh catalyst or technical setup today. LTP 671.45 sits below the 688.34 average price but well clear of the 655.58 stop. Long-standing DCCDL related-party yellow flag is unchanged, no new developments.
- HDFCBANK: HOLD (thesis_intact, conviction 5.5) - Moody's affirmed asset quality and ICICI Securities reiterated a Buy at target 1850, and the ema20_pullback setup still reads bullish_continuation, but LTP 809.40 sits only ~0.27% above the 807.24 stop - the thinnest cushion in the book. Q1 FY27 results due this week are real event risk into a risk-off, rate-sensitive tape. Thesis stays intact but conviction lowered on the thin margin.
- SBIN: EXIT (stop_breach, conviction 2.5) - LTP 1015.40 is exactly at the 1015.40 hard stop, mandatory exit. PSU-bank sector faces a headwind from the oil-driven bond-yield spike and rupee weakness past 96/USD; only tier-C chatter (Jefferies loan CAGR/ROE note) with no offsetting tier-A/B catalyst today. The 1019 intraday tripwire flagged last cycle has now given way to the hard stop itself.

SBIN hit its 1015.40 hard stop exactly (LTP 1015.40) and is EXITED this cycle on stop_breach; PSU-bank sector pressure from the oil-driven bond-yield spike and rupee weakness confirmed the exit-watch flagged last cycle. HDFCBANK holds at LTP 809.40, just ~0.27% above its 807.24 stop; Q1 FY27 results due this week are the key event risk, and Moody's affirmed asset quality plus an ICICI Securities Buy (target 1850) keep the thesis intact for now. CDSL (LTP 1428.50) and DLF (LTP 671.45) are unchanged holds with no fresh catalysts, both comfortably above their 1390.73 and 655.58 stops respectively. Oil price spike, rupee past 96/USD, and the global bond-yield spike remain the dominant macro headwinds across the book, especially for rate-sensitive financials. Watch HDFCBANK's stop closely intraday given the thin cushion, and consider redeploying capital freed by the SBIN exit next premarket.
<!-- auto:holdings_review:end -->
