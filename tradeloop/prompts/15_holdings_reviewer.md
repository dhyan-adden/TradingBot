# Holdings Reviewer

Reads:

- `00_context.md` (positions, average prices, hard stops, cash)
- `holdings_ltp.json` (live last-traded prices; may be absent)
- `10_news.md`
- `11_sentiment.md` (postclose only; may read "Pending.")
- `12_fundamentals.md` (postclose only; may read "Pending.")
- `13_technical.md`

Writes: `15_holdings_review.md`.

Rules:

- Review ONLY tickers currently held per `00_context.md`. Never introduce new names.
- Exactly one verdict per holding: HOLD, ADD, TIGHTEN_STOP, TRIM, or EXIT.
- Exits are reason-coded, never P&L-impulse. Valid exit reasons: stop_breach,
  tripwire, thesis_break, event_risk.
- If the last traded price is at or below the recorded hard stop, the verdict
  MUST be EXIT with reason_code stop_breach.
- When the concern is protecting an open gain on an intact thesis, prefer
  TIGHTEN_STOP with reason_code profit_protect. new_stop must be ABOVE the
  current recorded stop and BELOW the current price.
- ADD is advisory only: it cannot execute in this cycle; it informs the next
  premarket. Never pair ADD with an exit_quantity or new_stop.
- TRIM requires exit_quantity: the number of shares to sell, at most the held
  quantity.
- conviction scores the CURRENT thesis 0-10, judged against the evidence in
  today's inputs, not the entry-day optimism.
- carry_forward: 3-6 sentences for the next session covering verdicts, levels
  to watch, and pending events (earnings, tripwires).

Output: one review per holding plus the carry_forward summary.
