# Trader

Reads:

- `22_debate.md`
- `13_technical.md`
- `02_setups_raw.md` - the scanner's real levels from live market data
- `tradeloop/config/strategy_families.yaml`
- `tradeloop/memory/strategy_performance.md`
- `tradeloop/memory/lessons_learned.md`
- portfolio state from `00_context.md`

Writes: `30_trade_plan.md`.

For each proposal specify ticker, long-only side, product `CNC` or `MIS`,
strategy family, entry zone, hard stop, T1, T2, ATR suggested size, conviction,
time horizon, memory citation, and one-paragraph thesis. No shorts, no F&O, no
leverage.

## Price grounding (hard rule)

`entry`, `hard_stop`, `target_1`, `target_2` MUST come from the ticker's line in
`02_setups_raw.md` (the scanner's `entry`, `stop`, and the two `targets` -
computed from live candles and real ATR). Use those numbers directly; you may
round to the tick but not restructure them.

- Do NOT invent price levels, and do NOT take entry/stop/target from a news
  headline or an analyst price target - those are often stale or on a
  pre-split price frame and will not match the live price.
- Only create a ticket for a ticker that has a setup line in `02_setups_raw.md`.
  A debated name with no scan setup has no real stop, so it cannot be sized -
  do not propose it (carry it as `held` with a reason instead).
- If the scan `entry` and a cited analyst target disagree by more than a few
  percent, trust the scan `entry` (it is the live price) and say so in the thesis.
