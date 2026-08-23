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

## Slot scarcity (apply when open positions >= 3)

When 3 or 4 of the 4 position slots are already occupied, prefer shorter-horizon
strategies - they free slots faster and allow more round-trips.
Priority order when slots are scarce:

1. `results_momentum` (1-5 days) - highest priority
2. `20d_breakout` (3-10 days)
3. `post_earnings_drift` (5-15 days)
4. `ema20_pullback` / `sector_rotation_leader` (10-20 days) - lowest priority

If a long-horizon trade and a short-horizon trade are equally good, always
propose the shorter one. Do not leave a 5-day slot idle for a 20-day idea.

## Do not re-enter recent earnings plays

`00_context.md` contains a "Do Not Re-Enter" section listing tickers where
`results_momentum` or `post_earnings_drift` was used in the last 20 days.
Even if those tickers appear in `02_setups_raw.md` with a qualifying setup,
do NOT propose them. The earnings edge has been consumed; re-entering is
chasing residual drift without a fresh catalyst.

## Repeat EMA20 pullback

When a setup in `02_setups_raw.md` shows `ema20_2nd_pullback` or
`ema20_3rd_pullback` in the setup_type field, the stock has bounced off EMA20
multiple times recently. This is a meaningfully stronger signal than a first
touch - institutional buyers are actively defending that level. You may raise
the conviction score by 0.5-1.0 for 2nd touches and 1.0-1.5 for 3rd touches
relative to a plain `ema20_pullback` on the same stock.
