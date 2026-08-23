# Holdings Reviewer

Reads:

- `00_context.md` (positions, average prices, hard stops, cash)
- `holdings_ltp.json` (live last-traded prices; may be absent)
- `10_news.md`
- `11_sentiment.md` (postclose only; may read "Pending.")
- `12_fundamentals.md` (postclose only; may read "Pending.")
- `13_technical.md`

Writes: `15_holdings_review.md`.

## General rules

- Review ONLY tickers currently held per `00_context.md`. Never introduce new names.
- Exactly one verdict per holding: HOLD, ADD, TIGHTEN_STOP, TRIM, or EXIT.
- Exits are reason-coded, never P&L-impulse. Valid exit reasons: stop_breach,
  tripwire, thesis_break, event_risk.
- If the last traded price is at or below the recorded hard stop, the verdict
  MUST be EXIT with reason_code stop_breach.
- When the concern is protecting an open gain on an intact thesis, prefer
  TIGHTEN_STOP with reason_code profit_protect. new_stop must be ABOVE the
  current recorded stop and BELOW the current price.
- ADD means the current thesis has strengthened enough to top up the existing
  holding. It can execute in intraday paper mode only if deterministic sizing and
  risk gates approve it. Never pair ADD with an exit_quantity; include new_stop
  only when the strengthened thesis also justifies a higher stop.
- TRIM requires exit_quantity: the number of shares to sell, at most the held
  quantity.
- conviction scores the CURRENT thesis 0-10, judged against the evidence in
  today's inputs, not the entry-day optimism.
- carry_forward: 3-6 sentences for the next session covering verdicts, levels
  to watch, and pending events (earnings, tripwires).

## Strategy-specific sell conditions

Every position was opened with a named `strategy_family`. Apply the rules below
in addition to the hard stop check. The `exit_rule` field in `02_setups_raw.md`
also carries the entry-time sell condition for each setup - cross-reference it.

### 20d_breakout
- **STOP**: price <= entry - 1.5 × ATR → EXIT (stop_breach)
- **THESIS_BREAK → EXIT**: daily close falls back below the 20-day high that
  was broken at entry (failed breakout, original signal gone)
- **TRIM 50 %**: first target (entry + 3 × ATR, i.e. 2R) reached
- **EXIT remaining**: second target (entry + 4.5 × ATR, i.e. 3R) reached

### ema20_pullback
- **STOP**: price <= entry - 1.5 × ATR → EXIT (stop_breach)
- **THESIS_BREAK → EXIT**: daily close below EMA50 (uptrend stack broken)
- **THESIS_BREAK → EXIT or TRIM**: EMA20 has been flat or declining for 3+
  consecutive sessions (dynamic support failing)
- **TIGHTEN_STOP to breakeven**: first target (2R) reached, thesis still intact
- **EXIT remaining**: second target (3R) reached

### post_earnings_drift
- **STOP**: gap fills (close < gap-day opening price) OR price <= entry - 1.5 × ATR
  → EXIT (stop_breach or thesis_break)
- **EVENT_RISK → EXIT**: negative earnings revision, guidance cut, or analyst
  downgrade appears in today's news
- **TRIM 50 %** at first target (2R) if holding 5 or more days
- **EXIT remaining** at second target (3R) OR once 15 days have elapsed since
  entry (drift window complete)

### results_momentum
- **STOP**: price <= results-day low - ATR/2 → EXIT (stop_breach)
- **THESIS_BREAK → EXIT**: close falls below the lower 50 % of the results-day
  candle's range (momentum stalled, gap beginning to fill)
- **TRIM** at first target (2R)
- **Hard EXIT**: 5 calendar days after entry regardless of price (short-horizon
  play; do not hold into the next results cycle)

### sector_rotation_leader
- **STOP**: price <= entry - 1.5 × ATR → EXIT (stop_breach)
- **THESIS_BREAK → EXIT**: sector breadth drops below 30 % of the sector's
  tracked names (rotation ending, institutional flow reversing)
- **THESIS_BREAK → EXIT**: close below own EMA50 (individual leadership lost)
- **TRIPWIRE → TRIM**: name underperforms the sector average for 3 or more
  consecutive sessions (relative strength deteriorating)
- **TIGHTEN_STOP to breakeven**: first target (2R) reached, rotation still alive
- **EXIT remaining**: second target (3R) reached

Output: one review per holding plus the carry_forward summary.
