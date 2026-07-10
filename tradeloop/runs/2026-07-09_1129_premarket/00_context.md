# Context

Mode: premarket
Cash INR: 51098.4
Equity INR: 99992.66
Daily P&L INR: 0.0

## Positions
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
- 2026-07-09 watchlist carried forward for the next scan-healthy premarket:
  ICICIBANK (conviction 6.0, watch) is the top candidate - GREEN fundamentals,
  confirmed private-bank relative strength on a risk-off day; first name to
  ATR-size when the scanner is back, but note bank sector exposure was already
  ~48%/50% cap so a new bank long needs a slot to free. INFY (3.5, watch) is
  gated on the TCS Q1 FY27 read-through. TCS (2.0, pass) - reassess only after
  its result is digested.
- 2026-07-09 positions: HDFCBANK (30 @ 830.62, stop 807.24, GREEN) HOLD; SBIN
  (23 @ 1042.42, stop 1015.40) HOLD but EXIT-WATCH - thin ~0.8% cushion above
  stop, PSU-bank laggard tape and G-Sec MTM risk; intraday tripwire is a break
  below 1019 on volume.
- 2026-05-17 19:55 adhoc RELIANCE: pass for fresh long entry; watch only until
  price reclaims 1365-1389 and holds. Higher-quality trigger above 1405 with
  improved index tone. Avoid letting Jio listing optionality override weak
  swing technicals.
